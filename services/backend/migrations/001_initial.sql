-- Migration 001: Initial schema for matcher journal, canonical fridge events, and outbox

CREATE TABLE IF NOT EXISTS matcher_journal (
    seq BIGSERIAL PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('person', 'item', 'tick')),
    payload JSONB NOT NULL,
    event_id TEXT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS fridge_events (
    event_id TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS outbox (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES fridge_events(event_id),
    topic TEXT NOT NULL DEFAULT 'fridge.event',
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'published')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_outbox_pending ON outbox(id) WHERE status = 'pending';
