from __future__ import annotations

from typing import Callable, List
from typing_extensions import TypedDict

from langchain_core.documents import Document
from langchain_core.runnables import RunnableConfig


class GraphState(TypedDict):
    question: str              # the user's question
    generation: str            # the synthesizer's answer, citation tags stripped
    raw_generation: str        # synthesizer output before tag stripping (critic input)
    documents: List[Document]  # chunks returned by the researcher (incl. web results)
    doc_id: str                # which PDF to query
    retry_count: int           # critic revision counter (max MAX_REVISIONS)
    grounded: bool             # whether the critic approved the generation
    critic_feedback: str       # "" | "approve" | "revise: <reason>"
    error: str                 # set when a node fails or doc is not indexed
    session_id: str            # for conversation memory (empty string = no memory)
    hyde_triggered: bool       # whether HyDE fired during retrieval
    top_k: int                 # number of chunks to retrieve after reranking
    tool_usage: dict           # web_search / calculator usage, for UI badges
    use_tools: bool            # whether the researcher may call web_search / calculator
    cited_documents: List[Document]  # subset of `documents` actually referenced in the answer


def get_on_step(config: RunnableConfig) -> Callable[[str], None] | None:
    """The on_step(label) callback threaded in via config, if any, for real-time progress."""
    return (config or {}).get("configurable", {}).get("on_step")
