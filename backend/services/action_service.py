"""Corrective-action rules shared by the officer and worker APIs (UC-13)."""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

import models


TASK_STATUSES = ("Pending", "In Progress", "Resolved")


def sync_incident_status(db: Session, incident: Optional[models.Incident]) -> None:
    """Keep an incident's status in step with its corrective actions.

    Any unresolved action means the incident is being handled (in progress);
    once every action is resolved the incident is resolved.  Incidents with
    no actions are left to the officer.
    """

    if incident is None:
        return
    db.flush()
    statuses = [
        row[0]
        for row in db.query(models.CorrectiveAction.status)
        .filter(models.CorrectiveAction.incident_id == incident.id)
        .all()
    ]
    if not statuses:
        return
    if all(status == "Resolved" for status in statuses):
        incident.status = "resolved"
    else:
        incident.status = "in_progress"
