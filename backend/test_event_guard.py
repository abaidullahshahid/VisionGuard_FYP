"""Tests for false-person filtering and repeat-incident suppression (no YOLO).

Run:
    python test_event_guard.py
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from ai_module.event_guard import RepeatEventGuard
from ai_module.realtime_pipeline import RealtimePPEPipeline
from ai_module.violation_engine import TemporalViolationEngine, ViolationEngineConfig
from ai_module.zone_analyzer import RestrictedZone
from ai_module.zone_violation_engine import ZoneViolationConfig
from services.restricted_zone_service import FULL_FRAME_POLYGON


def zone_event(track_id, zone_id="location-1"):
    return SimpleNamespace(track_id=track_id, zone_id=zone_id, missing_items=())


def ppe_event(track_id, *items):
    return SimpleNamespace(track_id=track_id, missing_items=tuple(items))


LEFT = [10, 10, 60, 110]
LEFT_MOVED = [30, 12, 80, 112]
RIGHT = [300, 10, 350, 110]


def guard_tests() -> None:
    guard = RepeatEventGuard(window_seconds=20.0)
    assert guard.filter([zone_event(1)], {1: LEFT}, 0.0)                  # first entry reported
    assert not guard.filter([zone_event(1)], {1: LEFT}, 12.0)             # same ID re-confirmed
    assert not guard.filter([zone_event(2)], {2: LEFT_MOVED}, 15.0)       # ID 1 vanished, new ID nearby
    assert guard.filter([zone_event(3)], {2: LEFT_MOVED, 3: RIGHT}, 16.0)  # a second, separate person
    assert not guard.filter([zone_event(4)], {3: RIGHT, 4: RIGHT}, 17.0)   # duplicate box on person 3
    assert guard.filter([zone_event(1, "zone-9")], {1: LEFT}, 17.5)        # different zone is new

    # Report stays open while the person is visible, then expires 20 s after last seen.
    for second in range(18, 60, 5):
        guard.filter([], {2: LEFT_MOVED}, float(second))
    assert not guard.filter([zone_event(2)], {2: LEFT_MOVED}, 60.0)
    assert guard.filter([zone_event(2)], {2: LEFT_MOVED}, 81.0)           # left 21 s ago: new visit

    # A vanished person far from where a new ID appears is a different person.
    guard = RepeatEventGuard(window_seconds=20.0)
    assert guard.filter([zone_event(1)], {1: LEFT}, 0.0)
    assert guard.filter([zone_event(2)], {2: RIGHT}, 3.0)

    # PPE: covered items are repeats; a newly missing item is reported.
    guard = RepeatEventGuard(window_seconds=20.0)
    assert guard.filter([ppe_event(1, "gloves", "helmet", "vest")], {1: LEFT}, 0.0)
    assert not guard.filter([ppe_event(5, "gloves")], {5: LEFT}, 4.0)
    guard = RepeatEventGuard(window_seconds=20.0)
    assert guard.filter([ppe_event(1, "gloves")], {1: LEFT}, 0.0)
    assert guard.filter([ppe_event(1, "gloves", "helmet")], {1: LEFT}, 3.0)


def _pipeline(frames, restricted=True):
    """Real engines and filters; the tracker replays ``(track_id, confidence)`` per frame."""

    queue = list(frames)
    box = [20, 10, 80, 119]

    def track(frame, confidence):
        people = [
            SimpleNamespace(track_id=tid, detection={"bbox": box, "confidence": conf}, bbox=box)
            for tid, conf in queue.pop(0)
        ]
        return SimpleNamespace(people=people, detections=[p.detection for p in people])

    item = lambda name: SimpleNamespace(item_name=name, present=False)

    def analyze(detections):
        return [
            SimpleNamespace(person_detection=d, person_bbox=box, missing_items=["gloves"],
                            helmet=item("helmet"), vest=item("vest"), gloves=item("gloves"))
            for d in detections
        ]

    pipeline = object.__new__(RealtimePPEPipeline)
    pipeline.tracker = SimpleNamespace(track=track)
    pipeline.analyzer = SimpleNamespace(analyze=analyze)
    pipeline.violation_engine = TemporalViolationEngine(ViolationEngineConfig(confirmation_seconds=1.0))
    pipeline.zone_violation_config = ZoneViolationConfig(confirmation_seconds=1.0, track_expiration_seconds=2.0)
    pipeline.set_zones([RestrictedZone("location-1", "Restricted area", FULL_FRAME_POLYGON, normalized=True)] if restricted else None)
    pipeline.set_required_ppe(frozenset() if restricted else None)
    pipeline.incident_manager = None
    pipeline.incident_sink = None
    pipeline.confidence = 0.25
    pipeline._init_runtime_filters()
    return pipeline


def _run(pipeline, count):
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    events = []
    for index in range(count):
        events.extend(pipeline.process_frame(frame, index * 0.5).events)
    return [(event.event_type, event.track_id) for event in events]


def pipeline_tests() -> None:
    # A weak, flickering "person" (e.g. an object) never becomes a violation.
    assert _run(_pipeline([[(1, 0.3)]] * 10, restricted=False), 10) == []
    assert _run(_pipeline([[(1, 0.3)]] * 10), 10) == []

    # A real person (0.6 once) stays verified even when the score dips.
    frames = [[(1, 0.6)]] + [[(1, 0.3)]] * 9
    assert _run(_pipeline(frames), 10) == [("RESTRICTED_ZONE_VIOLATION", 1)]

    # Tracker loses the person (gap > zone expiry) and re-IDs them: one incident.
    frames = [[(1, 0.7)]] * 4 + [[]] * 6 + [[(2, 0.7)]] * 6 + [[(1, 0.7)]] * 6
    assert _run(_pipeline(frames), len(frames)) == [("RESTRICTED_ZONE_VIOLATION", 1)]

    # Same for PPE.
    frames = [[(1, 0.7)]] * 4 + [[]] * 2 + [[(9, 0.7)]] * 5
    assert _run(_pipeline(frames, restricted=False), len(frames)) == [("PPE_VIOLATION", 1)]


if __name__ == "__main__":
    guard_tests()
    pipeline_tests()
    print("Event guard tests passed:")
    print("  - weak/flickering false persons never create violations")
    print("  - one incident per person even when the tracker re-assigns IDs")
    print("  - separate people, other zones, new missing PPE and later visits still reported")
