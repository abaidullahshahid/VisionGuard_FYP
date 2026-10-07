"""Small OpenCV MJPEG helpers for the local VisionGuard demonstration."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Generator, Tuple, Union

import cv2


BACKEND_ROOT = Path(__file__).resolve().parents[1]
CaptureSource = Union[int, str]


class CameraStreamError(RuntimeError):
    """Raised when a configured camera source cannot provide video frames."""


def resolve_capture_source(stream_url: str) -> Tuple[CaptureSource, bool]:
    """Return an OpenCV source and whether a local video file should loop."""

    value = str(stream_url or "").strip()
    if not value:
        raise CameraStreamError("Camera has no configured stream source")
    if value.isdigit():
        return int(value), False
    if "://" in value:
        return value, False

    path = Path(value).expanduser()
    if not path.is_absolute():
        path = BACKEND_ROOT / path
    path = path.resolve()
    return str(path), path.is_file()


def open_camera_capture(stream_url: str) -> Tuple[cv2.VideoCapture, bool, float]:
    """Open one configured source and return capture, loop flag, and frame rate."""

    source, loop_file = resolve_capture_source(stream_url)
    capture = cv2.VideoCapture(source)
    if not capture.isOpened():
        capture.release()
        raise CameraStreamError("Camera source is unavailable")

    fps = float(capture.get(cv2.CAP_PROP_FPS))
    if not 1.0 <= fps <= 60.0:
        fps = 25.0
    return capture, loop_file, fps


def probe_camera_source(stream_url: str) -> None:
    """Confirm a source opens and provides at least one readable frame."""

    capture, _, _ = open_camera_capture(stream_url)
    try:
        ok, frame = capture.read()
        if not ok or frame is None or frame.size == 0:
            raise CameraStreamError("Camera source did not return a video frame")
    finally:
        capture.release()


def capture_snapshot_jpeg(
    stream_url: str,
    *,
    warmup_frames: int = 5,
    jpeg_quality: int = 90,
    max_width: int = 1280,
) -> bytes:
    """Return one JPEG of the source's current view (first frame for files).

    Live cameras often return dark frames while auto-exposure settles, so a
    few frames are read and the last good one is kept.  Downscaling keeps the
    aspect ratio, so normalized zone coordinates drawn on it stay valid.
    """

    capture, loop_file, _ = open_camera_capture(stream_url)
    try:
        frame = None
        for _ in range(1 if loop_file else max(1, int(warmup_frames))):
            ok, candidate = capture.read()
            if ok and candidate is not None and candidate.size > 0:
                frame = candidate
        if frame is None:
            raise CameraStreamError("Camera source did not return a video frame")
        if max_width > 0 and frame.shape[1] > max_width:
            scale = max_width / float(frame.shape[1])
            frame = cv2.resize(
                frame,
                (max_width, max(1, int(frame.shape[0] * scale))),
                interpolation=cv2.INTER_AREA,
            )
        encoded, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, int(jpeg_quality)])
        if not encoded:
            raise CameraStreamError("Camera frame could not be encoded")
        return jpeg.tobytes()
    finally:
        capture.release()


def iter_mjpeg_frames(
    capture: cv2.VideoCapture,
    *,
    loop_file: bool,
    fps: float,
    jpeg_quality: int = 80,
    max_width: int = 1280,
) -> Generator[bytes, None, None]:
    """Yield multipart JPEG frames and always release the capture on close."""

    # A browser demo does not benefit from encoding a 4K source at 30/60 FPS.
    # Keep the configured source intact while bounding CPU and network usage.
    frame_interval = 1.0 / max(1.0, min(float(fps), 20.0))
    next_frame_at = time.monotonic()
    try:
        while True:
            ok, frame = capture.read()
            if not ok or frame is None:
                if loop_file:
                    capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                break

            if max_width > 0 and frame.shape[1] > max_width:
                scale = max_width / float(frame.shape[1])
                frame = cv2.resize(
                    frame,
                    (max_width, max(1, int(frame.shape[0] * scale))),
                    interpolation=cv2.INTER_AREA,
                )

            encoded, jpeg = cv2.imencode(
                ".jpg",
                frame,
                [cv2.IMWRITE_JPEG_QUALITY, int(jpeg_quality)],
            )
            if not encoded:
                continue

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Cache-Control: no-cache\r\n\r\n"
                + jpeg.tobytes()
                + b"\r\n"
            )

            next_frame_at += frame_interval
            delay = next_frame_at - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_frame_at = time.monotonic()
    finally:
        capture.release()
