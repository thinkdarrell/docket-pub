"""Migration 045 — the council committees' own documents: the tables `committee_documents` and `committee_items`, and Birmingham's `committee_document_pages` metadata.

Each of Birmingham's eight standing committees has a page on the city's
site listing its agenda and minutes PDFs. `committee_documents` holds one
row per listed PDF, unique by `(municipality_id, url)`: what the page said
about it (`page_url`, `page_committee`, `listed_name`, `listed_heading`),
how far reading it has got (`status`, `fetched_at`, `fetch_attempts`,
`pdf_sha256`, `text`, `parser_version`), what it is by its own first lines
with the listing as the fallback (`kind`, `committees`, `meeting_date`,
`date_source`, `listing_disagrees`, `special`, `work_session`), what its
minutes say of attendance (`present`, `trailing_lines`), and the meeting it
belongs to (`meeting_id`, `attached_by`), which a later step sets.
`committee_items` holds what a minutes document says the committee took up,
one row per item in the minutes' order: its heading, its name, the minutes'
text for it, and the action in the minutes' own words with one of a closed
list of categories. A committee records a motion and a second, never a roll
call, so nothing here is a vote, and nothing here is written to
`agenda_items`, `votes`, `meetings.agenda_url` or `meetings.minutes_url`.

Birmingham's metadata gains `committee_document_pages`, a list of eight
`{"committee": <canonical name>, "url": <page address>}`; the names are
those of `docket.services.meeting_types.BIRMINGHAM_COMMITTEES` and the
addresses carry the council term `2025-2027`. The key is set with
`jsonb_set`, so every other key is left as it was.

Additive: no existing table's rows or columns change. The down drops both
tables and removes the key.
Plan `committee-documents`, M3.
"""

from __future__ import annotations


SQL_UP = r"""
CREATE TABLE IF NOT EXISTS committee_documents (
    id                SERIAL PRIMARY KEY,
    municipality_id   INTEGER NOT NULL REFERENCES municipalities,
    url               TEXT NOT NULL,
    page_url          TEXT NOT NULL,
    page_committee    TEXT NOT NULL,
    listed_name       TEXT,
    listed_heading    TEXT,
    first_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    status            TEXT NOT NULL DEFAULT 'listed'
                      CHECK (status IN ('listed', 'read', 'no_text', 'not_committee', 'fetch_failed')),
    fetched_at        TIMESTAMPTZ,
    fetch_attempts    INTEGER NOT NULL DEFAULT 0,
    pdf_sha256        TEXT,
    text              TEXT,
    kind              TEXT CHECK (kind IN ('agenda', 'minutes')),
    committees        TEXT[] NOT NULL DEFAULT '{}',
    meeting_date      DATE,
    date_source       TEXT CHECK (date_source IN ('header', 'heading')),
    listing_disagrees BOOLEAN NOT NULL DEFAULT FALSE,
    special           BOOLEAN NOT NULL DEFAULT FALSE,
    work_session      BOOLEAN NOT NULL DEFAULT FALSE,
    present           TEXT,
    trailing_lines    INTEGER,
    parser_version    SMALLINT,
    meeting_id        INTEGER REFERENCES meetings ON DELETE SET NULL,
    attached_by       TEXT CHECK (attached_by IN ('matched', 'created')),
    UNIQUE (municipality_id, url)
);

CREATE INDEX IF NOT EXISTS committee_documents_meeting_id_idx ON committee_documents (meeting_id);

CREATE TABLE IF NOT EXISTS committee_items (
    id               SERIAL PRIMARY KEY,
    document_id      INTEGER NOT NULL REFERENCES committee_documents ON DELETE CASCADE,
    position         INTEGER NOT NULL,
    heading_label    TEXT,
    heading_text     TEXT,
    owns_heading     BOOLEAN NOT NULL,
    group_text       TEXT,
    name             TEXT NOT NULL,
    body             TEXT NOT NULL DEFAULT '',
    action_text      TEXT NOT NULL,
    action_category  TEXT NOT NULL
                     CHECK (action_category IN ('recommended', 'recommended_consent', 'recommended_no_quorum',
                                                'no_recommendation', 'recommended_deny', 'information_only',
                                                'withdrawn', 'tabled', 'delayed', 'minutes_approved',
                                                'adjourned', 'other')),
    moved_by         TEXT,
    seconded_by      TEXT,
    UNIQUE (document_id, position)
);

UPDATE municipalities
   SET metadata = jsonb_set(metadata, '{committee_document_pages}', '[
        {"committee": "Arts and Parks", "url": "https://www.birminghamal.gov/government/city-council/council/council-committees-2025-2027/arts-parks-committee"},
        {"committee": "Budget and Finance", "url": "https://www.birminghamal.gov/government/city-council/council/council-committees-2025-2027/budget-finance-committee"},
        {"committee": "Committee of the Whole / Administration & Governmental Affairs", "url": "https://www.birminghamal.gov/government/city-council/council/council-committees-2025-2027/committee-whole-administration-governmental-affairs"},
        {"committee": "Community Development", "url": "https://www.birminghamal.gov/government/city-council/council/council-committees-2025-2027/community-development-committee"},
        {"committee": "Economic and Workforce Development / Tourism", "url": "https://www.birminghamal.gov/government/city-council/council/council-committees-2025-2027/economic-workforce-development-tourism-committee"},
        {"committee": "Planning & Zoning", "url": "https://www.birminghamal.gov/government/city-council/council/council-committees-2025-2027/planning-zoning-committee"},
        {"committee": "Public Safety", "url": "https://www.birminghamal.gov/government/city-council/council/council-committees-2025-2027/public-safety-committee"},
        {"committee": "Transportation & Infrastructure", "url": "https://www.birminghamal.gov/government/city-council/council/council-committees-2025-2027/transportation-infrastructure-committee"}
       ]'::jsonb, true)
 WHERE slug = 'birmingham';
"""

SQL_DOWN = r"""
UPDATE municipalities
   SET metadata = metadata - 'committee_document_pages'
 WHERE slug = 'birmingham';

DROP TABLE IF EXISTS committee_items;
DROP TABLE IF EXISTS committee_documents;
"""
