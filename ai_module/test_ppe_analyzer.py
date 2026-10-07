"""Standalone image/directory/webcam test runner for PPE-person analysis.

Run from the backend directory::

    python -m ai_module.test_ppe_analyzer --source "ai_module/Tests/images/test.jpg"
    python -m ai_module.test_ppe_analyzer --source "ai_module/Tests/images"
    python -m ai_module.test_ppe_analyzer --source 0
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple, Union

import cv2
import numpy as np

from .detector import PPEModelError, PPEDetector
from .ppe_analyzer import PPEAnalyzer, PPEItemStatus, PersonPPEStatus


OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "ppe_analysis"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".m4v", ".webm"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze candidate PPE compliance for each detected person.",
        epilog=(
            "Examples:\n"
            '  python -m ai_module.test_ppe_analyzer --source "ai_module/Tests/images/test.jpg"\n'
            '  python -m ai_module.test_ppe_analyzer --source "ai_module/Tests/images"\n'
            "  python -m ai_module.test_ppe_analyzer --source 0"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--source",
        required=True,
        help="An image path, image directory, or webcam index such as 0.",
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=0.25,
        help="YOLO detection confidence threshold (default: 0.25).",
    )
    return parser


def print_class_mapping(detector: PPEDetector) -> None:
    print("Supported model classes (model.names):")
    for class_id, class_name in sorted(detector.class_names.items()):
        print(f"  {class_id}: {class_name}")


def _format_item(status: PPEItemStatus, negative_name: str = "") -> str:
    if status.present:
        return f"PRESENT ({status.confidence:.2f})"
    if status.direct_negative and negative_name:
        return (
            f"MISSING (supported by {negative_name} "
            f"{status.direct_negative_confidence:.2f})"
        )
    return "MISSING"


def print_report(image_name: str, statuses: Sequence[PersonPPEStatus]) -> None:
    print("\n" + "=" * 52)
    print(f"Image: {image_name}")
    print("=" * 52)

    if not statuses:
        print("No Person detections found; no PPE decision was made.")
        return

    for status in statuses:
        print(f"\nPerson #{status.person_id}")
        print(f"Confidence: {status.person_confidence:.2f}")
        print(f"Helmet: {_format_item(status.helmet, 'no_helmet')}")
        print(f"Vest: {_format_item(status.vest)}")
        print(f"Gloves: {_format_item(status.gloves, 'no_gloves')}")
        print("\nMissing PPE:")
        if status.missing_items:
            for item in status.missing_items:
                print(f"- {item}")
        else:
            print("NONE")
        print(f"\nStatus: {status.status}")
        if status.candidate_violation:
            print("Assessment: CANDIDATE ONLY (not a confirmed incident)")


def _clip_box(box: Iterable[float], image: np.ndarray) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = (int(round(float(value))) for value in box)
    height, width = image.shape[:2]
    return (
        max(0, min(width - 1, x1)),
        max(0, min(height - 1, y1)),
        max(0, min(width - 1, x2)),
        max(0, min(height - 1, y2)),
    )


def _draw_box_label(
    image: np.ndarray,
    box: Iterable[float],
    label: str,
    color: Tuple[int, int, int],
    thickness: int = 2,
) -> None:
    x1, y1, x2, y2 = _clip_box(box, image)
    cv2.rectangle(image, (x1, y1), (x2, y2), color, thickness)
    (text_width, text_height), baseline = cv2.getTextSize(
        label,
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        2,
    )
    label_y1 = max(0, y1 - text_height - baseline - 8)
    label_x2 = min(image.shape[1] - 1, x1 + text_width + 10)
    cv2.rectangle(image, (x1, label_y1), (label_x2, y1), color, -1)
    cv2.putText(
        image,
        label,
        (x1 + 5, max(text_height + 2, y1 - baseline - 4)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )


def _draw_person_box(
    image: np.ndarray,
    status: PersonPPEStatus,
    color: Tuple[int, int, int],
    compact: bool = False,
) -> None:
    """Draw one person box with a compact banner kept inside the image."""

    x1, y1, x2, y2 = _clip_box(status.person_bbox, image)
    cv2.rectangle(image, (x1, y1), (x2, y2), color, 3)
    if status.compliant:
        lines = [f"Person {status.person_id} | COMPLIANT"]
    elif compact:
        short_names = {"helmet": "H", "vest": "V", "gloves": "G"}
        missing_codes = ",".join(short_names[item] for item in status.missing_items)
        lines = [f"P{status.person_id} | Missing: {missing_codes}"]
    else:
        lines = [
            f"Person {status.person_id} | CANDIDATE",
            f"Missing: {', '.join(status.missing_items)}",
        ]
    font_scale = 0.40 if compact else 0.48
    thickness = 2
    available_width = max(60, image.shape[1] - x1 - 4)
    initial_text_width = max(
        cv2.getTextSize(
            line,
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            thickness,
        )[0][0]
        for line in lines
    )
    if initial_text_width + 12 > available_width:
        font_scale = max(0.28, font_scale * available_width / (initial_text_width + 12))
    text_width = max(
        cv2.getTextSize(
            line,
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            thickness,
        )[0][0]
        for line in lines
    )
    line_height = max(14, int(round(19 * font_scale / 0.48)))
    banner_right = min(image.shape[1] - 1, x1 + text_width + 12)
    banner_bottom = min(y2, y1 + 7 + line_height * len(lines))
    cv2.rectangle(image, (x1, y1), (banner_right, banner_bottom), color, -1)
    for line_index, line in enumerate(lines):
        text_y = min(y2 - 3, y1 + 16 + line_index * line_height)
        cv2.putText(
            image,
            line,
            (x1 + 5, text_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (255, 255, 255),
            thickness,
            cv2.LINE_AA,
        )


def draw_analysis(image: np.ndarray, statuses: Sequence[PersonPPEStatus]) -> np.ndarray:
    annotated = image.copy()
    ppe_colors = {
        "helmet": (255, 150, 40),
        "vest": (0, 165, 255),
        "gloves": (210, 80, 210),
    }

    crowded_scene = len(statuses) > 6
    # Draw PPE first so the main per-person summary remains readable on top.
    for status in statuses:
        for item in (status.helmet, status.vest, status.gloves):
            for index, item_box in enumerate(item.bboxes):
                confidence = item.detections[index]["confidence"]
                if crowded_scene:
                    x1, y1, x2, y2 = _clip_box(item_box, annotated)
                    cv2.rectangle(
                        annotated,
                        (x1, y1),
                        (x2, y2),
                        ppe_colors[item.item_name],
                        2,
                    )
                else:
                    _draw_box_label(
                        annotated,
                        item_box,
                        f"{item.item_name} {confidence:.2f}",
                        ppe_colors[item.item_name],
                    )

        for item, label in (
            (status.helmet, "no_helmet"),
            (status.gloves, "no_gloves"),
        ):
            if item.present or item.direct_negative_detection is None:
                continue
            _draw_box_label(
                annotated,
                item.direct_negative_detection["bbox"],
                f"{label} {item.direct_negative_confidence:.2f}",
                (0, 0, 200),
            )

    for status in statuses:
        person_color = (30, 190, 80) if status.compliant else (20, 60, 230)
        _draw_person_box(annotated, status, person_color, compact=crowded_scene)
    return annotated


def analyze_image(
    detector: PPEDetector,
    analyzer: PPEAnalyzer,
    image_path: Path,
) -> List[PersonPPEStatus]:
    image = cv2.imread(str(image_path))
    if image is None:
        raise PPEModelError(f"OpenCV could not read the image: {image_path}")

    detections = detector.detect(image)
    statuses = analyzer.analyze(detections)
    # This also verifies that analyzer results contain only JSON-safe values.
    json.dumps([status.to_dict() for status in statuses])
    print_report(image_path.name, statuses)

    annotated = draw_analysis(image, statuses)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = (
        OUTPUT_DIR / f"{image_path.stem}_ppe_analysis{image_path.suffix.lower()}"
    ).resolve()
    if not cv2.imwrite(str(output_path), annotated):
        raise PPEModelError(f"OpenCV could not save the analysis image: {output_path}")
    print(f"\nAnnotated analysis saved to: {output_path}")
    return statuses


def image_files(directory: Path) -> List[Path]:
    return sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def run_webcam(detector: PPEDetector, analyzer: PPEAnalyzer, camera_index: int) -> None:
    capture = cv2.VideoCapture(camera_index)
    if not capture.isOpened():
        capture.release()
        raise PPEModelError(f"OpenCV could not open webcam {camera_index}.")

    previous_time = time.perf_counter()
    smoothed_fps = 0.0
    window_name = "VisionGuard Candidate PPE Analysis"
    print("Webcam analysis started. Press Q to quit.")
    print("Results are frame-level candidates only; no incidents are confirmed.")

    try:
        while True:
            success, frame = capture.read()
            if not success:
                raise PPEModelError("The webcam stopped returning frames.")

            detections = detector.detect(frame)
            statuses = analyzer.analyze(detections)
            annotated = draw_analysis(frame, statuses)

            current_time = time.perf_counter()
            elapsed = max(current_time - previous_time, 1e-9)
            current_fps = 1.0 / elapsed
            smoothed_fps = (
                current_fps
                if smoothed_fps == 0.0
                else 0.9 * smoothed_fps + 0.1 * current_fps
            )
            previous_time = current_time
            cv2.putText(
                annotated,
                f"FPS: {smoothed_fps:.1f} | Candidate analysis only",
                (15, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.75,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )
            cv2.imshow(window_name, annotated)
            if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q")):
                break
    finally:
        capture.release()
        cv2.destroyAllWindows()


def resolve_source(source_value: str) -> Tuple[str, Union[int, Path]]:
    stripped = source_value.strip()
    if stripped.isdigit():
        return "webcam", int(stripped)

    path = Path(stripped).expanduser().resolve()
    if path.is_dir():
        return "directory", path
    if not path.is_file():
        raise PPEModelError(f"Source was not found: {path}")
    if path.suffix.lower() in IMAGE_EXTENSIONS:
        return "image", path
    if path.suffix.lower() in VIDEO_EXTENSIONS:
        raise PPEModelError(
            "This stage is image-first. Use an image, image directory, or webcam; "
            "existing raw video tests remain available through ai_module.test_detector."
        )
    raise PPEModelError(f"Unsupported source type: {path.suffix or '(no extension)'}")


def main() -> int:
    args = build_parser().parse_args()
    try:
        detector = PPEDetector(confidence=args.confidence)
        analyzer = PPEAnalyzer()
        print(f"Loaded PPE model: {detector.model_path}")
        print(f"Confidence threshold: {detector.confidence:.2f}")
        print_class_mapping(detector)

        source_type, source = resolve_source(args.source)
        if source_type == "webcam":
            run_webcam(detector, analyzer, source)
        elif source_type == "image":
            analyze_image(detector, analyzer, source)
        else:
            images = image_files(source)
            if not images:
                raise PPEModelError(f"No supported images were found in: {source}")
            print(f"Found {len(images)} image(s) to analyze.")
            for image_path in images:
                analyze_image(detector, analyzer, image_path)
        return 0
    except (PPEModelError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped by user.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
