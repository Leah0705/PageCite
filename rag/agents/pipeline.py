from __future__ import annotations

import logging
from typing import Literal

from langgraph.graph import END, StateGraph

from rag.agents.critic import critic_node
from rag.agents.researcher import researcher_node
from rag.agents.state import GraphState
from rag.agents.synthesizer import synthesizer_node

logger = logging.getLogger(__name__)

MAX_REVISIONS = 2


def fallback_node(state: GraphState) -> GraphState:
    """Return a fallback message, using error details if available."""
    error = state.get("error", "")
    if error:
        return {"generation": error}
    return {"generation": "I do not know based on the provided document."}


def route_after_researcher(state: GraphState) -> Literal["synthesizer", "fallback"]:
    if state.get("error"):
        return "fallback"
    return "synthesizer"


def route_after_critic(state: GraphState) -> Literal["synthesizer", "__end__"]:
    if state.get("critic_feedback") == "approve":
        return END
    if state.get("retry_count", 0) > MAX_REVISIONS:
        return END
    return "synthesizer"


def build_agent_graph():
    """Wire the Researcher -> Synthesizer -> Critic pipeline.

    Researcher runs once. Synthesizer <-> Critic can loop up to MAX_REVISIONS
    times before the last draft is accepted regardless of the critic's verdict.
    Routing between the agents is fixed by the edges below, not chosen by an LLM.
    """
    graph = StateGraph(GraphState)

    graph.add_node("researcher", researcher_node)
    graph.add_node("synthesizer", synthesizer_node)
    graph.add_node("critic", critic_node)
    graph.add_node("fallback", fallback_node)

    graph.set_entry_point("researcher")

    graph.add_conditional_edges(
        "researcher",
        route_after_researcher,
        {"synthesizer": "synthesizer", "fallback": "fallback"},
    )
    graph.add_edge("synthesizer", "critic")
    graph.add_conditional_edges(
        "critic",
        route_after_critic,
        {"synthesizer": "synthesizer", END: END},
    )
    graph.add_edge("fallback", END)

    return graph.compile()
