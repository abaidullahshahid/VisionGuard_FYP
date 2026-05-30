from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Enum
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
    role       = Column(String(50), default="worker", nullable=False)
    status     = Column(String(50), default="active", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    assigned_locations    = relationship("WorkerLocation", back_populates="worker", foreign_keys="WorkerLocation.worker_id")
    corrective_actions    = relationship("CorrectiveAction", back_populates="assigned_user", foreign_keys="CorrectiveAction.assigned_to")
    created_instructions  = relationship("SafetyInstruction", back_populates="creator")
    acknowledgements      = relationship("Acknowledgement", back_populates="worker")


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

    location = relationship("Location", back_populates="cameras")


# ── SafetyRule ───────────────────────────────────────────────────
class SafetyRule(Base):
    __tablename__ = "safety_rules"

    id                 = Column(Integer, primary_key=True, index=True)
    location_id        = Column(Integer, ForeignKey("locations.id"), nullable=False)
    ppe_type           = Column(String(100), nullable=False)
    is_restricted_area = Column(Boolean, default=False)
    severity_level     = Column(String(50), default="High")
    created_at         = Column(DateTime(timezone=True), server_default=func.now())

    location = relationship("Location", back_populates="safety_rules")


# ── Incident ─────────────────────────────────────────────────────
class Incident(Base):
    __tablename__ = "incidents"

    id             = Column(Integer, primary_key=True, index=True)
    camera_id      = Column(Integer, ForeignKey("cameras.id"), nullable=True)
    location_id    = Column(Integer, ForeignKey("locations.id"), nullable=True)
    violation_type = Column(String(150), nullable=False)
    severity_level = Column(String(50), default="Medium")
    status         = Column(String(50), default="open")
    snapshot_url   = Column(String(500), nullable=True)
    detected_at    = Column(DateTime(timezone=True), server_default=func.now())

    camera       = relationship("Camera")
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
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=False)
    description = Column(Text)
    priority    = Column(String(50), default="High")
    deadline    = Column(String(50), nullable=True)
    status      = Column(String(50), default="Pending")
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    incident      = relationship("Incident", back_populates="corrective_actions")
    assigned_user = relationship("User", back_populates="corrective_actions", foreign_keys=[assigned_to])


# ── SafetyInstruction ────────────────────────────────────────────
class SafetyInstruction(Base):
    __tablename__ = "safety_instructions"

    id          = Column(Integer, primary_key=True, index=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    created_by  = Column(Integer, ForeignKey("users.id"), nullable=True)
    title       = Column(String(255), nullable=False)
    content     = Column(Text)
    category    = Column(String(100), default="procedures")
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    location         = relationship("Location", back_populates="safety_instructions")
    creator          = relationship("User", back_populates="created_instructions")
    acknowledgements = relationship("Acknowledgement", back_populates="instruction")


# ── Acknowledgement ──────────────────────────────────────────────
class Acknowledgement(Base):
    __tablename__ = "acknowledgements"

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

    id          = Column(Integer, primary_key=True, index=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    officer_id  = Column(Integer, ForeignKey("users.id"), nullable=True)
    date        = Column(DateTime(timezone=True), server_default=func.now())
    violations  = Column(Integer, default=0)
    status      = Column(String(50), default="pending")
    notes       = Column(Text, nullable=True)

    location = relationship("Location")
    officer  = relationship("User")
