"""A stop signal (--reload restart or Ctrl+C) ends open Live Feed streams.

uvicorn waits for open responses before shutting down, and an MJPEG stream
never ends on its own, so without this the backend hung until every Live
Feed page was closed.  Run:
    python test_shutdown_streams.py
(Importing main runs its usual idempotent startup migrations.)
"""

import signal
import threading
import time

import main


class FakeManager:
    def __init__(self):
        self.stopped = threading.Event()
        self.wait_args = []

    def stop_all(self, wait=True):
        self.wait_args.append(wait)
        self.stopped.set()


def run_tests() -> None:
    original_handler = signal.getsignal(signal.SIGINT)
    original_manager = main.monitor_manager
    seen = []
    signal.signal(signal.SIGINT, lambda signum, frame: seen.append(signum))  # stands in for uvicorn's handler
    fake = FakeManager()
    main.monitor_manager = fake
    try:
        main.end_live_streams_on_stop_signal()
        signal.raise_signal(signal.SIGINT)
        assert fake.stopped.wait(2.0), "monitors were not stopped"
        assert fake.wait_args == [False], fake.wait_args  # never blocks the signal handler
        assert seen == [signal.SIGINT], "uvicorn's own handler must still run"
    finally:
        main.monitor_manager = original_manager
        signal.signal(signal.SIGINT, original_handler)
    print("Shutdown tests passed:")
    print("  - stop signal ends live streams, then uvicorn's handler runs as usual")


if __name__ == "__main__":
    run_tests()
