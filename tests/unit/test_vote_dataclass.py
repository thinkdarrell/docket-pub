"""Tests for AgendaItemLink and Vote dataclass shape."""

from docket.models.vote import AgendaItemLink


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
