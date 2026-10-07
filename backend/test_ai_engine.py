"""OpenVINO engine selection and fallback (uses the real model files).

Run:
    python test_ai_engine.py
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
import time

import cv2

from ai_module import detector as detector_module
from ai_module.detector import DEFAULT_MODEL_PATH, PPEDetector, openvino_model_dir


def _fresh(**kwargs) -> PPEDetector:
    detector_module._load_model.cache_clear()
    detector_module._instances.clear()
    return PPEDetector(**kwargs)


def _boxes(detector: PPEDetector, image) -> list:
    return sorted(
        (d["class_name"], round(d["confidence"], 2), tuple(round(v) for v in d["bbox"]))
        for d in detector.detect(image)
    )


def run_tests() -> None:
    assert openvino_model_dir(DEFAULT_MODEL_PATH).is_dir(), "run export_openvino.py first"
    image = cv2.resize(cv2.imread(str(Path(__file__).resolve().parent / "test.jpg")), (1280, 720))

    # The exported copy is used automatically and finds the same objects.
    fast = _fresh()
    assert fast.engine == "openvino" and fast.device == "intel:cpu", fast.engine
    os.environ["VISIONGUARD_AI_ENGINE"] = "pytorch"
    try:
        reference = _fresh()
        assert reference.engine == "pytorch" and reference.device is None
        expected = _boxes(reference, image)
    finally:
        os.environ.pop("VISIONGUARD_AI_ENGINE")
    found = _boxes(_fresh(), image)
    assert [b[0] for b in found] == [b[0] for b in expected], (found, expected)
    for (name, conf, box), (_, ref_conf, ref_box) in zip(found, expected):
        assert abs(conf - ref_conf) <= 0.02 and max(abs(a - b) for a, b in zip(box, ref_box)) <= 3, (name, conf, ref_conf)

    # Each live camera gets its own model; the same camera reuses it.
    one = _fresh(instance_key="camera-1")
    assert PPEDetector(instance_key="camera-1").model is one.model
    assert PPEDetector(instance_key="camera-2").model is not one.model

    with tempfile.TemporaryDirectory() as folder:
        weights = Path(folder) / "best_ppe_yolo11n.pt"
        shutil.copy2(DEFAULT_MODEL_PATH, weights)
        # No OpenVINO copy next to these weights -> PyTorch.
        assert _fresh(model_path=weights).engine == "pytorch"
        # An outdated copy (older than the .pt) is ignored.
        shutil.copytree(openvino_model_dir(DEFAULT_MODEL_PATH), openvino_model_dir(weights))
        assert _fresh(model_path=weights).engine == "openvino"
        old = time.time() - 3600
        for path in openvino_model_dir(weights).iterdir():
            os.utime(path, (old, old))
        os.utime(weights, None)  # the .pt was just replaced/retrained
        assert _fresh(model_path=weights).engine == "pytorch"
        # A broken copy falls back instead of failing.
        now = time.time() + 5
        xml = openvino_model_dir(weights) / "best_ppe_yolo11n.xml"
        xml.write_text("not a model", encoding="utf-8")
        os.utime(xml, (now, now))
        assert _fresh(model_path=weights).engine == "pytorch"

    detector_module._load_model.cache_clear()
    detector_module._instances.clear()
    print("AI engine tests passed:")
    print("  - OpenVINO copy used automatically, same detections as PyTorch")
    print("  - one model per live camera, reused when the camera reopens")
    print("  - falls back to PyTorch when the copy is missing, outdated, broken or disabled")


if __name__ == "__main__":
    run_tests()
