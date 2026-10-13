from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableLambda


def _make_state(**kwargs):
    base = {
        "question": "test question",
        "generation": "",
        "raw_generation": "",
        "documents": [],
        "doc_id": "test_doc",
        "retry_count": 0,
        "grounded": False,
        "critic_feedback": "",
        "error": "",
        "session_id": "",
        "hyde_triggered": False,
        "top_k": 6,
        "use_tools": True,
        "cited_documents": [],
        "tool_usage": {
            "web_search": {"used": False, "count": 0, "results": []},
            "calculator": {"used": False, "expression": "", "result": ""},
        },
    }
    base.update(kwargs)
    return base


def _fake_doc(content="Some relevant content.", **metadata):
    meta = {"doc_id": "test_doc", "ref": "ref1", "page": 1, "chunk_id": 0, "source": "test.pdf"}
    meta.update(metadata)
    return Document(page_content=content, metadata=meta)


# ─────────────────────────────────────────────
# Researcher
# ─────────────────────────────────────────────

def test_researcher_returns_chunks_with_no_tool_use():
    from rag.agents.researcher import researcher_node

    docs = [_fake_doc("relevant content")]
    with patch("rag.agents.researcher.retrieve_with_hyde", return_value=(docs, False)), \
         patch("rag.agents.researcher._augment_with_tools", return_value=(docs, {
             "web_search": {"used": False, "count": 0, "results": []},
             "calculator": {"used": False, "expression": "", "result": ""},
         })):
        result = researcher_node(_make_state())

    assert result["documents"] == docs
    assert result["error"] == ""
    assert result["tool_usage"]["web_search"]["used"] is False


def test_researcher_sets_error_when_nothing_found():
    from rag.agents.researcher import researcher_node

    with patch("rag.agents.researcher.retrieve_with_hyde", return_value=([], False)), \
         patch("rag.agents.researcher._augment_with_tools", return_value=([], {
             "web_search": {"used": False, "count": 0, "results": []},
             "calculator": {"used": False, "expression": "", "result": ""},
         })):
        result = researcher_node(_make_state())

    assert result["documents"] == []
    assert "have been indexed" in result["error"]


def test_researcher_skips_tools_when_use_tools_false():
    from rag.agents.researcher import researcher_node

    docs = [_fake_doc("relevant content")]
    with patch("rag.agents.researcher.retrieve_with_hyde", return_value=(docs, False)), \
         patch("rag.agents.researcher._augment_with_tools") as mock_augment:
        result = researcher_node(_make_state(use_tools=False))

    mock_augment.assert_not_called()
    assert result["documents"] == docs
    assert result["tool_usage"]["web_search"]["used"] is False
    assert result["tool_usage"]["calculator"]["used"] is False


def test_researcher_recovers_from_retrieval_exception():
    from rag.agents.researcher import researcher_node

    with patch("rag.agents.researcher.retrieve_with_hyde", side_effect=RuntimeError("db down")), \
         patch("rag.agents.researcher._augment_with_tools", return_value=([], {
             "web_search": {"used": False, "count": 0, "results": []},
             "calculator": {"used": False, "expression": "", "result": ""},
         })):
        result = researcher_node(_make_state())

    assert result["documents"] == []
    assert result["error"]


def test_researcher_node_reports_on_step_progress():
    from rag.agents.researcher import researcher_node

    docs = [_fake_doc("relevant content")]
    steps: list[str] = []
    config = {"configurable": {"on_step": steps.append}}

    with patch("rag.agents.researcher.retrieve_with_hyde", return_value=(docs, True)), \
         patch("rag.agents.researcher._augment_with_tools", return_value=(docs, {
             "web_search": {"used": False, "count": 0, "results": []},
             "calculator": {"used": False, "expression": "", "result": ""},
         })):
        researcher_node(_make_state(), config)

    assert steps == ["Searching the document…", "Refining search…"]


def test_tool_agent_node_reports_tool_step():
    from langchain_core.messages import HumanMessage
    from rag.agents import researcher as researcher_mod

    fake_bound_llm = MagicMock()
    fake_bound_llm.invoke.return_value = AIMessage(
        content="", tool_calls=[{"name": "calculator", "args": {"expression": "1+1"}, "id": "call1"}]
    )
    fake_llm = MagicMock()
    fake_llm.bind_tools.return_value = fake_bound_llm

    steps: list[str] = []
    config = {"configurable": {"on_step": steps.append}}

    researcher_mod._build_tool_subgraph.cache_clear()
    with patch.object(researcher_mod, "get_llm", return_value=fake_llm):
        graph = researcher_mod._build_tool_subgraph()
        graph.invoke({"messages": [HumanMessage(content="what is 1+1")], "rounds": 0}, config=config)
    researcher_mod._build_tool_subgraph.cache_clear()

    assert "Calculating…" in steps


def test_augment_with_tools_merges_web_results():
    from rag.agents import researcher as researcher_mod

    fake_graph = MagicMock()
    fake_graph.invoke.return_value = {
        "messages": [
            AIMessage(content="", tool_calls=[{"name": "web_search", "args": {"query": "x"}, "id": "call1"}]),
            ToolMessage(
                name="web_search", tool_call_id="call1",
                content=json.dumps([{"title": "T", "url": "https://example.com", "snippet": "hello"}]),
            ),
        ]
    }
    with patch.object(researcher_mod, "_build_tool_subgraph", return_value=fake_graph):
        docs, tool_usage = researcher_mod._augment_with_tools(
            "q", [], researcher_mod._default_tool_usage(), {}
        )

    assert tool_usage["web_search"]["used"] is True
    assert tool_usage["web_search"]["count"] == 1
    assert docs[0].metadata["source"] == "web"
    assert docs[0].metadata["url"] == "https://example.com"


def test_augment_with_tools_records_calculator_usage():
    from rag.agents import researcher as researcher_mod

    fake_graph = MagicMock()
    fake_graph.invoke.return_value = {
        "messages": [
            AIMessage(content="", tool_calls=[{"name": "calculator", "args": {"expression": "2+2"}, "id": "call1"}]),
            ToolMessage(name="calculator", tool_call_id="call1", content="4"),
        ]
    }
    with patch.object(researcher_mod, "_build_tool_subgraph", return_value=fake_graph):
        docs, tool_usage = researcher_mod._augment_with_tools(
            "q", [], researcher_mod._default_tool_usage(), {}
        )

    assert docs == []
    assert tool_usage["calculator"] == {"used": True, "expression": "2+2", "result": "4"}


def test_tool_subgraph_caps_rounds_even_if_model_keeps_calling_tools():
    from langchain_core.messages import HumanMessage
    from rag.agents import researcher as researcher_mod

    call_count = {"n": 0}

    def fake_invoke(messages, config=None):
        call_count["n"] += 1
        return AIMessage(
            content="",
            tool_calls=[{"name": "calculator", "args": {"expression": "1+1"}, "id": f"call{call_count['n']}"}],
        )

    fake_bound_llm = MagicMock()
    fake_bound_llm.invoke.side_effect = fake_invoke
    fake_llm = MagicMock()
    fake_llm.bind_tools.return_value = fake_bound_llm

    researcher_mod._build_tool_subgraph.cache_clear()
    with patch.object(researcher_mod, "get_llm", return_value=fake_llm):
        graph = researcher_mod._build_tool_subgraph()
        graph.invoke({"messages": [HumanMessage(content="loop forever")], "rounds": 0})
    researcher_mod._build_tool_subgraph.cache_clear()

    assert call_count["n"] == researcher_mod.MAX_TOOL_ROUNDS


# ─────────────────────────────────────────────
# Critic
# ─────────────────────────────────────────────

def _mock_critic_llm(verdict: str, reason: str = ""):
    from rag.agents.critic import CriticVerdict

    parsed = CriticVerdict(verdict=verdict, reason=reason)
    structured = RunnableLambda(lambda _: {"raw": AIMessage(content=""), "parsed": parsed})
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


def test_critic_approves_grounded_answer(fake_redis):
    from rag.agents.critic import critic_node
    from rag.agents.memory import get_memory

    state = _make_state(
        session_id="critic_test_session",
        generation="Python is a language.",
        raw_generation="Python is a language. [[ref1:1]]",
        documents=[_fake_doc()],
    )
    with patch("rag.agents.critic.get_llm", return_value=_mock_critic_llm("approve")):
        result = critic_node(state)

    assert result["critic_feedback"] == "approve"
    assert result["grounded"] is True
    # An approved answer is remembered for follow-up questions on the same document.
    saved = get_memory("critic_test_session", "test_doc").messages
    assert [m.content for m in saved] == ["test question", "Python is a language."]


def test_critic_reports_on_step_progress(fake_redis):
    from rag.agents.critic import critic_node

    steps: list[str] = []
    state = _make_state(
        session_id="critic_step_session",
        generation="Python is a language.",
        raw_generation="Python is a language. [[ref1:1]]",
        documents=[_fake_doc()],
    )
    with patch("rag.agents.critic.get_llm", return_value=_mock_critic_llm("approve")):
        critic_node(state, {"configurable": {"on_step": steps.append}})

    assert steps == ["Reviewing answer…"]


def test_critic_requests_revision_and_increments_retry_count():
    from rag.agents.critic import critic_node

    state = _make_state(
        generation="The sky is green.",
        raw_generation="The sky is green.",
        documents=[_fake_doc("The sky is blue.")],
        retry_count=0,
    )
    with patch("rag.agents.critic.get_llm", return_value=_mock_critic_llm("revise", "not grounded")):
        result = critic_node(state)

    assert result["critic_feedback"] == "revise: not grounded"
    assert result["grounded"] is False
    assert result["retry_count"] == 1


def test_critic_defaults_to_approve_on_llm_error():
    from rag.agents.critic import critic_node

    state = _make_state(generation="Answer.", raw_generation="Answer.")
    with patch("rag.agents.critic.get_llm", side_effect=RuntimeError("API down")):
        result = critic_node(state)

    assert result["critic_feedback"] == "approve"
    assert result["grounded"] is True


def test_critic_returns_only_actually_cited_documents():
    """Citations shown to the user should be exactly the sources the model referenced."""
    from rag.agents.critic import critic_node

    cited_doc = _fake_doc("cited chunk", ref="ref1", page=1)
    uncited_doc = _fake_doc("uncited chunk", ref="ref2", page=2)
    state = _make_state(
        generation="Answer citing one source.",
        raw_generation="Answer citing one source. [[ref1:1]]",
        documents=[cited_doc, uncited_doc],
    )
    with patch("rag.agents.critic.get_llm", return_value=_mock_critic_llm("approve")):
        result = critic_node(state)

    assert result["cited_documents"] == [cited_doc]


def test_critic_returns_no_citations_for_refusal():
    from rag.agents.critic import critic_node

    docs = [_fake_doc("irrelevant chunk", ref="ref1", page=1)]
    state = _make_state(
        generation="I do not know based on the provided document.",
        raw_generation="I do not know based on the provided document.",
        documents=docs,
    )
    with patch("rag.agents.critic.get_llm", return_value=_mock_critic_llm("approve")):
        result = critic_node(state)

    assert result["cited_documents"] == []


def test_critic_format_context_includes_citation_tags():
    from rag.agents.critic import _format_context

    doc = _fake_doc("some content", ref="ref9", page=4)
    context = _format_context([doc], {})

    assert "[[ref9:4]]" in context


def test_critic_format_context_tags_calculator_result():
    from rag.agents.critic import _format_context

    tool_usage = {"calculator": {"used": True, "expression": "199-1+200", "result": "398"}}
    context = _format_context([], tool_usage)

    assert "[[calc]]" in context
    assert "398" in context


# ─────────────────────────────────────────────
# Synthesizer
# ─────────────────────────────────────────────

def test_build_context_tags_calculator_result():
    from rag.agents.synthesizer import _build_context

    tool_usage = {"calculator": {"used": True, "expression": "199-1+200", "result": "398"}}
    context = _build_context([], tool_usage)

    assert "[[calc]]" in context
    assert "398" in context


def test_synthesizer_strips_citation_tags_for_display():
    from rag.agents.synthesizer import synthesizer_node

    chain = RunnableLambda(lambda _: "Python is a language. [[ref1:1]]")
    with patch("rag.agents.synthesizer._get_chain", return_value=chain):
        result = synthesizer_node(_make_state(documents=[_fake_doc()]))

    assert result["raw_generation"] == "Python is a language. [[ref1:1]]"
    assert result["generation"] == "Python is a language."


def test_synthesizer_reports_writing_vs_revising_step():
    from rag.agents.synthesizer import synthesizer_node

    chain = RunnableLambda(lambda _: "Python is a language. [[ref1:1]]")
    with patch("rag.agents.synthesizer._get_chain", return_value=chain):
        first_steps: list[str] = []
        synthesizer_node(_make_state(documents=[_fake_doc()]), {"configurable": {"on_step": first_steps.append}})

        revise_steps: list[str] = []
        synthesizer_node(
            _make_state(documents=[_fake_doc()], critic_feedback="revise: missing citation"),
            {"configurable": {"on_step": revise_steps.append}},
        )

    assert first_steps == ["Writing answer…"]
    assert revise_steps == ["Revising answer…"]


def test_synthesizer_incorporates_revision_feedback():
    from rag.agents.synthesizer import synthesizer_node

    captured = {}

    def _capture(inputs):
        captured.update(inputs)
        return "Revised answer. [[ref1:1]]"

    chain = RunnableLambda(_capture)
    state = _make_state(
        documents=[_fake_doc()],
        critic_feedback="revise: missing citation",
        raw_generation="Old draft.",
    )
    with patch("rag.agents.synthesizer._get_chain", return_value=chain):
        synthesizer_node(state)

    assert "rejected by the critic" in captured["input"]
    assert "missing citation" in captured["input"]
    assert "Old draft." in captured["input"]


def test_synthesizer_falls_back_on_llm_error():
    from rag.agents.synthesizer import synthesizer_node

    with patch("rag.agents.synthesizer._get_chain", side_effect=RuntimeError("API down")):
        result = synthesizer_node(_make_state(documents=[_fake_doc("Some excerpt.")]))

    assert "Some excerpt." in result["generation"]
    assert result["grounded"] is True
    assert "API down" in result["error"]  # flags the fallback so the API won't cache it


def test_strip_citation_tags_handles_multiple_tags():
    from rag.agents.synthesizer import strip_citation_tags

    text = "First fact [[ref1:1]] and second fact [[web:https://x.com]] ."
    assert strip_citation_tags(text) == "First fact and second fact."


def test_strip_citation_tags_handles_malformed_bracket_list():
    from rag.agents.synthesizer import extract_cited_tags, strip_citation_tags

    text = "A claim backed by three sources [[ref1:1], [ref1:2], [web:https://x.com]]."
    assert strip_citation_tags(text) == "A claim backed by three sources."
    assert extract_cited_tags(text) == {"ref1:1", "ref1:2", "web:https://x.com"}


def test_citation_tag_for_document_and_web_source():
    from rag.agents.synthesizer import citation_tag

    doc = _fake_doc(ref="ref3", page=2)
    assert citation_tag(doc) == "ref3:2"

    web_doc = _fake_doc(source="web", url="https://example.com")
    assert citation_tag(web_doc) == "web:https://example.com"


def test_extract_cited_tags_returns_unique_set():
    from rag.agents.synthesizer import extract_cited_tags

    text = "Fact one [[ref1:1]] and fact two [[ref1:1]] and [[web:https://x.com]]."
    assert extract_cited_tags(text) == {"ref1:1", "web:https://x.com"}


# ─────────────────────────────────────────────
# Pipeline routing
# ─────────────────────────────────────────────

def test_route_after_researcher_goes_to_fallback_on_error():
    from rag.agents.pipeline import route_after_researcher

    assert route_after_researcher(_make_state(error="No documents indexed.")) == "fallback"


def test_route_after_researcher_goes_to_synthesizer():
    from rag.agents.pipeline import route_after_researcher

    assert route_after_researcher(_make_state(error="")) == "synthesizer"


def test_route_after_critic_ends_on_approve():
    from langgraph.graph import END
    from rag.agents.pipeline import route_after_critic

    assert route_after_critic(_make_state(critic_feedback="approve", retry_count=0)) == END


def test_route_after_critic_loops_within_revision_budget():
    from rag.agents.pipeline import route_after_critic

    assert route_after_critic(_make_state(critic_feedback="revise: x", retry_count=2)) == "synthesizer"


def test_route_after_critic_ends_when_revision_budget_exhausted():
    from langgraph.graph import END
    from rag.agents.pipeline import route_after_critic

    assert route_after_critic(_make_state(critic_feedback="revise: x", retry_count=3)) == END


# ─────────────────────────────────────────────
# Full pipeline (mocked nodes)
# ─────────────────────────────────────────────

def test_full_pipeline_end_to_end():
    from rag.agents.graph import build_graph

    fake_doc = _fake_doc("Python is a programming language.")

    with patch("rag.agents.pipeline.researcher_node", return_value={
            "documents": [fake_doc], "hyde_triggered": False, "error": "",
            "tool_usage": {"web_search": {"used": False, "count": 0, "results": []},
                           "calculator": {"used": False, "expression": "", "result": ""}},
         }), \
         patch("rag.agents.pipeline.synthesizer_node", return_value={
             "generation": "Python is a language.", "raw_generation": "Python is a language. [[ref1:1]]",
         }), \
         patch("rag.agents.pipeline.critic_node", return_value={"critic_feedback": "approve", "grounded": True}):
        build_graph.cache_clear()
        result = build_graph().invoke(_make_state(question="What is Python?", doc_id="pipeline_doc"))

    build_graph.cache_clear()
    assert result["generation"] == "Python is a language."
    assert result["grounded"] is True


def test_full_pipeline_revises_once_then_approves():
    from rag.agents.graph import build_graph

    fake_doc = _fake_doc("Python is a programming language.")
    synth_calls = []

    def fake_synthesizer(state):
        synth_calls.append(state.get("critic_feedback", ""))
        return {"generation": f"draft {len(synth_calls)}", "raw_generation": f"draft {len(synth_calls)} [[ref1:1]]"}

    critic_verdicts = iter([
        {"critic_feedback": "revise: needs a citation", "grounded": False, "retry_count": 1},
        {"critic_feedback": "approve", "grounded": True},
    ])

    with patch("rag.agents.pipeline.researcher_node", return_value={
            "documents": [fake_doc], "hyde_triggered": False, "error": "",
            "tool_usage": {"web_search": {"used": False, "count": 0, "results": []},
                           "calculator": {"used": False, "expression": "", "result": ""}},
         }), \
         patch("rag.agents.pipeline.synthesizer_node", side_effect=fake_synthesizer), \
         patch("rag.agents.pipeline.critic_node", side_effect=lambda state: next(critic_verdicts)):
        build_graph.cache_clear()
        result = build_graph().invoke(_make_state(question="What is Python?", doc_id="pipeline_doc"))

    build_graph.cache_clear()
    assert len(synth_calls) == 2
    assert result["generation"] == "draft 2"
    assert result["grounded"] is True


# ─────────────────────────────────────────────
# Conversation memory
# ─────────────────────────────────────────────

def test_conversation_memory_stores_and_retrieves(fake_redis):
    from rag.agents.memory import clear_memory, get_memory

    mem = get_memory("test_session_abc", "doc1")
    mem.add_user_message("What is this document about?")
    mem.add_ai_message("It is about machine learning.")

    mem2 = get_memory("test_session_abc", "doc1")  # a fresh handle, as another worker would use
    assert len(mem2.messages) == 2
    assert mem2.messages[0].content == "What is this document about?"
    assert mem2.messages[1].content == "It is about machine learning."

    clear_memory("test_session_abc", "doc1")
    assert len(get_memory("test_session_abc", "doc1").messages) == 0


def test_conversation_memory_different_sessions_are_isolated(fake_redis):
    from rag.agents.memory import get_memory

    get_memory("session_a", "doc1").add_user_message("Session A question")
    get_memory("session_b", "doc1").add_user_message("Session B question")

    assert [m.content for m in get_memory("session_a", "doc1").messages] == ["Session A question"]
    assert [m.content for m in get_memory("session_b", "doc1").messages] == ["Session B question"]


def test_conversation_memory_is_scoped_to_the_document(fake_redis):
    """The same session id on another document must not see this history."""
    from rag.agents.memory import get_memory

    get_memory("shared_session", "doc_of_user_a").add_user_message("private question")

    assert get_memory("shared_session", "doc_of_user_b").messages == []


def test_conversation_memory_is_trimmed_and_expires(fake_redis):
    from rag.agents.memory import MAX_MESSAGES, TTL_SECONDS, _key, get_memory

    mem = get_memory("long_session", "doc1")
    for i in range(MAX_MESSAGES + 5):
        mem.add_user_message(f"q{i}")

    contents = [m.content for m in mem.messages]
    assert len(contents) == MAX_MESSAGES
    assert contents[-1] == f"q{MAX_MESSAGES + 4}"
    assert fake_redis.ttl[_key("long_session", "doc1")] == TTL_SECONDS


def test_conversation_memory_degrades_when_redis_is_down(monkeypatch):
    from rag.agents import memory

    def _down():
        raise ConnectionError("Redis down")

    monkeypatch.setattr(memory, "_redis", _down)
    mem = memory.get_memory("s", "doc1")
    mem.add_user_message("still answered")  # must not raise
    assert mem.messages == []


def test_clear_document_memory_only_removes_that_document(fake_redis):
    from rag.agents.memory import clear_document_memory, get_memory

    get_memory("s1", "doc1").add_user_message("a")
    get_memory("s2", "doc1").add_user_message("b")
    get_memory("s1", "doc2").add_user_message("c")

    assert clear_document_memory("doc1") == 2
    assert get_memory("s1", "doc1").messages == []
    assert [m.content for m in get_memory("s1", "doc2").messages] == ["c"]
