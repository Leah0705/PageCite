"""Tests for the MCP server module (auth and tools)."""
from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# mcp_server.auth
# ---------------------------------------------------------------------------

def test_hash_key_is_deterministic():
    from mcp_server.auth import hash_key

    assert hash_key("pc_abc") == hash_key("pc_abc")
    assert hash_key("pc_abc") == hashlib.sha256(b"pc_abc").hexdigest()


def test_hash_key_differs_per_key():
    from mcp_server.auth import hash_key

    assert hash_key("pc_abc") != hash_key("pc_xyz")


def _mock_conn(row=None):
    """Return a mock psycopg2 connection that yields the given row."""
    cur = MagicMock()
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchone.return_value = row

    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cur
    return conn, cur


def test_validate_api_key_returns_user_id_for_valid_key():
    from mcp_server.auth import hash_key, validate_api_key

    key = "pc_testkey123"
    conn, cur = _mock_conn(row=("user_abc",))

    with patch("mcp_server.auth.psycopg2.connect", return_value=conn):
        result = validate_api_key(key)

    assert result == "user_abc"
    # should have looked up by hash
    call_args = cur.execute.call_args_list[0][0]
    assert hash_key(key) in call_args[1]


def test_validate_api_key_returns_none_for_unknown_key():
    from mcp_server.auth import validate_api_key

    conn, _ = _mock_conn(row=None)

    with patch("mcp_server.auth.psycopg2.connect", return_value=conn):
        result = validate_api_key("pc_unknown")

    assert result is None


def test_validate_api_key_returns_none_for_empty_string():
    from mcp_server.auth import validate_api_key

    result = validate_api_key("")
    assert result is None


def test_validate_api_key_returns_none_on_db_error():
    from mcp_server.auth import validate_api_key

    with patch("mcp_server.auth.psycopg2.connect", side_effect=Exception("conn failed")):
        result = validate_api_key("pc_any")

    assert result is None


# ---------------------------------------------------------------------------
# mcp_server.server: tools (user injected via ContextVar)
# ---------------------------------------------------------------------------

def _set_user(user_id: str):
    from mcp_server.server import _user_id_var
    return _user_id_var.set(user_id)


def test_list_documents_returns_rows():
    from mcp_server.server import list_documents

    row = {"doc_id": "abc", "filename": "paper.pdf", "page_count": 5, "created_at": "2026-01-01"}
    conn, cur = _mock_conn()
    cur.fetchall.return_value = [row]

    token = _set_user("user_1")
    try:
        with patch("mcp_server.server.psycopg2.connect", return_value=conn):
            result = list_documents()
    finally:
        from mcp_server.server import _user_id_var
        _user_id_var.reset(token)

    assert len(result) == 1
    assert result[0]["filename"] == "paper.pdf"


def test_get_document_returns_metadata():
    from mcp_server.server import get_document

    row = {
        "doc_id": "abc",
        "filename": "paper.pdf",
        "page_count": 3,
        "status": "indexed",
        "created_at": "2026-01-01",
        "preview": "This is the beginning of the document content.",
    }
    conn, cur = _mock_conn(row=row)

    token = _set_user("user_1")
    try:
        with patch("mcp_server.server.psycopg2.connect", return_value=conn):
            result = get_document("abc")
    finally:
        from mcp_server.server import _user_id_var
        _user_id_var.reset(token)

    assert result["filename"] == "paper.pdf"
    assert "first_500_chars" in result
    assert "preview" not in result


def test_get_document_returns_error_for_missing_doc():
    from mcp_server.server import get_document

    conn, cur = _mock_conn(row=None)

    token = _set_user("user_1")
    try:
        with patch("mcp_server.server.psycopg2.connect", return_value=conn):
            result = get_document("nonexistent-id")
    finally:
        from mcp_server.server import _user_id_var
        _user_id_var.reset(token)

    assert "error" in result


def test_search_documents_returns_ranked_results():
    from langchain_core.documents import Document as LCDoc
    from mcp_server.server import search_documents

    fake_docs = [
        LCDoc(page_content="Neural networks are powerful.", metadata={"filename": "ml.pdf", "page": 1, "ref": "r1"}),
        LCDoc(page_content="Deep learning requires data.", metadata={"filename": "ml.pdf", "page": 2, "ref": "r2"}),
    ]

    conn, cur = _mock_conn()
    cur.fetchall.return_value = [("doc-uuid-1",)]

    token = _set_user("user_1")
    try:
        with (
            patch("mcp_server.server.psycopg2.connect", return_value=conn),
            patch("mcp_server.server.hybrid_search", return_value=fake_docs),
        ):
            result = search_documents("neural networks", top_k=2)
    finally:
        from mcp_server.server import _user_id_var
        _user_id_var.reset(token)

    assert len(result) == 2
    assert result[0]["content"] == "Neural networks are powerful."
    assert result[0]["score"] > result[1]["score"]


def test_search_documents_clamps_top_k():
    from mcp_server.server import search_documents

    conn, cur = _mock_conn()
    cur.fetchall.return_value = []

    token = _set_user("user_1")
    try:
        with patch("mcp_server.server.psycopg2.connect", return_value=conn):
            result = search_documents("query", top_k=999)
    finally:
        from mcp_server.server import _user_id_var
        _user_id_var.reset(token)

    assert result == []


def test_search_documents_rejects_doc_id_owned_by_another_user():
    """A valid API key must not unlock another user's document by UUID."""
    from mcp_server.server import _user_id_var, search_documents

    token = _set_user("user_a")
    try:
        with (
            patch("mcp_server.server._user_doc_ids", return_value=["doc-of-user-a"]),
            patch("mcp_server.server.hybrid_search") as mock_search,
        ):
            with pytest.raises(ValueError, match="not found or access denied"):
                search_documents("query", doc_id="doc-of-user-b")
    finally:
        _user_id_var.reset(token)

    mock_search.assert_not_called()


def test_search_documents_accepts_owned_doc_id_in_any_case():
    from mcp_server.server import _user_id_var, search_documents

    token = _set_user("user_a")
    try:
        with (
            patch("mcp_server.server._user_doc_ids", return_value=["doc-of-user-a"]),
            patch("mcp_server.server.hybrid_search", return_value=[]) as mock_search,
        ):
            search_documents("query", doc_id=" DOC-OF-USER-A ")
    finally:
        _user_id_var.reset(token)

    assert mock_search.call_args.args[0] == "doc-of-user-a"


def test_require_user_raises_without_context_or_env():
    from mcp_server.server import _require_user

    with patch("mcp_server.server.key_from_env", return_value=None):
        with pytest.raises(RuntimeError, match="PAGECITE_API_KEY"):
            _require_user()


# ---------------------------------------------------------------------------
# HTTP/SSE transport mounted at /mcp in app.main
# ---------------------------------------------------------------------------

def test_mcp_sse_rejects_missing_api_key():
    from fastapi.testclient import TestClient
    from app.main import app

    with patch("app.main._validate_mcp_key", return_value=None):
        with TestClient(app) as client:
            resp = client.get("/mcp/sse")

    assert resp.status_code == 401


def test_mcp_sse_route_hands_the_request_to_the_transport():
    """Regression: the SSE endpoint used to be an ASGI (scope, receive, send) function
    registered as a Starlette Route, which Starlette calls as endpoint(request) -> 500."""
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    from fastapi.testclient import TestClient
    import app.main as main_mod

    @asynccontextmanager
    async def fake_connect_sse(scope, receive, send):
        assert scope["path"].endswith("/sse")
        yield MagicMock(), MagicMock()

    run = AsyncMock()
    with (
        patch("app.main._validate_mcp_key", return_value="user_a"),
        patch.object(main_mod._mcp_sse_transport, "connect_sse", fake_connect_sse),
        patch.object(main_mod._mcp._mcp_server, "run", run),
    ):
        with TestClient(main_mod.app) as client:
            resp = client.get("/mcp/sse", headers={"X-API-Key": "pc_valid"})

    assert resp.status_code == 200
    run.assert_awaited_once()


def test_mcp_messages_route_reaches_the_transport():
    from fastapi.testclient import TestClient
    from app.main import app

    with patch("app.main._validate_mcp_key", return_value="user_a"):
        with TestClient(app) as client:
            resp = client.post("/mcp/messages/", headers={"X-API-Key": "pc_valid"}, json={})

    # Answered by SseServerTransport itself, so the route is wired correctly.
    assert resp.status_code == 400
    assert "session_id is required" in resp.text
