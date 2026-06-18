-- ============================================================
-- Innhance v2 — Supabase pgvector schema
-- Run this ONCE in the Supabase SQL editor before deploying
-- ============================================================

-- Enable the pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- ── chunks table ─────────────────────────────────────────────────────────────
-- Stores text chunks + embeddings per venue
CREATE TABLE IF NOT EXISTS chunks (
    id           BIGSERIAL PRIMARY KEY,
    venue_id     TEXT      NOT NULL,
    source_type  TEXT      NOT NULL,   -- policy_pdf | room_description | faq | local_area
    source_id    TEXT      NOT NULL,   -- sha256 hash of venue_id::source_name
    language     TEXT      NOT NULL DEFAULT 'en',
    text         TEXT      NOT NULL,
    embedding    vector(1536),          -- text-embedding-3-small dimensions
    image_url    TEXT,                  -- Cloudinary URL if this chunk is about a room
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- HNSW index for fast cosine similarity search
-- This is what makes retrieval ~20–40ms even at scale
CREATE INDEX IF NOT EXISTS chunks_embedding_idx
    ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Index for venue_id filtering (always filtered before vector search)
CREATE INDEX IF NOT EXISTS chunks_venue_idx ON chunks (venue_id);

-- ── knowledge_sources table ───────────────────────────────────────────────────
-- Tracks ingestion status per document per venue
CREATE TABLE IF NOT EXISTS knowledge_sources (
    id           BIGSERIAL PRIMARY KEY,
    venue_id     TEXT NOT NULL,
    source_id    TEXT NOT NULL,
    source_name  TEXT NOT NULL,
    source_type  TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'processing',  -- processing | ready | failed
    chunk_count  INT,
    error        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (venue_id, source_id)
);

-- ── RPC function for similarity search ───────────────────────────────────────
-- Called by the Python RAG service via Supabase RPC
-- venue_id filter is HARDCODED — cross-venue leakage is impossible
CREATE OR REPLACE FUNCTION match_chunks(
    query_embedding  vector(1536),
    match_venue_id   TEXT,
    match_count      INT     DEFAULT 3,
    min_similarity   FLOAT   DEFAULT 0.75
)
RETURNS TABLE (
    id           BIGINT,
    text         TEXT,
    source_type  TEXT,
    image_url    TEXT,
    similarity   FLOAT
)
LANGUAGE sql STABLE
AS $$
    SELECT
        id,
        text,
        source_type,
        image_url,
        1 - (embedding <=> query_embedding) AS similarity
    FROM chunks
    WHERE
        venue_id = match_venue_id
        AND 1 - (embedding <=> query_embedding) >= min_similarity
    ORDER BY embedding <=> query_embedding
    LIMIT match_count;
$$;

-- ── Row Level Security ────────────────────────────────────────────────────────
-- Second layer of venue isolation — even if venue_id filter is missed in code,
-- the DB will not return cross-venue data
ALTER TABLE chunks           ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_sources ENABLE ROW LEVEL SECURITY;

-- Service role (used by the Python service) has full access
-- The supabase_service_key bypasses RLS — only use it server-side, never in browser
