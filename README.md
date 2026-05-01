# Docket.pub

**Municipal meeting intelligence platform for Alabama cities.**

Docket.pub automates the collection, parsing, enrichment, and indexing of public meeting records from local governments. The goal is civic transparency: make every agenda item, vote, and dollar amount searchable — and link every data point back to its original source on the city's website.

**Domain:** [docket.pub](https://docket.pub) | **Status:** Private Development | **Repo:** Dev fork (`docket-pub-dw-dev`)

---

## What's Built

The full pipeline is live: scraping, enrichment, vote extraction (from both official minutes and video OCR), vote-to-agenda-item matching, and an editorial-design frontend. Deployed to Railway.

### Cities Online

| City | Platform | Adapter | Meeting Types | Council Members |
|---|---|---|---|---|
| **Birmingham** | Granicus | `GranicusAdapter` | Council | 9 active + 3 prior-term (districts) |
| **Vestavia Hills** | CivicClerk | `CivicClerkAdapter` | Council, P&Z, BZA, Design Review, Parks, Library, Annexation | 5 (at-large) |
| **Mobile** | CivicClerk | `CivicClerkAdapter` | Council | 7 (districts) |
| **Homewood** | Generic CMS | `GenericCMSAdapter` | Council, Pre-Council, BZA, Planning Commission + 7 committees | 5 (wards + mayor) |

### Cities Deferred (Blocked)

| City | Issue |
|---|---|
| **Hoover** | CivicPlus AgendaCenter is empty — no documents published. Adapter stub exists. |
| **Montgomery** | Website behind Cloudflare (403). Legistar portal exists but API not configured. |

### Build Phases

1. **Foundation** — PostgreSQL schema (10 tables), Docker, models, migration runner
2. **Granicus Adapter + Services** — Birmingham scraper, ingest service, query service
3. **Additional Adapters** — CivicClerk (API), GenericCMS (HTML scraping), CivicPlus (stub)
4. **Data Enrichment** — Dollar extraction, sponsor extraction, topic classification (11 topics), scoring stubs
5. **Search + Query** — PostgreSQL FTS, cross-city timeline, topic browse, high-dollar items
6. **Flask App** — 15 routes (11 public + 4 admin), editorial design, HTMX source rail
7. **Council Rosters** — 26 members seeded across 4 cities, admin UI for management
8. **Admin Auth** — Session-based login on all `/admin/*` routes
9. **Railway Deployment** — Live at `docket-web-production-6110.up.railway.app`
10. **Minutes Vote Parser** — PDF extraction of attendance + votes from Birmingham minutes (870 meetings, ~6,800 votes)
11. **Video OCR** — Imported Jan–Apr 2026 votes from al-municipal-meetings, ran fresh OCR for April meetings (77 votes)
12. **Vote-to-Item Matching** — Timestamp proximity (video OCR) + text heuristics (resolution number, item number, keyword overlap). Ported from al-municipal-meetings.
13. **Council Member Linking** — member_votes linked to council_members via FK, with term date awareness for old/new council transitions
14. **Landing Page** — Contested votes, recent votes table, notable items (180-day recency), topic browse
15. **Tests** — 140 unit tests, ruff clean

### What's Next

- **Astro frontend evaluation** — considering migration from Flask/Jinja2+HTMX to Astro
- **Freshness Checks** — Silent Break alerts when a city's data feed stops updating
- **Custom domain** — connect `docket.pub` via Railway dashboard
- **Source reconciliation** — compare video OCR vs official minutes when both exist

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.10+ |
| Web Framework | Flask + HTMX |
| Database | PostgreSQL 16 |
| Search | PostgreSQL full-text search (tsvector/tsquery with GIN indexes) |
| Containerization | Docker + docker-compose |
| Deployment | Railway (live) |

---

## Architecture

### Data Flow

```
City Website (Granicus / CivicClerk / Generic CMS)
       |
       v
  Platform Adapter          (one per CMS type — implements MunicipalSourceAdapter protocol)
       |
       v
  RawMeeting / RawAgendaItem   (protocol dataclasses — no DB knowledge)
       |
       v
  Enrichment Layer          (dollars, sponsors, topics, scoring stubs)
       |
       v
  Ingest Service            (upserts to PostgreSQL, tracks processing status)
       |
       v
  PostgreSQL                (10 tables, FTS indexes, auto-updated search vectors)
       |
       v
  Query Service             (read APIs returning frozen dataclasses)
       |
       v
  Flask Routes / HTMX UI   (skeleton built — 12 routes, unstyled templates)
```

### Adapter-per-Platform Pattern

Every city's data source is accessed through an adapter that implements the `MunicipalSourceAdapter` protocol (`src/docket/models/protocol.py`). The rest of the system never knows which CMS a city uses.

```python
class MunicipalSourceAdapter(Protocol):
    municipality_slug: str
    def list_meetings(self, since: date | None = None) -> list[RawMeeting]: ...
    def fetch_agenda_items(self, meeting: RawMeeting) -> list[RawAgendaItem]: ...
    def fetch_minutes_text(self, meeting: RawMeeting) -> str | None: ...
    def fetch_votes(self, meeting: RawMeeting) -> list[RawVote]: ...
```

**Adding a new city on a supported platform = one row in `municipalities` table.**

### Service Layer is Canonical

Every entry point (Flask route, CLI, pipeline) calls into `docket.services.*`. Services own DB transactions. Adapters and analysis modules live underneath.

```
Flask route  -->  services.query.list_meetings()  -->  DB
CLI          -->  services.ingest.ingest_municipality()  -->  Adapter  -->  DB
Backfill     -->  services.enrichment.backfill_municipality()  -->  DB
```

### Data Honesty Protocol

This is a core design principle, not optional:

- Every data point links back to the **original source** on the city's website
- Inline source badges on votes: `"Video OCR - High confidence"` / `"Official Minutes"` / `"API"`
- Footer attribution with direct links to original documents
- When video OCR and official minutes disagree, **both are shown** with a `"Sources disagree"` flag
- Missing data is **honestly reported, never hidden**

---

## Database Schema

10 tables in PostgreSQL. Full schema in `src/docket/migrations/001_initial.py`.

### Core Tables

#### `municipalities`
The registry of cities being tracked.
```
id, slug, name, state, county, adapter_class, adapter_config (JSONB),
council_type, timezone, active, created_at, updated_at
```

#### `meetings`
One row per meeting (council session, work session, etc.).
```
id, municipality_id, external_id, title, meeting_date, meeting_type,
agenda_url, minutes_url, video_url, source_url,
search_vector (TSVECTOR, auto-updated), created_at, updated_at
```
- `meeting_type`: `'council'` | `'work_session'` | `'planning'` | `'special'` | `'committee'` | `'board'` | `'other'`
- `source_url`: Always links back to the original page on the city's website

#### `agenda_items`
Individual items on a meeting's agenda. This is the richest table.
```
id, meeting_id, external_id, item_number, title, description,
section, is_consent, sponsor, topic,
dollars_amount (NUMERIC 15,2), significance_score (REAL 0-10),
consent_placement_score (REAL 0-10),
video_timestamp_seconds (REAL),
search_vector (TSVECTOR, auto-updated), created_at
```
- `sponsor`: Extracted from "(Submitted by ...)" or "(sponsored by ...)" patterns. NULL if not found.
- `topic`: Keyword-classified topic slug. One of: `zoning`, `public_safety`, `public_works`, `budget`, `grants`, `contracts`, `legal`, `parks_culture`, `licensing`, `appointments`, `routine`. NULL if unclassified.
- `dollars_amount`: Extracted via regex from title/description. The **largest** dollar amount in the text. NULL if none found.
- `significance_score`: 0-10 scale. **Currently NULL** — AI scoring deferred.
- `consent_placement_score`: 0-10 scale. **Currently NULL** — AI scoring deferred.
- `is_consent`: Boolean flag — was this item on the consent agenda?

#### `votes`
Vote outcomes tied to agenda items.
```
id, meeting_id, agenda_item_id, external_id, result,
yeas, nays, abstentions,
source, confidence, header_result, needs_review, review_reason,
video_timestamp, raw_text,
resolution_number, match_context, match_confidence (REAL 0-1), match_method,
created_at
```
- `result`: `'passed'` | `'failed'` | `'tabled'`
- `source`: `'video_ocr'` | `'minutes_text'` | `'api'` | `'manual'`
- `confidence`: `'high'` | `'medium'` | `'low'`
- `needs_review`: Flag for votes with extraction issues

#### `member_votes`
How each council member voted on each vote.
```
id, vote_id, council_member_id, member_name, position
```
- `position`: `'yea'` | `'nay'` | `'abstain'` | `'absent'`

### Supporting Tables

| Table | Purpose |
|---|---|
| `council_members` | Elected officials per city (name, district, term_start, term_end, active) |
| `districts` | Wards/districts per city |
| `processing_status` | Pipeline stage tracking per meeting (agenda scraped, PDF downloaded, votes scanned, votes matched) |
| `source_checks` | Freshness monitoring per city (last checked, last found, status) |

### Search

Full-text search is **already wired into the schema** via PostgreSQL tsvector:

- `meetings.search_vector` — auto-populated from `title` via trigger
- `agenda_items.search_vector` — auto-populated from `title + description` via trigger
- GIN indexes on both columns for fast querying
- Query with: `WHERE search_vector @@ to_tsquery('english', 'search terms')`

A search service wrapper (`services/search.py`) has not been built yet.

---

## Data Models (Python)

These are the frozen dataclasses returned by the query service. The UI will consume these.

### Meeting
```python
@dataclass(frozen=True)
class Meeting:
    id: int
    municipality_id: int
    external_id: str | None
    title: str                    # "City Council Meeting", "Special Called Meeting"
    meeting_date: str | None      # "2026-04-27"
    meeting_type: str | None      # "council", "special", "work_session", "planning"
    agenda_url: str | None        # Link to agenda on city's website
    minutes_url: str | None       # Link to minutes on city's website
    video_url: str | None         # Link to video (if available)
    source_url: str | None        # Canonical link back to original source
```

### AgendaItem
```python
@dataclass(frozen=True)
class AgendaItem:
    id: int
    meeting_id: int
    external_id: str | None
    item_number: str | None       # "23-582", "1.1.1", "A"
    title: str                    # "Approve $2.3M contract with HCL Contracting"
    description: str | None       # Extended description (up to 300 chars)
    section: str | None           # "Consent Agenda", "New Business"
    is_consent: bool              # Was this on the consent agenda?
    sponsor: str | None           # "the Mayor", "Councilor Smith, Chair, Arts Committee"
    dollars_amount: Decimal | None      # Largest dollar figure found (e.g. 2300000.00)
    topic: str | None                   # "zoning", "budget", "public_safety", etc.
    significance_score: float | None    # 0-10 (NULL until AI enabled)
    consent_placement_score: float | None  # 0-10 (NULL until AI enabled)
```

### Vote
```python
@dataclass(frozen=True)
class Vote:
    id: int
    meeting_id: int
    agenda_item_id: int | None
    external_id: str | None
    result: str              # "passed", "failed", "tabled"
    yeas: int | None
    nays: int | None
    abstentions: int | None
    source: str              # "video_ocr", "minutes_text", "api", "manual"
    confidence: str          # "high", "medium", "low"
    header_result: str | None
    needs_review: bool       # True if extraction had issues
    review_reason: str | None  # "extraction_failed", "counts_mismatch", etc.
    member_votes: list[MemberVote]

@dataclass(frozen=True)
class MemberVote:
    member_name: str         # "D. Abbott"
    position: str            # "yea", "nay", "abstain", "absent"
    council_member_id: int | None
```

---

## Query Service API

The query service (`src/docket/services/query.py`) provides the read layer. Flask routes call these — there are no REST endpoints.

**Core reads:**

| Function | Returns | Description |
|---|---|---|
| `list_municipalities()` | `list[dict]` | All active cities with meeting counts and last meeting date |
| `get_municipality(slug)` | `dict \| None` | Single city by slug (e.g. `"birmingham"`) |
| `list_meetings(slug, type, since, limit, offset)` | `PaginatedMeetings` | Paginated meetings with total count |
| `get_meeting(meeting_id)` | `Meeting \| None` | Single meeting by ID |
| `list_agenda_items(meeting_id)` | `list[AgendaItem]` | All items for a meeting, ordered by item_number |
| `list_votes(meeting_id)` | `list[Vote]` | Votes with member_votes attached |
| `list_council_members(slug, active_only)` | `list[dict]` | Council members with district info |
| `get_council_member(id)` | `dict \| None` | Single member by ID |
| `dashboard_stats()` | `dict` | Counts: municipalities, meetings, agenda_items, votes |

**Cross-city / timeline:**

| Function | Returns | Description |
|---|---|---|
| `list_recent_meetings(days, limit)` | `list[dict]` | "This week" — recent meetings across all cities |
| `list_upcoming_meetings(days, limit)` | `list[dict]` | "Coming up" — future meetings across all cities |

**Search (PostgreSQL FTS):**

| Function | Returns | Description |
|---|---|---|
| `search_meetings(query, city?, limit, offset)` | `list[dict]` | FTS on meeting titles, city-scoped by default |
| `search_agenda_items(query, city?, limit, offset)` | `list[dict]` | FTS on agenda item text, city-scoped by default |

**Topic / dollar browsing:**

| Function | Returns | Description |
|---|---|---|
| `list_agenda_items_by_topic(topic, city?, limit, offset)` | `list[dict]` | Filter by topic slug |
| `topic_counts(city?)` | `list[dict]` | Topic distribution for browse-by-topic UI |
| `list_high_dollar_items(min_dollars, city?, limit)` | `list[dict]` | Items above dollar threshold |

---

## Dollar Amount Display

Dollar amounts are extracted from agenda item text via regex and stored as `NUMERIC(15,2)`. The UI should display them with color-coded tiers:

| Tier | Range | Suggested Color |
|---|---|---|
| **Green** | < $50,000 | `#22c55e` / green-500 |
| **Yellow** | $50,000 - $250,000 | `#eab308` / yellow-500 |
| **Orange** | $250,000 - $1,000,000 | `#f97316` / orange-500 |
| **Red** | > $1,000,000 | `#ef4444` / red-500 |

The tier classification function is available at `docket.enrichment.dollars.classify_dollar_tier(amount)`.

Items with no dollar amount (`dollars_amount IS NULL`) should display normally without a tier badge.

---

## Scoring (Future)

Two scores are reserved on every agenda item but are **currently NULL**:

- **Significance Score (0-10):** How impactful is this item to residents? A $16M road contract scores higher than approving meeting minutes.
- **Consent Placement Score (0-10):** Does this item belong on the consent agenda? High-dollar or controversial items on the consent agenda score low (suggesting they shouldn't be there).

The scoring stubs exist at `docket.enrichment.scoring`. When AI features are enabled, these functions will return real scores. The UI should handle NULL gracefully (hide the score, don't show "0").

---

## Flask Routes

### Public (8 routes)

```
GET  /                                  Homepage (cities, this week, upcoming)
GET  /al/<slug>/                        City overview (meetings, topics, stats)
GET  /al/<slug>/meetings/               Paginated meeting list with type filter
GET  /al/<slug>/meetings/<id>/          Meeting detail (agenda items, dollars, votes)
GET  /al/<slug>/council/                Council member cards
GET  /search                            FTS search (city-scoped by default)
GET  /topics/                           Browse by topic index
GET  /topics/<topic>/                   Items for a specific topic
```

### Admin (4 routes — session-based auth required)

```
GET       /admin/members/               List all council members
GET|POST  /admin/members/add            Add a new member
GET|POST  /admin/members/<id>/edit      Edit member details
POST      /admin/members/<id>/deactivate  Deactivate member
```

### Jinja2 Template Filters

- `{{ amount | dollar_tier }}` — returns `"green"`, `"yellow"`, `"orange"`, or `"red"`
- `{{ slug | topic_name }}` — returns display name like `"Zoning & Land Use"`

---

## Project Structure

```
docket-pub-dw-dev/
  src/docket/                    # Main package ("docket")
    config.py                    # Environment variable config
    db.py                        # PostgreSQL connection (db() and db_cursor() context managers)
    models/
      protocol.py                # MunicipalSourceAdapter protocol + Raw* dataclasses
      meeting.py                 # Meeting dataclass (frozen, from_row)
      agenda.py                  # AgendaItem dataclass (frozen, from_row)
      vote.py                    # Vote + MemberVote dataclasses (frozen, from_row)
    migrations/
      001_initial.py             # Full schema: 10 tables, FTS, triggers, Birmingham seed
      002_seed_cities.py         # Seeds Vestavia Hills, Mobile, Homewood
      003_add_topic.py           # Adds topic column + index to agenda_items
      004_expand_meeting_types.py # Updates adapter configs for all meeting types
      005_seed_council_rosters.py # Seeds 26 council members + districts across 4 cities
      runner.py                  # Migration runner (apply/rollback/status)
    adapters/
      __init__.py                # Adapter registry + get_adapter() factory
      _helpers.py                # Shared: classify_meeting(), is_consent_item()
      granicus.py                # HTML scraper for Granicus publisher pages
      civicclerk.py              # REST API client for CivicClerk (OData)
      civicplus.py               # Stub for CivicPlus AgendaCenter (civic-scraper lib)
      generic_cms.py             # HTML archive page scraper (PDF link extraction)
    services/
      ingest.py                  # Scrape + enrich + upsert pipeline
      query.py                   # Read APIs: meetings, search, topics, timeline, members
      enrichment.py              # Enrichment service (inline + backfill)
    enrichment/
      dollars.py                 # Regex dollar extraction + tier classification
      sponsors.py                # Sponsor extraction from (Submitted/sponsored by)
      topics.py                  # Keyword-based topic classification (11 topics)
      scoring.py                 # Scoring stubs (returns None — AI deferred)
      cli.py                     # Backfill CLI: python -m docket.enrichment.cli
    web/
      __init__.py                # create_app() factory
      public.py                  # 8 public routes (city, meetings, search, topics, council)
      admin.py                   # 4 admin routes (council member CRUD)
      templates/                 # Jinja2 templates (unstyled — UI team designs)
      static/                    # CSS/JS assets (empty — UI team fills)
    analysis/                    # Vote OCR pipeline (NOT YET PORTED)
    rosters/                     # Reserved for future auto-scrapers
  tests/
    unit/
      test_dollars.py            # 31 tests — dollar extraction + tiers
      test_helpers.py            # 22 tests — meeting classification, consent detection
      test_generic_cms.py        # 15 tests — date parsing from filenames
      test_civicclerk.py         # 13 tests — hierarchical agenda flattening
      test_sponsors.py           # 26 tests — sponsor extraction + title cleaning
      test_topics.py             # 31 tests — topic classification
    integration/                 # (empty — needs running PostgreSQL)
  docs/
    Docket_pub_Project_Plan.md   # High-level strategy document
    SECURITY_CHECKLIST.md        # Pre-deployment security requirements
  docker-compose.yml             # PostgreSQL 16 + app container
  Dockerfile
  pyproject.toml                 # Package config, dependencies, pytest/ruff settings
  requirements.txt               # Pinned dependencies (mirrors pyproject.toml)
  .env.example                   # Template environment variables
  CLAUDE.md                      # AI assistant instructions (internal dev reference)
```

---

## Local Setup

### Prerequisites
- Python 3.10+
- PostgreSQL 16 (via Docker or Homebrew)

### Quick Start

```bash
# 1. Clone
git clone git@github.com:thinkdarrell/docket-pub-dw-dev.git
cd docket-pub-dw-dev

# 2. Start PostgreSQL
docker-compose up -d   # or use local Homebrew PostgreSQL

# 3. Python environment
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

# 4. Configure
cp .env.example .env
# Edit .env if your PostgreSQL credentials differ

# 5. Run migrations
python -m docket.migrations.runner

# 6. Verify
pytest                    # 76 tests, all green
ruff check src/           # lint clean
```

### Key Commands

```bash
# Run the dev server (no routes exist yet)
flask run

# Check migration status
python -m docket.migrations.runner --status

# Backfill dollar enrichment for existing data
python -m docket.enrichment.cli --all

# Test an adapter against live data (no DB required)
python -c "
from docket.adapters.civicclerk import CivicClerkAdapter
adapter = CivicClerkAdapter('mobile', {'tenant': 'mobileal', 'category_id': 26})
meetings = adapter.list_meetings()
print(f'{len(meetings)} meetings')
"
```

---

## Related Repositories

| Repo | Description |
|---|---|
| [thinkdarrell/docket-pub](https://github.com/thinkdarrell/docket-pub) | Main repo (this is the dev fork) |
| [thinkdarrell/docket-pub-dw-dev](https://github.com/thinkdarrell/docket-pub-dw-dev) | Active dev fork — all work happens here first |
| [thinkdarrell/al-municipal-meetings](https://github.com/thinkdarrell/al-municipal-meetings) | Original Birmingham pipeline with vote OCR — code ported from here |
| [thinkdarrell/docket-pub-site](https://github.com/thinkdarrell/docket-pub-site) | Landing page for docket.pub |
