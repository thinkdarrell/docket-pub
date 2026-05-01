"""Drop deprecated singular FK columns from votes.

PR2 of the N:M matcher redesign. Migration 009 introduced vote_agenda_items
as the canonical store for vote↔agenda links; migration 010 backfilled the
prior matches into it. PR1 (the matcher rewrite + reader rewrite) shipped
with these singular columns left in place as rollback insurance.

Now that PR1 is verified live and reads exclusively from vote_agenda_items,
the singular columns can be dropped.

Columns removed:
  - votes.agenda_item_id   (replaced by vote_agenda_items.agenda_item_id, N:M)
  - votes.match_method     (now per-link on vote_agenda_items)
  - votes.match_confidence (now per-link on vote_agenda_items)
"""

SQL_UP = """
ALTER TABLE votes DROP COLUMN IF EXISTS agenda_item_id;
ALTER TABLE votes DROP COLUMN IF EXISTS match_method;
ALTER TABLE votes DROP COLUMN IF EXISTS match_confidence;
"""

SQL_DOWN = """
-- Rollback re-adds the columns as nullable (no FK on agenda_item_id since
-- the original migration's CASCADE-or-not behavior would need re-deriving;
-- if rolling back is needed, follow with a manual backfill from
-- vote_agenda_items).
ALTER TABLE votes ADD COLUMN IF NOT EXISTS agenda_item_id INTEGER REFERENCES agenda_items(id);
ALTER TABLE votes ADD COLUMN IF NOT EXISTS match_method TEXT;
ALTER TABLE votes ADD COLUMN IF NOT EXISTS match_confidence REAL;
"""
