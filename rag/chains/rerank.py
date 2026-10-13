from __future__ import annotations

import os
from functools import lru_cache
from typing import List

from langchain_core.documents import Document
from sentence_transformers import CrossEncoder

# English MS MARCO reranker by default; .env.example has a multilingual preset.
# HYDE_THRESHOLD is compared with this model's raw scores, so re-check it after a change.
_MODEL = os.getenv("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")


@lru_cache(maxsize=1)
def _get_cross_encoder() -> CrossEncoder:
    return CrossEncoder(_MODEL)


def rerank(query: str, documents: List[Document], top_k: int = 5) -> List[Document]:
    """
    Score each document against the query using a cross-encoder and return
    the top_k results sorted by relevance score descending.
    """
    if not documents:
        return []

    cross_encoder = _get_cross_encoder()
    pairs = [[query, doc.page_content] for doc in documents]
    scores = cross_encoder.predict(pairs)

    scored = sorted(zip(scores, documents), key=lambda x: x[0], reverse=True)
    return [doc for _, doc in scored[:top_k]]


def rerank_with_score(
    query: str, documents: List[Document], top_k: int = 5
) -> tuple[List[Document], float]:
    """Rerank and return (top_k docs, top reranker score). Score is 0.0 if no documents."""
    if not documents:
        return [], 0.0

    cross_encoder = _get_cross_encoder()
    pairs = [[query, doc.page_content] for doc in documents]
    scores = cross_encoder.predict(pairs)

    scored = sorted(zip(scores, documents), key=lambda x: x[0], reverse=True)
    top_docs = [doc for _, doc in scored[:top_k]]
    top_score = float(scored[0][0])
    return top_docs, top_score
