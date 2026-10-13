-- The API applies every file in migrations/ in order on start-up (app/migrate.py).
-- Each file is idempotent, so it is also safe to run them by hand:
--   python -m app.migrate

CREATE TABLE IF NOT EXISTS users (
    clerk_id TEXT PRIMARY KEY,
    email    TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS documents (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    TEXT NOT NULL REFERENCES users(clerk_id) ON DELETE CASCADE,
    filename   TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'uploaded',   -- 'uploaded' | 'indexed'
    page_count INTEGER,
    index_time_s DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS documents_user_id_idx ON documents (user_id);

CREATE TABLE IF NOT EXISTS conversations (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    TEXT NOT NULL REFERENCES users(clerk_id) ON DELETE CASCADE,
    doc_id     UUID REFERENCES documents(id) ON DELETE SET NULL,
    title      TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS conversations_user_id_idx ON conversations (user_id);

CREATE TABLE IF NOT EXISTS messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,   -- 'user' | 'assistant'
    content         TEXT NOT NULL,
    citations       JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS messages_conversation_id_idx ON messages (conversation_id);
