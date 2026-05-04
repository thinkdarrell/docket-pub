"""Tests for analysis/vote_resolution_extractor.py."""

from docket.analysis.vote_resolution_extractor import extract_resolution_number


def test_extracts_simple_resolution_number():
    text = "RESOLUTION 1854-25 A Resolution authorizing the Mayor..."
    assert extract_resolution_number(text) == "1854-25"


def test_extracts_ordinance_with_no_dot():
    text = "ORDINANCE NO 23-101 An Ordinance approving..."
    assert extract_resolution_number(text) == "23-101"


def test_extracts_ordinance_with_dot():
    text = "ORDINANCE NO. 23-101 An Ordinance approving..."
    assert extract_resolution_number(text) == "23-101"


def test_extracts_resolution_with_letter_prefix():
    text = "Resolution No. R-2024-0419 honoring the staff"
    assert extract_resolution_number(text) == "R-2024-0419"


def test_extracts_with_slash_separator():
    text = "ORDINANCE 22/2024 was adopted"
    assert extract_resolution_number(text) == "22/2024"


def test_returns_none_when_no_match():
    text = "The City Clerk read the minutes from last meeting."
    assert extract_resolution_number(text) is None


def test_returns_none_for_empty_input():
    assert extract_resolution_number("") is None
    assert extract_resolution_number(None) is None  # type: ignore[arg-type]


def test_picks_last_match_before_tally_marker():
    """When raw_text references multiple resolutions, pick the one being voted on."""
    text = (
        "Resolution 1100-25 was adopted last week. "
        "Today, RESOLUTION 1854-25 is presented for approval. "
        "Upon the roll being called, the vote was as follows: "
        "Ayes: All. Nays: None."
    )
    # Substring before the tally marker contains both 1100-25 and 1854-25;
    # we want the rightmost (1854-25, the one being voted on).
    assert extract_resolution_number(text) == "1854-25"


def test_falls_back_to_full_text_when_no_tally_marker():
    text = "RESOLUTION 1854-25 A Resolution authorizing..."
    assert extract_resolution_number(text) == "1854-25"


def test_case_insensitive_keyword():
    text = "resolution 1854-25 A Resolution authorizing..."
    assert extract_resolution_number(text) == "1854-25"


def test_does_not_match_bare_numbers():
    text = "The amount was $11,155.25 paid in 2025."
    assert extract_resolution_number(text) is None


def test_does_not_glue_onto_adjacent_text():
    """[-/] are the only separators; spaces and other chars don't extend the number."""
    text = "RESOLUTION 1854-25.adopted"
    # Stops at .adopted — not a separator
    assert extract_resolution_number(text) == "1854-25"
