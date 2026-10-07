"""Deterministic tests for location PPE safety rules driving the AI.

Run (in-memory SQLite, no YOLO):
    python test_ppe_rules.py
"""

from __future__ import annotations

from argparse import Namespace
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import get_db
import models
from ai_module.realtime_pipeline import RealtimePPEPipeline
from ai_module.test_realtime_pipeline import resolve_required_ppe
from ai_module.zone_analyzer import RestrictedZone
from ai_module.violation_engine import TemporalViolationEngine, ViolationEngineConfig
from routers import admin, auth
from routers.auth import hash_password
import numpy as np

from services import ppe_rule_service
from services.restricted_zone_service import (
    FULL_FRAME_POLYGON,
    RestrictedZoneReloader,
    load_enabled_zones_for_camera,
)
from services.ppe_rule_service import (
    ALL_PPE_ITEMS,
    PPERuleReloader,
    load_required_ppe_for_camera,
    required_items_from_rules,
)


def _rule(ppe_type, restricted=False, rule_id=1):
    return SimpleNamespace(id=rule_id, ppe_type=ppe_type, is_restricted_area=restricted)


def _stub_pipeline(missing_items, required_ppe=None) -> RealtimePPEPipeline:
    """Pipeline whose tracker/analyzer always report one person missing items."""

    person = SimpleNamespace(track_id=3, detection={"bbox": [0, 0, 10, 20]}, bbox=[0, 0, 10, 20])
    tracking = SimpleNamespace(people=[person], detections=[person.detection])
    status = SimpleNamespace(person_detection=person.detection, person_bbox=person.bbox, missing_items=list(missing_items))
    pipeline = object.__new__(RealtimePPEPipeline)
    pipeline.tracker = SimpleNamespace(track=lambda frame, confidence: tracking)
    pipeline.analyzer = SimpleNamespace(analyze=lambda detections: [status])
    pipeline.violation_engine = TemporalViolationEngine(ViolationEngineConfig(confirmation_seconds=2.0))
    pipeline.zone_violation_config = None
    pipeline.set_zones(None)
    pipeline.set_required_ppe(required_ppe)
    pipeline.incident_manager = None
    pipeline.incident_sink = None
    pipeline.confidence = 0.25
    pipeline._init_runtime_filters()
    return pipeline


def _confirmed_items(pipeline: RealtimePPEPipeline):
    pipeline.process_frame(object(), 0.0)
    events = pipeline.process_frame(object(), 2.0).events
    return [tuple(event.missing_items) for event in events]


def run_tests() -> None:
    # Rule labels -> analyzer items; no detectable PPE rule => check everything.
    assert required_items_from_rules([]) == ALL_PPE_ITEMS == {"helmet", "vest", "gloves"}
    assert required_items_from_rules([_rule("Helmet")]) == {"helmet"}
    assert required_items_from_rules([_rule("Safety Vest"), _rule("Gloves")]) == {"vest", "gloves"}
    assert required_items_from_rules([_rule(None, restricted=True)]) == frozenset()  # restricted: no PPE checks
    assert required_items_from_rules([_rule("Helmet"), _rule(None, restricted=True)]) == frozenset()
    assert required_items_from_rules([_rule("Goggles"), _rule("Safety Boots")]) == ALL_PPE_ITEMS
    assert required_items_from_rules([_rule("Goggles"), _rule("Helmet")]) == {"helmet"}
    assert required_items_from_rules([_rule("All PPE")]) == ALL_PPE_ITEMS
    assert required_items_from_rules([_rule("No PPE")]) == frozenset()
    assert required_items_from_rules([_rule("No PPE"), _rule(None, restricted=True)]) == frozenset()

    # The pipeline only turns required items into violations.
    missing = ["helmet", "vest", "gloves"]
    assert _confirmed_items(_stub_pipeline(missing)) == [("helmet", "vest", "gloves")]
    assert _confirmed_items(_stub_pipeline(missing, {"helmet"})) == [("helmet",)]
    assert _confirmed_items(_stub_pipeline(["gloves"], {"helmet", "vest"})) == []
    assert _confirmed_items(_stub_pipeline(missing, ALL_PPE_ITEMS)) == [("helmet", "vest", "gloves")]
    assert _confirmed_items(_stub_pipeline(missing, frozenset())) == []  # "No PPE" location

    # Restricted location: whole-frame zone, no PPE -> only the entry violation.
    restricted_pipeline = _stub_pipeline(missing, frozenset())
    restricted_pipeline.set_zones([RestrictedZone("location-9", "Restricted area: Store", FULL_FRAME_POLYGON, normalized=True)])
    frame = np.zeros((20, 10, 3), dtype=np.uint8)  # person bbox spans the whole frame
    restricted_pipeline.process_frame(frame, 0.0)
    events = [event.to_dict() for event in restricted_pipeline.process_frame(frame, 2.0).events]
    assert [event["event_type"] for event in events] == ["RESTRICTED_ZONE_VIOLATION"], events
    assert events[0]["zone_id"] == "location-9"

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    original_session_local = ppe_rule_service.SessionLocal
    try:
        with Session() as db:
            block, yard = models.Location(name="Block 1", zone="A", department="QA"), models.Location(name="Yard", zone="B", department="QA")
            store = models.Location(name="Store", zone="C", department="QA")
            db.add_all([block, yard, store]); db.flush()
            webcam = models.Camera(name="Webcam", type="WEBCAM", stream_url="0", status="active", location_id=block.id)
            yard_cam = models.Camera(name="Yard Cam", type="FILE", stream_url="x.mp4", status="active", location_id=yard.id)
            store_cam = models.Camera(name="Store Cam", type="FILE", stream_url="s.mp4", status="active", location_id=store.id)
            db.add_all([webcam, yard_cam, store_cam]); db.flush()
            db.add(models.RestrictedZone(camera_id=store_cam.id, name="Shelf", polygon_points=[[0.1, 0.1], [0.5, 0.1], [0.5, 0.5]]))
            db.add(models.User(name="Admin", email="admin@test.local", password=hash_password("test1234"), role="admin", status="active"))
            db.commit()
            webcam_id, yard_cam_id, block_id = webcam.id, yard_cam.id, block.id
            store_cam_id, store_id = store_cam.id, store.id

        client = TestClient(_app(Session))
        token = client.post("/auth/login", json={"email": "admin@test.local", "password": "test1234"}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Admin API accepts only the three detected PPE types.
        for ppe in ("Goggles", "Safety Boots", "Hat"):
            bad = client.post("/admin/safety-rules", json={"location_id": block_id, "ppe_type": ppe, "severity_level": "High"}, headers=headers)
            assert bad.status_code == 422, (ppe, bad.text)

        # Restricted location: no PPE rules, whole camera view is the zone.
        assert [z.name for z in load_enabled_zones_for_camera(store_cam_id, Session)] == ["Shelf"]
        now = [0.0]
        zone_reloader = RestrictedZoneReloader(store_cam_id, interval_seconds=5.0, session_factory=Session, clock=lambda: now[0])
        zone_reloader.load()
        restricted = client.post("/admin/safety-rules", json={"location_id": store_id, "is_restricted_area": True, "ppe_type": "Helmet", "severity_level": "High"}, headers=headers)
        assert restricted.status_code == 201 and restricted.json()["ppe_type"] is None
        assert client.post("/admin/safety-rules", json={"location_id": store_id, "is_restricted_area": True, "severity_level": "High"}, headers=headers).status_code == 409
        for ppe in ("Helmet", "All PPE", "No PPE"):
            blocked = client.post("/admin/safety-rules", json={"location_id": store_id, "ppe_type": ppe, "severity_level": "High"}, headers=headers)
            assert blocked.status_code == 409, (ppe, blocked.text)
        assert load_required_ppe_for_camera(store_cam_id, Session) == frozenset()
        zones = load_enabled_zones_for_camera(store_cam_id, Session)
        assert [(z.zone_id, z.name, z.polygon) for z in zones] == [(f"location-{store_id}", "Restricted area: Store", FULL_FRAME_POLYGON)]
        now[0] += 6
        assert [z.zone_id for z in zone_reloader.poll()] == [f"location-{store_id}"]  # running AI picks it up
        assert client.delete(f"/admin/safety-rules/{restricted.json()['id']}", headers=headers).status_code == 200
        assert load_required_ppe_for_camera(store_cam_id, Session) == ALL_PPE_ITEMS
        now[0] += 6
        assert [z.name for z in zone_reloader.poll()] == ["Shelf"]

        # A camera's required PPE follows its location's rules.
        assert load_required_ppe_for_camera(webcam_id, Session) == ALL_PPE_ITEMS  # no rules yet
        helmet = client.post("/admin/safety-rules", json={"location_id": block_id, "ppe_type": "Helmet", "severity_level": "High"}, headers=headers)
        assert helmet.status_code == 201, helmet.text
        assert load_required_ppe_for_camera(webcam_id, Session) == {"helmet"}
        assert load_required_ppe_for_camera(yard_cam_id, Session) == ALL_PPE_ITEMS  # other location unaffected
        blocked = client.post("/admin/safety-rules", json={"location_id": block_id, "is_restricted_area": True, "severity_level": "High"}, headers=headers)
        assert blocked.status_code == 409, blocked.text  # has PPE rules
        try:
            load_required_ppe_for_camera(99999, Session)
            raise AssertionError("missing camera should be rejected")
        except ValueError:
            pass

        # "All PPE" and "None" on another location; None cannot mix with PPE rules.
        yard_id = db_location_id(Session, yard_cam_id)
        # "None" needs no severity: it is optional and stored as a neutral Low.
        none_rule = client.post("/admin/safety-rules", json={"location_id": yard_id, "ppe_type": "No PPE"}, headers=headers)
        assert none_rule.status_code == 201 and none_rule.json()["severity_level"] == "Low", none_rule.text
        assert load_required_ppe_for_camera(yard_cam_id, Session) == frozenset()
        conflict = client.post("/admin/safety-rules", json={"location_id": yard_id, "ppe_type": "Gloves", "severity_level": "Low"}, headers=headers)
        assert conflict.status_code == 409, conflict.text
        conflict = client.post("/admin/safety-rules", json={"location_id": block_id, "ppe_type": "No PPE", "severity_level": "Low"}, headers=headers)
        assert conflict.status_code == 409, conflict.text
        all_ppe = client.post("/admin/safety-rules", json={"location_id": block_id, "ppe_type": "All PPE", "severity_level": "High"}, headers=headers)
        assert all_ppe.status_code == 201, all_ppe.text
        assert load_required_ppe_for_camera(webcam_id, Session) == ALL_PPE_ITEMS
        assert client.delete(f"/admin/safety-rules/{all_ppe.json()['id']}", headers=headers).status_code == 200

        # A running session picks up rule changes.
        now[0] = 0.0
        reloader = PPERuleReloader(webcam_id, interval_seconds=5.0, session_factory=Session, clock=lambda: now[0])
        assert reloader.load() == {"helmet"}
        now[0] += 6
        assert reloader.poll() is None  # unchanged
        assert client.post("/admin/safety-rules", json={"location_id": block_id, "ppe_type": "Safety Vest", "severity_level": "High"}, headers=headers).status_code == 201
        now[0] += 6
        assert reloader.poll() == {"helmet", "vest"}
        assert client.delete(f"/admin/safety-rules/{helmet.json()['id']}", headers=headers).status_code == 200
        now[0] += 6
        assert reloader.poll() == {"vest"}

        # CLI: --camera-db-id uses location rules; no camera uses all items.
        ppe_rule_service.SessionLocal = Session
        assert resolve_required_ppe(Namespace(camera_db_id=None, zone_reload_seconds=5.0))[0] is None
        items, cli_reloader, description = resolve_required_ppe(Namespace(camera_db_id=webcam_id, zone_reload_seconds=5.0))
        assert items == {"vest"} and cli_reloader is not None and "vest" in description
    finally:
        ppe_rule_service.SessionLocal = original_session_local
        models.Base.metadata.drop_all(engine)
        engine.dispose()

    print("PPE safety-rule tests passed:")
    print("  - rule labels map to helmet/vest/gloves; All PPE; None; no PPE rule => all three")
    print("  - None cannot be combined with PPE rules on one location")
    print("  - restricted location: no PPE rules/checks, whole view is a restricted zone")
    print("  - pipeline confirms only required missing items")
    print("  - Admin API rejects undetectable PPE types")
    print("  - camera -> location -> required PPE, CLI resolution, runtime reload")


def db_location_id(session_factory, camera_id: int) -> int:
    with session_factory() as db:
        return db.get(models.Camera, camera_id).location_id


def _app(session_factory) -> FastAPI:
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(admin.router)

    def override_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    return app


if __name__ == "__main__":
    run_tests()
