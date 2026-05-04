# AI Summaries & Scoring — Design

**Status:** Draft for review
**Date:** 2026-05-01
**Owner:** darrellnance
**Related:** `docs/Docket_pub_Project_Plan.md` (Data Honesty Protocol), `src/docket/enrichment/scoring.py` (existing stubs), migration `001_initial.py:90` (existing nullable score columns)

## 1. Motivation

The repo schema has carried `agenda_items.significance_score` and `agenda_items.consent_placement_score` as nullable columns since migration 001, with stub functions in `src/docket/enrichment/scoring.py` that return `None`. The Project Plan commits to AI-generated summaries with a Data Honesty Protocol: "every AI-generated summary or insight is linked directly back to the original source docket."

This document specifies the v1 implementation of:
- Per-item summaries (1–2 sentences)
- Per-item scores (significance + consent placement, 0–10, with rationale)
- Per-meeting executive summaries (2–3 sentences)
- The async pipeline that produces them, the data model that stores them, and the operational controls around them.

Council member rollups are out of scope and will be brainstormed separately.

## 2. Decision summary

| # | Decision | Choice | Notes |
|---|---|---|---|
| 1 | Scope | Item + meeting summaries; item scores only | Council rollups deferred |
| 2 | Citation strategy | Source-bounded grounding (input is the only source the model sees) | Long-term: per-claim citations + discrepancy-aware summaries + QA telemetry |
| 3 | Pipeline timing | Async batch worker + ad-hoc CLI | Decoupled from ingest |
| 4 | Item call structure | Single structured call → summary + both scores + rationales | Tool-use for structured output |
| 5 | Models | Haiku 4.5 for items; Sonnet 4.6 for meetings | Item volume is high, meeting synthesis is higher-value |
| 6 | Versioning | `ai_prompt_version` INT per row + JSONB metadata | No audit table; git history of prompts is sufficient |

## 3. Architecture

A new `ai` stage sits **after** the existing ingest/enrichment pipeline as a decoupled async worker. Ingest stays unchanged and never blocks on the Anthropic API.

```
[scrape → enrich → upsert]   (existing ingest, unchanged)
                  │
                  ▼
        agenda_items / meetings rows written
                  │
                  ▼
[ai worker (cron)] ──► claims rows where ai_prompt_version != current
                  │
                  ├── per item:    Haiku 4.5  → summary + scores + rationales
                  └── per meeting: Sonnet 4.6 → executive summary
                  │
                  ▼
        Updates row in place (with version + timestamp)
```

New package: `src/docket/ai/` with four modules:

- `prompts.py` — versioned prompt strings + version constants
- `client.py` — Anthropic SDK wrapper with prompt caching, retries, structured-output validation
- `worker.py` — batch processor (claim, process, write back)
- `cli.py` — operator interface mirroring `enrichment/cli.py`

Plus one new table (`ai_runs`) for cost telemetry.

## 4. Data model

### 4.1 Schema changes

One additive migration. Migration number is the next free slot at apply time (currently the runner is at 010; this may shift if other migrations land first).

**`agenda_items`** — keep existing nullable scores, add four columns:

```sql
ALTER TABLE agenda_items
  ADD COLUMN summary             TEXT,
  ADD COLUMN ai_metadata         JSONB,
  ADD COLUMN ai_prompt_version   INTEGER,
  ADD COLUMN ai_generated_at     TIMESTAMPTZ;

CREATE INDEX idx_agenda_items_ai_prompt_version
  ON agenda_items (ai_prompt_version);
```

`significance_score` and `consent_placement_score` from `001_initial.py:90` are unchanged. They remain nullable `REAL` and now have a populating mechanism.

**`meetings`** — mirror set:

```sql
ALTER TABLE meetings
  ADD COLUMN executive_summary   TEXT,
  ADD COLUMN ai_metadata         JSONB,
  ADD COLUMN ai_prompt_version   INTEGER,
  ADD COLUMN ai_generated_at     TIMESTAMPTZ;

CREATE INDEX idx_meetings_ai_prompt_version
  ON meetings (ai_prompt_version);
```

**`ai_runs`** — new table for cost telemetry:

```sql
CREATE TABLE ai_runs (
    id              SERIAL PRIMARY KEY,
    started_at      TIMESTAMPTZ NOT NULL,
    finished_at     TIMESTAMPTZ,
    stage           TEXT NOT NULL,        -- 'items' | 'meetings'
    model           TEXT NOT NULL,
    rows_processed  INTEGER NOT NULL DEFAULT 0,
    rows_failed     INTEGER NOT NULL DEFAULT 0,
    usage           JSONB NOT NULL DEFAULT '{}'::jsonb,
    cost_usd        NUMERIC(10, 4) NOT NULL DEFAULT 0,
    notes           TEXT
);
```

Migration is purely additive: all new columns are nullable, no data migration, no downtime on Railway. Rollback drops the new columns + `ai_runs` table.

### 4.2 `ai_metadata` JSONB shape

Documented in module docstring; deliberately schemaless so we can evolve fields without migrations.

```jsonc
// agenda_items.ai_metadata
{
  "significance_rationale": "Approves $4.2M road resurfacing contract — large dollar amount, infrastructure impact",
  "consent_placement_rationale": "Routine procurement following standard bid process; appropriate for consent",
  "confidence": "high",                                 // high | medium | low
  "is_substantive": true,                               // false → both scores must be NULL
  "model": "claude-haiku-4-5-20251001"
}

// meetings.ai_metadata
{
  "phase": "provisional",                               // provisional | adopted
  "is_substantive": true,
  "substantive_item_count": 12,
  "confidence": "high",
  "model": "claude-sonnet-4-6"
}
```

### 4.3 `ai_runs.usage` JSONB shape

Tracks the four pricing dimensions Anthropic reports per call so backfill cost estimates remain accurate when prompt caching takes effect.

```json
{
  "input_tokens": 4231,
  "cache_creation_input_tokens": 850,
  "cache_read_input_tokens": 38900,
  "output_tokens": 6120
}
```

### 4.4 Worker readiness gates

**Item readiness** — five-minute debounce after ingest commit:

```sql
WHERE ai_prompt_version IS DISTINCT FROM $current_version
  AND created_at < NOW() - INTERVAL '5 minutes'
```

This is a temporal safety margin only. Enrichment (dollars, sponsors, topics) runs inline during ingest before the row is committed, so the row is enrichment-complete by construction once visible.

Item summaries describe **what was proposed**, not **what was decided** — vote outcomes render adjacent to the summary in the UI from `vote_agenda_items` data. This keeps item readiness independent of the vote-matching pipeline.

**Meeting readiness** — two phases mirroring `services/minutes_adoption.py` and `analysis/vote_matcher.py:strict_reparse_meeting`:

```python
# Phase 1: Provisional (agenda known, all items processed, minutes not yet adopted)
WHERE m.ai_prompt_version IS DISTINCT FROM $current_version
  AND m.ai_metadata->>'phase' IS DISTINCT FROM 'provisional'
  AND m.minutes_adopted_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM agenda_items ai
    WHERE ai.meeting_id = m.id
      AND ai.ai_prompt_version IS NULL
  )

# Phase 2: Adopted (minutes promoted via sweep_adoptions)
WHERE m.minutes_adopted_at IS NOT NULL
  AND m.ai_metadata->>'phase' IS DISTINCT FROM 'adopted'
```

A meeting is summarized **twice over its lifetime**: once when items finish and the agenda story is knowable, once when minutes are officially adopted. The adopted pass overwrites the provisional `executive_summary`. Phase determination uses `meetings.minutes_adopted_at` (set by the existing adoption sweep), **not** `meetings.minutes_url` (a posted PDF can be in draft state for weeks).

**Empty / cancelled meetings** — pre-check counts substantive items; if zero, write `{is_substantive: false, substantive_item_count: 0, model: null}`, bump `ai_prompt_version`, and skip the Sonnet call.

## 5. Components

### 5.1 `ai/prompts.py`

Versioned prompt strings and version constants. No logic.

```python
ITEM_PROMPT_VERSION = 1
MEETING_PROMPT_VERSION = 1

ITEM_SYSTEM = """You are summarizing a single agenda item from a municipal
government meeting. You will only see fields from the agenda item itself.
Do not invent facts.

If the item is procedural (motion to adjourn, approval of prior minutes,
roll call), set is_substantive=false and return null for both scores.

For substantive items, write rationale BEFORE numbers. Then assign 0-10
scores grounded in the rationale you just wrote."""

ITEM_USER_TEMPLATE = """Title: {title}
Description: {description}
Sponsor: {sponsor}
Dollar amount: {dollars_amount}
Topic: {topic}
Is on consent agenda: {is_consent}"""

MEETING_SYSTEM = """You are writing a 2-3 sentence executive summary of a
municipal meeting. You will only see substantive agenda items from this
meeting. Lead with what the council DECIDED if minutes are adopted, or
what the council CONSIDERED if minutes are still provisional.
Do not invent facts not present in the items."""

MEETING_USER_TEMPLATE = """Meeting: {meeting_type} on {meeting_date}
Phase: {phase}
Substantive items ({count}):
{items_block}"""
```

`{items_block}` is built from each item's **AI-generated summary** (not raw title), so meeting summaries telescope from item summaries. This is enforced by both the readiness gate (items must be at current version) and by an integration test that asserts the meeting prompt context contains item summaries.

`{topic}` resolves cleanly: migration 003 added `topic` to `agenda_items` and it is populated by `enrichment/topics.py`.

Prompt caching: `ITEM_SYSTEM` and `MEETING_SYSTEM` are sent with `cache_control={"type": "ephemeral"}` so the system prompt + rubric is not re-billed across the batch.

Prompt version constants are imported by `worker.py` to drive the claim query. Bumping a constant is a code change tracked in git history — the audit trail.

### 5.2 `ai/client.py`

Single class, `AIClient`, with two methods:

```python
class AIClient:
    def summarize_item(self, item: AgendaItemContext) -> ItemAIResult: ...
    def summarize_meeting(self, meeting: MeetingContext) -> MeetingAIResult: ...
```

Inputs are dataclasses (`AgendaItemContext`, `MeetingContext`) so DB rows do not leak into the prompt directly. Outputs validated via Pydantic.

**NULL handling at the prompt boundary.** Several agenda-item columns are nullable in the existing schema (`description`, `sponsor`, `dollars_amount`, `topic`). The `AgendaItemContext.from_row()` factory normalizes them so the rendered prompt never contains the literal string "None":

| Column | NULL → render as |
|---|---|
| `description` | `"(no description provided)"` |
| `sponsor` | `"(no sponsor listed)"` |
| `dollars_amount` | `"(none)"` |
| `topic` | `"Uncategorized"` |

These defaults are the contract; tests in `test_ai_prompts.py` assert each rendering.

```python
class ItemAIResult(BaseModel):
    is_substantive: bool
    significance_rationale: str
    significance_score: float | None       # 0-10, null iff !is_substantive
    consent_placement_rationale: str
    consent_placement_score: float | None
    summary: str
    confidence: Literal["high", "medium", "low"]
```

**Structured output** uses Anthropic `tool_use` (more reliable than free-text JSON parsing).

**Model IDs** come from `config.py` (`AI_ITEM_MODEL`, `AI_MEETING_MODEL`); env-var change to swap.

**Retry policy** — per row, max 3 attempts:

| Failure | Action |
|---|---|
| HTTP 429 | Honor `retry-after`, sleep, retry up to 3x |
| HTTP 5xx / SDK timeout | Exponential backoff (2s, 4s, 8s), retry up to 3x |
| HTTP 401 / 403 | Raise `AIFatalError` — bad API key, worker exits |
| HTTP 400 | No retry; permanent for that row |
| Pydantic validation failure | 1 retry, then permanent |
| Token cap exceeded | No retry, permanent, log loud |

Exhausted retries raise `AIRateLimited` (worker breaks the batch) or `AITransientError` (worker skips the row).

**Validation guardrails** beyond Pydantic types:

- `is_substantive=False` → both scores must be `None`. Mismatch rejected.
- Summary length cap: 400 chars (item), 800 chars (meeting). Soft truncate with warning.
- Empty summary + `is_substantive=True` → permanent failure. We do not write empty summaries.
- Confidence not in `{"high", "medium", "low"}` → coerced to `"low"` with warning.

**Cost tracking** — `client.py` exposes a `PRICING` dict with per-model rates for the four pricing dimensions (regular input, cache creation, cache read, output). Rates verified against Anthropic's pricing page on the date noted in the module docstring; bumping rates is a code change in a PR. Each call returns a `Usage` dataclass that the worker accumulates per batch.

### 5.3 `ai/worker.py`

Single entry point: `run_once(stage: Literal["items", "meetings"], limit: int)`.

```python
def run_once(stage, limit):
    with db() as conn:
        rows = _claim(conn, stage, limit)        # SELECT ... FOR UPDATE SKIP LOCKED
        run_id = _open_run(conn, stage)
        for row in rows:
            try:
                result = _process(row)            # AIClient call
                _write_back(conn, row, result)    # UPDATE row + bump prompt_version
                _accumulate_usage(conn, run_id, result.usage)
                conn.commit()
            except AIRateLimited:
                conn.rollback()
                break                              # stop the batch, retry next run
            except AITransientError:
                conn.rollback()
                continue                           # skip this row, try next
            except Exception as e:
                log_and_skip(row, e)
                _mark_failed(conn, row, e)        # completed_failed state
                conn.commit()
        _close_run(conn, run_id)
```

Per-row commit (not per-batch) so a crash mid-batch does not lose completed rows. `SKIP LOCKED` claim makes multiple worker instances safe by construction — adding a second worker is an ops decision, not a code change.

**`completed_failed` state** — a row that cannot be summarized after retries gets `ai_prompt_version = $current` (so it is not re-claimed) plus `ai_metadata = {error: "...", confidence: "low"}`, but `summary` and scores remain NULL. The UI renders these as `[Auto summary unavailable]`. A prompt-version bump retries them.

### 5.4 `ai/cli.py`

Operator interface, mirrors `enrichment/cli.py`:

```bash
python -m docket.ai.cli --items                       # process pending items, default batch
python -m docket.ai.cli --meetings --limit 10
python -m docket.ai.cli --force --meeting-id 5        # bypass version check, re-run
python -m docket.ai.cli --dry-run --items --limit 5   # show what WOULD be processed
python -m docket.ai.cli --status                      # queue depth + last run summary
```

`--dry-run` is **required** before any prompt-version bump in production — operator confirms the count before kicking off a multi-thousand-row backfill.

### 5.5 Integration with existing code

- **Web reads** (`services/query.py`): existing readers add `summary` and `executive_summary` to their SELECT lists. No new query helpers; summaries are just more columns.
- **Templates** (`web/templates/`): `meeting_detail.html` adds an executive-summary block above the items table; item rows get a one-line summary under the title. Confidence-low rows render with a muted "[Auto summary — under review]" badge per Data Honesty Protocol.
- **Ingest** (`services/ingest.py`): **untouched.** The worker is the only path to AI fields.

## 6. Data flow

### 6.1 Item lifecycle

```
[ingested]        ai_prompt_version IS NULL, summary IS NULL
    │
    │  ≥ 5 min after created_at
    ▼
[claimed]         worker SELECT FOR UPDATE SKIP LOCKED
    │
    ▼
[ai called]       Haiku 4.5, structured output via tool_use
    │
    ├── success ─────────► [completed]
    │                       ai_prompt_version = current, ai_generated_at = NOW()
    │                       summary, scores, ai_metadata written
    │
    ├── transient error ─► row released, next batch retries
    │
    └── permanent error ─► [completed_failed]
                            ai_prompt_version = current (not re-claimed)
                            ai_metadata = {error: ..., confidence: "low"}
                            summary, scores remain NULL
```

### 6.2 Meeting lifecycle (two-phase)

```
[ingested]                 ai_prompt_version IS NULL
    │
    │  all items in this meeting have ai_prompt_version IS NOT NULL
    ▼
[provisional ready]        minutes_adopted_at IS NULL
    │
    ▼
[provisional summarized]   ai_metadata.phase = "provisional"
    │
    │  later: services/minutes_adoption.sweep_adoptions sets minutes_adopted_at
    ▼
[adopted ready]            minutes_adopted_at IS NOT NULL
                            ai_metadata.phase still = "provisional"  ← stale
    │
    ▼
[adopted summarized]       ai_metadata.phase = "adopted"
                            executive_summary overwritten
                            ai_prompt_version unchanged
```

The provisional → adopted transition is **independent of prompt versioning**.

### 6.3 Prompt-version bump cascade

Bumping `ITEM_PROMPT_VERSION` from 1 → 2 implicitly forces meeting re-runs, because the meeting readiness gate requires all items at current version. One rule, two stages, no orchestration.

Operator workflow:

1. Edit `src/docket/ai/prompts.py`, bump constant, write rationale in commit message
2. Deploy (`railway up --detach`)
3. `python -m docket.ai.cli --status` → confirm queue depth
4. `python -m docket.ai.cli --dry-run --items --limit 5` → eyeball candidates
5. `python -m docket.ai.cli --items --limit 500` (repeat in batches; cron also progresses queue)
6. After items finish, meetings auto-pick-up

### 6.4 Concurrency model

- One Railway scheduled cron: `python -m docket.ai.cli --items --limit 200` every 15 min
- One Railway scheduled cron: `--meetings --limit 50` every 30 min
- Adding a second worker instance is safe: `SKIP LOCKED` + per-row commit means no row processed twice and no row blocks another

### 6.5 Cost envelope

Rough sizing for current data volume:

| Stage | Rows | Model | Tokens (est.) | One-time cost (est.) |
|---|---|---|---|---|
| Item backfill | ~10K | Haiku 4.5 | 500 in + 200 out | $3–5 |
| Meeting provisional | ~1K | Sonnet 4.6 | 2000 in + 300 out | $8–15 |
| Meeting adopted (~870 already adopted) | ~870 | Sonnet 4.6 | same | $8–15 |
| **Total backfill** | | | | **~$20–35** |

Ongoing weekly: ~30 meetings × ~10 items + 60 meeting calls = pennies/week. Prompt caching reduces system-prompt cost to ~10% of nominal after the first call in a batch.

## 7. Operations

### 7.1 Cost controls

Three knobs in `.env`:

```
AI_DAILY_BUDGET_USD=10                 # soft cap per UTC day
AI_ITEM_MODEL=claude-haiku-4-5-20251001
AI_MEETING_MODEL=claude-sonnet-4-6
AI_MAX_BATCH_SIZE=200                  # hard cap per CLI invocation
```

The worker accumulates `cost_usd` per batch into the `ai_runs` row. Before starting a new batch, it sums today's `cost_usd`; if it exceeds `AI_DAILY_BUDGET_USD`, it refuses to proceed unless `--force-budget` is passed.

### 7.2 Logging

Standard Python `logging`:

- `INFO` — batch start/end, row counts, total cost
- `WARNING` — soft validation issues, retries, budget approached
- `ERROR` — row permanent failures (with row ID + reason)
- `CRITICAL` — fatal errors (bad API key, DB outage)

Per-row prompt and response are **not** logged by default. `--debug` enables full prompt/response logging for the duration of one CLI run, with API key scrubbed.

### 7.3 Observability

No dashboard build for v1. Three lightweight sources:

1. **`ai/cli.py --status`** — queue depth + last run summary
2. **Admin dashboard panel** at `/admin/` — rows pending, last 7 days' cost (incl. cache breakdown), last 10 failures with row IDs
3. **Railway stdout logs** — existing setup, no new infra

### 7.4 Security

- `ANTHROPIC_API_KEY` lives in Railway env vars; never in `.env.example`, never logged
- Prompt content is **already public** (agenda items + meetings are public records). No PII concern beyond what is on city websites
- No raw user input reaches the AI prompts — all inputs come from DB columns populated by ingest of municipal sources
- Pydantic validation prevents malformed model output from corrupting the DB; JSONB writes go through parameterized queries via the existing `db_cursor()` pattern
- Confidence-low rows render with a `[Auto summary — under review]` badge in the UI per Data Honesty Protocol; never silently shown as authoritative

## 8. Testing strategy

### 8.1 Unit tests (`tests/unit/`) — fast, no network, no DB

| File | Covers |
|---|---|
| `test_ai_prompts.py` | Template rendering with edge inputs (NULL description, $0, no sponsor, missing topic). Rationales-first ordering. Version constants importable. |
| `test_ai_pydantic.py` | `ItemAIResult` / `MeetingAIResult` validation: score range, is_substantive↔null-score consistency, confidence enum, summary length caps, empty-summary rejection. |
| `test_ai_client.py` | Mocked Anthropic responses: success, malformed JSON → 1 retry → permanent fail, 429 → retry honoring `retry-after`, 5xx → backoff, 401 → fatal, token-cap refusal. Pricing math against fixture usage objects (regular vs cache-creation vs cache-read tokens). |
| `test_ai_worker_claim.py` | Claim query SQL: 5-min debounce, item readiness, two-phase meeting gate, `SKIP LOCKED`. Uses real Postgres fixture. |
| `test_ai_worker_writeback.py` | Per-row commit, `completed_failed` state, prompt-version cascade, provisional → adopted promotion overwrites. |

### 8.2 Integration tests (`tests/integration/`) — fixture DB, mocked Anthropic

| File | Covers |
|---|---|
| `test_ai_pipeline_e2e.py` | Seed 5 meetings × 4 items each (mix of substantive, procedural, empty meeting, cancelled). Run worker. Assert correct rows summarized, correct rows skipped, `ai_runs` populated, costs accumulate correctly across cache states. |
| `test_ai_phase_lifecycle.py` | Run provisional pass, simulate `sweep_adoptions` setting `minutes_adopted_at`, run worker again, assert phase transitions to "adopted" and summary overwrites. |
| `test_ai_prompt_version_bump.py` | Run with v1, bump constant to v2, run again, assert all rows re-summarized; meetings auto-cascade after items finish. |
| `test_ai_meeting_telescoping.py` | Capture the meeting prompt context at call time and assert it contains item **summaries** (not raw titles). Pins the data flow at the boundary. |

### 8.3 Live tests (manual, opt-in) — `tests/live/`, gated by `--live` mark + `ANTHROPIC_API_KEY`

| File | Covers |
|---|---|
| `test_ai_live_smoke.py` | One real call to Haiku 4.5 with a known fixture item; one real call to Sonnet 4.6 with a known meeting. Asserts response shape + non-empty summary. Run before deploys; never in CI. |

### 8.4 Coverage targets

- All retry / fallback branches: 100%
- Claim query variants: 100% (each gate condition tested explicitly)
- Pydantic validators: 100%
- Existing test suite must continue to pass; new template snapshot for the executive-summary block

### 8.5 Manual QA before flipping the worker on in production

1. `--dry-run --items --limit 20` on prod DB — visually inspect candidate rows
2. `--items --limit 20` — inspect generated summaries against source PDFs
3. Spot-check 5 for accuracy: do scores match rationale? Hallucinations? Source-not-in-input claims?
4. If clean, ramp: 100, 500, 1000, then unleash to backfill cap
5. After full backfill: 100-row random sample manually graded for accuracy

## 9. Acceptance criteria

This work is **done** when all of:

- [ ] Migration applies cleanly on a fresh Railway DB and on the existing prod DB
- [ ] All unit + integration tests pass (target: 95%+ branch coverage on `src/docket/ai/`)
- [ ] Live smoke test passes against Anthropic API
- [ ] Backfill of all existing items completes without exceeding `AI_DAILY_BUDGET_USD` × 3 days
- [ ] Manual QA: ≥ 95% of a 100-row sample is judged "accurate, no hallucination" by a human reviewer
- [ ] `meeting_detail.html` renders the executive summary above items; item rows show per-item summary; confidence-low rows show the badge
- [ ] CLI `--status` reports queue depth correctly
- [ ] Admin dashboard panel shows last 7 days' usage with cache breakdown
- [ ] CLAUDE.md updated: new section under "What's been ported" + new build phase

## 10. Out of scope (explicit)

- Per-claim citations (Q2 option C) — Phase 2
- Discrepancy-aware summaries (long-term Data Honesty trajectory item #2) — Phase 2
- Council member rollups — separate brainstorm
- Multi-language summaries
- Public API exposure of summaries (deferred with public API per CLAUDE.md)
- A separate `ai_generations` audit table — git history of `prompts.py` is sufficient until proven otherwise

## 11. Long-term trajectory (informational)

After v1 stabilizes, the planned evolution is:

1. **Per-claim citations.** Once we've seen what summaries actually drift on, structure output as `{"text": "...", "source": "agenda_item.dollars_amount"}` and render footnoted UI.
2. **Discrepancy-aware summaries.** Extend the existing video-OCR-vs-minutes reconciliation pattern into AI prose: *"The motion passed 6–3 according to minutes; video OCR shows 5–3 (sources disagree)."* This is the differentiator vs. a generic "summarize this PDF" tool.
3. **QA / accuracy telemetry.** Weekly sampling, human review, tracked accuracy rate over time. Foundation for the public-release accuracy claim.

Not pursued: extractive quote-stuffing (forcing summaries to embed verbatim source spans) — reads poorly, citizens don't want it.
