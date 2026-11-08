"""Migration 041 — search cards: `agenda_item_search_cards`, `transcript_card_runs`, and card text in the item search vector.

A search card is one row of hidden text per agenda item, written from the
meeting's machine transcript so that search can find the item from loose
everyday words. Nothing in a card is displayed.

`agenda_item_search_cards` holds at most one card per agenda item. A card is
tied to the transcript upload it was written from by `(transcript_id,
source_uploaded_at)`, and is current when `source_uploaded_at` equals
`transcripts.uploaded_at`: that column changes exactly when a re-upload
replaces the segments a card's `seq` values point at. `start_seq` and
`end_seq` are the segments where the item is really taken up and where it
ends, both set or both null; `start_s` and `end_s` are those segments' times
in seconds. `card` is the validated card; `search_b` and `search_c` are the
two texts search reads. Deleting the item or the transcript deletes the card.

`transcript_card_runs` is the card stage's bookkeeping, one row per
transcript. It exists beside the card rows because a meeting can yield zero
cards and must not be claimed forever, and so that the stage never writes
the `transcripts` table, whose status column other readers depend on.

`agenda_items_search_update()` is migration 015's function, term for term,
plus a lookup of the item's card row and two terms: `search_b` at weight B
and `search_c` at weight C. One vector, one GIN index, one rank. The
function reads the card whenever an item row is written, so the writer of a
card refreshes its items with a no-op update of those rows
(`docket.ai.transcripts.cards.touch_search_vectors`).

`SQL_UP` is idempotent as a whole and holds no change to existing rows: no
card exists when it runs, so no vector changes. The integration tests
execute it again at the start of a file, because
`tests/integration/test_migration_013.py` leaves the function at migration
013's body for every file that runs after it.

The down restores migration 015's function, by executing that migration's
own `SQL_UP`, and drops both tables. Item vectors keep any card text they
hold until each row is next written.

Number 039 is `039_meeting_type_checks.py` (plan `meeting-types-name-the-body`, M6).
Plan: plans/completed/search-finds-what-was-said.md (M2).
"""

from __future__ import annotations

import importlib

_M015 = importlib.import_module("docket.migrations.015_search_vector_v3")

SQL_UP = r"""
CREATE TABLE IF NOT EXISTS agenda_item_search_cards (
    agenda_item_id     INTEGER PRIMARY KEY REFERENCES agenda_items(id) ON DELETE CASCADE,
    transcript_id      INTEGER NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
    source_uploaded_at TIMESTAMPTZ NOT NULL,
    prompt_version     INTEGER NOT NULL,
    model              TEXT NOT NULL,
    generated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    discussed          BOOLEAN NOT NULL,
    start_seq          INTEGER,
    end_seq            INTEGER,
    start_s            REAL,
    end_s              REAL,
    card               JSONB NOT NULL,
    search_b           TEXT NOT NULL DEFAULT '',
    search_c           TEXT NOT NULL DEFAULT '',
    CHECK ((start_seq IS NULL) = (end_seq IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_search_cards_transcript ON agenda_item_search_cards (transcript_id);

CREATE TABLE IF NOT EXISTS transcript_card_runs (
    transcript_id      INTEGER PRIMARY KEY REFERENCES transcripts(id) ON DELETE CASCADE,
    meeting_id         INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    source_uploaded_at TIMESTAMPTZ NOT NULL,
    prompt_version     INTEGER NOT NULL,
    status             TEXT NOT NULL CHECK (status IN ('claimed', 'done', 'failed', 'held')),
    attempts           INTEGER NOT NULL DEFAULT 0,
    last_attempted_at  TIMESTAMPTZ,
    last_error         TEXT,
    model              TEXT,
    counts             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION agenda_items_search_update() RETURNS trigger AS $$
DECLARE
  card_b text;
  card_c text;
BEGIN
  SELECT c.search_b, c.search_c INTO card_b, card_c
    FROM agenda_item_search_cards c
   WHERE c.agenda_item_id = NEW.id;
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
    || setweight(to_tsvector('english', coalesce(NEW.summary, '')), 'D')
    || setweight(to_tsvector('english', coalesce(card_b, '')), 'B')
    || setweight(to_tsvector('english', coalesce(card_c, '')), 'C');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

# The function goes back first, so that nothing reads the card table when it
# is dropped. Migration 015's SQL_UP is one CREATE OR REPLACE FUNCTION and is
# executed as it stands, not copied, so the restored body cannot drift from it.
SQL_DOWN = _M015.SQL_UP + r"""
DROP TABLE IF EXISTS agenda_item_search_cards;
DROP TABLE IF EXISTS transcript_card_runs;
"""
