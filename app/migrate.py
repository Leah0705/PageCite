"""Apply the SQL files in migrations/ in filename order.

migrations/ is the single source of truth for the database schema. Every file is
idempotent (IF NOT EXISTS, guarded DO blocks), so the API applies all of them on each
start-up and an existing database only picks up what it is missing.

Run by hand with:  python -m app.migrate
"""
from __future__ import annotations

from pathlib import Path

import psycopg2

from app.db import _DATABASE_URL

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

# Serialises concurrent start-ups (several API replicas) on one database.
_ADVISORY_LOCK_ID = 727_119_006


def database_dsn() -> str:
    """DATABASE_URL in the plain form psycopg2 expects."""
    return _DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def apply_migrations(dsn: str | None = None) -> list[str]:
    """Run every migration inside one transaction and return the file names applied."""
    files = migration_files()
    conn = psycopg2.connect(dsn or database_dsn())
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_ADVISORY_LOCK_ID,))
            for path in files:
                cur.execute(path.read_text(encoding="utf-8"))
    finally:
        conn.close()
    return [path.name for path in files]


if __name__ == "__main__":
    for name in apply_migrations():
        print(f"applied {name}")
