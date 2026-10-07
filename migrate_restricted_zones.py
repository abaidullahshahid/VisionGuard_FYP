"""Idempotently add camera-specific restricted zones to the existing database.

Run from the backend directory::

    python migrate_restricted_zones.py

Only creates what is missing; existing tables and rows are never dropped.
"""

from sqlalchemy import text

from database import engine


STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS restricted_zones (
        id SERIAL PRIMARY KEY,
        camera_id INTEGER NOT NULL REFERENCES cameras (id) ON DELETE CASCADE,
        name VARCHAR(150) NOT NULL,
        polygon_points JSON NOT NULL,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_restricted_zones_id ON restricted_zones (id)",
    "CREATE INDEX IF NOT EXISTS ix_restricted_zones_camera_id ON restricted_zones (camera_id)",
)


def run_migration() -> None:
    with engine.begin() as connection:
        for statement in STATEMENTS:
            connection.execute(text(statement))
    print("Restricted-zone schema migration completed successfully")


if __name__ == "__main__":
    run_migration()
