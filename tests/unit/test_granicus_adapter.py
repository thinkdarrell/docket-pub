"""Unit tests for GranicusAdapter parsing logic.

Covers the upcoming-meetings reconciliation path: event_id extraction,
event-id-based agenda URL builder, upcoming-row parser, and the
dual-table read in list_meetings (via _parse_publisher_page so HTTP
stays out of the unit suite).
"""

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from bs4 import BeautifulSoup

from docket.adapters.granicus import GranicusAdapter
from docket.models.protocol import RawMeeting


ADAPTER_CONFIG = {"view_id": 2, "base_url": "https://bhamal.granicus.com"}


def _adapter() -> GranicusAdapter:
    return GranicusAdapter("birmingham", ADAPTER_CONFIG)


# Real upcoming-row HTML captured 2026-05-16 from bhamal.granicus.com.
# The 5/19 BHM regular meeting — agenda posted Friday 5/15.
UPCOMING_ROW_HTML = """
<tr class="odd">
  <td class="listItem" headers="EventName" id="Regular-City-Council-Meeting" scope="row">
    Regular City Council Meeting
  </td>
  <td class="listItem" headers="EventDate Regular-City-Council-Meeting">
    <span style="display:none;">1779206400</span>
    May 19, 2026 - 09:00 AM
  </td>
  <td class="listItem">
    <a href="//bhamal.granicus.com/AgendaViewer.php?view_id=2&amp;event_id=2692">Agenda</a>
  </td>
  <td class="listItem" headers="EventLink Regular-City-Council-Meeting"></td>
</tr>
"""

# Real archive-row HTML (5/12 meeting), simplified for tests.
ARCHIVE_ROW_HTML = """
<tr class="even">
  <td class="listItem" headers="Name" id="Regular-City-Council-Meeting" scope="row">
    Regular City Council Meeting
  </td>
  <td class="listItem" headers="Date Regular-City-Council-Meeting">
    <span style="display:none;">1778569200</span>
    May 12, 2026
  </td>
  <td class="listItem" headers="Duration Regular-City-Council-Meeting">01h 27m</td>
  <td class="listItem" headers="Agenda Regular-City-Council-Meeting">
    <a href="//bhamal.granicus.com/AgendaViewer.php?view_id=2&amp;clip_id=1980">Agenda</a>
  </td>
  <td class="listItem" headers="Minutes Regular-City-Council-Meeting"></td>
  <td class="listItem" headers="VideoLink Regular-City-Council-Meeting">
    <a href="javascript:void(0);" onclick="window.open('//bhamal.granicus.com/MediaPlayer.php?view_id=2&amp;clip_id=1980')">Video</a>
  </td>
</tr>
"""


class TestExtractEventId:
    """Tests for GranicusAdapter._extract_event_id()."""

    def test_finds_in_href(self):
        row = BeautifulSoup(UPCOMING_ROW_HTML, "html.parser")
        assert GranicusAdapter._extract_event_id(row) == 2692

    def test_finds_in_onclick(self):
        html = """
        <tr><td>
          <a href="#" onclick="window.open('//x/AgendaViewer.php?event_id=999')">Agenda</a>
        </td></tr>
        """
        row = BeautifulSoup(html, "html.parser")
        assert GranicusAdapter._extract_event_id(row) == 999

    def test_returns_none_when_only_clip_id(self):
        row = BeautifulSoup(ARCHIVE_ROW_HTML, "html.parser")
        assert GranicusAdapter._extract_event_id(row) is None

    def test_returns_none_when_no_links(self):
        row = BeautifulSoup("<tr><td>no links</td></tr>", "html.parser")
        assert GranicusAdapter._extract_event_id(row) is None


class TestAgendaUrlByEventId:
    """Tests for GranicusAdapter._agenda_url_by_event_id()."""

    def test_builds_canonical_url(self):
        adapter = _adapter()
        assert (
            adapter._agenda_url_by_event_id(2692)
            == "https://bhamal.granicus.com/AgendaViewer.php?view_id=2&event_id=2692"
        )

    def test_respects_view_id_config(self):
        adapter = GranicusAdapter("other", {"view_id": 7, "base_url": "https://other.granicus.com"})
        assert (
            adapter._agenda_url_by_event_id(42)
            == "https://other.granicus.com/AgendaViewer.php?view_id=7&event_id=42"
        )


class TestParseUpcomingRow:
    """Tests for GranicusAdapter._parse_upcoming_row()."""

    def test_parses_real_upcoming_row(self):
        adapter = _adapter()
        row = BeautifulSoup(UPCOMING_ROW_HTML, "html.parser").find("tr")
        meeting = adapter._parse_upcoming_row(row)

        assert meeting is not None
        assert meeting.external_id == "event-2692"
        assert meeting.municipality_slug == "birmingham"
        assert meeting.title == "Regular City Council Meeting"
        assert meeting.meeting_date == date(2026, 5, 19)
        assert meeting.meeting_type == "council"
        assert (
            meeting.agenda_url
            == "https://bhamal.granicus.com/AgendaViewer.php?view_id=2&event_id=2692"
        )
        assert meeting.minutes_url is None
        assert meeting.video_url is None
        # source_url is the agenda page itself for upcoming meetings — no
        # player page exists yet, and source_url is non-optional on RawMeeting.
        assert meeting.source_url == meeting.agenda_url

    def test_returns_none_when_no_event_id(self):
        # Row that looks upcoming-shape but has no event_id link
        # (e.g., "Agenda Coming Soon" placeholder before publication)
        html = """
        <tr class="odd">
          <td headers="EventName">Some Meeting</td>
          <td headers="EventDate"><span style="display:none;">1779206400</span>May 19, 2026</td>
          <td><span>Agenda Coming Soon</span></td>
          <td headers="EventLink"></td>
        </tr>
        """
        row = BeautifulSoup(html, "html.parser").find("tr")
        adapter = _adapter()
        assert adapter._parse_upcoming_row(row) is None


class TestParsePublisherPage:
    """Tests for GranicusAdapter._parse_publisher_page() — the HTTP-free
    seam that list_meetings calls into. Covers the dual-table read."""

    def test_returns_both_upcoming_and_archive_meetings(self):
        html = f"""
        <html><body>
          <table id="upcoming">{UPCOMING_ROW_HTML}</table>
          <table id="archive">{ARCHIVE_ROW_HTML}</table>
        </body></html>
        """
        adapter = _adapter()
        meetings = adapter._parse_publisher_page(html)

        external_ids = sorted(m.external_id for m in meetings)
        assert external_ids == ["1980", "event-2692"]

    def test_handles_missing_upcoming_table(self):
        # Some Granicus deployments may not have an upcoming section
        html = f"""
        <html><body>
          <table id="archive">{ARCHIVE_ROW_HTML}</table>
        </body></html>
        """
        adapter = _adapter()
        meetings = adapter._parse_publisher_page(html)
        assert [m.external_id for m in meetings] == ["1980"]

    def test_handles_empty_upcoming_table(self):
        # Upcoming section present but no rows (no meetings scheduled)
        html = f"""
        <html><body>
          <table id="upcoming"></table>
          <table id="archive">{ARCHIVE_ROW_HTML}</table>
        </body></html>
        """
        adapter = _adapter()
        meetings = adapter._parse_publisher_page(html)
        assert [m.external_id for m in meetings] == ["1980"]

    def test_since_filter_applies_to_both_tables(self):
        html = f"""
        <html><body>
          <table id="upcoming">{UPCOMING_ROW_HTML}</table>
          <table id="archive">{ARCHIVE_ROW_HTML}</table>
        </body></html>
        """
        adapter = _adapter()
        # Cutoff after the archive row (5/12) but before the upcoming row (5/19)
        meetings = adapter._parse_publisher_page(html, since=date(2026, 5, 15))
        assert [m.external_id for m in meetings] == ["event-2692"]


# --- fetch_agenda_items dispatch tests -------------------------------------

FIXTURE_PDF = (
    Path(__file__).parent.parent / "fixtures" / "granicus_bham_agenda_2026_05_19.pdf"
)


def _upcoming_meeting() -> RawMeeting:
    """The 5/19 BHM upcoming meeting fixture."""
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


def _archive_meeting() -> RawMeeting:
    return RawMeeting(
        external_id="1980",
        municipality_slug="birmingham",
        title="Regular City Council Meeting",
        meeting_date=date(2026, 5, 12),
        meeting_type="council",
        agenda_url="https://bhamal.granicus.com/AgendaViewer.php?view_id=2&clip_id=1980",
        minutes_url=None,
        video_url=None,
        source_url="https://bhamal.granicus.com/player/clip/1980?view_id=2",
    )


def _mock_pdf_response(pdf_bytes: bytes) -> MagicMock:
    """Build a mock requests.Response object carrying a PDF body."""
    resp = MagicMock()
    resp.status_code = 200
    resp.content = pdf_bytes
    resp.raise_for_status = MagicMock(return_value=None)
    return resp


class TestFetchAgendaItemsEventPath:
    """For event-* meetings, fetch_agenda_items must download the AgendaViewer
    PDF and return items parsed from it (not the legacy MediaPlayer path)."""

    def test_returns_real_items_from_pdf(self):
        adapter = _adapter()
        pdf_bytes = FIXTURE_PDF.read_bytes()
        with patch(
            "docket.adapters.granicus.requests.get",
            return_value=_mock_pdf_response(pdf_bytes),
        ):
            items = adapter.fetch_agenda_items(_upcoming_meeting())

        assert len(items) == 102
        # First item: substantive, sponsor mentions Woods
        assert items[0].item_number == "1"
        assert items[0].is_consent is False
        assert items[0].sponsor and "Woods" in items[0].sponsor
        # Item 2: consent-with-public-hearing
        assert items[1].item_number == "2"
        assert items[1].is_consent is True

    def test_items_have_no_video_timestamps(self):
        """Pre-recording — there's no MediaPlayer index points yet."""
        adapter = _adapter()
        pdf_bytes = FIXTURE_PDF.read_bytes()
        with patch(
            "docket.adapters.granicus.requests.get",
            return_value=_mock_pdf_response(pdf_bytes),
        ):
            items = adapter.fetch_agenda_items(_upcoming_meeting())
        assert all(i.video_timestamp_seconds is None for i in items)

    def test_items_carry_namespaced_external_ids(self):
        """Item external_ids should be unique per (event_id, item_number)."""
        adapter = _adapter()
        pdf_bytes = FIXTURE_PDF.read_bytes()
        with patch(
            "docket.adapters.granicus.requests.get",
            return_value=_mock_pdf_response(pdf_bytes),
        ):
            items = adapter.fetch_agenda_items(_upcoming_meeting())
        ids = [i.external_id for i in items]
        # Unique
        assert len(set(ids)) == len(ids)
        # All carry the event prefix + item number
        assert all("event-2692" in eid for eid in ids)
        assert items[0].external_id == "event-2692-1"
        assert items[1].external_id == "event-2692-2"

    def test_meeting_external_id_propagated(self):
        adapter = _adapter()
        pdf_bytes = FIXTURE_PDF.read_bytes()
        with patch(
            "docket.adapters.granicus.requests.get",
            return_value=_mock_pdf_response(pdf_bytes),
        ):
            items = adapter.fetch_agenda_items(_upcoming_meeting())
        assert all(i.meeting_external_id == "event-2692" for i in items)

    def test_http_target_is_agenda_url(self):
        """Adapter must request the AgendaViewer URL, not MediaPlayer."""
        adapter = _adapter()
        pdf_bytes = FIXTURE_PDF.read_bytes()
        with patch(
            "docket.adapters.granicus.requests.get",
            return_value=_mock_pdf_response(pdf_bytes),
        ) as mock_get:
            adapter.fetch_agenda_items(_upcoming_meeting())
        # The single GET should be against the agenda_url
        url = mock_get.call_args.args[0]
        assert "AgendaViewer.php" in url
        assert "event_id=2692" in url
        assert "MediaPlayer.php" not in url


class TestFetchAgendaItemsClipPathUntouched:
    """Existing MediaPlayer path for archived meetings must still work."""

    def test_clip_meeting_uses_media_player(self):
        adapter = _adapter()
        # A minimal MediaPlayer-like response with one index point
        html = (
            "<html><body>"
            "<div class=\"index-point\" time=\"123.5\" data-id=\"abc\">"
            "Roll Call"
            "</div>"
            "</body></html>"
        )
        resp = MagicMock()
        resp.text = html
        resp.raise_for_status = MagicMock(return_value=None)
        with patch(
            "docket.adapters.granicus.requests.get", return_value=resp
        ) as mock_get:
            items = adapter.fetch_agenda_items(_archive_meeting())
        # MediaPlayer URL was fetched, not AgendaViewer
        url = mock_get.call_args.args[0]
        assert "MediaPlayer.php" in url
        assert "clip_id=1980" in url
        # Item came through with its video timestamp
        assert len(items) == 1
        assert items[0].video_timestamp_seconds == 123.5
