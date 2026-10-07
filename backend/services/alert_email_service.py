"""Email alerts: violations, camera failures and the daily compliance summary.

What is sent, and to whom, comes from the single ``alert_settings`` row that
admins edit in Alert Settings.  Every attempt (sent, failed or skipped) is
written to ``email_alert_log`` so admins can see what happened.

Emails are sent on a background worker so SMTP never slows the AI or the API.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import datetime
import html
import logging
import re
from typing import Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

import models
from services import email_service


logger = logging.getLogger(__name__)
SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
SEVERITY_COLORS = {"LOW": "#2563eb", "MEDIUM": "#d97706", "HIGH": "#dc2626", "CRITICAL": "#991b1b"}
INCIDENT_LABELS = {
    "PPE_VIOLATION": "PPE violation",
    "RESTRICTED_ZONE_VIOLATION": "Restricted zone violation",
}
EMAIL_PATTERN = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
MAX_SNAPSHOT_BYTES = 5 * 1024 * 1024

# Tests set ``run_inline = True`` and their own ``session_factory``.
run_inline = False
session_factory = None
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="email-alerts")


# -- Settings and recipients -------------------------------------------------
def get_settings(db: Session) -> models.AlertSettings:
    settings = db.query(models.AlertSettings).order_by(models.AlertSettings.id).first()
    if settings is None:
        settings = models.AlertSettings(id=1)
        db.add(settings)
        db.flush()
    return settings


def split_emails(value: Optional[str]) -> Tuple[List[str], List[str]]:
    """Return (valid, invalid) addresses from a comma/space/newline list."""

    valid, invalid = [], []
    for part in re.split(r"[\s,;]+", value or ""):
        if not part:
            continue
        (valid if EMAIL_PATTERN.match(part) else invalid).append(part.lower())
    return list(dict.fromkeys(valid)), invalid


def _role_emails(db: Session, role: str) -> List[str]:
    rows = db.query(models.User.email).filter(
        models.User.role == role,
        models.User.status == "active",
    ).order_by(models.User.id).all()
    return [row[0] for row in rows if row[0]]


def _location_worker_emails(db: Session, location_id: Optional[int]) -> List[str]:
    if location_id is None:
        return []
    rows = (
        db.query(models.User.email)
        .join(models.WorkerLocation, models.WorkerLocation.worker_id == models.User.id)
        .filter(
            models.WorkerLocation.location_id == location_id,
            models.User.status == "active",
        )
        .all()
    )
    return [row[0] for row in rows if row[0]]


def staff_recipients(db: Session, settings: models.AlertSettings) -> List[str]:
    """Officers/admins (as configured) plus the extra addresses."""

    emails: List[str] = []
    if settings.email_officers:
        emails += _role_emails(db, "officer")
    if settings.email_admins:
        emails += _role_emails(db, "admin")
    emails += split_emails(settings.extra_recipients)[0]
    return list(dict.fromkeys(email.lower() for email in emails))


def recipient_preview(db: Session, settings: models.AlertSettings) -> dict:
    worker_count = (
        db.query(models.WorkerLocation.worker_id)
        .join(models.User, models.User.id == models.WorkerLocation.worker_id)
        .filter(models.User.status == "active")
        .distinct()
        .count()
    )
    return {
        "officers": _role_emails(db, "officer"),
        "admins": _role_emails(db, "admin"),
        "extra": split_emails(settings.extra_recipients)[0],
        "assigned_workers": worker_count,
        "staff": staff_recipients(db, settings),
    }


def settings_payload(settings: models.AlertSettings) -> dict:
    return {
        "email_enabled": bool(settings.email_enabled),
        "min_severity": settings.min_severity,
        "email_officers": bool(settings.email_officers),
        "email_admins": bool(settings.email_admins),
        "email_workers": bool(settings.email_workers),
        "extra_recipients": settings.extra_recipients or "",
        "cooldown_minutes": settings.cooldown_minutes,
        "attach_snapshot": bool(settings.attach_snapshot),
        "camera_alerts": bool(settings.camera_alerts),
        "daily_summary": bool(settings.daily_summary),
        "daily_summary_hour": settings.daily_summary_hour,
        "last_summary_date": settings.last_summary_date.isoformat() if settings.last_summary_date else None,
        "updated_at": settings.updated_at,
    }


def log_payload(entry: models.EmailAlertLog) -> dict:
    return {
        "id": entry.id,
        "kind": entry.kind,
        "subject": entry.subject,
        "recipients": [part for part in (entry.recipients or "").split(", ") if part],
        "status": entry.status,
        "detail": entry.detail,
        "incident_id": entry.incident_id,
        "created_at": entry.created_at,
    }


def _log(
    db: Session,
    kind: str,
    subject: str,
    recipients: Iterable[str],
    status: str,
    detail: Optional[str] = None,
    *,
    cooldown_key: Optional[str] = None,
    incident_id: Optional[int] = None,
) -> models.EmailAlertLog:
    entry = models.EmailAlertLog(
        kind=kind,
        subject=subject[:255],
        recipients=", ".join(recipients),
        status=status,
        detail=detail,
        cooldown_key=cooldown_key,
        incident_id=incident_id,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def _in_cooldown(db: Session, key: str, minutes: int) -> bool:
    if minutes <= 0:
        return False
    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes)
    return db.query(models.EmailAlertLog.id).filter(
        models.EmailAlertLog.cooldown_key == key,
        models.EmailAlertLog.status == "sent",
        models.EmailAlertLog.created_at >= since,
    ).first() is not None


def _send(recipients: List[str], subject: str, text: str, body_html: str, **extras) -> Optional[str]:
    return email_service.send_email_checked(recipients, subject, text, body_html, **extras)


# -- Email layout ---------------------------------------------------------------
def _local_time(value: Optional[datetime.datetime]) -> str:
    if value is None:
        return "Unknown"
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone().strftime("%d %b %Y, %I:%M:%S %p")


def _page(title: str, color: str, intro: str, rows: List[Tuple[str, str]], extra_html: str = "",
          button: Optional[Tuple[str, str]] = None) -> str:
    table = "".join(
        f'<tr><td style="padding:7px 12px;color:#64748b;width:130px">{html.escape(label)}</td>'
        f'<td style="padding:7px 12px;color:#0f172a;font-weight:600">{html.escape(value)}</td></tr>'
        for label, value in rows
    )
    action = (
        f'<p style="margin:22px 0 4px"><a href="{html.escape(button[1])}" style="background:#2563eb;color:#ffffff;'
        f'padding:11px 20px;border-radius:8px;text-decoration:none;font-weight:600">{html.escape(button[0])}</a></p>'
        if button else ""
    )
    return f"""<div style="font-family:Arial,Helvetica,sans-serif;max-width:620px;margin:auto;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden">
  <div style="background:{color};color:#ffffff;padding:16px 22px;font-size:18px;font-weight:700">{html.escape(title)}</div>
  <div style="padding:20px 22px">
    <p style="margin:0 0 14px;color:#0f172a">{html.escape(intro)}</p>
    <table style="border-collapse:collapse;width:100%;background:#f8fafc;border-radius:8px">{table}</table>
    {extra_html}
    {action}
    <p style="margin-top:22px;color:#94a3b8;font-size:12px">Sent by VisionGuard Smart Workplace Safety. Alert settings are managed by your administrator.</p>
  </div>
</div>"""


def _incident_details(db: Session, incident: models.Incident) -> dict:
    label = INCIDENT_LABELS.get(incident.violation_type, incident.violation_type.replace("_", " ").title())
    location = incident.location_rel.name if incident.location_rel else None
    if location is None and incident.location_id is not None:
        found = db.get(models.Location, incident.location_id)
        location = found.name if found else None
    camera = incident.camera.name if incident.camera else (incident.camera_identifier or "Unknown")
    if incident.violation_type == "RESTRICTED_ZONE_VIOLATION":
        detail = f"Person entered {incident.zone_name or 'a restricted area'}"
    else:
        detail = "Missing " + (", ".join(incident.missing_items or []) or "required PPE")
    return {
        "label": label,
        "location": location or "Unknown location",
        "camera": camera,
        "detail": detail,
        "severity": (incident.severity_level or "MEDIUM").upper(),
        "time": _local_time(incident.detected_at),
    }


def _snapshot(incident: models.Incident) -> Optional[bytes]:
    if not incident.evidence_path:
        return None
    try:
        from services.incident_service import resolve_evidence_file

        path = resolve_evidence_file(incident.evidence_path)
        if path.stat().st_size > MAX_SNAPSHOT_BYTES:
            return None
        return path.read_bytes()
    except Exception:
        logger.warning("Snapshot for incident %s could not be attached", incident.id)
        return None


# -- Violation alerts ------------------------------------------------------------
def send_incident_alert(db: Session, incident_id: int) -> List[models.EmailAlertLog]:
    """Email one incident according to the alert settings."""

    if not email_service.is_configured():
        return []
    settings = get_settings(db)
    incident = db.get(models.Incident, incident_id)
    if incident is None or not settings.email_enabled:
        return []
    info = _incident_details(db, incident)
    if SEVERITY_RANK.get(info["severity"], 2) < SEVERITY_RANK.get(settings.min_severity, 3):
        return []

    subject = f"[VisionGuard] {info['severity']}: {info['label']} at {info['location']}"
    key = f"incident:{incident.location_id}:{incident.violation_type}"
    staff = staff_recipients(db, settings)
    workers = list(dict.fromkeys(
        email.lower() for email in _location_worker_emails(db, incident.location_id)
    )) if settings.email_workers else []
    workers = [email for email in workers if email not in staff]
    if not staff and not workers:
        return [_log(db, "incident", subject, [], "skipped", "No recipients are selected in Alert Settings.",
                     incident_id=incident.id)]
    if _in_cooldown(db, key, settings.cooldown_minutes):
        return [_log(db, "incident", subject, staff + workers, "skipped",
                     f"Same violation at this location was emailed less than {settings.cooldown_minutes} min ago.",
                     incident_id=incident.id)]

    base = email_service.frontend_url()
    rows = [
        ("Violation", info["label"]),
        ("Severity", info["severity"]),
        ("Location", info["location"]),
        ("Camera", info["camera"]),
        ("Detected", info["time"]),
        ("Details", info["detail"]),
        ("Incident", f"#{incident.id}"),
    ]
    logs = []
    if staff:
        link = f"{base}/officer/incidents?incident={incident.id}"
        snapshot = _snapshot(incident) if settings.attach_snapshot else None
        image_html = (
            '<p style="margin:18px 0 6px;color:#64748b">Snapshot</p>'
            '<img src="cid:snapshot" alt="Incident snapshot" style="max-width:100%;border-radius:8px;border:1px solid #e2e8f0">'
            if snapshot else ""
        )
        text = (
            "VisionGuard detected a safety violation.\n\n"
            + "\n".join(f"{label}: {value}" for label, value in rows)
            + f"\n\nOpen the incident (login required): {link}\n"
        )
        body = _page(
            f"{info['severity']} · {info['label']}",
            SEVERITY_COLORS.get(info["severity"], "#dc2626"),
            "VisionGuard detected a safety violation that needs attention.",
            rows,
            image_html,
            ("Open incident", link),
        )
        error = _send(staff, subject, text, body, inline_image=(snapshot, "snapshot") if snapshot else None)
        logs.append(_log(db, "incident", subject, staff, "failed" if error else "sent", error,
                         cooldown_key=key, incident_id=incident.id))
    if workers:
        worker_subject = f"[VisionGuard] Safety alert at {info['location']}"
        link = f"{base}/worker/instructions"
        worker_rows = [("Location", info["location"]), ("Alert", info["label"]), ("Time", info["time"])]
        text = (
            f"Safety alert at {info['location']}: {info['label']} detected at {info['time']}.\n"
            f"Please follow the safety instructions for this area: {link}\n"
        )
        body = _page(
            "Safety alert", SEVERITY_COLORS.get(info["severity"], "#dc2626"),
            "A safety violation was detected at your work location. Please follow the safety instructions for this area.",
            worker_rows, "", ("View safety instructions", link),
        )
        error = _send(workers, worker_subject, text, body)
        logs.append(_log(db, "worker_alert", worker_subject, workers, "failed" if error else "sent", error,
                         cooldown_key=key + ":workers", incident_id=incident.id))
    return logs


def send_camera_alert(db: Session, camera_id: int, error_text: str) -> Optional[models.EmailAlertLog]:
    if not email_service.is_configured():
        return None
    settings = get_settings(db)
    camera = db.get(models.Camera, camera_id)
    if camera is None or not settings.email_enabled or not settings.camera_alerts:
        return None
    subject = f"[VisionGuard] Camera feed unavailable: {camera.name}"
    key = f"camera:{camera.id}"
    staff = staff_recipients(db, settings)
    if not staff:
        return None
    if _in_cooldown(db, key, max(settings.cooldown_minutes, 30)):
        return None
    location = camera.location.name if camera.location else "No location"
    rows = [("Camera", camera.name), ("Location", location), ("Problem", error_text), ("Time", _local_time(datetime.datetime.now(datetime.timezone.utc)))]
    link = f"{email_service.frontend_url()}/admin/cameras"
    text = "A VisionGuard camera feed stopped working.\n\n" + "\n".join(f"{a}: {b}" for a, b in rows) + f"\n\nCheck it in Camera Management: {link}\n"
    body = _page("Camera feed unavailable", "#475569",
                 "A camera stopped sending video, so this area is not being monitored.",
                 rows, "", ("Open Camera Management", link))
    error = _send(staff, subject, text, body)
    return _log(db, "camera", subject, staff, "failed" if error else "sent", error, cooldown_key=key)


# -- Daily compliance summary -------------------------------------------------------
def send_daily_summary(db: Session, day: Optional[datetime.date] = None) -> models.EmailAlertLog:
    from services import compliance_service

    settings = get_settings(db)
    day = day or compliance_service.local_today()
    compliance_service.generate_for_day(db, day)
    db.commit()
    records = compliance_service.filtered_records(db, date_from=day, date_to=day)
    totals = compliance_service.stats(records)
    subject = f"[VisionGuard] Daily compliance summary - {day.strftime('%d %b %Y')}"
    staff = staff_recipients(db, settings)
    if not staff:
        return _log(db, "summary", subject, [], "skipped", "No recipients are selected in Alert Settings.")
    if not email_service.is_configured():
        return _log(db, "summary", subject, staff, "failed", "Gmail is not set up.")

    rate = f"{totals['complianceRate']}%" if totals["complianceRate"] is not None else "No records"
    rows = [
        ("Date", day.strftime("%A, %d %b %Y")),
        ("Locations", str(totals["total"])),
        ("Compliant", str(totals["compliant"])),
        ("Pending", str(totals["pending"])),
        ("Non-compliant", str(totals["nonCompliant"])),
        ("Violations", str(totals["totalViolations"])),
        ("Compliance rate", rate),
    ]
    colors = {"compliant": "#16a34a", "pending": "#d97706", "non-compliant": "#dc2626"}
    location_rows = "".join(
        f'<tr><td style="padding:7px 10px;border-top:1px solid #e2e8f0">{html.escape(record.location.name if record.location else "Unknown")}</td>'
        f'<td style="padding:7px 10px;border-top:1px solid #e2e8f0;color:{colors.get(record.status, "#475569")};font-weight:700">{html.escape(record.status)}</td>'
        f'<td style="padding:7px 10px;border-top:1px solid #e2e8f0;text-align:center">{record.violations or 0}</td>'
        f'<td style="padding:7px 10px;border-top:1px solid #e2e8f0;color:#475569;font-size:13px">{html.escape(record.summary or "")}</td></tr>'
        for record in records
    )
    location_html = (
        '<p style="margin:18px 0 6px;color:#64748b">By location</p>'
        '<table style="border-collapse:collapse;width:100%;font-size:14px">'
        '<tr style="background:#f1f5f9"><th align="left" style="padding:7px 10px">Location</th><th align="left" style="padding:7px 10px">Status</th>'
        '<th style="padding:7px 10px">Violations</th><th align="left" style="padding:7px 10px">Summary</th></tr>'
        f"{location_rows}</table>"
        if records else '<p style="color:#64748b">No monitored locations had records for this day.</p>'
    )
    link = f"{email_service.frontend_url()}/officer/compliance"
    text = (
        f"VisionGuard daily compliance summary for {day.isoformat()}\n\n"
        + "\n".join(f"{a}: {b}" for a, b in rows)
        + "\n\n"
        + "\n".join(
            f"- {record.location.name if record.location else 'Unknown'}: {record.status} ({record.violations or 0} violations) {record.summary or ''}"
            for record in records
        )
        + f"\n\nFull records: {link}\nThe CSV file is attached.\n"
    )
    body = _page("Daily compliance summary", "#0f766e",
                 "Here is today's safety compliance for each monitored location.",
                 rows, location_html, ("Open Compliance Records", link))
    csv_bytes = compliance_service.records_csv(records).encode("utf-8-sig")
    error = _send(staff, subject, text, body,
                  attachments=[(f"visionguard-compliance-{day.isoformat()}.csv", csv_bytes, "text/csv")])
    return _log(db, "summary", subject, staff, "failed" if error else "sent", error)


def maybe_send_daily_summary(db: Session, now: Optional[datetime.datetime] = None) -> Optional[models.EmailAlertLog]:
    """Called by the scheduler: send once a day after the chosen hour."""

    if not email_service.is_configured():
        return None
    settings = get_settings(db)
    if not (settings.email_enabled and settings.daily_summary):
        db.commit()
        return None
    now = now or datetime.datetime.now().astimezone()
    if now.hour < settings.daily_summary_hour or settings.last_summary_date == now.date():
        return None
    settings.last_summary_date = now.date()
    db.commit()
    return send_daily_summary(db, now.date())


def send_test(db: Session) -> models.EmailAlertLog:
    settings = get_settings(db)
    staff = staff_recipients(db, settings)
    subject = "[VisionGuard] Test alert"
    if not staff:
        return _log(db, "test", subject, [], "skipped", "No recipients are selected in Alert Settings.")
    rows = [
        ("Status", "Email alerts are on" if settings.email_enabled else "Email alerts are OFF (only this test was sent)"),
        ("Minimum severity", settings.min_severity),
        ("Sender", email_service.sender_address() or "Not set"),
        ("Time", _local_time(datetime.datetime.now(datetime.timezone.utc))),
    ]
    text = "This is a VisionGuard test alert. If you can read this, email alerts reach you.\n\n" + "\n".join(f"{a}: {b}" for a, b in rows)
    body = _page("Test alert", "#2563eb", "If you can read this, VisionGuard email alerts reach you.", rows)
    error = _send(staff, subject, text, body)
    return _log(db, "test", subject, staff, "failed" if error else "sent", error)


# -- Background queue ------------------------------------------------------------------
def _run(bind, job, *args) -> None:
    from database import SessionLocal

    factory = session_factory or (lambda: Session(bind=bind, autoflush=False) if bind is not None else SessionLocal())
    db = factory()
    try:
        job(db, *args)
    except Exception:
        db.rollback()
        logger.exception("Email alert job failed")
    finally:
        db.close()


def _alerts_on(db: Session) -> bool:
    """Checked in the caller's session so nothing is queued while alerts are off."""

    if not email_service.is_configured():
        return False
    try:
        settings = db.query(models.AlertSettings).order_by(models.AlertSettings.id).first()
    except Exception:
        db.rollback()
        return False
    # No row yet means the defaults: alerts on.
    return True if settings is None else bool(settings.email_enabled)


def _submit(db: Session, job, *args) -> None:
    if not _alerts_on(db):
        return
    bind = db.get_bind()
    if run_inline:
        _run(bind, job, *args)
    else:
        _executor.submit(_run, bind, job, *args)


def queue_incident_alert(db: Session, incident_id: Optional[int]) -> None:
    if incident_id is not None:
        _submit(db, send_incident_alert, int(incident_id))


def queue_camera_alert(db: Session, camera_id: int, error_text: str) -> None:
    _submit(db, send_camera_alert, int(camera_id), error_text)
