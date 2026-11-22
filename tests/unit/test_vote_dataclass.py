"""Tests for AgendaItemLink and Vote dataclass shape."""

from docket.models.vote import AgendaItemLink, Vote


def test_agenda_item_link_required_fields():
    link = AgendaItemLink(
        id=1,
        agenda_item_id=42,
        item_number="12",
        title="A Resolution authorizing X",
        is_consent=True,
        association_type="consent_named",
        match_method="consent_block_named",
        match_confidence=1.0,
        excerpt_context="...the resolution body text...",
        provisional=True,
        is_manual=False,
        is_active=True,
    )
    assert link.id == 1
    assert link.agenda_item_id == 42
    assert link.is_consent is True
    assert link.match_confidence == 1.0


def test_agenda_item_link_is_frozen():
    link = AgendaItemLink(
        id=1, agenda_item_id=42, item_number=None, title="X",
        is_consent=False, association_type="explicit", match_method=None,
        match_confidence=0.9, excerpt_context=None, provisional=False,
        is_manual=False, is_active=True,
    )
    import dataclasses
    try:
        link.match_confidence = 0.5
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("AgendaItemLink should be frozen")


def _make_link(**overrides):
    defaults = dict(
        id=1, agenda_item_id=42, item_number="12", title="X",
        is_consent=False, association_type="explicit", match_method="resolution_number",
        match_confidence=0.9, excerpt_context=None, provisional=False,
        is_manual=False, is_active=True,
    )
    defaults.update(overrides)
    return AgendaItemLink(**defaults)


def _make_vote(agenda_links=None, **overrides):
    defaults = dict(
        id=1, meeting_id=1, external_id=None, result="passed",
        yeas=5, nays=0, abstentions=0, source="minutes_text",
        confidence="high", header_result=None, needs_review=False,
        review_reason=None, resolution_number=None,
        agenda_links=agenda_links or [], member_votes=[],
    )
    defaults.update(overrides)
    return Vote(**defaults)


def test_vote_has_no_singular_agenda_item_id():
    """The new Vote shape removes singular FK fields."""
    vote = _make_vote()
    assert not hasattr(vote, "agenda_item_id"), \
        "Vote.agenda_item_id should be removed in the N:M refactor"
    assert not hasattr(vote, "match_confidence"), \
        "Vote.match_confidence (per-vote) is now per-link on AgendaItemLink"
    assert not hasattr(vote, "match_method"), \
        "Vote.match_method (per-vote) is now per-link on AgendaItemLink"


def test_vote_active_links_filters_inactive():
    active = _make_link(id=1, is_active=True)
    ghost = _make_link(id=2, is_active=False)
    vote = _make_vote(agenda_links=[active, ghost])
    assert vote.active_links == [active]


def test_vote_is_consent_block_true_when_any_active_link_is_consent():
    explicit = _make_link(id=1, association_type="explicit")
    consent = _make_link(id=2, association_type="consent_implicit")
    vote = _make_vote(agenda_links=[explicit, consent])
    assert vote.is_consent_block is True


def test_vote_is_consent_block_false_for_only_explicit():
    explicit = _make_link(id=1, association_type="explicit")
    vote = _make_vote(agenda_links=[explicit])
    assert vote.is_consent_block is False


def test_vote_has_provisional_links_ignores_inactive():
    """Ghost links keep provisional=True; they should NOT trigger UI warning."""
    ghost = _make_link(id=1, provisional=True, is_active=False)
    active = _make_link(id=2, provisional=False, is_active=True)
    vote = _make_vote(agenda_links=[ghost, active])
    assert vote.has_provisional_links is False


def test_vote_primary_link_only_for_single_active_link():
    one = _make_link(id=1, is_active=True)
    vote_single = _make_vote(agenda_links=[one])
    assert vote_single.primary_link is one

    two = _make_link(id=2, is_active=True)
    vote_multi = _make_vote(agenda_links=[one, two])
    assert vote_multi.primary_link is None

    vote_empty = _make_vote(agenda_links=[])
    assert vote_empty.primary_link is None


def test_vote_excluded_links_returns_only_inactive():
    active = _make_link(id=1, is_active=True)
    ghost = _make_link(id=2, is_active=False)
    vote = _make_vote(agenda_links=[active, ghost])
    assert vote.excluded_links == [ghost]


def _vote(**fields) -> Vote:
    return Vote(
        id=1, meeting_id=2, external_id=None, result="passed", yeas=7, nays=0, abstentions=0,
        source="minutes_text", confidence="high", header_result=None, needs_review=False,
        review_reason=None, **fields,
    )


def test_a_vote_carries_what_a_minutes_reader_stores_and_none_of_it_by_default():
    """Plan `mobile-votes-from-minutes`, M2: the fields a minutes reader's row adds."""
    names = ("minutes_reader", "source_page", "caption", "motion_text", "declared_text", "minutes_page_url")
    plain = _vote()
    assert [getattr(plain, name) for name in names] == [None] * 6
    read = _vote(minutes_reader="mobile", source_page=5, caption="A CAPTION", motion_text="X moved",
                 declared_text="the resolution adopted", minutes_page_url="https://city.example/f#page=5")
    assert [getattr(read, name) for name in names] == [
        "mobile", 5, "A CAPTION", "X moved", "the resolution adopted", "https://city.example/f#page=5"]


def test_vote_label_is_the_declaration_when_the_row_has_one():
    from docket.models.vote import vote_label

    assert vote_label("passed", "the resolution adopted") == "the resolution adopted"
    assert vote_label("failed", "the ordinance failed") == "the ordinance failed"
    assert vote_label("passed", None) == "passed"
    assert vote_label("tabled", None) == "tabled"
    assert vote_label("unknown", "") == "unknown"


def test_vote_tone_reads_the_result_and_the_declaration():
    from docket.models.vote import vote_tone

    # No declaration: the stored result alone, as every row before a minutes reader.
    assert vote_tone("passed", None) == "pass"
    assert vote_tone("failed", None) == "fail"
    assert vote_tone("tabled", None) == ""
    assert vote_tone("unknown", None) == ""
    # A declaration that says nothing more leaves the result's tone.
    assert vote_tone("passed", "the resolution adopted") == "pass"
    assert vote_tone("failed", "the motion lost") == "fail"
    assert vote_tone("unknown", "the resolution adopted") == ""
    # The motion carried and the thing voted on did not: a motion to deny, 7 to 0.
    assert vote_tone("passed", "the waiver denied") == "fail"
    assert vote_tone("passed", "the ordinance FAILED") == "fail"
    assert vote_tone("unknown", "the resolution denied") == "fail"
    # A declaration that says the item was not decided is neither.
    for declared in ("the waiver tabled", "the resolution held over until November 10, 2026",
                     "the ordinance laid over", "the item withdrawn", "the item Laid  Over", "the motion TABLED",
                     "the resolution Held  Over"):
        assert vote_tone("passed", declared) == "", declared
    # Whole words: none of these says failed, denied, tabled, held over, laid over or withdrawn.
    for declared in ("the undenied claim approved", "the failedness noted", "the tabledness adopted",
                     "the withdrawnness adopted", "the item upheld overnight", "the relaid overpass approved",
                     "the item held, over objection, adopted", "the item upheld over objection",
                     "the untabled item adopted"):
        assert vote_tone("passed", declared) == "pass", declared
    # A motion that failed is failed whatever else its declaration says.
    assert vote_tone("failed", "the motion to table failed") == "fail"
    assert vote_tone("failed", "the item tabled") == "fail"
    assert vote_tone("passed", "the motion to deny tabled") == ""
    assert vote_tone("passed", "the tabled item denied") == "fail"


def test_page_link_names_the_page_on_the_citys_address():
    from docket.models.vote import page_link

    url = "https://mobileal.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=3854,plainText=false)"
    assert page_link(url, 5) == url + "#page=5"
    assert page_link(url + "#page=2", 61) == url + "#page=61"
    assert page_link(url + "#", 1) == url + "#page=1"
    assert page_link("https://city.example/minutes.pdf?id=3#a#b", 7) == "https://city.example/minutes.pdf?id=3#page=7"
    assert page_link(url, None) is None
    assert page_link(None, 5) is None
    assert page_link(None, None) is None
    assert page_link("", 5) is None
