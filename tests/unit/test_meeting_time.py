from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from docket.services.meeting_time import (
    UPCOMING_PREDICATE_SQL,
    is_upcoming,
)

CT = ZoneInfo("America/Chicago")


def _now(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=CT)


def test_future_date_is_upcoming():
    # Meeting two days from now, no start_time known.
    assert is_upcoming(date(2026, 5, 21), None, _now(2026, 5, 19, 8)) is True


def test_past_date_is_not_upcoming():
    assert is_upcoming(date(2026, 5, 10), None, _now(2026, 5, 19, 8)) is False


def test_same_day_no_start_time_before_3pm_is_upcoming():
    # noon fallback + 3h = 3pm CT cutoff
    assert is_upcoming(date(2026, 5, 19), None, _now(2026, 5, 19, 14, 59)) is True


def test_same_day_no_start_time_at_3pm_is_not_upcoming():
    assert is_upcoming(date(2026, 5, 19), None, _now(2026, 5, 19, 15, 0)) is False


def test_same_day_with_start_time_before_buffer_is_upcoming():
    # 5:30pm meeting + 3h = 8:30pm CT cutoff
    assert is_upcoming(
        date(2026, 5, 19), time(17, 30), _now(2026, 5, 19, 20, 29)
    ) is True


def test_same_day_with_start_time_at_buffer_is_not_upcoming():
    assert is_upcoming(
        date(2026, 5, 19), time(17, 30), _now(2026, 5, 19, 20, 30)
    ) is False


def test_morning_committee_meeting_transitions_mid_morning():
    # 9am committee + 3h = noon CT cutoff
    assert is_upcoming(date(2026, 5, 19), time(9, 0), _now(2026, 5, 19, 11, 59)) is True
    assert is_upcoming(date(2026, 5, 19), time(9, 0), _now(2026, 5, 19, 12, 0)) is False


def test_late_evening_meeting_does_not_flip_at_midnight():
    # 8pm meeting + 3h = 11pm CT cutoff (same day, NOT midnight)
    assert is_upcoming(date(2026, 5, 19), time(20, 0), _now(2026, 5, 19, 22, 59)) is True
    assert is_upcoming(date(2026, 5, 19), time(20, 0), _now(2026, 5, 19, 23, 1)) is False


def test_now_defaults_to_current_chicago_time():
    # Smoke test: calling without explicit now shouldn't raise and should
    # return a bool. Don't assert direction — that depends on wall clock.
    result = is_upcoming(date(2026, 5, 19), None)
    assert result in (True, False)


def test_sql_predicate_is_a_nonempty_string():
    # The SQL fragment is consumed verbatim by query.py; downstream callers
    # rely on it being a well-formed predicate string.
    assert "meeting_date" in UPCOMING_PREDICATE_SQL
    assert "start_time" in UPCOMING_PREDICATE_SQL
