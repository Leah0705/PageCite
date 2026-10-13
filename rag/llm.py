from __future__ import annotations

import os
from functools import lru_cache

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_huggingface import HuggingFaceEmbeddings


@lru_cache(maxsize=1)
def get_llm() -> ChatGoogleGenerativeAI:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY environment variable is not set.")
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=api_key,
        temperature=0,
    )


# Embedding model and the input prefixes it was trained with. The default is the
# English model the stored evaluation results were produced with; .env.example has a
# multilingual preset for Chinese and other languages. The chunks.embedding column
# and the Redis cache index hold EMBEDDING_DIM-dimensional vectors, and vectors from
# different models are not comparable, so reindex every document after a change.
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-mpnet-base-v2")
EMBEDDING_QUERY_PREFIX = os.getenv("EMBEDDING_QUERY_PREFIX", "")
EMBEDDING_PASSAGE_PREFIX = os.getenv("EMBEDDING_PASSAGE_PREFIX", "")
EMBEDDING_DIM = 768


@lru_cache(maxsize=1)
def get_embeddings() -> HuggingFaceEmbeddings:
    passage_kwargs: dict = {"normalize_embeddings": True}
    query_kwargs: dict = {"normalize_embeddings": True}
    if EMBEDDING_PASSAGE_PREFIX:
        passage_kwargs["prompt"] = EMBEDDING_PASSAGE_PREFIX
    if EMBEDDING_QUERY_PREFIX:
        query_kwargs["prompt"] = EMBEDDING_QUERY_PREFIX
    embeddings = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={"device": "cpu"},
        encode_kwargs=passage_kwargs,
        query_encode_kwargs=query_kwargs,
    )
    dim = len(embeddings.embed_query("dimension check"))
    if dim != EMBEDDING_DIM:
        raise RuntimeError(
            f"EMBEDDING_MODEL {EMBEDDING_MODEL!r} returns {dim}-d vectors, but the "
            f"database schema stores {EMBEDDING_DIM}-d vectors."
        )
    return embeddings
