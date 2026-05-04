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
