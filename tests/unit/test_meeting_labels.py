"""Unit tests for label_for() and the cancelled-title predicate.

label_for builds the display label a reader sees in place of the clip name
(meeting_type, session_kind, body_name, title, cancelled). The symbols are
imported inside each test so this file collects before the code lands and
reads as failing tests, not as a collection error.
"""

import pytest

CANCELLED_BHM = "Regular City Council Meeting - Cancelled (Next Regular Meeting 03/24/2026)"


class TestLabelForCouncil:
    def test_regular(self):
        from docket.adapters._helpers import label_for

        assert label_for("council", "regular", None, "Regular City Council Meeting", cancelled=False) == "City Council meeting"

    def test_special(self):
        from docket.adapters._helpers import label_for

        assert label_for("council", "special", None, "Special Called Council Meeting", cancelled=False) == "Special called council meeting"

    def test_work_session(self):
        from docket.adapters._helpers import label_for

        assert label_for("council", "work_session", None, "City Council Regular Work Session", cancelled=False) == "Council work session"

    def test_budget_hearing(self):
        from docket.adapters._helpers import label_for

        assert label_for("council", "budget_hearing", None, "Budget Hearing", cancelled=False) == "Budget hearing"

    def test_cancelled_suffix(self):
        from docket.adapters._helpers import label_for

        assert label_for("council", "regular", None, CANCELLED_BHM, cancelled=True) == "City Council meeting (cancelled)"


class TestLabelForCommittee:
    def test_body_name_passes_through_unchanged(self):
        from docket.adapters._helpers import label_for

        name = "Committee of the Whole / Administration & Governmental Affairs"
        assert label_for("committee", "regular", name, "Regular City Council Meeting", cancelled=False) == name

    def test_no_body_name(self):
        from docket.adapters._helpers import label_for

        assert label_for("committee", "regular", None, "Regular City Council Meeting", cancelled=False) == "Council committee meeting"

    def test_special_called_suffix(self):
        from docket.adapters._helpers import label_for

        assert label_for("committee", "special", "Finance Committee", "Special Called Finance Committee", cancelled=False) == "Finance Committee (special called)"

    def test_cancelled_suffix_on_body_name(self):
        from docket.adapters._helpers import label_for

        assert label_for("committee", "regular", "Finance Committee", "Finance Committee - Cancelled", cancelled=True) == "Finance Committee (cancelled)"


class TestLabelForPlanningAndBoard:
    def test_planning_no_body_name(self):
        from docket.adapters._helpers import label_for

        assert label_for("planning", "regular", None, "x", cancelled=False) == "Planning commission meeting"

    def test_planning_body_name(self):
        from docket.adapters._helpers import label_for

        assert label_for("planning", "regular", "Planning Commission", "Planning Commission", cancelled=False) == "Planning Commission"

    def test_board_no_body_name(self):
        from docket.adapters._helpers import label_for

        assert label_for("board", "regular", None, "x", cancelled=False) == "Board meeting"

    def test_board_body_name(self):
        from docket.adapters._helpers import label_for

        assert label_for("board", "regular", "Design Review Board", "Design Review Board Meeting", cancelled=False) == "Design Review Board"

    def test_board_special_called_suffix(self):
        from docket.adapters._helpers import label_for

        assert label_for("board", "special", "Design Review Board", "Design Review Board Special Meeting", cancelled=False) == "Design Review Board (special called)"

    def test_board_work_session_suffix(self):
        from docket.adapters._helpers import label_for

        assert label_for("board", "work_session", "Parks and Recreation", "Parks and Recreation Work Session", cancelled=False) == "Parks and Recreation (work session)"


class TestLabelForOther:
    def test_title_itself(self):
        from docket.adapters._helpers import label_for

        assert label_for("other", "regular", None, "Granicus Test", cancelled=False) == "Granicus Test"

    def test_no_cancelled_suffix_on_the_title_itself(self):
        from docket.adapters._helpers import label_for

        title = "Press Conference - Cancelled"
        assert label_for("other", "regular", None, title, cancelled=True) == title


class TestIsCancelledTitle:
    @pytest.mark.parametrize(
        "title,expected",
        [
            (CANCELLED_BHM, True),
            ("Meeting canceled due to inclement weather", True),
            ("Regular City Council Meeting", False),
            (None, False),
        ],
    )
    def test_predicate(self, title, expected):
        from docket.services.query import is_cancelled_title

        assert is_cancelled_title(title) is expected

    def test_sql_predicate_is_built_from_the_same_pattern(self):
        from docket.services.query import CANCELLED_PREDICATE_SQL, CANCELLED_TITLE_PATTERN

        assert CANCELLED_TITLE_PATTERN == r"cancell?ed"
        assert CANCELLED_PREDICATE_SQL == "(title ~* 'cancell?ed')"
