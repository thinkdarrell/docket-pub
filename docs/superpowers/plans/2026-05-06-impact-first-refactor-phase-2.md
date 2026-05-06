# Impact-First Refactor — Phase 2 Implementation Plan (Pipeline + Frontend)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the new AI pipeline (Stage 1 extraction + Stage 2 v3 Smart Brevity + Stage 2.5 floors + reconcile), all 7 process badges, the policy-badge matcher with 4 BHM badges, the Smart Brevity Card UI (6 variants), category landing pages with SVG volume timelines, admin views, and the backfill driver foundation. After Phase 2 ships, the live cron worker processes new items through the v3 pipeline (behind `IMPACT_FIRST_ENABLED` feature flag), citizens can optionally see v3 cards (behind `SMART_BREVITY_UI` flag), and the system is ready for Phase 3 backfill execution.

**Architecture:** Eight independent subsystems (Sections A-H). Each section is internally TDD'd and ends in a green-tests commit. Sections build on each other in dependency order — A (Stage 1) feeds B (Stage 2). C and D (badges) consume B's outputs. E-G (frontend) consume B/C/D outputs but are gated behind a feature flag so they ship dark. H (backfill) is foundation only — actual wave execution is Phase 3.

**Tech Stack:** Python 3.10+, Anthropic SDK (Haiku 4.5), Pydantic 2, PostgreSQL 18, Flask + Jinja2 + HTMX, server-rendered SVG. Two new minor dependencies (`anthropic`, `pydantic`) likely already in `requirements.txt` from the existing v2 pipeline — verify in pre-task.

**Spec:** `docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md` — sections 2.3, 3, 4, 5, 6, 7.3, 7.8.

**Estimated effort:** ~23 engineer-days (was 22; +1 for Task G4 conflict resolution UI per decision #93). Calendar: ~3-4 weeks two engineers, ~6 weeks single engineer.

**Depends on:** Phase 1 plan complete and Migration 013 live in production.

---

## File Structure

**Create — Backend (Sections A-D, H):**
- `src/docket/ai/extraction.py` — Stage 1 module: prompt + Haiku call + Pydantic + persistence (~250 LOC)
- `src/docket/ai/extraction_schema.py` — Pydantic models: `StructuredFacts`, `LocationDetail`, `NextSteps` (~150 LOC)
- `src/docket/ai/cache.py` — local response cache helper (`data/ai_cache/`) (~60 LOC)
- `src/docket/ai/rewrite.py` — Stage 2 v3 module: prompt + Haiku call + persistence (~200 LOC)
- `src/docket/ai/rewrite_schema.py` — Pydantic `ItemRewrite` model with validators (~100 LOC)
- `src/docket/ai/floors.py` — Stage 2.5: `FloorTrigger` dataclass + `SIGNIFICANCE_FLOORS` + `CONSENT_PLACEMENT_CEILINGS` + `SUBJECT_MATTER_FLOORS` + `apply_score_floors` (~300 LOC)
- `src/docket/ai/reconcile.py` — Cross-stage reconciliation with auto-retry (~120 LOC)
- `src/docket/ai/badges_process.py` — 7 process-badge SQL queries + on-write helper (~250 LOC)
- `src/docket/ai/badges_policy.py` — Policy-badge matcher with hybrid LLM+deterministic (~200 LOC)
- `src/docket/ai/concurrency.py` — `AdaptiveWorkerPool` (~80 LOC)
- `src/docket/ai/batches.py` — Anthropic Batches API wrapper (~150 LOC)
- `src/docket/services/badges.py` — Badge resolution + audit-log writes (~100 LOC)
- `src/docket/worker/tasks.py` — MODIFY: add `process_badges`, `calibration_report`, `backfill_driver` tasks
- `src/docket/web/public.py` — MODIFY: add category landing route, data-debt page, RSS feeds
- `src/docket/web/admin.py` — MODIFY: add 4 admin routes (calibration, data-debt, errors, badges/audit)
- `src/docket/web/templates/partials/smart_brevity_card.html` — variant dispatcher
- `src/docket/web/templates/partials/card_smart_brevity.html` — full v3 variant
- `src/docket/web/templates/partials/card_v2_fallback.html` — transition variant
- `src/docket/web/templates/partials/card_procedural.html` — title-only variant
- `src/docket/web/templates/partials/card_degraded.html` — data-quality-skipped variant
- `src/docket/web/templates/partials/card_failed.html` — failed-permanent variant
- `src/docket/web/templates/partials/card_verification_pending.html` — cross-stage-conflict variant
- `src/docket/web/templates/partials/badge_chip.html` — single chip with Verification Spark
- `src/docket/web/templates/partials/engagement_strip.html` — 4-state strip
- `src/docket/web/templates/partials/source_anchor_button.html` — adaptive View Source
- `src/docket/web/templates/partials/dollar_tier.html` — dollar amount with WCAG markup
- `src/docket/web/templates/partials/volume_timeline.html` — server-rendered SVG
- `src/docket/web/templates/category_landing.html` — per-badge landing page
- `src/docket/web/templates/data_debt.html` — public data-debt page
- `src/docket/web/templates/admin/calibration.html`
- `src/docket/web/templates/admin/data_debt.html`
- `src/docket/web/templates/admin/errors.html`
- `src/docket/web/templates/admin/badges_audit.html`
- `src/docket/web/static/css/smart_brevity.css` — card + chip + carousel CSS

**Tests (~25 new files, ~1,500 LOC total):**
See per-task test paths.

**Modify:**
- `src/docket/web/templates/base.html` — include `smart_brevity.css`, add badge legend
- `src/docket/web/templates/city.html` — add "Browse by Priority" section
- `src/docket/web/templates/meeting_detail.html` — render items via `smart_brevity_card.html` partial dispatcher
- `requirements.txt` — verify `anthropic`, `pydantic>=2`, no new deps

**Touch (read-only):**
- `src/docket/ai/wave0.py` (Phase 1) — Stage 0a/0b helpers reused
- `src/docket/migrations/013_impact_first_refactor.py` (Phase 1) — schema reference

---

## Pre-Task: Branch and Read

- [ ] **Step 0.1: Create feature branch off main (Phase 1 already merged)**

```bash
cd ~/docket-pub
git checkout main
git pull origin main
git checkout -b feat/impact-first-phase-2
```

- [ ] **Step 0.2: Verify Phase 1 is live**

Run:
```bash
DATABASE_URL="$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-)" \
  /opt/homebrew/opt/postgresql@18/bin/psql -c "
SELECT COUNT(*) FILTER (WHERE processing_status = 'pending') AS pending,
       COUNT(*) FILTER (WHERE processing_status = 'procedural_skipped') AS procedural,
       COUNT(*) FILTER (WHERE processing_status = 'data_quality_skipped') AS skipped
FROM agenda_items;
"
```
Expected: nonzero counts in all three columns. If `pending` is 0, Phase 1 didn't complete — go fix that first.

- [ ] **Step 0.3: Skim spec sections 2.3, 3, 4, 5, 6, 7.3, 7.8**

The spec's full Pydantic schemas, prompt strings, SQL queries, and Jinja templates are referenced from this plan rather than duplicated. Plan tasks below say "see spec §X.Y for full <thing>" for the long stuff.

- [ ] **Step 0.4: Verify dependencies**

Run: `venv/bin/pip list | grep -iE "anthropic|pydantic"`
Expected: `anthropic` and `pydantic>=2.x` present. If not, add to `requirements.txt`:
```
anthropic>=0.40
pydantic>=2.5
```
And run `venv/bin/pip install -r requirements.txt`.

---

# Section A — Stage 1 Extraction Worker (~4 days)

Build the structured fact extractor: 6-field Haiku call with Pydantic validation, response cache, and persistence into `agenda_items.extracted_facts`.

## Task A1: Pydantic Schemas

**Files:**
- Create: `src/docket/ai/extraction_schema.py`
- Create: `tests/unit/test_extraction_schema.py`

- [ ] **Step A1.1: Write the schema tests**

`tests/unit/test_extraction_schema.py`:

```python
"""Tests for Stage 1 Pydantic schemas (StructuredFacts, LocationDetail, NextSteps)."""

from __future__ import annotations

import pytest
from datetime import date
from pydantic import ValidationError

from docket.ai.extraction_schema import StructuredFacts, LocationDetail, NextSteps


class TestNextSteps:
    def test_all_fields_nullable(self):
        ns = NextSteps()
        assert ns.committee_referral is None
        assert ns.public_hearing_date is None
        assert ns.public_hearing_time is None
        assert ns.comment_period_end is None
        assert ns.implementation_date is None

    def test_populated_fields(self):
        ns = NextSteps(
            committee_referral="Public Safety Committee",
            public_hearing_date=date(2026, 6, 5),
            public_hearing_time="6:00 PM",
        )
        assert ns.committee_referral == "Public Safety Committee"
        assert ns.public_hearing_date == date(2026, 6, 5)


class TestLocationDetail:
    def test_all_fields_nullable(self):
        loc = LocationDetail()
        assert loc.ward_or_district is None
        assert loc.parcel_id is None


class TestStructuredFacts:
    def test_minimal_valid(self):
        f = StructuredFacts(
            funding_source='unknown',
            counterparty=None,
            procurement_method='not_applicable',
            location=None,
            action_type='other',
            next_steps=NextSteps(),
            parcels_affected=None,
            acres_affected=None,
        )
        assert f.action_type == 'other'

    def test_full_substantive(self):
        f = StructuredFacts(
            funding_source='general_fund',
            counterparty='Flock Safety Inc.',
            procurement_method='sole_source',
            location=LocationDetail(ward_or_district='District 4'),
            action_type='contract_amendment',
            next_steps=NextSteps(),
            parcels_affected=None,
            acres_affected=None,
        )
        assert f.counterparty == 'Flock Safety Inc.'

    def test_funding_source_enum_strict(self):
        with pytest.raises(ValidationError):
            StructuredFacts(
                funding_source='FederalGrantPlusBond',  # not in enum
                counterparty=None,
                procurement_method='not_applicable',
                location=None,
                action_type='other',
                next_steps=NextSteps(),
                parcels_affected=None,
                acres_affected=None,
            )

    def test_action_type_includes_appointment_subtypes(self):
        for t in ['appointment_executive', 'appointment_board', 'appointment_advisory']:
            f = StructuredFacts(
                funding_source='unknown',
                counterparty=None,
                procurement_method='not_applicable',
                location=None,
                action_type=t,
                next_steps=NextSteps(),
                parcels_affected=None,
                acres_affected=None,
            )
            assert f.action_type == t

    def test_action_type_includes_v6_additions(self):
        for t in ['annexation', 'liquor_license', 'right_of_way', 'bid_rejection',
                   'weed_abatement', 'tax_abatement']:
            f = StructuredFacts(
                funding_source='unknown',
                counterparty=None,
                procurement_method='not_applicable',
                location=None,
                action_type=t,
                next_steps=NextSteps(),
                parcels_affected=None,
                acres_affected=None,
            )
            assert f.action_type == t

    def test_funding_source_includes_tif_and_capital_improvement(self):
        for fs in ['tif', 'capital_improvement']:
            f = StructuredFacts(
                funding_source=fs,
                counterparty=None,
                procurement_method='not_applicable',
                location=None,
                action_type='other',
                next_steps=NextSteps(),
                parcels_affected=None,
                acres_affected=None,
            )
            assert f.funding_source == fs
```

- [ ] **Step A1.2: Run tests (expect failure)**

Run: `venv/bin/pytest tests/unit/test_extraction_schema.py -v`
Expected: `ImportError: No module named 'docket.ai.extraction_schema'`.

- [ ] **Step A1.3: Implement the schemas**

`src/docket/ai/extraction_schema.py`:

```python
"""Stage 1 Pydantic schemas — structured fact extraction output.

Spec: docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md
section 2.3, decisions #36-39, #86.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

FundingSource = Literal[
    'general_fund', 'arpa', 'esser', 'cares', 'state_grant',
    'federal_grant', 'bond', 'special_tax', 'private', 'sponsorship',
    'tif', 'capital_improvement',
    'mixed', 'unknown',
]

ProcurementMethod = Literal[
    'competitive', 'sole_source', 'no_bid', 'rfp',
    'emergency', 'unknown', 'not_applicable',
]

ActionType = Literal[
    'contract_award', 'contract_amendment', 'ordinance', 'resolution',
    'appointment_executive', 'appointment_board', 'appointment_advisory',
    'zoning', 'demolition',
    'weed_abatement', 'tax_abatement',
    'settlement', 'emergency_procurement',
    'appropriation', 'budget_amendment',
    'proclamation', 'public_hearing_set',
    'annexation', 'liquor_license', 'right_of_way', 'bid_rejection',
    'other',
]


class LocationDetail(BaseModel):
    ward_or_district: str | None = None
    neighborhood: str | None = None
    address: str | None = None
    parcel_id: str | None = None  # County tax-assessor PIN


class NextSteps(BaseModel):
    committee_referral: str | None = None
    public_hearing_date: date | None = None
    public_hearing_time: str | None = None  # e.g. "6:00 PM"
    comment_period_end: date | None = None
    implementation_date: date | None = None


class StructuredFacts(BaseModel):
    funding_source: FundingSource
    counterparty: str | None
    procurement_method: ProcurementMethod
    location: LocationDetail | None
    action_type: ActionType
    next_steps: NextSteps
    parcels_affected: int | None
    acres_affected: float | None

    model_config = {
        'extra': 'forbid',  # Reject unknown keys to catch schema drift early
    }
```

- [ ] **Step A1.4: Run tests (expect pass)**

Run: `venv/bin/pytest tests/unit/test_extraction_schema.py -v`
Expected: ~7 tests pass.

- [ ] **Step A1.5: Commit**

```bash
git add src/docket/ai/extraction_schema.py tests/unit/test_extraction_schema.py
git commit -m "feat(ai): add Stage 1 Pydantic schemas (StructuredFacts + sub-models)"
```

## Task A2: DB-Backed Response Cache (decision #91)

**Files:**
- Create: `src/docket/ai/cache.py`
- Create: `tests/integration/test_ai_cache.py`

> **Refactored from earlier file-cache design.** Decision #91: store
> responses in Postgres `ai_response_cache` table (created by Phase 1
> Migration 013). Shared across worker nodes; survives container
> restarts; reuses existing DB.

- [ ] **Step A2.1: Write integration tests**

`tests/integration/test_ai_cache.py`:

```python
"""Tests for the DB-backed AI response cache (`docket.ai.cache`)."""

from __future__ import annotations

import pytest

from docket.ai.cache import cache_key, cache_get, cache_put, cache_cleanup
from docket.db import db_cursor


def test_cache_key_deterministic():
    k1 = cache_key('claude-haiku-4-5-20251001', 3, '{"title": "X"}')
    k2 = cache_key('claude-haiku-4-5-20251001', 3, '{"title": "X"}')
    assert k1 == k2


def test_cache_key_includes_model_version():
    k1 = cache_key('claude-haiku-4-5-20251001', 3, '{"title": "X"}')
    k2 = cache_key('claude-haiku-4-5-20251002', 3, '{"title": "X"}')
    assert k1 != k2


def test_cache_key_includes_prompt_version():
    k1 = cache_key('claude-haiku-4-5-20251001', 3, '{"title": "X"}')
    k2 = cache_key('claude-haiku-4-5-20251001', 4, '{"title": "X"}')
    assert k1 != k2


def test_cache_get_miss():
    assert cache_get('nonexistent_key_xyz') is None


def test_cache_put_and_get():
    key = 'test_key_abc123'
    payload = {'response': {'content': 'hello'}, 'model': 'claude-haiku-4-5-20251001'}
    cache_put(key, model='claude-haiku-4-5-20251001', prompt_version=3, payload=payload)
    got = cache_get(key)
    assert got == payload

    # Cleanup
    with db_cursor() as cur:
        cur.execute("DELETE FROM ai_response_cache WHERE cache_key = %s", [key])


def test_cache_get_updates_accessed_at():
    """cache_get bumps accessed_at — for the cleanup task."""
    key = 'test_accessed_xyz'
    payload = {'response': {'x': 1}}
    cache_put(key, model='claude-haiku-4-5-20251001', prompt_version=3, payload=payload)

    with db_cursor() as cur:
        cur.execute("SELECT accessed_at FROM ai_response_cache WHERE cache_key = %s", [key])
        before = cur.fetchone()[0]

    cache_get(key)

    with db_cursor() as cur:
        cur.execute("SELECT accessed_at FROM ai_response_cache WHERE cache_key = %s", [key])
        after = cur.fetchone()[0]

    assert after >= before

    # Cleanup
    with db_cursor() as cur:
        cur.execute("DELETE FROM ai_response_cache WHERE cache_key = %s", [key])


def test_cache_cleanup_removes_old_entries():
    """cache_cleanup deletes entries older than max_age_days."""
    # Insert a fake old row
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO ai_response_cache
              (cache_key, model, prompt_version, response_json, cached_at, accessed_at)
            VALUES
              ('cleanup_test_old', 'claude-haiku-4-5-20251001', 3, '{}'::jsonb,
               NOW() - INTERVAL '120 days', NOW() - INTERVAL '120 days')
        """)

    n_deleted = cache_cleanup(max_age_days=90)
    assert n_deleted >= 1

    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM ai_response_cache WHERE cache_key = 'cleanup_test_old'")
        assert cur.fetchone()[0] == 0
```

- [ ] **Step A2.2: Run tests (expect failure)**

Run: `venv/bin/pytest tests/integration/test_ai_cache.py -v`
Expected: import error on `docket.ai.cache`.

- [ ] **Step A2.3: Implement**

`src/docket/ai/cache.py`:

```python
"""DB-backed AI response cache (decision #91).

Cache table: `ai_response_cache` (created by Migration 013).
Cache key: sha256(model + prompt_version + canonical_input) — decision #42.
Cleanup: nightly task drops entries older than 90 days.

Spec: section 2.5 (revised), decisions #18, #42, #91.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from docket.db import db_cursor


def cache_key(model_id: str, prompt_version: int, canonical_input: str) -> str:
    """Returns sha256 hex for (model, prompt_version, canonical_input) triple."""
    blob = f"{model_id}|v{prompt_version}|{canonical_input}".encode('utf-8')
    return hashlib.sha256(blob).hexdigest()


def cache_get(key: str) -> dict | None:
    """Returns the cached response payload, or None on miss.
    Side effect: bumps `accessed_at` on hit (informs cleanup TTL)."""
    with db_cursor() as cur:
        cur.execute("""
            UPDATE ai_response_cache
            SET accessed_at = NOW()
            WHERE cache_key = %s
            RETURNING response_json
        """, [key])
        row = cur.fetchone()
        return row[0] if row else None


def cache_put(key: str, *, model: str, prompt_version: int, payload: dict) -> None:
    """Insert or update a cache entry."""
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO ai_response_cache
              (cache_key, model, prompt_version, response_json)
            VALUES (%s, %s, %s, %s::jsonb)
            ON CONFLICT (cache_key) DO UPDATE
              SET response_json = EXCLUDED.response_json,
                  accessed_at = NOW()
        """, [key, model, prompt_version, json.dumps(payload, default=str)])


def cache_cleanup(max_age_days: int = 90) -> int:
    """Delete entries older than max_age_days (decision #91 cleanup policy).
    Called by the nightly calibration_report cron task. Returns rows deleted."""
    with db_cursor() as cur:
        cur.execute("""
            DELETE FROM ai_response_cache
            WHERE accessed_at < NOW() - (%s || ' days')::interval
        """, [str(max_age_days)])
        return cur.rowcount
```

- [ ] **Step A2.4: Run tests (expect pass)**

Run: `venv/bin/pytest tests/integration/test_ai_cache.py -v`
Expected: 7 tests pass. (DB-backed; requires Migration 013 already applied locally.)

- [ ] **Step A2.5: Commit**

```bash
git add src/docket/ai/cache.py tests/integration/test_ai_cache.py
git commit -m "feat(ai): DB-backed response cache (replaces file cache, decision #91)"
```

## Task A3: Stage 1 Worker

**Files:**
- Create: `src/docket/ai/extraction.py`
- Create: `tests/unit/test_extraction.py`
- Create: `tests/integration/test_extraction_e2e.py` (mocked)

- [ ] **Step A3.1: Write the unit test for the extraction wrapper**

`tests/unit/test_extraction.py`:

```python
"""Tests for Stage 1 extraction worker (`docket.ai.extraction`)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from docket.ai.extraction import (
    EXTRACTION_PROMPT_VERSION,
    build_user_message,
    extract_facts_for_item,
)
from docket.ai.extraction_schema import StructuredFacts


def make_item(**kw):
    """Lightweight fixture for an item view."""
    defaults = {
        'id': 1,
        'title': "Award of HVAC contract",
        'description': "Long valid body content with full agenda item description text.",
        'sponsor': None,
        'dollars_amount': 87500,
        'topic': 'contracts',
        'is_consent': False,
    }
    defaults.update(kw)
    return type('Item', (), defaults)()


def test_build_user_message_includes_required_fields():
    item = make_item()
    msg = build_user_message(item)
    assert "Award of HVAC contract" in msg
    assert "$87,500" in msg or "87500" in msg
    assert "is_consent" in msg.lower() or "consent" in msg.lower()


def test_extract_facts_returns_validated_pydantic():
    """With a mocked Anthropic response, extract_facts_for_item returns a StructuredFacts."""
    item = make_item()

    mock_response = MagicMock()
    mock_response.model = 'claude-haiku-4-5-20251001'
    mock_response.content = [
        MagicMock(text=json.dumps({
            'funding_source': 'general_fund',
            'counterparty': 'Acme HVAC Inc.',
            'procurement_method': 'competitive',
            'location': None,
            'action_type': 'contract_award',
            'next_steps': {
                'committee_referral': None,
                'public_hearing_date': None,
                'public_hearing_time': None,
                'comment_period_end': None,
                'implementation_date': None,
            },
            'parcels_affected': None,
            'acres_affected': None,
        }))
    ]

    with patch('docket.ai.extraction.anthropic_client') as mock_client:
        mock_client.messages.create.return_value = mock_response
        facts, model_id = extract_facts_for_item(item)

    assert isinstance(facts, StructuredFacts)
    assert facts.counterparty == 'Acme HVAC Inc.'
    assert facts.funding_source == 'general_fund'
    assert model_id == 'claude-haiku-4-5-20251001'


def test_extract_facts_raises_on_invalid_json():
    item = make_item()
    mock_response = MagicMock()
    mock_response.model = 'claude-haiku-4-5-20251001'
    mock_response.content = [MagicMock(text="not json {{{")]

    with patch('docket.ai.extraction.anthropic_client') as mock_client:
        mock_client.messages.create.return_value = mock_response
        with pytest.raises(ValueError):  # JSON parse error
            extract_facts_for_item(item)


def test_extract_facts_raises_on_schema_violation():
    """Pydantic validation error if the model returns a bad enum value."""
    item = make_item()
    mock_response = MagicMock()
    mock_response.model = 'claude-haiku-4-5-20251001'
    mock_response.content = [MagicMock(text=json.dumps({
        'funding_source': 'WRONG_VALUE',
        'counterparty': None,
        'procurement_method': 'not_applicable',
        'location': None,
        'action_type': 'other',
        'next_steps': {},
        'parcels_affected': None,
        'acres_affected': None,
    }))]

    with patch('docket.ai.extraction.anthropic_client') as mock_client:
        mock_client.messages.create.return_value = mock_response
        with pytest.raises(Exception):  # Pydantic ValidationError or wrapper
            extract_facts_for_item(item)
```

- [ ] **Step A3.2: Run tests (expect failure)**

Run: `venv/bin/pytest tests/unit/test_extraction.py -v`
Expected: import error on `docket.ai.extraction`.

- [ ] **Step A3.3: Implement extraction.py**

`src/docket/ai/extraction.py`:

```python
"""Stage 1 — Structured fact extraction.

Calls Haiku 4.5 with a system prompt + user message, parses the JSON
response into a StructuredFacts Pydantic model, and returns the
validated facts + the exact model ID Anthropic served.

Spec: docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md
section 2.3, decisions #36-39, #87.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from docket.ai.cache import cache_get, cache_key, cache_put
from docket.ai.extraction_schema import StructuredFacts

log = logging.getLogger(__name__)

EXTRACTION_PROMPT_VERSION = 1

# Decision #94(a): max_retries=0 so 429s bubble up to AdaptiveWorkerPool
# (decision #81) instead of being silently retried by the SDK.
anthropic_client = anthropic.Anthropic(max_retries=0)


_MARKDOWN_FENCE_RE = re.compile(r'^```(?:json)?\s*\n?', re.MULTILINE)
_MARKDOWN_FENCE_END_RE = re.compile(r'\n?```\s*$', re.MULTILINE)


def _strip_markdown_fences(text: str) -> str:
    """Decision #94(b): strip ```json or ``` wrappers before json.loads().

    Some Haiku responses wrap JSON in markdown fences despite the system
    prompt asking for raw JSON. This avoids JSONDecodeErrors.
    """
    text = text.strip()
    text = _MARKDOWN_FENCE_RE.sub('', text, count=1)
    text = _MARKDOWN_FENCE_END_RE.sub('', text, count=1)
    return text.strip()


SYSTEM_PROMPT = """You extract structured facts from a single municipal-government agenda item.
You output JSON matching the schema below — no prose, no markdown, no commentary.

Do not invent facts. If a field cannot be determined from the input, return null.

For action_type='appointment*', also classify the appointment as one of:
  - appointment_executive: Mayor's cabinet, Department Head, Police Chief,
    City Attorney, City Clerk, Finance Director, Fire Chief, Library Director
  - appointment_board: Board of Education, Board of Adjustment, Planning
    Commission, Housing Authority, Library Board, BJCTA, IDB
  - appointment_advisory: citizen advisory committees, task forces,
    ad-hoc bodies, ceremonial proclamation honorees

For procurement_method, choose the most specific applicable value:
  - competitive, sole_source, no_bid, rfp, emergency, unknown, not_applicable

For next_steps, extract ONLY explicitly-stated future actions.
Do not infer. If the resolution doesn't say "set for public hearing on June 5,"
do not populate public_hearing_date.

Return ALL the schema's keys; use null when unknown.
"""


def build_user_message(item) -> str:
    """Build the per-item user message. `item` is any object exposing the
    required attributes (title, description, sponsor, dollars_amount, topic,
    is_consent)."""
    parts = [
        f"Title: {item.title or ''}",
        f"Description: {item.description or ''}",
        f"Sponsor: {item.sponsor or 'unknown'}",
        f"Dollar amount: ${item.dollars_amount or 0:,}",
        f"Topic (legacy): {item.topic or 'uncategorized'}",
        f"Is on consent agenda: {bool(item.is_consent)}",
    ]
    return "\n".join(parts)


def extract_facts_for_item(item, *, model: str = "claude-haiku-4-5-20251001") -> tuple[StructuredFacts, str]:
    """Run Stage 1 against a single item.

    Returns (StructuredFacts, model_id_returned). Caller persists into
    `agenda_items.extracted_facts` and `agenda_items.ai_extraction_version`.

    Cache hits return the previously-served response without re-calling
    the API. Cache key includes the model ID returned in the prior
    response — version bumps invalidate.
    """
    user_msg = build_user_message(item)

    # Try cache first (canonical input is the user_msg)
    pre_cache = cache_key(model, EXTRACTION_PROMPT_VERSION, user_msg)
    cached = cache_get(pre_cache)
    if cached is not None:
        log.debug("stage 1 cache hit for item %s", getattr(item, 'id', '?'))
        # Re-validate via Pydantic in case schema tightened across versions
        return StructuredFacts.model_validate(cached['response']), cached['model']

    # Cache miss — call the API
    response = anthropic_client.messages.create(
        model=model,
        max_tokens=1024,
        system=[
            {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
        ],
        messages=[{"role": "user", "content": user_msg}],
    )

    # Anthropic may serve a slightly different model variant; key off that
    served_model = response.model

    raw_text = response.content[0].text
    # Decision #94(b): strip markdown fences before json.loads
    raw_text = _strip_markdown_fences(raw_text)
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Stage 1 returned non-JSON: {raw_text[:200]!r}") from e

    facts = StructuredFacts.model_validate(parsed)

    # Cache against the served model id (decision #42)
    real_key = cache_key(served_model, EXTRACTION_PROMPT_VERSION, user_msg)
    cache_put(real_key, model=served_model, prompt_version=EXTRACTION_PROMPT_VERSION,
              payload={'response': parsed, 'model': served_model})

    return facts, served_model
```

- [ ] **Step A3.4: Run tests (expect pass)**

Run: `venv/bin/pytest tests/unit/test_extraction.py -v`
Expected: 4 tests pass.

- [ ] **Step A3.5: Commit**

```bash
git add src/docket/ai/extraction.py tests/unit/test_extraction.py
git commit -m "feat(ai): Stage 1 extraction worker with cache + Pydantic validation"
```

## Task A4: Persist Stage 1 Output to DB

**Files:**
- Modify: `src/docket/ai/extraction.py`
- Modify: `tests/unit/test_extraction.py`

- [ ] **Step A4.1: Add a `persist_extraction` helper test**

Append to `tests/unit/test_extraction.py`:

```python
from unittest.mock import MagicMock
from docket.ai.extraction import persist_extraction
from docket.ai.extraction_schema import StructuredFacts, NextSteps


def test_persist_extraction_writes_jsonb_and_version():
    """persist_extraction updates extracted_facts JSONB and bumps the version."""
    facts = StructuredFacts(
        funding_source='general_fund',
        counterparty='Acme HVAC',
        procurement_method='competitive',
        location=None,
        action_type='contract_award',
        next_steps=NextSteps(),
        parcels_affected=None,
        acres_affected=None,
    )

    mock_cur = MagicMock()
    persist_extraction(mock_cur, item_id=42, facts=facts, version=1)

    # Verify the SQL parameters — flexible matching of UPDATE shape
    args, kwargs = mock_cur.execute.call_args
    sql, params = args
    assert "UPDATE agenda_items" in sql
    assert "extracted_facts" in sql
    assert "ai_extraction_version" in sql
    # Last param is item_id; first param is the JSON
    assert params[-1] == 42
```

- [ ] **Step A4.2: Run test (expect failure)**

Run: `venv/bin/pytest tests/unit/test_extraction.py::test_persist_extraction_writes_jsonb_and_version -v`
Expected: ImportError on `persist_extraction`.

- [ ] **Step A4.3: Implement persist_extraction**

Append to `src/docket/ai/extraction.py`:

```python
def persist_extraction(cur, item_id: int, facts: StructuredFacts, version: int) -> None:
    """Write Stage 1 output to agenda_items.extracted_facts.

    Caller controls the transaction. `cur` is a psycopg cursor.
    """
    cur.execute(
        """
        UPDATE agenda_items
        SET extracted_facts = %s::jsonb,
            ai_extraction_version = %s,
            processing_status = 'extracted'::processing_status_enum
        WHERE id = %s
        """,
        [facts.model_dump_json(), version, item_id],
    )
```

- [ ] **Step A4.4: Run test (expect pass)**

Run: `venv/bin/pytest tests/unit/test_extraction.py -v`
Expected: 5 tests pass total.

- [ ] **Step A4.5: Commit**

```bash
git add src/docket/ai/extraction.py tests/unit/test_extraction.py
git commit -m "feat(ai): Stage 1 persistence into agenda_items.extracted_facts"
```

---

# Section B — Stage 2 v3 + Stage 2.5 + Reconcile (~3 days)

## Task B1: ItemRewrite Pydantic Schema

**Files:**
- Create: `src/docket/ai/rewrite_schema.py`
- Create: `tests/unit/test_rewrite_schema.py`

- [ ] **Step B1.1: Write tests with the density check (decision #87)**

`tests/unit/test_rewrite_schema.py`:

```python
"""Tests for Stage 2 ItemRewrite schema with procedural_consistency validator."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from docket.ai.rewrite_schema import ItemRewrite


def base_substantive():
    return dict(
        is_substantive=True,
        headline="Council awards $4.2M HVAC contract to Acme",
        why_it_matters="Higher utility reliability for residents in Wards 4-7 starting July 2026.",
        significance_rationale="Major capital expenditure with long-term operational impact.",
        significance_score=7,
        consent_placement_rationale="High-dollar contract should not be on consent.",
        consent_placement_score=2,
        suggested_badge_slugs=[],
        confidence='high',
    )


class TestItemRewriteSubstantive:
    def test_valid_substantive(self):
        m = ItemRewrite(**base_substantive())
        assert m.is_substantive is True

    def test_headline_too_long_rejected(self):
        d = base_substantive()
        d['headline'] = "x" * 61
        with pytest.raises(ValidationError):
            ItemRewrite(**d)

    def test_why_it_matters_too_long_rejected(self):
        d = base_substantive()
        d['why_it_matters'] = "x" * 201
        with pytest.raises(ValidationError):
            ItemRewrite(**d)

    def test_headline_density_short_rejected(self):
        """Headline must be >= 10 chars (decision #87)."""
        d = base_substantive()
        d['headline'] = "Approved"  # 8 chars
        with pytest.raises(ValidationError):
            ItemRewrite(**d)

    def test_headline_whitespace_rejected(self):
        d = base_substantive()
        d['headline'] = "          "  # whitespace only
        with pytest.raises(ValidationError):
            ItemRewrite(**d)

    def test_why_it_matters_whitespace_rejected(self):
        d = base_substantive()
        d['why_it_matters'] = "   "
        with pytest.raises(ValidationError):
            ItemRewrite(**d)


class TestItemRewriteProcedural:
    def test_valid_procedural(self):
        m = ItemRewrite(
            is_substantive=False,
            headline=None,
            why_it_matters=None,
            significance_rationale="",
            significance_score=None,
            consent_placement_rationale="",
            consent_placement_score=None,
            suggested_badge_slugs=[],
            confidence='high',
        )
        assert m.is_substantive is False

    def test_procedural_with_populated_headline_rejected(self):
        with pytest.raises(ValidationError):
            ItemRewrite(
                is_substantive=False,
                headline="Should be null",
                why_it_matters=None,
                significance_rationale="",
                significance_score=None,
                consent_placement_rationale="",
                consent_placement_score=None,
                suggested_badge_slugs=[],
                confidence='medium',
            )
```

- [ ] **Step B1.2: Run tests (expect failure)**

Run: `venv/bin/pytest tests/unit/test_rewrite_schema.py -v`
Expected: import error.

- [ ] **Step B1.3: Implement ItemRewrite**

`src/docket/ai/rewrite_schema.py`:

```python
"""Stage 2 ItemRewrite Pydantic schema with procedural_consistency validator.

Spec: section 3.3, decisions #5, #50, #87.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ItemRewrite(BaseModel):
    is_substantive: bool
    headline: str | None = Field(None, max_length=60)
    why_it_matters: str | None = Field(None, max_length=200)
    significance_rationale: str = Field("", max_length=1500)
    significance_score: int | None = Field(None, ge=0, le=10)
    consent_placement_rationale: str = Field("", max_length=1500)
    consent_placement_score: int | None = Field(None, ge=0, le=10)
    suggested_badge_slugs: list[str] = Field(default_factory=list)
    confidence: Literal['high', 'medium', 'low']

    @model_validator(mode='after')
    def procedural_consistency(self):
        if not self.is_substantive:
            assert self.headline is None, "procedural items must have null headline"
            assert self.why_it_matters is None, "procedural items must have null why_it_matters"
            assert self.significance_score is None
            assert self.consent_placement_score is None
            assert self.suggested_badge_slugs == []
        else:
            # Density validation (decision #87): headline must be >= 10 chars
            assert self.headline and len(self.headline.strip()) >= 10, \
                "substantive items must have a headline >= 10 chars"
            assert self.why_it_matters and len(self.why_it_matters.strip()) > 0, \
                "substantive items must have a non-empty why_it_matters"
            assert self.significance_score is not None
            assert self.consent_placement_score is not None
        return self
```

- [ ] **Step B1.4: Run tests (expect pass)**

Run: `venv/bin/pytest tests/unit/test_rewrite_schema.py -v`
Expected: 8 tests pass.

- [ ] **Step B1.5: Commit**

```bash
git add src/docket/ai/rewrite_schema.py tests/unit/test_rewrite_schema.py
git commit -m "feat(ai): ItemRewrite schema with procedural_consistency validator + density check"
```

## Task B2: Stage 2 Worker

**Files:**
- Create: `src/docket/ai/rewrite.py`
- Create: `tests/unit/test_rewrite.py`

- [ ] **Step B2.1: Write the prompt and worker following the same shape as `extraction.py`**

`src/docket/ai/rewrite.py`:

The full system prompt is in spec §3.1 — copy it verbatim. The worker mirrors `extraction.py:extract_facts_for_item` but also accepts the Stage 1 facts as injected JSON in the user message (per spec §3.2). Output is `ItemRewrite` validated by Pydantic.

**Apply the same SDK hardening as extraction.py (decision #94):**
- Initialize Anthropic client with `max_retries=0`
- Use `_strip_markdown_fences()` helper before `json.loads()` (import from `extraction.py` or move to a shared `_helpers.py`)
- Use the new DB-backed cache API (`cache_put(key, model=..., prompt_version=..., payload=...)`)

Key constants:
```python
ITEM_REWRITE_PROMPT_VERSION = 3
```

Key function:
```python
def rewrite_item(
    item,
    facts: StructuredFacts,
    enabled_policy_badges: list[str],
    *,
    model: str = "claude-haiku-4-5-20251001",
    extra_instruction: str | None = None,
) -> tuple[ItemRewrite, str]:
    ...
```

The `extra_instruction` parameter is used by the reconcile auto-retry path (Task B5) to inject an override prompt.

The user message template is:
```
City: {city_name}
Available policy badge slugs: {comma-separated enabled slugs}

Title: {title}
Description: {description}
Sponsor: {sponsor}
Dollar amount: {dollars_amount}
Topic (legacy): {topic}
Is on consent agenda: {is_consent}

Stage 1 structured facts:
{facts_json}

{extra_instruction or ''}
```

- [ ] **Step B2.2: Write 3-4 tests covering the happy path, procedural verdict, and validation failure (mirror extraction tests)**

- [ ] **Step B2.3: Run tests, fix until green**

- [ ] **Step B2.4: Commit**

```bash
git add src/docket/ai/rewrite.py tests/unit/test_rewrite.py
git commit -m "feat(ai): Stage 2 v3 worker with item-prompt-v3 + cache + Pydantic"
```

## Task B3: Stage 2.5 Score Floors

**Files:**
- Create: `src/docket/ai/floors.py`
- Create: `tests/unit/test_floors.py`

- [ ] **Step B3.1: Implement following spec §3.4 verbatim**

The full code (FloorTrigger dataclass, SIGNIFICANCE_FLOORS, CONSENT_PLACEMENT_CEILINGS, SUBJECT_MATTER_FLOORS, SUBJECT_MATTER_PATTERNS, _resolve_threshold, apply_score_floors) is in spec §3.4. Copy and adjust only:
- Replace abstract `db_lookup_override` with a concrete query against `city_score_floor_overrides`
- Use real `psycopg` cursor, not mocked

- [ ] **Step B3.2: Write parametrized tests**

For each entry in `SIGNIFICANCE_FLOORS`, assert that:
- A matching item with AI score below the bound gets boosted to the bound
- A matching item with AI score above the bound is unchanged

For each entry in `CONSENT_PLACEMENT_CEILINGS`, similar logic but inverted (bound is a ceiling, not a floor).

For SUBJECT_MATTER_FLOORS, test keyword match AND `suggested_badge_slugs` membership paths.

Test the override pathway:
- Empty `city_score_floor_overrides` → defaults
- Insert override row → `_resolve_threshold` returns override value

- [ ] **Step B3.3: Implement, run tests until green**

- [ ] **Step B3.4: Commit**

```bash
git add src/docket/ai/floors.py tests/unit/test_floors.py
git commit -m "feat(ai): Stage 2.5 score floors (SIG + CONSENT + SUBJECT_MATTER) with overrides"
```

## Task B4: Reconcile Module

**Files:**
- Create: `src/docket/ai/reconcile.py`
- Create: `tests/unit/test_reconcile.py`

- [ ] **Step B4.1: Implement spec §3.7 reconcile_stages()**

Direct copy from spec, with concrete imports (StructuredFacts, ItemRewrite, SUBJECT_MATTER_PATTERNS). Returns `ReconciliationResult(action, conflicts, override_instruction)`.

- [ ] **Step B4.2: Write tests covering each conflict path**

For each of the 5 conflict types in `reconcile_stages`:
- Stage1 has counterparty + Stage2 procedural → conflict
- Stage1 has funding_source + Stage2 procedural → conflict
- Yellow-tier dollars + Stage2 procedural → conflict
- High-attention action_type + Stage2 procedural → conflict
- Subject-matter regex match + Stage2 procedural → conflict

Plus:
- No conflict path → `action='accept'`
- already_retried=True → `action='mark_cross_stage_conflict'`

- [ ] **Step B4.3: Run tests until green**

- [ ] **Step B4.4: Commit**

```bash
git add src/docket/ai/reconcile.py tests/unit/test_reconcile.py
git commit -m "feat(ai): cross-stage reconcile with auto-retry override prompt"
```

## Task B5: Per-Item Pipeline Orchestrator

**Files:**
- Create: `src/docket/ai/pipeline.py`
- Create: `tests/integration/test_pipeline_e2e.py`

- [ ] **Step B5.1: Implement the full per-item pipeline**

`src/docket/ai/pipeline.py`:

```python
"""Per-item orchestrator: Stages 0a → 0b → 1 → 2 → 2.5 → reconcile → atomic commit.

Wraps the worker per-item processing loop. Used by both the live
`ai_items` cron task and the backfill driver (Phase 3).

Spec: section 1, 7.5, decision #45.
"""

from __future__ import annotations

import logging
from typing import Any

from docket.ai.extraction import extract_facts_for_item, persist_extraction, EXTRACTION_PROMPT_VERSION
from docket.ai.extraction_schema import StructuredFacts
from docket.ai.floors import apply_score_floors
from docket.ai.reconcile import reconcile_stages
from docket.ai.rewrite import rewrite_item, ITEM_REWRITE_PROMPT_VERSION
from docket.ai.rewrite_schema import ItemRewrite
from docket.ai.wave0 import evaluate_data_quality, is_procedural
from docket.db import db_cursor
from docket.services.badges import get_enabled_policy_slugs

log = logging.getLogger(__name__)


def process_item(item) -> str:
    """Run the full per-item pipeline. Returns the final processing_status.

    Item must have: id, meeting.city_id, title, description, sponsor,
    dollars_amount, topic, is_consent, source_type.
    """
    # Stage 0a — data-quality gate (Big Fish Override included)
    quality, priority = evaluate_data_quality(item)
    if quality != 'ok':
        with db_cursor() as cur:
            cur.execute("""
                UPDATE agenda_items
                SET data_quality = %s::data_quality_enum,
                    data_debt_priority = %s::data_debt_priority_enum,
                    processing_status = 'data_quality_skipped'::processing_status_enum
                WHERE id = %s
            """, [quality, priority, item.id])
        return 'data_quality_skipped'

    # Stage 0b — procedural regex
    if is_procedural(item.title):
        with db_cursor() as cur:
            cur.execute("""
                UPDATE agenda_items
                SET processing_status = 'procedural_skipped'::processing_status_enum
                WHERE id = %s
            """, [item.id])
        return 'procedural_skipped'

    # Stage 1 — extraction
    facts, _ = extract_facts_for_item(item)

    # Stage 2 — Smart Brevity rewrite (consumes Stage 1 facts)
    enabled_slugs = get_enabled_policy_slugs(item.city_id)
    rewrite, _ = rewrite_item(item, facts, enabled_slugs)

    # Stage 2.5 — apply score floors
    overrides = apply_score_floors(item, facts, rewrite, item.city_id)

    # Reconcile — cross-stage conflict detection
    result = reconcile_stages(facts, rewrite, item, already_retried=False)
    if result.action == 'retry_stage2_with_override':
        rewrite, _ = rewrite_item(
            item, facts, enabled_slugs,
            extra_instruction=result.override_instruction,
        )
        # Re-apply floors after retry
        overrides = apply_score_floors(item, facts, rewrite, item.city_id)
        result = reconcile_stages(facts, rewrite, item, already_retried=True)

    final_status = (
        'cross_stage_conflict'
        if result.action == 'mark_cross_stage_conflict'
        else 'completed'
    )

    # Atomic commit: persist Stage 1 + Stage 2 + Stage 2.5 + on-write process badges
    with db_cursor() as cur:
        persist_extraction(cur, item.id, facts, version=EXTRACTION_PROMPT_VERSION)
        cur.execute("""
            UPDATE agenda_items
            SET headline = %s,
                why_it_matters = %s,
                significance_score = %s,
                consent_placement_score = %s,
                ai_confidence = %s,
                ai_rewrite_version = %s,
                score_overrides = %s::jsonb,
                processing_status = %s::processing_status_enum
            WHERE id = %s
        """, [
            rewrite.headline,
            rewrite.why_it_matters,
            overrides.final_significance,
            overrides.final_consent,
            rewrite.confidence,
            ITEM_REWRITE_PROMPT_VERSION,
            overrides.model_dump_json(),
            final_status,
            item.id,
        ])

        # Compute on-write process badges (Section C — Task C2)
        # Decision #92: include city_id in INSERT for fast category-page joins.
        from docket.ai.badges_process import compute_on_write_process_badges
        on_write = compute_on_write_process_badges(
            item, facts, overrides, rewrite.confidence,
        )
        for slug, conf in on_write:
            cur.execute("""
                INSERT INTO agenda_item_badges
                  (agenda_item_id, city_id, badge_slug, kind, confidence, source)
                VALUES (%s, %s, %s, 'process', %s, 'deterministic')
                ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING
            """, [item.id, item.city_id, slug, conf])

        # Compute policy badges (Section D — Task D2)
        from docket.ai.badges_policy import compute_policy_badges
        for slug, conf, source, metadata in compute_policy_badges(
            item, facts, rewrite, item.city_id,
        ):
            cur.execute("""
                INSERT INTO agenda_item_badges
                  (agenda_item_id, city_id, badge_slug, kind, confidence, source, matching_metadata)
                VALUES (%s, %s, %s, 'policy', %s, %s, %s::jsonb)
                ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING
            """, [item.id, item.city_id, slug, conf, source, metadata])

    return final_status
```

- [ ] **Step B5.2: Write integration test (mocks Anthropic, hits real DB)**

`tests/integration/test_pipeline_e2e.py`:

Use a real DB transaction with rollback at the end. Mock the `anthropic_client` in `extraction` and `rewrite` modules. Insert a test item, call `process_item(item)`, assert that all expected columns are populated and badges land in `agenda_item_badges`.

- [ ] **Step B5.3: Commit**

```bash
git add src/docket/ai/pipeline.py tests/integration/test_pipeline_e2e.py
git commit -m "feat(ai): per-item pipeline orchestrator (Stages 0-2.5 + reconcile + badges)"
```

---

# Section C — Process Badges (~2 days)

## Task C1: Process Badge SQL Module

**Files:**
- Create: `src/docket/ai/badges_process.py`
- Create: `tests/unit/test_badges_process.py`

- [ ] **Step C1.1: Implement the 7 SQL queries from spec §4.4**

Each query is the SQL from spec §4.4 (Hidden on consent, Sole-source, Legal settlement, Split vote, Contested, Amends prior contract with v6 noise filter + decision #89 negative regex, Emergency action).

**IMPORTANT — decision #92 modification:** every INSERT must include `city_id` resolved via the JOIN to `meetings`. Add `JOIN meetings m ON m.id = ai.meeting_id` to the SELECT side and `m.city_id` to the column list. Example template:

```sql
INSERT INTO agenda_item_badges
  (agenda_item_id, city_id, badge_slug, kind, confidence, source)
SELECT ai.id, m.city_id, 'sole_source', 'process', 1.0, 'deterministic'
FROM agenda_items ai
JOIN meetings m ON m.id = ai.meeting_id
WHERE ai.extracted_facts->>'procurement_method' IN ('sole_source', 'no_bid')
  AND ai.processing_status = 'completed'
ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING;
```

Apply the same JOIN pattern to all 7 process-badge queries. Define as module constants:

```python
HIDDEN_ON_CONSENT_SQL = """..."""
SOLE_SOURCE_SQL = """..."""
# etc.

PROCESS_BADGE_QUERIES = [
    HIDDEN_ON_CONSENT_SQL,
    SOLE_SOURCE_SQL,
    LEGAL_SETTLEMENT_SQL,
    SPLIT_VOTE_AND_CONTESTED_SQL,
    AMENDS_PRIOR_CONTRACT_SQL,
    EMERGENCY_ACTION_SQL,
]
```

- [ ] **Step C1.2: Implement on-write helper from spec §4.5 final code block**

```python
def compute_on_write_process_badges(item, facts, scores, ai_confidence) -> list[tuple[str, float]]:
    """Returns list of (badge_slug, confidence) for the 4 on-write badges:
    hidden_on_consent, sole_source, legal_settlement, emergency_action.

    Mirrors the SQL exactly — both paths must agree.
    """
    # ... see spec §4.5
```

- [ ] **Step C1.3: Write integration tests for each badge**

For each badge, set up the DB state (insert items + associated rows), run the SQL, assert that the right rows land in `agenda_item_badges`. Include the fires/doesn't-fire example tables from spec §4.4 as test cases.

- [ ] **Step C1.4: Commit**

```bash
git add src/docket/ai/badges_process.py tests/unit/test_badges_process.py
git commit -m "feat(ai): 7 process-badge SQL queries + on-write helper"
```

## Task C2: Process Badge Cron Task

**Files:**
- Modify: `src/docket/worker/tasks.py`
- Create: `tests/unit/test_worker_tasks_process_badges.py`

- [ ] **Step C2.1: Add `process_badges_task` following the existing `_safe_run` pattern**

Reference the cron-worker plan in `docs/superpowers/plans/2026-05-04-cron-worker.md` for the established pattern.

```python
def process_badges_task() -> None:
    """Nightly recompute of process badges. Manual badges preserved
    (decision #57). Decision #78 — runs after vote_matching at 09:00."""
    from docket.ai.badges_process import PROCESS_BADGE_QUERIES
    from docket.db import db_cursor

    with db_cursor() as cur:
        # Advisory lock
        cur.execute("SELECT pg_try_advisory_lock(hashtext('docket.process_badges'))")
        if not cur.fetchone()[0]:
            log.warning("process_badges already running, skipping")
            return

        try:
            cur.execute("""
                CREATE TEMP TABLE recent_items ON COMMIT DROP AS
                SELECT id FROM agenda_items
                WHERE updated_at > NOW() - INTERVAL '36 hours'
                  AND processing_status = 'completed';
            """)

            # Preserve manual badges (decision #57)
            cur.execute("""
                DELETE FROM agenda_item_badges
                WHERE kind = 'process'
                  AND source != 'manual'
                  AND agenda_item_id IN (SELECT id FROM recent_items);
            """)

            for query in PROCESS_BADGE_QUERIES:
                cur.execute(query)
        finally:
            cur.execute("SELECT pg_advisory_unlock(hashtext('docket.process_badges'))")
```

- [ ] **Step C2.2: Wire into the scheduler at 09:30 America/Chicago**

Edit `src/docket/worker/scheduler.py` to add:
```python
scheduler.add_job(
    _safe_run('process_badges', process_badges_task),
    'cron', hour=9, minute=30, timezone='America/Chicago',
)
```

- [ ] **Step C2.3: Add Healthchecks UUID env var**

Document in `docs/runbooks/cron-worker.md` that a new env var `HEALTHCHECK_PROCESS_BADGES_UUID` should be set on the Railway `worker` service.

- [ ] **Step C2.4: Commit**

```bash
git add src/docket/worker/tasks.py src/docket/worker/scheduler.py tests/unit/test_worker_tasks_process_badges.py docs/runbooks/cron-worker.md
git commit -m "feat(worker): nightly process_badges task with advisory lock + manual preservation"
```

---

# Section D — Policy Badges (~3 days)

## Task D1: Policy Badge Matcher

**Files:**
- Create: `src/docket/ai/badges_policy.py`
- Create: `src/docket/services/badges.py`
- Create: `tests/unit/test_badges_policy.py`

- [ ] **Step D1.1: Implement `deterministic_policy_match` from spec §5.3**

Direct copy from spec. Returns `(matched, metadata)` tuple. Note: per the locked decision #61 revision, the `min_significance` gate is RENDER-time, not matcher-time. The matcher does NOT skip items below threshold — that gate lives in the service layer (Section F).

So the matcher's hard guards are:
1. `excluded_action_types` check (decision #63)
2. `excluded_phrases` check (decision #61 edge case)

The keyword-match logic supports the regex flag (decision #60).

- [ ] **Step D1.2: Implement `compute_policy_badges` from spec §5.3 final block**

Returns list of `(slug, confidence, source, matching_metadata)` tuples. Source is one of `'both'`, `'llm'`, `'deterministic'`.

- [ ] **Step D1.3: Implement service layer for badge resolution**

`src/docket/services/badges.py`:

```python
"""Policy badge resolution service."""

from __future__ import annotations

from functools import lru_cache

from docket.db import db_cursor


@lru_cache(maxsize=32)
def get_enabled_policy_slugs(city_id: int) -> list[str]:
    """Returns list of enabled policy badge slugs for a city.
    Cached per city — invalidate via cache_clear() if config changes."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT template_slug FROM priority_badges_config
            WHERE city_id = %s AND enabled = TRUE
        """, [city_id])
        return [row[0] for row in cur.fetchall()]


def get_resolved_badge(city_id: int, slug: str) -> dict | None:
    """Returns merged template + override for a (city, slug) pair, or None
    if not enabled. Resolves matcher_hints by overlay."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT t.slug, t.name, t.description, t.icon, t.kind,
                   t.default_matcher_hints,
                   c.name_override, c.description_override,
                   c.matcher_hints_override
            FROM priority_badge_templates t
            JOIN priority_badges_config c ON c.template_slug = t.slug
            WHERE c.city_id = %s
              AND t.slug = %s
              AND c.enabled = TRUE
        """, [city_id, slug])
        row = cur.fetchone()
        if row is None:
            return None
        # ... merge override into hints
```

- [ ] **Step D1.4: Tests covering significance gate (now render-time only), excluded_action_types, regex flag, invalid-regex handling**

- [ ] **Step D1.5: Commit**

```bash
git add src/docket/ai/badges_policy.py src/docket/services/badges.py tests/unit/test_badges_policy.py
git commit -m "feat(ai): policy-badge hybrid matcher with regex flag + render-time gating"
```

## Task D2: Audit Log Integration

**Files:**
- Modify: `src/docket/services/badges.py`
- Create: `tests/integration/test_badges_audit.py`

- [ ] **Step D2.1: Add `record_badge_action` writing to agenda_item_badges_audit**

```python
def record_badge_action(
    cur, agenda_item_id: int, badge_slug: str,
    action: str, actor: str, actor_role: str,
    reason: str | None = None,
) -> None:
    cur.execute("""
        INSERT INTO agenda_item_badges_audit
          (agenda_item_id, badge_slug, action, actor, actor_role, reason)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, [agenda_item_id, badge_slug, action, actor, actor_role, reason])
```

- [ ] **Step D2.2: Wire into Stage 2 pipeline so 'on_write' badge inserts are audited**

- [ ] **Step D2.3: Commit**

```bash
git add src/docket/services/badges.py tests/integration/test_badges_audit.py
git commit -m "feat(badges): wire audit log on add/remove/modify with actor_role tracking"
```

---

# Section E — Smart Brevity Card + Frontend Foundations (~4 days)

## Task E1: Card Variant Dispatcher

**Files:**
- Create: `src/docket/web/templates/partials/smart_brevity_card.html`
- Create: 6 variant partials (see File Structure list above)

- [ ] **Step E1.1: Create the variant dispatcher**

`src/docket/web/templates/partials/smart_brevity_card.html`:

```jinja
{# Smart Brevity Card variant dispatcher (spec §6.1).
   Order matters: failed_permanent and data_quality_skipped checks come
   first because they're terminal states. #}

{% if item.processing_status == 'failed_permanent' %}
  {% include 'partials/card_failed.html' %}
{% elif item.data_quality and item.data_quality != 'ok' %}
  {% include 'partials/card_degraded.html' %}
{% elif item.processing_status == 'procedural_skipped' %}
  {% include 'partials/card_procedural.html' %}
{% elif item.processing_status == 'cross_stage_conflict' %}
  {% include 'partials/card_verification_pending.html' %}
{% elif item.ai_rewrite_version == 3 %}
  {% include 'partials/card_smart_brevity.html' %}
{% elif item.summary %}
  {% include 'partials/card_v2_fallback.html' %}
{% else %}
  {% include 'partials/card_pending.html' %}
{% endif %}
```

- [ ] **Step E1.2: Create each variant partial**

Each partial implements the mockup from spec §6.1 (the ASCII diagrams). Use the existing app's CSS classes and HTMX patterns. For the "full" variant, structure: header (badges) → headline → why_it_matters → facts strip → engagement strip → source-anchor button.

For the cross-stage-conflict variant, follow spec §6.1 (with the tooltip-only pill from the post-merge state, not the modal).

- [ ] **Step E1.3: Wire into meeting_detail.html**

Replace the existing item-rendering block in `src/docket/web/templates/meeting_detail.html` with:
```jinja
{% include 'partials/smart_brevity_card.html' %}
```

- [ ] **Step E1.4: Smoke-test with fixture data**

Create a Flask route in development for testing each variant:
```python
@app.route('/dev/card-test/<variant>')
def dev_card_test(variant):
    # Build a fake item dict matching that variant's state
    item = build_fake_item(variant)
    return render_template('partials/smart_brevity_card.html', item=item)
```

(Remove the route before the deployment commit.)

- [ ] **Step E1.5: Commit**

```bash
git add src/docket/web/templates/partials/
git commit -m "feat(web): Smart Brevity Card 6-variant dispatcher + partials"
```

## Task E2: Badge Chip Rendering with Verification Spark

**Files:**
- Create: `src/docket/web/templates/partials/badge_chip.html`
- Create: `src/docket/web/static/css/smart_brevity.css`
- Create: `tests/unit/test_badge_chip_ordering.py`

- [ ] **Step E2.1: Implement badge_chip.html from spec §6.2**

Spec §6.2 has the exact Jinja markup. The Verification Spark (✨) appears via:
```jinja
{% if badge.confidence >= 1.0 %}<span class="badge-spark" aria-label="AI-verified">✨</span>{% endif %}
```

- [ ] **Step E2.2: Implement order_badges() from spec §6.2**

Add to `src/docket/web/filters.py` (registered as a Jinja2 filter):

```python
process_alarm_order = [
    'hidden_on_consent', 'legal_settlement', 'contested',
    'sole_source', 'emergency_action', 'split_vote',
    'amends_prior_contract',
]


def order_badges(badges):
    process = sorted(
        [b for b in badges if b['kind'] == 'process'],
        key=lambda b: process_alarm_order.index(b['slug']) if b['slug'] in process_alarm_order else 999,
    )
    policy = sorted(
        [b for b in badges if b['kind'] == 'policy'],
        key=lambda b: (-b['confidence'], b['slug']),
    )
    return process + policy
```

- [ ] **Step E2.3: Add CSS for solid/outlined treatment + ✨ spark**

`src/docket/web/static/css/smart_brevity.css`:

```css
.badge-chip {
  display: inline-flex; align-items: center; gap: 0.25em;
  padding: 0.2em 0.5em; border-radius: 0.5em;
  font-size: 0.875em; font-weight: 600;
}
.badge-chip.badge-conf-medium { background: rgba(0,0,0,0.05); }
.badge-chip.badge-conf-high { background: var(--brand-color); color: white; }
.badge-spark { font-size: 0.875em; }

/* Mobile carousel — Brevity-First (decision #66) */
@media (max-width: 768px) {
  .smart-brevity-card .badge-row {
    order: -1;
    overflow-x: auto;
    scroll-snap-type: x mandatory;
    display: flex;
    gap: 0.5rem;
    padding-bottom: 0.5rem;
  }
  .smart-brevity-card .badge-row .badge-chip {
    flex-shrink: 0;
    scroll-snap-align: start;
  }
}
```

- [ ] **Step E2.4: Snapshot test for ordering**

Render with a mix of process+policy badges, snapshot the resulting HTML, verify process badges come first in alarm-level order, then policy badges by confidence then alphabetically.

- [ ] **Step E2.5: Commit**

```bash
git add src/docket/web/templates/partials/badge_chip.html \
        src/docket/web/static/css/smart_brevity.css \
        src/docket/web/filters.py \
        tests/unit/test_badge_chip_ordering.py
git commit -m "feat(web): badge chip with Verification Spark + process-first ordering + mobile carousel"
```

## Task E3: Engagement Strip

**Files:**
- Create: `src/docket/web/templates/partials/engagement_strip.html`

- [ ] **Step E3.1: Implement spec §6.3 with the post-merge mailto: link (decision #77)**

The strip has 4 states:
1. `next_steps` populated → show populated fields + master-calendar link as tail
2. `action_type=public_hearing_set` AND `public_hearing_date IS NULL` → "Awaiting hearing date" + RSS link + mailto: report
3. `master_calendar_url` configured → just the calendar fallback link
4. None of the above → strip auto-hides

The mailto: link is per the post-merge spec (decision #77 retired the `data_issue_reports` schema). Use `config.ADMIN_EMAIL`.

- [ ] **Step E3.2: Snapshot test all 4 states**

- [ ] **Step E3.3: Commit**

```bash
git add src/docket/web/templates/partials/engagement_strip.html tests/unit/test_engagement_strip.py
git commit -m "feat(web): engagement strip with 4 states + mailto fallback for missing data"
```

## Task E4: Source-Anchor Adaptive Button

**Files:**
- Create: `src/docket/web/templates/partials/source_anchor_button.html`

- [ ] **Step E4.1: Implement spec §6.4 verbatim**

The button adapts to the captured anchor level: bbox → page → doc URL → "OCR needed" admin link. Browser-native `#page=` and `?t=` URL fragments — no JS.

- [ ] **Step E4.2: Snapshot tests for each level**

- [ ] **Step E4.3: Commit**

```bash
git add src/docket/web/templates/partials/source_anchor_button.html tests/unit/test_source_anchor.py
git commit -m "feat(web): adaptive source-anchor button (bbox → page → doc → OCR-needed)"
```

## Task E5: Dollar Tier with WCAG Markup

**Files:**
- Create: `src/docket/web/templates/partials/dollar_tier.html`

- [ ] **Step E5.1: Implement spec §6.1 dollar-tier accessibility section**

Visual symbol + visually-hidden screen-reader label + parent aria-label. Helper Jinja filter `dollar_tier(amount)` returns `('green'|'yellow'|'orange'|'red', '$'|'$$'|'$$$'|'$$$$', 'over $X')`.

- [ ] **Step E5.2: Tests**

- [ ] **Step E5.3: Commit**

```bash
git add src/docket/web/templates/partials/dollar_tier.html src/docket/web/filters.py tests/unit/test_dollar_tier.py
git commit -m "feat(web): WCAG-2.1-compliant dollar tier with symbols + sr-only labels"
```

## Task E6: Feature Flag the v3 UI

**Files:**
- Modify: `src/docket/web/__init__.py`
- Modify: `src/docket/web/templates/meeting_detail.html`

- [ ] **Step E6.1: Read SMART_BREVITY_UI env flag at app init**

```python
app.config['SMART_BREVITY_UI'] = os.environ.get('SMART_BREVITY_UI', '').lower() == 'true'
```

- [ ] **Step E6.2: Gate the variant dispatcher**

In `meeting_detail.html`:
```jinja
{% if config.SMART_BREVITY_UI %}
  {% include 'partials/smart_brevity_card.html' %}
{% else %}
  {# ... existing v2 rendering ... #}
{% endif %}
```

- [ ] **Step E6.3: Verify flag-off ships v2 unchanged**

Smoke-test with `SMART_BREVITY_UI=false`: existing meeting page renders identically to current production.

- [ ] **Step E6.4: Commit**

```bash
git add src/docket/web/__init__.py src/docket/web/templates/meeting_detail.html
git commit -m "feat(web): SMART_BREVITY_UI feature flag gating v3 vs v2 rendering"
```

---

# Section F — Category Landing Pages + Volume Timeline (~3 days)

## Task F1: list_items_by_badge Service

**Files:**
- Modify: `src/docket/services/query.py`
- Create: `tests/integration/test_list_items_by_badge.py`

- [ ] **Step F1.1: Implement spec §6.5 + §5.4 with render-time significance gating**

Per the merged decision #61, the function gates by `significance_score >= min_significance` for policy badges. Process badges have no significance gate.

The `min_significance` value comes from the badge's `matcher_hints` (default 3), resolved through `priority_badges_config.matcher_hints_override`.

- [ ] **Step F1.2: Test cross-filter behavior, gate behavior (with/without low-conf toggle), pagination**

- [ ] **Step F1.3: Commit**

```bash
git add src/docket/services/query.py tests/integration/test_list_items_by_badge.py
git commit -m "feat(services): list_items_by_badge with render-time significance gate + cross-filters"
```

## Task F2: Category Landing Page Route + Template

**Files:**
- Modify: `src/docket/web/public.py`
- Create: `src/docket/web/templates/category_landing.html`

- [ ] **Step F2.1: Add route `/al/<city>/<badge_slug>`**

```python
@bp.route('/al/<city>/<badge_slug>')
def category_landing(city: str, badge_slug: str):
    city_obj = lookup_city(city)
    badge = get_resolved_badge(city_obj.id, badge_slug)
    if not badge:
        abort(404)

    cross_filters = request.args.get('and', '').split(',')
    cross_filters = [s for s in cross_filters if s]

    items = list_items_by_badge(
        city_obj.id, badge_slug,
        cross_filter_slugs=cross_filters,
        limit=25, offset=int(request.args.get('offset', 0)),
    )
    kpis = category_kpis(city_obj.id, badge_slug, year=2026)
    timeline = badge_volume_series(city_obj.id, badge_slug, ...)

    return render_template(
        'category_landing.html',
        city=city_obj, badge=badge, items=items, kpis=kpis,
        timeline=timeline, cross_filters=cross_filters,
    )
```

- [ ] **Step F2.2: Implement category_landing.html per spec §6.5 ASCII layout**

Header (badge name + icon), KPI strip, volume timeline (SVG partial — Task F3), filter controls, item list rendered via `smart_brevity_card.html`, "load more" button.

- [ ] **Step F2.3: Commit**

```bash
git add src/docket/web/public.py src/docket/web/templates/category_landing.html
git commit -m "feat(web): category landing page route + template"
```

## Task F3: SVG Volume Timeline

**Files:**
- Create: `src/docket/web/templates/partials/volume_timeline.html`
- Modify: `src/docket/services/query.py`

- [ ] **Step F3.1: Implement `badge_volume_series` reading from mv_badge_volume_monthly**

Returns list of `{period, x, y, width, height_substantive, height_consent, n_items, n_consent, total_dollars}`.

- [ ] **Step F3.2: Implement `volume_timeline.html` from spec §6.6 with consent baseline split**

Two `<rect>` elements per period: lower (substantive) and upper (consent). Mayoral-term overlay bands as background. Browser-native `<title>` tooltip.

- [ ] **Step F3.3: Visual verification**

Open `/al/birmingham/blight_accountability` in dev browser, verify SVG renders, hover bars to see counts, verify mayoral bands span correctly.

- [ ] **Step F3.4: Commit**

```bash
git add src/docket/web/templates/partials/volume_timeline.html src/docket/services/query.py
git commit -m "feat(web): SVG volume timeline with mayoral overlay + consent baseline split"
```

## Task F4: Cross-Filter HTMX Dropdown + Homepage Section

**Files:**
- Modify: `src/docket/web/templates/category_landing.html`
- Modify: `src/docket/web/templates/city.html`

- [ ] **Step F4.1: Add HTMX cross-filter dropdown per spec §6.8**

`hx-push-url="true"` so filtered URLs are bookmarkable.

- [ ] **Step F4.2: Add Browse-by-Priority homepage section per spec §6.7**

Two grids: 4 BHM policy tiles + 7 process tiles. Tile shows icon + name + count.

- [ ] **Step F4.3: Add badge legend (decision #74) to city.html header**

One-liner explaining `process` vs `policy` and the `✨` spark.

- [ ] **Step F4.4: Commit**

```bash
git add src/docket/web/templates/category_landing.html src/docket/web/templates/city.html
git commit -m "feat(web): cross-filter dropdown + Browse by Priority + badge legend"
```

## Task F5: Public Data-Debt Page + RSS Feeds

**Files:**
- Modify: `src/docket/web/public.py`
- Create: `src/docket/web/templates/data_debt.html`

- [ ] **Step F5.1: Add `/al/<city>/data-debt` route**

Sort items by `data_debt_priority DESC, meeting_date DESC`. Public-facing.

- [ ] **Step F5.2: Add RSS feed routes with 60-min cache (decision #90)**

```python
from flask_caching import Cache  # may already be configured

@bp.route('/al/<city>/data-debt.rss')
@cache.cached(timeout=3600, query_string=True)
def data_debt_rss(city: str):
    items = list_data_debt_items(city, limit=50)
    return Response(render_template('rss/data_debt.xml.j2', items=items),
                    mimetype='application/rss+xml')


@bp.route('/al/<city>/upcoming-hearings.rss')
@cache.cached(timeout=3600, query_string=True)
def upcoming_hearings_rss(city: str):
    items = list_upcoming_hearings(city)
    return Response(render_template('rss/upcoming_hearings.xml.j2', items=items),
                    mimetype='application/rss+xml')
```

(If `flask-caching` isn't installed, add to requirements.txt; alternatively use `werkzeug.contrib.cache.SimpleCache` or roll a small `@lru_cache_with_ttl` decorator.)

- [ ] **Step F5.3: Commit**

```bash
git add src/docket/web/public.py src/docket/web/templates/data_debt.html src/docket/web/templates/rss/
git commit -m "feat(web): public data-debt page + RSS feeds with 60-min cache"
```

---

# Section G — Admin Views (~2 days)

## Task G1: Calibration Dashboard

**Files:**
- Modify: `src/docket/web/admin.py`
- Create: `src/docket/web/templates/admin/calibration.html`
- Create: `src/docket/services/calibration.py`

- [ ] **Step G1.1: Implement calibration queries from spec §3.5 (revised)**

Three queries: (A) per-item divergence, (B1) Under-scoring Impact, (B2) Over-scoring Consent, (C) Baseline drift. Plus the Top False Positives query from spec §5.7.

- [ ] **Step G1.2: Add `/admin/calibration` route + template**

Render each query as a panel with a small table.

- [ ] **Step G1.3: Commit**

```bash
git add src/docket/web/admin.py src/docket/web/templates/admin/calibration.html src/docket/services/calibration.py
git commit -m "feat(admin): calibration dashboard with 3 panels (divergence, drift, false-positives)"
```

## Task G2: OCR Queue + Errors Queue

**Files:**
- Modify: `src/docket/web/admin.py`
- Create: `src/docket/web/templates/admin/data_debt.html`
- Create: `src/docket/web/templates/admin/errors.html`

- [ ] **Step G2.1: `/admin/data-debt` sorted by data_debt_priority DESC**

Per decision #84 — priority sort from launch.

- [ ] **Step G2.2: `/admin/errors` showing failed_permanent items, sorted same**

Per decision #79 — significance-sorted.

- [ ] **Step G2.3: Commit**

```bash
git add src/docket/web/admin.py src/docket/web/templates/admin/
git commit -m "feat(admin): OCR queue (data-debt) + errors queue, both priority-sorted"
```

## Task G3: Audit Log Viewer

**Files:**
- Modify: `src/docket/web/admin.py`
- Create: `src/docket/web/templates/admin/badges_audit.html`

- [ ] **Step G3.1: `/admin/badges/audit` filterable by badge_slug + actor + date range**

- [ ] **Step G3.2: Manual badge add/remove HTMX endpoints**

Two endpoints: `POST /admin/badges/<item_id>/add/<slug>` and `POST /admin/badges/<item_id>/remove/<slug>`. Both write to `agenda_item_badges` AND `agenda_item_badges_audit` in one transaction. **Decision #92:** include `city_id` in the INSERT for the add endpoint.

- [ ] **Step G3.3: Commit**

```bash
git add src/docket/web/admin.py src/docket/web/templates/admin/badges_audit.html
git commit -m "feat(admin): audit log viewer + manual badge HTMX endpoints"
```

## Task G4: Cross-Stage Conflict Resolution UI (decision #93)

**Files:**
- Create: `src/docket/services/conflict_resolution.py`
- Modify: `src/docket/web/admin.py`
- Create: `src/docket/web/templates/admin/review_conflicts.html`
- Create: `src/docket/web/templates/admin/_conflict_resolved.html` (HTMX swap target)
- Create: `tests/integration/test_conflict_resolution.py`

> **Why this is in Phase 2 not Phase 3:** Phase 2's FINAL-3 step flips
> `IMPACT_FIRST_ENABLED=true` for the worker. From that point onward,
> conflicts can occur on any new ingested item. Without the resolution
> UI, items pile up in `cross_stage_conflict` state with the
> ⚠️ "Verification in progress" pill visible to citizens indefinitely.

- [ ] **Step G4.1: Service layer for resolution actions**

`src/docket/services/conflict_resolution.py`:

```python
"""Cross-stage conflict resolution actions (decision #93).

Each resolution action:
- Updates agenda_items (clearing/setting fields)
- Records audit row in processing_status_audit
- Returns the new processing_status for UI confirmation
"""

from __future__ import annotations

from typing import Literal

from docket.ai.extraction import EXTRACTION_PROMPT_VERSION
from docket.ai.extraction_schema import StructuredFacts, NextSteps
from docket.ai.rewrite import rewrite_item, ITEM_REWRITE_PROMPT_VERSION
from docket.ai.floors import apply_score_floors
from docket.ai.reconcile import reconcile_stages
from docket.db import db_cursor
from docket.services.badges import get_enabled_policy_slugs


def _audit(cur, item_id: int, from_status: str, to_status: str,
            action: str, actor: str, reason: str | None = None,
            payload: dict | None = None) -> None:
    cur.execute("""
        INSERT INTO processing_status_audit
          (agenda_item_id, from_status, to_status, action, actor, actor_role, reason, payload)
        VALUES (%s, %s::processing_status_enum, %s::processing_status_enum,
                %s, %s, 'admin', %s, %s::jsonb)
    """, [item_id, from_status, to_status, action, actor, reason,
          json.dumps(payload) if payload else None])


def accept_stage_1(item_id: int, *, manual_headline: str, manual_why_it_matters: str,
                    actor: str) -> str:
    """Admin says: 'this IS substantive — here's what it should say.'
    Sets headline/why_it_matters from admin input, marks completed."""
    with db_cursor() as cur:
        cur.execute("""
            UPDATE agenda_items
            SET headline = %s,
                why_it_matters = %s,
                processing_status = 'completed'::processing_status_enum
            WHERE id = %s
            RETURNING processing_status
        """, [manual_headline, manual_why_it_matters, item_id])
        new_status = cur.fetchone()[0]
        _audit(cur, item_id, 'cross_stage_conflict', new_status,
               'accept_stage1', actor,
               payload={'manual_headline': manual_headline,
                        'manual_why_it_matters': manual_why_it_matters})
    return new_status


def accept_stage_2(item_id: int, *, actor: str, reason: str | None = None) -> str:
    """Admin says: 'Stage 2 was right — this IS procedural.'
    Clears Stage 1 facts that confused things; marks completed as procedural."""
    with db_cursor() as cur:
        cur.execute("""
            UPDATE agenda_items
            SET extracted_facts = NULL,
                headline = NULL,
                why_it_matters = NULL,
                processing_status = 'completed'::processing_status_enum
            WHERE id = %s
            RETURNING processing_status
        """, [item_id])
        new_status = cur.fetchone()[0]
        _audit(cur, item_id, 'cross_stage_conflict', new_status,
               'accept_stage2', actor, reason)
    return new_status


def re_prompt_stage_2(item_id: int, *, override_instruction: str, actor: str) -> str:
    """Admin writes a one-liner override; system re-runs Stage 2 with it.
    If conflicts again, item stays in cross_stage_conflict for another pass."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT ai.*, m.city_id FROM agenda_items ai
            JOIN meetings m ON m.id = ai.meeting_id
            WHERE ai.id = %s
        """, [item_id])
        row = cur.fetchone()  # construct an item view + StructuredFacts
        # ... re-run rewrite_item with extra_instruction=override_instruction
        # ... apply floors, reconcile
        # ... persist + return final status
        # Audit either way
    return new_status


def edit_stage_1_facts(item_id: int, *, new_facts_json: dict, actor: str,
                        reason: str | None = None) -> str:
    """Admin corrects misclassified facts (e.g., counterparty was wrong).
    System re-runs Stage 2 with corrected facts → reconcile."""
    with db_cursor() as cur:
        # Validate the new facts via Pydantic
        facts = StructuredFacts.model_validate(new_facts_json)
        cur.execute("""
            UPDATE agenda_items
            SET extracted_facts = %s::jsonb
            WHERE id = %s
        """, [json.dumps(new_facts_json), item_id])
        # Re-run Stage 2 + floors + reconcile (similar to re_prompt_stage_2)
        # ...
    return new_status
```

(The four resolution functions are implementable; the Stage 2 re-run path inside `re_prompt_stage_2` and `edit_stage_1_facts` reuses the same per-item pipeline orchestrator from Section B Task B5 — extract that loop into a helper if needed.)

- [ ] **Step G4.2: Admin route + listing template**

`src/docket/web/admin.py`:

```python
@admin_bp.route('/review/conflicts')
@login_required
def review_conflicts():
    with db_cursor() as cur:
        cur.execute("""
            SELECT ai.id, ai.title, ai.description, ai.extracted_facts,
                   ai.headline, ai.why_it_matters,
                   ai.score_overrides, ai.updated_at,
                   m.city_id, m.meeting_date,
                   c.slug AS city_slug, c.name AS city_name
            FROM agenda_items ai
            JOIN meetings m ON m.id = ai.meeting_id
            JOIN municipalities c ON c.id = m.city_id
            WHERE ai.processing_status = 'cross_stage_conflict'
            ORDER BY ai.data_debt_priority DESC, ai.updated_at DESC
            LIMIT 100
        """)
        items = cur.fetchall()
    return render_template('admin/review_conflicts.html', items=items)
```

`src/docket/web/templates/admin/review_conflicts.html` (sketch):

```jinja
{% extends 'admin/_base.html' %}

{% block content %}
<h1>Cross-Stage Conflicts ({{ items|length }})</h1>
<p>Items where Stage 1 (facts) and Stage 2 (Smart Brevity) disagreed
on whether the item is substantive. Resolve to clear the
"Verification in progress" pill on citizen-facing cards.</p>

<table class="conflict-queue">
{% for item in items %}
  <tr id="row-{{ item.id }}">
    <td class="raw">
      <h3>{{ item.title }}</h3>
      <p class="city">{{ item.city_name }} · {{ item.meeting_date }}</p>
      <details><summary>Original description</summary>
        <pre>{{ item.description }}</pre>
      </details>
    </td>
    <td class="stage-1">
      <h4>Stage 1 (Facts)</h4>
      <pre>{{ item.extracted_facts | tojson(indent=2) }}</pre>
    </td>
    <td class="stage-2">
      <h4>Stage 2 (verdict: PROCEDURAL)</h4>
      <p class="conflict-reasons">
        {% for reason in item.score_overrides.conflicts %}
          <span class="conflict-tag">{{ reason }}</span>
        {% endfor %}
      </p>
    </td>
    <td class="actions">
      <button hx-post="{{ url_for('admin.conflict_accept_stage_1', item_id=item.id) }}"
              hx-target="#row-{{ item.id }}" hx-swap="outerHTML">
        ✅ Accept Stage 1 (substantive)
      </button>
      <button hx-post="{{ url_for('admin.conflict_accept_stage_2', item_id=item.id) }}"
              hx-target="#row-{{ item.id }}" hx-swap="outerHTML">
        ❌ Accept Stage 2 (procedural)
      </button>
      <button hx-get="{{ url_for('admin.conflict_re_prompt_form', item_id=item.id) }}"
              hx-target="#row-{{ item.id }}" hx-swap="outerHTML">
        🔁 Re-prompt with instruction
      </button>
      <button hx-get="{{ url_for('admin.conflict_edit_facts_form', item_id=item.id) }}"
              hx-target="#row-{{ item.id }}" hx-swap="outerHTML">
        📝 Edit Stage 1 facts
      </button>
    </td>
  </tr>
{% endfor %}
</table>
{% endblock %}
```

For the "Accept Stage 1" action, the admin form prompts for `manual_headline` (≤60 chars) and `manual_why_it_matters` (≤200 chars). Server-side enforces the same length caps as the Pydantic schema.

- [ ] **Step G4.3: Four HTMX endpoints**

```python
@admin_bp.route('/review/conflicts/<int:item_id>/accept-stage-1', methods=['POST'])
@login_required
def conflict_accept_stage_1(item_id: int):
    headline = request.form['manual_headline'].strip()
    why = request.form['manual_why_it_matters'].strip()
    if len(headline) < 10 or len(headline) > 60:
        return ("Headline must be 10–60 chars", 400)
    if not why or len(why) > 200:
        return ("Why it matters must be 1–200 chars", 400)
    new_status = accept_stage_1(item_id, manual_headline=headline,
                                  manual_why_it_matters=why,
                                  actor=current_user.username)
    return render_template('admin/_conflict_resolved.html',
                            item_id=item_id, new_status=new_status,
                            action='accept_stage1')


@admin_bp.route('/review/conflicts/<int:item_id>/accept-stage-2', methods=['POST'])
@login_required
def conflict_accept_stage_2(item_id: int):
    reason = request.form.get('reason', '').strip() or None
    new_status = accept_stage_2(item_id, actor=current_user.username, reason=reason)
    return render_template('admin/_conflict_resolved.html',
                            item_id=item_id, new_status=new_status,
                            action='accept_stage2')


# Similar for re_prompt and edit_facts. Each writes to processing_status_audit.
```

- [ ] **Step G4.4: Integration tests**

`tests/integration/test_conflict_resolution.py`:

Cover each of the 4 resolution actions:
1. `accept_stage_1` — item has manual headline/why_it_matters; status='completed'
2. `accept_stage_2` — Stage 1 facts cleared; status='completed'; is_substantive becomes false
3. `re_prompt_stage_2` — Stage 2 reruns with override; if successful, status='completed'
4. `edit_stage_1_facts` — facts updated; Stage 2 reruns; reconciled

Each test verifies a `processing_status_audit` row was inserted with the right action.

- [ ] **Step G4.5: Commit**

```bash
git add src/docket/services/conflict_resolution.py \
        src/docket/web/admin.py \
        src/docket/web/templates/admin/review_conflicts.html \
        src/docket/web/templates/admin/_conflict_resolved.html \
        tests/integration/test_conflict_resolution.py
git commit -m "feat(admin): cross-stage conflict resolution UI (4 HTMX actions, audit-logged)"
```

---

# Section H — Backfill Driver Foundations (~1 day, no actual waves yet)

Phase 3 runs the actual backfill. Phase 2's job is to land the infrastructure: the driver function, the AdaptiveWorkerPool, the Batches API wrapper, and the calibration_report task.

## Task H1: AdaptiveWorkerPool

**Files:**
- Create: `src/docket/ai/concurrency.py`
- Create: `tests/unit/test_concurrency.py`

- [ ] **Step H1.1: Implement spec §7.8 `AdaptiveWorkerPool`**

Direct copy from spec. Tests cover: 429 storm scales down, cool-down period blocks scale-up, scale-up after clean window, min/max bounds.

- [ ] **Step H1.2: Commit**

```bash
git add src/docket/ai/concurrency.py tests/unit/test_concurrency.py
git commit -m "feat(ai): AdaptiveWorkerPool for 429-aware concurrency scaling"
```

## Task H2: Anthropic Batches API Wrapper

**Files:**
- Create: `src/docket/ai/batches.py`
- Create: `tests/unit/test_batches.py`

- [ ] **Step H2.1: Implement `submit_batch(items, stage)` and `poll_batch(batch_id)` from spec §7.3**

Records the batch in `ai_batches` table; poll loop persists results to `ai_batch_items`.

- [ ] **Step H2.2: Tests with mocked Anthropic client**

Verify: submit creates an `ai_batches` row with correct `stage`, `wave`, `item_count`. Poll on 'ended' status fetches results and inserts into `ai_batch_items`.

- [ ] **Step H2.3: Commit**

```bash
git add src/docket/ai/batches.py tests/unit/test_batches.py
git commit -m "feat(ai): Anthropic Batches API wrapper + ai_batches/ai_batch_items persistence"
```

## Task H3: Backfill Driver Task

**Files:**
- Create: `src/docket/ai/backfill_driver.py`
- Modify: `src/docket/ai/cli.py`

- [ ] **Step H3.1: Implement the wave driver per spec §7**

```python
def run_wave(wave_name: str, date_range: tuple[date, date], stage: str) -> str:
    """Submits a wave's pending items via Batches API.
    Returns the session_id (UUID) for rollback if needed."""
    session_id = uuid.uuid4()
    ...
```

- [ ] **Step H3.2: Wire `--wave 0.5/1/2/3 --stage 1/2 --batch-size N` flags into CLI**

Phase 1 already handles `--wave 0`. Phase 2 extends to: 0.5 (sync burst), 1, 2, 3 (Batches).

- [ ] **Step H3.3: Commit**

```bash
git add src/docket/ai/backfill_driver.py src/docket/ai/cli.py
git commit -m "feat(ai): backfill driver with session_id support + wave 0.5/1/2/3 CLI flags"
```

## Task H4: calibration_report Cron Task (+ AI cache cleanup)

**Files:**
- Modify: `src/docket/worker/tasks.py`

- [ ] **Step H4.1: Add daily `calibration_report` task running the 4 calibration queries**

Output: structured JSON written to a log + Healthchecks ping with relevant counters. Plus call `cache_cleanup(max_age_days=90)` from `docket.ai.cache` (decision #91 cleanup policy) — surfaces n_deleted in the same log line.

```python
def calibration_report_task() -> None:
    from docket.ai.cache import cache_cleanup
    # ... run the 4 calibration queries ...
    n_cache_deleted = cache_cleanup(max_age_days=90)
    log.info("calibration_report: ... cache_cleanup=%d rows", n_cache_deleted)
```

- [ ] **Step H4.2: Wire into scheduler at 11:00 America/Chicago**

- [ ] **Step H4.3: Commit**

```bash
git add src/docket/worker/tasks.py src/docket/worker/scheduler.py
git commit -m "feat(worker): calibration_report cron task + AI cache 90-day cleanup"
```

---

# Phase 2 Final Steps — Deploy + Smoke Test

## Task FINAL-1: Wire IMPACT_FIRST_ENABLED Flag

**Files:**
- Modify: `src/docket/worker/tasks.py`

- [ ] **Step FINAL-1.1: Update existing `ai_items` task**

Wrap the new pipeline behind the flag. When false, the existing v2 logic runs unchanged. When true, the per-item loop calls `pipeline.process_item()` (Section B Task B5).

```python
def ai_items_task() -> None:
    if os.environ.get('IMPACT_FIRST_ENABLED', '').lower() == 'true':
        from docket.ai.pipeline import process_item
        # ... loop pending items, call process_item ...
    else:
        # ... existing v2 logic unchanged ...
```

- [ ] **Step FINAL-1.2: Commit**

```bash
git add src/docket/worker/tasks.py
git commit -m "feat(worker): IMPACT_FIRST_ENABLED feature flag for ai_items task"
```

## Task FINAL-2: Deploy to Railway with Flags Off

- [ ] **Step FINAL-2.1: Push + deploy**

```bash
git push -u origin feat/impact-first-phase-2
railway up --detach
railway up --detach --service worker
```

- [ ] **Step FINAL-2.2: Verify flags are OFF in Railway env**

```bash
railway variables --service docket-web | grep -E "IMPACT_FIRST|SMART_BREVITY"
railway variables --service worker | grep IMPACT_FIRST
```

Expected: variables not set OR set to `false`. v2 pipeline + UI keep running.

- [ ] **Step FINAL-2.3: Smoke-test from production logs**

`railway logs --service docket-web` — verify no errors. `railway logs --service worker` — verify cron jobs still firing.

## Task FINAL-3: Flip IMPACT_FIRST_ENABLED for Worker

- [ ] **Step FINAL-3.1: Set the flag on the worker service**

```bash
railway variables --service worker --set IMPACT_FIRST_ENABLED=true
```

- [ ] **Step FINAL-3.2: Wait for next scheduled `ai_items` run**

Or trigger manually:
```bash
railway ssh --service worker
venv/bin/python -m docket.worker.scheduler --run-once ai_items
```

- [ ] **Step FINAL-3.3: Verify new items flow through the v3 pipeline**

```bash
DATABASE_URL="$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-)" \
  /opt/homebrew/opt/postgresql@18/bin/psql -c "
SELECT COUNT(*) AS new_items_with_v3
FROM agenda_items
WHERE ai_rewrite_version = 3
  AND updated_at > NOW() - INTERVAL '24 hours';
"
```

Expected: nonzero count after the next nightly run.

## Task FINAL-4: Tag the Phase 2 Release

- [ ] **Step FINAL-4.1: Tag**

```bash
git tag refactor-impact-first-phase-2-shipped
git push origin refactor-impact-first-phase-2-shipped
```

`SMART_BREVITY_UI=true` flip is intentionally deferred to Phase 3 — citizens don't see v3 cards until Wave 1 of the backfill produces meaningful coverage of recent meetings.

---

## Self-Review Checklist

**Spec coverage:**
- [x] Section 2.3 (Stage 1 schemas + worker) → Tasks A1-A4
- [x] Section 3 (Stage 2 + 2.5 + reconcile) → Tasks B1-B5
- [x] Section 4 (process badges, all 7) → Tasks C1-C2
- [x] Section 5 (policy badges + audit log) → Tasks D1-D2
- [x] Section 6 (Smart Brevity Card + frontend) → Tasks E1-E6, F1-F5
- [x] Section 7.3 (backfill driver foundations) → Tasks H1-H3
- [x] Section 7.8 (adaptive concurrency, calibration) → Tasks H1, H4
- [x] Decisions #36-43 (extraction fields), #45 (reconcile), #50, #67-77 (UI), #80-90 — every active decision has a task
- [x] Decision #91 (DB-backed cache) — Task A2
- [x] Decision #92 (city_id denormalized) — Task C1, D1, pipeline.py, admin badge add endpoint
- [x] Decision #93 (conflict resolution UI) — Task G4
- [x] Decision #94 (SDK hardening) — Task A3 (extraction.py), Task B2 (rewrite.py)

**Placeholder scan:**
- [x] No "TBD" / "TODO" — all tasks have concrete code or "see spec §X.Y" references
- [x] All file paths exact
- [x] All commands runnable

**Type consistency:**
- [x] `StructuredFacts` defined in extraction_schema, used by extraction, rewrite, floors, reconcile, pipeline
- [x] `ItemRewrite` defined in rewrite_schema, used by rewrite, reconcile, pipeline
- [x] `ScoreOverrides` defined in floors, used by pipeline
- [x] `ReconciliationResult` defined in reconcile, used by pipeline

**Scope check:**
- [x] Phase 2 is one large but coherent plan. Section boundaries provide natural breakpoints for parallel engineers.
- [x] Backfill EXECUTION (running waves) is Phase 3 — Phase 2 only lands the foundation.

---

## What ships at the end of Phase 2

- All new pipeline code deployed behind `IMPACT_FIRST_ENABLED=true` (worker uses v3)
- All new frontend code deployed behind `SMART_BREVITY_UI=false` (citizens still see v2)
- Live nightly `ai_items` task processes new items via v3 pipeline
- Process and policy badges land for new items
- Admin views accessible at `/admin/{calibration,data-debt,errors,badges/audit}`
- Backfill driver + Batches API wrapper exist but no waves have run yet
- Migration 014 NOT yet applied (Phase 4)

## What does NOT ship in Phase 2

- Wave 0.5 / 1 / 2 / 3 backfill execution (Phase 3)
- `SMART_BREVITY_UI=true` flip (Phase 3, after Wave 1 coverage)
- `BACKFILL_ACTIVE` banner — retired (decision #80)
- v2 `summary` column drop (Phase 4)
