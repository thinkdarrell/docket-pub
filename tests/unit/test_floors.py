"""Tests for Stage 2.5 score floors (docket.ai.floors).

Coverage:
- Per-trigger parametrized tests for SIGNIFICANCE_FLOORS (12 entries)
- Per-trigger parametrized tests for CONSENT_PLACEMENT_CEILINGS (4 entries)
- Subject-matter floors: keyword path AND badge path
- Override pathway: empty table uses defaults; inserted row uses override value
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from docket.ai.extraction_schema import NextSteps, StructuredFacts
from docket.ai.floors import (
    CONSENT_PLACEMENT_CEILINGS,
    SIGNIFICANCE_FLOORS,
    SUBJECT_MATTER_FLOORS,
    ScoreOverrides,
    apply_score_floors,
    _resolve_threshold,
)
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
        'is_consent': False,
    }
    defaults.update(kw)
    return type('Item', (), defaults)()


def make_facts(**kw) -> StructuredFacts:
    """Minimal valid StructuredFacts."""
    defaults = dict(
        funding_source='general_fund',
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


def make_ai(significance_score: int | None = 3,
            consent_placement_score: int | None = 8) -> ItemRewrite:
    """Minimal ItemRewrite with low scores so floors/ceilings have room to fire."""
    return ItemRewrite(
        is_substantive=True,
        headline='A headline of sufficient length',
        why_it_matters='Why it matters content',
        significance_rationale='rationale',
        significance_score=significance_score,
        consent_placement_rationale='rationale',
        consent_placement_score=consent_placement_score,
        suggested_badge_slugs=[],
        confidence='high',
    )


def mock_cursor_no_override() -> MagicMock:
    """Cursor whose fetchone() always returns None (no override rows)."""
    cur = MagicMock()
    cur.fetchone.return_value = None
    return cur


# ---------------------------------------------------------------------------
# _resolve_threshold: empty table returns defaults
# ---------------------------------------------------------------------------

def test_resolve_threshold_no_row_returns_defaults():
    cur = mock_cursor_no_override()
    threshold, bound = _resolve_threshold(cur, city_id=1, trigger_name='red_1m',
                                          default_threshold=None, default_bound=7)
    assert threshold is None
    assert bound == 7


def test_resolve_threshold_row_overrides_bound():
    cur = MagicMock()
    cur.fetchone.return_value = (None, 9)  # override_threshold_amount=None, override_min_score=9
    threshold, bound = _resolve_threshold(cur, city_id=1, trigger_name='red_1m',
                                          default_threshold=None, default_bound=7)
    assert bound == 9


def test_resolve_threshold_row_null_min_score_falls_back_to_default():
    cur = MagicMock()
    cur.fetchone.return_value = (500_000, None)  # min_score is NULL
    threshold, bound = _resolve_threshold(cur, city_id=1, trigger_name='red_1m',
                                          default_threshold=None, default_bound=7)
    assert threshold == 500_000
    assert bound == 7  # falls back to default


# ---------------------------------------------------------------------------
# SIGNIFICANCE_FLOORS — parametrized per trigger
# ---------------------------------------------------------------------------

# Each tuple: (trigger_name, matching_item_kwargs, matching_facts_kwargs, ai_score_below_floor)
SIGNIFICANCE_FLOOR_CASES = [
    (
        "red_plus_10m",
        dict(dollars_amount=10_000_000),
        {},
        3,  # floor=9, ai=3 → should boost to 9
    ),
    (
        "red_1m",
        dict(dollars_amount=1_000_000),
        {},
        3,  # floor=7
    ),
    (
        "orange_sole_source",
        dict(dollars_amount=250_000),
        dict(procurement_method='sole_source'),
        3,  # floor=7
    ),
    (
        "orange_settlement",
        dict(dollars_amount=250_000),
        dict(action_type='settlement'),
        3,  # floor=8
    ),
    (
        "yellow_sole_source",
        dict(dollars_amount=50_000),
        dict(procurement_method='sole_source'),
        3,  # floor=6
    ),
    (
        "yellow_settlement",
        dict(dollars_amount=50_000),
        dict(action_type='settlement'),
        3,  # floor=6
    ),
    (
        "any_settlement",
        {},
        dict(action_type='settlement'),
        3,  # floor=6
    ),
    (
        "zoning_large",
        {},
        dict(action_type='zoning', parcels_affected=5),
        3,  # floor=7
    ),
    (
        "emergency_proc",
        {},
        dict(action_type='emergency_procurement'),
        3,  # floor=7
    ),
    (
        "appt_executive",
        {},
        dict(action_type='appointment_executive'),
        3,  # floor=7
    ),
    (
        "appt_board",
        {},
        dict(action_type='appointment_board'),
        3,  # floor=5
    ),
    (
        "tax_abatement_orange",
        dict(dollars_amount=250_000),
        dict(action_type='tax_abatement'),
        3,  # floor=7
    ),
]

# Map trigger name → its declared bound
_SIG_FLOOR_BOUNDS = {t.name: t.bound for t in SIGNIFICANCE_FLOORS}


@pytest.mark.parametrize("trigger_name,item_kw,facts_kw,ai_score", SIGNIFICANCE_FLOOR_CASES)
def test_significance_floor_boosts_score(trigger_name, item_kw, facts_kw, ai_score):
    """When a trigger matches and AI score is below the floor, the floor fires."""
    item = make_item(**item_kw)
    facts = make_facts(**facts_kw)
    ai = make_ai(significance_score=ai_score)
    cur = mock_cursor_no_override()
    expected_floor = _SIG_FLOOR_BOUNDS[trigger_name]

    result = apply_score_floors(cur, item, facts, ai, city_id=1)

    assert result.final_significance is not None
    assert result.final_significance >= expected_floor
    assert result.final_significance >= ai_score  # monotonically non-decreasing

    # At least one fired trigger should match this floor
    fired_names = [t['trigger'] for t in result.triggers]
    assert trigger_name in fired_names, (
        f"Expected trigger '{trigger_name}' to fire but fired={fired_names}"
    )


@pytest.mark.parametrize("trigger_name,item_kw,facts_kw,ai_score", SIGNIFICANCE_FLOOR_CASES)
def test_significance_floor_no_boost_when_already_above(trigger_name, item_kw, facts_kw, ai_score):
    """When AI score is already at or above the floor, it must not be lowered."""
    item = make_item(**item_kw)
    facts = make_facts(**facts_kw)
    floor = _SIG_FLOOR_BOUNDS[trigger_name]
    ai = make_ai(significance_score=floor)  # exactly at floor
    cur = mock_cursor_no_override()

    result = apply_score_floors(cur, item, facts, ai, city_id=1)

    # Score must not go down
    assert result.final_significance >= floor
    # Trigger should not be in fired list (bound == score, so condition is False)
    fired_names = [t['trigger'] for t in result.triggers if t['field'] == 'significance']
    assert trigger_name not in fired_names


# ---------------------------------------------------------------------------
# CONSENT_PLACEMENT_CEILINGS — parametrized per trigger
# ---------------------------------------------------------------------------

# Each tuple: (trigger_name, item_kw, facts_kw, ai_consent_above_ceiling)
CONSENT_CEILING_CASES = [
    (
        "red_consent",
        dict(dollars_amount=1_000_000, is_consent=True),
        {},
        8,  # ceiling=2, ai=8 → should cap to 2
    ),
    (
        "sole_source_consent",
        dict(is_consent=True),
        dict(procurement_method='sole_source'),
        8,  # ceiling=2
    ),
    (
        "settlement_consent",
        dict(is_consent=True),
        dict(action_type='settlement'),
        8,  # ceiling=1
    ),
    (
        "appt_executive_consent",
        dict(is_consent=True),
        dict(action_type='appointment_executive'),
        8,  # ceiling=2
    ),
]

_CONSENT_CEILING_BOUNDS = {t.name: t.bound for t in CONSENT_PLACEMENT_CEILINGS}


@pytest.mark.parametrize("trigger_name,item_kw,facts_kw,ai_consent", CONSENT_CEILING_CASES)
def test_consent_ceiling_caps_score(trigger_name, item_kw, facts_kw, ai_consent):
    """When a ceiling trigger matches and AI consent score is above the ceiling, it is capped."""
    item = make_item(**item_kw)
    facts = make_facts(**facts_kw)
    ai = make_ai(significance_score=5, consent_placement_score=ai_consent)
    cur = mock_cursor_no_override()
    expected_ceiling = _CONSENT_CEILING_BOUNDS[trigger_name]

    result = apply_score_floors(cur, item, facts, ai, city_id=1)

    assert result.final_consent is not None
    assert result.final_consent <= expected_ceiling  # capped down
    assert result.final_consent <= ai_consent  # monotonically non-increasing

    fired_names = [t['trigger'] for t in result.triggers]
    assert trigger_name in fired_names, (
        f"Expected trigger '{trigger_name}' to fire but fired={fired_names}"
    )


@pytest.mark.parametrize("trigger_name,item_kw,facts_kw,ai_consent", CONSENT_CEILING_CASES)
def test_consent_ceiling_no_change_when_already_at_or_below(trigger_name, item_kw, facts_kw, ai_consent):
    """When AI consent score is at or below the ceiling, it must not be raised."""
    item = make_item(**item_kw)
    facts = make_facts(**facts_kw)
    ceiling = _CONSENT_CEILING_BOUNDS[trigger_name]
    ai = make_ai(significance_score=5, consent_placement_score=ceiling)
    cur = mock_cursor_no_override()

    result = apply_score_floors(cur, item, facts, ai, city_id=1)

    assert result.final_consent <= ceiling
    # Trigger should not be in fired list (bound == score, so condition is False)
    fired_names = [t['trigger'] for t in result.triggers if t['field'] == 'consent_placement']
    assert trigger_name not in fired_names


# ---------------------------------------------------------------------------
# SUBJECT_MATTER_FLOORS
# ---------------------------------------------------------------------------

class TestSurveillanceAlprSignificance:
    """surveillance_alpr_significance — keyword regex path and badge path."""

    def test_keyword_flock_fires(self):
        item = make_item(title='Purchase of Flock Safety cameras', description='')
        facts = make_facts()
        ai = make_ai(significance_score=3)
        cur = mock_cursor_no_override()

        result = apply_score_floors(cur, item, facts, ai, city_id=1)

        assert result.final_significance is not None
        assert result.final_significance >= 7
        fired_names = [t['trigger'] for t in result.triggers]
        assert 'surveillance_alpr_significance' in fired_names

    def test_keyword_alpr_in_description_fires(self):
        item = make_item(title='Technology Agreement', description='Deployment of ALPR system downtown.')
        facts = make_facts()
        ai = make_ai(significance_score=2)
        cur = mock_cursor_no_override()

        result = apply_score_floors(cur, item, facts, ai, city_id=1)

        assert result.final_significance >= 7

    def test_badge_slug_fires(self):
        """public_safety_tech_privacy badge triggers the floor even without keyword."""
        item = make_item(title='Technology purchase', description='No keywords here.')
        # Inject the badge via a duck-typed object with suggested_badge_slugs
        facts_with_badge = type('FactsWithBadge', (), {
            'funding_source': 'general_fund',
            'counterparty': None,
            'procurement_method': 'competitive',
            'location': None,
            'action_type': 'contract_award',
            'parcels_affected': None,
            'acres_affected': None,
            'suggested_badge_slugs': ['public_safety_tech_privacy'],
        })()
        ai = make_ai(significance_score=2)
        cur = mock_cursor_no_override()

        result = apply_score_floors(cur, item, facts_with_badge, ai, city_id=1)

        assert result.final_significance >= 7
        fired_names = [t['trigger'] for t in result.triggers]
        assert 'surveillance_alpr_significance' in fired_names

    def test_no_match_no_fire(self):
        item = make_item(title='Routine street repair contract', description='Pothole patching.')
        facts = make_facts()
        ai = make_ai(significance_score=3)
        cur = mock_cursor_no_override()

        result = apply_score_floors(cur, item, facts, ai, city_id=1)

        fired_names = [t['trigger'] for t in result.triggers]
        assert 'surveillance_alpr_significance' not in fired_names


class TestSurveillanceAlprConsent:
    """surveillance_alpr_consent — consent ceiling when item is on consent agenda."""

    def test_keyword_and_consent_fires(self):
        item = make_item(title='Flock camera network expansion', is_consent=True)
        facts = make_facts()
        ai = make_ai(significance_score=7, consent_placement_score=8)
        cur = mock_cursor_no_override()

        result = apply_score_floors(cur, item, facts, ai, city_id=1)

        assert result.final_consent is not None
        assert result.final_consent <= 2
        fired_names = [t['trigger'] for t in result.triggers]
        assert 'surveillance_alpr_consent' in fired_names

    def test_keyword_without_consent_does_not_fire(self):
        item = make_item(title='Flock camera network expansion', is_consent=False)
        facts = make_facts()
        ai = make_ai(significance_score=7, consent_placement_score=8)
        cur = mock_cursor_no_override()

        result = apply_score_floors(cur, item, facts, ai, city_id=1)

        fired_names = [t['trigger'] for t in result.triggers]
        assert 'surveillance_alpr_consent' not in fired_names


class TestPoliceOversight:
    """police_oversight significance and consent floors."""

    def test_use_of_force_fires_significance(self):
        item = make_item(title='Use of force policy update', description='')
        facts = make_facts()
        ai = make_ai(significance_score=3)
        cur = mock_cursor_no_override()

        result = apply_score_floors(cur, item, facts, ai, city_id=1)

        assert result.final_significance >= 8
        fired_names = [t['trigger'] for t in result.triggers]
        assert 'police_oversight_significance' in fired_names

    def test_citizen_review_board_fires(self):
        item = make_item(title='Citizen Review Board annual report', description='')
        facts = make_facts()
        ai = make_ai(significance_score=5)
        cur = mock_cursor_no_override()

        result = apply_score_floors(cur, item, facts, ai, city_id=1)

        assert result.final_significance >= 8

    def test_consent_fires_when_is_consent(self):
        item = make_item(title='Police oversight committee report', is_consent=True)
        facts = make_facts()
        ai = make_ai(significance_score=8, consent_placement_score=9)
        cur = mock_cursor_no_override()

        result = apply_score_floors(cur, item, facts, ai, city_id=1)

        assert result.final_consent <= 2
        fired_names = [t['trigger'] for t in result.triggers]
        assert 'police_oversight_consent' in fired_names

    def test_no_match_no_fire(self):
        item = make_item(title='Approve new police vehicle fleet', description='')
        facts = make_facts()
        ai = make_ai(significance_score=4)
        cur = mock_cursor_no_override()

        result = apply_score_floors(cur, item, facts, ai, city_id=1)

        fired_names = [t['trigger'] for t in result.triggers]
        assert 'police_oversight_significance' not in fired_names


class TestEminentDomain:
    """eminent_domain significance and consent floors."""

    def test_eminent_domain_fires_significance(self):
        item = make_item(title='Eminent domain action for I-20 corridor', description='')
        facts = make_facts()
        ai = make_ai(significance_score=3)
        cur = mock_cursor_no_override()

        result = apply_score_floors(cur, item, facts, ai, city_id=1)

        assert result.final_significance >= 8
        fired_names = [t['trigger'] for t in result.triggers]
        assert 'eminent_domain_significance' in fired_names

    def test_condemnation_in_description_fires(self):
        item = make_item(title='Property acquisition', description='Condemnation for public use of parcel 18.')
        facts = make_facts()
        ai = make_ai(significance_score=4)
        cur = mock_cursor_no_override()

        result = apply_score_floors(cur, item, facts, ai, city_id=1)

        assert result.final_significance >= 8

    def test_consent_fires_when_is_consent(self):
        item = make_item(title='Eminent domain: 400 Main Street', is_consent=True)
        facts = make_facts()
        ai = make_ai(significance_score=8, consent_placement_score=9)
        cur = mock_cursor_no_override()

        result = apply_score_floors(cur, item, facts, ai, city_id=1)

        assert result.final_consent <= 2

    def test_no_match_no_fire(self):
        item = make_item(title='Purchase of city hall annex building', description='')
        facts = make_facts()
        ai = make_ai(significance_score=4)
        cur = mock_cursor_no_override()

        result = apply_score_floors(cur, item, facts, ai, city_id=1)

        fired_names = [t['trigger'] for t in result.triggers]
        assert 'eminent_domain_significance' not in fired_names


# ---------------------------------------------------------------------------
# ScoreOverrides audit record shape
# ---------------------------------------------------------------------------

def test_score_overrides_preserves_original_scores():
    """apply_score_floors always records original AI scores in ScoreOverrides."""
    item = make_item(dollars_amount=2_000_000)
    facts = make_facts()
    ai = make_ai(significance_score=4, consent_placement_score=6)
    cur = mock_cursor_no_override()

    result = apply_score_floors(cur, item, facts, ai, city_id=1)

    assert result.original_ai_significance == 4
    assert result.original_ai_consent == 6
    assert result.final_significance >= 7  # red_1m floor
    assert result.final_consent == 6  # no ceiling trigger matched (not is_consent)


def test_score_overrides_no_triggers_when_no_match():
    """When nothing matches, triggers list is empty and scores are unchanged."""
    item = make_item(dollars_amount=100, is_consent=False)
    facts = make_facts()
    ai = make_ai(significance_score=5, consent_placement_score=5)
    cur = mock_cursor_no_override()

    result = apply_score_floors(cur, item, facts, ai, city_id=1)

    assert result.triggers == []
    assert result.final_significance == 5
    assert result.final_consent == 5


def test_score_overrides_multiple_triggers_highest_floor_wins():
    """When multiple significance floors apply, the highest bound determines the final score.

    red_plus_10m (floor=9) fires first, raising sig to 9.
    red_1m (floor=7) also matches the predicate, but since 7 < 9 (current),
    it does NOT fire as a separate trigger — the score is already above it.
    The final significance is 9.
    """
    item = make_item(dollars_amount=15_000_000)
    facts = make_facts()
    ai = make_ai(significance_score=3)
    cur = mock_cursor_no_override()

    result = apply_score_floors(cur, item, facts, ai, city_id=1)

    assert result.final_significance == 9  # red_plus_10m wins
    fired_names = [t['trigger'] for t in result.triggers if t['field'] == 'significance']
    assert 'red_plus_10m' in fired_names
    # red_1m predicate matches but its bound (7) is below the current score (9),
    # so it does not appear as a separate fired trigger
    assert 'red_1m' not in fired_names


def test_score_overrides_multiple_consent_ceilings_lowest_wins():
    """When multiple consent ceilings fire, the lowest bound wins."""
    # settlement_consent (ceiling=1) and sole_source_consent (ceiling=2) both fire
    item = make_item(is_consent=True)
    facts = make_facts(action_type='settlement', procurement_method='sole_source')
    ai = make_ai(significance_score=6, consent_placement_score=8)
    cur = mock_cursor_no_override()

    result = apply_score_floors(cur, item, facts, ai, city_id=1)

    assert result.final_consent == 1  # settlement_consent wins
    fired_names = [t['trigger'] for t in result.triggers if t['field'] == 'consent_placement']
    assert 'settlement_consent' in fired_names


def test_significance_is_monotonically_non_decreasing():
    """Significance score is never lowered by apply_score_floors."""
    item = make_item(dollars_amount=500_000)  # orange tier, but no matching triggers beyond sig floor
    facts = make_facts()
    # Start with a very high AI score — no floor should lower it
    ai = make_ai(significance_score=10, consent_placement_score=3)
    cur = mock_cursor_no_override()

    result = apply_score_floors(cur, item, facts, ai, city_id=1)

    assert result.final_significance == 10


def test_consent_is_monotonically_non_increasing():
    """Consent placement score is never raised by apply_score_floors."""
    item = make_item(is_consent=True, dollars_amount=2_000_000)
    facts = make_facts()
    # Start with a very low consent score — no ceiling should raise it
    ai = make_ai(significance_score=7, consent_placement_score=0)
    cur = mock_cursor_no_override()

    result = apply_score_floors(cur, item, facts, ai, city_id=1)

    assert result.final_consent == 0


# ---------------------------------------------------------------------------
# Override pathway — real DB tests
# ---------------------------------------------------------------------------

class TestOverridePathway:
    """Tests that _resolve_threshold reads live rows from city_score_floor_overrides.

    Uses a real DB cursor with cleanup to avoid test pollution.
    """

    CITY_ID = 1  # Birmingham
    TRIGGER = 'red_1m_test_override'  # unique name, won't clash with production data

    def _cleanup(self, cur):
        cur.execute(
            "DELETE FROM city_score_floor_overrides WHERE city_id = %s AND trigger_name = %s",
            (self.CITY_ID, self.TRIGGER),
        )

    def test_no_override_row_returns_defaults(self):
        """When no row exists, _resolve_threshold returns the supplied defaults."""
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                self._cleanup(cur)  # ensure clean state
                threshold, bound = _resolve_threshold(
                    cur, self.CITY_ID, self.TRIGGER, None, 7
                )
        assert threshold is None
        assert bound == 7

    def test_inserted_override_row_used(self):
        """When a row exists with override_min_score, _resolve_threshold returns it."""
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                self._cleanup(cur)
                cur.execute(
                    """
                    INSERT INTO city_score_floor_overrides
                        (city_id, trigger_name, override_threshold_amount, override_min_score, reason, added_by)
                    VALUES (%s, %s, NULL, %s, 'test override', 'test_suite')
                    """,
                    (self.CITY_ID, self.TRIGGER, 9),
                )
                threshold, bound = _resolve_threshold(
                    cur, self.CITY_ID, self.TRIGGER, None, 7
                )
        assert bound == 9  # override wins

    def test_override_applied_end_to_end_via_apply_score_floors(self):
        """apply_score_floors respects the override for the matching trigger."""
        from docket.db import db

        # We'll override 'red_1m' so that city 1 gets floor=10 instead of 7
        override_trigger = 'red_1m'
        with db() as conn:
            with conn.cursor() as cur:
                # Delete any existing override for this trigger on city 1
                cur.execute(
                    "DELETE FROM city_score_floor_overrides WHERE city_id = %s AND trigger_name = %s",
                    (self.CITY_ID, override_trigger),
                )
                cur.execute(
                    """
                    INSERT INTO city_score_floor_overrides
                        (city_id, trigger_name, override_threshold_amount, override_min_score, reason, added_by)
                    VALUES (%s, %s, NULL, 10, 'test: red_1m override to 10', 'test_suite')
                    """,
                    (self.CITY_ID, override_trigger),
                )

                item = make_item(dollars_amount=1_000_000)
                facts = make_facts()
                ai = make_ai(significance_score=3, consent_placement_score=8)

                result = apply_score_floors(cur, item, facts, ai, city_id=self.CITY_ID)

                # Clean up before asserting (so failure doesn't leave test data)
                cur.execute(
                    "DELETE FROM city_score_floor_overrides WHERE city_id = %s AND trigger_name = %s",
                    (self.CITY_ID, override_trigger),
                )

        # The override (10) should beat the default floor (7)
        assert result.final_significance == 10
        fired_triggers = {t['trigger']: t for t in result.triggers}
        assert 'red_1m' in fired_triggers
        assert fired_triggers['red_1m']['post'] == 10
