"""Regression tests for the synchronous index endpoint and answer helpers in app.main."""
from unittest.mock import patch

from app.main import _is_no_answer, _sse


def test_index_endpoint_unpacks_five_tuple(authed_client_with_doc):
    """index_document returns (chunks, collection, pages, tokens_in, tokens_out);
    the endpoint must unpack all five values without crashing."""
    client, doc_id = authed_client_with_doc
    with patch("app.main.index_document", return_value=(12, "pgvector", 3, 100, 50)):
        r = client.post(f"/documents/{doc_id}/index")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["doc_id"] == doc_id
    assert data["chunks_indexed"] == 12
    assert data["collection"] == "pgvector"


def test_index_endpoint_404_for_unknown_doc(authed_client):
    r = authed_client.post("/documents/not-a-uuid/index")
    assert r.status_code == 404


def test_index_endpoint_requires_auth():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        r = client.post("/documents/some-id/index")
    assert r.status_code in (401, 403)


def test_is_no_answer_detects_refusals():
    assert _is_no_answer("I do not know based on the provided document.")
    assert _is_no_answer("  I don't know the answer to that.")
    assert _is_no_answer("No information about this topic was found.")


def test_is_no_answer_accepts_real_answers():
    assert not _is_no_answer("The transformer uses multi-head attention.")
    assert not _is_no_answer("Based on page 3, the answer is 42.")
    assert not _is_no_answer("")


def test_sse_formats_event_and_data():
    assert _sse("token", "hello") == "event: token\ndata: hello\n\n"


def test_sse_splits_a_multiline_payload_into_data_lines():
    """Regression: a token holding a paragraph break used to end the SSE frame early."""
    frame = _sse("token", " paragraph.\n\nSecond")
    assert frame == "event: token\ndata:  paragraph.\ndata: \ndata: Second\n\n"
    # The terminator is the only blank line, so a client splitting on "\n\n" sees one frame.
    assert frame.count("\n\n") == 1 and frame.endswith("\n\n")
