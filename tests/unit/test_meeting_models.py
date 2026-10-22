from datetime import date, time

from docket.models.meeting import Meeting
from docket.models.protocol import RawMeeting


def test_raw_meeting_accepts_start_time():
    rm = RawMeeting(
        external_id="event-123",
        municipality_slug="al-birmingham",
        title="Council Meeting",
        meeting_date=date(2026, 5, 20),
        meeting_type="council",
        agenda_url=None, minutes_url=None, video_url=None,
        source_url="https://example.com",
        start_time=time(17, 30),
    )
    assert rm.start_time == time(17, 30)


def test_raw_meeting_start_time_defaults_to_none():
    rm = RawMeeting(
        external_id="event-123",
        municipality_slug="al-birmingham",
        title="Council Meeting",
        meeting_date=date(2026, 5, 20),
        meeting_type="council",
        agenda_url=None, minutes_url=None, video_url=None,
        source_url="https://example.com",
    )
    assert rm.start_time is None


def test_meeting_from_row_reads_start_time():
    row = {
        "id": 1, "municipality_id": 1, "external_id": "e1",
        "title": "X", "meeting_date": date(2026, 5, 20),
        "meeting_type": "council", "agenda_url": None,
        "minutes_url": None, "video_url": None, "source_url": "u",
        "start_time": time(17, 30),
    }
    m = Meeting.from_row(row)
    assert m.start_time == time(17, 30)


def test_meeting_from_row_start_time_missing_is_none():
    row = {
        "id": 1, "municipality_id": 1, "external_id": "e1",
        "title": "X", "meeting_date": date(2026, 5, 20),
        "meeting_type": "council", "agenda_url": None,
        "minutes_url": None, "video_url": None, "source_url": "u",
    }
    m = Meeting.from_row(row)
    assert m.start_time is None


def test_meeting_from_row_reads_is_hidden_default_false():
    """Meeting.from_row should expose is_hidden as a bool (defaulting to False)."""
    row = {
        "id": 1, "municipality_id": 1, "external_id": "x",
        "title": "t", "meeting_date": None, "meeting_type": None,
        "agenda_url": None, "minutes_url": None, "video_url": None,
        "source_url": None,
        # is_hidden NOT in row — model should default to False
    }
    m = Meeting.from_row(row)
    assert m.is_hidden is False


def test_meeting_from_row_reads_is_hidden_true():
    row = {
        "id": 1, "municipality_id": 1, "external_id": "x",
        "title": "t", "meeting_date": None, "meeting_type": None,
        "agenda_url": None, "minutes_url": None, "video_url": None,
        "source_url": None,
        "is_hidden": True,
    }
    m = Meeting.from_row(row)
    assert m.is_hidden is True


def test_meeting_from_row_classification_defaults_when_keys_missing():
    """A row dict lacking the M2 columns yields the column defaults (plan meeting-types-name-the-body)."""
    row = {
        "id": 1, "municipality_id": 1, "external_id": "x",
        "title": "t", "meeting_date": None, "meeting_type": "council",
        "agenda_url": None, "minutes_url": None, "video_url": None,
        "source_url": None,
    }
    m = Meeting.from_row(row)
    assert m.session_kind == "regular"
    assert m.body_name is None
    assert m.type_source == "title"
    assert m.type_locked_at is None
    assert m.calendar_event_id is None


def test_meeting_from_row_reads_classification_columns():
    row = {
        "id": 1, "municipality_id": 1, "external_id": "x",
        "title": "Regular City Council Meeting", "meeting_date": None, "meeting_type": "committee",
        "agenda_url": None, "minutes_url": None, "video_url": None,
        "source_url": None,
        "session_kind": "special", "body_name": "Finance Committee",
        "type_source": "calendar", "type_locked_at": None, "calendar_event_id": 7,
    }
    m = Meeting.from_row(row)
    assert (m.meeting_type, m.session_kind, m.body_name, m.type_source, m.calendar_event_id) == (
        "committee", "special", "Finance Committee", "calendar", 7,
    )
