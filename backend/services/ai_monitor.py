"""Backend-run AI monitoring for the officer Live Video Feed.

While an officer watches a camera, a background thread runs the existing
``RealtimePPEPipeline`` (YOLO + ByteTrack + PPE and restricted-zone temporal
confirmation) on that camera's frames.  The thread:

* streams annotated frames as MJPEG to every viewer of the camera,
* publishes a JSON status (people, PPE state, active violations, recent
  events) for the page,
* persists confirmed incidents through ``DatabaseIncidentSink`` and follows
  Admin changes to the camera's zones and its location's rules.

Monitoring starts with the first viewer and stops a few seconds after the
last one leaves, so the camera and CPU are only used while someone watches.

Cameras that point at the same physical source (for example one webcam
registered twice under different locations) share one OpenCV capture, so the
device is opened once and each camera still applies its own rules.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import threading
import time
from typing import Callable, Deque, Dict, List, Optional, Tuple

import cv2
import numpy as np

from services.camera_stream import (
    CameraStreamError,
    capture_snapshot_jpeg,
    open_camera_capture,
    probe_camera_source,
    resolve_capture_source,
)


logger = logging.getLogger(__name__)

MAX_FRAME_WIDTH = 1280
STREAM_JPEG_QUALITY = 80
VIDEO_MAX_FPS = 30.0            # browser video rate (webcam rate); AI runs as fast as it can
VIEWER_GRACE_SECONDS = 3.0      # keep the model warm across a quick re-open
UNPULLED_TIMEOUT_SECONDS = 30.0  # safety net if a viewer vanished silently
SOURCE_READ_FAILURE_LIMIT = 50   # consecutive failed reads (~2.5 s) => error
RULE_RELOAD_SECONDS = 5.0
RECENT_EVENT_LIMIT = 20

RED = (40, 40, 230)
ORANGE = (0, 165, 255)
GREEN = (60, 190, 70)


def _limit_width(frame: np.ndarray) -> np.ndarray:
    if frame.shape[1] <= MAX_FRAME_WIDTH:
        return frame
    scale = MAX_FRAME_WIDTH / float(frame.shape[1])
    return cv2.resize(
        frame,
        (MAX_FRAME_WIDTH, max(1, int(frame.shape[0] * scale))),
        interpolation=cv2.INTER_AREA,
    )


def _encode_jpeg(frame: np.ndarray, quality: int = STREAM_JPEG_QUALITY) -> bytes:
    encoded, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    if not encoded:
        raise CameraStreamError("Camera frame could not be encoded")
    return jpeg.tobytes()


def source_key(stream_url: str) -> str:
    source, _ = resolve_capture_source(stream_url)
    return f"{type(source).__name__}:{source}"


# ── Shared camera sources ─────────────────────────────────────────


class SharedFrameSource:
    """One OpenCV capture read on its own thread; consumers take the latest frame."""

    def __init__(self, stream_url: str) -> None:
        self.key = source_key(stream_url)
        self.users = 0
        self.error: Optional[str] = None
        self._capture, self._loop_file, fps = open_camera_capture(stream_url)
        # Files are paced to their frame rate; live sources block on read().
        self._frame_interval = 1.0 / max(1.0, min(fps, 30.0)) if self._loop_file else 0.0
        self._cond = threading.Condition()
        self._frame: Optional[np.ndarray] = None
        self._seq = 0
        self._closed = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"source[{self.key}]", daemon=True)
        self._thread.start()

    @property
    def closed(self) -> bool:
        return self._closed

    def _run(self) -> None:
        failures = 0
        next_frame_at = time.monotonic()
        try:
            while not self._stop.is_set():
                ok, frame = self._capture.read()
                if not ok or frame is None or frame.size == 0:
                    failures += 1
                    if self._loop_file and failures <= 3:
                        self._capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    if self._loop_file or failures >= SOURCE_READ_FAILURE_LIMIT:
                        self.error = "The camera stopped returning frames"
                        break
                    time.sleep(0.05)
                    continue
                failures = 0
                frame = _limit_width(frame)
                with self._cond:
                    self._frame = frame
                    self._seq += 1
                    self._cond.notify_all()
                if self._frame_interval:
                    next_frame_at += self._frame_interval
                    delay = next_frame_at - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
                    else:
                        next_frame_at = time.monotonic()
        except Exception as exc:  # OpenCV backends can raise on unplug
            logger.exception("Camera source %s failed", self.key)
            self.error = str(exc) or "Camera source failed"
        finally:
            self._capture.release()
            with self._cond:
                self._closed = True
                self._cond.notify_all()

    def wait_frame(self, after_seq: int, timeout: float) -> Optional[Tuple[int, np.ndarray]]:
        with self._cond:
            self._cond.wait_for(lambda: self._seq > after_seq or self._closed, timeout)
            if self._seq > after_seq and self._frame is not None:
                return self._seq, self._frame
            return None

    def latest_frame(self) -> Optional[np.ndarray]:
        with self._cond:
            return self._frame

    def stop(self) -> None:
        self._stop.set()
        # Wait for release so the device can be reopened immediately.
        self._thread.join(timeout=3.0)


class FrameSourceRegistry:
    def __init__(self, source_factory: Callable[[str], SharedFrameSource] = SharedFrameSource) -> None:
        self._lock = threading.Lock()
        self._sources: Dict[str, SharedFrameSource] = {}
        self._source_factory = source_factory

    def acquire(self, stream_url: str) -> SharedFrameSource:
        key = source_key(stream_url)
        with self._lock:
            source = self._sources.get(key)
            if source is None or source.closed:
                source = self._source_factory(stream_url)
                self._sources[key] = source
            source.users += 1
            return source

    def release(self, source: SharedFrameSource) -> None:
        with self._lock:
            source.users -= 1
            if source.users > 0:
                return
            if self._sources.get(source.key) is source:
                del self._sources[source.key]
            source.stop()

    def active(self, stream_url: str) -> Optional[SharedFrameSource]:
        try:
            key = source_key(stream_url)
        except CameraStreamError:
            return None
        with self._lock:
            source = self._sources.get(key)
            return source if source is not None and not source.closed else None


# ── Pipeline setup and drawing ────────────────────────────────────


@dataclass
class MonitorSetup:
    pipeline: object
    zone_reloader: Optional[object] = None
    ppe_reloader: Optional[object] = None


def build_camera_pipeline(camera_db_id: int) -> MonitorSetup:
    """Same configuration as ``test_realtime_pipeline --camera-db-id N --persist-incidents``."""

    from ai_module.incident_manager import IncidentManager
    from ai_module.realtime_pipeline import RealtimePPEPipeline
    from ai_module.violation_engine import ViolationEngineConfig
    from ai_module.zone_violation_engine import ZoneViolationConfig
    from services.incident_service import DatabaseIncidentSink
    from services.ppe_rule_service import PPERuleReloader
    from services.restricted_zone_service import RestrictedZoneReloader

    zone_reloader = RestrictedZoneReloader(camera_db_id, interval_seconds=RULE_RELOAD_SECONDS)
    ppe_reloader = PPERuleReloader(camera_db_id, interval_seconds=RULE_RELOAD_SECONDS)
    zones = zone_reloader.load()
    required_ppe = ppe_reloader.load()
    from ai_module.detector import PPEDetector

    pipeline = RealtimePPEPipeline(
        confidence=0.25,
        # Own model per camera: ByteTrack state lives in the model.
        detector=PPEDetector(confidence=0.25, instance_key=f"camera-{camera_db_id}"),
        violation_config=ViolationEngineConfig(),
        zones=zones or None,
        zone_violation_config=ZoneViolationConfig(),
        incident_manager=IncidentManager(camera_id=str(camera_db_id)),
        incident_sink=DatabaseIncidentSink(camera_db_id=camera_db_id),
        required_ppe=required_ppe,
    )
    pipeline.reset()  # the camera's model may be reused from an earlier viewing
    return MonitorSetup(pipeline, zone_reloader, ppe_reloader)


def _is_location_zone(zone_id: str) -> bool:
    from services.restricted_zone_service import LOCATION_ZONE_PREFIX

    return str(zone_id).startswith(LOCATION_ZONE_PREFIX)


def describe_person(person: object) -> Dict[str, object]:
    """JSON-safe live state of one tracked person."""

    temporal = person.violation_state
    zone_state = person.zone_violation_state
    restricted = []
    entering = []
    if zone_state is not None:
        restricted = [
            "Restricted area" if _is_location_zone(zone_id) else zone_state.zones[zone_id].zone_name
            for zone_id in zone_state.confirmed_zone_ids
        ]
        entering = [
            "Restricted area" if _is_location_zone(zone_id) else zone_state.zones[zone_id].zone_name
            for zone_id in zone_state.candidate_zone_ids
        ]
    missing = list(temporal.confirmed_items)
    checking = list(temporal.candidate_items)
    if missing or restricted:
        state = "violation"
    elif checking or entering:
        state = "checking"
    else:
        state = "ok"
    ppe = person.ppe_status
    return {
        "track_id": int(person.track_id),
        "state": state,
        "missing": missing,
        "checking": checking,
        "restricted_zones": restricted,
        "entering_zones": entering,
        "wearing": {item.item_name: bool(item.present) for item in (ppe.helmet, ppe.vest, ppe.gloves)},
        # Out of view (e.g. hands below a webcam's frame), so not judged.
        "not_visible": [
            item.item_name
            for item in (ppe.helmet, ppe.vest, ppe.gloves)
            if not item.present and not getattr(item, "visible", True)
        ],
    }


def _person_label(info: Dict[str, object], ppe_checked: bool) -> Tuple[str, Tuple[int, int, int]]:
    parts: List[str] = []
    for zone in info["restricted_zones"]:
        parts.append("IN RESTRICTED AREA" if zone == "Restricted area" else f"IN ZONE: {zone}")
    if info["missing"]:
        parts.append("NO " + ", ".join(item.upper() for item in info["missing"]))
    if parts:
        return f"ID {info['track_id']} | " + " | ".join(parts), RED
    if info["entering_zones"]:
        parts.append("entering " + ", ".join(info["entering_zones"]))
    if info["checking"]:
        parts.append("checking " + ", ".join(info["checking"]))
    if parts:
        return f"ID {info['track_id']} | " + " | ".join(parts), ORANGE
    if not ppe_checked:
        return f"ID {info['track_id']} | Person", GREEN
    hidden = info.get("not_visible") or []
    note = f" | {', '.join(hidden)} not in view" if hidden else ""
    return f"ID {info['track_id']} | PPE OK{note}", GREEN


def _draw_header(image: np.ndarray, header: str) -> None:
    height, width = image.shape[:2]
    scale = max(0.5, min(0.75, width / 1700.0))
    (text_width, text_height), baseline = cv2.getTextSize(header, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
    # Bottom-left: person labels sit above boxes, so the top edge stays clear.
    box_top = height - (text_height + baseline + 18)
    overlay = image.copy()
    cv2.rectangle(overlay, (0, box_top), (text_width + 24, height), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.65, image, 0.35, 0.0, image)
    cv2.putText(image, header, (12, height - baseline - 9), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 2, cv2.LINE_AA)


def annotate_waiting_frame(frame: np.ndarray, video_fps: float) -> np.ndarray:
    """Video shown while the AI model is still loading."""

    image = frame.copy()
    _draw_header(image, f"AI STARTING...   Video {video_fps:4.1f} FPS")
    return image


def annotate_live_frame(
    frame: np.ndarray,
    result: object,
    people: List[Dict[str, object]],
    fps: float,
    ppe_checked: bool,
    restricted_location: bool,
    video_fps: Optional[float] = None,
) -> np.ndarray:
    """Boxes and labels for the browser stream.

    Drawn polygons are rendered by the page's own overlay, so only a
    whole-location restriction is marked here (a red border).
    """

    from ai_module.test_realtime_pipeline import _draw_label

    image = frame.copy()
    height, width = image.shape[:2]
    if restricted_location:
        cv2.rectangle(image, (0, 0), (width - 1, height - 1), RED, max(4, width // 160))
    for person, info in zip(result.people, people):
        label, color = _person_label(info, ppe_checked)
        _draw_label(image, person.tracked_person.bbox, label, color)
        if person.zone_status is not None:
            foot_x, foot_y = person.zone_status.foot_point
            cv2.circle(image, (int(round(foot_x)), int(round(foot_y))), 6, color, -1)

    violations = sum(1 for info in people if info["state"] == "violation")
    rates = f"{fps:4.1f} FPS" if video_fps is None else f"Video {video_fps:4.1f} FPS  AI {fps:4.1f} FPS"
    _draw_header(image, f"AI LIVE  {rates}   People: {len(people)}   Violations: {violations}")
    return image


def _event_summary(event: object) -> Dict[str, object]:
    zone_id = getattr(event, "zone_id", None)
    zone_name = getattr(event, "zone_name", None)
    if zone_id is not None and _is_location_zone(zone_id):
        zone_name = "Restricted area"
    return {
        "time": datetime.now(timezone.utc).isoformat(),
        "type": event.event_type,
        "track_id": int(event.track_id),
        "missing_items": list(getattr(event, "missing_items", ()) or ()),
        "zone_name": zone_name,
    }


# ── Per-camera monitor ────────────────────────────────────────────


@dataclass(frozen=True)
class AIView:
    """What the video loop draws: the AI loop's most recent result."""

    result: object
    people: List[Dict[str, object]]
    fps: float
    ppe_checked: bool
    restricted_location: bool



class CameraMonitor:
    """AI inference for one camera, shared by all of its viewers."""

    def __init__(
        self,
        camera_db_id: int,
        stream_url: str,
        registry: FrameSourceRegistry,
        pipeline_factory: Callable[[int], MonitorSetup] = build_camera_pipeline,
        clock: Callable[[], float] = time.monotonic,
        on_error: Optional[Callable[[int, str], None]] = None,
    ) -> None:
        self.camera_db_id = int(camera_db_id)
        self._on_error = on_error
        self.stream_url = stream_url
        self._registry = registry
        self._pipeline_factory = pipeline_factory
        self._clock = clock
        self._cond = threading.Condition()
        self.state = "starting"
        self.error: Optional[str] = None
        self._closing = False
        self._viewers = 0
        self._last_viewer_change = clock()
        self._last_pull = clock()
        self._jpeg: Optional[bytes] = None
        self._jpeg_seq = 0
        self._status: Dict[str, object] = {}
        self._events: Deque[Dict[str, object]] = deque(maxlen=RECENT_EVENT_LIMIT)
        self._events_total = 0
        # Latest AI result; the video loop draws it on every new camera frame.
        self._ai_view: Optional[AIView] = None
        self._video_fps = 0.0
        self._video_done = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"ai-camera-{camera_db_id}", daemon=True)
        self._thread.start()

    # Viewer bookkeeping -------------------------------------------------

    @property
    def finished(self) -> bool:
        return self.state in ("stopped", "error")

    def try_add_viewer(self) -> bool:
        with self._cond:
            if self._closing or self.finished:
                return False
            self._viewers += 1
            self._last_viewer_change = self._last_pull = self._clock()
            return True

    def remove_viewer(self) -> None:
        with self._cond:
            self._viewers = max(0, self._viewers - 1)
            self._last_viewer_change = self._clock()

    def _should_close(self) -> bool:
        with self._cond:
            now = self._clock()
            idle = (
                self._viewers == 0 and now - self._last_viewer_change > VIEWER_GRACE_SECONDS
            ) or now - self._last_pull > UNPULLED_TIMEOUT_SECONDS
            if idle or self._stop.is_set():
                self._closing = True
            return self._closing

    def stop(self) -> None:
        self._stop.set()
        with self._cond:
            self._closing = True
            self._cond.notify_all()

    def join(self, timeout: Optional[float] = None) -> None:
        self._thread.join(timeout)

    # Consumer API ------------------------------------------------------

    def wait_jpeg(self, after_seq: int, timeout: float) -> Optional[Tuple[int, bytes]]:
        with self._cond:
            self._last_pull = self._clock()
            self._cond.wait_for(lambda: self._jpeg_seq > after_seq or self.finished, timeout)
            if self._jpeg_seq > after_seq and self._jpeg is not None:
                return self._jpeg_seq, self._jpeg
            return None

    def status(self) -> Dict[str, object]:
        with self._cond:
            return {
                "camera_id": self.camera_db_id,
                "state": self.state,
                "error": self.error,
                **self._status,
                "recent_events": list(reversed(self._events)),
                "events_total": self._events_total,
            }

    # Workers -----------------------------------------------------------
    #
    # Two loops share the camera's frames:
    #   video loop: every new frame (up to VIDEO_MAX_FPS) + the latest AI
    #               boxes -> JPEG for the browser, so the picture stays smooth;
    #   AI loop:    the newest frame whenever the model is free -> tracking,
    #               violations, incidents and the latest AI result.
    # Detection results are exactly what the AI loop produces; only the
    # drawing is repeated on the frames in between.

    def _run(self) -> None:
        source = None
        video = None
        try:
            source = self._registry.acquire(self.stream_url)
            video = threading.Thread(
                target=self._video_loop,
                args=(source,),
                name=f"video-camera-{self.camera_db_id}",
                daemon=True,
            )
            video.start()  # the picture appears while the model loads
            setup = self._pipeline_factory(self.camera_db_id)
            self._loop(source, setup)
        except Exception as exc:
            logger.exception("AI monitoring failed for camera %s", self.camera_db_id)
            with self._cond:
                self.error = str(exc) or exc.__class__.__name__
                self.state = "error"
                self._cond.notify_all()
            if self._on_error is not None:
                try:
                    self._on_error(self.camera_db_id, self.error)
                except Exception:
                    logger.exception("Camera error hook failed for camera %s", self.camera_db_id)
        finally:
            self._video_done.set()
            if video is not None:
                video.join(timeout=5.0)
            if source is not None:
                self._registry.release(source)
            with self._cond:
                if self.state != "error":
                    self.state = "stopped"
                self._closing = True
                self._cond.notify_all()

    def _apply_reloads(self, setup: MonitorSetup) -> None:
        pipeline = setup.pipeline
        if setup.zone_reloader is not None:
            zones = setup.zone_reloader.poll()
            if zones is not None:
                pipeline.set_zones(zones or None)
        if setup.ppe_reloader is not None:
            items = setup.ppe_reloader.poll()
            if items is not None:
                pipeline.set_required_ppe(items)

    def _video_loop(self, source: SharedFrameSource) -> None:
        interval = 1.0 / VIDEO_MAX_FPS
        seq = 0
        previous = None
        try:
            while not self._video_done.is_set() and not self._should_close():
                item = source.wait_frame(seq, 0.5)
                if item is None:
                    if source.closed:
                        return
                    continue
                seq, frame = item
                started = time.perf_counter()
                if previous is not None:
                    instant = 1.0 / max(started - previous, 1e-6)
                    self._video_fps = instant if self._video_fps == 0.0 else 0.85 * self._video_fps + 0.15 * instant
                previous = started
                with self._cond:
                    view = self._ai_view
                if view is None:
                    annotated = annotate_waiting_frame(frame, self._video_fps)
                else:
                    annotated = annotate_live_frame(
                        frame, view.result, view.people, view.fps,
                        view.ppe_checked, view.restricted_location, self._video_fps,
                    )
                jpeg = _encode_jpeg(annotated)
                with self._cond:
                    self._jpeg = jpeg
                    self._jpeg_seq += 1
                    if self._status:
                        self._status["video_fps"] = round(self._video_fps, 1)
                    self._cond.notify_all()
                # Cap the browser rate; the next pass takes the newest frame.
                # time.sleep is precise on Windows; Event.wait rounds up to
                # ~15.6 ms steps, which alone cost about a third of the frames.
                remaining = interval - (time.perf_counter() - started)
                if remaining > 0.001:
                    time.sleep(remaining)
        except Exception:
            # The AI loop keeps running; it reports source errors itself.
            logger.exception("Video stream failed for camera %s", self.camera_db_id)

    def _loop(self, source: SharedFrameSource, setup: MonitorSetup) -> None:
        from ai_module.test_realtime_pipeline import draw_realtime_result

        pipeline = setup.pipeline
        started_at = time.monotonic()
        previous = None
        fps = 0.0
        seq = 0
        while not self._should_close():
            item = source.wait_frame(seq, 0.5)
            if item is None:
                if source.closed:
                    raise CameraStreamError(source.error or "Camera source closed")
                continue
            seq, frame = item
            self._apply_reloads(setup)
            result = pipeline.process_frame(frame, time.monotonic() - started_at, defer_incidents=True)

            now = time.perf_counter()
            if previous is not None:
                instant = 1.0 / max(now - previous, 1e-6)
                fps = instant if fps == 0.0 else 0.85 * fps + 0.15 * instant
            previous = now

            zones = pipeline.zone_analyzer.enabled_zones if pipeline.zone_analyzer is not None else ()
            restricted_location = any(_is_location_zone(zone.zone_id) for zone in zones)
            required = pipeline.required_ppe
            required_items = sorted(required) if required is not None else ["gloves", "helmet", "vest"]
            people = [describe_person(person) for person in result.people]
            for info in people:
                # Only report hidden items this location actually requires.
                info["not_visible"] = [item for item in info["not_visible"] if item in required_items]
            if result.events:
                # Evidence images keep the full CLI drawing, polygons included.
                pipeline.create_incidents(result, draw_realtime_result(frame, result, fps))

            with self._cond:
                self.state = "running"
                self._ai_view = AIView(result, people, fps, bool(required_items), restricted_location)
                for event in result.events:
                    self._events.append(_event_summary(event))
                    self._events_total += 1
                self._status = {
                    "fps": round(fps, 1),
                    "video_fps": round(self._video_fps, 1),
                    "frame_size": [int(frame.shape[1]), int(frame.shape[0])],
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "required_ppe": required_items,
                    "restricted_location": restricted_location,
                    "zones": [zone.name for zone in zones if not _is_location_zone(zone.zone_id)],
                    "people": people,
                    "active_violations": sum(1 for info in people if info["state"] == "violation"),
                }
                self._cond.notify_all()


# ── Manager ───────────────────────────────────────────────────────


class AIMonitorManager:
    def __init__(
        self,
        registry: Optional[FrameSourceRegistry] = None,
        pipeline_factory: Callable[[int], MonitorSetup] = build_camera_pipeline,
        on_camera_error: Optional[Callable[[int, str], None]] = None,
    ) -> None:
        self.registry = registry or FrameSourceRegistry()
        self._pipeline_factory = pipeline_factory
        self._on_camera_error = on_camera_error
        self._lock = threading.Lock()
        self._monitors: Dict[int, CameraMonitor] = {}

    def attach_viewer(self, camera_db_id: int, stream_url: str) -> CameraMonitor:
        """Return the camera's running monitor (starting one) with a viewer added."""

        with self._lock:
            monitor = self._monitors.get(int(camera_db_id))
            if monitor is not None and monitor.stream_url != stream_url:
                monitor.stop()  # camera source was edited by the Admin
                monitor = None
            if monitor is None or not monitor.try_add_viewer():
                monitor = CameraMonitor(
                    camera_db_id,
                    stream_url,
                    self.registry,
                    self._pipeline_factory,
                    on_error=self._on_camera_error,
                )
                monitor.try_add_viewer()
                self._monitors[int(camera_db_id)] = monitor
            return monitor

    def get(self, camera_db_id: int) -> Optional[CameraMonitor]:
        with self._lock:
            return self._monitors.get(int(camera_db_id))

    def stop_all(self, wait: bool = True) -> None:
        with self._lock:
            monitors = list(self._monitors.values())
            self._monitors.clear()
        for monitor in monitors:
            monitor.stop()
        if wait:
            for monitor in monitors:
                monitor.join(timeout=5.0)

    def ensure_source_available(self, stream_url: str) -> None:
        """Probe a source unless a running monitor already holds it open."""

        if self.registry.active(stream_url) is None:
            probe_camera_source(stream_url)

    def snapshot_jpeg(self, stream_url: str) -> bytes:
        """Current frame for the Admin zone editor without reopening a busy device."""

        source = self.registry.active(stream_url)
        frame = source.latest_frame() if source is not None else None
        if frame is not None:
            return _encode_jpeg(frame, quality=90)
        return capture_snapshot_jpeg(stream_url)


def _notify_camera_error(camera_db_id: int, error: str) -> None:
    from services.notification_service import notify_camera_unavailable

    notify_camera_unavailable(camera_db_id, error)


monitor_manager = AIMonitorManager(on_camera_error=_notify_camera_error)
