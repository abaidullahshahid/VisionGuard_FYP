"""Alerts (UC-09), corrective actions (UC-13), instructions (UC-15) and fixes.

Isolated in-memory SQLite; no YOLO.  Run:
    python test_workflows.py
"""

from __future__ import annotations

import os
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import get_db
import models
from routers import admin, auth, notifications, officer, worker
from routers.auth import hash_password
from services.incident_service import persist_incident


def _app(Session) -> FastAPI:
    app = FastAPI()
    for module in (auth, admin, officer, worker, notifications):
        app.include_router(module.router)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    return app


def _ai_incident(**overrides):
    payload = {
        "incident_id": str(uuid4()),
        "incident_type": "PPE_VIOLATION",
        "severity": "LOW",
        "track_id": 4,
        "stream_time_seconds": 3.0,
        "missing_items": ["gloves"],
        "metadata": {},
        "timestamp": "2026-10-07T10:00:00+00:00",
    }
    payload.update(overrides)
    return payload


def run_tests() -> None:
    # These checks cover the admin fallback; never send real email from tests.
    os.environ["SMTP_USERNAME"] = ""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with Session() as db:
        site, store, empty = (
            models.Location(name="Site A", zone="A", department="QA"),
            models.Location(name="Store", zone="B", department="QA"),
            models.Location(name="Spare", zone="C", department="QA"),
        )
        db.add_all([site, store, empty]); db.flush()
        users = {
            role: models.User(name=f"{role.title()} One", email=f"{role}@t.local", password=hash_password("test1234"), role=role, status="active")
            for role in ("admin", "officer", "worker")
        }
        other_worker = models.User(name="Other Worker", email="other@t.local", password=hash_password("test1234"), role="worker", status="active")
        db.add_all([*users.values(), other_worker]); db.flush()
        db.add(models.WorkerLocation(worker_id=users["worker"].id, location_id=site.id))
        db.add(models.WorkerLocation(worker_id=other_worker.id, location_id=store.id))
        camera = models.Camera(name="Gate Cam", type="WEBCAM", stream_url="0", status="active", location_id=site.id)
        store_cam = models.Camera(name="Store Cam", type="WEBCAM", stream_url="0", status="active", location_id=store.id)
        db.add_all([camera, store_cam]); db.commit()
        ids = {k: v.id for k, v in users.items()}
        site_id, store_id, empty_id, camera_id, store_cam_id = site.id, store.id, empty.id, camera.id, store_cam.id

    client = TestClient(_app(Session))
    headers = {
        role: {"Authorization": f"Bearer {client.post('/auth/login', json={'email': f'{role}@t.local', 'password': 'test1234'}).json()['token']}"}
        for role in ("admin", "officer", "worker")
    }

    # ── UC-15: a rule is published to the location's workers ─────────
    rule = client.post("/admin/safety-rules", json={"location_id": site_id, "ppe_type": "Gloves", "severity_level": "Critical"}, headers=headers["admin"])
    assert rule.status_code == 201, rule.text
    instructions = client.get("/worker/safety-instructions", headers=headers["worker"]).json()
    assert len(instructions) == 1 and instructions[0]["title"] == "Gloves Required at Site A"
    assert instructions[0]["source"] == "safety_rule" and instructions[0]["acknowledgeable"]
    assert instructions[0]["dos"] == ["Must wear Gloves"]
    note = client.get("/notifications", headers=headers["worker"]).json()
    assert note["unread"] == 1 and note["items"][0]["kind"] == "instruction"
    ack = client.post(f"/worker/safety-instructions/{instructions[0]['instruction_id']}/acknowledge", headers=headers["worker"])
    assert ack.status_code == 200 and client.get("/worker/safety-instructions", headers=headers["worker"]).json()[0]["acknowledged"]

    # Officer-written instruction + acknowledgement progress.
    published = client.post("/officer/safety-instructions", json={"location_id": site_id, "title": "Evacuation route", "content": "Use exit B.", "category": "emergency"}, headers=headers["officer"])
    assert published.status_code == 201, published.text
    listing = {item["title"]: item for item in client.get("/officer/safety-instructions", headers=headers["officer"]).json()}
    assert listing["Gloves Required at Site A"]["acknowledged_workers"] == 1 and listing["Evacuation route"]["assigned_workers"] == 1
    assert client.delete(f"/officer/safety-instructions/{listing['Gloves Required at Site A']['id']}", headers=headers["officer"]).status_code == 409
    assert client.delete(f"/officer/safety-instructions/{published.json()['id']}", headers=headers["officer"]).status_code == 200
    # Rules created before this feature are published on first view.
    with Session() as db:
        legacy = models.SafetyRule(location_id=store_id, is_restricted_area=True, severity_level="High")
        db.add(legacy); db.commit()
    other_token = client.post("/auth/login", json={"email": "other@t.local", "password": "test1234"}).json()["token"]
    store_instructions = client.get("/worker/safety-instructions", headers={"Authorization": f"Bearer {other_token}"}).json()
    assert [item["title"] for item in store_instructions] == ["Restricted Area: Do Not Enter Store"]
    # Deleting a rule removes its instruction and acknowledgements.
    assert client.delete(f"/admin/safety-rules/{rule.json()['id']}", headers=headers["admin"]).status_code == 200
    assert client.get("/worker/safety-instructions", headers=headers["worker"]).json() == []

    # ── UC-09 + rule severity: AI incidents alert officers and workers ─
    client.post("/admin/safety-rules", json={"location_id": site_id, "ppe_type": "Gloves", "severity_level": "Critical"}, headers=headers["admin"])
    with Session() as db:
        record, created = persist_incident(db, _ai_incident(), camera_db_id=camera_id)
        assert created and record.severity_level == "CRITICAL"
        assert record.incident_metadata["default_severity"] == "LOW" and record.incident_metadata["severity_source"] == "safety_rule"
        zone_record, _ = persist_incident(db, _ai_incident(incident_type="RESTRICTED_ZONE_VIOLATION", severity="HIGH", missing_items=[], zone_id=f"location-{store_id}", zone_name="Restricted area: Store"), camera_db_id=store_cam_id)
        assert zone_record.severity_level == "HIGH"  # store's restricted rule is High
        drawn, _ = persist_incident(db, _ai_incident(incident_type="RESTRICTED_ZONE_VIOLATION", severity="HIGH", missing_items=[], zone_id="17", zone_name="Shelf"), camera_db_id=camera_id)
        assert drawn.severity_level == "HIGH" and "severity_source" not in drawn.incident_metadata
        incident_id = record.id
    officer_alerts = client.get("/notifications", headers=headers["officer"]).json()
    assert officer_alerts["unread"] == 3
    top = officer_alerts["items"][0]
    assert top["kind"] == "incident" and top["severity"] == "CRITICAL" and top["link"] == f"/officer/incidents?incident={incident_id}"
    assert "Missing gloves" in top["message"] and "Gate Cam" in top["message"]
    worker_alerts = [item for item in client.get("/notifications", headers=headers["worker"]).json()["items"] if item["kind"] == "safety_alert"]
    assert len(worker_alerts) == 2  # both Site A incidents, not the Store one
    assert client.get("/notifications", headers=headers["admin"]).json()["unread"] == 0
    first = officer_alerts["items"][0]["id"]
    assert client.post(f"/notifications/{first}/read", headers=headers["officer"]).status_code == 200
    assert client.post(f"/notifications/{first}/read", headers=headers["worker"]).status_code == 404  # not theirs
    assert client.post("/notifications/read-all", headers=headers["officer"]).json()["updated"] == 2
    assert client.get("/notifications", headers=headers["officer"]).json()["unread"] == 0

    # ── UC-13: assignment notifies, worker updates, incident follows ──
    action = client.post("/officer/corrective-actions", json={"incident_id": incident_id, "assigned_to": ids["worker"], "description": "Collect gloves from store", "priority": "High", "deadline": "2026-10-10"}, headers=headers["officer"])
    assert action.status_code == 201 and action.json()["assignee_name"] == "Worker One"
    task_note = [item for item in client.get("/notifications", headers=headers["worker"]).json()["items"] if item["kind"] == "task"]
    assert task_note and task_note[0]["link"] == "/worker/tasks"
    detail = client.get(f"/officer/incidents/{incident_id}", headers=headers["officer"]).json()
    assert detail["status"] == "in_progress" and detail["corrective_actions"][0]["assignee_name"] == "Worker One"
    tasks = client.get("/worker/corrective-actions", headers=headers["worker"]).json()
    assert len(tasks) == 1 and tasks[0]["incident"]["location"] == "Site A"
    assert client.patch(f"/worker/corrective-actions/{tasks[0]['id']}", json={"status": "Done"}, headers=headers["worker"]).status_code == 422
    other_header = {"Authorization": f"Bearer {other_token}"}
    assert client.patch(f"/worker/corrective-actions/{tasks[0]['id']}", json={"status": "Resolved"}, headers=other_header).status_code == 404
    resolved = client.patch(f"/worker/corrective-actions/{tasks[0]['id']}", json={"status": "Resolved"}, headers=headers["worker"])
    assert resolved.status_code == 200 and resolved.json()["status"] == "Resolved"
    assert client.get(f"/officer/incidents/{incident_id}", headers=headers["officer"]).json()["status"] == "resolved"
    update_note = client.get("/notifications", headers=headers["officer"]).json()["items"][0]
    assert update_note["kind"] == "task_update" and "Worker One" in update_note["message"]
    # Officer reopening it notifies the worker and reopens the incident.
    client.patch(f"/officer/corrective-actions/{tasks[0]['id']}", json={"status": "In Progress"}, headers=headers["officer"])
    assert client.get(f"/officer/incidents/{incident_id}", headers=headers["officer"]).json()["status"] == "in_progress"
    worker_items = client.get("/notifications", headers=headers["worker"]).json()["items"]
    assert any(item["kind"] == "task_update" and not item["read"] for item in worker_items)
    assert worker_items[0]["severity"] == "CRITICAL"  # unread alerts are ordered most severe first

    # ── Forgot password: request only, admin resets ────────────────────
    assert client.post("/auth/reset-password", json={"email": "worker@t.local", "new_password": "hacked1", "confirm_password": "hacked1"}).status_code == 400  # no code, no change
    generic = client.post("/auth/forgot-password", json={"email": "worker@t.local"})
    unknown = client.post("/auth/forgot-password", json={"email": "nobody@t.local"})
    assert generic.status_code == unknown.status_code == 200 and generic.json() == unknown.json()
    client.post("/auth/forgot-password", json={"email": "worker@t.local"})  # repeat is not duplicated
    resets = [item for item in client.get("/notifications", headers=headers["admin"]).json()["items"] if item["kind"] == "password_reset"]
    assert len(resets) == 1 and "worker@t.local" in resets[0]["message"]
    assert client.post("/auth/login", json={"email": "worker@t.local", "password": "test1234"}).status_code == 200  # unchanged
    assert client.patch(f"/admin/users/{ids['worker']}", json={"password": "123"}, headers=headers["admin"]).status_code == 422
    assert client.patch(f"/admin/users/{ids['worker']}", json={"password": "temp4567"}, headers=headers["admin"]).status_code == 200
    assert client.post("/auth/login", json={"email": "worker@t.local", "password": "temp4567"}).status_code == 200
    assert client.patch(f"/admin/users/{ids['worker']}", json={"password": "x" * 8}, headers=headers["officer"]).status_code == 403

    # ── Location delete guard ────────────────────────────────────────
    blocked = client.delete(f"/admin/locations/{site_id}", headers=headers["admin"])
    assert blocked.status_code == 409 and "camera" in blocked.json()["detail"]
    client.post("/admin/safety-rules", json={"location_id": empty_id, "ppe_type": "Helmet", "severity_level": "High"}, headers=headers["admin"])
    assert client.delete(f"/admin/locations/{empty_id}", headers=headers["admin"]).status_code == 200  # rule + instruction go with it
    with Session() as db:
        db.query(models.Camera).filter(models.Camera.location_id == store_id).delete()
        db.commit()
    history = client.delete(f"/admin/locations/{store_id}", headers=headers["admin"])
    assert history.status_code == 409 and "incident history" in history.json()["detail"]

    # ── Deleting a user keeps their history ──────────────────────────
    with Session() as db:
        leaver = models.User(name="Leaving Worker", email="leaver@t.local", password=hash_password("test1234"), role="worker", status="active", department="QA")
        db.add(leaver); db.flush()
        incident, _ = persist_incident(db, _ai_incident(), camera_db_id=camera_id)
        db.add(models.WorkerLocation(worker_id=leaver.id, location_id=site_id))
        done = models.CorrectiveAction(incident_id=incident.id, assigned_to=leaver.id, description="Done task", priority="Low", status="Resolved")
        open_task = models.CorrectiveAction(incident_id=incident.id, assigned_to=leaver.id, description="Open task", priority="High", status="Pending")
        db.add_all([done, open_task]); db.commit()
        leaver_id, done_id, open_id = leaver.id, done.id, open_task.id
        instruction = db.query(models.SafetyInstruction).filter(models.SafetyInstruction.location_id == site_id).first()
        if instruction is not None:
            db.add(models.Acknowledgement(instruction_id=instruction.id, worker_id=leaver_id)); db.commit()
    deleted = client.delete(f"/admin/users/{leaver_id}", headers=headers["admin"])
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["unassigned_actions"] == [open_id] and "1 open one(s) now need a new assignee" in deleted.json()["detail"]
    kept = {a["id"]: a for a in client.get("/officer/corrective-actions", headers=headers["officer"]).json()}
    assert kept[done_id]["assigned_to"] is None and kept[done_id]["assignee_name"] == "Leaving Worker (deleted user)"
    assert kept[open_id]["status"] == "Pending" and kept[open_id]["assigned_to"] is None
    alert = client.get("/notifications", headers=headers["officer"]).json()["items"]
    assert any(item["title"] == f"Corrective action #{open_id} needs a new assignee" for item in alert), alert[:3]
    with Session() as db:
        assert db.get(models.User, leaver_id) is None
        assert db.query(models.WorkerLocation).filter_by(worker_id=leaver_id).count() == 0
    # An officer reassigns the open task; the new assignee is told.
    reassigned = client.patch(f"/officer/corrective-actions/{open_id}", json={"assigned_to": ids["worker"]}, headers=headers["officer"])
    assert reassigned.status_code == 200 and reassigned.json()["assignee_name"] == "Worker One", reassigned.text
    worker_alerts = client.get("/notifications", headers=headers["worker"]).json()["items"]
    assert any(item["kind"] == "task" and "Open task" in (item["message"] or "") for item in worker_alerts)
    assert open_id in [task["id"] for task in client.get("/worker/corrective-actions", headers=headers["worker"]).json()]
    assert client.patch(f"/officer/corrective-actions/{open_id}", json={"assigned_to": 999}, headers=headers["officer"]).status_code == 404
    # Admins cannot delete themselves or the last admin.
    assert client.delete(f"/admin/users/{ids['admin']}", headers=headers["admin"]).status_code == 400

    # ── Departments: admins have none, workers must have one ─────────
    new_admin = client.post("/admin/users", json={"name": "Second Admin", "email": "admin2@t.local", "password": "test1234", "role": "admin", "department": "Ops"}, headers=headers["admin"])
    assert new_admin.status_code == 201 and new_admin.json()["department"] is None, new_admin.text
    no_dept = client.post("/admin/users", json={"name": "New Worker", "email": "w2@t.local", "password": "test1234", "role": "worker", "department": "  "}, headers=headers["admin"])
    assert no_dept.status_code == 422 and "Department is required" in no_dept.json()["detail"]
    officer_no_dept = client.post("/admin/users", json={"name": "New Officer", "email": "o2@t.local", "password": "test1234", "role": "officer"}, headers=headers["admin"])
    assert officer_no_dept.status_code == 201 and officer_no_dept.json()["department"] is None
    promoted = client.patch(f"/admin/users/{officer_no_dept.json()['id']}", json={"role": "admin", "department": "QA"}, headers=headers["admin"])
    assert promoted.json()["role"] == "admin" and promoted.json()["department"] is None
    assert client.patch("/auth/me", json={"department": "Ops"}, headers=headers["admin"]).status_code == 200
    with Session() as db:
        assert db.get(models.User, ids["admin"]).department is None

    models.Base.metadata.drop_all(engine)
    engine.dispose()
    print("Workflow tests passed:")
    print("  - UC-15 rules publish acknowledgeable instructions; officer instructions + progress")
    print("  - UC-09 incidents alert officers (severity-first) and the location's workers")
    print("  - rule severity overrides the AI default (PPE + restricted location)")
    print("  - UC-13 assignment/update notifications, worker tasks, incident status follows actions")
    print("  - forgot password only requests an admin reset; admin sets a temporary password")
    print("  - locations with cameras or incident history cannot be deleted")
    print("  - admins have no department; workers need one")
    print("  - deleting a user keeps action history; open tasks are reassigned")


if __name__ == "__main__":
    run_tests()
