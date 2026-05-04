"""Add vote_agenda_items join table and meetings.minutes_adopted_at."""

SQL_UP = """
CREATE TABLE IF NOT EXISTS vote_agenda_items (
    id                 SERIAL PRIMARY KEY,
    vote_id            INT NOT NULL REFERENCES votes(id) ON DELETE CASCADE,
    agenda_item_id     INT NOT NULL REFERENCES agenda_items(id) ON DELETE CASCADE,
    association_type   TEXT NOT NULL CHECK (association_type IN
                         ('explicit', 'consent_named', 'consent_implicit', 'positional')),
    match_method       TEXT,
    match_confidence   REAL NOT NULL CHECK (match_confidence BETWEEN 0 AND 1),
    excerpt_context    TEXT,
    provisional        BOOLEAN NOT NULL DEFAULT TRUE,
    is_manual          BOOLEAN NOT NULL DEFAULT FALSE,
    is_active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (vote_id, agenda_item_id)
);

CREATE INDEX IF NOT EXISTS idx_vai_vote ON vote_agenda_items(vote_id);
CREATE INDEX IF NOT EXISTS idx_vai_agenda_item ON vote_agenda_items(agenda_item_id);
CREATE INDEX IF NOT EXISTS idx_vai_provisional ON vote_agenda_items(provisional) WHERE provisional;
CREATE INDEX IF NOT EXISTS idx_vai_active ON vote_agenda_items(is_active) WHERE is_active;

ALTER TABLE meetings ADD COLUMN IF NOT EXISTS minutes_adopted_at TIMESTAMPTZ NULL;
"""

SQL_DOWN = """
ALTER TABLE meetings DROP COLUMN IF EXISTS minutes_adopted_at;
DROP INDEX IF EXISTS idx_vai_active;
DROP INDEX IF EXISTS idx_vai_provisional;
DROP INDEX IF EXISTS idx_vai_agenda_item;
DROP INDEX IF EXISTS idx_vai_vote;
DROP TABLE IF EXISTS vote_agenda_items;
"""
