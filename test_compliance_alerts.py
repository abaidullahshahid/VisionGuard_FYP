"""Daily compliance records, CSV export and email alerts.

Isolated in-memory SQLite; emails are captured, never sent.  Run:
    python test_compliance_alerts.py
"""

from __future__ import annotations

import datetime
import os
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import get_db
import models
from routers import admin, alerts, auth, notifications, officer, worker
from routers.auth import hash_password
from services import alert_email_service, compliance_service, email_service
from services.incident_service import persist_incident


def _app(Session) -> FastAPI:
    app = FastAPI()
    for module in (auth, admin, officer, worker, notifications, alerts):
        app.include_router(module.router)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    return app


def _now_iso(offset_minutes: int = 0) -> str:
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=offset_minutes)).isoformat()


def _incident(**overrides):
    payload = {
        "incident_id": str(uuid4()),
        "incident_type": "PPE_VIOLATION",
        "severity": "HIGH",
        "track_id": 1,
        "stream_time_seconds": 2.0,
        "missing_items": ["helmet"],
        "metadata": {},
        "timestamp": _now_iso(),
    }
    payload.update(overrides)
    return payload


def _body(message) -> str:
    parts = [part.get_content() for part in message.walk() if part.get_content_type() in ("text/plain", "text/html")]
    return "\n".join(parts)


def run_tests() -> None:
    os.environ["SMTP_USERNAME"] = "visionguard.alerts@gmail.com"
    os.environ["SMTP_PASSWORD"] = "test-only"
    outbox = []
    email_service.transport = outbox.append
    alert_email_service.run_inline = True

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with Session() as db:
        site = models.Location(name="Site A", zone="A", department="QA")
        store = models.Location(name="Store", zone="B", department="QA")
        spare = models.Location(name="Spare", zone="C", department="QA")
        db.add_all([site, store, spare]); db.flush()
        users = {
            role: models.User(name=f"{role.title()} One", email=f"{role}@t.local", password=hash_password("test1234"), role=role, status="active")
            for role in ("admin", "officer", "worker")
        }
        db.add_all(users.values()); db.flush()
        db.add(models.WorkerLocation(worker_id=users["worker"].id, location_id=site.id))
        site_cam = models.Camera(name="Gate Cam", type="WEBCAM", stream_url="0", status="active", location_id=site.id)
        store_cam = models.Camera(name="Store Cam", type="WEBCAM", stream_url="0", status="active", location_id=store.id)
        db.add_all([site_cam, store_cam]); db.commit()
        site_id, store_id, spare_id, cam_id, store_cam_id = site.id, store.id, spare.id, site_cam.id, store_cam.id
        worker_id = users["worker"].id

    client = TestClient(_app(Session))
    headers = {
        role: {"Authorization": f"Bearer {client.post('/auth/login', json={'email': f'{role}@t.local', 'password': 'test1234'}).json()['token']}"}
        for role in ("admin", "officer", "worker")
    }
    today = compliance_service.local_today().isoformat()

    # ── An AI incident creates/refreshes today's record; alerts are off by default ─
    with Session() as db:
        first, _ = persist_incident(db, _incident(), camera_db_id=cam_id)
        first_id = first.id
    records = client.get("/officer/compliance-records", headers=headers["officer"]).json()
    assert len(records) == 1, records
    site_record = records[0]
    assert site_record["location"] == "Site A" and site_record["record_date"] == today
    assert site_record["violations"] == 1 and site_record["ppe_violations"] == 1
    assert site_record["status"] == "pending" and site_record["status_source"] == "auto"
    assert "missing helmet x1" in site_record["summary"], site_record["summary"]
    # Violations are emailed to safety officers by default.
    assert [message["To"] for message in outbox] == ["officer@t.local"], [m["To"] for m in outbox]
    assert outbox[0]["Subject"] == "[VisionGuard] HIGH: PPE violation at Site A"
    outbox.clear()

    # ── Generate: monitored locations get a record, unmonitored ones do not ─
    generated = client.post("/officer/compliance-records/generate", json={}, headers=headers["officer"])
    assert generated.status_code == 200 and generated.json()["generated"] == 2, generated.text
    by_location = {r["location"]: r for r in client.get("/officer/compliance-records", headers=headers["officer"]).json()}
    assert set(by_location) == {"Site A", "Store"}
    assert by_location["Store"]["status"] == "compliant" and by_location["Store"]["violations"] == 0
    assert "No violations detected (1 camera monitoring)" in by_location["Store"]["summary"]
    # Generating again does not duplicate rows.
    client.post("/officer/compliance-records/generate", json={}, headers=headers["officer"])
    assert len(client.get("/officer/compliance-records", headers=headers["officer"]).json()) == 2
    future = (compliance_service.local_today() + datetime.timedelta(days=1)).isoformat()
    assert client.post("/officer/compliance-records/generate", json={"date": future}, headers=headers["officer"]).status_code == 422
    assert client.post("/officer/compliance-records/generate", json={"location_id": 999}, headers=headers["officer"]).status_code == 404
    assert client.get("/officer/compliance-records", headers=headers["worker"]).status_code == 403

    stats = client.get("/officer/compliance-stats", headers=headers["officer"]).json()
    assert stats == {"compliant": 1, "nonCompliant": 0, "pending": 1, "total": 2, "totalViolations": 1, "complianceRate": 50.0}, stats
    assert [r["location"] for r in client.get("/officer/compliance-records?status=compliant", headers=headers["officer"]).json()] == ["Store"]
    assert len(client.get(f"/officer/compliance-records?location_id={site_id}", headers=headers["officer"]).json()) == 1
    assert client.get("/officer/compliance-records?date_from=2000-01-01&date_to=2000-01-02", headers=headers["officer"]).json() == []
    assert client.get("/officer/compliance-records?status=great", headers=headers["officer"]).status_code == 422
    assert client.get("/officer/compliance-records?date_from=yesterday", headers=headers["officer"]).status_code == 422

    # ── Corrective actions: resolving everything makes the day non-compliant ─
    action = client.post("/officer/corrective-actions", json={"incident_id": first_id, "assigned_to": worker_id, "description": "Wear helmet", "priority": "High"}, headers=headers["officer"])
    assert action.status_code == 201, action.text
    record = client.get(f"/officer/compliance-records?location_id={site_id}", headers=headers["officer"]).json()[0]
    assert record["actions_total"] == 1 and record["actions_resolved"] == 0 and record["status"] == "pending"
    done = client.patch(f"/worker/corrective-actions/{action.json()['id']}", json={"status": "Resolved"}, headers=headers["worker"])
    assert done.status_code == 200, done.text
    record = client.get(f"/officer/compliance-records?location_id={site_id}", headers=headers["officer"]).json()[0]
    assert record["actions_resolved"] == 1 and record["open_incidents"] == 0, record
    assert record["status"] == "non-compliant" and "1 of 1 resolved" in record["summary"], record

    # ── Officer review overrides the status and survives refreshes ─
    reviewed = client.patch(f"/officer/compliance-records/{record['id']}", json={"status": "compliant", "notes": "=HYPERLINK(\"x\") briefed team"}, headers=headers["officer"])
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "compliant" and reviewed.json()["status_source"] == "officer"
    assert reviewed.json()["officer"] == "Officer One" and reviewed.json()["reviewed_at"]
    with Session() as db:
        persist_incident(db, _incident(severity="LOW", missing_items=["gloves"]), camera_db_id=cam_id)
    record = client.get(f"/officer/compliance-records?location_id={site_id}", headers=headers["officer"]).json()[0]
    assert record["violations"] == 2 and record["status"] == "compliant" and record["auto_status"] == "pending", record
    back = client.patch(f"/officer/compliance-records/{record['id']}", json={"status": "auto"}, headers=headers["officer"]).json()
    assert back["status"] == "pending" and back["status_source"] == "auto"
    assert back["notes"].startswith("=HYPERLINK"), "notes are kept when only the status changes"
    assert client.patch(f"/officer/compliance-records/{record['id']}", json={"status": "bad"}, headers=headers["officer"]).status_code == 422
    assert client.patch("/officer/compliance-records/999", json={"status": "auto"}, headers=headers["officer"]).status_code == 404

    # ── CSV export ─
    export = client.get("/officer/compliance-records/export", headers=headers["officer"])
    assert export.status_code == 200 and export.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=\"visionguard-compliance-" in export.headers["content-disposition"]
    assert export.content.startswith(b"\xef\xbb\xbf"), "Excel needs the UTF-8 BOM"
    lines = export.content.decode("utf-8-sig").splitlines()
    assert lines[0].startswith("Date,Location,Status,Status set by,Violations"), lines[0]
    assert len(lines) == 3 and any("Site A" in line for line in lines)
    assert "'=HYPERLINK" in export.content.decode("utf-8-sig"), "formula-looking text is neutralised"
    only_store = client.get("/officer/compliance-records/export?status=compliant", headers=headers["officer"]).content.decode("utf-8-sig").splitlines()
    assert len(only_store) == 2 and "Store" in only_store[1]

    # ── Alert settings API ─
    assert client.get("/admin/alert-settings", headers=headers["officer"]).status_code == 403
    overview = client.get("/admin/alert-settings", headers=headers["admin"]).json()
    assert overview["email_configured"] and overview["sender"] == "visionguard.alerts@gmail.com"
    assert overview["settings"]["email_enabled"] is True and overview["settings"]["min_severity"] == "LOW"
    assert overview["recipients"]["staff"] == ["officer@t.local"] and overview["recipients"]["assigned_workers"] == 1
    settings = dict(overview["settings"])
    for key in ("last_summary_date", "updated_at"):
        settings.pop(key)
    bad = client.put("/admin/alert-settings", json={**settings, "extra_recipients": "boss@site.com, not-an-email"}, headers=headers["admin"])
    assert bad.status_code == 422 and "not-an-email" in bad.json()["detail"]
    assert client.put("/admin/alert-settings", json={**settings, "min_severity": "URGENT"}, headers=headers["admin"]).status_code == 422
    assert client.put("/admin/alert-settings", json={**settings, "daily_summary_hour": 24}, headers=headers["admin"]).status_code == 422
    settings.update(email_enabled=True, min_severity="HIGH", extra_recipients="Boss@Site.com; boss@site.com\nmanager@site.com", cooldown_minutes=5)
    saved = client.put("/admin/alert-settings", json=settings, headers=headers["admin"])
    assert saved.status_code == 200, saved.text
    assert saved.json()["settings"]["extra_recipients"] == "boss@site.com, manager@site.com"
    assert saved.json()["recipients"]["staff"] == ["officer@t.local", "boss@site.com", "manager@site.com"]

    # ── Violation email: HIGH incident goes out; repeats are held back; LOW is ignored ─
    outbox.clear()
    with Session() as db:  # start the cooldown checks from a clean log
        db.query(models.EmailAlertLog).delete(); db.commit()
    with Session() as db:
        alert, _ = persist_incident(db, _incident(incident_type="RESTRICTED_ZONE_VIOLATION", missing_items=[], zone_id="location-1", zone_name="Site A (restricted area)"), camera_db_id=cam_id)
        alert_id = alert.id
    assert len(outbox) == 1, outbox
    message = outbox[0]
    assert message["Subject"] == "[VisionGuard] HIGH: Restricted zone violation at Site A", message["Subject"]
    assert message["To"] == "officer@t.local, boss@site.com, manager@site.com"
    body = _body(message)
    assert f"/officer/incidents?incident={alert_id}" in body and "Gate Cam" in body and "Person entered Site A (restricted area)" in body
    with Session() as db:
        persist_incident(db, _incident(incident_type="RESTRICTED_ZONE_VIOLATION", missing_items=[], zone_id="location-1"), camera_db_id=cam_id)
        persist_incident(db, _incident(severity="LOW", missing_items=["gloves"]), camera_db_id=cam_id)
    assert len(outbox) == 1, "cooldown and minimum severity stop extra emails"
    log = client.get("/admin/alert-settings", headers=headers["admin"]).json()["log"]
    assert [entry["status"] for entry in log[:2]] == ["skipped", "sent"], log
    assert "less than 5 min" in log[0]["detail"]
    # A different violation type at the same place is not held back.
    with Session() as db:
        persist_incident(db, _incident(missing_items=["helmet", "vest"]), camera_db_id=cam_id)
    assert len(outbox) == 2 and "PPE violation at Site A" in outbox[1]["Subject"]
    assert "Missing helmet, vest" in _body(outbox[1])

    # Workers (opt-in) get their own email without the officer link.
    settings.update(email_workers=True, cooldown_minutes=0, extra_recipients="")
    client.put("/admin/alert-settings", json=settings, headers=headers["admin"])
    outbox.clear()
    with Session() as db:
        persist_incident(db, _incident(), camera_db_id=cam_id)
    assert [m["To"] for m in outbox] == ["officer@t.local", "worker@t.local"], [m["To"] for m in outbox]
    assert outbox[1]["Subject"] == "[VisionGuard] Safety alert at Site A"
    assert "/officer/incidents" not in _body(outbox[1]) and "/worker/instructions" in _body(outbox[1])
    # Officer-created incidents are emailed too.
    outbox.clear()
    manual = client.post("/officer/incidents", json={"camera_id": store_cam_id, "violation_type": "RESTRICTED_ZONE_VIOLATION", "severity_level": "CRITICAL", "zone_id": "manual"}, headers=headers["officer"])
    assert manual.status_code == 201, manual.text
    assert len(outbox) == 1 and outbox[0]["Subject"].startswith("[VisionGuard] CRITICAL:")
    store_record = client.get(f"/officer/compliance-records?location_id={store_id}", headers=headers["officer"]).json()[0]
    assert store_record["violations"] == 1 and store_record["status"] == "pending"

    # Turning alerts off stops them.
    settings.update(email_enabled=False)
    client.put("/admin/alert-settings", json=settings, headers=headers["admin"])
    outbox.clear()
    with Session() as db:
        persist_incident(db, _incident(), camera_db_id=cam_id)
    assert outbox == []

    # ── Snapshot is embedded in the email ─
    message = email_service.build_message(["a@b.com"], "s", "text", "<img src=\"cid:snapshot\">", inline_image=(b"\xff\xd8jpeg", "snapshot"))
    images = [part for part in message.walk() if part.get_content_type() == "image/jpeg"]
    assert len(images) == 1 and images[0]["Content-ID"] == "<snapshot>"

    # ── Test email, daily summary (manual + scheduled once a day), camera alert ─
    outbox.clear()
    test = client.post("/admin/alert-settings/test", headers=headers["admin"])
    assert test.status_code == 200 and test.json()["detail"] == "Sent to officer@t.local.", test.text
    assert outbox[-1]["Subject"] == "[VisionGuard] Test alert"
    summary = client.post("/admin/alert-settings/send-summary", headers=headers["admin"])
    assert summary.status_code == 200, summary.text
    sent = outbox[-1]
    assert sent["Subject"].startswith("[VisionGuard] Daily compliance summary")
    attachments = [part for part in sent.walk() if part.get_filename() == f"visionguard-compliance-{today}.csv"]
    assert len(attachments) == 1 and b"Site A" in attachments[0].get_payload(decode=True)
    assert "Compliance rate" in _body(sent)

    settings.update(email_enabled=True, daily_summary=True, daily_summary_hour=17)
    client.put("/admin/alert-settings", json=settings, headers=headers["admin"])
    outbox.clear()
    with Session() as db:
        early = datetime.datetime.now().astimezone().replace(hour=16, minute=0)
        late = early.replace(hour=18)
        assert alert_email_service.maybe_send_daily_summary(db, early) is None
        assert alert_email_service.maybe_send_daily_summary(db, late).status == "sent"
        assert alert_email_service.maybe_send_daily_summary(db, late.replace(hour=19)) is None
    assert len(outbox) == 1

    outbox.clear()
    with Session() as db:
        assert alert_email_service.send_camera_alert(db, cam_id, "Cannot open camera 0").status == "sent"
        assert alert_email_service.send_camera_alert(db, cam_id, "Cannot open camera 0") is None
    assert len(outbox) == 1 and "Camera feed unavailable: Gate Cam" in outbox[0]["Subject"]

    # No recipients → the test button explains why.
    settings.update(email_officers=False, extra_recipients="")
    client.put("/admin/alert-settings", json=settings, headers=headers["admin"])
    nobody = client.post("/admin/alert-settings/test", headers=headers["admin"])
    assert nobody.status_code == 400 and "No recipients" in nobody.json()["detail"]

    # Gmail failure is reported, not hidden.
    settings.update(email_officers=True)
    client.put("/admin/alert-settings", json=settings, headers=headers["admin"])

    def broken(message):
        raise OSError("connection refused")

    email_service.transport = broken
    failed = client.post("/admin/alert-settings/test", headers=headers["admin"])
    assert failed.status_code == 502 and "connection refused" in failed.json()["detail"]
    email_service.transport = outbox.append

    # Gmail not configured → clear message.
    os.environ["SMTP_PASSWORD"] = ""
    unconfigured = client.post("/admin/alert-settings/test", headers=headers["admin"])
    assert unconfigured.status_code == 400 and "Gmail is not set up" in unconfigured.json()["detail"]

    # Deleting a location still works with compliance history.
    assert client.delete(f"/admin/locations/{spare_id}", headers=headers["admin"]).status_code == 200
    print("compliance + email alert tests passed")


if __name__ == "__main__":
    run_tests()
