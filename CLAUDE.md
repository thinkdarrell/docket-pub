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
    services/              # Business logic layer (ingest, query, search, etc.)
    web/                   # Flask blueprints (public, admin, API)
    analysis/              # Vote OCR pipeline (ported from al-municipal-meetings)
    rosters/               # Council member rosters per city
    enrichment/            # Dollar extraction, scoring stubs
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

## Related Repositories

- [thinkdarrell/docket-pub](https://github.com/thinkdarrell/docket-pub) — main repo (this is the dev fork)
- [thinkdarrell/al-municipal-meetings](https://github.com/thinkdarrell/al-municipal-meetings) — Birmingham pipeline, code ported from here
