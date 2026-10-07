"""Time-based restricted-zone confirmation for tracked people."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Mapping, Optional, Set, Tuple

from .zone_analyzer import RestrictedZone


@dataclass(frozen=True)
class ZoneViolationConfig:
    """Restricted-zone timing controls in seconds."""

    confirmation_seconds: float = 1.5
    exit_grace_seconds: float = 0.5
    track_expiration_seconds: float = 8.0

    def __post_init__(self) -> None:
        for name in ("confirmation_seconds", "exit_grace_seconds"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be a finite value greater than or equal to 0")
        expiration = float(self.track_expiration_seconds)
        if not math.isfinite(expiration) or expiration <= 0.0:
            raise ValueError("track_expiration_seconds must be a finite value greater than 0")


@dataclass(frozen=True)
class ZoneViolationEvent:
    """One confirmed zone-entry episode, ready for JSON serialization."""

    track_id: int
    zone_id: str
    zone_name: str
    timestamp: str
    stream_time_seconds: float
    duration_seconds: float
    event_type: str = "RESTRICTED_ZONE_VIOLATION"
    confirmed: bool = True

    def to_dict(self) -> Dict[str, object]:
        return {
            "event_type": self.event_type,
            "track_id": int(self.track_id),
            "zone_id": self.zone_id,
            "zone_name": self.zone_name,
            "timestamp": self.timestamp,
            "stream_time_seconds": round(float(self.stream_time_seconds), 6),
            "duration_seconds": round(float(self.duration_seconds), 6),
            "confirmed": bool(self.confirmed),
        }


@dataclass(frozen=True)
class ZoneTransition:
    """Meaningful state change for one track/zone pair."""

    state: str
    track_id: int
    zone_id: str
    zone_name: str
    stream_time_seconds: float
    elapsed_seconds: float

    def to_dict(self) -> Dict[str, object]:
        return {
            "state": self.state,
            "track_id": int(self.track_id),
            "zone_id": self.zone_id,
            "zone_name": self.zone_name,
            "stream_time_seconds": round(float(self.stream_time_seconds), 6),
            "elapsed_seconds": round(float(self.elapsed_seconds), 6),
        }


@dataclass(frozen=True)
class ZoneStateSnapshot:
    zone_id: str
    zone_name: str
    state: str
    elapsed_seconds: float

    def to_dict(self) -> Dict[str, object]:
        return {
            "zone_id": self.zone_id,
            "zone_name": self.zone_name,
            "state": self.state,
            "elapsed_seconds": round(float(self.elapsed_seconds), 6),
        }


@dataclass(frozen=True)
class TrackZoneSnapshot:
    track_id: int
    zones: Mapping[str, ZoneStateSnapshot]

    @property
    def candidate_zone_ids(self) -> List[str]:
        return [zone_id for zone_id, state in self.zones.items() if state.state == "CANDIDATE"]

    @property
    def confirmed_zone_ids(self) -> List[str]:
        return [zone_id for zone_id, state in self.zones.items() if state.state == "CONFIRMED"]

    @property
    def candidate_zone_names(self) -> List[str]:
        return [self.zones[zone_id].zone_name for zone_id in self.candidate_zone_ids]

    @property
    def confirmed_zone_names(self) -> List[str]:
        return [self.zones[zone_id].zone_name for zone_id in self.confirmed_zone_ids]

    @property
    def candidate_elapsed_seconds(self) -> float:
        return max(
            (self.zones[zone_id].elapsed_seconds for zone_id in self.candidate_zone_ids),
            default=0.0,
        )

    def to_dict(self) -> Dict[str, object]:
        return {
            "track_id": int(self.track_id),
            "zones": {zone_id: state.to_dict() for zone_id, state in self.zones.items()},
            "candidate_zone_ids": self.candidate_zone_ids,
            "confirmed_zone_ids": self.confirmed_zone_ids,
        }


@dataclass(frozen=True)
class ZoneViolationUpdate:
    events: List[ZoneViolationEvent]
    transitions: List[ZoneTransition]
    snapshots: Mapping[int, TrackZoneSnapshot]
    active_confirmed_pairs: int


@dataclass
class _ZonePairState:
    track_id: int
    zone: RestrictedZone
    entered_at: float
    last_seen: float
    last_update: float
    outside_since: Optional[float] = None
    confirmed: bool = False
    observed_last_frame: bool = True


class TemporalZoneViolationEngine:
    """Maintain independent state for every active ``track_id + zone_id`` pair."""

    def __init__(
        self,
        zones: Iterable[RestrictedZone],
        config: Optional[ZoneViolationConfig] = None,
    ) -> None:
        self.zones = tuple(zone for zone in zones if zone.enabled)
        self._zones_by_id = {zone.zone_id: zone for zone in self.zones}
        if len(self._zones_by_id) != len(self.zones):
            raise ValueError("Zone IDs must be unique")
        self.config = config or ZoneViolationConfig()
        self._states: Dict[Tuple[int, str], _ZonePairState] = {}
        self._last_frame_time: Optional[float] = None

    def reset(self) -> None:
        self._states.clear()
        self._last_frame_time = None

    def update(
        self,
        observations: Mapping[int, Iterable[str]],
        timestamp: float,
    ) -> ZoneViolationUpdate:
        """Advance one frame using ``track_id -> zones currently containing its foot``."""

        now = self._validate_timestamp(timestamp)
        if self._last_frame_time is not None and now < self._last_frame_time:
            raise ValueError("timestamp must not move backwards; call reset() for a new source")
        self._last_frame_time = now

        normalized: Dict[int, Set[str]] = {}
        for raw_track_id, raw_zone_ids in observations.items():
            track_id = int(raw_track_id)
            if track_id < 0:
                raise ValueError("track IDs must be non-negative integers")
            zone_ids = {str(zone_id) for zone_id in raw_zone_ids}
            unknown = zone_ids.difference(self._zones_by_id)
            if unknown:
                raise ValueError(f"Unknown restricted zone(s): {', '.join(sorted(unknown))}")
            normalized[track_id] = zone_ids

        observed_track_ids = set(normalized)
        for state in self._states.values():
            elapsed_since_update = max(0.0, now - state.last_update)
            currently_observed = state.track_id in observed_track_ids
            if not state.observed_last_frame or not currently_observed:
                state.entered_at += elapsed_since_update
                if state.outside_since is not None:
                    state.outside_since += elapsed_since_update
            state.last_update = now
            state.observed_last_frame = currently_observed

        transitions: List[ZoneTransition] = []
        events: List[ZoneViolationEvent] = []
        resolved_keys: List[Tuple[int, str]] = []

        for track_id, inside_zone_ids in normalized.items():
            for zone in self.zones:
                key = (track_id, zone.zone_id)
                state = self._states.get(key)
                if zone.zone_id in inside_zone_ids:
                    if state is None:
                        state = _ZonePairState(track_id, zone, now, now, now)
                        self._states[key] = state
                        transitions.append(
                            ZoneTransition("CANDIDATE", track_id, zone.zone_id, zone.name, now, 0.0)
                        )
                    state.last_seen = now
                    state.last_update = now
                    state.observed_last_frame = True
                    state.outside_since = None
                    elapsed = max(0.0, now - state.entered_at)
                    if not state.confirmed and elapsed + 1e-9 >= self.config.confirmation_seconds:
                        state.confirmed = True
                        transitions.append(
                            ZoneTransition("CONFIRMED", track_id, zone.zone_id, zone.name, now, elapsed)
                        )
                        events.append(
                            ZoneViolationEvent(
                                track_id=track_id,
                                zone_id=zone.zone_id,
                                zone_name=zone.name,
                                timestamp=datetime.now(timezone.utc).isoformat(),
                                stream_time_seconds=now,
                                duration_seconds=elapsed,
                            )
                        )
                elif state is not None:
                    state.last_seen = now
                    state.last_update = now
                    state.observed_last_frame = True
                    if state.outside_since is None:
                        state.outside_since = now
                    if now - state.outside_since + 1e-9 >= self.config.exit_grace_seconds:
                        inside_duration = max(0.0, state.outside_since - state.entered_at)
                        transitions.append(
                            ZoneTransition(
                                "RESOLVED",
                                track_id,
                                zone.zone_id,
                                zone.name,
                                now,
                                inside_duration,
                            )
                        )
                        resolved_keys.append(key)

        for key in resolved_keys:
            self._states.pop(key, None)

        expired_keys = [
            key
            for key, state in self._states.items()
            if now - state.last_seen > self.config.track_expiration_seconds
        ]
        for key in expired_keys:
            del self._states[key]

        snapshot_track_ids = observed_track_ids.union(state.track_id for state in self._states.values())
        snapshots = {
            track_id: self._snapshot(track_id, now)
            for track_id in sorted(snapshot_track_ids)
        }
        active_confirmed = sum(state.confirmed for state in self._states.values())
        return ZoneViolationUpdate(events, transitions, snapshots, active_confirmed)

    def snapshot(self, track_id: int, timestamp: float) -> TrackZoneSnapshot:
        return self._snapshot(int(track_id), self._validate_timestamp(timestamp))

    def _snapshot(self, track_id: int, timestamp: float) -> TrackZoneSnapshot:
        zone_states: Dict[str, ZoneStateSnapshot] = {}
        for zone in self.zones:
            state = self._states.get((track_id, zone.zone_id))
            if state is None:
                zone_states[zone.zone_id] = ZoneStateSnapshot(zone.zone_id, zone.name, "OUTSIDE", 0.0)
            else:
                zone_states[zone.zone_id] = ZoneStateSnapshot(
                    zone.zone_id,
                    zone.name,
                    "CONFIRMED" if state.confirmed else "CANDIDATE",
                    max(0.0, timestamp - state.entered_at),
                )
        return TrackZoneSnapshot(track_id, zone_states)

    @staticmethod
    def _validate_timestamp(timestamp: float) -> float:
        value = float(timestamp)
        if not math.isfinite(value) or value < 0.0:
            raise ValueError("timestamp must be a finite value greater than or equal to 0")
        return value

