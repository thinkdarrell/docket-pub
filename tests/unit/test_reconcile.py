"""Tests for Stage 3 cross-stage reconcile (docket.ai.reconcile).

Coverage:
1. No conflict path → action='accept'
2. Stage 2 procedural + Stage 1 has counterparty → conflict
3. Stage 2 procedural + Stage 1 has funding_source → conflict
4. Stage 2 procedural + yellow-tier dollars → conflict
5. Stage 2 procedural + high-attention action_type → conflict
6. Stage 2 procedural + subject-matter regex match → conflict
7. already_retried=True with conflicts → action='mark_cross_stage_conflict'
8. retry_stage2_with_override path → override_instruction contains expected substrings
"""

from __future__ import annotations

import pytest

from docket.ai.extraction_schema import NextSteps, StructuredFacts
from docket.ai.reconcile import HIGH_ATTENTION_ACTION_TYPES, ReconciliationResult, reconcile_stages
from docket.ai.rewrite_schema import ItemRewrite


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_item(**kw):
    """Lightweight duck-typed agenda item fixture."""
    defaults = {
        'id': 1,
        'title': 'Award of contract',
        'description': 'Some description.',
        'dollars_amount': None,
    }
    defaults.update(kw)
    return type('Item', (), defaults)()


def make_facts(**kw) -> StructuredFacts:
    """Minimal valid StructuredFacts."""
    defaults = dict(
        funding_source='unknown',
        counterparty=None,
        procurement_method='competitive',
        location=None,
        action_type='contract_award',
        next_steps=NextSteps(),
        parcels_affected=None,
        acres_affected=None,
    )
    defaults.update(kw)
    return StructuredFacts(**defaults)


def make_procedural_rewrite() -> ItemRewrite:
    """ItemRewrite that Stage 2 classified as procedural."""
    return ItemRewrite(
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


def make_substantive_rewrite() -> ItemRewrite:
    """ItemRewrite that Stage 2 classified as substantive."""
    return ItemRewrite(
        is_substantive=True,
        headline="Council awards $4.2M HVAC contract",
        why_it_matters="Locks city into a multi-year maintenance agreement.",
        significance_rationale="Large dollar value contract with multi-year implications.",
        significance_score=7,
        consent_placement_rationale="High dollar amount suggests full council vote.",
        consent_placement_score=3,
        suggested_badge_slugs=[],
        confidence='high',
    )


# ---------------------------------------------------------------------------
# Test 1: No conflict path → action='accept'
# ---------------------------------------------------------------------------

def test_accept_when_stage2_is_substantive():
    """When Stage 2 marks substantive, no conflicts exist → accept."""
    item = make_item()
    facts = make_facts()
    rewrite = make_substantive_rewrite()

    result = reconcile_stages(facts, rewrite, item)

    assert result.action == 'accept'
    assert result.conflicts == []
    assert result.override_instruction is None


def test_accept_when_stage2_procedural_and_no_substance():
    """Stage 2 procedural + no counterparty/funding/dollars/action_type/subject → accept."""
    item = make_item(title='Roll Call', description='')
    facts = make_facts(
        funding_source='unknown',
        counterparty=None,
        action_type='other',
    )
    rewrite = make_procedural_rewrite()

    result = reconcile_stages(facts, rewrite, item)

    assert result.action == 'accept'
    assert result.conflicts == []


# ---------------------------------------------------------------------------
# Test 2: Stage 2 procedural + Stage 1 has counterparty → conflict
# ---------------------------------------------------------------------------

def test_conflict_counterparty():
    """Stage 2 procedural but Stage 1 found a counterparty → retry."""
    item = make_item()
    facts = make_facts(counterparty='Acme Corp', funding_source='unknown', action_type='other')
    rewrite = make_procedural_rewrite()

    result = reconcile_stages(facts, rewrite, item)

    assert result.action == 'retry_stage2_with_override'
    assert 'stage1_has_counterparty_but_stage2_procedural' in result.conflicts


# ---------------------------------------------------------------------------
# Test 3: Stage 2 procedural + Stage 1 has funding_source → conflict
# ---------------------------------------------------------------------------

def test_conflict_funding_source_general_fund():
    """funding_source='general_fund' (not 'unknown'/None) triggers conflict."""
    item = make_item()
    facts = make_facts(funding_source='general_fund', counterparty=None, action_type='other')
    rewrite = make_procedural_rewrite()

    result = reconcile_stages(facts, rewrite, item)

    assert result.action == 'retry_stage2_with_override'
    assert 'stage1_has_funding_source_but_stage2_procedural' in result.conflicts


def test_no_conflict_funding_source_unknown():
    """funding_source='unknown' should NOT trigger conflict."""
    item = make_item(title='Roll Call', description='')
    facts = make_facts(funding_source='unknown', counterparty=None, action_type='other')
    rewrite = make_procedural_rewrite()

    result = reconcile_stages(facts, rewrite, item)

    assert result.action == 'accept'
    assert 'stage1_has_funding_source_but_stage2_procedural' not in result.conflicts


# ---------------------------------------------------------------------------
# Test 4: Stage 2 procedural + yellow-tier dollars → conflict
# ---------------------------------------------------------------------------

def test_conflict_yellow_tier_dollars():
    """dollars_amount=75_000 meets the $50K yellow-tier threshold → conflict."""
    item = make_item(dollars_amount=75_000)
    facts = make_facts(funding_source='unknown', counterparty=None, action_type='other')
    rewrite = make_procedural_rewrite()

    result = reconcile_stages(facts, rewrite, item)

    assert result.action == 'retry_stage2_with_override'
    assert 'yellow_tier_dollars_but_stage2_procedural' in result.conflicts


def test_no_conflict_below_yellow_tier():
    """dollars_amount=49_999 is below $50K → no yellow-tier conflict."""
    item = make_item(title='Roll Call', description='', dollars_amount=49_999)
    facts = make_facts(funding_source='unknown', counterparty=None, action_type='other')
    rewrite = make_procedural_rewrite()

    result = reconcile_stages(facts, rewrite, item)

    assert 'yellow_tier_dollars_but_stage2_procedural' not in result.conflicts


def test_no_conflict_dollars_none():
    """dollars_amount=None → no yellow-tier conflict."""
    item = make_item(title='Roll Call', description='', dollars_amount=None)
    facts = make_facts(funding_source='unknown', counterparty=None, action_type='other')
    rewrite = make_procedural_rewrite()

    result = reconcile_stages(facts, rewrite, item)

    assert 'yellow_tier_dollars_but_stage2_procedural' not in result.conflicts


# ---------------------------------------------------------------------------
# Test 5: Stage 2 procedural + high-attention action_type → conflict
# ---------------------------------------------------------------------------

def test_conflict_action_type_settlement():
    """action_type='settlement' is in the high-attention list → conflict."""
    item = make_item(title='Roll Call', description='')
    facts = make_facts(funding_source='unknown', counterparty=None, action_type='settlement')
    rewrite = make_procedural_rewrite()

    result = reconcile_stages(facts, rewrite, item)

    assert result.action == 'retry_stage2_with_override'
    assert any('high_attention_action_type_but_stage2_procedural:settlement' in c
               for c in result.conflicts)


@pytest.mark.parametrize('action_type', sorted(HIGH_ATTENTION_ACTION_TYPES))
def test_conflict_all_high_attention_action_types(action_type):
    """Every action_type in the high-attention list triggers a conflict."""
    item = make_item(title='Roll Call', description='')
    facts = make_facts(funding_source='unknown', counterparty=None, action_type=action_type)
    rewrite = make_procedural_rewrite()

    result = reconcile_stages(facts, rewrite, item)

    assert any(f'high_attention_action_type_but_stage2_procedural:{action_type}' in c
               for c in result.conflicts)


def test_no_conflict_non_high_attention_action_type():
    """action_type='other' is not in the high-attention list → no action_type conflict."""
    item = make_item(title='Roll Call', description='')
    facts = make_facts(funding_source='unknown', counterparty=None, action_type='other')
    rewrite = make_procedural_rewrite()

    result = reconcile_stages(facts, rewrite, item)

    action_type_conflicts = [c for c in result.conflicts
                              if c.startswith('high_attention_action_type')]
    assert action_type_conflicts == []


# ---------------------------------------------------------------------------
# Test 6: Stage 2 procedural + subject-matter regex match → conflict
# ---------------------------------------------------------------------------

def test_conflict_subject_matter_flock_contract():
    """Title containing 'Flock' triggers surveillance_alpr subject-matter conflict."""
    item = make_item(title='Flock contract renewal', description='')
    facts = make_facts(funding_source='unknown', counterparty=None, action_type='other')
    rewrite = make_procedural_rewrite()

    result = reconcile_stages(facts, rewrite, item)

    assert result.action == 'retry_stage2_with_override'
    assert any('subject_matter_match_but_stage2_procedural:surveillance_alpr' in c
               for c in result.conflicts)


def test_conflict_subject_matter_only_one_appended():
    """The subject-matter loop breaks on first match — only one subject_matter conflict appended."""
    # Use a title that could match multiple patterns if not broken
    item = make_item(title='Use of force and eminent domain policy', description='')
    facts = make_facts(funding_source='unknown', counterparty=None, action_type='other')
    rewrite = make_procedural_rewrite()

    result = reconcile_stages(facts, rewrite, item)

    subject_matter_conflicts = [c for c in result.conflicts
                                 if c.startswith('subject_matter_match_but_stage2_procedural')]
    # The loop breaks after the first match, so exactly one subject_matter conflict
    assert len(subject_matter_conflicts) == 1


def test_conflict_subject_matter_in_description():
    """Subject-matter regex also searches description, not just title."""
    item = make_item(title='Technology agreement', description='Deployment of ALPR cameras citywide.')
    facts = make_facts(funding_source='unknown', counterparty=None, action_type='other')
    rewrite = make_procedural_rewrite()

    result = reconcile_stages(facts, rewrite, item)

    assert any('subject_matter_match_but_stage2_procedural' in c for c in result.conflicts)


def test_no_conflict_subject_matter_no_match():
    """Routine contract title doesn't match any subject-matter pattern."""
    item = make_item(title='Award street paving contract', description='Pothole repair citywide.')
    facts = make_facts(funding_source='unknown', counterparty=None, action_type='other')
    rewrite = make_procedural_rewrite()

    result = reconcile_stages(facts, rewrite, item)

    subject_matter_conflicts = [c for c in result.conflicts
                                 if c.startswith('subject_matter_match_but_stage2_procedural')]
    assert subject_matter_conflicts == []


# ---------------------------------------------------------------------------
# Test 7: already_retried=True with conflicts → action='mark_cross_stage_conflict'
# ---------------------------------------------------------------------------

def test_already_retried_escalates_to_cross_stage_conflict():
    """When already_retried=True and conflicts exist, escalate rather than retry."""
    item = make_item()
    facts = make_facts(counterparty='Acme Corp', funding_source='unknown', action_type='other')
    rewrite = make_procedural_rewrite()

    result = reconcile_stages(facts, rewrite, item, already_retried=True)

    assert result.action == 'mark_cross_stage_conflict'
    assert result.conflicts != []
    assert result.override_instruction is None  # No override on escalation


def test_already_retried_false_does_not_escalate():
    """When already_retried=False (default), first-time conflicts trigger retry not escalation."""
    item = make_item()
    facts = make_facts(counterparty='Acme Corp', funding_source='unknown', action_type='other')
    rewrite = make_procedural_rewrite()

    result = reconcile_stages(facts, rewrite, item, already_retried=False)

    assert result.action == 'retry_stage2_with_override'
    assert result.override_instruction is not None


# ---------------------------------------------------------------------------
# Test 8: retry_stage2_with_override → override_instruction contains expected substrings
# ---------------------------------------------------------------------------

def test_override_instruction_contains_expected_substrings():
    """The override_instruction message must contain all four key interpolations."""
    item = make_item(dollars_amount=75_000)
    facts = make_facts(
        counterparty='Acme Corp',
        funding_source='general_fund',
        action_type='settlement',
    )
    rewrite = make_procedural_rewrite()

    result = reconcile_stages(facts, rewrite, item)

    assert result.action == 'retry_stage2_with_override'
    assert result.override_instruction is not None

    oi = result.override_instruction
    assert "PREVIOUS ATTEMPT" in oi
    assert "Acme Corp" in oi              # counterparty value
    assert "settlement" in oi             # action_type value
    assert "$75,000" in oi               # dollar amount formatted with comma


def test_override_instruction_zero_dollars_formatting():
    """When dollars_amount is None, the override formats as $0."""
    item = make_item(dollars_amount=None)
    facts = make_facts(counterparty='Acme Corp', funding_source='unknown', action_type='other')
    rewrite = make_procedural_rewrite()

    result = reconcile_stages(facts, rewrite, item)

    assert result.override_instruction is not None
    assert "$0" in result.override_instruction


def test_override_instruction_not_set_on_accept():
    """No override_instruction on accept path."""
    item = make_item()
    facts = make_facts()
    rewrite = make_substantive_rewrite()

    result = reconcile_stages(facts, rewrite, item)

    assert result.action == 'accept'
    assert result.override_instruction is None


# ---------------------------------------------------------------------------
# ReconciliationResult dataclass shape
# ---------------------------------------------------------------------------

def test_reconciliation_result_is_dataclass():
    """ReconciliationResult is a proper dataclass with the expected fields."""
    r = ReconciliationResult(action='accept', conflicts=[])
    assert r.action == 'accept'
    assert r.conflicts == []
    assert r.override_instruction is None  # default


def test_reconciliation_result_with_override():
    r = ReconciliationResult(
        action='retry_stage2_with_override',
        conflicts=['stage1_has_counterparty_but_stage2_procedural'],
        override_instruction='PREVIOUS ATTEMPT ...',
    )
    assert r.action == 'retry_stage2_with_override'
    assert len(r.conflicts) == 1
    assert r.override_instruction is not None
