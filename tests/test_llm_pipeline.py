from __future__ import annotations


def test_llm_init(monkeypatch):
    """LLM initialises correctly when GOOGLE_API_KEY is present."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-api-key")
    from rag.llm import get_llm
    get_llm.cache_clear()
    try:
        llm = get_llm()
        assert "gemini-2.5-flash" in llm.model
    finally:
        get_llm.cache_clear()


def test_embeddings_dimension():
    """The default embedding model produces 768-dimensional vectors."""
    from rag.llm import get_embeddings
    embeddings = get_embeddings()
    vector = embeddings.embed_query("hello world")
    assert len(vector) == 768


def test_embedding_prefixes_are_passed_to_the_model(monkeypatch):
    """Models such as multilingual-e5 need "query: " / "passage: " prefixes."""
    from unittest.mock import MagicMock

    import rag.llm as llm

    created = {}

    def fake_hf(**kwargs):
        created.update(kwargs)
        emb = MagicMock()
        emb.embed_query.return_value = [0.0] * llm.EMBEDDING_DIM
        return emb

    monkeypatch.setattr(llm, "EMBEDDING_MODEL", "intfloat/multilingual-e5-base")
    monkeypatch.setattr(llm, "EMBEDDING_QUERY_PREFIX", "query: ")
    monkeypatch.setattr(llm, "EMBEDDING_PASSAGE_PREFIX", "passage: ")
    monkeypatch.setattr(llm, "HuggingFaceEmbeddings", fake_hf)
    llm.get_embeddings.cache_clear()
    try:
        llm.get_embeddings()
    finally:
        llm.get_embeddings.cache_clear()

    assert created["model_name"] == "intfloat/multilingual-e5-base"
    assert created["query_encode_kwargs"]["prompt"] == "query: "
    assert created["encode_kwargs"]["prompt"] == "passage: "


def test_embedding_model_with_wrong_dimension_is_rejected(monkeypatch):
    from unittest.mock import MagicMock

    import pytest

    import rag.llm as llm

    emb = MagicMock()
    emb.embed_query.return_value = [0.0] * 1024
    monkeypatch.setattr(llm, "HuggingFaceEmbeddings", lambda **kwargs: emb)
    llm.get_embeddings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="1024-d"):
            llm.get_embeddings()
    finally:
        llm.get_embeddings.cache_clear()
