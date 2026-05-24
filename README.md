# Docket.pub

**Municipal meeting intelligence platform for Alabama cities.**

Docket.pub automates the collection, parsing, enrichment, and indexing of public meeting records from local governments. The goal is civic transparency: make every agenda item, vote, and dollar amount searchable — and link every data point back to its original source on the city's website.

**Domain:** live at [https://docket.pub](https://docket.pub) (apex, Let's Encrypt via Railway) | **Status:** Private Development | **Repo:** [`thinkdarrell/docket-pub`](https://github.com/thinkdarrell/docket-pub)

---

## What's Built

The full pipeline is live: scraping, enrichment, vote extraction (from both official minutes and video OCR), N:M vote-to-agenda-item matching with a provisional/adopted lifecycle, and an editorial-design frontend. Deployed to Railway.

**N:M vote-to-agenda-item matching.** Every vote can link to one substantive agenda item or many consent-block items. Each vote is classified as substantive (1:1) or consent block (1:N); substantive matches run the existing three-tier heuristics (resolution number, item number, keyword overlap), while consent matches link to all `is_consent=TRUE` items for the meeting with named callouts upgraded to confidence 1.0. A strict re-parse promotes provisional consent links to official after council formally adopts the minutes. ~36,000 active links across Birmingham as of the most recent backfill.

**AI summaries + scoring (v3 pipeline live in production).** Per-item structured outputs — `extracted_facts` (JSONB: counterparty, funding_source, procurement_method, action_type, location, next_steps), `headline`, `why_it_matters`, and 0–10 significance + consent-placement scores — via Haiku 4.5 (Stage 1 extraction + Stage 2 Smart Brevity rewrite + Stage 2.5 reconcile). Per-meeting executive summaries via Sonnet 4.6 with two-phase lifecycle (provisional → adopted on `minutes_adopted_at`). Async batch worker (`python -m docket.ai.cli`) decoupled from ingest; `SELECT FOR UPDATE SKIP LOCKED` claim semantics, per-row commits, daily budget cap. Both feature flags `IMPACT_FIRST_ENABLED=true` (worker writes v3) and `SMART_BREVITY_UI=true` (citizen rendering) are live as of 2026-05. Spec at `docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md`.

**Conservative policy badges (refactor #2, live 2026-05-12).** Every `agenda_item_badges` row carries a `status` field — `applied` (citizen-visible, deterministic-backed), `flagged` (admin review only, LLM-suggested without deterministic backing), or `rejected` (archived). Admin queue at `/admin/badge-review` for approve/reject with audit trail. Reader queries filter `status='applied'`; the materialized view `mv_badge_volume_monthly` does the same. Stops a previously observed 71% over-tag rate on `public_safety_tech_privacy`. Spec at `docs/superpowers/plans/2026-05-11-conservative-policy-badges.md`.

**`processing_status='withdrawn'` (refactor #2 follow-up).** Items the council removes from the agenda (WITHDRAWN/DEFERRED/POSTPONED titles) get their own status bucket via migration 023, distinct from `procedural_skipped` (Roll Call / Pledge / etc.). `is_withdrawn_or_deferred()` in `wave0.py` routes them at classify time.

**Cron worker (live in production since 2026-05-04).** Railway `worker` service runs APScheduler with eleven scheduled tasks in `America/Chicago` — five from the original 2026-05-04 ship, six added through Phase 2/3: `prune_analytics` (day 1, 04:00, monthly), `refresh_backfill_ratio_mv` (04:30 daily), `repair_empty_agendas` (Mon 05:00), `ingest_all` (06:00), `video_ocr` (06:30), `ai_items` (07:00), `ai_meetings` (08:00), `vote_matching` (09:00), `process_badges` (09:30), `calibration_report` (11:00), and `process_batches` (every :00 and :30, polling Anthropic Batches API). Each task pings Healthchecks.io start/success/fail with the traceback as the alert body — two tasks are silent-by-design (`prune_analytics`, `calibration_report` — local-impact failure modes only). Manual triggers via `railway ssh --service worker` then `python -m docket.worker.scheduler --run-once <task>`. Spec at `docs/superpowers/specs/2026-05-04-cron-worker-design.md`; runbook at `docs/runbooks/cron-worker.md`.

**Prompt v2 design choices (validated in pilot):**
- Procedural items (Roll Call, Pledge, Invocation, "minutes not ready", etc.) get `is_substantive=false` with empty summary + empty rationales — title is self-explanatory and a paraphrase would be noise. Template renders nothing extra for these items.
- Meeting summaries split items into **distinctive** (sig ≥ 6) and **routine** (sig < 6) before feeding Sonnet. Distinctive items render in full and Sonnet leads with them. Routine items are grouped by topic with counts ("33 demolition orders, 18 public_safety items, 12 contracts") and Sonnet treats them as one closing background sentence at most. Without this split, Sonnet's framing was dominated by recurring abatement / demolition / weed-clearance volume, hiding the distinctive policy decisions citizens want to know about.

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
6. **Flask App** — 70+ routes (23 public + 48 admin), editorial design, HTMX source rail
7. **Council Rosters** — 26 members seeded across 4 cities, admin UI for management
8. **Admin Auth** — Session-based login on all `/admin/*` routes
9. **Railway Deployment** — Live at `docket-web-production-6110.up.railway.app`
10. **Minutes Vote Parser** — PDF extraction of attendance + votes from Birmingham minutes (870 meetings, ~6,800 votes)
11. **Video OCR** — Imported Jan–Apr 2026 votes from al-municipal-meetings, ran fresh OCR for April meetings (77 votes)
12. **Vote-to-Item Matching** — Timestamp proximity (video OCR) + text heuristics (resolution number, item number, keyword overlap). Ported from al-municipal-meetings.
13. **Council Member Linking** — member_votes linked to council_members via FK, with term date awareness for old/new council transitions
14. **Landing Page** — Contested votes, recent votes table, notable items (180-day recency), topic browse
15. **Vote-to-Item Matching N:M Redesign** — `vote_agenda_items` join table (migration 009), substantive + consent-block classifier and matchers, strict re-parse, dual-trigger adoption lifecycle
16. **Editorial Design Pass** — meetings list, topics index, topic detail, search, council pages all migrated to the editorial card design
17. **AI Summaries + Scoring** — `src/docket/ai/` package (migration 012, branch `feat/ai-summaries-scoring`). Item summaries via Haiku 4.5, meeting executive summaries via Sonnet 4.6, two-phase lifecycle, async batch worker + CLI, admin dashboard at `/admin/ai`, Pydantic-validated structured output, prompt caching. **Live on Railway prod** as of 2026-05-02. ITEM_PROMPT_VERSION=2 (procedural-skip), MEETING_PROMPT_VERSION=2 (distinctive-vs-routine).
18. **Cron Worker (T27)** — `src/docket/worker/` APScheduler service running 11 daily/weekly/monthly tasks (ingest_all, video_ocr, ai_items, ai_meetings, vote_matching, repair_empty_agendas, process_badges, calibration_report, process_batches, refresh_backfill_ratio_mv, prune_analytics) with Healthchecks.io heartbeats per task (9 monitored, 2 silent-by-design). **Live on Railway `worker` service since 2026-05-04.** Runbook at `docs/runbooks/cron-worker.md`.
19. **Impact-First Refactor — Phase 1** — Migration 013 (10 new tables, 16 indexes, `mv_badge_volume_monthly` materialized view, 11 priority badge templates, BHM mayoral terms, agenda_items v3 columns) + Wave 0 non-LLM classifier in `src/docket/ai/wave0.py`. Sets `data_quality`, `data_debt_priority`, `processing_status` on every item via Stage 0a (data-quality gate with title fallback for Granicus shape) and Stage 0b (Alabama-context procedural regex). **Live on Railway as of 2026-05-07.** Final Wave 0 distribution on 57,553 items: 65% pending, 28% data_quality_skipped, 7% procedural_skipped. Tag: `refactor-impact-first-phase-1-shipped`.
20. **Impact-First Refactor — Phase 2 (live in production)** — v3 pipeline (Stage 1 extraction + Stage 2 Smart Brevity rewrite + Stage 2.5 score floors + reconcile + atomic-commit-with-badges), 7 process badges + 4 BHM policy badges, Smart Brevity Card UI (6 variants), category landing pages with SVG volume timeline + cross-filter HTMX dropdown, public data-debt page + RSS feeds, admin calibration dashboard, admin OCR queue + errors queue, atomic per-item `process_item()` orchestrator. Both feature flags ON in production: `IMPACT_FIRST_ENABLED=true` (worker) and `SMART_BREVITY_UI=true` (web).
21. **Impact-First Refactor — Phase 3 (in progress)** — Anthropic Batches API backfill working through ~37K eligible items. ~652 v3-completed as of 2026-05-12.
22. **Refactor #2 — Conservative policy badges (live 2026-05-12)** — `agenda_item_badges.status` (applied/flagged/rejected, migration 021) + admin review queue + Section E backfill (65 LLM-only rows flipped to `flagged`). PRs #16/#17/#18/#19/#21. New `processing_status='withdrawn'` (migration 023) + `is_withdrawn_or_deferred()` in Wave 0 (PR #21). Plan: `docs/superpowers/plans/2026-05-11-conservative-policy-badges.md`.
23. **Tests** — 1366+ passing (1 pre-existing env-dependent deselect). Unit + integration; live AI smoke tests gated on `ANTHROPIC_API_KEY`.

### What's Next

**Active: Impact-First Refactor Phase 3 (backfill execution)** — The v3 pipeline is live in prod and the Anthropic Batches API backfill is working through the eligible queue (~$100 estimated total over 7–14 days). Plan: `docs/superpowers/plans/2026-05-06-impact-first-refactor-phase-3.md`.

**Then Phase 4 (cleanup)** — Migration 014 drops the legacy `agenda_items.summary` column once all completed items are at v3. Plan: `docs/superpowers/plans/2026-05-06-impact-first-refactor-phase-4.md`.

**Refactor #2 follow-ups:**
- **Broaden the WITHDRAWN regex** in `is_withdrawn_or_deferred()` to also catch the marker-first shape `WITHDRAWN <prefix> ITEM N.` (~240 prod rows currently in `pending` use this shape and aren't yet caught).
- **Consent-text recovery** — 7,500 consent items live in `data_quality_skipped` with `no_agenda_text` because Birmingham's Granicus HTML treats consent block items as title-only references. The body lives in the post-meeting minutes PDF (already in `votes.raw_text`). A new ingest pipeline could cascade that text back into `agenda_items.description` and re-run Wave 0 → Stage 1/2. Needs design.

**Operational follow-ups (not blocking the above):**
- **Move `www.docket.pub` to Railway** — apex is live with HSTS; `www.docket.pub` still routes through a Namecheap URL Redirect Record (HTTP-only). Plan: delete the redirect, add `www.docket.pub` as a second Railway custom domain, swap to a CNAME, tighten HSTS to `includeSubDomains` (+ `preload`), Flask redirect from www → apex.
- **Per-claim citations + discrepancy-aware summaries** — AI feature; v1 uses source-bounded grounding only.
- **Council member rollups** — separate brainstorm.
- **Astro frontend evaluation** — considering migration from Flask/Jinja2+HTMX to Astro.
- **Manual link-correction admin UI** — the `is_manual` column on `vote_agenda_items` is ready; form/route deferred.
- **Freshness Checks** — Silent Break alerts when a city's data feed stops updating.
- **Source reconciliation** — compare video OCR vs official minutes when both exist.
- **CSRF protection on admin POST forms** — codebase-wide gap; `SESSION_COOKIE_SAMESITE = "Lax"` provides partial mitigation.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.10+ |
| Web Framework | Flask + HTMX |
| Database | PostgreSQL 18.3 on Railway (prod); PG 16 locally |
| Search | PostgreSQL full-text search (tsvector/tsquery with GIN indexes) |
| Containerization | Docker + docker-compose |
| Deployment | Railway (live at https://docket.pub) |

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
  RawMeeting / RawAgendaItem / RawVote   (protocol dataclasses — no DB knowledge)
       |
       v
  Enrichment Layer          (dollars, sponsors, topics, scoring stubs)
       |
       v
  Ingest Service            (upserts to PostgreSQL, tracks processing status)
       |
       v
  Vote Matcher              (classify each vote → substantive 1:1 OR consent block 1:N)
       |                     (writes to vote_agenda_items via _upsert_link with manual shield)
       v
  Strict Re-parse           (after adoption: promote provisional → official, deactivate ghosts)
       |
       v
  Query Service             (3-query reader: votes + vote_agenda_items + member_votes)
       |
       v
  Flask Routes / HTMX UI    (editorial design — meeting detail with consent collapse, rails with deep links)
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

Core schema in `src/docket/migrations/001_initial.py` (10 base tables); migration 013 adds 10 more for the v3 Impact-First refactor (`priority_badge_templates`, `priority_badges_config`, `agenda_item_badges`, `agenda_item_badges_audit`, `city_score_floor_overrides`, `ai_batches`, `ai_batch_items`, `mayoral_terms`, `ai_response_cache`, `processing_status_audit`) plus the `mv_badge_volume_monthly` materialized view. Migration 021 adds `agenda_item_badges.status`; migration 023 adds `'withdrawn'` to the processing-status enum.

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
agenda_url, minutes_url, video_url, source_url, minutes_adopted_at,
search_vector (TSVECTOR, auto-updated), created_at, updated_at
```
- `meeting_type`: `'council'` | `'work_session'` | `'planning'` | `'special'` | `'committee'` | `'board'` | `'other'`
- `source_url`: Always links back to the original page on the city's website
- `minutes_adopted_at`: TIMESTAMPTZ NULL until council formally adopts the minutes for this meeting at a later meeting; set by `services.minutes_adoption.sweep_adoptions`. Used to gate the strict re-parse that promotes provisional consent links to official, and to flip the AI meeting summary from `phase=provisional` to `phase=adopted`.
- `executive_summary`, `ai_metadata`, `ai_prompt_version`, `ai_generated_at`: AI-generated 2-3 sentence executive summary + metadata (phase, is_substantive, substantive_item_count, confidence, model) + prompt versioning. NULL until processed. Two-pass: provisional summary when items are processed; adopted summary overwrites after `minutes_adopted_at` is set.

#### `agenda_items`
Individual items on a meeting's agenda. This is the richest table.
```
-- v1/v2 columns:
id, meeting_id, external_id, item_number, title, description,
section, is_consent, sponsor, topic,
dollars_amount (NUMERIC 15,2), significance_score (REAL 0-10),
consent_placement_score (REAL 0-10),
video_timestamp_seconds (REAL),
search_vector (TSVECTOR, auto-updated),
summary, ai_metadata (JSONB), ai_prompt_version, ai_generated_at,
created_at,
-- v3 columns (migration 013):
extracted_facts (JSONB), headline, why_it_matters, source_anchor (JSONB),
data_quality (data_quality_enum), data_debt_priority (data_debt_priority_enum),
processing_status (processing_status_enum),
processing_attempts, last_error_at, last_error_message,
score_overrides (JSONB),
ai_extraction_version, ai_rewrite_version, ai_confidence,
backfill_session_id (UUID)
```
- `sponsor`: Extracted from "(Submitted by ...)" or "(sponsored by ...)" patterns. NULL if not found.
- `topic`: Keyword-classified topic slug. One of: `zoning`, `public_safety`, `public_works`, `budget`, `grants`, `contracts`, `legal`, `parks_culture`, `licensing`, `appointments`, `routine`. NULL if unclassified.
- `dollars_amount`: Extracted via regex. The **largest** dollar amount in the text. NULL if none found.
- `significance_score`: 0-10 scale. NULL on procedural items by design.
- `consent_placement_score`: 0-10 scale. NULL on procedural items by design.
- `is_consent`: Boolean flag — was this item on the consent agenda?
- `summary`, `ai_metadata`: legacy v2 outputs. Phase 4 / migration 014 drops `summary` once all completed items are at v3.
- `extracted_facts` (JSONB, v3): structured facts from Stage 1 — `counterparty`, `funding_source`, `procurement_method`, `action_type`, `location`, `next_steps`, etc.
- `headline`, `why_it_matters` (v3): Smart Brevity headline + why-it-matters one-liner from Stage 2. Length CHECKs: headline ≤ 80, why_it_matters ≤ 280 (migration 020).
- `source_anchor` (JSONB): grounding metadata linking the v3 outputs back to a specific span in the source document.
- `data_quality`: `ok` | `no_text_layer` | `no_agenda_text` | `empty` | `foreign_language`. Set by Wave 0 Stage 0a.
- `processing_status`: `pending` | `procedural_skipped` | `data_quality_skipped` | `extracted` | `rewritten` | `badged` | `completed` | `failed_retry` | `failed_permanent` | `cross_stage_conflict` | `withdrawn`. Tracks v3 pipeline progress.
- `score_overrides` (JSONB): admin escalations + Stage 2.5 floor triggers.

See `docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md` for the v3 design.

#### `votes`
Vote outcomes recorded at a meeting. Links to agenda items live in the `vote_agenda_items` join table; the legacy singular `agenda_item_id` / `match_method` / `match_confidence` columns were dropped in migration 011 after the N:M reader was verified live.
```
id, meeting_id, external_id, result,
yeas, nays, abstentions,
source, confidence, header_result, needs_review, review_reason,
video_timestamp, raw_text,
resolution_number, match_context,
created_at
```
- `result`: `'passed'` | `'failed'` | `'tabled'`
- `source`: `'video_ocr'` | `'minutes_text'` | `'api'` | `'manual'`
- `confidence`: `'high'` | `'medium'` | `'low'`
- `needs_review`: Flag for votes with extraction issues
- `raw_text`: Up-to-1500-char pre-vote window plus the vote block — preserved so the matcher and the strict re-parse can re-derive links without re-downloading the PDF.

#### `vote_agenda_items`
The N:M join table linking votes to agenda items. One substantive vote → one row; one consent-block vote → many rows.
```
id, vote_id, agenda_item_id,
association_type, match_method, match_confidence (REAL 0-1),
excerpt_context, provisional, is_manual, is_active,
created_at, updated_at
```
- `association_type`: `'explicit'` (substantive 1:1) | `'consent_named'` (consent block, item explicitly named in the vote text) | `'consent_implicit'` (consent block, inferred from the agenda's `is_consent` flag) | `'positional'` (reserved).
- `match_method`: Free-form text describing the heuristic that produced the link — `resolution_number`, `item_number`, `text_similarity`, `consent_block_named`, `consent_block_default`, `consent_enumerated`, `timestamp`. Free-form (not enum) for forward extensibility.
- `provisional`: `TRUE` for fresh consent links, `FALSE` for substantive (`explicit`) links and for consent links promoted by the strict re-parse after the council adopts the minutes.
- `is_manual`: A human edited this link — the automated matcher must not overwrite it. Enforced both at the app level (pre-check in `_upsert_link`) and the DB level (`WHERE is_manual = FALSE` on every UPDATE).
- `is_active`: `FALSE` marks "ghost" links — items that were on the consent agenda at meeting time but were pulled out and voted separately. Kept for audit, hidden by the default reader.

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
    executive_summary: str | None # 2-3 sentence AI summary (Sonnet 4.6)
    ai_metadata: dict | None      # phase, is_substantive, substantive_item_count, confidence, model
    ai_prompt_version: int | None
    ai_generated_at: datetime | None
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
    significance_score: float | None    # 0-10 (NULL on procedural items by design)
    consent_placement_score: float | None  # 0-10 (NULL on procedural items by design)
    summary: str | None                 # 1-2 sentence AI summary (Haiku 4.5)
    ai_metadata: dict | None            # rationales, confidence, is_substantive, model
    ai_prompt_version: int | None       # bump prompts.py version → re-cascades
    ai_generated_at: datetime | None
```

### Vote
```python
@dataclass(frozen=True)
class Vote:
    id: int
    meeting_id: int
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
    resolution_number: str | None = None
    video_timestamp: float | None = None
    agenda_links: list[AgendaItemLink] = field(default_factory=list)
    member_votes: list[MemberVote] = field(default_factory=list)

    # Convenience properties for templates:
    @property
    def active_links(self) -> list[AgendaItemLink]: ...      # links where is_active=True
    @property
    def is_consent_block(self) -> bool: ...                  # any active link is consent_*
    @property
    def has_provisional_links(self) -> bool: ...             # any active link is provisional
    @property
    def primary_link(self) -> AgendaItemLink | None: ...     # the single active link, if exactly one
    @property
    def excluded_links(self) -> list[AgendaItemLink]: ...    # is_active=False (ghost) links

@dataclass(frozen=True)
class AgendaItemLink:
    id: int
    agenda_item_id: int
    item_number: str | None
    title: str
    is_consent: bool
    association_type: str       # 'explicit' | 'consent_named' | 'consent_implicit' | 'positional'
    match_method: str | None
    match_confidence: float
    excerpt_context: str | None # populated only when list_votes(include_excerpts=True)
    provisional: bool
    is_manual: bool
    is_active: bool

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
| `list_votes(meeting_id, *, include_excerpts=False)` | `list[Vote]` | Votes with `agenda_links: list[AgendaItemLink]` and `member_votes` attached. Three round-trips per page (votes + vote_agenda_items + member_votes). Pass `include_excerpts=True` to populate `AgendaItemLink.excerpt_context` for views that need the source snippet. |
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

## AI Summaries + Scoring

Two scores reserved on every agenda item, populated by the `docket.ai` Haiku 4.5 worker:

- **Significance Score (0-10):** How impactful is this item to residents? A $16M road contract scores higher than approving meeting minutes.
- **Consent Placement Score (0-10):** Does this item belong on the consent agenda? High-dollar or controversial items on the consent agenda score low (suggesting they shouldn't be there).

**Procedural items** (motion to adjourn, approval of prior minutes) have `is_substantive=False` and both scores are NULL by design — the AI is instructed to refuse rather than guess. UI hides scores when NULL.

**Item summaries.** 1-2 sentence prose summary stored in `agenda_items.summary`. Rationales for both scores stored in `ai_metadata` JSONB.

**Meeting executive summaries.** 2-3 sentence summary stored in `meetings.executive_summary` via Sonnet 4.6. Two-phase: a *provisional* summary lands when all items are processed and minutes haven't been formally adopted; an *adopted* summary overwrites once `minutes_adopted_at` is set. Phase tracked in `ai_metadata.phase`.

**Operator interface.**
```bash
python -m docket.ai.cli --status                    # queue depth + recent runs + cost
python -m docket.ai.cli --dry-run --items --limit 5
python -m docket.ai.cli --items --limit 200
python -m docket.ai.cli --meetings --limit 50
python -m docket.ai.cli --force --meeting-id 42     # re-process a single meeting
```

**Cost telemetry.** `ai_runs` table records per-batch cost broken down by Anthropic's four billing dimensions (regular input, cache creation, cache read, output). Daily budget cap (`AI_DAILY_BUDGET_USD`, default $10) enforced before any API call; override with `--force-budget`.

**Versioning.** Bumping `ITEM_PROMPT_VERSION` or `MEETING_PROMPT_VERSION` constants in `src/docket/ai/prompts.py` re-cascades the affected stage automatically — items first, then meetings (gated on items being current). Git history of `prompts.py` is the audit trail.

Full design at `docs/superpowers/specs/2026-05-01-summaries-and-scoring-design.md`.

---

## Flask Routes

Counts are approximate — exact registration lives in `src/docket/web/public.py` and `src/docket/web/admin.py`. The list below highlights the citizen-facing surface; admin is enumerated below the public set.

### Public (~23 routes — primary surfaces)

```
GET  /                                  Homepage (cities, this week, upcoming)
GET  /al/<slug>/                        City overview (meetings, topics, stats)
GET  /al/<slug>/meetings/               Paginated meeting list with type filter
GET  /al/<slug>/meetings/<id>/          Meeting detail (agenda items, dollars, votes)
GET  /al/<slug>/meetings/<id>/items/<item_id>/   Item-centric detail (PR #64 item-centric nav)
GET  /al/<slug>/council/                Council member cards
GET  /al/<slug>/council/<id>/           Council member detail (sponsored items, votes)
GET  /search                            FTS search (city-scoped by default)
GET  /topics/                           Browse by topic index
GET  /topics/<topic>/                   Items for a specific topic
GET  /coverage/                         Editorial coverage feed (v1)
GET  /coverage/<id>/                    Coverage entry detail
GET  /rss/...                           Per-meeting / per-topic RSS feeds
# plus category-landing pages, HTMX rail partials, and source-link redirects
```

### Admin (session-based auth required)

```
GET       /admin/members/                              List all council members
GET|POST  /admin/members/add                           Add a new member
GET|POST  /admin/members/<id>/edit                     Edit member details
POST      /admin/members/<id>/deactivate               Deactivate member
GET       /admin/ai                                    AI pipeline dashboard (queue depth, 7-day cost, recent runs)
GET       /admin/calibration                           Calibration dashboard (6 panels: per-item divergence, under/over-scoring, baseline drift, badge volume, top false positives)
GET       /admin/data-debt                             OCR queue (cross-city, items needing extraction, priority-sorted)
GET       /admin/errors                                Errors queue (cross-city, failed_permanent items)
POST      /admin/errors/<id>/retry                     Reset to pending + clear backfill_session_id + last_error_*
POST      /admin/errors/<id>/escalate                  Set score_overrides.admin_escalated for manual review
GET       /admin/badge-review                          Refactor #2 — queue of status='flagged' badges (Haiku-suggested without deterministic backing)
POST      /admin/badge-review/<id>/approve             Promote a flagged badge to status='applied'
POST      /admin/badge-review/<id>/reject              Archive a flagged badge as status='rejected'
GET       /admin/review-conflicts                      cross_stage_conflict resolution queue
GET       /admin/badges-audit                          Badge audit log viewer
```

Auth on `/admin/*` is enforced via blueprint-level `before_request` hook in `admin.py:13–21` — new admin routes do not need an explicit `@login_required` decorator.

### Jinja2 Template Filters

- `{{ amount | dollar_tier }}` — returns a `DollarTier(color, symbol, description)` NamedTuple for the v3 partial (`tier_data.color`, `tier_data.symbol`, `tier_data.description`); `__str__` returns the color string (`"green"`/`"yellow"`/`"orange"`/`"red"`) so existing v2 templates that interpolate the filter inside a CSS class (`tier-{{ amt | dollar_tier }}`) keep working unchanged. Returns `None` for missing/invalid input.
- `{{ slug | topic_name }}` — returns display name like `"Zoning & Land Use"`

---

## Project Structure

```
docket-pub/
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
      006_admin_users.py         # Admin auth (session-based)
      007_council_terms_and_backfill.py  # Term dates for old/new council linking
      008_vote_matching_support.py       # video_timestamp_seconds, resolution_number, match cols
      009_vote_agenda_items.py           # N:M join table + meetings.minutes_adopted_at
      010_backfill_vote_agenda_items.py  # Copies legacy votes.agenda_item_id rows into the join
      011_drop_deprecated_vote_columns.py # Drops singular FK columns from votes (idempotent)
      012_ai_summaries_and_scoring.py    # AI columns on agenda_items + meetings + ai_runs table
      013_impact_first_refactor.py       # v3 schema: 10 new tables, MV, enums, indexes, seed
      015_search_vector_v3.py            # search_vector includes headline/why_it_matters/JSONB
      016_relax_audit_fk.py              # agenda_item_badges_audit FK → ON DELETE SET NULL
      018_ai_batches_ingested_at.py      # ai_batches.ingested_at + index
      020_raise_headline_caps.py         # chk_headline_length 60→80, why_it_matters 200→280
      021_badge_status_column.py         # refactor #2 — agenda_item_badges.status
      022_badge_mv_status_filter.py      # refactor #2 — MV filters status='applied'
      023_processing_status_withdrawn.py # refactor #2 follow-up — 'withdrawn' enum value
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
      scoring.py                 # Scoring stubs (kept; real scoring lives in ai/)
      cli.py                     # Backfill CLI: python -m docket.enrichment.cli
    ai/
      prompts.py                 # Versioned prompt strings + version constants
      contexts.py                # AgendaItemContext / MeetingContext (DB row → prompt)
      results.py                 # ItemAIResult / MeetingAIResult (Pydantic, validated)
      pricing.py                 # Per-model rates for the four Anthropic billing dimensions
      exceptions.py              # AIRateLimited / AITransientError / AIFatalError / AIPermanentRowError
      client.py                  # Anthropic SDK wrapper: tool_use, retries, cost tracking
      worker.py                  # Batch processor: claim queries, write-back, run loop, budget
      cli.py                     # Operator CLI: --status / --dry-run / --items / --meetings / --force
    worker/
      scheduler.py               # APScheduler BlockingScheduler entry point + --run-once <task> flag
      tasks.py                   # 11 task wrappers (ingest_all, video_ocr, ai_items, ai_meetings, vote_matching, repair_empty_agendas, process_badges, calibration_report, process_batches, refresh_backfill_ratio_mv, prune_analytics) — _safe_run handles Healthchecks ping + exception swallow
      health.py                  # Healthchecks.io ping helper (no-ops when UUID env var unset)
    services/
      maintenance.py             # repair_empty_agendas() — clears stuck agenda_items_scraped flags weekly
      video_ocr.py               # Claim pattern + persistence for the video OCR cron (PR #84, 2026-05-22)
    web/
      __init__.py                # create_app() factory
      public.py                  # ~23 citizen-facing routes (city, meetings, items, votes, search, topics, council, coverage, RSS, item_detail anchors)
      admin.py                   # ~48 admin routes (member CRUD, AI dashboard, badge review, errors queue, calibration, OCR rescan, conflict resolution, coverage CRUD, hide/unhide meetings, badges audit)
      templates/                 # Jinja2 templates (editorial design — Source Serif + IBM Plex + HTMX)
      static/                    # CSS tokens + layout + componentry
    analysis/                    # Vote analysis pipelines
      minutes_parser.py          # Birmingham minutes PDF → attendance + votes
      vote_matcher.py            # N:M matcher (substantive + consent block + strict re-parse)
      agenda_parser.py           # Granicus upcoming-meeting agenda PDF parser (PR #65)
      ocr/                       # Video OCR subpackage (folded from al-municipal-meetings, PR #84)
    rosters/                     # Reserved for future auto-scrapers (council pages → council_members table)
  tests/
    unit/                        # 200+ unit tests
      test_dollars.py            # dollar extraction + tiers
      test_helpers.py            # meeting classification, consent detection
      test_generic_cms.py        # date parsing from filenames
      test_civicclerk.py         # hierarchical agenda flattening
      test_sponsors.py           # sponsor extraction + title cleaning
      test_topics.py             # topic classification
      test_minutes_parser.py     # PDF text extraction, attendance + votes
      test_minutes_adoption.py   # adoption-pattern detection + sweep_adoptions
      test_vote_matcher.py       # N:M matcher (substantive + consent matchers, strict re-parse)
      test_vote_dataclass.py     # Vote / AgendaItemLink / MemberVote shapes + properties
      test_query_list_votes.py   # 3-query N:M reader
      test_ai_pricing.py         # cost math (cache-aware)
      test_ai_results.py         # Pydantic validation (substantive ↔ score consistency)
      test_ai_contexts.py        # AgendaItemContext NULL handling at prompt boundary
      test_ai_prompts.py         # version constants + rationales-first ordering
      test_ai_client.py          # success path + retry/error/fatal paths
      test_ai_worker_claim.py    # claim queries (debounce, two-phase meeting gates)
      test_ai_worker_writeback.py # write-back (success / completed_failed / empty / phase)
      test_ai_worker_run.py      # run loop + ai_runs telemetry + budget gate
    integration/                 # 4 AI pipeline e2e tests (real Postgres + mocked AIClient)
      test_ai_pipeline_e2e.py    # mixed substantive/empty/cancelled meetings
      test_ai_meeting_telescoping.py # meeting prompt sees item summaries, not raw titles
      test_ai_phase_lifecycle.py # provisional → adopted overwrites
      test_ai_prompt_version_bump.py # version bump cascades items + meetings
    live/                        # gated by `pytest -m live` + ANTHROPIC_API_KEY
      test_ai_live_smoke.py      # one real Haiku + one real Sonnet call
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
- Python 3.10 (prod target; `brew install python@3.10`)
- PostgreSQL 16 (via Docker or Homebrew)
- `uv` (only needed if you'll bump dependencies; `brew install uv`)

### Quick Start

```bash
# 1. Clone
git clone git@github.com:thinkdarrell/docket-pub.git
cd docket-pub

# 2. Start PostgreSQL
docker-compose up -d   # or use local Homebrew PostgreSQL

# 3. Python environment (use Python 3.10 to match prod)
python3.10 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"   # reads requirements.lock — deterministic transitives

# 4. Configure
cp .env.example .env
# Edit .env if your PostgreSQL credentials differ

# 5. Run migrations
python -m docket.migrations.runner

# 6. Verify
pytest                    # 1700+ tests (unit + integration); live AI smoke tests gated on ANTHROPIC_API_KEY
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
| [thinkdarrell/docket-pub](https://github.com/thinkdarrell/docket-pub) | This repo — single canonical (consolidated 2026-05-03 from prior `docket-pub` + `docket-pub-dw-dev` split) |
| [thinkdarrell/docket-pub-archived](https://github.com/thinkdarrell/docket-pub-archived) | Read-only — abandoned skeleton from before the consolidation |
| [thinkdarrell/al-municipal-meetings](https://github.com/thinkdarrell/al-municipal-meetings) | Original Birmingham pipeline with vote OCR — code ported from here |
| [thinkdarrell/docket-pub-site](https://github.com/thinkdarrell/docket-pub-site) | Landing page for docket.pub |
