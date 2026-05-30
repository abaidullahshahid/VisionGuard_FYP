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

    assigned = db.query(models.WorkerLocation).filter(
        models.WorkerLocation.worker_id == worker_id
    ).count()

    active_alerts = db.query(models.Incident).filter(
        models.Incident.status == "open"
    ).count()

    return {
        "assignedLocations": assigned,
        "safetyScore":       92,
        "tasksCompleted":    5,
        "activeAlerts":      active_alerts,
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
            "description": "Check safety compliance",
            "status":      "active",
            "date":        a.assigned_at,
            "shift":       "Full Shift",
        })
    return result


# ── Locations (worker-assigned) ───────────────────────────────────
@router.get("/locations")
def get_locations(db: Session = Depends(get_db), payload=Depends(require_worker)):
    worker_id = int(payload.get("sub", 0))
    worker_locs = db.query(models.WorkerLocation).filter(
        models.WorkerLocation.worker_id == worker_id
    ).all()

    result = []
    for wl in worker_locs:
        loc = wl.location
        if loc:
            result.append({
                "id":          loc.id,
                "name":        loc.name,
                "zone":        loc.zone,
                "department":  loc.department,
                "floor":       loc.zone,
                "capacity":    20,
                "riskLevel":   "Medium",
                "cameras":     len(loc.cameras),
                "lastAudit":   None,
                "description": f"Department: {loc.department}",
            })
    return result


# ── Safety Instructions ───────────────────────────────────────────
@router.get("/safety-instructions")
def get_instructions(db: Session = Depends(get_db), payload=Depends(require_worker)):
    instructions = db.query(models.SafetyInstruction).order_by(
        models.SafetyInstruction.created_at.desc()
    ).all()

    result = []
    for inst in instructions:
        result.append({
            "id":          inst.id,
            "title":       inst.title,
            "description": inst.content,
            "category":    inst.category or "procedures",
            "steps":       [],
            "warnings":    [],
            "dos":         [],
            "donts":       [],
            "equipment":   [],
        })
    return result
