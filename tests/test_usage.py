from unittest.mock import AsyncMock, MagicMock, patch

from app.auth import ClerkUser, current_user
from app.db import get_db
from app.main import app
from fastapi.testclient import TestClient

_USER = ClerkUser(user_id="usage_user", email="u@test.com")


def _authed_client_with_db(mock_session):
    async def _db():
        yield mock_session

    app.dependency_overrides[current_user] = lambda: _USER
    app.dependency_overrides[get_db] = _db
    return TestClient(app)


def _teardown():
    app.dependency_overrides.pop(current_user, None)
    app.dependency_overrides.pop(get_db, None)


def test_usage_me_returns_totals():
    row = MagicMock()
    row.total_cost = 0.0042
    row.total_tokens = 1234

    result = MagicMock()
    result.one.return_value = row

    session = AsyncMock()
    session.execute.return_value = result

    client = _authed_client_with_db(session)
    try:
        r = client.get("/usage/me")
    finally:
        _teardown()

    assert r.status_code == 200
    data = r.json()
    assert "total_cost_usd" in data
    assert "total_tokens" in data
    assert data["total_tokens"] == 1234


def test_usage_me_requires_auth():
    with TestClient(app) as client:
        r = client.get("/usage/me")
    assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Rate limiting: 429 on query endpoints
# ---------------------------------------------------------------------------

def test_query_stream_429_when_rate_limited(authed_client):
    with patch("app.main.check_and_consume", return_value=(False, 3600)), \
         patch("app.main._get_doc_or_404"), \
         patch("app.main.semantic_cache.lookup", return_value=None):
        r = authed_client.post(
            "/query/stream",
            json={"doc_id": "x" * 36, "question": "What is this?"},
        )
    assert r.status_code == 429
    assert "Retry-After" in r.headers
    assert r.headers["Retry-After"] == "3600"


def test_query_429_when_rate_limited(authed_client):
    with patch("app.main.check_and_consume", return_value=(False, 1800)):
        r = authed_client.post(
            "/query",
            json={"doc_id": "x" * 36, "question": "What is this?", "top_k": 3},
        )
    assert r.status_code == 429
    assert r.headers.get("Retry-After") == "1800"


def test_query_proceeds_when_under_limit(authed_client):
    """When rate limit passes, the request proceeds (mocked _get_doc_or_404 → 404)."""
    from fastapi import HTTPException

    with patch("app.main.check_and_consume", return_value=(True, 0)), \
         patch("app.main._get_doc_or_404", new=AsyncMock(side_effect=HTTPException(404, "not found"))):
        r = authed_client.post(
            "/query",
            json={"doc_id": "x" * 36, "question": "What is this?", "top_k": 3},
        )
    assert r.status_code == 404  # passed rate limit, hit doc 404
