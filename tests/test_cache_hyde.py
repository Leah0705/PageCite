from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document


def _doc(content="test content", ref="ref1"):
    return Document(
        page_content=content,
        metadata={"doc_id": "test", "ref": ref, "page": 1, "chunk_id": 0, "source": "test.pdf"},
    )


# rerank_with_score

def test_rerank_with_score_returns_correct_top_score():
    from rag.chains.rerank import rerank_with_score

    docs = [_doc("doc a", "a"), _doc("doc b", "b")]
    mock_encoder = MagicMock()
    mock_encoder.predict.return_value = [0.8, 0.3]

    with patch("rag.chains.rerank._get_cross_encoder", return_value=mock_encoder):
        result_docs, top_score = rerank_with_score("query", docs, top_k=2)

    assert top_score == pytest.approx(0.8, abs=1e-4)
    assert result_docs[0].metadata["ref"] == "a"
    assert result_docs[1].metadata["ref"] == "b"


def test_rerank_with_score_empty_input():
    from rag.chains.rerank import rerank_with_score

    docs, score = rerank_with_score("query", [])
    assert docs == []
    assert score == 0.0


# semantic cache

def test_cache_lookup_graceful_when_redis_down():
    from rag import cache

    with patch("rag.cache._get_client", side_effect=ConnectionError("Redis down")):
        assert cache.lookup("any query", "doc-1") is None


def test_cache_store_graceful_when_redis_down():
    from rag import cache

    with patch("rag.cache._get_client", side_effect=ConnectionError("Redis down")):
        cache.store("q", "doc-1", "answer", [])  # must not raise


def test_cache_lookup_returns_none_on_empty_results():
    from rag import cache

    mock_client = MagicMock()
    mock_client.ft.return_value.info.return_value = {}
    mock_client.ft.return_value.search.return_value = MagicMock(docs=[])

    with patch("rag.cache._get_client", return_value=mock_client), \
         patch("rag.cache._embed", return_value=[0.0] * 768):
        assert cache.lookup("unknown query", "doc-1") is None


def test_cache_lookup_hit_above_threshold():
    from rag import cache

    citations = [{"ref": "r1", "page": 1, "chunk_id": 0, "source": "f.pdf"}]
    mock_doc = MagicMock()
    mock_doc.score = "0.01"  # distance → similarity = 0.99, above default 0.97
    mock_doc.answer = b"cached answer"
    mock_doc.citations = json.dumps(citations).encode()

    mock_client = MagicMock()
    mock_client.ft.return_value.info.return_value = {}
    mock_client.ft.return_value.search.return_value = MagicMock(docs=[mock_doc])

    with patch("rag.cache._get_client", return_value=mock_client), \
         patch("rag.cache._embed", return_value=[0.0] * 768), \
         patch.dict("os.environ", {"SEMANTIC_CACHE_THRESHOLD": "0.97"}):
        result = cache.lookup("what is attention?", "doc-1")

    assert result is not None
    assert result["answer"] == "cached answer"
    assert result["citations"] == citations


def test_cache_lookup_miss_below_threshold():
    from rag import cache

    mock_doc = MagicMock()
    mock_doc.score = "0.15"  # distance → similarity = 0.85, below 0.97

    mock_client = MagicMock()
    mock_client.ft.return_value.info.return_value = {}
    mock_client.ft.return_value.search.return_value = MagicMock(docs=[mock_doc])

    with patch("rag.cache._get_client", return_value=mock_client), \
         patch("rag.cache._embed", return_value=[0.0] * 768), \
         patch.dict("os.environ", {"SEMANTIC_CACHE_THRESHOLD": "0.97"}):
        assert cache.lookup("something different", "doc-1") is None


def test_cache_lookup_is_scoped_by_doc_id():
    from rag import cache

    # Redis returns no docs when the doc_id tag filter matches nothing
    mock_client = MagicMock()
    mock_client.ft.return_value.info.return_value = {}
    mock_client.ft.return_value.search.return_value = MagicMock(docs=[])

    with patch("rag.cache._get_client", return_value=mock_client), \
         patch("rag.cache._embed", return_value=[0.0] * 768):
        result = cache.lookup("same question as doc-a", "doc-b")

    # Verify the query string includes the doc_id tag filter
    call_args = mock_client.ft.return_value.search.call_args
    query_obj = call_args[0][0]
    assert "doc\\-b" in query_obj.query_string()  # UUID dashes are escaped in tag filter
    assert result is None


# retrieve_with_hyde

def test_retrieve_with_hyde_skips_hyde_when_confident():
    from rag.chains.retrieval import retrieve_with_hyde

    docs = [_doc()]

    # rerank_with_score is imported inside retrieve_with_hyde, so patch the source module
    with patch("rag.chains.retrieval.hybrid_search", return_value=docs), \
         patch("rag.chains.rerank.rerank_with_score", return_value=(docs, 0.8)), \
         patch("rag.chains.retrieval._hyde_dense_search") as mock_hyde, \
         patch.dict("os.environ", {"HYDE_THRESHOLD": "0.3"}):
        result, hyde_triggered = retrieve_with_hyde("test_doc", "what is attention?")

    mock_hyde.assert_not_called()
    assert result == docs
    assert hyde_triggered is False


def test_retrieve_with_hyde_triggers_when_low_confidence():
    from rag.chains.retrieval import retrieve_with_hyde

    original = [_doc("original", "orig")]
    hyde_results = [_doc("hypothetical", "hyde")]
    reranked = [_doc("merged", "merged")]

    rerank_calls = {"n": 0}

    def fake_rerank(query, docs, top_k=5):
        rerank_calls["n"] += 1
        if rerank_calls["n"] == 1:
            return original, 0.1  # low score → HyDE fires
        return reranked, 0.7

    with patch("rag.chains.retrieval.hybrid_search", return_value=original), \
         patch("rag.chains.rerank.rerank_with_score", side_effect=fake_rerank), \
         patch("rag.chains.retrieval._hyde_dense_search", return_value=hyde_results), \
         patch("rag.chains.retrieval._rrf_merge", return_value=reranked), \
         patch.dict("os.environ", {"HYDE_THRESHOLD": "0.3"}):
        result, hyde_triggered = retrieve_with_hyde("test_doc", "obscure query")

    assert result == reranked
    assert hyde_triggered is True
    assert rerank_calls["n"] == 2  # called once before HyDE, once after


def test_retrieve_with_hyde_returns_empty_when_no_candidates():
    from rag.chains.retrieval import retrieve_with_hyde

    with patch("rag.chains.retrieval.hybrid_search", return_value=[]):
        docs, hyde_triggered = retrieve_with_hyde("test_doc", "query")
    assert docs == []
    assert hyde_triggered is False


# /query from_cache field

def test_query_response_includes_from_cache_false(authed_client_with_doc):
    client, doc_id = authed_client_with_doc

    mock_state = {"generation": "an answer", "documents": [], "retry_count": 0, "hyde_triggered": False}
    mock_usage = MagicMock(tokens_in=10, tokens_out=20)

    with patch("app.main.semantic_cache.lookup", return_value=None), \
         patch("app.main.run_agent", return_value=(mock_state, mock_usage)):
        r = client.post("/query", json={"doc_id": doc_id, "question": "What is this?"})

    assert r.status_code == 200
    data = r.json()
    assert data["from_cache"] is False
    assert data["hyde_triggered"] is False


def test_query_returns_from_cache_true_on_hit(authed_client_with_doc):
    client, doc_id = authed_client_with_doc

    cached_payload = {
        "answer": "cached answer text",
        "citations": [{"ref": "r1", "page": 1, "chunk_id": 0, "source": "f.pdf"}],
    }

    with patch("app.main.semantic_cache.lookup", return_value=cached_payload):
        r = client.post("/query", json={"doc_id": doc_id, "question": "What is this document about?"})

    assert r.status_code == 200
    data = r.json()
    assert data["from_cache"] is True
    assert data["answer"] == "cached answer text"
    assert data["retrieved"] == 1


# cache hygiene: never cache error text, drop stale entries on reindex/delete

_NOT_INDEXED = "No documents have been indexed for this document. Please index the document first."


def test_query_does_not_cache_error_text(authed_client_with_doc):
    client, doc_id = authed_client_with_doc
    state = {"generation": _NOT_INDEXED, "documents": [], "error": _NOT_INDEXED}

    with patch("app.main.semantic_cache.lookup", return_value=None), \
         patch("app.main.semantic_cache.store") as mock_store, \
         patch("app.main.run_agent", return_value=(state, MagicMock(tokens_in=0, tokens_out=0))):
        r = client.post("/query", json={"doc_id": doc_id, "question": "What is this?"})

    assert r.status_code == 200
    mock_store.assert_not_called()


def test_query_caches_a_real_answer(authed_client_with_doc):
    client, doc_id = authed_client_with_doc
    state = {"generation": "The report covers Q3 revenue.", "documents": [_doc()], "error": ""}

    with patch("app.main.semantic_cache.lookup", return_value=None), \
         patch("app.main.semantic_cache.store") as mock_store, \
         patch("app.main.run_agent", return_value=(state, MagicMock(tokens_in=5, tokens_out=5))):
        r = client.post("/query", json={"doc_id": doc_id, "question": "What is this?"})

    assert r.status_code == 200
    mock_store.assert_called_once()


def test_query_stream_does_not_cache_error_text(authed_client_with_doc):
    client, doc_id = authed_client_with_doc
    state = {"generation": "Answer generation failed due to an API error.",
             "documents": [_doc()], "error": "Answer generation failed: API down"}

    with patch("app.main.semantic_cache.lookup", return_value=None), \
         patch("app.main.semantic_cache.store") as mock_store, \
         patch("app.main.check_and_consume", return_value=(True, 0)), \
         patch("app.main.run_agent", return_value=(state, MagicMock(tokens_in=0, tokens_out=0))):
        r = client.post("/query/stream", json={"doc_id": doc_id, "question": "What is this?"})

    assert r.status_code == 200
    assert "event: done" in r.text
    mock_store.assert_not_called()


def test_cache_invalidate_deletes_entries_for_the_document():
    from rag import cache

    client = MagicMock()
    first = MagicMock(docs=[MagicMock(id="cache:x:1"), MagicMock(id="cache:x:2")])
    client.ft.return_value.search.side_effect = [first, MagicMock(docs=[])]
    client.delete.return_value = 2

    with patch("rag.cache._get_client", return_value=client):
        removed = cache.invalidate("1234-abcd")

    assert removed == 2
    client.delete.assert_called_once_with("cache:x:1", "cache:x:2")
    query = client.ft.return_value.search.call_args_list[0].args[0]
    assert "@doc_id:{1234\\-abcd}" in query.query_string()


def test_cache_invalidate_graceful_when_redis_down():
    from rag import cache

    with patch("rag.cache._get_client", side_effect=ConnectionError("Redis down")):
        assert cache.invalidate("doc-1") == 0


def test_delete_document_invalidates_cache_and_chat_memory(authed_client_with_doc):
    client, doc_id = authed_client_with_doc

    with patch("app.main.clear_document"), \
         patch("app.main.clear_document_memory") as mock_clear_memory, \
         patch("app.main.semantic_cache.invalidate") as mock_invalidate:
        r = client.delete(f"/documents/{doc_id}")

    assert r.status_code == 204
    mock_invalidate.assert_called_once_with(doc_id)
    mock_clear_memory.assert_called_once_with(doc_id)


def test_reindex_document_invalidates_cache(authed_client_with_doc):
    import worker.tasks  # noqa: F401, pre-load so the patch below applies

    client, doc_id = authed_client_with_doc

    with patch("worker.tasks.ingest_document", MagicMock()), \
         patch("app.main.semantic_cache.invalidate") as mock_invalidate:
        r = client.post(f"/documents/{doc_id}/reindex")

    assert r.status_code == 200
    mock_invalidate.assert_called_once_with(doc_id)


def test_cache_namespace_follows_the_embedding_model():
    """Switching EMBEDDING_MODEL must not compare new vectors with old cached ones."""
    import importlib

    import rag.cache as cache
    import rag.llm as llm

    default_prefix, default_index = cache._KEY_PREFIX, cache._INDEX_NAME
    original = llm.EMBEDDING_MODEL
    try:
        llm.EMBEDDING_MODEL = "intfloat/multilingual-e5-base"
        importlib.reload(cache)
        assert cache._KEY_PREFIX != default_prefix
        assert cache._INDEX_NAME != default_index
    finally:
        llm.EMBEDDING_MODEL = original
        importlib.reload(cache)
    assert cache._KEY_PREFIX == default_prefix
