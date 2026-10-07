"""Deterministic, time-based PPE violation confirmation per tracked person.

Single-frame PPE results are candidates only.  This module confirms a missing
item after sustained evidence, tolerates short PPE-classification flicker, and
emits JSON-safe events once per active episode.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Mapping, Optional, Set, Tuple


PPE_ITEMS: Tuple[str, ...] = ("helmet", "vest", "gloves")


@dataclass(frozen=True)
class ViolationEngineConfig:
    """Timing controls, expressed in seconds rather than frame counts."""

    confirmation_seconds: float = 2.0
    grace_seconds: float = 0.5
    cooldown_seconds: float = 10.0
    track_expiration_seconds: float = 8.0

    def __post_init__(self) -> None:
        for name in ("confirmation_seconds", "grace_seconds", "cooldown_seconds"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be a finite value greater than or equal to 0")
        if not math.isfinite(float(self.track_expiration_seconds)) or self.track_expiration_seconds <= 0.0:
            raise ValueError("track_expiration_seconds must be a finite value greater than 0")


@dataclass(frozen=True)
class ViolationEvent:
    """A confirmed PPE violation ready for JSON serialization."""

    track_id: int
    missing_items: Tuple[str, ...]
    stream_time_seconds: float
    duration_seconds: float
    item_durations_seconds: Mapping[str, float]
    timestamp: str
    event_type: str = "PPE_VIOLATION"
    confirmed: bool = True

    def to_dict(self) -> Dict[str, object]:
        return {
            "event_type": self.event_type,
            "track_id": int(self.track_id),
            "missing_items": list(self.missing_items),
            "timestamp": self.timestamp,
            "stream_time_seconds": round(float(self.stream_time_seconds), 6),
            "duration_seconds": round(float(self.duration_seconds), 6),
            "item_durations_seconds": {
                item: round(float(duration), 6)
                for item, duration in self.item_durations_seconds.items()
            },
            "confirmed": bool(self.confirmed),
        }


@dataclass(frozen=True)
class ViolationTransition:
    """A meaningful per-item state change for concise terminal reporting."""

    state: str
    track_id: int
    item: str
    stream_time_seconds: float
    elapsed_seconds: float

    def to_dict(self) -> Dict[str, object]:
        return {
            "state": self.state,
            "track_id": int(self.track_id),
            "item": self.item,
            "stream_time_seconds": round(float(self.stream_time_seconds), 6),
            "elapsed_seconds": round(float(self.elapsed_seconds), 6),
        }


@dataclass(frozen=True)
class ItemViolationSnapshot:
    state: str
    elapsed_seconds: float

    def to_dict(self) -> Dict[str, object]:
        return {
            "state": self.state,
            "elapsed_seconds": round(float(self.elapsed_seconds), 6),
        }


@dataclass(frozen=True)
class TrackViolationSnapshot:
    track_id: int
    items: Mapping[str, ItemViolationSnapshot]

    @property
    def candidate_items(self) -> List[str]:
        return [item for item in PPE_ITEMS if self.items[item].state == "CANDIDATE"]

    @property
    def confirmed_items(self) -> List[str]:
        return [item for item in PPE_ITEMS if self.items[item].state == "CONFIRMED"]

    @property
    def candidate_elapsed_seconds(self) -> float:
        values = [self.items[item].elapsed_seconds for item in self.candidate_items]
        return max(values, default=0.0)

    def to_dict(self) -> Dict[str, object]:
        return {
            "track_id": int(self.track_id),
            "items": {item: value.to_dict() for item, value in self.items.items()},
            "candidate_items": self.candidate_items,
            "confirmed_items": self.confirmed_items,
        }


@dataclass(frozen=True)
class ViolationUpdate:
    events: List[ViolationEvent]
    transitions: List[ViolationTransition]
    snapshots: Mapping[int, TrackViolationSnapshot]
    active_confirmed_tracks: int


@dataclass
class _ItemState:
    missing_since: Optional[float] = None
    present_since: Optional[float] = None
    confirmed: bool = False


@dataclass
class _TrackState:
    track_id: int
    last_seen: float
    last_update: float
    observed_last_frame: bool = True
    items: Dict[str, _ItemState] = field(
        default_factory=lambda: {item: _ItemState() for item in PPE_ITEMS}
    )
    last_event_at: Optional[float] = None
    pending_event: bool = False


class TemporalViolationEngine:
    """Maintain candidate/confirmed/resolved PPE state for ByteTrack IDs."""

    def __init__(self, config: Optional[ViolationEngineConfig] = None) -> None:
        self.config = config or ViolationEngineConfig()
        self._tracks: Dict[int, _TrackState] = {}
        self._last_frame_time: Optional[float] = None

    def reset(self) -> None:
        """Discard all temporal state before starting another source."""

        self._tracks.clear()
        self._last_frame_time = None

    def update(
        self,
        observations: Mapping[int, Iterable[str]],
        timestamp: float,
    ) -> ViolationUpdate:
        """Advance one frame using ``track_id -> missing PPE items`` observations.

        Every observed item not listed as missing is considered present.  A
        present item must remain present for ``grace_seconds`` before an active
        candidate/violation is cleared; a shorter flicker preserves its timer.
        """

        now = self._validate_timestamp(timestamp)
        if self._last_frame_time is not None and now < self._last_frame_time:
            raise ValueError("timestamp must not move backwards; call reset() for a new source")
        self._last_frame_time = now

        normalized: Dict[int, Set[str]] = {}
        for raw_track_id, raw_items in observations.items():
            track_id = int(raw_track_id)
            if track_id < 0:
                raise ValueError("track IDs must be non-negative integers")
            items = {str(item).strip().lower() for item in raw_items}
            unknown = items.difference(PPE_ITEMS)
            if unknown:
                raise ValueError(f"Unsupported PPE item(s): {', '.join(sorted(unknown))}")
            normalized[track_id] = items

        transitions: List[ViolationTransition] = []
        events: List[ViolationEvent] = []

        observed_ids = set(normalized)
        for track_id, track in self._tracks.items():
            elapsed_since_update = max(0.0, now - track.last_update)
            currently_observed = track_id in observed_ids
            if not track.observed_last_frame or not currently_observed:
                self._pause_timers(track, elapsed_since_update)
            track.last_update = now
            track.observed_last_frame = currently_observed

        for track_id, missing_items in normalized.items():
            track = self._tracks.get(track_id)
            if track is None:
                track = _TrackState(track_id=track_id, last_seen=now, last_update=now)
                self._tracks[track_id] = track
            track.last_seen = now
            track.last_update = now
            track.observed_last_frame = True
            newly_confirmed = False

            for item_name in PPE_ITEMS:
                item = track.items[item_name]
                if item_name in missing_items:
                    item.present_since = None
                    if item.missing_since is None:
                        item.missing_since = now
                        transitions.append(
                            ViolationTransition("CANDIDATE", track_id, item_name, now, 0.0)
                        )

                    elapsed = max(0.0, now - item.missing_since)
                    if (
                        not item.confirmed
                        and elapsed + 1e-9 >= self.config.confirmation_seconds
                    ):
                        item.confirmed = True
                        newly_confirmed = True
                        transitions.append(
                            ViolationTransition("CONFIRMED", track_id, item_name, now, elapsed)
                        )
                elif item.missing_since is not None:
                    if item.present_since is None:
                        item.present_since = now
                    if now - item.present_since + 1e-9 >= self.config.grace_seconds:
                        elapsed = max(0.0, item.present_since - item.missing_since)
                        transitions.append(
                            ViolationTransition("RESOLVED", track_id, item_name, now, elapsed)
                        )
                        item.missing_since = None
                        item.present_since = None
                        item.confirmed = False

            active_confirmed = self._confirmed_items(track)
            if newly_confirmed:
                track.pending_event = True

            cooldown_ready = (
                track.last_event_at is None
                or now - track.last_event_at + 1e-9 >= self.config.cooldown_seconds
            )
            if track.pending_event and active_confirmed and cooldown_ready:
                events.append(self._make_event(track, active_confirmed, now))
                track.last_event_at = now
                track.pending_event = False

            if all(item.missing_since is None for item in track.items.values()):
                # A genuinely compliant period ends the active episode.  A
                # later missing episode can produce a new event after its own
                # full confirmation period, even if it occurs within 10 s.
                track.last_event_at = None
                track.pending_event = False

        expired_ids = [
            track_id
            for track_id, track in self._tracks.items()
            if now - track.last_seen > self.config.track_expiration_seconds
        ]
        for track_id in expired_ids:
            del self._tracks[track_id]

        snapshots = {
            track_id: self._snapshot(track, now)
            for track_id, track in self._tracks.items()
        }
        active_tracks = sum(bool(snapshot.confirmed_items) for snapshot in snapshots.values())
        return ViolationUpdate(events, transitions, snapshots, active_tracks)

    def snapshot(self, track_id: int, timestamp: float) -> TrackViolationSnapshot:
        """Return current display state for an active track."""

        track = self._tracks.get(int(track_id))
        if track is None:
            return TrackViolationSnapshot(
                track_id=int(track_id),
                items={item: ItemViolationSnapshot("COMPLIANT", 0.0) for item in PPE_ITEMS},
            )
        return self._snapshot(track, self._validate_timestamp(timestamp))

    @staticmethod
    def _validate_timestamp(timestamp: float) -> float:
        value = float(timestamp)
        if not math.isfinite(value) or value < 0.0:
            raise ValueError("timestamp must be a finite value greater than or equal to 0")
        return value

    @staticmethod
    def _confirmed_items(track: _TrackState) -> Tuple[str, ...]:
        return tuple(item for item in PPE_ITEMS if track.items[item].confirmed)

    @staticmethod
    def _pause_timers(track: _TrackState, duration: float) -> None:
        """Exclude full-person detection gaps from PPE evidence duration."""

        if duration <= 0.0:
            return
        for item in track.items.values():
            if item.missing_since is not None:
                item.missing_since += duration
            if item.present_since is not None:
                item.present_since += duration

    def _make_event(
        self,
        track: _TrackState,
        active_items: Tuple[str, ...],
        timestamp: float,
    ) -> ViolationEvent:
        durations = {
            item: max(0.0, timestamp - float(track.items[item].missing_since))
            for item in active_items
            if track.items[item].missing_since is not None
        }
        return ViolationEvent(
            track_id=track.track_id,
            missing_items=active_items,
            stream_time_seconds=timestamp,
            duration_seconds=max(durations.values(), default=0.0),
            item_durations_seconds=durations,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    def _snapshot(track: _TrackState, timestamp: float) -> TrackViolationSnapshot:
        items: Dict[str, ItemViolationSnapshot] = {}
        for item_name in PPE_ITEMS:
            item = track.items[item_name]
            if item.missing_since is None:
                items[item_name] = ItemViolationSnapshot("COMPLIANT", 0.0)
            else:
                state = "CONFIRMED" if item.confirmed else "CANDIDATE"
                items[item_name] = ItemViolationSnapshot(
                    state,
                    max(0.0, timestamp - item.missing_since),
                )
        return TrackViolationSnapshot(track.track_id, items)

