"""Create the OpenVINO copy of the PPE model (about 2x faster on Intel CPUs).

Run once, and again whenever best_ppe_yolo11n.pt is replaced or retrained:
    venv\\Scripts\\python export_openvino.py

The .pt file is not changed.  The backend uses the copy automatically
(ai_module/detector.py) and falls back to the .pt model without it; delete
the ai_module/models/best_ppe_yolo11n_openvino_model folder to undo.
"""

from pathlib import Path
import shutil
import time

import cv2
import numpy as np
import torch
from ultralytics import YOLO

from ai_module.detector import DEFAULT_MODEL_PATH, OPENVINO_DEVICE, openvino_model_dir


def main() -> None:
    target = openvino_model_dir(DEFAULT_MODEL_PATH)
    if target.exists():
        shutil.rmtree(target)
    # dynamic=True keeps the same input shape PyTorch uses (no extra square
    # padding), so detections match the .pt model; FP32 keeps full precision.
    exported = YOLO(str(DEFAULT_MODEL_PATH)).export(format="openvino", imgsz=640, dynamic=True, half=False)
    print(f"OpenVINO model saved to {exported}")

    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    sample = Path(__file__).resolve().parent / "test.jpg"
    if sample.is_file():
        frame = cv2.resize(cv2.imread(str(sample)), (1280, 720))
    for label, model, options in (
        ("PyTorch ", YOLO(str(DEFAULT_MODEL_PATH)), {}),
        ("OpenVINO", YOLO(str(target), task="detect"), {"device": OPENVINO_DEVICE}),
    ):
        if label == "OpenVINO":
            torch.set_num_threads(1)  # as the backend does when OpenVINO is used
        model.predict(frame, verbose=False, **options)
        started = time.perf_counter()
        for _ in range(10):
            model.predict(frame, verbose=False, **options)
        per_frame = (time.perf_counter() - started) / 10
        print(f"{label}: {per_frame * 1000:.0f} ms per frame (~{1 / per_frame:.0f} FPS)")


if __name__ == "__main__":
    main()
