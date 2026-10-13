from __future__ import annotations

import logging
import os
from functools import lru_cache

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_tavily_client():
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return None
    from tavily import TavilyClient

    return TavilyClient(api_key=api_key)


@tool
def web_search(query: str, max_results: int = 5) -> list[dict]:
    """Search the public web for up-to-date information not found in the document.

    Use this when the question needs current events, facts outside the document,
    or information you cannot find in the retrieved chunks.

    Args:
        query: The search query.
        max_results: Maximum number of results to return (default 5).

    Returns:
        A list of {"title", "url", "snippet"} dicts.
    """
    client = _get_tavily_client()
    if client is None:
        logger.warning("web_search called but TAVILY_API_KEY is not set, returning no results.")
        return []

    try:
        response = client.search(query, max_results=max_results)
    except Exception as e:
        logger.error(f"Tavily search failed: {e}")
        return []

    results = response.get("results", []) if isinstance(response, dict) else []
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("content", ""),
        }
        for r in results
    ]
