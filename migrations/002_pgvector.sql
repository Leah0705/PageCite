-- Run after 001_init.sql. Requires the pgvector extension (available on Supabase by default).

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS chunks (
    id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id   UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ref      TEXT NOT NULL,          -- human-readable id, e.g. "<doc_id>_p3_c7"
    content  TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    embedding vector(768),           -- EMBEDDING_DIM in rag/llm.py
    tsv      tsvector
);

CREATE UNIQUE INDEX IF NOT EXISTS chunks_ref_idx ON chunks (ref);
CREATE INDEX  IF NOT EXISTS chunks_doc_id_idx  ON chunks (doc_id);

-- HNSW index for fast approximate nearest-neighbour search (cosine distance)
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
    ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- GIN index for full-text search via ts_rank
CREATE INDEX IF NOT EXISTS chunks_tsv_gin_idx ON chunks USING GIN (tsv);

-- Trigger to keep tsv column current on every insert/update
CREATE OR REPLACE FUNCTION chunks_tsv_update() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    NEW.tsv := to_tsvector('english', COALESCE(NEW.content, ''));
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS chunks_tsv_trigger ON chunks;
CREATE TRIGGER chunks_tsv_trigger
    BEFORE INSERT OR UPDATE OF content ON chunks
    FOR EACH ROW EXECUTE FUNCTION chunks_tsv_update();
