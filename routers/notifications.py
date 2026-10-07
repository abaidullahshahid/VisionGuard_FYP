import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case
from sqlalchemy.orm import Session

from database import get_db
import models
from routers.auth import require_auth
from services.notification_service import notification_payload


router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    payload=Depends(require_auth),
):
    """The signed-in user's notifications: unread first, most severe first."""
    user_id = int(payload.get("sub", 0))
    base = db.query(models.Notification).filter(models.Notification.user_id == user_id)
    severity_rank = case(
        (models.Notification.severity == "CRITICAL", 4),
        (models.Notification.severity == "HIGH", 3),
        (models.Notification.severity == "MEDIUM", 2),
        (models.Notification.severity == "LOW", 1),
        else_=0,
    )
    items = base.order_by(
        models.Notification.read_at.isnot(None),
        case((models.Notification.read_at.is_(None), severity_rank), else_=0).desc(),
        models.Notification.created_at.desc(),
        models.Notification.id.desc(),
    ).limit(limit).all()
    unread = base.filter(models.Notification.read_at.is_(None)).count()
    latest = base.order_by(models.Notification.id.desc()).first()
    return {
        "unread": unread,
        "latest_id": latest.id if latest else 0,
        "items": [notification_payload(item) for item in items],
    }


@router.post("/{notification_id}/read")
def mark_read(notification_id: int, db: Session = Depends(get_db), payload=Depends(require_auth)):
    notification = db.get(models.Notification, notification_id)
    if notification is None or notification.user_id != int(payload.get("sub", 0)):
        raise HTTPException(status_code=404, detail="Notification not found")
    if notification.read_at is None:
        notification.read_at = datetime.datetime.now(datetime.timezone.utc)
        db.commit()
    return {"detail": "Marked as read"}


@router.post("/read-all")
def mark_all_read(db: Session = Depends(get_db), payload=Depends(require_auth)):
    now = datetime.datetime.now(datetime.timezone.utc)
    updated = db.query(models.Notification).filter(
        models.Notification.user_id == int(payload.get("sub", 0)),
        models.Notification.read_at.is_(None),
    ).update({models.Notification.read_at: now}, synchronize_session=False)
    db.commit()
    return {"detail": "All notifications marked as read", "updated": updated}
