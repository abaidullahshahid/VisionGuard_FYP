"""Restricted-zone configuration and tracked-person polygon containment."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple, Union

import cv2
import numpy as np

from .tracker import TrackedPerson


Point = Tuple[float, float]
PixelPoint = Tuple[float, float]


class ZoneConfigurationError(ValueError):
    """Raised when a restricted-zone definition is invalid."""


def _finite_number(value: object, description: str) -> float:
    if isinstance(value, bool):
        raise ZoneConfigurationError(f"{description} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ZoneConfigurationError(f"{description} must be a number") from exc
    if not math.isfinite(number):
        raise ZoneConfigurationError(f"{description} must be finite")
    return number


def _polygon_area(points: Sequence[Point]) -> float:
    return abs(
        sum(
            x1 * y2 - x2 * y1
            for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1])
        )
    ) / 2.0


@dataclass(frozen=True)
class RestrictedZone:
    """One enabled/disabled pixel or normalized restricted polygon.

    Normalized points use the inclusive range 0.0-1.0 and are multiplied by
    the current frame width/height when used. Pixel points are used as-is.
    """

    zone_id: str
    name: str
    polygon: Sequence[Sequence[float]]
    enabled: bool = True
    normalized: bool = False

    def __post_init__(self) -> None:
        zone_id = str(self.zone_id).strip()
        name = str(self.name).strip()
        if not zone_id:
            raise ZoneConfigurationError("zone_id must be a non-empty string")
        if not name:
            raise ZoneConfigurationError(f"Zone {zone_id!r} must have a non-empty name")
        if not isinstance(self.enabled, bool):
            raise ZoneConfigurationError(f"Zone {zone_id!r} enabled must be true or false")
        if not isinstance(self.normalized, bool):
            raise ZoneConfigurationError(f"Zone {zone_id!r} normalized must be true or false")
        if isinstance(self.polygon, (str, bytes)) or not isinstance(self.polygon, Sequence):
            raise ZoneConfigurationError(f"Zone {zone_id!r} polygon must be a list of points")
        if len(self.polygon) < 3:
            raise ZoneConfigurationError(f"Zone {zone_id!r} polygon requires at least 3 points")

        points: List[Point] = []
        for index, point in enumerate(self.polygon):
            if isinstance(point, (str, bytes)) or not isinstance(point, Sequence) or len(point) != 2:
                raise ZoneConfigurationError(
                    f"Zone {zone_id!r} polygon point {index} must contain exactly [x, y]"
                )
            x = _finite_number(point[0], f"Zone {zone_id!r} point {index} x")
            y = _finite_number(point[1], f"Zone {zone_id!r} point {index} y")
            if self.normalized and not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                raise ZoneConfigurationError(
                    f"Zone {zone_id!r} normalized coordinates must be between 0.0 and 1.0"
                )
            points.append((x, y))

        if len(set(points)) < 3 or _polygon_area(points) <= 1e-12:
            raise ZoneConfigurationError(f"Zone {zone_id!r} polygon must have a non-zero area")

        object.__setattr__(self, "zone_id", zone_id)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "polygon", tuple(points))

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "RestrictedZone":
        if not isinstance(data, Mapping):
            raise ZoneConfigurationError("Each zone must be a JSON object")
        missing = [key for key in ("zone_id", "name", "polygon") if key not in data]
        if missing:
            raise ZoneConfigurationError(f"Zone is missing required field(s): {', '.join(missing)}")
        return cls(
            zone_id=data["zone_id"],
            name=data["name"],
            polygon=data["polygon"],
            enabled=data.get("enabled", True),
            normalized=data.get("normalized", False),
        )

    def pixel_polygon(self, frame_width: int, frame_height: int) -> Tuple[PixelPoint, ...]:
        """Resolve the configured points for the current frame resolution."""

        width, height = _validate_frame_size(frame_width, frame_height)
        if not self.normalized:
            return tuple((float(x), float(y)) for x, y in self.polygon)
        return tuple((float(x) * width, float(y) * height) for x, y in self.polygon)

    def to_dict(self) -> Dict[str, object]:
        return {
            "zone_id": self.zone_id,
            "name": self.name,
            "enabled": self.enabled,
            "normalized": self.normalized,
            "polygon": [[float(x), float(y)] for x, y in self.polygon],
        }


@dataclass(frozen=True)
class ResolvedZone:
    """A configured zone converted to pixel coordinates for one frame."""

    zone: RestrictedZone
    pixel_polygon: Tuple[PixelPoint, ...]

    def to_dict(self) -> Dict[str, object]:
        return {
            **self.zone.to_dict(),
            "pixel_polygon": [[float(x), float(y)] for x, y in self.pixel_polygon],
        }


@dataclass(frozen=True)
class PersonZoneStatus:
    """Current-frame zone memberships for one tracked person."""

    track_id: int
    foot_point: PixelPoint
    inside_zones: Tuple[RestrictedZone, ...]

    @property
    def inside_zone_ids(self) -> List[str]:
        return [zone.zone_id for zone in self.inside_zones]

    @property
    def inside_zone_names(self) -> List[str]:
        return [zone.name for zone in self.inside_zones]

    @property
    def inside_any_zone(self) -> bool:
        return bool(self.inside_zones)

    def to_dict(self) -> Dict[str, object]:
        return {
            "track_id": int(self.track_id),
            "foot_point": [float(self.foot_point[0]), float(self.foot_point[1])],
            "inside_zone": self.inside_any_zone,
            "inside_zone_ids": self.inside_zone_ids,
            "inside_zone_names": self.inside_zone_names,
        }


def foot_point(bbox: Sequence[float]) -> PixelPoint:
    """Return the bottom-center point ``((x1 + x2) / 2, y2)`` of a box."""

    if len(bbox) != 4:
        raise ValueError("bbox must contain [x1, y1, x2, y2]")
    x1, _, x2, y2 = (_finite_number(value, "bbox coordinate") for value in bbox)
    return (x1 + x2) / 2.0, y2


class ZoneAnalyzer:
    """Test tracked-person foot points against any number of enabled zones."""

    def __init__(self, zones: Iterable[RestrictedZone]) -> None:
        self.zones = tuple(zones)
        zone_ids = [zone.zone_id for zone in self.zones]
        duplicates = sorted({zone_id for zone_id in zone_ids if zone_ids.count(zone_id) > 1})
        if duplicates:
            raise ZoneConfigurationError(f"Duplicate zone_id value(s): {', '.join(duplicates)}")

    @property
    def enabled_zones(self) -> Tuple[RestrictedZone, ...]:
        return tuple(zone for zone in self.zones if zone.enabled)

    def resolve_zones(self, frame_width: int, frame_height: int) -> List[ResolvedZone]:
        return [
            ResolvedZone(zone, zone.pixel_polygon(frame_width, frame_height))
            for zone in self.enabled_zones
        ]

    def analyze(
        self,
        tracked_people: Iterable[TrackedPerson],
        frame_width: int,
        frame_height: int,
    ) -> List[PersonZoneStatus]:
        resolved = self.resolve_zones(frame_width, frame_height)
        results: List[PersonZoneStatus] = []
        for person in tracked_people:
            position = foot_point(person.bbox)
            inside: List[RestrictedZone] = []
            for resolved_zone in resolved:
                contour = np.asarray(resolved_zone.pixel_polygon, dtype=np.float32)
                if cv2.pointPolygonTest(contour, position, False) >= 0.0:
                    inside.append(resolved_zone.zone)
            results.append(
                PersonZoneStatus(
                    track_id=int(person.track_id),
                    foot_point=position,
                    inside_zones=tuple(inside),
                )
            )
        return results


def load_zones(path: Union[str, Path]) -> List[RestrictedZone]:
    """Load and validate ``{"zones": [...]}`` from a JSON file."""

    zone_path = Path(path).expanduser().resolve()
    if not zone_path.is_file():
        raise ZoneConfigurationError(f"Zone configuration file was not found: {zone_path}")
    try:
        with zone_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except json.JSONDecodeError as exc:
        raise ZoneConfigurationError(
            f"Invalid JSON in zone configuration {zone_path}: line {exc.lineno}, column {exc.colno}"
        ) from exc
    except OSError as exc:
        raise ZoneConfigurationError(f"Could not read zone configuration {zone_path}: {exc}") from exc

    if not isinstance(payload, Mapping):
        raise ZoneConfigurationError("Zone configuration root must be a JSON object")
    raw_zones = payload.get("zones")
    if not isinstance(raw_zones, list):
        raise ZoneConfigurationError("Zone configuration must contain a 'zones' list")

    zones: List[RestrictedZone] = []
    for index, raw_zone in enumerate(raw_zones):
        try:
            zones.append(RestrictedZone.from_dict(raw_zone))
        except ZoneConfigurationError as exc:
            raise ZoneConfigurationError(f"Invalid zone at index {index}: {exc}") from exc
    ZoneAnalyzer(zones)  # Also validate unique IDs.
    return zones


def _validate_frame_size(frame_width: int, frame_height: int) -> Tuple[int, int]:
    width, height = int(frame_width), int(frame_height)
    if width <= 0 or height <= 0:
        raise ValueError("frame width and height must be greater than 0")
    return width, height

