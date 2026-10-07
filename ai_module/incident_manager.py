"""Convert confirmed VisionGuard AI events into standardized incidents."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union
from uuid import uuid4

import cv2
import numpy as np

from .violation_engine import ViolationEvent
from .zone_violation_engine import ZoneViolationEvent


PPE_VIOLATION = "PPE_VIOLATION"
RESTRICTED_ZONE_VIOLATION = "RESTRICTED_ZONE_VIOLATION"
SEVERITY_ORDER: Tuple[str, ...] = ("LOW", "MEDIUM", "HIGH")
EVIDENCE_ROOT = Path(__file__).resolve().parent / "evidence"

ConfirmedEvent = Union[ViolationEvent, ZoneViolationEvent]


class IncidentManagerError(RuntimeError):
    """Raised when a confirmed event cannot be converted into an incident."""


def highest_severity(severities: Iterable[str]) -> str:
    """Return the highest value from the ordered LOW/MEDIUM/HIGH policy."""

    values = [str(value).upper() for value in severities]
    if not values:
        raise ValueError("At least one severity value is required")
    unknown = set(values).difference(SEVERITY_ORDER)
    if unknown:
        raise ValueError(f"Unsupported severity value(s): {', '.join(sorted(unknown))}")
    return max(values, key=SEVERITY_ORDER.index)


def classify_severity(incident_type: str, missing_items: Iterable[str] = ()) -> str:
    """Apply deterministic VisionGuard policy; detection confidence is irrelevant."""

    normalized_type = str(incident_type).strip().upper()
    if normalized_type == RESTRICTED_ZONE_VIOLATION:
        return "HIGH"
    if normalized_type != PPE_VIOLATION:
        raise ValueError(f"Unsupported incident type: {incident_type}")

    items = {str(item).strip().lower() for item in missing_items}
    unknown = items.difference({"helmet", "vest", "gloves"})
    if unknown:
        raise ValueError(f"Unsupported PPE item(s): {', '.join(sorted(unknown))}")
    if not items:
        raise ValueError("A PPE violation must contain at least one missing item")

    applicable: List[str] = []
    if "helmet" in items:
        applicable.append("HIGH")
    if items == {"gloves"}:
        applicable.append("LOW")
    if items == {"vest"} or (len(items) >= 2 and "helmet" not in items):
        applicable.append("MEDIUM")
    if items == {"helmet", "vest", "gloves"}:
        applicable.append("HIGH")
    return highest_severity(applicable)


@dataclass(frozen=True)
class Incident:
    """JSON-safe standardized incident produced from one confirmed event."""

    incident_id: str
    incident_type: str
    track_id: int
    timestamp: str
    stream_time_seconds: float
    severity: str
    camera_id: Optional[str]
    missing_items: Tuple[str, ...] = field(default_factory=tuple)
    zone_id: Optional[str] = None
    zone_name: Optional[str] = None
    evidence_path: Optional[str] = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "incident_id": self.incident_id,
            "incident_type": self.incident_type,
            "track_id": int(self.track_id),
            "timestamp": self.timestamp,
            "stream_time_seconds": round(float(self.stream_time_seconds), 6),
            "severity": self.severity,
            "camera_id": self.camera_id,
            "missing_items": list(self.missing_items),
            "zone_id": self.zone_id,
            "zone_name": self.zone_name,
            "evidence_path": self.evidence_path,
            "metadata": _json_safe(dict(self.metadata)),
        }


class IncidentManager:
    """Save evidence and create one incident per unique confirmed AI event."""

    def __init__(
        self,
        camera_id: Optional[str] = None,
        evidence_root: Optional[Union[str, Path]] = None,
        jpeg_quality: int = 92,
    ) -> None:
        self.camera_id = str(camera_id).strip() if camera_id is not None else None
        if self.camera_id == "":
            self.camera_id = None
        self.evidence_root = Path(evidence_root or EVIDENCE_ROOT).expanduser().resolve()
        self.jpeg_quality = int(jpeg_quality)
        if not 0 <= self.jpeg_quality <= 100:
            raise ValueError("jpeg_quality must be between 0 and 100")
        self._fingerprints: set[str] = set()
        self._incidents: List[Incident] = []

    @property
    def incidents(self) -> Tuple[Incident, ...]:
        return tuple(self._incidents)

    def reset(self) -> None:
        """Start a new processing session without deleting saved evidence."""

        self._fingerprints.clear()
        self._incidents.clear()

    def create_incident(
        self,
        event: ConfirmedEvent,
        evidence_frame: np.ndarray,
        metadata: Optional[Mapping[str, object]] = None,
    ) -> Optional[Incident]:
        """Return a new incident, or ``None`` for an exact duplicate event."""

        if not bool(getattr(event, "confirmed", False)):
            return None
        event_type = str(getattr(event, "event_type", "")).upper()
        if event_type not in {PPE_VIOLATION, RESTRICTED_ZONE_VIOLATION}:
            raise IncidentManagerError(f"Unsupported confirmed event type: {event_type or '(empty)'}")

        fingerprint = self._fingerprint(event)
        if fingerprint in self._fingerprints:
            return None

        track_id = int(event.track_id)
        timestamp = str(event.timestamp)
        stream_time = float(event.stream_time_seconds)
        duration = float(event.duration_seconds)
        if not math.isfinite(stream_time) or not math.isfinite(duration):
            raise IncidentManagerError("Event time and duration must be finite")

        if event_type == PPE_VIOLATION:
            missing_items = tuple(sorted({str(item).lower() for item in event.missing_items}))
            zone_id = None
            zone_name = None
            event_metadata: Dict[str, object] = {
                "confirmation_duration_seconds": duration,
                "item_durations_seconds": dict(event.item_durations_seconds),
            }
        else:
            missing_items = ()
            zone_id = str(event.zone_id)
            zone_name = str(event.zone_name)
            event_metadata = {"confirmation_duration_seconds": duration}

        if metadata:
            event_metadata.update(dict(metadata))
        severity = classify_severity(event_type, missing_items)
        incident_id, evidence_path = self._save_evidence(
            event_type,
            track_id,
            timestamp,
            evidence_frame,
        )
        incident = Incident(
            incident_id=incident_id,
            incident_type=event_type,
            track_id=track_id,
            timestamp=timestamp,
            stream_time_seconds=stream_time,
            severity=severity,
            camera_id=self.camera_id,
            missing_items=missing_items,
            zone_id=zone_id,
            zone_name=zone_name,
            evidence_path=str(evidence_path),
            metadata=_json_safe(event_metadata),
        )
        # Serialize before accepting the incident so callers never receive a
        # payload containing NumPy values or other unsupported objects.
        json.dumps(incident.to_dict())
        self._fingerprints.add(fingerprint)
        self._incidents.append(incident)
        return incident

    def create_incidents(
        self,
        events: Sequence[ConfirmedEvent],
        evidence_frame: np.ndarray,
        metadata: Optional[Mapping[str, object]] = None,
    ) -> List[Incident]:
        created: List[Incident] = []
        for event in events:
            incident = self.create_incident(event, evidence_frame, metadata)
            if incident is not None:
                created.append(incident)
        return created

    def incidents_as_dicts(self) -> List[Dict[str, object]]:
        return [incident.to_dict() for incident in self._incidents]

    def save_report(self, output_path: Union[str, Path]) -> Path:
        """Save the current session's ``list[dict]`` incident report as JSON."""

        path = Path(output_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("w", encoding="utf-8") as file:
                json.dump(self.incidents_as_dicts(), file, indent=2, ensure_ascii=False)
                file.write("\n")
        except OSError as exc:
            raise IncidentManagerError(f"Could not save incident report {path}: {exc}") from exc
        return path

    def _save_evidence(
        self,
        incident_type: str,
        track_id: int,
        timestamp: str,
        frame: np.ndarray,
    ) -> Tuple[str, Path]:
        if not isinstance(frame, np.ndarray) or frame.size == 0:
            raise IncidentManagerError("Evidence frame must be a non-empty NumPy image")

        event_time = _parse_timestamp(timestamp)
        date_directory = self.evidence_root / event_time.date().isoformat()
        try:
            date_directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise IncidentManagerError(
                f"Could not create evidence directory {date_directory}: {exc}"
            ) from exc
        safe_type = re.sub(r"[^A-Z0-9_-]+", "_", incident_type.upper())
        timestamp_part = event_time.strftime("%Y%m%dT%H%M%S_%fZ")

        while True:
            incident_id = str(uuid4())
            filename = f"{safe_type}_track_{track_id}_{timestamp_part}_{incident_id}.jpg"
            path = (date_directory / filename).resolve()
            if not path.exists():
                break

        try:
            saved = cv2.imwrite(
                str(path),
                frame,
                [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality],
            )
        except cv2.error as exc:
            raise IncidentManagerError(f"OpenCV could not save evidence {path}: {exc}") from exc
        if not saved:
            raise IncidentManagerError(f"OpenCV could not save evidence: {path}")
        return incident_id, path

    @staticmethod
    def _fingerprint(event: ConfirmedEvent) -> str:
        payload = {
            "event_type": str(event.event_type),
            "track_id": int(event.track_id),
            "timestamp": str(event.timestamp),
            "stream_time_seconds": round(float(event.stream_time_seconds), 6),
            "missing_items": sorted(str(item) for item in getattr(event, "missing_items", ())),
            "zone_id": getattr(event, "zone_id", None),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def _parse_timestamp(timestamp: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except ValueError:
        parsed = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _json_safe(value: object) -> object:
    """Recursively convert common scalar/container values to JSON built-ins."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise IncidentManagerError("Metadata float values must be finite")
        return round(value, 6)
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    raise IncidentManagerError(f"Metadata value is not JSON serializable: {type(value).__name__}")

