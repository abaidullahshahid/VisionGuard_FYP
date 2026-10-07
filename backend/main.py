import os
import signal
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from database import engine, Base
import models  # noqa: F401 — ensures all models are imported before create_all

from routers import alerts, auth, admin, notifications, officer, worker
from services.ai_monitor import monitor_manager
from services.compliance_service import scheduler as compliance_scheduler


DEFAULT_CORS_ORIGINS = (
    "http://localhost:3000,http://127.0.0.1:3000,"
    "http://localhost:3001,http://127.0.0.1:3001"
)
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("VISIONGUARD_CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",")
    if origin.strip()
]


def disable_console_quick_edit():
    """In a Windows cmd window, a click inside the window starts text
    selection ("Select" in the title) and pauses the backend until Esc is
    pressed; every request meanwhile fails with "Cannot reach the
    VisionGuard server".  Switch QuickEdit off for this window.  Mouse
    selection then needs right-click > Mark; Ctrl+C still stops the server."""

    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return  # no console (e.g. started by a service or IDE)
        ENABLE_QUICK_EDIT_MODE, ENABLE_EXTENDED_FLAGS = 0x0040, 0x0080
        kernel32.SetConsoleMode(handle, (mode.value & ~ENABLE_QUICK_EDIT_MODE) | ENABLE_EXTENDED_FLAGS)
    except Exception:
        pass


disable_console_quick_edit()

# ── Create all database tables ────────────────────────────────────
Base.metadata.create_all(bind=engine)
with engine.begin() as conn:
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS department VARCHAR(100)"))
    conn.execute(text("ALTER TABLE safety_rules ALTER COLUMN ppe_type DROP NOT NULL"))
    conn.execute(text(
        "ALTER TABLE safety_instructions ADD COLUMN IF NOT EXISTS safety_rule_id INTEGER "
        "REFERENCES safety_rules(id) ON DELETE CASCADE"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_safety_instructions_safety_rule_id "
        "ON safety_instructions (safety_rule_id)"
    ))
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_acknowledgements_instruction_worker "
        "ON acknowledgements (instruction_id, worker_id)"
    ))
    # Deleting a user keeps their corrective actions (assignee becomes NULL).
    conn.execute(text("ALTER TABLE corrective_actions ALTER COLUMN assigned_to DROP NOT NULL"))
    conn.execute(text("ALTER TABLE corrective_actions ADD COLUMN IF NOT EXISTS former_assignee VARCHAR(150)"))
    # Daily compliance records (services/compliance_service.py).
    for column, kind in (
        ("record_date", "DATE"),
        ("ppe_violations", "INTEGER DEFAULT 0"),
        ("restricted_violations", "INTEGER DEFAULT 0"),
        ("open_incidents", "INTEGER DEFAULT 0"),
        ("actions_total", "INTEGER DEFAULT 0"),
        ("actions_resolved", "INTEGER DEFAULT 0"),
        ("cameras", "INTEGER DEFAULT 0"),
        ("auto_status", "VARCHAR(50)"),
        ("status_source", "VARCHAR(20) DEFAULT 'auto'"),
        ("summary", "TEXT"),
        ("reviewed_at", "TIMESTAMP WITH TIME ZONE"),
        ("updated_at", "TIMESTAMP WITH TIME ZONE DEFAULT now()"),
    ):
        conn.execute(text(f"ALTER TABLE compliance_records ADD COLUMN IF NOT EXISTS {column} {kind}"))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_compliance_records_record_date ON compliance_records (record_date)"
    ))

# ── App setup ─────────────────────────────────────────────────────
app = FastAPI(
    title       = "VisionGuard API",
    description = "Smart Workplace Safety Management System — Backend API",
    version     = "1.0.0",
    docs_url    = "/docs",
    redoc_url   = "/redoc",
)

# ── CORS ──────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins     = CORS_ORIGINS,
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

# ── Routers ───────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(officer.router)
app.include_router(worker.router)
app.include_router(notifications.router)
app.include_router(alerts.router)


@app.on_event("startup")
def start_compliance_scheduler():
    # Builds daily compliance records and sends the daily summary email.
    compliance_scheduler.start()


@app.on_event("startup")
def end_live_streams_on_stop_signal():
    """A Live Feed stream never finishes on its own, and uvicorn waits for
    open responses before it shuts down, so a --reload restart or Ctrl+C
    hung (API unreachable) until every Live Feed page was closed.  When the
    stop signal arrives, stop the camera monitors: their streams end and the
    shutdown completes.  Runs before uvicorn's own handler, which it keeps."""

    if threading.current_thread() is not threading.main_thread():
        return
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        previous = signal.getsignal(sig)

        def handler(signum, frame, previous=previous):
            # A thread: the handler must not block on the monitors' locks.
            threading.Thread(target=monitor_manager.stop_all, kwargs={"wait": False}, daemon=True).start()
            if callable(previous):
                previous(signum, frame)

        signal.signal(sig, handler)


@app.on_event("shutdown")
def stop_ai_monitors():
    # Release cameras held by Live Video Feed AI monitoring.
    monitor_manager.stop_all()
    compliance_scheduler.stop()


# ── Health check ──────────────────────────────────────────────────
@app.get("/", tags=["health"])
def root():
    return {"status": "ok", "service": "VisionGuard API", "version": "1.0.0"}


@app.get("/health", tags=["health"])
def health():
    return {"status": "healthy"}


# ── Entry point ───────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
