from __future__ import annotations

import logging
import os
from typing import List

import psycopg2
import psycopg2.extras
from langchain_core.documents import Document

from rag.store import _postgres_dsn, similarity_search, similarity_search_by_vector

logger = logging.getLogger(__name__)

RRF_K = 60


def _rrf_score(rank: int) -> float:
    return 1.0 / (RRF_K + rank + 1)


def _rrf_merge(list_a: List[Document], list_b: List[Document], k: int) -> List[Document]:
    rrf_scores: dict[str, float] = {}
    for rank, doc in enumerate(list_a):
        ref = doc.metadata["ref"]
        rrf_scores[ref] = rrf_scores.get(ref, 0.0) + _rrf_score(rank)
    for rank, doc in enumerate(list_b):
        ref = doc.metadata["ref"]
        rrf_scores[ref] = rrf_scores.get(ref, 0.0) + _rrf_score(rank)

    all_docs: dict[str, Document] = {d.metadata["ref"]: d for d in list_a + list_b}
    sorted_refs = sorted(rrf_scores, key=lambda r: rrf_scores[r], reverse=True)
    return [all_docs[ref] for ref in sorted_refs[:k]]


def sparse_search(doc_id: str, query: str, k: int = 10) -> List[Document]:
    """PostgreSQL ts_rank full-text search (BM25 replacement)."""
    dsn = _postgres_dsn()
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT content, metadata,
                       ts_rank(tsv, plainto_tsquery('english', %s)) AS rank
                FROM chunks
                WHERE doc_id = %s::uuid
                  AND tsv @@ plainto_tsquery('english', %s)
                ORDER BY rank DESC
                LIMIT %s
                """,
                (query, doc_id, query, k),
            )
            rows = cur.fetchall()

    return [Document(page_content=r[0], metadata=r[1]) for r in rows]


def hybrid_search(doc_id: str, query: str, k: int = 10) -> List[Document]:
    """Dense vector search + sparse ts_rank fused with RRF."""
    dense = similarity_search(doc_id, query, k=k)
    sparse = sparse_search(doc_id, query, k=k)

    if not sparse:
        return dense
    if not dense:
        return sparse

    return _rrf_merge(dense, sparse, k=k)


def _hyde_dense_search(doc_id: str, query: str, k: int) -> List[Document]:
    from rag.llm import get_embeddings, get_llm

    hypothetical = get_llm().invoke(
        f"Write a hypothetical 3-sentence passage that directly answers: {query}"
    ).content.strip()
    logger.info("[HyDE] hypothetical: %r", hypothetical[:120])
    return similarity_search_by_vector(doc_id, get_embeddings().embed_query(hypothetical), k=k)


def retrieve_with_hyde(doc_id: str, query: str, top_k: int = 6) -> tuple[List[Document], bool]:
    """Hybrid search + reranking. Triggers HyDE when top reranker score < HYDE_THRESHOLD."""
    from rag.chains.rerank import rerank_with_score

    hyde_threshold = float(os.getenv("HYDE_THRESHOLD", "0.3"))
    candidate_k = top_k * 4

    candidates = hybrid_search(doc_id, query, k=candidate_k)
    if not candidates:
        return [], False

    docs, top_score = rerank_with_score(query, candidates, top_k=top_k)

    if top_score < hyde_threshold:
        logger.info("[HyDE] score=%.3f < %.3f, triggering for: %r", top_score, hyde_threshold, query)
        hyde_candidates = _hyde_dense_search(doc_id, query, k=candidate_k)
        merged = _rrf_merge(candidates, hyde_candidates, k=candidate_k)
        docs, _ = rerank_with_score(query, merged, top_k=top_k)
        return docs, True

    return docs, False
