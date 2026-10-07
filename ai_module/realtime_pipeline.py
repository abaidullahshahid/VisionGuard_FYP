"""Realtime orchestration for PPE detection, person tracking, and confirmation."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from .detector import PPEDetector
from .event_guard import RepeatEventGuard
from .incident_manager import Incident, IncidentManager
from .ppe_analyzer import PPEAnalyzer, PersonPPEStatus
from .tracker import PersonTracker, TrackedPerson, TrackingFrame
from .violation_engine import (
    TemporalViolationEngine,
    TrackViolationSnapshot,
    ViolationEngineConfig,
    ViolationEvent,
    ViolationTransition,
)
from .zone_analyzer import PersonZoneStatus, ResolvedZone, RestrictedZone, ZoneAnalyzer
from .zone_violation_engine import (
    TemporalZoneViolationEngine,
    TrackZoneSnapshot,
    ZoneTransition,
    ZoneViolationConfig,
    ZoneViolationEvent,
)


RealtimeEvent = Union[ViolationEvent, ZoneViolationEvent]
RealtimeTransition = Union[ViolationTransition, ZoneTransition]
IncidentSink = Callable[[Mapping[str, object]], object]
logger = logging.getLogger(__name__)
# Real people score ~0.5-0.85 on the PPE model's Person class; one-off false
# "people" (objects, sideways bodies) stay around 0.1-0.35.
MIN_PERSON_CONFIDENCE = 0.45
REPEAT_EVENT_WINDOW_SECONDS = 20.0
PERSON_MEMORY_SECONDS = 60.0


def _iou(first: Sequence[float], second: Sequence[float]) -> float:
    x1 = max(float(first[0]), float(second[0]))
    y1 = max(float(first[1]), float(second[1]))
    x2 = min(float(first[2]), float(second[2]))
    y2 = min(float(first[3]), float(second[3]))
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    first_area = max(0.0, float(first[2]) - float(first[0])) * max(
        0.0, float(first[3]) - float(first[1])
    )
    second_area = max(0.0, float(second[2]) - float(second[0])) * max(
        0.0, float(second[3]) - float(second[1])
    )
    union = first_area + second_area - intersection
    return intersection / union if union > 0.0 else 0.0


@dataclass(frozen=True)
class TrackedPPEAnalysis:
    """PPE and temporal state tied to one temporary ByteTrack ID."""

    tracked_person: TrackedPerson
    ppe_status: PersonPPEStatus
    violation_state: TrackViolationSnapshot
    zone_status: Optional[PersonZoneStatus] = None
    zone_violation_state: Optional[TrackZoneSnapshot] = None

    @property
    def track_id(self) -> int:
        return self.tracked_person.track_id

    def to_dict(self) -> Dict[str, object]:
        data = self.ppe_status.to_dict()
        data["track_id"] = int(self.track_id)
        data["temporal_state"] = self.violation_state.to_dict()
        data["confirmed_incident"] = bool(self.violation_state.confirmed_items)
        if self.zone_status is not None and self.zone_violation_state is not None:
            data["zone_analysis"] = self.zone_status.to_dict()
            data["zone_temporal_state"] = self.zone_violation_state.to_dict()
            data["confirmed_zone_violation"] = bool(
                self.zone_violation_state.confirmed_zone_ids
            )
        return data


@dataclass(frozen=True)
class RealtimeFrameResult:
    """All reusable results produced for one frame."""

    timestamp_seconds: float
    tracking: TrackingFrame
    people: List[TrackedPPEAnalysis]
    events: List[RealtimeEvent]
    transitions: List[RealtimeTransition]
    active_confirmed_violations: int
    zones: List[ResolvedZone] = field(default_factory=list)
    active_confirmed_ppe_violations: int = 0
    active_confirmed_zone_violations: int = 0
    incidents: List[Incident] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        data = {
            "timestamp_seconds": round(float(self.timestamp_seconds), 6),
            "detections": [dict(detection) for detection in self.tracking.detections],
            "people": [person.to_dict() for person in self.people],
            "events": [event.to_dict() for event in self.events],
            "transitions": [transition.to_dict() for transition in self.transitions],
            "active_confirmed_violations": int(self.active_confirmed_violations),
            "incidents": [incident.to_dict() for incident in self.incidents],
        }
        if self.zones:
            data["zones"] = [zone.to_dict() for zone in self.zones]
            data["active_confirmed_ppe_violations"] = int(
                self.active_confirmed_ppe_violations
            )
            data["active_confirmed_zone_violations"] = int(
                self.active_confirmed_zone_violations
            )
        return data


class RealtimePPEPipeline:
    """Run one inference per frame, then PPE association and temporal state."""

    def __init__(
        self,
        confidence: float = 0.25,
        violation_config: Optional[ViolationEngineConfig] = None,
        detector: Optional[PPEDetector] = None,
        analyzer: Optional[PPEAnalyzer] = None,
        zones: Optional[Sequence[RestrictedZone]] = None,
        zone_violation_config: Optional[ZoneViolationConfig] = None,
        incident_manager: Optional[IncidentManager] = None,
        incident_sink: Optional[IncidentSink] = None,
        required_ppe: Optional[Iterable[str]] = None,
        min_person_confidence: float = MIN_PERSON_CONFIDENCE,
        repeat_window_seconds: float = REPEAT_EVENT_WINDOW_SECONDS,
    ) -> None:
        self.detector = detector or PPEDetector(confidence=confidence)
        self.tracker = PersonTracker(self.detector)
        self.analyzer = analyzer or PPEAnalyzer()
        self.violation_engine = TemporalViolationEngine(violation_config)
        self.zone_violation_config = zone_violation_config
        self.set_zones(zones)
        self.set_required_ppe(required_ppe)
        self.incident_manager = incident_manager
        self.incident_sink = incident_sink
        self.confidence = float(confidence)
        self._init_runtime_filters(min_person_confidence, repeat_window_seconds)

    def _init_runtime_filters(
        self,
        min_person_confidence: float = MIN_PERSON_CONFIDENCE,
        repeat_window_seconds: float = REPEAT_EVENT_WINDOW_SECONDS,
    ) -> None:
        """False-person and repeat-incident filters (see ``_verified_people``)."""

        self.min_person_confidence = float(min_person_confidence)
        self._person_peaks: Dict[int, Tuple[float, float]] = {}
        self.event_guard = RepeatEventGuard(repeat_window_seconds)

    def _verified_people(
        self,
        tracked_people: Sequence[TrackedPerson],
        timestamp_seconds: float,
    ) -> List[TrackedPerson]:
        """Tracks whose person confidence has reached the minimum at least once.

        A track is judged on its best detection so far, so a real person whose
        score dips for a few frames stays verified, while a low-scoring false
        "person" never produces a violation.
        """

        now = float(timestamp_seconds)
        verified: List[TrackedPerson] = []
        for person in tracked_people:
            confidence = float(person.detection.get("confidence", 1.0))
            peak = max(self._person_peaks.get(person.track_id, (0.0, now))[0], confidence)
            self._person_peaks[person.track_id] = (peak, now)
            if peak >= self.min_person_confidence:
                verified.append(person)
        self._person_peaks = {
            track_id: value
            for track_id, value in self._person_peaks.items()
            if now - value[1] <= PERSON_MEMORY_SECONDS
        }
        return verified

    @property
    def class_names(self) -> Dict[int, str]:
        return self.detector.class_names

    def set_zones(self, zones: Optional[Sequence[RestrictedZone]]) -> None:
        """Replace the restricted zones, e.g. after an Admin changes them.

        ``None`` disables zone analysis (PPE only).  Zone temporal state starts
        over because in-progress episodes belong to the previous polygons;
        PPE tracking and violation state are unaffected.
        """

        self.zone_analyzer = ZoneAnalyzer(zones) if zones is not None else None
        self.zone_violation_engine = (
            TemporalZoneViolationEngine(
                self.zone_analyzer.enabled_zones,
                self.zone_violation_config,
            )
            if self.zone_analyzer is not None
            else None
        )

    def set_required_ppe(self, items: Optional[Iterable[str]]) -> None:
        """Limit PPE violations to these items (e.g. a location's rules).

        ``None`` enforces every item the analyzer checks.  Items that stop
        being required simply resolve through the normal grace period.
        """

        self.required_ppe = frozenset(items) if items is not None else None

    def _enforced_missing_items(self, missing_items: Sequence[str]) -> List[str]:
        if self.required_ppe is None:
            return list(missing_items)
        return [item for item in missing_items if item in self.required_ppe]

    def process_frame(
        self,
        frame: object,
        timestamp_seconds: float,
        evidence_frame: Optional[object] = None,
        defer_incidents: bool = False,
    ) -> RealtimeFrameResult:
        """Process one OpenCV BGR frame at a caller-provided stream time."""

        tracking = self.tracker.track(frame, confidence=self.confidence)
        verified_people = self._verified_people(tracking.people, timestamp_seconds)
        ppe_results = self.analyzer.analyze(tracking.detections)
        paired = self._pair_people(verified_people, ppe_results)
        observations = {
            person.track_id: self._enforced_missing_items(status.missing_items)
            for person, status in paired
        }
        update = self.violation_engine.update(observations, timestamp_seconds)
        resolved_zones: List[ResolvedZone] = []
        zone_statuses: Dict[int, PersonZoneStatus] = {}
        zone_snapshots: Dict[int, TrackZoneSnapshot] = {}
        zone_events: List[ZoneViolationEvent] = []
        zone_transitions: List[ZoneTransition] = []
        active_zone_violations = 0

        if self.zone_analyzer is not None and self.zone_violation_engine is not None:
            shape = getattr(frame, "shape", None)
            if shape is None or len(shape) < 2:
                raise ValueError("Zone analysis requires an image frame with width and height")
            frame_height, frame_width = int(shape[0]), int(shape[1])
            resolved_zones = self.zone_analyzer.resolve_zones(frame_width, frame_height)
            analyzed_zones = self.zone_analyzer.analyze(
                verified_people,
                frame_width,
                frame_height,
            )
            zone_statuses = {status.track_id: status for status in analyzed_zones}
            zone_observations = {
                status.track_id: status.inside_zone_ids for status in analyzed_zones
            }
            zone_update = self.zone_violation_engine.update(
                zone_observations,
                timestamp_seconds,
            )
            zone_snapshots = dict(zone_update.snapshots)
            zone_events = zone_update.events
            zone_transitions = zone_update.transitions
            active_zone_violations = zone_update.active_confirmed_pairs

        people = [
            TrackedPPEAnalysis(
                tracked_person=person,
                ppe_status=status,
                violation_state=update.snapshots[person.track_id],
                zone_status=zone_statuses.get(person.track_id),
                zone_violation_state=zone_snapshots.get(person.track_id),
            )
            for person, status in paired
            if person.track_id in update.snapshots
        ]
        result = RealtimeFrameResult(
            timestamp_seconds=float(timestamp_seconds),
            tracking=tracking,
            people=people,
            # One incident per person presence, even if the tracker re-IDs them.
            events=self.event_guard.filter(
                [*update.events, *zone_events],
                {person.track_id: person.bbox for person in verified_people},
                timestamp_seconds,
            ),
            transitions=[*update.transitions, *zone_transitions],
            active_confirmed_violations=(
                update.active_confirmed_tracks + active_zone_violations
            ),
            zones=resolved_zones,
            active_confirmed_ppe_violations=update.active_confirmed_tracks,
            active_confirmed_zone_violations=active_zone_violations,
        )
        if self.incident_manager is not None and result.events and not defer_incidents:
            self.create_incidents(
                result,
                evidence_frame if evidence_frame is not None else frame,
            )
        return result

    @property
    def generated_incidents(self) -> Tuple[Incident, ...]:
        if self.incident_manager is None:
            return ()
        return self.incident_manager.incidents

    def incidents_as_dicts(self) -> List[Dict[str, object]]:
        if self.incident_manager is None:
            return []
        return self.incident_manager.incidents_as_dicts()

    def create_incidents(
        self,
        result: RealtimeFrameResult,
        evidence_frame: object,
    ) -> List[Incident]:
        """Finalize confirmed events using an annotated frame when available."""

        if self.incident_manager is None or not result.events:
            return []
        created = self.incident_manager.create_incidents(
            result.events,
            evidence_frame,
        )
        result.incidents.extend(created)
        if self.incident_sink is not None:
            for incident in created:
                try:
                    self.incident_sink(incident.to_dict())
                except Exception:
                    # A storage outage must not stop live camera inference.  A
                    # full traceback is logged so the failure is never silent.
                    logger.exception(
                        "Incident sink failed for incident %s",
                        incident.incident_id,
                    )
        return created

    def reset(self) -> None:
        """Reset tracking and violation state before a different source."""

        self.tracker.reset()
        self._person_peaks.clear()
        self.event_guard.reset()
        self.violation_engine.reset()
        if self.zone_violation_engine is not None:
            self.zone_violation_engine.reset()
        if self.incident_manager is not None:
            self.incident_manager.reset()

    @staticmethod
    def _pair_people(
        tracked_people: Sequence[TrackedPerson],
        statuses: Sequence[PersonPPEStatus],
    ) -> List[Tuple[TrackedPerson, PersonPPEStatus]]:
        """Pair analyzer people back to IDs from the same detector result."""

        by_detection_identity = {
            id(person.detection): person for person in tracked_people
        }
        paired: List[Tuple[TrackedPerson, PersonPPEStatus]] = []
        used_track_ids = set()
        unmatched_statuses: List[PersonPPEStatus] = []

        for status in statuses:
            person = by_detection_identity.get(id(status.person_detection))
            if person is None:
                unmatched_statuses.append(status)
                continue
            paired.append((person, status))
            used_track_ids.add(person.track_id)

        # Identity matching is exact for the normal path.  IoU is a defensive
        # fallback if a future analyzer copies normalized detection dicts.
        available = [
            person for person in tracked_people if person.track_id not in used_track_ids
        ]
        for status in unmatched_statuses:
            candidates = [
                (_iou(status.person_bbox, person.bbox), person)
                for person in available
            ]
            if not candidates:
                continue
            overlap, person = max(candidates, key=lambda pair: pair[0])
            if overlap < 0.5:
                continue
            paired.append((person, status))
            available.remove(person)

        paired.sort(key=lambda pair: pair[0].track_id)
        return paired

