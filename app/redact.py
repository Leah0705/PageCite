from __future__ import annotations

import logging
import os
from functools import lru_cache

logger = logging.getLogger(__name__)

PII_REDACTION = os.getenv("PII_REDACTION", "true").lower() == "true"

_ENTITIES = ["EMAIL_ADDRESS", "PHONE_NUMBER", "US_SSN", "CREDIT_CARD"]

_LABEL_MAP = {
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER":  "PHONE",
    "US_SSN":        "SSN",
    "CREDIT_CARD":   "CREDIT_CARD",
}


@lru_cache(maxsize=1)
def _get_analyzer():
    from presidio_analyzer import AnalyzerEngine
    return AnalyzerEngine()


@lru_cache(maxsize=1)
def _get_anonymizer():
    from presidio_anonymizer import AnonymizerEngine
    return AnonymizerEngine()


def redact(text: str) -> tuple[str, dict[str, str]]:
    """Replace PII in *text* with placeholders like <EMAIL_1>.

    Returns (redacted_text, mapping) where mapping maps placeholder → original.
    When PII_REDACTION is disabled, returns (text, {}) unchanged.
    Falls back to no-op if presidio is not installed.
    """
    if not PII_REDACTION or not text.strip():
        return text, {}

    try:
        analyzer = _get_analyzer()
    except Exception as exc:
        logger.warning("PII redaction unavailable (presidio not installed?): %s", exc)
        return text, {}

    results = analyzer.analyze(text=text, entities=_ENTITIES, language="en")

    if not results:
        return text, {}

    logger.info("PII redaction: found %d entity/entities in query", len(results))
    # Sort by position descending so we can replace without offset drift
    results_sorted = sorted(results, key=lambda r: r.start, reverse=True)

    mapping: dict[str, str] = {}
    counters: dict[str, int] = {}
    redacted = text

    for result in results_sorted:
        label = _LABEL_MAP.get(result.entity_type, result.entity_type)
        counters[label] = counters.get(label, 0) + 1
        placeholder = f"<{label}_{counters[label]}>"
        original = redacted[result.start:result.end]
        mapping[placeholder] = original
        redacted = redacted[: result.start] + placeholder + redacted[result.end :]

    return redacted, mapping


def restore(text: str, mapping: dict[str, str]) -> str:
    """Replace placeholders back with their original values."""
    if not mapping:
        return text
    for placeholder, original in mapping.items():
        text = text.replace(placeholder, original)
    return text
