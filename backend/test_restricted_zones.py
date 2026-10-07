"""Deterministic tests for camera-specific restricted zones.

Run isolated tests (in-memory SQLite, no YOLO):
    python test_restricted_zones.py

Also verify the configured PostgreSQL table (transaction is rolled back):
    python test_restricted_zones.py --postgres
"""

from __future__ import annotations

import argparse
from argparse import Namespace
from pathlib import Path
import shutil
from uuid import uuid4

import cv2
from fastapi import FastAPI
from fastapi.testclient import TestClient
import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import SessionLocal, get_db
import models
from ai_module.detector import Detection
from ai_module.realtime_pipeline import RealtimePPEPipeline
from ai_module.test_realtime_pipeline import resolve_zone_configuration
from ai_module.tracker import TrackedPerson
from ai_module.zone_analyzer import RestrictedZone as AnalyzerZone, ZoneAnalyzer
from ai_module.zone_violation_engine import TemporalZoneViolationEngine, ZoneViolationConfig
from routers import admin, auth, officer, worker
from routers.auth import hash_password
from services import restricted_zone_service
from services.incident_service import EVIDENCE_ROOT
from services.restricted_zone_service import (
    RestrictedZoneReloader,
    load_enabled_zones,
    to_analyzer_zone,
)

BACKEND_ROOT = Path(__file__).resolve().parent
EXAMPLE_ZONES = BACKEND_ROOT / "ai_module" / "Tests" / "zones" / "test_zones.json"
SQUARE = [[0.55, 0.30], [0.90, 0.30], [0.90, 0.90], [0.55, 0.90]]


def _person(track_id: int, bbox: list) -> TrackedPerson:
    detection: Detection = {"class_id": 6, "class_name": "Person", "confidence": 0.9, "bbox": bbox}
    return TrackedPerson(track_id=track_id, detection=detection)


def _make_test_video(directory: Path, size=(160, 90)) -> Path:
    path = directory / "zone_camera.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 8.0, size)
    if not writer.isOpened():
        raise RuntimeError("Could not create the zone camera test video")
    try:
        for index in range(3):
            frame = np.zeros((size[1], size[0], 3), dtype=np.uint8)
            frame[:, :] = (40 + index * 40, 90, 160)
            writer.write(frame)
    finally:
        writer.release()
    return path


def _build_test_app(session_factory) -> FastAPI:
    app = FastAPI()
    for router in (auth.router, admin.router, officer.router, worker.router):
        app.include_router(router)

    def override_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    return app


def _login(client: TestClient, email: str) -> dict:
    response = client.post("/auth/login", json={"email": email, "password": "test1234"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def run_isolated_tests() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    work_directory = (EVIDENCE_ROOT / f"_zone_test_{uuid4().hex}").resolve()
    work_directory.mkdir(parents=True, exist_ok=False)
    original_session_local = restricted_zone_service.SessionLocal

    try:
        video_path = _make_test_video(work_directory)
        with TestSession() as db:
            location = models.Location(name="Zone Test Floor", zone="Z", department="QA")
            db.add(location)
            db.flush()
            factory_camera = models.Camera(name="Factory Floor", type="FILE", stream_url=str(video_path), status="active", location_id=location.id)
            empty_camera = models.Camera(name="No Zone Camera", type="FILE", stream_url=str(video_path), status="active", location_id=location.id)
            broken_camera = models.Camera(name="Broken Source", type="FILE", stream_url=str(work_directory / "missing.mp4"), status="active", location_id=location.id)
            db.add_all([factory_camera, empty_camera, broken_camera])
            db.add_all([
                models.User(name="Admin", email="admin@test.local", password=hash_password("test1234"), role="admin", status="active"),
                models.User(name="Officer", email="officer@test.local", password=hash_password("test1234"), role="officer", status="active"),
                models.User(name="Worker", email="worker@test.local", password=hash_password("test1234"), role="worker", status="active"),
            ])
            db.commit()
            camera_id, empty_camera_id, broken_camera_id = factory_camera.id, empty_camera.id, broken_camera.id
            location_id = location.id

        client = TestClient(_build_test_app(TestSession))
        admin_headers = _login(client, "admin@test.local")
        officer_headers = _login(client, "officer@test.local")
        worker_headers = _login(client, "worker@test.local")
        zones_url = f"/admin/cameras/{camera_id}/restricted-zones"

        # Camera with zero zones: empty lists, PPE-only pipeline configuration.
        assert client.get(zones_url, headers=admin_headers).json() == []
        empty = client.get(f"/officer/cameras/{empty_camera_id}/restricted-zones", headers=officer_headers)
        assert empty.status_code == 200 and empty.json() == []
        with TestSession() as db:
            assert load_enabled_zones(db, empty_camera_id) == []

        # Create a valid zone; points are stored normalized as floats.
        created = client.post(zones_url, json={"name": "  Heavy Machinery Area ", "polygon_points": SQUARE}, headers=admin_headers)
        assert created.status_code == 201, created.text
        heavy = created.json()
        assert heavy["name"] == "Heavy Machinery Area"
        assert heavy["camera_id"] == camera_id and heavy["enabled"] is True
        assert heavy["polygon_points"] == SQUARE
        integer_corners = client.post(zones_url, json={"name": "Electrical Panel Area", "polygon_points": [[0, 0], [1, 0], [0, 1]]}, headers=admin_headers)
        assert integer_corners.status_code == 201, integer_corners.text
        assert integer_corners.json()["polygon_points"] == [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]
        loading = client.post(zones_url, json={"name": "Loading Area", "polygon_points": [[0.1, 0.6], [0.4, 0.6], [0.4, 0.95]], "enabled": False}, headers=admin_headers)
        assert loading.status_code == 201 and loading.json()["enabled"] is False

        # Validation: reject malformed polygons with readable string details.
        invalid_payloads = {
            "fewer than 3 points": {"name": "Bad", "polygon_points": [[0.1, 0.1], [0.5, 0.5]]},
            "x out of range": {"name": "Bad", "polygon_points": [[0.1, 0.1], [1.2, 0.1], [0.5, 0.5]]},
            "y out of range": {"name": "Bad", "polygon_points": [[0.1, -0.1], [0.9, 0.1], [0.5, 0.5]]},
            "zero area": {"name": "Bad", "polygon_points": [[0.1, 0.1], [0.5, 0.5], [0.9, 0.9]]},
            "duplicate points": {"name": "Bad", "polygon_points": [[0.1, 0.1], [0.1, 0.1], [0.5, 0.5]]},
            "string coordinate": {"name": "Bad", "polygon_points": [["0.1", 0.1], [0.9, 0.1], [0.5, 0.5]]},
            "boolean coordinate": {"name": "Bad", "polygon_points": [[True, 0.1], [0.9, 0.1], [0.5, 0.5]]},
            "object point": {"name": "Bad", "polygon_points": [{"x": 0.1, "y": 0.1}, [0.9, 0.1], [0.5, 0.5]]},
            "three-value point": {"name": "Bad", "polygon_points": [[0.1, 0.1, 0.0], [0.9, 0.1], [0.5, 0.5]]},
            "object instead of list": {"name": "Bad", "polygon_points": {"points": SQUARE}},
            "blank name": {"name": "   ", "polygon_points": SQUARE},
            "too many points": {"name": "Bad", "polygon_points": [[0.5 + 0.4 * np.cos(i / 101 * 6.28), 0.5 + 0.4 * np.sin(i / 101 * 6.28)] for i in range(101)]},
        }
        for label, payload in invalid_payloads.items():
            response = client.post(zones_url, json=payload, headers=admin_headers)
            assert response.status_code == 422, (label, response.status_code, response.text)
            assert isinstance(response.json()["detail"], str), label
        nan_response = client.post(
            zones_url,
            content='{"name": "Bad", "polygon_points": [[NaN, 0.1], [0.9, 0.1], [0.5, 0.5]]}',
            headers={**admin_headers, "Content-Type": "application/json"},
        )
        assert nan_response.status_code == 422, nan_response.text
        assert client.post("/admin/cameras/99999/restricted-zones", json={"name": "X", "polygon_points": SQUARE}, headers=admin_headers).status_code == 404

        # Multiple zones; Officer sees enabled ones only.
        listing = client.get(zones_url, headers=admin_headers).json()
        assert [zone["name"] for zone in listing] == ["Heavy Machinery Area", "Electrical Panel Area", "Loading Area"]
        officer_view = client.get(f"/officer/cameras/{camera_id}/restricted-zones", headers=officer_headers).json()
        assert [zone["name"] for zone in officer_view] == ["Heavy Machinery Area", "Electrical Panel Area"]
        assert client.get("/officer/cameras/99999/restricted-zones", headers=officer_headers).status_code == 404

        # Enable/disable, rename, and redraw.
        zone_url = f"{zones_url}/{heavy['id']}"
        disabled = client.patch(zone_url, json={"enabled": False}, headers=admin_headers)
        assert disabled.status_code == 200 and disabled.json()["enabled"] is False
        officer_view = client.get(f"/officer/cameras/{camera_id}/restricted-zones", headers=officer_headers).json()
        assert [zone["name"] for zone in officer_view] == ["Electrical Panel Area"]
        redrawn = client.patch(zone_url, json={"enabled": True, "name": "Heavy Machinery", "polygon_points": [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]}, headers=admin_headers)
        assert redrawn.status_code == 200, redrawn.text
        assert redrawn.json()["name"] == "Heavy Machinery" and redrawn.json()["enabled"] is True
        assert redrawn.json()["polygon_points"][0] == [0.2, 0.2]
        assert client.patch(zone_url, json={"polygon_points": [[0.2, 0.2], [0.8, 0.8]]}, headers=admin_headers).status_code == 422
        assert client.patch(zone_url, json={"name": ""}, headers=admin_headers).status_code == 422
        assert client.patch(f"/admin/cameras/{empty_camera_id}/restricted-zones/{heavy['id']}", json={"enabled": False}, headers=admin_headers).status_code == 404

        # Role separation: only Admin may modify; Worker cannot view.
        zone_payload = {"name": "Officer Zone", "polygon_points": SQUARE}
        for headers in (officer_headers, worker_headers):
            assert client.get(zones_url, headers=headers).status_code == 403
            assert client.post(zones_url, json=zone_payload, headers=headers).status_code == 403
            assert client.patch(zone_url, json={"enabled": False}, headers=headers).status_code == 403
            assert client.delete(zone_url, headers=headers).status_code == 403
            assert client.get(f"/admin/cameras/{camera_id}/snapshot", headers=headers).status_code == 403
        assert client.get(f"/officer/cameras/{camera_id}/restricted-zones", headers=worker_headers).status_code == 403
        assert client.get(zones_url, headers={"Authorization": "Bearer invalid"}).status_code == 401

        # Snapshot: authenticated JPEG of the camera's current/first frame.
        snapshot = client.get(f"/admin/cameras/{camera_id}/snapshot", headers=admin_headers)
        assert snapshot.status_code == 200, snapshot.text
        assert snapshot.headers["content-type"] == "image/jpeg"
        decoded = cv2.imdecode(np.frombuffer(snapshot.content, dtype=np.uint8), cv2.IMREAD_COLOR)
        assert decoded is not None and decoded.shape[:2] == (90, 160)
        assert client.get(f"/admin/cameras/{broken_camera_id}/snapshot", headers=admin_headers).status_code == 503
        assert client.get("/admin/cameras/99999/snapshot", headers=admin_headers).status_code == 404

        # DB rows convert to the existing AI RestrictedZone and drive ZoneAnalyzer.
        with TestSession() as db:
            record = db.get(models.RestrictedZone, heavy["id"])
            converted = to_analyzer_zone(record)
            assert isinstance(converted, AnalyzerZone)
            assert converted.zone_id == str(heavy["id"]) and converted.name == "Heavy Machinery"
            assert converted.normalized and converted.enabled
            enabled_zones = load_enabled_zones(db, camera_id)
        assert [zone.name for zone in enabled_zones] == ["Heavy Machinery", "Electrical Panel Area"]
        analyzer = ZoneAnalyzer(enabled_zones)
        assert analyzer.resolve_zones(1280, 720)[0].pixel_polygon[0] == (256.0, 144.0)
        statuses = {s.track_id: s for s in analyzer.analyze([
            _person(1, [600, 200, 700, 500]),  # foot (650, 500): inside Heavy Machinery
            _person(2, [1100, 300, 1200, 700]),  # foot (1150, 700): outside both
        ], 1280, 720)}
        assert statuses[1].inside_zone_names == ["Heavy Machinery"]
        assert statuses[2].inside_zone_ids == []
        engine_ = TemporalZoneViolationEngine(analyzer.enabled_zones, ZoneViolationConfig())
        engine_.update({1: statuses[1].inside_zone_ids}, 0.0)
        assert not engine_.update({1: statuses[1].inside_zone_ids}, 1.4).events
        events = engine_.update({1: statuses[1].inside_zone_ids}, 1.5).events
        assert [(event.zone_id, event.zone_name) for event in events] == [(str(heavy["id"]), "Heavy Machinery")]

        # Pipeline zone swap without YOLO: DB zones on, then PPE only.
        pipeline = object.__new__(RealtimePPEPipeline)
        pipeline.zone_violation_config = None
        pipeline.set_zones(enabled_zones)
        assert len(pipeline.zone_analyzer.enabled_zones) == 2 and pipeline.zone_violation_engine is not None
        pipeline.set_zones(None)
        assert pipeline.zone_analyzer is None and pipeline.zone_violation_engine is None

        # Zone source precedence and runtime reload against this test database.
        restricted_zone_service.SessionLocal = TestSession
        base_args = dict(zone_reload_seconds=5.0)
        zones, reloader, source = resolve_zone_configuration(Namespace(zones=str(EXAMPLE_ZONES), camera_db_id=camera_id, **base_args))
        assert reloader is None and source.startswith("JSON") and zones[0].zone_id == "zone_1"
        zones, reloader, source = resolve_zone_configuration(Namespace(zones=None, camera_db_id=camera_id, **base_args))
        assert source == f"database camera {camera_id}" and [zone.name for zone in zones] == ["Heavy Machinery", "Electrical Panel Area"]
        zones, reloader, _ = resolve_zone_configuration(Namespace(zones=None, camera_db_id=empty_camera_id, **base_args))
        assert zones is None and reloader is not None  # zero zones => PPE only
        assert resolve_zone_configuration(Namespace(zones=None, camera_db_id=None, **base_args)) == (None, None, "none (PPE only)")
        try:
            resolve_zone_configuration(Namespace(zones=None, camera_db_id=99999, **base_args))
            raise AssertionError("Missing DB camera should be rejected")
        except ValueError:
            pass

        now = [100.0]
        reloader = RestrictedZoneReloader(camera_id, interval_seconds=5.0, session_factory=TestSession, clock=lambda: now[0])
        assert len(reloader.load()) == 2
        now[0] += 10
        assert reloader.poll() is None  # unchanged
        client.patch(f"{zones_url}/{integer_corners.json()['id']}", json={"enabled": False}, headers=admin_headers)
        now[0] += 1
        assert reloader.poll() is None  # interval not reached yet
        now[0] += 5
        assert [zone.name for zone in reloader.poll()] == ["Heavy Machinery"]
        client.patch(zone_url, json={"enabled": False}, headers=admin_headers)
        now[0] += 5
        assert reloader.poll() == []  # all disabled => PPE only

        # Delete one zone, then delete the camera: no orphan zone rows remain.
        assert client.delete(f"{zones_url}/{loading.json()['id']}", headers=admin_headers).status_code == 200
        assert client.delete(f"{zones_url}/{loading.json()['id']}", headers=admin_headers).status_code == 404
        assert len(client.get(zones_url, headers=admin_headers).json()) == 2
        assert client.delete(f"/admin/cameras/{camera_id}", headers=admin_headers).status_code == 200
        with TestSession() as db:
            assert db.query(models.RestrictedZone).filter(models.RestrictedZone.camera_id == camera_id).count() == 0
            assert db.query(models.RestrictedZone).count() == 0
            assert db.get(models.Location, location_id) is not None

        print("Isolated restricted-zone tests passed:")
        print("  - create valid zones; multiple zones per camera; zero-zone cameras")
        print("  - reject <3 points, out-of-range, zero-area, non-numeric, NaN, and malformed JSON")
        print("  - enable/disable, rename, redraw, delete, camera-scoped zone IDs")
        print("  - Admin-only writes; Officer read-only enabled zones; Worker rejected")
        print("  - authenticated camera snapshot and graceful source errors")
        print("  - DB rows -> existing RestrictedZone -> ZoneAnalyzer -> temporal confirmation")
        print("  - JSON vs DB precedence, PPE-only fallback, runtime reload polling")
        print("  - camera deletion cascades to its zones")
    finally:
        restricted_zone_service.SessionLocal = original_session_local
        models.Base.metadata.drop_all(engine)
        engine.dispose()
        if work_directory.exists() and work_directory.parent == EVIDENCE_ROOT:
            shutil.rmtree(work_directory)


def run_postgres_transaction_test() -> None:
    """Exercise the real restricted_zones table without retaining rows."""

    db = SessionLocal()
    try:
        marker = uuid4().hex
        location = models.Location(name=f"Zone Integration {marker}", zone="test", department="QA")
        db.add(location)
        db.flush()
        camera = models.Camera(name=f"Zone Camera {marker}", type="FILE", stream_url="integration-test", status="active", location_id=location.id)
        db.add(camera)
        db.flush()
        zone = models.RestrictedZone(camera_id=camera.id, name="Integration Zone", polygon_points=SQUARE, enabled=True)
        db.add(zone)
        db.flush()
        loaded = load_enabled_zones(db, camera.id)
        assert [z.polygon for z in loaded] == [tuple(tuple(point) for point in SQUARE)]
        assert loaded[0].zone_id == str(zone.id)
        db.delete(camera)
        db.flush()
        assert db.query(models.RestrictedZone).filter(models.RestrictedZone.id == zone.id).count() == 0
        print("PostgreSQL restricted-zone transaction test passed (all test rows rolled back).")
    finally:
        db.rollback()
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres", action="store_true", help="Also test the configured PostgreSQL table inside a rollback-only transaction.")
    args = parser.parse_args()
    run_isolated_tests()
    if args.postgres:
        run_postgres_transaction_test()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
