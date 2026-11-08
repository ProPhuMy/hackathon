-- Migration 002: Version metadata table and index for emission ordering

CREATE TABLE IF NOT EXISTS matcher_version (
    id INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_outbox_event_id ON outbox(event_id);
