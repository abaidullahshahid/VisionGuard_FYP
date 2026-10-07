import datetime
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse, Response, StreamingResponse
import jwt
from starlette.concurrency import run_in_threadpool
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from database import get_db
import models
import schemas
from routers.auth import ALGORITHM, SECRET_KEY, decode_token
from services.incident_service import EvidenceReferenceError, delete_incidents, resolve_evidence_file
from services.restricted_zone_service import enabled_zone_records
from services.action_service import sync_incident_status
from services import alert_email_service, compliance_service
from services.instruction_service import ensure_rule_instructions
from services.notification_service import (
    notify_action_assigned,
    notify_action_updated,
    notify_instruction_published,
    notify_new_incident,
)
from services.ai_monitor import CameraMonitor, monitor_manager
from services.camera_stream import CameraStreamError


router = APIRouter(prefix="/officer", tags=["officer"])
INCIDENT_STATUSES = {"open", "in_progress", "resolved"}
ACTION_STATUSES = {"Pending", "In Progress", "Resolved"}
ACTION_PRIORITIES = {"Low", "Medium", "High", "Critical"}


def require_officer(authorization: str = Header(...)):
    token = authorization.replace("Bearer ", "")
    payload = decode_token(token)
    if payload.get("role") not in ("officer", "admin"):
        raise HTTPException(status_code=403, detail="Officer access required")
    return payload


def _incident_payload(incident: models.Incident, include_actions: bool = False):
    """Expose new AI fields while retaining the existing frontend contract."""

    evidence_url = (
        f"/officer/incidents/{incident.id}/evidence"
        if incident.evidence_path
        else None
    )
    signed_snapshot_url = None
    if evidence_url:
        evidence_token = jwt.encode(
            {
                "purpose": "incident_evidence",
                "incident_id": incident.id,
                "exp": datetime.datetime.now(datetime.timezone.utc)
                + datetime.timedelta(minutes=10),
            },
            SECRET_KEY,
            algorithm=ALGORITHM,
        )
        signed_snapshot_url = f"{evidence_url}?access_token={evidence_token}"
    severity = incident.severity_level or "Medium"
    legacy_severity = severity.title() if severity.upper() in {"LOW", "MEDIUM", "HIGH", "CRITICAL"} else severity
    result = {
        "id": incident.id,
        "violation_type": incident.violation_type,
        "severity_level": legacy_severity,
        "status": incident.status,
        "location": incident.location_rel.name if incident.location_rel else "Unknown",
        "camera_id": incident.camera_id,
        "location_id": incident.location_id,
        "snapshot_url": signed_snapshot_url or incident.snapshot_url,
        "detected_at": incident.detected_at,
        "incident_id": incident.incident_uuid,
        "incident_type": incident.violation_type,
        "track_id": incident.track_id,
        "timestamp": incident.detected_at,
        "stream_time_seconds": incident.stream_time_seconds,
        "severity": severity,
        "camera_identifier": incident.camera_identifier,
        "missing_items": incident.missing_items or [],
        "zone_id": incident.zone_id,
        "zone_name": incident.zone_name,
        "metadata": incident.incident_metadata or {},
        "officer_notes": incident.officer_notes,
        "evidence_url": evidence_url,
        "created_at": incident.created_at,
        "updated_at": incident.updated_at,
    }
    if include_actions:
        result["corrective_actions"] = incident.corrective_actions
    return result


def _find_incident(db: Session, identifier: str) -> Optional[models.Incident]:
    """Resolve either the legacy integer key or the standardized AI UUID."""

    if identifier.isdigit():
        return db.get(models.Incident, int(identifier))
    return db.query(models.Incident).filter(
        models.Incident.incident_uuid == identifier
    ).first()


# -- Stats -----------------------------------------------------------------
@router.get("/stats", response_model=schemas.OfficerStats)
def get_stats(db: Session = Depends(get_db), payload=Depends(require_officer)):
    today = datetime.datetime.utcnow().date()
    total_incidents = db.query(models.Incident).count()
    pending_actions = db.query(models.CorrectiveAction).filter(
        models.CorrectiveAction.status.in_(["Pending", "In Progress"])
    ).count()
    resolved_today = db.query(models.CorrectiveAction).filter(
        models.CorrectiveAction.status == "Resolved",
        func.date(models.CorrectiveAction.created_at) == today,
    ).count()
    active_alerts = db.query(models.Incident).filter(
        models.Incident.status == "open"
    ).count()
    return {
        "totalIncidents": total_incidents,
        "pendingActions": pending_actions,
        "resolvedToday": resolved_today,
        "activeAlerts": active_alerts,
    }


# -- Incidents -------------------------------------------------------------
@router.get("/incidents", response_model=List[schemas.IncidentResponse])
def list_incidents(
    status: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    incident_type: Optional[str] = Query(None),
    camera: Optional[str] = Query(None),
    date_from: Optional[datetime.datetime] = Query(None),
    date_to: Optional[datetime.datetime] = Query(None),
    limit: Optional[int] = Query(None, ge=1, le=500),
    db: Session = Depends(get_db),
    payload=Depends(require_officer),
):
    query = db.query(models.Incident).order_by(models.Incident.detected_at.desc())
    if status:
        query = query.filter(func.lower(models.Incident.status) == status.lower())
    if severity:
        query = query.filter(func.lower(models.Incident.severity_level) == severity.lower())
    if incident_type:
        query = query.filter(
            func.upper(models.Incident.violation_type) == incident_type.upper()
        )
    if camera:
        camera_filters = [models.Incident.camera_identifier == camera]
        if camera.isdigit():
            camera_filters.append(models.Incident.camera_id == int(camera))
        query = query.filter(or_(*camera_filters))
    if date_from:
        query = query.filter(models.Incident.detected_at >= date_from)
    if date_to:
        query = query.filter(models.Incident.detected_at <= date_to)
    if location:
        query = query.outerjoin(models.Location).filter(
            func.lower(models.Location.name).contains(location.lower())
        )
    if limit:
        query = query.limit(limit)
    return [_incident_payload(incident) for incident in query.all()]


@router.get("/incidents/{incident_identifier}", response_model=schemas.IncidentDetailResponse)
def get_incident(
    incident_identifier: str,
    db: Session = Depends(get_db),
    payload=Depends(require_officer),
):
    incident = _find_incident(db, incident_identifier)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return _incident_payload(incident, include_actions=True)


@router.get("/incidents/{incident_identifier}/evidence")
def get_incident_evidence(
    incident_identifier: str,
    authorization: Optional[str] = Header(None),
    access_token: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    if authorization:
        require_officer(authorization)
    elif access_token:
        token_payload = decode_token(access_token)
        if (
            token_payload.get("purpose") != "incident_evidence"
            or str(token_payload.get("incident_id")) != incident_identifier
        ):
            raise HTTPException(status_code=403, detail="Invalid evidence token")
    else:
        raise HTTPException(status_code=401, detail="Evidence authorization required")
    incident = _find_incident(db, incident_identifier)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    try:
        path = resolve_evidence_file(incident.evidence_path)
    except EvidenceReferenceError:
        raise HTTPException(status_code=404, detail="Evidence image not found")
    media_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return FileResponse(path, media_type=media_type, filename=path.name)


@router.post("/incidents", response_model=schemas.IncidentResponse, status_code=201)
def create_incident(
    body: schemas.IncidentCreate,
    db: Session = Depends(get_db),
    payload=Depends(require_officer),
):
    camera = db.get(models.Camera, body.camera_id) if body.camera_id is not None else None
    if body.camera_id is not None and camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    incident_uuid = body.incident_id or str(uuid4())
    try:
        UUID(incident_uuid)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="incident_id must be a valid UUID")
    incident = models.Incident(
        incident_uuid=incident_uuid,
        camera_id=body.camera_id,
        camera_identifier=body.camera_identifier,
        location_id=camera.location_id if camera else body.location_id,
        violation_type=body.violation_type,
        severity_level=body.severity_level,
        track_id=body.track_id,
        stream_time_seconds=body.stream_time_seconds,
        missing_items=body.missing_items,
        zone_id=body.zone_id,
        zone_name=body.zone_name,
        incident_metadata=body.metadata,
        officer_notes=body.officer_notes,
        snapshot_url=body.snapshot_url,
        status="open",
    )
    try:
        db.add(incident)
        db.flush()
        notify_new_incident(db, incident)
        db.commit()
        db.refresh(incident)
    except Exception:
        db.rollback()
        raise
    compliance_service.refresh_for_incidents(db, [incident])
    alert_email_service.queue_incident_alert(db, incident.id)
    return _incident_payload(incident)


@router.patch("/incidents/{incident_identifier}", response_model=schemas.IncidentResponse)
def update_incident(
    incident_identifier: str,
    body: schemas.IncidentUpdate,
    db: Session = Depends(get_db),
    payload=Depends(require_officer),
):
    incident = _find_incident(db, incident_identifier)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    if body.status is not None:
        normalized_status = body.status.strip().lower()
        if normalized_status not in INCIDENT_STATUSES:
            raise HTTPException(
                status_code=422,
                detail="status must be open, in_progress, or resolved",
            )
        incident.status = normalized_status
    if "officer_notes" in body.model_fields_set:
        incident.officer_notes = body.officer_notes
    try:
        db.commit()
        db.refresh(incident)
    except Exception:
        db.rollback()
        raise
    if body.status is not None:
        compliance_service.refresh_for_incidents(db, [incident])
    return _incident_payload(incident)


@router.delete("/incidents/{incident_identifier}")
def delete_incident(
    incident_identifier: str,
    db: Session = Depends(get_db),
    payload=Depends(require_officer),
):
    incident = _find_incident(db, incident_identifier)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    label = f"Incident #{incident.id}"
    delete_incidents(db, [incident])
    return {"deleted": 1, "detail": f"{label} was deleted with its corrective actions and snapshot."}


@router.post("/incidents/delete")
def delete_many_incidents(
    body: schemas.IncidentBulkDelete,
    db: Session = Depends(get_db),
    payload=Depends(require_officer),
):
    """Delete the listed incidents, or every incident when ``all`` is true."""

    query = db.query(models.Incident)
    if not body.all:
        if not body.ids:
            raise HTTPException(status_code=422, detail="Choose incidents to delete")
        query = query.filter(models.Incident.id.in_(body.ids))
    incidents = query.all()
    count = delete_incidents(db, incidents)
    return {
        "deleted": count,
        "detail": f"Deleted {count} incident{'' if count == 1 else 's'} with their corrective actions and snapshots.",
    }


# -- Corrective Actions ----------------------------------------------------
@router.get("/corrective-actions", response_model=List[schemas.CorrectiveActionOut])
def list_actions(db: Session = Depends(get_db), payload=Depends(require_officer)):
    return db.query(models.CorrectiveAction).order_by(
        models.CorrectiveAction.created_at.desc()
    ).all()


@router.post("/corrective-actions", response_model=schemas.CorrectiveActionOut, status_code=201)
def create_action(
    body: schemas.CorrectiveActionCreate,
    db: Session = Depends(get_db),
    payload=Depends(require_officer),
):
    incident = db.get(models.Incident, body.incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    assignee = db.get(models.User, body.assigned_to)
    if assignee is None:
        raise HTTPException(status_code=404, detail="Assigned user not found")
    if assignee.status != "active":
        raise HTTPException(status_code=400, detail="Assigned user must be active")
    if body.priority not in ACTION_PRIORITIES:
        raise HTTPException(status_code=422, detail="Unsupported corrective-action priority")
    action = models.CorrectiveAction(
        incident_id=body.incident_id,
        assigned_to=body.assigned_to,
        description=body.description,
        priority=body.priority,
        deadline=body.deadline,
        status="Pending",
    )
    db.add(action)
    db.flush()
    sync_incident_status(db, incident)
    notify_action_assigned(db, action, incident)
    db.commit()
    compliance_service.refresh_for_incidents(db, [incident])
    db.refresh(action)
    return action


@router.patch("/corrective-actions/{action_id}", response_model=schemas.CorrectiveActionOut)
def update_action(
    action_id: int,
    body: schemas.CorrectiveActionUpdate,
    db: Session = Depends(get_db),
    payload=Depends(require_officer),
):
    action = db.get(models.CorrectiveAction, action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Action not found")
    reassigned = False
    if body.assigned_to is not None and body.assigned_to != action.assigned_to:
        assignee = db.get(models.User, body.assigned_to)
        if assignee is None:
            raise HTTPException(status_code=404, detail="Assigned user not found")
        if assignee.status != "active":
            raise HTTPException(status_code=400, detail="Assigned user must be active")
        action.assigned_to = assignee.id
        action.former_assignee = None
        reassigned = True
    if body.status is not None:
        if body.status not in ACTION_STATUSES:
            raise HTTPException(status_code=422, detail="Unsupported corrective-action status")
        action.status = body.status
    if body.description is not None:
        action.description = body.description
    if body.priority is not None:
        if body.priority not in ACTION_PRIORITIES:
            raise HTTPException(status_code=422, detail="Unsupported corrective-action priority")
        action.priority = body.priority
    if "deadline" in body.model_fields_set:
        action.deadline = body.deadline
    sync_incident_status(db, action.incident)
    db.flush()
    if reassigned:
        notify_action_assigned(db, action, action.incident)
    else:
        notify_action_updated(db, action, int(payload.get("sub", 0)), payload.get("role", "officer"))
    db.commit()
    compliance_service.refresh_for_incidents(db, [action.incident])
    db.refresh(action)
    return action


# -- Cameras, locations, alerts -------------------------------------------
@router.get("/assignees", response_model=List[schemas.UserOut])
def list_assignees(db: Session = Depends(get_db), payload=Depends(require_officer)):
    """Return active users available for corrective-action assignment."""

    return db.query(models.User).filter(
        models.User.status == "active"
    ).order_by(models.User.name.asc()).all()


@router.get("/cameras", response_model=List[schemas.CameraOut])
def list_cameras(db: Session = Depends(get_db), payload=Depends(require_officer)):
    return db.query(models.Camera).filter(models.Camera.status == "active").all()


def _get_stream_camera(db: Session, camera_id: int) -> models.Camera:
    camera = db.get(models.Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    if str(camera.status).lower() != "active":
        raise HTTPException(status_code=409, detail="Camera is offline")
    if not str(camera.stream_url or "").strip():
        raise HTTPException(status_code=503, detail="Camera has no configured stream source")
    return camera


def _authorize_stream_request(
    camera_id: int,
    authorization: Optional[str],
    access_token: Optional[str],
) -> None:
    if authorization:
        require_officer(authorization)
        return
    if not access_token:
        raise HTTPException(status_code=401, detail="Camera stream authorization required")
    token_payload = decode_token(access_token)
    if (
        token_payload.get("purpose") != "camera_stream"
        or str(token_payload.get("camera_id")) != str(camera_id)
    ):
        raise HTTPException(status_code=403, detail="Invalid camera stream token")


@router.get("/cameras/{camera_id}/stream-url")
def get_camera_stream_url(
    camera_id: int,
    db: Session = Depends(get_db),
    payload=Depends(require_officer),
):
    camera = _get_stream_camera(db, camera_id)
    try:
        monitor_manager.ensure_source_available(camera.stream_url)
    except CameraStreamError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=5)
    stream_token = jwt.encode(
        {
            "purpose": "camera_stream",
            "camera_id": camera.id,
            "exp": expires_at,
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )
    return {
        "camera_id": camera.id,
        "stream_url": f"/officer/cameras/{camera.id}/stream?access_token={stream_token}",
        "expires_at": expires_at,
    }


@router.get("/cameras/{camera_id}/stream")
def stream_camera(
    camera_id: int,
    authorization: Optional[str] = Header(None),
    access_token: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """AI-annotated MJPEG: monitoring runs while at least one viewer is connected."""
    _authorize_stream_request(camera_id, authorization, access_token)
    camera = _get_stream_camera(db, camera_id)
    try:
        monitor_manager.ensure_source_available(camera.stream_url)
    except CameraStreamError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    monitor = monitor_manager.attach_viewer(camera.id, camera.stream_url)

    return StreamingResponse(
        _monitor_mjpeg(monitor),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
        },
    )


async def _monitor_mjpeg(monitor: CameraMonitor):
    # Async so a client disconnect cancels the wait and releases the viewer.
    seq = 0
    try:
        while True:
            item = await run_in_threadpool(monitor.wait_jpeg, seq, 1.0)
            if item is None:
                if monitor.finished:
                    break
                continue
            seq, jpeg = item
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Cache-Control: no-cache\r\n\r\n"
                + jpeg
                + b"\r\n"
            )
    finally:
        monitor.remove_viewer()


@router.get("/cameras/{camera_id}/ai-status")
def get_camera_ai_status(
    camera_id: int,
    db: Session = Depends(get_db),
    payload=Depends(require_officer),
):
    """Live AI state for the camera being watched (people, PPE, violations)."""
    if db.get(models.Camera, camera_id) is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    monitor = monitor_manager.get(camera_id)
    if monitor is None:
        return {"camera_id": camera_id, "state": "stopped", "error": None, "recent_events": [], "events_total": 0}
    return monitor.status()


@router.get("/cameras/{camera_id}/restricted-zones", response_model=List[schemas.RestrictedZoneOut])
def list_camera_restricted_zones(
    camera_id: int,
    db: Session = Depends(get_db),
    payload=Depends(require_officer),
):
    """Enabled zones only, for the read-only Live Video Feed overlay."""
    if db.get(models.Camera, camera_id) is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    return enabled_zone_records(db, camera_id)


@router.get("/locations", response_model=List[schemas.LocationOut])
def list_locations(db: Session = Depends(get_db), payload=Depends(require_officer)):
    return db.query(models.Location).all()


@router.get("/alerts")
def list_alerts(db: Session = Depends(get_db), payload=Depends(require_officer)):
    incidents = db.query(models.Incident).filter(
        models.Incident.status == "open",
        models.Incident.camera_id.isnot(None),
    ).order_by(models.Incident.detected_at.desc()).limit(20).all()
    return [
        {
            "id": incident.id,
            "type": incident.violation_type,
            "severity": (
                incident.severity_level.title()
                if incident.severity_level
                and incident.severity_level.upper() in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
                else incident.severity_level
            ),
            "timestamp": incident.detected_at,
        }
        for incident in incidents
    ]


# -- Safety instructions (UC-15) -------------------------------------------
INSTRUCTION_CATEGORIES = {"ppe", "procedures", "emergency", "hazards"}


def _instruction_payload(db: Session, instruction: models.SafetyInstruction) -> dict:
    worker_ids = {
        row[0]
        for row in db.query(models.WorkerLocation.worker_id)
        .filter(models.WorkerLocation.location_id == instruction.location_id)
        .all()
    }
    acknowledged_ids = {ack.worker_id for ack in instruction.acknowledgements}
    return {
        "id": instruction.id,
        "title": instruction.title,
        "content": instruction.content,
        "category": instruction.category,
        "location_id": instruction.location_id,
        "location": instruction.location.name if instruction.location else "Unknown",
        "source": "safety_rule" if instruction.safety_rule_id else "officer",
        "created_by": instruction.creator.name if instruction.creator else None,
        "created_at": instruction.created_at,
        "assigned_workers": len(worker_ids),
        "acknowledged_workers": len(acknowledged_ids & worker_ids),
    }


@router.get("/safety-instructions")
def list_safety_instructions(db: Session = Depends(get_db), payload=Depends(require_officer)):
    ensure_rule_instructions(db, [row[0] for row in db.query(models.Location.id).all()])
    instructions = db.query(models.SafetyInstruction).order_by(
        models.SafetyInstruction.created_at.desc()
    ).all()
    return [_instruction_payload(db, instruction) for instruction in instructions]


@router.post("/safety-instructions", status_code=201)
def publish_safety_instruction(
    body: schemas.SafetyInstructionCreate,
    db: Session = Depends(get_db),
    payload=Depends(require_officer),
):
    title = body.title.strip()
    content = body.content.strip()
    if not title or not content:
        raise HTTPException(status_code=422, detail="Title and instruction text are required")
    if body.category not in INSTRUCTION_CATEGORIES:
        raise HTTPException(status_code=422, detail="Unsupported instruction category")
    if db.get(models.Location, body.location_id) is None:
        raise HTTPException(status_code=404, detail="Location not found")
    instruction = models.SafetyInstruction(
        location_id=body.location_id,
        created_by=int(payload.get("sub", 0)) or None,
        title=title[:255],
        content=content,
        category=body.category,
    )
    db.add(instruction)
    db.flush()
    notify_instruction_published(db, instruction)
    db.commit()
    db.refresh(instruction)
    return _instruction_payload(db, instruction)


@router.delete("/safety-instructions/{instruction_id}")
def delete_safety_instruction(
    instruction_id: int,
    db: Session = Depends(get_db),
    payload=Depends(require_officer),
):
    instruction = db.get(models.SafetyInstruction, instruction_id)
    if instruction is None:
        raise HTTPException(status_code=404, detail="Safety instruction not found")
    if instruction.safety_rule_id is not None:
        raise HTTPException(
            status_code=409,
            detail="This instruction comes from a safety rule. Delete the rule in Safety Rules instead.",
        )
    db.delete(instruction)
    db.commit()
    return {"detail": "Safety instruction deleted"}


# -- Compliance records ---------------------------------------------------
def _parse_day(value: Optional[str], field: str) -> Optional[datetime.date]:
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{field} must be a date (YYYY-MM-DD)")


def _compliance_filters(status, location_id, date_from, date_to) -> dict:
    if status and status not in compliance_service.STATUSES:
        raise HTTPException(status_code=422, detail="status must be compliant, non-compliant, or pending")
    return {
        "status": status or None,
        "location_id": location_id,
        "date_from": _parse_day(date_from, "date_from"),
        "date_to": _parse_day(date_to, "date_to"),
    }


@router.get("/compliance-records")
def list_compliance(
    status: Optional[str] = None,
    location_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    payload=Depends(require_officer),
):
    filters = _compliance_filters(status, location_id, date_from, date_to)
    return [compliance_service.record_payload(record) for record in compliance_service.filtered_records(db, **filters)]


@router.get("/compliance-stats", response_model=schemas.ComplianceStats)
def compliance_stats(
    status: Optional[str] = None,
    location_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    payload=Depends(require_officer),
):
    filters = _compliance_filters(status, location_id, date_from, date_to)
    return compliance_service.stats(compliance_service.filtered_records(db, **filters))


@router.get("/compliance-records/export")
def export_compliance(
    status: Optional[str] = None,
    location_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    payload=Depends(require_officer),
):
    filters = _compliance_filters(status, location_id, date_from, date_to)
    records = compliance_service.filtered_records(db, **filters)
    filename = f"visionguard-compliance-{compliance_service.local_today().isoformat()}.csv"
    return Response(
        content=compliance_service.records_csv(records).encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/compliance-records/generate")
def generate_compliance(
    body: schemas.ComplianceGenerate,
    db: Session = Depends(get_db),
    payload=Depends(require_officer),
):
    day = body.date or compliance_service.local_today()
    if day > compliance_service.local_today():
        raise HTTPException(status_code=422, detail="Records cannot be generated for a future date")
    if body.location_id is not None and db.get(models.Location, body.location_id) is None:
        raise HTTPException(status_code=404, detail="Location not found")
    records = compliance_service.generate_for_day(db, day, body.location_id)
    db.commit()
    return {
        "date": day.isoformat(),
        "generated": len(records),
        "detail": (
            f"{len(records)} record(s) updated for {day.isoformat()}."
            if records else "No records: no location had cameras or incidents on this day."
        ),
    }


@router.patch("/compliance-records/{record_id}")
def review_compliance(
    record_id: int,
    body: schemas.ComplianceReview,
    db: Session = Depends(get_db),
    payload=Depends(require_officer),
):
    record = db.get(models.ComplianceRecord, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Compliance record not found")
    if body.status is not None and body.status not in (*compliance_service.STATUSES, "auto"):
        raise HTTPException(status_code=422, detail="status must be compliant, non-compliant, pending, or auto")
    compliance_service.review_record(
        db,
        record,
        int(payload.get("sub", 0)) or None,
        body.status,
        body.notes,
        "notes" in body.model_fields_set,
    )
    db.commit()
    db.refresh(record)
    return compliance_service.record_payload(record)
