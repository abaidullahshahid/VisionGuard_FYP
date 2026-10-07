"""Read-only final release checks for the configured VisionGuard database."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import inspect

from database import SessionLocal, engine
import models
from services.incident_service import resolve_evidence_file


EXPECTED_TABLES = {
    "users",
    "locations",
    "cameras",
    "safety_rules",
    "incidents",
    "corrective_actions",
    "safety_instructions",
    "acknowledgements",
    "worker_locations",
    "compliance_records",
    "restricted_zones",
}
EXPECTED_INCIDENT_COLUMNS = {
    "incident_uuid",
    "camera_id",
    "camera_identifier",
    "location_id",
    "violation_type",
    "track_id",
    "stream_time_seconds",
    "severity_level",
    "missing_items",
    "zone_id",
    "zone_name",
    "evidence_path",
    "metadata",
    "status",
    "officer_notes",
    "detected_at",
    "created_at",
    "updated_at",
}


def run_release_audit() -> dict:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    missing_tables = sorted(EXPECTED_TABLES - tables)
    if missing_tables:
        raise AssertionError(f"Missing database tables: {', '.join(missing_tables)}")

    incident_columns = {column["name"] for column in inspector.get_columns("incidents")}
    missing_columns = sorted(EXPECTED_INCIDENT_COLUMNS - incident_columns)
    if missing_columns:
        raise AssertionError(f"Missing incident columns: {', '.join(missing_columns)}")

    incident_indexes = inspector.get_indexes("incidents")
    uuid_index = next(
        (
            index
            for index in incident_indexes
            if index.get("unique") and index.get("column_names") == ["incident_uuid"]
        ),
        None,
    )
    if uuid_index is None:
        raise AssertionError("incidents.incident_uuid does not have a unique index")

    acknowledgement_indexes = inspector.get_indexes("acknowledgements")
    acknowledgement_unique_index = next(
        (
            index
            for index in acknowledgement_indexes
            if index.get("unique")
            and index.get("column_names") == ["instruction_id", "worker_id"]
        ),
        None,
    )
    if acknowledgement_unique_index is None:
        raise AssertionError("acknowledgements is missing its instruction/worker unique index")

    db = SessionLocal()
    try:
        users = db.query(models.User).all()
        locations = db.query(models.Location).all()
        cameras = db.query(models.Camera).all()
        incidents = db.query(models.Incident).all()
        actions = db.query(models.CorrectiveAction).all()
        assignments = db.query(models.WorkerLocation).all()
        acknowledgements = db.query(models.Acknowledgement).all()

        for camera in cameras:
            if camera.location is None:
                raise AssertionError(f"Camera {camera.id} has no valid location")
        for incident in incidents:
            if incident.camera_id is not None and incident.camera is None:
                raise AssertionError(f"Incident {incident.id} has an invalid camera reference")
            if incident.location_id is not None and incident.location_rel is None:
                raise AssertionError(f"Incident {incident.id} has an invalid location reference")
            if incident.status not in {"open", "in_progress", "resolved"}:
                raise AssertionError(f"Incident {incident.id} has invalid status {incident.status!r}")
            if not isinstance(incident.missing_items, list):
                raise AssertionError(f"Incident {incident.id} missing_items is not a JSON list")
            if not isinstance(incident.incident_metadata, dict):
                raise AssertionError(f"Incident {incident.id} metadata is not a JSON object")
            if incident.incident_uuid and str(incident.severity_level).upper() not in {
                "LOW",
                "MEDIUM",
                "HIGH",
            }:
                raise AssertionError(f"AI incident {incident.id} has invalid severity")
            if incident.evidence_path:
                if Path(incident.evidence_path).is_absolute():
                    raise AssertionError(f"Incident {incident.id} stores an absolute evidence path")
                resolve_evidence_file(incident.evidence_path)

        uuids = [incident.incident_uuid for incident in incidents if incident.incident_uuid]
        if len(uuids) != len(set(uuids)):
            raise AssertionError("Duplicate non-null incident UUIDs were found")

        for action in actions:
            if action.incident is None or action.assigned_user is None:
                raise AssertionError(f"Corrective action {action.id} has an orphan relationship")
            if action.status not in {"Pending", "In Progress", "Resolved"}:
                raise AssertionError(f"Corrective action {action.id} has invalid status")
        for assignment in assignments:
            if assignment.worker is None or assignment.location is None:
                raise AssertionError(f"Worker assignment {assignment.id} has an orphan relationship")
        acknowledgement_keys = []
        for acknowledgement in acknowledgements:
            if acknowledgement.worker is None or acknowledgement.instruction is None:
                raise AssertionError(f"Acknowledgement {acknowledgement.id} has an orphan relationship")
            acknowledgement_keys.append(
                (acknowledgement.instruction_id, acknowledgement.worker_id)
            )
        if len(acknowledgement_keys) != len(set(acknowledgement_keys)):
            raise AssertionError("Duplicate worker/instruction acknowledgements were found")

        summary = {
            "tables": len(tables),
            "users": len(users),
            "locations": len(locations),
            "cameras": len(cameras),
            "incidents": len(incidents),
            "ai_incidents": len(uuids),
            "corrective_actions": len(actions),
            "worker_assignments": len(assignments),
            "acknowledgements": len(acknowledgements),
            "evidence_files_verified": sum(bool(item.evidence_path) for item in incidents),
            "uuid_unique_index": uuid_index["name"],
            "acknowledgement_unique_index": acknowledgement_unique_index["name"],
        }
        print("Read-only PostgreSQL release audit passed:")
        print(json.dumps(summary, indent=2))
        return summary
    finally:
        db.close()


if __name__ == "__main__":
    run_release_audit()
