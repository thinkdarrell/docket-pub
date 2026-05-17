"""Unit tests for the event-* short-circuit guards.

The Granicus adapter now returns RawMeeting rows with `external_id` of
shape `event-{event_id}` for upcoming meetings (no clip_id assigned
yet). Both the adapter's `fetch_agenda_items` and the ingest service's
`_ingest_agenda_items` / `_ingest_votes` must handle these safely:

1. fetch_agenda_items must return [] without trying to `int()` the
   external_id (which would raise ValueError).

2. _ingest_agenda_items must return 0 *without* writing
   `processing_status.agenda_items_scraped=TRUE`. The flag is keyed on
   the integer `meeting_id` PK, so it would persist through the eventual
   external_id upgrade (event-N → clip_id) and lock the meeting out of
   agenda extraction forever.

3. _ingest_votes must short-circuit the same way for defense-in-depth,
   even though in practice the caller's `minutes_url is None` check
   already gates it (upcoming meetings never have minutes).
"""

from datetime import date
from unittest.mock import MagicMock, patch

from docket.adapters.granicus import GranicusAdapter
from docket.models.protocol import RawMeeting
from docket.services.ingest import _ingest_agenda_items, _ingest_votes


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


class TestAdapterFetchAgendaItemsGuard:
    """GranicusAdapter.fetch_agenda_items must not raise for event-* meetings."""

    def test_returns_empty_list_for_event_meeting(self):
        adapter = GranicusAdapter(
            "birmingham", {"view_id": 2, "base_url": "https://bhamal.granicus.com"}
        )
        # Must not raise ValueError trying to int("event-2692")
        items = adapter.fetch_agenda_items(_upcoming_meeting())
        assert items == []

    def test_does_not_make_http_request_for_event_meeting(self):
        adapter = GranicusAdapter(
            "birmingham", {"view_id": 2, "base_url": "https://bhamal.granicus.com"}
        )
        with patch("docket.adapters.granicus.requests.get") as mock_get:
            adapter.fetch_agenda_items(_upcoming_meeting())
            mock_get.assert_not_called()


class TestIngestAgendaItemsGuard:
    """_ingest_agenda_items must short-circuit before any DB or adapter call."""

    @patch("docket.services.ingest.db_cursor")
    @patch("docket.services.ingest.db")
    def test_returns_zero_for_event_meeting(self, mock_db, mock_db_cursor):
        adapter = MagicMock()
        result = _ingest_agenda_items(
            municipality_id=1, adapter=adapter, raw_meeting=_upcoming_meeting()
        )
        assert result == 0

    @patch("docket.services.ingest.db_cursor")
    @patch("docket.services.ingest.db")
    def test_does_not_call_adapter_for_event_meeting(self, mock_db, mock_db_cursor):
        adapter = MagicMock()
        _ingest_agenda_items(1, adapter, _upcoming_meeting())
        adapter.fetch_agenda_items.assert_not_called()

    @patch("docket.services.ingest.db_cursor")
    @patch("docket.services.ingest.db")
    def test_does_not_touch_db_for_event_meeting(self, mock_db, mock_db_cursor):
        # Most critical assertion: no processing_status write under any path,
        # because the integer meeting_id PK would carry the flag through the
        # eventual event-N → clip_id upgrade.
        adapter = MagicMock()
        _ingest_agenda_items(1, adapter, _upcoming_meeting())
        mock_db.assert_not_called()
        mock_db_cursor.assert_not_called()


class TestIngestVotesGuard:
    """_ingest_votes guard — defense in depth even though minutes_url=None
    on upcoming meetings already prevents the caller from reaching this."""

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
