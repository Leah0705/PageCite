from __future__ import annotations

import hashlib
import os

import psycopg2

from rag.store import _postgres_dsn


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def validate_api_key(key: str) -> str | None:
    """Return user_id for a valid key and refresh last_used_at, or None."""
    if not key:
        return None
    key_hash = hash_key(key)
    try:
        with psycopg2.connect(_postgres_dsn()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT user_id FROM api_keys WHERE key_hash = %s",
                    (key_hash,),
                )
                row = cur.fetchone()
                if row:
                    cur.execute(
                        "UPDATE api_keys SET last_used_at = now() WHERE key_hash = %s",
                        (key_hash,),
                    )
                    conn.commit()
                    return row[0]
    except Exception:
        pass
    return None


def key_from_env() -> str | None:
    return os.environ.get("PAGECITE_API_KEY")
