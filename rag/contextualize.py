from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path

from langchain_google_genai import ChatGoogleGenerativeAI

_PROMPT = (
    "<document>{doc}</document>\n"
    "<chunk>{chunk}</chunk>\n"
    "Give a short, one-sentence context to situate this chunk within the overall "
    "document for search retrieval. Write it in the language of the document. "
    "Answer with only the sentence."
)

_DB_PATH = Path.home() / ".pagecite" / "context_cache.db"


def _get_conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS context_cache (
            doc_hash  TEXT NOT NULL,
            chunk_hash TEXT NOT NULL,
            context   TEXT NOT NULL,
            PRIMARY KEY (doc_hash, chunk_hash)
        )
        """
    )
    conn.commit()
    return conn


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _get_llm() -> ChatGoogleGenerativeAI:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY is not set.")
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=api_key,
        temperature=0,
    )


def _parse_usage(response: object) -> tuple[int, int]:
    usage = getattr(response, "usage_metadata", None) or {}
    if isinstance(usage, dict):
        return int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
    return int(getattr(usage, "input_tokens", 0) or 0), int(getattr(usage, "output_tokens", 0) or 0)


def contextualize_chunk(full_doc: str, chunk: str) -> tuple[str, int, int]:
    """Return (context, tokens_in, tokens_out). Cache hits return 0 tokens."""
    doc_hash = _sha256(full_doc)
    chunk_hash = _sha256(chunk)

    with _get_conn() as conn:
        row = conn.execute(
            "SELECT context FROM context_cache WHERE doc_hash=? AND chunk_hash=?",
            (doc_hash, chunk_hash),
        ).fetchone()
        if row:
            return row[0], 0, 0

        prompt = _PROMPT.format(doc=full_doc, chunk=chunk)
        response = _get_llm().invoke(prompt)
        context = response.content.strip()
        tin, tout = _parse_usage(response)

        conn.execute(
            "INSERT OR REPLACE INTO context_cache (doc_hash, chunk_hash, context) VALUES (?,?,?)",
            (doc_hash, chunk_hash, context),
        )

    return context, tin, tout
