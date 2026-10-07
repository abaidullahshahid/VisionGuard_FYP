from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from database import get_db
import models, schemas
from routers.auth import decode_token
from services.action_service import TASK_STATUSES, sync_incident_status
from services import compliance_service
from services.instruction_service import ensure_rule_instructions, instruction_view
from services.notification_service import notify_action_updated
from typing import List

router = APIRouter(prefix="/worker", tags=["worker"])


def require_worker(authorization: str = Header(...)):
    token = authorization.replace("Bearer ", "")
    payload = decode_token(token)
    if payload.get("role") not in ("worker", "officer", "admin"):
        raise HTTPException(status_code=403, detail="Worker access required")
    return payload


# ── Stats ─────────────────────────────────────────────────────────
@router.get("/stats")
def get_stats(db: Session = Depends(get_db), payload=Depends(require_worker)):
    worker_id = int(payload.get("sub", 0))
    assigned_locations = db.query(models.WorkerLocation).filter(
        models.WorkerLocation.worker_id == worker_id
    ).all()
    assigned_location_ids = [assignment.location_id for assignment in assigned_locations]
    assigned_actions = db.query(models.CorrectiveAction).filter(
        models.CorrectiveAction.assigned_to == worker_id,
        models.CorrectiveAction.status.in_(["Pending", "In Progress"])
    ).count()
    completed_actions = db.query(models.CorrectiveAction).filter(
        models.CorrectiveAction.assigned_to == worker_id,
        models.CorrectiveAction.status == "Resolved"
    ).count()

    open_incidents_query = db.query(models.Incident).filter(
        models.Incident.status == "open"
    )
    if assigned_location_ids:
        open_incidents_query = open_incidents_query.filter(models.Incident.location_id.in_(assigned_location_ids))
    else:
        open_incidents_query = open_incidents_query.filter(models.Incident.id == -1)
    open_incidents = open_incidents_query.count()

    return {
        "availableLocations": len(assigned_locations),
        "assignedLocations":  len(assigned_locations),
        "assignedActions":    assigned_actions,
        "completedActions":   completed_actions,
        "openIncidents":      open_incidents,
    }


# ── Assignments ───────────────────────────────────────────────────
@router.get("/assignments")
def get_assignments(db: Session = Depends(get_db), payload=Depends(require_worker)):
    worker_id = int(payload.get("sub", 0))
    assignments = db.query(models.WorkerLocation).filter(
        models.WorkerLocation.worker_id == worker_id
    ).all()
    result = []
    for a in assignments:
        result.append({
            "id":          a.id,
            "location":    a.location.name if a.location else "—",
            "date":        a.assigned_at,
        })
    return result


# ── Locations (worker-assigned) ───────────────────────────────────
@router.get("/locations")
def get_locations(db: Session = Depends(get_db), payload=Depends(require_worker)):
    worker_id = int(payload.get("sub", 0))
    severity_rank = {"Low": 1, "Medium": 2, "High": 3, "Critical": 4}
    result = []
    assignments = db.query(models.WorkerLocation).filter(
        models.WorkerLocation.worker_id == worker_id
    ).order_by(models.WorkerLocation.assigned_at.desc()).all()
    for assignment in assignments:
        loc = assignment.location
        if not loc:
            continue
        severities = [rule.severity_level for rule in loc.safety_rules]
        severities.extend(inc.severity_level for inc in loc.incidents if inc.status == "open")
        risk_level = max(severities, key=lambda s: severity_rank.get(s, 0)) if severities else None

        result.append({
            "assignment_id": assignment.id,
            "id":          loc.id,
            "name":        loc.name,
            "zone":        loc.zone,
            "department":  loc.department,
            "assigned_at": assignment.assigned_at,
            "riskLevel":   risk_level,
            "cameras":     len(loc.cameras),
            "rules":       len(loc.safety_rules),
            "openIncidents": len([inc for inc in loc.incidents if inc.status == "open"]),
            "description": f"Department: {loc.department}",
        })
    return result


# ── Safety Instructions ───────────────────────────────────────────
@router.get("/safety-instructions")
def get_instructions(db: Session = Depends(get_db), payload=Depends(require_worker)):
    """Rule-published and officer-written instructions for my locations."""
    worker_id = int(payload.get("sub", 0))
    assignments = db.query(models.WorkerLocation).filter(
        models.WorkerLocation.worker_id == worker_id
    ).all()
    assigned_location_ids = [assignment.location_id for assignment in assignments]
    if not assigned_location_ids:
        return []

    ensure_rule_instructions(db, assigned_location_ids)
    instructions = db.query(models.SafetyInstruction).filter(
        models.SafetyInstruction.location_id.in_(assigned_location_ids)
    ).order_by(
        models.SafetyInstruction.safety_rule_id.is_(None),
        models.SafetyInstruction.created_at.desc(),
    ).all()

    acknowledgements = {
        acknowledgement.instruction_id: acknowledgement
        for acknowledgement in db.query(models.Acknowledgement).filter(
            models.Acknowledgement.worker_id == worker_id
        ).all()
    }

    result = []
    for inst in instructions:
        acknowledgement = acknowledgements.get(inst.id)
        result.append({
            "id":          f"inst_{inst.id}",
            "instruction_id": inst.id,
            "title":       inst.title,
            "description": inst.content,
            "category":    inst.category or "procedures",
            "location_id":  inst.location_id,
            "location":     inst.location.name if inst.location else "Assigned Location",
            "source":      "safety_rule" if inst.safety_rule_id else "officer",
            "steps":       [],
            **instruction_view(inst),
            "acknowledgeable": payload.get("role") == "worker",
            "acknowledged": acknowledgement is not None,
            "acknowledged_at": acknowledgement.acknowledged_at if acknowledgement else None,
            "created_at":  inst.created_at,
        })
    return result


# ── My corrective actions (UC-13) ─────────────────────────────────
def _task_payload(action: models.CorrectiveAction) -> dict:
    incident = action.incident
    return {
        "id": action.id,
        "description": action.description,
        "priority": action.priority,
        "deadline": action.deadline,
        "status": action.status,
        "created_at": action.created_at,
        "incident": {
            "id": incident.id,
            "type": incident.violation_type,
            "severity": incident.severity_level,
            "location": incident.location_rel.name if incident.location_rel else "Unknown",
            "detected_at": incident.detected_at,
            "missing_items": incident.missing_items or [],
            "zone_name": incident.zone_name,
        } if incident else None,
    }


@router.get("/corrective-actions")
def my_corrective_actions(db: Session = Depends(get_db), payload=Depends(require_worker)):
    actions = db.query(models.CorrectiveAction).filter(
        models.CorrectiveAction.assigned_to == int(payload.get("sub", 0))
    ).order_by(models.CorrectiveAction.created_at.desc()).all()
    return [_task_payload(action) for action in actions]


@router.patch("/corrective-actions/{action_id}")
def update_my_corrective_action(
    action_id: int,
    body: schemas.TaskStatusUpdate,
    db: Session = Depends(get_db),
    payload=Depends(require_worker),
):
    user_id = int(payload.get("sub", 0))
    action = db.get(models.CorrectiveAction, action_id)
    if action is None or action.assigned_to != user_id:
        raise HTTPException(status_code=404, detail="Corrective action not found")
    if body.status not in TASK_STATUSES:
        raise HTTPException(status_code=422, detail="Status must be Pending, In Progress, or Resolved")
    if action.status != body.status:
        action.status = body.status
        sync_incident_status(db, action.incident)
        notify_action_updated(db, action, user_id, payload.get("role", "worker"))
        db.commit()
        compliance_service.refresh_for_incidents(db, [action.incident])
        db.refresh(action)
    return _task_payload(action)


@router.post(
    "/safety-instructions/{instruction_id}/acknowledge",
    response_model=schemas.AcknowledgementOut,
)
def acknowledge_instruction(
    instruction_id: int,
    db: Session = Depends(get_db),
    payload=Depends(require_worker),
):
    if payload.get("role") != "worker":
        raise HTTPException(status_code=403, detail="Only workers can acknowledge instructions")
    worker_id = int(payload.get("sub", 0))
    instruction = db.get(models.SafetyInstruction, instruction_id)
    if instruction is None:
        raise HTTPException(status_code=404, detail="Safety instruction not found")

    allowed = db.query(models.WorkerLocation).filter(
        models.WorkerLocation.worker_id == worker_id,
        models.WorkerLocation.location_id == instruction.location_id,
    ).first()
    if allowed is None:
        raise HTTPException(
            status_code=403,
            detail="This safety instruction is not assigned to your locations",
        )

    existing = db.query(models.Acknowledgement).filter(
        models.Acknowledgement.worker_id == worker_id,
        models.Acknowledgement.instruction_id == instruction.id,
    ).first()
    if existing is not None:
        return {
            "id": existing.id,
            "instruction_id": existing.instruction_id,
            "acknowledged": True,
            "created": False,
            "acknowledged_at": existing.acknowledged_at,
        }

    acknowledgement = models.Acknowledgement(
        instruction_id=instruction.id,
        worker_id=worker_id,
    )
    try:
        db.add(acknowledgement)
        db.commit()
        db.refresh(acknowledgement)
    except IntegrityError:
        db.rollback()
        acknowledgement = db.query(models.Acknowledgement).filter(
            models.Acknowledgement.worker_id == worker_id,
            models.Acknowledgement.instruction_id == instruction.id,
        ).first()
        if acknowledgement is None:
            raise
        return {
            "id": acknowledgement.id,
            "instruction_id": acknowledgement.instruction_id,
            "acknowledged": True,
            "created": False,
            "acknowledged_at": acknowledgement.acknowledged_at,
        }

    return {
        "id": acknowledgement.id,
        "instruction_id": acknowledgement.instruction_id,
        "acknowledged": True,
        "created": True,
        "acknowledged_at": acknowledgement.acknowledged_at,
    }
