from __future__ import annotations

from contextvars import ContextVar
from typing import Any

import psycopg2
import psycopg2.extras
from mcp.server.fastmcp import FastMCP

from mcp_server.auth import key_from_env, validate_api_key
from rag.chains.retrieval import hybrid_search
from rag.store import _postgres_dsn

# Per-request user_id: set by HTTP middleware for SSE, resolved lazily from env for stdio.
_user_id_var: ContextVar[str] = ContextVar("mcp_user_id")

mcp = FastMCP(
    "pagecite",
    instructions=(
        "PageCite gives you semantic search and retrieval over the user's "
        "knowledge base of work documents, such as policies, manuals, and reports. "
        "Use search_documents to find relevant passages, "
        "list_documents to enumerate the library, and get_document for metadata."
    ),
)


def _require_user() -> str:
    try:
        return _user_id_var.get()
    except LookupError:
        # stdio transport: resolve once from env key
        raw = key_from_env() or ""
        user_id = validate_api_key(raw)
        if not user_id:
            raise RuntimeError(
                "PAGECITE_API_KEY is missing or invalid. "
                "Set it in the MCP server environment."
            )
        _user_id_var.set(user_id)
        return user_id


def _user_doc_ids(user_id: str) -> list[str]:
    with psycopg2.connect(_postgres_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id::text FROM documents WHERE user_id = %s AND status = 'indexed'",
                (user_id,),
            )
            return [r[0] for r in cur.fetchall()]


@mcp.tool()
def search_documents(
    query: str,
    top_k: int = 5,
    doc_id: str | None = None,
) -> list[dict[str, Any]]:
    """Search documents using hybrid retrieval (dense vector + Postgres full-text + RRF).

    Args:
        query:  Natural-language search query.
        top_k:  Maximum results to return (default 5, max 20).
        doc_id: Restrict search to a specific document UUID. Omit to search all.

    Returns:
        List of {content, source, page, score, doc_id}.
    """
    user_id = _require_user()
    top_k = max(1, min(top_k, 20))
    owned_doc_ids = _user_doc_ids(user_id)
    if doc_id:
        doc_id = doc_id.strip().lower()  # Postgres renders UUIDs as lowercase text
    if doc_id and doc_id not in owned_doc_ids:
        raise ValueError(f"Document {doc_id!r} not found or access denied")
    doc_ids = [doc_id] if doc_id else owned_doc_ids

    results: list[dict[str, Any]] = []
    for did in doc_ids:
        for rank, doc in enumerate(hybrid_search(did, query, k=top_k)):
            results.append(
                {
                    "content": doc.page_content,
                    "source": doc.metadata.get("filename", did),
                    "page": doc.metadata.get("page"),
                    "score": round(1.0 / (rank + 1), 4),
                    "doc_id": did,
                }
            )

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


@mcp.tool()
def list_documents() -> list[dict[str, Any]]:
    """List all indexed documents in the user's library.

    Returns:
        List of {doc_id, filename, page_count, created_at}.
    """
    user_id = _require_user()
    with psycopg2.connect(_postgres_dsn()) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id::text AS doc_id, filename, page_count, created_at::text
                FROM documents
                WHERE user_id = %s AND status = 'indexed'
                ORDER BY created_at DESC
                """,
                (user_id,),
            )
            return [dict(r) for r in cur.fetchall()]


@mcp.tool()
def get_document(doc_id: str) -> dict[str, Any]:
    """Get metadata and a content preview for a document.

    Args:
        doc_id: Document UUID.

    Returns:
        {doc_id, filename, page_count, status, created_at, first_500_chars}.
    """
    user_id = _require_user()
    with psycopg2.connect(_postgres_dsn()) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT d.id::text AS doc_id, d.filename, d.page_count,
                       d.status, d.created_at::text,
                       (SELECT content FROM chunks
                        WHERE doc_id = d.id ORDER BY id LIMIT 1) AS preview
                FROM documents d
                WHERE d.id = %s::uuid AND d.user_id = %s
                """,
                (doc_id, user_id),
            )
            row = cur.fetchone()

    if not row:
        return {"error": f"Document {doc_id!r} not found or access denied"}

    result = dict(row)
    preview = result.pop("preview", None) or ""
    result["first_500_chars"] = preview[:500]
    return result
