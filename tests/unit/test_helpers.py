"""Unit tests for shared adapter helpers."""

from docket.adapters._helpers import classify_meeting, is_consent_item


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
