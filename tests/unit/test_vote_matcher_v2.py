"""Tier-by-tier tests for vote_matcher v2 changes.

Each test exercises one tier in isolation. Integration test for the full
flow lives at tests/integration/test_vote_matcher_v2_integration.py.
"""

from __future__ import annotations

from tests.fixtures.vote_matcher_v2 import (
    VOTE_1342_RAW_TEXT,
    VOTE_1342_MATCH_CONTEXT,
    AGENDA_ITEM_1256,
    DISTRACTOR_AGENDA_ITEMS,
)


def _make_vote(*, raw_text=VOTE_1342_RAW_TEXT, match_context=VOTE_1342_MATCH_CONTEXT,
               resolution_number=None):
    return {
        "id": 1342,
        "raw_text": raw_text,
        "match_context": match_context,
        "resolution_number": resolution_number,
    }


def test_keyword_tier_reads_raw_text_not_match_context():
    """The wrong-haystack regression: substance lives in raw_text, not match_context."""
    from docket.analysis.vote_matcher import _try_keyword_match

    vote = _make_vote()
    items = [AGENDA_ITEM_1256] + DISTRACTOR_AGENDA_ITEMS
    result = _try_keyword_match(vote, items)
    assert result is not None, "expected keyword tier to match item 1256 from raw_text"
    item_id, conf, method = result
    assert item_id == 1256
    assert method == "text_similarity"
    assert 0.5 <= conf <= 0.75


def test_keyword_tier_falls_back_to_match_context_when_raw_text_null():
    """Legacy rows without raw_text should still get the old behavior."""
    from docket.analysis.vote_matcher import _try_keyword_match

    # An older vote with strong substance in match_context (unrealistic for v1
    # rows, but shows the fallback logic works).
    vote = _make_vote(raw_text=None,
                      match_context="Shield Property Solutions $11,155.25 Quitclaim deed")
    items = [AGENDA_ITEM_1256]
    result = _try_keyword_match(vote, items)
    assert result is not None


def test_stop_words_filter_procedural_noise():
    """Vote with only procedural words should NOT match an item with the same
    procedural words but different substance."""
    from docket.analysis.vote_matcher import _try_keyword_match

    vote = _make_vote(
        raw_text=(
            "councilmember motion seconded ordinance resolution mayor "
            "ayes nays council presiding officer whereupon hereby"
        ),
        match_context="",
    )
    items = [{
        "id": 999,
        "item_number": "1",
        "title": "An Ordinance approving the council's resolution by the Mayor",
        "description": "",
    }]
    result = _try_keyword_match(vote, items)
    assert result is None, "procedural overlap alone should not produce a match"


def test_structured_fact_tier_matches_proper_noun_plus_dollar():
    """Vote 1342 baseline: proper noun + dollar match → conf 0.9."""
    from docket.analysis.vote_matcher import _try_structured_fact_match

    vote = _make_vote()
    items = [AGENDA_ITEM_1256] + DISTRACTOR_AGENDA_ITEMS
    result = _try_structured_fact_match(
        vote, items,
        council_surnames={"Gunn", "Smith", "Smitherman", "Williams", "Woods", "Tate", "Alexander"},
    )
    assert result is not None
    item_id, conf, method = result
    assert item_id == 1256
    assert method == "structured_fact"
    assert conf == 0.9


def test_structured_fact_tier_proper_noun_only_lower_confidence():
    """Item title without the dollar amount → conf 0.8."""
    from docket.analysis.vote_matcher import _try_structured_fact_match

    items = [{
        "id": 200,
        "item_number": "1",
        "title": "An Ordinance about Shield Property Solutions activities",
        "description": "",
    }]
    vote = _make_vote()  # raw_text contains both proper noun and dollar
    result = _try_structured_fact_match(vote, items, council_surnames=set())
    assert result is not None
    item_id, conf, method = result
    assert item_id == 200
    assert conf == 0.8


def test_structured_fact_tier_dollar_only_no_match():
    """Same dollar amount in two unrelated items must not match by dollar alone."""
    from docket.analysis.vote_matcher import _try_structured_fact_match

    items = [{
        "id": 300,
        "item_number": "1",
        "title": "A Resolution paying $11,155.25 to a totally unrelated vendor",
        "description": "",
    }]
    vote = _make_vote()
    result = _try_structured_fact_match(vote, items, council_surnames=set())
    assert result is None


def test_structured_fact_tier_tied_proper_nouns_no_match():
    """If two items share the proper noun, defer."""
    from docket.analysis.vote_matcher import _try_structured_fact_match

    items = [
        {"id": 401, "item_number": "1",
         "title": "Item about Shield Property Solutions",
         "description": ""},
        {"id": 402, "item_number": "2",
         "title": "Another Shield Property Solutions matter",
         "description": ""},
    ]
    vote = _make_vote()
    result = _try_structured_fact_match(vote, items, council_surnames=set())
    assert result is None


def test_rank_aware_keyword_rejects_close_runner_up():
    """Best 1.0 vs second 1.0 (exact tie with title-recall) → no match (margin gate)."""
    from docket.analysis.vote_matcher import _try_keyword_match

    vote = {
        "raw_text": "alpha beta gamma delta epsilon zeta eta theta iota kappa",
        "match_context": "",
    }
    items = [
        {"id": 1, "item_number": "1",
         "title": "alpha beta gamma delta",
         "description": ""},
        {"id": 2, "item_number": "2",
         "title": "alpha beta gamma kappa",
         "description": ""},
    ]
    result = _try_keyword_match(vote, items)
    assert result is None, "near-tie should not commit"


def test_rank_aware_keyword_accepts_clear_winner():
    """Best clearly beats second → match."""
    from docket.analysis.vote_matcher import _try_keyword_match

    vote = {
        "raw_text": "alpha beta gamma delta epsilon zeta eta theta",
        "match_context": "",
    }
    items = [
        {"id": 1, "item_number": "1",
         "title": "alpha beta gamma delta epsilon",
         "description": ""},
        {"id": 2, "item_number": "2",
         "title": "completely different unrelated text",
         "description": ""},
    ]
    result = _try_keyword_match(vote, items)
    assert result is not None
    item_id, _conf, _method = result
    assert item_id == 1


def test_rank_aware_keyword_single_candidate_falls_back_to_absolute_threshold():
    """Single-item meeting has no second-best; use today's 0.3 floor."""
    from docket.analysis.vote_matcher import _try_keyword_match

    vote = {
        "raw_text": "alpha beta gamma delta",
        "match_context": "",
    }
    items = [
        {"id": 1, "item_number": "1",
         "title": "alpha beta gamma",
         "description": ""},
    ]
    result = _try_keyword_match(vote, items)
    assert result is not None


def test_upsert_link_respects_manual_shield_after_v2_changes():
    """A vote_agenda_items row with is_manual=TRUE must not be overwritten
    even when one of the new tiers (structured-fact) would otherwise commit
    a different link."""
    from docket.analysis.vote_matcher import _upsert_link
    from docket.db import db_cursor

    # This test uses real DB but ephemeral fixture rows. Wrap in cleanup.
    MEETING_ID = 99500
    VOTE_ID = 995000
    ITEM_ID = 995100
    try:
        with db_cursor() as cur:
            cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham' LIMIT 1")
            muni = cur.fetchone()
            cur.execute(
                """INSERT INTO meetings (id, municipality_id, meeting_date, title, source_url)
                   VALUES (%s, %s, '2025-01-01', 't', '') ON CONFLICT (id) DO NOTHING""",
                (MEETING_ID, muni["id"]),
            )
            cur.execute(
                """INSERT INTO agenda_items (id, meeting_id, item_number, title, description, is_consent)
                   VALUES (%s, %s, '1', 'manual title', '', FALSE)
                   ON CONFLICT (id) DO NOTHING""",
                (ITEM_ID, MEETING_ID),
            )
            cur.execute(
                """INSERT INTO votes (id, meeting_id, source, raw_text, yeas, nays, abstentions, result)
                   VALUES (%s, %s, 'minutes_text', 'irrelevant', 5, 0, 0, 'passed')
                   ON CONFLICT (id) DO NOTHING""",
                (VOTE_ID, MEETING_ID),
            )
            # Insert a manually-locked link first
            cur.execute(
                """INSERT INTO vote_agenda_items
                    (vote_id, agenda_item_id, association_type, match_method,
                     match_confidence, is_manual, is_active, provisional)
                   VALUES (%s, %s, 'explicit', 'manual', 1.0, TRUE, TRUE, FALSE)""",
                (VOTE_ID, ITEM_ID),
            )

            # Now try to overwrite via _upsert_link (simulating any v2 tier)
            _upsert_link(
                cur,
                vote_id=VOTE_ID,
                agenda_item_id=ITEM_ID,
                association_type="explicit",
                match_method="structured_fact",
                match_confidence=0.9,
                excerpt_context="should not appear",
                provisional=False,
            )

            cur.execute(
                "SELECT match_method, match_confidence, excerpt_context FROM vote_agenda_items "
                "WHERE vote_id = %s AND agenda_item_id = %s",
                (VOTE_ID, ITEM_ID),
            )
            row = cur.fetchone()
            assert row["match_method"] == "manual", "manual shield was breached"
            assert row["match_confidence"] == 1.0
            assert row["excerpt_context"] != "should not appear"
    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM vote_agenda_items WHERE vote_id = %s", (VOTE_ID,))
            cur.execute("DELETE FROM votes WHERE id = %s", (VOTE_ID,))
            cur.execute("DELETE FROM agenda_items WHERE id = %s", (ITEM_ID,))
            cur.execute("DELETE FROM meetings WHERE id = %s", (MEETING_ID,))
