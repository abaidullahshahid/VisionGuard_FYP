"""Location PPE safety rules -> the PPE items the AI enforces for a camera.

A camera belongs to a location; that location's non-restricted safety rules
list the PPE workers must wear there ("All PPE" = every item, "No PPE" =
nothing).  A location without any PPE rule enforces every item the analyzer
checks (helmet, vest, gloves), so a forgotten rule never disables checks.
A restricted location enforces no PPE: any person there is already a
violation (see ``restricted_zone_service.location_restricted_zone``).
"""

from __future__ import annotations

import logging
import time
from typing import Callable, FrozenSet, Iterable, Optional

from sqlalchemy.orm import Session

from database import SessionLocal
import models


logger = logging.getLogger(__name__)

ALL_PPE_ITEMS: FrozenSet[str] = frozenset({"helmet", "vest", "gloves"})
NO_PPE = "No PPE"
# Safety-rule PPE values (as stored by the Admin UI) -> analyzer item names.
PPE_RULE_ITEMS = {
    "All PPE": ALL_PPE_ITEMS,
    "Helmet": frozenset({"helmet"}),
    "Safety Vest": frozenset({"vest"}),
    "Gloves": frozenset({"gloves"}),
    NO_PPE: frozenset(),
}


def required_items_from_rules(rules: Iterable[models.SafetyRule]) -> FrozenSet[str]:
    """Union of the location's PPE rules; ALL items when it has none.

    A restricted location requires nothing: wearing PPE does not make entry
    allowed, so only the restricted-area violation is raised there.
    """

    rules = list(rules)
    if any(rule.is_restricted_area for rule in rules):
        return frozenset()
    items = set()
    configured = False
    for rule in rules:
        rule_items = PPE_RULE_ITEMS.get(str(rule.ppe_type or "").strip())
        if rule_items is None:
            # Older rules may name PPE the analyzer does not judge (boots, goggles).
            logger.warning("Ignoring safety rule %s: PPE type %r is not detected", rule.id, rule.ppe_type)
            continue
        configured = True
        items.update(rule_items)
    return frozenset(items) if configured else ALL_PPE_ITEMS


def load_required_ppe_for_camera(
    camera_db_id: int,
    session_factory: Optional[Callable[[], Session]] = None,
) -> FrozenSet[str]:
    db = (session_factory or SessionLocal)()
    try:
        camera = db.get(models.Camera, int(camera_db_id))
        if camera is None:
            raise ValueError(f"Camera {camera_db_id} does not exist")
        rules = db.query(models.SafetyRule).filter(
            models.SafetyRule.location_id == camera.location_id
        ).all()
        return required_items_from_rules(rules)
    finally:
        db.close()


class PPERuleReloader:
    """Poll the camera's location rules so a running AI session follows edits.

    ``poll()`` returns the new required-item set only when it changed, and
    ``None`` otherwise (including on database errors, which are logged).
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
        self._current: Optional[FrozenSet[str]] = None
        self._last_check = 0.0

    def load(self) -> FrozenSet[str]:
        self._current = load_required_ppe_for_camera(self.camera_db_id, self.session_factory)
        self._last_check = self.clock()
        return self._current

    def poll(self) -> Optional[FrozenSet[str]]:
        now = self.clock()
        if self.interval_seconds <= 0 or now - self._last_check < self.interval_seconds:
            return None
        self._last_check = now
        try:
            items = load_required_ppe_for_camera(self.camera_db_id, self.session_factory)
        except Exception:
            logger.exception("Could not reload PPE rules for camera %s", self.camera_db_id)
            return None
        if items == self._current:
            return None
        self._current = items
        return items
