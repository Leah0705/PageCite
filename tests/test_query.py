from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app

_404 = HTTPException(status_code=404, detail="Document not found.")


def test_query_requires_auth():
    with TestClient(app) as client:
        r = client.post("/query", json={"doc_id": "some-id", "question": "What is this?", "top_k": 3})
    assert r.status_code in (401, 403)


def test_query_returns_404_for_missing_doc(authed_client):
    with patch("app.main._get_doc_or_404", new=AsyncMock(side_effect=_404)):
        r = authed_client.post("/query", json={"doc_id": "missing-doc", "question": "What is this?", "top_k": 3})
    assert r.status_code == 404


def test_query_validation_short_question(authed_client):
    r = authed_client.post("/query", json={"doc_id": "x", "question": "a"})
    assert r.status_code in (400, 422)


def test_query_response_schema_on_missing_doc(authed_client):
    with patch("app.main._get_doc_or_404", new=AsyncMock(side_effect=_404)):
        r = authed_client.post("/query", json={"doc_id": "missing-doc", "question": "hello world", "top_k": 5})
    assert r.status_code == 404


def test_query_does_not_block_the_event_loop():
    """While one /query waits on the agent, other requests must still be served.

    Regression: run_agent (several LLM calls) used to run directly inside the
    async endpoint, so a single query froze every other request on the worker.
    """
    import asyncio
    import time
    from unittest.mock import MagicMock

    import httpx

    from app.auth import current_user
    from app.db import get_db
    from tests.conftest import TEST_USER, _mock_db_session

    def slow_agent(**kwargs):
        time.sleep(1.0)  # stands in for the LLM round trips
        return {"generation": "ok", "documents": [], "error": ""}, MagicMock(tokens_in=0, tokens_out=0)

    session = _mock_db_session()

    async def _db():
        yield session

    async def scenario() -> float:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            t0 = time.perf_counter()
            query = asyncio.create_task(client.post(
                "/query", json={"doc_id": "00000000-0000-0000-0000-000000000001", "question": "What is this?"}
            ))
            await asyncio.sleep(0.1)  # let /query reach the agent call
            health = await client.get("/health")
            health_done = time.perf_counter() - t0
            assert health.status_code == 200
            assert (await query).status_code == 200
            return health_done

    app.dependency_overrides[current_user] = lambda: TEST_USER
    app.dependency_overrides[get_db] = _db
    try:
        with patch("app.main._get_doc_or_404", new=AsyncMock()), \
             patch("app.main.check_and_consume", return_value=(True, 0)), \
             patch("app.main.semantic_cache.lookup", return_value=None), \
             patch("app.main.semantic_cache.store"), \
             patch("app.main.redact", side_effect=lambda q: (q, {})), \
             patch("app.main.run_agent", side_effect=slow_agent):
            elapsed = asyncio.run(scenario())
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_db, None)

    # The agent takes 1s; a blocked loop would hold /health until it finished.
    assert elapsed < 0.6, f"/health finished {elapsed:.2f}s after start, behind a running /query"
