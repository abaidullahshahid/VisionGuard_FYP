from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from database import get_db
import models, schemas
from routers.auth import decode_token
from typing import List

router = APIRouter(prefix="/worker", tags=["worker"])


def require_worker(authorization: str = Header(...)):
    if authorization == "Bearer demo":
        return {"sub": "3", "role": "worker", "name": "Demo Worker"}
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
    worker_id = int(payload.get("sub", 0))
    assignments = db.query(models.WorkerLocation).filter(
        models.WorkerLocation.worker_id == worker_id
    ).all()
    assigned_location_ids = [assignment.location_id for assignment in assignments]

    instructions = []
    if assigned_location_ids:
        instructions = db.query(models.SafetyInstruction).filter(
            models.SafetyInstruction.location_id.in_(assigned_location_ids)
        ).order_by(models.SafetyInstruction.created_at.desc()).all()

    result = []
    for inst in instructions:
        loc_name = inst.location.name if inst.location else "Assigned Location"
        result.append({
            "id":          f"inst_{inst.id}",
            "title":       inst.title,
            "description": inst.content,
            "category":    inst.category or "procedures",
            "location_id":  inst.location_id,
            "location":     loc_name,
            "steps":       [],
            "warnings":    [],
            "dos":         [],
            "donts":       [],
            "equipment":   [],
        })

    restricted_rules = db.query(models.SafetyRule).filter(
        models.SafetyRule.is_restricted_area == True
    ).all()
    ppe_rules = []
    if assigned_location_ids:
        ppe_rules = db.query(models.SafetyRule).filter(
            models.SafetyRule.location_id.in_(assigned_location_ids),
            models.SafetyRule.is_restricted_area == False
        ).all()

    rules = restricted_rules + ppe_rules
    for rule in rules:
        loc_name = rule.location.name if rule.location else "Assigned Location"

        if rule.is_restricted_area:
            title = f"Restricted Area: Do Not Enter {loc_name}"
            description = f"{loc_name} is a restricted area. Workers must not enter this location."
            dos = ["Stay out of this restricted area", "Report attempted entry to a safety officer"]
            warnings = ["No worker is authorized to enter this location."]
            donts = ["Do not enter this area", "Do not attempt work inside this zone"]
            equipment = []
        else:
            title = f"Safety Rule: {rule.ppe_type} Required"
            description = f"Mandatory safety rule for {loc_name}."
            dos = [f"Must wear {rule.ppe_type}"]
            warnings = []
            donts = []
            equipment = [rule.ppe_type]

        result.append({
            "id":          f"rule_{rule.id}",
            "title":       title,
            "description": description,
            "category":    "ppe",
            "location_id":  rule.location_id,
            "location":     loc_name,
            "steps":       [],
            "warnings":    warnings,
            "dos":         dos,
            "donts":       donts,
            "equipment":   equipment,
        })

    return result
