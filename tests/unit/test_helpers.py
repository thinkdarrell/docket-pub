"""Unit tests for shared adapter helpers."""

from docket.adapters._helpers import classify_meeting, is_consent_item, normalize_title


class TestClassifyMeeting:
    """Tests for classify_meeting()."""

    def test_regular(self):
        assert classify_meeting("Regular City Council Meeting") == "council"

    def test_special(self):
        assert classify_meeting("Special Called Meeting") == "special"

    def test_called(self):
        assert classify_meeting("Called Meeting - Emergency") == "special"

    def test_work_session(self):
        assert classify_meeting("Council Work Session") == "work_session"

    def test_committee(self):
        assert classify_meeting("Finance Committee Meeting") == "committee"

    def test_planning(self):
        assert classify_meeting("Planning Commission") == "planning"

    def test_bza(self):
        assert classify_meeting("Board of Zoning Adjustment (BZA)") == "planning"

    def test_zoning(self):
        assert classify_meeting("Zoning Board Meeting") == "planning"

    def test_budget_work_session(self):
        assert classify_meeting("Budget Work Session") == "work_session"

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
