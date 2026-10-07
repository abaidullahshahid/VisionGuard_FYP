"""Persistent person tracking built on Ultralytics ByteTrack.

The tracker runs the existing PPE YOLO model once per frame.  Its normalized
detections can therefore be passed directly to :class:`PPEAnalyzer` without a
second inference pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec
from typing import Any, Dict, List, Optional

from .detector import Detection, PPEDetector, PPEModelError


class TrackingError(RuntimeError):
    """Raised when ByteTrack cannot process a frame."""


def _normalized_name(name: str) -> str:
    return name.strip().lower().replace("-", "_").replace(" ", "_")


@dataclass(frozen=True)
class TrackedPerson:
    """A person detection with a temporary ByteTrack identity."""

    track_id: int
    detection: Detection

    @property
    def bbox(self) -> List[float]:
        return [float(value) for value in self.detection["bbox"]]

    @property
    def confidence(self) -> float:
        return float(self.detection["confidence"])

    def to_dict(self) -> Dict[str, object]:
        return {
            "track_id": int(self.track_id),
            "class_id": int(self.detection["class_id"]),
            "class_name": str(self.detection["class_name"]),
            "confidence": self.confidence,
            "bbox": self.bbox,
        }


@dataclass(frozen=True)
class TrackingFrame:
    """Normalized detector output and the tracked people in one frame."""

    detections: List[Detection]
    people: List[TrackedPerson]

    def to_dict(self) -> Dict[str, object]:
        return {
            "detections": [dict(detection) for detection in self.detections],
            "tracked_people": [person.to_dict() for person in self.people],
        }


class PersonTracker:
    """Use ByteTrack to keep temporary integer IDs for detected people."""

    PERSON_CLASS_NAME = "person"

    def __init__(self, detector: PPEDetector, tracker_config: str = "bytetrack.yaml") -> None:
        self.detector = detector
        self.tracker_config = tracker_config

    def track(self, frame: Any, confidence: Optional[float] = None) -> TrackingFrame:
        """Track one BGR frame and return all PPE detections plus tracked people."""

        if find_spec("lap") is None:
            raise TrackingError(
                "Ultralytics ByteTrack requires lap>=0.5.12. "
                "Install backend requirements before running tracking."
            )

        threshold = self.detector.confidence if confidence is None else float(confidence)
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")

        try:
            results = self.detector.model.track(
                source=frame,
                conf=threshold,
                persist=True,
                tracker=self.tracker_config,
                verbose=False,
                **getattr(self.detector, "inference_options", dict)(),
            )
        except Exception as exc:
            raise TrackingError(f"ByteTrack inference failed: {exc}") from exc
        finally:
            settle = getattr(self.detector, "after_inference", None)
            if callable(settle):
                settle()

        if not results:
            return TrackingFrame(detections=[], people=[])

        boxes = getattr(results[0], "boxes", None)
        if boxes is None:
            return TrackingFrame(detections=[], people=[])

        detections: List[Detection] = []
        people: List[TrackedPerson] = []
        class_names = self.detector.class_names

        for box in boxes:
            class_id = int(box.cls[0].item())
            detection: Detection = {
                "class_id": class_id,
                "class_name": class_names.get(class_id, str(class_id)),
                "confidence": float(box.conf[0].item()),
                "bbox": [float(value) for value in box.xyxy[0].cpu().tolist()],
            }
            detections.append(detection)

            track_tensor = getattr(box, "id", None)
            if (
                _normalized_name(detection["class_name"]) == self.PERSON_CLASS_NAME
                and track_tensor is not None
                and len(track_tensor) > 0
            ):
                people.append(
                    TrackedPerson(
                        track_id=int(track_tensor[0].item()),
                        detection=detection,
                    )
                )

        return TrackingFrame(detections=detections, people=people)

    def reset(self) -> None:
        """Clear ByteTrack state before a different video or camera stream."""

        predictor = getattr(self.detector.model, "predictor", None)
        for tracker in getattr(predictor, "trackers", []) or []:
            reset = getattr(tracker, "reset", None)
            if callable(reset):
                reset()

