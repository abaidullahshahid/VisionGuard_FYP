"""Geometry-based PPE-to-person association for single-frame analysis.

This module deliberately does not run YOLO itself. It consumes the normalized
``Detection`` dictionaries returned by :class:`ai_module.detector.PPEDetector`,
which keeps model loading and inference in one place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .detector import Detection


BBox = Tuple[float, float, float, float]
Candidate = Tuple[int, Detection]


def _normalized_name(name: str) -> str:
    return name.strip().lower().replace("-", "_").replace(" ", "_")


def _bbox(detection: Detection) -> BBox:
    x1, y1, x2, y2 = detection["bbox"]
    return float(x1), float(y1), float(x2), float(y2)


def _bbox_list(box: Sequence[float]) -> List[float]:
    return [float(value) for value in box]


def _dimensions(box: BBox) -> Tuple[float, float]:
    return max(0.0, box[2] - box[0]), max(0.0, box[3] - box[1])


def _area(box: BBox) -> float:
    width, height = _dimensions(box)
    return width * height


def _center(box: BBox) -> Tuple[float, float]:
    return (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0


def _intersection_area(first: BBox, second: BBox) -> float:
    width = max(0.0, min(first[2], second[2]) - max(first[0], second[0]))
    height = max(0.0, min(first[3], second[3]) - max(first[1], second[1]))
    return width * height


def _contains_point(box: BBox, point: Tuple[float, float]) -> bool:
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


def _expand_box(
    box: BBox,
    horizontal_fraction: float,
    top_fraction: float,
    bottom_fraction: float,
) -> BBox:
    width, height = _dimensions(box)
    return (
        box[0] - width * horizontal_fraction,
        box[1] - height * top_fraction,
        box[2] + width * horizontal_fraction,
        box[3] + height * bottom_fraction,
    )


@dataclass(frozen=True)
class AssociationConfig:
    """Tunable geometry thresholds for PPE association.

    Margins are fractions of the person's width/height. They intentionally
    allow small PPE boxes to be associated without requiring high IoU.
    """

    min_association_score: float = 0.32
    min_negative_association_score: float = 0.35
    min_item_overlap: float = 0.12

    helmet_horizontal_margin: float = 0.12
    helmet_top_margin: float = 0.20
    helmet_bottom_margin: float = 0.06
    helmet_target_y: float = 0.13
    helmet_y_tolerance: float = 0.42
    helmet_min_y: float = -0.20
    helmet_max_y: float = 0.48

    vest_horizontal_margin: float = 0.08
    vest_top_margin: float = 0.08
    vest_bottom_margin: float = 0.08
    vest_target_y: float = 0.42
    vest_y_tolerance: float = 0.48
    vest_min_y: float = 0.05
    vest_max_y: float = 0.82

    glove_horizontal_margin: float = 0.30
    glove_top_margin: float = 0.12
    glove_bottom_margin: float = 0.18
    glove_target_y: float = 0.50
    glove_y_tolerance: float = 0.72
    glove_min_y: float = -0.12
    glove_max_y: float = 1.15
    # Gloves are only judged when the hands can be in view.  The model's
    # "no_gloves" class almost never fires, so a missing glove detection is
    # not evidence by itself: a head-and-shoulders view (person box wider
    # than tall, e.g. someone sitting at a webcam) hides the hands.
    glove_visible_min_aspect: float = 1.0

    negative_person_area_ratio: float = 0.35
    negative_person_margin: float = 0.12
    negative_person_target_y: float = 0.50
    negative_person_y_tolerance: float = 0.70
    negative_person_min_y: float = -0.15
    negative_person_max_y: float = 1.15


@dataclass
class PPEItemStatus:
    """Association result for one PPE category on one person."""

    item_name: str
    detections: List[Detection] = field(default_factory=list)
    direct_negative_detection: Optional[Detection] = None
    # False when this body part cannot be seen, so the item cannot be judged.
    visible: bool = True

    @property
    def present(self) -> bool:
        return bool(self.detections)

    @property
    def confidence(self) -> Optional[float]:
        if not self.detections:
            return None
        return float(max(item["confidence"] for item in self.detections))

    @property
    def bbox(self) -> Optional[List[float]]:
        if not self.detections:
            return None
        best = max(self.detections, key=lambda item: item["confidence"])
        return _bbox_list(best["bbox"])

    @property
    def bboxes(self) -> List[List[float]]:
        return [_bbox_list(item["bbox"]) for item in self.detections]

    @property
    def direct_negative(self) -> bool:
        return self.direct_negative_detection is not None

    @property
    def direct_negative_confidence(self) -> Optional[float]:
        if self.direct_negative_detection is None:
            return None
        return float(self.direct_negative_detection["confidence"])

    def to_dict(self) -> Dict[str, object]:
        """Return JSON-safe built-in Python values."""

        negative_bbox = (
            _bbox_list(self.direct_negative_detection["bbox"])
            if self.direct_negative_detection is not None
            else None
        )
        return {
            "present": self.present,
            "confidence": self.confidence,
            "bbox": self.bbox,
            "bboxes": self.bboxes,
            "candidate_missing": not self.present and self.visible,
            "visible": self.visible,
            "direct_negative": self.direct_negative,
            "direct_negative_confidence": self.direct_negative_confidence,
            "direct_negative_bbox": negative_bbox,
        }


@dataclass
class PersonPPEStatus:
    """Candidate PPE compliance result for one detected person."""

    person_id: int
    person_detection: Detection
    helmet: PPEItemStatus
    vest: PPEItemStatus
    gloves: PPEItemStatus

    @property
    def person_bbox(self) -> List[float]:
        return _bbox_list(self.person_detection["bbox"])

    @property
    def person_confidence(self) -> float:
        return float(self.person_detection["confidence"])

    @property
    def missing_items(self) -> List[str]:
        return [
            item.item_name
            for item in (self.helmet, self.vest, self.gloves)
            if not item.present and item.visible
        ]

    @property
    def not_visible_items(self) -> List[str]:
        """Items that could not be checked because that body part is out of view."""

        return [
            item.item_name
            for item in (self.helmet, self.vest, self.gloves)
            if not item.present and not item.visible
        ]

    @property
    def compliant(self) -> bool:
        return not self.missing_items

    @property
    def candidate_violation(self) -> bool:
        return not self.compliant

    @property
    def status(self) -> str:
        return "COMPLIANT" if self.compliant else "PPE_VIOLATION"

    def to_dict(self) -> Dict[str, object]:
        """Return a result ready for ``json.dumps`` or a future API response."""

        missing_items = list(self.missing_items)
        return {
            "person_id": int(self.person_id),
            "person_bbox": self.person_bbox,
            "person_confidence": self.person_confidence,
            "ppe": {
                "helmet": self.helmet.to_dict(),
                "vest": self.vest.to_dict(),
                "gloves": self.gloves.to_dict(),
            },
            "missing_items": missing_items,
            "candidate_missing_items": missing_items,
            "not_visible_items": list(self.not_visible_items),
            "compliant": self.compliant,
            "candidate_violation": self.candidate_violation,
            "confirmed_incident": False,
            "status": self.status,
        }


class PPEAnalyzer:
    """Associate PPE detections with people using lightweight geometry."""

    PERSON = "person"
    HELMET = "helmet"
    VEST = "vest"
    GLOVES = "gloves"
    NO_HELMET = "no_helmet"
    NO_GLOVES = "no_gloves"

    def __init__(self, config: Optional[AssociationConfig] = None) -> None:
        self.config = config or AssociationConfig()

    def analyze(self, detections: Iterable[Detection]) -> List[PersonPPEStatus]:
        """Return per-person candidate PPE statuses for one image/frame."""

        indexed = list(enumerate(detections))
        by_name: Dict[str, List[Candidate]] = {}
        for index, detection in indexed:
            by_name.setdefault(_normalized_name(detection["class_name"]), []).append(
                (index, detection)
            )

        # Left-to-right ordering makes person numbering stable for demonstrations.
        people = sorted(
            by_name.get(self.PERSON, []),
            key=lambda item: (_center(_bbox(item[1]))[0], _center(_bbox(item[1]))[1]),
        )
        if not people:
            return []

        helmets = self._assign_single(people, by_name.get(self.HELMET, []), self.HELMET)
        vests = self._assign_single(people, by_name.get(self.VEST, []), self.VEST)
        gloves = self._assign_multiple(people, by_name.get(self.GLOVES, []), self.GLOVES)
        no_helmets = self._assign_single(
            people,
            by_name.get(self.NO_HELMET, []),
            self.HELMET,
            direct_negative=True,
        )
        no_gloves = self._assign_single(
            people,
            by_name.get(self.NO_GLOVES, []),
            self.GLOVES,
            direct_negative=True,
        )

        results: List[PersonPPEStatus] = []
        for person_index, (_, person_detection) in enumerate(people):
            results.append(
                PersonPPEStatus(
                    person_id=person_index + 1,
                    person_detection=person_detection,
                    helmet=PPEItemStatus(
                        item_name=self.HELMET,
                        detections=[helmets[person_index]] if person_index in helmets else [],
                        direct_negative_detection=no_helmets.get(person_index),
                    ),
                    vest=PPEItemStatus(
                        item_name=self.VEST,
                        detections=[vests[person_index]] if person_index in vests else [],
                    ),
                    gloves=PPEItemStatus(
                        item_name=self.GLOVES,
                        detections=gloves.get(person_index, []),
                        direct_negative_detection=no_gloves.get(person_index),
                        visible=(
                            person_index in gloves
                            or person_index in no_gloves
                            or self._hands_in_view(person_detection)
                        ),
                    ),
                )
            )
        return results

    def _hands_in_view(self, person_detection: Detection) -> bool:
        width, height = _dimensions(_bbox(person_detection))
        if width <= 0:
            return False
        return height / width >= self.config.glove_visible_min_aspect

    def analyze_as_dicts(self, detections: Iterable[Detection]) -> List[Dict[str, object]]:
        """Convenience wrapper returning JSON-ready dictionaries."""

        return [result.to_dict() for result in self.analyze(detections)]

    def _assign_single(
        self,
        people: Sequence[Candidate],
        candidates: Sequence[Candidate],
        item_kind: str,
        direct_negative: bool = False,
    ) -> Dict[int, Detection]:
        """Greedily make a one-to-one assignment for helmets/vests/negatives."""

        scored_pairs: List[Tuple[float, int, int, Detection]] = []
        minimum = (
            self.config.min_negative_association_score
            if direct_negative
            else self.config.min_association_score
        )
        for person_index, (_, person) in enumerate(people):
            for candidate_index, (_, candidate) in enumerate(candidates):
                score = self._association_score(
                    person,
                    candidate,
                    item_kind,
                    direct_negative=direct_negative,
                )
                if score is not None and score >= minimum:
                    scored_pairs.append(
                        (score, person_index, candidate_index, candidate)
                    )

        assignments: Dict[int, Detection] = {}
        assigned_candidates = set()
        for _, person_index, candidate_index, candidate in sorted(
            scored_pairs,
            key=lambda item: item[0],
            reverse=True,
        ):
            if person_index in assignments or candidate_index in assigned_candidates:
                continue
            assignments[person_index] = candidate
            assigned_candidates.add(candidate_index)
        return assignments

    def _assign_multiple(
        self,
        people: Sequence[Candidate],
        candidates: Sequence[Candidate],
        item_kind: str,
    ) -> Dict[int, List[Detection]]:
        """Assign each glove to its best person while allowing multiple gloves/person."""

        assignments: Dict[int, List[Detection]] = {}
        for _, candidate in candidates:
            scored_people = []
            for person_index, (_, person) in enumerate(people):
                score = self._association_score(person, candidate, item_kind)
                if score is not None and score >= self.config.min_association_score:
                    scored_people.append((score, person_index))
            if not scored_people:
                continue
            _, best_person = max(scored_people, key=lambda item: item[0])
            assignments.setdefault(best_person, []).append(candidate)

        for detections in assignments.values():
            detections.sort(key=lambda item: item["confidence"], reverse=True)
        return assignments

    def _association_score(
        self,
        person: Detection,
        candidate: Detection,
        item_kind: str,
        direct_negative: bool = False,
    ) -> Optional[float]:
        person_box = _bbox(person)
        candidate_box = _bbox(candidate)
        person_width, person_height = _dimensions(person_box)
        if person_width <= 0.0 or person_height <= 0.0 or _area(candidate_box) <= 0.0:
            return None

        candidate_area_ratio = _area(candidate_box) / max(_area(person_box), 1e-9)
        if (
            direct_negative
            and candidate_area_ratio > self.config.negative_person_area_ratio
        ):
            # Some negative labels cover much of the person rather than only a
            # head/hand region, so treat those as person-region evidence.
            margin_x = margin_top = margin_bottom = self.config.negative_person_margin
            target_y = self.config.negative_person_target_y
            tolerance_y = self.config.negative_person_y_tolerance
            min_y = self.config.negative_person_min_y
            max_y = self.config.negative_person_max_y
        elif item_kind == self.HELMET:
            margin_x = self.config.helmet_horizontal_margin
            margin_top = self.config.helmet_top_margin
            margin_bottom = self.config.helmet_bottom_margin
            target_y = self.config.helmet_target_y
            tolerance_y = self.config.helmet_y_tolerance
            min_y, max_y = self.config.helmet_min_y, self.config.helmet_max_y
        elif item_kind == self.VEST:
            margin_x = self.config.vest_horizontal_margin
            margin_top = self.config.vest_top_margin
            margin_bottom = self.config.vest_bottom_margin
            target_y = self.config.vest_target_y
            tolerance_y = self.config.vest_y_tolerance
            min_y, max_y = self.config.vest_min_y, self.config.vest_max_y
        else:
            margin_x = self.config.glove_horizontal_margin
            margin_top = self.config.glove_top_margin
            margin_bottom = self.config.glove_bottom_margin
            target_y = self.config.glove_target_y
            tolerance_y = self.config.glove_y_tolerance
            min_y, max_y = self.config.glove_min_y, self.config.glove_max_y

        expanded_person = _expand_box(
            person_box,
            horizontal_fraction=margin_x,
            top_fraction=margin_top,
            bottom_fraction=margin_bottom,
        )
        candidate_center = _center(candidate_box)
        relative_x = (candidate_center[0] - person_box[0]) / person_width
        relative_y = (candidate_center[1] - person_box[1]) / person_height
        if not min_y <= relative_y <= max_y:
            return None

        overlap_fraction = _intersection_area(person_box, candidate_box) / max(
            _area(candidate_box), 1e-9
        )
        center_in_person = _contains_point(person_box, candidate_center)
        center_in_expanded = _contains_point(expanded_person, candidate_center)
        if not center_in_expanded and overlap_fraction < self.config.min_item_overlap:
            return None

        center_score = 1.0 if center_in_person else (0.65 if center_in_expanded else 0.25)
        vertical_score = max(0.0, 1.0 - abs(relative_y - target_y) / tolerance_y)
        horizontal_score = max(0.0, 1.0 - abs(relative_x - 0.5) / (0.5 + margin_x))
        confidence = min(1.0, max(0.0, float(candidate["confidence"])))

        # Containment matters most; vertical position then distinguishes head,
        # torso, and hand candidates without demanding high box IoU.
        return (
            0.38 * min(1.0, overlap_fraction)
            + 0.22 * center_score
            + 0.17 * vertical_score
            + 0.08 * horizontal_score
            + 0.15 * confidence
        )
