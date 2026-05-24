# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**docket.pub** — a municipal meeting intelligence platform that ingests, parses, and indexes public meeting records from Alabama cities (Birmingham, Mobile, Montgomery, Hoover, Homewood, Vestavia Hills). The goal is civic transparency: make local government dockets searchable and link every data point back to the original source document.

Domain: `docket.pub` | Status: **Private Development Phase** | Repo: `thinkdarrell/docket-pub`

This project builds on work from the [al-municipal-meetings](https://github.com/thinkdarrell/al-municipal-meetings) repo (Birmingham-focused Granicus scraper with vote OCR). docket.pub generalizes that into a multi-city platform with a public-facing web interface.

## Layout

```
docket-pub/
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
      011_drop_deprecated_vote_columns.py  # Drops votes.agenda_item_id / match_method / match_confidence (PR2)
      012_ai_summaries_and_scoring.py   # AI columns on agenda_items, ai_runs cost telemetry
      013_impact_first_refactor.py      # v3 schema: 10 new tables, MV, enums, indexes, seed data
      015_search_vector_v3.py           # search_vector now includes headline/why_it_matters/JSONB
      016_relax_audit_fk.py             # agenda_item_badges_audit FK → ON DELETE SET NULL (baked into 013)
      018_ai_batches_ingested_at.py     # ai_batches.ingested_at + index
      020_raise_headline_caps.py        # chk_headline_length 60→80, why_it_matters 200→280 (prompt v4)
      021_badge_status_column.py        # agenda_item_badges.status (applied/flagged/rejected) — refactor #2
      022_badge_mv_status_filter.py     # mv_badge_volume_monthly filters status='applied' — refactor #2
      023_processing_status_withdrawn.py  # Adds 'withdrawn' to processing_status_enum
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
      maintenance.py       # repair_empty_agendas() — clears agenda_items_scraped flag for stuck meetings, called weekly by the cron worker
      minutes_adoption.py  # Adoption-pattern detection + sweep_adoptions; dual-trigger contract with strict_reparse_meeting
    worker/                # Cron worker (Railway `worker` service, runs `python -m docket.worker.scheduler`)
      scheduler.py         # APScheduler BlockingScheduler entry point + --run-once <task> flag
      tasks.py             # 11 task wrappers (ingest_all, video_ocr, ai_items, ai_meetings, vote_matching, repair_empty_agendas, process_badges, calibration_report, process_batches, refresh_backfill_ratio_mv, prune_analytics) calling existing services; _safe_run handles Healthchecks ping + exception swallow
      health.py            # Healthchecks.io ping helper (no-ops when UUID env var unset)
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
    unit/                  # ~270 tests (dollars, helpers, sponsors, topics, civicclerk, generic_cms, ai/*, worker/*)
    integration/           # AI pipeline e2e + maintenance repair
    live/                  # Gated on ANTHROPIC_API_KEY (real Haiku/Sonnet smoke tests)
  docs/
    Docket_pub_Project_Plan.md
    runbooks/
      cron-worker.md       # Healthchecks setup, deploy, --run-once verification, alert response, 18-month backfill
  docker-compose.yml       # PostgreSQL + app
  Dockerfile
  pyproject.toml
  requirements.txt
  .env.example
```

## Tech Stack

- **Language:** Python 3.10+
- **Web Framework:** Flask + HTMX
- **Database:** PostgreSQL 18.3 on Railway (production); PG 16 locally via Docker or Homebrew
- **Search:** PostgreSQL full-text search (tsvector/tsquery with GIN indexes)
- **Containerization:** Docker + docker-compose
- **Deployment:** Railway (live)

## Key Commands

```bash
# Docker setup (PostgreSQL + app)
docker-compose up -d

# Local setup (without Docker app container)
python3.10 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"          # reads requirements.lock via pyproject — deterministic
cp .env.example .env

# Refresh the lockfile when you edit requirements.txt
uv pip compile requirements.txt --python-version 3.10 -o requirements.lock
# (brew install uv if not present)

# Run migrations
python -m docket.migrations.runner
python -m docket.migrations.runner --status
python -m docket.migrations.runner --down 1

# Run dev server
flask run

# Tests
pytest
```

**Dependency lockfile workflow:**
`requirements.txt` is the source-of-truth for top-level deps (loose `>=`
ranges). `requirements.lock` is the pinned tree generated by
`uv pip compile`. Dockerfile and `pyproject.toml`'s
`[tool.setuptools.dynamic]` both read the lock, so local dev (`pip
install -e ".[dev]"`), CI, and Railway resolve the same versions. When
you bump a dep, edit `requirements.txt` AND regenerate the lock — never
commit one without the other. The lockfile is targeted at Python 3.10
(matching the Dockerfile + Railway).

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

## Development Workflow

Single repo: `thinkdarrell/docket-pub`. `main` is the source of truth and what Railway deploys. Feature work goes on `feat/*` branches and merges back via PR.

(Historical note: this used to be a "dev fork" workflow split across `docket-pub` and `docket-pub-dw-dev`. As of 2026-05-03 those were consolidated; the abandoned skeleton lives at `thinkdarrell/docket-pub-archived` for history. Pre-consolidation safety tags `pre-consolidation/*` are preserved on `origin`.)

### Rules

- **Build and test here freely.** Feature branches are the sandbox.
- **Commit frequently with clear messages.** Each phase of work gets its own commit.
- **Port code from `al-municipal-meetings`, don't copy blindly.** Adapt for PostgreSQL, multi-city, and the adapter protocol. The original repo uses SQLite and is Birmingham-only.
- **Test against live data when possible.** The Granicus adapter should be tested against `bhamal.granicus.com`. Use polite delays (1s+) between requests.
- **Deploy ONLY from `main`.** `railway up --detach` deploys whatever's in your local working tree — it doesn't care which branch is checked out. To prevent code going live before review, the norm is: merge the PR first, `git checkout main && git pull`, *then* `railway up --detach`. Don't deploy from a feature branch even when "it would be faster." This norm is the lightweight version of branch protection (parked on issue #37 LOW #9 pending GitHub Pro); the protocol is enforced by discipline, not by GitHub. (Also: don't use `railway redeploy` — restarts the old build.)

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
| Video OCR import | Done | `scripts/import_video_ocr.py` — maps al-municipal-meetings SQLite → docket PostgreSQL. **Deprecated after 2026-05-22 OCR fold** (PR #84); kept one cycle as schema-mapping reference. |
| Video OCR (folded into worker) | **LIVE** | PR #84 shipped 2026-05-22 (merge `6ca584b`). New `src/docket/analysis/ocr/` subpackage ported from al-muni: classifier, header, layout, ocr, sequence, pipeline, frame_io, rosters, _models. New `docket.services.video_ocr` orchestrates claim → scan → persist via the Claim pattern (CTE + `FOR UPDATE SKIP LOCKED`, atomic UPDATE-RETURNING, no row lock held during scan). New `video_ocr` cron task at 06:30 CT between `ingest_all` and `ai_items`; 3-attempt cap + 24h backoff + 60-day window. Migration 034 adds `processing_status.video_ocr_*` cols + partial unique index `idx_votes_ocr_unique` on `votes (meeting_id, video_timestamp, source='video_ocr')` so persistence is idempotent via ON CONFLICT. Roster built at runtime from `council_members` (half-open date range — see decisions). Admin force-rescan at `POST /admin/meetings/<id>/rescan-ocr`. Worker image now includes `ffmpeg` + `tesseract-ocr` + `opencv-python-headless` + `pytesseract`. Smoke against meeting 2232: 5 votes / 38 member_votes / 2 needs_review correctly mapped to `confidence='medium'` (the bug the old import path silently inherited as `'high'`). 71 new tests. Follow-ups: issue #85 (parameterize city slug + scan_interval), issue #86 (audit log for rescans). Spec: `docs/superpowers/specs/2026-05-21-fold-al-muni-ocr-design.md`. Plan: `docs/superpowers/plans/2026-05-21-fold-al-muni-ocr.md`. |
| Vote-to-item matching | Done | `analysis/vote_matcher.py` — timestamp matching (bisect, ported from al-municipal-meetings) + text heuristics (resolution number, item number, keyword overlap) |
| Council member linking | Done | Migration 007 (term dates), `scripts/backfill_member_vote_ids.py` (dynamic roster-based), query uses council_member_id FK |
| Landing page | Done | Contested votes, recent votes table, notable items (180-day limit), topic browse |
| `vote_agenda_items` join table | Done | Migration 009 — N:M shape with `association_type`, `provisional`, `is_manual`, `is_active` |
| Adoption sweep + strict re-parse | Done | `services/minutes_adoption.py` (sweep) + `analysis/vote_matcher.py:strict_reparse_meeting` — promotes provisional consent links to official after council adopts the minutes |
| N:M reader rewrite | Done | `services/query.py:list_votes(meeting_id, *, include_excerpts=False)` — 3-query pattern (votes + vote_agenda_items + member_votes) |
| `meeting_detail.html` N:M render | Done | Substantive vs consent-block branching, consent-block collapse, provisional/adopted pills |
| Council member rail with linked items | Done | `rail_member.html` — shows what each vote was about, with source-document deep links |
| Editorial design pass on remaining templates | Done | meetings list, topics index, topic detail, search, council pages |
| AI summaries + scoring | Done | `src/docket/ai/` — Haiku item summaries, Sonnet meeting executive summaries, two-phase lifecycle keyed off `minutes_adopted_at`, `ai_runs` cost telemetry, async batch worker + CLI (`python -m docket.ai.cli`). **Live on Railway as of 2026-05-02.** Item prompt v2 (procedural-skip), meeting prompt v2 (distinctive-vs-routine split at sig=6). 240 tests. |
| Cron worker (T27) | Done | `src/docket/worker/` — APScheduler `BlockingScheduler` running 10 daily/weekly/monthly tasks (ingest, AI items/meetings, vote matching, weekly empty-agenda repair, badge processing, calibration report, batch result polling, backfill ratio MV refresh, monthly analytics prune) with Healthchecks.io heartbeats per task. Multi-city by default; per-city ingest failures isolated. **Live on Railway `worker` service as of 2026-05-04.** Runbook at `docs/runbooks/cron-worker.md`. 36+ tests. |
| Impact-First Refactor — Phase 1 | Done | Migration 013 (10 new tables, 16 indexes, mv_badge_volume_monthly, 11 priority_badge_templates, BHM mayoral_terms, agenda_items v3 columns) + Wave 0 non-LLM classifier (`src/docket/ai/wave0.py`, `_priority.py`). Sets `data_quality`, `data_debt_priority`, `processing_status` on every item via Stage 0a (data-quality gate with Big Fish Override + title fallback for Granicus adapter shape) and Stage 0b (Alabama-context procedural regex). **Live on Railway as of 2026-05-07.** Final Wave 0 distribution on 57,553 items: 37,475 pending (65%), 16,169 data_quality_skipped (28%), 3,909 procedural_skipped (7%). 61 tests. Tag: `refactor-impact-first-phase-1-shipped`. Spec: `docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md`. |
| Impact-First Refactor — Phase 2 | **LIVE** | v3 pipeline (Stage 1 extraction + Stage 2 Smart Brevity rewrite + Stage 2.5 score floors + reconcile + atomic-commit-with-badges), 7 process badges + 4 BHM policy badges, Smart Brevity Card UI (6 variants), category landing pages, admin views, backfill driver, atomic per-item `process_item()` orchestrator. Both feature flags ON in production: `IMPACT_FIRST_ENABLED=true` on `worker` (v3 pipeline writes), `SMART_BREVITY_UI=true` on `docket-web` (citizen rendering). |
| Impact-First Refactor — Phase 3 | **In progress** | Backfill execution via Anthropic Batches API. As of 2026-05-12 prod has 652 v3-`completed` items vs. 36,601 `pending` — backfill is running through the eligible queue. Plan at `docs/superpowers/plans/2026-05-06-impact-first-refactor-phase-3.md`. |
| Impact-First Refactor — Phase 4 | Not built | Cleanup + Migration 014 (drop legacy `summary` column once all completed items are at v3). Plan: `docs/superpowers/plans/2026-05-06-impact-first-refactor-phase-4.md`. |
| Refactor #2 — Conservative policy badges | **Done** | `agenda_item_badges.status` (applied/flagged/rejected, migration 021) + admin review queue at `/admin/badge-review` + conservative writer that gates `applied` on deterministic backing + Section E backfill. LLM-only suggestions land `status='flagged'` (admin triage); deterministic-backed badges go `applied`. **Live on Railway as of 2026-05-12.** 65 LLM-only policy badges in the admin queue (53 property_recovery, 5 blight, 4 public_safety_tech_privacy, 3 housing_stability). PRs #16/#17/#18/#19/#21. Spec: `docs/superpowers/plans/2026-05-11-conservative-policy-badges.md`. |
| `processing_status='withdrawn'` (refactor #2 follow-up) | **Done** | Migration 023 added `'withdrawn'` to the enum so council-withdrawn/deferred/postponed items aren't lumped under `procedural_skipped`. `is_withdrawn_or_deferred()` in `wave0.py` runs before `is_procedural()`. 332 prod rows reclassified via a narrow UPDATE. PR #21. |
| Editorial coverage v1 | Done | Migration 027, notes + citations attached to items/meetings/members/badges, item_detail block + 6-surface chips, /coverage/ listing + RSS + permalinks. v1.1+ pairs (meeting/member/badge blocks + chips) follow as paired ships. |
| Analytics (Umami) | Done | Pageviews + 2 custom events (outbound_source_click, search_submit) in the `umami` database on the existing Railway Postgres instance. Read-only access via `umami_reader` role (credentials in `~/.docket-pub.env.local` as `UMAMI_READER_URL`). Query only `v_*` views — never raw tables. See `docs/analytics-queries.md` + `docs/runbooks/analytics.md`. |
| Item-centric navigation + anchor fix | **LIVE** | PR #64 shipped 2026-05-17 (commit `b88a2d3`). Citizen drilldown now routes through `public.item_detail` instead of `meeting_detail#item-N` (cards, Notable Items, member sponsored items). New `partials/_vote_result_block.html` renders prevailing vote + collapsed history + branched no-vote copy (`processing_status` with NULL fallback). `meeting_detail.html` now actually emits `id="item-N"` and `id="vote-N"` (retroactively fixes silent dead-link bug across RSS / admin / member pages); `layout.css` adds `scroll-margin-top: 80px` under the sticky masthead. `query.get_vote_for_item(item_id) -> ItemVoteData | None` resolves prevailing via `is_manual DESC, meeting_date DESC, association_type CASE, votes.id DESC` (is_active filter). `partials/pagination_controls.html` added; search + topic_detail get prev/next via `len == per_page` heuristic. Admin paths + RSS GUIDs deliberately kept on `meeting_detail`. Follow-ups: issue #66 (pagination empty-Next polish), issue #67 (anchor-fix announcement reference). 34 new tests (11 service + 16 vote-block + 7 pagination). |
| Granicus upcoming-meeting support | **LIVE** | PRs #61 + #65 shipped 2026-05-17 (merges `9c98800` + `e8a02d8`). Closes the 3-10 day pre-recording blind spot — docket.pub now surfaces BHM agendas the Friday before each Tuesday meeting with full item-level detail. **PR #61:** `GranicusAdapter.list_meetings` reads both `#upcoming` and `#archive` tables; upcoming meetings get namespaced `external_id="event-{event_id}"`. New `_extract_event_id`, `_agenda_url_by_event_id`, `_parse_upcoming_row`, `_parse_publisher_page` seam. `normalize_title` helper in `adapters/_helpers.py` strips cancellation suffixes for cross-row matching. Reconciliation in `services/ingest.py:_try_upgrade_event_row` upgrades `event-N` → `clip_id` in place on transition via dual-tier match on `(muni, date, normalize_title(title))` — refuses to guess on ambiguous candidates. Safety guards prevent `processing_status.agenda_items_scraped=TRUE` lockout. **PR #65:** new `analysis/agenda_parser.py` parses BHM agenda PDFs (regex on `(CONSENT(\(ph\))?\s+)?ITEM N.`, sponsor from `(Submitted by ...)`, page-header stripping). `fetch_agenda_items` branches by external_id shape — event-* downloads + parses the AgendaViewer PDF; clip-id stays on MediaPlayer. New `_backfill_video_timestamps` runs on `already_scraped=TRUE` clip-id meetings: idempotent, fetches MediaPlayer index-points, extracts `ITEM N` from titles, UPDATEs `video_timestamp_seconds` by `item_number` match — preserves AI summaries, only timestamp column touched. Live: 5/19 BHM meeting renders 102 items (5 regular + 97 consent). Follow-ups: issue #62 (orphan event-* row cleanup in `repair_empty_agendas`), issue #63 (`meetings_reconciled` count in `IngestResult`). 47 new tests. Spec: `docs/superpowers/specs/2026-05-16-granicus-upcoming-meetings-blind-spot.md`. |
| Upcoming-meeting flagging (chip + Vote Result branch) | **LIVE** | PR #68 shipped 2026-05-17 (commit `ceb9dfc`). Surfaces upcoming meetings (driven by PR #65's parsing) to the citizen UI so 100+ vote-less items don't read as data-missing. `.meeting-card__upcoming` badge on `partials/meeting_card.html`, `.card-upcoming-chip` in `partials/_card_shell.html` meta-line (gated by `show_meeting_context`), `chip is-warn` upcoming badge in `meeting_detail.html` hero eyebrow, and a new top-priority branch in `partials/_vote_result_block.html`'s no-vote section that says "This meeting hasn't happened yet. Vote results will appear here after the council meets on {date}." instead of the misleading "we couldn't match" copy. Driver: a per-request `today` Jinja context processor in `web/__init__.py`, anchored to `America/Chicago` (NOT server UTC — naive `date.today()` would flip mid-evening at 7pm CT during a live council meeting). All template call sites guard with `{% if today is defined and ... %}` so standalone test apps render no-op rather than UndefinedError. 8 new tests covering future/past/today-meeting permutations on the chip and the Vote Result branch. |
| Upcoming-meeting forward voice (Layer 1 + 2) | **LIVE** | Two-layer ship 2026-05-18 covering body text on upcoming meetings (companion to PR #68's chip work). **Layer 1** (PR #71 + hot-fix #74, merges `40e1e2c` + `042fa23`): template-level gates suppress completed-action AI text on upcoming meetings. Hero exec summary swaps to an "Agenda published" notice; consent blurb flips "Items passed" → "Items expected to pass"; per-card `headline`/`why_it_matters` fall back to raw `item.title`. Hot-fix #74 lifted `m.meeting_date` into `query.list_agenda_items` so the gate fires on cards rendered via `meeting_detail.html`. **Layer 2** (PR #75 + hot-fix #76 + hot-fix #77, merges `b180bdb` + `19265ab` + `9683301`): migration 031 added `agenda_items.ai_rewrite_voice` + `meetings.executive_summary_voice` columns; new `SYSTEM_PROMPT_UPCOMING` (Haiku) + `MEETING_SYSTEM_UPCOMING` (Sonnet) with forbidden-verb guardrails (`approved`, `passed`, `enacted`, `adopted`, `awarded`, `decided`, `ratified`); `select_item_voice` (rewrite.py) + `select_meeting_voice` (client.py) pick the variant at queue time keyed off `meeting.meeting_date >= today` (Chicago-anchored); voice persisted on Phase C UPDATE and `write_meeting_result`. Hot-fix #76 lifted `m.meeting_date` in `claim_items_v3_sql` (second of two read paths needing it, mirrors #74). Hot-fix #77 bumped `ITEM_REWRITE_PROMPT_UPCOMING_VERSION` + `MEETING_PROMPT_UPCOMING_VERSION` from 1 to 100 so they pass the `smart_brevity_card.html` dispatcher's `ai_rewrite_version >= 3` gate — **two parallel sequences now**: 4, 5, 6… for completed; 100, 101, 102… for upcoming. Layer 1 template gates revised to render forward-voice text when `ai_rewrite_voice='upcoming'` (suppressing only completed-voice text on upcoming meetings). Verified live on `https://docket.pub/al/birmingham/meetings/2232/`: 101 forward-voice item cards + Sonnet exec summary opening "The council will consider…". 34 new tests across both layers. **Outstanding follow-ups:** Task 11 (daily 04:45 CT `recast_post_meeting_ai` cron) not yet shipped — post-meeting items + summary will stay in upcoming voice until manually re-queued or cron lands. Spec: `docs/superpowers/specs/2026-05-18-upcoming-meeting-forward-voice-design.md`. Plan: `docs/superpowers/plans/2026-05-18-upcoming-meeting-forward-voice.md`. Reviewer follow-ups: #72 (notice phrasing), #73 (empty upcoming `<section>`). |
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
17. ~~Cron worker (T27)~~ — DONE (`src/docket/worker/` package, APScheduler on Railway `worker` service, 10 scheduled tasks, Healthchecks.io heartbeats, runbook)
18. Astro frontend evaluation — DEFERRED

### Key decisions to preserve

- **PostgreSQL from day 1** — no SQLite fallback
- **AI summaries + scoring:** items use Haiku 4.5, meetings use Sonnet 4.6. Two-phase meeting lifecycle keyed off `minutes_adopted_at` (provisional → adopted overwrites the executive summary). NULL `topic` renders as `"Uncategorized"` in prompts (never the literal `"None"`). Daily budget gate via `AI_DAILY_BUDGET_USD`; bumping `ITEM_PROMPT_VERSION` re-cascades both stages automatically. Worker writes per-row using `SELECT FOR UPDATE SKIP LOCKED` so multiple instances are safe.
- **Procedural items (item prompt v2):** Roll Call, Pledge, Invocation, "Minutes Not Ready" notices etc. get `is_substantive=false`, null scores, empty summary, and empty rationales. Title is the source of truth — a paraphrase would be noise. Template renders nothing extra for these.
- **Distinctive vs routine in meeting summaries (meeting prompt v2):** worker pre-classifies items by `significance_score` before feeding Sonnet. Sig ≥ 6 → distinctive, rendered in full and Sonnet leads with them. Sig < 6 → routine, grouped by topic with counts ("33 demolitions, 18 public_safety, 12 contracts") so Sonnet treats the cluster as one closing background sentence at most. Without this split, recurring abatements/demolitions dominated the framing.
- **Schema length caps:** rationales 1500 chars, item summaries 400 chars, executive summaries 1500 chars. Original 600/800 caps were rejecting Haiku/Sonnet's longer-but-correct outputs.
- **Cost expectation:** ~$0.0026/item (Haiku, with cache), ~$0.0085/meeting (Sonnet). 57K item backfill ≈ $140, ~14 days at default $10/day cap.
- **Local CLI runs against prod DB:** use `DATABASE_URL=$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-) ANTHROPIC_API_KEY=$(railway variables --service docket-web --kv | grep '^ANTHROPIC_API_KEY=' | cut -d= -f2-) venv/bin/python -m docket.ai.cli ...`. The internal `postgres.railway.internal` hostname only resolves inside Railway's VPC.
- **Two scoring dimensions:** significance (0-10) + consent placement (0-10)
- **Dollar tiers:** green <$50K, yellow $50-250K, orange $250K-1M, red >$1M
- **Source overlap:** video OCR + official minutes coexist, flag discrepancies only
- **Council rosters:** scrape council pages, don't manually seed
- **Search:** PostgreSQL FTS (tsvector/tsquery), not a separate engine
- **Data Honesty:** inline badges + footer attribution + discrepancy flags
- **Silent Break alerts:** dashboard + email notifications
- **Deployment:** Railway (live), gunicorn, production cookies, Procfile
- **Vote sources:** Minutes PDF (~9,934 minutes_text votes across 788 meetings), video OCR (77 votes, Jan–Apr 2026). Consent-block votes get 1:N coverage (one vote → many items), and that's the dominant link source — **33,303 active links** across Birmingham post-backfill (21,695 consent_block_named + 10,688 consent_block_default + 606 consent_enumerated + 162 resolution_number + 77 timestamp + 57 text_similarity + 18 item_number). 32,383 are provisional, 920 are official; 96 meetings have `minutes_adopted_at` set. Vote-level match rate is 10.7% (1,067 of 9,934) — the rest are substantive votes whose minutes don't reference a resolution/item number or carry strong title-keyword overlap, a known data limitation.
- **Vote matching:** Timestamp proximity for OCR votes (bisect, ported from al-municipal-meetings), text heuristics for minutes votes (resolution number, item number, keyword overlap). Each vote is first classified substantive vs consent_block; substantive runs 3-tier matching, consent_block runs named-callout + default-fill passes.
- **N:M vote↔agenda links:** `vote_agenda_items` join table — one consent vote can link to many items. Named callouts get `match_confidence=1.0`, default consent fill gets `0.8`.
- **Provisional → Official lifecycle:** `consent_named` and `consent_implicit` links insert with `provisional=TRUE`. They flip to `FALSE` when council adopts the minutes (sweep_adoptions sets `meetings.minutes_adopted_at`, then strict re-parse promotes the links). Substantive (`explicit`) links insert with `provisional=FALSE` directly.
- **Manual shield:** `is_manual=TRUE` on a `vote_agenda_items` row protects it from automated overwrite — enforced both by an app-level pre-check in `_upsert_link` and a DB-level `WHERE is_manual = FALSE` predicate on every UPDATE.
- **Active vs ghost links:** `is_active=FALSE` marks links to items that were on the consent agenda at meeting time but pulled out and voted separately. Kept for audit; hidden from the default reader (`Vote.active_links`).
- **Strict re-parse safety:** when the enumerated consent list resolves to zero target agenda items, `strict_reparse_meeting` aborts (does NOT mass-deactivate). Protects against PDF/OCR glitches that could otherwise wipe every active consent link in the meeting.
- **Dual-trigger contract:** `strict_reparse_meeting` fires from both the matcher (when matching a meeting whose `minutes_adopted_at` is already non-NULL) and the sweep (when newly flipping a meeting NULL → adopted). Order independent — either path lands the same end state.
- **Video OCR (folded 2026-05-22):** Pipeline now lives natively in `docket.analysis.ocr.*` (PR #84). al-muni stays alive as a research sandbox; full repo absorption (path B) is deferred. OCR runs as the `video_ocr` cron at 06:30 CT via the **Claim pattern** — atomic `UPDATE ... RETURNING` fed by a CTE with `FOR UPDATE SKIP LOCKED`, attempts counter bumped at claim time so a crash mid-scan still consumes one attempt, 24h backoff and 3-attempt cap and 60-day window keep retries bounded. Roster built at runtime from `council_members` via `build_roster_for_meeting(meeting_id)` with **half-open date range** `>= term_start AND < term_end + 1 day` (avoids the BETWEEN-inclusivity foot-gun where one member's `term_end` and the successor's `term_start` are the same date). `DetectedVote` / `MemberVote` live at `docket.analysis.ocr._models` (NOT `docket.models` — would collide with docket's existing N:M `Vote`/`MemberVote` shape). Persistence at `docket.services.video_ocr.persist_detected_votes` writes with **idempotency via the partial unique index** `idx_votes_ocr_unique (meeting_id, video_timestamp, source) WHERE source='video_ocr'` + `ON CONFLICT DO NOTHING`. **`needs_review=True` maps to `confidence='medium'`** — the column default `'high'` would otherwise silently mislabel cross-verification failures on the citizen UI's confidence badges (the smoke against meeting 2232 revealed 2 of 5 votes had this flag, which the old `scripts/import_video_ocr.py` path was silently inheriting as `'high'`). Admin force-rescan at `POST /admin/meetings/<id>/rescan-ocr` is required because ON CONFLICT is timestamp-stable: a future OCR fix that picks different terminal frames needs the explicit DELETE-first reset, not just a re-run.
- **OCR module renames during the port:** `muni.analysis.vote_classifier` → `docket.analysis.ocr.classifier` (etc., dropping the `vote_` prefix throughout). `scan_meeting_for_votes` now **requires** an explicit `layout=` kwarg — raises ValueError if None (no stale hardcoded fallback like al-muni's `get_birmingham_layout`). `MatchedVote` was NOT ported — docket uses the N:M `vote_agenda_items` join table for matching, not a single-FK shape on the vote row.
- **OCR worker resource ceiling:** ffmpeg + tesseract + opencv push the worker image RSS noticeably during a scan (al-muni empirical: peak ~600 MB Python + ~150 MB ffmpeg subprocess). Combined with the worker daemon's idle ~954 MB, an active OCR task pushes service memory to ~1.7 GB. If the Railway worker tier headroom shrinks, options are: bump tier, drop `LIMIT 5` in the loop to `LIMIT 1` per cron tick, or pull OCR into its own service (deferred B2 split).
- **Council member linking:** Dynamic name→ID resolution using roster + term dates, not hardcoded maps
- **Deploy:** `railway up --detach` (NOT `railway redeploy` which restarts old build without new code)
- **Minutes parser:** Must handle curly apostrophes (U+2019) in name regex — O'Quinn fix. Pre-vote window is 1500 chars (was 500, last 200) so the resolution body is captured into `votes.raw_text`.
- **Cron worker:** Railway `worker` service (separate from `docket-web`, same image) runs `python -m docket.worker.scheduler` 24/7. Eleven tasks staggered through the day in `America/Chicago`: `prune_analytics` day=1 04:00 (monthly), `refresh_backfill_ratio_mv` 04:30, `repair_empty_agendas` Mon 05:00, `ingest_all` 06:00, `video_ocr` 06:30, `ai_items` 07:00, `ai_meetings` 08:00, `vote_matching` 09:00, `process_badges` 09:30, `calibration_report` 11:00, `process_batches` :00 and :30 (every 30 min). Each pings Healthchecks.io start/success/fail with traceback body on exception (UUIDs in env vars; `prune_analytics` and `calibration_report` are silent-by-design — local-impact failure modes only — task gracefully no-ops the ping when env var is missing). `BudgetExceededError` swallowed in AI tasks — expected behavior, not failure. Per-city ingest failures isolated (Birmingham failing won't block Mobile). Manual triggers via `railway ssh --service worker` then `python -m docket.worker.scheduler --run-once <task>` — NOT `railway run` (which executes locally where `postgres.railway.internal` doesn't resolve). Runbook at `docs/runbooks/cron-worker.md`.
- **Procfile multi-process gotcha:** Railway only runs the `web:` line by default. The `worker:` line in Procfile is informational; the actual worker is a separate Railway service whose Custom Start Command overrides Procfile. One-time setup via dashboard (Empty Service → Custom Start Command → copy env vars from `docket-web`). Re-deploy with `railway up --service worker --detach` from `~/docket-pub`.
- **Custom domain (live 2026-05-04):** apex `docket.pub` is on Railway with auto-provisioned Let's Encrypt cert. DNS at Namecheap: `CNAME @ → zu815cqb.up.railway.app` + `TXT _railway-verify=...`. HSTS shipped (1 year, no `includeSubDomains` yet). **`www.docket.pub` is NOT yet on Railway** — currently a Namecheap URL Redirect Record (HTTP-only). Pickup: delete the URL Redirect, add `www.docket.pub` as second Railway custom domain, replace with the CNAME Railway provides, add Flask `before_request` redirect from `www.docket.pub` to apex, then tighten HSTS to `includeSubDomains` (and consider `preload`).
- **HSTS header:** `Strict-Transport-Security: max-age=31536000` set in `web/__init__.py` `after_request` when `FLASK_ENV != "development"`. `includeSubDomains` intentionally omitted until www is also Railway-served (otherwise browsers would force-upgrade www to HTTPS and fail).
- **Wave 0 title-fallback rule:** `evaluate_data_quality` in `src/docket/ai/wave0.py` treats `title` as the body when `description` and `raw_text` are both empty AND title is >= 120 chars. This handles the Granicus adapter (Birmingham) shape where the full agenda body sits in `title` and `description` is NULL — without this rule, Wave 0 misclassifies 90% of the Birmingham archive as `no_agenda_text`. Fix landed in `9332811` after the first Wave 0 production run on 2026-05-06 caught the bug.
- **DO NOT run `python -m docket.ai.cli --wave 0` against Railway prod on a small DB volume.** The per-row UPDATE pattern across ~57K items generates ~360MB of WAL — overflowed the 500MB Railway Postgres volume on 2026-05-12 and crash-looped Postgres (`could not write to file pg_wal/xlogtemp.35: No space left on device`). Volume was resized to 1GB to recover. For bulk reclassification, use a single targeted SQL UPDATE scoped via WHERE clause (~3MB WAL for hundreds of rows). If a full Wave 0 sweep is truly needed, resize the volume to ≥ 5GB first.
- **Impact-First Refactor pipeline directionality:** The v3 AI pipeline is what's currently live in prod (both `IMPACT_FIRST_ENABLED=true` and `SMART_BREVITY_UI=true` set). v3 replaces the legacy `summary` column with structured `extracted_facts` (JSONB) + `headline` + `why_it_matters` and runs 4 stages (Wave 0 → Stage 1 extraction → Stage 2 rewrite → Stage 2.5 reconcile). Phase 3 backfill is still working through the ~37K eligible items (~652 completed as of 2026-05-12). Migration 014 (Phase 4, not yet built) will drop the legacy `summary` column once every completed item is at v3. Spec: `docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md`.
- **Conservative policy badges (refactor #2):** Live on Railway as of 2026-05-12. `agenda_item_badges.status` column gates citizen visibility — `applied` (visible) when there's deterministic backing (keyword / action-type / topic), `flagged` (admin review only) when only Haiku suggested it, `rejected` (archived) after admin reject. Confidence values: 1.0 for both signals, 0.8 for deterministic-only, 0.4 for LLM-only. `decide_status_and_confidence()` in `src/docket/ai/badges_policy.py` is the single source of truth. Admin queue: `/admin/badge-review`. Plan: `docs/superpowers/plans/2026-05-11-conservative-policy-badges.md`.
- **`processing_status='withdrawn'` is its own bucket** (not `procedural_skipped`). Items the council removes from the agenda — title contains `WITHDRAWN` / `DEFERRED` / `POSTPONED` after the item-number prefix — go to `'withdrawn'` so the procedural-skipped queue isn't polluted by them. `is_withdrawn_or_deferred()` in `src/docket/ai/wave0.py` catches the `<prefix> ITEM N. <marker>` shape; the alternate `WITHDRAWN <prefix> ITEM N.` shape is a known follow-up. Migration 023.
- **Editorial coverage:** v1 schema (migration 027) has snapshot-on-publish bylines, normalized citation table via `outlets` controlled vocab, polymorphic N:M subjects with ON UPDATE CASCADE on badge slug. v1 surfaces only item_detail + cross-surface item-card chips; meeting/member/badge blocks pair with their chips in v1.1+. Automation slots (`status='proposed'`, `source='ai_proposal|press_scraper'`) are reserved but unused in v1. Spec: `docs/superpowers/specs/2026-05-13-editorial-coverage-design.md`.
- **Analytics (Umami):** Pageviews + 2 custom events live in the `umami` database on the existing Railway Postgres instance. Query via the read-only `umami_reader` role with credentials in `~/.docket-pub.env.local` (set `UMAMI_READER_URL`). See `docs/analytics-queries.md` for view schemas and common query patterns. **Never query raw Umami tables (`website_event`, `event_data`, `session`) — only the `v_*` views.** The view layer is what absorbs Umami schema changes. Schema fixture at `tests/fixtures/umami_schema_v3.sql`; regenerate only on Umami version bumps (procedure in `docs/runbooks/analytics.md`).

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

- [thinkdarrell/docket-pub](https://github.com/thinkdarrell/docket-pub) — this repo (single canonical)
- [thinkdarrell/docket-pub-site](https://github.com/thinkdarrell/docket-pub-site) — public landing page (separate)
- [thinkdarrell/docket-pub-archived](https://github.com/thinkdarrell/docket-pub-archived) — abandoned skeleton from before consolidation; read-only
- [thinkdarrell/al-municipal-meetings](https://github.com/thinkdarrell/al-municipal-meetings) — Birmingham pipeline, code ported from here
