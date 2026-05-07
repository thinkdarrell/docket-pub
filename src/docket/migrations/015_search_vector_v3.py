"""Search-vector v3: index JSONB extracted_facts + weighted headline/why_it_matters.

The Smart Brevity v3 rewrite moves critical entity strings (vendor names,
addresses, parcel IDs, ward/district, neighborhood) into
agenda_items.extracted_facts JSONB and shrinks the long-form summary
into headline + why_it_matters.

Migration 013 extended the trigger to cover headline + why_it_matters + summary,
but it still reads only scalar columns — it never reads JSONB. Without this
fix, a citizen searching for "Southeastern Sealcoating" or "Highland Park" or
a parcel PIN returns nothing when the term only appears in extracted_facts.

This migration replaces the trigger function (CREATE OR REPLACE — idempotent)
to also tokenize:
  - headline (weight A — top tier with title)
  - why_it_matters (weight B with description)
  - extracted_facts->>'counterparty' (weight B — vendor names matter)
  - extracted_facts->'location'->>{address,neighborhood,ward_or_district,parcel_id}
    (weight C)
  - summary stays at weight D until Phase 4's Migration 014 drops the column.

Note: the spec draft mentioned raw_text at weight C, but agenda_items has no
raw_text column (raw_text lives on the votes table). The line is omitted here.

Relationship to Phase 4 (Migration 014):
  Migration 014 will also do a CREATE OR REPLACE on this same function to drop
  the summary term before dropping the column. The two migrations must remain
  in numeric order (015 before 014 would be wrong; but Phase 4 does 014 and
  this is 015 — Phase 4's 014 is NOT YET REGISTERED in runner.py, so order
  is enforced by appending 015 here and 014 will slot between 013 and 015 when
  Phase 4 is built). In practice, the order is:
    013 (add columns) → 015 (this: JSONB in trigger) → 014 (drop summary)
  This numbering is intentional — 015 must land on feat/impact-first-phase-2
  before Phase 3 backfill (~37K items) so search vectors are correct from
  day one of the backfill.

DO NOT add a bulk UPDATE inside this migration. The existing-row recompute
is done separately via scripts/backfill_search_vector_v3.py — batched at 5K
rows with a sleep between batches, per the Railway bulk-UPDATE rule.
"""

from __future__ import annotations

SQL_UP = r"""
CREATE OR REPLACE FUNCTION agenda_items_search_update() RETURNS trigger AS $$
BEGIN
  NEW.search_vector :=
       setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A')
    || setweight(to_tsvector('english', coalesce(NEW.headline, '')), 'A')
    || setweight(to_tsvector('english', coalesce(NEW.description, '')), 'B')
    || setweight(to_tsvector('english', coalesce(NEW.why_it_matters, '')), 'B')
    || setweight(to_tsvector('english',
         coalesce(NEW.extracted_facts->>'counterparty', '')), 'B')
    || setweight(to_tsvector('english',
         coalesce(NEW.extracted_facts->'location'->>'address', '')), 'C')
    || setweight(to_tsvector('english',
         coalesce(NEW.extracted_facts->'location'->>'neighborhood', '')), 'C')
    || setweight(to_tsvector('english',
         coalesce(NEW.extracted_facts->'location'->>'ward_or_district', '')), 'C')
    || setweight(to_tsvector('english',
         coalesce(NEW.extracted_facts->'location'->>'parcel_id', '')), 'C')
    || setweight(to_tsvector('english', coalesce(NEW.summary, '')), 'D');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

# Revert to Migration 013's function body (title+description+headline+why_it_matters+summary,
# unweighted). This is the state installed by 013's SQL_UP; reverting 015 should land
# exactly there so that a down→up cycle on 015 is idempotent with 013.
SQL_DOWN = r"""
CREATE OR REPLACE FUNCTION agenda_items_search_update() RETURNS trigger AS $$
BEGIN
  NEW.search_vector := to_tsvector('english',
    COALESCE(NEW.title, '')          || ' ' ||
    COALESCE(NEW.description, '')    || ' ' ||
    COALESCE(NEW.headline, '')       || ' ' ||
    COALESCE(NEW.why_it_matters, '') || ' ' ||
    COALESCE(NEW.summary, '')
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""
