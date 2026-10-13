"""migrations/ is the only schema source: these tests keep it in step with app/models.py."""
from __future__ import annotations

import re
import uuid
from unittest.mock import MagicMock, call, patch

import psycopg2
import pytest

from app.migrate import _ADVISORY_LOCK_ID, apply_migrations, database_dsn, migration_files


def test_migration_files_are_numbered_and_unique():
    names = [p.name for p in migration_files()]
    numbers = [re.match(r"(\d{3})_", n).group(1) for n in names]
    assert names == sorted(names)
    assert len(numbers) == len(set(numbers))
    assert numbers[0] == "001"


def test_apply_migrations_locks_then_runs_files_in_order():
    cur = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur

    with patch("app.migrate.psycopg2.connect", return_value=conn):
        applied = apply_migrations("postgresql://x")

    files = migration_files()
    assert applied == [p.name for p in files]
    assert cur.execute.call_args_list[0] == call("SELECT pg_advisory_xact_lock(%s)", (_ADVISORY_LOCK_ID,))
    executed = [c.args[0] for c in cur.execute.call_args_list[1:]]
    assert executed == [p.read_text(encoding="utf-8") for p in files]
    conn.close.assert_called_once()


# ---------------------------------------------------------------------------
# Integration: needs Postgres with pgvector (the CI service). Skipped otherwise.
# Migrations are idempotent and the API runs them on every start-up, so applying
# them to a development database here is safe.
# ---------------------------------------------------------------------------

def _connect_or_skip():
    try:
        return psycopg2.connect(database_dsn(), connect_timeout=2)
    except psycopg2.OperationalError as exc:
        pytest.skip(f"Postgres not reachable: {exc}")


def test_migrations_are_idempotent_and_cover_every_orm_column():
    from app.models import Base

    _connect_or_skip().close()
    apply_migrations()
    apply_migrations()  # a second run must be a no-op, not an error

    conn = _connect_or_skip()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema()"
            )
            db_columns = set(cur.fetchall())
    finally:
        conn.close()

    missing = sorted(
        f"{table.name}.{column.name}"
        for table in Base.metadata.sorted_tables
        for column in table.columns
        if (table.name, column.name) not in db_columns
    )
    assert missing == [], f"ORM columns missing from migrations/: {missing}"
    assert ("chunks", "embedding") in db_columns


def test_orm_can_write_every_model_after_migrations():
    """Round trip through SQLAlchemy inside a transaction that is rolled back."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.models import ApiKey, Conversation, Document, IngestionEvent, Message, User

    _connect_or_skip().close()
    apply_migrations()

    engine = create_engine(database_dsn())
    try:
        with engine.connect() as connection:
            trans = connection.begin()
            session = Session(bind=connection)
            user_id = f"test_{uuid.uuid4().hex}"
            doc = Document(user_id=user_id, filename="policy.pdf", status="processing",
                           celery_task_id="task-1", error_message=None,
                           stopped_at_progress=40, stopped_at_step="Parsing")
            session.add(User(clerk_id=user_id, email="t@example.com"))
            session.flush()
            session.add(doc)
            session.flush()
            conv = Conversation(user_id=user_id, doc_id=doc.id)
            session.add(conv)
            session.flush()
            session.add_all([
                Message(conversation_id=conv.id, role="assistant", content="hi",
                        citations={"items": []}, tokens_in=1, tokens_out=2, cost_usd=0.1),
                IngestionEvent(user_id=user_id, doc_id=doc.id, tokens_in=3, tokens_out=4, cost_usd=0.2),
                ApiKey(user_id=user_id, key_hash=uuid.uuid4().hex, name="ci"),
            ])
            session.flush()
            assert session.get(Document, doc.id).celery_task_id == "task-1"
            session.close()
            trans.rollback()
    finally:
        engine.dispose()
