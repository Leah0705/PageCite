-- Run after 002_pgvector.sql.
-- Adds token and cost tracking columns to the messages table.

ALTER TABLE messages
    ADD COLUMN IF NOT EXISTS tokens_in  INTEGER,
    ADD COLUMN IF NOT EXISTS tokens_out INTEGER,
    ADD COLUMN IF NOT EXISTS cost_usd   DOUBLE PRECISION;
