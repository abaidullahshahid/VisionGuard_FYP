from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from database import engine, Base
import models  # noqa: F401 — ensures all models are imported before create_all

from routers import auth, admin, officer, worker

# ── Create all database tables ────────────────────────────────────
Base.metadata.create_all(bind=engine)
with engine.begin() as conn:
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS department VARCHAR(100)"))
    conn.execute(text("ALTER TABLE safety_rules ALTER COLUMN ppe_type DROP NOT NULL"))

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
    allow_origins     = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

# ── Routers ───────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(officer.router)
app.include_router(worker.router)


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
