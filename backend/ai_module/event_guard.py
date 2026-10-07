"""Suppress repeat incidents for a person the tracker re-identified.

ByteTrack IDs are temporary: when detections flicker (low light, low FPS, an
unusual pose) the same person can lose an ID and come back under a new one,
and the temporal engines then confirm the "new" person again.  This guard
sits between confirmed events and incident creation and keeps one incident
per person presence:

* the same track repeating the same violation within the window is dropped;
* a new track repeating a violation is treated as the earlier person when
  that person's track has vanished and the new box appears near its last
  position, or when both boxes overlap (a duplicate box on one person);
* a PPE event that adds a new missing item is still reported.

Each report stays "open" while any of its tracks is visible and expires
``window_seconds`` after the person was last seen, so a later visit creates a
new incident.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


Box = Sequence[float]


def _iou(first: Box, second: Box) -> float:
    x1, y1 = max(first[0], second[0]), max(first[1], second[1])
    x2, y2 = min(first[2], second[2]), min(first[3], second[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area = lambda box: max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])
    union = area(first) + area(second) - intersection
    return intersection / union if union > 0.0 else 0.0


def _near(previous: Box, current: Box) -> bool:
    """Centres within one diagonal of the previous box."""

    diagonal = math.hypot(previous[2] - previous[0], previous[3] - previous[1])
    previous_centre = ((previous[0] + previous[2]) / 2.0, (previous[1] + previous[3]) / 2.0)
    current_centre = ((current[0] + current[2]) / 2.0, (current[1] + current[3]) / 2.0)
    return math.dist(previous_centre, current_centre) <= diagonal


@dataclass
class _Report:
    key: Tuple[str, ...]
    items: FrozenSet[str]
    track_ids: Set[int]
    last_seen: float
    last_box: Optional[Tuple[float, ...]] = None
    suppressed: int = field(default=0)


class RepeatEventGuard:
    def __init__(self, window_seconds: float = 20.0, overlap_iou: float = 0.3) -> None:
        if not math.isfinite(window_seconds) or window_seconds < 0.0:
            raise ValueError("window_seconds must be a finite value greater than or equal to 0")
        self.window_seconds = float(window_seconds)
        self.overlap_iou = float(overlap_iou)
        self._reports: List[_Report] = []

    def reset(self) -> None:
        self._reports.clear()

    @staticmethod
    def _key(event: object) -> Tuple[Tuple[str, ...], FrozenSet[str]]:
        zone_id = getattr(event, "zone_id", None)
        if zone_id is not None:
            return ("zone", str(zone_id)), frozenset()
        return ("ppe",), frozenset(str(item) for item in getattr(event, "missing_items", ()))

    def filter(
        self,
        events: Iterable[object],
        visible_boxes: Mapping[int, Box],
        timestamp: float,
    ) -> List[object]:
        """Return only the events that start a new incident.

        ``visible_boxes`` maps every person track in the current frame to its
        ``[x1, y1, x2, y2]`` box.
        """

        now = float(timestamp)
        # Expire first, so a person returning after the window is a new visit.
        self._reports = [r for r in self._reports if now - r.last_seen <= self.window_seconds]
        for report in self._reports:
            visible = [track_id for track_id in report.track_ids if track_id in visible_boxes]
            if visible:
                report.last_seen = now
                report.last_box = tuple(float(v) for v in visible_boxes[visible[0]])

        kept: List[object] = []
        for event in events:
            key, items = self._key(event)
            track_id = int(event.track_id)
            box = visible_boxes.get(track_id)
            report = self._match(key, items, track_id, box, visible_boxes)
            if report is not None:
                report.track_ids.add(track_id)
                report.items = report.items | items
                report.last_seen = now
                if box is not None:
                    report.last_box = tuple(float(v) for v in box)
                report.suppressed += 1
                continue
            self._reports.append(
                _Report(key, items, {track_id}, now, tuple(float(v) for v in box) if box is not None else None)
            )
            kept.append(event)
        return kept

    def _match(
        self,
        key: Tuple[str, ...],
        items: FrozenSet[str],
        track_id: int,
        box: Optional[Box],
        visible_boxes: Mapping[int, Box],
    ) -> Optional[_Report]:
        for report in self._reports:
            if report.key != key or not items <= report.items:
                continue
            if track_id in report.track_ids:
                return report
            if box is None:
                continue
            visible = [visible_boxes[t] for t in report.track_ids if t in visible_boxes]
            if visible:
                # Two IDs at once: same person only if the boxes overlap.
                if any(_iou(other, box) >= self.overlap_iou for other in visible):
                    return report
            elif report.last_box is None or _near(report.last_box, box):
                # Earlier ID vanished and a new one appeared where it was.
                return report
        return None
