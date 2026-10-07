"""Daily compliance records: one row per location per day.

A record summarises that day's incidents at the location:
  * compliant      - no violations were detected (location has cameras),
  * pending        - violations happened and some are not resolved yet,
  * non-compliant  - violations happened; all of them have been handled.
An officer can review a record, add remarks and set the status by hand
(``status_source = "officer"``); later refreshes then keep that status.

Records are refreshed when incidents/corrective actions change, by the
"Generate" button, and by a background scheduler every few minutes.
"""

from __future__ import annotations

from collections import Counter
import csv
import datetime
import io
import logging
import threading
from typing import Iterable, List, Optional

from sqlalchemy.orm import Session

import models


logger = logging.getLogger(__name__)
STATUSES = ("compliant", "non-compliant", "pending")
REFRESH_SECONDS = 300
ITEM_LABELS = {"helmet": "helmet", "vest": "safety vest", "gloves": "gloves"}


def local_tz() -> datetime.tzinfo:
    return datetime.datetime.now().astimezone().tzinfo


def local_today() -> datetime.date:
    return datetime.datetime.now().astimezone().date()


def local_day(value: Optional[datetime.datetime]) -> Optional[datetime.date]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(local_tz()).date()


def _day_incidents(db: Session, location_id: int, day: datetime.date) -> List[models.Incident]:
    # Query a wide window, then match the local day in Python so the result
    # does not depend on how the database stores time zones.
    start = datetime.datetime.combine(day, datetime.time.min, tzinfo=local_tz())
    rows = (
        db.query(models.Incident)
        .filter(
            models.Incident.location_id == location_id,
            models.Incident.detected_at >= start - datetime.timedelta(days=1),
            models.Incident.detected_at < start + datetime.timedelta(days=2),
        )
        .all()
    )
    return [incident for incident in rows if local_day(incident.detected_at) == day]


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _summary(incidents: List[models.Incident], ppe: int, restricted: int, actions_total: int,
             actions_resolved: int, open_count: int, cameras: int) -> str:
    if not incidents:
        return f"No violations detected ({_plural(cameras, 'camera')} monitoring)."
    parts = []
    if ppe:
        missing = Counter(
            item for incident in incidents if incident.violation_type == "PPE_VIOLATION"
            for item in (incident.missing_items or [])
        )
        details = ", ".join(
            f"{ITEM_LABELS.get(item, item)} x{count}" for item, count in missing.most_common()
        )
        parts.append(f"{_plural(ppe, 'PPE violation')}{f' (missing {details})' if details else ''}")
    if restricted:
        parts.append(f"{restricted} restricted-area {'entry' if restricted == 1 else 'entries'}")
    others = len(incidents) - ppe - restricted
    if others:
        parts.append(_plural(others, "other violation"))
    text = "; ".join(parts) + "."
    if actions_total:
        text += f" Corrective actions: {actions_resolved} of {actions_total} resolved."
    else:
        text += " No corrective actions yet."
    if open_count:
        text += f" {_plural(open_count, 'incident')} not resolved."
    return text


def build_record(
    db: Session,
    location: models.Location,
    day: datetime.date,
    *,
    create_empty: bool = True,
) -> Optional[models.ComplianceRecord]:
    """Create or refresh the record for ``location`` on ``day``."""

    db.flush()
    incidents = _day_incidents(db, location.id, day)
    cameras = db.query(models.Camera).filter(models.Camera.location_id == location.id).count()
    existing = (
        db.query(models.ComplianceRecord)
        .filter(
            models.ComplianceRecord.location_id == location.id,
            models.ComplianceRecord.record_date == day,
        )
        .order_by(models.ComplianceRecord.id)
        .all()
    )
    record = existing[0] if existing else None
    for duplicate in existing[1:]:
        # Two threads can create the same day at once; keep the oldest row.
        db.delete(duplicate)
    if record is None and not incidents and not (create_empty and cameras):
        return None

    ppe = sum(1 for incident in incidents if incident.violation_type == "PPE_VIOLATION")
    restricted = sum(1 for incident in incidents if incident.violation_type == "RESTRICTED_ZONE_VIOLATION")
    open_count = sum(1 for incident in incidents if incident.status != "resolved")
    incident_ids = [incident.id for incident in incidents]
    action_statuses = [
        row[0]
        for row in db.query(models.CorrectiveAction.status)
        .filter(models.CorrectiveAction.incident_id.in_(incident_ids))
        .all()
    ] if incident_ids else []
    actions_resolved = sum(1 for status in action_statuses if status == "Resolved")

    if not incidents:
        auto_status = "compliant"
    elif open_count:
        auto_status = "pending"
    else:
        auto_status = "non-compliant"

    if record is None:
        record = models.ComplianceRecord(location_id=location.id, record_date=day, status_source="auto")
        db.add(record)
    record.violations = len(incidents)
    record.ppe_violations = ppe
    record.restricted_violations = restricted
    record.open_incidents = open_count
    record.actions_total = len(action_statuses)
    record.actions_resolved = actions_resolved
    record.cameras = cameras
    record.auto_status = auto_status
    record.summary = _summary(incidents, ppe, restricted, len(action_statuses), actions_resolved, open_count, cameras)
    if record.status_source != "officer":
        record.status_source = "auto"
        record.status = auto_status
    record.updated_at = datetime.datetime.now(datetime.timezone.utc)
    return record


def generate_for_day(
    db: Session,
    day: datetime.date,
    location_id: Optional[int] = None,
) -> List[models.ComplianceRecord]:
    query = db.query(models.Location)
    if location_id is not None:
        query = query.filter(models.Location.id == location_id)
    records = []
    for location in query.order_by(models.Location.id).all():
        record = build_record(db, location, day)
        if record is not None:
            records.append(record)
    db.flush()
    return records


def refresh_for_incidents(db: Session, incidents: Iterable[Optional[models.Incident]]) -> None:
    """Refresh the day records touched by these incidents and commit.

    Called after the caller's own commit; a failure here is logged and never
    undoes the incident or action change that triggered it.
    """

    try:
        seen = set()
        for incident in incidents:
            if incident is None or incident.location_id is None:
                continue
            day = local_day(incident.detected_at) or local_today()
            key = (incident.location_id, day)
            if key in seen:
                continue
            seen.add(key)
            location = db.get(models.Location, incident.location_id)
            if location is not None:
                build_record(db, location, day)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Could not refresh compliance records")


def review_record(
    db: Session,
    record: models.ComplianceRecord,
    reviewer_id: Optional[int],
    status: Optional[str],
    notes: Optional[str],
    notes_given: bool,
) -> models.ComplianceRecord:
    if status is not None:
        if status == "auto":
            record.status_source = "auto"
            record.status = record.auto_status or record.status
        else:
            record.status_source = "officer"
            record.status = status
    if notes_given:
        record.notes = (notes or "").strip() or None
    record.officer_id = reviewer_id
    record.reviewed_at = datetime.datetime.now(datetime.timezone.utc)
    return record


def record_payload(record: models.ComplianceRecord) -> dict:
    return {
        "id": record.id,
        "location_id": record.location_id,
        "location": record.location.name if record.location else "Unknown",
        "record_date": record.record_date.isoformat() if record.record_date else None,
        "date": record.record_date.isoformat() if record.record_date else record.date,
        "violations": record.violations or 0,
        "ppe_violations": record.ppe_violations or 0,
        "restricted_violations": record.restricted_violations or 0,
        "open_incidents": record.open_incidents or 0,
        "actions_total": record.actions_total or 0,
        "actions_resolved": record.actions_resolved or 0,
        "cameras": record.cameras or 0,
        "status": record.status,
        "auto_status": record.auto_status,
        "status_source": record.status_source or "auto",
        "summary": record.summary,
        "notes": record.notes,
        "officer": record.officer.name if record.officer else None,
        "reviewed_at": record.reviewed_at,
        "updated_at": record.updated_at,
    }


def filtered_records(
    db: Session,
    *,
    status: Optional[str] = None,
    location_id: Optional[int] = None,
    date_from: Optional[datetime.date] = None,
    date_to: Optional[datetime.date] = None,
) -> List[models.ComplianceRecord]:
    query = db.query(models.ComplianceRecord)
    if status:
        query = query.filter(models.ComplianceRecord.status == status)
    if location_id is not None:
        query = query.filter(models.ComplianceRecord.location_id == location_id)
    if date_from is not None:
        query = query.filter(models.ComplianceRecord.record_date >= date_from)
    if date_to is not None:
        query = query.filter(models.ComplianceRecord.record_date <= date_to)
    return query.order_by(
        models.ComplianceRecord.record_date.desc(),
        models.ComplianceRecord.location_id,
        models.ComplianceRecord.id.desc(),
    ).all()


def stats(records: List[models.ComplianceRecord]) -> dict:
    counts = Counter(record.status for record in records)
    total = len(records)
    return {
        "compliant": counts.get("compliant", 0),
        "nonCompliant": counts.get("non-compliant", 0),
        "pending": counts.get("pending", 0),
        "total": total,
        "totalViolations": sum(record.violations or 0 for record in records),
        "complianceRate": round(counts.get("compliant", 0) * 100 / total, 1) if total else None,
    }


CSV_COLUMNS = (
    "Date", "Location", "Status", "Status set by", "Violations", "PPE violations",
    "Restricted-area entries", "Unresolved incidents", "Corrective actions",
    "Actions resolved", "Cameras", "Summary", "Officer remarks", "Reviewed by", "Reviewed at",
)


def _cell(value: object) -> object:
    # Stop spreadsheet apps from treating text as a formula.
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def records_csv(records: List[models.ComplianceRecord]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    for record in records:
        reviewed = record.reviewed_at
        if reviewed is not None and reviewed.tzinfo is None:
            reviewed = reviewed.replace(tzinfo=datetime.timezone.utc)
        writer.writerow([_cell(value) for value in (
            record.record_date.isoformat() if record.record_date else "",
            record.location.name if record.location else "Unknown",
            record.status,
            "Officer" if record.status_source == "officer" else "Automatic",
            record.violations or 0,
            record.ppe_violations or 0,
            record.restricted_violations or 0,
            record.open_incidents or 0,
            record.actions_total or 0,
            record.actions_resolved or 0,
            record.cameras or 0,
            record.summary or "",
            record.notes or "",
            record.officer.name if record.officer else "",
            reviewed.astimezone(local_tz()).strftime("%Y-%m-%d %H:%M") if reviewed else "",
        )])
    return buffer.getvalue()


class ComplianceScheduler:
    """Keeps today's and yesterday's records current and runs the daily summary email."""

    def __init__(self, session_factory=None, interval: float = REFRESH_SECONDS) -> None:
        self.session_factory = session_factory
        self.interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def run_once(self) -> None:
        from database import SessionLocal
        from services import alert_email_service

        db = (self.session_factory or SessionLocal)()
        try:
            today = local_today()
            for day in (today - datetime.timedelta(days=1), today):
                generate_for_day(db, day)
            db.commit()
            alert_email_service.maybe_send_daily_summary(db)
        except Exception:
            db.rollback()
            logger.exception("Compliance scheduler run failed")
        finally:
            db.close()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.run_once()
            self._stop.wait(self.interval)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="compliance-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


scheduler = ComplianceScheduler()
