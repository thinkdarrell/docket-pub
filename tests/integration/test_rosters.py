"""Integration tests for docket.analysis.ocr.rosters.build_roster_for_meeting.

Covers boundary cases the spec called out:
- transition-date inclusivity (half-open range)
- duplicate surnames (deterministic ordering)
- empty council (no rows)
"""
import os
import pytest

from docket.analysis.ocr.rosters import (
    OCRRoster,
    CouncilLayout,
    build_roster_for_meeting,
    _to_initial_lastname,
)

pytestmark = pytest.mark.skipif(
    "railway.internal" in os.environ.get("DATABASE_URL", "")
    or "railway.app" in os.environ.get("DATABASE_URL", ""),
    reason="Roster test mutates DB; must not run against Railway prod.",
)


def test_to_initial_lastname_simple():
    assert _to_initial_lastname("Carole Smitherman") == "C. Smitherman"


def test_to_initial_lastname_middle_name():
    assert _to_initial_lastname("Jonathan Q Public") == "J. Public"


def test_to_initial_lastname_single_token_passthrough():
    assert _to_initial_lastname("Madonna") == "Madonna"


def test_boundary_term_end_exclusive(seeded_term_end_boundary):
    """Half-open ``>= term_start AND < term_end + 1day`` must exclude the
    member whose term_end matches the meeting date."""
    outgoing_id, incoming_id, meeting_id = seeded_term_end_boundary
    roster = build_roster_for_meeting(meeting_id)
    assert incoming_id in roster.member_map.values()
    assert outgoing_id not in roster.member_map.values()


def test_deterministic_ordering_duplicate_surname(seeded_duplicate_surname):
    """Two Smithermans on the same date both appear, deterministically ordered."""
    roster = build_roster_for_meeting(seeded_duplicate_surname.meeting_id)
    names = roster.layout.member_names
    smithermans = [n for n in names if n.endswith("Smitherman")]
    assert len(smithermans) == 2


def test_empty_council_returns_empty_layout(seeded_empty_meeting):
    """Meeting where no council members are active returns empty layout."""
    roster = build_roster_for_meeting(seeded_empty_meeting)
    assert roster.layout.member_names == []
    assert roster.member_map == {}


def test_layout_has_correct_shape(seeded_term_end_boundary):
    """The returned CouncilLayout must have the al-muni shape — city, rows, max_members
    — not the simplified name_list shape the original plan assumed."""
    _, _, meeting_id = seeded_term_end_boundary
    roster = build_roster_for_meeting(meeting_id)
    assert isinstance(roster, OCRRoster)
    assert isinstance(roster.layout, CouncilLayout)
    assert roster.layout.city == "birmingham"
    assert roster.layout.max_members == len(roster.member_map)
    assert len(roster.layout.rows) == len(roster.member_map)
    # member_names property flattens rows correctly
    assert set(roster.layout.member_names) == set(roster.member_map.keys())
