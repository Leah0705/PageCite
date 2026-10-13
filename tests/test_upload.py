from unittest.mock import MagicMock, patch

import worker.tasks  # noqa: F401, pre-load so patch("worker.tasks.ingest_document") works

FAKE_PDF = b"%PDF-1.4\n%fake\n1 0 obj\n<<>>\nendobj\n%%EOF"


def test_upload_pdf_success(tmp_path, monkeypatch, authed_client):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    mock_task = MagicMock()
    with patch("worker.tasks.ingest_document", mock_task):
        r = authed_client.post("/documents", files={"file": ("sample.pdf", FAKE_PDF, "application/pdf")})
    assert r.status_code == 200, r.text
    data = r.json()
    assert "doc_id" in data
    assert data["filename"] == "sample.pdf"


def test_upload_returns_pending_status(tmp_path, monkeypatch, authed_client):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    mock_task = MagicMock()
    with patch("worker.tasks.ingest_document", mock_task):
        r = authed_client.post("/documents", files={"file": ("doc.pdf", FAKE_PDF, "application/pdf")})
    assert r.status_code == 200
    assert r.json()["status"] == "pending"


def test_upload_enqueues_celery_task(tmp_path, monkeypatch, authed_client):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    mock_task = MagicMock()
    with patch("worker.tasks.ingest_document", mock_task):
        r = authed_client.post("/documents", files={"file": ("doc.pdf", FAKE_PDF, "application/pdf")})
    assert r.status_code == 200
    doc_id = r.json()["doc_id"]
    mock_task.delay.assert_called_once_with(doc_id)


def test_upload_reject_non_pdf(tmp_path, monkeypatch, authed_client):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    r = authed_client.post("/documents", files={"file": ("note.txt", b"hello", "text/plain")})
    assert r.status_code == 400


def test_upload_requires_auth():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        r = client.post("/documents", files={"file": ("sample.pdf", b"%PDF", "application/pdf")})
    assert r.status_code in (401, 403)
