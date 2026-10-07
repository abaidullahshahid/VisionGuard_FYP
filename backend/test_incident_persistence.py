"""Deterministic tests for AI incident persistence and Officer APIs.

Run isolated tests:
    python test_incident_persistence.py

Also verify the configured PostgreSQL database (transaction is rolled back):
    python test_incident_persistence.py --postgres
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import shutil
from urllib.parse import parse_qs, urlsplit
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
from ai_module.incident_manager import Incident
from ai_module.realtime_pipeline import RealtimePPEPipeline
from routers import admin, auth, officer, worker
from routers.auth import decode_token, hash_password
from services.camera_stream import iter_mjpeg_frames, open_camera_capture
from services.incident_service import EVIDENCE_ROOT, persist_incident


def _payload(
    incident_type: str,
    evidence_path: Path,
    camera_id: object,
    **changes: object,
) -> dict:
    payload = {
        "incident_id": str(uuid4()),
        "incident_type": incident_type,
        "track_id": 7,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stream_time_seconds": 4.2,
        "severity": "HIGH",
        "camera_id": camera_id,
        "missing_items": ["helmet", "gloves"] if incident_type == "PPE_VIOLATION" else [],
        "zone_id": "zone_1" if incident_type == "RESTRICTED_ZONE_VIOLATION" else None,
        "zone_name": "Restricted Area" if incident_type == "RESTRICTED_ZONE_VIOLATION" else None,
        "evidence_path": str(evidence_path),
        "metadata": {"confirmation_duration_seconds": 2.0},
    }
    payload.update(changes)
    return payload


def _make_evidence_directory() -> tuple[Path, Path]:
    directory = (EVIDENCE_ROOT / f"_persistence_test_{uuid4().hex}").resolve()
    directory.mkdir(parents=True, exist_ok=False)
    image_path = directory / "evidence.jpg"
    image = np.zeros((32, 48, 3), dtype=np.uint8)
    image[:, :] = (15, 120, 220)
    if not cv2.imwrite(str(image_path), image):
        raise RuntimeError("Could not create the test evidence image")
    return directory, image_path


def _make_test_video(directory: Path) -> Path:
    video_path = directory / "camera_stream.avi"
    writer = cv2.VideoWriter(
        str(video_path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        8.0,
        (96, 64),
    )
    if not writer.isOpened():
        raise RuntimeError("Could not create the camera stream test video")
    try:
        for index in range(4):
            frame = np.zeros((64, 96, 3), dtype=np.uint8)
            frame[:, :] = (20 + index * 30, 80, 180)
            cv2.putText(frame, str(index), (36, 42), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            writer.write(frame)
    finally:
        writer.release()
    return video_path


def _build_test_app(session_factory):
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(officer.router)
    app.include_router(worker.router)

    def override_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    return app


def run_isolated_tests() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    evidence_directory, evidence_path = _make_evidence_directory()
    stream_path = _make_test_video(evidence_directory)

    try:
        db = TestSession()
        location = models.Location(name="Persistence Test Location", zone="T", department="QA")
        db.add(location)
        db.flush()
        camera = models.Camera(
            name="Persistence Test Camera",
            type="USB",
            stream_url=str(stream_path),
            status="active",
            location_id=location.id,
        )
        offline_camera = models.Camera(
            name="Offline Test Camera",
            type="FILE",
            stream_url=str(stream_path),
            status="inactive",
            location_id=location.id,
        )
        unavailable_camera = models.Camera(
            name="Unavailable Test Camera",
            type="FILE",
            stream_url=str(evidence_directory / "missing-stream.mp4"),
            status="active",
            location_id=location.id,
        )
        users = [
            models.User(name="Admin", email="admin@test.local", password=hash_password("test1234"), role="admin", status="active"),
            models.User(name="Officer", email="officer@test.local", password=hash_password("test1234"), role="officer", status="active"),
            models.User(name="Worker", email="worker@test.local", password=hash_password("test1234"), role="worker", status="active"),
        ]
        other_location = models.Location(
            name="Unassigned Restricted Location",
            zone="R",
            department="QA",
        )
        db.add_all([camera, offline_camera, unavailable_camera])
        db.add_all(users)
        db.add(other_location)
        db.flush()
        worker_user = next(user for user in users if user.role == "worker")
        admin_user = next(user for user in users if user.role == "admin")
        allowed_instruction = models.SafetyInstruction(
            location_id=location.id,
            created_by=admin_user.id,
            title="Assigned PPE Briefing",
            content="Wear the required PPE before entering the work area.",
            category="ppe",
        )
        denied_instruction = models.SafetyInstruction(
            location_id=other_location.id,
            created_by=admin_user.id,
            title="Unassigned Location Briefing",
            content="This instruction must remain outside the worker's scope.",
            category="procedures",
        )
        db.add_all([
            models.WorkerLocation(worker_id=worker_user.id, location_id=location.id),
            models.SafetyRule(
                location_id=location.id,
                ppe_type="Helmet",
                is_restricted_area=False,
                severity_level="High",
            ),
            models.SafetyRule(
                location_id=other_location.id,
                ppe_type=None,
                is_restricted_area=True,
                severity_level="High",
            ),
            allowed_instruction,
            denied_instruction,
        ])
        db.commit()
        db.refresh(camera)
        db.refresh(offline_camera)
        db.refresh(unavailable_camera)
        db.refresh(allowed_instruction)
        db.refresh(denied_instruction)

        ppe_payload = _payload("PPE_VIOLATION", evidence_path, camera.id)
        ppe, created = persist_incident(db, ppe_payload)
        assert created
        assert ppe.camera_id == camera.id
        assert ppe.location_id == location.id
        assert ppe.track_id == 7
        assert ppe.severity_level == "HIGH"
        assert ppe.missing_items == ["helmet", "gloves"]
        assert ppe.zone_id is None and ppe.zone_name is None
        assert ppe.incident_metadata["confirmation_duration_seconds"] == 2.0
        assert not Path(ppe.evidence_path).is_absolute()

        duplicate, duplicate_created = persist_incident(db, ppe_payload)
        assert not duplicate_created
        assert duplicate.id == ppe.id
        assert db.query(models.Incident).filter(
            models.Incident.incident_uuid == ppe_payload["incident_id"]
        ).count() == 1

        zone_payload = _payload(
            "RESTRICTED_ZONE_VIOLATION",
            evidence_path,
            camera.id,
            track_id=26,
            stream_time_seconds=3.63,
            metadata={"confirmation_duration_seconds": 1.5},
        )
        zone, created = persist_incident(db, zone_payload)
        assert created
        assert zone.missing_items == []
        assert zone.zone_id == "zone_1"
        assert zone.zone_name == "Restricted Area"
        assert zone.severity_level == "HIGH"
        json.dumps(zone_payload)

        malicious = models.Incident(
            incident_uuid=str(uuid4()),
            camera_id=camera.id,
            location_id=location.id,
            violation_type="PPE_VIOLATION",
            severity_level="HIGH",
            missing_items=["helmet"],
            incident_metadata={},
            evidence_path="../database.py",
            status="open",
        )
        db.add(malicious)
        db.commit()
        db.refresh(malicious)
        officer_id = next(user.id for user in users if user.role == "officer")
        worker_id = next(user.id for user in users if user.role == "worker")
        assigned_location_id = location.id
        camera_db_id = camera.id
        offline_camera_id = offline_camera.id
        unavailable_camera_id = unavailable_camera.id
        ppe_db_id = ppe.id
        malicious_db_id = malicious.id
        allowed_instruction_id = allowed_instruction.id
        denied_instruction_id = denied_instruction.id
        db.close()

        client = TestClient(_build_test_app(TestSession))
        for route in ("/admin/stats", "/officer/stats", "/worker/stats"):
            demo_response = client.get(route, headers={"Authorization": "Bearer demo"})
            assert demo_response.status_code == 401, demo_response.text

        login = client.post(
            "/auth/login",
            json={"email": "officer@test.local", "password": "test1234"},
        )
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['token']}"}

        stream_url_response = client.get(
            f"/officer/cameras/{camera_db_id}/stream-url",
            headers=headers,
        )
        assert stream_url_response.status_code == 200, stream_url_response.text
        signed_stream_url = stream_url_response.json()["stream_url"]
        signed_stream_token = parse_qs(urlsplit(signed_stream_url).query)["access_token"][0]
        stream_claims = decode_token(signed_stream_token)
        assert stream_claims["purpose"] == "camera_stream"
        assert stream_claims["camera_id"] == camera_db_id
        assert client.get(f"/officer/cameras/{camera_db_id}/stream-url").status_code == 422
        assert client.get(
            f"/officer/cameras/{offline_camera_id}/stream-url",
            headers=headers,
        ).status_code == 409
        assert client.get(
            f"/officer/cameras/{unavailable_camera_id}/stream-url",
            headers=headers,
        ).status_code == 503
        assert client.get(
            "/officer/cameras/99999/stream-url",
            headers=headers,
        ).status_code == 404
        invalid_stream = client.get(
            f"/officer/cameras/{camera_db_id}/stream",
            params={"access_token": login.json()["token"]},
        )
        assert invalid_stream.status_code == 403

        capture, loop_file, fps = open_camera_capture(str(stream_path))
        stream_generator = iter_mjpeg_frames(capture, loop_file=loop_file, fps=fps)
        first_chunk = next(stream_generator)
        assert first_chunk.startswith(b"--frame\r\nContent-Type: image/jpeg")
        assert b"\xff\xd8" in first_chunk and b"\xff\xd9" in first_chunk
        stream_generator.close()
        assert not capture.isOpened()

        listing = client.get(
            "/officer/incidents",
            params={"severity": "High", "incident_type": "PPE_VIOLATION", "camera": str(camera_db_id)},
            headers=headers,
        )
        assert listing.status_code == 200, listing.text
        assert len(listing.json()) == 2  # valid PPE plus traversal test row
        persisted = next(item for item in listing.json() if item["incident_id"] == ppe_payload["incident_id"])
        assert persisted["missing_items"] == ["helmet", "gloves"]
        assert persisted["severity"] == "HIGH"
        json.dumps(listing.json())

        detail = client.get(f"/officer/incidents/{ppe_db_id}", headers=headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["metadata"]["confirmation_duration_seconds"] == 2.0
        assert detail.json()["zone_id"] is None
        uuid_detail = client.get(
            f"/officer/incidents/{ppe_payload['incident_id']}",
            headers=headers,
        )
        assert uuid_detail.status_code == 200, uuid_detail.text
        assert uuid_detail.json()["id"] == ppe_db_id

        updated = client.patch(
            f"/officer/incidents/{ppe_db_id}",
            json={"status": "in_progress", "officer_notes": "Reviewed by safety officer"},
            headers=headers,
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["status"] == "in_progress"
        assert updated.json()["officer_notes"] == "Reviewed by safety officer"

        evidence = client.get(f"/officer/incidents/{ppe_db_id}/evidence", headers=headers)
        assert evidence.status_code == 200, evidence.text
        assert evidence.headers["content-type"].startswith("image/jpeg")
        assert evidence.content
        signed_evidence = client.get(updated.json()["snapshot_url"])
        assert signed_evidence.status_code == 200, signed_evidence.text
        unauthenticated_evidence = client.get(f"/officer/incidents/{ppe_db_id}/evidence")
        assert unauthenticated_evidence.status_code == 401
        traversal = client.get(
            f"/officer/incidents/{malicious_db_id}/evidence",
            headers=headers,
        )
        assert traversal.status_code == 404

        action = client.post(
            "/officer/corrective-actions",
            json={
                "incident_id": ppe_db_id,
                "assigned_to": officer_id,
                "description": "Inspect PPE controls",
                "priority": "High",
            },
            headers=headers,
        )
        assert action.status_code == 201, action.text
        action_update = client.patch(
            f"/officer/corrective-actions/{action.json()['id']}",
            json={"status": "Resolved", "description": "PPE controls inspected"},
            headers=headers,
        )
        assert action_update.status_code == 200, action_update.text
        assert action_update.json()["description"] == "PPE controls inspected"
        invalid_action_status = client.patch(
            f"/officer/corrective-actions/{action.json()['id']}",
            json={"status": "Deleted"},
            headers=headers,
        )
        assert invalid_action_status.status_code == 422
        missing_assignee = client.post(
            "/officer/corrective-actions",
            json={
                "incident_id": ppe_db_id,
                "assigned_to": 99999,
                "description": "Invalid assignee test",
                "priority": "High",
            },
            headers=headers,
        )
        assert missing_assignee.status_code == 404

        for email, route in (
            ("admin@test.local", "/admin/stats"),
            ("worker@test.local", "/worker/stats"),
        ):
            role_login = client.post(
                "/auth/login",
                json={"email": email, "password": "test1234"},
            )
            assert role_login.status_code == 200, role_login.text
            role_response = client.get(
                route,
                headers={"Authorization": f"Bearer {role_login.json()['token']}"},
            )
            assert role_response.status_code == 200, role_response.text

        worker_login = client.post(
            "/auth/login",
            json={"email": "worker@test.local", "password": "test1234"},
        )
        worker_headers = {"Authorization": f"Bearer {worker_login.json()['token']}"}
        worker_instructions = client.get(
            "/worker/safety-instructions",
            headers=worker_headers,
        )
        assert worker_instructions.status_code == 200, worker_instructions.text
        assert {item["location_id"] for item in worker_instructions.json()} == {assigned_location_id}
        stored_instruction = next(
            item for item in worker_instructions.json()
            if item["instruction_id"] == allowed_instruction_id
        )
        assert stored_instruction["acknowledgeable"] is True
        assert stored_instruction["acknowledged"] is False
        assert all(item["instruction_id"] != denied_instruction_id for item in worker_instructions.json())

        acknowledged = client.post(
            f"/worker/safety-instructions/{allowed_instruction_id}/acknowledge",
            headers=worker_headers,
        )
        assert acknowledged.status_code == 200, acknowledged.text
        assert acknowledged.json()["created"] is True
        acknowledgement_id = acknowledged.json()["id"]
        duplicate_acknowledgement = client.post(
            f"/worker/safety-instructions/{allowed_instruction_id}/acknowledge",
            headers=worker_headers,
        )
        assert duplicate_acknowledgement.status_code == 200, duplicate_acknowledgement.text
        assert duplicate_acknowledgement.json()["created"] is False
        assert duplicate_acknowledgement.json()["id"] == acknowledgement_id
        with TestSession() as verification_db:
            assert verification_db.query(models.Acknowledgement).filter(
                models.Acknowledgement.worker_id == worker_id,
                models.Acknowledgement.instruction_id == allowed_instruction_id,
            ).count() == 1
        refreshed_instructions = client.get(
            "/worker/safety-instructions",
            headers=worker_headers,
        )
        refreshed_stored = next(
            item for item in refreshed_instructions.json()
            if item["instruction_id"] == allowed_instruction_id
        )
        assert refreshed_stored["acknowledged"] is True
        assert refreshed_stored["acknowledged_at"] is not None
        forbidden_acknowledgement = client.post(
            f"/worker/safety-instructions/{denied_instruction_id}/acknowledge",
            headers=worker_headers,
        )
        assert forbidden_acknowledgement.status_code == 403
        officer_cannot_acknowledge = client.post(
            f"/worker/safety-instructions/{allowed_instruction_id}/acknowledge",
            headers=headers,
        )
        assert officer_cannot_acknowledge.status_code == 403

        admin_login = client.post(
            "/auth/login",
            json={"email": "admin@test.local", "password": "test1234"},
        )
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['token']}"}
        created_user = client.post(
            "/admin/users",
            json={
                "name": "Release Test User",
                "email": "release.user@test.local",
                "password": "test1234",
                "role": "worker",
                "department": "QA",
            },
            headers=admin_headers,
        )
        assert created_user.status_code == 201, created_user.text
        user_update = client.patch(
            f"/admin/users/{created_user.json()['id']}",
            json={"status": "inactive"},
            headers=admin_headers,
        )
        assert user_update.status_code == 200 and user_update.json()["status"] == "inactive"
        assert client.delete(
            f"/admin/users/{created_user.json()['id']}",
            headers=admin_headers,
        ).status_code == 200

        created_location = client.post(
            "/admin/locations",
            json={"name": "Release Test Location", "zone": "R", "department": "QA"},
            headers=admin_headers,
        )
        assert created_location.status_code == 201, created_location.text
        release_location_id = created_location.json()["id"]
        created_camera = client.post(
            "/admin/cameras",
            json={
                "name": "Release Test Camera",
                "type": "FILE",
                "stream_url": "test.mp4",
                "location_id": release_location_id,
            },
            headers=admin_headers,
        )
        assert created_camera.status_code == 201, created_camera.text
        created_rule = client.post(
            "/admin/safety-rules",
            json={
                "location_id": release_location_id,
                "ppe_type": "Helmet",
                "is_restricted_area": False,
                "severity_level": "High",
            },
            headers=admin_headers,
        )
        assert created_rule.status_code == 201, created_rule.text
        created_assignment = client.post(
            "/admin/worker-locations",
            json={"worker_id": worker_id, "location_id": release_location_id},
            headers=admin_headers,
        )
        assert created_assignment.status_code == 201, created_assignment.text
        assert client.delete(
            f"/admin/worker-locations/{created_assignment.json()['id']}",
            headers=admin_headers,
        ).status_code == 200
        assert client.delete(
            f"/admin/safety-rules/{created_rule.json()['id']}",
            headers=admin_headers,
        ).status_code == 200
        assert client.delete(
            f"/admin/cameras/{created_camera.json()['id']}",
            headers=admin_headers,
        ).status_code == 200
        assert client.delete(
            f"/admin/locations/{release_location_id}",
            headers=admin_headers,
        ).status_code == 200

        invalid_status = client.patch(
            f"/officer/incidents/{ppe_db_id}",
            json={"status": "deleted"},
            headers=headers,
        )
        assert invalid_status.status_code == 422
        assignees = client.get("/officer/assignees", headers=headers)
        assert assignees.status_code == 200, assignees.text
        assert {user["role"] for user in assignees.json()} == {"admin", "officer", "worker"}

        delivered = []
        generated = Incident(
            incident_id=str(uuid4()),
            incident_type="PPE_VIOLATION",
            track_id=99,
            timestamp=datetime.now(timezone.utc).isoformat(),
            stream_time_seconds=1.0,
            severity="HIGH",
            camera_id=str(camera_db_id),
            missing_items=("helmet",),
            evidence_path=str(evidence_path),
        )

        class FakeManager:
            def create_incidents(self, events, evidence_frame):
                return [generated]

        pipeline = object.__new__(RealtimePPEPipeline)
        pipeline.incident_manager = FakeManager()
        pipeline.incident_sink = delivered.append
        frame_result = type("FrameResult", (), {"events": [object()], "incidents": []})()
        created_incidents = pipeline.create_incidents(frame_result, np.zeros((2, 2, 3)))
        assert created_incidents == [generated]
        assert delivered == [generated.to_dict()]
        def failing_sink(incident):
            raise RuntimeError("simulated database outage")

        pipeline.incident_sink = failing_sink
        logging.disable(logging.CRITICAL)
        try:
            assert pipeline.create_incidents(frame_result, np.zeros((2, 2, 3))) == [generated]
        finally:
            logging.disable(logging.NOTSET)

        print("Isolated incident persistence/API tests passed:")
        print("  - PPE and restricted-zone round trips")
        print("  - JSON fields, severity, camera/location relationships")
        print("  - duplicate UUID rejection")
        print("  - list, filter, detail, status, notes, and corrective action APIs")
        print("  - authenticated evidence response and path-traversal rejection")
        print("  - auth, admin, officer, and worker route regression checks")
        print("  - privileged demo-token rejection and worker instruction scoping")
        print("  - signed camera stream authorization, MJPEG generation, and graceful source errors")
        print("  - persistent, idempotent worker acknowledgement and refresh state")
        print("  - out-of-scope and non-worker acknowledgement rejection")
        print("  - corrective-action assignee and workflow validation")
        print("  - admin user, location, camera, rule, and assignment CRUD")
        print("  - realtime pipeline incident-sink callback")
        print("  - incident-sink failure isolation")
    finally:
        models.Base.metadata.drop_all(engine)
        engine.dispose()
        if evidence_directory.exists() and evidence_directory.parent == EVIDENCE_ROOT:
            shutil.rmtree(evidence_directory)


def run_postgres_transaction_test() -> None:
    """Exercise both incident types against PostgreSQL without retaining rows."""

    evidence_directory, evidence_path = _make_evidence_directory()
    db = SessionLocal()
    try:
        marker = uuid4().hex
        location = models.Location(
            name=f"AI Integration Test {marker}",
            zone="test",
            department="QA",
        )
        db.add(location)
        db.flush()
        camera = models.Camera(
            name=f"AI Integration Camera {marker}",
            type="FILE",
            stream_url="integration-test",
            status="active",
            location_id=location.id,
        )
        db.add(camera)
        db.flush()

        ppe_payload = _payload("PPE_VIOLATION", evidence_path, camera.id)
        ppe, ppe_created = persist_incident(db, ppe_payload, commit=False)
        zone_payload = _payload("RESTRICTED_ZONE_VIOLATION", evidence_path, camera.id)
        zone, zone_created = persist_incident(db, zone_payload, commit=False)
        duplicate, duplicate_created = persist_incident(db, ppe_payload, commit=False)
        assert ppe_created and zone_created and not duplicate_created
        assert duplicate.id == ppe.id
        assert ppe.missing_items == ["helmet", "gloves"]
        assert zone.zone_id == "zone_1" and zone.missing_items == []
        assert ppe.camera_id == camera.id and zone.location_id == location.id
        json.dumps({
            "ppe": ppe_payload,
            "zone": zone_payload,
        })
        print("PostgreSQL transaction test passed (all test rows rolled back).")
    finally:
        db.rollback()
        db.close()
        if evidence_directory.exists() and evidence_directory.parent == EVIDENCE_ROOT:
            shutil.rmtree(evidence_directory)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--postgres",
        action="store_true",
        help="Also test the configured PostgreSQL database inside a rollback-only transaction.",
    )
    args = parser.parse_args()
    run_isolated_tests()
    if args.postgres:
        run_postgres_transaction_test()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
