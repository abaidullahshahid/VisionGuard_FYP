"""In-platform notifications (UC-09 alerts, task assignments, rule updates).

Helpers here only add rows to the caller's session; the caller commits, so a
notification is saved together with the change that caused it.
"""

from __future__ import annotations

import datetime
import logging
from typing import Iterable, List, Optional, Sequence

from sqlalchemy.orm import Session

import models


logger = logging.getLogger(__name__)
SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
INCIDENT_LABELS = {
    "PPE_VIOLATION": "PPE violation",
    "RESTRICTED_ZONE_VIOLATION": "Restricted zone violation",
}


def notify(
    db: Session,
    user_ids: Iterable[int],
    *,
    kind: str,
    title: str,
    message: Optional[str] = None,
    severity: Optional[str] = None,
    link: Optional[str] = None,
) -> List[models.Notification]:
    created = []
    for user_id in dict.fromkeys(int(value) for value in user_ids):
        notification = models.Notification(
            user_id=user_id,
            kind=kind,
            title=title[:255],
            message=message,
            severity=severity.upper() if severity else None,
            link=link,
        )
        db.add(notification)
        created.append(notification)
    return created


def active_user_ids(db: Session, roles: Sequence[str]) -> List[int]:
    rows = db.query(models.User.id).filter(
        models.User.role.in_(list(roles)),
        models.User.status == "active",
    ).all()
    return [row[0] for row in rows]


def location_worker_ids(db: Session, location_id: Optional[int]) -> List[int]:
    if location_id is None:
        return []
    rows = (
        db.query(models.WorkerLocation.worker_id)
        .join(models.User, models.User.id == models.WorkerLocation.worker_id)
        .filter(
            models.WorkerLocation.location_id == location_id,
            models.User.status == "active",
        )
        .all()
    )
    return [row[0] for row in rows]


def _incident_summary(incident: models.Incident) -> str:
    if incident.violation_type == "RESTRICTED_ZONE_VIOLATION":
        return f"Person entered {incident.zone_name or 'a restricted zone'}"
    items = ", ".join(incident.missing_items or []) or "required PPE"
    return f"Missing {items}"


def notify_new_incident(db: Session, incident: models.Incident) -> None:
    """Alert officers (with the evidence link) and the location's workers."""

    label = INCIDENT_LABELS.get(incident.violation_type, incident.violation_type.replace("_", " ").title())
    location = incident.location_rel.name if incident.location_rel else None
    if location is None and incident.location_id is not None:
        found = db.get(models.Location, incident.location_id)
        location = found.name if found else None
    camera = incident.camera.name if incident.camera else incident.camera_identifier
    where = " · ".join(part for part in (location, camera) if part)
    notify(
        db,
        active_user_ids(db, ["officer"]),
        kind="incident",
        title=f"{label}{f' at {location}' if location else ''}",
        message=f"{_incident_summary(incident)}{f' — {where}' if where else ''}",
        severity=incident.severity_level,
        link=f"/officer/incidents?incident={incident.id}",
    )
    notify(
        db,
        location_worker_ids(db, incident.location_id),
        kind="safety_alert",
        title=f"Safety alert{f' at {location}' if location else ''}",
        message=f"{label} detected. Follow the safety instructions for this area.",
        severity=incident.severity_level,
        link="/worker/instructions",
    )


def notify_action_assigned(db: Session, action: models.CorrectiveAction, incident: models.Incident) -> None:
    assignee = db.get(models.User, action.assigned_to) if action.assigned_to is not None else None
    if assignee is None:
        return
    link = "/worker/tasks" if assignee.role == "worker" else "/officer/actions"
    due = f" Due {action.deadline}." if action.deadline else ""
    notify(
        db,
        [assignee.id],
        kind="task",
        title=f"New corrective action ({action.priority or 'High'} priority)",
        message=f"{action.description or 'Corrective action'} — incident #{incident.id}.{due}",
        severity=action.priority,
        link=link,
    )


def notify_action_updated(
    db: Session,
    action: models.CorrectiveAction,
    changed_by_id: int,
    changed_by_role: str,
) -> None:
    """Tell the other side of the task about a change."""

    if changed_by_role == "worker" or changed_by_id == action.assigned_to:
        recipients = [uid for uid in active_user_ids(db, ["officer"]) if uid != changed_by_id]
        name = action.assignee_name or "The assignee"
        notify(
            db,
            recipients,
            kind="task_update",
            title=f"Corrective action #{action.id}: {action.status}",
            message=f"{name} updated: {action.description or 'corrective action'}",
            link="/officer/actions",
        )
    elif action.assigned_to is not None and action.assigned_to != changed_by_id:
        assignee = db.get(models.User, action.assigned_to)
        if assignee is None:
            return
        notify(
            db,
            [assignee.id],
            kind="task_update",
            title=f"Corrective action #{action.id} updated: {action.status}",
            message=action.description or "Corrective action",
            severity=action.priority,
            link="/worker/tasks" if assignee.role == "worker" else "/officer/actions",
        )


def notify_instruction_published(db: Session, instruction: models.SafetyInstruction) -> None:
    location = instruction.location.name if instruction.location else None
    if location is None and instruction.location_id is not None:
        found = db.get(models.Location, instruction.location_id)
        location = found.name if found else None
    notify(
        db,
        location_worker_ids(db, instruction.location_id),
        kind="instruction",
        title=f"New safety instruction{f' for {location}' if location else ''}",
        message=f"{instruction.title}. Please read and acknowledge it.",
        link="/worker/instructions",
    )


def notify_password_reset_request(db: Session, user: models.User) -> bool:
    """Ask admins to reset a password; skips repeats within 15 minutes."""

    recent = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=15)
    marker = f"({user.email})"
    duplicate = db.query(models.Notification.id).filter(
        models.Notification.kind == "password_reset",
        models.Notification.message.contains(marker),
        models.Notification.created_at >= recent,
    ).first()
    if duplicate is not None:
        return False
    notify(
        db,
        active_user_ids(db, ["admin"]),
        kind="password_reset",
        title="Password reset requested",
        message=f"{user.name} {marker} forgot their password. Set a temporary password in Manage Users.",
        severity="MEDIUM",
        link="/admin/users",
    )
    return True


def notify_camera_unavailable(camera_db_id: int, error: str) -> None:
    """Background-thread hook: tell admins and officers a feed failed."""

    from database import SessionLocal

    db = SessionLocal()
    try:
        camera = db.get(models.Camera, int(camera_db_id))
        if camera is None:
            return
        recent = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)
        title = f"Camera feed unavailable: {camera.name}"
        if db.query(models.Notification.id).filter(
            models.Notification.kind == "camera",
            models.Notification.title == title,
            models.Notification.created_at >= recent,
        ).first() is not None:
            return
        notify(
            db,
            active_user_ids(db, ["admin", "officer"]),
            kind="camera",
            title=title,
            message=f"{error}. Check the camera source in Camera Management.",
            severity="HIGH",
            link="/admin/cameras",
        )
        db.commit()
        from services.alert_email_service import queue_camera_alert

        queue_camera_alert(db, camera.id, error)
    except Exception:
        db.rollback()
        logger.exception("Could not record camera-unavailable notification")
    finally:
        db.close()


def notification_payload(notification: models.Notification) -> dict:
    return {
        "id": notification.id,
        "kind": notification.kind,
        "title": notification.title,
        "message": notification.message,
        "severity": notification.severity,
        "link": notification.link,
        "read": notification.read_at is not None,
        "created_at": notification.created_at,
    }
