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

        Note: ``source_type`` is accepted for API compatibility with the
        plan but NOT persisted — the ``agenda_items`` table has no
        ``source_type`` column. The duck-typed item shape exposes it via
        ``_ItemView`` (defaulted to 'agenda') so callers reading the row
        can still see the attribute.
        """
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agenda_items
                  (meeting_id, title, description, sponsor, dollars_amount,
                   topic, is_consent,
                   data_quality, data_debt_priority, processing_status)
                VALUES (%s, %s, %s, %s, %s, %s, %s,
                        'ok'::data_quality_enum,
                        'normal'::data_debt_priority_enum,
                        'pending'::processing_status_enum)
                RETURNING id
                """,
                (meeting_id, title, description, sponsor, dollars_amount,
                 topic, is_consent),
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
                   ai.data_quality::text AS data_quality,
                   ai.processing_status::text AS processing_status,
                   ai.extracted_facts, ai.headline, ai.why_it_matters,
                   ai.significance_score, ai.consent_placement_score,
                   ai.score_overrides,
                   ai.ai_extraction_version, ai.ai_rewrite_version,
                   m.municipality_id AS city_id,
                   muni.name AS city_name
              FROM agenda_items ai
              JOIN meetings m ON m.id = ai.meeting_id
              JOIN municipalities muni ON muni.id = m.municipality_id
             WHERE ai.id = %s
            """,
            (item_id,),
        )
        row = dict(cur.fetchone())
        # source_type is duck-typed onto items even though no column exists.
        # Wave 0's evaluate_data_quality and rewrite_item read it.
        row["source_type"] = "agenda"
        return row


def _read_badges(item_id: int) -> list[tuple]:
    """Read agenda_item_badges rows for assertions.

    Tuple shape: (badge_slug, kind, confidence, source, city_id, status).
    """
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT badge_slug, kind, confidence::float, source, city_id, status
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
    # Refactor #2: process badges always write status='applied'.
    by_slug = {b[0]: b for b in badges}
    assert by_slug["legal_settlement"][5] == "applied"


def test_pipeline_writes_status_flagged_for_llm_only_policy_badge(bag, monkeypatch):
    """Refactor #2: when Stage 2 suggests a policy badge but no
    deterministic signal backs it, the badge row lands at
    status='flagged' so it's invisible to citizens until an admin
    promotes it."""
    from docket.ai import pipeline

    monkeypatch.setattr(
        "docket.ai.pipeline.evaluate_data_quality",
        lambda item: ("ok", "normal"),
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.is_procedural",
        lambda title: False,
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.extract_facts_for_item",
        lambda *a, **kw: (_sample_facts(), "claude-haiku-4-5-20251001"),
    )

    rewrite = _substantive_rewrite()
    # Force a single policy-badge slug suggestion. Bypass real
    # enabled-badge lookup by monkeypatching compute_policy_badges to
    # yield exactly what Section A.3 specifies for an LLM-only path.
    monkeypatch.setattr(
        "docket.ai.pipeline.rewrite_item",
        lambda *a, **kw: (rewrite, "claude-haiku-4-5-20251001"),
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.compute_policy_badges",
        lambda item, facts, rw, city_id: [
            ("housing_stability", 0.4, "llm", {"llm_only": True}, "flagged"),
        ],
    )

    m = bag.add_meeting()
    iid = bag.add_pending_item(m, title="Routine procurement housekeeping")
    item = _ItemView(_load_item(iid))

    status = pipeline.process_item(item)
    assert status == "completed"

    badges = _read_badges(iid)
    by_slug = {b[0]: b for b in badges}
    assert "housing_stability" in by_slug
    row = by_slug["housing_stability"]
    # (badge_slug, kind, confidence, source, city_id, status)
    assert row[1] == "policy"
    assert row[3] == "llm"
    assert row[5] == "flagged"


def test_pipeline_writes_audit_row_when_policy_badge_lands_flagged(bag, monkeypatch):
    """Refactor #2 retro [MEDIUM #2]: when a policy badge is inserted
    with status='flagged' at write time, the pipeline must also write
    an agenda_item_badges_audit row recording the on-write flag so
    flagged badges have audit provenance from the moment they land —
    not just the ones touched by the one-off backfill script."""
    from docket.ai import pipeline

    monkeypatch.setattr(
        "docket.ai.pipeline.evaluate_data_quality",
        lambda item: ("ok", "normal"),
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.is_procedural",
        lambda title: False,
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.extract_facts_for_item",
        lambda *a, **kw: (_sample_facts(), "claude-haiku-4-5-20251001"),
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.rewrite_item",
        lambda *a, **kw: (_substantive_rewrite(), "claude-haiku-4-5-20251001"),
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.compute_policy_badges",
        lambda item, facts, rw, city_id: [
            ("housing_stability", 0.4, "llm", {"llm_only": True}, "flagged"),
            ("blight_accountability", 0.8, "deterministic",
             {"matched_keywords": ["blight"]}, "applied"),
        ],
    )

    m = bag.add_meeting()
    iid = bag.add_pending_item(m, title="Routine procurement housekeeping")
    item = _ItemView(_load_item(iid))

    status = pipeline.process_item(item)
    assert status == "completed"

    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT badge_slug, action, actor, actor_role
              FROM agenda_item_badges_audit
             WHERE agenda_item_id = %s
             ORDER BY badge_slug
            """,
            (iid,),
        )
        audit_rows = cur.fetchall()

    by_slug = {r[0]: r for r in audit_rows}

    # Flagged badge must have an audit row attributed to the pipeline.
    assert "housing_stability" in by_slug, (
        "Expected an audit row for the LLM-only policy badge landed at "
        "status='flagged', but none was written."
    )
    flagged_row = by_slug["housing_stability"]
    assert flagged_row[1] == "flagged", \
        f"audit action should be 'flagged', got {flagged_row[1]!r}"
    assert flagged_row[2] == "pipeline", \
        f"audit actor should be 'pipeline', got {flagged_row[2]!r}"
    assert flagged_row[3] == "on_write", \
        f"audit actor_role should be 'on_write', got {flagged_row[3]!r}"

    # Applied badge must NOT generate an audit row at write time — audit
    # rows only fire on the flagged path (the moment a badge becomes
    # invisible to citizens is the moment we record provenance for it).
    assert "blight_accountability" not in by_slug, (
        "Deterministic 'applied' badges should not write audit rows at "
        "write time; got an unexpected audit row."
    )


def test_pipeline_writes_status_applied_for_deterministic_policy_badge(bag, monkeypatch):
    """Deterministic backing → status='applied' on the policy badge."""
    from docket.ai import pipeline

    monkeypatch.setattr(
        "docket.ai.pipeline.evaluate_data_quality",
        lambda item: ("ok", "normal"),
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.is_procedural",
        lambda title: False,
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.extract_facts_for_item",
        lambda *a, **kw: (_sample_facts(), "claude-haiku-4-5-20251001"),
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.rewrite_item",
        lambda *a, **kw: (_substantive_rewrite(), "claude-haiku-4-5-20251001"),
    )
    monkeypatch.setattr(
        "docket.ai.pipeline.compute_policy_badges",
        lambda item, facts, rw, city_id: [
            ("blight_accountability", 0.8, "deterministic",
             {"matched_keywords": ["blight"]}, "applied"),
        ],
    )

    m = bag.add_meeting()
    iid = bag.add_pending_item(m, title="Blight demolition order")
    item = _ItemView(_load_item(iid))

    status = pipeline.process_item(item)
    assert status == "completed"

    badges = _read_badges(iid)
    by_slug = {b[0]: b for b in badges}
    assert "blight_accountability" in by_slug
    row = by_slug["blight_accountability"]
    assert row[3] == "deterministic"
    assert row[5] == "applied"


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
    # Decision #13 atomicity contract: the inline extraction UPDATE
    # must also roll back when the guard fires. Pins the full Phase C
    # all-or-none property — a future refactor that splits the
    # extraction write from the main UPDATE would silently violate
    # decision #13 without these assertions catching it.
    assert final["extracted_facts"] is None, (
        "inline extraction UPDATE must also roll back on guard-fire"
    )
    assert final["ai_extraction_version"] is None, (
        "ai_extraction_version write must also roll back on guard-fire"
    )


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

    # Pull the sole_source row, verify confidence + source + city_id + status.
    sole_source_row = [b for b in badges if b[0] == "sole_source"][0]
    slug, kind, conf, source, city_id, status = sole_source_row
    assert kind == "process"
    assert conf == 1.0
    assert source == "deterministic"
    assert city_id == bag.city_id  # decision #92
    assert status == "applied"  # refactor #2: process badges always applied


def test_process_item_e2e_extracted_facts_persisted_inline(
    bag, monkeypatch,
):
    """The Stage 1 facts JSONB is persisted into agenda_items.extracted_facts
    by the pipeline's inline UPDATE — replaces the original persist_extraction
    call to avoid the processing_status='extracted' side-effect that would
    have spuriously fired decision #13's expected_status guard on admin paths
    (see "Post-implementation deviations" appendix in the B5 plan).

    End-to-end verification: extracted_facts column matches the
    StructuredFacts the mock returned, and ai_extraction_version matches
    EXTRACTION_PROMPT_VERSION."""
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

    status_first = pipeline.process_item(item)
    badges_first = _read_badges(iid)
    final_first = _load_item(iid)

    # Re-load item (now has post-first-run state) and call again.
    item2 = _ItemView(_load_item(iid))
    status_second = pipeline.process_item(item2)
    badges_second = _read_badges(iid)
    final_second = _load_item(iid)

    # Exact-same badge set — no duplicates from the ON CONFLICT DO NOTHING.
    assert badges_first == badges_second
    # SUG-3: pin the idempotency contract beyond badges.
    # Both calls return 'completed'; both writes produce the same headline.
    # A future "skip if already completed" short-circuit would change the
    # second call's return value — this assertion catches that regression.
    assert status_first == "completed"
    assert status_second == "completed"
    assert final_first["headline"] == final_second["headline"]
    assert final_first["headline"] == "Council awards $75K janitorial contract"


# ---------------------------------------------------------------------------
# Regression test for #57 (v3 ai_items hang after 2 Anthropic calls)
# ---------------------------------------------------------------------------


def test_process_item_uses_caller_conn_to_avoid_self_deadlock(bag, monkeypatch):
    """The v3 worker holds ``FOR UPDATE`` row locks on its own connection
    across the call to ``process_item`` (see ``claim_items_v3_sql``).
    Before the fix, ``process_item`` opened a *new* connection via ``db()``
    for Phase C's UPDATE. That new connection blocks forever waiting for
    the worker's lock — PostgreSQL can't detect this because there's no
    cycle in the wait graph.

    The fix threads the worker's ``conn`` through ``process_item`` so all
    DB writes go through the same connection. This test pins that
    contract: when a conn is passed in, ``process_item`` must NOT open a
    fresh ``db()`` connection. We assert that by patching
    ``docket.ai.pipeline.db`` to a forbidder — if the pipeline tries to
    fall through to ``db()`` despite the conn arg, the test fails fast.

    A passing test means the regression is fixed; without the fix the
    integration of worker + pipeline would hang for ~15 min before
    container SIGKILL on Railway (observed 2026-05-11 FINAL-3 attempt).
    """
    import psycopg2
    from docket.ai import pipeline
    from docket.config import DATABASE_URL

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

    # The forbidder: if pipeline opens a new db() connection while a
    # conn was provided, we fail immediately instead of deadlocking.
    # Patches ``pipeline.db`` (the local import inside pipeline.py) —
    # the bag fixture uses ``docket.db.db`` directly so cleanup is
    # unaffected by this patch.
    def _forbid_db(*args, **kwargs):
        raise AssertionError(
            "pipeline opened a new db() connection while caller passed "
            "conn — would self-deadlock against worker's FOR UPDATE lock "
            "(#57 regression)"
        )
    monkeypatch.setattr("docket.ai.pipeline.db", _forbid_db)

    m = bag.add_meeting()
    iid = bag.add_pending_item(m)

    # Connect directly (not via the patched ``db()``) so we own the
    # commit/rollback cycle the same way the worker does.
    worker_conn = psycopg2.connect(DATABASE_URL)
    try:
        with worker_conn.cursor() as cur:
            # Mirrors claim_items_v3_sql's lock acquisition shape.
            cur.execute(
                "SELECT id FROM agenda_items WHERE id = %s FOR UPDATE",
                (iid,),
            )
            assert cur.fetchone() is not None, "test row should be claimable"
        # Build the duck-typed item shape on the same connection so we
        # don't trigger _load_item's db_cursor (which uses the patched db).
        with worker_conn.cursor() as cur:
            cur.execute(
                """
                SELECT ai.id, ai.meeting_id, ai.title, ai.description,
                       ai.sponsor, ai.dollars_amount, ai.topic, ai.is_consent,
                       m.municipality_id AS city_id,
                       muni.name         AS city_name
                  FROM agenda_items ai
                  JOIN meetings m ON m.id = ai.meeting_id
                  JOIN municipalities muni ON muni.id = m.municipality_id
                 WHERE ai.id = %s
                """,
                (iid,),
            )
            columns = [
                "id", "meeting_id", "title", "description",
                "sponsor", "dollars_amount", "topic", "is_consent",
                "city_id", "city_name",
            ]
            row_dict = dict(zip(columns, cur.fetchone()))
            row_dict["source_type"] = "agenda"
            row_dict["raw_text"] = None
        item = _ItemView(row_dict)

        # The critical call. Without the fix this would raise the
        # AssertionError above (pre-fix) or hang waiting for the lock
        # (pre-fix, no patch). With the fix it threads ``conn`` and
        # never calls ``db()``.
        status = pipeline.process_item(item, conn=worker_conn)
        worker_conn.commit()
    except Exception:
        worker_conn.rollback()
        raise
    finally:
        worker_conn.close()

    assert status == "completed"

    final = _load_item(iid)
    assert final["processing_status"] == "completed"
    assert final["headline"] == "Council awards $75K janitorial contract"
    assert final["ai_extraction_version"] is not None
    assert final["ai_rewrite_version"] is not None
