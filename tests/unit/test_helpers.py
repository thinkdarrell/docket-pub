"""Unit tests for shared adapter helpers."""

import pytest

from docket.adapters._helpers import classify_meeting, is_consent_item, normalize_title


class TestClassifyMeeting:
    """Tests for classify_meeting()."""

    def test_regular(self):
        assert classify_meeting("Regular City Council Meeting") == "council"

    def test_special(self):
        # A special called sitting with no body named is the council's; the
        # sitting itself lives on session_kind (classify_title).
        assert classify_meeting("Special Called Meeting") == "council"

    def test_called(self):
        assert classify_meeting("Called Meeting - Emergency") == "council"

    def test_work_session(self):
        # A council work session is the council's; "work_session" is a
        # session_kind, not a body.
        assert classify_meeting("Council Work Session") == "council"

    def test_committee(self):
        assert classify_meeting("Finance Committee Meeting") == "committee"

    def test_planning(self):
        assert classify_meeting("Planning Commission") == "planning"

    def test_bza(self):
        assert classify_meeting("Board of Zoning Adjustment (BZA)") == "planning"

    def test_zoning(self):
        assert classify_meeting("Zoning Board Meeting") == "planning"

    def test_budget_work_session(self):
        assert classify_meeting("Budget Work Session") == "council"

    def test_budget_hearing(self):
        assert classify_meeting("Budget Hearing") == "council"

    def test_generic_council(self):
        assert classify_meeting("City Council Meeting") == "council"

    def test_empty(self):
        assert classify_meeting("") == "other"

    def test_case_insensitive(self):
        assert classify_meeting("SPECIAL CALLED MEETING") == "special"

    def test_board(self):
        assert classify_meeting("Design Review Board Meeting") == "board"

    def test_parks_board(self):
        assert classify_meeting("Parks and Recreation Board Meeting") == "board"

    def test_library_board(self):
        assert classify_meeting("Library Board of Trustees Meeting") == "board"

    def test_commission(self):
        assert classify_meeting("Planning and Zoning Commission Meeting") == "planning"


# One row per title in the inventory the plan's Context lists (Homewood,
# Vestavia Hills, Mobile, the Birmingham variants, and the three `other`
# shapes): (title, meeting_type, session_kind, body_name).
TITLE_INVENTORY = [
    # Homewood (generic_cms): titles name the body.
    ("Council Meeting", "council", "regular", None),
    ("Finance Committee", "committee", "regular", "Finance Committee"),
    ("Special Called Special Issues Committee", "committee", "special", "Special Issues Committee"),
    ("Public Works Committee", "committee", "regular", "Public Works Committee"),
    ("Public Safety Committee", "committee", "regular", "Public Safety Committee"),
    ("Planning & Development Committee", "committee", "regular", "Planning & Development Committee"),
    ("Board of Zoning Adjustment", "planning", "regular", "Board of Zoning Adjustment"),
    ("Board of Zoning Adjustment (BZA)", "planning", "regular", "Board of Zoning Adjustment"),
    ("Planning Commission", "planning", "regular", "Planning Commission"),
    ("Historic Preservation Commission", "board", "regular", "Historic Preservation Commission"),
    ("Special Called Council Meeting", "council", "special", None),
    ("Library Board", "board", "regular", "Library Board"),
    ("Pre-Council Work Session", "council", "work_session", None),
    ("Special Called Finance Committee", "committee", "special", "Finance Committee"),
    # Vestavia Hills (civicclerk).
    ("City Council Meeting", "council", "regular", None),
    ("Parks and Recreation Board Meeting", "board", "regular", "Parks and Recreation Board"),
    ("Parks and Recreation Board Meeting - March 2026", "board", "regular", "Parks and Recreation Board"),
    ("Planning and Zoning Commission Meeting", "planning", "regular", "Planning and Zoning Commission"),
    ("Board of Zoning Adjustment Meeting", "planning", "regular", "Board of Zoning Adjustment"),
    ("Design Review Board Meeting", "board", "regular", "Design Review Board"),
    ("Library Board of Trustees Meeting", "board", "regular", "Library Board of Trustees"),
    ("City Council Organizational Meeting", "council", "regular", None),
    ("City Council Regular Work Session", "council", "work_session", None),
    ("Parks and Recreation Work Session", "board", "work_session", "Parks and Recreation"),
    ("Standing Annexation Committee", "committee", "regular", "Standing Annexation Committee"),
    ("Design Review Board Special Meeting", "board", "special", "Design Review Board"),
    ("City Council Special Meeting", "council", "special", None),
    ("City Council Special Work Session", "council", "work_session", None),
    # Mobile (civicclerk, council category only).
    ("One Time Event", "other", "regular", None),
    # Birmingham (granicus): the generic title and its variants.
    ("Regular City Council Meeting", "council", "regular", None),
    ("Regular City Council Meeting - Cancelled (Next Regular Meeting 03/24/2026)", "council", "regular", None),
    ("Regular City Council Meeting Part II", "council", "regular", None),
    ("Virtual Regular City Council Meeting - See agenda for access", "council", "regular", None),
    ("Budget Hearing", "council", "budget_hearing", None),
    ("FY2026 Budget Meeting", "council", "budget_hearing", None),
    # The three `other` shapes, plus the empty and bare-date titles.
    ("Granicus Test", "other", "regular", None),
    ("Press Conference", "other", "regular", None),
    ("Municipal Election Results", "other", "regular", None),
    ("April 23, 2024", "other", "regular", None),
    ("", "other", "regular", None),
]


class TestClassifyTitle:
    """Tests for classify_title(): body, session kind, and body name per title."""

    @pytest.mark.parametrize("title,meeting_type,session_kind,body_name", TITLE_INVENTORY)
    def test_inventory(self, title, meeting_type, session_kind, body_name):
        from docket.adapters._helpers import Classification, classify_title

        assert classify_title(title) == Classification(meeting_type, session_kind, body_name)

    def test_vocabulary_tuples(self):
        from docket.adapters._helpers import MEETING_TYPES, SESSION_KINDS

        assert MEETING_TYPES == ("council", "committee", "planning", "board", "other")
        assert SESSION_KINDS == ("regular", "special", "work_session", "budget_hearing")

    def test_every_inventory_value_is_in_the_vocabulary(self):
        from docket.adapters._helpers import MEETING_TYPES, SESSION_KINDS

        for _, meeting_type, session_kind, _ in TITLE_INVENTORY:
            assert meeting_type in MEETING_TYPES
            assert session_kind in SESSION_KINDS

    def test_classify_meeting_is_the_body(self):
        from docket.adapters._helpers import classify_meeting, classify_title

        for title, *_ in TITLE_INVENTORY:
            assert classify_meeting(title) == classify_title(title).meeting_type


class TestIsConsentItem:
    """Tests for is_consent_item()."""

    def test_consent_in_title(self):
        assert is_consent_item("Consent Agenda Item 1") is True

    def test_no_consent(self):
        assert is_consent_item("Approve contract for roadwork") is False

    def test_consent_case_insensitive(self):
        assert is_consent_item("CONSENT AGENDA") is True

    def test_empty(self):
        assert is_consent_item("") is False

    def test_partial_match(self):
        assert is_consent_item("Items removed from consent agenda") is True


class TestNormalizeTitle:
    """Tests for normalize_title().

    Used by the Granicus upcoming-meetings reconciliation step in ingest.py
    to match a freshly-archived row against its prior upcoming-row counterpart
    on (municipality, date, normalize_title(title)). Must be aggressive enough
    to survive minor edits (case, whitespace, punctuation, cancellation
    suffixes) without collapsing genuinely different titles.
    """

    def test_lowercases(self):
        assert normalize_title("Regular City Council Meeting") == "regular city council meeting"

    def test_collapses_internal_whitespace(self):
        assert normalize_title("Regular  City   Council    Meeting") == "regular city council meeting"

    def test_strips_surrounding_whitespace(self):
        assert normalize_title("   Regular City Council Meeting   ") == "regular city council meeting"

    def test_strips_cancelled_suffix(self):
        assert normalize_title("Regular City Council Meeting - Cancelled") == "regular city council meeting"

    def test_strips_cancelled_suffix_with_trailing_explanation(self):
        # Real-world shape: BHM uses suffixes like "- Cancelled (Next Regular Meeting 3/24)"
        assert (
            normalize_title("Regular City Council Meeting - Cancelled (Next Regular Meeting 3/24)")
            == "regular city council meeting"
        )

    def test_strips_rescheduled_suffix(self):
        assert normalize_title("Regular City Council Meeting - Rescheduled") == "regular city council meeting"

    def test_strips_postponed_suffix(self):
        assert normalize_title("Regular City Council Meeting - Postponed") == "regular city council meeting"

    def test_strips_deferred_suffix(self):
        assert normalize_title("Regular City Council Meeting - Deferred") == "regular city council meeting"

    def test_suffix_match_is_case_insensitive(self):
        assert normalize_title("Regular City Council Meeting - CANCELLED") == "regular city council meeting"

    def test_drops_trailing_punctuation(self):
        assert normalize_title("Regular City Council Meeting.") == "regular city council meeting"

    def test_drops_internal_punctuation(self):
        # Commas, periods, colons inside the title shouldn't prevent a match
        assert normalize_title("Council: Regular Meeting, May 2026") == "council regular meeting may 2026"

    def test_normalizes_unicode_whitespace(self):
        # Non-breaking space (U+00A0) should normalize like a regular space
        assert normalize_title("Regular City Council Meeting") == "regular city council meeting"

    def test_idempotent(self):
        once = normalize_title("Regular City Council Meeting - Cancelled")
        twice = normalize_title(once)
        assert once == twice

    def test_empty(self):
        assert normalize_title("") == ""

    def test_only_whitespace(self):
        assert normalize_title("   \t\n   ") == ""

    def test_preserves_alphanumeric(self):
        # Don't strip out digits or letters; numbers in meeting titles are meaningful
        assert normalize_title("Budget Hearing FY2026") == "budget hearing fy2026"

    def test_does_not_strip_suffix_without_hyphen_marker(self):
        # "Cancelled" appearing as part of a longer phrase without the " - " marker
        # should NOT trigger the truncation — it's not the suffix shape.
        assert normalize_title("Cancelled Project Review Meeting") == "cancelled project review meeting"
