"""Unit tests for DOCX ingestion: rag/ingest.py DOCX paths."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests.fixtures.elements import (
    SAMPLE_HTML_TABLE,
    SAMPLE_NARRATIVE,
    make_narrative,
    make_table,
)


# ── helpers ────────────────────────────────────────────────────────────────────


def _make_title_el(text: str, page: int = 1, depth: int = 0):
    """Fake unstructured Title element with category_depth metadata."""
    from unstructured.documents.elements import Title

    el = Title(text=text)
    el.metadata = SimpleNamespace(page_number=page, category_depth=depth)
    el.category = "Title"
    return el


def _make_header_el(text: str, page: int = 1, depth: int = 1):
    """Fake unstructured Header element."""
    from unstructured.documents.elements import Title  # headers share Title in some versions

    el = Title(text=text)
    el.metadata = SimpleNamespace(page_number=page, category_depth=depth)
    el.category = "Header"
    return el


def _dummy_docx(tmp_path: Path) -> Path:
    p = tmp_path / "docxs" / "testdoc.docx"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"PK\x03\x04placeholder")  # minimal zip-like header
    return p


# ── _build_docs_from_elements with track_sections=True ────────────────────────


def test_heading_updates_section_breadcrumb():
    from rag.ingest import _build_docs_from_elements

    elements = [
        _make_title_el("Introduction", page=1, depth=0),
        make_narrative("Some intro text.", page=1),
    ]
    docs, _, _ = _build_docs_from_elements(elements, "doc1", "test.docx", False, "", track_sections=True)
    text_chunks = [d for d in docs if d.metadata.get("element_type") == "text"]
    # Narrative text after the heading should have the section populated
    narrative_chunks = [d for d in text_chunks if "intro text" in d.page_content.lower()]
    assert narrative_chunks, "Expected at least one chunk from the narrative"
    for chunk in narrative_chunks:
        assert chunk.metadata.get("section") == "Introduction"


def test_nested_heading_builds_path():
    from rag.ingest import _build_docs_from_elements

    elements = [
        _make_title_el("Chapter 2", page=1, depth=0),
        _make_header_el("Background", page=1, depth=1),
        make_narrative("Background content here.", page=1),
    ]
    docs, _, _ = _build_docs_from_elements(elements, "doc1", "test.docx", False, "", track_sections=True)
    text_chunks = [d for d in docs if "background content" in d.page_content.lower()]
    assert text_chunks, "Expected chunk from background narrative"
    assert text_chunks[0].metadata["section"] == "Chapter 2 > Background"


def test_heading_resets_at_same_depth():
    from rag.ingest import _build_docs_from_elements

    elements = [
        _make_title_el("Part A", page=1, depth=0),
        make_narrative("Part A content.", page=1),
        _make_title_el("Part B", page=2, depth=0),
        make_narrative("Part B content.", page=2),
    ]
    docs, _, _ = _build_docs_from_elements(elements, "doc1", "test.docx", False, "", track_sections=True)
    part_b_chunks = [d for d in docs if "part b content" in d.page_content.lower()]
    assert part_b_chunks
    assert part_b_chunks[0].metadata["section"] == "Part B"


def test_table_in_docx_has_section_metadata():
    from rag.ingest import _build_docs_from_elements

    elements = [
        _make_title_el("Results", page=3, depth=0),
        make_table("BLEU scores", SAMPLE_HTML_TABLE, page=3),
    ]
    docs, _, _ = _build_docs_from_elements(elements, "doc1", "test.docx", False, "", track_sections=True)
    table_chunks = [d for d in docs if d.metadata.get("element_type") == "table"]
    assert table_chunks
    assert table_chunks[0].metadata["section"] == "Results"


def test_no_section_tracking_when_disabled():
    from rag.ingest import _build_docs_from_elements

    elements = [
        _make_title_el("Introduction", page=1, depth=0),
        make_narrative("Some text.", page=1),
    ]
    docs, _, _ = _build_docs_from_elements(elements, "doc1", "test.pdf", False, "", track_sections=False)
    for doc in docs:
        assert "section" not in doc.metadata


def test_extra_meta_propagated():
    from rag.ingest import _build_docs_from_elements

    elements = [make_narrative(SAMPLE_NARRATIVE, page=1)]
    docs, _, _ = _build_docs_from_elements(
        elements, "doc1", "test.docx", False, "",
        track_sections=True,
        extra_meta={"source_url": "https://example.com"},
    )
    for doc in docs:
        assert doc.metadata.get("source_url") == "https://example.com"


# ── extract_docx_elements ──────────────────────────────────────────────────────


def test_extract_docx_elements_calls_partition_docx(tmp_path):
    docx_file = _dummy_docx(tmp_path)
    mock_elements = [make_narrative("Hello from DOCX.", page=1)]

    with patch("rag.ingest.extract_docx_elements") as mock_fn:
        mock_fn.return_value = mock_elements
        result = mock_fn(docx_file)

    assert result == mock_elements


# ── index_docx_document ────────────────────────────────────────────────────────


def test_index_docx_document_normal_path(tmp_path, monkeypatch):
    from rag import ingest as ingest_mod

    monkeypatch.setenv("CONTEXTUAL_RETRIEVAL", "false")
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

    _dummy_docx(tmp_path)

    elements = [
        _make_title_el("Introduction", page=1, depth=0),
        make_narrative(SAMPLE_NARRATIVE * 3, page=1),
        make_table("val", SAMPLE_HTML_TABLE, page=2),
    ]

    with patch("rag.ingest.extract_docx_elements", return_value=elements), \
         patch("rag.ingest.clear_document"), \
         patch("rag.ingest.add_documents") as mock_add:
        count, collection, page_count, _, _ = ingest_mod.index_docx_document("testdoc")

    assert count > 0
    mock_add.assert_called_once()
    assert collection == "pgvector"
    assert page_count == 2


def test_index_docx_raises_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    from rag.ingest import index_docx_document

    with pytest.raises(FileNotFoundError):
        index_docx_document("ghost_doc")


def test_index_docx_zero_chunks_on_empty_elements(tmp_path, monkeypatch):
    from rag import ingest as ingest_mod

    monkeypatch.setenv("CONTEXTUAL_RETRIEVAL", "false")
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

    _dummy_docx(tmp_path)

    with patch("rag.ingest.extract_docx_elements", return_value=[]), \
         patch("rag.ingest.clear_document"):
        count, collection, page_count, _, _ = ingest_mod.index_docx_document("testdoc")

    assert count == 0
    assert page_count == 0


def test_index_docx_progress_callback(tmp_path, monkeypatch):
    from rag import ingest as ingest_mod

    monkeypatch.setenv("CONTEXTUAL_RETRIEVAL", "false")
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

    _dummy_docx(tmp_path)
    messages: list[str] = []
    elements = [make_narrative(SAMPLE_NARRATIVE, page=1)]

    with patch("rag.ingest.extract_docx_elements", return_value=elements), \
         patch("rag.ingest.clear_document"), \
         patch("rag.ingest.add_documents"):
        ingest_mod.index_docx_document("testdoc", progress=messages.append)

    assert any("Parsing" in m or "chunk" in m.lower() for m in messages)
