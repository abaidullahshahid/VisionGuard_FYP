from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import Response
from sqlalchemy.orm import Session
from database import get_db
import models, schemas
from routers.auth import decode_token, hash_password
from services.ai_monitor import monitor_manager
from services.instruction_service import publish_rule_instruction
from services.notification_service import active_user_ids, notify
from services.camera_stream import CameraStreamError
from services.ppe_rule_service import ALL_PPE_ITEMS, NO_PPE, PPE_RULE_ITEMS
from services.restricted_zone_service import (
    ZoneConfigurationError,
    validate_polygon_points,
    validate_zone_name,
)
from typing import List, Optional

router = APIRouter(prefix="/admin", tags=["admin"])
USER_ROLES = {"admin", "officer", "worker"}
USER_STATUSES = {"active", "inactive"}
CAMERA_STATUSES = {"active", "inactive"}
RULE_SEVERITIES = {"Low", "Medium", "High", "Critical"}


def require_admin(authorization: str = Header(...)):
    token = authorization.replace("Bearer ", "")
    payload = decode_token(token)
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return payload


# ── Stats ─────────────────────────────────────────────────────────
@router.get("/stats", response_model=schemas.AdminStats)
def get_stats(db: Session = Depends(get_db), payload=Depends(require_admin)):
    return {
        "totalUsers":     db.query(models.User).count(),
        "totalCameras":   db.query(models.Camera).count(),
        "totalIncidents": db.query(models.Incident).count(),
        "totalLocations": db.query(models.Location).count(),
    }


# ── Users ─────────────────────────────────────────────────────────
@router.get("/users", response_model=List[schemas.UserOut])
def list_users(db: Session = Depends(get_db), payload=Depends(require_admin)):
    return db.query(models.User).order_by(models.User.created_at.desc()).all()


@router.post("/users", response_model=schemas.UserOut, status_code=201)
def create_user(body: schemas.UserCreate, db: Session = Depends(get_db), payload=Depends(require_admin)):
    email = body.email.strip().lower()
    role = body.role.strip().lower()
    if role not in USER_ROLES:
        raise HTTPException(status_code=422, detail="role must be admin, officer, or worker")
    if len(body.password) < 6:
        raise HTTPException(status_code=422, detail="Password must be at least 6 characters")
    # Admins manage the whole system, so they have no department; workers need one.
    department = (body.department or "").strip() or None
    if role == "admin":
        department = None
    elif role == "worker" and department is None:
        raise HTTPException(status_code=422, detail="Department is required for workers")
    existing = db.query(models.User).filter(models.User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = models.User(
        name     = body.name,
        email    = email,
        password = hash_password(body.password),
        department = department,
        role     = role,
        status   = "active",
    )
    db.add(user); db.commit(); db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=schemas.UserOut)
def update_user(user_id: int, body: schemas.UserUpdate, db: Session = Depends(get_db), payload=Depends(require_admin)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if body.status is not None:
        status_value = body.status.strip().lower()
        if status_value not in USER_STATUSES:
            raise HTTPException(status_code=422, detail="status must be active or inactive")
        user.status = status_value
    if body.role is not None:
        role_value = body.role.strip().lower()
        if role_value not in USER_ROLES:
            raise HTTPException(status_code=422, detail="role must be admin, officer, or worker")
        user.role = role_value
    if body.department is not None:
        user.department = body.department.strip() or None
    if user.role == "admin":
        user.department = None
    if body.password is not None:
        # Temporary password set by an admin after a forgot-password request.
        if len(body.password) < 6:
            raise HTTPException(status_code=422, detail="Password must be at least 6 characters")
        user.password = hash_password(body.password)
        notify(
            db, [user.id], kind="account",
            title="Your password was reset by an administrator",
            message="Change it from your profile (top-right avatar) after signing in.",
        )
    db.commit(); db.refresh(user)
    return user


@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), payload=Depends(require_admin)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == int(payload.get("sub", 0)):
        raise HTTPException(status_code=400, detail="You cannot delete your own account.")
    if user.role == "admin":
        other_admins = db.query(models.User).filter(
            models.User.role == "admin", models.User.status == "active", models.User.id != user.id,
        ).count()
        if other_admins == 0:
            raise HTTPException(status_code=409, detail="This is the only active admin. Add another admin first.")

    # Keep history: the user's corrective actions stay, showing their name;
    # unfinished ones become unassigned so an officer can reassign them.
    name = user.name
    actions = db.query(models.CorrectiveAction).filter(models.CorrectiveAction.assigned_to == user.id).all()
    reopened = []
    for action in actions:
        action.former_assignee = name
        action.assigned_to = None
        if action.status != "Resolved":
            reopened.append(action.id)
    db.query(models.WorkerLocation).filter(models.WorkerLocation.worker_id == user.id).delete(synchronize_session=False)
    db.query(models.Acknowledgement).filter(models.Acknowledgement.worker_id == user.id).delete(synchronize_session=False)
    db.query(models.SafetyInstruction).filter(models.SafetyInstruction.created_by == user.id).update(
        {models.SafetyInstruction.created_by: None}, synchronize_session=False)
    db.query(models.ComplianceRecord).filter(models.ComplianceRecord.officer_id == user.id).update(
        {models.ComplianceRecord.officer_id: None}, synchronize_session=False)
    db.query(models.AlertSettings).filter(models.AlertSettings.updated_by == user.id).update(
        {models.AlertSettings.updated_by: None}, synchronize_session=False)
    if reopened:
        plural = "s" if len(reopened) > 1 else ""
        notify(
            db, [uid for uid in active_user_ids(db, ["officer"]) if uid != user.id],
            kind="task_update",
            title=f"Corrective action{plural} {', '.join(f'#{i}' for i in reopened)} need{'' if plural else 's'} a new assignee",
            message=f"The account of {name} was deleted. Reassign the open task{plural} in Corrective Actions.",
            severity="MEDIUM",
            link="/officer/actions",
        )
    db.flush()
    db.expire(user)
    db.delete(user)
    db.commit()
    detail = f"{name} was deleted."
    if actions:
        detail += f" Their {len(actions)} corrective action(s) are kept in the history"
        detail += f"; {len(reopened)} open one(s) now need a new assignee in Corrective Actions." if reopened else "."
    return {"detail": detail, "unassigned_actions": reopened}


# ── Locations ─────────────────────────────────────────────────────
@router.get("/locations", response_model=List[schemas.LocationOut])
def list_locations(db: Session = Depends(get_db), payload=Depends(require_admin)):
    return db.query(models.Location).order_by(models.Location.created_at.desc()).all()


@router.post("/locations", response_model=schemas.LocationOut, status_code=201)
def create_location(body: schemas.LocationCreate, db: Session = Depends(get_db), payload=Depends(require_admin)):
    loc = models.Location(name=body.name, zone=body.zone, department=body.department)
    db.add(loc); db.commit(); db.refresh(loc)
    return loc


@router.delete("/locations/{location_id}")
def delete_location(location_id: int, db: Session = Depends(get_db), payload=Depends(require_admin)):
    loc = db.query(models.Location).filter(models.Location.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")
    if loc.cameras:
        count = len(loc.cameras)
        raise HTTPException(
            status_code=409,
            detail=f"{loc.name} still has {count} camera{'s' if count != 1 else ''}. Move or delete them in Cameras first.",
        )
    if loc.incidents:
        raise HTTPException(
            status_code=409,
            detail=f"{loc.name} has incident history, so it cannot be deleted (incident records must be kept).",
        )
    # Configuration that only belongs to this location goes with it.
    for rule in list(loc.safety_rules):
        db.delete(rule)
    for instruction in list(loc.safety_instructions):
        db.delete(instruction)
    for assignment in list(loc.worker_locations):
        db.delete(assignment)
    db.query(models.ComplianceRecord).filter(models.ComplianceRecord.location_id == loc.id).delete()
    db.delete(loc); db.commit()
    return {"detail": "Location deleted"}


# ── Cameras ───────────────────────────────────────────────────────
@router.get("/worker-locations")
def list_worker_locations(db: Session = Depends(get_db), payload=Depends(require_admin)):
    assignments = db.query(models.WorkerLocation).order_by(models.WorkerLocation.assigned_at.desc()).all()
    return [
        {
            "id": assignment.id,
            "worker_id": assignment.worker_id,
            "worker_name": assignment.worker.name if assignment.worker else "Unassigned",
            "worker_email": assignment.worker.email if assignment.worker else "",
            "worker_department": assignment.worker.department if assignment.worker else "",
            "location_id": assignment.location_id,
            "location_name": assignment.location.name if assignment.location else "Unknown",
            "assigned_at": assignment.assigned_at,
        }
        for assignment in assignments
    ]


@router.post("/worker-locations", response_model=schemas.WorkerLocationOut, status_code=201)
def assign_worker_location(body: schemas.WorkerLocationCreate, db: Session = Depends(get_db), payload=Depends(require_admin)):
    worker = db.query(models.User).filter(models.User.id == body.worker_id).first()
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    if worker.role != "worker":
        raise HTTPException(status_code=400, detail="Selected user is not a worker")
    if worker.status != "active":
        raise HTTPException(status_code=400, detail="Worker must be active")

    location = db.query(models.Location).filter(models.Location.id == body.location_id).first()
    if not location:
        raise HTTPException(status_code=404, detail="Location not found")

    existing = db.query(models.WorkerLocation).filter(
        models.WorkerLocation.worker_id == body.worker_id,
        models.WorkerLocation.location_id == body.location_id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Worker is already assigned to this location")

    assignment = models.WorkerLocation(worker_id=body.worker_id, location_id=body.location_id)
    db.add(assignment); db.commit(); db.refresh(assignment)
    return assignment


@router.delete("/worker-locations/{assignment_id}")
def delete_worker_location(assignment_id: int, db: Session = Depends(get_db), payload=Depends(require_admin)):
    assignment = db.query(models.WorkerLocation).filter(models.WorkerLocation.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    db.delete(assignment); db.commit()
    return {"detail": "Worker location assignment removed"}


@router.get("/cameras", response_model=List[schemas.CameraOut])
def list_cameras(db: Session = Depends(get_db), payload=Depends(require_admin)):
    return db.query(models.Camera).order_by(models.Camera.created_at.desc()).all()


@router.post("/cameras", response_model=schemas.CameraOut, status_code=201)
def create_camera(body: schemas.CameraCreate, db: Session = Depends(get_db), payload=Depends(require_admin)):
    loc = db.query(models.Location).filter(models.Location.id == body.location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")
    cam = models.Camera(
        name=body.name, type=body.type,
        stream_url=body.stream_url, location_id=body.location_id, status="active"
    )
    db.add(cam); db.commit(); db.refresh(cam)
    return cam


@router.patch("/cameras/{camera_id}", response_model=schemas.CameraOut)
def update_camera(camera_id: int, body: schemas.CameraUpdate, db: Session = Depends(get_db), payload=Depends(require_admin)):
    cam = db.query(models.Camera).filter(models.Camera.id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="Camera name is required")
        cam.name = name
    if body.type is not None:
        source_type = body.type.strip()
        if not source_type:
            raise HTTPException(status_code=422, detail="Source type is required")
        cam.type = source_type
    if body.stream_url is not None:
        stream_url = body.stream_url.strip()
        if not stream_url:
            raise HTTPException(status_code=422, detail="Stream URL is required")
        cam.stream_url = stream_url
    if body.location_id is not None:
        loc = db.query(models.Location).filter(models.Location.id == body.location_id).first()
        if not loc:
            raise HTTPException(status_code=404, detail="Location not found")
        cam.location_id = body.location_id
    if body.status is not None:
        status_value = body.status.strip().lower()
        if status_value not in CAMERA_STATUSES:
            raise HTTPException(status_code=422, detail="status must be active or inactive")
        cam.status = status_value
    db.commit(); db.refresh(cam)
    return cam


@router.delete("/cameras/{camera_id}")
def delete_camera(camera_id: int, db: Session = Depends(get_db), payload=Depends(require_admin)):
    cam = db.query(models.Camera).filter(models.Camera.id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    db.delete(cam); db.commit()
    return {"detail": "Camera deleted"}


@router.get("/cameras/{camera_id}/snapshot")
def get_camera_snapshot(camera_id: int, db: Session = Depends(get_db), payload=Depends(require_admin)):
    """Return one current JPEG frame for drawing restricted zones."""
    cam = db.query(models.Camera).filter(models.Camera.id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    if not str(cam.stream_url or "").strip():
        raise HTTPException(status_code=503, detail="Camera has no configured stream source")
    try:
        # Reuses the live frame when the AI monitor already has this source open.
        jpeg = monitor_manager.snapshot_jpeg(cam.stream_url)
    except CameraStreamError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return Response(content=jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


# ── Restricted Zones ──────────────────────────────────────────────
def _get_camera_or_404(db: Session, camera_id: int) -> models.Camera:
    cam = db.query(models.Camera).filter(models.Camera.id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    return cam


def _get_zone_or_404(db: Session, camera_id: int, zone_id: int) -> models.RestrictedZone:
    zone = db.query(models.RestrictedZone).filter(
        models.RestrictedZone.id == zone_id,
        models.RestrictedZone.camera_id == camera_id,
    ).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Restricted zone not found")
    return zone


@router.get("/cameras/{camera_id}/restricted-zones", response_model=List[schemas.RestrictedZoneOut])
def list_restricted_zones(camera_id: int, db: Session = Depends(get_db), payload=Depends(require_admin)):
    _get_camera_or_404(db, camera_id)
    return db.query(models.RestrictedZone).filter(
        models.RestrictedZone.camera_id == camera_id
    ).order_by(models.RestrictedZone.id.asc()).all()


@router.post("/cameras/{camera_id}/restricted-zones", response_model=schemas.RestrictedZoneOut, status_code=201)
def create_restricted_zone(camera_id: int, body: schemas.RestrictedZoneCreate, db: Session = Depends(get_db), payload=Depends(require_admin)):
    _get_camera_or_404(db, camera_id)
    try:
        name = validate_zone_name(body.name)
        points = validate_polygon_points(body.polygon_points, name)
    except ZoneConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    zone = models.RestrictedZone(camera_id=camera_id, name=name, polygon_points=points, enabled=body.enabled)
    db.add(zone); db.commit(); db.refresh(zone)
    return zone


@router.patch("/cameras/{camera_id}/restricted-zones/{zone_id}", response_model=schemas.RestrictedZoneOut)
def update_restricted_zone(camera_id: int, zone_id: int, body: schemas.RestrictedZoneUpdate, db: Session = Depends(get_db), payload=Depends(require_admin)):
    zone = _get_zone_or_404(db, camera_id, zone_id)
    try:
        name = validate_zone_name(body.name) if body.name is not None else zone.name
        points = validate_polygon_points(body.polygon_points, name) if body.polygon_points is not None else None
    except ZoneConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    zone.name = name
    if points is not None:
        zone.polygon_points = points
    if body.enabled is not None:
        zone.enabled = body.enabled
    db.commit(); db.refresh(zone)
    return zone


@router.delete("/cameras/{camera_id}/restricted-zones/{zone_id}")
def delete_restricted_zone(camera_id: int, zone_id: int, db: Session = Depends(get_db), payload=Depends(require_admin)):
    zone = _get_zone_or_404(db, camera_id, zone_id)
    db.delete(zone); db.commit()
    return {"detail": "Restricted zone deleted"}


# ── Safety Rules ──────────────────────────────────────────────────
@router.get("/safety-rules", response_model=List[schemas.SafetyRuleOut])
def list_rules(db: Session = Depends(get_db), payload=Depends(require_admin)):
    return db.query(models.SafetyRule).order_by(models.SafetyRule.created_at.desc()).all()


@router.post("/safety-rules", status_code=201)
def create_rule(body: schemas.SafetyRuleCreate, db: Session = Depends(get_db), payload=Depends(require_admin)):
    if body.ppe_types is not None and not body.is_restricted_area:
        # Same address as a single rule: some browser extensions block URLs
        # containing "batch", which left the page unable to reach the server.
        batch = schemas.SafetyRuleBatchCreate(
            location_id=body.location_id, ppe_types=body.ppe_types, severity_level=body.severity_level,
        )
        return create_rules(batch, db, payload)
    location = db.get(models.Location, body.location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found")
    if not body.is_restricted_area and not body.ppe_type:
        raise HTTPException(status_code=400, detail="PPE type is required unless the location is restricted")
    is_restricted_location = any(rule.is_restricted_area for rule in location.safety_rules)
    if body.is_restricted_area:
        if is_restricted_location:
            raise HTTPException(status_code=409, detail="This location is already marked as restricted.")
        if any(not rule.is_restricted_area for rule in location.safety_rules):
            raise HTTPException(status_code=409, detail="This location has PPE rules. Delete them before marking it restricted.")
    elif is_restricted_location:
        raise HTTPException(status_code=409, detail="This location is restricted, so PPE rules do not apply. Delete the restricted rule first.")
    if not body.is_restricted_area:
        if body.ppe_type not in PPE_RULE_ITEMS:
            raise HTTPException(status_code=422, detail="PPE type must be All PPE, Helmet, Safety Vest, Gloves, or No PPE")
        existing_ppe = {
            rule.ppe_type for rule in location.safety_rules
            if not rule.is_restricted_area and rule.ppe_type
        }
        if body.ppe_type == NO_PPE and existing_ppe - {NO_PPE}:
            raise HTTPException(status_code=409, detail="This location already requires PPE. Delete those rules before choosing None.")
        if body.ppe_type != NO_PPE and NO_PPE in existing_ppe:
            raise HTTPException(status_code=409, detail="This location is set to require no PPE. Delete that rule first.")
    severity = body.severity_level
    if not body.is_restricted_area and body.ppe_type == NO_PPE:
        severity = "Low"  # nothing is checked here, so no violation can use it
    if severity not in RULE_SEVERITIES:
        raise HTTPException(status_code=422, detail="Unsupported safety-rule severity")
    rule = models.SafetyRule(
        location_id=body.location_id,
        ppe_type=None if body.is_restricted_area else body.ppe_type,
        is_restricted_area=body.is_restricted_area, severity_level=severity
    )
    db.add(rule); db.flush()
    # Workers assigned to the location see the rule as an instruction to acknowledge.
    publish_rule_instruction(db, rule, created_by=int(payload.get("sub", 0)) or None)
    db.commit(); db.refresh(rule)
    return schemas.SafetyRuleOut.model_validate(rule).model_dump()


PPE_CHOICE_ORDER = ("Helmet", "Safety Vest", "Gloves")


@router.post("/safety-rules/batch", status_code=201)
def create_rules(body: schemas.SafetyRuleBatchCreate, db: Session = Depends(get_db), payload=Depends(require_admin)):
    """Require several PPE items at once; one rule per item (all three = "All PPE")."""

    location = db.get(models.Location, body.location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found")
    if any(rule.is_restricted_area for rule in location.safety_rules):
        raise HTTPException(status_code=409, detail="This location is restricted, so PPE rules do not apply. Delete the restricted rule first.")
    chosen = list(dict.fromkeys(str(value).strip() for value in body.ppe_types if str(value).strip()))
    if not chosen:
        raise HTTPException(status_code=422, detail="Choose at least one PPE item")
    unknown = [value for value in chosen if value not in PPE_RULE_ITEMS or value == NO_PPE]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unsupported PPE item: {', '.join(unknown)}")
    if body.severity_level not in RULE_SEVERITIES:
        raise HTTPException(status_code=422, detail="Unsupported safety-rule severity")
    existing = [rule.ppe_type for rule in location.safety_rules if rule.ppe_type]
    if NO_PPE in existing:
        raise HTTPException(status_code=409, detail="This location is set to require no PPE. Delete that rule first.")

    wanted = frozenset().union(*(PPE_RULE_ITEMS[value] for value in chosen))
    types = ["All PPE"] if wanted == ALL_PPE_ITEMS else [
        value for value in PPE_CHOICE_ORDER if PPE_RULE_ITEMS[value] <= wanted
    ]
    covered = frozenset().union(*(PPE_RULE_ITEMS.get(value, frozenset()) for value in existing))
    created, skipped = [], []
    for ppe_type in types:
        if ppe_type in existing or PPE_RULE_ITEMS[ppe_type] <= covered:
            skipped.append(ppe_type)
            continue
        rule = models.SafetyRule(
            location_id=location.id, ppe_type=ppe_type,
            is_restricted_area=False, severity_level=body.severity_level,
        )
        db.add(rule); db.flush()
        publish_rule_instruction(db, rule, created_by=int(payload.get("sub", 0)) or None)
        created.append(rule)
    if not created:
        raise HTTPException(status_code=409, detail=f"{location.name} already requires {', '.join(types)}.")
    db.commit()
    names = ", ".join(rule.ppe_type for rule in created)
    detail = f"{location.name} now requires {names}."
    if skipped:
        detail += f" Already required: {', '.join(skipped)}."
    return {
        "created": [schemas.SafetyRuleOut.model_validate(rule).model_dump() for rule in created],
        "skipped": skipped,
        "detail": detail,
    }


@router.delete("/safety-rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db), payload=Depends(require_admin)):
    rule = db.query(models.SafetyRule).filter(models.SafetyRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule); db.commit()
    return {"detail": "Rule deleted"}
