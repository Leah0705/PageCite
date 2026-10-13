from __future__ import annotations

from unittest.mock import patch

from langchain_core.documents import Document

from rag.usage import TokenUsageCallback


def test_run_pipeline_unpacks_run_agent_tuple():
    """Regression test: run_agent() returns (state, usage), not just state."""
    from eval.run import _run_pipeline

    doc = Document(page_content="Python is a language.", metadata={"ref": "r1", "page": 1})
    fake_state = {"generation": "Python is a language.", "documents": [doc]}

    with patch("eval.run.run_agent", return_value=(fake_state, TokenUsageCallback())) as mock_run:
        answer, contexts = _run_pipeline("What is Python?", "doc123")

    assert answer == "Python is a language."
    assert contexts == ["Python is a language."]
    assert mock_run.call_args.kwargs["use_tools"] is False


def test_run_pipeline_handles_empty_documents():
    from eval.run import _run_pipeline

    fake_state = {"generation": "I do not know based on the provided document.", "documents": []}
    with patch("eval.run.run_agent", return_value=(fake_state, TokenUsageCallback())):
        answer, contexts = _run_pipeline("Unrelated question?", "doc123")

    assert answer == "I do not know based on the provided document."
    assert contexts == ["No context retrieved."]
