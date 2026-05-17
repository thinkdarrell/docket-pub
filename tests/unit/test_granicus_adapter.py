"""Unit tests for GranicusAdapter parsing logic.

Covers the upcoming-meetings reconciliation path: event_id extraction,
event-id-based agenda URL builder, upcoming-row parser, and the
dual-table read in list_meetings (via _parse_publisher_page so HTTP
stays out of the unit suite).
"""

from datetime import date

from bs4 import BeautifulSoup

from docket.adapters.granicus import GranicusAdapter


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
