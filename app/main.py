from __future__ import annotations

import logging
import os
import warnings

os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
logging.getLogger("unstructured").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore", message=".*max_size.*", category=FutureWarning)

import asyncio
import hashlib
import json
import secrets
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator, List, Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from langchain_core.documents import Document

from sqlalchemy import text

import redis as _redis_mod

from app.auth import ClerkUser, current_user
from app.db import get_db
from app.migrate import apply_migrations
from app.models import ApiKey, Conversation, Document as DocModel, IngestionEvent, Message, User
from app.pricing import compute_cost
from app.ratelimit import check_and_consume
from app.redact import redact, restore
from app.storage import (
    delete_docx, delete_pdf, docx_path, get_storage_root,
    new_doc_id, pdf_path, save_docx, save_pdf,
)
from rag import cache as semantic_cache
from rag.agents.memory import clear_document_memory
from rag.agents.graph import run_agent
from rag.ingest import get_docx_pdf_path, index_document
from rag.llm import get_embeddings, get_llm
from rag.store import clear_document

APP_ENV = os.getenv("ENVIRONMENT", "local")

_redis_client = _redis_mod.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True
)


def _get_progress(doc_id: str) -> int:
    val = _redis_client.get(f"doc:{doc_id}:progress")
    return int(val) if val else 0


def _get_step(doc_id: str) -> str | None:
    return _redis_client.get(f"doc:{doc_id}:step")


async def _init_db() -> None:
    """Bring the schema up to date by applying migrations/*.sql (idempotent)."""
    applied = await asyncio.to_thread(apply_migrations)
    logger.info("Database schema up to date (%d migration files)", len(applied))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _init_db()
    get_embeddings()
    try:
        get_llm()
    except RuntimeError:
        pass
    yield


app = FastAPI(title="PageCite", version="3.0.0", lifespan=lifespan)

_cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],
)



async def _ensure_user(db: AsyncSession, user: ClerkUser) -> None:
    """Upsert the Clerk user into the users table on every authenticated request."""
    stmt = (
        pg_insert(User)
        .values(clerk_id=user.user_id, email=user.email)
        .on_conflict_do_nothing(index_elements=["clerk_id"])
    )
    await db.execute(stmt)
    await db.commit()


async def _get_doc_or_404(
    db: AsyncSession, doc_id: str, user_id: str
) -> DocModel:
    try:
        doc_uuid = uuid.UUID(doc_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Document not found.")
    result = await db.execute(
        select(DocModel).where(
            DocModel.id == doc_uuid,
            DocModel.user_id == user_id,
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return doc



class HealthResponse(BaseModel):
    status: str = "ok"
    environment: str = APP_ENV


class UploadResponse(BaseModel):
    doc_id: str
    filename: str
    status: str = "pending"
    source_type: str = "pdf"



class IndexResponse(BaseModel):
    doc_id: str
    chunks_indexed: int
    collection: str


class QueryRequest(BaseModel):
    doc_id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=2)
    top_k: int = Field(5, ge=1, le=20)
    session_id: Optional[str] = Field(None)


class Citation(BaseModel):
    ref: str
    page: int
    chunk_id: int
    source: str
    url: Optional[str] = None


class ToolUsageResponse(BaseModel):
    web_search: dict = Field(default_factory=lambda: {"used": False, "count": 0, "results": []})
    calculator: dict = Field(default_factory=lambda: {"used": False, "expression": "", "result": ""})


class QueryResponse(BaseModel):
    doc_id: str
    question: str
    answer: str
    citations: List[Citation]
    retrieved: int
    retries: int
    latency_ms: float
    from_cache: bool = False
    hyde_triggered: bool = False
    pii_redacted: bool = False
    tool_usage: Optional[ToolUsageResponse] = None


class DocRecord(BaseModel):
    doc_id: str
    filename: str
    uploaded_at: str
    status: str
    indexed: bool
    source_type: str = "pdf"
    index_time_s: Optional[float] = None
    page_count: Optional[int] = None
    progress_percent: int = 0
    step: Optional[str] = None
    ingestion_cost_usd: Optional[float] = None
    ingestion_tokens: Optional[int] = None


class DocStatusResponse(BaseModel):
    status: str
    progress_percent: int
    page_count: Optional[int] = None
    step: Optional[str] = None


class StreamQueryRequest(BaseModel):
    doc_id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=2)
    session_id: Optional[str] = Field(None)


class ApiKeyCreate(BaseModel):
    name: str = Field("Default", min_length=1, max_length=80)


class ApiKeyRecord(BaseModel):
    id: str
    name: str
    created_at: str
    last_used_at: Optional[str] = None


class ApiKeyCreated(BaseModel):
    id: str
    name: str
    key: str  # shown once, never stored
    created_at: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.get("/documents", response_model=List[DocRecord])
async def list_documents(
    user: ClerkUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> List[DocRecord]:
    await _ensure_user(db, user)
    result = await db.execute(
        select(DocModel)
        .where(DocModel.user_id == user.user_id)
        .order_by(DocModel.created_at.desc())
    )
    docs = result.scalars().all()

    # Aggregate ingestion cost/tokens per doc in one query
    ie_rows = await db.execute(
        select(
            IngestionEvent.doc_id,
            func.sum(IngestionEvent.cost_usd).label("cost"),
            func.sum(IngestionEvent.tokens_in + IngestionEvent.tokens_out).label("tokens"),
        )
        .where(IngestionEvent.user_id == user.user_id)
        .group_by(IngestionEvent.doc_id)
    )
    ingest_by_doc: dict = {
        str(row.doc_id): (row.cost, row.tokens)
        for row in ie_rows.all()
    }

    return [
        DocRecord(
            doc_id=str(doc.id),
            filename=doc.filename,
            uploaded_at=doc.created_at.isoformat(),
            status=doc.status,
            indexed=doc.status == "indexed",
            source_type=doc.source_type or "pdf",
            index_time_s=doc.index_time_s,
            page_count=doc.page_count,
            progress_percent=(
                _get_progress(str(doc.id)) if doc.status == "processing"
                else (100 if doc.status == "indexed"
                      else (doc.stopped_at_progress or 0) if doc.status == "stopped"
                      else 0)
            ),
            step=(
                _get_step(str(doc.id)) if doc.status == "processing"
                else (doc.stopped_at_step if doc.status == "stopped" else None)
            ),
            ingestion_cost_usd=ingest_by_doc.get(str(doc.id), (None, None))[0],
            ingestion_tokens=ingest_by_doc.get(str(doc.id), (None, None))[1],
        )
        for doc in docs
    ]


_ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".docx"}
_MIME_ALLOWLIST = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/octet-stream",  # some browsers send this for .docx
}


@app.post("/documents", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    user: ClerkUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    fname = (file.filename or "").lower()
    ext = "." + fname.rsplit(".", 1)[-1] if "." in fname else ""
    if ext not in _ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Only PDF and DOCX files are supported.",
        )

    await _ensure_user(db, user)

    doc_id = new_doc_id()
    content = await file.read()
    source_type = "docx" if ext == ".docx" else "pdf"

    if source_type == "pdf":
        save_pdf(pdf_path(doc_id), content)
    else:
        save_docx(docx_path(doc_id), content)

    doc = DocModel(
        id=uuid.UUID(doc_id),
        user_id=user.user_id,
        filename=file.filename,
        status="pending",
        source_type=source_type,
    )
    db.add(doc)
    await db.commit()

    from worker.tasks import ingest_document as _enqueue_ingest
    task = _enqueue_ingest.delay(doc_id)
    doc.celery_task_id = task.id
    await db.commit()

    return UploadResponse(doc_id=doc_id, filename=file.filename or "", status="pending", source_type=source_type)



@app.post("/documents/{doc_id}/index", response_model=IndexResponse)
async def index(
    doc_id: str,
    user: ClerkUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> IndexResponse:
    await _ensure_user(db, user)
    doc = await _get_doc_or_404(db, doc_id, user.user_id)

    t0 = time.perf_counter()
    chunks_indexed, collection_name, page_count, _, _ = index_document(doc_id)
    index_time_s = time.perf_counter() - t0

    doc.status = "indexed"
    doc.index_time_s = round(index_time_s, 1)
    doc.page_count = page_count
    await db.commit()

    return IndexResponse(
        doc_id=doc_id,
        chunks_indexed=chunks_indexed,
        collection=collection_name,
    )


@app.post("/documents/{doc_id}/index/stream")
async def index_stream(
    doc_id: str,
    user: ClerkUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    await _ensure_user(db, user)
    doc = await _get_doc_or_404(db, doc_id, user.user_id)

    async def event_stream() -> AsyncIterator[str]:
        from app.db import async_session_factory

        queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def on_progress(msg: str) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, ("status", msg))

        t0 = time.perf_counter()
        future = loop.run_in_executor(None, lambda: index_document(doc_id, on_progress))
        yield _sse("status", "Starting…")

        while not future.done():
            try:
                event, data = await asyncio.wait_for(queue.get(), timeout=0.5)
                yield _sse(event, data)
            except asyncio.TimeoutError:
                pass

        while not queue.empty():
            event, data = queue.get_nowait()
            yield _sse(event, data)

        try:
            chunks_indexed, _, page_count, _, _ = await future
        except Exception as e:
            yield _sse("error", str(e))
            return

        index_time_s = time.perf_counter() - t0

        # Update status in DB using a fresh session (we can't reuse the request session across threads)
        async with async_session_factory() as sess:
            result = await sess.execute(select(DocModel).where(DocModel.id == doc.id))
            d = result.scalar_one_or_none()
            if d:
                d.status = "indexed"
                d.index_time_s = round(index_time_s, 1)
                d.page_count = page_count
                await sess.commit()

        yield _sse("done", json.dumps({"chunks": chunks_indexed, "index_time_s": round(index_time_s, 1)}))

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/documents/{doc_id}/status", response_model=DocStatusResponse)
async def get_document_status(
    doc_id: str,
    user: ClerkUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> DocStatusResponse:
    await _ensure_user(db, user)
    try:
        doc_uuid = uuid.UUID(doc_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Document not found.")
    result = await db.execute(
        select(DocModel).where(DocModel.id == doc_uuid, DocModel.user_id == user.user_id)
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    if doc.status == "processing":
        progress = _get_progress(doc_id)
        step = _get_step(doc_id)
    elif doc.status == "indexed":
        progress = 100
        step = None
    elif doc.status == "stopped":
        progress = doc.stopped_at_progress or 0
        step = doc.stopped_at_step
    else:
        progress = 0
        step = None

    return DocStatusResponse(
        status=doc.status,
        progress_percent=progress,
        page_count=doc.page_count,
        step=step,
    )


@app.post("/documents/{doc_id}/stop", status_code=200)
async def stop_document(
    doc_id: str,
    user: ClerkUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _ensure_user(db, user)
    try:
        doc_uuid = uuid.UUID(doc_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Document not found.")
    result = await db.execute(
        select(DocModel).where(DocModel.id == doc_uuid, DocModel.user_id == user.user_id)
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    if doc.status not in ("pending", "processing"):
        raise HTTPException(status_code=400, detail="Document is not active.")

    if doc.celery_task_id:
        from worker.celery_app import celery_app as _celery
        try:
            _celery.control.revoke(doc.celery_task_id, terminate=True, signal="SIGTERM")
        except Exception:
            pass

    doc.status = "stopped"
    doc.stopped_at_progress = _get_progress(doc_id) or 0
    doc.stopped_at_step = _get_step(doc_id)
    await db.commit()
    return {"status": "stopped"}


@app.post("/documents/{doc_id}/reindex", status_code=200)
async def reindex_document(
    doc_id: str,
    user: ClerkUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _ensure_user(db, user)
    try:
        doc_uuid = uuid.UUID(doc_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Document not found.")
    result = await db.execute(
        select(DocModel).where(DocModel.id == doc_uuid, DocModel.user_id == user.user_id)
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    source_type = doc.source_type or "pdf"
    if source_type == "pdf" and not pdf_path(doc_id).exists():
        raise HTTPException(status_code=404, detail="Document file not found.")
    if source_type == "docx" and not docx_path(doc_id).exists():
        raise HTTPException(status_code=404, detail="Document file not found.")

    doc.status = "pending"
    doc.error_message = None
    await db.commit()
    semantic_cache.invalidate(doc_id)  # answers cached for the old index are stale

    from worker.tasks import ingest_document as _enqueue_ingest
    task = _enqueue_ingest.delay(doc_id)
    doc.celery_task_id = task.id
    await db.commit()

    return {"status": "pending", "doc_id": doc_id}


@app.delete("/documents/{doc_id}", status_code=204)
async def delete_doc(
    doc_id: str,
    user: ClerkUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _ensure_user(db, user)
    doc = await _get_doc_or_404(db, doc_id, user.user_id)

    source_type = doc.source_type or "pdf"
    if source_type == "pdf":
        delete_pdf(doc_id)
        figures_dir = get_storage_root() / "figures" / doc_id
        if figures_dir.exists():
            shutil.rmtree(figures_dir)
    elif source_type == "docx":
        delete_docx(doc_id)
        converted = get_docx_pdf_path(doc_id)
        if converted.exists():
            converted.unlink()
        figures_dir = get_storage_root() / "figures" / doc_id
        if figures_dir.exists():
            shutil.rmtree(figures_dir)

    clear_document(doc_id)
    semantic_cache.invalidate(doc_id)
    clear_document_memory(doc_id)
    await db.execute(delete(DocModel).where(DocModel.id == doc.id))
    await db.commit()


@app.get("/documents/{doc_id}/file")
async def get_document_file(
    doc_id: str,
    user: ClerkUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    await _ensure_user(db, user)
    doc = await _get_doc_or_404(db, doc_id, user.user_id)
    source_type = doc.source_type or "pdf"
    if source_type == "docx":
        # Serve the converted PDF from the docx folder so the inline viewer works.
        # Fall back to the original DOCX if conversion hasn't run yet.
        converted = get_docx_pdf_path(doc_id)
        if converted.exists():
            return FileResponse(converted, media_type="application/pdf", filename=converted.name)
        path = docx_path(doc_id)
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        return FileResponse(path, media_type=media_type, filename=path.name)
    path = pdf_path(doc_id)
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@app.get("/documents/{doc_id}/download")
async def download_document(
    doc_id: str,
    user: ClerkUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    await _ensure_user(db, user)
    doc = await _get_doc_or_404(db, doc_id, user.user_id)
    source_type = doc.source_type or "pdf"
    if source_type == "docx":
        path = docx_path(doc_id)
        if not path.exists():
            raise HTTPException(status_code=404, detail="File not found.")
        return FileResponse(
            path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=doc.filename,
        )
    path = pdf_path(doc_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(path, media_type="application/pdf", filename=doc.filename)


@app.post("/query", response_model=QueryResponse)
async def query(
    req: QueryRequest,
    user: ClerkUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> QueryResponse:
    await _ensure_user(db, user)
    allowed, retry_after = check_and_consume(user.user_id)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded.",
            headers={"Retry-After": str(retry_after)},
        )
    await _get_doc_or_404(db, req.doc_id, user.user_id)

    t0 = time.perf_counter()
    # Blocking work (embedding the question, Redis, Presidio, the agent's LLM calls)
    # runs in worker threads so one slow query cannot stall the event loop.
    cached = await asyncio.to_thread(semantic_cache.lookup, req.question, req.doc_id)
    if cached:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        raw = cached.get("citations", [])
        citations = [
            Citation(ref=c.get("ref", ""), page=c.get("page", -1),
                     chunk_id=c.get("chunk_id", -1), source=c.get("source", ""),
                     url=c.get("url"))
            for c in raw
        ]
        return QueryResponse(
            doc_id=req.doc_id, question=req.question, answer=cached["answer"],
            citations=citations, retrieved=len(citations), retries=0,
            latency_ms=round(latency_ms, 2), from_cache=True,
        )

    safe_question, pii_map = await asyncio.to_thread(redact, req.question)
    state, usage = await asyncio.to_thread(
        run_agent, question=safe_question, doc_id=req.doc_id, session_id=req.session_id or ""
    )
    answer = restore(state.get("generation", ""), pii_map)
    docs: List[Document] = state.get("documents", [])
    cited_docs: List[Document] = state.get("cited_documents", [])

    if not answer and not docs:
        raise HTTPException(status_code=404, detail="Document not indexed.")

    citations = (
        []
        if _is_no_answer(answer)
        else [
            Citation(ref=d.metadata.get("ref", ""), page=d.metadata.get("page", -1),
                     chunk_id=d.metadata.get("chunk_id", -1), source=d.metadata.get("source", ""),
                     url=d.metadata.get("url"))
            for d in cited_docs
        ]
    )
    latency_ms = (time.perf_counter() - t0) * 1000.0
    tool_usage = state.get("tool_usage", {})

    cost = (
        compute_cost("gemini-2.5-flash", usage.tokens_in, usage.tokens_out)
        if (usage.tokens_in + usage.tokens_out > 0)
        else 0.0
    )
    if _is_cacheable(answer, state):
        await asyncio.to_thread(
            semantic_cache.store, req.question, req.doc_id, answer, [c.model_dump() for c in citations]
        )
    await _persist_usage(db, user.user_id, req.doc_id, req.session_id, req.question, answer,
                         [c.model_dump() for c in citations], usage.tokens_in, usage.tokens_out, cost,
                         tool_usage)

    return QueryResponse(
        doc_id=req.doc_id, question=req.question, answer=answer,
        citations=citations, retrieved=len(docs), retries=state.get("retry_count", 0),
        latency_ms=round(latency_ms, 2), hyde_triggered=state.get("hyde_triggered", False),
        pii_redacted=bool(pii_map), tool_usage=tool_usage,
    )


@app.post("/query/stream")
async def query_stream(
    req: StreamQueryRequest,
    user: ClerkUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    await _ensure_user(db, user)
    await _get_doc_or_404(db, req.doc_id, user.user_id)

    cached = await asyncio.to_thread(semantic_cache.lookup, req.question, req.doc_id)

    if not cached:
        allowed, retry_after = check_and_consume(user.user_id)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded.",
                headers={"Retry-After": str(retry_after)},
            )

    sse_queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def _run_query() -> None:
        try:
            if cached:
                await sse_queue.put(_sse("status", "Retrieving from cache..."))
                for i, word in enumerate(cached["answer"].split(" ")):
                    await sse_queue.put(_sse("token", word if i == 0 else " " + word))
                    await asyncio.sleep(0.005)
                await sse_queue.put(_sse("citations", json.dumps(cached.get("citations", []))))
                await sse_queue.put(_sse("meta", json.dumps({"hyde_triggered": False, "pii_redacted": False, "from_cache": True})))
                await sse_queue.put(_sse("usage", json.dumps({"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0})))
                await sse_queue.put(_sse("done", ""))
                return

            safe_question, pii_map = await asyncio.to_thread(redact, req.question)
            if pii_map:
                await sse_queue.put(_sse("pii", ""))

            loop = asyncio.get_running_loop()
            step_queue: asyncio.Queue[str] = asyncio.Queue()

            def on_step(label: str) -> None:
                loop.call_soon_threadsafe(step_queue.put_nowait, label)

            future = loop.run_in_executor(
                None,
                lambda: run_agent(
                    question=safe_question,
                    doc_id=req.doc_id,
                    session_id=req.session_id or "",
                    on_step=on_step,
                ),
            )

            while not future.done():
                try:
                    label = await asyncio.wait_for(step_queue.get(), timeout=0.3)
                    await sse_queue.put(_sse("status", label))
                except asyncio.TimeoutError:
                    pass
            while not step_queue.empty():
                await sse_queue.put(_sse("status", step_queue.get_nowait()))

            state, usage = await future
            answer = restore(state.get("generation", ""), pii_map)
            docs: List[Document] = state.get("documents", [])
            cited_docs: List[Document] = state.get("cited_documents", [])

            if not answer and not docs:
                await sse_queue.put(_sse("error", "Document not indexed."))
                return
            if not answer:
                await sse_queue.put(_sse("error", "Could not generate an answer. Try rephrasing your question."))
                return

            citations_data = (
                []
                if _is_no_answer(answer)
                else [
                    {
                        "ref": d.metadata.get("ref", ""),
                        "page": d.metadata.get("page", -1),
                        "chunk_id": d.metadata.get("chunk_id", -1),
                        "source": d.metadata.get("source", ""),
                        "url": d.metadata.get("url"),
                        "text": d.page_content[:200],
                    }
                    for d in cited_docs
                ]
            )
            tool_usage = state.get("tool_usage", {})

            cost = (
                compute_cost("gemini-2.5-flash", usage.tokens_in, usage.tokens_out)
                if (usage.tokens_in + usage.tokens_out > 0)
                else 0.0
            )
            if _is_cacheable(answer, state):
                await asyncio.to_thread(
                    semantic_cache.store, req.question, req.doc_id, answer, citations_data
                )
            from app.db import async_session_factory
            async with async_session_factory() as sess:
                await _persist_usage(
                    sess, user.user_id, req.doc_id, req.session_id, req.question, answer,
                    citations_data, usage.tokens_in, usage.tokens_out, cost, tool_usage,
                )

            for i, word in enumerate(answer.split(" ")):
                await sse_queue.put(_sse("token", word if i == 0 else " " + word))
                await asyncio.sleep(0.005)

            await sse_queue.put(_sse("citations", json.dumps(citations_data)))
            await sse_queue.put(_sse("meta", json.dumps({
                "hyde_triggered": state.get("hyde_triggered", False),
                "pii_redacted": bool(pii_map),
            })))
            await sse_queue.put(_sse("usage", json.dumps({
                "tokens_in": usage.tokens_in,
                "tokens_out": usage.tokens_out,
                "cost_usd": round(cost, 6),
            })))
            await sse_queue.put(_sse("tool_usage", json.dumps(tool_usage)))
            await sse_queue.put(_sse("done", ""))

        except Exception as e:
            try:
                await sse_queue.put(_sse("error", str(e)))
            except Exception:
                pass
        finally:
            await sse_queue.put(None)

    asyncio.create_task(_run_query())

    async def event_stream() -> AsyncIterator[str]:
        while True:
            item = await sse_queue.get()
            if item is None:
                break
            yield item

    return StreamingResponse(event_stream(), media_type="text/event-stream")



class UsageResponse(BaseModel):
    total_cost_usd: float
    total_tokens: int


class UsageHistoryPoint(BaseModel):
    bucket: str
    tokens: int
    requests: int
    cost_usd: float


class UsageHistoryResponse(BaseModel):
    points: list[UsageHistoryPoint]


_PERIOD_INTERVALS: dict[str, str | None] = {
    "1h":  "1 hour",
    "24h": "24 hours",
    "7d":  "7 days",
    "30d": "30 days",
    "all": None,
}

_PERIOD_TRUNC: dict[str, str] = {
    "1h":  "minute",
    "24h": "hour",
    "7d":  "day",
    "30d": "day",
    "all": "day",
}


@app.get("/usage/me", response_model=UsageResponse)
async def get_my_usage(
    period: str = "30d",
    user: ClerkUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> UsageResponse:
    await _ensure_user(db, user)
    if period not in _PERIOD_INTERVALS:
        period = "30d"
    interval = _PERIOD_INTERVALS[period]
    time_filter_chat = f"AND m.created_at >= now() - INTERVAL '{interval}'" if interval else ""
    time_filter_ingest = f"AND ie.created_at >= now() - INTERVAL '{interval}'" if interval else ""
    result = await db.execute(
        text(f"""
            SELECT COALESCE(SUM(combined.cost), 0)   AS total_cost,
                   COALESCE(SUM(combined.tokens), 0) AS total_tokens
            FROM (
                SELECT m.cost_usd AS cost, (m.tokens_in + m.tokens_out) AS tokens
                FROM messages m
                JOIN conversations c ON c.id = m.conversation_id
                WHERE c.user_id = :uid AND m.role = 'assistant'
                {time_filter_chat}
                UNION ALL
                SELECT ie.cost_usd AS cost, (ie.tokens_in + ie.tokens_out) AS tokens
                FROM ingestion_events ie
                WHERE ie.user_id = :uid
                {time_filter_ingest}
            ) combined
        """),
        {"uid": user.user_id},
    )
    row = result.one()
    return UsageResponse(
        total_cost_usd=round(float(row.total_cost), 6),
        total_tokens=int(row.total_tokens),
    )


@app.get("/usage/me/history", response_model=UsageHistoryResponse)
async def get_my_usage_history(
    period: str = "30d",
    user: ClerkUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> UsageHistoryResponse:
    await _ensure_user(db, user)
    if period not in _PERIOD_INTERVALS:
        period = "30d"
    interval = _PERIOD_INTERVALS[period]
    trunc = _PERIOD_TRUNC.get(period, "day")
    time_filter_chat = f"AND m.created_at >= now() - INTERVAL '{interval}'" if interval else ""
    time_filter_ingest = f"AND ie.created_at >= now() - INTERVAL '{interval}'" if interval else ""
    result = await db.execute(
        text(f"""
            SELECT DATE_TRUNC('{trunc}', combined.created_at) AS bucket,
                   COUNT(*)                                    AS requests,
                   COALESCE(SUM(combined.tokens), 0)          AS tokens,
                   COALESCE(SUM(combined.cost), 0)            AS cost
            FROM (
                SELECT m.created_at,
                       (m.tokens_in + m.tokens_out) AS tokens,
                       m.cost_usd                   AS cost
                FROM messages m
                JOIN conversations c ON c.id = m.conversation_id
                WHERE c.user_id = :uid AND m.role = 'assistant'
                {time_filter_chat}
                UNION ALL
                SELECT ie.created_at,
                       (ie.tokens_in + ie.tokens_out) AS tokens,
                       ie.cost_usd                    AS cost
                FROM ingestion_events ie
                WHERE ie.user_id = :uid
                {time_filter_ingest}
            ) combined
            GROUP BY bucket
            ORDER BY bucket ASC
        """),
        {"uid": user.user_id},
    )
    rows = result.fetchall()
    points = [
        UsageHistoryPoint(
            bucket=row.bucket.isoformat() if row.bucket else "",
            tokens=int(row.tokens),
            requests=int(row.requests),
            cost_usd=round(float(row.cost), 6),
        )
        for row in rows
    ]
    return UsageHistoryResponse(points=points)



class ConversationMessageResponse(BaseModel):
    role: str
    content: str
    citations: list = []
    tool_usage: Optional[dict] = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    created_at: str = ""


@app.get("/conversations/{session_id}", response_model=List[ConversationMessageResponse])
async def get_conversation_messages(
    session_id: str,
    user: ClerkUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> List[ConversationMessageResponse]:
    await _ensure_user(db, user)
    try:
        conv_id = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found.")
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.user_id == user.user_id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Not found.")
    msgs_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.asc())
    )
    msgs = msgs_result.scalars().all()
    return [
        ConversationMessageResponse(
            role=m.role,
            content=m.content,
            citations=m.citations.get("items", []) if m.citations else [],
            tool_usage=m.citations.get("tool_usage") if m.citations else None,
            tokens_in=m.tokens_in or 0,
            tokens_out=m.tokens_out or 0,
            cost_usd=m.cost_usd or 0.0,
            created_at=m.created_at.isoformat() if m.created_at else "",
        )
        for m in msgs
    ]



async def _persist_usage(
    db: AsyncSession,
    user_id: str,
    doc_id: str,
    session_id: str | None,
    question: str,
    answer: str,
    citations: list,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
    tool_usage: dict | None = None,
) -> None:
    """Store or update a conversation + user/assistant message pair with usage info."""
    try:
        conv_id: uuid.UUID | None = None
        if session_id:
            try:
                conv_id = uuid.UUID(session_id)
            except ValueError:
                conv_id = None

        if conv_id is not None:
            # Verify the conversation actually exists, create it if the session is new
            existing = await db.get(Conversation, conv_id)
            if existing is None:
                conv = Conversation(
                    id=conv_id,
                    user_id=user_id,
                    doc_id=uuid.UUID(doc_id),
                )
                db.add(conv)
                await db.flush()
        else:
            conv = Conversation(
                user_id=user_id,
                doc_id=uuid.UUID(doc_id),
            )
            db.add(conv)
            await db.flush()
            conv_id = conv.id

        user_msg = Message(
            conversation_id=conv_id,
            role="user",
            content=question,
        )
        assistant_citations: dict = {"items": citations}
        if tool_usage:
            assistant_citations["tool_usage"] = tool_usage

        assistant_msg = Message(
            conversation_id=conv_id,
            role="assistant",
            content=answer,
            citations=assistant_citations,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
        )
        db.add(user_msg)
        db.add(assistant_msg)
        await db.commit()
    except Exception as _exc:
        logger.warning("_persist_usage failed (non-critical): %s", _exc)


_NO_ANSWER_PREFIXES = (
    "i do not know", "i don't know", "i cannot find", "i can't find",
    "no information", "not mentioned", "not found", "not provided",
    "not available in", "based on the provided document, i",
    "based on the provided context, i",
)


def _is_no_answer(text: str) -> bool:
    lowered = text.strip().lower()
    return any(lowered.startswith(p) for p in _NO_ANSWER_PREFIXES)


def _is_cacheable(answer: str, state: dict) -> bool:
    """Cache only real answers: no refusals, and no error text from a failed graph node
    (e.g. "No documents have been indexed..." or a synthesizer fallback)."""
    return bool(answer) and not state.get("error") and not _is_no_answer(answer)


def _sse(event: str, data: str) -> str:
    """Format one Server-Sent Event.

    Every line of the payload gets its own "data:" field, as the SSE spec requires,
    so a payload that contains a blank line can never end the frame early. The
    client joins the data lines back together with "\\n".
    """
    data_lines = "".join(f"data: {line}\n" for line in data.split("\n"))
    return f"event: {event}\n{data_lines}\n"


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


@app.post("/api-keys", response_model=ApiKeyCreated, status_code=201)
async def create_api_key(
    body: ApiKeyCreate,
    user: ClerkUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyCreated:
    await _ensure_user(db, user)
    raw_key = f"pc_{secrets.token_urlsafe(32)}"
    record = ApiKey(
        user_id=user.user_id,
        key_hash=_hash_key(raw_key),
        name=body.name,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return ApiKeyCreated(
        id=str(record.id),
        name=record.name,
        key=raw_key,
        created_at=record.created_at.isoformat(),
    )


@app.get("/api-keys", response_model=List[ApiKeyRecord])
async def list_api_keys(
    user: ClerkUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> List[ApiKeyRecord]:
    await _ensure_user(db, user)
    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.user_id == user.user_id)
        .order_by(ApiKey.created_at.desc())
    )
    rows = result.scalars().all()
    return [
        ApiKeyRecord(
            id=str(r.id),
            name=r.name,
            created_at=r.created_at.isoformat(),
            last_used_at=r.last_used_at.isoformat() if r.last_used_at else None,
        )
        for r in rows
    ]


@app.delete("/api-keys/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: str,
    user: ClerkUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        key_uuid = uuid.UUID(key_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Key not found.")
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_uuid, ApiKey.user_id == user.user_id)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Key not found.")
    await db.delete(record)
    await db.commit()


# ---------------------------------------------------------------------------
# MCP HTTP/SSE transport, mounted at /mcp for Cursor and other HTTP clients
# ---------------------------------------------------------------------------

try:
    from mcp.server.sse import SseServerTransport as _SseTransport
    from mcp_server.auth import validate_api_key as _validate_mcp_key
    from mcp_server.server import _user_id_var as _mcp_user_var
    from mcp_server.server import mcp as _mcp

    # Relative to the /mcp mount: the transport prepends the mount's root_path when it
    # tells the client where to POST, so the client receives /mcp/messages/?session_id=...
    _mcp_sse_transport = _SseTransport("/messages/")

    class _MCPAuthMiddleware:
        """Pure-ASGI middleware: validates X-API-Key before handing off to SSE."""

        def __init__(self, asgi_app):
            self._app = asgi_app

        async def __call__(self, scope, receive, send):
            if scope["type"] not in ("http", "websocket"):
                await self._app(scope, receive, send)
                return

            headers = {k.lower(): v for k, v in scope.get("headers", [])}
            raw_key = headers.get(b"x-api-key", b"").decode()
            user_id = _validate_mcp_key(raw_key)
            if not user_id:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [[b"content-type", b"application/json"]],
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": b'{"detail":"Invalid or missing API key"}',
                    }
                )
                return

            token = _mcp_user_var.set(user_id)
            try:
                await self._app(scope, receive, send)
            finally:
                _mcp_user_var.reset(token)

    from starlette.applications import Starlette
    from starlette.requests import Request as _StarletteRequest
    from starlette.responses import Response as _StarletteResponse
    from starlette.routing import Mount, Route

    async def _mcp_sse_handler(request: _StarletteRequest) -> _StarletteResponse:
        # Starlette calls a Route endpoint as endpoint(request), so the raw ASGI
        # callables are taken from the request object.
        async with _mcp_sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as (read, write):
            await _mcp._mcp_server.run(
                read, write, _mcp._mcp_server.create_initialization_options()
            )
        # The SSE response has already been sent; an empty Response keeps Starlette
        # from calling None when the client disconnects.
        return _StarletteResponse()

    _mcp_asgi = _MCPAuthMiddleware(
        Starlette(
            routes=[
                Route("/sse", endpoint=_mcp_sse_handler, methods=["GET"]),
                Mount("/messages/", app=_mcp_sse_transport.handle_post_message),
            ]
        )
    )
    app.mount("/mcp", _mcp_asgi)
    logger.info("MCP HTTP/SSE transport mounted at /mcp")

except ImportError:
    logger.warning("mcp package not installed, HTTP/SSE transport disabled")
