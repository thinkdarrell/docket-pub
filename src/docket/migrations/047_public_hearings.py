"""Migration 047 — `public_hearings`, `public_hearing_items`, and Birmingham's `coming_up` flag.

A council resolution sets a public hearing for a later date, and more than
one agenda item can set the same hearing (an agenda repeated on a leftover
meeting row, a resolution that amends an earlier one). `public_hearings`
holds each hearing once: its date, its kind, its subject as read from the
item's title, the key by which two readings are told to be one hearing
(`subject_key`), a property count for a weed-lot resolution, and the
version of the reader's rules that read it. `public_hearing_items` links
every agenda item that set a hearing to it. The link's primary key is the
item: one title yields one reading, so an item belongs to at most one
hearing, and a later run moves its link and never doubles it.

The kind list in the CHECK is frozen text; its owner is `KINDS` in
`docket.enrichment.hearings`. `docket.services.hearings` owns every
statement on the two tables.

Birmingham's metadata gains `"coming_up": true`, the gate the hearing step
of ingest reads (and, later in the plan, the coming-up page and its feed),
in the shape of 037's `"briefing": true`.

Additive; the down removes the key and drops both tables.
Plan `birmingham-coming-up`, M2.
"""

from __future__ import annotations


SQL_UP = r"""
CREATE TABLE IF NOT EXISTS public_hearings (
    id              SERIAL PRIMARY KEY,
    municipality_id INTEGER NOT NULL REFERENCES municipalities(id) ON DELETE CASCADE,
    hearing_date    DATE NOT NULL,
    kind            TEXT NOT NULL CHECK (kind IN ('zoning', 'weed_lots', 'vacation', 'budget', 'other')),
    subject         TEXT NOT NULL,
    subject_key     TEXT NOT NULL,
    property_count  INTEGER NULL,
    rule_version    INTEGER NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (municipality_id, hearing_date, kind, subject_key)
);
CREATE INDEX IF NOT EXISTS idx_public_hearings_city_date ON public_hearings (municipality_id, hearing_date);

CREATE TABLE IF NOT EXISTS public_hearing_items (
    agenda_item_id INTEGER PRIMARY KEY REFERENCES agenda_items(id) ON DELETE CASCADE,
    hearing_id     INTEGER NOT NULL REFERENCES public_hearings(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_public_hearing_items_hearing ON public_hearing_items (hearing_id);

UPDATE municipalities
   SET metadata = metadata || '{"coming_up": true}'::jsonb
 WHERE slug = 'birmingham';
"""

SQL_DOWN = r"""
UPDATE municipalities
   SET metadata = metadata - 'coming_up'
 WHERE slug = 'birmingham';

DROP TABLE IF EXISTS public_hearing_items;
DROP TABLE IF EXISTS public_hearings;
"""
