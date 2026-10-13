from __future__ import annotations

# USD per 1M tokens as (input, output), Gemini API Standard paid tier.
# gemini-2.5-flash and gemini-2.5-pro were checked against
# https://ai.google.dev/gemini-api/docs/pricing on 2026-10-13 (gemini-2.5-pro at the
# <=200k-token prompt tier). The preview and 2.0 rows are legacy entries that page
# no longer lists. Output tokens include thinking tokens: langchain-google-genai adds
# thoughts_token_count to usage_metadata["output_tokens"], and Google bills them at
# the output rate.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash":          (0.30,  2.50),
    "gemini-2.5-flash-preview":  (0.15,  0.60),
    "gemini-2.5-pro":            (1.25,  10.00),
    "gemini-2.0-flash":          (0.10,  0.40),
    "sentence-transformers/all-mpnet-base-v2": (0.0, 0.0),
}

_DEFAULT = MODEL_PRICING["gemini-2.5-flash"]


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return cost in USD for a single LLM call."""
    input_rate, output_rate = MODEL_PRICING.get(model, _DEFAULT)
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
