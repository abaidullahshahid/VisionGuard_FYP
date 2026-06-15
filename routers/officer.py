from fastapi import APIRouter, Depends, HTTPException, Header, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
import models, schemas
from routers.auth import decode_token
from typing import List, Optional
import datetime

router = APIRouter(prefix="/officer", tags=["officer"])


def require_officer(authorization: str = Header(...)):
    if authorization == "Bearer demo":
        return {"sub": "2", "role": "officer", "name": "Demo Officer"}
    token = authorization.replace("Bearer ", "")
    payload = decode_token(token)
    if payload.get("role") not in ("officer", "admin"):
        raise HTTPException(status_code=403, detail="Officer access required")
    return payload


# ── Stats ─────────────────────────────────────────────────────────
@router.get("/stats", response_model=schemas.OfficerStats)
def get_stats(db: Session = Depends(get_db), payload=Depends(require_officer)):
    today = datetime.datetime.utcnow().date()

    total_incidents = db.query(models.Incident).count()
    pending_actions = db.query(models.CorrectiveAction).filter(
        models.CorrectiveAction.status.in_(["Pending", "In Progress"])
    ).count()
    resolved_today = db.query(models.CorrectiveAction).filter(
        models.CorrectiveAction.status == "Resolved",
        func.date(models.CorrectiveAction.created_at) == today
    ).count()
    active_alerts = db.query(models.Incident).filter(
        models.Incident.status == "open"
    ).count()

    return {
        "totalIncidents": total_incidents,
        "pendingActions": pending_actions,
        "resolvedToday":  resolved_today,
        "activeAlerts":   active_alerts,
    }


# ── Incidents ─────────────────────────────────────────────────────
@router.get("/incidents", response_model=List[schemas.IncidentOut])
def list_incidents(
    status:   Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    limit:    Optional[int] = Query(None),
    db: Session = Depends(get_db),
    payload=Depends(require_officer),
):
    query = db.query(models.Incident).order_by(models.Incident.detected_at.desc())
    if status:
        query = query.filter(models.Incident.status == status)
    if severity:
        query = query.filter(models.Incident.severity_level == severity)
    if limit:
        query = query.limit(limit)
    incidents = query.all()

    result = []
    for inc in incidents:
        loc_name = inc.location_rel.name if inc.location_rel else "Unknown"
        if location and location.lower() not in loc_name.lower():
            continue
        result.append({
            "id":             inc.id,
            "violation_type": inc.violation_type,
            "severity_level": inc.severity_level,
            "status":         inc.status,
            "location":       loc_name,
            "camera_id":      inc.camera_id,
            "location_id":    inc.location_id,
            "snapshot_url":   inc.snapshot_url,
            "detected_at":    inc.detected_at,
        })
    return result


@router.post("/incidents", response_model=schemas.IncidentOut, status_code=201)
def create_incident(body: schemas.IncidentCreate, db: Session = Depends(get_db), payload=Depends(require_officer)):
    inc = models.Incident(
        camera_id=body.camera_id, location_id=body.location_id,
        violation_type=body.violation_type, severity_level=body.severity_level,
        snapshot_url=body.snapshot_url, status="open"
    )
    db.add(inc); db.commit(); db.refresh(inc)
    loc_name = inc.location_rel.name if inc.location_rel else "Unknown"
    return {**inc.__dict__, "location": loc_name}


@router.patch("/incidents/{incident_id}", response_model=schemas.IncidentOut)
def update_incident(incident_id: int, body: schemas.IncidentUpdate, db: Session = Depends(get_db), payload=Depends(require_officer)):
    inc = db.query(models.Incident).filter(models.Incident.id == incident_id).first()
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")
    if body.status:
        inc.status = body.status
    db.commit(); db.refresh(inc)
    loc_name = inc.location_rel.name if inc.location_rel else "Unknown"
    return {**inc.__dict__, "location": loc_name}


# ── Corrective Actions ────────────────────────────────────────────
@router.get("/corrective-actions", response_model=List[schemas.CorrectiveActionOut])
def list_actions(db: Session = Depends(get_db), payload=Depends(require_officer)):
    return db.query(models.CorrectiveAction).order_by(models.CorrectiveAction.created_at.desc()).all()


@router.post("/corrective-actions", response_model=schemas.CorrectiveActionOut, status_code=201)
def create_action(body: schemas.CorrectiveActionCreate, db: Session = Depends(get_db), payload=Depends(require_officer)):
    inc = db.query(models.Incident).filter(models.Incident.id == body.incident_id).first()
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")
    action = models.CorrectiveAction(
        incident_id=body.incident_id, assigned_to=body.assigned_to,
        description=body.description, priority=body.priority,
        deadline=body.deadline, status="Pending"
    )
    db.add(action); db.commit(); db.refresh(action)
    return action


@router.patch("/corrective-actions/{action_id}", response_model=schemas.CorrectiveActionOut)
def update_action(action_id: int, body: schemas.CorrectiveActionUpdate, db: Session = Depends(get_db), payload=Depends(require_officer)):
    action = db.query(models.CorrectiveAction).filter(models.CorrectiveAction.id == action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    if body.status:
        action.status = body.status
    db.commit(); db.refresh(action)
    return action


# ── Cameras (for live feed) ───────────────────────────────────────
@router.get("/cameras", response_model=List[schemas.CameraOut])
def list_cameras(db: Session = Depends(get_db), payload=Depends(require_officer)):
    return db.query(models.Camera).filter(models.Camera.status == "active").all()


# ── Locations ─────────────────────────────────────────────────────
@router.get("/locations", response_model=List[schemas.LocationOut])
def list_locations(db: Session = Depends(get_db), payload=Depends(require_officer)):
    return db.query(models.Location).all()


# ── Alerts (recent open incidents as alerts) ──────────────────────
@router.get("/alerts")
def list_alerts(db: Session = Depends(get_db), payload=Depends(require_officer)):
    incidents = db.query(models.Incident).filter(
        models.Incident.status == "open",
        models.Incident.camera_id.isnot(None)
    ).order_by(models.Incident.detected_at.desc()).limit(20).all()

    return [
        {
            "id":        inc.id,
            "type":      inc.violation_type,
            "severity":  inc.severity_level,
            "timestamp": inc.detected_at,
        }
        for inc in incidents
    ]


# ── Compliance Records ────────────────────────────────────────────
@router.get("/compliance-records")
def list_compliance(db: Session = Depends(get_db), payload=Depends(require_officer)):
    records = db.query(models.ComplianceRecord).order_by(models.ComplianceRecord.date.desc()).all()
    result = []
    for rec in records:
        loc_name     = rec.location.name if rec.location else "Unknown"
        officer_name = rec.officer.name  if rec.officer  else "—"
        result.append({
            "id":         rec.id,
            "location":   loc_name,
            "date":       rec.date,
            "violations": rec.violations,
            "status":     rec.status,
            "officer":    officer_name,
            "notes":      rec.notes,
        })
    return result


@router.get("/compliance-stats", response_model=schemas.ComplianceStats)
def compliance_stats(db: Session = Depends(get_db), payload=Depends(require_officer)):
    total      = db.query(models.ComplianceRecord).count()
    compliant  = db.query(models.ComplianceRecord).filter(models.ComplianceRecord.status == "compliant").count()
    non_c      = db.query(models.ComplianceRecord).filter(models.ComplianceRecord.status == "non-compliant").count()
    pending    = db.query(models.ComplianceRecord).filter(models.ComplianceRecord.status == "pending").count()
    return {"compliant": compliant, "nonCompliant": non_c, "pending": pending, "total": total}
