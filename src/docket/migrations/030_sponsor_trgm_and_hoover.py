"""Migration 030 — sponsor trigram index + Hoover council_type fix.

Two P3 carry-forwards bundled in one migration:

1. Trigram index on agenda_items.sponsor (TEXT column, no FK to council_members).
   Supports the ILIKE %name% substring match used by:
   - member_detail sponsorship count
   - query.list_related_items_by_sponsor (P4-2 §5.3)
   pg_trgm extension already enabled by migration 013.

2. Correct Hoover council_type from "Mayor-council" to "Council-manager"
   (PR #55 review note). Idempotent — leaves correct value in place.
"""
from __future__ import annotations


SQL_UP = r"""
CREATE INDEX IF NOT EXISTS idx_agenda_items_sponsor_trgm
    ON agenda_items USING gin (sponsor gin_trgm_ops);

UPDATE municipalities
    SET metadata = jsonb_set(metadata, '{council_type}', '"Council-manager"')
    WHERE slug = 'hoover';
"""

SQL_DOWN = r"""
DROP INDEX IF EXISTS idx_agenda_items_sponsor_trgm;
"""
