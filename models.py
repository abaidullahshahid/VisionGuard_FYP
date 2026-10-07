from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from database import Base


class UserRole(str, enum.Enum):
    admin = "admin"
    officer = "officer"
    worker = "worker"


class UserStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"


class CameraStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"
    maintenance = "maintenance"


class SeverityLevel(str, enum.Enum):
    Low = "Low"
    Medium = "Medium"
    High = "High"
    Critical = "Critical"


class IncidentStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"


class ActionStatus(str, enum.Enum):
    Pending = "Pending"
    In_Progress = "In Progress"
    Resolved = "Resolved"


# ── User ─────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String(150), nullable=False)
    email      = Column(String(255), unique=True, index=True, nullable=False)
    password   = Column(String(255), nullable=False)
    department = Column(String(100), nullable=True)
    role       = Column(String(50), default="worker", nullable=False)
    status     = Column(String(50), default="active", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    assigned_locations    = relationship("WorkerLocation", back_populates="worker", foreign_keys="WorkerLocation.worker_id")
    corrective_actions    = relationship("CorrectiveAction", back_populates="assigned_user", foreign_keys="CorrectiveAction.assigned_to")
    created_instructions  = relationship("SafetyInstruction", back_populates="creator")
    acknowledgements      = relationship("Acknowledgement", back_populates="worker")
    notifications         = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    reset_codes           = relationship("PasswordResetCode", back_populates="user", cascade="all, delete-orphan")


# ── Location ─────────────────────────────────────────────────────
class Location(Base):
    __tablename__ = "locations"

    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String(150), nullable=False)
    zone       = Column(String(100))
    department = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    cameras              = relationship("Camera", back_populates="location")
    safety_rules         = relationship("SafetyRule", back_populates="location")
    safety_instructions  = relationship("SafetyInstruction", back_populates="location")
    worker_locations     = relationship("WorkerLocation", back_populates="location")
    incidents            = relationship("Incident", back_populates="location_rel")


# ── Camera ───────────────────────────────────────────────────────
class Camera(Base):
    __tablename__ = "cameras"

    id          = Column(Integer, primary_key=True, index=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    name        = Column(String(150), nullable=False)
    type        = Column(String(50), default="IP")
    stream_url  = Column(String(500))
    status      = Column(String(50), default="active")
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    location  = relationship("Location", back_populates="cameras")
    incidents = relationship("Incident", back_populates="camera")
    # Zones belong to exactly one camera, so they are deleted with it.
    restricted_zones = relationship(
        "RestrictedZone",
        back_populates="camera",
        cascade="all, delete-orphan",
        order_by="RestrictedZone.id",
    )


# ── RestrictedZone ───────────────────────────────────────────────
class RestrictedZone(Base):
    __tablename__ = "restricted_zones"

    # ``polygon_points`` holds [[x, y], ...] normalized to 0.0-1.0 of the
    # camera frame, so one polygon fits every rendering resolution.
    id             = Column(Integer, primary_key=True, index=True)
    camera_id      = Column(Integer, ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False, index=True)
    name           = Column(String(150), nullable=False)
    polygon_points = Column(JSON, nullable=False)
    enabled        = Column(Boolean, default=True, nullable=False)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
    updated_at     = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    camera = relationship("Camera", back_populates="restricted_zones")


# ── SafetyRule ───────────────────────────────────────────────────
class SafetyRule(Base):
    __tablename__ = "safety_rules"

    id                 = Column(Integer, primary_key=True, index=True)
    location_id        = Column(Integer, ForeignKey("locations.id"), nullable=False)
    ppe_type           = Column(String(100), nullable=True)
    is_restricted_area = Column(Boolean, default=False)
    severity_level     = Column(String(50), default="High")
    created_at         = Column(DateTime(timezone=True), server_default=func.now())

    location = relationship("Location", back_populates="safety_rules")
    # The instruction workers acknowledge for this rule; removed with the rule.
    instructions = relationship(
        "SafetyInstruction",
        back_populates="rule",
        cascade="all, delete-orphan",
    )


# ── Incident ─────────────────────────────────────────────────────
class Incident(Base):
    __tablename__ = "incidents"

    # ``id`` remains the local integer key used by the existing frontend and
    # corrective_actions table.  ``incident_uuid`` is the stable identifier
    # generated by the AI IncidentManager.
    id                  = Column(Integer, primary_key=True, index=True)
    incident_uuid       = Column(String(36), unique=True, index=True, nullable=True)
    camera_id           = Column(Integer, ForeignKey("cameras.id"), nullable=True)
    camera_identifier   = Column(String(255), nullable=True)
    location_id         = Column(Integer, ForeignKey("locations.id"), nullable=True)
    violation_type      = Column(String(150), nullable=False)
    track_id            = Column(Integer, nullable=True)
    stream_time_seconds = Column(Float, nullable=True)
    severity_level      = Column(String(50), default="Medium", nullable=False)
    missing_items       = Column(JSON, default=list, nullable=False)
    zone_id             = Column(String(255), nullable=True)
    zone_name           = Column(String(255), nullable=True)
    evidence_path       = Column(String(1000), nullable=True)
    incident_metadata   = Column("metadata", JSON, default=dict, nullable=False)
    status              = Column(String(50), default="open", nullable=False)
    officer_notes       = Column(Text, nullable=True)
    snapshot_url        = Column(String(500), nullable=True)
    detected_at         = Column(DateTime(timezone=True), server_default=func.now())
    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    updated_at          = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    camera       = relationship("Camera", back_populates="incidents")
    location_rel = relationship("Location", back_populates="incidents")
    corrective_actions = relationship("CorrectiveAction", back_populates="incident")

    @property
    def location(self):
        return self.location_rel.name if self.location_rel else "Unknown"


# ── CorrectiveAction ─────────────────────────────────────────────
class CorrectiveAction(Base):
    __tablename__ = "corrective_actions"

    id          = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False)
    # NULL once the assignee's account is deleted; ``former_assignee`` keeps
    # their name so the action history still says who it was.
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)
    former_assignee = Column(String(150), nullable=True)
    description = Column(Text)
    priority    = Column(String(50), default="High")
    deadline    = Column(String(50), nullable=True)
    status      = Column(String(50), default="Pending")
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    incident      = relationship("Incident", back_populates="corrective_actions")
    assigned_user = relationship("User", back_populates="corrective_actions", foreign_keys=[assigned_to])

    @property
    def assignee_name(self):
        if self.assigned_user:
            return self.assigned_user.name
        return f"{self.former_assignee} (deleted user)" if self.former_assignee else None

    @property
    def assignee_role(self):
        return self.assigned_user.role if self.assigned_user else None


# ── SafetyInstruction ────────────────────────────────────────────
class SafetyInstruction(Base):
    __tablename__ = "safety_instructions"

    id          = Column(Integer, primary_key=True, index=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    created_by  = Column(Integer, ForeignKey("users.id"), nullable=True)
    title       = Column(String(255), nullable=False)
    content     = Column(Text)
    category    = Column(String(100), default="procedures")
    # Set when the instruction was published automatically from a safety rule.
    safety_rule_id = Column(Integer, ForeignKey("safety_rules.id", ondelete="CASCADE"), nullable=True, index=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    location         = relationship("Location", back_populates="safety_instructions")
    creator          = relationship("User", back_populates="created_instructions")
    rule             = relationship("SafetyRule", back_populates="instructions")
    acknowledgements = relationship(
        "Acknowledgement",
        back_populates="instruction",
        cascade="all, delete-orphan",
    )


# ── Acknowledgement ──────────────────────────────────────────────
class Acknowledgement(Base):
    __tablename__ = "acknowledgements"
    __table_args__ = (
        UniqueConstraint("instruction_id", "worker_id", name="uq_acknowledgement_instruction_worker"),
    )

    id             = Column(Integer, primary_key=True, index=True)
    instruction_id = Column(Integer, ForeignKey("safety_instructions.id"), nullable=False)
    worker_id      = Column(Integer, ForeignKey("users.id"), nullable=False)
    acknowledged_at = Column(DateTime(timezone=True), server_default=func.now())

    instruction = relationship("SafetyInstruction", back_populates="acknowledgements")
    worker      = relationship("User", back_populates="acknowledgements")


# ── WorkerLocation ───────────────────────────────────────────────
class WorkerLocation(Base):
    __tablename__ = "worker_locations"

    id          = Column(Integer, primary_key=True, index=True)
    worker_id   = Column(Integer, ForeignKey("users.id"), nullable=False)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    assigned_at = Column(DateTime(timezone=True), server_default=func.now())

    worker   = relationship("User", back_populates="assigned_locations", foreign_keys=[worker_id])
    location = relationship("Location", back_populates="worker_locations")


# ── ComplianceRecord ─────────────────────────────────────────────
class ComplianceRecord(Base):
    __tablename__ = "compliance_records"

    # One row per location per day, built from that day's incidents
    # (services/compliance_service.py).  ``officer_id``/``notes`` hold the
    # officer's review; ``status_source`` says whether the officer set the status.
    id          = Column(Integer, primary_key=True, index=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    officer_id  = Column(Integer, ForeignKey("users.id"), nullable=True)
    date        = Column(DateTime(timezone=True), server_default=func.now())
    record_date = Column(Date, nullable=True, index=True)
    violations  = Column(Integer, default=0)
    ppe_violations        = Column(Integer, default=0)
    restricted_violations = Column(Integer, default=0)
    open_incidents        = Column(Integer, default=0)
    actions_total         = Column(Integer, default=0)
    actions_resolved      = Column(Integer, default=0)
    cameras               = Column(Integer, default=0)
    status        = Column(String(50), default="pending")
    auto_status   = Column(String(50), nullable=True)
    status_source = Column(String(20), default="auto")
    summary       = Column(Text, nullable=True)
    notes         = Column(Text, nullable=True)
    reviewed_at   = Column(DateTime(timezone=True), nullable=True)
    updated_at    = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    location = relationship("Location")
    officer  = relationship("User")


# ── Email alert settings (one row) and log ───────────────────────
class AlertSettings(Base):
    __tablename__ = "alert_settings"

    id                 = Column(Integer, primary_key=True)
    # Safety officers get an email for every violation unless an admin changes it.
    email_enabled      = Column(Boolean, default=True, nullable=False)
    min_severity       = Column(String(20), default="LOW", nullable=False)
    email_officers     = Column(Boolean, default=True, nullable=False)
    email_admins       = Column(Boolean, default=False, nullable=False)
    email_workers      = Column(Boolean, default=False, nullable=False)
    extra_recipients   = Column(Text, nullable=True)
    cooldown_minutes   = Column(Integer, default=5, nullable=False)
    attach_snapshot    = Column(Boolean, default=True, nullable=False)
    camera_alerts      = Column(Boolean, default=True, nullable=False)
    daily_summary      = Column(Boolean, default=False, nullable=False)
    daily_summary_hour = Column(Integer, default=18, nullable=False)
    last_summary_date  = Column(Date, nullable=True)
    updated_by         = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at         = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class EmailAlertLog(Base):
    __tablename__ = "email_alert_log"

    id           = Column(Integer, primary_key=True, index=True)
    kind         = Column(String(30), nullable=False)
    subject      = Column(String(255), nullable=False)
    recipients   = Column(Text, nullable=True)
    status       = Column(String(20), nullable=False)
    detail       = Column(Text, nullable=True)
    cooldown_key = Column(String(120), nullable=True, index=True)
    incident_id  = Column(Integer, ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now(), index=True)


# ── Notification ─────────────────────────────────────────────────
class Notification(Base):
    """In-platform alert for one user (incidents, tasks, rules, requests)."""

    __tablename__ = "notifications"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind       = Column(String(50), nullable=False)
    title      = Column(String(255), nullable=False)
    message    = Column(Text, nullable=True)
    severity   = Column(String(20), nullable=True)
    link       = Column(String(255), nullable=True)
    read_at    = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    user = relationship("User", back_populates="notifications")


# ── PasswordResetCode ────────────────────────────────────────────
class PasswordResetCode(Base):
    """One emailed reset code + link token; only hashes are stored."""

    __tablename__ = "password_reset_codes"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    code_hash  = Column(String(128), nullable=False)
    token_hash = Column(String(128), nullable=False, unique=True, index=True)
    attempts   = Column(Integer, default=0, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at    = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="reset_codes")
