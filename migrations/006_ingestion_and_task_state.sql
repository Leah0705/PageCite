-- Migration 006: background ingestion state and ingestion cost history.

-- Task state used by the Celery worker and the stop / reindex endpoints.
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS error_message       TEXT,
    ADD COLUMN IF NOT EXISTS celery_task_id      VARCHAR,
    ADD COLUMN IF NOT EXISTS stopped_at_progress INTEGER,
    ADD COLUMN IF NOT EXISTS stopped_at_step     VARCHAR;

-- Token and cost usage of each ingestion run (contextual retrieval, figure captions).
CREATE TABLE IF NOT EXISTS ingestion_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     TEXT NOT NULL REFERENCES users(clerk_id),
    doc_id      UUID REFERENCES documents(id) ON DELETE SET NULL,
    tokens_in   INTEGER NOT NULL DEFAULT 0,
    tokens_out  INTEGER NOT NULL DEFAULT 0,
    cost_usd    DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Deleting a document must keep its cost history and conversations, so both
-- foreign keys use ON DELETE SET NULL. Databases created before this rule get
-- their constraint rebuilt once; later runs find SET NULL and skip it.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.referential_constraints
        WHERE constraint_schema = current_schema()
          AND constraint_name = 'ingestion_events_doc_id_fkey'
          AND delete_rule <> 'SET NULL'
    ) THEN
        ALTER TABLE ingestion_events DROP CONSTRAINT ingestion_events_doc_id_fkey;
        ALTER TABLE ingestion_events ADD CONSTRAINT ingestion_events_doc_id_fkey
            FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE SET NULL;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.referential_constraints
        WHERE constraint_schema = current_schema()
          AND constraint_name = 'conversations_doc_id_fkey'
          AND delete_rule <> 'SET NULL'
    ) THEN
        ALTER TABLE conversations DROP CONSTRAINT conversations_doc_id_fkey;
        ALTER TABLE conversations ADD CONSTRAINT conversations_doc_id_fkey
            FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE SET NULL;
    END IF;
END
$$;
