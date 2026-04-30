# Docket.pub

**Municipal meeting intelligence platform for Alabama cities.**

Docket.pub automates the collection, parsing, enrichment, and indexing of public meeting records from local governments. The goal is civic transparency: make every agenda item, vote, and dollar amount searchable — and link every data point back to its original source on the city's website.

**Domain:** [docket.pub](https://docket.pub) | **Status:** Private Development | **Repo:** Dev fork (`docket-pub-dw-dev`)

---

## What's Built

The backend pipeline is complete through data enrichment. There is **no frontend yet** — that's the next phase.

### Cities Online

| City | Platform | Adapter | Data Available |
|---|---|---|---|
| **Birmingham** | Granicus | `GranicusAdapter` | 1,001+ meetings, agenda items via HTML scraping |
| **Vestavia Hills** | CivicClerk | `CivicClerkAdapter` | 108 events, structured agenda items via REST API |
| **Mobile** | CivicClerk | `CivicClerkAdapter` | Meetings + 69 agenda items (with dollar amounts) |
| **Homewood** | Generic CMS | `GenericCMSAdapter` | 248 meetings (2016-present), agenda + minutes PDFs |

### Cities Deferred (Blocked)

| City | Issue |
|---|---|
| **Hoover** | CivicPlus AgendaCenter is empty — no documents published. Adapter stub exists. |
| **Montgomery** | Website behind Cloudflare (403). Legistar portal exists but API not configured. |

### Build Phases Completed

1. **Foundation** — PostgreSQL schema (10 tables), Docker, models, migration runner
2. **Granicus Adapter + Services** — Birmingham scraper, ingest service, query service
3. **Additional Adapters** — CivicClerk (API), GenericCMS (HTML scraping), CivicPlus (stub)
4. **Data Enrichment** — Dollar extraction (regex), scoring stubs (AI deferred)
5. **Tests + Lint** — 76 unit tests, ruff clean

### What's Next

- **Search + Frontend** — PostgreSQL FTS is wired in the schema (tsvector/tsquery with GIN indexes, auto-updated via triggers). Needs a search service wrapper and the HTMX-based citizen UI.
- **Vote OCR Pipeline** — 8-module video analysis pipeline exists in [al-municipal-meetings](https://github.com/thinkdarrell/al-municipal-meetings), not yet ported.
- **Admin Dashboard** — Health monitoring, "Silent Break" alerts when a city's data feed stops updating.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.10+ |
| Web Framework | Flask + HTMX |
| Database | PostgreSQL 16 |
| Search | PostgreSQL full-text search (tsvector/tsquery with GIN indexes) |
| Containerization | Docker + docker-compose |
| Deployment | Deferred (Hetzner or Railway) |

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
  Enrichment Layer          (dollar extraction, scoring stubs)
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
  Flask Routes / HTMX UI   (NOT YET BUILT)
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
- `meeting_type`: `'council'` | `'work_session'` | `'bza'` | `'planning'` | `'special'` | `'committee'`
- `source_url`: Always links back to the original page on the city's website

#### `agenda_items`
Individual items on a meeting's agenda. This is the richest table.
```
id, meeting_id, external_id, item_number, title, description,
section, is_consent, sponsor,
dollars_amount (NUMERIC 15,2), significance_score (REAL 0-10),
consent_placement_score (REAL 0-10),
search_vector (TSVECTOR, auto-updated), created_at
```
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
video_timestamp, raw_text, created_at
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
| `council_members` | Elected officials per city (name, district, term dates, photo) |
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
    sponsor: str | None           # Council member who sponsored
    dollars_amount: Decimal | None      # Largest dollar figure found (e.g. 2300000.00)
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

The query service (`src/docket/services/query.py`) provides the read layer. The frontend calls these functions — there are no REST endpoints yet.

| Function | Returns | Description |
|---|---|---|
| `list_municipalities()` | `list[dict]` | All active cities with meeting counts and last meeting date |
| `get_municipality(slug)` | `dict \| None` | Single city by slug (e.g. `"birmingham"`) |
| `list_meetings(slug, type, since, limit, offset)` | `list[Meeting]` | Paginated meetings for a city, newest first |
| `get_meeting(meeting_id)` | `Meeting \| None` | Single meeting by ID |
| `list_agenda_items(meeting_id)` | `list[AgendaItem]` | All items for a meeting, ordered by item_number |
| `list_votes(meeting_id)` | `list[Vote]` | Votes with member_votes attached |
| `dashboard_stats()` | `dict` | Counts: municipalities, meetings, agenda_items, votes |

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

## URL Routing (Suggested)

The project plan specifies semantic routing:

```
/                                          # Home — city picker + search
/{state}/{city}/                           # City overview — recent meetings, stats
/{state}/{city}/meetings/                  # Meeting list with filters
/{state}/{city}/meetings/{date}-{slug}/    # Meeting detail — agenda items, votes
/search?q=...                              # Cross-city search results
```

Example: `/al/birmingham/meetings/2026-04-15-regular-council/`

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
      query.py                   # Read APIs (list_meetings, list_agenda_items, etc.)
      enrichment.py              # Dollar enrichment service (inline + backfill)
    enrichment/
      dollars.py                 # Regex dollar extraction + tier classification
      scoring.py                 # Scoring stubs (returns None — AI deferred)
      cli.py                     # Backfill CLI: python -m docket.enrichment.cli
    web/                         # Flask blueprints (NOT YET BUILT)
    analysis/                    # Vote OCR pipeline (NOT YET PORTED)
    rosters/                     # Council member rosters (NOT YET BUILT)
  tests/
    unit/
      test_dollars.py            # 31 tests — dollar extraction + tiers
      test_helpers.py            # 17 tests — meeting classification, consent detection
      test_generic_cms.py        # 15 tests — date parsing from filenames
      test_civicclerk.py         # 13 tests — hierarchical agenda flattening
    integration/                 # (empty — needs running PostgreSQL)
  docs/
    Docket_pub_Project_Plan.md   # High-level strategy document
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
