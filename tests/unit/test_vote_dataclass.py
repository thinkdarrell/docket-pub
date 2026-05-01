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
