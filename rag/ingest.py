from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, List, Tuple

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage
from langchain_text_splitters import RecursiveCharacterTextSplitter
from unstructured.documents.elements import Image as UnstructuredImage
from unstructured.documents.elements import Table
from unstructured.partition.pdf import partition_pdf
import unstructured_pytesseract

_tesseract_cmd = os.environ.get("TESSERACT_CMD")
if _tesseract_cmd:
    unstructured_pytesseract.pytesseract.tesseract_cmd = _tesseract_cmd


def _tesseract_available() -> bool:
    import shutil
    cmd = _tesseract_cmd or "tesseract"
    return shutil.which(cmd) is not None

from rag.contextualize import contextualize_chunk
from rag.store import add_documents, clear_document

DEFAULT_COLLECTION = "pgvector"


# The CJK sentence marks only apply to text that contains them, so English
# documents are split exactly as before.
_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=800,
    chunk_overlap=100,
    separators=["\n\n", "\n", "。", "！", "？", "；", ". ", " ", ""],
)

_MAX_FIGURES = 30

_FIGURE_PROMPT = (
    "Describe this figure from a document in 2-3 sentences for retrieval purposes. "
    "Include visible numbers, labels, or trends."
)

_IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def get_storage_dir() -> Path:
    return Path(os.getenv("STORAGE_DIR", "storage"))


def get_pdf_path(doc_id: str) -> Path:
    return get_storage_dir() / "pdfs" / f"{doc_id}.pdf"


def get_docx_path(doc_id: str) -> Path:
    return get_storage_dir() / "docxs" / f"{doc_id}.docx"


def get_docx_pdf_path(doc_id: str) -> Path:
    """Path for the PDF produced by converting a DOCX file."""
    return get_storage_dir() / "docxs" / f"{doc_id}.pdf"


# Control characters (except tab and newline), zero-width spaces and the BOM.
_INVISIBLE_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b\ufeff]")
# Full-width marks that Chinese text uses as ordinary punctuation: ！（），：；？
_CJK_PUNCT = re.compile(r"[\uff01\uff08\uff09\uff0c\uff1a\uff1b\uff1f]")


def _nfkc_keep_cjk_punct(text: str) -> str:
    """NFKC everywhere except the full-width punctuation in _CJK_PUNCT."""
    parts: list[str] = []
    last = 0
    for match in _CJK_PUNCT.finditer(text):
        parts.append(unicodedata.normalize("NFKC", text[last:match.start()]))
        parts.append(match.group())
        last = match.end()
    parts.append(unicodedata.normalize("NFKC", text[last:]))
    return "".join(parts)


def _clean_text(text: str) -> str:
    """Normalise extracted text without dropping non-English characters.

    NFKC folds ligatures (ﬁ -> fi) and full-width letters and digits (Ｑ３ -> Q3)
    while Chinese characters, accented Latin and other scripts stay intact.
    """
    text = _nfkc_keep_cjk_punct(text)
    text = _INVISIBLE_CHARS.sub(" ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_figures_enabled() -> bool:
    return os.getenv("EXTRACT_FIGURES", "").lower() in ("1", "true", "yes")


def convert_docx_to_pdf(doc_id: str) -> Path:
    """Convert a DOCX file to PDF using LibreOffice.

    The converted PDF is stored alongside the original DOCX in the docxs folder.
    Returns the path of the generated PDF.
    """
    docx_file = get_docx_path(doc_id)
    if not docx_file.exists():
        raise FileNotFoundError(f"DOCX not found: {docx_file}")

    dest = get_docx_pdf_path(doc_id)
    dest.parent.mkdir(parents=True, exist_ok=True)

    lo_bin = shutil.which("libreoffice") or shutil.which("soffice")
    if not lo_bin:
        raise RuntimeError("LibreOffice is not installed or not on PATH")

    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            [lo_bin, "--headless", "--convert-to", "pdf", "--outdir", tmp, str(docx_file)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120,
        )
        generated = Path(tmp) / f"{docx_file.stem}.pdf"
        if not generated.exists():
            raise RuntimeError(f"LibreOffice did not produce a PDF for {docx_file.name}")
        shutil.move(str(generated), str(dest))

    return dest


def _use_contextual_retrieval() -> bool:
    return os.getenv("CONTEXTUAL_RETRIEVAL", "").lower() in ("1", "true", "yes")


def _html_to_markdown(html: str) -> str:
    try:
        import markdownify
        return markdownify.markdownify(html, heading_style="ATX").strip()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html).strip()


def _parse_llm_usage(response: object) -> tuple[int, int]:
    usage = getattr(response, "usage_metadata", None) or {}
    if isinstance(usage, dict):
        return int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
    return int(getattr(usage, "input_tokens", 0) or 0), int(getattr(usage, "output_tokens", 0) or 0)


def _caption_figure(image_path: str) -> tuple[str, int, int]:
    from rag.llm import get_llm

    path = Path(image_path)
    if not path.exists():
        return "", 0, 0

    mime_type = _IMAGE_MIME.get(path.suffix.lower(), "image/png")
    with open(path, "rb") as fh:
        image_b64 = base64.b64encode(fh.read()).decode("utf-8")

    message = HumanMessage(
        content=[
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{image_b64}"},
            },
            {"type": "text", "text": _FIGURE_PROMPT},
        ]
    )
    try:
        resp = get_llm().invoke([message])
        tin, tout = _parse_llm_usage(resp)
        return resp.content.strip(), tin, tout
    except Exception:
        return "", 0, 0


def extract_elements(pdf_path: Path, doc_id: str) -> list:
    if not _tesseract_available():
        cmd = _tesseract_cmd or "tesseract"
        raise RuntimeError(
            f"Tesseract not found at '{cmd}'. "
            "Install it (macOS: brew install tesseract, Ubuntu: apt install tesseract-ocr) "
            "and set TESSERACT_CMD in your .env if it is not on PATH."
        )
    kwargs: dict = {
        "filename": str(pdf_path),
        "infer_table_structure": True,
        "strategy": "hi_res",
    }
    if _extract_figures_enabled():
        figures_dir = get_storage_dir() / "figures" / doc_id
        figures_dir.mkdir(parents=True, exist_ok=True)
        kwargs["extract_images_in_pdf"] = True
        kwargs["extract_image_block_output_dir"] = str(figures_dir)

    return partition_pdf(**kwargs)


def extract_docx_elements(docx_file: Path, doc_id: str = "") -> list:
    from unstructured.partition.docx import partition_docx
    kwargs: dict = {"filename": str(docx_file), "infer_table_structure": True}
    if _extract_figures_enabled() and doc_id:
        figures_dir = get_storage_dir() / "figures" / doc_id
        figures_dir.mkdir(parents=True, exist_ok=True)
        kwargs["extract_image_block_output_dir"] = str(figures_dir)
        kwargs["extract_image_block_types"] = ["Image"]
    return partition_docx(**kwargs)


_CONTEXTUALIZE_WORKERS = int(os.getenv("CONTEXTUALIZE_WORKERS", "8"))

_HEADING_CATEGORIES = {"Title", "Header"}


def _build_docs_from_elements(
    elements: list,
    doc_id: str,
    source_name: str,
    contextual: bool,
    full_doc_text: str,
    track_sections: bool = False,
    extra_meta: dict | None = None,
) -> tuple[List[Document], int, int]:
    """Convert parsed elements to Documents, parallelising contextualisation calls.

    Returns (docs, total_tokens_in, total_tokens_out).
    track_sections: when True (DOCX), maintain a heading breadcrumb.
    extra_meta: additional key/value pairs merged into every chunk's metadata.
    """

    raw: List[dict] = []
    chunk_id = 0
    figure_count = 0
    figure_tokens_in = 0
    figure_tokens_out = 0
    text_buf: List[Tuple[int, str]] = []
    current_page: int = -1
    section_path: List[str] = []  # only populated when track_sections=True

    def _flush_buf() -> None:
        nonlocal chunk_id
        if not text_buf:
            return
        page = text_buf[0][0]
        combined = "\n\n".join(t for _, t in text_buf)
        for c in _SPLITTER.split_text(combined):
            if not c.strip():
                continue
            entry: dict = {
                "content": c,
                "page": page,
                "chunk_id": chunk_id,
                "element_type": "text",
                "image_path": None,
            }
            if track_sections:
                entry["section"] = " > ".join(section_path) if section_path else ""
            raw.append(entry)
            chunk_id += 1
        text_buf.clear()

    for el in elements:
        page = el.metadata.page_number or 0
        category = getattr(el, "category", None) or type(el).__name__

        if track_sections and category in _HEADING_CATEGORIES and el.text:
            _flush_buf()
            current_page = page
            depth = getattr(el.metadata, "category_depth", 0) or 0
            section_path = section_path[:depth] + [el.text.strip()]
            # Also emit heading as a text chunk so it's searchable
            text_buf.append((page, _clean_text(el.text)))
            continue

        if isinstance(el, Table):
            _flush_buf()
            current_page = page
            html = getattr(el.metadata, "text_as_html", None) or ""
            md_text = _html_to_markdown(html) if html else _clean_text(el.text or "")
            if md_text.strip():
                entry = {
                    "content": md_text,
                    "page": page,
                    "chunk_id": chunk_id,
                    "element_type": "table",
                    "image_path": None,
                }
                if track_sections:
                    entry["section"] = " > ".join(section_path) if section_path else ""
                raw.append(entry)
                chunk_id += 1

        elif isinstance(el, UnstructuredImage):
            _flush_buf()
            current_page = page
            if not _extract_figures_enabled() or figure_count >= _MAX_FIGURES:
                continue
            image_path = (
                getattr(el.metadata, "image_path", None)
                or getattr(el.metadata, "filename", None)
            )
            if not image_path:
                continue
            caption, fig_tin, fig_tout = _caption_figure(str(image_path))
            if not caption:
                continue
            figure_tokens_in += fig_tin
            figure_tokens_out += fig_tout
            entry = {
                "content": caption,
                "page": page,
                "chunk_id": chunk_id,
                "element_type": "figure",
                "image_path": str(image_path),
            }
            if track_sections:
                entry["section"] = " > ".join(section_path) if section_path else ""
            raw.append(entry)
            chunk_id += 1
            figure_count += 1

        else:
            text = _clean_text(el.text or "")
            if not text:
                continue
            if page != current_page and text_buf:
                _flush_buf()
            current_page = page
            text_buf.append((page, text))

    _flush_buf()

    if not raw:
        return [], figure_tokens_in, figure_tokens_out

    ctx_tokens_in = 0
    ctx_tokens_out = 0
    if contextual:
        contexts: List[str] = [""] * len(raw)

        def _ctx(idx: int) -> Tuple[int, str, int, int]:
            ctx, tin, tout = contextualize_chunk(full_doc_text, raw[idx]["content"])
            return idx, ctx, tin, tout

        with ThreadPoolExecutor(max_workers=_CONTEXTUALIZE_WORKERS) as pool:
            futures = {pool.submit(_ctx, i): i for i in range(len(raw))}
            for fut in as_completed(futures):
                idx, ctx, tin, tout = fut.result()
                contexts[idx] = ctx
                ctx_tokens_in += tin
                ctx_tokens_out += tout
    else:
        contexts = [""] * len(raw)

    all_docs: List[Document] = []
    for item, ctx in zip(raw, contexts):
        c = item["content"]
        embed_text = f"{ctx} {c}" if ctx else c
        ref = (
            f"{doc_id}_p{item['page']}_fig{item['chunk_id']}"
            if item["element_type"] == "figure"
            else f"{doc_id}_p{item['page']}_c{item['chunk_id']}"
        )
        meta: dict = {
            "doc_id": doc_id,
            "ref": ref,
            "page": item["page"],
            "chunk_id": item["chunk_id"],
            "source": source_name,
            "element_type": item["element_type"],
            "original_content": c,
        }
        if item.get("image_path"):
            meta["image_path"] = item["image_path"]
        if track_sections and "section" in item:
            meta["section"] = item["section"]
        if extra_meta:
            meta.update(extra_meta)
        all_docs.append(Document(page_content=embed_text, metadata=meta))

    total_tin = figure_tokens_in + ctx_tokens_in
    total_tout = figure_tokens_out + ctx_tokens_out
    return all_docs, total_tin, total_tout


def index_document(
    doc_id: str,
    progress: Callable[[str], None] | None = None,
    on_pct: Callable[[int], None] | None = None,
) -> Tuple[int, str, int, int, int]:
    def emit(msg: str) -> None:
        if progress:
            progress(msg)

    def pct(n: int) -> None:
        if on_pct:
            on_pct(n)

    # Check the docx-converted PDF first, then fall back to the native PDF path.
    docx_pdf = get_docx_pdf_path(doc_id)
    pdf_path = docx_pdf if docx_pdf.exists() else get_pdf_path(doc_id)
    if not pdf_path.exists():
        raise FileNotFoundError(str(pdf_path))

    clear_document(doc_id)

    source_name = pdf_path.name
    contextual = _use_contextual_retrieval()

    emit("Parsing PDF with hi_res layout analysis…")
    elements = extract_elements(pdf_path, doc_id)
    page_count = max((el.metadata.page_number or 0) for el in elements) if elements else 0

    pct(70)
    emit(f"Parsed {len(elements)} elements. Building document chunks…")

    full_doc_text = (
        "\n\n".join(
            el.text
            for el in elements
            if not isinstance(el, UnstructuredImage) and el.text
        )
        if contextual
        else ""
    )
    all_docs, tokens_in, tokens_out = _build_docs_from_elements(
        elements, doc_id, source_name, contextual, full_doc_text
    )

    if not all_docs:
        return 0, DEFAULT_COLLECTION, page_count, tokens_in, tokens_out

    pct(80)
    emit(f"Built {len(all_docs)} chunks. Generating embeddings and storing in pgvector…")

    def _on_embed_batch(done: int, total: int) -> None:
        pct(80 + int((done / total) * 17))

    add_documents(doc_id, all_docs, on_batch=_on_embed_batch)
    return len(all_docs), DEFAULT_COLLECTION, page_count, tokens_in, tokens_out


def index_docx_document(
    doc_id: str,
    progress: Callable[[str], None] | None = None,
    on_pct: Callable[[int], None] | None = None,
) -> Tuple[int, str, int, int, int]:
    def emit(msg: str) -> None:
        if progress:
            progress(msg)

    def pct(n: int) -> None:
        if on_pct:
            on_pct(n)

    docx_file = get_docx_path(doc_id)
    if not docx_file.exists():
        raise FileNotFoundError(str(docx_file))

    clear_document(doc_id)

    source_name = docx_file.name
    contextual = _use_contextual_retrieval()

    emit("Parsing DOCX…")
    elements = extract_docx_elements(docx_file, doc_id)
    page_count = max((el.metadata.page_number or 0) for el in elements) if elements else 0

    pct(70)
    emit(f"Parsed {len(elements)} elements. Building document chunks…")

    full_doc_text = (
        "\n\n".join(el.text for el in elements if el.text)
        if contextual
        else ""
    )
    all_docs, tokens_in, tokens_out = _build_docs_from_elements(
        elements,
        doc_id,
        source_name,
        contextual,
        full_doc_text,
        track_sections=True,
    )

    if not all_docs:
        return 0, DEFAULT_COLLECTION, page_count, tokens_in, tokens_out

    pct(80)
    emit(f"Built {len(all_docs)} chunks. Generating embeddings and storing in pgvector…")

    def _on_embed_batch(done: int, total: int) -> None:
        pct(80 + int((done / total) * 17))

    add_documents(doc_id, all_docs, on_batch=_on_embed_batch)
    return len(all_docs), DEFAULT_COLLECTION, page_count, tokens_in, tokens_out


