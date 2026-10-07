"""Several PPE items per rule, and deleting incidents (one, listed, all).

Isolated in-memory SQLite; no YOLO, no email.  Run:
    python test_rules_and_deletes.py
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path
import shutil
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import get_db
import models
from routers import admin, auth, notifications, officer
from routers.auth import hash_password
from services.incident_service import EVIDENCE_ROOT, persist_incident
from services.ppe_rule_service import load_required_ppe_for_camera


def _app(Session) -> FastAPI:
    app = FastAPI()
    for module in (auth, admin, officer, notifications):
        app.include_router(module.router)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    return app


def _incident(**overrides):
    payload = {
        "incident_id": str(uuid4()),
        "incident_type": "PPE_VIOLATION",
        "severity": "HIGH",
        "track_id": 1,
        "stream_time_seconds": 2.0,
        "missing_items": ["helmet"],
        "metadata": {},
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    payload.update(overrides)
    return payload


def run_tests() -> None:
    os.environ["SMTP_USERNAME"] = ""  # no email from these tests
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with Session() as db:
        site, yard, store = (models.Location(name=n, zone="Z", department="QA") for n in ("Site", "Yard", "Store"))
        db.add_all([site, yard, store]); db.flush()
        users = {role: models.User(name=f"{role.title()} One", email=f"{role}@t.local", password=hash_password("test1234"), role=role, status="active") for role in ("admin", "officer", "worker")}
        db.add_all(users.values()); db.flush()
        site_cam = models.Camera(name="Site Cam", type="WEBCAM", stream_url="0", status="active", location_id=site.id)
        yard_cam = models.Camera(name="Yard Cam", type="WEBCAM", stream_url="1", status="active", location_id=yard.id)
        db.add_all([site_cam, yard_cam]); db.commit()
        site_id, yard_id, store_id, site_cam_id, yard_cam_id = site.id, yard.id, store.id, site_cam.id, yard_cam.id
        worker_id = users["worker"].id
    client = TestClient(_app(Session))
    headers = {
        role: {"Authorization": f"Bearer {client.post('/auth/login', json={'email': f'{role}@t.local', 'password': 'test1234'}).json()['token']}"}
        for role in ("admin", "officer")
    }

    # ── Several PPE items at once ───────────────────────────────────
    two = client.post("/admin/safety-rules/batch", json={"location_id": site_id, "ppe_types": ["Safety Vest", "Helmet"], "severity_level": "High"}, headers=headers["admin"])
    assert two.status_code == 201, two.text
    assert [rule["ppe_type"] for rule in two.json()["created"]] == ["Helmet", "Safety Vest"]
    assert two.json()["detail"] == "Site now requires Helmet, Safety Vest."
    assert load_required_ppe_for_camera(site_cam_id, Session) == frozenset({"helmet", "vest"})
    # Workers get one instruction per required item.
    with Session() as db:
        assert db.query(models.SafetyInstruction).filter_by(location_id=site_id).count() == 2
    again = client.post("/admin/safety-rules/batch", json={"location_id": site_id, "ppe_types": ["Helmet"], "severity_level": "High"}, headers=headers["admin"])
    assert again.status_code == 409 and "already requires Helmet" in again.json()["detail"]
    more = client.post("/admin/safety-rules/batch", json={"location_id": site_id, "ppe_types": ["Helmet", "Gloves"], "severity_level": "Low"}, headers=headers["admin"])
    assert more.status_code == 201 and more.json()["skipped"] == ["Helmet"], more.text
    assert load_required_ppe_for_camera(site_cam_id, Session) == frozenset({"helmet", "vest", "gloves"})
    # All three ticked = one "All PPE" rule.
    everything = client.post("/admin/safety-rules/batch", json={"location_id": yard_id, "ppe_types": ["Helmet", "Safety Vest", "Gloves"]}, headers=headers["admin"])
    assert [rule["ppe_type"] for rule in everything.json()["created"]] == ["All PPE"], everything.text
    covered = client.post("/admin/safety-rules/batch", json={"location_id": yard_id, "ppe_types": ["Gloves"]}, headers=headers["admin"])
    assert covered.status_code == 409
    # The page uses the plain address (some extensions block "batch" URLs).
    plain = client.post("/admin/safety-rules", json={"location_id": store_id, "ppe_types": ["Helmet", "Gloves"], "severity_level": "Medium"}, headers=headers["admin"])
    assert plain.status_code == 201 and plain.json()["detail"] == "Store now requires Helmet, Gloves.", plain.text
    single = client.post("/admin/safety-rules", json={"location_id": store_id, "ppe_type": "Safety Vest", "severity_level": "Low"}, headers=headers["admin"])
    assert single.status_code == 201 and single.json()["ppe_type"] == "Safety Vest", single.text
    with Session() as db:
        for rule in db.query(models.SafetyRule).filter_by(location_id=store_id).all():
            db.delete(rule)
        db.commit()
    # Conflicts and bad input.
    client.post("/admin/safety-rules", json={"location_id": store_id, "ppe_type": "No PPE"}, headers=headers["admin"])
    assert client.post("/admin/safety-rules/batch", json={"location_id": store_id, "ppe_types": ["Helmet"]}, headers=headers["admin"]).status_code == 409
    assert client.post("/admin/safety-rules/batch", json={"location_id": yard_id, "ppe_types": []}, headers=headers["admin"]).status_code == 422
    assert client.post("/admin/safety-rules/batch", json={"location_id": yard_id, "ppe_types": ["Boots"]}, headers=headers["admin"]).status_code == 422
    assert client.post("/admin/safety-rules/batch", json={"location_id": yard_id, "ppe_types": ["No PPE"]}, headers=headers["admin"]).status_code == 422
    assert client.post("/admin/safety-rules/batch", json={"location_id": 999, "ppe_types": ["Helmet"]}, headers=headers["admin"]).status_code == 404
    assert client.post("/admin/safety-rules/batch", json={"location_id": yard_id, "ppe_types": ["Helmet"]}, headers=headers["officer"]).status_code == 403

    # ── Deleting incidents ──────────────────────────────────────────
    folder = EVIDENCE_ROOT / "test-delete"
    folder.mkdir(parents=True, exist_ok=True)
    snapshot = folder / f"{uuid4()}.jpg"
    snapshot.write_bytes(b"\xff\xd8test\xff\xd9")
    try:
        with Session() as db:
            first, _ = persist_incident(db, _incident(evidence_path=str(snapshot.relative_to(EVIDENCE_ROOT))), camera_db_id=site_cam_id)
            ids = [first.id] + [persist_incident(db, _incident(), camera_db_id=cam)[0].id for cam in (site_cam_id, yard_cam_id, yard_cam_id)]
            db.add(models.CorrectiveAction(incident_id=first.id, assigned_to=worker_id, description="Fix", priority="High", status="Pending"))
            db.commit()
        assert snapshot.is_file()
        record = lambda: client.get(f"/officer/compliance-records?location_id={site_id}", headers=headers["officer"]).json()[0]
        assert record()["violations"] == 2

        one = client.delete(f"/officer/incidents/{ids[0]}", headers=headers["officer"])
        assert one.status_code == 200 and "Incident #" in one.json()["detail"], one.text
        assert not snapshot.exists(), "evidence image removed"
        with Session() as db:
            assert db.get(models.Incident, ids[0]) is None
            assert db.query(models.CorrectiveAction).filter_by(incident_id=ids[0]).count() == 0
            assert db.query(models.Notification).filter(models.Notification.link == f"/officer/incidents?incident={ids[0]}").count() == 0
        assert record()["violations"] == 1, "compliance count follows the deletion"
        assert client.delete(f"/officer/incidents/{ids[0]}", headers=headers["officer"]).status_code == 404

        listed = client.post("/officer/incidents/delete", json={"ids": [ids[1], ids[2]]}, headers=headers["officer"])
        assert listed.status_code == 200 and listed.json()["deleted"] == 2
        assert [i["id"] for i in client.get("/officer/incidents", headers=headers["officer"]).json()] == [ids[3]]
        assert client.post("/officer/incidents/delete", json={}, headers=headers["officer"]).status_code == 422

        with Session() as db:
            for _ in range(3):
                persist_incident(db, _incident(), camera_db_id=yard_cam_id)
        everything = client.post("/officer/incidents/delete", json={"all": True}, headers=headers["admin"])
        assert everything.status_code == 200 and everything.json()["deleted"] == 4, everything.text
        assert client.get("/officer/incidents", headers=headers["officer"]).json() == []
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    engine.dispose()
    print("Rule and delete tests passed:")
    print("  - several PPE items in one go (duplicates skipped, all three = All PPE)")
    print("  - delete one, listed or all incidents with actions, alerts and snapshots")


if __name__ == "__main__":
    run_tests()
