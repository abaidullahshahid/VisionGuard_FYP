"""Standalone realtime test runner for VisionGuard PPE and zone events.

Run from the backend directory::

    python -m ai_module.test_realtime_pipeline --source "ai_module/Tests/videos/video.mp4"
    python -m ai_module.test_realtime_pipeline --source "ai_module/Tests/videos/video.mp4" --zones "ai_module/Tests/zones/test_zones.json" --camera-id "test_camera_1"
    python -m ai_module.test_realtime_pipeline --source 0 --camera-db-id 3 --persist-incidents
    python -m ai_module.test_realtime_pipeline --source "ai_module/Tests/videos" --save-video

Restricted zones: an explicit ``--zones`` JSON file wins; otherwise
``--camera-db-id`` loads that camera's enabled zones from the database (and
re-checks them every ``--zone-reload-seconds``); otherwise PPE only.

Required PPE: with ``--camera-db-id`` only the items named by the camera
location's safety rules are enforced (all of helmet/vest/gloves when the
location has no PPE rules), re-checked on the same interval; otherwise all.
A location marked restricted in Safety Rules checks no PPE and treats the
camera's whole view as one restricted zone: anyone seen there is a violation.
    python -m ai_module.test_realtime_pipeline --source 0
    python -m ai_module.test_realtime_pipeline --self-test

Press Q to stop an OpenCV video/webcam window.  Annotated recordings are
written only to ``ai_module/output/realtime``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import cv2
import numpy as np

from .detector import PPEModelError
from .incident_manager import Incident, IncidentManager, IncidentManagerError
from .realtime_pipeline import RealtimeFrameResult, RealtimePPEPipeline
from .tracker import TrackingError
from .violation_engine import TemporalViolationEngine, ViolationEngineConfig
from .zone_analyzer import RestrictedZone, load_zones
from .zone_violation_engine import ZoneTransition, ZoneViolationConfig

if TYPE_CHECKING:
    from services.ppe_rule_service import PPERuleReloader
    from services.restricted_zone_service import RestrictedZoneReloader


OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "realtime"
INCIDENT_OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "incidents"
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".m4v", ".webm"}


@dataclass
class RunSummary:
    source: str
    zones_configured: bool = False
    frames_processed: int = 0
    events: int = 0
    ppe_events: int = 0
    zone_events: int = 0
    incidents: int = 0
    ppe_incidents: int = 0
    zone_incidents: int = 0
    severities: Counter = field(default_factory=Counter)
    evidence_paths: List[str] = field(default_factory=list)
    unique_track_ids: set = field(default_factory=set)
    observations_by_track: Counter = field(default_factory=Counter)
    longest_streak_by_track: Dict[int, int] = field(default_factory=dict)
    _current_streak_by_track: Dict[int, int] = field(default_factory=dict)
    _last_frame_by_track: Dict[int, int] = field(default_factory=dict)

    def observe(self, track_ids: Iterable[int], frame_number: int) -> None:
        for track_id in track_ids:
            self.unique_track_ids.add(track_id)
            self.observations_by_track[track_id] += 1
            previous_frame = self._last_frame_by_track.get(track_id)
            current = (
                self._current_streak_by_track.get(track_id, 0) + 1
                if previous_frame == frame_number - 1
                else 1
            )
            self._current_streak_by_track[track_id] = current
            self._last_frame_by_track[track_id] = frame_number
            self.longest_streak_by_track[track_id] = max(
                self.longest_streak_by_track.get(track_id, 0), current
            )

    def record_events(self, events: Iterable[object]) -> None:
        for event in events:
            self.events += 1
            if getattr(event, "event_type", "") == "RESTRICTED_ZONE_VIOLATION":
                self.zone_events += 1
            else:
                self.ppe_events += 1

    def record_incidents(self, incidents: Iterable[Incident]) -> None:
        for incident in incidents:
            self.incidents += 1
            if incident.incident_type == "RESTRICTED_ZONE_VIOLATION":
                self.zone_incidents += 1
            else:
                self.ppe_incidents += 1
            self.severities[incident.severity] += 1
            if incident.evidence_path:
                self.evidence_paths.append(incident.evidence_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Test ByteTrack with temporal PPE and restricted-zone confirmation.",
        epilog=(
            "Examples:\n"
            '  python -m ai_module.test_realtime_pipeline --source "ai_module/Tests/videos/video.mp4"\n'
            '  python -m ai_module.test_realtime_pipeline --source "ai_module/Tests/videos/video.mp4" --zones "ai_module/Tests/zones/test_zones.json" --camera-id "test_camera_1" --save-video --save-incidents\n'
            '  python -m ai_module.test_realtime_pipeline --source "ai_module/Tests/videos/video.mp4" --camera-db-id 1 --persist-incidents\n'
            '  python -m ai_module.test_realtime_pipeline --source "ai_module/Tests/videos" --save-video\n'
            "  python -m ai_module.test_realtime_pipeline --source 0\n"
            "  python -m ai_module.test_realtime_pipeline --self-test"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--source",
        help="Video path, directory containing videos, or webcam index such as 0.",
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=0.25,
        help="YOLO confidence threshold (default: 0.25).",
    )
    parser.add_argument(
        "--confirmation-seconds",
        type=float,
        default=2.0,
        help="Continuous candidate duration required to confirm (default: 2.0).",
    )
    parser.add_argument(
        "--cooldown-seconds",
        type=float,
        default=10.0,
        help="Minimum gap between duplicate active-track events (default: 10.0).",
    )
    parser.add_argument(
        "--grace-seconds",
        type=float,
        default=0.5,
        help="Sustained compliance needed to clear flicker (default: 0.5).",
    )
    parser.add_argument(
        "--track-expiration-seconds",
        type=float,
        default=8.0,
        help="Remove inactive temporal state after this duration (default: 8.0).",
    )
    parser.add_argument(
        "--zones",
        help=(
            "Optional JSON file containing restricted-zone polygons. Takes precedence "
            "over database zones loaded through --camera-db-id."
        ),
    )
    parser.add_argument(
        "--zone-reload-seconds",
        type=float,
        default=5.0,
        help=(
            "With --camera-db-id, re-check the camera's database zones (unless "
            "--zones is given) and its location's PPE rules this often during a "
            "run; 0 disables reloading (default: 5.0)."
        ),
    )
    parser.add_argument(
        "--zone-confirmation-seconds",
        type=float,
        default=1.5,
        help="Time inside a zone required to confirm (default: 1.5).",
    )
    parser.add_argument(
        "--zone-grace-seconds",
        type=float,
        default=0.5,
        help="Continuous time outside required to resolve (default: 0.5).",
    )
    parser.add_argument(
        "--camera-id",
        help="Optional camera identifier included in generated incidents.",
    )
    parser.add_argument(
        "--camera-db-id",
        type=int,
        help=(
            "Existing cameras.id: loads that camera's enabled restricted zones "
            "(unless --zones is given) and its location's required PPE, and is "
            "used when persisting incidents."
        ),
    )
    parser.add_argument(
        "--persist-incidents",
        action="store_true",
        help="Persist generated incidents through the SQLAlchemy service bridge.",
    )
    parser.add_argument(
        "--save-incidents",
        action="store_true",
        help="Save the generated list[dict] report under ai_module/output/incidents.",
    )
    parser.add_argument(
        "--save-video",
        action="store_true",
        help="Save annotated MP4 output under ai_module/output/realtime.",
    )
    parser.add_argument(
        "--no-display",
        action="store_true",
        help="Disable OpenCV windows (useful for unattended directory tests).",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        help="Optional frame limit for a quick or headless test.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run deterministic synthetic timing tests without loading YOLO.",
    )
    return parser


def _clip_box(box: Sequence[float], image: np.ndarray) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = (int(round(float(value))) for value in box)
    height, width = image.shape[:2]
    return (
        max(0, min(width - 1, x1)),
        max(0, min(height - 1, y1)),
        max(0, min(width - 1, x2)),
        max(0, min(height - 1, y2)),
    )


def _draw_label(
    image: np.ndarray,
    box: Sequence[float],
    label: str,
    color: Tuple[int, int, int],
) -> None:
    x1, y1, x2, y2 = _clip_box(box, image)
    scale = max(0.45, min(0.8, image.shape[1] / 2400.0))
    thickness = max(2, int(round(scale * 3)))
    cv2.rectangle(image, (x1, y1), (x2, y2), color, thickness)
    (text_width, text_height), baseline = cv2.getTextSize(
        label, cv2.FONT_HERSHEY_SIMPLEX, scale, 2
    )
    banner_y1 = max(0, y1 - text_height - baseline - 9)
    banner_x2 = min(image.shape[1] - 1, x1 + text_width + 12)
    cv2.rectangle(image, (x1, banner_y1), (banner_x2, y1), color, -1)
    cv2.putText(
        image,
        label,
        (x1 + 5, max(text_height + 2, y1 - baseline - 4)),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )


def draw_realtime_result(
    frame: np.ndarray,
    result: RealtimeFrameResult,
    fps: float,
) -> np.ndarray:
    """Draw exactly one primary box/label for each tracked person."""

    annotated = frame.copy()
    if result.zones:
        overlay = annotated.copy()
        for resolved_zone in result.zones:
            polygon = np.rint(np.asarray(resolved_zone.pixel_polygon)).astype(np.int32)
            cv2.fillPoly(overlay, [polygon], (30, 30, 210))
        cv2.addWeighted(overlay, 0.14, annotated, 0.86, 0.0, annotated)
        for resolved_zone in result.zones:
            polygon = np.rint(np.asarray(resolved_zone.pixel_polygon)).astype(np.int32)
            cv2.polylines(annotated, [polygon], True, (20, 20, 235), 4, cv2.LINE_AA)
            label_x = max(5, int(np.min(polygon[:, 0])))
            label_y = max(58, int(np.min(polygon[:, 1])) - 10)
            cv2.putText(
                annotated,
                f"RESTRICTED: {resolved_zone.zone.name}",
                (label_x, label_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.72,
                (20, 20, 235),
                2,
                cv2.LINE_AA,
            )

    for person in result.people:
        temporal = person.violation_state
        if not result.zones:
            if temporal.confirmed_items:
                color = (20, 20, 230)
                label = (
                    f"ID {person.track_id} | VIOLATION: "
                    f"{', '.join(temporal.confirmed_items)}"
                )
            elif temporal.candidate_items:
                color = (0, 165, 255)
                label = (
                    f"ID {person.track_id} | Candidate: "
                    f"{', '.join(temporal.candidate_items)} "
                    f"({temporal.candidate_elapsed_seconds:.1f}s)"
                )
            else:
                color = (35, 190, 70)
                label = f"ID {person.track_id} | COMPLIANT"
            _draw_label(annotated, person.tracked_person.bbox, label, color)
            continue

        zone_temporal = person.zone_violation_state
        components: List[str] = []
        confirmed = bool(temporal.confirmed_items)
        candidate = bool(temporal.candidate_items)
        if temporal.confirmed_items:
            components.append(f"PPE VIOLATION: {', '.join(temporal.confirmed_items)}")
        elif temporal.candidate_items:
            components.append(
                f"PPE candidate: {', '.join(temporal.candidate_items)} "
                f"({temporal.candidate_elapsed_seconds:.1f}s)"
            )
        if zone_temporal is not None and zone_temporal.confirmed_zone_names:
            components.append(f"RESTRICTED: {', '.join(zone_temporal.confirmed_zone_names)}")
            confirmed = True
        elif zone_temporal is not None and zone_temporal.candidate_zone_names:
            components.append(
                f"Zone candidate: {', '.join(zone_temporal.candidate_zone_names)} "
                f"({zone_temporal.candidate_elapsed_seconds:.1f}s)"
            )
            candidate = True

        color = (20, 20, 230) if confirmed else ((0, 165, 255) if candidate else (35, 190, 70))
        label = f"ID {person.track_id} | " + (" | ".join(components) if components else "COMPLIANT")
        _draw_label(annotated, person.tracked_person.bbox, label, color)
        if person.zone_status is not None:
            foot_x, foot_y = person.zone_status.foot_point
            cv2.circle(annotated, (int(round(foot_x)), int(round(foot_y))), 7, color, -1)

    header = (
        f"FPS: {fps:.1f} | Tracked: {len(result.people)} | "
        f"Active violations: {result.active_confirmed_violations}"
    )
    cv2.rectangle(annotated, (0, 0), (min(annotated.shape[1] - 1, 780), 42), (20, 20, 20), -1)
    cv2.putText(
        annotated,
        header,
        (12, 29),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.72,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return annotated


def print_state_changes(result: RealtimeFrameResult) -> None:
    for transition in result.transitions:
        if isinstance(transition, ZoneTransition):
            if transition.state == "CANDIDATE":
                print(
                    f"[ZONE CANDIDATE] Track {transition.track_id} entered "
                    f"{transition.zone_name} at {transition.stream_time_seconds:.2f}s"
                )
            elif transition.state == "CONFIRMED":
                print(
                    f"[ZONE CONFIRMED STATE] Track {transition.track_id} in "
                    f"{transition.zone_name} for {transition.elapsed_seconds:.2f}s"
                )
            elif transition.state == "RESOLVED":
                print(
                    f"[ZONE RESOLVED] Track {transition.track_id} exited "
                    f"{transition.zone_name} at {transition.stream_time_seconds:.2f}s"
                )
            continue
        if transition.state == "CANDIDATE":
            print(
                f"[CANDIDATE] Track {transition.track_id} missing "
                f"{transition.item} at {transition.stream_time_seconds:.2f}s"
            )
        elif transition.state == "CONFIRMED":
            print(
                f"[CONFIRMED STATE] Track {transition.track_id} missing "
                f"{transition.item} for {transition.elapsed_seconds:.2f}s"
            )
        elif transition.state == "RESOLVED":
            print(
                f"[RESOLVED] Track {transition.track_id} {transition.item} compliant "
                f"at {transition.stream_time_seconds:.2f}s"
            )
    for event in result.events:
        prefix = "[ZONE CONFIRMED]" if event.event_type == "RESTRICTED_ZONE_VIOLATION" else "[CONFIRMED]"
        print(f"{prefix} {json.dumps(event.to_dict(), sort_keys=True)}")


def print_incidents(incidents: Iterable[Incident]) -> None:
    for incident in incidents:
        print("\n" + "=" * 48)
        print("INCIDENT CREATED")
        print("=" * 48)
        print(f"ID: {incident.incident_id}")
        print(f"Type: {incident.incident_type}")
        print(f"Track: {incident.track_id}")
        print(f"Severity: {incident.severity}")
        if incident.missing_items:
            print(f"Missing PPE: {', '.join(incident.missing_items)}")
        if incident.zone_id:
            print(f"Zone: {incident.zone_name} ({incident.zone_id})")
        print(f"Camera: {incident.camera_id or '(not supplied)'}")
        print(f"Evidence: {incident.evidence_path}")
        print("=" * 48)


def _create_writer(path: Path, fps: float, width: int, height: int) -> cv2.VideoWriter:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps if fps > 0.0 else 30.0,
        (width, height),
    )
    if not writer.isOpened():
        writer.release()
        raise PPEModelError(f"OpenCV could not create output video: {path}")
    return writer


def _video_output_path(source: Path, zones_enabled: bool = False) -> Path:
    suffix = "_zones_realtime.mp4" if zones_enabled else "_realtime.mp4"
    return (OUTPUT_DIR / f"{source.stem}{suffix}").resolve()


def _incident_report_path(source_name: str) -> Path:
    return (INCIDENT_OUTPUT_DIR / f"{source_name}_incidents.json").resolve()


def _print_summary(
    summary: RunSummary,
    output_path: Optional[Path],
    incident_report_path: Optional[Path] = None,
) -> None:
    print("\nRun summary")
    print(f"  Source: {summary.source}")
    print(f"  Frames processed: {summary.frames_processed}")
    print(f"  Confirmed events: {summary.events}")
    if summary.zones_configured:
        print(f"    PPE events: {summary.ppe_events}")
        print(f"    Restricted-zone events: {summary.zone_events}")
    print(f"  Unique tracked person IDs: {len(summary.unique_track_ids)}")
    for track_id in sorted(summary.unique_track_ids):
        print(
            f"    ID {track_id}: {summary.observations_by_track[track_id]} observed frame(s), "
            f"longest continuous streak {summary.longest_streak_by_track[track_id]} frame(s)"
        )
    if not summary.unique_track_ids:
        print("    No people were tracked; zero-person frames completed safely.")
    print("\nIncident summary")
    print(f"  Total incidents: {summary.incidents}")
    print(f"  PPE incidents: {summary.ppe_incidents}")
    print(f"  Restricted-zone incidents: {summary.zone_incidents}")
    for severity in ("LOW", "MEDIUM", "HIGH"):
        print(f"  {severity}: {summary.severities[severity]}")
    if summary.evidence_paths:
        print("  Evidence files:")
        for evidence_path in summary.evidence_paths:
            print(f"    {evidence_path}")
    if output_path is not None:
        print(f"  Annotated video saved to: {output_path}")
    if incident_report_path is not None:
        print(f"  Incident report saved to: {incident_report_path}")


def _apply_zone_reload(
    pipeline: RealtimePPEPipeline,
    zone_reloader: Optional["RestrictedZoneReloader"],
    summary: RunSummary,
) -> None:
    """Swap in the camera's latest database zones when an Admin changed them."""

    if zone_reloader is None:
        return
    zones = zone_reloader.poll()
    if zones is None:
        return
    pipeline.set_zones(zones or None)
    summary.zones_configured = summary.zones_configured or bool(zones)
    names = ", ".join(f"{zone.name} ({zone.zone_id})" for zone in zones) or "none, PPE only"
    print(f"[ZONES RELOADED] {len(zones)} enabled zone(s): {names}")


def _apply_ppe_rule_reload(
    pipeline: RealtimePPEPipeline,
    ppe_reloader: Optional["PPERuleReloader"],
) -> None:
    """Follow Admin changes to the camera location's PPE safety rules."""

    if ppe_reloader is None:
        return
    items = ppe_reloader.poll()
    if items is None:
        return
    pipeline.set_required_ppe(items)
    print(f"[PPE RULES RELOADED] Required PPE: {', '.join(sorted(items)) or 'none'}")


def resolve_required_ppe(
    args: argparse.Namespace,
) -> Tuple[Optional[frozenset], Optional["PPERuleReloader"], str]:
    """Return ``(required_items, reloader, description)``.

    With ``--camera-db-id`` the camera location's safety rules decide which
    PPE items are enforced; without it every analyzed item is enforced.
    """

    if args.camera_db_id is None:
        return None, None, "helmet, vest, gloves (no --camera-db-id)"
    from sqlalchemy.exc import SQLAlchemyError
    from services.ppe_rule_service import PPERuleReloader

    reloader = PPERuleReloader(args.camera_db_id, interval_seconds=args.zone_reload_seconds)
    try:
        items = reloader.load()
    except SQLAlchemyError as exc:
        raise ValueError(f"Could not load PPE rules for camera {args.camera_db_id}: {exc}") from exc
    names = ", ".join(sorted(items)) or "none (No PPE or restricted location)"
    return items, reloader, f"{names} (location rules for camera {args.camera_db_id})"


def run_video(
    pipeline: RealtimePPEPipeline,
    source: Path,
    display: bool,
    save_video: bool,
    max_frames: Optional[int],
    save_incidents: bool = False,
    zone_reloader: Optional["RestrictedZoneReloader"] = None,
    ppe_reloader: Optional["PPERuleReloader"] = None,
) -> Tuple[RunSummary, bool]:
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        capture.release()
        raise PPEModelError(f"OpenCV could not open video: {source}")

    source_fps = float(capture.get(cv2.CAP_PROP_FPS))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if source_fps <= 0.0:
        source_fps = 30.0
        print("Warning: video FPS metadata was invalid; using 30 FPS timeline fallback.")

    zones_enabled = bool(
        pipeline.zone_analyzer is not None and pipeline.zone_analyzer.enabled_zones
    )
    output_path = _video_output_path(source, zones_enabled) if save_video else None
    writer = (
        _create_writer(output_path, source_fps, width, height)
        if output_path is not None
        else None
    )
    summary = RunSummary(
        source=str(source.resolve()),
        zones_configured=zones_enabled,
    )
    window_name = f"VisionGuard Realtime - {source.name}"
    smoothed_fps = 0.0
    previous_processing_time = time.perf_counter()
    stopped = False
    pipeline.reset()

    print("\n" + "=" * 68)
    print(f"Video: {source.resolve()}")
    print(f"Resolution: {width}x{height} | FPS: {source_fps:.3f} | Frames: {total_frames}")
    print("Timeline: frame index / source FPS (not processing speed)")
    if display:
        print("Press Q to stop.")

    try:
        while True:
            success, frame = capture.read()
            if not success:
                break
            summary.frames_processed += 1
            frame_number = summary.frames_processed
            timestamp_seconds = (frame_number - 1) / source_fps
            _apply_zone_reload(pipeline, zone_reloader, summary)
            _apply_ppe_rule_reload(pipeline, ppe_reloader)
            result = pipeline.process_frame(
                frame,
                timestamp_seconds,
                defer_incidents=True,
            )

            current_processing_time = time.perf_counter()
            instantaneous_fps = 1.0 / max(current_processing_time - previous_processing_time, 1e-9)
            smoothed_fps = (
                instantaneous_fps
                if smoothed_fps == 0.0
                else 0.9 * smoothed_fps + 0.1 * instantaneous_fps
            )
            previous_processing_time = current_processing_time
            annotated = draw_realtime_result(frame, result, smoothed_fps)
            created_incidents = pipeline.create_incidents(result, annotated)

            print_state_changes(result)
            print_incidents(created_incidents)
            summary.record_events(result.events)
            summary.record_incidents(created_incidents)
            summary.observe((person.track_id for person in result.people), frame_number)

            if writer is not None:
                writer.write(annotated)
            if display:
                cv2.imshow(window_name, annotated)
                if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q")):
                    stopped = True
                    break
            if max_frames is not None and frame_number >= max_frames:
                break
    finally:
        capture.release()
        if writer is not None:
            writer.release()
        if display:
            cv2.destroyWindow(window_name)

    incident_report_path = None
    if save_incidents and pipeline.incident_manager is not None:
        incident_report_path = pipeline.incident_manager.save_report(
            _incident_report_path(source.stem)
        )
    _print_summary(summary, output_path, incident_report_path)
    return summary, stopped


def run_webcam(
    pipeline: RealtimePPEPipeline,
    camera_index: int,
    display: bool,
    save_video: bool,
    max_frames: Optional[int],
    save_incidents: bool = False,
    zone_reloader: Optional["RestrictedZoneReloader"] = None,
    ppe_reloader: Optional["PPERuleReloader"] = None,
) -> RunSummary:
    if not display and max_frames is None:
        raise ValueError("Headless webcam mode requires --max-frames so the run can finish.")

    capture = cv2.VideoCapture(camera_index)
    if not capture.isOpened():
        capture.release()
        raise PPEModelError(f"OpenCV could not open webcam {camera_index}.")

    source_fps = float(capture.get(cv2.CAP_PROP_FPS))
    if source_fps <= 0.0:
        source_fps = 30.0
    output_path = None
    writer = None
    summary = RunSummary(
        source=f"webcam:{camera_index}",
        zones_configured=bool(
            pipeline.zone_analyzer is not None and pipeline.zone_analyzer.enabled_zones
        ),
    )
    pipeline.reset()
    started_at = time.monotonic()
    previous_processing_time = time.perf_counter()
    smoothed_fps = 0.0
    session_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    window_name = f"VisionGuard Realtime - Webcam {camera_index}"
    print(f"Webcam {camera_index} started. Timeline uses time.monotonic().")
    if display:
        print("Press Q to stop.")

    try:
        while True:
            success, frame = capture.read()
            if not success:
                raise PPEModelError("The webcam stopped returning frames.")
            summary.frames_processed += 1
            frame_number = summary.frames_processed
            timestamp_seconds = time.monotonic() - started_at
            _apply_zone_reload(pipeline, zone_reloader, summary)
            _apply_ppe_rule_reload(pipeline, ppe_reloader)
            result = pipeline.process_frame(
                frame,
                timestamp_seconds,
                defer_incidents=True,
            )

            current_processing_time = time.perf_counter()
            instantaneous_fps = 1.0 / max(current_processing_time - previous_processing_time, 1e-9)
            smoothed_fps = (
                instantaneous_fps
                if smoothed_fps == 0.0
                else 0.9 * smoothed_fps + 0.1 * instantaneous_fps
            )
            previous_processing_time = current_processing_time
            annotated = draw_realtime_result(frame, result, smoothed_fps)
            created_incidents = pipeline.create_incidents(result, annotated)

            print_state_changes(result)
            print_incidents(created_incidents)
            summary.record_events(result.events)
            summary.record_incidents(created_incidents)
            summary.observe((person.track_id for person in result.people), frame_number)

            if save_video and writer is None:
                OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                output_path = (
                    OUTPUT_DIR
                    / f"webcam_{camera_index}_{session_stamp}_realtime.mp4"
                ).resolve()
                height, width = frame.shape[:2]
                writer = _create_writer(output_path, source_fps, width, height)
            if writer is not None:
                writer.write(annotated)
            if display:
                cv2.imshow(window_name, annotated)
                if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q")):
                    break
            if max_frames is not None and frame_number >= max_frames:
                break
    finally:
        capture.release()
        if writer is not None:
            writer.release()
        if display:
            cv2.destroyWindow(window_name)

    incident_report_path = None
    if save_incidents and pipeline.incident_manager is not None:
        incident_report_path = pipeline.incident_manager.save_report(
            _incident_report_path(f"webcam_{camera_index}_{session_stamp}")
        )
    _print_summary(summary, output_path, incident_report_path)
    return summary


def video_files(directory: Path) -> List[Path]:
    return sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    )


def resolve_source(source_value: str) -> Tuple[str, Union[int, Path]]:
    stripped = source_value.strip()
    if stripped.isdigit():
        return "webcam", int(stripped)
    path = Path(stripped).expanduser().resolve()
    if path.is_dir():
        return "directory", path
    if not path.is_file():
        raise PPEModelError(f"Source was not found: {path}")
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        raise PPEModelError(f"Unsupported realtime source type: {path.suffix or '(no extension)'}")
    return "video", path


def run_synthetic_temporal_tests() -> None:
    """Verify timing, grace, cooldown, cleanup, and empty-frame behavior."""

    config = ViolationEngineConfig(
        confirmation_seconds=2.0,
        grace_seconds=0.5,
        cooldown_seconds=10.0,
        track_expiration_seconds=8.0,
    )

    engine = TemporalViolationEngine(config)
    assert not engine.update({}, 0.0).events
    first = engine.update({7: ["helmet"]}, 0.0)
    assert [transition.state for transition in first.transitions] == ["CANDIDATE"]
    assert not first.events
    assert not engine.update({7: ["helmet"]}, 1.99).events
    confirmed = engine.update({7: ["helmet"]}, 2.0)
    assert len(confirmed.events) == 1
    assert confirmed.events[0].missing_items == ("helmet",)
    assert abs(confirmed.events[0].duration_seconds - 2.0) < 1e-9
    assert not engine.update({7: ["helmet"]}, 2.1).events

    # A present classification shorter than 0.5 s must not clear the episode.
    assert not engine.update({7: []}, 2.2).events
    flicker = engine.update({7: ["helmet"]}, 2.4)
    assert flicker.snapshots[7].confirmed_items == ["helmet"]
    assert not flicker.events

    engine.update({7: []}, 3.0)
    resolved = engine.update({7: []}, 3.5)
    assert any(transition.state == "RESOLVED" for transition in resolved.transitions)
    assert not resolved.snapshots[7].confirmed_items

    # Full compliance resets the active episode, so a later real episode can
    # emit after its own 2 s confirmation even inside the previous cooldown.
    engine.update({7: ["helmet"]}, 3.6)
    repeated = engine.update({7: ["helmet"]}, 5.6)
    assert len(repeated.events) == 1

    expired = engine.update({}, 13.7)
    assert 7 not in expired.snapshots

    # Confirmations use elapsed video time, independent of processing speed.
    engine = TemporalViolationEngine(config)
    video_events = []
    for frame_index in range(0, 63):
        update = engine.update({3: ["vest", "gloves"]}, frame_index / 30.0)
        video_events.extend(update.events)
    assert len(video_events) == 1
    assert video_events[0].stream_time_seconds >= 2.0
    assert video_events[0].stream_time_seconds < 2.0 + 1.0 / 30.0 + 1e-9
    assert video_events[0].missing_items == ("vest", "gloves")

    # Time with no person observation is not evidence of missing PPE.
    engine = TemporalViolationEngine(config)
    engine.update({9: ["helmet"]}, 0.0)
    engine.update({}, 1.0)
    engine.update({}, 2.0)
    assert not engine.update({9: ["helmet"]}, 2.1).events
    assert not engine.update({9: ["helmet"]}, 4.0).events
    assert len(engine.update({9: ["helmet"]}, 4.1).events) == 1

    # A new item joining an already active violation is held by cooldown and
    # emitted once, not every frame, after the cooldown expires.
    engine = TemporalViolationEngine(config)
    engine.update({1: ["helmet"]}, 0.0)
    assert len(engine.update({1: ["helmet"]}, 2.0).events) == 1
    engine.update({1: ["helmet", "vest"]}, 2.1)
    assert not engine.update({1: ["helmet", "vest"]}, 4.1).events
    assert not engine.update({1: ["helmet", "vest"]}, 11.9).events
    cooldown_event = engine.update({1: ["helmet", "vest"]}, 12.0)
    assert len(cooldown_event.events) == 1
    assert cooldown_event.events[0].missing_items == ("helmet", "vest")

    print("Synthetic temporal tests passed:")
    print("  - zero-person frames")
    print("  - no immediate confirmation")
    print("  - 2.0-second video-time confirmation")
    print("  - 0.5-second flicker grace")
    print("  - no duplicate event every frame")
    print("  - person-detection gaps do not count as missing-PPE evidence")
    print("  - cooldown and compliant reset")
    print("  - 8.0-second inactive-track cleanup")


def resolve_zone_configuration(
    args: argparse.Namespace,
) -> Tuple[Optional[List[RestrictedZone]], Optional["RestrictedZoneReloader"], str]:
    """Return ``(zones, reloader, description)`` using this precedence:

    1. ``--zones`` JSON file (regression/testing), never reloaded.
    2. ``--camera-db-id``: that camera's enabled database zones, reloadable.
    3. Neither: ``None`` zones, i.e. PPE only.

    A camera with zero enabled zones also yields ``None`` (PPE only).
    """

    if args.zones:
        return load_zones(args.zones), None, f"JSON file {args.zones}"
    if args.camera_db_id is not None:
        # Database access stays in this executable adapter, like the incident
        # sink, so the reusable pipeline never depends on SQLAlchemy.
        from sqlalchemy.exc import SQLAlchemyError
        from services.restricted_zone_service import RestrictedZoneReloader

        reloader = RestrictedZoneReloader(
            args.camera_db_id,
            interval_seconds=args.zone_reload_seconds,
        )
        try:
            zones = reloader.load()
        except SQLAlchemyError as exc:
            raise ValueError(
                f"Could not load restricted zones for camera {args.camera_db_id}: {exc}"
            ) from exc
        return zones or None, reloader, f"database camera {args.camera_db_id}"
    return None, None, "none (PPE only)"


def _build_pipeline(
    args: argparse.Namespace,
    zones: Optional[Sequence[RestrictedZone]] = None,
    required_ppe: Optional[Iterable[str]] = None,
) -> RealtimePPEPipeline:
    config = ViolationEngineConfig(
        confirmation_seconds=args.confirmation_seconds,
        grace_seconds=args.grace_seconds,
        cooldown_seconds=args.cooldown_seconds,
        track_expiration_seconds=args.track_expiration_seconds,
    )
    zone_config = ZoneViolationConfig(
        confirmation_seconds=args.zone_confirmation_seconds,
        exit_grace_seconds=args.zone_grace_seconds,
        track_expiration_seconds=args.track_expiration_seconds,
    )
    camera_identifier = args.camera_id
    if camera_identifier is None and args.camera_db_id is not None:
        camera_identifier = str(args.camera_db_id)
    incident_manager = IncidentManager(camera_id=camera_identifier)
    incident_sink = None
    if args.persist_incidents:
        # Database integration stays in this executable adapter; the reusable
        # AI pipeline itself only knows about a callback.
        from services.incident_service import DatabaseIncidentSink

        incident_sink = DatabaseIncidentSink(camera_db_id=args.camera_db_id)
    return RealtimePPEPipeline(
        confidence=args.confidence,
        violation_config=config,
        zones=zones,
        zone_violation_config=zone_config,
        incident_manager=incident_manager,
        incident_sink=incident_sink,
        required_ppe=required_ppe,
    )


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.max_frames is not None and args.max_frames <= 0:
            raise ValueError("--max-frames must be greater than 0")
        if args.persist_incidents and args.camera_db_id is None:
            raise ValueError("--persist-incidents requires --camera-db-id")
        if args.zone_reload_seconds < 0:
            raise ValueError("--zone-reload-seconds must be 0 or greater")
        if args.self_test:
            run_synthetic_temporal_tests()
            from .test_zone_analyzer import run_synthetic_zone_tests
            from .test_incident_manager import run_synthetic_incident_tests

            run_synthetic_zone_tests()
            run_synthetic_incident_tests()
        if args.source is None:
            if args.self_test:
                return 0
            raise ValueError("--source is required unless --self-test is used")

        source_type, source = resolve_source(args.source)
        zones, zone_reloader, zone_source = resolve_zone_configuration(args)
        required_ppe, ppe_reloader, ppe_source = resolve_required_ppe(args)
        pipeline = _build_pipeline(args, zones, required_ppe)
        print(f"Loaded PPE model: {pipeline.detector.model_path}")
        print(f"Model classes: {json.dumps(pipeline.class_names, sort_keys=True)}")
        print(
            "Temporal settings: "
            f"confirmation={args.confirmation_seconds:.2f}s, "
            f"grace={args.grace_seconds:.2f}s, "
            f"cooldown={args.cooldown_seconds:.2f}s, "
            f"track expiration={args.track_expiration_seconds:.2f}s"
        )
        print(f"Incident camera: {args.camera_id or args.camera_db_id or '(not supplied)'}")
        print(f"Database persistence: {'enabled' if args.persist_incidents else 'disabled'}")
        print(f"Required PPE: {ppe_source}")
        print(f"Restricted zones source: {zone_source}")
        if zone_reloader is not None:
            reload_note = (
                f"re-checked every {args.zone_reload_seconds:g}s"
                if args.zone_reload_seconds > 0
                else "reloading disabled"
            )
            print(f"  Database zone changes: {reload_note}")
            if pipeline.zone_analyzer is None:
                print("  No enabled zones for this camera; running PPE only.")
        if pipeline.zone_analyzer is not None:
            print(
                "Zone settings: "
                f"confirmation={args.zone_confirmation_seconds:.2f}s, "
                f"exit grace={args.zone_grace_seconds:.2f}s, "
                f"enabled zones={len(pipeline.zone_analyzer.enabled_zones)}"
            )
            for zone in pipeline.zone_analyzer.zones:
                coordinate_type = "normalized" if zone.normalized else "pixel"
                state = "enabled" if zone.enabled else "disabled"
                print(f"  {zone.zone_id}: {zone.name} ({coordinate_type}, {state})")

        display = not args.no_display
        if source_type == "webcam":
            run_webcam(
                pipeline,
                source,
                display=display,
                save_video=args.save_video,
                max_frames=args.max_frames,
                save_incidents=args.save_incidents,
                zone_reloader=zone_reloader,
                ppe_reloader=ppe_reloader,
            )
        elif source_type == "video":
            run_video(
                pipeline,
                source,
                display=display,
                save_video=args.save_video,
                max_frames=args.max_frames,
                save_incidents=args.save_incidents,
                zone_reloader=zone_reloader,
                ppe_reloader=ppe_reloader,
            )
        else:
            videos = video_files(source)
            if not videos:
                raise PPEModelError(f"No supported videos were found in: {source}")
            print(f"Found {len(videos)} video(s) to process.")
            for video in videos:
                _, stopped = run_video(
                    pipeline,
                    video,
                    display=display,
                    save_video=args.save_video,
                    max_frames=args.max_frames,
                    save_incidents=args.save_incidents,
                    zone_reloader=zone_reloader,
                    ppe_reloader=ppe_reloader,
                )
                if stopped:
                    break
        return 0
    except (
        PPEModelError,
        TrackingError,
        IncidentManagerError,
        ValueError,
        AssertionError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped by user.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

