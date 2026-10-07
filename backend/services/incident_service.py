"""Persistence bridge between JSON-safe AI incidents and SQLAlchemy."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence, Tuple, Union
from uuid import UUID

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from database import SessionLocal
import models


logger = logging.getLogger(__name__)
BACKEND_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = (BACKEND_ROOT / "ai_module" / "evidence").resolve()
ALLOWED_INCIDENT_TYPES = {"PPE_VIOLATION", "RESTRICTED_ZONE_VIOLATION"}
ALLOWED_SEVERITIES = {"LOW", "MEDIUM", "HIGH"}
SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


class IncidentPersistenceError(RuntimeError):
    """Raised when an AI incident cannot be safely persisted."""


class EvidenceReferenceError(ValueError):
    """Raised for evidence references outside VisionGuard's evidence root."""


def _json_copy(value: object, field_name: str) -> object:
    try:
        return json.loads(json.dumps(value))
    except (TypeError, ValueError) as exc:
        raise IncidentPersistenceError(f"{field_name} must be JSON serializable") from exc


def _parse_timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise IncidentPersistenceError("Incident timestamp is invalid") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_evidence_reference(value: Optional[Union[str, Path]]) -> Optional[str]:
    """Return a backend-relative evidence path after enforcing its root."""

    if value is None or not str(value).strip():
        return None
    supplied = Path(str(value).strip()).expanduser()
    if supplied.is_absolute():
        candidate = supplied.resolve()
    else:
        backend_candidate = (BACKEND_ROOT / supplied).resolve()
        evidence_candidate = (EVIDENCE_ROOT / supplied).resolve()
        candidate = (
            backend_candidate
            if backend_candidate == EVIDENCE_ROOT
            or EVIDENCE_ROOT in backend_candidate.parents
            else evidence_candidate
        )
    try:
        candidate.relative_to(EVIDENCE_ROOT)
    except ValueError as exc:
        raise EvidenceReferenceError("Evidence path is outside ai_module/evidence") from exc
    if candidate.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        raise EvidenceReferenceError("Evidence file must be a JPEG or PNG image")
    return candidate.relative_to(BACKEND_ROOT).as_posix()


def resolve_evidence_file(reference: Optional[str]) -> Path:
    """Resolve an existing evidence image without permitting path traversal."""

    normalized = normalize_evidence_reference(reference)
    if normalized is None:
        raise EvidenceReferenceError("Incident has no evidence image")
    path = (BACKEND_ROOT / normalized).resolve()
    if not path.is_file():
        raise EvidenceReferenceError("Evidence image was not found")
    return path


def delete_incidents(db: Session, incidents: Sequence[models.Incident]) -> int:
    """Delete incidents with their corrective actions, alerts and evidence images.

    Commits, then refreshes the compliance records of the affected days so
    their violation counts stay correct.
    """

    from types import SimpleNamespace

    from services import compliance_service

    touched = []
    evidence_files = []
    for incident in incidents:
        touched.append(SimpleNamespace(location_id=incident.location_id, detected_at=incident.detected_at))
        if incident.evidence_path:
            try:
                evidence_files.append(resolve_evidence_file(incident.evidence_path))
            except EvidenceReferenceError:
                pass
        db.query(models.CorrectiveAction).filter(
            models.CorrectiveAction.incident_id == incident.id
        ).delete(synchronize_session=False)
        db.query(models.Notification).filter(
            models.Notification.link == f"/officer/incidents?incident={incident.id}"
        ).delete(synchronize_session=False)
        db.query(models.EmailAlertLog).filter(
            models.EmailAlertLog.incident_id == incident.id
        ).update({models.EmailAlertLog.incident_id: None}, synchronize_session=False)
        db.delete(incident)
    db.commit()
    for path in evidence_files:
        try:
            path.unlink()
        except OSError:
            logger.warning("Could not remove evidence image %s", path)
    compliance_service.refresh_for_incidents(db, touched)
    return len(touched)


def rule_severity(
    db: Session,
    location_id: Optional[int],
    incident_type: str,
    missing_items,
    zone_id: Optional[str],
) -> Optional[str]:
    """Severity chosen by the Admin in Safety Rules for this violation, if any.

    PPE: the highest severity among the location's rules that require one of
    the missing items.  Restricted location: its restricted rule's severity.
    Drawn zones and locations without a matching rule keep the AI default.
    """

    if location_id is None:
        return None
    from services.ppe_rule_service import PPE_RULE_ITEMS
    from services.restricted_zone_service import LOCATION_ZONE_PREFIX

    rules = db.query(models.SafetyRule).filter(models.SafetyRule.location_id == location_id).all()
    if incident_type == "RESTRICTED_ZONE_VIOLATION":
        if not str(zone_id or "").startswith(LOCATION_ZONE_PREFIX):
            return None
        values = [rule.severity_level for rule in rules if rule.is_restricted_area]
    else:
        missing = {str(item) for item in missing_items}
        values = [
            rule.severity_level
            for rule in rules
            if not rule.is_restricted_area and PPE_RULE_ITEMS.get(str(rule.ppe_type or ""), frozenset()) & missing
        ]
    ranked = [str(value).upper() for value in values if value and str(value).upper() in SEVERITY_RANK]
    return max(ranked, key=SEVERITY_RANK.get) if ranked else None


def _resolve_camera(
    db: Session,
    payload_camera_id: object,
    camera_db_id: Optional[int],
) -> Tuple[Optional[models.Camera], Optional[str]]:
    raw_identifier = None
    candidate_id = camera_db_id
    if payload_camera_id is not None:
        raw_identifier = str(payload_camera_id).strip() or None
        if candidate_id is None and raw_identifier and raw_identifier.isdigit():
            candidate_id = int(raw_identifier)
    if candidate_id is None:
        return None, raw_identifier
    camera = db.get(models.Camera, int(candidate_id))
    if camera is None:
        raise IncidentPersistenceError(f"Camera {candidate_id} does not exist")
    return camera, raw_identifier or str(camera.id)


def persist_incident(
    db: Session,
    incident: Mapping[str, object],
    *,
    camera_db_id: Optional[int] = None,
    commit: bool = True,
) -> Tuple[models.Incident, bool]:
    """Persist one IncidentManager payload and return ``(record, created)``.

    Re-submitting the same AI UUID is an idempotent no-op.  ``track_id`` is
    stored only as temporary tracking data and is never mapped to a user.
    """

    payload = dict(incident)
    incident_uuid = str(payload.get("incident_id", "")).strip()
    try:
        UUID(incident_uuid)
    except (TypeError, ValueError) as exc:
        raise IncidentPersistenceError("incident_id must be a valid UUID") from exc

    existing = (
        db.query(models.Incident)
        .filter(models.Incident.incident_uuid == incident_uuid)
        .first()
    )
    if existing is not None:
        return existing, False

    incident_type = str(payload.get("incident_type", "")).strip().upper()
    if incident_type not in ALLOWED_INCIDENT_TYPES:
        raise IncidentPersistenceError(f"Unsupported incident_type: {incident_type or '(empty)'}")
    severity = str(payload.get("severity", "")).strip().upper()
    if severity not in ALLOWED_SEVERITIES:
        raise IncidentPersistenceError(f"Unsupported severity: {severity or '(empty)'}")

    try:
        track_id = int(payload["track_id"])
        stream_time = float(payload["stream_time_seconds"])
    except (KeyError, TypeError, ValueError) as exc:
        raise IncidentPersistenceError("track_id and stream_time_seconds are required") from exc

    missing_items_value = _json_copy(payload.get("missing_items", []), "missing_items")
    if not isinstance(missing_items_value, list) or not all(
        isinstance(item, str) for item in missing_items_value
    ):
        raise IncidentPersistenceError("missing_items must be a JSON list of strings")
    metadata_value = _json_copy(payload.get("metadata", {}), "metadata")
    if not isinstance(metadata_value, dict):
        raise IncidentPersistenceError("metadata must be a JSON object")

    if incident_type == "PPE_VIOLATION" and not missing_items_value:
        raise IncidentPersistenceError("PPE incidents require missing_items")
    if incident_type == "RESTRICTED_ZONE_VIOLATION" and not payload.get("zone_id"):
        raise IncidentPersistenceError("Restricted-zone incidents require zone_id")

    try:
        camera, camera_identifier = _resolve_camera(
            db,
            payload.get("camera_id"),
            camera_db_id,
        )
        evidence_reference = normalize_evidence_reference(payload.get("evidence_path"))
        configured = rule_severity(
            db,
            camera.location_id if camera else None,
            incident_type,
            missing_items_value,
            payload.get("zone_id"),
        )
        if configured is not None and configured != severity:
            metadata_value["default_severity"] = severity
            metadata_value["severity_source"] = "safety_rule"
            severity = configured
        record = models.Incident(
            incident_uuid=incident_uuid,
            camera_id=camera.id if camera else None,
            camera_identifier=camera_identifier,
            location_id=camera.location_id if camera else None,
            violation_type=incident_type,
            track_id=track_id,
            stream_time_seconds=stream_time,
            severity_level=severity,
            missing_items=missing_items_value,
            zone_id=str(payload["zone_id"]) if payload.get("zone_id") is not None else None,
            zone_name=str(payload["zone_name"]) if payload.get("zone_name") is not None else None,
            evidence_path=evidence_reference,
            incident_metadata=metadata_value,
            status="open",
            detected_at=_parse_timestamp(payload.get("timestamp")),
        )
        db.add(record)
        db.flush()
        if evidence_reference:
            record.snapshot_url = f"/officer/incidents/{record.id}/evidence"
        # UC-09: alert officers and the location's workers with the incident.
        from services.notification_service import notify_new_incident

        notify_new_incident(db, record)
        if commit:
            db.commit()
            db.refresh(record)
            # Keep the day's compliance record current and email the alert.
            from services import alert_email_service, compliance_service

            compliance_service.refresh_for_incidents(db, [record])
            alert_email_service.queue_incident_alert(db, record.id)
        else:
            db.flush()
        return record, True
    except IntegrityError as exc:
        db.rollback()
        duplicate = (
            db.query(models.Incident)
            .filter(models.Incident.incident_uuid == incident_uuid)
            .first()
        )
        if duplicate is not None:
            return duplicate, False
        raise IncidentPersistenceError("Database integrity error while saving incident") from exc
    except (EvidenceReferenceError, IncidentPersistenceError):
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise IncidentPersistenceError("Database error while saving incident") from exc


class DatabaseIncidentSink:
    """Failure-isolated callback suitable for ``RealtimePPEPipeline``."""

    def __init__(
        self,
        camera_db_id: Optional[int] = None,
        session_factory: Callable[[], Session] = SessionLocal,
    ) -> None:
        self.camera_db_id = camera_db_id
        self.session_factory = session_factory

    def __call__(self, incident: Mapping[str, object]) -> Optional[models.Incident]:
        db = self.session_factory()
        try:
            record, created = persist_incident(
                db,
                incident,
                camera_db_id=self.camera_db_id,
            )
            if created:
                logger.info(
                    "Persisted incident %s as database row %s",
                    record.incident_uuid,
                    record.id,
                )
            return record
        except Exception:
            db.rollback()
            logger.exception(
                "Could not persist AI incident %s; inference will continue",
                incident.get("incident_id"),
            )
            return None
        finally:
            db.close()
