-- Migration 003: Idempotent people roster metadata table
CREATE TABLE IF NOT EXISTS people (
    person_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
