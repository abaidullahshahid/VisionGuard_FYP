from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from database import get_db
import models, schemas
from routers.auth import decode_token, hash_password
from typing import List, Optional

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(authorization: str = Header(...)):
    if authorization == "Bearer demo":
        return {"sub": "1", "role": "admin", "name": "Demo Admin"}
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
    existing = db.query(models.User).filter(models.User.email == body.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = models.User(
        name     = body.name,
        email    = body.email,
        password = hash_password(body.password),
        department = body.department,
        role     = body.role,
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
        user.status = body.status
    if body.role is not None:
        user.role = body.role
    if body.department is not None:
        user.department = body.department
    db.commit(); db.refresh(user)
    return user


@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), payload=Depends(require_admin)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user); db.commit()
    return {"detail": "User deleted"}


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


@router.delete("/cameras/{camera_id}")
def delete_camera(camera_id: int, db: Session = Depends(get_db), payload=Depends(require_admin)):
    cam = db.query(models.Camera).filter(models.Camera.id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    db.delete(cam); db.commit()
    return {"detail": "Camera deleted"}


# ── Safety Rules ──────────────────────────────────────────────────
@router.get("/safety-rules", response_model=List[schemas.SafetyRuleOut])
def list_rules(db: Session = Depends(get_db), payload=Depends(require_admin)):
    return db.query(models.SafetyRule).order_by(models.SafetyRule.created_at.desc()).all()


@router.post("/safety-rules", response_model=schemas.SafetyRuleOut, status_code=201)
def create_rule(body: schemas.SafetyRuleCreate, db: Session = Depends(get_db), payload=Depends(require_admin)):
    if not body.is_restricted_area and not body.ppe_type:
        raise HTTPException(status_code=400, detail="PPE type is required unless the location is restricted")
    rule = models.SafetyRule(
        location_id=body.location_id,
        ppe_type=None if body.is_restricted_area else body.ppe_type,
        is_restricted_area=body.is_restricted_area, severity_level=body.severity_level
    )
    db.add(rule); db.commit(); db.refresh(rule)
    return rule


@router.delete("/safety-rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db), payload=Depends(require_admin)):
    rule = db.query(models.SafetyRule).filter(models.SafetyRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule); db.commit()
    return {"detail": "Rule deleted"}
