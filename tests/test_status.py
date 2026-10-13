"""Tests for GET /documents/{doc_id}/status."""
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

TEST_USER = ClerkUser(user_id="test_user", email="test@test.com")


def _make_doc(doc_id: str, status: str, page_count: int | None = None) -> DocModel:
    return DocModel(
        id=uuid.UUID(doc_id),
        user_id="test_user",
        filename="report.pdf",
        status=status,
        page_count=page_count,
        created_at=datetime.now(timezone.utc),
    )


def _client_with_doc(doc: DocModel):
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = doc
    session.execute.return_value = result

    async def _db():
        yield session

    app.dependency_overrides[current_user] = lambda: TEST_USER
    app.dependency_overrides[get_db] = _db
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch):
    """Prevent real Redis calls during status tests."""
    monkeypatch.setattr("app.main._get_progress", lambda doc_id: 42)
    monkeypatch.setattr("app.main._get_step", lambda doc_id: "Parsing PDF")


def test_status_indexed(monkeypatch):
    doc_id = str(uuid.uuid4())
    doc = _make_doc(doc_id, "indexed", page_count=10)
    client = _client_with_doc(doc)
    try:
        r = client.get(f"/documents/{doc_id}/status")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "indexed"
        assert data["progress_percent"] == 100
        assert data["page_count"] == 10
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_db, None)


def test_status_processing(monkeypatch):
    doc_id = str(uuid.uuid4())
    doc = _make_doc(doc_id, "processing")
    client = _client_with_doc(doc)
    try:
        r = client.get(f"/documents/{doc_id}/status")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "processing"
        assert data["progress_percent"] == 42  # mocked Redis value
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_db, None)


def test_status_pending():
    doc_id = str(uuid.uuid4())
    doc = _make_doc(doc_id, "pending")
    client = _client_with_doc(doc)
    try:
        r = client.get(f"/documents/{doc_id}/status")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "pending"
        assert data["progress_percent"] == 0
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_db, None)


def test_status_failed():
    doc_id = str(uuid.uuid4())
    doc = _make_doc(doc_id, "failed")
    client = _client_with_doc(doc)
    try:
        r = client.get(f"/documents/{doc_id}/status")
        assert r.status_code == 200
        assert r.json()["status"] == "failed"
        assert r.json()["progress_percent"] == 0
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_db, None)


def test_status_404_for_unknown_doc():
    doc_id = str(uuid.uuid4())
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result

    async def _db():
        yield session

    app.dependency_overrides[current_user] = lambda: TEST_USER
    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as client:
            r = client.get(f"/documents/{doc_id}/status")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_db, None)


def test_status_invalid_uuid():
    app.dependency_overrides[current_user] = lambda: TEST_USER
    session = AsyncMock()

    async def _db():
        yield session

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as client:
            r = client.get("/documents/not-a-uuid/status")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_db, None)
