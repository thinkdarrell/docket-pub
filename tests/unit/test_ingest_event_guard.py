"""Unit tests for the event-* short-circuit guards.

Birmingham's upcoming meetings carry an external_id of shape
`event-{event_id}` until the meeting is recorded. After PR introducing
agenda PDF parsing:

- fetch_agenda_items NOW returns real items for event-* (it downloads
  and parses the AgendaViewer PDF) — covered in test_granicus_adapter.
- _ingest_agenda_items NO LONGER short-circuits — it lets the adapter
  return PDF-derived items and ingests them normally.
- _ingest_votes STILL short-circuits — upcoming meetings have no
  minutes URL so vote scraping isn't possible.

This file now only covers the votes guard. The previous agenda-items
guard tests were removed when the PDF-parsing path landed.
"""

from datetime import date
from unittest.mock import MagicMock, patch

from docket.models.protocol import RawMeeting
from docket.services.ingest import _ingest_votes


def _upcoming_meeting() -> RawMeeting:
    return RawMeeting(
        external_id="event-2692",
        municipality_slug="birmingham",
        title="Regular City Council Meeting",
        meeting_date=date(2026, 5, 19),
        meeting_type="council",
        agenda_url="https://bhamal.granicus.com/AgendaViewer.php?view_id=2&event_id=2692",
        minutes_url=None,
        video_url=None,
        source_url="https://bhamal.granicus.com/AgendaViewer.php?view_id=2&event_id=2692",
    )


class TestIngestVotesGuard:
    """_ingest_votes must short-circuit for event-* meetings — they have no
    minutes URL and no votes recorded yet."""

    @patch("docket.services.ingest.db_cursor")
    @patch("docket.services.ingest.db")
    def test_returns_zero_for_event_meeting(self, mock_db, mock_db_cursor):
        adapter = MagicMock()
        result = _ingest_votes(1, adapter, _upcoming_meeting())
        assert result == 0

    @patch("docket.services.ingest.db_cursor")
    @patch("docket.services.ingest.db")
    def test_does_not_call_adapter_for_event_meeting(self, mock_db, mock_db_cursor):
        adapter = MagicMock()
        _ingest_votes(1, adapter, _upcoming_meeting())
        adapter.fetch_votes.assert_not_called()

    @patch("docket.services.ingest.db_cursor")
    @patch("docket.services.ingest.db")
    def test_does_not_touch_db_for_event_meeting(self, mock_db, mock_db_cursor):
        adapter = MagicMock()
        _ingest_votes(1, adapter, _upcoming_meeting())
        mock_db.assert_not_called()
        mock_db_cursor.assert_not_called()
