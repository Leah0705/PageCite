from __future__ import annotations

import json
import os
import uuid
from typing import Callable, List

import psycopg2
import psycopg2.extras
from pgvector.psycopg2 import register_vector
from langchain_core.documents import Document

from rag.llm import get_embeddings

_EMBED_BATCH = 96  # chunks per embedding batch


def _postgres_dsn() -> str:
    url = os.getenv("DATABASE_URL", "postgresql://pagecite:pagecite@localhost:5432/pagecite")
    # Strip asyncpg driver prefix if present (this module uses sync psycopg2)
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _conn() -> psycopg2.extensions.connection:
    conn = psycopg2.connect(_postgres_dsn())
    register_vector(conn)
    psycopg2.extras.register_uuid(conn)
    return conn


def clear_document(doc_id: str) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM chunks WHERE doc_id = %s::uuid", (doc_id,))
        conn.commit()


def add_documents(
    doc_id: str,
    documents: List[Document],
    on_batch: Callable[[int, int], None] | None = None,
) -> None:
    if not documents:
        return

    embedder = get_embeddings()
    texts = [doc.page_content for doc in documents]

    total_batches = max(1, (len(texts) + _EMBED_BATCH - 1) // _EMBED_BATCH)
    all_embeddings: list[list[float]] = []
    for batch_num, i in enumerate(range(0, len(texts), _EMBED_BATCH), 1):
        all_embeddings.extend(embedder.embed_documents(texts[i : i + _EMBED_BATCH]))
        if on_batch:
            on_batch(batch_num, total_batches)

    rows = [
        (
            uuid.uuid4(),
            doc_id,
            doc.metadata.get("ref", f"{doc_id}_c{idx}"),
            doc.page_content,
            json.dumps(doc.metadata),
            embedding,
        )
        for idx, (doc, embedding) in enumerate(zip(documents, all_embeddings))
    ]

    with _conn() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO chunks (id, doc_id, ref, content, metadata, embedding)
                VALUES %s
                ON CONFLICT (ref) DO UPDATE
                    SET content = EXCLUDED.content,
                        metadata = EXCLUDED.metadata,
                        embedding = EXCLUDED.embedding
                """,
                rows,
                template="(%s, %s::uuid, %s, %s, %s::jsonb, %s)",
            )
        conn.commit()


def similarity_search(doc_id: str, query: str, k: int = 5) -> List[Document]:
    embedding = get_embeddings().embed_query(query)
    return similarity_search_by_vector(doc_id, embedding, k=k)


def similarity_search_by_vector(doc_id: str, embedding: List[float], k: int = 5) -> List[Document]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT content, metadata
                FROM chunks
                WHERE doc_id = %s::uuid
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (doc_id, embedding, k),
            )
            rows = cur.fetchall()

    return [Document(page_content=r[0], metadata=r[1]) for r in rows]
