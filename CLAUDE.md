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
      vote.py              # Vote + MemberVote + AgendaItemLink dataclasses (N:M shape)
    migrations/
      001_initial.py       # Full multi-city PostgreSQL schema
      007_council_terms_and_backfill.py  # Historical council members + term dates
      008_vote_matching_support.py       # video_timestamp_seconds, resolution_number, match columns
      009_vote_agenda_items.py           # N:M join table + meetings.minutes_adopted_at
      010_backfill_vote_agenda_items.py  # Copies legacy votes.agenda_item_id rows into the join table
      runner.py            # Migration runner (apply/rollback/status)
    adapters/              # Platform adapters (one per CMS type)
      _helpers.py          # Shared classify_meeting(), is_consent_item()
      granicus.py          # Birmingham (Granicus HTML scraper)
      civicclerk.py        # Vestavia Hills, Mobile (CivicClerk REST API)
      civicplus.py         # Stub for CivicPlus AgendaCenter sites
      generic_cms.py       # Homewood (HTML archive page with PDF links)
    services/              # Business logic layer (ingest, query, search, etc.)
      ingest.py            # Scrape + enrich + upsert pipeline (calls sweep_adoptions at end of each run)
      query.py             # Read APIs: meetings, items, search, topics, timeline; list_votes uses 3-query N:M reader
      enrichment.py        # Enrichment service (inline + backfill)
      minutes_adoption.py  # Adoption-pattern detection + sweep_adoptions; dual-trigger contract with strict_reparse_meeting
    web/                   # Flask app factory + blueprints
      __init__.py          # create_app() factory (production cookie settings)
      public.py            # Citizen-facing routes (11 routes + 3 HTMX partials)
      admin.py             # Admin routes (4 routes — council member CRUD, auth-gated)
      auth.py              # Auth blueprint — /admin/login, /admin/logout, login_required
      create_admin.py      # CLI: python -m docket.web.create_admin <user> <pass>
      templates/           # Jinja2 templates (editorial design from Claude Design)
        base.html          # App shell with rail sidebar, fonts, HTMX
        city.html          # Birmingham overview (hero, KPIs, topics, legislation, council)
        meeting_detail.html # Renders the N:M vote shape: substantive 1:1, consent block collapse, provisional/adopted pills
        partials/          # HTMX fragments
          masthead.html, footer.html
          rail_default.html, rail_meeting.html, rail_member.html  # Rail states (member rail shows linked agenda items + source-doc deep links)
          council_card.html  # Shared council member card (used by city.html + council.html)
      static/              # Design system CSS (Source Serif + IBM Plex + JetBrains Mono)
        styles.css         # Tokens, typography, chips, tiers, citations
        layout.css         # Masthead, hero, KPIs, feed, council cards, rail
        councilmatic.css   # This-week strip, topic browse, legislation cards
        tweaks.css         # Footer, rail empty CTA
    analysis/
      minutes_parser.py    # Birmingham minutes PDF → attendance + votes (1500-char pre-vote window, persists raw_text, sets is_likely_consent)
      vote_matcher.py      # N:M matcher: classify substantive vs consent_block, run substantive 3-tier + consent_block (named-callout + default-fill) matchers, strict_reparse_meeting for adoption promotion. _upsert_link enforces the manual shield (app-level + DB-level WHERE is_manual=FALSE).
    rosters/               # Council member rosters (not yet built)
    enrichment/            # Dollar extraction, sponsors, topics, scoring
      dollars.py           # Regex dollar extraction + tier classification
      sponsors.py          # Sponsor extraction from (Submitted/sponsored by)
      topics.py            # Keyword-based topic classification (11 topics)
      scoring.py           # Scoring stubs (AI deferred)
      cli.py               # Backfill CLI: python -m docket.enrichment.cli
  scripts/                   # Data backfill and import scripts
    import_video_ocr.py      # Import video OCR votes from al-municipal-meetings SQLite
    backfill_member_vote_ids.py  # Dynamic name→council_member_id resolution using roster
    backfill_agenda_timestamps.py  # Re-scrape Granicus for agenda item video timestamps
    backfill_vote_context.py  # Re-parse minutes PDFs for resolution_number + match_context
    run_vote_matching.py      # Batch runner for vote-to-agenda-item matching
  tests/
    unit/                  # 140 tests (dollars, helpers, sponsors, topics, civicclerk, generic_cms)
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
| Sponsor extraction | Done | `enrichment/sponsors.py` — Birmingham + Mobile patterns |
| Topic classification | Done | `enrichment/topics.py` — 11 keyword-based topics |
| Scoring stubs | Done | `enrichment/scoring.py` — returns None, ready for AI integration |
| Enrichment service | Done | `services/enrichment.py` — inline + backfill, CLI at `enrichment/cli.py` |
| Search service | Done | `services/query.py` — FTS via websearch_to_tsquery, city-scoped |
| Query service | Done | Timeline, topic browse, high-dollar items, council members, pagination |
| Flask app + routes | Done | 15 routes (11 public + 4 admin), HTMX rail partials |
| Migration 003 | Done | Adds `topic` column to agenda_items |
| Migration 004 | Done | Expands adapter configs for all meeting types |
| Migration 005 | Done | Seeds 26 council members + districts across 4 cities |
| Citizen frontend | Done | Editorial design from Claude Design — Source Serif + IBM Plex + HTMX |
| Source-of-truth rail | Done | HTMX partials update on click (meeting, member, default) |
| Council roster admin | Done | `/admin/members/` — add, edit, deactivate council members |
| Security checklist | Done | `docs/SECURITY_CHECKLIST.md` — pre-deployment requirements |
| Admin auth | Done | Session-based login, migration 006, `/admin/login`, `create_admin` CLI |
| Deployment | Done | Railway — live at `docket-web-production-6110.up.railway.app` |
| Minutes vote parser | Done | `analysis/minutes_parser.py` — PDF text extraction, attendance + votes (curly apostrophe fix for O'Quinn) |
| Vote ingestion | Done | Ingest pipeline Stage 4 — parses minutes, inserts votes + member_votes with resolution_number + match_context |
| Video OCR pipeline | Done | Imported Jan–Apr 2026 votes from al-municipal-meetings, ran fresh OCR for April meetings |
| Video OCR import | Done | `scripts/import_video_ocr.py` — maps al-municipal-meetings SQLite → docket PostgreSQL |
| Vote-to-item matching | Done | `analysis/vote_matcher.py` — timestamp matching (bisect, ported from al-municipal-meetings) + text heuristics (resolution number, item number, keyword overlap) |
| Council member linking | Done | Migration 007 (term dates), `scripts/backfill_member_vote_ids.py` (dynamic roster-based), query uses council_member_id FK |
| Landing page | Done | Contested votes, recent votes table, notable items (180-day limit), topic browse |
| `vote_agenda_items` join table | Done | Migration 009 — N:M shape with `association_type`, `provisional`, `is_manual`, `is_active` |
| Adoption sweep + strict re-parse | Done | `services/minutes_adoption.py` (sweep) + `analysis/vote_matcher.py:strict_reparse_meeting` — promotes provisional consent links to official after council adopts the minutes |
| N:M reader rewrite | Done | `services/query.py:list_votes(meeting_id, *, include_excerpts=False)` — 3-query pattern (votes + vote_agenda_items + member_votes) |
| `meeting_detail.html` N:M render | Done | Substantive vs consent-block branching, consent-block collapse, provisional/adopted pills |
| Council member rail with linked items | Done | `rail_member.html` — shows what each vote was about, with source-document deep links |
| Editorial design pass on remaining templates | Done | meetings list, topics index, topic detail, search, council pages |
| AI summaries + scoring | Done | `src/docket/ai/` — Haiku item summaries, Sonnet meeting executive summaries, two-phase lifecycle keyed off `minutes_adopted_at`, `ai_runs` cost telemetry, async batch worker + CLI (`python -m docket.ai.cli`) |
| Source reconciliation | Not built | Compare video OCR vs official minutes |
| Freshness checks | Not built | Nightly auto-check + manual trigger |
| Public API | Not built | Flask blueprint for `/api/v1/` (deferred — security concern) |
| Astro frontend | Deferred | Evaluate Astro as Flask/Jinja2+HTMX replacement |

### Build phases (reference)

1. ~~Foundation (schema, Docker, models)~~ — DONE
2. ~~Granicus adapter + services~~ — DONE
3. ~~Additional adapters (CivicClerk, GenericCMS)~~ — DONE (Hoover/Montgomery deferred — blocked)
4. ~~Data enrichment (dollars, sponsors, topics, scoring stubs)~~ — DONE (vote OCR, reconciliation → Phase 4b)
5. ~~Search + query expansion~~ — DONE (FTS, timeline, topics, high-dollar; public REST API deferred)
6. ~~Citizen frontend~~ — DONE (editorial design from Claude Design, HTMX source rail, council cards)
7. ~~Admin auth~~ — DONE (session-based login, migration 006)
8. ~~Deployment~~ — DONE (Railway, gunicorn, production cookies)
9. ~~Minutes vote extraction~~ — DONE (PDF parser for Birmingham, 870 meetings with minutes)
10. ~~Video OCR for post-12/30 meetings~~ — DONE (imported from al-municipal-meetings + fresh April OCR)
11. ~~Vote-to-item matching~~ — DONE (migration 008, timestamp + text matching, backfill scripts)
12. ~~Council member linking~~ — DONE (migration 007, dynamic backfill, FK-based queries)
13. ~~Landing page refresh~~ — DONE (contested votes, recent votes, 180-day notable items)
14. ~~Vote-to-item matching N:M redesign~~ — DONE (vote_agenda_items join table, substantive + consent matchers, strict re-parse, dual-trigger adoption lifecycle)
15. ~~Editorial design pass on remaining templates~~ — DONE (meetings/topics/topic_detail/search/council)
16. ~~AI summaries + scoring~~ — DONE (migration 012, `src/docket/ai/` package, Haiku items + Sonnet meetings, two-phase lifecycle, ai_runs telemetry, admin panel)
17. Astro frontend evaluation — DEFERRED

### Key decisions to preserve

- **PostgreSQL from day 1** — no SQLite fallback
- **AI summaries + scoring:** items use Haiku 4.5, meetings use Sonnet 4.6. Two-phase meeting lifecycle keyed off `minutes_adopted_at` (provisional → adopted overwrites the executive summary). NULL `topic` renders as `"Uncategorized"` in prompts (never the literal `"None"`). Daily budget gate via `AI_DAILY_BUDGET_USD`; bumping `ITEM_PROMPT_VERSION` re-cascades both stages automatically. Worker writes per-row using `SELECT FOR UPDATE SKIP LOCKED` so multiple instances are safe.
- **Two scoring dimensions:** significance (0-10) + consent placement (0-10)
- **Dollar tiers:** green <$50K, yellow $50-250K, orange $250K-1M, red >$1M
- **Source overlap:** video OCR + official minutes coexist, flag discrepancies only
- **Council rosters:** scrape council pages, don't manually seed
- **Search:** PostgreSQL FTS (tsvector/tsquery), not a separate engine
- **Data Honesty:** inline badges + footer attribution + discrepancy flags
- **Silent Break alerts:** dashboard + email notifications
- **Deployment:** Railway (live), gunicorn, production cookies, Procfile
- **Vote sources:** Minutes PDF (~6,800 votes across 870 meetings), video OCR (77 votes, Jan–Apr 2026). Consent-block votes get 1:N coverage (one vote → many items), and that's now the dominant link source — total active links across Birmingham land at ~36K after the backfill.
- **Vote matching:** Timestamp proximity for OCR votes (bisect, ported from al-municipal-meetings), text heuristics for minutes votes (resolution number, item number, keyword overlap). Each vote is first classified substantive vs consent_block; substantive runs 3-tier matching, consent_block runs named-callout + default-fill passes.
- **N:M vote↔agenda links:** `vote_agenda_items` join table — one consent vote can link to many items. Named callouts get `match_confidence=1.0`, default consent fill gets `0.8`.
- **Provisional → Official lifecycle:** `consent_named` and `consent_implicit` links insert with `provisional=TRUE`. They flip to `FALSE` when council adopts the minutes (sweep_adoptions sets `meetings.minutes_adopted_at`, then strict re-parse promotes the links). Substantive (`explicit`) links insert with `provisional=FALSE` directly.
- **Manual shield:** `is_manual=TRUE` on a `vote_agenda_items` row protects it from automated overwrite — enforced both by an app-level pre-check in `_upsert_link` and a DB-level `WHERE is_manual = FALSE` predicate on every UPDATE.
- **Active vs ghost links:** `is_active=FALSE` marks links to items that were on the consent agenda at meeting time but pulled out and voted separately. Kept for audit; hidden from the default reader (`Vote.active_links`).
- **Strict re-parse safety:** when the enumerated consent list resolves to zero target agenda items, `strict_reparse_meeting` aborts (does NOT mass-deactivate). Protects against PDF/OCR glitches that could otherwise wipe every active consent link in the meeting.
- **Dual-trigger contract:** `strict_reparse_meeting` fires from both the matcher (when matching a meeting whose `minutes_adopted_at` is already non-NULL) and the sweep (when newly flipping a meeting NULL → adopted). Order independent — either path lands the same end state.
- **Video OCR:** Import `muni.analysis` from al-municipal-meetings (installed in venv), don't re-port
- **Council member linking:** Dynamic name→ID resolution using roster + term dates, not hardcoded maps
- **Deploy:** `railway up --detach` (NOT `railway redeploy` which restarts old build without new code)
- **Minutes parser:** Must handle curly apostrophes (U+2019) in name regex — O'Quinn fix. Pre-vote window is 1500 chars (was 500, last 200) so the resolution body is captured into `votes.raw_text`.

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
