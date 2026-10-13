from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_calculator_evaluates_basic_expression():
    from rag.tools.calculator import calculator

    assert calculator.invoke({"expression": "2 + 2"}) == "4"


def test_calculator_evaluates_complex_expression():
    from rag.tools.calculator import calculator

    assert calculator.invoke({"expression": "12 * (7 + 3) / 2"}) == "60.0"


def test_calculator_rejects_unsafe_expression():
    from rag.tools.calculator import calculator

    result = calculator.invoke({"expression": "__import__('os').system('echo pwned')"})
    assert result.startswith("Error:")


def test_calculator_rejects_undefined_names():
    from rag.tools.calculator import calculator

    result = calculator.invoke({"expression": "undefined_variable + 1"})
    assert result.startswith("Error:")


def test_calculator_handles_division_by_zero():
    from rag.tools.calculator import calculator

    result = calculator.invoke({"expression": "1 / 0"})
    assert result.startswith("Error:")


def test_web_search_returns_empty_without_api_key(monkeypatch):
    import rag.tools.web_search as web_search_mod

    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    web_search_mod._get_tavily_client.cache_clear()

    result = web_search_mod.web_search.invoke({"query": "latest AI news"})
    assert result == []
    web_search_mod._get_tavily_client.cache_clear()


def test_web_search_returns_parsed_results():
    import rag.tools.web_search as web_search_mod

    fake_client = MagicMock()
    fake_client.search.return_value = {
        "results": [
            {"title": "Result A", "url": "https://a.example.com", "content": "snippet A"},
            {"title": "Result B", "url": "https://b.example.com", "content": "snippet B"},
        ]
    }

    with patch.object(web_search_mod, "_get_tavily_client", return_value=fake_client):
        result = web_search_mod.web_search.invoke({"query": "latest AI news", "max_results": 2})

    assert result == [
        {"title": "Result A", "url": "https://a.example.com", "snippet": "snippet A"},
        {"title": "Result B", "url": "https://b.example.com", "snippet": "snippet B"},
    ]


def test_web_search_returns_empty_on_client_error():
    import rag.tools.web_search as web_search_mod

    fake_client = MagicMock()
    fake_client.search.side_effect = RuntimeError("Tavily is down")

    with patch.object(web_search_mod, "_get_tavily_client", return_value=fake_client):
        result = web_search_mod.web_search.invoke({"query": "x"})

    assert result == []
