"""Reusable inference wrapper for the pretrained VisionGuard PPE model.

Engine: when an OpenVINO copy of the model exists next to the ``.pt`` file
(``<name>_openvino_model/``, made by ``python export_openvino.py``) it is used
instead of PyTorch.  On Intel CPUs it is about twice as fast and gives the
same detections.  Set ``VISIONGUARD_AI_ENGINE=pytorch`` to force PyTorch; a
missing, outdated or broken OpenVINO copy falls back to the ``.pt`` model.
"""

from dataclasses import dataclass
from functools import lru_cache
from importlib.util import find_spec
import logging
import os
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional, Tuple, TypedDict, Union

import numpy as np


DEFAULT_MODEL_PATH = Path(__file__).resolve().parent / "models" / "best_ppe_yolo11n.pt"
OPENVINO_DEVICE = "intel:cpu"
logger = logging.getLogger(__name__)


class PPEModelError(RuntimeError):
    """Raised when the PPE model cannot be loaded or used for inference."""


class Detection(TypedDict):
    """Normalized representation of one YOLO detection."""

    class_id: int
    class_name: str
    confidence: float
    bbox: List[float]


def _validate_confidence(confidence: float) -> float:
    value = float(confidence)
    if not 0.0 <= value <= 1.0:
        raise ValueError("confidence must be between 0.0 and 1.0")
    return value


@dataclass(frozen=True)
class LoadedModel:
    model: Any
    engine: str  # "openvino" or "pytorch"
    device: Optional[str]
    weights: Path


def openvino_model_dir(model_path: Union[str, Path]) -> Path:
    path = Path(model_path)
    return path.with_name(f"{path.stem}_openvino_model")


def _usable_openvino_dir(path: Path) -> Optional[Path]:
    if os.getenv("VISIONGUARD_AI_ENGINE", "auto").strip().lower() == "pytorch":
        return None
    folder = openvino_model_dir(path)
    xml = folder / f"{path.stem}.xml"
    if not xml.is_file() or find_spec("openvino") is None:
        return None
    if path.stat().st_mtime > xml.stat().st_mtime + 1:
        logger.warning("OpenVINO model is older than %s; using PyTorch. Run export_openvino.py again.", path.name)
        return None
    return folder


def _create_model(model_path: str) -> LoadedModel:
    path = Path(model_path)
    if not path.is_file():
        raise PPEModelError(f"PPE model file was not found: {path}")

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise PPEModelError(
            "Ultralytics is not installed. Run: python -m pip install -r requirements.txt"
        ) from exc

    folder = _usable_openvino_dir(path)
    if folder is not None:
        try:
            model = YOLO(str(folder), task="detect")
            # Without an explicit device Ultralytics prepares the model for
            # OpenVINO "AUTO", which also compiles it for the integrated GPU
            # (~20 s+).  Pin the CPU and warm up once at a webcam frame size.
            model.overrides["device"] = OPENVINO_DEVICE
            model.predict(np.zeros((720, 1280, 3), dtype=np.uint8), device=OPENVINO_DEVICE, verbose=False)
            return LoadedModel(model, "openvino", OPENVINO_DEVICE, folder)
        except Exception:
            logger.exception("OpenVINO model could not be loaded; using PyTorch instead")

    try:
        return LoadedModel(YOLO(str(path)), "pytorch", None, path)
    except Exception as exc:
        raise PPEModelError(f"Failed to load PPE model from {path}: {exc}") from exc


@lru_cache(maxsize=1)
def _load_model(model_path: str) -> LoadedModel:
    """Load and cache one YOLO model instance for the process lifetime."""

    return _create_model(model_path)


_instances: Dict[Tuple[str, str], LoadedModel] = {}
_instances_lock = threading.Lock()


def _load_model_instance(model_path: str, key: str) -> LoadedModel:
    """A model kept for one user (e.g. one live camera).

    Each live camera needs its own instance: ByteTrack's state lives inside
    the model, so two cameras sharing one would mix up their person IDs.
    The instance is reused the next time the same camera starts.
    """

    with _instances_lock:
        loaded = _instances.get((model_path, key))
        if loaded is None:
            loaded = _create_model(model_path)
            _instances[(model_path, key)] = loaded
        return loaded


class PPEDetector:
    """Run PPE inference using a single cached Ultralytics YOLO model."""

    def __init__(
        self,
        confidence: float = 0.25,
        model_path: Optional[Union[str, Path]] = None,
        instance_key: Optional[str] = None,
    ) -> None:
        self.confidence = _validate_confidence(confidence)
        self.model_path = Path(model_path or DEFAULT_MODEL_PATH).expanduser().resolve()
        loaded = (
            _load_model_instance(str(self.model_path), instance_key)
            if instance_key
            else _load_model(str(self.model_path))
        )
        self._model = loaded.model
        self.engine = loaded.engine
        self.device = loaded.device
        self.weights_path = loaded.weights
        self._class_names = self._read_class_names()

    def inference_options(self) -> Dict[str, Any]:
        """Extra keyword arguments for Ultralytics predict/track calls."""

        return {"device": self.device} if self.device else {}

    def after_inference(self) -> None:
        """With OpenVINO, PyTorch only runs the small post-processing step;
        its worker threads would otherwise compete with OpenVINO's.
        Ultralytics resets the thread count when it sets a model up, so this
        is re-applied after inference calls."""

        if self.engine == "openvino":
            import torch

            if torch.get_num_threads() != 1:
                torch.set_num_threads(1)

    @property
    def class_names(self) -> Dict[int, str]:
        """Return the class mapping reported by the loaded YOLO model."""

        return dict(self._class_names)

    @property
    def model(self) -> Any:
        """Expose the cached YOLO model to reusable adapters such as tracking."""

        return self._model

    def _read_class_names(self) -> Dict[int, str]:
        names = getattr(self._model, "names", None)
        if isinstance(names, dict):
            return {int(class_id): str(name) for class_id, name in names.items()}
        if isinstance(names, (list, tuple)):
            return {class_id: str(name) for class_id, name in enumerate(names)}
        raise PPEModelError("The loaded PPE model does not provide a valid model.names mapping.")

    def detect(self, source: Any, confidence: Optional[float] = None) -> List[Detection]:
        """Run inference on one image/frame and return normalized detections."""

        threshold = self.confidence if confidence is None else _validate_confidence(confidence)
        prediction_source = str(source) if isinstance(source, Path) else source

        try:
            results = self._model.predict(
                source=prediction_source,
                conf=threshold,
                verbose=False,
                **self.inference_options(),
            )
        except Exception as exc:
            raise PPEModelError(f"PPE inference failed: {exc}") from exc
        finally:
            self.after_inference()

        if not results:
            return []

        boxes = getattr(results[0], "boxes", None)
        if boxes is None:
            return []

        detections: List[Detection] = []
        for box in boxes:
            class_id = int(box.cls[0].item())
            coordinates = [float(value) for value in box.xyxy[0].cpu().tolist()]
            detections.append(
                {
                    "class_id": class_id,
                    "class_name": self._class_names.get(class_id, str(class_id)),
                    "confidence": float(box.conf[0].item()),
                    "bbox": coordinates,
                }
            )

        return detections
