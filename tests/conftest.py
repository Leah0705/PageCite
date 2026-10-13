"""Shared pytest fixtures."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.auth import ClerkUser, current_user
from app.db import get_db
from app.main import app
from app.models import Document as DocModel


@pytest.fixture(autouse=True)
def _skip_db_init(monkeypatch):
    """Prevent lifespan from connecting to Postgres or downloading ML models."""
    async def _noop():
        pass
    monkeypatch.setattr("app.main._init_db", _noop)
    monkeypatch.setattr("app.main.get_embeddings", MagicMock)

@pytest.fixture
def fake_redis(monkeypatch):
    """Route conversation memory to an in-memory fake instead of a Redis server."""
    from tests.fixtures.fake_redis import FakeRedis

    fake = FakeRedis()
    monkeypatch.setattr("rag.agents.memory._redis", lambda: fake)
    return fake


TEST_USER = ClerkUser(user_id="test_user", email="test@test.com")


def _mock_db_session(doc: DocModel | None = None) -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()  # synchronous in SQLAlchemy
    result = MagicMock()
    result.scalar_one_or_none.return_value = doc
    result.scalars.return_value.all.return_value = [doc] if doc else []
    session.execute.return_value = result
    return session


@pytest.fixture
def authed_client():
    """TestClient with auth and DB dependencies overridden (no real document)."""
    session = _mock_db_session()

    async def _db():
        yield session

    app.dependency_overrides[current_user] = lambda: TEST_USER
    app.dependency_overrides[get_db] = _db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(current_user, None)
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def authed_client_with_doc(tmp_path, monkeypatch):
    """TestClient + auth + a fake indexed document in the mock DB + PDF on disk."""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

    doc_id = str(uuid.uuid4())
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir(parents=True)
    (pdf_dir / f"{doc_id}.pdf").write_bytes(b"%PDF-1.4 placeholder")

    doc = DocModel(
        id=uuid.UUID(doc_id),
        user_id="test_user",
        filename="test.pdf",
        status="indexed",
        created_at=datetime.now(timezone.utc),
    )
    session = _mock_db_session(doc)

    async def _db():
        yield session

    app.dependency_overrides[current_user] = lambda: TEST_USER
    app.dependency_overrides[get_db] = _db
    with TestClient(app) as client:
        yield client, doc_id
    app.dependency_overrides.pop(current_user, None)
    app.dependency_overrides.pop(get_db, None)
