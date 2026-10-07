"""Deterministic tests for restricted-zone geometry and temporal state.

Run from the backend directory::

    python -m ai_module.test_zone_analyzer
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Type

from .detector import Detection
from .tracker import TrackedPerson
from .zone_analyzer import (
    RestrictedZone,
    ZoneAnalyzer,
    ZoneConfigurationError,
    foot_point,
    load_zones,
)
from .zone_violation_engine import TemporalZoneViolationEngine, ZoneViolationConfig


EXAMPLE_ZONES = Path(__file__).resolve().parent / "Tests" / "zones" / "test_zones.json"


def _person(track_id: int, bbox: list[float]) -> TrackedPerson:
    detection: Detection = {
        "class_id": 6,
        "class_name": "Person",
        "confidence": 0.9,
        "bbox": bbox,
    }
    return TrackedPerson(track_id=track_id, detection=detection)


def _assert_raises(error_type: Type[Exception], action: Callable[[], object]) -> None:
    try:
        action()
    except error_type:
        return
    raise AssertionError(f"Expected {error_type.__name__}")


def run_synthetic_zone_tests() -> None:
    normalized = RestrictedZone(
        zone_id="normalized",
        name="Normalized Area",
        normalized=True,
        polygon=[[0.5, 0.4], [0.9, 0.4], [0.9, 0.9], [0.5, 0.9]],
    )
    pixel = RestrictedZone(
        zone_id="pixel",
        name="Pixel Area",
        normalized=False,
        polygon=[[10, 10], [40, 10], [40, 40], [10, 40]],
    )
    disabled = RestrictedZone(
        zone_id="disabled",
        name="Disabled Area",
        enabled=False,
        normalized=True,
        polygon=[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]],
    )
    analyzer = ZoneAnalyzer([normalized, pixel, disabled])

    # Bottom-center, not whole-box center, is the primary ground point.
    assert foot_point([60, 10, 80, 75]) == (70.0, 75.0)

    resolved = analyzer.resolve_zones(200, 100)
    assert resolved[0].pixel_polygon == (
        (100.0, 40.0),
        (180.0, 40.0),
        (180.0, 90.0),
        (100.0, 90.0),
    )
    assert resolved[1].pixel_polygon == (
        (10.0, 10.0),
        (40.0, 10.0),
        (40.0, 40.0),
        (10.0, 40.0),
    )
    assert len(resolved) == 2  # Disabled zones are not analyzed.

    people = [
        _person(1, [120, 10, 160, 75]),  # foot=(140, 75), normalized zone
        _person(2, [10, 0, 30, 30]),  # foot=(20, 30), pixel zone
        _person(3, [0, 0, 8, 8]),  # outside both zones
    ]
    statuses = {status.track_id: status for status in analyzer.analyze(people, 200, 100)}
    assert statuses[1].inside_zone_ids == ["normalized"]
    assert statuses[2].inside_zone_ids == ["pixel"]
    assert statuses[3].inside_zone_ids == []
    assert analyzer.analyze([], 200, 100) == []

    _assert_raises(
        ZoneConfigurationError,
        lambda: RestrictedZone("bad", "Too few", [[0, 0], [1, 1]]),
    )
    _assert_raises(
        ZoneConfigurationError,
        lambda: RestrictedZone("bad", "No area", [[0, 0], [1, 1], [2, 2]]),
    )
    _assert_raises(
        ZoneConfigurationError,
        lambda: RestrictedZone(
            "bad",
            "Out of normalized range",
            [[0, 0], [1.1, 0], [0, 1]],
            normalized=True,
        ),
    )

    loaded = load_zones(EXAMPLE_ZONES)
    assert loaded and loaded[0].normalized

    config = ZoneViolationConfig(
        confirmation_seconds=1.5,
        exit_grace_seconds=0.5,
        track_expiration_seconds=8.0,
    )

    # A short entry resolves without ever becoming an event.
    engine = TemporalZoneViolationEngine([normalized], config)
    assert not engine.update({}, 0.0).events
    candidate = engine.update({4: ["normalized"]}, 0.0)
    assert [transition.state for transition in candidate.transitions] == ["CANDIDATE"]
    assert not candidate.events
    assert not engine.update({4: ["normalized"]}, 1.0).events
    assert not engine.update({4: []}, 1.1).events
    short_exit = engine.update({4: []}, 1.6)
    assert any(transition.state == "RESOLVED" for transition in short_exit.transitions)
    assert not short_exit.events

    # Confirmation, no duplicates, boundary jitter, genuine exit, then re-entry.
    engine = TemporalZoneViolationEngine([normalized], config)
    engine.update({4: ["normalized"]}, 0.0)
    assert not engine.update({4: ["normalized"]}, 1.49).events
    confirmed = engine.update({4: ["normalized"]}, 1.5)
    assert len(confirmed.events) == 1
    assert confirmed.events[0].duration_seconds == 1.5
    assert json.loads(json.dumps(confirmed.events[0].to_dict()))["confirmed"] is True
    assert not engine.update({4: ["normalized"]}, 2.0).events

    engine.update({4: []}, 2.1)
    jitter = engine.update({4: ["normalized"]}, 2.4)
    assert jitter.snapshots[4].confirmed_zone_ids == ["normalized"]
    assert not jitter.events

    engine.update({4: []}, 3.0)
    exited = engine.update({4: []}, 3.5)
    assert any(transition.state == "RESOLVED" for transition in exited.transitions)
    assert exited.snapshots[4].confirmed_zone_ids == []

    engine.update({4: ["normalized"]}, 4.0)
    reentry = engine.update({4: ["normalized"]}, 5.5)
    assert len(reentry.events) == 1

    # Multiple people and multiple zones are independent pairs.
    engine = TemporalZoneViolationEngine([normalized, pixel], config)
    engine.update({1: ["normalized"], 2: ["pixel"], 3: []}, 0.0)
    multiple = engine.update({1: ["normalized"], 2: ["pixel"], 3: []}, 1.5)
    assert {(event.track_id, event.zone_id) for event in multiple.events} == {
        (1, "normalized"),
        (2, "pixel"),
    }
    assert multiple.active_confirmed_pairs == 2

    print("Synthetic restricted-zone tests passed:")
    print("  - bottom-center foot point")
    print("  - outside and inside polygon")
    print("  - normalized and pixel coordinates")
    print("  - disabled and multiple zones")
    print("  - multiple and zero people")
    print("  - malformed polygon validation")
    print("  - short entry without confirmation")
    print("  - 1.5-second confirmation and event serialization")
    print("  - boundary jitter / 0.5-second exit grace")
    print("  - confirmed exit, deduplication, and re-entry")


def main() -> int:
    try:
        run_synthetic_zone_tests()
        return 0
    except (AssertionError, ValueError) as exc:
        print(f"Restricted-zone test failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

