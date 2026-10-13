from __future__ import annotations

from functools import lru_cache
from typing import Callable

from rag.agents.state import GraphState
from rag.agents.pipeline import build_agent_graph
from rag.usage import TokenUsageCallback


_NODE_LABELS: dict[str, str] = {
    "fallback": "Preparing response…",
}


@lru_cache(maxsize=1)
def build_graph():
    return build_agent_graph()


def run_agent(
    question: str,
    doc_id: str,
    session_id: str = "",
    on_step: Callable[[str], None] | None = None,
    top_k: int = 6,
    use_tools: bool = True,
) -> tuple[GraphState, TokenUsageCallback]:
    """Run the Researcher -> Synthesizer -> Critic graph, reporting progress via on_step(label).

    on_step is threaded into each node's config so nodes can report sub-steps as they
    actually happen (e.g. "Searching the web…" the moment that tool is called), instead
    of a single generic label that only fires once the whole node has finished.

    use_tools=False skips the researcher's web_search / calculator step entirely, used by
    the RAGAS eval runner so scores measure document-grounded retrieval + synthesis only.

    Returns (state, usage) where usage.tokens_in / tokens_out are totals across all LLM calls.
    """
    graph = build_graph()
    usage = TokenUsageCallback()
    usage.activate()
    try:
        init: GraphState = {
            "question": question,
            "generation": "",
            "raw_generation": "",
            "documents": [],
            "cited_documents": [],
            "doc_id": doc_id,
            "retry_count": 0,
            "grounded": False,
            "critic_feedback": "",
            "error": "",
            "session_id": session_id,
            "hyde_triggered": False,
            "top_k": top_k,
            "use_tools": use_tools,
            "tool_usage": {
                "web_search": {"used": False, "count": 0, "results": []},
                "calculator": {"used": False, "expression": "", "result": ""},
            },
        }

        if on_step is None:
            result = graph.invoke(init)
            return result, usage

        config = {"configurable": {"on_step": on_step}}
        final: GraphState = init
        for chunk in graph.stream(init, config=config, stream_mode="updates"):
            for node_name in chunk:
                if node_name in _NODE_LABELS:
                    on_step(_NODE_LABELS[node_name])
                final = {**final, **chunk[node_name]}
        return final, usage
    finally:
        usage.deactivate()
