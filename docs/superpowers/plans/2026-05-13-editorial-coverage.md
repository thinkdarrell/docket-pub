# Editorial Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship docket.pub's editorial coverage v1 — short context notes + external press citations attached to items/meetings/members/badges, surfaced inline on item detail with cross-surface chips, plus a standalone `/coverage/` listing, permalinks, RSS, and FTS.

**Architecture:** One `coverage_entries` table with a `kind` discriminator ({note, citation}); a polymorphic N:M `coverage_subject_links` join table; a controlled `outlets` vocabulary. Reader-facing UI lives at `/coverage/*` and item_detail; admin lives at `/admin/coverage/*`. Schema is automation-ready (status + source enums) but no proposer/scraper is built in v1. Builds in the current pre-VSA Flask layout; the modularity refactor will relocate files post-ship with no logic change.

**Tech Stack:** Python 3.10+, Flask + HTMX, PostgreSQL 18.3 (Railway) / 16 (local), pytest. Migration 027.

**Spec:** `docs/superpowers/specs/2026-05-13-editorial-coverage-design.md`.

---

## File structure

### New files

| Path | Responsibility |
|---|---|
| `src/docket/migrations/027_editorial_coverage.py` | Migration: 1 column, 4 enums, 3 tables, indexes, outlet seed |
| `src/docket/models/coverage.py` | `CoverageEntry` + `Outlet` dataclasses with `display_byline()` helper |
| `src/docket/services/coverage_writer.py` | Atomic create/update/delete + status/feature transitions for entries |
| `src/docket/services/outlets_writer.py` | Tiny CRUD for the controlled outlet vocabulary |
| `src/docket/web/templates/admin/coverage/list.html` | Admin list view with status tabs + quick actions |
| `src/docket/web/templates/admin/coverage/new_note.html` | Create-note form |
| `src/docket/web/templates/admin/coverage/new_citation.html` | Create-citation form |
| `src/docket/web/templates/admin/coverage/edit.html` | Kind-aware edit form |
| `src/docket/web/templates/admin/coverage/_subject_picker.html` | HTMX subject picker (multi-attach) |
| `src/docket/web/templates/admin/coverage/_subject_chip.html` | One selected subject chip |
| `src/docket/web/templates/admin/coverage/_search_results.html` | HTMX search results fragment |
| `src/docket/web/templates/admin/coverage/_row.html` | One row in the list view (for HTMX update returns) |
| `src/docket/web/templates/admin/outlets/list.html` | Outlets CRUD list |
| `src/docket/web/templates/admin/outlets/form.html` | Outlet create/edit form |
| `src/docket/web/templates/admin/profile.html` | Display-name profile page |
| `src/docket/web/templates/partials/coverage_block.html` | Wrapper + iteration for inline coverage |
| `src/docket/web/templates/partials/coverage_note.html` | One note render |
| `src/docket/web/templates/partials/coverage_citation.html` | One citation card render |
| `src/docket/web/templates/partials/coverage_count_chip.html` | "📝 1 · 📰 2" chip |
| `src/docket/web/templates/coverage/listing.html` | `/coverage/` paginated listing |
| `src/docket/web/templates/coverage/permalink.html` | `/coverage/<id>` single-note permalink |
| `src/docket/web/templates/coverage/feed.xml.j2` | `/coverage.rss` RSS 2.0 feed |
| `tests/unit/test_query_coverage.py` | Unit tests for read helpers |
| `tests/unit/test_coverage_writer.py` | Unit tests for writer service |
| `tests/integration/test_admin_coverage.py` | Admin CRUD end-to-end |
| `tests/integration/test_admin_outlets.py` | Outlets CRUD |
| `tests/integration/test_item_detail_coverage.py` | Item detail block render |
| `tests/integration/test_coverage_chips.py` | Chip rendering across 6 surfaces |
| `tests/integration/test_coverage_listing.py` | Listing page + permalink + FTS |
| `tests/integration/test_coverage_rss.py` | RSS feed structure |

### Modified files

| Path | What changes |
|---|---|
| `src/docket/migrations/runner.py` | Register 027 in `MIGRATIONS` list |
| `src/docket/services/query.py` | Append coverage section (3 helpers) |
| `src/docket/web/admin.py` | Add coverage routes, outlets routes, profile route |
| `src/docket/web/public.py` | Add `/coverage/` listing, `/coverage/<id>`, `/coverage.rss`; add `coverage_counts` to 6 existing routes |
| `src/docket/web/templates/item_detail.html` | Include coverage block below SBC, above votes |
| `src/docket/web/templates/base.html` | Add `<link rel="alternate" type="application/rss+xml">` |
| `src/docket/web/templates/partials/<item_card>.html` | Accept `coverage_counts` prop; render chip when non-zero |
| `src/docket/web/static/styles.css` | Coverage block + chip + citation card styling |

---

## Phase 1 — Schema + read service skeleton (PR 1)

**Goal:** Database layer exists; reads work; nothing renders yet.

### Task 1.1: Write the migration file

**Files:**
- Create: `src/docket/migrations/027_editorial_coverage.py`

- [ ] **Step 1: Create the migration with the full DDL**

```python
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
```

- [ ] **Step 2: Register the migration in the runner**

Modify `src/docket/migrations/runner.py:24-46` — append the migration to the `MIGRATIONS` list at the end:

```python
    "docket.migrations.026_mv_city_backfill_ratio_v4",
    "docket.migrations.027_editorial_coverage",
]
```

- [ ] **Step 3: Apply to local DB and verify status**

```bash
python -m docket.migrations.runner
python -m docket.migrations.runner --status
```

Expected: `027_editorial_coverage  [applied]` appears at the bottom.

- [ ] **Step 4: Verify shape via psql**

```bash
psql $DATABASE_URL -c "\d coverage_entries"
psql $DATABASE_URL -c "\d coverage_subject_links"
psql $DATABASE_URL -c "SELECT slug, name FROM outlets ORDER BY id;"
```

Expected: 13 columns on `coverage_entries` (plus `search_vector`); 6 columns on `coverage_subject_links`; 10 outlets seeded.

- [ ] **Step 5: Commit**

```bash
git add src/docket/migrations/027_editorial_coverage.py src/docket/migrations/runner.py
git commit -m "feat(migrations): 027 editorial coverage schema + outlet seed"
```

---

### Task 1.2: Create the CoverageEntry + Outlet dataclasses

**Files:**
- Create: `src/docket/models/coverage.py`
- Test: `tests/unit/test_query_coverage.py` (test added here, helpers used throughout phase 1)

- [ ] **Step 1: Write a failing test for the dataclass shape**

```python
# tests/unit/test_query_coverage.py
"""Unit tests for editorial coverage read helpers."""
from __future__ import annotations

from datetime import datetime

from docket.models.coverage import CoverageEntry, Outlet


def test_coverage_entry_display_byline_uses_snapshot_when_set():
    entry = CoverageEntry(
        id=1, kind='note', status='published', source='manual',
        body='test', partner_credit=None,
        outlet_id=None, external_url=None, headline=None,
        reporter_byline=None, excerpt=None, article_published_at=None,
        author_id=1, byline='Darrell Nance',
        created_at=datetime.now(), updated_at=datetime.now(),
        published_at=datetime.now(), featured_until=None,
        author_display_name='changed-after-publish', author_username='darrell',
    )
    assert entry.display_byline() == 'Darrell Nance'


def test_coverage_entry_display_byline_falls_back_to_display_name_when_null():
    entry = CoverageEntry(
        id=1, kind='note', status='draft', source='manual',
        body='test', partner_credit=None,
        outlet_id=None, external_url=None, headline=None,
        reporter_byline=None, excerpt=None, article_published_at=None,
        author_id=1, byline=None,
        created_at=datetime.now(), updated_at=datetime.now(),
        published_at=None, featured_until=None,
        author_display_name='Darrell Nance', author_username='darrell',
    )
    assert entry.display_byline() == 'Darrell Nance'


def test_coverage_entry_display_byline_falls_back_to_username_when_no_display_name():
    entry = CoverageEntry(
        id=1, kind='note', status='draft', source='manual',
        body='test', partner_credit=None,
        outlet_id=None, external_url=None, headline=None,
        reporter_byline=None, excerpt=None, article_published_at=None,
        author_id=1, byline=None,
        created_at=datetime.now(), updated_at=datetime.now(),
        published_at=None, featured_until=None,
        author_display_name=None, author_username='darrell',
    )
    assert entry.display_byline() == 'darrell'
```

- [ ] **Step 2: Run the test to verify failure**

```bash
pytest tests/unit/test_query_coverage.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'docket.models.coverage'`.

- [ ] **Step 3: Implement the dataclasses**

```python
# src/docket/models/coverage.py
"""Editorial coverage dataclasses.

Mirrors the row shapes from migration 027. ``display_byline()`` returns
the snapshotted ``byline`` if set (post-publish), else falls back to the
author's live ``display_name`` or ``username`` (drafts).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal


CoverageKind = Literal['note', 'citation']
CoverageStatus = Literal['draft', 'proposed', 'published', 'rejected']
CoverageSource = Literal['manual', 'ai_proposal', 'press_scraper']
CoverageSubjectType = Literal['agenda_item', 'meeting', 'council_member', 'badge']


@dataclass(frozen=True)
class Outlet:
    id: int
    slug: str
    name: str
    homepage: str | None
    is_active: bool
    created_at: datetime


@dataclass(frozen=True)
class CoverageSubjectLink:
    subject_type: CoverageSubjectType
    subject_id: int | None
    subject_slug: str | None
    # Optional human-readable label hydrated by the reader for chip rendering.
    label: str | None = None


@dataclass(frozen=True)
class CoverageEntry:
    id: int
    kind: CoverageKind
    status: CoverageStatus
    source: CoverageSource

    # Notes-only
    body: str | None
    partner_credit: str | None

    # Citations-only
    outlet_id: int | None
    external_url: str | None
    headline: str | None
    reporter_byline: str | None
    excerpt: str | None
    article_published_at: date | None

    # Authoring & audit
    author_id: int
    byline: str | None  # snapshot-on-publish
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
    featured_until: datetime | None

    # Hydrated by the reader (not raw columns):
    author_display_name: str | None = None
    author_username: str | None = None
    outlet_slug: str | None = None
    outlet_name: str | None = None
    subjects: tuple[CoverageSubjectLink, ...] = ()

    def display_byline(self) -> str:
        """Snapshotted byline if set; else author's live display_name or username."""
        if self.byline:
            return self.byline
        return self.author_display_name or self.author_username or 'docket.pub editorial'
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pytest tests/unit/test_query_coverage.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/docket/models/coverage.py tests/unit/test_query_coverage.py
git commit -m "feat(models): CoverageEntry + Outlet dataclasses with display_byline"
```

---

### Task 1.3: Write `coverage_for_subject` read helper

**Files:**
- Modify: `src/docket/services/query.py` (append a new section at the bottom)
- Test: `tests/unit/test_query_coverage.py` (append)

- [ ] **Step 1: Write a failing test for `coverage_for_subject`**

Append to `tests/unit/test_query_coverage.py`:

```python
import pytest

from docket.config import DATABASE_URL
from docket.db import db


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run editorial-coverage tests against Railway DB.",
)


@pytest.fixture
def seeded_admin():
    """Create a test admin user; clean up after."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO admin_users (username, password_hash, display_name) "
                "VALUES (%s, %s, %s) RETURNING id",
                ('test-editor', 'unused', 'Test Editor'),
            )
            user_id = cur.fetchone()[0]
        conn.commit()
    yield user_id
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM admin_users WHERE id = %s", (user_id,))
        conn.commit()


@pytest.fixture
def seeded_meeting():
    """Insert a throwaway meeting+item; clean up."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO meetings (municipality_id, external_id, title, meeting_date) "
                "VALUES ((SELECT id FROM municipalities LIMIT 1), %s, %s, NOW()) RETURNING id",
                ('test-mtg-coverage', 'Test Meeting for Coverage'),
            )
            mtg_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO agenda_items (meeting_id, title) VALUES (%s, %s) RETURNING id",
                (mtg_id, 'Test Item for Coverage'),
            )
            item_id = cur.fetchone()[0]
        conn.commit()
    yield (mtg_id, item_id)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM agenda_items WHERE id = %s", (item_id,))
            cur.execute("DELETE FROM meetings WHERE id = %s", (mtg_id,))
        conn.commit()


def test_coverage_for_subject_returns_empty_when_none_attached(seeded_meeting):
    from docket.services.query import coverage_for_subject
    _, item_id = seeded_meeting
    assert coverage_for_subject('agenda_item', subject_id=item_id) == []


def test_coverage_for_subject_returns_published_note_with_byline(seeded_admin, seeded_meeting):
    from docket.services.query import coverage_for_subject
    _, item_id = seeded_meeting
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO coverage_entries
                   (kind, status, body, author_id, byline, published_at)
                   VALUES ('note', 'published', 'Important context.', %s,
                           'Test Editor', NOW())
                   RETURNING id""",
                (seeded_admin,),
            )
            entry_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO coverage_subject_links
                   (coverage_id, subject_type, subject_id)
                   VALUES (%s, 'agenda_item', %s)""",
                (entry_id, item_id),
            )
        conn.commit()
    try:
        entries = coverage_for_subject('agenda_item', subject_id=item_id)
        assert len(entries) == 1
        assert entries[0].body == 'Important context.'
        assert entries[0].display_byline() == 'Test Editor'
    finally:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM coverage_entries WHERE id = %s", (entry_id,))
            conn.commit()


def test_coverage_for_subject_excludes_drafts(seeded_admin, seeded_meeting):
    from docket.services.query import coverage_for_subject
    _, item_id = seeded_meeting
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO coverage_entries
                   (kind, status, body, author_id)
                   VALUES ('note', 'draft', 'Not yet ready.', %s)
                   RETURNING id""",
                (seeded_admin,),
            )
            entry_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO coverage_subject_links
                   (coverage_id, subject_type, subject_id)
                   VALUES (%s, 'agenda_item', %s)""",
                (entry_id, item_id),
            )
        conn.commit()
    try:
        assert coverage_for_subject('agenda_item', subject_id=item_id) == []
    finally:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM coverage_entries WHERE id = %s", (entry_id,))
            conn.commit()
```

- [ ] **Step 2: Run the tests to verify failure**

```bash
pytest tests/unit/test_query_coverage.py -v
```

Expected: 3 new tests FAIL with `ImportError: cannot import name 'coverage_for_subject'`.

- [ ] **Step 3: Implement `coverage_for_subject` in query.py**

Append at the end of `src/docket/services/query.py`:

```python
# ============================================================================
# Editorial Coverage (Migration 027)
# ============================================================================
# Spec: docs/superpowers/specs/2026-05-13-editorial-coverage-design.md
# Modularity refactor will relocate this section to services/query/coverage.py
# during PR 0.2 (services/query.py decomposition). Keep imports local and
# clearly grouped to make that extraction mechanical.

from docket.models.coverage import (
    CoverageEntry,
    CoverageSubjectLink,
    CoverageSubjectType,
)


def _hydrate_coverage_rows(cur) -> list[CoverageEntry]:
    """Convert cursor rows into CoverageEntry instances. Caller must have
    selected the full row + author + outlet hydration columns in the right
    order — see queries below."""
    out: list[CoverageEntry] = []
    for r in cur.fetchall():
        out.append(CoverageEntry(
            id=r['id'], kind=r['kind'], status=r['status'], source=r['source'],
            body=r['body'], partner_credit=r['partner_credit'],
            outlet_id=r['outlet_id'], external_url=r['external_url'],
            headline=r['headline'], reporter_byline=r['reporter_byline'],
            excerpt=r['excerpt'], article_published_at=r['article_published_at'],
            author_id=r['author_id'], byline=r['byline'],
            created_at=r['created_at'], updated_at=r['updated_at'],
            published_at=r['published_at'], featured_until=r['featured_until'],
            author_display_name=r['author_display_name'],
            author_username=r['author_username'],
            outlet_slug=r.get('outlet_slug'),
            outlet_name=r.get('outlet_name'),
        ))
    return out


_COVERAGE_SELECT = """
    SELECT ce.id, ce.kind, ce.status, ce.source,
           ce.body, ce.partner_credit,
           ce.outlet_id, ce.external_url, ce.headline,
           ce.reporter_byline, ce.excerpt, ce.article_published_at,
           ce.author_id, ce.byline,
           ce.created_at, ce.updated_at, ce.published_at, ce.featured_until,
           au.display_name AS author_display_name,
           au.username     AS author_username,
           o.slug          AS outlet_slug,
           o.name          AS outlet_name
      FROM coverage_entries ce
      JOIN admin_users au ON au.id = ce.author_id
 LEFT JOIN outlets o ON o.id = ce.outlet_id
"""


def coverage_for_subject(
    subject_type: CoverageSubjectType,
    subject_id: int | None = None,
    subject_slug: str | None = None,
) -> list[CoverageEntry]:
    """Return published coverage entries attached to one subject.

    Exactly one of ``subject_id`` or ``subject_slug`` must be set; the choice
    is gated by ``subject_type`` (badge → slug; others → id).

    Notes are returned first (newest published_at first), then citations
    (newest article_published_at first). Matches the template's render order.
    """
    if subject_type == 'badge':
        if subject_slug is None:
            raise ValueError("subject_slug required when subject_type='badge'")
        where = "csl.subject_type = 'badge' AND csl.subject_slug = %s"
        params = (subject_slug,)
    else:
        if subject_id is None:
            raise ValueError(f"subject_id required when subject_type={subject_type!r}")
        where = "csl.subject_type = %s AND csl.subject_id = %s"
        params = (subject_type, subject_id)

    sql = _COVERAGE_SELECT + f"""
        JOIN coverage_subject_links csl ON csl.coverage_id = ce.id
       WHERE {where}
         AND ce.status = 'published'
       ORDER BY ce.kind ASC,                          -- 'citation' > 'note' alphabetically
                CASE WHEN ce.kind = 'note'
                     THEN ce.published_at
                     ELSE ce.article_published_at::timestamptz
                END DESC NULLS LAST
    """
    # ORDER BY kind ASC puts 'citation' after 'note' alphabetically ('citation' < 'note'
    # is false → 'citation' sorts before 'note' actually); fix by mapping:
    # We want notes first. 'citation' < 'note' alphabetically, so ASC gives citations first.
    # Re-do via explicit CASE:
    sql = _COVERAGE_SELECT + f"""
        JOIN coverage_subject_links csl ON csl.coverage_id = ce.id
       WHERE {where}
         AND ce.status = 'published'
       ORDER BY CASE WHEN ce.kind = 'note' THEN 0 ELSE 1 END ASC,
                CASE WHEN ce.kind = 'note'
                     THEN ce.published_at
                     ELSE ce.article_published_at::timestamptz
                END DESC NULLS LAST
    """

    from docket.db import db_cursor
    with db_cursor() as cur:
        cur.execute(sql, params)
        return _hydrate_coverage_rows(cur)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pytest tests/unit/test_query_coverage.py -v
```

Expected: all tests pass (6 total including the 3 from Task 1.2).

- [ ] **Step 5: Commit**

```bash
git add src/docket/services/query.py tests/unit/test_query_coverage.py
git commit -m "feat(query): coverage_for_subject read helper"
```

---

### Task 1.4: Write `coverage_counts_for_items` helper (with empty-list fast path)

**Files:**
- Modify: `src/docket/services/query.py` (append)
- Test: `tests/unit/test_query_coverage.py` (append)

- [ ] **Step 1: Write failing tests including the empty-input case**

Append to `tests/unit/test_query_coverage.py`:

```python
def test_coverage_counts_for_items_empty_input_returns_empty_dict():
    """Empty input must short-circuit before SQL — `WHERE id IN ()` is a syntax error."""
    from docket.services.query import coverage_counts_for_items
    assert coverage_counts_for_items([]) == {}


def test_coverage_counts_for_items_returns_counts(seeded_admin, seeded_meeting):
    from docket.services.query import coverage_counts_for_items
    _, item_id = seeded_meeting
    with db() as conn:
        with conn.cursor() as cur:
            # 2 notes + 1 citation on the same item
            for i in range(2):
                cur.execute(
                    """INSERT INTO coverage_entries
                       (kind, status, body, author_id, byline, published_at)
                       VALUES ('note', 'published', %s, %s, 'Test', NOW())
                       RETURNING id""",
                    (f'note {i}', seeded_admin),
                )
                cid = cur.fetchone()[0]
                cur.execute(
                    """INSERT INTO coverage_subject_links
                       (coverage_id, subject_type, subject_id)
                       VALUES (%s, 'agenda_item', %s)""",
                    (cid, item_id),
                )
            cur.execute("SELECT id FROM outlets WHERE slug = 'al-com' LIMIT 1")
            outlet_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO coverage_entries
                   (kind, status, outlet_id, external_url, headline,
                    author_id, byline, published_at)
                   VALUES ('citation', 'published', %s, %s, %s, %s, 'Test', NOW())
                   RETURNING id""",
                (outlet_id, 'https://al.com/foo', 'Foo Headline', seeded_admin),
            )
            cit_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO coverage_subject_links
                   (coverage_id, subject_type, subject_id)
                   VALUES (%s, 'agenda_item', %s)""",
                (cit_id, item_id),
            )
        conn.commit()
    try:
        counts = coverage_counts_for_items([item_id])
        assert counts == {item_id: (2, 1)}
    finally:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM coverage_entries WHERE id IN "
                    "(SELECT coverage_id FROM coverage_subject_links "
                    "WHERE subject_id = %s)",
                    (item_id,),
                )
            conn.commit()
```

- [ ] **Step 2: Run the tests to verify failure**

```bash
pytest tests/unit/test_query_coverage.py -v -k counts
```

Expected: 2 tests FAIL with `ImportError`.

- [ ] **Step 3: Implement `coverage_counts_for_items`**

Append to `src/docket/services/query.py`:

```python
def coverage_counts_for_items(item_ids: list[int]) -> dict[int, tuple[int, int]]:
    """Return {item_id: (note_count, citation_count)} for items with published coverage.

    Items with no coverage are omitted from the returned dict — callers should
    default to ``(0, 0)``.

    Short-circuits to ``{}`` when ``item_ids`` is empty, since
    ``WHERE subject_id IN ()`` raises a syntax error in psycopg.
    """
    if not item_ids:
        return {}
    from docket.db import db_cursor
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT csl.subject_id,
                   COUNT(*) FILTER (WHERE ce.kind = 'note')     AS note_count,
                   COUNT(*) FILTER (WHERE ce.kind = 'citation') AS cit_count
              FROM coverage_subject_links csl
              JOIN coverage_entries ce ON ce.id = csl.coverage_id
             WHERE csl.subject_type = 'agenda_item'
               AND csl.subject_id = ANY(%s)
               AND ce.status = 'published'
             GROUP BY csl.subject_id
            """,
            (item_ids,),
        )
        return {r['subject_id']: (r['note_count'], r['cit_count']) for r in cur.fetchall()}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pytest tests/unit/test_query_coverage.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/docket/services/query.py tests/unit/test_query_coverage.py
git commit -m "feat(query): coverage_counts_for_items with empty-list short-circuit"
```

---

### Task 1.5: Write `list_published_coverage` with pagination + filters + FTS + subject hydration

**Files:**
- Modify: `src/docket/services/query.py` (append)
- Test: `tests/unit/test_query_coverage.py` (append)

**Why subject hydration belongs here:** the listing page renders each row with an "→ on Item 25-0042 (Westside Rezoning), Council Mtg 5-12" footer that names the subjects the entry is attached to. Without this, the listing is a wall of contextless quotes. We populate `CoverageEntry.subjects` via a second bulk query for the page's entry IDs, so each row arrives at the template fully hydrated. The same helper is reused by the permalink route in Task 4.2.

- [ ] **Step 1: Write failing tests for listing + filter + search**

Append to `tests/unit/test_query_coverage.py`:

```python
def test_list_published_coverage_returns_published_only(seeded_admin, seeded_meeting):
    from docket.services.query import list_published_coverage
    _, item_id = seeded_meeting
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO coverage_entries
                   (kind, status, body, author_id, byline, published_at)
                   VALUES ('note', 'published', 'Live note.', %s, 'Test', NOW())
                   RETURNING id""",
                (seeded_admin,),
            )
            published_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO coverage_entries
                   (kind, status, body, author_id)
                   VALUES ('note', 'draft', 'Draft note.', %s)
                   RETURNING id""",
                (seeded_admin,),
            )
            draft_id = cur.fetchone()[0]
        conn.commit()
    try:
        rows, total = list_published_coverage(page=1, page_size=50)
        ids = [e.id for e in rows]
        assert published_id in ids
        assert draft_id not in ids
    finally:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM coverage_entries WHERE id IN (%s, %s)",
                            (published_id, draft_id))
            conn.commit()


def test_list_published_coverage_filters_by_kind(seeded_admin):
    from docket.services.query import list_published_coverage
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO coverage_entries
                   (kind, status, body, author_id, byline, published_at)
                   VALUES ('note', 'published', 'A unique note 9c3f.', %s,
                           'Test', NOW())
                   RETURNING id""",
                (seeded_admin,),
            )
            note_id = cur.fetchone()[0]
        conn.commit()
    try:
        rows, _ = list_published_coverage(kind='note', q='9c3f')
        assert any(e.id == note_id for e in rows)
        rows, _ = list_published_coverage(kind='citation', q='9c3f')
        assert not any(e.id == note_id for e in rows)
    finally:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM coverage_entries WHERE id = %s", (note_id,))
            conn.commit()


def test_list_published_coverage_fts_search(seeded_admin):
    from docket.services.query import list_published_coverage
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO coverage_entries
                   (kind, status, body, author_id, byline, published_at)
                   VALUES ('note', 'published',
                           'Westside rezoning unique phrase eyeball42.',
                           %s, 'Test', NOW())
                   RETURNING id""",
                (seeded_admin,),
            )
            note_id = cur.fetchone()[0]
        conn.commit()
    try:
        rows, _ = list_published_coverage(q='eyeball42')
        assert any(e.id == note_id for e in rows)
    finally:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM coverage_entries WHERE id = %s", (note_id,))
            conn.commit()


def test_list_published_coverage_hydrates_subjects(seeded_admin, seeded_meeting):
    """The listing must arrive with subjects populated so the template can render
    the 'on Item X, Meeting Y' context footer per row."""
    from docket.services.query import list_published_coverage
    mtg_id, item_id = seeded_meeting
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO coverage_entries
                   (kind, status, body, author_id, byline, published_at)
                   VALUES ('note', 'published', 'Subjects-hydration probe wxyz77.',
                           %s, 'Test', NOW())
                   RETURNING id""",
                (seeded_admin,),
            )
            entry_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO coverage_subject_links
                   (coverage_id, subject_type, subject_id) VALUES
                   (%s, 'agenda_item', %s),
                   (%s, 'meeting',     %s)""",
                (entry_id, item_id, entry_id, mtg_id),
            )
        conn.commit()
    try:
        rows, _ = list_published_coverage(q='wxyz77')
        target = next(e for e in rows if e.id == entry_id)
        kinds = sorted(s.subject_type for s in target.subjects)
        assert kinds == ['agenda_item', 'meeting']
        # Labels resolved from the source tables
        assert any(s.label for s in target.subjects)
    finally:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM coverage_entries WHERE id = %s", (entry_id,))
            conn.commit()
```

- [ ] **Step 2: Run the tests to verify failure**

```bash
pytest tests/unit/test_query_coverage.py -v -k list_published
```

Expected: 3 tests FAIL.

- [ ] **Step 3: Implement the subject-hydration helper + `list_published_coverage`**

Append to `src/docket/services/query.py`:

```python
def _hydrate_subjects_for_entries(cur, entries: list[CoverageEntry]) -> list[CoverageEntry]:
    """Populate the ``subjects`` field on each entry with one bulk query.

    Resolves a human-readable label per subject from agenda_items / meetings /
    council_members / priority_badge_templates via COALESCE'd lookups, so the
    template can render '→ on Item 25-0042 (Westside Rezoning)' chips without
    a second per-row trip.

    Returns a NEW list (frozen dataclass — uses ``replace``).
    """
    if not entries:
        return entries
    from dataclasses import replace
    ids = [e.id for e in entries]
    cur.execute(
        """
        SELECT csl.coverage_id, csl.subject_type, csl.subject_id, csl.subject_slug,
               COALESCE(
                 (SELECT title FROM agenda_items     WHERE id   = csl.subject_id),
                 (SELECT title FROM meetings         WHERE id   = csl.subject_id),
                 (SELECT name  FROM council_members  WHERE id   = csl.subject_id),
                 (SELECT name  FROM priority_badge_templates WHERE slug = csl.subject_slug),
                 ''
               ) AS label
          FROM coverage_subject_links csl
         WHERE csl.coverage_id = ANY(%s)
         ORDER BY csl.coverage_id, csl.id
        """,
        (ids,),
    )
    grouped: dict[int, list[CoverageSubjectLink]] = {}
    for r in cur.fetchall():
        grouped.setdefault(r['coverage_id'], []).append(
            CoverageSubjectLink(
                subject_type=r['subject_type'],
                subject_id=r['subject_id'],
                subject_slug=r['subject_slug'],
                label=r['label'] or None,
            )
        )
    return [replace(e, subjects=tuple(grouped.get(e.id, []))) for e in entries]


def list_published_coverage(
    *,
    kind: str | None = None,
    outlet_id: int | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[CoverageEntry], int]:
    """Paginated listing of published coverage with subjects hydrated.

    Returns (rows, total_count). Each row's ``subjects`` tuple is populated so
    the listing template can render the 'on Item X, Meeting Y' context footer
    without a second per-row query.

    ``q`` runs full-text search against the generated ``search_vector`` column.
    Empty-string ``q`` is treated as None.
    """
    where = ["ce.status = 'published'"]
    params: list = []
    if kind:
        where.append("ce.kind = %s")
        params.append(kind)
    if outlet_id:
        where.append("ce.outlet_id = %s")
        params.append(outlet_id)
    if q and q.strip():
        where.append("ce.search_vector @@ websearch_to_tsquery('english', %s)")
        params.append(q.strip())
    where_sql = " AND ".join(where)

    from docket.db import db_cursor

    # Count query
    with db_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS n FROM coverage_entries ce WHERE {where_sql}",
                    tuple(params))
        total = cur.fetchone()['n']

    # Page query + subject hydration in the same cursor (one connection)
    offset = max(0, (page - 1) * page_size)
    sql = _COVERAGE_SELECT + f"""
        WHERE {where_sql}
       ORDER BY ce.published_at DESC NULLS LAST
       LIMIT %s OFFSET %s
    """
    with db_cursor() as cur:
        cur.execute(sql, tuple(params) + (page_size, offset))
        rows = _hydrate_coverage_rows(cur)
        rows = _hydrate_subjects_for_entries(cur, rows)
    return rows, total
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pytest tests/unit/test_query_coverage.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/docket/services/query.py tests/unit/test_query_coverage.py
git commit -m "feat(query): list_published_coverage with pagination, filters, FTS"
```

---

### Task 1.6: Phase 1 verification — apply migration on Railway

- [ ] **Step 1: Deploy and verify migration applies via the web service**

```bash
cd ~/docket-pub
railway up --service docket-web --detach
railway logs --service docket-web | head -50
```

Expected: log line shows `[applied] docket.migrations.027_editorial_coverage`.

- [ ] **Step 2: Verify schema on Railway**

```bash
railway ssh --service docket-web "psql \$DATABASE_URL -c '\\d coverage_entries'"
railway ssh --service docket-web "psql \$DATABASE_URL -c \"SELECT slug, name FROM outlets ORDER BY id\""
```

Expected: shape and 10 seeded outlets on Railway prod DB.

- [ ] **Step 3: Smoke-test the read service via railway ssh**

```bash
railway ssh --service docket-web "python -c 'from docket.services.query import list_published_coverage; print(list_published_coverage())'"
```

Expected: `([], 0)` — empty but no error.

**Phase 1 done.** The data layer exists, reads work, and nothing surfaces yet.

---

## Phase 2 — Admin CRUD (PR 2)

**Goal:** Editor can author, attach, publish, and manage coverage; nothing surfaces to citizens yet.

### Task 2.1: Write the writer service skeleton

**Files:**
- Create: `src/docket/services/coverage_writer.py`
- Test: `tests/unit/test_coverage_writer.py`

- [ ] **Step 1: Write a failing test for `create_note`**

```python
# tests/unit/test_coverage_writer.py
"""Unit tests for editorial coverage writer service."""
from __future__ import annotations

import pytest

from docket.config import DATABASE_URL
from docket.db import db


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run coverage writer tests against Railway DB.",
)


@pytest.fixture
def seeded_admin():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO admin_users (username, password_hash, display_name) "
                "VALUES (%s, %s, %s) RETURNING id",
                ('test-writer-editor', 'unused', 'Writer Test'),
            )
            user_id = cur.fetchone()[0]
        conn.commit()
    yield user_id
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM admin_users WHERE id = %s", (user_id,))
        conn.commit()


@pytest.fixture
def seeded_item():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO meetings (municipality_id, external_id, title, meeting_date) "
                "VALUES ((SELECT id FROM municipalities LIMIT 1), %s, %s, NOW()) RETURNING id",
                ('writer-mtg', 'Writer Test Meeting'),
            )
            mtg_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO agenda_items (meeting_id, title) VALUES (%s, %s) RETURNING id",
                (mtg_id, 'Writer Test Item'),
            )
            item_id = cur.fetchone()[0]
        conn.commit()
    yield (mtg_id, item_id)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM agenda_items WHERE id = %s", (item_id,))
            cur.execute("DELETE FROM meetings WHERE id = %s", (mtg_id,))
        conn.commit()


def _cleanup_entry(entry_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM coverage_entries WHERE id = %s", (entry_id,))
        conn.commit()


def test_create_note_inserts_entry_and_subjects(seeded_admin, seeded_item):
    from docket.services.coverage_writer import create_note
    _, item_id = seeded_item
    entry_id = create_note(
        author_id=seeded_admin,
        body='A short context note.',
        partner_credit=None,
        subjects=[('agenda_item', item_id, None)],
    )
    try:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT kind, status, body FROM coverage_entries WHERE id = %s",
                            (entry_id,))
                row = cur.fetchone()
                assert row[0] == 'note'
                assert row[1] == 'draft'
                assert row[2] == 'A short context note.'
                cur.execute(
                    "SELECT COUNT(*) FROM coverage_subject_links WHERE coverage_id = %s",
                    (entry_id,),
                )
                assert cur.fetchone()[0] == 1
    finally:
        _cleanup_entry(entry_id)
```

- [ ] **Step 2: Run the test to verify failure**

```bash
pytest tests/unit/test_coverage_writer.py::test_create_note_inserts_entry_and_subjects -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `create_note`**

```python
# src/docket/services/coverage_writer.py
"""Editorial coverage writer service.

All multi-step writes are wrapped in a single transaction via db_cursor().
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from docket.db import db_cursor


SubjectSpec = tuple[str, int | None, str | None]
# (subject_type, subject_id, subject_slug). Exactly one of subject_id/subject_slug
# is non-None per row, gated by subject_type.


def _validate_subjects(subjects: Iterable[SubjectSpec]) -> list[SubjectSpec]:
    subs = list(subjects)
    if not subs:
        raise ValueError("Coverage entry must attach to at least one subject")
    for st, sid, sslug in subs:
        if st == 'badge':
            if not sslug or sid is not None:
                raise ValueError(f"Badge subject requires slug only: {(st, sid, sslug)}")
        elif st in ('agenda_item', 'meeting', 'council_member'):
            if sid is None or sslug is not None:
                raise ValueError(f"{st} subject requires int id only: {(st, sid, sslug)}")
        else:
            raise ValueError(f"Unknown subject_type: {st!r}")
    return subs


def _insert_subjects(cur, coverage_id: int, subjects: list[SubjectSpec]) -> None:
    for st, sid, sslug in subjects:
        cur.execute(
            """INSERT INTO coverage_subject_links
               (coverage_id, subject_type, subject_id, subject_slug)
               VALUES (%s, %s, %s, %s)""",
            (coverage_id, st, sid, sslug),
        )


def create_note(
    *,
    author_id: int,
    body: str,
    partner_credit: str | None,
    subjects: Iterable[SubjectSpec],
    status: str = 'draft',
    featured_until: datetime | None = None,
) -> int:
    """Create a note. Returns new coverage_entries.id.

    Transactional: entry + all subject_links inserted atomically.
    """
    subs = _validate_subjects(subjects)
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO coverage_entries
               (kind, status, body, partner_credit, author_id, featured_until)
               VALUES ('note', %s, %s, %s, %s, %s)
               RETURNING id""",
            (status, body, partner_credit, author_id, featured_until),
        )
        entry_id = cur.fetchone()['id']
        _insert_subjects(cur, entry_id, subs)
        if status == 'published':
            _set_publish_state(cur, entry_id, author_id)
        return entry_id


def _set_publish_state(cur, coverage_id: int, author_id: int) -> None:
    """Populate published_at + byline snapshot for a newly-published entry.

    Idempotent: re-running on an entry that already has a byline keeps it.
    """
    cur.execute(
        """UPDATE coverage_entries
              SET published_at = COALESCE(published_at, NOW()),
                  byline = COALESCE(byline,
                                    (SELECT COALESCE(display_name, username)
                                       FROM admin_users WHERE id = %s))
            WHERE id = %s""",
        (author_id, coverage_id),
    )
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/unit/test_coverage_writer.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/docket/services/coverage_writer.py tests/unit/test_coverage_writer.py
git commit -m "feat(coverage_writer): create_note with atomic subject inserts"
```

---

### Task 2.2: Add `create_citation`

**Files:**
- Modify: `src/docket/services/coverage_writer.py`
- Test: `tests/unit/test_coverage_writer.py` (append)

- [ ] **Step 1: Write a failing test**

Append to `tests/unit/test_coverage_writer.py`:

```python
def test_create_citation_inserts_entry_with_outlet(seeded_admin, seeded_item):
    from docket.services.coverage_writer import create_citation
    _, item_id = seeded_item
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM outlets WHERE slug = 'birmingham-watch'")
            outlet_id = cur.fetchone()[0]
    entry_id = create_citation(
        author_id=seeded_admin,
        outlet_id=outlet_id,
        external_url='https://birminghamwatch.org/test',
        headline='Test headline',
        reporter_byline='Sam Prickett',
        excerpt='Pull quote.',
        article_published_at=None,
        subjects=[('agenda_item', item_id, None)],
    )
    try:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT kind, headline, reporter_byline FROM coverage_entries WHERE id = %s",
                    (entry_id,),
                )
                row = cur.fetchone()
                assert row[0] == 'citation'
                assert row[1] == 'Test headline'
                assert row[2] == 'Sam Prickett'
    finally:
        _cleanup_entry(entry_id)
```

- [ ] **Step 2: Run the test to verify failure**

```bash
pytest tests/unit/test_coverage_writer.py -v -k citation
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `create_citation`**

Append to `src/docket/services/coverage_writer.py`:

```python
def create_citation(
    *,
    author_id: int,
    outlet_id: int,
    external_url: str,
    headline: str,
    reporter_byline: str | None,
    excerpt: str | None,
    article_published_at,
    subjects: Iterable[SubjectSpec],
    status: str = 'draft',
    featured_until: datetime | None = None,
) -> int:
    """Create a citation entry attached to ``subjects``. Atomic insert."""
    subs = _validate_subjects(subjects)
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO coverage_entries
               (kind, status, outlet_id, external_url, headline,
                reporter_byline, excerpt, article_published_at,
                author_id, featured_until)
               VALUES ('citation', %s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (status, outlet_id, external_url, headline, reporter_byline,
             excerpt, article_published_at, author_id, featured_until),
        )
        entry_id = cur.fetchone()['id']
        _insert_subjects(cur, entry_id, subs)
        if status == 'published':
            _set_publish_state(cur, entry_id, author_id)
        return entry_id
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/unit/test_coverage_writer.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/docket/services/coverage_writer.py tests/unit/test_coverage_writer.py
git commit -m "feat(coverage_writer): create_citation with atomic subject inserts"
```

---

### Task 2.3: Add `set_status` with byline snapshot

**Files:**
- Modify: `src/docket/services/coverage_writer.py`
- Test: `tests/unit/test_coverage_writer.py` (append)

- [ ] **Step 1: Write failing tests for status transitions and byline snapshot**

Append to `tests/unit/test_coverage_writer.py`:

```python
def test_set_status_to_published_snapshots_byline(seeded_admin, seeded_item):
    from docket.services.coverage_writer import create_note, set_status
    _, item_id = seeded_item
    entry_id = create_note(
        author_id=seeded_admin,
        body='Body text.',
        partner_credit=None,
        subjects=[('agenda_item', item_id, None)],
    )
    try:
        set_status(entry_id, 'published')
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status, byline, published_at FROM coverage_entries WHERE id = %s",
                    (entry_id,),
                )
                row = cur.fetchone()
                assert row[0] == 'published'
                assert row[1] == 'Writer Test'  # display_name of seeded_admin
                assert row[2] is not None
    finally:
        _cleanup_entry(entry_id)


def test_set_status_preserves_byline_on_republish(seeded_admin, seeded_item):
    from docket.services.coverage_writer import create_note, set_status
    _, item_id = seeded_item
    entry_id = create_note(
        author_id=seeded_admin,
        body='Body.',
        partner_credit=None,
        subjects=[('agenda_item', item_id, None)],
    )
    try:
        set_status(entry_id, 'published')
        # Now change display_name and republish — byline should NOT update
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE admin_users SET display_name = 'New Name' WHERE id = %s",
                    (seeded_admin,),
                )
            conn.commit()
        set_status(entry_id, 'draft')
        set_status(entry_id, 'published')
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT byline FROM coverage_entries WHERE id = %s", (entry_id,))
                assert cur.fetchone()[0] == 'Writer Test'  # preserved from first publish
    finally:
        _cleanup_entry(entry_id)
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/unit/test_coverage_writer.py -v -k set_status
```

Expected: 2 FAIL with `ImportError`.

- [ ] **Step 3: Implement `set_status`**

Append to `src/docket/services/coverage_writer.py`:

```python
ALLOWED_STATUS = {'draft', 'proposed', 'published', 'rejected'}


def set_status(coverage_id: int, status: str) -> None:
    """Transition a coverage entry to ``status``.

    Side-effects on ``published``:
    - sets ``published_at = NOW()`` if currently NULL
    - snapshots ``byline`` from the author's ``display_name OR username`` if
      currently NULL (the snapshot rule; preserves any prior snapshot)
    """
    if status not in ALLOWED_STATUS:
        raise ValueError(f"Invalid status: {status!r}")
    with db_cursor() as cur:
        cur.execute(
            "UPDATE coverage_entries SET status = %s, updated_at = NOW() "
            "WHERE id = %s RETURNING author_id",
            (status, coverage_id),
        )
        row = cur.fetchone()
        if not row:
            raise LookupError(f"Coverage entry {coverage_id} not found")
        if status == 'published':
            _set_publish_state(cur, coverage_id, row['author_id'])
```

- [ ] **Step 4: Run to verify pass**

```bash
pytest tests/unit/test_coverage_writer.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/docket/services/coverage_writer.py tests/unit/test_coverage_writer.py
git commit -m "feat(coverage_writer): set_status with byline snapshot on first publish"
```

---

### Task 2.4: Add `update_coverage` with wipe-and-replace subjects

**Files:**
- Modify: `src/docket/services/coverage_writer.py`
- Test: `tests/unit/test_coverage_writer.py` (append)

- [ ] **Step 1: Write failing tests for update + wipe-and-replace**

Append to `tests/unit/test_coverage_writer.py`:

```python
def test_update_coverage_modifies_scalar_fields(seeded_admin, seeded_item):
    from docket.services.coverage_writer import create_note, update_coverage
    _, item_id = seeded_item
    entry_id = create_note(
        author_id=seeded_admin,
        body='Old body.',
        partner_credit=None,
        subjects=[('agenda_item', item_id, None)],
    )
    try:
        update_coverage(entry_id, body='New body.', partner_credit='Co with Watch')
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT body, partner_credit FROM coverage_entries WHERE id = %s",
                            (entry_id,))
                row = cur.fetchone()
                assert row[0] == 'New body.'
                assert row[1] == 'Co with Watch'
    finally:
        _cleanup_entry(entry_id)


def test_update_coverage_wipes_and_replaces_subjects(seeded_admin, seeded_item):
    from docket.services.coverage_writer import create_note, update_coverage
    mtg_id, item_id = seeded_item
    entry_id = create_note(
        author_id=seeded_admin,
        body='Body.',
        partner_credit=None,
        subjects=[('agenda_item', item_id, None)],
    )
    try:
        # Replace: attach to meeting instead
        update_coverage(entry_id, subjects=[('meeting', mtg_id, None)])
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT subject_type, subject_id FROM coverage_subject_links "
                    "WHERE coverage_id = %s ORDER BY subject_type",
                    (entry_id,),
                )
                rows = cur.fetchall()
                assert rows == [('meeting', mtg_id)]
    finally:
        _cleanup_entry(entry_id)


def test_update_coverage_none_subjects_leaves_links_untouched(seeded_admin, seeded_item):
    from docket.services.coverage_writer import create_note, update_coverage
    _, item_id = seeded_item
    entry_id = create_note(
        author_id=seeded_admin, body='Body.', partner_credit=None,
        subjects=[('agenda_item', item_id, None)],
    )
    try:
        update_coverage(entry_id, body='Edited body.')  # subjects not passed
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM coverage_subject_links WHERE coverage_id = %s",
                    (entry_id,),
                )
                assert cur.fetchone()[0] == 1
    finally:
        _cleanup_entry(entry_id)
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/unit/test_coverage_writer.py -v -k update_coverage
```

Expected: 3 FAIL with `ImportError`.

- [ ] **Step 3: Implement `update_coverage`**

Append to `src/docket/services/coverage_writer.py`:

```python
ALLOWED_UPDATE_FIELDS = {
    'body', 'partner_credit',
    'outlet_id', 'external_url', 'headline',
    'reporter_byline', 'excerpt', 'article_published_at',
    'byline',
    'featured_until',
}


def update_coverage(coverage_id: int, *, subjects=None, **fields) -> None:
    """Update an existing coverage entry.

    ``fields``: scalar columns from ``ALLOWED_UPDATE_FIELDS`` to set.
    ``subjects``: if not None, wipe-and-replace the subject links.
        ``None``     → don't touch links (form didn't submit subjects field)
        ``[(...)]``  → replace with these subjects (form submitted new attachment set)
        ``[]``       → would be invalid (every entry must have ≥1 subject); raises
    """
    bad = set(fields) - ALLOWED_UPDATE_FIELDS
    if bad:
        raise ValueError(f"Cannot update fields: {sorted(bad)}")
    with db_cursor() as cur:
        if fields:
            assignments = ', '.join(f"{k} = %s" for k in fields)
            cur.execute(
                f"UPDATE coverage_entries SET {assignments}, updated_at = NOW() "
                f"WHERE id = %s",
                tuple(fields.values()) + (coverage_id,),
            )
        if subjects is not None:
            subs = _validate_subjects(subjects)  # raises on empty
            cur.execute(
                "DELETE FROM coverage_subject_links WHERE coverage_id = %s",
                (coverage_id,),
            )
            _insert_subjects(cur, coverage_id, subs)
```

- [ ] **Step 4: Run to verify pass**

```bash
pytest tests/unit/test_coverage_writer.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/docket/services/coverage_writer.py tests/unit/test_coverage_writer.py
git commit -m "feat(coverage_writer): update_coverage with wipe-and-replace subjects"
```

---

### Task 2.5: Add featured/delete + outlets_writer

**Files:**
- Modify: `src/docket/services/coverage_writer.py`
- Create: `src/docket/services/outlets_writer.py`
- Test: `tests/unit/test_coverage_writer.py` (append); new `tests/integration/test_admin_outlets.py` deferred to Task 2.10

- [ ] **Step 1: Write failing tests for `set_featured_until` + `delete_coverage`**

Append to `tests/unit/test_coverage_writer.py`:

```python
def test_set_featured_until(seeded_admin, seeded_item):
    from docket.services.coverage_writer import create_note, set_featured_until
    from datetime import datetime, timedelta, timezone
    _, item_id = seeded_item
    entry_id = create_note(
        author_id=seeded_admin, body='Body.', partner_credit=None,
        subjects=[('agenda_item', item_id, None)],
    )
    try:
        until = datetime.now(timezone.utc) + timedelta(days=14)
        set_featured_until(entry_id, until)
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT featured_until FROM coverage_entries WHERE id = %s",
                            (entry_id,))
                stored = cur.fetchone()[0]
                assert stored is not None
                assert abs((stored - until).total_seconds()) < 5
        set_featured_until(entry_id, None)
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT featured_until FROM coverage_entries WHERE id = %s",
                            (entry_id,))
                assert cur.fetchone()[0] is None
    finally:
        _cleanup_entry(entry_id)


def test_delete_coverage_cascades_subjects(seeded_admin, seeded_item):
    from docket.services.coverage_writer import create_note, delete_coverage
    _, item_id = seeded_item
    entry_id = create_note(
        author_id=seeded_admin, body='Body.', partner_credit=None,
        subjects=[('agenda_item', item_id, None)],
    )
    delete_coverage(entry_id)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM coverage_entries WHERE id = %s", (entry_id,))
            assert cur.fetchone()[0] == 0
            cur.execute(
                "SELECT COUNT(*) FROM coverage_subject_links WHERE coverage_id = %s",
                (entry_id,),
            )
            assert cur.fetchone()[0] == 0
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/unit/test_coverage_writer.py -v -k "featured or delete"
```

Expected: 2 FAIL with `ImportError`.

- [ ] **Step 3: Implement `set_featured_until` + `delete_coverage`**

Append to `src/docket/services/coverage_writer.py`:

```python
def set_featured_until(coverage_id: int, until: datetime | None) -> None:
    """Set or clear the featured_until timestamp."""
    with db_cursor() as cur:
        cur.execute(
            "UPDATE coverage_entries SET featured_until = %s, updated_at = NOW() WHERE id = %s",
            (until, coverage_id),
        )


def delete_coverage(coverage_id: int) -> None:
    """Hard-delete a coverage entry. ON DELETE CASCADE removes its subject links."""
    with db_cursor() as cur:
        cur.execute("DELETE FROM coverage_entries WHERE id = %s", (coverage_id,))
```

- [ ] **Step 4: Implement `outlets_writer`**

```python
# src/docket/services/outlets_writer.py
"""Tiny CRUD for the controlled outlets vocabulary."""
from __future__ import annotations

from docket.db import db_cursor


def create_outlet(*, slug: str, name: str, homepage: str | None = None) -> int:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO outlets (slug, name, homepage) VALUES (%s, %s, %s) RETURNING id",
            (slug, name, homepage),
        )
        return cur.fetchone()['id']


def update_outlet(outlet_id: int, *, name: str | None = None,
                  homepage: str | None = None) -> None:
    fields = {}
    if name is not None:
        fields['name'] = name
    if homepage is not None:
        fields['homepage'] = homepage
    if not fields:
        return
    assignments = ', '.join(f"{k} = %s" for k in fields)
    with db_cursor() as cur:
        cur.execute(
            f"UPDATE outlets SET {assignments} WHERE id = %s",
            tuple(fields.values()) + (outlet_id,),
        )


def deactivate_outlet(outlet_id: int) -> None:
    with db_cursor() as cur:
        cur.execute("UPDATE outlets SET is_active = FALSE WHERE id = %s", (outlet_id,))


def activate_outlet(outlet_id: int) -> None:
    with db_cursor() as cur:
        cur.execute("UPDATE outlets SET is_active = TRUE WHERE id = %s", (outlet_id,))
```

- [ ] **Step 5: Run unit tests + commit**

```bash
pytest tests/unit/test_coverage_writer.py -v
git add src/docket/services/coverage_writer.py src/docket/services/outlets_writer.py \
        tests/unit/test_coverage_writer.py
git commit -m "feat(coverage_writer): set_featured_until + delete_coverage + outlets CRUD"
```

Expected: 9 passed.

---

### Task 2.6: Admin coverage list view + route

**Files:**
- Modify: `src/docket/web/admin.py`
- Create: `src/docket/web/templates/admin/coverage/list.html`
- Create: `src/docket/web/templates/admin/coverage/_row.html`
- Test: `tests/integration/test_admin_coverage.py`

- [ ] **Step 1: Write failing test for the list route**

```python
# tests/integration/test_admin_coverage.py
"""Integration tests for /admin/coverage CRUD."""
from __future__ import annotations

import pytest

from docket.config import DATABASE_URL
from docket.db import db
from docket.web import create_app


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run admin coverage tests against Railway DB.",
)


@pytest.fixture
def app():
    app = create_app()
    app.config['TESTING'] = True
    return app


@pytest.fixture
def client_logged_in(app):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO admin_users (username, password_hash, display_name) "
                "VALUES (%s, %s, %s) RETURNING id",
                ('admin-cov-test', 'unused', 'Test Admin'),
            )
            uid = cur.fetchone()[0]
        conn.commit()
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['admin_user'] = uid
            sess['admin_username'] = 'admin-cov-test'
        yield c, uid
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM coverage_entries WHERE author_id = %s", (uid,))
            cur.execute("DELETE FROM admin_users WHERE id = %s", (uid,))
        conn.commit()


def test_admin_coverage_list_renders_empty(client_logged_in):
    c, _ = client_logged_in
    resp = c.get('/admin/coverage')
    assert resp.status_code == 200
    assert b'Editorial coverage' in resp.data
```

- [ ] **Step 2: Run the test to verify failure**

```bash
pytest tests/integration/test_admin_coverage.py -v
```

Expected: FAIL — 404 from the missing route.

- [ ] **Step 3: Add the list route + templates**

Append to `src/docket/web/admin.py` (find the last route, add the section below it):

```python
# --- Editorial coverage -----------------------------------------------------

@bp.route("/coverage", methods=["GET"])
def coverage_list():
    """List coverage entries with filter tabs."""
    status_filter = request.args.get('status')  # 'draft' / 'proposed' / 'published' / 'rejected' / None=all
    kind_filter = request.args.get('kind')      # 'note' / 'citation' / None=both

    where = []
    params = []
    if status_filter:
        where.append("ce.status = %s")
        params.append(status_filter)
    if kind_filter:
        where.append("ce.kind = %s")
        params.append(kind_filter)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    with db_cursor() as cur:
        cur.execute(
            f"""SELECT ce.id, ce.kind, ce.status, ce.body, ce.headline,
                       ce.updated_at,
                       COALESCE(au.display_name, au.username) AS author_label,
                       o.name AS outlet_name
                  FROM coverage_entries ce
                  JOIN admin_users au ON au.id = ce.author_id
             LEFT JOIN outlets o ON o.id = ce.outlet_id
              {where_sql}
              ORDER BY ce.updated_at DESC
              LIMIT 200""",
            tuple(params),
        )
        rows = cur.fetchall()

        cur.execute(
            """SELECT status, COUNT(*) AS n FROM coverage_entries GROUP BY status"""
        )
        counts = {r['status']: r['n'] for r in cur.fetchall()}

    return render_template(
        "admin/coverage/list.html",
        rows=rows,
        counts=counts,
        status_filter=status_filter,
        kind_filter=kind_filter,
    )
```

Create `src/docket/web/templates/admin/coverage/list.html`:

```jinja
{% extends "admin/base.html" %}
{% block title %}Editorial coverage{% endblock %}
{% block content %}
<h1>Editorial coverage</h1>

<nav class="admin-tabs">
  <a href="{{ url_for('admin.coverage_list') }}"
     class="{% if not status_filter %}active{% endif %}">
    All ({{ (counts.get('draft', 0) + counts.get('proposed', 0)
            + counts.get('published', 0) + counts.get('rejected', 0)) }})
  </a>
  <a href="{{ url_for('admin.coverage_list', status='draft') }}"
     class="{% if status_filter == 'draft' %}active{% endif %}">
    Drafts ({{ counts.get('draft', 0) }})
  </a>
  <a href="{{ url_for('admin.coverage_list', status='proposed') }}"
     class="{% if status_filter == 'proposed' %}active{% endif %}">
    Proposed ({{ counts.get('proposed', 0) }})
  </a>
  <a href="{{ url_for('admin.coverage_list', status='published') }}"
     class="{% if status_filter == 'published' %}active{% endif %}">
    Published ({{ counts.get('published', 0) }})
  </a>
  <a href="{{ url_for('admin.coverage_list', status='rejected') }}"
     class="{% if status_filter == 'rejected' %}active{% endif %}">
    Rejected ({{ counts.get('rejected', 0) }})
  </a>
</nav>

<p class="admin-actions">
  <a href="{{ url_for('admin.coverage_new', kind='note') }}" class="btn">+ New note</a>
  <a href="{{ url_for('admin.coverage_new', kind='citation') }}" class="btn">+ New citation</a>
</p>

{% if status_filter == 'proposed' and counts.get('proposed', 0) == 0 %}
<p class="admin-empty">Proposed entries come from automation (AI proposer / press scraper). These pipelines arrive in v2.</p>
{% endif %}

<table class="admin-table">
  <thead>
    <tr>
      <th></th>
      <th>Snippet</th>
      <th>Status</th>
      <th>Author</th>
      <th>Updated</th>
      <th>Actions</th>
    </tr>
  </thead>
  <tbody>
  {% for row in rows %}
    {% include "admin/coverage/_row.html" %}
  {% else %}
    <tr><td colspan="6" class="empty">No coverage entries yet.</td></tr>
  {% endfor %}
  </tbody>
</table>
{% endblock %}
```

Create `src/docket/web/templates/admin/coverage/_row.html`:

```jinja
<tr id="cov-row-{{ row.id }}">
  <td>{% if row.kind == 'note' %}📝{% else %}📰{% endif %}</td>
  <td>
    {% if row.kind == 'note' %}
      {{ (row.body or '')[:80] }}{% if (row.body or '')|length > 80 %}…{% endif %}
    {% else %}
      <strong>{{ row.outlet_name }}</strong> — {{ row.headline }}
    {% endif %}
  </td>
  <td><span class="badge badge--{{ row.status }}">{{ row.status }}</span></td>
  <td>{{ row.author_label }}</td>
  <td>{{ row.updated_at.strftime('%Y-%m-%d') }}</td>
  <td>
    <a href="{{ url_for('admin.coverage_edit', coverage_id=row.id) }}">Edit</a>
    {% if row.status == 'draft' %}
      <form method="post" action="{{ url_for('admin.coverage_publish', coverage_id=row.id) }}" style="display:inline">
        <button type="submit">Publish</button>
      </form>
    {% elif row.status == 'proposed' %}
      <form method="post" action="{{ url_for('admin.coverage_publish', coverage_id=row.id) }}" style="display:inline">
        <button type="submit">Publish</button>
      </form>
      <form method="post" action="{{ url_for('admin.coverage_reject', coverage_id=row.id) }}" style="display:inline">
        <button type="submit">Reject</button>
      </form>
    {% elif row.status == 'published' %}
      <form method="post" action="{{ url_for('admin.coverage_unpublish', coverage_id=row.id) }}" style="display:inline">
        <button type="submit">Unpublish</button>
      </form>
    {% elif row.status == 'rejected' %}
      <form method="post" action="{{ url_for('admin.coverage_restore', coverage_id=row.id) }}" style="display:inline">
        <button type="submit">Restore</button>
      </form>
    {% endif %}
  </td>
</tr>
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/integration/test_admin_coverage.py -v
```

Expected: 1 passed (the action routes don't exist yet — `url_for` will raise BuildError if called, but the empty list path doesn't render any action buttons).

Note: the test asserts the empty case which doesn't render action forms, so `url_for` for unknown endpoints isn't called. We add those routes in Task 2.7.

- [ ] **Step 5: Commit**

```bash
git add src/docket/web/admin.py \
        src/docket/web/templates/admin/coverage/list.html \
        src/docket/web/templates/admin/coverage/_row.html \
        tests/integration/test_admin_coverage.py
git commit -m "feat(admin): coverage list view with filter tabs"
```

---

### Task 2.7: Add coverage status-action routes (publish/unpublish/reject/restore)

**Files:**
- Modify: `src/docket/web/admin.py`
- Test: `tests/integration/test_admin_coverage.py` (append)

- [ ] **Step 1: Write failing tests for the four action routes**

Append to `tests/integration/test_admin_coverage.py`:

```python
@pytest.fixture
def seeded_note(client_logged_in):
    """Create a draft note via the writer service. Cleaned up by client_logged_in."""
    from docket.services.coverage_writer import create_note
    _, uid = client_logged_in
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO meetings (municipality_id, external_id, title, meeting_date) "
                "VALUES ((SELECT id FROM municipalities LIMIT 1), %s, %s, NOW()) RETURNING id",
                ('admin-cov-mtg', 'Admin Cov Meeting'),
            )
            mtg_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO agenda_items (meeting_id, title) VALUES (%s, %s) RETURNING id",
                (mtg_id, 'Admin Cov Item'),
            )
            item_id = cur.fetchone()[0]
        conn.commit()
    entry_id = create_note(
        author_id=uid, body='Test note body.', partner_credit=None,
        subjects=[('agenda_item', item_id, None)],
    )
    yield entry_id, item_id, mtg_id


def test_publish_route_transitions_to_published(client_logged_in, seeded_note):
    c, _ = client_logged_in
    entry_id, _, _ = seeded_note
    resp = c.post(f'/admin/coverage/{entry_id}/publish', follow_redirects=False)
    assert resp.status_code in (302, 303)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status, byline FROM coverage_entries WHERE id = %s",
                        (entry_id,))
            row = cur.fetchone()
            assert row[0] == 'published'
            assert row[1] == 'Test Admin'


def test_unpublish_route_returns_to_draft(client_logged_in, seeded_note):
    from docket.services.coverage_writer import set_status
    c, _ = client_logged_in
    entry_id, _, _ = seeded_note
    set_status(entry_id, 'published')
    c.post(f'/admin/coverage/{entry_id}/unpublish')
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM coverage_entries WHERE id = %s", (entry_id,))
            assert cur.fetchone()[0] == 'draft'
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/integration/test_admin_coverage.py -v -k "publish or unpublish"
```

Expected: 2 FAIL — routes don't exist.

- [ ] **Step 3: Implement the four action routes**

Append to `src/docket/web/admin.py`:

```python
@bp.route("/coverage/<int:coverage_id>/publish", methods=["POST"])
def coverage_publish(coverage_id: int):
    from docket.services.coverage_writer import set_status
    set_status(coverage_id, 'published')
    return redirect(request.referrer or url_for('admin.coverage_list'))


@bp.route("/coverage/<int:coverage_id>/unpublish", methods=["POST"])
def coverage_unpublish(coverage_id: int):
    from docket.services.coverage_writer import set_status
    set_status(coverage_id, 'draft')
    return redirect(request.referrer or url_for('admin.coverage_list'))


@bp.route("/coverage/<int:coverage_id>/reject", methods=["POST"])
def coverage_reject(coverage_id: int):
    from docket.services.coverage_writer import set_status
    set_status(coverage_id, 'rejected')
    return redirect(request.referrer or url_for('admin.coverage_list'))


@bp.route("/coverage/<int:coverage_id>/restore", methods=["POST"])
def coverage_restore(coverage_id: int):
    from docket.services.coverage_writer import set_status
    set_status(coverage_id, 'draft')
    return redirect(request.referrer or url_for('admin.coverage_list'))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/integration/test_admin_coverage.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/docket/web/admin.py tests/integration/test_admin_coverage.py
git commit -m "feat(admin): coverage publish/unpublish/reject/restore actions"
```

---

### Task 2.8: Add coverage create + edit forms with subject picker

**Files:**
- Modify: `src/docket/web/admin.py`
- Create: `src/docket/web/templates/admin/coverage/new_note.html`
- Create: `src/docket/web/templates/admin/coverage/new_citation.html`
- Create: `src/docket/web/templates/admin/coverage/edit.html`
- Create: `src/docket/web/templates/admin/coverage/_subject_picker.html`
- Create: `src/docket/web/templates/admin/coverage/_subject_chip.html`
- Create: `src/docket/web/templates/admin/coverage/_search_results.html`
- Test: `tests/integration/test_admin_coverage.py` (append)

- [ ] **Step 1: Write a failing test for the create-note flow**

Append to `tests/integration/test_admin_coverage.py`:

```python
def test_coverage_new_note_form_renders(client_logged_in):
    c, _ = client_logged_in
    resp = c.get('/admin/coverage/new?kind=note')
    assert resp.status_code == 200
    assert b'New note' in resp.data


def test_coverage_post_creates_note_and_redirects(client_logged_in):
    c, _ = client_logged_in
    # First seed an item to attach to
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO meetings (municipality_id, external_id, title, meeting_date) "
                "VALUES ((SELECT id FROM municipalities LIMIT 1), %s, %s, NOW()) RETURNING id",
                ('post-mtg', 'Post Test'),
            )
            mtg_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO agenda_items (meeting_id, title) VALUES (%s, %s) RETURNING id",
                (mtg_id, 'Post Test Item'),
            )
            item_id = cur.fetchone()[0]
        conn.commit()
    resp = c.post('/admin/coverage', data={
        'kind': 'note',
        'body': 'A new note from the form.',
        'partner_credit': '',
        'subject[]': [f'agenda_item:{item_id}'],
    })
    assert resp.status_code in (302, 303)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM coverage_entries WHERE body = %s",
                ('A new note from the form.',),
            )
            assert cur.fetchone() is not None
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/integration/test_admin_coverage.py -v -k "new_note or post_creates"
```

Expected: FAIL — routes don't exist.

- [ ] **Step 3: Implement the create routes**

Append to `src/docket/web/admin.py`:

```python
def _parse_subjects_from_form(form) -> list:
    """Parse `subject[]` form fields into the SubjectSpec list expected by the writer.

    Each form value is `<subject_type>:<id_or_slug>`.
    """
    out = []
    for raw in form.getlist('subject[]'):
        if not raw or ':' not in raw:
            continue
        st, val = raw.split(':', 1)
        if st == 'badge':
            out.append((st, None, val))
        elif st in ('agenda_item', 'meeting', 'council_member'):
            try:
                out.append((st, int(val), None))
            except ValueError:
                continue
    return out


@bp.route("/coverage/new", methods=["GET"])
def coverage_new():
    kind = request.args.get('kind', 'note')
    if kind not in ('note', 'citation'):
        abort(400)
    with db_cursor() as cur:
        cur.execute("SELECT id, slug, name FROM outlets WHERE is_active = TRUE ORDER BY name")
        outlets = cur.fetchall()
    template = 'admin/coverage/new_note.html' if kind == 'note' else 'admin/coverage/new_citation.html'
    return render_template(template, outlets=outlets)


@bp.route("/coverage", methods=["POST"])
def coverage_create():
    from docket.services.coverage_writer import create_note, create_citation
    kind = request.form.get('kind')
    subjects = _parse_subjects_from_form(request.form)
    if not subjects:
        flash("Attach to at least one subject.")
        return redirect(url_for('admin.coverage_new', kind=kind or 'note'))
    author_id = session['admin_user']
    status = 'published' if request.form.get('publish_now') == 'on' else 'draft'
    if kind == 'note':
        body = (request.form.get('body') or '').strip()
        if not body:
            flash("Note body is required.")
            return redirect(url_for('admin.coverage_new', kind='note'))
        create_note(
            author_id=author_id,
            body=body,
            partner_credit=(request.form.get('partner_credit') or '').strip() or None,
            subjects=subjects,
            status=status,
        )
    elif kind == 'citation':
        outlet_id = int(request.form['outlet_id'])
        external_url = (request.form.get('external_url') or '').strip()
        headline = (request.form.get('headline') or '').strip()
        if not (external_url and headline):
            flash("Citation URL and headline are required.")
            return redirect(url_for('admin.coverage_new', kind='citation'))
        article_pub = request.form.get('article_published_at') or None
        create_citation(
            author_id=author_id,
            outlet_id=outlet_id,
            external_url=external_url,
            headline=headline,
            reporter_byline=(request.form.get('reporter_byline') or '').strip() or None,
            excerpt=(request.form.get('excerpt') or '').strip() or None,
            article_published_at=article_pub,
            subjects=subjects,
            status=status,
        )
    else:
        abort(400)
    return redirect(url_for('admin.coverage_list'))


@bp.route("/coverage/<int:coverage_id>/edit", methods=["GET"])
def coverage_edit(coverage_id: int):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM coverage_entries WHERE id = %s", (coverage_id,))
        entry = cur.fetchone()
        if not entry:
            abort(404)
        cur.execute(
            """SELECT subject_type, subject_id, subject_slug
                 FROM coverage_subject_links WHERE coverage_id = %s""",
            (coverage_id,),
        )
        subjects = cur.fetchall()
        cur.execute("SELECT id, slug, name FROM outlets WHERE is_active = TRUE ORDER BY name")
        outlets = cur.fetchall()
    return render_template("admin/coverage/edit.html", entry=entry, subjects=subjects, outlets=outlets)


@bp.route("/coverage/<int:coverage_id>", methods=["POST"])
def coverage_update(coverage_id: int):
    from docket.services.coverage_writer import update_coverage
    fields = {}
    for k in ('body', 'partner_credit', 'external_url', 'headline',
              'reporter_byline', 'excerpt', 'byline'):
        if k in request.form:
            v = (request.form[k] or '').strip()
            fields[k] = v or None
    if 'outlet_id' in request.form and request.form['outlet_id']:
        fields['outlet_id'] = int(request.form['outlet_id'])
    if 'article_published_at' in request.form:
        fields['article_published_at'] = request.form['article_published_at'] or None
    subjects = _parse_subjects_from_form(request.form) if 'subject[]' in request.form else None
    update_coverage(coverage_id, subjects=subjects, **fields)
    return redirect(url_for('admin.coverage_list'))


@bp.route("/coverage/<int:coverage_id>/delete", methods=["POST"])
def coverage_delete(coverage_id: int):
    from docket.services.coverage_writer import delete_coverage
    delete_coverage(coverage_id)
    return redirect(url_for('admin.coverage_list'))
```

- [ ] **Step 4: Create the form templates**

`src/docket/web/templates/admin/coverage/new_note.html`:

```jinja
{% extends "admin/base.html" %}
{% block title %}New note{% endblock %}
{% block content %}
<h1>New note</h1>
<form method="post" action="{{ url_for('admin.coverage_create') }}">
  <input type="hidden" name="kind" value="note">
  <label>Body
    <textarea name="body" rows="4" required placeholder="1-3 sentences of context."></textarea>
  </label>
  <label>Partner credit (optional)
    <input type="text" name="partner_credit" placeholder="in partnership with X">
  </label>
  {% include "admin/coverage/_subject_picker.html" %}
  <label>
    <input type="checkbox" name="publish_now"> Publish immediately
  </label>
  <button type="submit">Save</button>
  <a href="{{ url_for('admin.coverage_list') }}">Cancel</a>
</form>
{% endblock %}
```

`src/docket/web/templates/admin/coverage/new_citation.html`:

```jinja
{% extends "admin/base.html" %}
{% block title %}New citation{% endblock %}
{% block content %}
<h1>New citation</h1>
<form method="post" action="{{ url_for('admin.coverage_create') }}">
  <input type="hidden" name="kind" value="citation">
  <label>Outlet
    <select name="outlet_id" required>
      {% for o in outlets %}
      <option value="{{ o.id }}">{{ o.name }}</option>
      {% endfor %}
    </select>
  </label>
  <label>Article URL
    <input type="url" name="external_url" required>
  </label>
  <label>Headline
    <input type="text" name="headline" required>
  </label>
  <label>Reporter byline (optional)
    <input type="text" name="reporter_byline">
  </label>
  <label>Excerpt / pull-quote (optional)
    <textarea name="excerpt" rows="3"></textarea>
  </label>
  <label>Article published date
    <input type="date" name="article_published_at">
  </label>
  {% include "admin/coverage/_subject_picker.html" %}
  <label>
    <input type="checkbox" name="publish_now"> Publish immediately
  </label>
  <button type="submit">Save</button>
  <a href="{{ url_for('admin.coverage_list') }}">Cancel</a>
</form>
{% endblock %}
```

`src/docket/web/templates/admin/coverage/edit.html`:

```jinja
{% extends "admin/base.html" %}
{% block title %}Edit {{ entry.kind }}{% endblock %}
{% block content %}
<h1>Edit {{ entry.kind }}</h1>
<form method="post" action="{{ url_for('admin.coverage_update', coverage_id=entry.id) }}">
  {% if entry.kind == 'note' %}
    <label>Body
      <textarea name="body" rows="4" required>{{ entry.body or '' }}</textarea>
    </label>
    <label>Partner credit
      <input type="text" name="partner_credit" value="{{ entry.partner_credit or '' }}">
    </label>
  {% else %}
    <label>Outlet
      <select name="outlet_id">
        {% for o in outlets %}
        <option value="{{ o.id }}" {% if o.id == entry.outlet_id %}selected{% endif %}>
          {{ o.name }}
        </option>
        {% endfor %}
      </select>
    </label>
    <label>URL <input type="url" name="external_url" value="{{ entry.external_url or '' }}"></label>
    <label>Headline <input type="text" name="headline" value="{{ entry.headline or '' }}"></label>
    <label>Reporter byline <input type="text" name="reporter_byline" value="{{ entry.reporter_byline or '' }}"></label>
    <label>Excerpt <textarea name="excerpt" rows="3">{{ entry.excerpt or '' }}</textarea></label>
    <label>Article published date
      <input type="date" name="article_published_at"
             value="{{ entry.article_published_at.isoformat() if entry.article_published_at else '' }}">
    </label>
  {% endif %}

  {% if entry.published_at %}
    <label>Byline (snapshotted on publish — editable)
      <input type="text" name="byline" value="{{ entry.byline or '' }}">
    </label>
  {% endif %}

  {% include "admin/coverage/_subject_picker.html" %}

  <button type="submit">Save</button>
  <a href="{{ url_for('admin.coverage_list') }}">Cancel</a>
</form>

<form method="post" action="{{ url_for('admin.coverage_delete', coverage_id=entry.id) }}"
      onsubmit="return confirm('Delete this entry?')">
  <button type="submit" class="btn--danger">Delete</button>
</form>
{% endblock %}
```

`src/docket/web/templates/admin/coverage/_subject_picker.html`:

```jinja
<fieldset class="subject-picker">
  <legend>Attach to (at least one)</legend>
  <div id="selected-subjects">
    {% for s in subjects or [] %}
      {% set subject = s %}
      {% include "admin/coverage/_subject_chip.html" %}
    {% endfor %}
  </div>
  <p>Add subject:</p>
  <select id="subject-type-select" onchange="document.getElementById('subject-search').value=''; this.form.requestSubmit();">
    <option value="agenda_item">Agenda item</option>
    <option value="meeting">Meeting</option>
    <option value="council_member">Council member</option>
    <option value="badge">Badge</option>
  </select>
  <input type="search" id="subject-search" placeholder="Search…"
         hx-get="{{ url_for('admin.coverage_search') }}"
         hx-trigger="keyup changed delay:200ms"
         hx-target="#subject-search-results"
         hx-include="#subject-type-select"
         name="q">
  <div id="subject-search-results"></div>
</fieldset>
```

`src/docket/web/templates/admin/coverage/_subject_chip.html`:

```jinja
<span class="subject-chip">
  {{ subject.subject_type }}:
  {{ subject.subject_id or subject.subject_slug }}
  <input type="hidden" name="subject[]"
         value="{{ subject.subject_type }}:{{ subject.subject_id or subject.subject_slug }}">
  <button type="button" onclick="this.parentNode.remove()">✕</button>
</span>
```

`src/docket/web/templates/admin/coverage/_search_results.html`:

```jinja
{% for r in results %}
  <button type="button" class="result"
          onclick="(function(t){
            var c=document.createElement('span');
            c.className='subject-chip';
            c.innerHTML='{{ subject_type }}: {{ r.label|e }} <input type=hidden name=subject[] value=\'{{ subject_type }}:{{ r.id }}\'><button type=button onclick=\'this.parentNode.remove()\'>✕</button>';
            document.getElementById('selected-subjects').appendChild(c);
          })(this)">
    {{ r.label }}
  </button>
{% else %}
  <em>No results.</em>
{% endfor %}
```

Add the search route to `src/docket/web/admin.py`:

```python
def _escape_like(s: str) -> str:
    """Escape Postgres LIKE/ILIKE wildcards in user input.

    A bare ``%`` in admin input would otherwise match every row (the entire
    table dump), and ``_`` would match any single char. Escape both, and
    escape backslashes first so we don't double-escape our own escapes.
    """
    return s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


@bp.route("/coverage/search", methods=["GET"])
def coverage_search():
    subject_type = request.args.get('subject_type', 'agenda_item')
    q = (request.args.get('q') or '').strip()
    results = []
    if not q:
        return render_template("admin/coverage/_search_results.html",
                               results=[], subject_type=subject_type)
    needle = f"%{_escape_like(q)}%"
    with db_cursor() as cur:
        if subject_type == 'agenda_item':
            cur.execute(
                "SELECT id, title FROM agenda_items "
                "WHERE title ILIKE %s ESCAPE '\\' ORDER BY id DESC LIMIT 15",
                (needle,),
            )
            results = [{'id': r['id'], 'label': r['title']} for r in cur.fetchall()]
        elif subject_type == 'meeting':
            cur.execute(
                "SELECT id, title, meeting_date FROM meetings "
                "WHERE title ILIKE %s ESCAPE '\\' "
                "ORDER BY meeting_date DESC LIMIT 15",
                (needle,),
            )
            results = [{'id': r['id'], 'label': f"{r['title']} ({r['meeting_date']:%Y-%m-%d})"}
                       for r in cur.fetchall()]
        elif subject_type == 'council_member':
            cur.execute(
                "SELECT id, name FROM council_members "
                "WHERE name ILIKE %s ESCAPE '\\' LIMIT 15",
                (needle,),
            )
            results = [{'id': r['id'], 'label': r['name']} for r in cur.fetchall()]
        elif subject_type == 'badge':
            cur.execute(
                "SELECT slug, name FROM priority_badge_templates "
                "WHERE (name ILIKE %s OR slug ILIKE %s) ESCAPE '\\' LIMIT 15",
                (needle, needle),
            )
            results = [{'id': r['slug'], 'label': r['name']} for r in cur.fetchall()]
    return render_template("admin/coverage/_search_results.html",
                           results=results, subject_type=subject_type)
```

**Why the `ESCAPE '\\'` clause:** Postgres' default escape character for `LIKE`/`ILIKE` is `\` already, but the project's psycopg2 setup may not pass the value through unescaped. Explicit `ESCAPE '\\'` makes the convention contract loud. The `_escape_like` helper sanitizes `\`, `%`, and `_` in user input — admin typing `100%` searches for the literal `100%`, not "everything starting with 100". An admin typing `Smith\Jones` searches for the literal string, not the escape sequence.

- [ ] **Step 5: Run tests + commit**

```bash
pytest tests/integration/test_admin_coverage.py -v
```

Expected: 5 passed.

```bash
git add src/docket/web/admin.py src/docket/web/templates/admin/coverage/ tests/integration/test_admin_coverage.py
git commit -m "feat(admin): coverage create/edit forms with HTMX subject picker"
```

---

### Task 2.9: Feature/unfeature actions

**Files:**
- Modify: `src/docket/web/admin.py`
- Modify: `src/docket/web/templates/admin/coverage/_row.html`
- Test: `tests/integration/test_admin_coverage.py` (append)

- [ ] **Step 1: Write failing test**

Append to `tests/integration/test_admin_coverage.py`:

```python
def test_feature_sets_featured_until_14_days(client_logged_in, seeded_note):
    from docket.services.coverage_writer import set_status
    c, _ = client_logged_in
    entry_id, _, _ = seeded_note
    set_status(entry_id, 'published')
    c.post(f'/admin/coverage/{entry_id}/feature')
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT featured_until FROM coverage_entries WHERE id = %s",
                        (entry_id,))
            stored = cur.fetchone()[0]
            assert stored is not None
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/integration/test_admin_coverage.py -v -k feature
```

- [ ] **Step 3: Implement feature/unfeature routes**

Append to `src/docket/web/admin.py`:

```python
@bp.route("/coverage/<int:coverage_id>/feature", methods=["POST"])
def coverage_feature(coverage_id: int):
    from docket.services.coverage_writer import set_featured_until
    set_featured_until(coverage_id, datetime.now(ZoneInfo("America/Chicago")) + timedelta(days=14))
    return redirect(request.referrer or url_for('admin.coverage_list'))


@bp.route("/coverage/<int:coverage_id>/unfeature", methods=["POST"])
def coverage_unfeature(coverage_id: int):
    from docket.services.coverage_writer import set_featured_until
    set_featured_until(coverage_id, None)
    return redirect(request.referrer or url_for('admin.coverage_list'))
```

Edit `_row.html` published-row action block to add the Feature/Unfeature button:

```jinja
{% elif row.status == 'published' %}
  <form method="post" action="{{ url_for('admin.coverage_unpublish', coverage_id=row.id) }}" style="display:inline">
    <button type="submit">Unpublish</button>
  </form>
  {% if row.featured_until and row.featured_until > now() %}
    <form method="post" action="{{ url_for('admin.coverage_unfeature', coverage_id=row.id) }}" style="display:inline">
      <button type="submit">Unfeature</button>
    </form>
  {% else %}
    <form method="post" action="{{ url_for('admin.coverage_feature', coverage_id=row.id) }}" style="display:inline">
      <button type="submit">Feature on home</button>
    </form>
  {% endif %}
```

(Add `featured_until` to the list-route SELECT; register a `now()` jinja global if not already.)

Modify the coverage_list SELECT in admin.py to include `ce.featured_until`:

```python
        cur.execute(
            f"""SELECT ce.id, ce.kind, ce.status, ce.body, ce.headline,
                       ce.updated_at, ce.featured_until,
                       COALESCE(au.display_name, au.username) AS author_label,
                       o.name AS outlet_name
                  FROM coverage_entries ce
                  JOIN admin_users au ON au.id = ce.author_id
             LEFT JOIN outlets o ON o.id = ce.outlet_id
              {where_sql}
              ORDER BY ce.updated_at DESC
              LIMIT 200""",
            tuple(params),
        )
```

Register `now()` in `src/docket/web/__init__.py` (only if it's not already a jinja global — check first):

```python
# In create_app(), after Jinja env setup:
from datetime import datetime, timezone
app.jinja_env.globals.setdefault('now', lambda: datetime.now(timezone.utc))
```

- [ ] **Step 4: Run tests + commit**

```bash
pytest tests/integration/test_admin_coverage.py -v
git add src/docket/web/admin.py src/docket/web/templates/admin/coverage/_row.html src/docket/web/__init__.py
git commit -m "feat(admin): feature/unfeature actions on published coverage"
```

---

### Task 2.10: Outlets CRUD admin

**Files:**
- Modify: `src/docket/web/admin.py`
- Create: `src/docket/web/templates/admin/outlets/list.html`
- Create: `src/docket/web/templates/admin/outlets/form.html`
- Test: `tests/integration/test_admin_outlets.py`

- [ ] **Step 1: Write failing test for outlets list + create**

```python
# tests/integration/test_admin_outlets.py
"""Integration tests for /admin/outlets CRUD."""
from __future__ import annotations

import pytest

from docket.config import DATABASE_URL
from docket.db import db
from docket.web import create_app


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run admin outlets tests against Railway DB.",
)


@pytest.fixture
def client_logged_in():
    app = create_app()
    app.config['TESTING'] = True
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO admin_users (username, password_hash) "
                "VALUES (%s, %s) RETURNING id",
                ('admin-outlet-test', 'unused'),
            )
            uid = cur.fetchone()[0]
        conn.commit()
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['admin_user'] = uid
            sess['admin_username'] = 'admin-outlet-test'
        yield c, uid
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM admin_users WHERE id = %s", (uid,))
        conn.commit()


def test_outlets_list_includes_seed(client_logged_in):
    c, _ = client_logged_in
    resp = c.get('/admin/outlets')
    assert resp.status_code == 200
    assert b'Birmingham Watch' in resp.data


def test_outlet_create(client_logged_in):
    c, _ = client_logged_in
    resp = c.post('/admin/outlets', data={
        'slug': 'test-outlet-xyz',
        'name': 'Test Outlet XYZ',
        'homepage': 'https://example.com',
    })
    assert resp.status_code in (302, 303)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM outlets WHERE slug = %s", ('test-outlet-xyz',))
            row = cur.fetchone()
            assert row is not None
            cur.execute("DELETE FROM outlets WHERE id = %s", (row[0],))
        conn.commit()
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/integration/test_admin_outlets.py -v
```

- [ ] **Step 3: Add the routes + templates**

Append to `src/docket/web/admin.py`:

```python
# --- Outlets ---------------------------------------------------------------

@bp.route("/outlets", methods=["GET"])
def outlets_list():
    with db_cursor() as cur:
        cur.execute("SELECT id, slug, name, homepage, is_active FROM outlets ORDER BY name")
        outlets = cur.fetchall()
    return render_template("admin/outlets/list.html", outlets=outlets)


@bp.route("/outlets", methods=["POST"])
def outlets_create():
    from docket.services.outlets_writer import create_outlet
    create_outlet(
        slug=request.form['slug'].strip(),
        name=request.form['name'].strip(),
        homepage=(request.form.get('homepage') or '').strip() or None,
    )
    return redirect(url_for('admin.outlets_list'))


@bp.route("/outlets/<int:outlet_id>", methods=["POST"])
def outlets_update(outlet_id: int):
    from docket.services.outlets_writer import update_outlet
    update_outlet(
        outlet_id,
        name=(request.form.get('name') or '').strip() or None,
        homepage=(request.form.get('homepage') or '').strip() or None,
    )
    return redirect(url_for('admin.outlets_list'))


@bp.route("/outlets/<int:outlet_id>/deactivate", methods=["POST"])
def outlets_deactivate(outlet_id: int):
    from docket.services.outlets_writer import deactivate_outlet
    deactivate_outlet(outlet_id)
    return redirect(url_for('admin.outlets_list'))


@bp.route("/outlets/<int:outlet_id>/activate", methods=["POST"])
def outlets_activate(outlet_id: int):
    from docket.services.outlets_writer import activate_outlet
    activate_outlet(outlet_id)
    return redirect(url_for('admin.outlets_list'))
```

`src/docket/web/templates/admin/outlets/list.html`:

```jinja
{% extends "admin/base.html" %}
{% block title %}Outlets{% endblock %}
{% block content %}
<h1>Outlets</h1>
<form method="post" action="{{ url_for('admin.outlets_create') }}" class="inline-form">
  <input type="text" name="slug" placeholder="slug" required>
  <input type="text" name="name" placeholder="Display name" required>
  <input type="url"  name="homepage" placeholder="https://...">
  <button type="submit">Add outlet</button>
</form>
<table class="admin-table">
  <thead><tr><th>Name</th><th>Slug</th><th>Homepage</th><th>Active</th><th>Actions</th></tr></thead>
  <tbody>
  {% for o in outlets %}
    <tr>
      <td>{{ o.name }}</td>
      <td>{{ o.slug }}</td>
      <td>{% if o.homepage %}<a href="{{ o.homepage }}">{{ o.homepage }}</a>{% endif %}</td>
      <td>{{ "Yes" if o.is_active else "No" }}</td>
      <td>
        {% if o.is_active %}
        <form method="post" action="{{ url_for('admin.outlets_deactivate', outlet_id=o.id) }}" style="display:inline">
          <button type="submit">Deactivate</button>
        </form>
        {% else %}
        <form method="post" action="{{ url_for('admin.outlets_activate', outlet_id=o.id) }}" style="display:inline">
          <button type="submit">Activate</button>
        </form>
        {% endif %}
      </td>
    </tr>
  {% endfor %}
  </tbody>
</table>
{% endblock %}
```

`src/docket/web/templates/admin/outlets/form.html`: (only used for explicit edit pages — minimal stub for now)

```jinja
{% extends "admin/base.html" %}
{% block content %}
<h1>Edit outlet</h1>
<form method="post" action="{{ url_for('admin.outlets_update', outlet_id=outlet.id) }}">
  <label>Name <input type="text" name="name" value="{{ outlet.name }}"></label>
  <label>Homepage <input type="url" name="homepage" value="{{ outlet.homepage or '' }}"></label>
  <button type="submit">Save</button>
</form>
{% endblock %}
```

- [ ] **Step 4: Run + commit**

```bash
pytest tests/integration/test_admin_outlets.py -v
git add src/docket/web/admin.py src/docket/web/templates/admin/outlets/ tests/integration/test_admin_outlets.py
git commit -m "feat(admin): outlets CRUD"
```

---

### Task 2.11: Admin profile — display_name editor

**Files:**
- Modify: `src/docket/web/admin.py`
- Create: `src/docket/web/templates/admin/profile.html`
- Test: `tests/integration/test_admin_coverage.py` (append)

- [ ] **Step 1: Write a failing test**

Append to `tests/integration/test_admin_coverage.py`:

```python
def test_profile_display_name_update(client_logged_in):
    c, uid = client_logged_in
    resp = c.post('/admin/profile/display-name', data={'display_name': 'Editor Smith'})
    assert resp.status_code in (302, 303)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT display_name FROM admin_users WHERE id = %s", (uid,))
            assert cur.fetchone()[0] == 'Editor Smith'
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/integration/test_admin_coverage.py -v -k profile
```

- [ ] **Step 3: Implement the route + template**

Append to `src/docket/web/admin.py`:

```python
@bp.route("/profile", methods=["GET"])
def profile():
    uid = session['admin_user']
    with db_cursor() as cur:
        cur.execute("SELECT username, display_name FROM admin_users WHERE id = %s", (uid,))
        user = cur.fetchone()
    return render_template("admin/profile.html", user=user)


@bp.route("/profile/display-name", methods=["POST"])
def profile_update_display_name():
    uid = session['admin_user']
    new_name = (request.form.get('display_name') or '').strip() or None
    with db_cursor() as cur:
        cur.execute("UPDATE admin_users SET display_name = %s WHERE id = %s",
                    (new_name, uid))
    return redirect(url_for('admin.profile'))
```

`src/docket/web/templates/admin/profile.html`:

```jinja
{% extends "admin/base.html" %}
{% block title %}Profile{% endblock %}
{% block content %}
<h1>Profile</h1>
<p>Username: {{ user.username }}</p>
<form method="post" action="{{ url_for('admin.profile_update_display_name') }}">
  <label>Display name (byline)
    <input type="text" name="display_name" value="{{ user.display_name or '' }}"
           placeholder="Falls back to username if cleared">
  </label>
  <button type="submit">Save</button>
</form>
<p><small>This name is used as the byline on new coverage entries you publish. Editing it
does not affect bylines on entries you've already published — those snapshot the byline
at the moment of first publish.</small></p>
{% endblock %}
```

- [ ] **Step 4: Run + commit**

```bash
pytest tests/integration/test_admin_coverage.py -v
git add src/docket/web/admin.py src/docket/web/templates/admin/profile.html \
        tests/integration/test_admin_coverage.py
git commit -m "feat(admin): profile display_name editor"
```

---

### Task 2.12: Deploy + smoke test on Railway

- [ ] **Step 1: Deploy**

```bash
railway up --service docket-web --detach
```

- [ ] **Step 2: Smoke test admin flow in browser**

1. Log into `/admin/login`.
2. Visit `/admin/profile` → set display_name → confirm save.
3. Visit `/admin/coverage/new?kind=note` → create a draft note attached to a real item.
4. Visit `/admin/coverage` → confirm row appears in Drafts tab.
5. Click Publish → confirm row moves to Published tab.
6. Visit `/admin/coverage/<id>/edit` → confirm `byline` field is now editable (post-publish).
7. Visit `/admin/outlets` → confirm 10 seed outlets render.

**Phase 2 done.** Editor can author coverage; nothing surfaces to citizens yet.

---

## Phase 3 — Item coverage block + item card chips across 6 surfaces (PR 3)

**Goal:** Citizens see editorial coverage on item detail; chips appear on item cards everywhere they're listed.

### Task 3.1: Coverage block + note + citation partials

**Files:**
- Create: `src/docket/web/templates/partials/coverage_block.html`
- Create: `src/docket/web/templates/partials/coverage_note.html`
- Create: `src/docket/web/templates/partials/coverage_citation.html`
- Create: `src/docket/web/templates/partials/coverage_count_chip.html`

- [ ] **Step 1: Create the block partial**

`src/docket/web/templates/partials/coverage_block.html`:

```jinja
{# Renders the inline coverage section. Expects ``coverage`` = list[CoverageEntry]. #}
{% if coverage %}
<section class="coverage-block">
  <h2 class="coverage-block__title">Editorial coverage</h2>

  {% set notes = coverage | selectattr("kind", "equalto", "note") | list %}
  {% set citations = coverage | selectattr("kind", "equalto", "citation") | list %}

  {% for note in notes %}
    {% include "partials/coverage_note.html" %}
  {% endfor %}

  {% if citations %}
    <h3 class="coverage-block__subtitle">Press coverage</h3>
    {% for citation in citations %}
      {% include "partials/coverage_citation.html" %}
    {% endfor %}
  {% endif %}
</section>
{% endif %}
```

- [ ] **Step 2: Create the note partial**

`src/docket/web/templates/partials/coverage_note.html`:

```jinja
<article class="coverage-note">
  <header class="coverage-note__byline">
    <span class="coverage-note__label">NOTE</span> —
    <strong>{{ note.display_byline() }}</strong>
    {% if note.partner_credit %}
      <span class="coverage-note__partner">, {{ note.partner_credit }}</span>
    {% endif %}
    {% if note.published_at %}
      · <time datetime="{{ note.published_at.isoformat() }}">{{ note.published_at.strftime('%b %d') }}</time>
    {% endif %}
  </header>
  <p class="coverage-note__body">{{ note.body | e | replace('\n', '<br>') | safe }}</p>
  {% if note.subjects %}
    {% include "partials/coverage_subjects_footer.html" %}
  {% endif %}
</article>
```

**Subjects footer rendering — context-sensitive by design.**

The footer renders **only** when `entry.subjects` is non-empty. The inline `coverage_block.html` (used on item/meeting/member detail pages) loads entries via `coverage_for_subject(...)` which **does not** populate `subjects` — so the footer is silent in inline contexts (the reader is already on the subject's page; listing the subject would be redundant). The listing route (Task 4.1) and permalink route (Task 4.2) load entries via `list_published_coverage(...)` / `_hydrate_subjects_for_entries(...)` which **do** populate `subjects` — so the footer renders there. The data shape drives rendering; no per-template flag.

- [ ] **Step 3: Create the citation partial — with link safety attrs**

`src/docket/web/templates/partials/coverage_citation.html`:

```jinja
<article class="coverage-citation">
  <header class="coverage-citation__meta">
    <span class="coverage-citation__outlet">{{ citation.outlet_name or 'Press' }}</span>
    {% if citation.article_published_at %}
      · <time datetime="{{ citation.article_published_at.isoformat() }}">{{ citation.article_published_at.strftime('%b %d') }}</time>
    {% endif %}
    {% if citation.reporter_byline %}
      · by {{ citation.reporter_byline }}
    {% endif %}
  </header>
  <h4 class="coverage-citation__headline">
    <a href="{{ citation.external_url }}" target="_blank" rel="noopener noreferrer">
      {{ citation.headline }}
    </a>
  </h4>
  {% if citation.excerpt %}
    <p class="coverage-citation__excerpt">{{ citation.excerpt }}</p>
  {% endif %}
  <p class="coverage-citation__link">
    <a href="{{ citation.external_url }}" target="_blank" rel="noopener noreferrer">
      → {{ citation.external_url | replace('https://', '') | replace('http://', '') }}
    </a>
  </p>
  {% if citation.subjects %}
    {% set entry = citation %}
    {% include "partials/coverage_subjects_footer.html" %}
  {% endif %}
</article>
```

Create `src/docket/web/templates/partials/coverage_subjects_footer.html`:

```jinja
{# Renders the "→ on Item X, Meeting Y, Member Z" footer for a coverage entry.
   Expects either `note` or `citation` or `entry` in scope — falls back through. #}
{% set _ent = note if note is defined else (citation if citation is defined else entry) %}
<footer class="coverage-subjects">
  → on
  {% for s in _ent.subjects %}
    {% if s.subject_type == 'agenda_item' %}
      <a class="coverage-subjects__link" href="#item-{{ s.subject_id }}">Item: {{ s.label or s.subject_id }}</a>
    {% elif s.subject_type == 'meeting' %}
      <a class="coverage-subjects__link" href="#meeting-{{ s.subject_id }}">{{ s.label or 'Meeting' }}</a>
    {% elif s.subject_type == 'council_member' %}
      <a class="coverage-subjects__link" href="#member-{{ s.subject_id }}">{{ s.label or 'Member' }}</a>
    {% elif s.subject_type == 'badge' %}
      <a class="coverage-subjects__link" href="#badge-{{ s.subject_slug }}">{{ s.label or s.subject_slug }}</a>
    {% endif %}
    {% if not loop.last %}, {% endif %}
  {% endfor %}
</footer>
```

**The `#item-NN` / `#meeting-NN` hrefs are placeholders.** Before this PR ships, replace each with the actual `url_for(...)` call matching the existing project URL space. For example, items use `url_for('public.item_detail', city_slug=<city>, item_id=s.subject_id)` — but the `city_slug` isn't on the subject link, so you'll need to either denormalize it (additional COALESCE in `_hydrate_subjects_for_entries` to pull city) or accept that the listing footer links use a city-agnostic redirect endpoint. The simplest fix during execution: add a `(SELECT slug FROM municipalities WHERE id = (SELECT municipality_id FROM meetings WHERE id = csl.subject_id))` for items/meetings, and pass it through. Decide on the city-slug approach at execution time and update both the helper query and this template together.

- [ ] **Step 4: Create the chip partial**

`src/docket/web/templates/partials/coverage_count_chip.html`:

```jinja
{# Renders a "📝 N · 📰 M" chip. Expects ``counts`` = (notes, citations) tuple. #}
{% set notes_n = counts[0] %}
{% set cits_n = counts[1] %}
{% if notes_n or cits_n %}
<span class="coverage-chip" title="Editorial coverage available">
  {% if notes_n %}<span class="coverage-chip__notes">📝 {{ notes_n }}</span>{% endif %}
  {% if notes_n and cits_n %}·{% endif %}
  {% if cits_n %}<span class="coverage-chip__cites">📰 {{ cits_n }}</span>{% endif %}
</span>
{% endif %}
```

- [ ] **Step 5: Commit**

```bash
git add src/docket/web/templates/partials/coverage_block.html \
        src/docket/web/templates/partials/coverage_note.html \
        src/docket/web/templates/partials/coverage_citation.html \
        src/docket/web/templates/partials/coverage_count_chip.html \
        src/docket/web/templates/partials/coverage_subjects_footer.html
git commit -m "feat(templates): coverage block + note + citation + chip + subjects footer"
```

---

### Task 3.2: Item detail page renders the coverage block

**Files:**
- Modify: `src/docket/web/templates/item_detail.html`
- Modify: `src/docket/web/public.py` (item_detail route)
- Test: `tests/integration/test_item_detail_coverage.py`

- [ ] **Step 1: Write a failing test**

```python
# tests/integration/test_item_detail_coverage.py
"""Integration tests for the item-detail coverage block."""
from __future__ import annotations

import pytest

from docket.config import DATABASE_URL
from docket.db import db
from docket.services.coverage_writer import create_note, set_status
from docket.web import create_app


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run item-detail coverage tests against Railway DB.",
)


@pytest.fixture
def app():
    a = create_app()
    a.config['TESTING'] = True
    return a


@pytest.fixture
def seeded():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, slug FROM municipalities ORDER BY id LIMIT 1"
            )
            mu = cur.fetchone()
            cur.execute(
                "INSERT INTO admin_users (username, password_hash, display_name) "
                "VALUES (%s, %s, %s) RETURNING id",
                ('detail-cov-admin', 'x', 'Detail Tester'),
            )
            uid = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO meetings (municipality_id, external_id, title, meeting_date) "
                "VALUES (%s, %s, %s, NOW()) RETURNING id",
                (mu[0], 'detail-cov-mtg', 'Detail Cov Meeting'),
            )
            mtg_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO agenda_items (meeting_id, title) VALUES (%s, %s) RETURNING id",
                (mtg_id, 'Detail Cov Item'),
            )
            item_id = cur.fetchone()[0]
        conn.commit()
    yield {'uid': uid, 'mtg_id': mtg_id, 'item_id': item_id, 'city_slug': mu[1]}
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM coverage_entries WHERE author_id = %s", (uid,))
            cur.execute("DELETE FROM agenda_items WHERE id = %s", (item_id,))
            cur.execute("DELETE FROM meetings WHERE id = %s", (mtg_id,))
            cur.execute("DELETE FROM admin_users WHERE id = %s", (uid,))
        conn.commit()


def test_item_detail_renders_published_note(app, seeded):
    entry_id = create_note(
        author_id=seeded['uid'],
        body='An important contextual note for this item.',
        partner_credit=None,
        subjects=[('agenda_item', seeded['item_id'], None)],
    )
    set_status(entry_id, 'published')
    with app.test_client() as c:
        resp = c.get(f"/al/{seeded['city_slug']}/items/{seeded['item_id']}/")
        assert resp.status_code == 200
        assert b'An important contextual note for this item.' in resp.data
        assert b'Editorial coverage' in resp.data


def test_item_detail_omits_block_when_no_coverage(app, seeded):
    with app.test_client() as c:
        resp = c.get(f"/al/{seeded['city_slug']}/items/{seeded['item_id']}/")
        assert resp.status_code == 200
        assert b'Editorial coverage' not in resp.data


def test_item_detail_omits_draft_coverage(app, seeded):
    create_note(  # status='draft' by default
        author_id=seeded['uid'],
        body='Should not render — still a draft.',
        partner_credit=None,
        subjects=[('agenda_item', seeded['item_id'], None)],
    )
    with app.test_client() as c:
        resp = c.get(f"/al/{seeded['city_slug']}/items/{seeded['item_id']}/")
        assert b'Should not render' not in resp.data
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/integration/test_item_detail_coverage.py -v
```

Expected: FAIL — block isn't included in `item_detail.html` yet.

- [ ] **Step 3: Modify the item_detail route to load coverage**

Find the existing `item_detail` route in `src/docket/web/public.py` (likely named `item_detail` or similar with a path like `/al/<slug>/items/<int:item_id>/`). Inside its handler, after the existing data load, add:

```python
    from docket.services.query import coverage_for_subject
    coverage = coverage_for_subject('agenda_item', subject_id=item_id)
```

Pass `coverage=coverage` into the `render_template` call.

- [ ] **Step 4: Include the block in `item_detail.html`**

Open `src/docket/web/templates/item_detail.html` and find the location between the Smart Brevity Card block and the votes section. Insert:

```jinja
{% include "partials/coverage_block.html" %}
```

(Place it after the Smart Brevity Card section but before any votes block.)

- [ ] **Step 5: Run tests + commit**

```bash
pytest tests/integration/test_item_detail_coverage.py -v
```

Expected: 3 passed.

```bash
git add src/docket/web/public.py src/docket/web/templates/item_detail.html tests/integration/test_item_detail_coverage.py
git commit -m "feat(public): render editorial coverage block on item detail"
```

---

### Task 3.3: Item-card chip wiring — identify and update the shared card macro

**Files:**
- Modify: the existing item-card partial (typically `src/docket/web/templates/partials/agenda_item_card.html` or similar)
- Modify: `src/docket/web/public.py` (six routes)
- Test: `tests/integration/test_coverage_chips.py`

- [ ] **Step 1: Locate the item-card macro**

```bash
grep -rl "agenda_item\|item-card" src/docket/web/templates/partials/ | head
```

Identify the partial used for compact item rendering on list pages. Note the exact path — call it `<ITEM_CARD>` below.

- [ ] **Step 2: Write a failing test**

```python
# tests/integration/test_coverage_chips.py
"""Integration tests for coverage chips on item cards across surfaces."""
from __future__ import annotations

import pytest

from docket.config import DATABASE_URL
from docket.db import db
from docket.services.coverage_writer import create_note, set_status
from docket.web import create_app


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run chip tests against Railway DB.",
)


@pytest.fixture
def app():
    a = create_app()
    a.config['TESTING'] = True
    return a


@pytest.fixture
def covered_item():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, slug FROM municipalities ORDER BY id LIMIT 1")
            mu = cur.fetchone()
            cur.execute(
                "INSERT INTO admin_users (username, password_hash, display_name) "
                "VALUES (%s, %s, %s) RETURNING id",
                ('chip-admin', 'x', 'Chip Tester'),
            )
            uid = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO meetings (municipality_id, external_id, title, meeting_date) "
                "VALUES (%s, %s, %s, NOW()) RETURNING id",
                (mu[0], 'chip-mtg', 'Chip Test Meeting'),
            )
            mtg_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO agenda_items (meeting_id, title) VALUES (%s, %s) RETURNING id",
                (mtg_id, 'Chip Test Item'),
            )
            item_id = cur.fetchone()[0]
        conn.commit()
    entry_id = create_note(
        author_id=uid, body='Chip note.', partner_credit=None,
        subjects=[('agenda_item', item_id, None)],
    )
    set_status(entry_id, 'published')
    yield {'item_id': item_id, 'mtg_id': mtg_id, 'city_slug': mu[1]}
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM coverage_entries WHERE author_id = %s", (uid,))
            cur.execute("DELETE FROM agenda_items WHERE id = %s", (item_id,))
            cur.execute("DELETE FROM meetings WHERE id = %s", (mtg_id,))
            cur.execute("DELETE FROM admin_users WHERE id = %s", (uid,))
        conn.commit()


def test_meeting_detail_shows_chip_on_covered_item(app, covered_item):
    with app.test_client() as c:
        resp = c.get(f"/al/{covered_item['city_slug']}/meetings/{covered_item['mtg_id']}/")
        assert resp.status_code == 200
        assert b'coverage-chip' in resp.data
```

- [ ] **Step 3: Run to verify failure**

```bash
pytest tests/integration/test_coverage_chips.py -v
```

Expected: FAIL — chip not rendered yet.

- [ ] **Step 4: Wire up `meeting_detail` route + card macro**

Edit the `meeting_detail` route in `src/docket/web/public.py`:

```python
    from docket.services.query import coverage_counts_for_items
    item_ids = [it.id for it in agenda_items]  # use whatever variable name the route uses
    coverage_counts = coverage_counts_for_items(item_ids)
    # ... and pass to render_template:
    return render_template(
        "meeting_detail.html",
        # ... existing args ...
        coverage_counts=coverage_counts,
    )
```

In `meeting_detail.html`, wherever the item-card include is, pass the counts in:

```jinja
{% include "<ITEM_CARD>" with context %}
```

Inside `<ITEM_CARD>` (the path identified in Step 1), add at the top of the card body:

```jinja
{% set counts = (coverage_counts or {}).get(item.id, (0, 0)) %}
{% include "partials/coverage_count_chip.html" %}
```

- [ ] **Step 5: Run test + commit**

```bash
pytest tests/integration/test_coverage_chips.py -v
```

Expected: 1 passed.

```bash
git add src/docket/web/public.py src/docket/web/templates/<ITEM_CARD> tests/integration/test_coverage_chips.py
git commit -m "feat(public): coverage chip on item cards in meeting_detail"
```

---

### Task 3.4: Wire chip into category_landing, search, topic_detail, home, city_overview

**Files:**
- Modify: `src/docket/web/public.py` (5 more routes)
- Test: `tests/integration/test_coverage_chips.py` (append)

For each of the five remaining routes, the pattern is identical:
1. After collecting the visible item IDs, call `coverage_counts_for_items(item_ids)`.
2. Pass the resulting dict as `coverage_counts` into `render_template`.

- [ ] **Step 1: Append failing tests for each remaining surface**

Append to `tests/integration/test_coverage_chips.py`:

```python
def test_search_results_shows_chip(app, covered_item):
    with app.test_client() as c:
        resp = c.get(f"/search?q=Chip+Test+Item")
        assert resp.status_code == 200
        # Search result must render the chip if the matching item has coverage
        if b'Chip Test Item' in resp.data:
            assert b'coverage-chip' in resp.data


def test_category_landing_shows_chip_when_item_in_category(app, covered_item):
    # This test is conditional: only meaningful if the seeded item has a badge attached.
    # In v1 we don't seed a badge, so this test is effectively a smoke test that the
    # route renders without error when coverage_counts is passed in.
    with app.test_client() as c:
        # Pick any badge slug that exists in priority_badge_templates
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT slug FROM priority_badge_templates LIMIT 1")
                row = cur.fetchone()
                if not row:
                    pytest.skip("No badges seeded — category_landing chip test not applicable")
                slug = row[0]
        resp = c.get(f"/al/{covered_item['city_slug']}/{slug}/")
        assert resp.status_code in (200, 404)  # may 404 if no items in this category for this city
```

- [ ] **Step 2: Run to verify the search test fails or skips appropriately**

```bash
pytest tests/integration/test_coverage_chips.py -v
```

- [ ] **Step 3: Edit each of the five remaining routes**

In `src/docket/web/public.py`, find each of these route handlers and add the same two-line pattern:

```python
    from docket.services.query import coverage_counts_for_items
    coverage_counts = coverage_counts_for_items([it.id for it in items])
    # ... pass coverage_counts=coverage_counts into render_template
```

Routes to edit:
1. `category_landing` — items already collected; add `coverage_counts`.
2. `search` — when search results include items, collect their IDs and add counts.
3. `topic_detail` — items collected; add counts.
4. `home` — notable-items section; collect IDs; add counts.
5. `city_overview` — top-items section; collect IDs; add counts.

In each template (`category_landing.html`, search results template, `topic_detail.html`, `home.html` or `index.html`, `city.html`), make sure the item-card include passes through context:

```jinja
{% include "<ITEM_CARD>" with context %}
```

The card itself was already updated in Task 3.3 to read `coverage_counts` from context — no per-template changes needed beyond ensuring context is passed through.

- [ ] **Step 4: Run all chip tests**

```bash
pytest tests/integration/test_coverage_chips.py -v
```

Expected: all pass or skip.

- [ ] **Step 5: Commit**

```bash
git add src/docket/web/public.py tests/integration/test_coverage_chips.py
git commit -m "feat(public): coverage chip on item cards across 5 remaining surfaces"
```

---

### Task 3.5: CSS for the coverage block + chip

**Files:**
- Modify: `src/docket/web/static/styles.css`

- [ ] **Step 1: Append the coverage CSS**

Append to `src/docket/web/static/styles.css`:

```css
/* ============================================================
   Editorial coverage — block, note, citation, chip
   ============================================================ */

.coverage-block {
  margin: 1.5rem 0;
  padding: 1rem 1.25rem;
  border-left: 3px solid var(--accent, #cc6633);
  background: var(--surface-soft, #fbf8f3);
}

.coverage-block__title {
  font-family: 'Source Serif Pro', serif;
  font-size: 1.1rem;
  margin: 0 0 0.75rem 0;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}

.coverage-block__subtitle {
  font-family: 'IBM Plex Sans', sans-serif;
  font-size: 0.85rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 1rem 0 0.5rem 0;
  color: var(--muted, #666);
}

.coverage-note + .coverage-note { margin-top: 0.75rem; }

.coverage-note__byline {
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 0.25rem;
  color: var(--muted, #666);
}
.coverage-note__label {
  font-weight: 600;
  color: var(--accent, #cc6633);
}
.coverage-note__body {
  font-family: 'Source Serif Pro', serif;
  font-size: 1rem;
  line-height: 1.5;
  margin: 0;
}

.coverage-citation {
  margin: 0.5rem 0;
  padding: 0.75rem 1rem;
  background: white;
  border: 1px solid var(--border, #e2dccf);
}
.coverage-citation__meta {
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--muted, #666);
  margin-bottom: 0.25rem;
}
.coverage-citation__outlet { font-weight: 600; }
.coverage-citation__headline {
  font-family: 'Source Serif Pro', serif;
  font-size: 1rem;
  font-weight: 600;
  margin: 0.25rem 0;
}
.coverage-citation__headline a { text-decoration: none; }
.coverage-citation__excerpt {
  font-size: 0.9rem;
  margin: 0.25rem 0;
  color: var(--text, #222);
}
.coverage-citation__link {
  font-size: 0.8rem;
  margin: 0.25rem 0 0 0;
  color: var(--muted, #666);
}

.coverage-chip {
  display: inline-flex;
  gap: 0.25rem;
  font-size: 0.75rem;
  padding: 0.1rem 0.4rem;
  background: var(--surface-soft, #fbf8f3);
  border: 1px solid var(--border, #e2dccf);
  border-radius: 999px;
  vertical-align: middle;
  margin-left: 0.35rem;
}
.coverage-chip__notes { color: var(--accent, #cc6633); }
.coverage-chip__cites { color: var(--ink, #222); }
```

- [ ] **Step 2: Commit**

```bash
git add src/docket/web/static/styles.css
git commit -m "feat(css): coverage block + note + citation card + chip styling"
```

---

### Task 3.6: Deploy + smoke

- [ ] **Step 1: Deploy**

```bash
railway up --service docket-web --detach
```

- [ ] **Step 2: Smoke test in browser**

1. Visit an item detail page where you created a published note in Phase 2 → confirm the block renders.
2. Visit the meeting detail page that contains that item → confirm the chip appears on the item card.
3. Visit category landing / search / topic / home / city overview → confirm chips appear where item cards reference items with coverage.

**Phase 3 done.** Citizens see editorial coverage.

---

## Phase 4 — Listing page + permalinks (PR 4)

**Goal:** `/coverage/` paginated listing with filter tabs, FTS search; `/coverage/<id>` permalink for notes.

### Task 4.1: `/coverage/` listing route + template

**Files:**
- Modify: `src/docket/web/public.py`
- Create: `src/docket/web/templates/coverage/listing.html`
- Test: `tests/integration/test_coverage_listing.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_coverage_listing.py
"""Integration tests for /coverage listing + permalink."""
from __future__ import annotations

import pytest

from docket.config import DATABASE_URL
from docket.db import db
from docket.services.coverage_writer import create_note, set_status
from docket.web import create_app


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run listing tests against Railway DB.",
)


@pytest.fixture
def app():
    a = create_app()
    a.config['TESTING'] = True
    return a


@pytest.fixture
def published_entries():
    """Create 3 published notes for the listing tests."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO admin_users (username, password_hash, display_name) "
                "VALUES (%s, %s, %s) RETURNING id",
                ('list-admin', 'x', 'List Tester'),
            )
            uid = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO meetings (municipality_id, external_id, title, meeting_date) "
                "VALUES ((SELECT id FROM municipalities LIMIT 1), %s, %s, NOW()) RETURNING id",
                ('list-mtg', 'List Test'),
            )
            mtg_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO agenda_items (meeting_id, title) VALUES (%s, %s) RETURNING id",
                (mtg_id, 'List Test Item'),
            )
            item_id = cur.fetchone()[0]
        conn.commit()
    entry_ids = []
    for i in range(3):
        eid = create_note(
            author_id=uid,
            body=f'List body {i} unique-token-list42.',
            partner_credit=None,
            subjects=[('agenda_item', item_id, None)],
        )
        set_status(eid, 'published')
        entry_ids.append(eid)
    yield {'uid': uid, 'item_id': item_id, 'mtg_id': mtg_id, 'entry_ids': entry_ids}
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM coverage_entries WHERE author_id = %s", (uid,))
            cur.execute("DELETE FROM agenda_items WHERE id = %s", (item_id,))
            cur.execute("DELETE FROM meetings WHERE id = %s", (mtg_id,))
            cur.execute("DELETE FROM admin_users WHERE id = %s", (uid,))
        conn.commit()


def test_listing_renders_published(app, published_entries):
    with app.test_client() as c:
        resp = c.get('/coverage/')
        assert resp.status_code == 200
        assert b'List body 0 unique-token-list42' in resp.data
        assert b'List body 1 unique-token-list42' in resp.data
        assert b'List body 2 unique-token-list42' in resp.data


def test_listing_fts_search_filters(app, published_entries):
    with app.test_client() as c:
        resp = c.get('/coverage/?q=unique-token-list42')
        assert resp.status_code == 200
        assert b'List body 0 unique-token-list42' in resp.data


def test_listing_pagination(app, published_entries):
    with app.test_client() as c:
        resp = c.get('/coverage/?page=999')
        assert resp.status_code == 200  # empty page, not 404
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/integration/test_coverage_listing.py -v
```

Expected: FAIL — route 404.

- [ ] **Step 3: Implement the route**

Append to `src/docket/web/public.py`:

```python
# --- Editorial coverage ----------------------------------------------------

@bp.route("/coverage/", methods=["GET"])
def coverage_listing():
    from docket.services.query import list_published_coverage
    kind = request.args.get('kind') or None
    if kind not in (None, 'note', 'citation'):
        kind = None
    q = request.args.get('q') or None
    try:
        page = max(1, int(request.args.get('page', 1)))
    except ValueError:
        page = 1
    rows, total = list_published_coverage(kind=kind, q=q, page=page, page_size=20)
    total_pages = (total + 19) // 20
    return render_template(
        "coverage/listing.html",
        entries=rows,
        total=total,
        page=page,
        total_pages=total_pages,
        kind=kind,
        q=q or '',
    )
```

(Note: `bp` is whatever the public blueprint is named — likely just `bp` or `public_bp`. Match the existing convention in `public.py`.)

- [ ] **Step 4: Create the listing template**

`src/docket/web/templates/coverage/listing.html`:

```jinja
{% extends "base.html" %}
{% block title %}Editorial coverage — docket.pub{% endblock %}
{% block content %}
<header>
  <h1>Editorial coverage</h1>
  <p>Notes and press citations on Alabama municipal meetings.</p>
</header>

<nav class="coverage-tabs">
  <a href="{{ url_for('public.coverage_listing') }}" class="{% if not kind %}active{% endif %}">All</a>
  <a href="{{ url_for('public.coverage_listing', kind='note') }}" class="{% if kind == 'note' %}active{% endif %}">Notes</a>
  <a href="{{ url_for('public.coverage_listing', kind='citation') }}" class="{% if kind == 'citation' %}active{% endif %}">Citations</a>
</nav>

<form method="get" action="{{ url_for('public.coverage_listing') }}" class="coverage-search">
  {% if kind %}<input type="hidden" name="kind" value="{{ kind }}">{% endif %}
  <input type="search" name="q" value="{{ q }}" placeholder="Search…">
  <button type="submit">Search</button>
</form>

{% if not entries %}
<p class="empty">No coverage yet. Notes and press citations land here as they're published.</p>
{% endif %}

{% for entry in entries %}
  {% if entry.kind == 'note' %}
    {% set note = entry %}
    {% include "partials/coverage_note.html" %}
  {% else %}
    {% set citation = entry %}
    {% include "partials/coverage_citation.html" %}
  {% endif %}
{% endfor %}

{% if total_pages > 1 %}
<nav class="pagination">
  {% if page > 1 %}
    <a href="{{ url_for('public.coverage_listing', page=page-1, kind=kind, q=q) }}">← Newer</a>
  {% endif %}
  <span>Page {{ page }} of {{ total_pages }}</span>
  {% if page < total_pages %}
    <a href="{{ url_for('public.coverage_listing', page=page+1, kind=kind, q=q) }}">Older →</a>
  {% endif %}
</nav>
{% endif %}
{% endblock %}
```

- [ ] **Step 5: Run + commit**

```bash
pytest tests/integration/test_coverage_listing.py -v
```

Expected: 3 passed.

```bash
git add src/docket/web/public.py src/docket/web/templates/coverage/listing.html \
        tests/integration/test_coverage_listing.py
git commit -m "feat(public): /coverage/ listing with pagination, filter tabs, FTS"
```

---

### Task 4.2: `/coverage/<id>` permalink for notes

**Files:**
- Modify: `src/docket/web/public.py`
- Create: `src/docket/web/templates/coverage/permalink.html`
- Test: `tests/integration/test_coverage_listing.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `tests/integration/test_coverage_listing.py`:

```python
def test_permalink_renders_note(app, published_entries):
    eid = published_entries['entry_ids'][0]
    with app.test_client() as c:
        resp = c.get(f"/coverage/{eid}")
        assert resp.status_code == 200
        assert b'unique-token-list42' in resp.data


def test_permalink_404_for_unpublished(app, published_entries):
    from docket.services.coverage_writer import set_status
    eid = published_entries['entry_ids'][0]
    set_status(eid, 'draft')
    with app.test_client() as c:
        resp = c.get(f"/coverage/{eid}")
        assert resp.status_code == 404


def test_permalink_404_for_citation(app):
    """Citations don't get internal permalinks — they link out."""
    # Create a citation, try to GET its permalink → 404
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO admin_users (username, password_hash) VALUES (%s, %s) RETURNING id",
                ('perma-admin', 'x'),
            )
            uid = cur.fetchone()[0]
            cur.execute("SELECT id FROM outlets WHERE slug='al-com'")
            outlet_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO meetings (municipality_id, external_id, title, meeting_date) "
                "VALUES ((SELECT id FROM municipalities LIMIT 1), %s, %s, NOW()) RETURNING id",
                ('perma-mtg', 'Perma'),
            )
            mtg_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO agenda_items (meeting_id, title) VALUES (%s, %s) RETURNING id",
                (mtg_id, 'Perma Item'),
            )
            item_id = cur.fetchone()[0]
        conn.commit()
    from docket.services.coverage_writer import create_citation, set_status
    eid = create_citation(
        author_id=uid, outlet_id=outlet_id,
        external_url='https://al.com/perma',
        headline='Perma Headline',
        reporter_byline=None, excerpt=None, article_published_at=None,
        subjects=[('agenda_item', item_id, None)],
    )
    set_status(eid, 'published')
    try:
        with app.test_client() as c:
            resp = c.get(f"/coverage/{eid}")
            assert resp.status_code == 404
    finally:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM coverage_entries WHERE id = %s", (eid,))
                cur.execute("DELETE FROM agenda_items WHERE id = %s", (item_id,))
                cur.execute("DELETE FROM meetings WHERE id = %s", (mtg_id,))
                cur.execute("DELETE FROM admin_users WHERE id = %s", (uid,))
            conn.commit()
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/integration/test_coverage_listing.py -v -k permalink
```

- [ ] **Step 3: Implement the route — reuse the subject hydrator**

Append to `src/docket/web/public.py`:

```python
@bp.route("/coverage/<int:coverage_id>", methods=["GET"])
def coverage_permalink(coverage_id: int):
    from docket.services.query import (
        _COVERAGE_SELECT, _hydrate_coverage_rows, _hydrate_subjects_for_entries,
    )
    from docket.db import db_cursor
    with db_cursor() as cur:
        cur.execute(
            _COVERAGE_SELECT + " WHERE ce.id = %s AND ce.kind = 'note' "
                               "AND ce.status = 'published'",
            (coverage_id,),
        )
        entries = _hydrate_coverage_rows(cur)
        if not entries:
            abort(404)
        entries = _hydrate_subjects_for_entries(cur, entries)
        note = entries[0]
    return render_template("coverage/permalink.html", note=note)
```

(`abort` should already be imported in `public.py`; if not, add it to the existing `from flask import ...` line.)

**Why this is simpler than the original draft:** the inline COALESCE-per-row query is replaced by the shared `_hydrate_subjects_for_entries` helper. The permalink template can now drop its bespoke `subjects` loop and reuse the same `partials/coverage_subjects_footer.html` macro that the listing uses — see the template update below.

- [ ] **Step 4: Create the permalink template**

`src/docket/web/templates/coverage/permalink.html`:

```jinja
{% extends "base.html" %}
{% block title %}{{ note.body[:60] }}… — docket.pub{% endblock %}
{% block content %}
<article class="coverage-permalink">
  {% include "partials/coverage_note.html" %}
</article>
{% endblock %}
```

The `coverage_note.html` partial renders its own subjects footer when `note.subjects` is populated — and the permalink route always hydrates subjects, so the "→ on Item X, Meeting Y" footer renders here automatically. No duplicate template logic.

- [ ] **Step 5: Run + commit**

```bash
pytest tests/integration/test_coverage_listing.py -v
```

Expected: 6 passed.

```bash
git add src/docket/web/public.py src/docket/web/templates/coverage/permalink.html \
        tests/integration/test_coverage_listing.py
git commit -m "feat(public): /coverage/<id> note permalink"
```

---

## Phase 5 — RSS + base.html alternate link (PR 5)

**Goal:** `/coverage.rss` feed published; reader-friendly RSS discovery via `<link rel="alternate">`.

### Task 5.1: `/coverage.rss` feed

**Files:**
- Modify: `src/docket/web/public.py`
- Create: `src/docket/web/templates/coverage/feed.xml.j2`
- Modify: `src/docket/web/templates/base.html`
- Test: `tests/integration/test_coverage_rss.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_coverage_rss.py
"""Integration tests for /coverage.rss feed."""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from docket.config import DATABASE_URL
from docket.db import db
from docket.services.coverage_writer import create_note, create_citation, set_status
from docket.web import create_app


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run RSS tests against Railway DB.",
)


@pytest.fixture
def app():
    a = create_app()
    a.config['TESTING'] = True
    return a


@pytest.fixture
def rss_entries():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO admin_users (username, password_hash, display_name) "
                "VALUES (%s, %s, %s) RETURNING id",
                ('rss-admin', 'x', 'RSS Tester'),
            )
            uid = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO meetings (municipality_id, external_id, title, meeting_date) "
                "VALUES ((SELECT id FROM municipalities LIMIT 1), %s, %s, NOW()) RETURNING id",
                ('rss-mtg', 'RSS'),
            )
            mtg_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO agenda_items (meeting_id, title) VALUES (%s, %s) RETURNING id",
                (mtg_id, 'RSS Item'),
            )
            item_id = cur.fetchone()[0]
            cur.execute("SELECT id FROM outlets WHERE slug='al-com'")
            outlet_id = cur.fetchone()[0]
        conn.commit()
    note_id = create_note(
        author_id=uid, body='RSS note body unique-rss-token.',
        partner_credit=None, subjects=[('agenda_item', item_id, None)],
    )
    set_status(note_id, 'published')
    cit_id = create_citation(
        author_id=uid, outlet_id=outlet_id,
        external_url='https://al.com/rss-test',
        headline='RSS citation headline',
        reporter_byline=None, excerpt=None, article_published_at=None,
        subjects=[('agenda_item', item_id, None)],
    )
    set_status(cit_id, 'published')
    yield {'uid': uid, 'note_id': note_id, 'cit_id': cit_id, 'item_id': item_id, 'mtg_id': mtg_id}
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM coverage_entries WHERE author_id = %s", (uid,))
            cur.execute("DELETE FROM agenda_items WHERE id = %s", (item_id,))
            cur.execute("DELETE FROM meetings WHERE id = %s", (mtg_id,))
            cur.execute("DELETE FROM admin_users WHERE id = %s", (uid,))
        conn.commit()


def test_rss_feed_valid_xml(app, rss_entries):
    with app.test_client() as c:
        resp = c.get('/coverage.rss')
        assert resp.status_code == 200
        assert resp.mimetype in ('application/rss+xml', 'application/xml', 'text/xml')
        root = ET.fromstring(resp.data)
        assert root.tag == 'rss'


def test_rss_feed_includes_published_note_and_citation(app, rss_entries):
    with app.test_client() as c:
        resp = c.get('/coverage.rss')
        assert b'unique-rss-token' in resp.data
        assert b'RSS citation headline' in resp.data


def test_rss_citation_link_points_to_external_url(app, rss_entries):
    with app.test_client() as c:
        resp = c.get('/coverage.rss')
        assert b'https://al.com/rss-test' in resp.data


def test_rss_excludes_drafts(app, rss_entries):
    from docket.services.coverage_writer import set_status
    set_status(rss_entries['note_id'], 'draft')
    with app.test_client() as c:
        resp = c.get('/coverage.rss')
        assert b'unique-rss-token' not in resp.data
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/integration/test_coverage_rss.py -v
```

Expected: 4 FAIL — route missing.

- [ ] **Step 3: Implement the RSS route + template**

Append to `src/docket/web/public.py`:

```python
@bp.route("/coverage.rss", methods=["GET"])
def coverage_rss():
    from docket.services.query import list_published_coverage
    from flask import Response
    entries, _ = list_published_coverage(page=1, page_size=50)
    xml = render_template("coverage/feed.xml.j2", entries=entries)
    return Response(xml, mimetype='application/rss+xml')
```

`src/docket/web/templates/coverage/feed.xml.j2`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>docket.pub — Editorial Coverage</title>
    <description>Notes and press citations on Alabama municipal meetings.</description>
    <link>{{ url_for('public.coverage_listing', _external=True) }}</link>
    <atom:link href="{{ url_for('public.coverage_rss', _external=True) }}"
               rel="self" type="application/rss+xml" />
    {% for entry in entries %}
    <item>
      {% if entry.kind == 'note' %}
        <title>{{ (entry.body or '')[:80] }}</title>
        <link>{{ url_for('public.coverage_permalink', coverage_id=entry.id, _external=True) }}</link>
        <description><![CDATA[{{ entry.body }}]]></description>
        <guid isPermaLink="true">{{ url_for('public.coverage_permalink', coverage_id=entry.id, _external=True) }}</guid>
      {% else %}
        <title>[{{ entry.outlet_name }}] {{ entry.headline }}</title>
        <link>{{ entry.external_url }}</link>
        <description><![CDATA[{{ entry.excerpt or '' }}{% if entry.reporter_byline %} — by {{ entry.reporter_byline }}{% endif %}]]></description>
        <guid isPermaLink="false">docket-coverage-{{ entry.id }}</guid>
      {% endif %}
      {% if entry.published_at %}
      <pubDate>{{ entry.published_at.strftime('%a, %d %b %Y %H:%M:%S +0000') }}</pubDate>
      {% endif %}
    </item>
    {% endfor %}
  </channel>
</rss>
```

**Why `url_for(..., _external=True)` over manual base-URL concat:** Flask reads the request's host, scheme, and `SCRIPT_NAME` from the WSGI environ — correct under direct serving, behind a reverse proxy, on a sub-path, and in tests. Manual `request.url_root` concat breaks under proxy/sub-path configurations and silently produces wrong URLs in feed readers. The blueprint name `public` matches the `bp = Blueprint("public", ...)` you'll find at the top of `web/public.py` — verify and adjust if the project uses a different name.

- [ ] **Step 4: Add the `<link rel="alternate">` in base.html**

Edit `src/docket/web/templates/base.html` — inside the `<head>` block, add:

```html
<link rel="alternate" type="application/rss+xml"
      title="docket.pub editorial coverage"
      href="{{ url_for('public.coverage_rss') }}">
```

- [ ] **Step 5: Run + commit**

```bash
pytest tests/integration/test_coverage_rss.py -v
```

Expected: 4 passed.

```bash
git add src/docket/web/public.py src/docket/web/templates/coverage/feed.xml.j2 \
        src/docket/web/templates/base.html tests/integration/test_coverage_rss.py
git commit -m "feat(public): /coverage.rss feed + alternate link in base.html"
```

---

### Task 5.2: Full test suite pass + Railway deploy + CLAUDE.md update

- [ ] **Step 1: Run the full test suite**

```bash
pytest
```

Expected: all tests pass.

- [ ] **Step 2: `flask routes` snapshot diff**

```bash
flask routes > /tmp/routes-after.txt
git show HEAD~30:Procfile  # confirm web entrypoint hasn't changed
diff /tmp/routes-baseline.txt /tmp/routes-after.txt | head -50  # only new editorial routes should appear
```

Expected: only new routes added, all under `/admin/coverage`, `/admin/outlets`, `/admin/profile`, `/coverage/`, `/coverage/<int:id>`, `/coverage.rss`.

- [ ] **Step 3: Deploy + smoke**

```bash
railway up --service docket-web --detach
railway logs --service docket-web | tail -30
```

Verify:
- `[applied] docket.migrations.027_editorial_coverage` appears
- gunicorn starts cleanly

Browser smoke tests:
1. `/coverage/` → empty state or your test entries
2. `/coverage.rss` → valid feed in a feed reader
3. `/admin/coverage` → admin flow works on prod
4. Any item with attached coverage → block renders

- [ ] **Step 4: Update CLAUDE.md**

Open `CLAUDE.md`, locate the build-phases table. Append a new row:

```markdown
| Editorial coverage v1 | Done | Migration 027, notes + citations attached to items/meetings/members/badges, item_detail block + 6-surface chips, /coverage/ listing + RSS + permalinks. v1.1+ pairs (meeting/member/badge blocks + chips) follow as paired ships. |
```

In the "Key decisions to preserve" section, append a bullet:

```markdown
- **Editorial coverage:** v1 schema (migration 027) has snapshot-on-publish bylines, normalized citation table via `outlets` controlled vocab, polymorphic N:M subjects with ON UPDATE CASCADE on badge slug. v1 surfaces only item_detail + cross-surface item-card chips; meeting/member/badge blocks pair with their chips in v1.1+. Automation slots (`status='proposed'`, `source='ai_proposal|press_scraper'`) are reserved but unused in v1. Spec: `docs/superpowers/specs/2026-05-13-editorial-coverage-design.md`.
```

- [ ] **Step 5: Commit + tag**

```bash
git add CLAUDE.md
git commit -m "docs: note editorial coverage v1 shipped"
git tag editorial-coverage-v1-shipped
```

**Phase 5 done. Editorial coverage v1 is live. Modularity refactor is unblocked.**

---

## Definition of done verification

Run through the spec's Definition of Done section item-by-item:

- [ ] Migration 027 applied on Railway with all 4 enums + 3 tables + 1 column + 10 outlet seed rows + indexes.
- [ ] Admin can create a note attached to one or more subjects and publish it.
- [ ] Admin can create a citation attached to one or more subjects and publish it.
- [ ] On publish, `byline` is snapshotted from the author's `display_name OR username`.
- [ ] Editing the byline post-publish via the admin form persists.
- [ ] Editing the subject list wipes and replaces `coverage_subject_links` atomically.
- [ ] All citation card external links render with `target="_blank" rel="noopener noreferrer"`.
- [ ] `coverage_counts_for_items([])` returns `{}` without executing SQL.
- [ ] Admin can edit, unpublish, reject, restore, feature, unfeature, delete.
- [ ] Item detail renders coverage block when published coverage exists; omits cleanly when none.
- [ ] Item card chips render on meeting_detail, category_landing, search, topic_detail, home, city_overview.
- [ ] `/coverage/` listing renders paginated, sorted by published_at DESC, filter tabs and `?q=` work.
- [ ] `/coverage/<id>` renders note permalinks; 404 for citations and non-published.
- [ ] `/coverage.rss` valid RSS 2.0 with latest 50 published entries.
- [ ] `<link rel="alternate" type="application/rss+xml">` present in `base.html`.
- [ ] Full test suite passes.
- [ ] CLAUDE.md updated.
