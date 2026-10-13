# PageCite

PageCite turns work documents such as policies, manuals, reports, and specifications into a private knowledge base. You upload PDF or DOCX files, ask questions in plain language, and get answers that are checked against the source and cite the pages they came from. Clicking a citation opens the built-in PDF viewer at that page.

Each question goes through three LangGraph agents. A **Researcher** retrieves passages, a **Synthesizer** writes an answer that tags every claim with its source, and a **Critic** checks the draft for unsupported claims and missing citations before the user sees it. The same knowledge base is also exposed through a Model Context Protocol (MCP) server, the protocol Claude Desktop and Cursor use to call external tools, so those assistants can search your documents directly.

## Features

- **Answers with page citations.** The Synthesizer tags each claim with a `[[ref:page]]` marker that names the source chunk. Only the chunks that the final answer actually cites are returned as citations, and each one links to its page in the PDF viewer.
- **Hybrid retrieval.** Dense search over a pgvector HNSW index and PostgreSQL full-text search run side by side. Their result lists are merged with Reciprocal Rank Fusion (RRF), which combines lists by rank position, and the merged candidates are re-scored by a cross-encoder reranker.
- **HyDE fallback.** When the best reranker score is below a threshold, Gemini writes a hypothetical answer passage and its embedding drives a second search. HyDE stands for Hypothetical Document Embeddings.
- **Contextual retrieval.** Before embedding, Gemini writes one sentence that places each chunk within its document, so a short passage keeps the context it needs to be found.
- **Self-checking answers.** The Critic can send a draft back to the Synthesizer up to two times.
- **Tool use.** If the retrieved passages are not enough, the Researcher can call Tavily web search or a sandboxed calculator through Gemini function calling.
- **Layout-aware ingestion.** The `unstructured` hi_res parser reads PDF layouts, with Tesseract OCR for scanned pages. Tables are kept whole as Markdown, figures are captioned by Gemini, and DOCX files are converted to PDF with LibreOffice so both formats share one pipeline.
- **Background ingestion.** A Celery worker indexes uploads and reports progress by stage. Users can stop or reindex a document at any time.
- **Multi-user by design.** Clerk JWT authentication, per-user data isolation, per-user API keys for MCP, Redis rate limits, PII masking with Presidio, and a token and cost dashboard.
- **Measured quality.** A RAGAS evaluation runner scores the pipeline on a 30-question golden dataset.

## Architecture

```mermaid
flowchart LR
    UI["Next.js web app"] -- "REST + SSE" --> API["FastAPI"]
    AI["Claude Desktop / Cursor"] -- "MCP over HTTP/SSE at /mcp" --> API
    AI -- "MCP over stdio" --> MCP["MCP server process"]
    API -- "enqueue ingestion" --> RS[("Redis Stack")]
    RS --> W["Celery worker"]
    API --> PG[("PostgreSQL + pgvector")]
    W --> PG
    MCP --> PG
    API --> RS
    API --> GM["Gemini 2.5 Flash"]
    W --> GM
```

PostgreSQL stores users, documents, conversations, cost records, and the chunk table with its vectors and full-text index. Redis Stack has five jobs: Celery broker, semantic cache built on RediSearch vector search, rate-limit counters, ingestion progress, and conversation memory. Embedding and reranking models run locally on CPU through sentence-transformers. Gemini handles generation, contextual sentences, figure captions, and HyDE passages.

### Ingestion

1. The API stores the uploaded file and queues a Celery task.
2. The worker converts DOCX to PDF, then parses the PDF with `unstructured` hi_res layout analysis and OCR.
3. Text is split into 800-character chunks with 100 characters of overlap. Tables stay whole as Markdown, and up to 30 figures per document are captioned.
4. When `CONTEXTUAL_RETRIEVAL` is on, Gemini adds a one-sentence context to every chunk.
5. Chunks are embedded and written to PostgreSQL. A trigger fills the `tsvector` column for full-text search.
6. The token cost of the run is recorded so the usage dashboard can show it.

### Answering a question

1. **Semantic cache.** If a near-identical question about the same document was answered before, with a cosine similarity of at least 0.97, the cached answer is returned.
2. **PII masking.** Presidio replaces email addresses, phone numbers, US SSNs, and card numbers with placeholders before any text reaches Gemini, and the placeholders are restored in the final answer.
3. **Researcher.** Hybrid search returns 24 candidates, the reranker keeps the best 6, and HyDE runs if the top score is below `HYDE_THRESHOLD`. Web search or the calculator is called only when the passages fall short.
4. **Synthesizer.** Writes the answer with citation tags, using the last three exchanges of the conversation as context.
5. **Critic.** Approves the draft or returns a reason for revision. After two revisions the last draft is accepted.
6. **Response.** Citation tags are stripped, the cited chunks are returned, and the exchange is saved with its token cost.

`POST /query/stream` sends progress events over Server-Sent Events (SSE) while the agents run, then sends the answer once the Critic has approved it.

## Design decisions

- **RRF instead of score blending.** Dense scores and `ts_rank` scores live on different scales. RRF uses only rank positions, so the two lists can be merged without calibrating one score against the other. Dense search catches paraphrases, and full-text search catches exact terms such as clause numbers or product codes.
- **A bounded review loop.** Every Critic pass adds an LLM call, so revisions are capped at two. If the Critic call itself fails, the draft is approved instead of blocking the user.
- **Progress streaming instead of token streaming.** Streaming tokens before the Critic finishes would show text that might be rewritten. The UI streams real progress steps instead, such as "Searching the document" and "Reviewing answer", and shows the answer once it has passed review.
- **Cache entries that cannot go stale.** The semantic cache never stores error text or refusals, drops a document's entries when it is reindexed or deleted, and keeps entries from different embedding models apart.
- **One source of truth for the schema.** The SQL files in `migrations/` are idempotent. The API applies all of them in one transaction on start-up, under an advisory lock so that parallel replicas do not collide. A test compares every ORM column with the migrated database.
- **Memory scoped to the document.** Conversation memory lives in Redis under `chat:{doc_id}:{session_id}`, so every API worker shares it. The API checks document ownership before running the agents, so a guessed session id cannot expose another user's history.

## Evaluation

The golden dataset in `eval/golden.jsonl` has 30 questions about *Attention Is All You Need* (Vaswani et al., 2017): 15 factual, 8 reasoning, 5 multi-hop, and 2 out-of-scope questions that the system should decline. The runner calls the pipeline with tools disabled, so scores measure document-grounded retrieval and synthesis only, and uses Gemini as the RAGAS judge.

Scores from the most recent full run:

<!-- EVAL-RESULTS-START -->
| Metric | Score | |
|---|---|---|
| `faithfulness` | 0.985 | ███████████████████ |
| `answer_relevancy` | 0.909 | ██████████████████ |
| `context_precision` | 0.784 | ███████████████ |
| `context_recall` | 0.917 | ██████████████████ |

_Evaluated on 30 questions · 2026-08-22 · full results in [`eval/results/latest.json`](eval/results/latest.json)_
<!-- EVAL-RESULTS-END -->

To reproduce, upload and index the paper from [arXiv:1706.03762](https://arxiv.org/abs/1706.03762), then run:

```bash
DOC_ID=<doc_id> make eval      # writes eval/results/<timestamp>.json and updates this table
```

Re-run the evaluation after changing the embedding model, the reranker, or the chunking settings. See [`eval/EVALUATION_GUIDE.md`](eval/EVALUATION_GUIDE.md) for the metric definitions and options.

## Getting started

### What you need

- Docker with Docker Compose
- A Gemini API key from [Google AI Studio](https://aistudio.google.com/)
- A [Clerk](https://clerk.com/) application: the publishable key, the secret key, and the JWT public key in PEM format
- Optional: a [Tavily](https://tavily.com/) API key. Without it, the web search tool returns no results.

### Run everything with Docker Compose

```bash
git clone https://github.com/Leah0705/PageCite.git
cd PageCite
cp .env.example .env        # fill in GOOGLE_API_KEY and the three Clerk values
docker compose up --build
```

Open <http://localhost:3000> for the web app. The API listens on port 8000 and serves interactive API docs at <http://localhost:8000/docs>. The first start downloads the embedding and reranker models into the `hf_cache` volume, so it takes a few minutes. The Clerk publishable key is baked into the web image at build time, so rebuild the `web` service after changing it.

### Local development

The backend needs Python 3.12 and three system tools for ingestion: Tesseract, Poppler, and LibreOffice. On macOS: `brew install tesseract poppler` and `brew install --cask libreoffice`.

```bash
docker compose up -d postgres redis                 # databases only

python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_lg             # language model used by Presidio
cp .env.example .env                                # add your keys

make run                                            # API on :8000, applies migrations on start-up
.venv/bin/celery -A worker.celery_app worker --loglevel=info   # in a second terminal

cd web
cp .env.local.example .env.local                    # Clerk keys for the frontend
npm ci && npm run dev                               # web app on :3000
```

On Linux, installing the CPU build of PyTorch first avoids downloading the CUDA wheels: `pip install torch --index-url https://download.pytorch.org/whl/cpu`.

With `ENVIRONMENT=local` and no `CLERK_JWT_KEY`, the API accepts any bearer token as a single development user. The web app still signs in through Clerk.

## Configuration

All settings are environment variables. `.env.example` lists them with their defaults.

| Variable | Default | Purpose |
|---|---|---|
| `GOOGLE_API_KEY` | | Gemini access, required |
| `TAVILY_API_KEY` | | Web search tool, optional |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, `CLERK_JWT_KEY` | | Clerk authentication |
| `DATABASE_URL` | `postgresql://pagecite:pagecite@localhost:5432/pagecite` | PostgreSQL with pgvector |
| `REDIS_URL` | `redis://localhost:6379` | Redis Stack |
| `CONTEXTUAL_RETRIEVAL` | `true` | Add a context sentence to each chunk before embedding |
| `EXTRACT_FIGURES` | `true` | Caption figures with Gemini during ingestion |
| `SEMANTIC_CACHE_THRESHOLD` | `0.97` | Minimum cosine similarity for a cache hit |
| `CACHE_TTL_SECONDS` | `86400` | Lifetime of a cached answer |
| `HYDE_THRESHOLD` | `0.3` | Reranker score below which HyDE runs |
| `EMBEDDING_MODEL` | `sentence-transformers/all-mpnet-base-v2` | Embedding model, must output 768-d vectors |
| `RERANK_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Cross-encoder reranker |
| `CHAT_MEMORY_TTL_SECONDS` | `604800` | How long a conversation is remembered |
| `RATE_LIMIT_PER_HOUR`, `RATE_LIMIT_PER_DAY` | `30`, `200` | Questions per user |
| `PII_REDACTION` | `true` | Mask PII before text reaches Gemini |

### Chinese and other languages

Text extraction keeps every script, and answers follow the language of the question. The default models are English, so `.env.example` includes a multilingual preset: `intfloat/multilingual-e5-base` for embeddings and `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` for reranking. After switching, reindex every document, because vectors from different models are not comparable. Then re-run the evaluation and re-check `SEMANTIC_CACHE_THRESHOLD` and `HYDE_THRESHOLD`, since both thresholds depend on the models' score ranges.

## Use the knowledge base from Claude Desktop or Cursor

1. Open **API Keys** in the web app and create a key. The key is shown once.
2. **Claude Desktop** starts the MCP server as a local process. Add this entry to `claude_desktop_config.json` and restart the app:

    ```json
    {
      "mcpServers": {
        "pagecite": {
          "command": "/absolute/path/to/pagecite/.venv/bin/python3",
          "args": ["-m", "mcp_server"],
          "env": {
            "PAGECITE_API_KEY": "pc_YOUR_KEY_HERE",
            "DATABASE_URL": "postgresql://pagecite:pagecite@localhost:5432/pagecite",
            "PYTHONPATH": "/absolute/path/to/pagecite"
          }
        }
      }
    }
    ```

3. **Cursor** connects over HTTP: point it at `http://localhost:8000/mcp/sse` and send the key in the `X-API-Key` header.

The server offers three tools: `search_documents` runs hybrid search across your documents or within one of them, `list_documents` lists your indexed documents, and `get_document` returns a document's metadata and a short preview. A key only reaches its owner's documents.

## API

The main endpoints are listed below, and interactive documentation is served at `/docs` on the API. Every endpoint except `/health` requires a Clerk bearer token.

| Method and path | Purpose |
|---|---|
| `POST /documents` | Upload a PDF or DOCX file and queue it for ingestion |
| `GET /documents` | List your documents with status, progress, and ingestion cost |
| `GET /documents/{id}/status` | Ingestion status and current stage |
| `POST /documents/{id}/stop`, `POST /documents/{id}/reindex` | Stop or restart ingestion |
| `GET /documents/{id}/file`, `GET /documents/{id}/download` | PDF for the viewer, original file for download |
| `DELETE /documents/{id}` | Delete a document with its chunks, cached answers, and chat memory |
| `POST /query/stream` | Ask a question, with progress, citations, and usage sent as SSE events |
| `POST /query` | Ask a question and receive one JSON response |
| `GET /conversations/{session_id}` | Messages of a conversation |
| `GET /usage/me`, `GET /usage/me/history` | Token and cost totals, overall and over time |
| `POST /api-keys`, `GET /api-keys`, `DELETE /api-keys/{id}` | Manage MCP API keys |

## Testing

```bash
make test        # backend tests (pytest)
make test-ui     # frontend tests (Jest)
make lint        # ruff
```

Most backend tests mock the database, Redis, and Gemini. The migration tests run against a real PostgreSQL when `DATABASE_URL` points to one and are skipped otherwise. GitHub Actions runs ruff, the backend tests with PostgreSQL, pgvector and Redis service containers, and the Jest tests with a TypeScript type check on every push to `main`.

## Project structure

```text
app/          FastAPI app: routes, auth, models, migrations runner, pricing, rate limits, PII masking
rag/          Retrieval pipeline
  agents/     LangGraph graph: researcher, synthesizer, critic, pipeline wiring, Redis memory
  chains/     Hybrid search, RRF, HyDE, reranking
  tools/      Web search and calculator tools
  ingest.py   Parsing, chunking, figure captions, contextual sentences
worker/       Celery app and ingestion task
mcp_server/   MCP server (stdio entry point and tools)
migrations/   SQL schema, applied in order on start-up
eval/         Golden dataset, RAGAS runner, results
web/          Next.js 16 frontend (React 19, Tailwind CSS, shadcn/ui, Clerk)
tests/        Backend tests
```

## Limitations

- A chat covers one document at a time. Searching across the whole library is available through the MCP `search_documents` tool, not yet in the chat UI.
- Each account sees only its own documents. There is no sharing between team members yet.
- Full-text search uses the PostgreSQL `english` configuration. For Chinese text, dense retrieval and the reranker do the work.
- The multilingual model preset has not been benchmarked on the golden dataset.
- Contextual retrieval sends the whole document with every chunk, so ingestion cost grows with the number of chunks times the document length.
- Uploaded files are stored in a local directory set by `STORAGE_DIR` rather than in object storage.

## Changelog

See [`CHANGELOG.md`](CHANGELOG.md).

## Author

Built by [Leah](https://github.com/Leah0705).
