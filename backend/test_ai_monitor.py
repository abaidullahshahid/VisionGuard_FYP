"""Tests for backend-run Live Video Feed AI monitoring (no YOLO needed).

Run:
    python test_ai_monitor.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace

import cv2
import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_module.realtime_pipeline import RealtimePPEPipeline
from ai_module.violation_engine import TemporalViolationEngine, ViolationEngineConfig
from ai_module.zone_analyzer import RestrictedZone
from database import get_db
import models
from routers import auth, officer
from routers.auth import hash_password
from services import ai_monitor
from services.ai_monitor import AIMonitorManager, FrameSourceRegistry, MonitorSetup
from services.restricted_zone_service import FULL_FRAME_POLYGON


def _write_video(path: Path, frames: int = 30) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (160, 120))
    for index in range(frames):
        frame = np.full((120, 160, 3), 40 + index, dtype=np.uint8)
        writer.write(frame)
    writer.release()


def _stub_pipeline(restricted_location: bool) -> RealtimePPEPipeline:
    """Real temporal engines; detector/analyzer replaced by one fixed person."""

    item = lambda name, present: SimpleNamespace(item_name=name, present=present)
    person = SimpleNamespace(track_id=7, detection={"bbox": [20, 10, 80, 119]}, bbox=[20, 10, 80, 119])
    status = SimpleNamespace(
        person_detection=person.detection,
        person_bbox=person.bbox,
        missing_items=["gloves"],
        helmet=item("helmet", True),
        vest=item("vest", True),
        gloves=item("gloves", False),
    )
    pipeline = object.__new__(RealtimePPEPipeline)
    pipeline.tracker = SimpleNamespace(track=lambda frame, confidence: SimpleNamespace(people=[person], detections=[person.detection]))
    pipeline.analyzer = SimpleNamespace(analyze=lambda detections: [status])
    pipeline.violation_engine = TemporalViolationEngine(ViolationEngineConfig(confirmation_seconds=0.3))
    from ai_module.zone_violation_engine import ZoneViolationConfig

    pipeline.zone_violation_config = ZoneViolationConfig(confirmation_seconds=0.3)
    if restricted_location:
        pipeline.set_zones([RestrictedZone("location-4", "Restricted area: Store", FULL_FRAME_POLYGON, normalized=True)])
        pipeline.set_required_ppe(frozenset())
    else:
        pipeline.set_zones(None)
        pipeline.set_required_ppe(None)
    pipeline.incident_manager = None
    pipeline.incident_sink = None
    pipeline.confidence = 0.25
    pipeline._init_runtime_filters()
    return pipeline


def _wait(predicate, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def run_tests() -> None:
    original_grace = ai_monitor.VIEWER_GRACE_SECONDS
    ai_monitor.VIEWER_GRACE_SECONDS = 0.3
    built = []

    def factory(camera_db_id):
        built.append(camera_db_id)
        return MonitorSetup(_stub_pipeline(restricted_location=camera_db_id == 2))

    with tempfile.TemporaryDirectory() as folder:
        video = Path(folder) / "clip.mp4"
        _write_video(video)
        manager = AIMonitorManager(FrameSourceRegistry(), pipeline_factory=factory)
        try:
            # Two cameras on the same source share one capture.
            first = manager.attach_viewer(1, str(video))
            second = manager.attach_viewer(2, str(video))
            assert _wait(lambda: first.state == "running" and second.state == "running"), (first.status(), second.status())
            shared = manager.registry.active(str(video))
            assert shared is not None and shared.users == 2

            # Annotated JPEG stream and live status.
            seq, jpeg = first.wait_jpeg(0, 3.0)
            assert jpeg.startswith(b"\xff\xd8") and seq >= 1
            assert _wait(lambda: first.status()["active_violations"] == 1)
            status = first.status()
            assert status["required_ppe"] == ["gloves", "helmet", "vest"] and not status["restricted_location"]
            person = status["people"][0]
            assert person["state"] == "violation" and person["missing"] == ["gloves"]
            assert person["wearing"] == {"helmet": True, "vest": True, "gloves": False}
            assert status["recent_events"][0]["type"] == "PPE_VIOLATION" and status["events_total"] == 1

            # Restricted location: no PPE checks, entry is the violation.
            assert _wait(lambda: second.status().get("active_violations") == 1)
            restricted = second.status()
            assert restricted["restricted_location"] and restricted["required_ppe"] == []
            assert restricted["people"][0]["restricted_zones"] == ["Restricted area"]
            assert restricted["people"][0]["missing"] == []
            assert [event["type"] for event in restricted["recent_events"]] == ["RESTRICTED_ZONE_VIOLATION"]

            # Same monitor is reused while running; the snapshot reuses the open source.
            assert manager.attach_viewer(1, str(video)) is first
            first.remove_viewer()
            assert manager.snapshot_jpeg(str(video)).startswith(b"\xff\xd8")

            # The async MJPEG generator yields frames and releases its viewer on close.
            async def read_one_chunk():
                generator = officer._monitor_mjpeg(manager.attach_viewer(1, str(video)))
                chunk = await generator.__anext__()
                await generator.aclose()
                return chunk

            chunk = asyncio.run(read_one_chunk())
            assert chunk.startswith(b"--frame\r\nContent-Type: image/jpeg") and b"\xff\xd9" in chunk

            # Last viewer leaves -> monitor stops and the device is released.
            first.remove_viewer()
            assert _wait(lambda: first.state == "stopped"), first.state
            assert shared.users == 1 and not shared.closed  # camera 2 still watching
            second.remove_viewer()
            assert _wait(lambda: second.state == "stopped" and shared.closed)
            assert manager.registry.active(str(video)) is None

            # A new viewer after a stop starts a fresh monitor.
            again = manager.attach_viewer(1, str(video))
            assert again is not first and _wait(lambda: again.state == "running")
            again.remove_viewer()

            # Unavailable sources end in an error state instead of hanging.
            broken = manager.attach_viewer(3, str(Path(folder) / "missing.mp4"))
            assert _wait(lambda: broken.state == "error") and broken.status()["error"]
        finally:
            manager.stop_all()

        # Smooth video: frames keep flowing while a slow AI works, and the
        # picture appears before the model has finished loading.
        def slow_factory(camera_db_id):
            time.sleep(0.8)  # model loading
            pipeline = _stub_pipeline(restricted_location=False)
            analyse = pipeline.process_frame

            def slow_process(*args, **kwargs):
                time.sleep(0.25)  # ~4 AI frames per second
                return analyse(*args, **kwargs)

            pipeline.process_frame = slow_process
            return MonitorSetup(pipeline)

        slow_manager = AIMonitorManager(FrameSourceRegistry(), pipeline_factory=slow_factory)
        try:
            monitor = slow_manager.attach_viewer(5, str(video))
            early = monitor.wait_jpeg(0, 3.0)
            assert early is not None and monitor.state == "starting", monitor.state
            assert _wait(lambda: monitor.state == "running")
            start_seq = monitor.wait_jpeg(0, 1.0)[0]
            time.sleep(1.5)
            frames = monitor.wait_jpeg(0, 1.0)[0] - start_seq
            status = monitor.status()
            assert frames >= 18, f"only {frames} video frames in 1.5 s"
            assert status["video_fps"] > 2.5 * status["fps"], status
            assert status["video_fps"] <= ai_monitor.VIDEO_MAX_FPS + 3, status
            # Detection still works on the AI frames.
            assert _wait(lambda: monitor.status()["active_violations"] == 1)
            assert monitor.status()["recent_events"][0]["type"] == "PPE_VIOLATION"
            monitor.remove_viewer()
            assert _wait(lambda: monitor.state == "stopped")
        finally:
            slow_manager.stop_all()
            ai_monitor.VIEWER_GRACE_SECONDS = original_grace

    _endpoint_tests()
    print("AI monitor tests passed:")
    print("  - one shared capture for two cameras on the same webcam/file")
    print("  - annotated MJPEG + live status (people, PPE, violations, events)")
    print("  - smooth video: frames keep flowing while the AI is slow or loading")
    print("  - restricted location: entry violation only, no PPE checks")
    print("  - stops after the last viewer leaves; errors are reported")
    print("  - /officer/cameras/{id}/ai-status endpoint")


def _endpoint_tests() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with Session() as db:
        location = models.Location(name="Block", zone="A", department="QA")
        db.add(location); db.flush()
        camera = models.Camera(name="Cam", type="FILE", stream_url="x.mp4", status="active", location_id=location.id)
        db.add(camera)
        db.add(models.User(name="Officer", email="officer@test.local", password=hash_password("test1234"), role="officer", status="active"))
        db.commit()
        camera_id = camera.id

    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(officer.router)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    token = client.post("/auth/login", json={"email": "officer@test.local", "password": "test1234"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    idle = client.get(f"/officer/cameras/{camera_id}/ai-status", headers=headers)
    assert idle.status_code == 200 and idle.json()["state"] == "stopped", idle.text
    assert client.get("/officer/cameras/9999/ai-status", headers=headers).status_code == 404
    assert client.get(f"/officer/cameras/{camera_id}/ai-status").status_code == 422
    engine.dispose()


if __name__ == "__main__":
    run_tests()
