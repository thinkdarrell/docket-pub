# Editorial Coverage — Notes + Citations for docket.pub

**Date:** 2026-05-13
**Status:** Design (spec). Pre-flight requirement for the modularity refactor (`2026-05-13-modularity-cleanup-design.md`).
**Scope:** Add a lightweight editorial layer to docket.pub — short context notes plus external press citations, attachable to agenda items / meetings / council members / badges, surfaced inline on detail pages and discoverable via a standalone listing, RSS feed, and full-text search.

---

## Motivation

docket.pub today is a structured-record platform: every agenda item gets AI-extracted facts, a Smart Brevity card, badges, and tied votes. What it lacks is a **human-voice layer** — the place where an editor (or partner) can say "this is the third version of this ordinance, vetoed last year" or "Birmingham Watch ran a long investigation on this." Without that layer, the platform tells a citizen *what* happened but not *why it matters* in the context of recent civic history.

Editorial coverage adds two things to every item, meeting, member, and category:

1. **Short context notes** authored in-house (occasionally co-credited to a partner) that surface alongside the AI-extracted record without displacing it.
2. **External press citations** that point readers to local journalism covering the same item — making docket.pub the index that ties official records to the journalism around them.

Longer-form pieces are deliberately out of scope: if the editor has more to say, they publish elsewhere (Substack, `/blog`) and cite that piece back into docket as a citation. The platform stays focused on *being the index* rather than becoming a publication.

### Position relative to the modularity refactor

This feature is a **pre-flight requirement** for the modularity refactor (per the modularity spec, "Future capability slots — Editorial"). It ships in the current pre-VSA Flask layout. When the refactor sweeps through, every file in this feature has a known destination in the VSA folders — pure file-move PRs.

---

## Module structure

Two views: where v1 ships, and where the modularity refactor will move things later.

| Concern | Pre-VSA (v1 ships here) | Post-VSA (refactor moves it here) |
|---|---|---|
| Schema | `src/docket/migrations/027_editorial_coverage.py` | unchanged |
| Read service | new section in `src/docket/services/query.py` | extracted to `src/docket/services/query/coverage.py` as part of modularity PR 0.2 |
| Write service (entries) | new `src/docket/services/coverage_writer.py` | unchanged |
| Write service (outlets) | new `src/docket/services/outlets_writer.py` | unchanged |
| Model dataclass | new `src/docket/models/coverage.py` (`CoverageEntry`) | unchanged |
| Admin routes | new section in `src/docket/web/admin.py` | extracted to `features/admin/editorial/` |
| Public routes (listing, RSS, permalink) | new section in `src/docket/web/public.py` | extracted to `features/public/coverage/` |
| Admin templates | `src/docket/web/templates/admin/coverage/` and `admin/outlets/` | move with the admin feature folder |
| Public templates | `src/docket/web/templates/coverage/` (listing, permalink, RSS feed) | move with the public feature folder |
| Shared render macros | `src/docket/web/templates/partials/coverage_*.html` | `src/docket/components/coverage/` |
| Surface integration | edits to existing `item_detail.html` and item-card partials | edits to corresponding feature templates |
| Tests | `tests/unit/test_query_coverage.py`, `tests/integration/test_*_coverage.py` | move alongside features |

**Naming convention:** the public feature folder is `features/public/coverage/` (citizen-facing surface name); the admin feature folder is `features/admin/editorial/` (editor-facing surface name). This matches the URL space (`/coverage/...`) and the admin nav ("Editorial").

---

## Data model

Migration **027** adds one column to an existing table and three new tables, plus four enums.

### Existing table change

```sql
ALTER TABLE admin_users ADD COLUMN display_name TEXT;
-- NULL means "fall back to username." Per-user setting controls byline display.
```

### `outlets` — controlled publication vocabulary

```sql
CREATE TABLE outlets (
    id          SERIAL PRIMARY KEY,
    slug        TEXT NOT NULL UNIQUE,           -- 'birmingham-watch', 'al-com'
    name        TEXT NOT NULL,                  -- 'Birmingham Watch'
    homepage    TEXT,                           -- optional outlet URL
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Seeded with ~10 Alabama outlets. `is_active=FALSE` keeps an outlet around for historical citations but removes it from the citation-form picker.

**Seed:**

```sql
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
```

The final outlet is a self-citation slot: when the editor publishes a deeper piece on Substack or `/blog`, they cite it back via this outlet like any other external coverage.

### `coverage_entries` — one row per note OR citation

```sql
CREATE TYPE coverage_kind   AS ENUM ('note', 'citation');
CREATE TYPE coverage_status AS ENUM ('draft', 'proposed', 'published', 'rejected');
CREATE TYPE coverage_source AS ENUM ('manual', 'ai_proposal', 'press_scraper');

CREATE TABLE coverage_entries (
    id                   SERIAL PRIMARY KEY,
    kind                 coverage_kind   NOT NULL,
    status               coverage_status NOT NULL DEFAULT 'draft',
    source               coverage_source NOT NULL DEFAULT 'manual',

    -- Notes-only fields
    body                 TEXT,                       -- 1-3 sentences typical
    partner_credit       TEXT,                       -- free-form "in partnership with X"

    -- Citations-only fields
    outlet_id            INTEGER REFERENCES outlets(id),
    external_url         TEXT,
    headline             TEXT,
    byline               TEXT,                       -- reporter name (optional)
    excerpt              TEXT,                       -- optional pull-quote
    article_published_at DATE,                       -- when the outlet published it

    -- Authoring & audit
    author_id            INTEGER NOT NULL REFERENCES admin_users(id),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at         TIMESTAMPTZ,                -- set when status transitions to 'published'
    featured_until       TIMESTAMPTZ,                -- editor's-pick expiry; NULL = not featured

    -- Full-text search vector (Postgres GENERATED column)
    search_vector        tsvector GENERATED ALWAYS AS (
        to_tsvector('english',
            coalesce(body,     '') || ' ' ||
            coalesce(headline, '') || ' ' ||
            coalesce(excerpt,  '') || ' ' ||
            coalesce(byline,   '')
        )
    ) STORED,

    CHECK (
        (kind = 'note' AND body IS NOT NULL AND outlet_id IS NULL)
      OR
        (kind = 'citation' AND outlet_id IS NOT NULL
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
```

**Why one table with a `kind` discriminator (not two tables):** the listing page, the RSS feed, and the editor's-picks rail all interleave notes and citations by recency. One table is one query; two tables would require `UNION ALL` everywhere. The CHECK constraint enforces row validity at the database level. The shape mirrors how `agenda_items` mixes substantive and procedural items via `is_substantive`.

**Why `published_at` is a timestamp (not a boolean):** the listing page sorts by it; it records when something went live (auditable); republishing a previously-rejected entry updates it to `NOW()`. A row is "published" iff `status='published'` AND `published_at IS NOT NULL` — kept in sync by the writer service.

**Why `search_vector` is a `GENERATED ... STORED` column:** Postgres recomputes on every UPDATE — no trigger, no writer-service maintenance. The GIN index makes `?q=` search on the listing page a sub-10ms lookup.

### `coverage_subject_links` — N:M to subjects

```sql
CREATE TYPE coverage_subject_type AS ENUM ('agenda_item', 'meeting', 'council_member', 'badge');

CREATE TABLE coverage_subject_links (
    id            SERIAL PRIMARY KEY,
    coverage_id   INTEGER NOT NULL REFERENCES coverage_entries(id) ON DELETE CASCADE,
    subject_type  coverage_subject_type NOT NULL,
    subject_id    INTEGER,         -- FK to agenda_items.id / meetings.id / council_members.id
    subject_slug  TEXT,            -- FK to priority_badge_templates.slug when subject_type='badge'
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Exactly one of (subject_id, subject_slug) per row
    CHECK (
        (subject_type IN ('agenda_item', 'meeting', 'council_member')
            AND subject_id IS NOT NULL AND subject_slug IS NULL)
      OR
        (subject_type = 'badge'
            AND subject_slug IS NOT NULL AND subject_id IS NULL)
    ),

    -- A coverage entry attaches to a given subject at most once
    UNIQUE (coverage_id, subject_type, subject_id, subject_slug)
);

CREATE INDEX idx_coverage_subject_links_subject_int
    ON coverage_subject_links(subject_type, subject_id)
    WHERE subject_id IS NOT NULL;

CREATE INDEX idx_coverage_subject_links_subject_slug
    ON coverage_subject_links(subject_type, subject_slug)
    WHERE subject_slug IS NOT NULL;
```

**Two FK columns (`subject_id` INTEGER + `subject_slug` TEXT) instead of one polymorphic column:** items, meetings, and council members are SERIAL integers; badges are TEXT slugs. Keeping the natural type per subject means each inline-render lookup uses a clean indexed query — no casting, no planner ambiguity. The CHECK constraint enforces that exactly one column is set per row, gated by `subject_type`.

**No formal FK to target tables.** Postgres doesn't support polymorphic FK constraints. Application-level integrity is sufficient for a low-volume editorial feature. If a target row is deleted, the orphaned coverage link fails to render gracefully (the read query simply doesn't find the joined target). A periodic cleanup task is a future option if it ever happens at scale.

**Why N:M from day one:** one Birmingham Watch article often covers 3-5 items from one meeting. Without N:M, you'd create five duplicate citations and lose the "one article" identity (which the future auto-proposer needs for dedup-by-URL). With N:M: one `coverage_entries` row, five `coverage_subject_links` rows. This is the entire reason the citation side is normalized rather than flat.

### Index strategy summary

| Index | Used by |
|---|---|
| `idx_coverage_entries_status_published` (partial: WHERE published) | listing page, RSS feed, editor's-picks rail |
| `idx_coverage_entries_featured` (partial: WHERE featured) | home editor's-picks query |
| `idx_coverage_entries_kind_status` | admin review queue (filter by kind+status) |
| `idx_coverage_entries_search` (GIN on tsvector) | listing page `?q=` search |
| `idx_coverage_subject_links_subject_int` (partial: WHERE int FK set) | inline render on item / meeting / member detail pages, chip-count queries |
| `idx_coverage_subject_links_subject_slug` (partial: WHERE slug FK set) | inline render on category landing |

All inline-render and chip-count queries hit one partial index with high selectivity.

### What's NOT in the schema

| Excluded | Reason |
|---|---|
| `editorial_revisions` history table | YAGNI for v1. `updated_at` is the audit trail. Add when a note gets factually wrong and you need a diff. |
| Tag / topic taxonomy on coverage | Subjects already categorize. |
| Coverage versioning / draft branching | Single-author site; one draft per entry. |
| Public reactions / comments | Not a discussion site. |
| Image / media attachment | Text only in v1. Citations link out for imagery. |
| Rich markup (Markdown / HTML body) | Plain text + `nl2br`. |

---

## Authorship and attribution

### Notes

| Field | Source |
|---|---|
| **Byline** | `admin_users.display_name OR admin_users.username` for the logged-in author at render time |
| **Partner credit** | Optional free-form text on the entry: e.g., "in partnership with Birmingham Watch" |
| **Date** | `published_at` (display: relative "May 13" / absolute on permalink) |

Byline is **not snapshotted** — changing your `display_name` retroactively changes the byline on past entries. Intentional in v1: one author, one consistent identity. If per-entry byline overrides are needed later, add a `byline_override TEXT` column to `coverage_entries` (v1.1 follow-up).

### Citations

| Field | Source |
|---|---|
| **Outlet** | `outlets.name` via FK (`outlet_id`). Controlled vocabulary; admin-managed. |
| **Headline** | `headline` text on the entry — copied from the article as published |
| **Byline** | Optional `byline` text (the reporter's name) |
| **Date** | `article_published_at` (when the outlet published) |
| **Excerpt** | Optional pull-quote (`excerpt` text) — 1-2 sentences from the article |
| **Link** | `external_url` — clicking the citation card goes to the article |

---

## Admin workflow

### Routes

```
GET    /admin/coverage                  → list view (filterable by status, kind)
GET    /admin/coverage/new?kind=note    → new-note form
GET    /admin/coverage/new?kind=citation → new-citation form
POST   /admin/coverage                  → create
GET    /admin/coverage/<id>/edit        → edit form
POST   /admin/coverage/<id>             → update
POST   /admin/coverage/<id>/publish     → quick action: status→published, published_at=NOW()
POST   /admin/coverage/<id>/unpublish   → status→draft
POST   /admin/coverage/<id>/reject      → status→rejected
POST   /admin/coverage/<id>/restore     → status→draft (from rejected)
POST   /admin/coverage/<id>/feature     → set featured_until = NOW() + 14 days
POST   /admin/coverage/<id>/unfeature   → featured_until = NULL
POST   /admin/coverage/<id>/delete      → delete (drafts only)
GET    /admin/coverage/search/<type>?q= → HTMX autocomplete for the subject picker

GET    /admin/outlets                   → outlet list (CRUD)
POST   /admin/outlets                   → create
POST   /admin/outlets/<id>              → update
POST   /admin/outlets/<id>/deactivate

POST   /admin/profile/display-name      → update current user's display_name
```

### Subject picker (HTMX)

A coverage entry attaches to 1-N subjects, mixed types. The picker:

```
┌──────────────────────────────────────────────────┐
│ Attach to:                                       │
│ [✕ item: "12-08 Westside Rezoning" (id 12345)]   │
│ [✕ member: "Crystal Smitherman" (id 27)]         │
│                                                  │
│ Add another:                                     │
│ Type: [item ▾]  Search: [westside paving____]    │
│   → Item 25-0042: Westside Paving Resolution     │
│   → Item 25-0078: Westside Lot Acquisition       │
│   → (click to add)                               │
└──────────────────────────────────────────────────┘
```

Selected subjects render as chips; the search-as-you-type input hits `/admin/coverage/search/<type>?q=` and returns an HTML fragment of results; clicking a result appends a hidden form input `subject[]=item:12345` and re-renders the chips.

On POST, the route handler parses `subject[]` values and calls `coverage_writer.create_note(...)` or `coverage_writer.create_citation(...)` — both accept a `subjects` list and insert the entry plus all subject_links in a single transaction.

### Status transitions

```
            ┌───────┐  publish    ┌───────────┐
  create →  │ draft │ ─────────→  │ published │
            └───────┘             └───────────┘
                ↑                       │
                │  unpublish            │  reject
                └───────────────────────┘
                            ↓
                       ┌──────────┐
                       │ rejected │ ── restore → draft
                       └──────────┘
```

`proposed` slots in alongside `draft` for entries created by automation; same transitions out. v1 never produces `proposed` rows — they exist only because the schema is automation-ready.

### List view

| Column | Notes |
|---|---|
| Kind icon | 📝 note / 📰 citation |
| Snippet | Note body first 80 chars / citation headline |
| Attached to | Comma-joined subject names ("Item 25-0042, Member Smith") |
| Status badge | Colored chip |
| Author | display_name |
| Updated | Relative date |
| Actions | Edit + quick-action button per status |

Filter tabs (HTMX-driven): `All / Drafts / Proposed (0) / Published / Rejected`. Optional secondary filter `Notes / Citations / Both`. The "Proposed" tab renders `(0)` and an explanatory message in v1.

### Quick actions per row

| Current status | Buttons shown |
|---|---|
| draft | **Publish** / Edit / Delete |
| proposed | **Publish** / **Reject** / Edit |
| published | **Unpublish** / **Feature on home** (or **Unfeature** if active) / Edit |
| rejected | **Restore to drafts** / Edit |

**Publish** does two things atomically: `status='published'`, `published_at=NOW()`. **Feature on home** sets `featured_until = NOW() + INTERVAL '14 days'`. The 14-day window is hard-coded in v1; a "feature for N days" form is a v1.1 follow-up.

### Display-name profile

A "Profile" link in the admin nav lets the logged-in user set their `display_name` (one field, one form). Cleared → falls back to `username`. Changes apply to all entries (past and future) since byline is rendered live, not snapshotted.

### What's NOT in the admin (v1)

| Excluded | Reason |
|---|---|
| Bulk operations (publish/reject multiple at once) | Volume doesn't justify |
| Edit history / diff view | `updated_at` is sufficient audit |
| Comments between editors | Single-author site for the foreseeable future |
| Rich-text editor (Markdown, WYSIWYG) | Plain text + `nl2br` only |
| Image attachment | v1.x feature |
| Scheduled publish | Leave drafts as drafts |
| Browser-based draft autosave | Single-author, low collision risk |
| Per-entry byline override | v1.1 if needed (`byline_override` column) |

---

## Citizen surfaces

### v1: item_detail (full block) + item card chips (6 surfaces)

#### Item detail — coverage block

`web/templates/item_detail.html` adds the coverage block **below the Smart Brevity Card, above the votes section**. The reader's mental model:

1. **AI says** — Smart Brevity Card (canonical extracted record)
2. **Editor adds** — Coverage block (notes + citations)
3. **Council did** — Votes section (official record)

Visual shape:

```
┌─────────────────────────────────────────────────────┐
│ Smart Brevity Card (unchanged)                      │
└─────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────┐
│ Editorial coverage                                  │
│                                                     │
│ ┃ NOTE — Darrell Nance, in partnership with         │
│ ┃ Birmingham Watch · May 13                         │
│ ┃                                                   │
│ ┃ This is the third version of this ordinance.      │
│ ┃ Mayor Woodfin vetoed the previous version in      │
│ ┃ March 2024.                                       │
│                                                     │
│ Press coverage                                      │
│ ┌─────────────────────────────────────────────────┐ │
│ │ BIRMINGHAM WATCH · May 8                        │ │
│ │ Council split on encampment ordinance           │ │
│ │ by Sam Prickett                                 │ │
│ │ "Three council members said publicly..."        │ │
│ │ → birminghamwatch.org/...                       │ │
│ └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────┐
│ Votes (unchanged)                                   │
└─────────────────────────────────────────────────────┘
```

**Ordering inside the block:**
1. Notes first, citations after (docket voice → external voice)
2. Within notes: newest `published_at` first
3. Within citations: newest `article_published_at` first

**When there's no coverage:** the entire block is omitted (no empty header). `{% if coverage %}...{% endif %}`.

**Macros used:**
- `partials/coverage_block.html` → `components/coverage/block.html` (renders the section wrapper + iterates)
- `partials/coverage_note.html` → `components/coverage/note.html` (one note)
- `partials/coverage_citation.html` → `components/coverage/citation.html` (one citation card)

The block macro accepts a list of `CoverageEntry` objects (already-filtered to `status='published'`); the iteration logic stays in the template. The query lives in `services/query.py` as `coverage_for_subject(subject_type, subject_id_or_slug)`.

#### Item card chips — 6 surfaces

A small "📝 1 · 📰 2" chip on item cards across every surface that lists items:

| Surface | Route (pre-VSA) |
|---|---|
| meeting_detail | `web/public.py` meeting_detail |
| category_landing | `web/public.py` category_landing |
| search | `web/public.py` search |
| topic_detail | `web/public.py` topic_detail |
| home | `web/public.py` home |
| city_overview | `web/public.py` city_overview |

**Implementation pattern:**
- One chip macro: `partials/coverage_count_chip.html` → `components/coverage/count_chip.html`
- One read helper: `coverage_counts_for_items(item_ids: list[int]) -> dict[int, tuple[int, int]]` returning (note_count, citation_count) per item
- Each route calls the helper for its visible item IDs and passes a `coverage_counts` dict into the template
- The item-card macro accepts the dict (defaults to `{}`) and renders the chip when the count for the current item is non-zero

The chip renders only when the count is non-zero. The macro is a tiny reusable atom so any new item-card surface added later picks it up by passing the dict.

### v1.1+ surface plan (documented now for forward-compatibility)

| v1.x | Adds | Detail block | Card chips |
|---|---|---|---|
| 1.1 | meeting-level coverage | `meeting_detail.html` block at top | Meeting card chips on meetings_list, home, city_overview |
| 1.2 | council member coverage | Member detail page block + rail addition | Member card chips on council list, city_overview |
| 1.3 | category-landing featured editorial + home editor's-picks rail | category_landing featured slot, home top-3 featured | (No new chip surfaces — badges already display as chips elsewhere) |
| 2.0 | AI proposer pipeline | (no UI change) | (no UI change) |
| 2.1 | Press scraper pipeline | (no UI change) | (no UI change) |

**The chip-and-block-ship-together rule:** a card chip without a destination block is a dead-end tease. Meeting/member/badge chips ship paired with their respective blocks.

### What's NOT a surface in v1

- Meeting / member / badge coverage blocks (v1.1-1.3)
- Meeting / member card chips (paired with their blocks)
- Home editor's-picks rail (v1.3)
- Per-outlet pages (`/coverage/outlets/<slug>`)
- Per-author pages
- Coverage results in the global `/search` endpoint (listing-page search only in v1)

---

## Discoverability

### Listing page — `/coverage/`

| Field | Value |
|---|---|
| URL | `/coverage/` |
| Default sort | `published_at DESC` |
| Page size | 20 |
| Pagination | `?page=N` |
| Filter UI | Tabs: `All / Notes only / Citations only`. Optional outlet dropdown. |
| Search | `?q=keyword` — full-text via `search_vector` GIN index |
| Empty state | "No coverage yet. Notes and press citations land here as they're published." |

**Row shape:**

```
┌─────────────────────────────────────────────────────────┐
│ 📝 NOTE · Darrell Nance · May 13                        │
│ "This is the third version of this ordinance..."        │
│ → on Item 25-0042 (Westside Rezoning), Council Mtg 5-12 │
├─────────────────────────────────────────────────────────┤
│ 📰 BIRMINGHAM WATCH · May 8 · by Sam Prickett           │
│ Council split on encampment ordinance                   │
│ "Three council members said publicly..."                │
│ → on Item 25-0089, Item 25-0091 (Encampment Ordinance)  │
│ → birminghamwatch.org/...                               │
└─────────────────────────────────────────────────────────┘
```

Notes render full body inline (they're short). Citations render as a card; clicking the headline goes to the external article. Both render "attached-to" chips as links back into docket.

### Permalinks

| Subject | Permalink URL | Renders |
|---|---|---|
| Note | `/coverage/<id>` | Full note: byline, body, attached-to chips. OG tags inherit from `base.html` defaults. |
| Citation | none in v1 | Citations always link out to the outlet — no internal permalink. |

**ID-based, not slug-based.** Slugs require uniqueness logic + collision handling. IDs are auto-increment from the PK. A `slug TEXT UNIQUE` column can be added later without breaking ID URLs.

### RSS feed — `/coverage.rss`

| Field | Value |
|---|---|
| URL | `/coverage.rss` |
| Entries | Latest 50 published coverage entries, newest first by `published_at` |
| Item `<title>` | Note: first 80 chars of body. Citation: `"[OUTLET] HEADLINE"` |
| Item `<link>` | Note: `/coverage/<id>` permalink. Citation: external article URL. |
| Item `<description>` | Note: full body. Citation: excerpt (if present) + byline. |
| Item `<pubDate>` | `published_at` |
| Channel `<title>` | "docket.pub — Editorial Coverage" |
| Channel `<description>` | "Notes and press citations on Alabama municipal meetings." |

Reuses the existing RSS template pattern from `/al/<city>/upcoming-hearings.rss`. Discoverable via `<link rel="alternate" type="application/rss+xml">` in `base.html`.

### Full-text search

`coverage_entries.search_vector` (Postgres `GENERATED ... STORED` `tsvector`) covers `body + headline + excerpt + byline`. GIN index makes `?q=` search fast.

**Search surface in v1:** the `/coverage/?q=` parameter on the listing page only. Integration into the global `/search` endpoint is deferred to v1.x (requires designing a "coverage result card" that mixes correctly with existing meeting and item result cards).

### What's NOT in v1 discoverability

| Excluded | Reason / future |
|---|---|
| Per-outlet pages (`/coverage/outlets/<slug>`) | Defer; trivial follow-up when an outlet earns its own listing page |
| Per-author pages | Defer; single author for now |
| Per-city RSS feeds | Defer; one global feed |
| Slug-based permalinks | Defer to v1.x with SEO improvements |
| Coverage in global `/search` | Defer until result-card UX is settled |
| Email digest / newsletter integration | Out of scope entirely |
| Sitemap.xml inclusion for coverage permalinks | v1.x with slugs |
| Per-entry OG / Twitter meta tags | Base layout defaults are sufficient |

---

## Sequencing

### Pre-flight check

| Pre-flight item | Status / interaction with editorial v1 |
|---|---|
| Refactor #2 follow-up #2 — consent-text recovery (touches `services/`, `ai/wave0.py`) | Independent of editorial; can ship in parallel. Both must land before modularity refactor starts. |
| Migration 027 collision check | Last applied migration is 026. 027 is the next free slot; verify at PR-1 prep time. |
| `services/query.py` collision risk | Editorial appends a coverage section to `query.py`. Modularity PR 0.2 will split `query.py` afterward and absorb editorial's section into `services/query/coverage.py`. Order is fine. |
| AI Phase 3 backfill | UNAFFECTED. No prompt changes, no `ai/` touches. |

### v1 — five PRs

Each independently shippable, reversible (`git revert`-clean), scoped to a single concern. Target <500 lines each except PR 3 (the surface ship, ~700-800 lines because it touches 6 templates).

#### PR 1 — Schema + read service skeleton

- Migration `027_editorial_coverage.py`:
  - `ALTER TABLE admin_users ADD COLUMN display_name TEXT`
  - Tables: `outlets`, `coverage_entries`, `coverage_subject_links`
  - Enums: `coverage_kind`, `coverage_status`, `coverage_source`, `coverage_subject_type`
  - Indexes per the index-strategy table above
  - Outlet seed (10 rows)
  - FTS `GENERATED` column + GIN index on `coverage_entries`
- `services/query.py`: append a coverage section with:
  - `coverage_for_subject(subject_type, subject_id=None, subject_slug=None) -> list[CoverageEntry]`
  - `coverage_counts_for_items(item_ids: list[int]) -> dict[int, tuple[int, int]]`
  - `list_published_coverage(*, kind=None, outlet_id=None, q=None, page=1, page_size=20) -> tuple[list[CoverageEntry], int]`
- New `models/coverage.py`: `CoverageEntry` dataclass with a derived `byline()` property (`author.display_name or author.username`).
- Tests: `tests/unit/test_query_coverage.py` exercising all three reads against a fixture-seeded test DB.
- **No UI; no admin; nothing surfaces yet.** This PR is "the data layer exists."

#### PR 2 — Admin CRUD

- New `services/coverage_writer.py` (mirrors `badges_writer.py` shape):
  - `create_note(*, author_id, body, partner_credit, subjects, status='draft', featured_until=None) -> int`
  - `create_citation(*, author_id, outlet_id, external_url, headline, byline, excerpt, article_published_at, subjects, status='draft', featured_until=None) -> int`
  - `update_coverage(coverage_id, **fields) -> None`
  - `set_status(coverage_id, status) -> None`  *(sets `published_at = NOW()` when status='published')*
  - `set_featured_until(coverage_id, until) -> None`
  - `delete_coverage(coverage_id) -> None`
  - Each function wraps a single transaction; multi-step writes (entry + subject_links) are atomic.
- New `services/outlets_writer.py`: tiny CRUD for outlets.
- Admin routes in `web/admin.py`: the 12 coverage routes + 5 outlet routes + 1 profile display_name route listed above.
- New admin templates in `web/templates/admin/coverage/`:
  - `list.html` (filtered table + quick-action buttons)
  - `new_note.html`, `new_citation.html`, `edit.html`
  - `_subject_picker.html`, `_subject_chip.html`, `_search_results.html` (HTMX fragments)
- New admin templates in `web/templates/admin/outlets/`: `list.html`, `form.html`.
- Profile display_name form added to admin profile area.
- Tests: `tests/integration/test_admin_coverage.py` (create, update, status transitions, subject attach/detach), `tests/integration/test_admin_outlets.py`.
- **No citizen-facing surface yet.** This PR is "an editor can author coverage and review it in admin."

#### PR 3 — Item coverage block + item card chips across 6 surfaces

- New shared macros:
  - `partials/coverage_block.html`, `coverage_note.html`, `coverage_citation.html`
  - `partials/coverage_count_chip.html`
- `web/templates/item_detail.html` includes the coverage block.
- Item-card macro (existing partial) accepts a `coverage_counts` dict prop; renders the chip when count is non-zero.
- Six route handlers updated to call `coverage_counts_for_items(item_ids)` and pass the dict into the template:
  - meeting_detail, category_landing, search, topic_detail, home, city_overview
- CSS additions in `web/static/styles.css` for the coverage block + chip styling.
- Tests: `tests/integration/test_item_detail_coverage.py`, `tests/integration/test_coverage_chips.py`.
- **This is the v1 reader-facing ship.** Citizens see editorial coverage on item detail pages and discover it via chips on item lists.

#### PR 4 — Listing page + permalinks

- New routes `/coverage/` (paginated list with filters + FTS) and `/coverage/<int:coverage_id>` (note permalink; 404 for non-note or non-published).
- New templates:
  - `web/templates/coverage/listing.html`
  - `web/templates/coverage/permalink.html`
- Existing `partials/coverage_note.html` and `partials/coverage_citation.html` reused.
- Search box wires `?q=` to `list_published_coverage(q=...)`.
- Tests: `tests/integration/test_coverage_listing.py` (pagination, filter tabs, FTS).
- **After this PR merges, coverage is browseable cross-site.**

#### PR 5 — RSS feed

- New route `/coverage.rss`.
- New template `web/templates/coverage/feed.xml.j2`.
- `<link rel="alternate">` added to `base.html` head for feed discovery.
- Tests: `tests/integration/test_coverage_rss.py` (feed structure, item ordering, kind-aware link selection).
- **After this PR merges, v1 is shipped.** Modularity refactor unblocks.

### v1.1+ — paired surface follow-ups

| Phase | Adds |
|---|---|
| v1.1 | meeting_detail coverage block + meeting card chips on meetings_list / home / city_overview |
| v1.2 | council member detail coverage block + member card chips on council list / city_overview |
| v1.3 | category_landing featured-editorial slot + home editor's-picks rail |
| v2.0 | AI proposer pipeline (extends existing AI pipeline) |
| v2.1 | Press scraper pipeline (new ingest task) |

Each follow-up is a paired chip+block unit. Each is one PR.

### Per-PR verification

- `pytest tests/` passes.
- `flask routes` snapshot diff confirms only intended new routes.
- Manual smoke test on Railway after each PR (admin can author → public can read where applicable).

### Rollback strategy

- PR 1: revert drops 3 tables + 1 column + 4 enums. Safe — no data depends on them yet.
- PR 2-5: revert leaves the schema in place, removes routes/templates. No URL collisions because no other feature claims `/coverage/*`. Drafts in the DB are harmless (nothing renders them).

---

## Scope boundaries

### In scope (v1)

| Area | Specifics |
|---|---|
| Entry types | Notes (1-3 sentence context) + Citations (external press) |
| Subjects | agenda_item, meeting, council_member, badge (4 types) |
| Authorship | Logged-in admin user with `display_name`. Optional free-form `partner_credit` on notes. |
| Outlets | Controlled `outlets` table seeded with 10 Alabama publications + admin CRUD |
| Status flow | `draft / proposed / published / rejected` (proposed unused in v1) |
| Featured | `featured_until` timestamp; 14-day hard-coded "feature on home" action |
| Citizen surfaces | Item detail (full coverage block). Item card chips on 6 surfaces. |
| Discoverability | `/coverage/` listing with pagination + filter tabs + FTS. `/coverage/<id>` permalinks for notes. `/coverage.rss` global feed. |
| FTS | Generated `search_vector` + GIN index on `coverage_entries` |
| Admin | List view, create-note, create-citation, edit, status quick-actions, outlets CRUD, profile display_name |
| Automation readiness | `status='proposed'` reserved; `source` enum exists; subjects N:M |

### Explicitly NOT in scope (v1)

| Excluded | Where it goes |
|---|---|
| Medium / long-form pieces (type B/C) | Author externally; cite back via the `docket-substack` outlet |
| Additional subjects: topic, city, standalone | Defer; `ALTER TYPE ... ADD VALUE` if ever needed |
| AI proposer pipeline | v2.0 |
| Press-scraper pipeline | v2.1 |
| Meeting / member / category-landing coverage blocks | v1.1 / v1.2 / v1.3 paired follow-ups |
| Meeting / member / badge card chips | Ship paired with their respective blocks |
| Editor's-picks rail on home | v1.3 |
| Per-outlet pages, per-author pages | Defer indefinitely |
| Slug-based permalinks | v1.x with SEO improvements |
| Coverage results in global `/search` | v1.x — needs result-card UX design |
| Per-city RSS feeds | Defer |
| Email digest / newsletter | Out of scope entirely |
| Image / media attachments | v1.x |
| Rich-text body, Markdown | Out of scope; plain text + `nl2br` |
| Edit history / diff view / draft branching | `updated_at` audit only |
| Bulk operations in admin | Volume doesn't justify |
| Scheduled publish | Leave drafts as drafts |
| Per-entry OG / Twitter meta tags | Base layout defaults |
| Sitemap inclusion for coverage permalinks | v1.x with slugs |

---

## Definition of done

- [ ] Migration 027 applied on Railway with all 4 enums + 3 tables + 1 column + 10 outlet seed rows + indexes.
- [ ] Admin can create a note attached to one or more subjects (item, meeting, member, badge) and publish it.
- [ ] Admin can create a citation attached to one or more subjects and publish it.
- [ ] Admin can edit, unpublish, reject, restore, feature, unfeature, and delete coverage entries.
- [ ] Admin can manage outlets (create / update / deactivate).
- [ ] Admin can set their `display_name`.
- [ ] Item detail page renders the coverage block when published coverage exists for the item; omits cleanly when none.
- [ ] Item card chips render on meeting_detail, category_landing, search, topic_detail, home, and city_overview when item coverage exists.
- [ ] `/coverage/` listing page renders paginated, sorted by `published_at DESC`, with filter tabs and `?q=` FTS search working.
- [ ] `/coverage/<id>` renders note permalinks; returns 404 for citations and non-published entries.
- [ ] `/coverage.rss` renders a valid RSS 2.0 feed with the latest 50 published entries.
- [ ] `<link rel="alternate" type="application/rss+xml" href="/coverage.rss">` present in `base.html`.
- [ ] Full test suite passes (`pytest`).
- [ ] `CLAUDE.md` updated with editorial coverage section.

---

## Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Polymorphic subject FK is application-enforced (no DB-level FK). Deleting a subject row could orphan coverage links. | Low | Read query encapsulates this — orphaned subjects fail to render gracefully. Optional cleanup task if it ever happens at volume. |
| Postgres can't natively drop enum values | Low | No enum value looks likely to retire. Standard `CREATE TYPE ... v2 AS ENUM (...)` migration recipe if ever needed. |
| Two-column polymorphic subject (subject_id INT vs subject_slug TEXT) is easy to mishandle | Medium | All access goes through `coverage_for_subject(...)` and `coverage_writer.create_*(subjects=...)` helpers — callers never touch the two columns directly. Unit-test the helpers thoroughly. |
| Citation URL duplication (same article cited twice for the same subject) | Medium | Admin form runs a "URL already cited" check at submission. Server-side enforced by `UNIQUE (coverage_id, subject_type, subject_id, subject_slug)`. |
| Chip queries add per-request latency on item-list pages | Low | `coverage_counts_for_items(item_ids)` is a single indexed GROUP BY against the partial index. ~10ms expected for 30-item meeting pages. Verify with EXPLAIN before each chip-route ships. |
| Coverage block renders for unpublished items | Very low | Read query hard-filters to `status='published'`. Unit-test confirms drafts never render. |
| Featured-until expiry isn't enforced server-side beyond query filtering | Negligible | Old featured entries stop being featured (`WHERE featured_until > NOW()`). No cleanup needed. |
| Display name change retroactively changes byline on existing entries | Intentional, not a risk | Current byline by design. Per-entry `byline_override` is a v1.1 add if needed. |
| Migration 027 collides with another pre-flight migration | Very low | 026 is highest current migration; verify at PR-1 prep time and bump if needed. |
| RSS feed reveals draft content | Very low | Feed query hard-filters to `status='published'`. Unit-test confirms drafts never appear. |
| Editorial v1 slips and blocks modularity refactor | Medium | v1 is intentionally scoped to 5 PRs (~1-2 weeks of work). Modularity waits for v1 ship — not for v1.1+. |

---

## Future capability slots

### AI proposer (v2.0)

Extends the existing `src/docket/ai/` pipeline. During Stage 2 (Smart Brevity rewrite), or as a new Stage 3, Claude evaluates each item and proposes a note when it detects context worth surfacing:

- "This is the third version of an ordinance" (cross-meeting pattern)
- "Same contractor as a previous high-dollar item" (cross-item pattern)
- "Item connects to a state-level law" (external context)

The proposer creates `coverage_entries` rows with `kind='note'`, `status='proposed'`, `source='ai_proposal'`. The admin queue's "Proposed" tab surfaces them for human review. Cost adds to the existing AI budget; gated by the same `AI_DAILY_BUDGET_USD`.

### Press scraper (v2.1)

New scheduled worker task scans local-press RSS feeds (or sitemaps where no RSS exists) for recent articles, runs keyword + date matching against recent items/meetings, and proposes citations:

- Creates `coverage_entries` rows with `kind='citation'`, `status='proposed'`, `source='press_scraper'`
- Idempotent on `external_url` (the schema's normalized shape supports this; flat would not)
- Outlet identification via the controlled `outlets` table
- Admin queue's "Proposed" tab surfaces for review

### Per-outlet pages (v1.x)

`/coverage/outlets/<slug>` lists all citations from a given outlet. Trivial follow-up given the `outlets` table already exists.

### Per-author pages (v1.x)

`/coverage/authors/<username>` for multi-author sites. Defer until there's a second author.

### Editorial revisions history (v1.x)

`coverage_revisions` table snapshots body + headline + excerpt on every UPDATE via app-level append or PostgreSQL trigger. Adds diff view in admin. Add when a note gets factually wrong.

### Image attachments (v1.x)

`coverage_media` table with FK to `coverage_entries`. Stored in object storage (S3 / Railway Volume). Add when citation excerpts feel insufficient.

### Slug-based permalinks (v1.x)

Add `slug TEXT UNIQUE` column to `coverage_entries`. ID URLs stay canonical with 301 to slug URL. Improves SEO and shareability.

---

## Interaction with in-flight work

(State as of 2026-05-13.)

| Item | Interaction |
|---|---|
| Modularity refactor (`2026-05-13-modularity-cleanup-design.md`) | Editorial v1 is a pre-flight requirement. v1 ships in the current Flask layout; refactor moves files into VSA folders afterward with no logic change. |
| Refactor #2 follow-up #2 — consent-text recovery | Independent; can ship in parallel. Both must land before modularity starts. |
| Refactor #2 retro outstanding findings (3 MEDIUM, 5 LOW) | Independent of editorial; resolved or deferred before modularity starts. |
| AI Phase 3 backfill (Anthropic Batches API, ~37K items) | UNAFFECTED. No prompt changes, no `ai/` touches. |
| Per-page rail variants (proven on category landing) | Editorial v1 doesn't add a rail variant. Future v1.x can add a `coverage_body` rail variant per the modularity spec's slot. |
| Cron worker (live since 2026-05-04) | UNAFFECTED in v1. v2.0 (AI proposer) and v2.1 (press scraper) will add scheduled tasks to the existing worker. |
| `www.docket.pub` Railway move | Independent infrastructure task. |
| Astro frontend evaluation | Deferred. Editorial's macro-based components migrate cleanly to Astro when/if that decision lands. |

---

## References

- **Pre-flight relationship:** `docs/superpowers/specs/2026-05-13-modularity-cleanup-design.md` — "Future capability slots → Editorial."
- **Related specs:**
  - `docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md` — v3 AI pipeline (this feature's future v2.0 proposer extends).
  - `docs/superpowers/specs/2026-05-04-cron-worker-design.md` — `worker/` layer (this feature's future v2.1 press-scraper adds to).
  - `docs/superpowers/plans/2026-05-11-conservative-policy-badges.md` — Refactor #2 (includes `badges_writer` pattern this feature's `coverage_writer` mirrors).

---

## Open items deferred to implementation plan

The implementation plan (separate `docs/superpowers/plans/<date>-editorial-coverage.md`, produced via `superpowers:writing-plans` after this spec is approved) will detail:

- Exact `pytest` commands per PR for verification.
- Fixture-seeding strategy for `coverage_for_subject` and `list_published_coverage` unit tests.
- HTMX endpoint shapes and the autocomplete query design for the subject picker.
- CSS spec for the coverage block, citation card, and chip — including the visual treatment for distinguishing notes from citations and from the surrounding Smart Brevity Card.
- The exact ordering of route registration in `web/__init__.py` (or `web/public.py` `register_blueprint` calls).
- The set of admin-side validation rules (URL format, headline length cap, body length cap if any).
- Verification approach for the `flask routes` snapshot diff used in pre-merge checks.
