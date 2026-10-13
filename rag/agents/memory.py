"""Conversation memory shared by every API worker.

History lives in Redis, so a follow-up question keeps its context across worker
processes and restarts. Each session keeps its last MAX_MESSAGES messages and
expires TTL_SECONDS after its last update.

Keys include the document id. The API only runs the agent after checking that the
caller owns that document, so guessing another user's session id does not expose
their history. The stored text is what the model saw: questions after PII masking.

If Redis is unavailable, reads return an empty history and writes are skipped;
the question is still answered, only without earlier turns.
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import Sequence

import redis as redis_lib
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import BaseMessage, message_to_dict, messages_from_dict

logger = logging.getLogger(__name__)

MAX_MESSAGES = 20
TTL_SECONDS = int(os.getenv("CHAT_MEMORY_TTL_SECONDS", str(7 * 24 * 3600)))
_KEY_PREFIX = "chat:"


@lru_cache(maxsize=1)
def _redis() -> redis_lib.Redis:
    return redis_lib.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True
    )


def _key(session_id: str, doc_id: str) -> str:
    return f"{_KEY_PREFIX}{doc_id}:{session_id}"


class RedisChatHistory(BaseChatMessageHistory):
    """A Redis list of JSON-encoded LangChain messages, oldest first."""

    def __init__(self, key: str) -> None:
        self.key = key

    @property
    def messages(self) -> list[BaseMessage]:  # type: ignore[override]
        try:
            raw = _redis().lrange(self.key, 0, -1)
        except Exception as exc:
            logger.warning("Chat memory read failed, continuing without history: %s", exc)
            return []
        return messages_from_dict([json.loads(item) for item in raw])

    def add_messages(self, messages: Sequence[BaseMessage]) -> None:
        if not messages:
            return
        try:
            pipe = _redis().pipeline()
            pipe.rpush(self.key, *[json.dumps(message_to_dict(m)) for m in messages])
            pipe.ltrim(self.key, -MAX_MESSAGES, -1)
            pipe.expire(self.key, TTL_SECONDS)
            pipe.execute()
        except Exception as exc:
            logger.warning("Chat memory write failed: %s", exc)

    def clear(self) -> None:
        try:
            _redis().delete(self.key)
        except Exception as exc:
            logger.warning("Chat memory clear failed: %s", exc)


def get_memory(session_id: str, doc_id: str) -> RedisChatHistory:
    """Return the history of one chat session on one document."""
    return RedisChatHistory(_key(session_id, doc_id))


def clear_memory(session_id: str, doc_id: str) -> None:
    get_memory(session_id, doc_id).clear()


def clear_document_memory(doc_id: str) -> int:
    """Delete every chat history of a document (used when the document is deleted)."""
    try:
        client = _redis()
        keys = list(client.scan_iter(match=f"{_KEY_PREFIX}{doc_id}:*", count=500))
        return client.delete(*keys) if keys else 0
    except Exception as exc:
        logger.warning("Chat memory cleanup failed: %s", exc)
        return 0
