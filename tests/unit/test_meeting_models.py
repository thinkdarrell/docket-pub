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
