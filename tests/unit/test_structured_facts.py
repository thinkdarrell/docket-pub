"""Tests for analysis/structured_facts.py."""

from docket.analysis.structured_facts import (
    extract_dollar_amounts,
    extract_proper_nouns,
)


def test_extract_dollar_amounts_simple():
    text = "Pay $11,155.25 to the vendor."
    assert extract_dollar_amounts(text) == {11155.25}


def test_extract_dollar_amounts_multiple():
    text = "Two contracts: $50,000 and $1,250.75."
    assert extract_dollar_amounts(text) == {50000.0, 1250.75}


def test_extract_dollar_amounts_none():
    text = "No money mentioned here."
    assert extract_dollar_amounts(text) == set()


def test_extract_proper_nouns_finds_company():
    text = "Pay Shield Property Solutions for the work."
    surnames: set[str] = set()
    result = extract_proper_nouns(text, council_surnames=surnames)
    assert "Shield Property Solutions" in result


def test_extract_proper_nouns_excludes_council_surnames():
    text = "Councilmember Smitherman seconded the motion by Tate."
    surnames = {"Smitherman", "Tate"}
    result = extract_proper_nouns(text, council_surnames=surnames)
    # Surnames should be filtered. "Councilmember Smitherman" wouldn't match
    # the regex shape (Councilmember is filtered as procedural), but if any
    # surnames slipped through they'd be removed.
    assert "Smitherman" not in result
    assert "Tate" not in result


def test_extract_proper_nouns_excludes_procedural_phrases():
    text = "The City Clerk read the resolution."
    result = extract_proper_nouns(text, council_surnames=set())
    assert "City Clerk" not in result


def test_extract_proper_nouns_excludes_month_names():
    text = "On December 16, the council met."
    result = extract_proper_nouns(text, council_surnames=set())
    assert not any("December" in p for p in result)


def test_extract_proper_nouns_handles_ampersand():
    text = "The contract with Smith & Jones LLC was approved."
    result = extract_proper_nouns(text, council_surnames=set())
    assert any("Smith & Jones" in p for p in result)


def test_extract_proper_nouns_min_two_tokens():
    """Single capitalized words should not be treated as proper-noun phrases."""
    text = "The Mayor signed it."
    result = extract_proper_nouns(text, council_surnames=set())
    # "Mayor" alone is not a multi-token phrase
    assert "Mayor" not in result


def test_extract_proper_nouns_real_world_vote_1342():
    """Vote 1342: must extract 'Shield Property Solutions' and not surnames."""
    from tests.fixtures.vote_matcher_v2 import (
        VOTE_1342_RAW_TEXT,
        BIRMINGHAM_COUNCIL_SURNAMES_DEC_2025,
    )
    result = extract_proper_nouns(
        VOTE_1342_RAW_TEXT,
        council_surnames=BIRMINGHAM_COUNCIL_SURNAMES_DEC_2025,
    )
    assert "Shield Property Solutions" in result
    # Surnames must not leak through
    for surname in BIRMINGHAM_COUNCIL_SURNAMES_DEC_2025:
        assert surname not in result, f"council surname {surname} leaked into proper nouns"
