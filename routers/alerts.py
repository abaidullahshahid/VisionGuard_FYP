"""Admin Alert Settings: who gets email alerts, and when."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
import models
import schemas
from routers.admin import require_admin
from services import alert_email_service, email_service


router = APIRouter(prefix="/admin/alert-settings", tags=["alerts"])


def _overview(db: Session) -> dict:
    settings = alert_email_service.get_settings(db)
    db.commit()
    log = (
        db.query(models.EmailAlertLog)
        .order_by(models.EmailAlertLog.created_at.desc(), models.EmailAlertLog.id.desc())
        .limit(20)
        .all()
    )
    return {
        "settings": alert_email_service.settings_payload(settings),
        "email_configured": email_service.is_configured(),
        "sender": email_service.sender_address() or None,
        "recipients": alert_email_service.recipient_preview(db, settings),
        "log": [alert_email_service.log_payload(entry) for entry in log],
    }


@router.get("")
def get_alert_settings(db: Session = Depends(get_db), payload=Depends(require_admin)):
    return _overview(db)


@router.put("")
def update_alert_settings(
    body: schemas.AlertSettingsUpdate,
    db: Session = Depends(get_db),
    payload=Depends(require_admin),
):
    severity = body.min_severity.strip().upper()
    if severity not in alert_email_service.SEVERITY_RANK:
        raise HTTPException(status_code=422, detail="Minimum severity must be LOW, MEDIUM, HIGH, or CRITICAL")
    if not 0 <= body.cooldown_minutes <= 1440:
        raise HTTPException(status_code=422, detail="Cooldown must be between 0 and 1440 minutes")
    if not 0 <= body.daily_summary_hour <= 23:
        raise HTTPException(status_code=422, detail="Summary hour must be between 0 and 23")
    valid, invalid = alert_email_service.split_emails(body.extra_recipients)
    if invalid:
        raise HTTPException(status_code=422, detail=f"Not a valid email address: {', '.join(invalid)}")

    settings = alert_email_service.get_settings(db)
    if body.daily_summary_hour != settings.daily_summary_hour or (body.daily_summary and not settings.daily_summary):
        settings.last_summary_date = None
    settings.email_enabled = body.email_enabled
    settings.min_severity = severity
    settings.email_officers = body.email_officers
    settings.email_admins = body.email_admins
    settings.email_workers = body.email_workers
    settings.extra_recipients = ", ".join(valid) or None
    settings.cooldown_minutes = body.cooldown_minutes
    settings.attach_snapshot = body.attach_snapshot
    settings.camera_alerts = body.camera_alerts
    settings.daily_summary = body.daily_summary
    settings.daily_summary_hour = body.daily_summary_hour
    settings.updated_by = int(payload.get("sub", 0)) or None
    db.commit()
    return _overview(db)


def _require_email() -> None:
    if not email_service.is_configured():
        raise HTTPException(
            status_code=400,
            detail="Gmail is not set up. Add SMTP_USERNAME and SMTP_PASSWORD to backend/.env and restart the backend.",
        )


def _result(entry: models.EmailAlertLog) -> dict:
    if entry.status == "skipped":
        raise HTTPException(status_code=400, detail=entry.detail or "Nothing was sent")
    if entry.status == "failed":
        raise HTTPException(status_code=502, detail=f"Gmail refused the email: {entry.detail}")
    return {"detail": f"Sent to {entry.recipients}.", "entry": alert_email_service.log_payload(entry)}


@router.post("/test")
def send_test_alert(db: Session = Depends(get_db), payload=Depends(require_admin)):
    _require_email()
    return _result(alert_email_service.send_test(db))


@router.post("/send-summary")
def send_summary_now(db: Session = Depends(get_db), payload=Depends(require_admin)):
    _require_email()
    return _result(alert_email_service.send_daily_summary(db))
