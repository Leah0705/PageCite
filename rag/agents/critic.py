from __future__ import annotations

import logging
from typing import List, Literal

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from rag.agents.state import GraphState, get_on_step
from rag.agents.synthesizer import CALC_TAG, citation_tag, extract_cited_tags
from rag.llm import get_llm

logger = logging.getLogger(__name__)


class CriticVerdict(BaseModel):
    verdict: Literal["approve", "revise"] = Field(
        description="'approve' if the answer is grounded, cited, and on-topic, 'revise' otherwise."
    )
    reason: str = Field(default="", description="If 'revise', a short actionable reason why.")


_CRITIC_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are the critic in a document Q&A pipeline. Review the draft answer against "
            "the source context and the question, and check three things:\n"
            "1. Hallucination: every factual claim must be supported by the source context. "
            "A refusal ('I do not know...') is always grounded.\n"
            "2. Missing citations: the answer must cite whichever source in the context "
            "actually supports it, using [[ref:page]] for a document chunk, [[web:url]] for "
            "a web result, or [[calc]] for a calculation. It only needs to cite the source(s) "
            "it actually used, not every source in the context. Skip this check entirely if "
            "the answer is a refusal or no source context was provided.\n"
            "3. Off-topic: the answer must actually address the question asked.\n\n"
            "Reply 'approve' if all checks pass, 'revise' with a short reason otherwise.",
        ),
        (
            "human",
            "Question: {question}\n\nSource context:\n{context}\n\nDraft answer:\n{draft}",
        ),
    ]
)


def _format_context(documents: List[Document], tool_usage: dict) -> str:
    parts = [
        f"[[{citation_tag(doc)}]]: {doc.metadata.get('original_content') or doc.page_content}"
        for doc in documents
    ]
    calc = tool_usage.get("calculator", {}) if tool_usage else {}
    if calc.get("used"):
        parts.append(f"[[{CALC_TAG}]]: Calculation: {calc.get('expression')} = {calc.get('result')}")
    return "\n\n".join(parts) if parts else "(no source context)"


def _cited_documents(draft: str, documents: List[Document]) -> List[Document]:
    """Only the chunks the synthesizer actually cited. This is what the API surfaces as citations."""
    cited = extract_cited_tags(draft)
    if not cited:
        return []
    return [doc for doc in documents if citation_tag(doc) in cited]


def critic_node(state: GraphState, config: RunnableConfig = {}) -> GraphState:
    """Check the synthesizer's draft for hallucination, missing citations, and off-topic drift."""
    on_step = get_on_step(config)
    if on_step:
        on_step("Reviewing answer…")

    draft = state.get("raw_generation") or state.get("generation", "")
    documents = state.get("documents", [])
    tool_usage = state.get("tool_usage", {})
    cited_documents = _cited_documents(draft, documents)

    try:
        from rag.usage import capture_from_message

        llm = get_llm().with_structured_output(CriticVerdict, include_raw=True)
        chain = _CRITIC_PROMPT | llm
        raw_result = chain.invoke(
            {
                "question": state["question"],
                "context": _format_context(documents, tool_usage),
                "draft": draft,
            },
            config=config,
        )
        capture_from_message(raw_result["raw"])
        verdict: CriticVerdict = raw_result["parsed"]

        if verdict.verdict == "approve":
            _save_to_memory(state)
            return {"critic_feedback": "approve", "grounded": True, "cited_documents": cited_documents}

        return {
            "critic_feedback": f"revise: {verdict.reason}",
            "grounded": False,
            "retry_count": state.get("retry_count", 0) + 1,
            "cited_documents": cited_documents,
        }

    except Exception as e:
        logger.error(f"Critic failed, approving by default: {e}")
        _save_to_memory(state)
        return {"critic_feedback": "approve", "grounded": True, "cited_documents": cited_documents}


def _save_to_memory(state: GraphState) -> None:
    session_id = state.get("session_id", "")
    answer = state.get("generation", "")
    if not session_id or not answer:
        return
    from rag.agents.memory import get_memory

    mem = get_memory(session_id, state["doc_id"])
    mem.add_user_message(state["question"])
    mem.add_ai_message(answer)
