from __future__ import annotations

import contextvars

# Per-request bucket set before the graph runs, read by each chain node
_current_var: contextvars.ContextVar[dict[str, int] | None] = contextvars.ContextVar(
    "_token_usage", default=None
)


def capture_from_message(msg: object) -> object:
    """Inserted as a RunnableLambda after every LLM call.

    Reads usage_metadata from the AIMessage, adds to the active bucket, and
    returns the message unchanged so the rest of the chain works normally.
    """
    bucket = _current_var.get()
    if bucket is not None:
        meta = getattr(msg, "usage_metadata", None) or {}
        if isinstance(meta, dict):
            bucket["in"] += meta.get("input_tokens", 0)
            bucket["out"] += meta.get("output_tokens", 0)
    return msg


class TokenUsageCallback:
    """Tracks tokens for a single agent run via a shared contextvar bucket."""

    def __init__(self) -> None:
        self._bucket: dict[str, int] = {"in": 0, "out": 0}
        self._token: contextvars.Token | None = None

    def activate(self) -> None:
        """Install this callback's bucket as the active context."""
        self._token = _current_var.set(self._bucket)

    def deactivate(self) -> None:
        if self._token is not None:
            _current_var.reset(self._token)
            self._token = None

    @property
    def tokens_in(self) -> int:
        return self._bucket["in"]

    @property
    def tokens_out(self) -> int:
        return self._bucket["out"]

    @property
    def total_tokens(self) -> int:
        return self._bucket["in"] + self._bucket["out"]
