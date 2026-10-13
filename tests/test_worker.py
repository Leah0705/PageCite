"""Unit tests for the Celery ingest_document task."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import worker.tasks  # noqa: F401, ensures module is in sys.modules before patching
from worker.tasks import ingest_document


def _make_doc(status="pending"):
    doc = MagicMock()
    doc.status = status
    doc.page_count = None
    doc.error_message = None
    return doc


def _make_session(doc):
    """Return a context-manager-compatible SQLAlchemy session mock."""
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    session.get.return_value = doc
    return session


def _run(doc, index_return=(15, "pgvector", 5, 0, 0), index_raise=None, doc_id=None):
    """Execute the task with external I/O fully mocked. Returns the doc mock."""
    if doc_id is None:
        doc_id = str(uuid.uuid4())
    session = _make_session(doc)
    mock_session_cls = MagicMock(return_value=session)

    index_kwargs = {"side_effect": index_raise} if index_raise else {"return_value": index_return}

    with patch("worker.tasks._Session", mock_session_cls), \
         patch("worker.tasks._set_progress"), \
         patch("worker.tasks._clear_progress"), \
         patch("worker.tasks._set_step"), \
         patch("worker.tasks._clear_step"), \
         patch("rag.ingest.index_document", **index_kwargs):
        try:
            ingest_document(doc_id)
        except Exception:
            pass

    return doc


def test_success_sets_indexed_status():
    doc = _make_doc("pending")
    _run(doc)
    assert doc.status == "indexed"


def test_success_stores_index_time_and_page_count():
    doc = _make_doc("pending")
    _run(doc, index_return=(20, "pgvector", 7, 0, 0))
    assert doc.index_time_s is not None
    assert doc.page_count == 7


def test_success_progress_reaches_100():
    doc_id = str(uuid.uuid4())
    doc = _make_doc("pending")
    session = _make_session(doc)
    captured_progress: list[int] = []

    with patch("worker.tasks._Session", MagicMock(return_value=session)), \
         patch("worker.tasks._set_progress", side_effect=lambda _, pct: captured_progress.append(pct)), \
         patch("worker.tasks._clear_progress"), \
         patch("worker.tasks._set_step"), \
         patch("worker.tasks._clear_step"), \
         patch("rag.ingest.index_document", return_value=(5, "pgvector", 3, 0, 0)):
        ingest_document(doc_id)

    assert 100 in captured_progress


def test_failure_sets_failed_status():
    doc = _make_doc("pending")
    _run(doc, index_raise=RuntimeError("OCR crashed"))
    assert doc.status == "failed"


def test_failure_stores_error_message():
    doc = _make_doc("pending")
    _run(doc, index_raise=RuntimeError("OCR crashed"))
    assert "OCR crashed" in (doc.error_message or "")


def test_failure_clears_progress():
    doc_id = str(uuid.uuid4())
    doc = _make_doc("pending")
    session = _make_session(doc)

    with patch("worker.tasks._Session", MagicMock(return_value=session)), \
         patch("worker.tasks._set_progress"), \
         patch("worker.tasks._clear_progress") as mock_clear, \
         patch("worker.tasks._set_step"), \
         patch("worker.tasks._clear_step"), \
         patch("rag.ingest.index_document", side_effect=RuntimeError("fail")):
        try:
            ingest_document(doc_id)
        except Exception:
            pass

    mock_clear.assert_called_with(doc_id)


def test_missing_doc_returns_early_without_indexing():
    doc_id = str(uuid.uuid4())
    missing_session = MagicMock()
    missing_session.__enter__ = MagicMock(return_value=missing_session)
    missing_session.__exit__ = MagicMock(return_value=False)
    missing_session.get.return_value = None

    with patch("worker.tasks._Session", MagicMock(return_value=missing_session)), \
         patch("worker.tasks._set_progress"), \
         patch("worker.tasks._clear_progress"), \
         patch("worker.tasks._set_step"), \
         patch("worker.tasks._clear_step"), \
         patch("rag.ingest.index_document") as mock_index:
        result = ingest_document(doc_id)

    assert result == {"error": "document not found"}
    mock_index.assert_not_called()
