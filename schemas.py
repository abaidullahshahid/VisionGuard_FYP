from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime


# ── Auth ──────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email: str
    password: str

class LoginResponse(BaseModel):
    token: str
    role: str
    name: str

class PasswordResetRequest(BaseModel):
    email: str
    new_password: str
    confirm_password: str

class MessageResponse(BaseModel):
    message: str

class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    department: Optional[str] = None
    current_password: Optional[str] = None
    new_password: Optional[str] = None
    confirm_password: Optional[str] = None


# ── User ──────────────────────────────────────────────────────────
class UserCreate(BaseModel):
    name: str
    email: str
    password: str
    role: str = "worker"
    department: Optional[str] = None

class UserUpdate(BaseModel):
    status: Optional[str] = None
    role: Optional[str] = None
    department: Optional[str] = None

class UserOut(BaseModel):
    id: int
    name: str
    email: str
    department: Optional[str] = None
    role: str
    status: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── Location ──────────────────────────────────────────────────────
class LocationCreate(BaseModel):
    name: str
    zone: str
    department: str

class LocationOut(BaseModel):
    id: int
    name: str
    zone: Optional[str] = None
    department: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── Camera ────────────────────────────────────────────────────────
class CameraCreate(BaseModel):
    name: str
    type: str = "IP"
    stream_url: str
    location_id: int

class CameraUpdate(BaseModel):
    status: Optional[str] = None

class CameraOut(BaseModel):
    id: int
    name: str
    type: str
    stream_url: Optional[str] = None
    location_id: int
    status: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── SafetyRule ────────────────────────────────────────────────────
class SafetyRuleCreate(BaseModel):
    location_id: int
    ppe_type: Optional[str] = None
    is_restricted_area: bool = False
    severity_level: str = "High"

class SafetyRuleOut(BaseModel):
    id: int
    location_id: int
    ppe_type: Optional[str] = None
    is_restricted_area: bool
    severity_level: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── Incident ──────────────────────────────────────────────────────
class IncidentCreate(BaseModel):
    camera_id: Optional[int] = None
    location_id: Optional[int] = None
    violation_type: str
    severity_level: str = "Medium"
    snapshot_url: Optional[str] = None

class IncidentUpdate(BaseModel):
    status: Optional[str] = None

class IncidentOut(BaseModel):
    id: int
    violation_type: str
    severity_level: str
    status: str
    location: Optional[str] = None
    camera_id: Optional[int] = None
    location_id: Optional[int] = None
    snapshot_url: Optional[str] = None
    detected_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── CorrectiveAction ──────────────────────────────────────────────
class CorrectiveActionCreate(BaseModel):
    incident_id: int
    assigned_to: int
    description: str
    priority: str = "High"
    deadline: Optional[str] = None

class CorrectiveActionUpdate(BaseModel):
    status: Optional[str] = None

class CorrectiveActionOut(BaseModel):
    id: int
    incident_id: int
    assigned_to: int
    description: Optional[str] = None
    priority: str
    deadline: Optional[str] = None
    status: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── SafetyInstruction ─────────────────────────────────────────────
class SafetyInstructionCreate(BaseModel):
    title: str
    content: str
    category: str = "procedures"
    location_id: Optional[int] = None

class SafetyInstructionOut(BaseModel):
    id: int
    title: str
    content: Optional[str] = None
    category: Optional[str] = None
    location_id: Optional[int] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── WorkerLocation ────────────────────────────────────────────────
class WorkerLocationCreate(BaseModel):
    worker_id: int
    location_id: int

class WorkerLocationOut(BaseModel):
    id: int
    worker_id: int
    location_id: int
    assigned_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── ComplianceRecord ──────────────────────────────────────────────
class ComplianceRecordOut(BaseModel):
    id: int
    location: Optional[str] = None
    date: Optional[datetime] = None
    violations: int
    status: str
    officer: Optional[str] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


# ── Stats ─────────────────────────────────────────────────────────
class AdminStats(BaseModel):
    totalUsers: int
    totalCameras: int
    totalIncidents: int
    totalLocations: int

class OfficerStats(BaseModel):
    totalIncidents: int
    pendingActions: int
    resolvedToday: int
    activeAlerts: int

class ComplianceStats(BaseModel):
    compliant: int
    nonCompliant: int
    pending: int
    total: int
