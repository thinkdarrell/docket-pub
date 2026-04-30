# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**docket.pub** — a municipal meeting intelligence platform that ingests, parses, and indexes public meeting records from Alabama cities (Birmingham, Mobile, Montgomery, Hoover, Homewood, Vestavia Hills). The goal is civic transparency: make local government dockets searchable and link every data point back to the original source document.

Domain: `docket.pub` | Status: **Private Development Phase** | Dev fork: `docket-pub-dw-dev`

This project builds on work from the [al-municipal-meetings](https://github.com/thinkdarrell/al-municipal-meetings) repo (Birmingham-focused Granicus scraper with vote OCR). docket.pub generalizes that into a multi-city platform with a public-facing web interface.

## Layout

```
docket-pub-dw-dev/
  src/docket/              # Main package
    config.py              # Environment variable config
    db.py                  # PostgreSQL connection manager (db() and db_cursor())
    models/
      protocol.py          # MunicipalSourceAdapter protocol + Raw* dataclasses
      meeting.py           # Meeting dataclass
      agenda.py            # AgendaItem dataclass
      vote.py              # Vote + MemberVote dataclasses
    migrations/
      001_initial.py       # Full multi-city PostgreSQL schema
      runner.py            # Migration runner (apply/rollback/status)
    adapters/              # Platform adapters (one per CMS type)
      _helpers.py          # Shared classify_meeting(), is_consent_item()
      granicus.py          # Birmingham (Granicus HTML scraper)
      civicclerk.py        # Vestavia Hills, Mobile (CivicClerk REST API)
      civicplus.py         # Stub for CivicPlus AgendaCenter sites
      generic_cms.py       # Homewood (HTML archive page with PDF links)
    services/              # Business logic layer (ingest, query, search, etc.)
      enrichment.py        # Enrichment service (inline + backfill)
    web/                   # Flask blueprints (public, admin, API)
    analysis/              # Vote OCR pipeline (ported from al-municipal-meetings)
    rosters/               # Council member rosters per city
    enrichment/            # Dollar extraction, scoring stubs
      dollars.py           # Regex dollar extraction + tier classification
      scoring.py           # Scoring stubs (AI deferred)
      cli.py               # Backfill CLI: python -m docket.enrichment.cli
  tests/
    unit/
    integration/
  docs/
    Docket_pub_Project_Plan.md
  docker-compose.yml       # PostgreSQL + app
  Dockerfile
  pyproject.toml
  requirements.txt
  .env.example
```

## Tech Stack

- **Language:** Python 3.10+
- **Web Framework:** Flask + HTMX
- **Database:** PostgreSQL 16 (via Docker)
- **Search:** PostgreSQL full-text search (tsvector/tsquery with GIN indexes)
- **Containerization:** Docker + docker-compose
- **Deployment:** Deferred (Hetzner or Railway)

## Key Commands

```bash
# Docker setup (PostgreSQL + app)
docker-compose up -d

# Local setup (without Docker app container)
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env

# Run migrations
python -m docket.migrations.runner
python -m docket.migrations.runner --status
python -m docket.migrations.runner --down 1

# Run dev server
flask run

# Tests
pytest
```

## Architecture

### Adapter-per-platform pattern

Every municipal data source is accessed through a platform adapter implementing `MunicipalSourceAdapter` (in `models/protocol.py`). The rest of the system never knows which CMS a city uses.

Supported platforms: Granicus, CivicClerk, CivicPlus, Generic CMS.

Adding a new city on a supported platform = one row in `municipalities` table + council member data.

### Service layer is canonical

Every entry point (Flask route, CLI, pipeline) calls into `docket.services.*`. Services own DB transactions. Adapters and analysis modules live underneath.

### Data Honesty Protocol

- Every data point links back to the original source on the city's website
- Inline source badges on votes: "Video OCR - High confidence" / "Official Minutes" / "API"
- Footer attribution with direct links to original documents
- When video OCR and official minutes disagree, both are shown with a "Sources disagree" flag
- Missing data is honestly reported, never hidden

### Scoring model

Two independent 0-10 scores on every agenda item (NULL until AI features enabled):
- **Significance score:** How impactful is this item?
- **Consent placement score:** Should this be on the consent agenda?

### Dollar amount tiers

All dollar amounts extracted, displayed with color-coded tiers:
- Green: < $50K | Yellow: $50-250K | Orange: $250K-1M | Red: > $1M

## Conventions

- Package name: `docket` (under `src/docket/`)
- All Python modules use absolute imports rooted at `docket.*`
- Environment secrets go in `.env`, never committed
- Web routes are thin — business logic belongs in `services/`
- Adapter modules live in `adapters/`, one module per platform type
- PostgreSQL connection via `docket.db.db()` or `docket.db.db_cursor()`

## Dev Fork Workflow

This repo (`docket-pub-dw-dev`) is a **test/dev fork** of the main `docket-pub` repo. All active development happens here first.

### Rules for this fork

- **Build and test here freely.** This is the sandbox — experiment, iterate, break things.
- **Do NOT push directly to `docket-pub` (main repo).** When work is ready to merge back, it goes via:
  ```bash
  cd /path/to/docket-pub
  git remote add dev-fork git@github.com:thinkdarrell/docket-pub-dev.git
  git fetch dev-fork
  git merge dev-fork/main
  ```
- **Commit frequently with clear messages.** Each phase of work gets its own commit.
- **Port code from `al-municipal-meetings`, don't copy blindly.** Adapt for PostgreSQL, multi-city, and the adapter protocol. The original repo uses SQLite and is Birmingham-only.
- **Test against live data when possible.** The Granicus adapter should be tested against `bhamal.granicus.com`. Use polite delays (1s+) between requests.

### What's been ported and what hasn't

| Component | Status | Notes |
|---|---|---|
| PostgreSQL schema + migrations | Done | 10 tables, FTS indexes, Birmingham seeded |
| Adapter protocol + registry | Done | `MunicipalSourceAdapter` in `models/protocol.py` |
| GranicusAdapter | Done | Verified with 1,001 live Birmingham meetings |
| CivicClerkAdapter | Done | Vestavia Hills (108 events) + Mobile (69 agenda items verified) |
| CivicPlusAdapter | Stubbed | Hoover AgendaCenter is empty; adapter exists but returns no data |
| GenericCMSAdapter | Done | Homewood: 248 meetings (2016-present), agenda + minutes PDFs |
| Shared adapter helpers | Done | `_helpers.py` with `classify_meeting()`, `is_consent_item()` |
| Migration 002 | Done | Seeds Vestavia Hills, Mobile, Homewood |
| Ingest service | Done | Scrapes meetings + agenda items via adapters, enriches inline |
| Query service | Done | Reads meetings, items, votes, dashboard stats |
| Dollar extraction | Done | Regex pipeline in `enrichment/dollars.py`, tested against Mobile (24/69 items) |
| Scoring stubs | Done | `enrichment/scoring.py` — returns None, ready for AI integration |
| Enrichment service | Done | `services/enrichment.py` — inline + backfill, CLI at `enrichment/cli.py` |
| Vote OCR pipeline | Not ported | Lives in `al-municipal-meetings/src/muni/analysis/` |
| Council roster scrapers | Not built | Scrape city council pages for member data |
| Source reconciliation | Not built | Compare video OCR vs official minutes |
| Freshness checks | Not built | Nightly auto-check + manual trigger |
| Search service | Not built | PostgreSQL FTS wrapper |
| Public API | Not built | Flask blueprint for `/api/v1/` |
| Citizen frontend | Not built | HTMX-based UI |
| Admin dashboard | Not built | Health monitoring + Silent Break alerts |

### Build phases (reference)

1. ~~Foundation (schema, Docker, models)~~ — DONE
2. ~~Granicus adapter + services~~ — DONE
3. ~~Additional adapters (CivicClerk, GenericCMS)~~ — DONE (Hoover/Montgomery deferred — blocked)
4. ~~Data enrichment (dollars, scoring stubs)~~ — DONE (vote OCR, reconciliation, freshness → Phase 4b)
5. Search + public API
6. Citizen frontend + admin monitoring

### Key decisions to preserve

- **PostgreSQL from day 1** — no SQLite fallback
- **AI features deferred** — scoring columns exist in schema but are NULL
- **Two scoring dimensions:** significance (0-10) + consent placement (0-10)
- **Dollar tiers:** green <$50K, yellow $50-250K, orange $250K-1M, red >$1M
- **Source overlap:** video OCR + official minutes coexist, flag discrepancies only
- **Council rosters:** scrape council pages, don't manually seed
- **Search:** PostgreSQL FTS (tsvector/tsquery), not a separate engine
- **Data Honesty:** inline badges + footer attribution + discrepancy flags
- **Silent Break alerts:** dashboard + email notifications
- **Deployment:** Docker-based, hosting deferred (Hetzner or Railway)

### Local PostgreSQL setup

If not using Docker, PostgreSQL 16 can be run via Homebrew:
```bash
# Start
/opt/homebrew/opt/postgresql@16/bin/pg_ctl -D /opt/homebrew/var/postgresql@16 start

# Stop
/opt/homebrew/opt/postgresql@16/bin/pg_ctl -D /opt/homebrew/var/postgresql@16 stop

# Create DB (first time only)
/opt/homebrew/opt/postgresql@16/bin/createuser -s docket
/opt/homebrew/opt/postgresql@16/bin/createdb -O docket docket_db
```

Then set `DATABASE_URL=postgresql://docket@localhost:5432/docket_db` in `.env`.

## Related Repositories

- [thinkdarrell/docket-pub](https://github.com/thinkdarrell/docket-pub) — main repo (this is the dev fork)
- [thinkdarrell/al-municipal-meetings](https://github.com/thinkdarrell/al-municipal-meetings) — Birmingham pipeline, code ported from here
