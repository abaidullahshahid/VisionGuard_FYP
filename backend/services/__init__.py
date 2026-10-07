"""Backend service layer for VisionGuard."""

from .incident_service import DatabaseIncidentSink, persist_incident

__all__ = ["DatabaseIncidentSink", "persist_incident"]
