"""Migration 020 — raise headline / why_it_matters length CHECK constraints
to match prompt v4 (60 → 80 chars and 200 → 280 chars).

Migration 013 added DB-level CHECK constraints alongside the Pydantic
field caps. PR #15 (2026-05-11) raised the Pydantic caps to allow dense
items more breathing room, but the DB constraints were missed — Stage 2
batch ingest fails with `chk_headline_length` violations on any item
whose validated headline length is between 61 and 80.

Caught during the v4 verification cron: process_batches couldn't ingest
the Wave 1 Stage 2 v4 batch because real prompt-v4 headlines that pass
Pydantic still tripped the DB check.

Up: relax both constraints to the new caps.
Down: re-tighten to the original caps — only safe if no row has
already been written that exceeds the old cap, otherwise the
constraint will refuse to enable. The rollback note in the comment
documents that.
"""

from __future__ import annotations


SQL_UP = r"""
ALTER TABLE agenda_items
    DROP CONSTRAINT IF EXISTS chk_headline_length,
    DROP CONSTRAINT IF EXISTS chk_why_it_matters_length,
    ADD CONSTRAINT chk_headline_length CHECK (
        headline IS NULL OR length(headline) <= 80
    ),
    ADD CONSTRAINT chk_why_it_matters_length CHECK (
        why_it_matters IS NULL OR length(why_it_matters) <= 280
    );
"""


SQL_DOWN = r"""
-- Will fail if any row exceeds the old caps; clean those out first if
-- a rollback is actually needed:
--   UPDATE agenda_items SET headline = NULL WHERE length(headline) > 60;
--   UPDATE agenda_items SET why_it_matters = NULL WHERE length(why_it_matters) > 200;
ALTER TABLE agenda_items
    DROP CONSTRAINT IF EXISTS chk_headline_length,
    DROP CONSTRAINT IF EXISTS chk_why_it_matters_length,
    ADD CONSTRAINT chk_headline_length CHECK (
        headline IS NULL OR length(headline) <= 60
    ),
    ADD CONSTRAINT chk_why_it_matters_length CHECK (
        why_it_matters IS NULL OR length(why_it_matters) <= 200
    );
"""
