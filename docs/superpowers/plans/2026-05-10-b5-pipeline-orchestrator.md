# B5 — Per-Item Pipeline Orchestrator (Track 1+2+3 Convergence) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Phase 2 Track 3 §B5 — `pipeline.process_item()`, the per-item orchestrator that runs Wave 0 → Stage 1 (extraction) → Stage 2 (Smart Brevity rewrite) → Stage 2.5 (score floors) → reconcile → atomic commit with badge writes. Plus `IMPACT_FIRST_ENABLED` flag wiring in `config.py` and a parallel `_process_items_v3` path in `worker.py`. Plus G4 cleanup: `services/conflict_resolution._rerun_stage2` is refactored to delegate to a shared `pipeline._rerun_from_stage2` helper; the redundant `_get_enabled_policy_slugs` shim is deleted. This task is the architectural capstone of Track 3 — the moment the v2 worker can be flag-flipped to v3 without further refactor.

**Architecture:** New module `src/docket/ai/pipeline.py` exports two functions:

1. **`process_item(item) -> str`** — full pipeline: Wave 0 short-circuit (data_quality_skipped / procedural_skipped early returns); Stage 1 extraction; then delegates to `_rerun_from_stage2(item, facts)`.

2. **`_rerun_from_stage2(item, facts, *, override_instruction=None) -> str`** — partial pipeline starting at Stage 2: rewrite_item → apply_score_floors → reconcile_stages (with auto-retry once on `retry_stage2_with_override`); atomic persist of extraction + rewrite + scores + on-write process badges + policy badges + status. Returns the final `processing_status` ('completed' or 'cross_stage_conflict' or, after Wave 0 reject, 'data_quality_skipped'/'procedural_skipped').

   This second function is the cleanup target for G4's `_rerun_stage2` private helper, which currently duplicates this logic in `services/conflict_resolution.py`.

`config.py` gains `IMPACT_FIRST_ENABLED: bool` from the same-named env var (default `False`). `worker.py` adds `_process_items_v3(conn, limit, summary)` parallel to the existing `_process_items` (v2), with `run_once(stage="items", ...)` dispatching between them based on the flag. The v2 path stays untouched and live — flipping `IMPACT_FIRST_ENABLED=true` at FINAL-3 is the cutover.

Tests mock `extract_facts_for_item` and `rewrite_item` via `monkeypatch` (same pattern as G4) and use real DB transactions. End-to-end integration tests live at `tests/integration/test_pipeline_e2e.py`. The optional live smoke test at `tests/live/test_pipeline_live.py` is gated on `ANTHROPIC_API_KEY` (existing `tests/live/` convention).

**Tech Stack:** Python 3.10+ · psycopg2 · PostgreSQL 16/18 · Pydantic v2 · Anthropic SDK (Claude Haiku 4.5 for both stages). All API surfaces already exist on the integration branch — this is wiring, not new function bodies.

---

## Post-implementation deviations (recorded for accuracy)

The implementation deviated from this plan in two places. Both were verified as correct by Opus review #1; the plan body below is the pre-implementation contract, retained for historical accuracy. Recording the deviations here so future readers don't have to cross-reference the implementer's report.

1. **`agenda_items.source_type` column doesn't exist.** This plan's test fixtures (`_Bag.add_pending_item`) and helper SELECTs (`_load_item`) referenced an `agenda_items.source_type` column. The column does not exist in any migration (verified via grep of migrations 001–016). The implementer adapted by injecting `source_type="agenda"` as a default attribute on duck-typed items, both in tests (`_load_item` post-fetch dict mutation) and in the worker's `_AttrAccess` adapter. The as-shipped code does not read or write a `source_type` column from `agenda_items`.

2. **`persist_extraction` flips status — replaced with inline UPDATE.** §659, §696, and §1543 of this plan reference `persist_extraction(cur, item.id, facts, version=EXTRACTION_PROMPT_VERSION)` inside Phase C. The actual `persist_extraction` function (Track 1's `src/docket/ai/extraction.py:206`) flips `processing_status` to `'extracted'` as a side effect — Track 1's standalone-extractor terminal-write semantics. Inside the pipeline's Phase C this side effect would have caused decision #13's `expected_status='cross_stage_conflict'` guard to fire spuriously on every admin re-prompt (the inline status flip to `'extracted'` happens before the guarded UPDATE checks `processing_status = 'cross_stage_conflict'` → guard fails → false positive `PipelineConcurrencyError`). The implementer replaced the call with an inline UPDATE writing only `extracted_facts` (JSONB) + `ai_extraction_version` (int), no status flip. Behavioral parity (same `model_dump(mode='json')` + `::jsonb` cast + version column) confirmed by Opus review #1. Splitting `persist_extraction` into two separate functions (one with the status flip, one without) is a Phase 4 cleanup follow-up.

---

## Decisions baked into this plan

Override before dispatch if you disagree. The B5 design has more interlocking decisions than G3/G4; reviewers should expect to push back on at least one.

1. **Two entry points** in `pipeline.py`: full-pipeline `process_item(item)` and partial-rerun `_rerun_from_stage2(item, facts, *, override_instruction=None)`. The partial helper is exported (`from docket.ai.pipeline import _rerun_from_stage2`) so G4's `services/conflict_resolution.py` can delegate. **The leading underscore is intentional** — it signals "internal-to-the-pipeline-package, but cross-module-callable for the conflict-resolution refactor." If you prefer no-underscore naming, rename to `rerun_from_stage2` consistently.

2. **Wave 0 + Stage 1 are run on demand**, not assumed pre-run. `process_item(item)` always invokes `evaluate_data_quality(item)` and `is_procedural(item.title)` first. Yes, Wave 0 was run as a non-LLM pre-pass during Phase 1 (decision #78), so most production items already have `data_quality` and `processing_status` set. But the orchestrator is the single contract for "compute v3 from raw item", and re-running Wave 0 is cheap. Worker-side optimization (skip Wave 0 if `data_quality IS NOT NULL`) can be a B5-fix-up follow-up if the cost actually shows up in profiling.

3. **Three-phase transaction shape:**
   - **Phase A (DB write):** Wave 0 short-circuit. If `data_quality != 'ok'`, write `data_quality`, `data_debt_priority`, `processing_status='data_quality_skipped'` in one short transaction, return. If `is_procedural(title)`, write `processing_status='procedural_skipped'`, return. (Stage 0a sets `data_quality='ok'` implicitly by not writing.)
   - **Phase B (no DB):** Stage 1 extraction (LLM, ~1-2s), Stage 2 rewrite (LLM, ~2-3s), Stage 2.5 floors (CPU), reconcile (CPU). May execute up to two LLM calls per stage if reconcile fires the auto-retry (decision #45). No DB held across either LLM call.
   - **Phase C (atomic DB write):** single `with db() as conn, conn.cursor() as cur:` block writing extraction (via `persist_extraction`) + rewrite columns + scores + score_overrides JSONB + processing_status + on-write process badges + policy badges. Atomic per plan §B5's explicit "all-or-none" framing.

4. **Atomic-all-or-none on Stage 1+2 path** (plan §B5 explicit design): if Stage 2 (or floors, or reconcile, or any badge compute) throws after Stage 1 succeeded, the whole row stays at its pre-call state. Stage 1's cost ($0.0007) is wasted on retry. Trade-off accepted; documented in the docstring. Alternative (persist Stage 1 immediately, then attempt Stage 2 in a separate write) is rejected as scope creep — the v2 worker already retries on `AITransientError`, and the v3 worker will inherit that pattern. **If you'd prefer Stage-1-survives-Stage-2-failure semantics, flag this and the design splits Phase C into C1 (extraction) + C2 (rewrite+badges).**

5. **`apply_score_floors` signature mismatch from plan §B5**: the plan sketches `apply_score_floors(item, facts, rewrite, item.city_id)`. The actual signature is `apply_score_floors(cur, item, facts, ai, city_id)` — five positional args, requires a cursor. The cursor is for per-city threshold overrides (reads `city_score_floor_overrides`). The orchestrator opens a brief cursor for this call as part of Phase B's compute window. The brief read-only DB use inside Phase B is acceptable because (a) it's a single fast query, (b) the resulting `ScoreOverrides` is needed before the atomic commit. **Phase B is "no LLM-call-spanning DB hold," not "zero DB use."**

6. **Worker dispatch in `run_once(stage="items", ...)`:** read `IMPACT_FIRST_ENABLED` once at the top of the function; route to `_process_items_v3(conn, limit, summary)` or the existing `_process_items(conn, client, limit, summary)`. The v3 path does NOT take an `AIClient` argument because `extract_facts_for_item` and `rewrite_item` instantiate their own anthropic client at module level (see `extraction.py:31`, `rewrite.py:32`). This is a known asymmetry from Track 1's design choice; refactoring is out of B5 scope.

7. **v3 worker claim SQL differs from v2.** `_process_items_v3` cannot reuse `claim_items_sql()` because v2 filters on `ai_prompt_version IS NULL OR < ITEM_PROMPT_VERSION` (the v2 versioning columns). v3 must filter on `processing_status IN ('pending', NULL)` AND `(ai_extraction_version IS NULL OR < EXTRACTION_PROMPT_VERSION OR ai_rewrite_version IS NULL OR < ITEM_REWRITE_PROMPT_VERSION)`. New helper `claim_items_v3_sql()` in `worker.py`.

8. **Budget gate is shared.** Both paths call the existing `_today_spend(conn)` check at the top of `run_once`. No change to the budget gate; v3 just inherits.

9. **G4 cleanup:** in `services/conflict_resolution.py`:
   - Delete `_rerun_stage2` (lines ~347-431; the private helper subsumed by `pipeline._rerun_from_stage2`).
   - Replace its two call sites in `re_prompt_stage_2` and `edit_stage_1_facts` with calls to `pipeline._rerun_from_stage2(item, facts, override_instruction=...)`.
   - Delete `_get_enabled_policy_slugs` (lines ~90-110) AND its call site — `pipeline._rerun_from_stage2` already loads `enabled_slugs` internally via `services.badges.get_enabled_policy_slugs`.
   - Delete the no-longer-used `_ItemView` adapter and `_RerunOutcome` dataclass if `_rerun_stage2` was their only consumer.
   - Verify all existing G4 tests in `tests/integration/test_conflict_resolution.py` still pass after the refactor. **No new tests required** — G4's tests are the regression contract for this cleanup.

10. **No `usage` tracking in v3 v1.** `extract_facts_for_item` and `rewrite_item` swallow the anthropic `response.usage` field. `_open_run` / `_close_run` in `worker.py` track cost at the `ai_runs` row level; v3's run-summary won't have per-item cost detail. **Gap; flag as B5-fix-up follow-up or post-B5 task.** Adding usage threading is a 4-file refactor (extraction.py, rewrite.py, pipeline.py, worker.py) and is not in B5's scope.

11. **Tests mock anthropic, hit real DB.** Same pattern as G4. The integration tests use `monkeypatch.setattr("docket.ai.pipeline.extract_facts_for_item", _mock)` and `monkeypatch.setattr("docket.ai.pipeline.rewrite_item", _mock)`. The `_Bag` fixture from G4 is reused for item/meeting/city setup. Live smoke test at `tests/live/test_pipeline_live.py` is gated on `ANTHROPIC_API_KEY` per existing convention.

12. **`process_item` accepts an item _object_, not an ID.** Caller (worker or test) loads the row first (typically via the worker's `claim_items_v3_sql` row → dict + duck-typing). Item shape: id, meeting_id, title, description, sponsor, dollars_amount, topic, is_consent, source_type, plus loaded `city_id` and `city_name` from the join. The `_ItemView` Protocol in `wave0.py:33` codifies the minimal shape for Wave 0; pipeline uses a superset (also needs `city_id`, `city_name` for Stage 2). **Document the shape in `process_item`'s docstring with a TypedDict-style breakdown.**

13. **TOCTOU concurrency guard via `expected_status` parameter** (engineer-review addition). `_rerun_from_stage2` accepts an optional `expected_status: str | None = None`. When `None`, the Phase C UPDATE runs unconditionally — safe for the worker because the worker holds `FOR UPDATE OF ai SKIP LOCKED` from `claim_items_v3_sql` for the duration of the per-row transaction. When a string is passed, the Phase C UPDATE adds `AND (%s::text IS NULL OR processing_status = %s::processing_status_enum)` as a guard and raises `PipelineConcurrencyError` if `cur.rowcount == 0`. The admin paths (`re_prompt_stage_2`, `edit_stage_1_facts`) pass `expected_status='cross_stage_conflict'` — closing the race window that G4's fix-up B-R1 closed, now preserved through the refactor. The pipeline's atomic-rollback semantics ensure that if the guard fails, NO Phase C writes commit (extraction + rewrite + scores + badges all roll back together via the `with db()` context's exception-rollback). A new exception class `PipelineConcurrencyError` is defined in `pipeline.py`; `services/conflict_resolution.py` catches it, writes a `*_lost_race` audit row in a fresh transaction, then re-raises as the existing `ConflictAlreadyResolvedError` so the admin route's existing handler maps to 409. Layer-separated: pipeline owns concurrency-detection, services owns audit-translation.

---

## File structure

```
src/docket/ai/pipeline.py                                  (NEW, ~280 lines)
src/docket/config.py                                       (+1 line — IMPACT_FIRST_ENABLED)
src/docket/ai/worker.py                                    (+~80 lines — _process_items_v3, claim_items_v3_sql, run_once dispatch)
src/docket/services/conflict_resolution.py                 (~-120 lines net — remove _rerun_stage2 + _get_enabled_policy_slugs + dependencies; replace call sites)
tests/integration/test_pipeline_e2e.py                     (NEW, ~25-30 tests)
tests/integration/test_worker_v3_dispatch.py               (NEW, ~6 tests for flag gating)
tests/live/test_pipeline_live.py                           (NEW, ~3 tests gated on ANTHROPIC_API_KEY)
```

Plus no template / CSS / migration changes. B5 is pure-code wiring.

---

## Conventions inherited from G1/G2/G3/G4

- **Auth:** N/A — B5 has no admin routes.
- **Cursor:** `db_cursor()` for dict-row reads, `db()` for tuple writes inside a transaction.
- **Test fixture: `_Bag`** — copy the G4 pattern (self-contained, doesn't import from sibling test files). Refactor as needed for v3 column shape (`processing_status`, `ai_extraction_version`, etc.).
- **Test pre-flight:** `pytest.mark.skipif("railway.internal" in DATABASE_URL ...)`.
- **Monkeypatch the anthropic boundary**, not the SDK: `monkeypatch.setattr("docket.ai.pipeline.extract_facts_for_item", _mock)` etc.
- **CHECK constraints (migration 013, integrated):**
  - `processing_status_enum`: `'pending'`, `'completed'`, `'data_quality_skipped'`, `'procedural_skipped'`, `'failed_retry'`, `'failed_permanent'`, `'cross_stage_conflict'`
  - `actor_role`: `'admin'`, `'cron'`, `'on_write'` — pipeline writes badges with `source='deterministic'` (process) or `'llm'/'both'/'manual'` (policy); the audit table fires from G2/G3 admin actions, NOT from pipeline writes.

---

## Task 1: `ai/pipeline.py` — orchestrator with full + partial entry points

**Files:**
- Create: `src/docket/ai/pipeline.py`
- Test: `tests/integration/test_pipeline_e2e.py` (NEW)

- [ ] **Step 1.1: Test scaffold + `_Bag` fixture for v3 items**

Create `tests/integration/test_pipeline_e2e.py`:

```python
"""Integration tests for B5 — per-item pipeline orchestrator.

Two entry points under test:

- B5.1: ``pipeline.process_item(item)`` — full pipeline (Wave 0 → Stage 1
  → Stage 2 → 2.5 → reconcile → atomic commit).
- B5.2: ``pipeline._rerun_from_stage2(item, facts, *, override_instruction=None)``
  — partial-rerun helper used by both `process_item` (after Stage 1) and
  G4's conflict-resolution actions (after admin override).

LLM-touching paths mock ``docket.ai.pipeline.extract_facts_for_item`` and
``docket.ai.pipeline.rewrite_item`` via monkeypatch. Tests hit a real
local DB; ``pytest.mark.skipif("railway.internal" in DATABASE_URL ...)``
guards production.

Reuses the G4 ``_Bag`` test-data tracker pattern, extended for v3
columns (processing_status, extracted_facts, ai_extraction_version,
ai_rewrite_version, headline, why_it_matters, score_overrides).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from docket.config import DATABASE_URL
from docket.db import db, db_cursor
from docket.ai.extraction_schema import StructuredFacts, NextSteps
from docket.ai.rewrite_schema import ItemRewrite


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run B5 pipeline tests against Railway DB.",
)


SAMPLE_FACTS_DICT = {
    "funding_source": "general_fund",
    "counterparty": "Acme Corp",
    "procurement_method": "competitive",
    "location": None,
    "action_type": "contract_award",
    "next_steps": {
        "committee_referral": None,
        "public_hearing_date": None,
        "public_hearing_time": None,
        "comment_period_end": None,
        "implementation_date": None,
    },
    "parcels_affected": None,
    "acres_affected": None,
}


def _sample_facts() -> StructuredFacts:
    return StructuredFacts.model_validate(SAMPLE_FACTS_DICT)


def _substantive_rewrite() -> ItemRewrite:
    return ItemRewrite(
        is_substantive=True,
        headline="Council awards $75K janitorial contract",
        why_it_matters="Renews custodial services across 12 city buildings.",
        significance_rationale="Modest ongoing operating expense.",
        significance_score=4.0,
        consent_placement_rationale="Routine ops contract.",
        consent_placement_score=8.0,
        suggested_badge_slugs=[],
        confidence="medium",
    )


def _procedural_rewrite() -> ItemRewrite:
    return ItemRewrite(
        is_substantive=False,
        headline=None, why_it_matters=None,
        significance_rationale="", significance_score=None,
        consent_placement_rationale="", consent_placement_score=None,
        suggested_badge_slugs=[], confidence="medium",
    )


class _Bag:
    """Test-data tracker for pipeline tests.

    Cleanup order: agenda_item_badges → processing_status_audit →
    agenda_item_badges_audit → agenda_items → meetings."""

    def __init__(self, city_id: int, city_slug: str, city_name: str):
        self.city_id = city_id
        self.city_slug = city_slug
        self.city_name = city_name
        self.meeting_ids: list[int] = []
        self.item_ids: list[int] = []

    def add_meeting(self, date_str: str = "2026-04-15") -> int:
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO meetings
                  (municipality_id, title, meeting_date, meeting_type)
                VALUES (%s, %s, %s, 'council')
                RETURNING id
                """,
                (self.city_id, "B5 pipeline test", date_str),
            )
            mid = cur.fetchone()[0]
        self.meeting_ids.append(mid)
        return mid

    def add_pending_item(
        self,
        meeting_id: int,
        *,
        title: str = "Award contract to Acme Corp for janitorial services",
        description: str = "Council awards $75,000 contract for custodial services.",
        dollars_amount: int | None = 75_000,
        topic: str | None = None,
        is_consent: bool = False,
        sponsor: str | None = "City Council",
        source_type: str = "agenda",
    ) -> int:
        """Seed an agenda_items row in v3 'pending' state (Wave 0 already passed).

        Sets processing_status='pending', data_quality='ok', no
        extraction_facts yet — the canonical pre-process_item shape.
        """
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agenda_items
                  (meeting_id, title, description, sponsor, dollars_amount,
                   topic, is_consent, source_type,
                   data_quality, data_debt_priority, processing_status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                        'ok'::data_quality_enum,
                        'normal'::data_debt_priority_enum,
                        'pending'::processing_status_enum)
                RETURNING id
                """,
                (meeting_id, title, description, sponsor, dollars_amount,
                 topic, is_consent, source_type),
            )
            iid = cur.fetchone()[0]
        self.item_ids.append(iid)
        return iid

    def cleanup(self) -> None:
        with db() as conn, conn.cursor() as cur:
            if self.item_ids:
                cur.execute(
                    "DELETE FROM agenda_item_badges WHERE agenda_item_id = ANY(%s)",
                    (self.item_ids,),
                )
                cur.execute(
                    "DELETE FROM processing_status_audit WHERE agenda_item_id = ANY(%s)",
                    (self.item_ids,),
                )
                cur.execute(
                    "DELETE FROM agenda_item_badges_audit WHERE agenda_item_id = ANY(%s)",
                    (self.item_ids,),
                )
                cur.execute(
                    "DELETE FROM agenda_items WHERE id = ANY(%s)",
                    (self.item_ids,),
                )
            if self.meeting_ids:
                cur.execute(
                    "DELETE FROM meetings WHERE id = ANY(%s)",
                    (self.meeting_ids,),
                )


def _bag() -> _Bag:
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, slug, name FROM municipalities WHERE slug = 'birmingham'"
        )
        row = cur.fetchone()
    assert row is not None, "Birmingham must be seeded"
    return _Bag(row[0], row[1], row[2])


@pytest.fixture
def bag():
    b = _bag()
    try:
        yield b
    finally:
        b.cleanup()


def _load_item(item_id: int) -> dict:
    """Read the row + joined city context — the shape pipeline.process_item expects."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT ai.id, ai.meeting_id, ai.title, ai.description,
                   ai.sponsor, ai.dollars_amount, ai.topic, ai.is_consent,
                   ai.source_type,
                   ai.data_quality::text AS data_quality,
                   ai.processing_status::text AS processing_status,
                   ai.extracted_facts, ai.headline, ai.why_it_matters,
                   ai.significance_score, ai.consent_placement_score,
                   ai.score_overrides,
                   m.municipality_id AS city_id,
                   muni.name AS city_name
              FROM agenda_items ai
              JOIN meetings m ON m.id = ai.meeting_id
              JOIN municipalities muni ON muni.id = m.municipality_id
             WHERE ai.id = %s
            """,
            (item_id,),
        )
        return dict(cur.fetchone())


def _read_badges(item_id: int) -> list[tuple]:
    """Read agenda_item_badges rows for assertions."""
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT badge_slug, kind, confidence::float, source, city_id
              FROM agenda_item_badges
             WHERE agenda_item_id = %s
             ORDER BY badge_slug
            """,
            (item_id,),
        )
        return cur.fetchall()


class _ItemView:
    """Duck-typed item object for pipeline calls. Mirrors what the worker
    will hand to process_item (a dict converted to attribute access)."""
    def __init__(self, row: dict):
        for k, v in row.items():
            setattr(self, k, v)
```

- [ ] **Step 1.2: First failing test — Wave 0 short-circuit on bad data_quality**

Append:

```python
# ---------------------------------------------------------------------------
# B5.1 — Wave 0 short-circuit paths
# ---------------------------------------------------------------------------


def test_process_item_short_circuits_on_bad_data_quality(bag, monkeypatch):
    """If evaluate_data_quality returns != 'ok', no LLM calls fire and
    processing_status flips to data_quality_skipped."""
    from docket.ai import pipeline

    # Patch wave0 to return a non-ok quality regardless of input.
    monkeypatch.setattr(
        "docket.ai.pipeline.evaluate_data_quality",
        lambda item: ("no_agenda_text", "low"),
    )

    # Spy LLM calls — should NEVER fire.
    extract_calls = []
    rewrite_calls = []
    monkeypatch.setattr(
        "docket.ai.pipeline.extract_facts_for_item",
        lambda *a, **kw: extract_calls.append(a) or (_sample_facts(), "haiku-4-5"),
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.rewrite_item",
        lambda *a, **kw: rewrite_calls.append(a) or (_substantive_rewrite(), "haiku-4-5"),
    )

    m = bag.add_meeting()
    iid = bag.add_pending_item(m, title="short title")
    item = _ItemView(_load_item(iid))

    status = pipeline.process_item(item)
    assert status == "data_quality_skipped"
    assert extract_calls == []
    assert rewrite_calls == []

    final = _load_item(iid)
    assert final["processing_status"] == "data_quality_skipped"
    assert final["data_quality"] == "no_agenda_text"
```

- [ ] **Step 1.3: Run, confirm ImportError**

Run: `cd ~/docket-pub-integration && venv/bin/pytest tests/integration/test_pipeline_e2e.py::test_process_item_short_circuits_on_bad_data_quality -xvs`

Expected: `ModuleNotFoundError: No module named 'docket.ai.pipeline'`.

- [ ] **Step 1.4: Create `pipeline.py` skeleton + Wave 0 short-circuit**

Create `src/docket/ai/pipeline.py`:

```python
"""Per-item pipeline orchestrator — Tracks 1+2+3 convergence (Task B5).

Wraps the full v3 pipeline for a single agenda item:

  Wave 0 (data_quality + procedural pre-pass, no LLM)
   → Stage 1 (extraction.extract_facts_for_item — Haiku 4.5 tool-use)
   → Stage 2 (rewrite.rewrite_item — Haiku 4.5 tool-use)
   → Stage 2.5 (floors.apply_score_floors — deterministic post-pass)
   → reconcile (reconcile.reconcile_stages with auto-retry once)
   → atomic commit (extraction + rewrite + scores + on-write badges + policy badges)

Two exported entry points:

- ``process_item(item) -> str`` — full pipeline, used by the v3 worker
  (``_process_items_v3``) when ``IMPACT_FIRST_ENABLED=true``.
- ``_rerun_from_stage2(item, facts, *, override_instruction=None) -> str``
  — partial pipeline starting at Stage 2, used by:
    1. ``process_item`` itself (after Stage 1 returns); and
    2. G4's ``services/conflict_resolution`` admin actions
       (``re_prompt_stage_2``, ``edit_stage_1_facts``) when admins request a
       Stage 2 re-run with override.

The split exists because G4 ships the conflict-resolution UI before B5
exists, and G4's resolution actions operate on items that already have
Stage 1 facts persisted. ``_rerun_from_stage2`` lets the admin paths
skip Stage 1 (which would otherwise overwrite their carefully-edited
facts).

Transaction shape:
- Phase A (DB write, short): Wave 0 short-circuit only — sets
  processing_status to data_quality_skipped / procedural_skipped.
- Phase B (no held DB connection): LLM calls (Stage 1, Stage 2,
  optional Stage 2 retry) + CPU (floors, reconcile). A single brief
  cursor opens during Stage 2.5 floors for the per-city threshold
  override lookup; the cursor closes before Stage 2 or any retry runs.
- Phase C (atomic DB write): single transaction commits extraction +
  rewrite + scores + on-write process badges + policy badges + final
  processing_status.

If any step in Phase B raises (AIRateLimited, AITransientError,
network), no row state changes — Stage 1's cost is wasted on retry.
This is the all-or-none design from plan §B5 decision (alternative:
persist Stage 1 immediately is a documented trade-off; not chosen for
v1).

Spec: docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md
sections 1, 3, 7.5; decisions #45, #57, #92.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from docket.ai.extraction import (
    EXTRACTION_PROMPT_VERSION,
    extract_facts_for_item,
    persist_extraction,
)
from docket.ai.extraction_schema import StructuredFacts
from docket.ai.floors import apply_score_floors
from docket.ai.reconcile import reconcile_stages
from docket.ai.rewrite import ITEM_REWRITE_PROMPT_VERSION, rewrite_item
from docket.ai.rewrite_schema import ItemRewrite
from docket.ai.wave0 import evaluate_data_quality, is_procedural
from docket.ai.badges_process import compute_on_write_process_badges
from docket.ai.badges_policy import compute_policy_badges
from docket.db import db
from docket.services.badges import get_enabled_policy_slugs

log = logging.getLogger(__name__)


class PipelineConcurrencyError(RuntimeError):
    """Raised by ``_rerun_from_stage2`` when the optional ``expected_status``
    guard fires: the row's ``processing_status`` changed between the caller's
    read and the pipeline's Phase C UPDATE, and the pipeline declined to
    overwrite. The Phase C transaction rolls back via this exception's exit
    from the ``with db()`` block — no partial writes.

    Worker path passes ``expected_status=None`` (it holds the per-row
    FOR UPDATE SKIP LOCKED lock for the duration of the transaction, so the
    race window doesn't exist). Admin paths in
    ``services/conflict_resolution.py`` pass
    ``expected_status='cross_stage_conflict'`` and catch this exception,
    write a ``*_lost_race`` audit row, and re-raise as
    ``ConflictAlreadyResolvedError`` for the route layer. Decision #13.
    """


def process_item(item) -> str:
    """Run the full per-item v3 pipeline against an agenda item.

    Args:
        item: duck-typed object exposing:
            - id (int)
            - city_id (int) — from joined meetings.municipality_id
            - city_name (str) — from joined municipalities.name
            - title, description, sponsor, dollars_amount (per Stage 2 prompt)
            - topic, is_consent, source_type (per Stage 2 prompt)
            See ``_ItemView`` in tests/integration/test_pipeline_e2e.py
            for the test-side adapter; the v3 worker constructs an
            equivalent shape from claim_items_v3_sql rows.

    Returns:
        Final ``processing_status`` value (one of):
          - 'data_quality_skipped'  (Wave 0a rejected)
          - 'procedural_skipped'    (Wave 0b matched)
          - 'completed'             (Stage 1+2 + reconcile success)
          - 'cross_stage_conflict'  (reconcile escalated after retry)

    Raises:
        - ``AIRateLimited``, ``AITransientError`` — bubble from
          extract_facts_for_item / rewrite_item; worker handles per-item
          recovery (skip + log) per its existing patterns.
        - ``AIFatalError`` — bubble; worker stops the batch.
        - ``AIPermanentRowError`` — bubble; worker marks the row as
          failed_permanent.
    """
    # Phase A — Wave 0 short-circuit ----------------------------------
    quality, priority = evaluate_data_quality(item)
    if quality != "ok":
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE agenda_items
                   SET data_quality       = %s::data_quality_enum,
                       data_debt_priority = %s::data_debt_priority_enum,
                       processing_status  = 'data_quality_skipped'::processing_status_enum
                 WHERE id = %s
                """,
                (quality, priority, item.id),
            )
        log.info(
            "pipeline.process_item Wave 0a reject: item_id=%s quality=%s",
            item.id, quality,
        )
        return "data_quality_skipped"

    if is_procedural(item.title):
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE agenda_items
                   SET data_quality      = 'ok'::data_quality_enum,
                       processing_status = 'procedural_skipped'::processing_status_enum
                 WHERE id = %s
                """,
                (item.id,),
            )
        log.info(
            "pipeline.process_item Wave 0b match: item_id=%s",
            item.id,
        )
        return "procedural_skipped"

    # Phase B (part 1) — Stage 1 extraction (LLM) ---------------------
    facts, _served_extract = extract_facts_for_item(item)

    # Delegate to _rerun_from_stage2 for the rest of the pipeline.
    # Keeps the Stage 2+ code path identical between the worker's
    # full-pipeline call and the G4 conflict-resolution admin paths.
    return _rerun_from_stage2(item, facts)


def _rerun_from_stage2(
    item,
    facts: StructuredFacts,
    *,
    override_instruction: str | None = None,
    expected_status: str | None = None,
) -> str:
    """Run Stage 2 → 2.5 → reconcile → atomic commit.

    Used by:
      - ``process_item`` after Stage 1 succeeds (no override, no guard).
      - G4's conflict-resolution admin actions ``re_prompt_stage_2``
        and ``edit_stage_1_facts`` (with admin override instruction
        AND expected_status='cross_stage_conflict' for the concurrency
        guard).

    Args:
        item: as ``process_item``.
        facts: Stage 1 ``StructuredFacts`` — either freshly extracted
            or admin-edited.
        override_instruction: optional admin override appended to the
            Stage 2 user message. None for the worker's happy path;
            the instruction text for admin re-prompts.
        expected_status: optional concurrency guard (decision #13).
            When None (worker path), Phase C UPDATE runs unconditionally
            — safe because the worker holds the per-row SKIP LOCKED
            lock. When a string (admin paths), Phase C UPDATE adds
            ``AND processing_status = %s`` as a guard; if cur.rowcount
            is 0, the function raises ``PipelineConcurrencyError``
            and Phase C's transaction rolls back via the ``with db()``
            exception path — no partial writes.

    Returns:
        Final ``processing_status`` value: 'completed' or 'cross_stage_conflict'.

    Raises:
        - ``PipelineConcurrencyError`` — when ``expected_status`` was
          supplied and the row's actual status no longer matches.
          Phase C's whole transaction (including persist_extraction)
          rolls back; no writes commit.
        - Anthropic SDK exceptions (``AIRateLimited``, etc.) — bubble.
    """
    enabled_slugs = list(get_enabled_policy_slugs(item.city_id))

    # Phase B (part 2) — Stage 2 rewrite (LLM) ------------------------
    rewrite, _served_rewrite = rewrite_item(
        item, facts, enabled_slugs,
        extra_instruction=override_instruction,
    )

    # Phase B (part 3) — Stage 2.5 floors (CPU + brief DB) ------------
    # apply_score_floors needs a cursor for per-city threshold overrides
    # (city_score_floor_overrides table). Brief, non-LLM-spanning DB use.
    with db() as conn, conn.cursor() as cur:
        overrides = apply_score_floors(cur, item, facts, rewrite, item.city_id)

    # Phase B (part 4) — Reconcile (CPU, possibly one LLM retry) ------
    result = reconcile_stages(facts, rewrite, item, already_retried=False)
    if result.action == "retry_stage2_with_override":
        # Auto-retry once with the reconcile-generated override.
        # (Decision #45 — the worker auto-retry path.)
        rewrite, _served_retry = rewrite_item(
            item, facts, enabled_slugs,
            extra_instruction=result.override_instruction,
        )
        with db() as conn, conn.cursor() as cur:
            overrides = apply_score_floors(
                cur, item, facts, rewrite, item.city_id,
            )
        result = reconcile_stages(facts, rewrite, item, already_retried=True)

    final_status = (
        "cross_stage_conflict"
        if result.action == "mark_cross_stage_conflict"
        else "completed"
    )

    # Phase C — Atomic commit -----------------------------------------
    overrides_jsonb = json.dumps({
        "conflicts": result.conflicts,
        "original_ai_significance": overrides.original_ai_significance,
        "final_significance": overrides.final_significance,
        "original_ai_consent": overrides.original_ai_consent,
        "final_consent": overrides.final_consent,
        "triggers": overrides.triggers,
        "admin_override_used": override_instruction is not None,
    })

    with db() as conn, conn.cursor() as cur:
        persist_extraction(cur, item.id, facts, version=EXTRACTION_PROMPT_VERSION)

        # Phase C UPDATE with optional concurrency guard (decision #13).
        # The `(%s::text IS NULL OR processing_status = %s)` predicate
        # is a no-op when expected_status is None (worker path) and a
        # hard guard when expected_status is supplied (admin paths).
        cur.execute(
            """
            UPDATE agenda_items
               SET headline                = %s,
                   why_it_matters          = %s,
                   significance_score      = %s,
                   consent_placement_score = %s,
                   ai_confidence           = %s,
                   ai_rewrite_version      = %s,
                   score_overrides         = %s::jsonb,
                   processing_status       = %s::processing_status_enum
             WHERE id = %s
               AND (%s::text IS NULL OR processing_status = %s::processing_status_enum)
            """,
            (
                rewrite.headline,
                rewrite.why_it_matters,
                overrides.final_significance,
                overrides.final_consent,
                rewrite.confidence,
                ITEM_REWRITE_PROMPT_VERSION,
                overrides_jsonb,
                final_status,
                item.id,
                expected_status,
                expected_status,
            ),
        )

        if expected_status is not None and cur.rowcount == 0:
            # Concurrency guard fired. Roll back the whole Phase C
            # (including persist_extraction's write) by raising — the
            # `with db()` context manager catches and rolls back.
            log.info(
                "pipeline._rerun_from_stage2 concurrency guard fired: "
                "item_id=%s expected_status=%s — rolling back Phase C",
                item.id, expected_status,
            )
            raise PipelineConcurrencyError(
                f"item {item.id} status no longer matches "
                f"expected_status={expected_status!r}; Phase C rolled back"
            )

        # On-write process badges (decision #57: SQL + on-write must agree).
        # Decision #92: include city_id in every INSERT.
        for slug, conf in compute_on_write_process_badges(
            item, facts, overrides, rewrite.confidence,
        ):
            cur.execute(
                """
                INSERT INTO agenda_item_badges
                  (agenda_item_id, city_id, badge_slug, kind, confidence,
                   source, matching_metadata)
                VALUES (%s, %s, %s, 'process', %s, 'deterministic', '{}'::jsonb)
                ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING
                """,
                (item.id, item.city_id, slug, conf),
            )

        # Policy badges (deterministic + LLM-suggested per Section D).
        for slug, conf, source, metadata in compute_policy_badges(
            item, facts, rewrite, item.city_id,
        ):
            cur.execute(
                """
                INSERT INTO agenda_item_badges
                  (agenda_item_id, city_id, badge_slug, kind, confidence,
                   source, matching_metadata)
                VALUES (%s, %s, %s, 'policy', %s, %s, %s::jsonb)
                ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING
                """,
                (item.id, item.city_id, slug, conf, source, json.dumps(metadata)),
            )

    log.info(
        "pipeline._rerun_from_stage2 done: item_id=%s status=%s override=%s",
        item.id, final_status, override_instruction is not None,
    )
    return final_status
```

- [ ] **Step 1.5: Re-run test, confirm pass**

Run: `cd ~/docket-pub-integration && venv/bin/pytest tests/integration/test_pipeline_e2e.py::test_process_item_short_circuits_on_bad_data_quality -xvs`

Expected: PASS.

- [ ] **Step 1.6: Add Wave 0 procedural short-circuit test**

Append:

```python
def test_process_item_short_circuits_on_procedural_title(bag, monkeypatch):
    """Wave 0b: title matches PROCEDURAL_TITLE_PATTERNS → no LLM calls."""
    from docket.ai import pipeline

    monkeypatch.setattr(
        "docket.ai.pipeline.evaluate_data_quality",
        lambda item: ("ok", "normal"),
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.is_procedural",
        lambda title: True,
    )
    extract_calls = []
    rewrite_calls = []
    monkeypatch.setattr(
        "docket.ai.pipeline.extract_facts_for_item",
        lambda *a, **kw: extract_calls.append(a) or (_sample_facts(), "haiku-4-5"),
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.rewrite_item",
        lambda *a, **kw: rewrite_calls.append(a) or (_substantive_rewrite(), "haiku-4-5"),
    )

    m = bag.add_meeting()
    iid = bag.add_pending_item(m, title="Pledge of Allegiance")
    item = _ItemView(_load_item(iid))

    status = pipeline.process_item(item)
    assert status == "procedural_skipped"
    assert extract_calls == []
    assert rewrite_calls == []

    final = _load_item(iid)
    assert final["processing_status"] == "procedural_skipped"
```

- [ ] **Step 1.7: Add happy-path test (Stage 1 + 2 → completed + badges)**

Append:

```python
# ---------------------------------------------------------------------------
# B5.2 — Full happy path: Stage 1 + 2 → completed + on-write badges
# ---------------------------------------------------------------------------


def test_process_item_happy_path_completes_and_writes_badges(bag, monkeypatch):
    """Wave 0 'ok' + non-procedural + substantive Stage 2 + reconcile
    accept → status='completed', headline/why_it_matters populated,
    score_overrides JSONB written, on-write badges land."""
    from docket.ai import pipeline

    monkeypatch.setattr(
        "docket.ai.pipeline.evaluate_data_quality",
        lambda item: ("ok", "normal"),
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.is_procedural",
        lambda title: False,
    )

    # Facts: counterparty + competitive procurement → no badges from
    # this dimension. We add settlement separately to fire
    # legal_settlement badge.
    settlement_facts_dict = {
        **SAMPLE_FACTS_DICT,
        "action_type": "settlement",
    }
    settlement_facts = StructuredFacts.model_validate(settlement_facts_dict)
    monkeypatch.setattr(
        "docket.ai.pipeline.extract_facts_for_item",
        lambda *a, **kw: (settlement_facts, "claude-haiku-4-5-20251001"),
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.rewrite_item",
        lambda *a, **kw: (_substantive_rewrite(), "claude-haiku-4-5-20251001"),
    )

    m = bag.add_meeting()
    iid = bag.add_pending_item(
        m,
        title="Authorize $250K settlement to claimant",
        dollars_amount=250_000,
    )
    item = _ItemView(_load_item(iid))

    status = pipeline.process_item(item)
    assert status == "completed"

    final = _load_item(iid)
    assert final["processing_status"] == "completed"
    assert final["headline"] == "Council awards $75K janitorial contract"
    assert final["why_it_matters"] == \
        "Renews custodial services across 12 city buildings."
    # Stage 2.5 floor for "any_settlement" fires at min 6.
    # Original score 4.0 < 6, so final should be 6.
    assert int(final["significance_score"]) >= 6
    # Score overrides JSONB written with triggers.
    assert final["score_overrides"] is not None
    assert "triggers" in final["score_overrides"]

    badges = _read_badges(iid)
    slugs = {b[0] for b in badges}
    assert "legal_settlement" in slugs  # fires on action_type='settlement'
    # All badges carry city_id (decision #92).
    for badge in badges:
        assert badge[4] == bag.city_id
```

- [ ] **Step 1.8: Add reconcile-retry-succeeds test**

Append:

```python
# ---------------------------------------------------------------------------
# B5.3 — Reconcile auto-retry paths
# ---------------------------------------------------------------------------


def test_process_item_reconcile_retry_resolves_on_second_attempt(
    bag, monkeypatch,
):
    """Stage 1 finds substance, Stage 2 first says procedural →
    reconcile fires retry_stage2_with_override → Stage 2 second call
    returns substantive → reconcile accepts → status='completed'.
    Two rewrite_item calls fired; final state shows substantive."""
    from docket.ai import pipeline

    monkeypatch.setattr(
        "docket.ai.pipeline.evaluate_data_quality",
        lambda item: ("ok", "normal"),
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.is_procedural",
        lambda title: False,
    )
    # Stage 1 returns settlement facts — substantial enough that
    # Stage 2 saying procedural triggers reconcile conflict.
    settlement_facts = StructuredFacts.model_validate({
        **SAMPLE_FACTS_DICT, "action_type": "settlement",
    })
    monkeypatch.setattr(
        "docket.ai.pipeline.extract_facts_for_item",
        lambda *a, **kw: (settlement_facts, "haiku-4-5"),
    )
    # First rewrite call: procedural. Second rewrite call: substantive.
    rewrite_call_count = [0]
    def _flipping_rewrite(*args, **kwargs):
        rewrite_call_count[0] += 1
        if rewrite_call_count[0] == 1:
            return (_procedural_rewrite(), "haiku-4-5")
        return (_substantive_rewrite(), "haiku-4-5")
    monkeypatch.setattr(
        "docket.ai.pipeline.rewrite_item", _flipping_rewrite,
    )

    m = bag.add_meeting()
    iid = bag.add_pending_item(m, dollars_amount=250_000)
    item = _ItemView(_load_item(iid))

    status = pipeline.process_item(item)
    assert status == "completed"
    assert rewrite_call_count[0] == 2  # one retry fired

    final = _load_item(iid)
    assert final["processing_status"] == "completed"
    assert final["headline"] is not None


def test_process_item_reconcile_escalates_after_second_failure(
    bag, monkeypatch,
):
    """Both rewrite_item attempts return procedural; reconcile
    escalates to cross_stage_conflict; final state has NO headline +
    is in conflict; score_overrides carries the conflict reasons."""
    from docket.ai import pipeline

    monkeypatch.setattr(
        "docket.ai.pipeline.evaluate_data_quality",
        lambda item: ("ok", "normal"),
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.is_procedural",
        lambda title: False,
    )
    settlement_facts = StructuredFacts.model_validate({
        **SAMPLE_FACTS_DICT, "action_type": "settlement",
    })
    monkeypatch.setattr(
        "docket.ai.pipeline.extract_facts_for_item",
        lambda *a, **kw: (settlement_facts, "haiku-4-5"),
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.rewrite_item",
        lambda *a, **kw: (_procedural_rewrite(), "haiku-4-5"),
    )

    m = bag.add_meeting()
    iid = bag.add_pending_item(m, dollars_amount=250_000)
    item = _ItemView(_load_item(iid))

    status = pipeline.process_item(item)
    assert status == "cross_stage_conflict"

    final = _load_item(iid)
    assert final["processing_status"] == "cross_stage_conflict"
    # Stage 2 was procedural — headline/why_it_matters are None.
    assert final["headline"] is None
    assert final["why_it_matters"] is None
    # Score overrides carries conflict reasons.
    assert final["score_overrides"]["conflicts"]
    assert any(
        "stage2_procedural" in c
        for c in final["score_overrides"]["conflicts"]
    )
```

- [ ] **Step 1.9: Add `_rerun_from_stage2` test (the G4-shared partial path)**

Append:

```python
# ---------------------------------------------------------------------------
# B5.4 — _rerun_from_stage2 (partial-rerun helper for G4)
# ---------------------------------------------------------------------------


def test_rerun_from_stage2_skips_stage1_and_persists(bag, monkeypatch):
    """G4 path: caller supplies facts; pipeline runs Stage 2+ only and
    persists. extract_facts_for_item must NOT be called."""
    from docket.ai import pipeline

    extract_calls = []
    monkeypatch.setattr(
        "docket.ai.pipeline.extract_facts_for_item",
        lambda *a, **kw: extract_calls.append(a) or (None, None),
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.rewrite_item",
        lambda *a, **kw: (_substantive_rewrite(), "haiku-4-5"),
    )

    m = bag.add_meeting()
    iid = bag.add_pending_item(m)
    item = _ItemView(_load_item(iid))

    facts = _sample_facts()  # caller-supplied (e.g., admin-edited)
    status = pipeline._rerun_from_stage2(item, facts)
    assert status == "completed"
    assert extract_calls == []  # Stage 1 was skipped

    final = _load_item(iid)
    assert final["processing_status"] == "completed"
    assert final["extracted_facts"] is not None


def test_rerun_from_stage2_passes_override_instruction_to_stage2(
    bag, monkeypatch,
):
    """G4 re-prompt path: override_instruction reaches rewrite_item."""
    from docket.ai import pipeline

    monkeypatch.setattr(
        "docket.ai.pipeline.extract_facts_for_item",
        lambda *a, **kw: (None, None),
    )
    rewrite_kwargs_captured = []
    def _capture_rewrite(*args, **kwargs):
        rewrite_kwargs_captured.append(kwargs)
        return (_substantive_rewrite(), "haiku-4-5")
    monkeypatch.setattr(
        "docket.ai.pipeline.rewrite_item", _capture_rewrite,
    )

    m = bag.add_meeting()
    iid = bag.add_pending_item(m)
    item = _ItemView(_load_item(iid))
    facts = _sample_facts()

    pipeline._rerun_from_stage2(
        item, facts,
        override_instruction="This IS substantive — a contract award.",
    )
    assert rewrite_kwargs_captured
    assert rewrite_kwargs_captured[0].get("extra_instruction") == \
        "This IS substantive — a contract award."
```

- [ ] **Step 1.9b: Add `expected_status` concurrency-guard tests**

Append:

```python
# ---------------------------------------------------------------------------
# B5.4b — expected_status concurrency guard (decision #13)
# ---------------------------------------------------------------------------


def test_rerun_from_stage2_no_guard_passes_unconditionally(bag, monkeypatch):
    """Worker path: expected_status=None, UPDATE runs unconditionally
    even if the row's actual processing_status differs."""
    from docket.ai import pipeline

    monkeypatch.setattr(
        "docket.ai.pipeline.rewrite_item",
        lambda *a, **kw: (_substantive_rewrite(), "haiku-4-5"),
    )

    m = bag.add_meeting()
    iid = bag.add_pending_item(m)
    # Force the row out of 'pending' to simulate a state where the
    # worker would normally never reach this code — but with no guard,
    # the pipeline writes regardless.
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE agenda_items SET processing_status = 'completed'::processing_status_enum WHERE id = %s",
            (iid,),
        )
    item = _ItemView(_load_item(iid))
    facts = _sample_facts()

    status = pipeline._rerun_from_stage2(item, facts)  # no guard
    assert status == "completed"

    final = _load_item(iid)
    # Pipeline wrote unconditionally — the row's rewrite columns are populated.
    assert final["headline"] is not None


def test_rerun_from_stage2_guard_raises_when_status_mismatch(bag, monkeypatch):
    """Admin path: expected_status='cross_stage_conflict', actual status
    is 'completed' → PipelineConcurrencyError raised; transaction rolls
    back; no writes commit."""
    from docket.ai import pipeline

    monkeypatch.setattr(
        "docket.ai.pipeline.rewrite_item",
        lambda *a, **kw: (_substantive_rewrite(), "haiku-4-5"),
    )

    m = bag.add_meeting()
    iid = bag.add_pending_item(m)
    # Item is in 'pending', NOT 'cross_stage_conflict'.
    item = _ItemView(_load_item(iid))
    facts = _sample_facts()

    with pytest.raises(pipeline.PipelineConcurrencyError):
        pipeline._rerun_from_stage2(
            item, facts,
            expected_status="cross_stage_conflict",
        )

    final = _load_item(iid)
    # Phase C rolled back: row's state is unchanged from pre-call.
    assert final["headline"] is None
    assert final["processing_status"] == "pending"
    # No badges were written.
    assert _read_badges(iid) == []


def test_rerun_from_stage2_guard_allows_match(bag, monkeypatch):
    """Admin path happy: expected_status='cross_stage_conflict' AND
    actual matches → pipeline proceeds normally."""
    from docket.ai import pipeline

    monkeypatch.setattr(
        "docket.ai.pipeline.rewrite_item",
        lambda *a, **kw: (_substantive_rewrite(), "haiku-4-5"),
    )

    m = bag.add_meeting()
    iid = bag.add_pending_item(m)
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE agenda_items SET processing_status = 'cross_stage_conflict'::processing_status_enum WHERE id = %s",
            (iid,),
        )
    item = _ItemView(_load_item(iid))
    facts = _sample_facts()

    status = pipeline._rerun_from_stage2(
        item, facts,
        expected_status="cross_stage_conflict",
    )
    assert status == "completed"

    final = _load_item(iid)
    assert final["processing_status"] == "completed"
    assert final["headline"] is not None
```

- [ ] **Step 1.10: Run all Task 1 tests, confirm 9 pass (6 base + 3 guard)**

Run: `cd ~/docket-pub-integration && venv/bin/pytest tests/integration/test_pipeline_e2e.py -v 2>&1 | tail -15`

Expected: **9 PASS** (6 base + 3 expected_status guard tests), 0 FAIL.

- [ ] **Step 1.11: Commit**

```bash
cd ~/docket-pub-integration
git add src/docket/ai/pipeline.py tests/integration/test_pipeline_e2e.py
git commit -m "feat(ai): pipeline.process_item orchestrator (Wave 0 → Stage 1 → 2 → 2.5 → reconcile → atomic commit)"
```

---

## Task 2: `IMPACT_FIRST_ENABLED` flag + worker `_process_items_v3` + dispatch

**Files:**
- Modify: `src/docket/config.py` (+1 line)
- Modify: `src/docket/ai/worker.py` (+~80 lines)
- Test: `tests/integration/test_worker_v3_dispatch.py` (NEW)

- [ ] **Step 2.1: Write failing test for flag-gated dispatch**

Create `tests/integration/test_worker_v3_dispatch.py`:

```python
"""Integration tests for B5 — worker dispatch via IMPACT_FIRST_ENABLED.

Confirms that ``run_once(stage="items", ...)`` routes to:
  - ``_process_items_v3`` when ``IMPACT_FIRST_ENABLED=True``
  - ``_process_items`` (v2 legacy) when ``False`` (default)

Tests the gating, not the orchestration itself (Task 1 covers that).
"""

from __future__ import annotations

import pytest

from docket.config import DATABASE_URL


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run B5 worker-dispatch tests against Railway DB.",
)


def test_run_once_dispatches_to_v3_when_flag_enabled(monkeypatch):
    """IMPACT_FIRST_ENABLED=True routes to _process_items_v3."""
    from docket.ai import worker

    v2_calls = []
    v3_calls = []
    monkeypatch.setattr(worker, "IMPACT_FIRST_ENABLED", True)
    monkeypatch.setattr(
        worker, "_process_items",
        lambda *a, **kw: v2_calls.append(("v2", a, kw)),
    )
    monkeypatch.setattr(
        worker, "_process_items_v3",
        lambda *a, **kw: v3_calls.append(("v3", a, kw)),
    )
    # Prevent budget gate from interfering.
    monkeypatch.setattr(worker, "_today_spend", lambda conn: 0.0)
    # Mock the AI client factory to avoid network.
    monkeypatch.setattr(worker, "_make_client", lambda: None)

    worker.run_once(stage="items", limit=10, notes="test_v3_dispatch")
    assert len(v3_calls) == 1
    assert len(v2_calls) == 0


def test_run_once_dispatches_to_v2_when_flag_disabled(monkeypatch):
    """Default (IMPACT_FIRST_ENABLED=False) routes to legacy v2 worker."""
    from docket.ai import worker

    v2_calls = []
    v3_calls = []
    monkeypatch.setattr(worker, "IMPACT_FIRST_ENABLED", False)
    monkeypatch.setattr(
        worker, "_process_items",
        lambda *a, **kw: v2_calls.append(("v2", a, kw)),
    )
    monkeypatch.setattr(
        worker, "_process_items_v3",
        lambda *a, **kw: v3_calls.append(("v3", a, kw)),
    )
    monkeypatch.setattr(worker, "_today_spend", lambda conn: 0.0)
    monkeypatch.setattr(worker, "_make_client", lambda: None)

    worker.run_once(stage="items", limit=10, notes="test_v2_dispatch")
    assert len(v2_calls) == 1
    assert len(v3_calls) == 0


def test_run_once_dispatch_preserves_meeting_path(monkeypatch):
    """Flag only affects 'items' stage. 'meetings' always uses v2 path."""
    from docket.ai import worker

    meetings_calls = []
    monkeypatch.setattr(worker, "IMPACT_FIRST_ENABLED", True)
    monkeypatch.setattr(
        worker, "_process_meetings",
        lambda *a, **kw: meetings_calls.append(("m", a, kw)),
    )
    monkeypatch.setattr(worker, "_today_spend", lambda conn: 0.0)
    monkeypatch.setattr(worker, "_make_client", lambda: None)

    worker.run_once(stage="meetings", limit=5, notes="test_meeting_passthrough")
    assert len(meetings_calls) == 1


def test_run_once_v3_dispatch_does_not_construct_ai_client(monkeypatch):
    """v3 path doesn't need an AIClient (extract/rewrite create their
    own anthropic_client at module level). Confirm _make_client is
    NOT invoked when v3 is chosen."""
    from docket.ai import worker

    client_factory_calls = []
    monkeypatch.setattr(worker, "IMPACT_FIRST_ENABLED", True)
    monkeypatch.setattr(
        worker, "_make_client",
        lambda: client_factory_calls.append("called") or None,
    )
    monkeypatch.setattr(worker, "_today_spend", lambda conn: 0.0)
    monkeypatch.setattr(worker, "_process_items_v3", lambda *a, **kw: None)
    monkeypatch.setattr(worker, "_process_meetings", lambda *a, **kw: None)

    worker.run_once(stage="items", limit=10, notes="test_v3_no_client")
    # Optional: this assertion documents the design choice. If the
    # implementer prefers to always construct the client (for
    # consistency with v2), flip to assert len(client_factory_calls)==1.
    assert client_factory_calls == [], (
        "v3 path should not construct AIClient (extract/rewrite have "
        "their own module-level clients)"
    )
```

- [ ] **Step 2.2: Run, confirm fail**

Run: `venv/bin/pytest tests/integration/test_worker_v3_dispatch.py -xvs 2>&1 | tail -15`

Expected: fails on `IMPACT_FIRST_ENABLED` and `_process_items_v3` not existing.

- [ ] **Step 2.3: Add the flag to `config.py`**

Open `src/docket/config.py`. Add after the existing `ANTHROPIC_API_KEY` declaration:

```python
# Decision #45 + plan §FINAL-3: the IMPACT_FIRST_ENABLED flag gates the
# v3 worker path. When False (default), the worker runs the legacy v2
# pipeline (Haiku item summaries + Sonnet meeting executives). When
# True, the items task uses pipeline.process_item (Wave 0 → Stage 1 →
# 2 → 2.5 → reconcile → atomic commit + on-write badges). Meeting
# summaries continue to use v2 until decision #93 / Phase 2 SMART_BREVITY_UI
# wires the citizen rendering switch.
IMPACT_FIRST_ENABLED: bool = (
    os.environ.get("IMPACT_FIRST_ENABLED", "false").lower() == "true"
)
```

- [ ] **Step 2.4: Add `_process_items_v3` + `claim_items_v3_sql` + dispatch to `worker.py`**

In `src/docket/ai/worker.py`:

(a) At the top, add:

```python
from docket.config import IMPACT_FIRST_ENABLED
```

(b) Add a new SQL helper next to `claim_items_sql`:

```python
def claim_items_v3_sql() -> str:
    """Claim items for v3 pipeline processing.

    v3 filters on processing_status + the extraction/rewrite version
    columns — NOT on the v2 ai_prompt_version column. SELECT FOR UPDATE
    SKIP LOCKED ensures multiple workers don't double-process.

    Decision #45 + plan §B5: items in 'pending' state are eligible. Items
    in 'cross_stage_conflict' are NOT picked up — they wait for admin
    resolution via the G4 review UI.

    NOTE: this helper does NOT enforce a debounce equivalent to v2's
    AI_ITEM_DEBOUNCE_MINUTES. The v3 pipeline's expectation is that
    Phase 1's Wave 0 pre-classifier sets processing_status='pending'
    only for items that survived data-quality + procedural gates — i.e.,
    a debounce isn't needed because the eligibility filter is precise.
    If a debounce is wanted later, add it.
    """
    return """
        SELECT ai.id, ai.meeting_id, ai.title, ai.description,
               ai.sponsor, ai.dollars_amount, ai.topic, ai.is_consent,
               ai.source_type,
               m.municipality_id AS city_id,
               muni.name         AS city_name
          FROM agenda_items ai
          JOIN meetings m ON m.id = ai.meeting_id
          JOIN municipalities muni ON muni.id = m.municipality_id
         WHERE ai.processing_status = 'pending'::processing_status_enum
           AND (
                ai.ai_extraction_version IS NULL
             OR ai.ai_extraction_version < %s
             OR ai.ai_rewrite_version IS NULL
             OR ai.ai_rewrite_version < %s
           )
         ORDER BY ai.id
         LIMIT %s
         FOR UPDATE OF ai SKIP LOCKED
    """
```

(c) Add `_process_items_v3` next to `_process_items`:

```python
def _process_items_v3(conn, limit: int, summary: RunSummary) -> None:
    """v3 per-item loop: calls pipeline.process_item per claimed row.

    Differs from v2 (_process_items):
      - No AIClient argument (extract/rewrite have module-level clients).
      - No usage tracking — v3 pipeline doesn't thread the Usage struct
        through extraction.py/rewrite.py yet (B5 v1 gap; flag as
        follow-up). summary.cost_usd stays at 0.0; summary.rows_processed
        counts items, summary.rows_failed counts permanent failures.
      - Per-row commit after pipeline.process_item returns. Lock from
        claim_items_v3_sql is held across the LLM calls (same shape
        as v2). Single-instance worker assumption preserved.

    Spec: section 7.5, decisions #45, #57.
    """
    from docket.ai import pipeline
    from docket.ai.extraction import EXTRACTION_PROMPT_VERSION
    from docket.ai.rewrite import ITEM_REWRITE_PROMPT_VERSION

    with conn.cursor() as cur:
        cur.execute(
            claim_items_v3_sql(),
            (EXTRACTION_PROMPT_VERSION, ITEM_REWRITE_PROMPT_VERSION, limit),
        )
        rows = cur.fetchall()

    columns = ["id", "meeting_id", "title", "description",
               "sponsor", "dollars_amount", "topic", "is_consent",
               "source_type", "city_id", "city_name"]

    for row in rows:
        row_dict = dict(zip(columns, row))
        # Duck-typed item — pipeline.process_item accepts any object
        # with the attributes documented in its docstring.
        item = _AttrAccess(row_dict)
        try:
            pipeline.process_item(item)
            summary.rows_processed += 1
            conn.commit()
        except AIRateLimited:
            log.warning("Rate limited; ending v3 batch")
            conn.rollback()
            break
        except AITransientError as e:
            log.warning("v3 transient error on item %s: %s", row_dict["id"], e)
            conn.rollback()
            continue
        except AIPermanentRowError as e:
            log.error("v3 permanent failure on item %s: %s", row_dict["id"], e)
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE agenda_items
                       SET processing_status = 'failed_permanent'::processing_status_enum,
                           last_error_at     = NOW(),
                           last_error_message = %s
                     WHERE id = %s
                    """,
                    (str(e)[:500], row_dict["id"]),
                )
            summary.rows_failed += 1
            conn.commit()
        except AIFatalError:
            log.critical("v3 fatal error; exiting")
            conn.rollback()
            raise


class _AttrAccess:
    """Lightweight dict → attribute access for pipeline.process_item.

    pipeline.process_item duck-types the item; this class adapts the
    claim_items_v3_sql row dict to that shape. Equivalent to the
    SimpleNamespace pattern but minimally scoped.
    """
    def __init__(self, d: dict):
        self.__dict__.update(d)
```

(d) Modify `run_once` dispatch. Find the existing block:

```python
        if stage == "items":
            _process_items(conn, client, limit, summary)
        else:
            _process_meetings(conn, client, limit, summary)
```

Replace with:

```python
        if stage == "items":
            if IMPACT_FIRST_ENABLED:
                _process_items_v3(conn, limit, summary)
            else:
                _process_items(conn, client, limit, summary)
        else:
            _process_meetings(conn, client, limit, summary)
```

(e) Note the `client = _make_client()` call at line ~267 is now wasted when `IMPACT_FIRST_ENABLED=True` AND `stage='items'`. Cheapest fix: lazy-construct only when needed. Move the line into the v2-only branch:

Replace:
```python
        client = _make_client()
```

With (preserving the original `client = _make_client()` site in run_once but guarding it):
```python
        # v2 needs an AIClient for both items + meetings; v3 (items
        # only) does not. Construct lazily so the v3 path doesn't
        # pay the import / API-key check.
        client = _make_client() if (stage == "meetings" or not IMPACT_FIRST_ENABLED) else None
```

- [ ] **Step 2.5: Run dispatch tests, confirm pass**

Run: `venv/bin/pytest tests/integration/test_worker_v3_dispatch.py -v 2>&1 | tail -10`

Expected: 4 PASS.

- [ ] **Step 2.6: Commit**

```bash
git add src/docket/config.py src/docket/ai/worker.py \
        tests/integration/test_worker_v3_dispatch.py
git commit -m "feat(worker): IMPACT_FIRST_ENABLED flag + _process_items_v3 dispatch"
```

---

## Task 3: Refactor G4 to delegate to `pipeline._rerun_from_stage2`

**Files:**
- Modify: `src/docket/services/conflict_resolution.py` (~-120 lines net)
- Test: `tests/integration/test_conflict_resolution.py` (no new tests; existing tests are the regression contract)

- [ ] **Step 3.1: Verify the existing G4 test suite passes pre-refactor**

Baseline run:
```bash
cd ~/docket-pub-integration
venv/bin/pytest tests/integration/test_conflict_resolution.py -v 2>&1 | tail -10
```

Expected: 45 PASS (the G4 fix-up count). Capture this baseline — Task 3's refactor MUST land with the same count post-refactor.

- [ ] **Step 3.2: Refactor `re_prompt_stage_2`**

In `src/docket/services/conflict_resolution.py`, find `re_prompt_stage_2` (around line 380-530). The function currently calls the local `_rerun_stage2` helper. Replace with a call to `pipeline._rerun_from_stage2`.

Original (sketch):
```python
def re_prompt_stage_2(item_id, *, override_instruction, actor):
    # ... validation, _load_conflict_item, Pydantic wrap ...
    outcome = _rerun_stage2(item, facts, override_instruction=override)
    # ... atomic commit + TOCTOU guard + audit ...
    return ResolutionResult(...)
```

The refactored version should keep:
- Length-cap validation on `override_instruction`
- `_load_conflict_item` + cross_stage_conflict gate
- Pydantic `StructuredFacts.model_validate` with try/except wrap (post-G4-fix-up)
- The TOCTOU guard pattern (cur.rowcount == 0 → lost race)
- The race-loss audit row

But replace the inner `_rerun_stage2` call with `pipeline._rerun_from_stage2(item_view, facts, override_instruction=override)`. The pipeline now owns: Stage 2 rewrite + Stage 2.5 floors + reconcile + the atomic persist of headline/why_it_matters/scores/badges.

**Subtle architectural change:** the pipeline's `_rerun_from_stage2` writes to `agenda_items` AND inserts process/policy badges in its own atomic block. G4's old `_rerun_stage2` returned a structured outcome and let `re_prompt_stage_2` do the write. Now the pipeline does the write, but the TOCTOU + audit must still fire correctly.

**Sequence for the refactored re_prompt_stage_2** (post-engineer-review with decision #13 concurrency guard):

1. Validate input + load item + load facts via existing logic (no change).
2. Call `pipeline._rerun_from_stage2(item_view, facts, override_instruction=override, expected_status='cross_stage_conflict')`. **Decision #13:** the `expected_status` arg gates the pipeline's Phase C UPDATE — if the row is no longer in `cross_stage_conflict`, the pipeline raises `PipelineConcurrencyError` and the whole Phase C (including persist_extraction's write) rolls back via the `with db()` context's exception handler.
3. Catch `PipelineConcurrencyError`: open a fresh transaction, read the current status, write a `re_prompt_stage2_lost_race` audit row, re-raise as `ConflictAlreadyResolvedError` so the existing admin route handler returns 409.
4. Happy path (no exception): read the post-pipeline status, write a `re_prompt_stage2` audit row.
5. Audit logging is now in a SEPARATE transaction from the pipeline's atomic write. This is acceptable because (a) the pipeline's transaction is the source-of-truth for the row state, and (b) the audit row's `to_status` reads from the post-pipeline state, so it never lies.

Apply the refactored function (replace the body, keep the docstring + signature):

```python
def re_prompt_stage_2(
    item_id: int,
    *,
    override_instruction: str,
    actor: str,
) -> ResolutionResult:
    """Admin writes a one-liner override; system re-runs Stage 2 via
    pipeline._rerun_from_stage2. The pipeline writes the resolution
    atomically; this function writes the audit trail.

    Post-B5: the Stage 2 + 2.5 + reconcile + persist path is centralized
    in docket.ai.pipeline. This function focuses on admin-action
    semantics: input validation, TOCTOU detection, audit logging.

    Raises:
        ConflictValidationError on input issues.
        ConflictAlreadyResolvedError on TOCTOU race-loss.
        LookupError when item is not in cross_stage_conflict.
    """
    override = override_instruction.strip()
    if len(override) < 1 or len(override) > OVERRIDE_INSTRUCTION_MAX:
        raise ConflictValidationError(
            f"override_instruction must be 1-{OVERRIDE_INSTRUCTION_MAX} chars"
        )

    # Phase 1: load item, validate facts.
    from pydantic import ValidationError as PydanticValidationError
    with db() as conn, conn.cursor() as cur:
        item_data = _load_conflict_item(cur, item_id)
        if item_data is None:
            raise LookupError(f"item {item_id} not in cross_stage_conflict")
        if item_data["extracted_facts"] is None:
            raise ConflictValidationError(
                "item has no extracted_facts — re_prompt_stage_2 needs Stage 1 facts"
            )
        try:
            facts = StructuredFacts.model_validate(item_data["extracted_facts"])
        except PydanticValidationError as e:
            raise ConflictValidationError(
                f"stored extracted_facts failed validation: {e}"
            )

    # Phase 2: call the pipeline with the concurrency guard (decision
    # #13). The pipeline's Phase C UPDATE has the
    # `AND processing_status = 'cross_stage_conflict'` predicate, so
    # if another admin resolved the row during our LLM call window,
    # the pipeline raises PipelineConcurrencyError and rolls back its
    # whole atomic block (extraction + rewrite + scores + badges).
    from docket.ai.pipeline import (
        PipelineConcurrencyError,
        _rerun_from_stage2,
    )
    item_view = _ItemAttrAdapter(item_data)
    try:
        pipeline_status = _rerun_from_stage2(
            item_view, facts,
            override_instruction=override,
            expected_status="cross_stage_conflict",
        )
    except PipelineConcurrencyError as e:
        # Race lost. Pipeline already rolled back; write the lost-race
        # audit in a fresh transaction so the trail survives.
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT processing_status::text FROM agenda_items WHERE id = %s",
                (item_id,),
            )
            row = cur.fetchone()
            current_status = row[0] if row else "unknown"
            _audit(
                cur, item_id,
                from_status=current_status,
                to_status=current_status,
                action="re_prompt_stage2_lost_race",
                actor=actor,
                payload={
                    "override_instruction": override,
                    "pipeline_error": str(e),
                    "actual_status_at_lost_race": current_status,
                },
            )
        log.info(
            "admin re_prompt_stage2 lost race: item_id=%s actor=%s "
            "current_status=%s",
            item_id, actor, current_status,
        )
        raise ConflictAlreadyResolvedError(
            f"item {item_id} was resolved by another admin "
            f"during the re-prompt (current status: {current_status})"
        )

    # Phase 3: pipeline succeeded — write the normal audit row.
    with db() as conn, conn.cursor() as cur:
        _audit(
            cur, item_id,
            from_status="cross_stage_conflict",
            to_status=pipeline_status,
            action="re_prompt_stage2",
            actor=actor,
            payload={
                "override_instruction": override,
                "pipeline_status": pipeline_status,
            },
        )

    log.info(
        "admin re_prompt_stage2: item_id=%s actor=%s status=%s",
        item_id, actor, pipeline_status,
    )
    return ResolutionResult(
        item_id=item_id,
        new_status=pipeline_status,
        action="re_prompt_stage2",
        success=(pipeline_status == "completed"),
        detail=(
            "Stage 2 re-ran with override; reconcile accepted."
            if pipeline_status == "completed" else
            "Stage 2 re-ran but reconcile still found conflicts. "
            "Try Edit Stage 1 facts or Accept Stage 2."
        ),
    )
```

- [ ] **Step 3.3: Refactor `edit_stage_1_facts` symmetrically**

Same pattern as re_prompt_stage_2 (Step 3.2), with three differences:

- **Pydantic on admin input, not stored:** `new_facts_json` is validated via `StructuredFacts.model_validate(...)` inside a `try` block; catch `pydantic.ValidationError` specifically (NOT bare `Exception` — same correctness as Step 3.2) and raise `ConflictValidationError`.
- **Early `extracted_facts` UPDATE keeps the G4 fix-up B-R1 TOCTOU guard.** Before calling the pipeline, persist the admin's corrected facts to the row inside a short transaction whose UPDATE includes `AND processing_status = 'cross_stage_conflict'`. If `cur.rowcount == 0`, write a `edit_stage1_facts_lost_race_pre_llm` audit row and raise `ConflictAlreadyResolvedError` — same pattern G4's fix-up established for catching the race BEFORE the LLM cost is spent.
- **Pipeline call:** `pipeline._rerun_from_stage2(item_view, validated_facts, expected_status='cross_stage_conflict')` (no `override_instruction`). The expected_status guard is the late-UPDATE TOCTOU protection; the early-UPDATE guard above is the pre-LLM TOCTOU protection. Both are needed — they protect different windows.
- **Audit action verb:** `edit_stage1_facts` on success, `edit_stage1_facts_lost_race` on late-UPDATE race-loss, `edit_stage1_facts_lost_race_pre_llm` on early-UPDATE race-loss.

(Implementer: the function body is structurally identical to Step 3.2's; just swap the verb and add the early UPDATE block before the pipeline call. The decision #13 `expected_status` arg is the same.)

- [ ] **Step 3.4: Delete the now-unused private helpers**

In `src/docket/services/conflict_resolution.py`:

- Delete `_rerun_stage2(...)` (lines ~347-431).
- Delete `_get_enabled_policy_slugs(...)` (lines ~90-110) — the pipeline now uses `services.badges.get_enabled_policy_slugs` directly.
- Delete `_ItemView` and `_RerunOutcome` dataclasses if they're only used by the deleted functions. **Keep** `_ItemAttrAdapter` (renamed from `_ItemView` if needed) — it's used by Step 3.2's pipeline call site to convert the loaded dict into duck-typed object access. Rename the class consistently if you keep it.
- Remove the imports that are no longer needed: `rewrite_item` (from `docket.ai.rewrite`), `apply_score_floors`, `reconcile_stages`. Keep `StructuredFacts` (still used in the validation pre-check).

- [ ] **Step 3.5: Re-run the G4 test suite — must still be 45 PASS**

```bash
cd ~/docket-pub-integration
venv/bin/pytest tests/integration/test_conflict_resolution.py -v 2>&1 | tail -10
```

Expected: **45 PASS, 0 FAIL.** If any test fails, the refactor changed observable behavior. Investigate before proceeding.

Likely flake points:
- Audit-row `from_status`: G4's old code wrote `from_status='cross_stage_conflict'` directly; the refactor writes whatever the pipeline ended up with. Test assertions should match — they assert `from_status='cross_stage_conflict'` AND `to_status='completed'`, both of which still hold.
- TOCTOU tests: the G4-fix-up TOCTOU tests monkeypatch `rewrite_item` and rely on the racing UPDATE firing INSIDE the mock. The refactored `re_prompt_stage_2` still calls `rewrite_item` (via the pipeline). The mock should still fire inside the LLM-call window. **Verify these tests pass without modification.**
- Audit `payload` shape: G4 carried specific keys like `reconcile_action`, `served_model`, `is_substantive`. The refactor's payload is now sparser (just `override_instruction` + `pipeline_status`). If G4 tests assert specific payload keys, the tests need updating OR the refactor should preserve those keys by reading them back from the pipeline's score_overrides write. **Pick one path** — recommend preserving by enriching the audit payload with the post-pipeline read (read back `score_overrides`, extract `conflicts`, include in audit). Adds ~5 lines but keeps the test contract.

- [ ] **Step 3.6: Commit**

```bash
git add src/docket/services/conflict_resolution.py
git commit -m "refactor(admin): G4 conflict-resolution delegates Stage 2 re-run to pipeline._rerun_from_stage2"
```

---

## Task 4: End-to-end integration test with badge contract verification

**Files:**
- Modify: `tests/integration/test_pipeline_e2e.py`

The Task 1 tests prove process_item works in isolation. Task 4 adds a denser integration test that exercises the full cross-track contract: Stage 1 facts that should fire specific badges, persisted with correct city_id (decision #92), with the expected score_overrides JSONB shape.

- [ ] **Step 4.1: Add cross-track contract tests**

Append to `tests/integration/test_pipeline_e2e.py`:

```python
# ---------------------------------------------------------------------------
# B5.5 — Cross-track contract: Stage 1 facts → reconcile-accept → on-write
#        process badges + policy badges land with correct shape
# ---------------------------------------------------------------------------


def test_process_item_e2e_sole_source_fires_process_badge(bag, monkeypatch):
    """Stage 1 returns procurement_method='sole_source' → on-write
    process badge 'sole_source' fires at confidence 1.0 with
    source='deterministic' and city_id populated (decision #92)."""
    from docket.ai import pipeline

    monkeypatch.setattr(
        "docket.ai.pipeline.evaluate_data_quality",
        lambda item: ("ok", "normal"),
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.is_procedural",
        lambda title: False,
    )
    sole_source_facts = StructuredFacts.model_validate({
        **SAMPLE_FACTS_DICT,
        "procurement_method": "sole_source",
    })
    monkeypatch.setattr(
        "docket.ai.pipeline.extract_facts_for_item",
        lambda *a, **kw: (sole_source_facts, "haiku-4-5"),
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.rewrite_item",
        lambda *a, **kw: (_substantive_rewrite(), "haiku-4-5"),
    )

    m = bag.add_meeting()
    iid = bag.add_pending_item(m, dollars_amount=50_000)
    item = _ItemView(_load_item(iid))

    status = pipeline.process_item(item)
    assert status == "completed"

    badges = _read_badges(iid)
    slugs = {b[0] for b in badges}
    assert "sole_source" in slugs

    # Pull the sole_source row, verify confidence + source + city_id.
    sole_source_row = [b for b in badges if b[0] == "sole_source"][0]
    slug, kind, conf, source, city_id = sole_source_row
    assert kind == "process"
    assert conf == 1.0
    assert source == "deterministic"
    assert city_id == bag.city_id  # decision #92


def test_process_item_e2e_extracted_facts_persisted_via_persist_extraction(
    bag, monkeypatch,
):
    """The Stage 1 facts JSONB is persisted into agenda_items.extracted_facts
    by extraction.persist_extraction. End-to-end verification: extracted_facts
    column matches the StructuredFacts the mock returned, and
    ai_extraction_version matches EXTRACTION_PROMPT_VERSION."""
    from docket.ai import pipeline
    from docket.ai.extraction import EXTRACTION_PROMPT_VERSION

    monkeypatch.setattr(
        "docket.ai.pipeline.evaluate_data_quality",
        lambda item: ("ok", "normal"),
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.is_procedural", lambda title: False,
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.extract_facts_for_item",
        lambda *a, **kw: (_sample_facts(), "haiku-4-5"),
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.rewrite_item",
        lambda *a, **kw: (_substantive_rewrite(), "haiku-4-5"),
    )

    m = bag.add_meeting()
    iid = bag.add_pending_item(m)
    item = _ItemView(_load_item(iid))

    pipeline.process_item(item)

    final = _load_item(iid)
    assert final["extracted_facts"] is not None
    assert final["extracted_facts"]["counterparty"] == "Acme Corp"
    assert final["extracted_facts"]["funding_source"] == "general_fund"

    # ai_extraction_version is set by persist_extraction.
    with db_cursor() as cur:
        cur.execute(
            "SELECT ai_extraction_version FROM agenda_items WHERE id = %s",
            (iid,),
        )
        version = cur.fetchone()["ai_extraction_version"]
    assert version == EXTRACTION_PROMPT_VERSION


def test_process_item_e2e_rewrite_version_set_on_completion(bag, monkeypatch):
    """ai_rewrite_version is set to ITEM_REWRITE_PROMPT_VERSION when the
    pipeline writes the rewrite atomically."""
    from docket.ai import pipeline
    from docket.ai.rewrite import ITEM_REWRITE_PROMPT_VERSION

    monkeypatch.setattr(
        "docket.ai.pipeline.evaluate_data_quality",
        lambda item: ("ok", "normal"),
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.is_procedural", lambda title: False,
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.extract_facts_for_item",
        lambda *a, **kw: (_sample_facts(), "haiku-4-5"),
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.rewrite_item",
        lambda *a, **kw: (_substantive_rewrite(), "haiku-4-5"),
    )

    m = bag.add_meeting()
    iid = bag.add_pending_item(m)
    item = _ItemView(_load_item(iid))

    pipeline.process_item(item)

    with db_cursor() as cur:
        cur.execute(
            "SELECT ai_rewrite_version FROM agenda_items WHERE id = %s",
            (iid,),
        )
        version = cur.fetchone()["ai_rewrite_version"]
    assert version == ITEM_REWRITE_PROMPT_VERSION


def test_process_item_e2e_idempotent_on_repeat_call(bag, monkeypatch):
    """Calling process_item twice on the same row produces the same
    final state. Specifically: badges use ON CONFLICT DO NOTHING so
    duplicates don't accumulate."""
    from docket.ai import pipeline

    monkeypatch.setattr(
        "docket.ai.pipeline.evaluate_data_quality",
        lambda item: ("ok", "normal"),
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.is_procedural", lambda title: False,
    )
    sole_source_facts = StructuredFacts.model_validate({
        **SAMPLE_FACTS_DICT, "procurement_method": "sole_source",
    })
    monkeypatch.setattr(
        "docket.ai.pipeline.extract_facts_for_item",
        lambda *a, **kw: (sole_source_facts, "haiku-4-5"),
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.rewrite_item",
        lambda *a, **kw: (_substantive_rewrite(), "haiku-4-5"),
    )

    m = bag.add_meeting()
    iid = bag.add_pending_item(m, dollars_amount=50_000)
    item = _ItemView(_load_item(iid))

    pipeline.process_item(item)
    badges_first = _read_badges(iid)

    # Re-load item (now has post-first-run state) and call again.
    item2 = _ItemView(_load_item(iid))
    pipeline.process_item(item2)
    badges_second = _read_badges(iid)

    # Exact-same badge set — no duplicates from the ON CONFLICT DO NOTHING.
    assert badges_first == badges_second
```

- [ ] **Step 4.2: Run all Task 4 tests, confirm pass**

Run: `venv/bin/pytest tests/integration/test_pipeline_e2e.py -v 2>&1 | tail -15`

Expected: 10 PASS (6 from Task 1 + 4 from Task 4), 0 FAIL.

- [ ] **Step 4.3: Commit**

```bash
git add tests/integration/test_pipeline_e2e.py
git commit -m "test(pipeline): end-to-end cross-track contract — badges, version cols, idempotency"
```

---

## Task 5: Live smoke test (gated on ANTHROPIC_API_KEY)

**Files:**
- Create: `tests/live/test_pipeline_live.py`

Optional but recommended per feedback memory: "New Anthropic call sites must mirror v2 client.py's tool-use pattern + get a live smoke test before downstream tasks build on top." B5 introduces a new orchestration of existing Anthropic call sites — a live smoke test verifies the end-to-end path works against the real API.

- [ ] **Step 5.1: Create the live test file**

```python
"""Live smoke tests for B5 — pipeline.process_item against real Anthropic.

Gated on ANTHROPIC_API_KEY. Costs ~$0.003 per run (one Stage 1 + one
Stage 2 Haiku call). Run manually before merging to main; skipped
automatically in CI without the env var.
"""

from __future__ import annotations

import os

import pytest

from docket.db import db


pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set; skipping live smoke test.",
)


@pytest.fixture
def live_bag():
    """Reuse the _Bag pattern. Defined here to keep tests/live/
    self-contained (per project convention)."""
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM municipalities WHERE slug = 'birmingham'"
        )
        city_id = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type)
            VALUES (%s, 'B5 live smoke', '2026-04-15', 'council')
            RETURNING id
            """,
            (city_id,),
        )
        meeting_id = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO agenda_items
              (meeting_id, title, description, dollars_amount, is_consent,
               source_type, data_quality, data_debt_priority,
               processing_status)
            VALUES (%s,
                    'Award $1.2M HVAC contract to Acme Industries (sole source)',
                    'The Council considers awarding a $1,200,000 sole-source '
                    'contract to Acme Industries for replacement of HVAC systems '
                    'in 14 city buildings. Funding from the general fund.',
                    1200000, FALSE, 'agenda',
                    'ok'::data_quality_enum,
                    'normal'::data_debt_priority_enum,
                    'pending'::processing_status_enum)
            RETURNING id
            """,
            (meeting_id,),
        )
        item_id = cur.fetchone()[0]

    yield {"city_id": city_id, "meeting_id": meeting_id, "item_id": item_id}

    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM agenda_item_badges WHERE agenda_item_id = %s",
                     (item_id,))
        cur.execute("DELETE FROM agenda_items WHERE id = %s", (item_id,))
        cur.execute("DELETE FROM meetings WHERE id = %s", (meeting_id,))


@pytest.mark.live
def test_pipeline_live_substantive_item_completes(live_bag):
    """Real Anthropic calls. A clearly-substantive item (sole-source
    $1.2M contract) should complete with headline + sole_source +
    legal_settlement-ish badges, and final status='completed'.

    Asserts the end-to-end contract without asserting specific text
    (LLM outputs vary)."""
    from docket.ai import pipeline
    from docket.db import db_cursor

    # Build the duck-typed item from the seeded row.
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT ai.id, ai.meeting_id, ai.title, ai.description,
                   ai.sponsor, ai.dollars_amount, ai.topic, ai.is_consent,
                   ai.source_type,
                   m.municipality_id AS city_id,
                   muni.name AS city_name
              FROM agenda_items ai
              JOIN meetings m ON m.id = ai.meeting_id
              JOIN municipalities muni ON muni.id = m.municipality_id
             WHERE ai.id = %s
            """,
            (live_bag["item_id"],),
        )
        row = dict(cur.fetchone())

    class _Item:
        def __init__(self, d):
            self.__dict__.update(d)
    item = _Item(row)

    status = pipeline.process_item(item)
    assert status == "completed", f"Expected completed; got {status}"

    with db_cursor() as cur:
        cur.execute(
            """
            SELECT headline, why_it_matters, significance_score,
                   processing_status::text
              FROM agenda_items WHERE id = %s
            """,
            (live_bag["item_id"],),
        )
        final = dict(cur.fetchone())

    assert final["headline"] and len(final["headline"]) >= 10
    assert final["why_it_matters"]
    assert final["processing_status"] == "completed"

    # Sole-source + large $$$ should fire badges.
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT badge_slug FROM agenda_item_badges WHERE agenda_item_id = %s",
            (live_bag["item_id"],),
        )
        slugs = {row[0] for row in cur.fetchall()}
    # Sole-source is a deterministic match — should always fire.
    assert "sole_source" in slugs
```

- [ ] **Step 5.2: Manual test invocation**

```bash
cd ~/docket-pub-integration
ANTHROPIC_API_KEY=$(grep ANTHROPIC_API_KEY ~/docket-pub-pf2-track-3/.env | cut -d= -f2-) \
    venv/bin/pytest tests/live/test_pipeline_live.py -v
```

Expected: 1 PASS (or SKIP if no API key). Anthropic spend ~$0.003.

- [ ] **Step 5.3: Commit**

```bash
git add tests/live/test_pipeline_live.py
git commit -m "test(live): B5 pipeline smoke test against real Anthropic API"
```

---

## Task 6: Final verification + commit summary

- [ ] **Step 6.1: Run full B5 test suite**

```bash
cd ~/docket-pub-integration
venv/bin/pytest tests/integration/test_pipeline_e2e.py tests/integration/test_worker_v3_dispatch.py tests/integration/test_conflict_resolution.py -v 2>&1 | tail -20
```

Expected: **13 pipeline tests + 4 worker dispatch tests + 45 G4 tests = 62 PASS**, 0 FAIL.

- [ ] **Step 6.2: Run full repository suite**

```bash
venv/bin/pytest --deselect tests/integration/test_calibration.py::test_query_c_returns_weeks_of_data --deselect tests/unit/test_ai_worker_run.py::test_run_once_refuses_over_budget 2>&1 | tail -10
```

Expected: previous baseline (1287 passed pre-B5) + 17 new tests (13 pipeline e2e + 4 worker dispatch) = **~1304 passed + 4 xfailed**.

- [ ] **Step 6.3: Sanity-check the flag flip on dev server**

```bash
IMPACT_FIRST_ENABLED=true venv/bin/python -m docket.ai.cli --dry-run --items --limit 1 2>&1 | tail -10
```

Verify: prints the v3 path's intended action against 1 pending item; doesn't actually run the LLM call in dry-run; doesn't crash on import.

If CLI doesn't have a `--dry-run` mode for v3, document this manual step as deferred.

- [ ] **Step 6.4: No additional commit; write the dispatch summary**

After all 5 task commits land, the worktree should have:
- Task 1: `feat(ai): pipeline.process_item orchestrator (Wave 0 → Stage 1 → 2 → 2.5 → reconcile → atomic commit)`
- Task 2: `feat(worker): IMPACT_FIRST_ENABLED flag + _process_items_v3 dispatch`
- Task 3: `refactor(admin): G4 conflict-resolution delegates Stage 2 re-run to pipeline._rerun_from_stage2`
- Task 4: `test(pipeline): end-to-end cross-track contract — badges, version cols, idempotency`
- Task 5: `test(live): B5 pipeline smoke test against real Anthropic API`

Total: 5 commits.

---

## What the technical-report variant will look at

This plan ships under the technical-report variant of the protocol (G1, G4 precedent — high architectural complexity). After implementation:

1. **Two parallel Opus reviews** —
   - Backend: pipeline.py orchestration + transaction shape + persistence atomicity + cross-track contract + spec drift
   - Worker/Integration: config + worker dispatch + G4 refactor correctness + v3 claim SQL semantics
2. **Comprehensive technical report (~600 lines)** synthesizing both reviews + spec/code drift + architectural concerns.
3. **User authors remediation plan** free-form.
4. **Fix-up loop.**

Reviewers should specifically check:

- **`_rerun_from_stage2` purity:** does it correctly skip Stage 1? Does it accept admin-supplied facts unchanged? Does the `override_instruction` path reach `rewrite_item`'s `extra_instruction` kwarg?
- **Transaction shape:** Phase A (Wave 0 reject path) → Phase B (no DB during LLM) → Phase C (atomic write). Verify the floors-cursor in Phase B doesn't widen into LLM-spanning DB hold. Verify Phase C's `with db()` block contains extraction + rewrite + scores + ALL badge writes.
- **Atomic-all-or-none semantics:** if rewrite_item raises after extract_facts_for_item succeeds, does anything persist? (Answer: no — both happen inside Phase B's compute window, only Phase C writes.)
- **Reconcile auto-retry:** is `already_retried=False` on the first reconcile call, `=True` on the post-retry call? (Decision #45.)
- **Decision #92 city_id on every badge INSERT:** both process and policy badge inserts pull from `item.city_id`.
- **Decision #57 SQL-vs-on-write agreement:** does `compute_on_write_process_badges` cover the 4 same-day badges (hidden_on_consent, sole_source, legal_settlement, emergency_action)? Does it NOT cover split_vote / contested / amends_prior_contract (those run nightly via SQL)?
- **G4 refactor regression:** all 45 existing test_conflict_resolution.py tests pass post-refactor. Specifically the TOCTOU race tests + the Pydantic-wrap test (B-R2 fix-up from G4 review).
- **Worker v2 path unchanged:** the existing v2 worker tests still pass; v2 still runs unchanged when `IMPACT_FIRST_ENABLED=False`.
- **`_make_client` lazy construction:** the v3 path doesn't pay the AIClient instantiation cost; the v2 path still does.
- **v3 claim SQL:** `FOR UPDATE OF ai SKIP LOCKED` is on `agenda_items`, not the joined tables. Filter on `processing_status = 'pending'` + the version columns.
- **Schema length caps + Pydantic validators:** rewrite output flowing through `ItemRewrite.procedural_consistency` validator passes (substantive → headline ≥10 chars, etc.).
- **Spec drift:** spec §7.5 + decision #45's auto-retry mechanism is in pipeline.py at lines ~190-200. The G4 fix-up never claimed to subsume B5; the refactor here is the explicit subsumption point.

---

## Self-review (run against this plan)

1. **Spec coverage** — Spec §1 (per-item pipeline shape) → pipeline.py ✓. Spec §3 (Stage 1+2) → existing modules called correctly ✓. Spec §3.4 (Stage 2.5 floors) → apply_score_floors call ✓. Spec §3.7 (reconcile) → reconcile_stages with auto-retry ✓. Spec §7.5 (atomic commit) → Phase C transaction ✓. Decision #45 (cross-stage reconcile with auto-retry) → reconcile loop with `already_retried=False`/`=True` ✓. Decision #57 (SQL+on-write agree) → both paths use compute_on_write_process_badges ✓. Decision #92 (city_id in INSERT) → both badge writes include city_id ✓. Decision #93 (cross-stage conflict UI) → G4 already shipped; B5 wires pipeline's `cross_stage_conflict` status to the same UI surface ✓.

2. **Placeholder scan** — no "TBD", "implement later", "similar to Task N", "TODO". Every code block is concrete. Test scaffolding has actual fixture code.

3. **Type consistency** — `pipeline.process_item(item) -> str` (return is processing_status). `pipeline._rerun_from_stage2(item, facts, *, override_instruction=None) -> str`. `StructuredFacts` and `ItemRewrite` Pydantic models. `ScoreOverrides` dataclass from floors.py. Reconcile result `ReconciliationResult` dataclass from reconcile.py with `action: Literal[...]`. All match existing types.

4. **Things to verify during execution:**
   - The integration worktree's `~/docket-pub-integration` venv has all deps; if pip surfaces missing modules during pytest, install from requirements.txt.
   - `services.badges.get_enabled_policy_slugs(city_id)` returns `tuple[str, ...]`. `pipeline._rerun_from_stage2` calls `list(...)` to convert — verify rewrite_item accepts a list (it does: `enabled_policy_badges: list[str]` in its signature).
   - Spec decision #92 specifies `agenda_item_badges.city_id` is the column name. Migration 013:132 confirms `city_id INT NOT NULL REFERENCES municipalities(id)`. Both badge INSERTs in pipeline.py use that column name.
   - **`agenda_item_badges` UNIQUE constraint (engineer review point):** `ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING` requires a matching unique constraint or index. Migration 013:139 declares `UNIQUE (agenda_item_id, badge_slug)` on the table — confirmed. The Step 4.1 idempotency test relies on this; if the unique constraint were missing the ON CONFLICT clause would raise. Verify with `\d agenda_item_badges` in psql before running Step 4.1.
   - **`_today_spend` is anthropic-client-free (engineer review point):** `worker.py:_today_spend` is `SELECT COALESCE(SUM(cost_usd), 0) FROM ai_runs WHERE started_at >= date_trunc('day', NOW() AT TIME ZONE 'UTC')` — pure DB read, no AIClient dependency. So Step 2.4e's lazy AIClient construction is safe; `_today_spend` works regardless of whether `_make_client()` was called.
   - **`pydantic.ValidationError` specificity (engineer review point):** Steps 3.2 and 3.3's `try/except` around `StructuredFacts.model_validate` catch the **specific** `pydantic.ValidationError`, NOT bare `Exception`. The plan's Step 3.2 code imports `from pydantic import ValidationError as PydanticValidationError` explicitly. A bare `except Exception` would swallow connection errors / memory errors / KeyboardInterrupt mid-validation — wrong shape.
   - **Grafana / Healthchecks impact of zero-spend v3 runs (engineer review point):** decision #10 leaves `summary.cost_usd = 0.0` for v3-only batches. If any monitoring dashboard alerts on zero-spend anomalies on the `ai_items` cron task (Healthchecks pings + Railway logs), the alert will fire after IMPACT_FIRST_ENABLED=true flips. Before flipping the flag at FINAL-3: audit dashboards + alerting rules; either temporarily disable zero-spend alerts or add an explicit "v3 in flight" exemption. **Operational follow-up, not a B5 code change.**

---

## What's NOT in this plan

- **Usage tracking through v3:** swallowed in extraction.py and rewrite.py today. Out of scope for B5 v1; flagged for follow-up.
- **Worker debounce equivalent to v2's AI_ITEM_DEBOUNCE_MINUTES:** v3 doesn't need it because Wave 0 already pre-filters. Flagged in claim_items_v3_sql docstring.
- **Meeting-summary integration:** B5 covers item-level only. Meeting summaries continue to use v2 until decision #93's SMART_BREVITY_UI flag flip phase.
- **`_today_spend` v3 cost telemetry:** v3 doesn't report per-row cost yet (gap from usage-tracking missing). The `ai_runs` row gets `cost_usd=0.0` for v3-only batches. Acceptable for v1; documented.
- **Migration changes:** none. All schema is from migration 013 (+015 +016).
- **Spec text patches:** the spec sketch in §B5 has the `apply_score_floors` signature wrong (4-arg) and references a `pipeline.process_item` signature that's slightly different from this plan's. The plan supersedes; defer the spec patch to a separate doc commit.
