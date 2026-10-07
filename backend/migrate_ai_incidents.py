"""Idempotently extend the existing incidents table for AI persistence."""

from sqlalchemy import text

from database import engine


STATEMENTS = (
    "ALTER TABLE incidents ADD COLUMN IF NOT EXISTS incident_uuid VARCHAR(36)",
    "ALTER TABLE incidents ADD COLUMN IF NOT EXISTS camera_identifier VARCHAR(255)",
    "ALTER TABLE incidents ADD COLUMN IF NOT EXISTS track_id INTEGER",
    "ALTER TABLE incidents ADD COLUMN IF NOT EXISTS stream_time_seconds DOUBLE PRECISION",
    "ALTER TABLE incidents ADD COLUMN IF NOT EXISTS missing_items JSON NOT NULL DEFAULT '[]'",
    "ALTER TABLE incidents ADD COLUMN IF NOT EXISTS zone_id VARCHAR(255)",
    "ALTER TABLE incidents ADD COLUMN IF NOT EXISTS zone_name VARCHAR(255)",
    "ALTER TABLE incidents ADD COLUMN IF NOT EXISTS evidence_path VARCHAR(1000)",
    "ALTER TABLE incidents ADD COLUMN IF NOT EXISTS metadata JSON NOT NULL DEFAULT '{}'",
    "ALTER TABLE incidents ADD COLUMN IF NOT EXISTS officer_notes TEXT",
    "ALTER TABLE incidents ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP",
    "ALTER TABLE incidents ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_incidents_incident_uuid ON incidents (incident_uuid)",
    "CREATE INDEX IF NOT EXISTS ix_incidents_status ON incidents (status)",
    "CREATE INDEX IF NOT EXISTS ix_incidents_detected_at ON incidents (detected_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_acknowledgements_instruction_worker "
    "ON acknowledgements (instruction_id, worker_id)",
)


def run_migration() -> None:
    with engine.begin() as connection:
        for statement in STATEMENTS:
            connection.execute(text(statement))
    print("AI incident schema migration completed successfully")


if __name__ == "__main__":
    run_migration()
