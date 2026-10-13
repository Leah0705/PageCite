# Changelog

Notable engineering milestones for PageCite, an agentic RAG system that turns work documents into a private knowledge base with page-cited answers. Newest first. Versions follow [Semantic Versioning](https://semver.org/).

## [3.0.0] - 2026-08-24

### Added
- Multi-agent architecture: a Researcher / Synthesizer / Critic pipeline (LangGraph) with a revision loop replaces the linear pipeline, with the Critic routing drafts back for revision on hallucination or missing citations.
- Tool calling: the Researcher autonomously invokes web search (Tavily) and a sandboxed calculator via Gemini function calling, with no hardcoded trigger rules.

### Changed
- Citation filtering: only sources actually referenced in the final answer are surfaced, not every chunk retrieved.

### Fixed
- Eval harness reproducibility (`use_tools=False`) and a pre-existing crash in the eval runner.

## [2.3.1] - 2026-07-17
### Fixed
- SSE streaming endpoint returning no response due to a naming collision.

## [2.3.0] - 2026-06-09
### Added
- MCP (Model Context Protocol) server exposing document search as native tools for Claude Desktop and Cursor, with per-user API key auth.

## [2.2.0] - 2026-06-09
### Added
- DOCX ingestion via LibreOffice conversion, sharing the same OCR pipeline as PDFs.

### Fixed
- Historical cost data now survives document deletion.

## [2.1.0] - 2026-06-03
### Added
- Per-query token/cost tracking with a usage dashboard, Redis-backed rate limiting, and PII redaction (Presidio) on every query before it reaches the LLM.

### Fixed
- SSE queries persist to Postgres even if the client disconnects mid-stream.

## [2.0.0] - 2026-05-25
### Added
- Celery-based async ingestion queue with live progress tracking.

## [1.7.0] - 2026-05-23
### Added
- Migrated to Postgres + pgvector with hybrid search (dense HNSW + sparse full-text, fused via RRF), replacing Chroma.
- Clerk JWT auth with per-user document isolation.

## [1.6.0] - 2026-05-21
### Added
- Inline PDF viewer with citation-click-to-page-jump.

### Fixed
- Query rewriting for misspelled inputs.

## [1.5.1] - 2026-05-17
### Fixed
- OCR binary resolution and a React hydration warning.

## [1.5.0] - 2026-05-16
### Added
- Next.js frontend with SSE streaming chat and per-session memory.

### Changed
- Replaced an LLM router call with instant keyword detection, cutting latency and cost per query.

## [1.4.0] - 2026-05-09
### Added
- Multimodal ingestion: table-aware PDF parsing and figure captioning via Gemini vision.

## [1.3.1] - 2026-05-08
### Changed
- Docker build pipeline switched to `uv`, cutting build time significantly.

## [1.3.0] - 2026-05-07
### Added
- HyDE (Hypothetical Document Embeddings) fallback retrieval and a Redis semantic cache for near-identical queries.

## [1.2.0] - 2026-05-06
### Added
- Contextual Retrieval (Anthropic's technique): situating context prepended to each chunk before embedding.

### Improved
- RAGAS scores on a 30-question golden set: faithfulness +3.1pp, context precision +6.9pp, context recall +13.3pp.

## [1.1.0] - 2026-05-06
### Added
- RAGAS evaluation harness with a 30-question golden dataset and automated per-question scoring.

## [1.0.0] - 2026-04-12
### Added
- Agentic RAG pipeline (LangGraph): router, grader, generator, hallucination check, query rewriter.
- Hybrid search (BM25 + dense retrieval) with cross-encoder reranking.

## [0.1.0] - 2026-03-04
### Added
- Initial RAG pipeline: PDF ingestion, vector indexing, and cited Q&A over FastAPI.
