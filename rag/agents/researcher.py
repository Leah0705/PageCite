from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Annotated, List
from typing_extensions import TypedDict

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from rag.agents.state import GraphState, get_on_step
from rag.chains.retrieval import retrieve_with_hyde
from rag.llm import get_llm
from rag.tools.calculator import calculator
from rag.tools.web_search import web_search

logger = logging.getLogger(__name__)

_TOOLS = [web_search, calculator]
MAX_TOOL_ROUNDS = 3

_TOOL_SYSTEM_PROMPT = (
    "You are the research assistant for a document Q&A system. Below are ALL the "
    "chunks already retrieved from the document for the user's question.\n\n"
    "You have two optional tools:\n"
    "- web_search: for anything time-sensitive (today's date, the current time, "
    "recent/live events, prices, or similar) or facts that are clearly absent from "
    "the chunks below. Time-sensitive questions always need web_search, you do not "
    "have real-time knowledge on your own.\n"
    "- calculator: for arithmetic the question requires.\n\n"
    "First, read every chunk below carefully. The answer is often present but not "
    "in the first chunk. Only call a tool if, after checking ALL the chunks, they "
    "are still not sufficient to answer the question. If the chunks already answer "
    "it, do not call any tool, just reply with a brief acknowledgement.\n\n"
    "Retrieved chunks:\n{chunks}"
)

_CHUNK_PREVIEW_CHARS = 1000


class ResearcherToolState(TypedDict):
    messages: Annotated[list, add_messages]
    rounds: int


def _default_tool_usage() -> dict:
    return {
        "web_search": {"used": False, "count": 0, "results": []},
        "calculator": {"used": False, "expression": "", "result": ""},
    }


_TOOL_STEP_LABELS = {"web_search": "Searching the web…", "calculator": "Calculating…"}


@lru_cache(maxsize=1)
def _build_tool_subgraph():
    def agent_node(state: ResearcherToolState, config: RunnableConfig = {}) -> ResearcherToolState:
        from rag.usage import capture_from_message

        llm_with_tools = get_llm().bind_tools(_TOOLS)
        ai_msg = llm_with_tools.invoke(state["messages"], config=config)
        capture_from_message(ai_msg)

        on_step = get_on_step(config)
        if on_step:
            for call in ai_msg.tool_calls or []:
                label = _TOOL_STEP_LABELS.get(call["name"])
                if label:
                    on_step(label)

        return {"messages": [ai_msg], "rounds": state.get("rounds", 0) + 1}

    def route_tools(state: ResearcherToolState) -> str:
        # Hard cap so a model that keeps requesting tools can't loop forever.
        if state.get("rounds", 0) >= MAX_TOOL_ROUNDS:
            return END
        return tools_condition(state)

    graph = StateGraph(ResearcherToolState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(_TOOLS))
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", route_tools, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile()


def _tool_call_args(messages: list) -> dict[str, dict]:
    """Map tool_call_id -> args, read off every AIMessage's tool_calls."""
    args_by_id: dict[str, dict] = {}
    for msg in messages:
        if isinstance(msg, AIMessage):
            for call in msg.tool_calls or []:
                args_by_id[call["id"]] = call.get("args", {})
    return args_by_id


def _augment_with_tools(
    question: str, docs: List[Document], tool_usage: dict, config: RunnableConfig
) -> tuple[List[Document], dict]:
    chunks_preview = "\n\n".join(
        (d.metadata.get("original_content") or d.page_content)[:_CHUNK_PREVIEW_CHARS] for d in docs
    ) or "(no chunks retrieved from the document)"

    graph = _build_tool_subgraph()
    messages = [
        SystemMessage(content=_TOOL_SYSTEM_PROMPT.format(chunks=chunks_preview)),
        HumanMessage(content=question),
    ]
    result = graph.invoke({"messages": messages, "rounds": 0}, config=config)
    result_messages = result["messages"]
    call_args = _tool_call_args(result_messages)

    for msg in result_messages:
        if not isinstance(msg, ToolMessage):
            continue

        if msg.name == "web_search":
            try:
                results = json.loads(msg.content)
            except (json.JSONDecodeError, TypeError):
                results = []
            if not results:
                continue
            tool_usage["web_search"]["used"] = True
            tool_usage["web_search"]["count"] += len(results)
            tool_usage["web_search"]["results"].extend(results)
            docs = docs + [
                Document(
                    page_content=r.get("snippet", ""),
                    metadata={
                        "source": "web",
                        "url": r.get("url", ""),
                        "ref": r.get("url", ""),
                        "title": r.get("title", ""),
                        "page": -1,
                        "chunk_id": -1,
                    },
                )
                for r in results
            ]

        elif msg.name == "calculator":
            expr = call_args.get(msg.tool_call_id, {}).get("expression", "")
            tool_usage["calculator"] = {"used": True, "expression": expr, "result": msg.content}

    return docs, tool_usage


def researcher_node(state: GraphState, config: RunnableConfig = {}) -> GraphState:
    """Hybrid retrieval (with HyDE fallback), then optional LLM-selected web search / calculator."""
    on_step = get_on_step(config)
    if on_step:
        on_step("Searching the document…")

    top_k = state.get("top_k", 6)
    try:
        docs, hyde_triggered = retrieve_with_hyde(doc_id=state["doc_id"], query=state["question"], top_k=top_k)
    except Exception as e:
        logger.error(f"Researcher retrieval failed: {e}")
        docs, hyde_triggered = [], False

    if hyde_triggered and on_step:
        on_step("Refining search…")

    tool_usage = _default_tool_usage()
    if state.get("use_tools", True):
        try:
            docs, tool_usage = _augment_with_tools(state["question"], docs, tool_usage, config)
        except Exception as e:
            logger.error(f"Researcher tool step failed: {e}")

    if not docs:
        return {
            "documents": [],
            "hyde_triggered": hyde_triggered,
            "tool_usage": tool_usage,
            "error": (
                "No documents have been indexed for this document. "
                "Please index the document first."
            ),
        }

    return {"documents": docs, "hyde_triggered": hyde_triggered, "tool_usage": tool_usage, "error": ""}
