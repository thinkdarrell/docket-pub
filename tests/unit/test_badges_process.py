"""Tests for process badges module (docket.ai.badges_process).

Coverage:
- compute_on_write_process_badges: unit tests (no DB) for the 4 fast badges
- SQL integration tests (real DB) for each of the 6 SQL constants / 7 badges

DB pattern mirrors tests/unit/test_floors.py:TestOverridePathway.
"""
from __future__ import annotations

import pytest

from docket.ai.badges_process import (
    AMENDS_PRIOR_CONTRACT_SQL,
    EMERGENCY_ACTION_SQL,
    HIDDEN_ON_CONSENT_SQL,
    LEGAL_SETTLEMENT_SQL,
    PROCESS_BADGE_QUERIES,
    SOLE_SOURCE_SQL,
    SPLIT_VOTE_AND_CONTESTED_SQL,
    compute_on_write_process_badges,
)
from docket.ai.extraction_schema import NextSteps, StructuredFacts
from docket.ai.floors import ScoreOverrides


# ===========================================================================
# Helpers / fixtures
# ===========================================================================

def make_item(**kw):
    """Duck-typed agenda item for on-write helper tests."""
    defaults = {'is_consent': False, 'title': 'Standard agenda item'}
    defaults.update(kw)
    return type('Item', (), defaults)()


def make_facts(**kw) -> StructuredFacts:
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


def make_scores(final_consent=8, triggers=None) -> ScoreOverrides:
    return ScoreOverrides(
        original_ai_significance=5,
        final_significance=5,
        original_ai_consent=final_consent,
        final_consent=final_consent,
        triggers=triggers or [],
    )


# ===========================================================================
# compute_on_write_process_badges — unit tests (no DB)
# ===========================================================================

class TestHiddenOnConsent:
    """hidden_on_consent badge logic."""

    def test_fires_when_consent_and_high_confidence(self):
        item = make_item(is_consent=True)
        facts = make_facts()
        scores = make_scores(final_consent=2)
        badges = compute_on_write_process_badges(item, facts, scores, 'high')
        slugs = [s for s, _ in badges]
        assert 'hidden_on_consent' in slugs

    def test_fires_when_consent_and_medium_confidence(self):
        item = make_item(is_consent=True)
        facts = make_facts()
        scores = make_scores(final_consent=3)
        badges = compute_on_write_process_badges(item, facts, scores, 'medium')
        slugs = [s for s, _ in badges]
        assert 'hidden_on_consent' in slugs

    def test_fires_when_floor_fired_even_if_low_confidence(self):
        item = make_item(is_consent=True)
        facts = make_facts()
        trigger = {'field': 'consent_placement', 'trigger': 'red_consent', 'pre': 8, 'post': 2}
        scores = make_scores(final_consent=2, triggers=[trigger])
        badges = compute_on_write_process_badges(item, facts, scores, 'low')
        slugs = [s for s, _ in badges]
        assert 'hidden_on_consent' in slugs

    def test_does_not_fire_when_low_confidence_and_no_floor(self):
        item = make_item(is_consent=True)
        facts = make_facts()
        scores = make_scores(final_consent=2, triggers=[])
        badges = compute_on_write_process_badges(item, facts, scores, 'low')
        slugs = [s for s, _ in badges]
        assert 'hidden_on_consent' not in slugs

    def test_does_not_fire_when_not_on_consent(self):
        item = make_item(is_consent=False)
        facts = make_facts()
        scores = make_scores(final_consent=1)
        badges = compute_on_write_process_badges(item, facts, scores, 'high')
        slugs = [s for s, _ in badges]
        assert 'hidden_on_consent' not in slugs

    def test_does_not_fire_when_consent_score_above_3(self):
        item = make_item(is_consent=True)
        facts = make_facts()
        scores = make_scores(final_consent=4)
        badges = compute_on_write_process_badges(item, facts, scores, 'high')
        slugs = [s for s, _ in badges]
        assert 'hidden_on_consent' not in slugs

    def test_does_not_fire_when_consent_score_is_none(self):
        item = make_item(is_consent=True)
        facts = make_facts()
        scores = make_scores(final_consent=None)
        badges = compute_on_write_process_badges(item, facts, scores, 'high')
        slugs = [s for s, _ in badges]
        assert 'hidden_on_consent' not in slugs

    def test_confidence_1_0_when_fires(self):
        item = make_item(is_consent=True)
        facts = make_facts()
        scores = make_scores(final_consent=2)
        badges = compute_on_write_process_badges(item, facts, scores, 'high')
        match = {s: c for s, c in badges}
        assert match['hidden_on_consent'] == 1.0


class TestSoleSource:
    """sole_source badge logic."""

    def test_fires_for_sole_source(self):
        item = make_item()
        facts = make_facts(procurement_method='sole_source')
        scores = make_scores()
        badges = compute_on_write_process_badges(item, facts, scores, 'high')
        slugs = [s for s, _ in badges]
        assert 'sole_source' in slugs

    def test_fires_for_no_bid(self):
        item = make_item()
        facts = make_facts(procurement_method='no_bid')
        scores = make_scores()
        badges = compute_on_write_process_badges(item, facts, scores, 'high')
        slugs = [s for s, _ in badges]
        assert 'sole_source' in slugs

    def test_does_not_fire_for_competitive(self):
        item = make_item()
        facts = make_facts(procurement_method='competitive')
        scores = make_scores()
        badges = compute_on_write_process_badges(item, facts, scores, 'high')
        slugs = [s for s, _ in badges]
        assert 'sole_source' not in slugs


class TestLegalSettlement:
    """legal_settlement badge logic."""

    def test_fires_for_settlement(self):
        item = make_item()
        facts = make_facts(action_type='settlement')
        scores = make_scores()
        badges = compute_on_write_process_badges(item, facts, scores, 'high')
        slugs = [s for s, _ in badges]
        assert 'legal_settlement' in slugs

    def test_does_not_fire_for_contract_award(self):
        item = make_item()
        facts = make_facts(action_type='contract_award')
        scores = make_scores()
        badges = compute_on_write_process_badges(item, facts, scores, 'high')
        slugs = [s for s, _ in badges]
        assert 'legal_settlement' not in slugs


class TestEmergencyAction:
    """emergency_action badge logic."""

    def test_fires_for_emergency_procurement_action_type(self):
        item = make_item()
        facts = make_facts(action_type='emergency_procurement')
        scores = make_scores()
        badges = compute_on_write_process_badges(item, facts, scores, 'high')
        slugs = [s for s, _ in badges]
        assert 'emergency_action' in slugs

    def test_fires_for_emergency_procurement_method(self):
        item = make_item()
        facts = make_facts(procurement_method='emergency')
        scores = make_scores()
        badges = compute_on_write_process_badges(item, facts, scores, 'high')
        slugs = [s for s, _ in badges]
        assert 'emergency_action' in slugs

    def test_fires_when_title_matches_emergency_keyword(self):
        item = make_item(title='Emergency repair of water main')
        facts = make_facts()
        scores = make_scores()
        badges = compute_on_write_process_badges(item, facts, scores, 'high')
        slugs = [s for s, _ in badges]
        assert 'emergency_action' in slugs

    def test_fires_for_exigent_in_title(self):
        item = make_item(title='Exigent circumstances — special procurement')
        facts = make_facts()
        scores = make_scores()
        badges = compute_on_write_process_badges(item, facts, scores, 'low')
        slugs = [s for s, _ in badges]
        assert 'emergency_action' in slugs

    def test_fires_for_expedited_in_title(self):
        item = make_item(title='Expedited contract for road clearing')
        facts = make_facts()
        scores = make_scores()
        badges = compute_on_write_process_badges(item, facts, scores, None)
        slugs = [s for s, _ in badges]
        assert 'emergency_action' in slugs

    def test_does_not_fire_on_benign_title(self):
        item = make_item(title='Ratifying personnel decisions for Q1 2025')
        facts = make_facts()
        scores = make_scores()
        badges = compute_on_write_process_badges(item, facts, scores, 'high')
        slugs = [s for s, _ in badges]
        assert 'emergency_action' not in slugs

    def test_case_insensitive_keyword_match(self):
        item = make_item(title='EMERGENCY water main break repair')
        facts = make_facts()
        scores = make_scores()
        badges = compute_on_write_process_badges(item, facts, scores, 'low')
        slugs = [s for s, _ in badges]
        assert 'emergency_action' in slugs


class TestProcessBadgeQueriesList:
    """Sanity checks on the PROCESS_BADGE_QUERIES list."""

    def test_has_six_entries(self):
        assert len(PROCESS_BADGE_QUERIES) == 6

    def test_all_strings(self):
        for q in PROCESS_BADGE_QUERIES:
            assert isinstance(q, str)
            assert len(q) > 10

    def test_all_inserts_set_status_explicitly(self):
        """Refactor #2 retro [MEDIUM #1]: every badge INSERT must set
        ``status`` explicitly rather than relying on the DB default.

        Process badges are deterministic and always land at
        ``status='applied'`` — but expressing that as a literal in the
        SQL keeps the writer SSOT durable against future changes to
        the table default. Defended at the call-site level here, and
        echoed by ``decide_status_and_confidence`` for the policy-badge
        path (which has a real branching decision)."""
        import re
        for q in PROCESS_BADGE_QUERIES:
            # Every constant inserts into agenda_item_badges; the column
            # list must include 'status' (along with the existing five).
            col_list_match = re.search(
                r"INSERT INTO agenda_item_badges\s*\(([^)]+)\)",
                q,
                re.IGNORECASE | re.DOTALL,
            )
            assert col_list_match, (
                "Could not parse column list from SQL constant — "
                "tests/unit/test_badges_process.py assumed a single-INSERT shape"
            )
            cols = [c.strip() for c in col_list_match.group(1).split(",")]
            assert "status" in cols, (
                f"INSERT column list missing 'status' — relies on DB default. "
                f"Cols: {cols}"
            )
            # The value list must contain the literal 'applied' so the
            # writer is unambiguous even if the DB default ever moves.
            assert "'applied'" in q, (
                "SQL constant inserts process badges but does not set "
                "status='applied' explicitly"
            )


# ===========================================================================
# SQL integration tests — real DB
# ===========================================================================

# We use a test municipality slug that won't clash with production data.
TEST_CITY_SLUG = 'test_badges_process_city'


def _setup_city(cur):
    """Insert or reuse test municipality. Returns city_id."""
    cur.execute(
        """
        INSERT INTO municipalities (slug, name, state, county, adapter_class, adapter_config)
        VALUES (%s, 'Test Badges City', 'AL', 'Test', 'TestAdapter', '{}')
        ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
        RETURNING id
        """,
        (TEST_CITY_SLUG,),
    )
    return cur.fetchone()[0]


def _setup_meeting(cur, city_id, *, external_id='test-badges-mtg-1',
                   meeting_date='2025-01-15'):
    """Insert a test meeting. Returns meeting_id."""
    cur.execute(
        """
        INSERT INTO meetings (municipality_id, external_id, title, meeting_date)
        VALUES (%s, %s, 'Test Badges Meeting', %s)
        ON CONFLICT (municipality_id, external_id) DO UPDATE SET title = EXCLUDED.title
        RETURNING id
        """,
        (city_id, external_id, meeting_date),
    )
    return cur.fetchone()[0]


def _setup_agenda_item(cur, meeting_id, *, item_number='1', title='Test item',
                       is_consent=False, processing_status='completed',
                       extracted_facts=None, score_overrides=None,
                       ai_confidence=None, consent_placement_score=None,
                       dollars_amount=None):
    """Insert a test agenda item. Returns agenda_item_id."""
    import json
    cur.execute(
        """
        INSERT INTO agenda_items
            (meeting_id, item_number, title, is_consent, processing_status,
             extracted_facts, score_overrides, ai_confidence,
             consent_placement_score, dollars_amount)
        VALUES (%s, %s, %s, %s, %s::processing_status_enum,
                %s::jsonb, %s::jsonb, %s, %s, %s)
        RETURNING id
        """,
        (
            meeting_id, item_number, title, is_consent, processing_status,
            json.dumps(extracted_facts) if extracted_facts else None,
            json.dumps(score_overrides) if score_overrides else None,
            ai_confidence,
            consent_placement_score,
            dollars_amount,
        ),
    )
    return cur.fetchone()[0]


def _badge_exists(cur, agenda_item_id, badge_slug):
    """Return True if the badge row exists."""
    cur.execute(
        "SELECT 1 FROM agenda_item_badges WHERE agenda_item_id = %s AND badge_slug = %s",
        (agenda_item_id, badge_slug),
    )
    return cur.fetchone() is not None


def _cleanup(cur, city_id):
    """Remove all test data in FK dependency order."""
    # Get all meeting ids for this city
    cur.execute("SELECT id FROM meetings WHERE municipality_id = %s", (city_id,))
    meeting_ids = [r[0] for r in cur.fetchall()]
    if meeting_ids:
        cur.execute(
            "SELECT id FROM agenda_items WHERE meeting_id = ANY(%s)",
            (meeting_ids,),
        )
        item_ids = [r[0] for r in cur.fetchall()]
        if item_ids:
            cur.execute(
                "DELETE FROM agenda_item_badges WHERE agenda_item_id = ANY(%s)",
                (item_ids,),
            )
            # vote_agenda_items → member_votes → votes
            cur.execute(
                "SELECT id FROM votes WHERE meeting_id = ANY(%s)", (meeting_ids,)
            )
            vote_ids = [r[0] for r in cur.fetchall()]
            if vote_ids:
                cur.execute(
                    "DELETE FROM vote_agenda_items WHERE vote_id = ANY(%s)",
                    (vote_ids,),
                )
                cur.execute(
                    "DELETE FROM member_votes WHERE vote_id = ANY(%s)", (vote_ids,)
                )
                cur.execute(
                    "DELETE FROM votes WHERE id = ANY(%s)", (vote_ids,)
                )
            cur.execute(
                "DELETE FROM agenda_items WHERE id = ANY(%s)", (item_ids,)
            )
    cur.execute("DELETE FROM meetings WHERE municipality_id = %s", (city_id,))
    cur.execute("DELETE FROM municipalities WHERE slug = %s", (TEST_CITY_SLUG,))


class TestHiddenOnConsentSQL:
    """SQL integration tests for HIDDEN_ON_CONSENT_SQL."""

    def test_fires_when_medium_confidence(self):
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_id = _setup_meeting(cur, city_id)
                    item_id = _setup_agenda_item(
                        cur, mtg_id,
                        is_consent=True,
                        consent_placement_score=2,
                        ai_confidence='medium',
                        processing_status='completed',
                    )
                    cur.execute(HIDDEN_ON_CONSENT_SQL)
                    assert _badge_exists(cur, item_id, 'hidden_on_consent')
                finally:
                    _cleanup(cur, city_id)

    def test_fires_when_floor_fired_and_low_confidence(self):
        import json
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_id = _setup_meeting(cur, city_id, external_id='test-badges-mtg-floor')
                    score_overrides = {
                        'triggers': [{'field': 'consent_placement', 'trigger': 'red_consent'}]
                    }
                    item_id = _setup_agenda_item(
                        cur, mtg_id,
                        is_consent=True,
                        consent_placement_score=1,
                        ai_confidence='low',
                        score_overrides=score_overrides,
                        processing_status='completed',
                    )
                    cur.execute(HIDDEN_ON_CONSENT_SQL)
                    assert _badge_exists(cur, item_id, 'hidden_on_consent')
                finally:
                    _cleanup(cur, city_id)

    def test_does_not_fire_when_low_confidence_no_floor(self):
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_id = _setup_meeting(cur, city_id, external_id='test-badges-mtg-lowconf')
                    item_id = _setup_agenda_item(
                        cur, mtg_id,
                        is_consent=True,
                        consent_placement_score=2,
                        ai_confidence='low',
                        score_overrides={'triggers': []},
                        processing_status='completed',
                    )
                    cur.execute(HIDDEN_ON_CONSENT_SQL)
                    assert not _badge_exists(cur, item_id, 'hidden_on_consent')
                finally:
                    _cleanup(cur, city_id)

    def test_does_not_fire_when_score_above_3(self):
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_id = _setup_meeting(cur, city_id, external_id='test-badges-mtg-score4')
                    item_id = _setup_agenda_item(
                        cur, mtg_id,
                        is_consent=True,
                        consent_placement_score=4,
                        ai_confidence='high',
                        processing_status='completed',
                    )
                    cur.execute(HIDDEN_ON_CONSENT_SQL)
                    assert not _badge_exists(cur, item_id, 'hidden_on_consent')
                finally:
                    _cleanup(cur, city_id)

    def test_does_not_fire_when_not_completed(self):
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_id = _setup_meeting(cur, city_id, external_id='test-badges-mtg-pending')
                    item_id = _setup_agenda_item(
                        cur, mtg_id,
                        is_consent=True,
                        consent_placement_score=1,
                        ai_confidence='high',
                        processing_status='pending',
                    )
                    cur.execute(HIDDEN_ON_CONSENT_SQL)
                    assert not _badge_exists(cur, item_id, 'hidden_on_consent')
                finally:
                    _cleanup(cur, city_id)

    def test_idempotent(self):
        """Running twice doesn't insert duplicate rows."""
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_id = _setup_meeting(cur, city_id, external_id='test-badges-mtg-idem')
                    item_id = _setup_agenda_item(
                        cur, mtg_id,
                        is_consent=True,
                        consent_placement_score=2,
                        ai_confidence='high',
                        processing_status='completed',
                    )
                    cur.execute(HIDDEN_ON_CONSENT_SQL)
                    cur.execute(HIDDEN_ON_CONSENT_SQL)
                    cur.execute(
                        "SELECT COUNT(*) FROM agenda_item_badges WHERE agenda_item_id = %s AND badge_slug = 'hidden_on_consent'",
                        (item_id,),
                    )
                    assert cur.fetchone()[0] == 1
                finally:
                    _cleanup(cur, city_id)


class TestSoleSourceSQL:
    """SQL integration tests for SOLE_SOURCE_SQL."""

    def test_fires_for_sole_source(self):
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_id = _setup_meeting(cur, city_id, external_id='test-ss-mtg-1')
                    item_id = _setup_agenda_item(
                        cur, mtg_id,
                        extracted_facts={'procurement_method': 'sole_source', 'action_type': 'contract_award'},
                        processing_status='completed',
                    )
                    cur.execute(SOLE_SOURCE_SQL)
                    assert _badge_exists(cur, item_id, 'sole_source')
                finally:
                    _cleanup(cur, city_id)

    def test_fires_for_no_bid(self):
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_id = _setup_meeting(cur, city_id, external_id='test-ss-mtg-2')
                    item_id = _setup_agenda_item(
                        cur, mtg_id,
                        extracted_facts={'procurement_method': 'no_bid', 'action_type': 'contract_award'},
                        processing_status='completed',
                    )
                    cur.execute(SOLE_SOURCE_SQL)
                    assert _badge_exists(cur, item_id, 'sole_source')
                finally:
                    _cleanup(cur, city_id)

    def test_does_not_fire_for_competitive(self):
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_id = _setup_meeting(cur, city_id, external_id='test-ss-mtg-3')
                    item_id = _setup_agenda_item(
                        cur, mtg_id,
                        extracted_facts={'procurement_method': 'competitive', 'action_type': 'contract_award'},
                        processing_status='completed',
                    )
                    cur.execute(SOLE_SOURCE_SQL)
                    assert not _badge_exists(cur, item_id, 'sole_source')
                finally:
                    _cleanup(cur, city_id)


class TestLegalSettlementSQL:
    """SQL integration tests for LEGAL_SETTLEMENT_SQL."""

    def test_fires_for_settlement(self):
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_id = _setup_meeting(cur, city_id, external_id='test-ls-mtg-1')
                    item_id = _setup_agenda_item(
                        cur, mtg_id,
                        extracted_facts={'action_type': 'settlement', 'procurement_method': 'competitive'},
                        processing_status='completed',
                    )
                    cur.execute(LEGAL_SETTLEMENT_SQL)
                    assert _badge_exists(cur, item_id, 'legal_settlement')
                finally:
                    _cleanup(cur, city_id)

    def test_does_not_fire_for_contract_award(self):
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_id = _setup_meeting(cur, city_id, external_id='test-ls-mtg-2')
                    item_id = _setup_agenda_item(
                        cur, mtg_id,
                        extracted_facts={'action_type': 'contract_award', 'procurement_method': 'competitive'},
                        processing_status='completed',
                    )
                    cur.execute(LEGAL_SETTLEMENT_SQL)
                    assert not _badge_exists(cur, item_id, 'legal_settlement')
                finally:
                    _cleanup(cur, city_id)


class TestEmergencyActionSQL:
    """SQL integration tests for EMERGENCY_ACTION_SQL."""

    def test_fires_for_emergency_action_type(self):
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_id = _setup_meeting(cur, city_id, external_id='test-ea-mtg-1')
                    item_id = _setup_agenda_item(
                        cur, mtg_id,
                        extracted_facts={'action_type': 'emergency_procurement', 'procurement_method': 'competitive'},
                        processing_status='completed',
                    )
                    cur.execute(EMERGENCY_ACTION_SQL)
                    assert _badge_exists(cur, item_id, 'emergency_action')
                finally:
                    _cleanup(cur, city_id)

    def test_fires_for_emergency_procurement_method(self):
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_id = _setup_meeting(cur, city_id, external_id='test-ea-mtg-2')
                    item_id = _setup_agenda_item(
                        cur, mtg_id,
                        extracted_facts={'action_type': 'contract_award', 'procurement_method': 'emergency'},
                        processing_status='completed',
                    )
                    cur.execute(EMERGENCY_ACTION_SQL)
                    assert _badge_exists(cur, item_id, 'emergency_action')
                finally:
                    _cleanup(cur, city_id)

    def test_fires_for_emergency_keyword_in_title(self):
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_id = _setup_meeting(cur, city_id, external_id='test-ea-mtg-3')
                    item_id = _setup_agenda_item(
                        cur, mtg_id,
                        title='Emergency repair of water main break on 1st Ave',
                        extracted_facts={'action_type': 'contract_award', 'procurement_method': 'competitive'},
                        processing_status='completed',
                    )
                    cur.execute(EMERGENCY_ACTION_SQL)
                    assert _badge_exists(cur, item_id, 'emergency_action')
                finally:
                    _cleanup(cur, city_id)

    def test_does_not_fire_for_benign_title(self):
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_id = _setup_meeting(cur, city_id, external_id='test-ea-mtg-4')
                    item_id = _setup_agenda_item(
                        cur, mtg_id,
                        title='Ratifying personnel decisions for Q1 2025',
                        extracted_facts={'action_type': 'contract_award', 'procurement_method': 'competitive'},
                        processing_status='completed',
                    )
                    cur.execute(EMERGENCY_ACTION_SQL)
                    assert not _badge_exists(cur, item_id, 'emergency_action')
                finally:
                    _cleanup(cur, city_id)


class TestSplitVoteAndContestedSQL:
    """SQL integration tests for SPLIT_VOTE_AND_CONTESTED_SQL.

    Inserts real vote + member_vote + vote_agenda_items rows.
    Validates both split_vote and contested badge thresholds.
    """

    def _setup_vote_with_members(self, cur, meeting_id, agenda_item_id,
                                  yeas, nays, abstains):
        """Insert a vote + member_votes + vote_agenda_items row."""
        cur.execute(
            """
            INSERT INTO votes (meeting_id, result, source, confidence)
            VALUES (%s, 'passed', 'minutes_text', 'high')
            RETURNING id
            """,
            (meeting_id,),
        )
        vote_id = cur.fetchone()[0]

        position_counter = 1
        for _ in range(yeas):
            cur.execute(
                "INSERT INTO member_votes (vote_id, member_name, position) VALUES (%s, %s, 'yea')",
                (vote_id, f'Member Yea {position_counter}'),
            )
            position_counter += 1
        for _ in range(nays):
            cur.execute(
                "INSERT INTO member_votes (vote_id, member_name, position) VALUES (%s, %s, 'nay')",
                (vote_id, f'Member Nay {position_counter}'),
            )
            position_counter += 1
        for _ in range(abstains):
            cur.execute(
                "INSERT INTO member_votes (vote_id, member_name, position) VALUES (%s, %s, 'abstain')",
                (vote_id, f'Member Abstain {position_counter}'),
            )
            position_counter += 1

        cur.execute(
            """
            INSERT INTO vote_agenda_items
                (vote_id, agenda_item_id, association_type, match_confidence, is_active)
            VALUES (%s, %s, 'explicit', 1.0, TRUE)
            """,
            (vote_id, agenda_item_id),
        )
        return vote_id

    def test_split_vote_fires_for_1_dissenter(self):
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_id = _setup_meeting(cur, city_id, external_id='test-sv-mtg-1')
                    item_id = _setup_agenda_item(cur, mtg_id, title='8-1 vote item')
                    self._setup_vote_with_members(cur, mtg_id, item_id,
                                                   yeas=8, nays=1, abstains=0)
                    cur.execute(SPLIT_VOTE_AND_CONTESTED_SQL)
                    assert _badge_exists(cur, item_id, 'split_vote')
                    assert not _badge_exists(cur, item_id, 'contested')  # only 1 dissenter
                finally:
                    _cleanup(cur, city_id)

    def test_both_badges_fire_for_2_dissenters_above_20pct(self):
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_id = _setup_meeting(cur, city_id, external_id='test-sv-mtg-2')
                    item_id = _setup_agenda_item(cur, mtg_id, title='7-2 vote item')
                    # 7-2 → 9 voting, 2 dissent = 22% > 20%
                    self._setup_vote_with_members(cur, mtg_id, item_id,
                                                   yeas=7, nays=2, abstains=0)
                    cur.execute(SPLIT_VOTE_AND_CONTESTED_SQL)
                    assert _badge_exists(cur, item_id, 'split_vote')
                    assert _badge_exists(cur, item_id, 'contested')
                finally:
                    _cleanup(cur, city_id)

    def test_contested_does_not_fire_below_20pct(self):
        """Large council: 9-2 (11 members) → 18% dissent → split fires, contested doesn't."""
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_id = _setup_meeting(cur, city_id, external_id='test-sv-mtg-3')
                    item_id = _setup_agenda_item(cur, mtg_id, title='9-2 Homewood vote')
                    # 9 yeas, 2 nays = 11 voting, 18.2% < 20%
                    self._setup_vote_with_members(cur, mtg_id, item_id,
                                                   yeas=9, nays=2, abstains=0)
                    cur.execute(SPLIT_VOTE_AND_CONTESTED_SQL)
                    assert _badge_exists(cur, item_id, 'split_vote')
                    assert not _badge_exists(cur, item_id, 'contested')
                finally:
                    _cleanup(cur, city_id)

    def test_neither_fires_for_unanimous(self):
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_id = _setup_meeting(cur, city_id, external_id='test-sv-mtg-4')
                    item_id = _setup_agenda_item(cur, mtg_id, title='9-0 unanimous')
                    self._setup_vote_with_members(cur, mtg_id, item_id,
                                                   yeas=9, nays=0, abstains=0)
                    cur.execute(SPLIT_VOTE_AND_CONTESTED_SQL)
                    assert not _badge_exists(cur, item_id, 'split_vote')
                    assert not _badge_exists(cur, item_id, 'contested')
                finally:
                    _cleanup(cur, city_id)

    def test_abstain_counts_as_dissent(self):
        """5 yes, 2 abstain = 7 voting, 2 dissent = 28.6% → both badges."""
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_id = _setup_meeting(cur, city_id, external_id='test-sv-mtg-5')
                    item_id = _setup_agenda_item(cur, mtg_id, title='5 yes 2 abstain')
                    self._setup_vote_with_members(cur, mtg_id, item_id,
                                                   yeas=5, nays=0, abstains=2)
                    cur.execute(SPLIT_VOTE_AND_CONTESTED_SQL)
                    assert _badge_exists(cur, item_id, 'split_vote')
                    assert _badge_exists(cur, item_id, 'contested')
                finally:
                    _cleanup(cur, city_id)

    def test_only_active_links_counted(self):
        """Inactive vote_agenda_items rows should not trigger badges."""
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_id = _setup_meeting(cur, city_id, external_id='test-sv-mtg-6')
                    item_id = _setup_agenda_item(cur, mtg_id, title='Inactive link item')
                    # Set up a dissenting vote but mark the link is_active=FALSE
                    cur.execute(
                        "INSERT INTO votes (meeting_id, result, source, confidence) VALUES (%s, 'passed', 'minutes_text', 'high') RETURNING id",
                        (mtg_id,),
                    )
                    vote_id = cur.fetchone()[0]
                    cur.execute(
                        "INSERT INTO member_votes (vote_id, member_name, position) VALUES (%s, 'Member A', 'yea'), (%s, 'Member B', 'nay')",
                        (vote_id, vote_id),
                    )
                    cur.execute(
                        "INSERT INTO vote_agenda_items (vote_id, agenda_item_id, association_type, match_confidence, is_active) VALUES (%s, %s, 'explicit', 1.0, FALSE)",
                        (vote_id, item_id),
                    )
                    cur.execute(SPLIT_VOTE_AND_CONTESTED_SQL)
                    assert not _badge_exists(cur, item_id, 'split_vote')
                finally:
                    _cleanup(cur, city_id)


class TestAmendsPriorContractSQL:
    """SQL integration tests for AMENDS_PRIOR_CONTRACT_SQL."""

    def test_fires_when_counterparty_matches_prior_award(self):
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    # Prior meeting (earlier date)
                    mtg_prior_id = _setup_meeting(
                        cur, city_id,
                        external_id='test-apc-mtg-prior',
                        meeting_date='2024-06-01',
                    )
                    # Prior contract award
                    _setup_agenda_item(
                        cur, mtg_prior_id,
                        item_number='P1',
                        extracted_facts={
                            'action_type': 'contract_award',
                            'counterparty': 'Acme Construction LLC',
                        },
                        dollars_amount=500000,
                        processing_status='completed',
                    )
                    # Later meeting
                    mtg_later_id = _setup_meeting(
                        cur, city_id,
                        external_id='test-apc-mtg-later',
                        meeting_date='2025-01-15',
                    )
                    # Amendment item with same counterparty
                    amend_item_id = _setup_agenda_item(
                        cur, mtg_later_id,
                        item_number='A1',
                        title='Amendment to Acme Construction contract',
                        extracted_facts={
                            'action_type': 'contract_amendment',
                            'counterparty': 'Acme Construction LLC',
                        },
                        processing_status='completed',
                    )
                    cur.execute(AMENDS_PRIOR_CONTRACT_SQL)
                    assert _badge_exists(cur, amend_item_id, 'amends_prior_contract')
                finally:
                    _cleanup(cur, city_id)

    def test_does_not_fire_when_noise_filter_matches(self):
        """Items with 'monthly invoice' in title/description are excluded."""
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_prior_id = _setup_meeting(
                        cur, city_id,
                        external_id='test-apc-noise-prior',
                        meeting_date='2024-03-01',
                    )
                    _setup_agenda_item(
                        cur, mtg_prior_id,
                        item_number='N1',
                        extracted_facts={
                            'action_type': 'contract_award',
                            'counterparty': 'Utility Corp',
                        },
                        dollars_amount=200000,
                        processing_status='completed',
                    )
                    mtg_later_id = _setup_meeting(
                        cur, city_id,
                        external_id='test-apc-noise-later',
                        meeting_date='2025-02-01',
                    )
                    noise_item_id = _setup_agenda_item(
                        cur, mtg_later_id,
                        item_number='N2',
                        title='Monthly invoice payment for Utility Corp services',
                        extracted_facts={
                            'action_type': 'contract_amendment',
                            'counterparty': 'Utility Corp',
                        },
                        processing_status='completed',
                    )
                    cur.execute(AMENDS_PRIOR_CONTRACT_SQL)
                    assert not _badge_exists(cur, noise_item_id, 'amends_prior_contract')
                finally:
                    _cleanup(cur, city_id)

    def test_does_not_fire_for_different_counterparty(self):
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_prior_id = _setup_meeting(
                        cur, city_id,
                        external_id='test-apc-diff-prior',
                        meeting_date='2024-04-01',
                    )
                    _setup_agenda_item(
                        cur, mtg_prior_id,
                        item_number='D1',
                        extracted_facts={
                            'action_type': 'contract_award',
                            'counterparty': 'Big Corp Inc',
                        },
                        dollars_amount=300000,
                        processing_status='completed',
                    )
                    mtg_later_id = _setup_meeting(
                        cur, city_id,
                        external_id='test-apc-diff-later',
                        meeting_date='2025-03-01',
                    )
                    amend_item_id = _setup_agenda_item(
                        cur, mtg_later_id,
                        item_number='D2',
                        title='Amendment to Completely Different Vendor contract',
                        extracted_facts={
                            'action_type': 'contract_amendment',
                            'counterparty': 'Completely Different Vendor',
                        },
                        processing_status='completed',
                    )
                    cur.execute(AMENDS_PRIOR_CONTRACT_SQL)
                    assert not _badge_exists(cur, amend_item_id, 'amends_prior_contract')
                finally:
                    _cleanup(cur, city_id)

    def test_confidence_is_0_6(self):
        """amends_prior_contract uses confidence=0.6 (not 1.0)."""
        from docket.db import db
        with db() as conn:
            with conn.cursor() as cur:
                city_id = _setup_city(cur)
                try:
                    mtg_prior_id = _setup_meeting(
                        cur, city_id,
                        external_id='test-apc-conf-prior',
                        meeting_date='2024-05-01',
                    )
                    _setup_agenda_item(
                        cur, mtg_prior_id,
                        item_number='C1',
                        extracted_facts={
                            'action_type': 'contract_award',
                            'counterparty': 'Reliable Contractors',
                        },
                        dollars_amount=400000,
                        processing_status='completed',
                    )
                    mtg_later_id = _setup_meeting(
                        cur, city_id,
                        external_id='test-apc-conf-later',
                        meeting_date='2025-04-01',
                    )
                    amend_item_id = _setup_agenda_item(
                        cur, mtg_later_id,
                        item_number='C2',
                        title='Amendment to Reliable Contractors agreement',
                        extracted_facts={
                            'action_type': 'contract_amendment',
                            'counterparty': 'Reliable Contractors',
                        },
                        processing_status='completed',
                    )
                    cur.execute(AMENDS_PRIOR_CONTRACT_SQL)
                    cur.execute(
                        "SELECT confidence FROM agenda_item_badges WHERE agenda_item_id = %s AND badge_slug = 'amends_prior_contract'",
                        (amend_item_id,),
                    )
                    row = cur.fetchone()
                    assert row is not None
                    assert float(row[0]) == pytest.approx(0.6)
                finally:
                    _cleanup(cur, city_id)
