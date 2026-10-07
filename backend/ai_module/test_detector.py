"""Standalone image, video, and webcam test runner for the PPE detector.

Run these examples from the backend directory::

    py -m ai_module.test_detector --source "ai_module/Tests/images/sample.jpg"
    py -m ai_module.test_detector --source "ai_module/Tests/videos/sample.mp4"
    py -m ai_module.test_detector --source 0

Annotated output is always written to ``ai_module/output``.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Iterable, Optional, Union

import cv2
import numpy as np

from .detector import Detection, PPEModelError, PPEDetector


OUTPUT_DIR = Path(__file__).resolve().parent / "output"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".m4v", ".webm"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Test the pretrained VisionGuard PPE model on an image, video, or webcam.",
        epilog=(
            'Examples:\n'
            '  py -m ai_module.test_detector --source "ai_module/Tests/images/sample.jpg"\n'
            '  py -m ai_module.test_detector --source "ai_module/Tests/videos/sample.mp4"\n'
            '  py -m ai_module.test_detector --source 0'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--source",
        required=True,
        help='Image/video path, or a webcam index such as "0".',
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=0.25,
        help="Minimum detection confidence between 0.0 and 1.0 (default: 0.25).",
    )
    parser.add_argument(
        "--save-video",
        action="store_true",
        help="Save an annotated copy when processing video or webcam input.",
    )
    return parser


def print_class_mapping(detector: PPEDetector) -> None:
    print("Supported model classes (model.names):")
    for class_id, class_name in sorted(detector.class_names.items()):
        print(f"  {class_id}: {class_name}")


def print_detections(detections: Iterable[Detection]) -> None:
    items = list(detections)
    if not items:
        print("No detections found.")
        return

    print(f"Detections ({len(items)}):")
    for index, detection in enumerate(items, start=1):
        bbox = ", ".join(f"{coordinate:.1f}" for coordinate in detection["bbox"])
        print(
            f"  {index}. class={detection['class_name']} "
            f"confidence={detection['confidence']:.4f} bbox=[{bbox}]"
        )


def class_color(class_id: int) -> tuple[int, int, int]:
    """Create a stable display color without assigning meaning to any class ID."""

    return (
        40 + (class_id * 67) % 190,
        80 + (class_id * 43) % 170,
        70 + (class_id * 97) % 180,
    )


def draw_detections(frame: np.ndarray, detections: Iterable[Detection]) -> np.ndarray:
    annotated = frame.copy()
    for detection in detections:
        x1, y1, x2, y2 = (int(round(value)) for value in detection["bbox"])
        color = class_color(detection["class_id"])
        label = f"{detection['class_name']} {detection['confidence']:.2f}"

        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        (text_width, text_height), baseline = cv2.getTextSize(
            label,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            2,
        )
        label_top = max(0, y1 - text_height - baseline - 8)
        label_right = min(annotated.shape[1] - 1, x1 + text_width + 10)
        cv2.rectangle(annotated, (x1, label_top), (label_right, y1), color, -1)
        cv2.putText(
            annotated,
            label,
            (x1 + 5, max(text_height + 2, y1 - baseline - 4)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
    return annotated


def run_image(detector: PPEDetector, image_path: Path) -> None:
    image = cv2.imread(str(image_path))
    if image is None:
        raise PPEModelError(f"OpenCV could not read the image: {image_path}")

    detections = detector.detect(image)
    print_detections(detections)
    annotated = draw_detections(image, detections)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = (OUTPUT_DIR / f"{image_path.stem}_annotated{image_path.suffix.lower()}").resolve()
    if not cv2.imwrite(str(output_path), annotated):
        raise PPEModelError(f"OpenCV could not save the annotated image: {output_path}")
    print(f"Annotated image saved to: {output_path}")


def create_video_writer(
    capture: cv2.VideoCapture,
    output_stem: str,
) -> tuple[cv2.VideoWriter, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = (OUTPUT_DIR / f"{output_stem}_annotated.mp4").resolve()
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = capture.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 0:
        fps = 30.0

    writer = cv2.VideoWriter(
        str(output_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        writer.release()
        raise PPEModelError(f"OpenCV could not create the output video: {output_path}")
    return writer, output_path


def run_stream(
    detector: PPEDetector,
    source: Union[Path, int],
    save_video: bool,
    is_webcam: bool,
) -> None:
    capture_source: Union[str, int] = source if isinstance(source, int) else str(source)
    capture = cv2.VideoCapture(capture_source)
    if not capture.isOpened():
        capture.release()
        source_label = f"webcam {source}" if is_webcam else str(source)
        raise PPEModelError(f"OpenCV could not open {source_label}.")

    writer: Optional[cv2.VideoWriter] = None
    output_path: Optional[Path] = None
    if save_video:
        output_stem = f"webcam_{source}" if is_webcam else Path(source).stem
        writer, output_path = create_video_writer(capture, output_stem)

    window_name = "VisionGuard PPE - Webcam" if is_webcam else "VisionGuard PPE - Video"
    smoothed_fps = 0.0
    previous_time = time.perf_counter()

    try:
        while True:
            success, frame = capture.read()
            if not success:
                break

            detections = detector.detect(frame)
            annotated = draw_detections(frame, detections)

            if is_webcam:
                current_time = time.perf_counter()
                elapsed = max(current_time - previous_time, 1e-9)
                current_fps = 1.0 / elapsed
                smoothed_fps = current_fps if smoothed_fps == 0.0 else (0.9 * smoothed_fps + 0.1 * current_fps)
                previous_time = current_time
                cv2.putText(
                    annotated,
                    f"FPS: {smoothed_fps:.1f}",
                    (15, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 255, 0),
                    2,
                    cv2.LINE_AA,
                )

            if writer is not None:
                writer.write(annotated)

            cv2.imshow(window_name, annotated)
            if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q")):
                break
    finally:
        capture.release()
        if writer is not None:
            writer.release()
        cv2.destroyAllWindows()

    if output_path is not None:
        print(f"Annotated video saved to: {output_path}")


def parse_source(source_value: str) -> tuple[str, Union[Path, int]]:
    stripped_source = source_value.strip()
    if stripped_source.isdigit():
        return "webcam", int(stripped_source)

    source_path = Path(stripped_source).expanduser().resolve()
    if not source_path.is_file():
        raise PPEModelError(f"Source file was not found: {source_path}")

    extension = source_path.suffix.lower()
    if extension in IMAGE_EXTENSIONS:
        return "image", source_path
    if extension in VIDEO_EXTENSIONS:
        return "video", source_path
    raise PPEModelError(
        f"Unsupported source type '{extension}'. Use a supported image, video, or webcam index."
    )


def main() -> int:
    args = build_parser().parse_args()

    try:
        detector = PPEDetector(confidence=args.confidence)
        print(f"Loaded PPE model: {detector.model_path}")
        print(f"Confidence threshold: {detector.confidence:.2f}")
        print_class_mapping(detector)

        source_type, source = parse_source(args.source)
        if source_type == "image":
            run_image(detector, source)
        elif source_type == "video":
            run_stream(detector, source, args.save_video, is_webcam=False)
        else:
            run_stream(detector, source, args.save_video, is_webcam=True)
        return 0
    except (PPEModelError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped by user.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
