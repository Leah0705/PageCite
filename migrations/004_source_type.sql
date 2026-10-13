-- Migration 004: DOCX support
-- Adds source_type to documents.

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS source_type  VARCHAR NOT NULL DEFAULT 'pdf';
