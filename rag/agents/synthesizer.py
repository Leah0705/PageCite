from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import List

from langchain_core.documents import Document
from langchain_core.messages import BaseMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableConfig, RunnableLambda

from rag.agents.state import GraphState, get_on_step
from rag.llm import get_llm

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a precise, helpful assistant that answers questions strictly based on "
    "the context extracted from a PDF document, plus any web search or calculation "
    "results included below.\n\n"
    "Rules:\n"
    "- Answer ONLY using information present in the context below.\n"
    "- After each claim that comes from a source, append its citation tag exactly as "
    "shown next to that source (e.g. [[abc123:4]] for a document chunk, "
    "[[web:https://example.com]] for a web result, [[calc]] for a calculation). Never "
    "invent a tag that isn't shown in the context. If a claim is supported by more than "
    "one source, repeat the tag format for each one back to back, e.g. "
    "[[abc123:4]][[abc123:5]]. Never combine multiple tags into one bracket or a "
    "comma-separated list.\n"
    "- When the context contains labels, names, or terms that directly address the "
    "substance of the question, use them to answer. Do not refuse just because a "
    "secondary detail is not explicitly confirmed, answer from what IS in the context.\n"
    "- If a Calculation or web result in the context already answers the question, use "
    "it directly and do not cite unrelated document chunks just because they were "
    "retrieved.\n"
    "- If the context genuinely contains no information relevant to the question, "
    "start your reply with exactly 'I do not know based on the provided document.' "
    "in English, followed by the same sentence in the question's language if that "
    "is not English.\n"
    "- Otherwise answer in the same language as the question.\n"
    "- Do not speculate or add information beyond what is in the context.\n"
    "- Respond in plain text only. Do not use markdown, bullet points, bold, or any special formatting.\n\n"
    "Context:\n{context}"
)

_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", _SYSTEM_PROMPT),
        MessagesPlaceholder("chat_history", optional=True),
        ("human", "{input}"),
    ]
)

CALC_TAG = "calc"

_CITATION_TAG_RE = re.compile(r"\[\[([^\[\]]+)\]\]")
_MALFORMED_TAG_LIST_RE = re.compile(r"\[(\[[^\[\]]+\](?:\s*,\s*\[[^\[\]]+\])+)\]")
_INNER_TAG_RE = re.compile(r"\[([^\[\]]+)\]")


def citation_tag(doc: Document) -> str:
    """The exact [[...]] tag content a source is cited by, shared with the critic's filter."""
    if doc.metadata.get("source") == "web":
        return f"web:{doc.metadata.get('url', '')}"
    return f"{doc.metadata.get('ref', '')}:{doc.metadata.get('page', '')}"


def _source_block(doc: Document) -> str:
    text = doc.metadata.get("original_content") or doc.page_content
    tag = f"[[{citation_tag(doc)}]]"
    if doc.metadata.get("source") == "web":
        title = doc.metadata.get("title", "")
        return f"Source {tag} ({title}):\n{text}"
    return f"Source {tag}:\n{text}"


def _build_context(documents: List[Document], tool_usage: dict) -> str:
    blocks = [_source_block(doc) for doc in documents]
    calc = tool_usage.get("calculator", {}) if tool_usage else {}
    if calc.get("used"):
        blocks.append(f"Source [[{CALC_TAG}]]:\nCalculation: {calc.get('expression')} = {calc.get('result')}")
    return "\n\n".join(blocks) if blocks else "(no context available)"


def _normalize_citation_tags(text: str) -> str:
    """Fold a malformed [[tag1], [tag2]] list into separate [[tag1]][[tag2]] tags.

    The model occasionally cites multiple sources for one claim as a single
    bracketed list instead of repeating the [[tag]] format. Left as-is, that
    text doesn't match _CITATION_TAG_RE (nested brackets) and leaks straight
    through to the user unstripped.
    """

    def _expand(match: "re.Match[str]") -> str:
        return "".join(f"[[{tag}]]" for tag in _INNER_TAG_RE.findall(match.group(1)))

    return _MALFORMED_TAG_LIST_RE.sub(_expand, text)


def extract_cited_tags(text: str) -> set[str]:
    """The set of [[...]] tag contents actually referenced in a generation."""
    text = _normalize_citation_tags(text)
    return {tag.strip() for tag in _CITATION_TAG_RE.findall(text)}


def strip_citation_tags(text: str) -> str:
    """Remove [[...]] citation tags for the user-facing answer. UI cites via `cited_documents`."""
    cleaned = _normalize_citation_tags(text)
    cleaned = _CITATION_TAG_RE.sub("", cleaned)
    cleaned = re.sub(r" {2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]+([.,;:!?])", r"\1", cleaned)
    return cleaned.strip()


@lru_cache(maxsize=1)
def _get_chain():
    from rag.usage import capture_from_message

    llm = get_llm()
    return _PROMPT | llm | RunnableLambda(capture_from_message) | StrOutputParser()


def synthesizer_node(state: GraphState, config: RunnableConfig = {}) -> GraphState:
    """Write the answer with inline [[ref:page]] / [[web:url]] citation tags.

    On a critic revision, the reason is folded into the input and the previous
    draft is shown so the model can address it directly.
    """
    try:
        question = state["question"]
        feedback = state.get("critic_feedback", "")

        on_step = get_on_step(config)
        if on_step:
            on_step("Revising answer…" if feedback.startswith("revise:") else "Writing answer…")

        session_id = state.get("session_id", "")
        chat_history: List[BaseMessage] = []
        if session_id:
            from rag.agents.memory import get_memory
            chat_history = get_memory(session_id, state["doc_id"]).messages[-6:]  # last 3 exchanges

        if feedback.startswith("revise:"):
            reason = feedback.split(":", 1)[1].strip()
            question = (
                f"{question}\n\n"
                f"(Your previous answer was rejected by the critic for this reason: {reason}. "
                f"Previous draft: {state.get('raw_generation', '')}\n"
                f"Write an improved answer that fixes this issue.)"
            )

        context = _build_context(state.get("documents", []), state.get("tool_usage", {}))
        chain = _get_chain()
        raw_answer = chain.invoke(
            {"context": context, "input": question, "chat_history": chat_history}, config=config
        )

        return {"raw_generation": raw_answer, "generation": strip_citation_tags(raw_answer), "error": ""}

    except Exception as e:
        logger.error(f"Synthesizer failed, falling back to raw chunks: {e}")
        raw = "\n\n".join(
            (doc.metadata.get("original_content") or doc.page_content)[:300]
            for doc in state.get("documents", [])
        )
        fallback = (
            f"Answer generation failed due to an API error. "
            f"Here are the relevant excerpts from the document:\n\n{raw}"
            if raw else "Answer generation failed and no relevant content was found."
        )
        # Mark as grounded to avoid burning through the revision budget on an API outage,
        # and record the failure so the API does not cache this fallback text.
        return {
            "generation": fallback,
            "raw_generation": fallback,
            "grounded": True,
            "error": f"Answer generation failed: {e}",
        }
