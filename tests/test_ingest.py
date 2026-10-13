"""Unit tests for rag/ingest.py: table extraction, figure captioning, OCR fallback."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import sys

sys.path.insert(0, str(Path(__file__).parent))

from fixtures.elements import (
    SAMPLE_HTML_TABLE,
    SAMPLE_NARRATIVE,
    make_image,
    make_narrative,
    make_table,
    make_title,
)


def _dummy_pdf(tmp_path: Path) -> Path:
    """Write a trivial valid-looking file that satisfies path.exists()."""
    p = tmp_path / "pdfs" / "test123.pdf"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"%PDF-1.4 placeholder")
    return p


# _clean_text

def test_clean_text_ligatures():
    from rag.ingest import _clean_text
    assert "fi" in _clean_text("ﬁnancial")  # ﬁ → fi via NFKC


def test_clean_text_keeps_chinese_and_accented_text():
    """Regression: an ASCII-only filter used to erase Chinese text and accented names."""
    from rag.ingest import _clean_text

    assert _clean_text("报销政策：差旅费用（含住宿）需在30天内提交，逾期不予报销。") == \
        "报销政策：差旅费用（含住宿）需在30天内提交，逾期不予报销。"
    assert _clean_text("Łukasz Kaiser and Jürgen Schmidhuber") == "Łukasz Kaiser and Jürgen Schmidhuber"


def test_clean_text_folds_full_width_and_strips_invisible_chars():
    from rag.ingest import _clean_text

    assert _clean_text("\ufeffＱ３ revenue\u200bgrew\x0c 12％") == "Q3 revenue grew 12%"


def test_splitter_breaks_long_chinese_text_at_sentence_marks():
    from rag.ingest import _SPLITTER

    text = "。".join(["第" + str(i) + "条规定员工差旅需要提前审批并保留全部票据以便财务核对" for i in range(40)]) + "。"
    chunks = _SPLITTER.split_text(text)
    assert len(chunks) > 1
    assert all(len(c) <= 800 for c in chunks)
    # Pieces start or end on a sentence mark rather than in the middle of a clause.
    assert all(c.startswith("。") or c.endswith("。") or c.startswith("第") for c in chunks)


def test_clean_text_collapses_whitespace():
    from rag.ingest import _clean_text
    result = _clean_text("foo   bar\n\n\n\nbaz")
    assert "   " not in result
    assert result.count("\n") <= 2


# _html_to_markdown

def test_html_to_markdown_produces_pipe_table():
    from rag.ingest import _html_to_markdown
    md = _html_to_markdown(SAMPLE_HTML_TABLE)
    assert "|" in md
    assert "BLEU" in md
    assert "27.3" in md


def test_html_to_markdown_fallback_on_import_error(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def _block_markdownify(name, *args, **kwargs):
        if name == "markdownify":
            raise ImportError
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block_markdownify)
    from rag.ingest import _html_to_markdown
    result = _html_to_markdown("<b>hello</b>")
    assert "hello" in result
    assert "<" not in result


# _build_docs_from_elements: table handling

def test_table_becomes_single_markdown_chunk():
    from rag.ingest import _build_docs_from_elements
    elements = [make_table("Model BLEU ...", SAMPLE_HTML_TABLE, page=2)]
    docs, _, _ = _build_docs_from_elements(elements, "doc1", "test.pdf", False, "")
    assert len(docs) == 1
    doc = docs[0]
    assert doc.metadata["element_type"] == "table"
    assert doc.metadata["page"] == 2
    assert "|" in doc.page_content  # Markdown table pipe chars


def test_table_with_no_html_falls_back_to_text():
    from rag.ingest import _build_docs_from_elements
    from unstructured.documents.elements import Table
    from types import SimpleNamespace
    el = Table(text="col1 col2\nval1 val2")
    el.metadata = SimpleNamespace(page_number=1, text_as_html=None)
    docs, _, _ = _build_docs_from_elements([el], "doc1", "test.pdf", False, "")
    assert len(docs) == 1
    assert "col1" in docs[0].page_content


# _build_docs_from_elements: narrative/title chunking

def test_narrative_is_chunked():
    from rag.ingest import _build_docs_from_elements
    long_text = (SAMPLE_NARRATIVE + " ") * 20  # force multiple chunks
    elements = [make_narrative(long_text, page=1)]
    docs, _, _ = _build_docs_from_elements(elements, "doc1", "test.pdf", False, "")
    assert len(docs) >= 2
    for d in docs:
        assert d.metadata["element_type"] == "text"
        assert d.metadata["source"] == "test.pdf"


def test_title_element_produces_chunk():
    from rag.ingest import _build_docs_from_elements
    elements = [make_title("Attention Is All You Need", page=1)]
    docs, _, _ = _build_docs_from_elements(elements, "doc1", "test.pdf", False, "")
    assert len(docs) == 1
    assert docs[0].metadata["element_type"] == "text"


# _build_docs_from_elements: figure captioning

def test_figure_creates_chunk_with_caption(tmp_path, monkeypatch):
    from rag.ingest import _build_docs_from_elements

    img_path = tmp_path / "fig1.png"
    img_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)  # minimal PNG-like bytes

    monkeypatch.setenv("EXTRACT_FIGURES", "true")
    with patch("rag.ingest._caption_figure", return_value=("A bar chart showing accuracy.", 0, 0)):
        elements = [make_image(str(img_path), page=3)]
        docs, _, _ = _build_docs_from_elements(elements, "doc1", "test.pdf", False, "")

    assert len(docs) == 1
    doc = docs[0]
    assert doc.metadata["element_type"] == "figure"
    assert doc.metadata["page"] == 3
    assert doc.metadata["image_path"] == str(img_path)
    assert "bar chart" in doc.page_content


def test_figure_skipped_when_disabled(tmp_path, monkeypatch):
    from rag.ingest import _build_docs_from_elements

    img_path = tmp_path / "fig1.png"
    img_path.write_bytes(b"PNG")
    monkeypatch.setenv("EXTRACT_FIGURES", "false")
    elements = [make_image(str(img_path), page=1)]
    docs, _, _ = _build_docs_from_elements(elements, "doc1", "test.pdf", False, "")
    assert docs == []


def test_figure_cap_respected(tmp_path, monkeypatch):
    from rag import ingest as ingest_mod
    from rag.ingest import _build_docs_from_elements

    monkeypatch.setenv("EXTRACT_FIGURES", "true")
    monkeypatch.setattr(ingest_mod, "_MAX_FIGURES", 2)

    img_paths = []
    for i in range(5):
        p = tmp_path / f"fig{i}.png"
        p.write_bytes(b"PNG")
        img_paths.append(str(p))

    elements = [make_image(p, page=1) for p in img_paths]
    with patch("rag.ingest._caption_figure", return_value=("Some figure.", 0, 0)):
        docs, _, _ = _build_docs_from_elements(elements, "doc1", "test.pdf", False, "")

    assert len(docs) == 2


# _caption_figure

def test_caption_figure_returns_empty_for_missing_file():
    from rag.ingest import _caption_figure
    result = _caption_figure("/nonexistent/path/fig.png")
    assert result == ("", 0, 0)


def test_caption_figure_calls_gemini(tmp_path):
    from rag.ingest import _caption_figure

    img = tmp_path / "fig.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content="A trend line showing model loss.")
    with patch("rag.llm.get_llm", return_value=mock_llm):
        result = _caption_figure(str(img))

    assert result[0] == "A trend line showing model loss."


def test_caption_figure_returns_empty_on_api_error(tmp_path):
    from rag.ingest import _caption_figure

    img = tmp_path / "fig.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = RuntimeError("API error")
    with patch("rag.llm.get_llm", return_value=mock_llm):
        result = _caption_figure(str(img))

    assert result == ("", 0, 0)


# index_document integration

def test_index_document_normal_path(tmp_path, monkeypatch):
    from rag import ingest as ingest_mod

    monkeypatch.setenv("CONTEXTUAL_RETRIEVAL", "false")
    monkeypatch.setenv("EXTRACT_FIGURES", "false")
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

    _dummy_pdf(tmp_path)
    doc_id = "test123"

    elements = [
        make_narrative(SAMPLE_NARRATIVE * 3, page=1),
        make_table("val", SAMPLE_HTML_TABLE, page=2),
    ]

    with patch("rag.ingest.extract_elements", return_value=elements), \
         patch("rag.ingest.clear_document"), \
         patch("rag.ingest.add_documents") as mock_add:
        count, collection, page_count, _, _ = ingest_mod.index_document(doc_id)

    assert count > 0
    mock_add.assert_called_once()
    assert collection == "pgvector"
    assert page_count == 2  # max page number across elements (1 and 2)


def test_index_document_raises_when_pdf_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    from rag.ingest import index_document
    with pytest.raises(FileNotFoundError):
        index_document("ghost_doc")


def test_index_document_zero_page_count_on_empty_elements(tmp_path, monkeypatch):
    from rag import ingest as ingest_mod

    monkeypatch.setenv("CONTEXTUAL_RETRIEVAL", "false")
    monkeypatch.setenv("EXTRACT_FIGURES", "false")
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

    _dummy_pdf(tmp_path)

    with patch("rag.ingest.extract_elements", return_value=[]), \
         patch("rag.ingest.clear_document"):
        count, collection, page_count, _, _ = ingest_mod.index_document("test123")

    assert count == 0
    assert page_count == 0


def test_index_document_progress_callback(tmp_path, monkeypatch):
    from rag import ingest as ingest_mod

    monkeypatch.setenv("CONTEXTUAL_RETRIEVAL", "false")
    monkeypatch.setenv("EXTRACT_FIGURES", "false")
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

    _dummy_pdf(tmp_path)
    messages: list[str] = []

    elements = [make_narrative(SAMPLE_NARRATIVE, page=1)]

    with patch("rag.ingest.extract_elements", return_value=elements), \
         patch("rag.ingest.clear_document"), \
         patch("rag.ingest.add_documents"):
        ingest_mod.index_document("test123", progress=messages.append)

    assert any("Parsing" in m for m in messages)
