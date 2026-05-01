# AI Summaries & Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement AI-generated summaries (item + meeting executive) and AI-generated scores (significance + consent placement) for every agenda item, fed by an async batch worker decoupled from ingest.

**Architecture:** New `src/docket/ai/` package containing prompts, an Anthropic SDK wrapper, a batch worker, and a CLI. Async cron-driven; writes to new columns on `agenda_items` and `meetings` plus a new `ai_runs` cost-telemetry table. Two-phase meeting summaries keyed off `minutes_adopted_at`. Per-row commits + `SELECT FOR UPDATE SKIP LOCKED` claim semantics.

**Tech Stack:** Python 3.10+, Anthropic Python SDK, Pydantic v2, PostgreSQL 16 (psycopg2), pytest, Flask + Jinja2 + HTMX (existing).

**Spec:** `docs/superpowers/specs/2026-05-01-summaries-and-scoring-design.md` (read this first). All section references in the plan (`§4.1`, `§5.2`, etc.) point to that spec.

**Commit discipline:** Each task ends with a commit. Use the existing repo's commit message style (lowercase verb, no Conventional Commits prefix per `git log` history).

---

## File Structure

**Created files:**

```
src/docket/ai/__init__.py
src/docket/ai/exceptions.py
src/docket/ai/pricing.py
src/docket/ai/results.py            # Pydantic models
src/docket/ai/contexts.py           # Input dataclasses (DB row → prompt)
src/docket/ai/prompts.py            # Prompt strings + version constants
src/docket/ai/client.py             # Anthropic SDK wrapper
src/docket/ai/worker.py             # Batch processor
src/docket/ai/cli.py                # Operator interface

src/docket/migrations/011_ai_summaries_and_scoring.py
src/docket/web/templates/admin/ai_panel.html

tests/unit/test_ai_pricing.py
tests/unit/test_ai_results.py
tests/unit/test_ai_contexts.py
tests/unit/test_ai_prompts.py
tests/unit/test_ai_client.py
tests/unit/test_ai_worker_claim.py
tests/unit/test_ai_worker_writeback.py
tests/unit/test_ai_worker_run.py

tests/integration/test_ai_pipeline_e2e.py
tests/integration/test_ai_phase_lifecycle.py
tests/integration/test_ai_prompt_version_bump.py
tests/integration/test_ai_meeting_telescoping.py

tests/live/__init__.py
tests/live/test_ai_live_smoke.py
```

**Modified files:**

```
requirements.txt
src/docket/config.py
.env.example                                     # if present; else create
src/docket/migrations/runner.py                  # MIGRATIONS list registration
src/docket/services/query.py                     # add summary cols to SELECTs
src/docket/web/templates/meeting_detail.html     # exec summary block + per-item summaries
src/docket/web/admin.py                          # AI panel route
CLAUDE.md                                        # status table + build phase
```

The plan numbers the migration as **011** based on the current state of `src/docket/migrations/runner.py:MIGRATIONS`. If another migration lands first and shifts the number, rename the file and the runner registration before applying.

---

## Task 1: Add dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add `anthropic` and `pydantic` to `requirements.txt`**

Open `requirements.txt` and append:

```
anthropic>=0.39
pydantic>=2.6
```

(Pydantic v1 is incompatible with the v2 syntax used in `results.py`. Pin to v2.)

- [ ] **Step 2: Install**

Run: `venv/bin/pip install -r requirements.txt`
Expected: `anthropic` and `pydantic` install with no version conflicts.

- [ ] **Step 3: Verify imports**

Run: `venv/bin/python -c "import anthropic, pydantic; print(anthropic.__version__, pydantic.__version__)"`
Expected: prints two version numbers, no errors.

- [ ] **Step 4: Commit**

```bash
cd /Users/darrellnance/docket-pub-dw-dev
git add requirements.txt
git commit -m "add anthropic and pydantic dependencies for ai pipeline"
```

---

## Task 2: Migration 011 — schema additions

**Files:**
- Create: `src/docket/migrations/011_ai_summaries_and_scoring.py`
- Modify: `src/docket/migrations/runner.py:16-27` (MIGRATIONS list)

- [ ] **Step 1: Create the migration file**

```python
# src/docket/migrations/011_ai_summaries_and_scoring.py
"""Add AI summary + scoring columns to agenda_items and meetings, plus ai_runs cost-telemetry table."""

SQL_UP = """
-- agenda_items: per-item summary + AI metadata
ALTER TABLE agenda_items
  ADD COLUMN summary             TEXT,
  ADD COLUMN ai_metadata         JSONB,
  ADD COLUMN ai_prompt_version   INTEGER,
  ADD COLUMN ai_generated_at     TIMESTAMPTZ;

CREATE INDEX idx_agenda_items_ai_prompt_version
  ON agenda_items (ai_prompt_version);

-- meetings: executive summary + AI metadata
ALTER TABLE meetings
  ADD COLUMN executive_summary   TEXT,
  ADD COLUMN ai_metadata         JSONB,
  ADD COLUMN ai_prompt_version   INTEGER,
  ADD COLUMN ai_generated_at     TIMESTAMPTZ;

CREATE INDEX idx_meetings_ai_prompt_version
  ON meetings (ai_prompt_version);

-- ai_runs: per-batch telemetry (cost, usage breakdown)
CREATE TABLE ai_runs (
    id              SERIAL PRIMARY KEY,
    started_at      TIMESTAMPTZ NOT NULL,
    finished_at     TIMESTAMPTZ,
    stage           TEXT NOT NULL,
    model           TEXT NOT NULL,
    rows_processed  INTEGER NOT NULL DEFAULT 0,
    rows_failed     INTEGER NOT NULL DEFAULT 0,
    usage           JSONB NOT NULL DEFAULT '{}'::jsonb,
    cost_usd        NUMERIC(10, 4) NOT NULL DEFAULT 0,
    notes           TEXT
);

CREATE INDEX idx_ai_runs_started_at ON ai_runs (started_at DESC);
CREATE INDEX idx_ai_runs_stage_started ON ai_runs (stage, started_at DESC);
"""

SQL_DOWN = """
DROP TABLE IF EXISTS ai_runs;

DROP INDEX IF EXISTS idx_meetings_ai_prompt_version;
ALTER TABLE meetings
  DROP COLUMN IF EXISTS ai_generated_at,
  DROP COLUMN IF EXISTS ai_prompt_version,
  DROP COLUMN IF EXISTS ai_metadata,
  DROP COLUMN IF EXISTS executive_summary;

DROP INDEX IF EXISTS idx_agenda_items_ai_prompt_version;
ALTER TABLE agenda_items
  DROP COLUMN IF EXISTS ai_generated_at,
  DROP COLUMN IF EXISTS ai_prompt_version,
  DROP COLUMN IF EXISTS ai_metadata,
  DROP COLUMN IF EXISTS summary;
"""
```

- [ ] **Step 2: Register the migration in the runner**

Open `src/docket/migrations/runner.py` and append `"docket.migrations.011_ai_summaries_and_scoring",` to the `MIGRATIONS` list (after line 26, before the closing `]`).

- [ ] **Step 3: Apply the migration locally**

Run: `venv/bin/python -m docket.migrations.runner --status`
Expected: line `[pending] 011: docket.migrations.011_ai_summaries_and_scoring`.

Run: `venv/bin/python -m docket.migrations.runner`
Expected: `Applying migration 011: ...` then `Applied migration 011`.

- [ ] **Step 4: Verify schema**

Run:
```bash
psql postgresql://docket@localhost:5432/docket_db -c "\d agenda_items" | grep -E "summary|ai_"
psql postgresql://docket@localhost:5432/docket_db -c "\d meetings" | grep -E "executive_summary|ai_"
psql postgresql://docket@localhost:5432/docket_db -c "\d ai_runs"
```
Expected: new columns visible on both tables; `ai_runs` table exists with all columns.

- [ ] **Step 5: Verify rollback works**

Run: `venv/bin/python -m docket.migrations.runner --down 11`
Expected: `Rolled back migration 11`.

Run: `psql ... -c "\d ai_runs"` — Expected: `Did not find any relation`.

Re-apply: `venv/bin/python -m docket.migrations.runner`

- [ ] **Step 6: Commit**

```bash
git add src/docket/migrations/011_ai_summaries_and_scoring.py src/docket/migrations/runner.py
git commit -m "migration 011: ai summaries, scoring metadata, and ai_runs telemetry"
```

---

## Task 3: Config additions

**Files:**
- Modify: `src/docket/config.py`
- Modify (or create): `.env.example`

- [ ] **Step 1: Add AI config to `src/docket/config.py`**

Append to `config.py`:

```python
# AI pipeline (summaries + scoring)
ANTHROPIC_API_KEY: str | None = os.environ.get("ANTHROPIC_API_KEY")
AI_ITEM_MODEL: str = os.environ.get("AI_ITEM_MODEL", "claude-haiku-4-5-20251001")
AI_MEETING_MODEL: str = os.environ.get("AI_MEETING_MODEL", "claude-sonnet-4-6")
AI_DAILY_BUDGET_USD: float = float(os.environ.get("AI_DAILY_BUDGET_USD", "10"))
AI_MAX_BATCH_SIZE: int = int(os.environ.get("AI_MAX_BATCH_SIZE", "200"))
AI_ITEM_DEBOUNCE_MINUTES: int = int(os.environ.get("AI_ITEM_DEBOUNCE_MINUTES", "5"))
```

- [ ] **Step 2: Update `.env.example`**

If `.env.example` exists, append:

```
# AI pipeline
ANTHROPIC_API_KEY=
AI_ITEM_MODEL=claude-haiku-4-5-20251001
AI_MEETING_MODEL=claude-sonnet-4-6
AI_DAILY_BUDGET_USD=10
AI_MAX_BATCH_SIZE=200
```

If `.env.example` does not exist, create it with these lines plus the existing required keys (`DATABASE_URL`, `SECRET_KEY`).

- [ ] **Step 3: Verify imports**

Run: `venv/bin/python -c "from docket.config import AI_ITEM_MODEL, AI_DAILY_BUDGET_USD; print(AI_ITEM_MODEL, AI_DAILY_BUDGET_USD)"`
Expected: `claude-haiku-4-5-20251001 10.0`.

- [ ] **Step 4: Commit**

```bash
git add src/docket/config.py .env.example
git commit -m "config: ai pipeline env vars (model, budget, batch size)"
```

---

## Task 4: Exceptions module

**Files:**
- Create: `src/docket/ai/__init__.py`
- Create: `src/docket/ai/exceptions.py`

- [ ] **Step 1: Create empty package init**

```python
# src/docket/ai/__init__.py
"""AI pipeline: summaries + scoring for agenda items and meetings."""
```

- [ ] **Step 2: Create exceptions module**

```python
# src/docket/ai/exceptions.py
"""Exceptions raised by the AI pipeline."""

from __future__ import annotations


class AIError(Exception):
    """Base for all AI pipeline errors."""


class AIRateLimited(AIError):
    """Anthropic API returned 429 after retries exhausted. Worker should stop the batch."""


class AITransientError(AIError):
    """Anthropic API returned a 5xx or timeout after retries. Worker should skip the row."""


class AIFatalError(AIError):
    """Configuration error (bad API key, missing model). Worker should exit."""


class AIPermanentRowError(AIError):
    """This row cannot be processed and should be marked completed_failed."""
```

- [ ] **Step 3: Verify**

Run: `venv/bin/python -c "from docket.ai.exceptions import AIRateLimited, AITransientError, AIFatalError, AIPermanentRowError; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add src/docket/ai/__init__.py src/docket/ai/exceptions.py
git commit -m "ai: exceptions module"
```

---

## Task 5: Pricing module + tests

**Files:**
- Create: `src/docket/ai/pricing.py`
- Create: `tests/unit/test_ai_pricing.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_ai_pricing.py
"""Tests for AI pricing math."""

import pytest

from docket.ai.pricing import PRICING, calculate_cost_usd, Usage


def test_haiku_uncached_only():
    """1000 input tokens uncached, 500 output, no cache."""
    usage = Usage(input_tokens=1000, cache_creation_input_tokens=0,
                  cache_read_input_tokens=0, output_tokens=500)
    cost = calculate_cost_usd("claude-haiku-4-5-20251001", usage)
    rates = PRICING["claude-haiku-4-5-20251001"]
    expected = (1000 * rates["input"]) + (500 * rates["output"])
    assert cost == pytest.approx(expected, rel=1e-9)


def test_haiku_cache_read_dominates():
    """38900 cache-read tokens cost 90% less than regular input."""
    usage = Usage(input_tokens=200, cache_creation_input_tokens=0,
                  cache_read_input_tokens=38900, output_tokens=300)
    cost = calculate_cost_usd("claude-haiku-4-5-20251001", usage)
    rates = PRICING["claude-haiku-4-5-20251001"]
    expected = (200 * rates["input"]) + (38900 * rates["cache_read"]) + (300 * rates["output"])
    assert cost == pytest.approx(expected, rel=1e-9)
    # Sanity: cache_read rate is 0.1x input rate
    assert rates["cache_read"] == pytest.approx(rates["input"] * 0.1, rel=0.01)


def test_cache_creation_premium():
    """Cache creation tokens cost 1.25x regular input."""
    rates = PRICING["claude-haiku-4-5-20251001"]
    assert rates["cache_creation"] == pytest.approx(rates["input"] * 1.25, rel=0.01)


def test_unknown_model_raises():
    usage = Usage(input_tokens=100, cache_creation_input_tokens=0,
                  cache_read_input_tokens=0, output_tokens=50)
    with pytest.raises(KeyError):
        calculate_cost_usd("not-a-model", usage)


def test_sonnet_present():
    """Sonnet 4.6 has a pricing entry."""
    assert "claude-sonnet-4-6" in PRICING
    rates = PRICING["claude-sonnet-4-6"]
    assert rates["input"] > 0
    assert rates["output"] > rates["input"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/unit/test_ai_pricing.py -v`
Expected: ImportError on `docket.ai.pricing`.

- [ ] **Step 3: Implement `pricing.py`**

```python
# src/docket/ai/pricing.py
"""Per-model pricing for the four Anthropic billing dimensions.

Rates are in USD per token (not per million). Verified against
https://www.anthropic.com/pricing on 2026-05-01. Update with PR
review when Anthropic changes pricing.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    output_tokens: int


# Per-token rates (USD). Source: anthropic.com/pricing, verified 2026-05-01.
# cache_creation = 1.25x input; cache_read = 0.10x input.
PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {
        "input":          1.00 / 1_000_000,
        "output":         5.00 / 1_000_000,
        "cache_creation": 1.25 / 1_000_000,
        "cache_read":     0.10 / 1_000_000,
    },
    "claude-sonnet-4-6": {
        "input":          3.00 / 1_000_000,
        "output":        15.00 / 1_000_000,
        "cache_creation": 3.75 / 1_000_000,
        "cache_read":     0.30 / 1_000_000,
    },
}


def calculate_cost_usd(model: str, usage: Usage) -> float:
    """Return the USD cost for a single API call's usage. Raises KeyError on unknown model."""
    rates = PRICING[model]
    return (
        usage.input_tokens * rates["input"]
        + usage.cache_creation_input_tokens * rates["cache_creation"]
        + usage.cache_read_input_tokens * rates["cache_read"]
        + usage.output_tokens * rates["output"]
    )


def usage_to_jsonb(usage: Usage) -> dict[str, int]:
    """Render usage as the JSONB shape stored in ai_runs.usage."""
    return {
        "input_tokens": usage.input_tokens,
        "cache_creation_input_tokens": usage.cache_creation_input_tokens,
        "cache_read_input_tokens": usage.cache_read_input_tokens,
        "output_tokens": usage.output_tokens,
    }


def usage_add(a: Usage, b: Usage) -> Usage:
    """Sum two Usage records (for batch accumulation)."""
    return Usage(
        input_tokens=a.input_tokens + b.input_tokens,
        cache_creation_input_tokens=a.cache_creation_input_tokens + b.cache_creation_input_tokens,
        cache_read_input_tokens=a.cache_read_input_tokens + b.cache_read_input_tokens,
        output_tokens=a.output_tokens + b.output_tokens,
    )
```

If the actual Anthropic pricing differs from these placeholders, update them — but they should be correct as of the spec date. Confirm against https://www.anthropic.com/pricing before deploying.

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/unit/test_ai_pricing.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/docket/ai/pricing.py tests/unit/test_ai_pricing.py
git commit -m "ai: pricing module with cache-aware cost math"
```

---

## Task 6: Pydantic result models + tests

**Files:**
- Create: `src/docket/ai/results.py`
- Create: `tests/unit/test_ai_results.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_ai_results.py
"""Tests for ItemAIResult / MeetingAIResult Pydantic validation."""

import pytest
from pydantic import ValidationError

from docket.ai.results import ItemAIResult, MeetingAIResult


def test_item_substantive_valid():
    result = ItemAIResult(
        is_substantive=True,
        significance_rationale="Approves $4.2M road contract",
        significance_score=7.5,
        consent_placement_rationale="Routine procurement",
        consent_placement_score=2.0,
        summary="Approves $4.2M road resurfacing contract.",
        confidence="high",
    )
    assert result.significance_score == 7.5


def test_item_non_substantive_must_have_null_scores():
    """is_substantive=False with non-null scores → validation error."""
    with pytest.raises(ValidationError, match="is_substantive=False"):
        ItemAIResult(
            is_substantive=False,
            significance_rationale="Procedural",
            significance_score=3.0,    # invalid: must be None
            consent_placement_rationale="N/A",
            consent_placement_score=None,
            summary="Motion to adjourn.",
            confidence="high",
        )


def test_item_substantive_must_have_non_null_scores():
    """is_substantive=True with null scores → validation error."""
    with pytest.raises(ValidationError, match="is_substantive=True"):
        ItemAIResult(
            is_substantive=True,
            significance_rationale="Approves $4.2M road contract",
            significance_score=None,   # invalid: must be 0-10
            consent_placement_rationale="Routine",
            consent_placement_score=2.0,
            summary="Approves $4.2M road resurfacing contract.",
            confidence="high",
        )


def test_score_range():
    with pytest.raises(ValidationError):
        ItemAIResult(
            is_substantive=True,
            significance_rationale="x",
            significance_score=11.0,    # > 10
            consent_placement_rationale="x",
            consent_placement_score=0.0,
            summary="ok",
            confidence="high",
        )


def test_summary_length_cap_item():
    """Item summary > 400 chars rejected."""
    with pytest.raises(ValidationError):
        ItemAIResult(
            is_substantive=True,
            significance_rationale="x",
            significance_score=5.0,
            consent_placement_rationale="x",
            consent_placement_score=5.0,
            summary="x" * 401,
            confidence="high",
        )


def test_summary_empty_when_substantive():
    with pytest.raises(ValidationError, match="summary"):
        ItemAIResult(
            is_substantive=True,
            significance_rationale="x",
            significance_score=5.0,
            consent_placement_rationale="x",
            consent_placement_score=5.0,
            summary="",
            confidence="high",
        )


def test_confidence_enum():
    with pytest.raises(ValidationError):
        ItemAIResult(
            is_substantive=True,
            significance_rationale="x",
            significance_score=5.0,
            consent_placement_rationale="x",
            consent_placement_score=5.0,
            summary="ok",
            confidence="excellent",   # invalid
        )


def test_meeting_summary_length_cap():
    """Meeting summary > 800 chars rejected."""
    with pytest.raises(ValidationError):
        MeetingAIResult(
            is_substantive=True,
            substantive_item_count=5,
            executive_summary="x" * 801,
            phase="provisional",
            confidence="high",
        )


def test_meeting_non_substantive():
    """Non-substantive meeting allows empty summary."""
    result = MeetingAIResult(
        is_substantive=False,
        substantive_item_count=0,
        executive_summary="",
        phase="provisional",
        confidence="high",
    )
    assert result.executive_summary == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/unit/test_ai_results.py -v`
Expected: ImportError on `docket.ai.results`.

- [ ] **Step 3: Implement `results.py`**

```python
# src/docket/ai/results.py
"""Pydantic models for validated AI output."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


Confidence = Literal["high", "medium", "low"]
MeetingPhase = Literal["provisional", "adopted"]


class ItemAIResult(BaseModel):
    """Structured output for one agenda-item AI call."""

    # NOTE: rationales are listed BEFORE scores so the model produces them first
    # (rationales-first prompting / chain-of-thought grounding).
    is_substantive: bool
    significance_rationale: str = Field(min_length=1, max_length=600)
    significance_score: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    consent_placement_rationale: str = Field(min_length=1, max_length=600)
    consent_placement_score: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    summary: str = Field(max_length=400)
    confidence: Confidence

    @model_validator(mode="after")
    def _scores_match_substantive(self) -> "ItemAIResult":
        if self.is_substantive:
            if self.significance_score is None or self.consent_placement_score is None:
                raise ValueError("is_substantive=True requires non-null scores")
            if not self.summary.strip():
                raise ValueError("is_substantive=True requires a non-empty summary")
        else:
            if self.significance_score is not None or self.consent_placement_score is not None:
                raise ValueError("is_substantive=False requires both scores to be null")
        return self


class MeetingAIResult(BaseModel):
    """Structured output for one meeting executive-summary AI call."""

    is_substantive: bool
    substantive_item_count: int = Field(ge=0)
    executive_summary: str = Field(max_length=800)
    phase: MeetingPhase
    confidence: Confidence

    @model_validator(mode="after")
    def _summary_required_when_substantive(self) -> "MeetingAIResult":
        if self.is_substantive and not self.executive_summary.strip():
            raise ValueError("is_substantive=True requires a non-empty executive_summary")
        return self
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/unit/test_ai_results.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add src/docket/ai/results.py tests/unit/test_ai_results.py
git commit -m "ai: pydantic result models with substantive/score validators"
```

---

## Task 7: Context dataclasses + tests

**Files:**
- Create: `src/docket/ai/contexts.py`
- Create: `tests/unit/test_ai_contexts.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_ai_contexts.py
"""Tests for AgendaItemContext / MeetingContext NULL-handling at the prompt boundary."""

from datetime import date
from decimal import Decimal

from docket.ai.contexts import AgendaItemContext, MeetingContext


def test_item_all_fields_present():
    ctx = AgendaItemContext.from_row({
        "id": 42,
        "title": "Authorize $4.2M road contract",
        "description": "Resurfacing contract for downtown corridor",
        "sponsor": "Public Works Dept.",
        "dollars_amount": Decimal("4200000.00"),
        "topic": "Public Works",
        "is_consent": False,
    })
    rendered = ctx.render_user_prompt()
    assert "Authorize $4.2M road contract" in rendered
    assert "Public Works" in rendered
    assert "$4,200,000" in rendered or "4200000" in rendered
    assert "(no description provided)" not in rendered


def test_item_null_topic_renders_uncategorized():
    ctx = AgendaItemContext.from_row({
        "id": 1, "title": "ok", "description": None, "sponsor": None,
        "dollars_amount": None, "topic": None, "is_consent": False,
    })
    rendered = ctx.render_user_prompt()
    assert "Uncategorized" in rendered
    assert "(no description provided)" in rendered
    assert "(no sponsor listed)" in rendered
    assert "(none)" in rendered
    assert "None" not in rendered  # never the literal string


def test_item_consent_flag_rendering():
    yes_ctx = AgendaItemContext.from_row({
        "id": 1, "title": "x", "description": None, "sponsor": None,
        "dollars_amount": None, "topic": None, "is_consent": True,
    })
    assert "Yes" in yes_ctx.render_user_prompt()


def test_meeting_renders_item_summaries():
    """Meeting context must render item AI summaries (telescoping)."""
    ctx = MeetingContext(
        meeting_id=10,
        meeting_type="Council Meeting",
        meeting_date=date(2026, 4, 1),
        phase="provisional",
        item_summaries=[
            "Approves $4.2M road resurfacing contract.",
            "Authorizes 3-year IT support agreement.",
        ],
    )
    rendered = ctx.render_user_prompt()
    assert "Approves $4.2M road resurfacing contract." in rendered
    assert "Authorizes 3-year IT support agreement." in rendered
    assert "Phase: provisional" in rendered
    assert "(2)" in rendered  # item count
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/unit/test_ai_contexts.py -v`
Expected: ImportError on `docket.ai.contexts`.

- [ ] **Step 3: Implement `contexts.py`**

```python
# src/docket/ai/contexts.py
"""Dataclasses that mediate between DB rows and prompt strings.

Each context's from_row() factory normalizes NULL columns so rendered
prompts never contain the literal string "None".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Sequence

from docket.ai.results import MeetingPhase


def _format_dollars(amount: Decimal | None) -> str:
    if amount is None:
        return "(none)"
    return f"${amount:,.2f}"


@dataclass(frozen=True)
class AgendaItemContext:
    item_id: int
    title: str
    description: str
    sponsor: str
    dollars_amount: str
    topic: str
    is_consent_label: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "AgendaItemContext":
        return cls(
            item_id=row["id"],
            title=row["title"],
            description=row["description"] or "(no description provided)",
            sponsor=row["sponsor"] or "(no sponsor listed)",
            dollars_amount=_format_dollars(row["dollars_amount"]),
            topic=row["topic"] or "Uncategorized",
            is_consent_label="Yes" if row["is_consent"] else "No",
        )

    def render_user_prompt(self) -> str:
        from docket.ai.prompts import ITEM_USER_TEMPLATE
        return ITEM_USER_TEMPLATE.format(
            title=self.title,
            description=self.description,
            sponsor=self.sponsor,
            dollars_amount=self.dollars_amount,
            topic=self.topic,
            is_consent=self.is_consent_label,
        )


@dataclass(frozen=True)
class MeetingContext:
    meeting_id: int
    meeting_type: str
    meeting_date: date
    phase: MeetingPhase
    item_summaries: Sequence[str]    # AI-generated item summaries, NOT raw titles

    def render_user_prompt(self) -> str:
        from docket.ai.prompts import MEETING_USER_TEMPLATE
        items_block = "\n".join(f"- {s}" for s in self.item_summaries)
        return MEETING_USER_TEMPLATE.format(
            meeting_type=self.meeting_type,
            meeting_date=self.meeting_date.isoformat(),
            phase=self.phase,
            count=len(self.item_summaries),
            items_block=items_block,
        )
```

- [ ] **Step 4: Run tests to verify they pass (will still fail until prompts.py exists)**

Run: `venv/bin/pytest tests/unit/test_ai_contexts.py -v`
Expected: ImportError on `docket.ai.prompts` (resolved in Task 8).

Skip this step — return to it after Task 8.

- [ ] **Step 5: Commit**

```bash
git add src/docket/ai/contexts.py tests/unit/test_ai_contexts.py
git commit -m "ai: context dataclasses with null-safe prompt rendering"
```

---

## Task 8: Prompts module + tests

**Files:**
- Create: `src/docket/ai/prompts.py`
- Create: `tests/unit/test_ai_prompts.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_ai_prompts.py
"""Tests for prompt templates and version constants."""

from docket.ai.prompts import (
    ITEM_PROMPT_VERSION,
    MEETING_PROMPT_VERSION,
    ITEM_SYSTEM,
    MEETING_SYSTEM,
    ITEM_USER_TEMPLATE,
    MEETING_USER_TEMPLATE,
)


def test_versions_are_integers():
    assert isinstance(ITEM_PROMPT_VERSION, int)
    assert isinstance(MEETING_PROMPT_VERSION, int)
    assert ITEM_PROMPT_VERSION >= 1
    assert MEETING_PROMPT_VERSION >= 1


def test_item_system_says_rationale_before_score():
    """Rationales-first instruction is present, since the result schema requires it."""
    text = ITEM_SYSTEM.lower()
    rationale_idx = text.find("rationale")
    score_idx = text.find("score")
    assert rationale_idx != -1 and score_idx != -1
    assert rationale_idx < score_idx


def test_item_system_handles_procedural():
    """Procedural items must be handled (is_substantive=False)."""
    text = ITEM_SYSTEM.lower()
    assert "is_substantive" in text or "procedural" in text


def test_meeting_system_phase_aware():
    """Meeting prompt distinguishes adopted vs provisional."""
    text = MEETING_SYSTEM.lower()
    assert "adopted" in text
    assert "provisional" in text or "considered" in text


def test_item_user_template_renders():
    rendered = ITEM_USER_TEMPLATE.format(
        title="Test", description="d", sponsor="s",
        dollars_amount="$0", topic="Other", is_consent="No",
    )
    assert "Test" in rendered


def test_meeting_user_template_renders():
    rendered = MEETING_USER_TEMPLATE.format(
        meeting_type="Council", meeting_date="2026-04-01", phase="provisional",
        count=2, items_block="- a\n- b",
    )
    assert "Council" in rendered
    assert "2026-04-01" in rendered
    assert "- a" in rendered
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/unit/test_ai_prompts.py -v`
Expected: ImportError on `docket.ai.prompts`.

- [ ] **Step 3: Implement `prompts.py`**

```python
# src/docket/ai/prompts.py
"""Versioned prompt strings + version constants.

Bumping a version constant is the trigger for re-summarization. The git
history of this file IS the audit trail — write a commit message
explaining why the rubric changed when bumping a version.
"""

from __future__ import annotations

ITEM_PROMPT_VERSION = 1
MEETING_PROMPT_VERSION = 1


ITEM_SYSTEM = """You are summarizing a single agenda item from a municipal
government meeting. You will only see fields from the agenda item itself.
Do not invent facts.

If the item is procedural (motion to adjourn, approval of prior minutes,
roll call), set is_substantive=false and return null for both scores.

For substantive items, write the rationale BEFORE the numeric score.
Then assign 0-10 scores grounded in the rationale you just wrote:

- significance_score: How impactful is this item? 0 = trivial, 10 = major.
- consent_placement_score: How appropriate is consent-agenda placement?
  0 = should never be on consent (high public interest), 10 = perfect
  consent candidate (routine, non-controversial).

Confidence: "high" if the item's text is unambiguous, "medium" if title
is clear but details are sparse, "low" if you had to guess at intent.

Summary: 1-2 sentences describing what was proposed. Plain prose, no jargon.
"""


ITEM_USER_TEMPLATE = """Title: {title}
Description: {description}
Sponsor: {sponsor}
Dollar amount: {dollars_amount}
Topic: {topic}
Is on consent agenda: {is_consent}"""


MEETING_SYSTEM = """You are writing a 2-3 sentence executive summary of a
municipal meeting. You will only see substantive agenda items from this
meeting (each represented by its own AI-generated summary).

If phase is "adopted": lead with what the council DECIDED (votes are final).
If phase is "provisional": lead with what the council CONSIDERED (votes
not yet ratified).

Do not invent facts not present in the items. Do not list every item —
identify the 1-3 most consequential decisions or debates and frame the
meeting around those.

Confidence: "high" if items are clear and substantive; "medium" if items
are vague; "low" if synthesis required guessing.
"""


MEETING_USER_TEMPLATE = """Meeting: {meeting_type} on {meeting_date}
Phase: {phase}
Substantive items ({count}):
{items_block}"""
```

- [ ] **Step 4: Run prompt + context tests together**

Run: `venv/bin/pytest tests/unit/test_ai_prompts.py tests/unit/test_ai_contexts.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/docket/ai/prompts.py tests/unit/test_ai_prompts.py
git commit -m "ai: prompt templates v1 and version constants"
```

---

## Task 9: AIClient — success path + tests

**Files:**
- Create: `src/docket/ai/client.py`
- Create: `tests/unit/test_ai_client.py`

- [ ] **Step 1: Write the failing test (success path only)**

```python
# tests/unit/test_ai_client.py
"""Tests for AIClient: success, retries, validation, cost tracking."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from docket.ai.client import AIClient
from docket.ai.contexts import AgendaItemContext, MeetingContext
from docket.ai.exceptions import AIFatalError, AIRateLimited, AITransientError, AIPermanentRowError
from docket.ai.pricing import Usage


def _stub_anthropic_message(json_payload: dict, usage: dict | None = None):
    """Return a MagicMock matching the relevant parts of anthropic.types.Message."""
    msg = MagicMock()
    msg.stop_reason = "tool_use"
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.input = json_payload
    msg.content = [tool_block]
    u = MagicMock()
    u.input_tokens = (usage or {}).get("input_tokens", 100)
    u.cache_creation_input_tokens = (usage or {}).get("cache_creation_input_tokens", 0)
    u.cache_read_input_tokens = (usage or {}).get("cache_read_input_tokens", 0)
    u.output_tokens = (usage or {}).get("output_tokens", 50)
    msg.usage = u
    return msg


def _item_ctx() -> AgendaItemContext:
    return AgendaItemContext.from_row({
        "id": 1, "title": "Test", "description": "x", "sponsor": "y",
        "dollars_amount": Decimal("100.00"), "topic": "Other", "is_consent": False,
    })


def _meeting_ctx() -> MeetingContext:
    return MeetingContext(
        meeting_id=1, meeting_type="Council", meeting_date=date(2026, 4, 1),
        phase="provisional", item_summaries=["item summary 1", "item summary 2"],
    )


@patch("docket.ai.client.Anthropic")
def test_summarize_item_success(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _stub_anthropic_message({
        "is_substantive": True,
        "significance_rationale": "ok",
        "significance_score": 5.0,
        "consent_placement_rationale": "ok",
        "consent_placement_score": 5.0,
        "summary": "ok",
        "confidence": "high",
    })

    client = AIClient(api_key="test-key")
    result, usage = client.summarize_item(_item_ctx())
    assert result.summary == "ok"
    assert result.significance_score == 5.0
    assert isinstance(usage, Usage)
    assert usage.input_tokens == 100


@patch("docket.ai.client.Anthropic")
def test_summarize_meeting_success(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _stub_anthropic_message({
        "is_substantive": True,
        "substantive_item_count": 2,
        "executive_summary": "Council considered two items.",
        "phase": "provisional",
        "confidence": "high",
    })

    client = AIClient(api_key="test-key")
    result, usage = client.summarize_meeting(_meeting_ctx())
    assert result.executive_summary == "Council considered two items."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/unit/test_ai_client.py -v`
Expected: ImportError on `docket.ai.client`.

- [ ] **Step 3: Implement the success path of `client.py`**

```python
# src/docket/ai/client.py
"""Anthropic SDK wrapper: prompts, structured output, retries, cost tracking."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from anthropic import Anthropic, APIError, APIStatusError, APITimeoutError, RateLimitError
from pydantic import ValidationError

from docket.ai.contexts import AgendaItemContext, MeetingContext
from docket.ai.exceptions import (
    AIFatalError,
    AIPermanentRowError,
    AIRateLimited,
    AITransientError,
)
from docket.ai.pricing import Usage
from docket.ai.prompts import (
    ITEM_SYSTEM,
    ITEM_PROMPT_VERSION,
    MEETING_SYSTEM,
    MEETING_PROMPT_VERSION,
)
from docket.ai.results import ItemAIResult, MeetingAIResult


log = logging.getLogger(__name__)


# Tool schemas for structured output. Anthropic's tool_use returns the
# input as a dict matching the input_schema, which Pydantic then validates.
ITEM_TOOL = {
    "name": "submit_item_summary",
    "description": "Submit the structured summary and scores for one agenda item.",
    "input_schema": {
        "type": "object",
        "required": [
            "is_substantive", "significance_rationale", "significance_score",
            "consent_placement_rationale", "consent_placement_score",
            "summary", "confidence",
        ],
        "properties": {
            "is_substantive": {"type": "boolean"},
            "significance_rationale": {"type": "string"},
            "significance_score": {"type": ["number", "null"]},
            "consent_placement_rationale": {"type": "string"},
            "consent_placement_score": {"type": ["number", "null"]},
            "summary": {"type": "string"},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
    },
}

MEETING_TOOL = {
    "name": "submit_meeting_summary",
    "description": "Submit the executive summary for one meeting.",
    "input_schema": {
        "type": "object",
        "required": [
            "is_substantive", "substantive_item_count",
            "executive_summary", "phase", "confidence",
        ],
        "properties": {
            "is_substantive": {"type": "boolean"},
            "substantive_item_count": {"type": "integer"},
            "executive_summary": {"type": "string"},
            "phase": {"type": "string", "enum": ["provisional", "adopted"]},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
    },
}


MAX_RETRIES = 3
TOKEN_INPUT_CAP = 30_000   # refuse calls with prompt tokens above this; log loudly


class AIClient:
    def __init__(self, api_key: str, item_model: str | None = None,
                 meeting_model: str | None = None):
        if not api_key:
            raise AIFatalError("ANTHROPIC_API_KEY is not set")
        from docket.config import AI_ITEM_MODEL, AI_MEETING_MODEL
        self.item_model = item_model or AI_ITEM_MODEL
        self.meeting_model = meeting_model or AI_MEETING_MODEL
        self._client = Anthropic(api_key=api_key)

    # ---- public API ----

    def summarize_item(self, ctx: AgendaItemContext) -> tuple[ItemAIResult, Usage]:
        message = self._call_with_retries(
            model=self.item_model,
            system=ITEM_SYSTEM,
            user=ctx.render_user_prompt(),
            tool=ITEM_TOOL,
        )
        payload = self._extract_tool_input(message, ITEM_TOOL["name"])
        try:
            result = ItemAIResult.model_validate(payload)
        except ValidationError as e:
            raise AIPermanentRowError(f"Pydantic validation failed for item: {e}") from e
        return result, self._extract_usage(message)

    def summarize_meeting(self, ctx: MeetingContext) -> tuple[MeetingAIResult, Usage]:
        message = self._call_with_retries(
            model=self.meeting_model,
            system=MEETING_SYSTEM,
            user=ctx.render_user_prompt(),
            tool=MEETING_TOOL,
        )
        payload = self._extract_tool_input(message, MEETING_TOOL["name"])
        try:
            result = MeetingAIResult.model_validate(payload)
        except ValidationError as e:
            raise AIPermanentRowError(f"Pydantic validation failed for meeting: {e}") from e
        return result, self._extract_usage(message)

    # ---- internals ----

    def _call_with_retries(self, *, model: str, system: str, user: str, tool: dict[str, Any]):
        last_exc = None
        delay = 2.0
        for attempt in range(MAX_RETRIES):
            try:
                return self._client.messages.create(
                    model=model,
                    max_tokens=1024,
                    tools=[tool],
                    tool_choice={"type": "tool", "name": tool["name"]},
                    system=[
                        {"type": "text", "text": system,
                         "cache_control": {"type": "ephemeral"}},
                    ],
                    messages=[{"role": "user", "content": user}],
                )
            except RateLimitError as e:
                last_exc = e
                retry_after = float(e.response.headers.get("retry-after", delay)) if hasattr(e, "response") else delay
                log.warning("Rate limited (attempt %d/%d); sleeping %.1fs", attempt + 1, MAX_RETRIES, retry_after)
                time.sleep(retry_after)
                delay *= 2
            except APITimeoutError as e:
                last_exc = e
                log.warning("Timeout (attempt %d/%d); backoff %.1fs", attempt + 1, MAX_RETRIES, delay)
                time.sleep(delay)
                delay *= 2
            except APIStatusError as e:
                if e.status_code in (401, 403):
                    raise AIFatalError(f"Auth error from Anthropic: {e}") from e
                if e.status_code == 400:
                    raise AIPermanentRowError(f"Bad request to Anthropic: {e}") from e
                if e.status_code >= 500:
                    last_exc = e
                    log.warning("5xx (attempt %d/%d); backoff %.1fs", attempt + 1, MAX_RETRIES, delay)
                    time.sleep(delay)
                    delay *= 2
                else:
                    raise AIPermanentRowError(f"Unexpected status from Anthropic: {e}") from e
            except APIError as e:
                last_exc = e
                log.warning("Generic API error (attempt %d/%d): %s", attempt + 1, MAX_RETRIES, e)
                time.sleep(delay)
                delay *= 2
        # Retries exhausted
        if isinstance(last_exc, RateLimitError):
            raise AIRateLimited("Rate limit retries exhausted") from last_exc
        raise AITransientError(f"Transient retries exhausted: {last_exc}") from last_exc

    @staticmethod
    def _extract_tool_input(message, tool_name: str) -> dict:
        for block in message.content:
            if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
                return dict(block.input)
            # Some SDKs put tool_use blocks without explicit name field; defensive
            if getattr(block, "type", None) == "tool_use":
                return dict(block.input)
        raise AIPermanentRowError(f"No tool_use block named {tool_name} in response")

    @staticmethod
    def _extract_usage(message) -> Usage:
        u = message.usage
        return Usage(
            input_tokens=getattr(u, "input_tokens", 0) or 0,
            cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            output_tokens=getattr(u, "output_tokens", 0) or 0,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/unit/test_ai_client.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/docket/ai/client.py tests/unit/test_ai_client.py
git commit -m "ai: client success path with structured-output tool_use"
```

---

## Task 10: AIClient — retry, validation, fatal paths + tests

**Files:**
- Modify: `tests/unit/test_ai_client.py`

- [ ] **Step 1: Add failing tests for the failure modes**

Append to `tests/unit/test_ai_client.py`:

```python
from anthropic import APIStatusError, APITimeoutError, RateLimitError


def _make_status_error(code: int):
    """Construct an APIStatusError with a given status code."""
    response = MagicMock()
    response.status_code = code
    response.headers = {}
    err = APIStatusError(message="x", response=response, body=None)
    return err


@patch("docket.ai.client.Anthropic")
def test_401_raises_fatal(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.side_effect = _make_status_error(401)
    with pytest.raises(AIFatalError):
        AIClient(api_key="bad").summarize_item(_item_ctx())


@patch("docket.ai.client.Anthropic")
def test_400_raises_permanent(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.side_effect = _make_status_error(400)
    with pytest.raises(AIPermanentRowError):
        AIClient(api_key="ok").summarize_item(_item_ctx())


@patch("docket.ai.client.Anthropic")
@patch("docket.ai.client.time.sleep", lambda _: None)
def test_5xx_retries_then_transient(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.side_effect = _make_status_error(503)
    with pytest.raises(AITransientError):
        AIClient(api_key="ok").summarize_item(_item_ctx())
    assert mock_client.messages.create.call_count == 3


@patch("docket.ai.client.Anthropic")
@patch("docket.ai.client.time.sleep", lambda _: None)
def test_5xx_then_success(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    success_msg = _stub_anthropic_message({
        "is_substantive": True, "significance_rationale": "ok", "significance_score": 5.0,
        "consent_placement_rationale": "ok", "consent_placement_score": 5.0,
        "summary": "ok", "confidence": "high",
    })
    mock_client.messages.create.side_effect = [_make_status_error(503), success_msg]
    result, _ = AIClient(api_key="ok").summarize_item(_item_ctx())
    assert result.summary == "ok"
    assert mock_client.messages.create.call_count == 2


@patch("docket.ai.client.Anthropic")
def test_validation_error_is_permanent(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    # Invalid: is_substantive=True but null scores
    mock_client.messages.create.return_value = _stub_anthropic_message({
        "is_substantive": True, "significance_rationale": "x", "significance_score": None,
        "consent_placement_rationale": "x", "consent_placement_score": None,
        "summary": "ok", "confidence": "high",
    })
    with pytest.raises(AIPermanentRowError):
        AIClient(api_key="ok").summarize_item(_item_ctx())


def test_no_api_key_raises_fatal():
    with pytest.raises(AIFatalError):
        AIClient(api_key="")
```

- [ ] **Step 2: Run tests to verify the new ones fail or pass appropriately**

Run: `venv/bin/pytest tests/unit/test_ai_client.py -v`
Expected: most pass; if any fail, fix `client.py` accordingly. The retry-with-success test verifies the retry loop reuses on the next attempt.

- [ ] **Step 3: Iterate `client.py` until all tests pass**

If any test fails, the bug is most likely in `_call_with_retries` exception handling. The expected behavior matrix is in §5.2 of the spec.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_ai_client.py
git commit -m "ai: client retry/error/fatal path tests"
```

---

## Task 11: Worker claim queries — items + tests

**Files:**
- Create: `src/docket/ai/worker.py` (skeleton)
- Create: `tests/unit/test_ai_worker_claim.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_ai_worker_claim.py
"""Tests for the worker's claim queries (item readiness, meeting two-phase)."""

from datetime import datetime, timedelta, timezone

import pytest

from docket.ai.prompts import ITEM_PROMPT_VERSION, MEETING_PROMPT_VERSION
from docket.ai.worker import claim_items_sql, claim_meetings_sql
from docket.db import db


@pytest.fixture
def fresh_db():
    """Clean agenda_items / meetings rows before each test."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM vote_agenda_items")
            cur.execute("DELETE FROM member_votes")
            cur.execute("DELETE FROM votes")
            cur.execute("DELETE FROM agenda_items")
            cur.execute("DELETE FROM meetings WHERE municipality_id IN (SELECT id FROM municipalities WHERE slug LIKE 'test_%')")
        conn.commit()
        yield conn


def _seed_item(conn, *, meeting_id, title="t", created_minutes_ago=10,
                ai_prompt_version=None):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO agenda_items (meeting_id, title, is_consent, ai_prompt_version, created_at)
            VALUES (%s, %s, FALSE, %s, NOW() - INTERVAL '%s minutes')
            RETURNING id
        """, (meeting_id, title, ai_prompt_version, created_minutes_ago))
        return cur.fetchone()[0]


def _seed_meeting(conn, *, slug="test_city", minutes_adopted_at=None, ai_prompt_version=None,
                   ai_metadata=None):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO municipalities (slug, name, state, adapter_type, base_url, active)
            VALUES (%s, %s, 'AL', 'granicus', 'https://example.test', TRUE)
            ON CONFLICT (slug) DO UPDATE SET active = TRUE
            RETURNING id
        """, (slug, slug.replace("_", " ").title()))
        muni_id = cur.fetchone()[0]
        cur.execute("""
            INSERT INTO meetings (municipality_id, meeting_type, meeting_date, source_url,
                                   minutes_adopted_at, ai_prompt_version, ai_metadata)
            VALUES (%s, 'Council Meeting', CURRENT_DATE, 'https://x', %s, %s, %s)
            RETURNING id
        """, (muni_id, minutes_adopted_at, ai_prompt_version, ai_metadata))
        return cur.fetchone()[0]


def test_claim_items_skips_recent_rows(fresh_db):
    """Items younger than 5 min are not claimed (debounce)."""
    m_id = _seed_meeting(fresh_db)
    young = _seed_item(fresh_db, meeting_id=m_id, created_minutes_ago=2)
    old = _seed_item(fresh_db, meeting_id=m_id, created_minutes_ago=30)
    fresh_db.commit()

    with fresh_db.cursor() as cur:
        cur.execute(claim_items_sql(), (ITEM_PROMPT_VERSION, 5, 100))
        ids = [row[0] for row in cur.fetchall()]
    assert old in ids
    assert young not in ids


def test_claim_items_skips_already_current(fresh_db):
    """Items at current ai_prompt_version are not re-claimed."""
    m_id = _seed_meeting(fresh_db)
    pending = _seed_item(fresh_db, meeting_id=m_id, ai_prompt_version=None)
    current = _seed_item(fresh_db, meeting_id=m_id, ai_prompt_version=ITEM_PROMPT_VERSION)
    stale = _seed_item(fresh_db, meeting_id=m_id, ai_prompt_version=ITEM_PROMPT_VERSION - 1)
    fresh_db.commit()

    with fresh_db.cursor() as cur:
        cur.execute(claim_items_sql(), (ITEM_PROMPT_VERSION, 5, 100))
        ids = [row[0] for row in cur.fetchall()]
    assert pending in ids
    assert stale in ids
    assert current not in ids


def test_claim_meetings_provisional_phase(fresh_db):
    """Meeting with all items processed and minutes_adopted_at NULL is claimable for provisional pass."""
    m_id = _seed_meeting(fresh_db, slug="test_provisional", minutes_adopted_at=None)
    _seed_item(fresh_db, meeting_id=m_id, ai_prompt_version=ITEM_PROMPT_VERSION)
    fresh_db.commit()

    with fresh_db.cursor() as cur:
        cur.execute(claim_meetings_sql(), (MEETING_PROMPT_VERSION, ITEM_PROMPT_VERSION, 100))
        ids = [row[0] for row in cur.fetchall()]
    assert m_id in ids


def test_claim_meetings_blocked_by_pending_items(fresh_db):
    """A meeting with one item not yet AI-processed is NOT claimable."""
    m_id = _seed_meeting(fresh_db, slug="test_blocked")
    _seed_item(fresh_db, meeting_id=m_id, ai_prompt_version=ITEM_PROMPT_VERSION)
    _seed_item(fresh_db, meeting_id=m_id, ai_prompt_version=None)   # blocker
    fresh_db.commit()

    with fresh_db.cursor() as cur:
        cur.execute(claim_meetings_sql(), (MEETING_PROMPT_VERSION, ITEM_PROMPT_VERSION, 100))
        ids = [row[0] for row in cur.fetchall()]
    assert m_id not in ids


def test_claim_meetings_adopted_phase_overrides(fresh_db):
    """Meeting with minutes_adopted_at set and phase=provisional is re-claimable."""
    import json
    m_id = _seed_meeting(
        fresh_db, slug="test_adopted",
        minutes_adopted_at=datetime.now(timezone.utc),
        ai_prompt_version=MEETING_PROMPT_VERSION,
        ai_metadata=json.dumps({"phase": "provisional"}),
    )
    _seed_item(fresh_db, meeting_id=m_id, ai_prompt_version=ITEM_PROMPT_VERSION)
    fresh_db.commit()

    with fresh_db.cursor() as cur:
        cur.execute(claim_meetings_sql(), (MEETING_PROMPT_VERSION, ITEM_PROMPT_VERSION, 100))
        ids = [row[0] for row in cur.fetchall()]
    assert m_id in ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/unit/test_ai_worker_claim.py -v`
Expected: ImportError on `docket.ai.worker`.

- [ ] **Step 3: Implement claim queries in `worker.py`**

```python
# src/docket/ai/worker.py
"""Batch worker: claims rows, calls AIClient, writes back."""

from __future__ import annotations

import logging
from typing import Literal

from docket.db import db


log = logging.getLogger(__name__)


def claim_items_sql() -> str:
    """Returns the SELECT SQL. Args: (current_item_version, debounce_minutes, limit)."""
    return """
        SELECT id, meeting_id, title, description, sponsor, dollars_amount, topic, is_consent
        FROM agenda_items
        WHERE (ai_prompt_version IS NULL OR ai_prompt_version < %s)
          AND created_at < NOW() - (%s || ' minutes')::interval
        ORDER BY id
        FOR UPDATE SKIP LOCKED
        LIMIT %s
    """


def claim_meetings_sql() -> str:
    """Returns the SELECT SQL. Args: (current_meeting_version, current_item_version, limit).

    A meeting is claimable if EITHER:
      (a) provisional pass:  ai_prompt_version != current AND minutes_adopted_at IS NULL
                             AND all items at current item version
                             AND ai_metadata.phase != 'provisional'
      (b) adopted pass:      minutes_adopted_at IS NOT NULL AND ai_metadata.phase != 'adopted'
    """
    return """
        SELECT m.id, m.meeting_type, m.meeting_date, m.minutes_adopted_at, m.ai_metadata
        FROM meetings m
        WHERE (
            -- (a) provisional pass
            ((m.ai_prompt_version IS NULL OR m.ai_prompt_version < %s)
             AND m.minutes_adopted_at IS NULL
             AND COALESCE(m.ai_metadata->>'phase', '') != 'provisional'
             AND NOT EXISTS (
               SELECT 1 FROM agenda_items ai
               WHERE ai.meeting_id = m.id
                 AND (ai.ai_prompt_version IS NULL OR ai.ai_prompt_version < %s)
             ))
            OR
            -- (b) adopted pass
            (m.minutes_adopted_at IS NOT NULL
             AND COALESCE(m.ai_metadata->>'phase', '') != 'adopted')
          )
        ORDER BY m.id
        FOR UPDATE OF m SKIP LOCKED
        LIMIT %s
    """
```

(Note the meetings query uses two separate `%s` placeholders for the version constants, matching the test signature `(MEETING_PROMPT_VERSION, ITEM_PROMPT_VERSION, 100)`. The first goes into branch (a)'s version check; the second goes into branch (a)'s NOT EXISTS subquery. Branch (b) doesn't use either version constant.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/unit/test_ai_worker_claim.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/docket/ai/worker.py tests/unit/test_ai_worker_claim.py
git commit -m "ai: worker claim queries with two-phase meeting gates"
```

---

## Task 12: Worker write-back — items + tests

**Files:**
- Modify: `src/docket/ai/worker.py`
- Create: `tests/unit/test_ai_worker_writeback.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_ai_worker_writeback.py
"""Tests for the worker's write-back of AI results to rows."""

import json

import pytest

from docket.ai.prompts import ITEM_PROMPT_VERSION
from docket.ai.results import ItemAIResult
from docket.ai.worker import write_item_result, mark_item_failed
from docket.db import db


@pytest.fixture
def seed_item():
    """Insert a fresh agenda item and return its id."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO municipalities (slug, name, state, adapter_type, base_url, active)
                VALUES ('test_wb', 'Test', 'AL', 'granicus', 'https://x', TRUE)
                ON CONFLICT (slug) DO UPDATE SET active = TRUE
                RETURNING id
            """)
            muni = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO meetings (municipality_id, meeting_type, meeting_date, source_url)
                VALUES (%s, 'C', CURRENT_DATE, 'x')
                RETURNING id
            """, (muni,))
            m_id = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO agenda_items (meeting_id, title, is_consent)
                VALUES (%s, 'test', FALSE) RETURNING id
            """, (m_id,))
            item_id = cur.fetchone()[0]
        conn.commit()
    yield item_id
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM agenda_items WHERE id = %s", (item_id,))
            cur.execute("DELETE FROM meetings WHERE id IN (SELECT meeting_id FROM agenda_items WHERE id = %s)", (item_id,))
        conn.commit()


def test_write_item_result_substantive(seed_item):
    result = ItemAIResult(
        is_substantive=True,
        significance_rationale="r1", significance_score=7.5,
        consent_placement_rationale="r2", consent_placement_score=2.0,
        summary="A substantive item.",
        confidence="high",
    )
    with db() as conn:
        write_item_result(conn, seed_item, result, model="claude-haiku-4-5-20251001")
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT summary, significance_score, consent_placement_score,
                       ai_prompt_version, ai_generated_at, ai_metadata
                FROM agenda_items WHERE id = %s
            """, (seed_item,))
            row = cur.fetchone()
    assert row[0] == "A substantive item."
    assert float(row[1]) == 7.5
    assert float(row[2]) == 2.0
    assert row[3] == ITEM_PROMPT_VERSION
    assert row[4] is not None
    md = row[5]
    assert md["confidence"] == "high"
    assert md["is_substantive"] is True
    assert md["model"] == "claude-haiku-4-5-20251001"


def test_write_item_result_non_substantive(seed_item):
    result = ItemAIResult(
        is_substantive=False,
        significance_rationale="procedural", significance_score=None,
        consent_placement_rationale="n/a", consent_placement_score=None,
        summary="Motion to adjourn.",
        confidence="high",
    )
    with db() as conn:
        write_item_result(conn, seed_item, result, model="claude-haiku-4-5-20251001")
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT summary, significance_score, consent_placement_score, ai_prompt_version
                FROM agenda_items WHERE id = %s
            """, (seed_item,))
            row = cur.fetchone()
    assert row[0] == "Motion to adjourn."
    assert row[1] is None
    assert row[2] is None
    assert row[3] == ITEM_PROMPT_VERSION


def test_mark_item_failed_keeps_summary_null(seed_item):
    """Permanent failure: prompt_version bumped, summary remains NULL, confidence=low."""
    with db() as conn:
        mark_item_failed(conn, seed_item, "token cap exceeded")
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT summary, ai_prompt_version, ai_metadata
                FROM agenda_items WHERE id = %s
            """, (seed_item,))
            row = cur.fetchone()
    assert row[0] is None
    assert row[1] == ITEM_PROMPT_VERSION
    assert row[2]["confidence"] == "low"
    assert "error" in row[2]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/unit/test_ai_worker_writeback.py -v`
Expected: ImportError on `write_item_result` / `mark_item_failed`.

- [ ] **Step 3: Append to `worker.py`**

```python
# Append to src/docket/ai/worker.py

import json
from psycopg2.extras import Json

from docket.ai.prompts import ITEM_PROMPT_VERSION, MEETING_PROMPT_VERSION
from docket.ai.results import ItemAIResult, MeetingAIResult


def write_item_result(conn, item_id: int, result: ItemAIResult, *, model: str) -> None:
    """Update an agenda_item row with AI output."""
    metadata = {
        "significance_rationale": result.significance_rationale,
        "consent_placement_rationale": result.consent_placement_rationale,
        "confidence": result.confidence,
        "is_substantive": result.is_substantive,
        "model": model,
    }
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE agenda_items
               SET summary                 = %s,
                   significance_score      = %s,
                   consent_placement_score = %s,
                   ai_metadata             = %s,
                   ai_prompt_version       = %s,
                   ai_generated_at         = NOW()
             WHERE id = %s
        """, (
            result.summary,
            result.significance_score,
            result.consent_placement_score,
            Json(metadata),
            ITEM_PROMPT_VERSION,
            item_id,
        ))


def mark_item_failed(conn, item_id: int, reason: str) -> None:
    """Permanently mark an item as completed_failed: summary stays NULL, version bumped."""
    metadata = {
        "confidence": "low",
        "is_substantive": None,
        "error": reason,
        "model": None,
    }
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE agenda_items
               SET ai_metadata       = %s,
                   ai_prompt_version = %s,
                   ai_generated_at   = NOW()
             WHERE id = %s
        """, (Json(metadata), ITEM_PROMPT_VERSION, item_id))
```

- [ ] **Step 4: Run tests**

Run: `venv/bin/pytest tests/unit/test_ai_worker_writeback.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/docket/ai/worker.py tests/unit/test_ai_worker_writeback.py
git commit -m "ai: worker writeback for items (success + completed_failed)"
```

---

## Task 13: Worker write-back — meetings + tests

**Files:**
- Modify: `src/docket/ai/worker.py`
- Modify: `tests/unit/test_ai_worker_writeback.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_ai_worker_writeback.py`:

```python
from docket.ai.results import MeetingAIResult
from docket.ai.worker import write_meeting_result, mark_meeting_empty


@pytest.fixture
def seed_meeting():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO municipalities (slug, name, state, adapter_type, base_url, active)
                VALUES ('test_mwb', 'Test', 'AL', 'granicus', 'https://x', TRUE)
                ON CONFLICT (slug) DO UPDATE SET active = TRUE
                RETURNING id
            """)
            muni = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO meetings (municipality_id, meeting_type, meeting_date, source_url)
                VALUES (%s, 'Council', CURRENT_DATE, 'x') RETURNING id
            """, (muni,))
            mid = cur.fetchone()[0]
        conn.commit()
    yield mid
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE id = %s", (mid,))
        conn.commit()


def test_write_meeting_result_provisional(seed_meeting):
    result = MeetingAIResult(
        is_substantive=True, substantive_item_count=3,
        executive_summary="Council considered three items.",
        phase="provisional", confidence="high",
    )
    with db() as conn:
        write_meeting_result(conn, seed_meeting, result, model="claude-sonnet-4-6")
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT executive_summary, ai_metadata, ai_prompt_version
                FROM meetings WHERE id = %s
            """, (seed_meeting,))
            row = cur.fetchone()
    assert row[0] == "Council considered three items."
    assert row[1]["phase"] == "provisional"
    assert row[1]["substantive_item_count"] == 3
    assert row[2] == 1


def test_write_meeting_result_adopted_overwrites(seed_meeting):
    """Adopted pass overwrites a previous provisional summary."""
    prov = MeetingAIResult(is_substantive=True, substantive_item_count=2,
                           executive_summary="prov", phase="provisional", confidence="high")
    adopted = MeetingAIResult(is_substantive=True, substantive_item_count=2,
                              executive_summary="adopted", phase="adopted", confidence="high")
    with db() as conn:
        write_meeting_result(conn, seed_meeting, prov, model="claude-sonnet-4-6")
        conn.commit()
        write_meeting_result(conn, seed_meeting, adopted, model="claude-sonnet-4-6")
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT executive_summary, ai_metadata FROM meetings WHERE id = %s", (seed_meeting,))
            row = cur.fetchone()
    assert row[0] == "adopted"
    assert row[1]["phase"] == "adopted"


def test_mark_meeting_empty(seed_meeting):
    with db() as conn:
        mark_meeting_empty(conn, seed_meeting)
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT executive_summary, ai_metadata, ai_prompt_version
                FROM meetings WHERE id = %s
            """, (seed_meeting,))
            row = cur.fetchone()
    assert row[0] is None
    assert row[1]["is_substantive"] is False
    assert row[1]["substantive_item_count"] == 0
    assert row[1]["model"] is None
    assert row[2] == 1
```

- [ ] **Step 2: Run tests to verify failure**

Run: `venv/bin/pytest tests/unit/test_ai_worker_writeback.py -v -k meeting`
Expected: ImportError on `write_meeting_result` / `mark_meeting_empty`.

- [ ] **Step 3: Append to `worker.py`**

```python
def write_meeting_result(conn, meeting_id: int, result: MeetingAIResult, *, model: str) -> None:
    metadata = {
        "phase": result.phase,
        "is_substantive": result.is_substantive,
        "substantive_item_count": result.substantive_item_count,
        "confidence": result.confidence,
        "model": model,
    }
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE meetings
               SET executive_summary = %s,
                   ai_metadata       = %s,
                   ai_prompt_version = %s,
                   ai_generated_at   = NOW()
             WHERE id = %s
        """, (result.executive_summary, Json(metadata), MEETING_PROMPT_VERSION, meeting_id))


def mark_meeting_empty(conn, meeting_id: int) -> None:
    """Skip Sonnet call: meeting has zero substantive items."""
    metadata = {
        "phase": "provisional",
        "is_substantive": False,
        "substantive_item_count": 0,
        "confidence": "high",
        "model": None,
    }
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE meetings
               SET ai_metadata       = %s,
                   ai_prompt_version = %s,
                   ai_generated_at   = NOW()
             WHERE id = %s
        """, (Json(metadata), MEETING_PROMPT_VERSION, meeting_id))
```

- [ ] **Step 4: Run tests**

Run: `venv/bin/pytest tests/unit/test_ai_worker_writeback.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/docket/ai/worker.py tests/unit/test_ai_worker_writeback.py
git commit -m "ai: worker writeback for meetings (provisional/adopted/empty)"
```

---

## Task 14: Worker run loop + ai_runs accumulation + tests

**Files:**
- Modify: `src/docket/ai/worker.py`
- Create: `tests/unit/test_ai_worker_run.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_ai_worker_run.py
"""Test the worker run loop: claim, process, write back, accumulate ai_runs."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from docket.ai.pricing import Usage
from docket.ai.results import ItemAIResult
from docket.ai.worker import run_once
from docket.db import db


@pytest.fixture
def seed_two_items():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO municipalities (slug, name, state, adapter_type, base_url, active)
                VALUES ('test_run', 'Test', 'AL', 'granicus', 'https://x', TRUE)
                ON CONFLICT (slug) DO UPDATE SET active = TRUE RETURNING id
            """)
            muni = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO meetings (municipality_id, meeting_type, meeting_date, source_url)
                VALUES (%s, 'C', CURRENT_DATE, 'x') RETURNING id
            """, (muni,))
            m = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO agenda_items (meeting_id, title, is_consent, created_at)
                VALUES (%s, 'a', FALSE, NOW() - INTERVAL '1 hour') RETURNING id
            """, (m,))
            id1 = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO agenda_items (meeting_id, title, is_consent, created_at)
                VALUES (%s, 'b', FALSE, NOW() - INTERVAL '1 hour') RETURNING id
            """, (m,))
            id2 = cur.fetchone()[0]
        conn.commit()
    yield (m, id1, id2)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM agenda_items WHERE id IN (%s, %s)", (id1, id2))
            cur.execute("DELETE FROM meetings WHERE id = %s", (m,))
            cur.execute("DELETE FROM ai_runs WHERE stage = 'items' AND notes LIKE 'test_run_%%'")
        conn.commit()


def _stub_item_result():
    return ItemAIResult(
        is_substantive=True,
        significance_rationale="r1", significance_score=5.0,
        consent_placement_rationale="r2", consent_placement_score=5.0,
        summary="ok", confidence="high",
    ), Usage(input_tokens=100, cache_creation_input_tokens=0,
             cache_read_input_tokens=0, output_tokens=50)


def test_run_once_processes_pending_items(seed_two_items, monkeypatch):
    _, id1, id2 = seed_two_items

    fake_client = MagicMock()
    fake_client.summarize_item.side_effect = lambda ctx: _stub_item_result()
    fake_client.item_model = "claude-haiku-4-5-20251001"

    monkeypatch.setattr("docket.ai.worker._make_client", lambda: fake_client)

    summary = run_once(stage="items", limit=10, notes="test_run_basic")

    assert summary.rows_processed == 2
    assert summary.rows_failed == 0
    assert fake_client.summarize_item.call_count == 2

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT summary FROM agenda_items WHERE id = %s", (id1,))
            assert cur.fetchone()[0] == "ok"
            cur.execute("SELECT cost_usd, rows_processed FROM ai_runs WHERE notes = 'test_run_basic'")
            row = cur.fetchone()
            assert row[1] == 2
            assert float(row[0]) > 0
```

- [ ] **Step 2: Run test to verify failure**

Run: `venv/bin/pytest tests/unit/test_ai_worker_run.py -v`
Expected: ImportError on `run_once`.

- [ ] **Step 3: Append to `worker.py`**

```python
# Append to src/docket/ai/worker.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

from docket.ai.client import AIClient
from docket.ai.contexts import AgendaItemContext, MeetingContext
from docket.ai.exceptions import (
    AIFatalError,
    AIPermanentRowError,
    AIRateLimited,
    AITransientError,
)
from docket.ai.pricing import Usage, calculate_cost_usd, usage_add, usage_to_jsonb
from docket.config import (
    ANTHROPIC_API_KEY,
    AI_ITEM_DEBOUNCE_MINUTES,
    AI_MAX_BATCH_SIZE,
)


@dataclass
class RunSummary:
    stage: str
    rows_processed: int = 0
    rows_failed: int = 0
    cost_usd: float = 0.0
    usage: Usage = field(default_factory=lambda: Usage(0, 0, 0, 0))


def _make_client() -> AIClient:
    """Factory wrapped for monkeypatching in tests."""
    return AIClient(api_key=ANTHROPIC_API_KEY or "")


def _open_run(conn, stage: str, model: str, notes: str | None) -> int:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO ai_runs (started_at, stage, model, notes)
            VALUES (NOW(), %s, %s, %s) RETURNING id
        """, (stage, model, notes))
        return cur.fetchone()[0]


def _close_run(conn, run_id: int, summary: RunSummary) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE ai_runs
               SET finished_at    = NOW(),
                   rows_processed = %s,
                   rows_failed    = %s,
                   usage          = %s,
                   cost_usd       = %s
             WHERE id = %s
        """, (summary.rows_processed, summary.rows_failed,
              Json(usage_to_jsonb(summary.usage)), summary.cost_usd, run_id))


def run_once(*, stage: Literal["items", "meetings"],
             limit: int = AI_MAX_BATCH_SIZE,
             notes: str | None = None) -> RunSummary:
    """Process up to `limit` rows for the given stage. Returns summary."""
    if limit > AI_MAX_BATCH_SIZE:
        limit = AI_MAX_BATCH_SIZE

    client = _make_client()
    summary = RunSummary(stage=stage)
    model = client.item_model if stage == "items" else client.meeting_model

    with db() as conn:
        run_id = _open_run(conn, stage, model, notes)
        conn.commit()

        if stage == "items":
            _process_items(conn, client, limit, summary)
        else:
            _process_meetings(conn, client, limit, summary)

        _close_run(conn, run_id, summary)
        conn.commit()

    return summary


def _process_items(conn, client: AIClient, limit: int, summary: RunSummary) -> None:
    with conn.cursor() as cur:
        cur.execute(claim_items_sql(), (ITEM_PROMPT_VERSION, AI_ITEM_DEBOUNCE_MINUTES, limit))
        rows = cur.fetchall()

    columns = ["id", "meeting_id", "title", "description", "sponsor",
               "dollars_amount", "topic", "is_consent"]

    for row in rows:
        row_dict = dict(zip(columns, row))
        ctx = AgendaItemContext.from_row(row_dict)
        try:
            result, usage = client.summarize_item(ctx)
            write_item_result(conn, row_dict["id"], result, model=client.item_model)
            summary.usage = usage_add(summary.usage, usage)
            summary.cost_usd += calculate_cost_usd(client.item_model, usage)
            summary.rows_processed += 1
            conn.commit()
        except AIRateLimited:
            log.warning("Rate limited; ending batch")
            conn.rollback()
            break
        except AITransientError as e:
            log.warning("Transient error on item %s: %s", row_dict["id"], e)
            conn.rollback()
            continue
        except AIPermanentRowError as e:
            log.error("Permanent failure on item %s: %s", row_dict["id"], e)
            conn.rollback()
            mark_item_failed(conn, row_dict["id"], reason=str(e)[:200])
            summary.rows_failed += 1
            conn.commit()
        except AIFatalError:
            log.critical("Fatal error; exiting")
            conn.rollback()
            raise


def _process_meetings(conn, client: AIClient, limit: int, summary: RunSummary) -> None:
    with conn.cursor() as cur:
        cur.execute(claim_meetings_sql(),
                    (MEETING_PROMPT_VERSION, ITEM_PROMPT_VERSION, limit))
        rows = cur.fetchall()

    for row in rows:
        meeting_id, meeting_type, meeting_date, minutes_adopted_at, ai_metadata = row
        # Pre-check substantive item count
        with conn.cursor() as cur:
            cur.execute("""
                SELECT summary
                  FROM agenda_items
                 WHERE meeting_id = %s
                   AND COALESCE(ai_metadata->>'is_substantive', '') = 'true'
                   AND summary IS NOT NULL
                 ORDER BY id
            """, (meeting_id,))
            item_summaries = [r[0] for r in cur.fetchall()]

        if not item_summaries:
            mark_meeting_empty(conn, meeting_id)
            conn.commit()
            summary.rows_processed += 1
            continue

        phase = "adopted" if minutes_adopted_at else "provisional"
        ctx = MeetingContext(
            meeting_id=meeting_id, meeting_type=meeting_type,
            meeting_date=meeting_date, phase=phase,
            item_summaries=item_summaries,
        )
        try:
            result, usage = client.summarize_meeting(ctx)
            write_meeting_result(conn, meeting_id, result, model=client.meeting_model)
            summary.usage = usage_add(summary.usage, usage)
            summary.cost_usd += calculate_cost_usd(client.meeting_model, usage)
            summary.rows_processed += 1
            conn.commit()
        except AIRateLimited:
            log.warning("Rate limited; ending batch")
            conn.rollback()
            break
        except AITransientError as e:
            log.warning("Transient error on meeting %s: %s", meeting_id, e)
            conn.rollback()
            continue
        except AIPermanentRowError as e:
            log.error("Permanent failure on meeting %s: %s", meeting_id, e)
            conn.rollback()
            summary.rows_failed += 1
        except AIFatalError:
            conn.rollback()
            raise
```

- [ ] **Step 4: Run tests**

Run: `venv/bin/pytest tests/unit/test_ai_worker_run.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/docket/ai/worker.py tests/unit/test_ai_worker_run.py
git commit -m "ai: worker run loop with ai_runs telemetry and per-row commits"
```

---

## Task 15: Daily budget check

**Files:**
- Modify: `src/docket/ai/worker.py`
- Modify: `tests/unit/test_ai_worker_run.py`

- [ ] **Step 1: Append failing test**

Append to `tests/unit/test_ai_worker_run.py`:

```python
def test_run_once_refuses_over_budget(seed_two_items, monkeypatch):
    """If today's spend exceeds AI_DAILY_BUDGET_USD, run_once raises unless force_budget=True."""
    from docket.ai.worker import BudgetExceededError
    monkeypatch.setattr("docket.ai.worker.AI_DAILY_BUDGET_USD", 0.001)   # absurdly low

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ai_runs (started_at, finished_at, stage, model, cost_usd)
                VALUES (NOW(), NOW(), 'items', 'claude-haiku-4-5-20251001', 1.0)
            """)
        conn.commit()

    with pytest.raises(BudgetExceededError):
        run_once(stage="items", limit=10, notes="test_run_budget")


def test_run_once_force_budget_overrides(seed_two_items, monkeypatch):
    from docket.ai.worker import BudgetExceededError
    monkeypatch.setattr("docket.ai.worker.AI_DAILY_BUDGET_USD", 0.001)

    fake_client = MagicMock()
    fake_client.summarize_item.side_effect = lambda ctx: _stub_item_result()
    fake_client.item_model = "claude-haiku-4-5-20251001"
    monkeypatch.setattr("docket.ai.worker._make_client", lambda: fake_client)

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ai_runs (started_at, finished_at, stage, model, cost_usd)
                VALUES (NOW(), NOW(), 'items', 'claude-haiku-4-5-20251001', 1.0)
            """)
        conn.commit()

    summary = run_once(stage="items", limit=10, notes="test_run_force", force_budget=True)
    assert summary.rows_processed == 2
```

- [ ] **Step 2: Append to `worker.py`**

```python
from docket.config import AI_DAILY_BUDGET_USD


class BudgetExceededError(Exception):
    """Today's accumulated cost exceeds AI_DAILY_BUDGET_USD."""


def _today_spend(conn) -> float:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COALESCE(SUM(cost_usd), 0) FROM ai_runs
             WHERE started_at >= date_trunc('day', NOW() AT TIME ZONE 'UTC')
        """)
        return float(cur.fetchone()[0])


# Modify run_once signature:
def run_once(*, stage, limit=AI_MAX_BATCH_SIZE, notes=None,
             force_budget: bool = False) -> RunSummary:
    if limit > AI_MAX_BATCH_SIZE:
        limit = AI_MAX_BATCH_SIZE

    with db() as conn:
        spent = _today_spend(conn)
    if spent >= AI_DAILY_BUDGET_USD and not force_budget:
        raise BudgetExceededError(
            f"Today's AI spend ${spent:.2f} >= budget ${AI_DAILY_BUDGET_USD:.2f}; "
            f"pass --force-budget to override"
        )

    # ... rest of run_once unchanged
```

(Replace the existing `run_once` function with the new signature and prepended budget check.)

- [ ] **Step 3: Run tests**

Run: `venv/bin/pytest tests/unit/test_ai_worker_run.py -v`
Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add src/docket/ai/worker.py tests/unit/test_ai_worker_run.py
git commit -m "ai: daily budget check with --force-budget override"
```

---

## Task 16: CLI — status, dry-run, items, meetings

**Files:**
- Create: `src/docket/ai/cli.py`

- [ ] **Step 1: Implement the CLI**

```python
# src/docket/ai/cli.py
"""CLI for the AI pipeline (summaries + scoring).

Examples:
    python -m docket.ai.cli --status
    python -m docket.ai.cli --dry-run --items --limit 5
    python -m docket.ai.cli --items
    python -m docket.ai.cli --meetings --limit 10
    python -m docket.ai.cli --force --meeting-id 5
    python -m docket.ai.cli --items --force-budget
"""

from __future__ import annotations

import argparse
import logging
import sys

from docket.ai.prompts import ITEM_PROMPT_VERSION, MEETING_PROMPT_VERSION
from docket.ai.worker import (
    BudgetExceededError,
    _today_spend,
    claim_items_sql,
    claim_meetings_sql,
    run_once,
)
from docket.config import AI_DAILY_BUDGET_USD, AI_ITEM_DEBOUNCE_MINUTES, AI_MAX_BATCH_SIZE
from docket.db import db


log = logging.getLogger(__name__)


def cmd_status() -> None:
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM agenda_items
                 WHERE (ai_prompt_version IS NULL OR ai_prompt_version < %s)
                   AND created_at < NOW() - (%s || ' minutes')::interval
            """, (ITEM_PROMPT_VERSION, AI_ITEM_DEBOUNCE_MINUTES))
            items_pending = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*) FROM meetings m
                 WHERE (
                   ((m.ai_prompt_version IS NULL OR m.ai_prompt_version < %s)
                    AND m.minutes_adopted_at IS NULL
                    AND COALESCE(m.ai_metadata->>'phase', '') != 'provisional'
                    AND NOT EXISTS (
                      SELECT 1 FROM agenda_items ai
                       WHERE ai.meeting_id = m.id
                         AND (ai.ai_prompt_version IS NULL OR ai.ai_prompt_version < %s)
                    ))
                   OR (m.minutes_adopted_at IS NOT NULL
                       AND COALESCE(m.ai_metadata->>'phase', '') != 'adopted')
                 )
            """, (MEETING_PROMPT_VERSION, ITEM_PROMPT_VERSION))
            meetings_pending = cur.fetchone()[0]

            cur.execute("""
                SELECT id, started_at, stage, rows_processed, rows_failed, cost_usd
                  FROM ai_runs
                 ORDER BY id DESC
                 LIMIT 5
            """)
            recent_runs = cur.fetchall()

            spent_today = _today_spend(conn)

    print(f"Item prompt version:    {ITEM_PROMPT_VERSION}")
    print(f"Meeting prompt version: {MEETING_PROMPT_VERSION}")
    print(f"Items pending:          {items_pending:,}")
    print(f"Meetings pending:       {meetings_pending:,}")
    print(f"Today's spend:          ${spent_today:.4f} / ${AI_DAILY_BUDGET_USD:.2f}")
    print()
    print("Recent runs:")
    for run in recent_runs:
        rid, started, stage, processed, failed, cost = run
        print(f"  #{rid} {started.isoformat()} {stage:8s} processed={processed:5d} "
              f"failed={failed:3d} cost=${float(cost):.4f}")


def cmd_dry_run(stage: str, limit: int) -> None:
    with db() as conn:
        with conn.cursor() as cur:
            if stage == "items":
                cur.execute(claim_items_sql(),
                            (ITEM_PROMPT_VERSION, AI_ITEM_DEBOUNCE_MINUTES, limit))
                rows = cur.fetchall()
                print(f"Would process {len(rows)} item(s):")
                for r in rows:
                    print(f"  item #{r[0]} (meeting={r[1]}) — {r[2][:80]}")
            else:
                cur.execute(claim_meetings_sql(),
                            (MEETING_PROMPT_VERSION, ITEM_PROMPT_VERSION, limit))
                rows = cur.fetchall()
                print(f"Would process {len(rows)} meeting(s):")
                for r in rows:
                    print(f"  meeting #{r[0]} {r[1]} {r[2]}  "
                          f"(adopted={r[3] is not None})")
            conn.rollback()   # release locks


def cmd_force_meeting(meeting_id: int) -> None:
    """Reset a single meeting's prompt version so it'll be re-claimed."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE meetings SET ai_prompt_version = NULL, ai_metadata = NULL WHERE id = %s", (meeting_id,))
            cur.execute("""
                UPDATE agenda_items
                   SET ai_prompt_version = NULL, ai_metadata = NULL,
                       summary = NULL, significance_score = NULL, consent_placement_score = NULL
                 WHERE meeting_id = %s
            """, (meeting_id,))
        conn.commit()
    print(f"Reset AI state for meeting #{meeting_id} and its items.")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI pipeline (summaries + scoring)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--status", action="store_true")
    group.add_argument("--items", action="store_true", help="Process pending items")
    group.add_argument("--meetings", action="store_true", help="Process pending meetings")
    parser.add_argument("--limit", type=int, default=AI_MAX_BATCH_SIZE)
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be processed without calling AI")
    parser.add_argument("--force", action="store_true",
                        help="Bypass version check (with --meeting-id)")
    parser.add_argument("--meeting-id", type=int)
    parser.add_argument("--force-budget", action="store_true",
                        help="Override daily budget cap")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.status:
        cmd_status()
        return

    stage = "items" if args.items else "meetings"

    if args.force and args.meeting_id is None:
        sys.exit("--force requires --meeting-id")
    if args.meeting_id is not None:
        if not args.force:
            sys.exit("--meeting-id requires --force")
        cmd_force_meeting(args.meeting_id)
        return

    if args.dry_run:
        cmd_dry_run(stage, args.limit)
        return

    try:
        summary = run_once(stage=stage, limit=args.limit,
                           notes=f"cli_{stage}", force_budget=args.force_budget)
    except BudgetExceededError as e:
        sys.exit(str(e))

    print(f"Processed {summary.rows_processed} {stage}, "
          f"{summary.rows_failed} failed, cost ${summary.cost_usd:.4f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify CLI parses**

Run: `venv/bin/python -m docket.ai.cli --status`
Expected: prints version, pending counts, today's spend (zero), and "Recent runs:" with whatever exists.

Run: `venv/bin/python -m docket.ai.cli --dry-run --items --limit 5`
Expected: lists up to 5 items that would be processed (or `Would process 0 item(s):`).

- [ ] **Step 3: Commit**

```bash
git add src/docket/ai/cli.py
git commit -m "ai: cli (status, dry-run, items, meetings, force, force-budget)"
```

---

## Task 17: Integration test — end-to-end pipeline

**Files:**
- Create: `tests/integration/test_ai_pipeline_e2e.py`

- [ ] **Step 1: Write the test**

```python
# tests/integration/test_ai_pipeline_e2e.py
"""End-to-end: seed mixed meetings/items, run worker, verify outcomes + ai_runs."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from docket.ai.pricing import Usage
from docket.ai.results import ItemAIResult, MeetingAIResult
from docket.ai.worker import run_once
from docket.db import db


@pytest.fixture
def seeded_e2e():
    """5 meetings × 4 items, mixing substantive/procedural/empty/cancelled."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO municipalities (slug, name, state, adapter_type, base_url, active)
                VALUES ('test_e2e', 'Test E2E', 'AL', 'granicus', 'https://x', TRUE)
                ON CONFLICT (slug) DO UPDATE SET active=TRUE RETURNING id
            """)
            muni = cur.fetchone()[0]

            meetings, items = [], []
            for n in range(5):
                cur.execute("""
                    INSERT INTO meetings (municipality_id, meeting_type, meeting_date, source_url)
                    VALUES (%s, 'Council', CURRENT_DATE - %s, 'x') RETURNING id
                """, (muni, n))
                m_id = cur.fetchone()[0]
                meetings.append(m_id)
                if n == 4:
                    continue   # meeting #4 is empty
                for k in range(4):
                    cur.execute("""
                        INSERT INTO agenda_items (meeting_id, title, is_consent, created_at)
                        VALUES (%s, %s, %s, NOW() - INTERVAL '1 hour') RETURNING id
                    """, (m_id, f"Item {n}-{k}", k % 2 == 0))
                    items.append(cur.fetchone()[0])
        conn.commit()
    yield {"meetings": meetings, "items": items, "muni": muni}
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM agenda_items WHERE meeting_id = ANY(%s)", (meetings,))
            cur.execute("DELETE FROM meetings WHERE id = ANY(%s)", (meetings,))
            cur.execute("DELETE FROM ai_runs WHERE notes LIKE 'test_e2e_%'")
        conn.commit()


def _stub_item():
    return ItemAIResult(
        is_substantive=True,
        significance_rationale="r", significance_score=5.0,
        consent_placement_rationale="r", consent_placement_score=5.0,
        summary="ok", confidence="high",
    ), Usage(100, 0, 0, 50)


def _stub_meeting(item_summaries):
    return MeetingAIResult(
        is_substantive=True,
        substantive_item_count=len(item_summaries),
        executive_summary="meeting ok",
        phase="provisional",
        confidence="high",
    ), Usage(500, 0, 0, 100)


def test_end_to_end(seeded_e2e, monkeypatch):
    fake_client = MagicMock()
    fake_client.item_model = "claude-haiku-4-5-20251001"
    fake_client.meeting_model = "claude-sonnet-4-6"
    fake_client.summarize_item.side_effect = lambda ctx: _stub_item()
    fake_client.summarize_meeting.side_effect = lambda ctx: _stub_meeting(ctx.item_summaries)

    monkeypatch.setattr("docket.ai.worker._make_client", lambda: fake_client)

    items_summary = run_once(stage="items", limit=200, notes="test_e2e_items", force_budget=True)
    assert items_summary.rows_processed == 16   # 4 meetings × 4 items
    assert items_summary.cost_usd > 0

    meetings_summary = run_once(stage="meetings", limit=200, notes="test_e2e_meetings", force_budget=True)
    assert meetings_summary.rows_processed == 5   # 4 substantive + 1 empty (auto-skipped)

    # The empty meeting should be marked is_substantive=false with no API call
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ai_metadata FROM meetings WHERE id = %s
            """, (seeded_e2e["meetings"][4],))
            md = cur.fetchone()[0]
    assert md["is_substantive"] is False
    assert md["substantive_item_count"] == 0
```

- [ ] **Step 2: Run**

Run: `venv/bin/pytest tests/integration/test_ai_pipeline_e2e.py -v`
Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_ai_pipeline_e2e.py
git commit -m "test: ai pipeline end-to-end with mixed meeting/item shapes"
```

---

## Task 18: Integration test — meeting telescoping

**Files:**
- Create: `tests/integration/test_ai_meeting_telescoping.py`

- [ ] **Step 1: Write the test**

```python
# tests/integration/test_ai_meeting_telescoping.py
"""Meeting prompt context must contain item AI summaries (not raw titles)."""

from unittest.mock import MagicMock

import pytest

from docket.ai.client import AIClient
from docket.ai.contexts import MeetingContext
from docket.ai.pricing import Usage
from docket.ai.results import ItemAIResult, MeetingAIResult
from docket.ai.worker import run_once
from docket.db import db


@pytest.fixture
def seeded():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO municipalities (slug, name, state, adapter_type, base_url, active)
                VALUES ('test_tel', 'Test', 'AL', 'granicus', 'https://x', TRUE)
                ON CONFLICT (slug) DO UPDATE SET active=TRUE RETURNING id
            """)
            muni = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO meetings (municipality_id, meeting_type, meeting_date, source_url)
                VALUES (%s, 'C', CURRENT_DATE, 'x') RETURNING id
            """, (muni,))
            m_id = cur.fetchone()[0]
            ids = []
            titles = ["Authorize $4.2M road contract", "Approve 3-year IT support agreement"]
            for t in titles:
                cur.execute("""
                    INSERT INTO agenda_items (meeting_id, title, is_consent, created_at)
                    VALUES (%s, %s, FALSE, NOW() - INTERVAL '1 hour') RETURNING id
                """, (m_id, t))
                ids.append(cur.fetchone()[0])
        conn.commit()
    yield (m_id, ids)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM agenda_items WHERE id = ANY(%s)", (ids,))
            cur.execute("DELETE FROM meetings WHERE id = %s", (m_id,))
        conn.commit()


def test_meeting_prompt_includes_item_summaries(seeded, monkeypatch):
    """Telescoping: the meeting prompt sees ITEM SUMMARIES, not raw titles."""
    captured: list[MeetingContext] = []

    item_summaries = [
        "Approves $4.2M road resurfacing contract.",
        "Authorizes 3-year IT support agreement.",
    ]

    def fake_summarize_item(self, ctx):
        # Use the item title to pick which canned summary to return
        idx = 0 if "road" in ctx.title.lower() else 1
        return ItemAIResult(
            is_substantive=True,
            significance_rationale="r", significance_score=5.0,
            consent_placement_rationale="r", consent_placement_score=5.0,
            summary=item_summaries[idx], confidence="high",
        ), Usage(100, 0, 0, 50)

    def fake_summarize_meeting(self, ctx):
        captured.append(ctx)
        return MeetingAIResult(
            is_substantive=True, substantive_item_count=2,
            executive_summary="ok", phase="provisional", confidence="high",
        ), Usage(500, 0, 0, 100)

    monkeypatch.setattr(AIClient, "summarize_item", fake_summarize_item)
    monkeypatch.setattr(AIClient, "summarize_meeting", fake_summarize_meeting)
    monkeypatch.setattr("docket.config.ANTHROPIC_API_KEY", "test-key", raising=False)
    monkeypatch.setattr("docket.ai.client.ANTHROPIC_API_KEY", "test-key", raising=False)

    run_once(stage="items", limit=10, notes="test_tel_items", force_budget=True)
    run_once(stage="meetings", limit=10, notes="test_tel_meetings", force_budget=True)

    assert len(captured) == 1
    ctx = captured[0]
    rendered = ctx.render_user_prompt()
    assert "Approves $4.2M road resurfacing contract." in rendered
    assert "Authorizes 3-year IT support agreement." in rendered
    # Crucially, the raw titles must NOT appear in the meeting prompt
    assert "Authorize $4.2M road contract" not in rendered
```

- [ ] **Step 2: Run**

Run: `venv/bin/pytest tests/integration/test_ai_meeting_telescoping.py -v`
Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_ai_meeting_telescoping.py
git commit -m "test: meeting prompt telescopes from item summaries (boundary pin)"
```

---

## Task 19: Integration test — phase lifecycle

**Files:**
- Create: `tests/integration/test_ai_phase_lifecycle.py`

- [ ] **Step 1: Write the test**

```python
# tests/integration/test_ai_phase_lifecycle.py
"""Verify provisional → adopted promotion overwrites the meeting summary."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from docket.ai.client import AIClient
from docket.ai.pricing import Usage
from docket.ai.results import ItemAIResult, MeetingAIResult
from docket.ai.worker import run_once
from docket.db import db


@pytest.fixture
def seeded_meeting():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO municipalities (slug, name, state, adapter_type, base_url, active)
                VALUES ('test_phase', 'T', 'AL', 'granicus', 'https://x', TRUE)
                ON CONFLICT (slug) DO UPDATE SET active=TRUE RETURNING id
            """)
            muni = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO meetings (municipality_id, meeting_type, meeting_date, source_url)
                VALUES (%s, 'Council', CURRENT_DATE, 'x') RETURNING id
            """, (muni,))
            m_id = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO agenda_items (meeting_id, title, is_consent, created_at)
                VALUES (%s, 'item', FALSE, NOW() - INTERVAL '1 hour') RETURNING id
            """, (m_id,))
            i_id = cur.fetchone()[0]
        conn.commit()
    yield (m_id, i_id)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM agenda_items WHERE id = %s", (i_id,))
            cur.execute("DELETE FROM meetings WHERE id = %s", (m_id,))
        conn.commit()


def test_provisional_then_adopted(seeded_meeting, monkeypatch):
    m_id, _ = seeded_meeting
    summaries = ["PROVISIONAL summary", "ADOPTED summary"]
    call_idx = {"n": 0}

    def fake_item(self, ctx):
        return ItemAIResult(
            is_substantive=True, significance_rationale="r", significance_score=5.0,
            consent_placement_rationale="r", consent_placement_score=5.0,
            summary="item ok", confidence="high",
        ), Usage(100, 0, 0, 50)

    def fake_meeting(self, ctx):
        out = summaries[min(call_idx["n"], 1)]
        call_idx["n"] += 1
        return MeetingAIResult(
            is_substantive=True, substantive_item_count=1,
            executive_summary=out, phase=ctx.phase, confidence="high",
        ), Usage(500, 0, 0, 100)

    monkeypatch.setattr(AIClient, "summarize_item", fake_item)
    monkeypatch.setattr(AIClient, "summarize_meeting", fake_meeting)
    monkeypatch.setattr("docket.ai.client.ANTHROPIC_API_KEY", "test-key", raising=False)

    # Phase 1: provisional
    run_once(stage="items", limit=10, notes="phase_test_items", force_budget=True)
    run_once(stage="meetings", limit=10, notes="phase_test_prov", force_budget=True)

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT executive_summary, ai_metadata FROM meetings WHERE id = %s", (m_id,))
            row = cur.fetchone()
    assert row[0] == "PROVISIONAL summary"
    assert row[1]["phase"] == "provisional"

    # Phase 2: simulate adoption sweep setting minutes_adopted_at
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE meetings SET minutes_adopted_at = %s WHERE id = %s",
                        (datetime.now(timezone.utc), m_id))
        conn.commit()

    run_once(stage="meetings", limit=10, notes="phase_test_adopt", force_budget=True)

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT executive_summary, ai_metadata FROM meetings WHERE id = %s", (m_id,))
            row = cur.fetchone()
    assert row[0] == "ADOPTED summary"
    assert row[1]["phase"] == "adopted"
```

- [ ] **Step 2: Run**

Run: `venv/bin/pytest tests/integration/test_ai_phase_lifecycle.py -v`
Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_ai_phase_lifecycle.py
git commit -m "test: meeting provisional → adopted phase transition"
```

---

## Task 20: Integration test — prompt-version bump cascade

**Files:**
- Create: `tests/integration/test_ai_prompt_version_bump.py`

- [ ] **Step 1: Write the test**

```python
# tests/integration/test_ai_prompt_version_bump.py
"""Bumping ITEM_PROMPT_VERSION re-runs items; meetings auto-cascade afterward."""

from unittest.mock import MagicMock

import pytest

from docket.ai.client import AIClient
from docket.ai.pricing import Usage
from docket.ai.results import ItemAIResult, MeetingAIResult
from docket.db import db


@pytest.fixture
def seeded_minor():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO municipalities (slug, name, state, adapter_type, base_url, active)
                VALUES ('test_bump', 'T', 'AL', 'granicus', 'https://x', TRUE)
                ON CONFLICT (slug) DO UPDATE SET active=TRUE RETURNING id
            """)
            muni = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO meetings (municipality_id, meeting_type, meeting_date, source_url)
                VALUES (%s, 'C', CURRENT_DATE, 'x') RETURNING id
            """, (muni,))
            mid = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO agenda_items (meeting_id, title, is_consent, created_at)
                VALUES (%s, 'item', FALSE, NOW() - INTERVAL '1 hour') RETURNING id
            """, (mid,))
            iid = cur.fetchone()[0]
        conn.commit()
    yield (mid, iid)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM agenda_items WHERE id = %s", (iid,))
            cur.execute("DELETE FROM meetings WHERE id = %s", (mid,))
        conn.commit()


def test_item_version_bump_recascades(seeded_minor, monkeypatch):
    mid, iid = seeded_minor

    def fake_item(self, ctx):
        return ItemAIResult(
            is_substantive=True, significance_rationale="r", significance_score=5.0,
            consent_placement_rationale="r", consent_placement_score=5.0,
            summary="v1", confidence="high",
        ), Usage(100, 0, 0, 50)

    def fake_meeting(self, ctx):
        return MeetingAIResult(
            is_substantive=True, substantive_item_count=1,
            executive_summary="m-v1", phase="provisional", confidence="high",
        ), Usage(500, 0, 0, 100)

    monkeypatch.setattr(AIClient, "summarize_item", fake_item)
    monkeypatch.setattr(AIClient, "summarize_meeting", fake_meeting)
    monkeypatch.setattr("docket.ai.client.ANTHROPIC_API_KEY", "test-key", raising=False)

    from docket.ai import worker
    worker.run_once(stage="items", limit=10, notes="bump_v1", force_budget=True)
    worker.run_once(stage="meetings", limit=10, notes="bump_v1m", force_budget=True)

    # Bump constants
    monkeypatch.setattr("docket.ai.prompts.ITEM_PROMPT_VERSION", 2)
    monkeypatch.setattr("docket.ai.prompts.MEETING_PROMPT_VERSION", 2)
    # And the references inside worker.py module that imported them at module load
    monkeypatch.setattr("docket.ai.worker.ITEM_PROMPT_VERSION", 2)
    monkeypatch.setattr("docket.ai.worker.MEETING_PROMPT_VERSION", 2)

    def fake_item_v2(self, ctx):
        return ItemAIResult(
            is_substantive=True, significance_rationale="r", significance_score=6.0,
            consent_placement_rationale="r", consent_placement_score=6.0,
            summary="v2", confidence="high",
        ), Usage(100, 0, 0, 50)

    def fake_meeting_v2(self, ctx):
        return MeetingAIResult(
            is_substantive=True, substantive_item_count=1,
            executive_summary="m-v2", phase="provisional", confidence="high",
        ), Usage(500, 0, 0, 100)

    monkeypatch.setattr(AIClient, "summarize_item", fake_item_v2)
    monkeypatch.setattr(AIClient, "summarize_meeting", fake_meeting_v2)

    s_items = worker.run_once(stage="items", limit=10, notes="bump_v2", force_budget=True)
    assert s_items.rows_processed == 1   # the one item was re-claimed

    s_meetings = worker.run_once(stage="meetings", limit=10, notes="bump_v2m", force_budget=True)
    assert s_meetings.rows_processed == 1   # meeting also re-runs (cascade)

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT summary, ai_prompt_version FROM agenda_items WHERE id = %s", (iid,))
            row = cur.fetchone()
            assert row[0] == "v2"
            assert row[1] == 2
            cur.execute("SELECT executive_summary, ai_prompt_version FROM meetings WHERE id = %s", (mid,))
            row = cur.fetchone()
            assert row[0] == "m-v2"
            assert row[1] == 2
```

- [ ] **Step 2: Run**

Run: `venv/bin/pytest tests/integration/test_ai_prompt_version_bump.py -v`
Expected: 1 passed. (If the monkeypatch doesn't override `ITEM_PROMPT_VERSION` because of how it's imported, refactor `worker.py` to read it lazily through a getter instead of binding it at import time.)

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_ai_prompt_version_bump.py
git commit -m "test: prompt-version bump re-cascades items then meetings"
```

---

## Task 21: Live smoke test

**Files:**
- Create: `tests/live/__init__.py`
- Create: `tests/live/test_ai_live_smoke.py`
- Modify: `pyproject.toml` (add pytest marker registration)

- [ ] **Step 1: Create empty `tests/live/__init__.py`**

Empty file.

- [ ] **Step 2: Register the `live` marker**

Open `pyproject.toml`. If a `[tool.pytest.ini_options]` block exists, add:

```toml
markers = ["live: makes real Anthropic API calls; opt-in via --live"]
```

If the block does not exist, add it.

- [ ] **Step 3: Write the live test**

```python
# tests/live/test_ai_live_smoke.py
"""LIVE smoke test — calls real Anthropic API. Run with: pytest -m live tests/live/."""

import os
from datetime import date
from decimal import Decimal

import pytest

from docket.ai.client import AIClient
from docket.ai.contexts import AgendaItemContext, MeetingContext


pytestmark = pytest.mark.live


@pytest.fixture
def client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        pytest.skip("ANTHROPIC_API_KEY not set")
    return AIClient(api_key=key)


def test_haiku_item_smoke(client):
    ctx = AgendaItemContext.from_row({
        "id": 1,
        "title": "Authorize a $4,200,000 contract with ABC Construction for downtown street resurfacing",
        "description": "Three-year contract with optional one-year extension",
        "sponsor": "Public Works Department",
        "dollars_amount": Decimal("4200000.00"),
        "topic": "Public Works",
        "is_consent": False,
    })
    result, usage = client.summarize_item(ctx)
    assert result.is_substantive
    assert result.summary
    assert 0 <= result.significance_score <= 10
    assert usage.input_tokens > 0
    print(f"\nItem result: {result.summary}")
    print(f"Scores: sig={result.significance_score} consent={result.consent_placement_score}")


def test_sonnet_meeting_smoke(client):
    ctx = MeetingContext(
        meeting_id=1,
        meeting_type="Council Meeting",
        meeting_date=date(2026, 4, 1),
        phase="provisional",
        item_summaries=[
            "Approves $4.2M road resurfacing contract.",
            "Authorizes 3-year IT support agreement worth $850K.",
            "Defers vote on short-term rental ordinance to next meeting.",
        ],
    )
    result, usage = client.summarize_meeting(ctx)
    assert result.is_substantive
    assert result.executive_summary
    assert result.phase == "provisional"
    print(f"\nMeeting result: {result.executive_summary}")
```

- [ ] **Step 4: Verify it skips by default**

Run: `venv/bin/pytest tests/live/ -v`
Expected: tests deselected because `-m live` not given (or skipped if `ANTHROPIC_API_KEY` is absent).

- [ ] **Step 5: Verify with --live and a real key (optional manual)**

Set `ANTHROPIC_API_KEY` in your env, then:

Run: `venv/bin/pytest -m live tests/live/ -v -s`
Expected: 2 passed; printed summaries look reasonable.

- [ ] **Step 6: Commit**

```bash
git add tests/live/__init__.py tests/live/test_ai_live_smoke.py pyproject.toml
git commit -m "test: live smoke tests for haiku/sonnet api"
```

---

## Task 22: Wire summaries into web reads

**Files:**
- Modify: `src/docket/services/query.py`

- [ ] **Step 1: Read existing readers**

Run: `venv/bin/grep -n "FROM agenda_items\|FROM meetings " src/docket/services/query.py`

Note the function names that build SELECTs against these tables (likely `list_meetings`, `get_meeting`, `list_items`, etc.).

- [ ] **Step 2: Add new columns to each SELECT**

For each read function that selects from `meetings`, add `executive_summary, ai_metadata, ai_prompt_version, ai_generated_at` to the column list.

For each read function that selects from `agenda_items`, add `summary, ai_metadata, ai_prompt_version, ai_generated_at` to the column list.

For dict-based readers using `db_cursor()`, no further changes needed — the new keys appear automatically.

For dataclass-based readers, add the new fields to the corresponding model in `src/docket/models/`.

- [ ] **Step 3: Run existing query tests**

Run: `venv/bin/pytest tests/ -v -k query`
Expected: existing tests pass (since new columns are nullable, no behavior change).

- [ ] **Step 4: Commit**

```bash
git add src/docket/services/query.py src/docket/models/
git commit -m "query: include ai summary columns in meeting/item reads"
```

---

## Task 23: Render summaries in `meeting_detail.html`

**Files:**
- Modify: `src/docket/web/templates/meeting_detail.html`
- Modify: `src/docket/web/static/styles.css` (or `layout.css` — match existing design pass)

- [ ] **Step 1: Read current template**

Run: `cat src/docket/web/templates/meeting_detail.html | head -80`

Identify the section that renders the meeting header and the items list.

- [ ] **Step 2: Add executive-summary block**

Above the items list, after the meeting header, add:

```jinja
{% if meeting.executive_summary %}
<section class="exec-summary">
  <h2>Executive Summary</h2>
  <p>{{ meeting.executive_summary }}</p>
  {% if meeting.ai_metadata and meeting.ai_metadata.phase == 'provisional' %}
  <p class="badge badge-provisional">Provisional — minutes not yet adopted</p>
  {% endif %}
  {% if meeting.ai_metadata and meeting.ai_metadata.confidence == 'low' %}
  <p class="badge badge-review">[Auto summary — under review]</p>
  {% endif %}
</section>
{% endif %}
```

- [ ] **Step 3: Add per-item summary lines**

Inside the loop that renders agenda items, beneath each item's title, add:

```jinja
{% if item.summary %}
<p class="item-summary">{{ item.summary }}</p>
{% if item.ai_metadata and item.ai_metadata.confidence == 'low' %}
<span class="badge badge-review">[Auto summary — under review]</span>
{% endif %}
{% elif item.ai_prompt_version %}
<p class="item-summary muted">[Auto summary unavailable]</p>
{% endif %}
```

- [ ] **Step 4: Add CSS**

Append to the CSS file matching the existing design pass (likely `static/layout.css` based on CLAUDE.md):

```css
.exec-summary {
  background: var(--surface, #f7f5f0);
  border-left: 3px solid var(--accent, #2a4f6e);
  padding: 1rem 1.25rem;
  margin: 1.5rem 0;
}
.exec-summary h2 { font-size: 1.1rem; margin: 0 0 0.5rem; }
.item-summary {
  color: var(--text-secondary, #555);
  font-size: 0.92rem;
  margin: 0.25rem 0;
}
.item-summary.muted { font-style: italic; opacity: 0.6; }
.badge-provisional { color: #8a6a00; font-size: 0.8rem; }
.badge-review { color: #b04a00; font-size: 0.8rem; }
```

(Match variable names to the existing design system in `styles.css`.)

- [ ] **Step 5: Manual test**

Start the dev server:
```bash
flask --app docket.web run
```

Open a meeting page that has a summary in the DB (after Task 17 fixtures or after running the worker on real data). Visually verify the executive-summary block and per-item summary lines render correctly.

If no summarized data exists locally, run:
```bash
venv/bin/python -m docket.ai.cli --items --limit 5 --force-budget
```
(requires a real `ANTHROPIC_API_KEY`).

- [ ] **Step 6: Commit**

```bash
git add src/docket/web/templates/meeting_detail.html src/docket/web/static/
git commit -m "web: render executive summary, item summaries, and review badges"
```

---

## Task 24: Admin AI panel

**Files:**
- Modify: `src/docket/web/admin.py`
- Create: `src/docket/web/templates/admin/ai_panel.html`

- [ ] **Step 1: Add admin route**

Open `src/docket/web/admin.py` and add:

```python
@admin_bp.route("/ai")
@login_required
def ai_panel():
    from docket.ai.prompts import ITEM_PROMPT_VERSION, MEETING_PROMPT_VERSION
    from docket.config import AI_DAILY_BUDGET_USD, AI_ITEM_DEBOUNCE_MINUTES
    with db_cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) FROM agenda_items
             WHERE (ai_prompt_version IS NULL OR ai_prompt_version < %s)
               AND created_at < NOW() - (%s || ' minutes')::interval
        """, (ITEM_PROMPT_VERSION, AI_ITEM_DEBOUNCE_MINUTES))
        items_pending = cur.fetchone()["count"]

        cur.execute("""
            SELECT COALESCE(SUM(cost_usd), 0)::float AS total,
                   COALESCE(SUM((usage->>'cache_read_input_tokens')::int), 0) AS cache_reads,
                   COALESCE(SUM((usage->>'input_tokens')::int), 0) AS regular_reads
              FROM ai_runs
             WHERE started_at > NOW() - INTERVAL '7 days'
        """)
        seven_day = dict(cur.fetchone())

        cur.execute("""
            SELECT id, started_at, stage, model, rows_processed, rows_failed, cost_usd
              FROM ai_runs
             ORDER BY id DESC
             LIMIT 20
        """)
        runs = [dict(row) for row in cur.fetchall()]

    return render_template(
        "admin/ai_panel.html",
        items_pending=items_pending, seven_day=seven_day, runs=runs,
        budget=AI_DAILY_BUDGET_USD,
        item_version=ITEM_PROMPT_VERSION, meeting_version=MEETING_PROMPT_VERSION,
    )
```

- [ ] **Step 2: Create the template**

```jinja
{# src/docket/web/templates/admin/ai_panel.html #}
{% extends "base.html" %}
{% block content %}
<h1>AI Pipeline</h1>

<section class="kpis">
  <div class="kpi"><span>Items pending</span><strong>{{ "{:,}".format(items_pending) }}</strong></div>
  <div class="kpi"><span>7-day cost</span><strong>${{ "%.4f"|format(seven_day.total) }}</strong></div>
  <div class="kpi"><span>Cache reads</span><strong>{{ "{:,}".format(seven_day.cache_reads) }}</strong></div>
  <div class="kpi"><span>Daily budget</span><strong>${{ "%.2f"|format(budget) }}</strong></div>
</section>

<p>Item prompt version: <code>{{ item_version }}</code> · Meeting prompt version: <code>{{ meeting_version }}</code></p>

<h2>Recent runs</h2>
<table>
  <thead>
    <tr><th>#</th><th>Started</th><th>Stage</th><th>Model</th><th>Processed</th><th>Failed</th><th>Cost</th></tr>
  </thead>
  <tbody>
    {% for r in runs %}
    <tr>
      <td>{{ r.id }}</td>
      <td>{{ r.started_at.strftime('%Y-%m-%d %H:%M') }}</td>
      <td>{{ r.stage }}</td>
      <td>{{ r.model }}</td>
      <td>{{ r.rows_processed }}</td>
      <td>{{ r.rows_failed }}</td>
      <td>${{ "%.4f"|format(r.cost_usd | float) }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

- [ ] **Step 3: Add link from admin index**

Find the existing admin index template and add a link to `/admin/ai`.

- [ ] **Step 4: Manual smoke**

Start the dev server, log in as admin, navigate to `/admin/ai`. Verify counts and the table render. Empty state must work too (zero runs, zero pending).

- [ ] **Step 5: Commit**

```bash
git add src/docket/web/admin.py src/docket/web/templates/admin/ai_panel.html
git commit -m "admin: ai pipeline dashboard panel"
```

---

## Task 25: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add row to status table**

Find the table starting around line 184 ("What's been ported and what hasn't"). Add:

```markdown
| AI summaries + scoring | Done | `src/docket/ai/` — Haiku item summaries, Sonnet meeting executive summaries, two-phase keyed off minutes_adopted_at, ai_runs cost telemetry |
```

- [ ] **Step 2: Add build phase**

Find the "Build phases (reference)" list. Append:

```markdown
17. ~~AI summaries + scoring~~ — DONE (migration 011, ai/ package, Haiku items + Sonnet meetings, two-phase lifecycle, admin panel)
```

- [ ] **Step 3: Add to "Key decisions to preserve"**

Append:

```markdown
- **AI summaries + scoring:** items use Haiku 4.5, meetings use Sonnet 4.6. Two-phase meeting lifecycle keyed off `minutes_adopted_at`. NULL `topic` renders as "Uncategorized" in prompts (never the literal string "None"). Daily budget gate via `AI_DAILY_BUDGET_USD`. Prompt-version bump re-cascades both stages automatically.
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: claude.md updated for ai pipeline (migration 011, ai/ package)"
```

---

## Task 26: Apply migration on Railway, dry-run on prod, manual QA

**Files:**
- None (operational steps)

- [ ] **Step 1: Apply migration on Railway**

Connect to Railway and run migrations:
```bash
railway run python -m docket.migrations.runner
```
Verify with `railway run python -m docket.migrations.runner --status` — expect `[applied] 011: ...`.

- [ ] **Step 2: Confirm queue depth on prod**

```bash
railway run python -m docket.ai.cli --status
```
Expected: items pending in the thousands (entire history); meetings pending in the hundreds.

- [ ] **Step 3: Dry-run inspection**

```bash
railway run python -m docket.ai.cli --dry-run --items --limit 20
```
Expected: 20 candidate items printed. Visually confirm they look like valid agenda items.

- [ ] **Step 4: First production batch (20 items)**

```bash
railway run python -m docket.ai.cli --items --limit 20
```
Expected: `Processed 20 items, 0 failed, cost $0.0X`.

Open the admin panel at `/admin/ai` and the affected meetings' detail pages. Manually inspect the 20 generated summaries against source PDFs.

- [ ] **Step 5: Spot-check accuracy**

Pick 5 items at random; compare each summary to the source agenda PDF (linked via the existing source-doc deep link). Score each: accurate / minor inaccuracy / hallucination / source-not-in-input.

If any hallucinations are found, **stop**. Investigate the prompt and either tighten `ITEM_SYSTEM` (and bump the version) or add explicit constraints. Do not proceed to ramp until accuracy is clean.

- [ ] **Step 6: Ramp**

If clean: 100, 500, 1000 items, then unleash. Monitor `/admin/ai` between each ramp step. The cron jobs configured in Task 27 will pick up the rest automatically.

- [ ] **Step 7: After full backfill, sample 100 rows**

Run a SQL query to pick 100 random summarized items, manually grade for accuracy. Target ≥ 95% clean. If below, it's a prompt-tuning task — bump `ITEM_PROMPT_VERSION`, re-run.

- [ ] **Step 8: No commit (operational only)**

---

## Task 27: Configure cron jobs on Railway

**Files:**
- None (Railway config)

- [ ] **Step 1: In Railway dashboard, add a scheduled job**

Service: docket-web
Schedule: `*/15 * * * *`
Command: `python -m docket.ai.cli --items --limit 200`

- [ ] **Step 2: Add a second scheduled job**

Service: docket-web
Schedule: `*/30 * * * *`
Command: `python -m docket.ai.cli --meetings --limit 50`

- [ ] **Step 3: Verify schedules are active**

In the Railway scheduled-jobs UI, confirm both jobs show "Active" with their next-run times.

After 30 minutes, confirm new `ai_runs` rows appear in `/admin/ai`.

- [ ] **Step 4: No commit**

---

## Self-Review

**Spec coverage check:**

- §3 architecture (decoupled worker, ai/ package, four modules + cli) → Tasks 4–16 ✓
- §4.1 schema migration → Task 2 ✓
- §4.2 ai_metadata JSONB shape → Tasks 12, 13 (write_*_result functions) ✓
- §4.3 ai_runs.usage shape with cache breakdown → Tasks 5, 14 ✓
- §4.4 worker readiness gates (5-min debounce, two-phase meeting) → Task 11 ✓
- §5.1 prompts with rationales-first + topic NULL handling → Tasks 7, 8 ✓
- §5.2 client retry policy + Pydantic + cost tracking → Tasks 6, 9, 10 ✓
- §5.3 worker per-row commits, completed_failed state → Tasks 12, 14 ✓
- §5.4 CLI with all flags → Task 16 ✓
- §5.5 web integration (query.py, meeting_detail.html, admin) → Tasks 22, 23, 24 ✓
- §6 data flow (item lifecycle, meeting two-phase, version bump cascade) → Tasks 17, 18, 19, 20 ✓
- §7.1 cost controls + budget gate → Task 15 ✓
- §7.2 logging → Tasks 14, 16 (basicConfig in CLI) ✓
- §7.3 observability (status, admin panel, stdout) → Tasks 16, 24 ✓
- §7.4 security (env vars, no PII) → Task 3 ✓
- §8 testing strategy (unit + integration + live) → Tasks 5–10, 14, 15, 17–21 ✓
- §9 acceptance criteria → Tasks 26 (manual QA), 27 (cron) ✓
- §10 out-of-scope items → not implemented (correct) ✓

**Placeholder scan:** No "TBD", "TODO", or "implement appropriate error handling" instances. All code blocks contain real code; all commands are exact.

**Type consistency check:** Verified `Usage`, `ItemAIResult`, `MeetingAIResult`, `AgendaItemContext`, `MeetingContext`, `RunSummary`, `BudgetExceededError` are all referenced consistently across tasks. `claim_items_sql()` / `claim_meetings_sql()` argument signatures match between definition (Task 11) and callers (Tasks 14, 16). `_make_client` factory pattern is consistent between worker.py (Task 14) and the integration test monkeypatches (Tasks 17–20).

One minor inconsistency to note for the implementer: Task 20's monkeypatch of `ITEM_PROMPT_VERSION` may not work if `worker.py` does `from ... import ITEM_PROMPT_VERSION` at module load. If the test fails with the expected version still being 1, refactor `worker.py` to access the constants via `prompts.ITEM_PROMPT_VERSION` (lazy lookup) rather than rebinding at import. Comment in the task notes this caveat.
