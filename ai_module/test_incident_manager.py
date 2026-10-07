"""Deterministic tests for incident severity, evidence, and deduplication.

Run from the backend directory::

    python -m ai_module.test_incident_manager
"""

from __future__ import annotations

import json
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from uuid import uuid4

import numpy as np

from .incident_manager import (
    PPE_VIOLATION,
    RESTRICTED_ZONE_VIOLATION,
    IncidentManager,
    classify_severity,
)
from .violation_engine import ViolationEvent
from .zone_violation_engine import ZoneViolationEvent


@contextmanager
def _writable_test_directory() -> Iterator[Path]:
    parent = Path(__file__).resolve().parent / "output"
    parent.mkdir(parents=True, exist_ok=True)
    path = parent / f"incident_manager_test_{uuid4()}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _ppe_event(
    missing_items: tuple[str, ...],
    timestamp: str,
    stream_time: float,
    confirmed: bool = True,
) -> ViolationEvent:
    return ViolationEvent(
        track_id=7,
        missing_items=missing_items,
        stream_time_seconds=stream_time,
        duration_seconds=2.0,
        item_durations_seconds={item: 2.0 for item in missing_items},
        timestamp=timestamp,
        confirmed=confirmed,
    )


def run_synthetic_incident_tests() -> None:
    assert classify_severity(PPE_VIOLATION, ["gloves"]) == "LOW"
    assert classify_severity(PPE_VIOLATION, ["vest"]) == "MEDIUM"
    assert classify_severity(PPE_VIOLATION, ["helmet"]) == "HIGH"
    assert classify_severity(PPE_VIOLATION, ["helmet", "gloves"]) == "HIGH"
    assert classify_severity(PPE_VIOLATION, ["vest", "gloves"]) == "MEDIUM"
    assert classify_severity(PPE_VIOLATION, ["helmet", "vest", "gloves"]) == "HIGH"
    assert classify_severity(RESTRICTED_ZONE_VIOLATION) == "HIGH"

    frame = np.zeros((120, 180, 3), dtype=np.uint8)
    frame[20:100, 30:150] = (40, 120, 220)

    with _writable_test_directory() as temporary_directory:
        manager = IncidentManager(
            camera_id="test_camera_1",
            evidence_root=temporary_directory,
        )
        first_event = _ppe_event(
            ("gloves",),
            "2026-10-04T10:00:00+00:00",
            4.2,
        )
        first = manager.create_incident(first_event, frame)
        assert first is not None
        assert first.severity == "LOW"
        assert first.zone_id is None and first.zone_name is None
        assert first.missing_items == ("gloves",)
        assert first.camera_id == "test_camera_1"
        assert first.evidence_path is not None

        first_path = Path(first.evidence_path)
        assert first_path.is_file()

        # Exact resubmission is rejected and creates no extra snapshot.
        assert manager.create_incident(first_event, frame) is None
        assert len(list(Path(temporary_directory).rglob("*.jpg"))) == 1

        # Candidate events never become incidents or snapshots.
        candidate = _ppe_event(
            ("helmet",),
            "2026-10-04T10:00:00.500000+00:00",
            4.7,
            confirmed=False,
        )
        assert manager.create_incident(candidate, frame) is None
        assert len(list(Path(temporary_directory).rglob("*.jpg"))) == 1

        # A later episode with the same rule/track remains legitimate.
        later_event = _ppe_event(
            ("gloves",),
            "2026-10-04T10:01:00+00:00",
            64.2,
        )
        later = manager.create_incident(
            later_event,
            frame,
            metadata={
                "numpy_scalar": np.int64(3),
                "floating_duration": np.float64(1.9999999999999996),
            },
        )
        assert later is not None
        assert later.incident_id != first.incident_id
        assert later.evidence_path != first.evidence_path
        assert later.metadata["numpy_scalar"] == 3
        assert later.to_dict()["metadata"]["floating_duration"] == 2.0

        zone_event = ZoneViolationEvent(
            track_id=26,
            zone_id="zone_1",
            zone_name="Restricted Area",
            timestamp="2026-10-04T10:02:00+00:00",
            stream_time_seconds=123.5,
            duration_seconds=1.5,
        )
        zone = manager.create_incident(zone_event, frame)
        assert zone is not None
        assert zone.severity == "HIGH"
        assert zone.missing_items == ()
        assert zone.zone_id == "zone_1" and zone.zone_name == "Restricted Area"

        snapshots = list(Path(temporary_directory).rglob("*.jpg"))
        assert len(snapshots) == 3
        assert len({snapshot.name for snapshot in snapshots}) == 3

        payload = manager.incidents_as_dicts()
        assert len(payload) == 3
        serialized = json.dumps(payload)
        assert json.loads(serialized)[0]["zone_id"] is None
        assert json.loads(serialized)[2]["missing_items"] == []

        report_path = manager.save_report(Path(temporary_directory) / "incidents.json")
        assert report_path.is_file()
        assert len(json.loads(report_path.read_text(encoding="utf-8"))) == 3

    print("Synthetic incident-manager tests passed:")
    print("  - gloves LOW, vest MEDIUM, helmet HIGH")
    print("  - helmet combinations HIGH and vest+gloves MEDIUM")
    print("  - restricted-zone HIGH")
    print("  - confirmed-only snapshot creation")
    print("  - unique evidence filenames")
    print("  - JSON serialization and optional/null fields")
    print("  - defensive duplicate rejection")
    print("  - later legitimate incident accepted")


def main() -> int:
    try:
        run_synthetic_incident_tests()
        return 0
    except (AssertionError, ValueError, RuntimeError) as exc:
        print(f"Incident-manager test failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

