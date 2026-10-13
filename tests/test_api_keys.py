"""Tests for the API key management endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.auth import ClerkUser, current_user
from app.db import get_db
from app.main import app
from app.models import ApiKey


def _key_session(key: ApiKey | None = None) -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = key
    result.scalars.return_value.all.return_value = [key] if key else []
    session.execute.return_value = result
    return session


def _make_key(user_id: str = "test_user", name: str = "My Key") -> ApiKey:
    return ApiKey(
        id=uuid.uuid4(),
        user_id=user_id,
        key_hash="fakehash",
        name=name,
        created_at=datetime.now(timezone.utc),
        last_used_at=None,
    )


def _authed(session: AsyncMock):
    """Override auth + DB and return a TestClient context."""
    async def _db():
        yield session

    app.dependency_overrides[current_user] = lambda: ClerkUser(user_id="test_user", email="t@t.com")
    app.dependency_overrides[get_db] = _db
    return TestClient(app)


# -- create ------------------------------------------------------------------

def test_create_api_key_returns_201_with_key():
    session = _key_session()

    async def mock_refresh(record):
        record.created_at = datetime.now(timezone.utc)

    session.refresh.side_effect = mock_refresh

    with _authed(session) as client:
        r = client.post("/api-keys", json={"name": "Claude Desktop"})
    app.dependency_overrides.clear()

    assert r.status_code == 201
    data = r.json()
    assert data["key"].startswith("pc_")
    assert data["name"] == "Claude Desktop"
    assert "id" in data
    assert "created_at" in data


def test_create_api_key_default_name():
    session = _key_session()

    async def mock_refresh(record):
        record.created_at = datetime.now(timezone.utc)

    session.refresh.side_effect = mock_refresh

    with _authed(session) as client:
        r = client.post("/api-keys", json={})
    app.dependency_overrides.clear()

    assert r.status_code == 201
    assert r.json()["name"] == "Default"


def test_create_api_key_requires_auth():
    with TestClient(app) as client:
        r = client.post("/api-keys", json={"name": "x"})
    assert r.status_code in (401, 403)


# -- list --------------------------------------------------------------------

def test_list_api_keys_returns_records():
    key = _make_key(name="Cursor")
    session = _key_session(key)

    with _authed(session) as client:
        r = client.get("/api-keys")
    app.dependency_overrides.clear()

    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["name"] == "Cursor"
    assert "key" not in rows[0]  # plaintext must never appear in list


def test_list_api_keys_empty():
    session = _key_session()

    with _authed(session) as client:
        r = client.get("/api-keys")
    app.dependency_overrides.clear()

    assert r.status_code == 200
    assert r.json() == []


def test_list_api_keys_requires_auth():
    with TestClient(app) as client:
        r = client.get("/api-keys")
    assert r.status_code in (401, 403)


# -- revoke ------------------------------------------------------------------

def test_revoke_api_key_returns_204():
    key = _make_key()
    session = _key_session(key)

    with _authed(session) as client:
        r = client.delete(f"/api-keys/{key.id}")
    app.dependency_overrides.clear()

    assert r.status_code == 204
    session.delete.assert_called_once_with(key)


def test_revoke_nonexistent_key_returns_404():
    session = _key_session(key=None)

    with _authed(session) as client:
        r = client.delete(f"/api-keys/{uuid.uuid4()}")
    app.dependency_overrides.clear()

    assert r.status_code == 404


def test_revoke_invalid_uuid_returns_404():
    session = _key_session()

    with _authed(session) as client:
        r = client.delete("/api-keys/not-a-uuid")
    app.dependency_overrides.clear()

    assert r.status_code == 404


def test_revoke_requires_auth():
    with TestClient(app) as client:
        r = client.delete(f"/api-keys/{uuid.uuid4()}")
    assert r.status_code in (401, 403)
