"""Camera-specific restricted zones stored in PostgreSQL.

This module is the only bridge between ``restricted_zones`` rows and the AI
module's :class:`ai_module.zone_analyzer.RestrictedZone`.  Polygon geometry
(point count, finite values, 0-1 range, non-zero area) is validated by that
existing class so the API and the AI pipeline enforce identical rules.
"""

from __future__ import annotations

import logging
import time
from numbers import Real
from typing import Callable, List, Optional, Sequence

from sqlalchemy.orm import Session

from ai_module import zone_analyzer
from database import SessionLocal
import models


logger = logging.getLogger(__name__)
ZoneConfigurationError = zone_analyzer.ZoneConfigurationError
MAX_ZONE_NAME_LENGTH = 150
MAX_POLYGON_POINTS = 100
FULL_FRAME_POLYGON = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
LOCATION_ZONE_PREFIX = "location-"


def validate_zone_name(value: object) -> str:
    name = str(value or "").strip()
    if not name:
        raise ZoneConfigurationError("Zone name is required")
    if len(name) > MAX_ZONE_NAME_LENGTH:
        raise ZoneConfigurationError(f"Zone name must be at most {MAX_ZONE_NAME_LENGTH} characters")
    return name


def validate_polygon_points(points: object, zone_name: str = "Zone") -> List[List[float]]:
    """Return ``[[x, y], ...]`` normalized points or raise a configuration error.

    Only a JSON list of ``[number, number]`` pairs is accepted; strings,
    booleans, objects, and nested structures are rejected before geometry
    checks run.
    """

    if not isinstance(points, list):
        raise ZoneConfigurationError("polygon_points must be a list of [x, y] points")
    if len(points) > MAX_POLYGON_POINTS:
        raise ZoneConfigurationError(f"A zone polygon can have at most {MAX_POLYGON_POINTS} points")
    for index, point in enumerate(points):
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ZoneConfigurationError(f"Point {index + 1} must be an [x, y] pair")
        if any(isinstance(value, bool) or not isinstance(value, Real) for value in point):
            raise ZoneConfigurationError(f"Point {index + 1} coordinates must be numbers")

    validated = zone_analyzer.RestrictedZone(
        zone_id=zone_name,
        name=zone_name,
        polygon=points,
        normalized=True,
    )
    return [[float(x), float(y)] for x, y in validated.polygon]


def to_analyzer_zone(record: models.RestrictedZone) -> zone_analyzer.RestrictedZone:
    """Convert one database row to the AI module's existing zone object.

    ``zone_id`` is the database primary key as a string, so restricted-zone
    incidents reference ``restricted_zones.id`` directly.
    """

    return zone_analyzer.RestrictedZone(
        zone_id=str(record.id),
        name=record.name,
        polygon=record.polygon_points,
        enabled=bool(record.enabled),
        normalized=True,
    )


def enabled_zone_records(db: Session, camera_id: int) -> List[models.RestrictedZone]:
    return (
        db.query(models.RestrictedZone)
        .filter(
            models.RestrictedZone.camera_id == camera_id,
            models.RestrictedZone.enabled.is_(True),
        )
        .order_by(models.RestrictedZone.id.asc())
        .all()
    )


def load_enabled_zones(db: Session, camera_id: int) -> List[zone_analyzer.RestrictedZone]:
    """Return the camera's enabled zones; an empty list means "no zone checks"."""

    zones: List[zone_analyzer.RestrictedZone] = []
    for record in enabled_zone_records(db, camera_id):
        try:
            zones.append(to_analyzer_zone(record))
        except ZoneConfigurationError:
            # Rows are validated on write; a hand-edited bad row must not stop
            # PPE inference for the whole camera.
            logger.warning("Skipping invalid restricted zone %s for camera %s", record.id, camera_id)
    return zones


def location_restricted_zone(db: Session, location_id: Optional[int]) -> Optional[zone_analyzer.RestrictedZone]:
    """Whole-frame zone for a location marked restricted in Safety Rules.

    Anyone the camera sees there is a violation, worker or not and with or
    without PPE.  ``zone_id`` is ``location-<id>`` so incidents name the
    location instead of a drawn ``restricted_zones`` row.
    """

    if location_id is None:
        return None
    restricted = (
        db.query(models.SafetyRule.id)
        .filter(
            models.SafetyRule.location_id == location_id,
            models.SafetyRule.is_restricted_area.is_(True),
        )
        .first()
    )
    if restricted is None:
        return None
    location = db.get(models.Location, location_id)
    return zone_analyzer.RestrictedZone(
        zone_id=f"{LOCATION_ZONE_PREFIX}{location_id}",
        name=f"Restricted area: {location.name if location else location_id}",
        polygon=FULL_FRAME_POLYGON,
        normalized=True,
    )


def load_enabled_zones_for_camera(
    camera_db_id: int,
    session_factory: Optional[Callable[[], Session]] = None,
) -> List[zone_analyzer.RestrictedZone]:
    """Zones the AI enforces for a camera.

    A restricted location covers the whole view, which already contains any
    drawn zones, so only that one zone is returned (one incident per entry).
    """

    db = (session_factory or SessionLocal)()
    try:
        camera = db.get(models.Camera, int(camera_db_id))
        if camera is None:
            raise ValueError(f"Camera {camera_db_id} does not exist")
        whole_location = location_restricted_zone(db, camera.location_id)
        if whole_location is not None:
            return [whole_location]
        return load_enabled_zones(db, int(camera_db_id))
    finally:
        db.close()


class RestrictedZoneReloader:
    """Poll the database so a running AI session picks up Admin zone changes.

    ``poll()`` returns the new zone list only when the enabled zones changed
    since the last load, and ``None`` otherwise (including on database errors,
    which are logged so inference keeps running with the previous zones).
    """

    def __init__(
        self,
        camera_db_id: int,
        interval_seconds: float = 5.0,
        session_factory: Optional[Callable[[], Session]] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.camera_db_id = int(camera_db_id)
        self.interval_seconds = float(interval_seconds)
        self.session_factory = session_factory
        self.clock = clock
        self._current: Optional[Sequence[zone_analyzer.RestrictedZone]] = None
        self._last_check = 0.0

    def load(self) -> List[zone_analyzer.RestrictedZone]:
        zones = load_enabled_zones_for_camera(self.camera_db_id, self.session_factory)
        self._current = tuple(zones)
        self._last_check = self.clock()
        return zones

    def poll(self) -> Optional[List[zone_analyzer.RestrictedZone]]:
        now = self.clock()
        if self.interval_seconds <= 0 or now - self._last_check < self.interval_seconds:
            return None
        self._last_check = now
        try:
            zones = load_enabled_zones_for_camera(self.camera_db_id, self.session_factory)
        except Exception:
            logger.exception("Could not reload restricted zones for camera %s", self.camera_db_id)
            return None
        if tuple(zones) == self._current:
            return None
        self._current = tuple(zones)
        return zones
