"""Migration 027 — editorial coverage.

Adds the data layer for the editorial coverage feature (spec:
docs/superpowers/specs/2026-05-13-editorial-coverage-design.md):

- ``admin_users.display_name`` column for byline display
- ``outlets`` table — controlled press-outlet vocabulary, 10 rows seeded
- ``coverage_entries`` — one row per note OR citation, with a ``kind``
  discriminator and an exhaustive mutual-exclusion CHECK
- ``coverage_subject_links`` — polymorphic N:M to agenda_items / meetings
  / council_members (app-level FK) / priority_badge_templates (real FK
  with ON UPDATE CASCADE so slug renames propagate)
- Four enums: coverage_kind, coverage_status, coverage_source,
  coverage_subject_type
- Indexes per the spec's index-strategy table
- ``coverage_entries.search_vector`` GENERATED column + GIN index for FTS
  (powers /coverage/?q= search in PR 4)

The schema is automation-ready (status='proposed', source enum, N:M
subjects) but v1 ships human-curated. Proposer pipelines arrive in v2.
"""

from __future__ import annotations


SQL_UP = r"""
ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS display_name TEXT;

CREATE TYPE coverage_kind         AS ENUM ('note', 'citation');
CREATE TYPE coverage_status       AS ENUM ('draft', 'proposed', 'published', 'rejected');
CREATE TYPE coverage_source       AS ENUM ('manual', 'ai_proposal', 'press_scraper');
CREATE TYPE coverage_subject_type AS ENUM ('agenda_item', 'meeting', 'council_member', 'badge');

CREATE TABLE outlets (
    id          SERIAL PRIMARY KEY,
    slug        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    homepage    TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO outlets (slug, name, homepage) VALUES
    ('al-com',                'AL.com',                     'https://al.com'),
    ('birmingham-watch',      'Birmingham Watch',           'https://birminghamwatch.org'),
    ('al-reporter',           'Alabama Reporter',           'https://alreporter.com'),
    ('al-political-reporter', 'Alabama Political Reporter', 'https://www.alreporter.com'),
    ('wbhm',                  'WBHM 90.3',                  'https://wbhm.org'),
    ('wbrc',                  'WBRC FOX6 News',             'https://wbrc.com'),
    ('reflector-alabama',     'Reflector Alabama',          'https://reflector-alabama.com'),
    ('bham-times',            'Birmingham Times',           'https://birminghamtimes.com'),
    ('weld-bham',             'Weld for Birmingham',        'https://weldbham.com'),
    ('docket-substack',       'docket.pub (Substack)',      NULL);

CREATE TABLE coverage_entries (
    id                   SERIAL PRIMARY KEY,
    kind                 coverage_kind   NOT NULL,
    status               coverage_status NOT NULL DEFAULT 'draft',
    source               coverage_source NOT NULL DEFAULT 'manual',
    body                 TEXT,
    partner_credit       TEXT,
    outlet_id            INTEGER REFERENCES outlets(id),
    external_url         TEXT,
    headline             TEXT,
    reporter_byline      TEXT,
    excerpt              TEXT,
    article_published_at DATE,
    author_id            INTEGER NOT NULL REFERENCES admin_users(id),
    byline               TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at         TIMESTAMPTZ,
    featured_until       TIMESTAMPTZ,
    search_vector        tsvector GENERATED ALWAYS AS (
        to_tsvector('english',
            coalesce(body,            '') || ' ' ||
            coalesce(headline,        '') || ' ' ||
            coalesce(excerpt,         '') || ' ' ||
            coalesce(reporter_byline, '')
        )
    ) STORED,
    CHECK (
        (kind = 'note'
            AND body IS NOT NULL
            AND outlet_id IS NULL
            AND external_url IS NULL
            AND headline IS NULL
            AND reporter_byline IS NULL
            AND excerpt IS NULL
            AND article_published_at IS NULL)
      OR
        (kind = 'citation'
            AND body IS NULL
            AND partner_credit IS NULL
            AND outlet_id IS NOT NULL
            AND external_url IS NOT NULL
            AND headline IS NOT NULL)
    )
);

CREATE INDEX idx_coverage_entries_status_published
    ON coverage_entries(status, published_at DESC)
    WHERE status = 'published';

CREATE INDEX idx_coverage_entries_featured
    ON coverage_entries(featured_until)
    WHERE featured_until IS NOT NULL;

CREATE INDEX idx_coverage_entries_kind_status
    ON coverage_entries(kind, status);

CREATE INDEX idx_coverage_entries_search
    ON coverage_entries USING GIN(search_vector);

CREATE TABLE coverage_subject_links (
    id            SERIAL PRIMARY KEY,
    coverage_id   INTEGER NOT NULL REFERENCES coverage_entries(id) ON DELETE CASCADE,
    subject_type  coverage_subject_type NOT NULL,
    subject_id    INTEGER,
    subject_slug  TEXT REFERENCES priority_badge_templates(slug) ON UPDATE CASCADE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (
        (subject_type IN ('agenda_item', 'meeting', 'council_member')
            AND subject_id IS NOT NULL AND subject_slug IS NULL)
      OR
        (subject_type = 'badge'
            AND subject_slug IS NOT NULL AND subject_id IS NULL)
    ),
    UNIQUE (coverage_id, subject_type, subject_id, subject_slug)
);

CREATE INDEX idx_coverage_subject_links_subject_int
    ON coverage_subject_links(subject_type, subject_id)
    WHERE subject_id IS NOT NULL;

CREATE INDEX idx_coverage_subject_links_subject_slug
    ON coverage_subject_links(subject_type, subject_slug)
    WHERE subject_slug IS NOT NULL;
"""

SQL_DOWN = r"""
DROP TABLE IF EXISTS coverage_subject_links;
DROP TABLE IF EXISTS coverage_entries;
DROP TABLE IF EXISTS outlets;
DROP TYPE  IF EXISTS coverage_subject_type;
DROP TYPE  IF EXISTS coverage_source;
DROP TYPE  IF EXISTS coverage_status;
DROP TYPE  IF EXISTS coverage_kind;
ALTER TABLE admin_users DROP COLUMN IF EXISTS display_name;
"""
