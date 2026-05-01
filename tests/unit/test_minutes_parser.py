"""Tests for minutes parser context capture and consent-phrase detection."""

from docket.analysis.minutes_parser import parse_minutes, ParsedVote, _contains_consent_phrase


CONSENT_BLOCK_TEXT = """
Some preceding text describing item 12 about a contract for paving services
authorized by ordinance 1854-25 with HCL Contracting at $2.3M.

The resolutions and ordinances introduced as consent agenda matters were read by the
City Clerk, all public hearings having been announced, and unanimous consent having been
previously granted, Councilmember Alexander moved their adoption which motion was
seconded by Councilmember Smitherman, and upon the roll being called, the vote was as
follows:
Ayes: Alexander, Smitherman, Williams, O'Quinn
Nays: None
"""

SUBSTANTIVE_VOTE_TEXT = """
A Resolution authorizing the Mayor to execute an agreement with HCL Contracting Inc.
in the amount of two million three hundred thousand dollars ($2,300,000) for paving
services on 9th Avenue North, said work being more particularly described in the
attached Exhibit A.

The resolution was read by the City Clerk, whereupon Councilmember Smitherman moved
its adoption which motion was seconded by Councilmember Williams, and upon the roll
being called, the vote was as follows:
Ayes: Alexander, Smitherman, Williams, O'Quinn
Nays: None
"""


def test_parser_captures_1500_char_window():
    """The parser must capture pre-vote context up to 1500 chars (was effectively 200)."""
    long_preamble = "X " * 800  # ~1600 chars of filler
    text = long_preamble + SUBSTANTIVE_VOTE_TEXT
    result = parse_minutes(text)
    assert len(result.votes) == 1
    vote = result.votes[0]
    # context should include text from the resolution body, not just the trailing boilerplate
    assert "HCL Contracting" in vote.context, \
        "Parser must capture far enough back to include the resolution body"


def test_parser_persists_raw_text_with_pre_and_post_window():
    text = SUBSTANTIVE_VOTE_TEXT
    result = parse_minutes(text)
    vote = result.votes[0]
    assert vote.raw_text, "raw_text must be populated"
    assert "HCL Contracting" in vote.raw_text
    assert "Ayes:" in vote.raw_text


def test_parser_flags_likely_consent_block():
    """is_likely_consent must be True when consent phrase is present in the captured window."""
    result = parse_minutes(CONSENT_BLOCK_TEXT)
    assert len(result.votes) == 1
    assert result.votes[0].is_likely_consent is True


def test_parser_flags_substantive_vote_as_not_consent():
    result = parse_minutes(SUBSTANTIVE_VOTE_TEXT)
    assert len(result.votes) == 1
    assert result.votes[0].is_likely_consent is False


def test_contains_consent_phrase_detects_each_canonical_phrase():
    assert _contains_consent_phrase("the resolutions and ordinances introduced as consent agenda matters were read")
    assert _contains_consent_phrase("...consent agenda matters were read by the city clerk...")
    assert _contains_consent_phrase("X all items on the consent agenda Y")
    assert _contains_consent_phrase("items on consent")
    assert not _contains_consent_phrase("this is just a regular resolution being voted on")
