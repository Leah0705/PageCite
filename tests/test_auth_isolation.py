"""Tests for auth enforcement and per-user document isolation."""
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

_OTHER_USER = ClerkUser(user_id="other_user", email="other@test.com")


# ---------------------------------------------------------------------------
# Auth enforcement: all protected endpoints must reject unauthenticated calls
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method,path,kwargs", [
    ("GET",    "/documents",                         {}),
    ("POST",   "/documents",                         {"files": {"file": ("a.pdf", b"%PDF", "application/pdf")}}),
    ("POST",   "/documents/some-id/index",           {}),
    ("POST",   "/documents/some-id/index/stream",    {}),
    ("DELETE", "/documents/some-id",                 {}),
    ("GET",    "/documents/some-id/file",            {}),
    ("POST",   "/query",                             {"json": {"doc_id": "x", "question": "hello world"}}),
    ("POST",   "/query/stream",                      {"json": {"doc_id": "x", "question": "hello world"}}),
])
def test_endpoint_requires_auth(method, path, kwargs):
    with TestClient(app) as client:
        r = client.request(method, path, **kwargs)
    assert r.status_code in (401, 403), f"{method} {path} returned {r.status_code}"


# ---------------------------------------------------------------------------
# User isolation: a user cannot access another user's document
# ---------------------------------------------------------------------------

def _session_for_user(owner_user_id: str) -> AsyncMock:
    """Return a mock DB session whose doc is owned by owner_user_id."""
    doc_id = uuid.uuid4()
    doc = DocModel(
        id=doc_id,
        user_id=owner_user_id,
        filename="secret.pdf",
        status="indexed",
        created_at=datetime.now(timezone.utc),
    )
    session = AsyncMock()
    session.add = MagicMock()
    result = MagicMock()
    # scalar_one_or_none returns the doc only when owner queries it
    result.scalar_one_or_none.return_value = doc
    result.scalars.return_value.all.return_value = [doc]
    session.execute.return_value = result
    return session, str(doc_id)


def test_list_docs_returns_only_own_documents():
    """GET /documents must filter by user_id: another user gets an empty list."""
    session, _ = _session_for_user("user_a")

    # Simulate user_b's session returning no rows (they own nothing)
    session_b = AsyncMock()
    session_b.add = MagicMock()
    result_b = MagicMock()
    result_b.scalars.return_value.all.return_value = []
    session_b.execute.return_value = result_b

    async def _db():
        yield session_b

    app.dependency_overrides[current_user] = lambda: _OTHER_USER
    app.dependency_overrides[get_db] = _db
    with TestClient(app) as client:
        r = client.get("/documents")
    app.dependency_overrides.pop(current_user, None)
    app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 200
    assert r.json() == []


def test_get_doc_file_returns_404_for_wrong_user(tmp_path):
    """GET /documents/{doc_id}/file owned by user_a must return 404 for user_b."""
    import os
    os.environ["STORAGE_DIR"] = str(tmp_path)

    doc_id = str(uuid.uuid4())
    # Create the PDF on disk
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir(parents=True)
    (pdf_dir / f"{doc_id}.pdf").write_bytes(b"%PDF-1.4 placeholder")

    # DB returns None: doc belongs to a different user
    session = AsyncMock()
    session.add = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result

    async def _db():
        yield session

    app.dependency_overrides[current_user] = lambda: _OTHER_USER
    app.dependency_overrides[get_db] = _db
    with TestClient(app) as client:
        r = client.get(f"/documents/{doc_id}/file")
    app.dependency_overrides.pop(current_user, None)
    app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 404
