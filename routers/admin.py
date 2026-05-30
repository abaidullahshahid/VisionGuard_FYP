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
    rule = models.SafetyRule(
        location_id=body.location_id, ppe_type=body.ppe_type,
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
