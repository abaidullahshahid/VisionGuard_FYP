from pydantic import BaseModel, EmailStr, Field
from typing import Any, Dict, Optional, List
from datetime import date as Date, datetime


# ── Auth ──────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email: str
    password: str

class LoginResponse(BaseModel):
    token: str
    role: str
    name: str

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetCheckRequest(BaseModel):
    email: Optional[str] = None
    code: Optional[str] = None
    token: Optional[str] = None

class ResetPasswordRequest(ResetCheckRequest):
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
    # Admin-set temporary password (forgot-password flow).
    password: Optional[str] = None

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
    name: Optional[str] = None
    type: Optional[str] = None
    stream_url: Optional[str] = None
    location_id: Optional[int] = None
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


# ── RestrictedZone ────────────────────────────────────────────────
# polygon_points is typed loosely on purpose: the zone service validates the
# exact [[x, y], ...] structure and returns readable 422 messages.
class RestrictedZoneCreate(BaseModel):
    name: str
    polygon_points: Any
    enabled: bool = True

class RestrictedZoneUpdate(BaseModel):
    name: Optional[str] = None
    polygon_points: Optional[Any] = None
    enabled: Optional[bool] = None

class RestrictedZoneOut(BaseModel):
    id: int
    camera_id: int
    name: str
    polygon_points: List[List[float]]
    enabled: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── SafetyRule ────────────────────────────────────────────────────
class SafetyRuleCreate(BaseModel):
    location_id: int
    ppe_type: Optional[str] = None
    # Several items at once, e.g. ["Helmet", "Safety Vest"]; replaces ppe_type.
    ppe_types: Optional[List[str]] = None
    is_restricted_area: bool = False
    severity_level: str = "High"

class SafetyRuleBatchCreate(BaseModel):
    """Several PPE items for one location, e.g. Helmet + Safety Vest."""

    location_id: int
    ppe_types: List[str]
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
    incident_id: Optional[str] = None
    camera_id: Optional[int] = None
    camera_identifier: Optional[str] = None
    location_id: Optional[int] = None
    violation_type: str
    severity_level: str = "Medium"
    track_id: Optional[int] = None
    stream_time_seconds: Optional[float] = None
    missing_items: List[str] = Field(default_factory=list)
    zone_id: Optional[str] = None
    zone_name: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    officer_notes: Optional[str] = None
    snapshot_url: Optional[str] = None

class IncidentBulkDelete(BaseModel):
    ids: List[int] = Field(default_factory=list, max_length=10000)
    all: bool = False


class IncidentUpdate(BaseModel):
    status: Optional[str] = None
    officer_notes: Optional[str] = None

class IncidentResponse(BaseModel):
    id: int
    incident_id: Optional[str] = None
    incident_type: str
    violation_type: str
    track_id: Optional[int] = None
    timestamp: Optional[datetime] = None
    stream_time_seconds: Optional[float] = None
    severity: str
    severity_level: str
    status: str
    location: Optional[str] = None
    camera_id: Optional[int] = None
    camera_identifier: Optional[str] = None
    location_id: Optional[int] = None
    missing_items: List[str] = Field(default_factory=list)
    zone_id: Optional[str] = None
    zone_name: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    officer_notes: Optional[str] = None
    evidence_url: Optional[str] = None
    snapshot_url: Optional[str] = None
    detected_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class IncidentOut(IncidentResponse):
    """Backward-compatible name retained for existing route declarations."""

# ── CorrectiveAction ──────────────────────────────────────────────
class CorrectiveActionCreate(BaseModel):
    incident_id: int
    assigned_to: int
    description: str
    priority: str = "High"
    deadline: Optional[str] = None

class CorrectiveActionUpdate(BaseModel):
    assigned_to: Optional[int] = None
    status: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    deadline: Optional[str] = None

class TaskStatusUpdate(BaseModel):
    status: str

class CorrectiveActionOut(BaseModel):
    id: int
    incident_id: int
    assigned_to: Optional[int] = None
    assignee_name: Optional[str] = None
    assignee_role: Optional[str] = None
    description: Optional[str] = None
    priority: str
    deadline: Optional[str] = None
    status: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class IncidentDetailResponse(IncidentResponse):
    corrective_actions: List[CorrectiveActionOut] = Field(default_factory=list)


# ── SafetyInstruction ─────────────────────────────────────────────
class SafetyInstructionCreate(BaseModel):
    title: str
    content: str
    category: str = "procedures"
    location_id: int

class SafetyInstructionOut(BaseModel):
    id: int
    title: str
    content: Optional[str] = None
    category: Optional[str] = None
    location_id: Optional[int] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AcknowledgementOut(BaseModel):
    id: int
    instruction_id: int
    acknowledged: bool = True
    created: bool
    acknowledged_at: Optional[datetime] = None

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
    totalViolations: int = 0
    complianceRate: Optional[float] = None


class ComplianceGenerate(BaseModel):
    date: Optional[Date] = None
    location_id: Optional[int] = None


class ComplianceReview(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None


# ── Alert settings ────────────────────────────────────────────────
class AlertSettingsUpdate(BaseModel):
    email_enabled: bool
    min_severity: str
    email_officers: bool
    email_admins: bool
    email_workers: bool
    extra_recipients: Optional[str] = ""
    cooldown_minutes: int
    attach_snapshot: bool
    camera_alerts: bool
    daily_summary: bool
    daily_summary_hour: int
