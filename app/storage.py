from __future__ import annotations

import os
import uuid
from pathlib import Path


def new_doc_id() -> str:
    return str(uuid.uuid4())


def get_storage_root() -> Path:
    return Path(os.getenv("STORAGE_DIR", "storage")).resolve()


def pdf_path(doc_id: str) -> Path:
    root = get_storage_root() / "pdfs"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{doc_id}.pdf"


def save_pdf(path: Path, content: bytes) -> None:
    path.write_bytes(content)


def delete_pdf(doc_id: str) -> None:
    path = pdf_path(doc_id)
    if path.exists():
        path.unlink()


def docx_path(doc_id: str) -> Path:
    root = get_storage_root() / "docxs"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{doc_id}.docx"


def save_docx(path: Path, content: bytes) -> None:
    path.write_bytes(content)


def delete_docx(doc_id: str) -> None:
    path = docx_path(doc_id)
    if path.exists():
        path.unlink()
