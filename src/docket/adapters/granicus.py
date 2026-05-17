"""Granicus platform adapter.

Scrapes meeting data from Granicus publisher pages (used by Birmingham and
potentially other Alabama cities). Implements MunicipalSourceAdapter protocol.

Config keys (stored in municipalities.adapter_config):
    base_url:  e.g. "https://bhamal.granicus.com"
    view_id:   e.g. 2
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime, timezone

import requests
from bs4 import BeautifulSoup

from docket.adapters._helpers import classify_meeting, is_consent_item
from docket.analysis.minutes_parser import (
    download_minutes_pdf,
    extract_text_from_pdf,
    parse_minutes,
)
from docket.models.protocol import RawAgendaItem, RawMeeting, RawVote

logger = logging.getLogger(__name__)


class GranicusAdapter:
    """Adapter for cities using the Granicus CMS."""

    def __init__(self, municipality_slug: str, config: dict):
        self.municipality_slug = municipality_slug
        self.base_url = config["base_url"]
        self.view_id = config["view_id"]
        self.delay = config.get("delay", 1.0)

    # --- URL builders -------------------------------------------------------

    def _publisher_url(self) -> str:
        return f"{self.base_url}/ViewPublisher.php?view_id={self.view_id}"

    def _player_url(self, clip_id: int) -> str:
        return f"{self.base_url}/MediaPlayer.php?view_id={self.view_id}&clip_id={clip_id}"

    def _agenda_url(self, clip_id: int) -> str:
        return f"{self.base_url}/AgendaViewer.php?view_id={self.view_id}&clip_id={clip_id}"

    def _agenda_url_by_event_id(self, event_id: int) -> str:
        return f"{self.base_url}/AgendaViewer.php?view_id={self.view_id}&event_id={event_id}"

    def _minutes_url(self, clip_id: int) -> str:
        return f"{self.base_url}/MinutesViewer.php?view_id={self.view_id}&clip_id={clip_id}"

    def _download_url(self, clip_id: int) -> str:
        return f"{self.base_url}/DownloadFile.php?view_id={self.view_id}&clip_id={clip_id}"

    def _source_url(self, clip_id: int) -> str:
        return f"{self.base_url}/player/clip/{clip_id}?view_id={self.view_id}"

    # --- Protocol methods ---------------------------------------------------

    def list_meetings(self, since: date | None = None) -> list[RawMeeting]:
        """Scrape the Granicus publisher page for all meeting rows."""
        logger.info("Fetching %s ...", self._publisher_url())
        resp = requests.get(self._publisher_url(), timeout=60)
        resp.raise_for_status()
        return self._parse_publisher_page(resp.text, since=since)

    def _parse_publisher_page(
        self, html: str, since: date | None = None
    ) -> list[RawMeeting]:
        """Parse a Granicus ViewPublisher page into RawMeetings.

        Reads both the `#upcoming` table (events not yet recorded — keyed
        by event_id) and the `#archive` table (recorded meetings — keyed
        by clip_id). Returns the union. Split from list_meetings so unit
        tests can exercise parsing without HTTP.
        """
        soup = BeautifulSoup(html, "html.parser")
        row_pattern = re.compile(r"^(even|odd)$")
        meetings: list[RawMeeting] = []

        upcoming_table = soup.find("table", id="upcoming")
        if upcoming_table:
            for row in upcoming_table.find_all("tr", class_=row_pattern):
                meeting = self._parse_upcoming_row(row)
                if meeting is None:
                    continue
                if since and meeting.meeting_date < since:
                    continue
                meetings.append(meeting)

        archive_table = soup.find("table", id="archive")
        if not archive_table:
            tables = soup.find_all("table")
            archive_table = tables[1] if len(tables) > 1 else (tables[0] if tables else None)

        if archive_table:
            for row in archive_table.find_all("tr", class_=row_pattern):
                meeting = self._parse_archive_row(row)
                if meeting is None:
                    continue
                if since and meeting.meeting_date < since:
                    continue
                meetings.append(meeting)

        logger.info("Parsed %d meetings (both tables)", len(meetings))
        return meetings

    def fetch_agenda_items(self, meeting: RawMeeting) -> list[RawAgendaItem]:
        """Fetch agenda item index points from the player page."""
        clip_id = int(meeting.external_id)
        url = self._player_url(clip_id)

        resp = requests.get(url, timeout=30)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        index_points = soup.find_all("div", class_="index-point")

        items = []
        for i, point in enumerate(index_points):
            timestamp = point.get("time")
            meta_id = point.get("data-id")
            description = point.get_text(strip=True)

            if timestamp is not None:
                items.append(
                    RawAgendaItem(
                        external_id=meta_id or f"{clip_id}-{i}",
                        meeting_external_id=meeting.external_id,
                        item_number=str(i + 1),
                        title=description,
                        description=None,
                        section=None,
                        is_consent=is_consent_item(description),
                        sponsor=None,
                        video_timestamp_seconds=float(timestamp),
                    )
                )

        time.sleep(self.delay)
        return items

    def fetch_minutes_text(self, meeting: RawMeeting) -> str | None:
        """Download minutes PDF and extract text."""
        if meeting.minutes_url is None:
            return None

        pdf_bytes = download_minutes_pdf(meeting.minutes_url)
        if pdf_bytes is None:
            return None

        text = extract_text_from_pdf(pdf_bytes)
        time.sleep(self.delay)
        return text or None

    def fetch_votes(self, meeting: RawMeeting) -> list[RawVote]:
        """Extract votes from minutes PDF.

        Downloads the minutes PDF, parses attendance and vote records,
        and returns RawVote objects with member positions.
        """
        if meeting.minutes_url is None:
            return []

        pdf_bytes = download_minutes_pdf(meeting.minutes_url)
        if pdf_bytes is None:
            return []

        text = extract_text_from_pdf(pdf_bytes)
        if not text:
            return []

        result = parse_minutes(text)
        time.sleep(self.delay)

        raw_votes = []
        for i, vote in enumerate(result.votes):
            member_votes = []
            for name in vote.ayes:
                member_votes.append({"member": name, "vote": "yea"})
            for name in vote.nays:
                member_votes.append({"member": name, "vote": "nay"})
            for name in vote.abstentions:
                member_votes.append({"member": name, "vote": "abstain"})

            # Mark absent members from attendance record
            if result.attendance:
                # Use the last attendance record (regular meeting, not pre-council)
                att = result.attendance[-1]
                voted_names = {n for n in vote.ayes + vote.nays + vote.abstentions}
                for name in att.absent:
                    if name not in voted_names:
                        member_votes.append({"member": name, "vote": "absent"})

            raw_votes.append(
                RawVote(
                    external_id=f"{meeting.external_id}-vote-{i + 1}",
                    meeting_external_id=meeting.external_id,
                    agenda_item_external_id=None,
                    result=vote.result,
                    yeas=len(vote.ayes),
                    nays=len(vote.nays),
                    abstentions=len(vote.abstentions),
                    member_votes=member_votes,
                    source="minutes_text",
                    confidence="high",
                    resolution_number=vote.resolution_number,
                    match_context=vote.context[-200:] if vote.context else None,
                    raw_text=vote.raw_text or None,
                )
            )

        logger.info(
            "Parsed %d votes from minutes for %s (%s)",
            len(raw_votes),
            meeting.external_id,
            meeting.meeting_date,
        )
        return raw_votes

    # --- Row parsing --------------------------------------------------------

    def _parse_archive_row(self, row) -> RawMeeting | None:
        """Extract meeting data from a single archived-table row (has clip_id)."""
        cells = row.find_all("td")
        if len(cells) < 4:
            return None

        # Title
        name_cell = row.find("td", headers="Name")
        title = name_cell.get_text(strip=True) if name_cell else ""

        # Date
        date_cell = row.find("td", headers="Date")
        meeting_date = None
        if date_cell:
            hidden_span = date_cell.find("span", style=re.compile(r"display:\s*none"))
            if hidden_span:
                try:
                    ts = int(hidden_span.get_text(strip=True))
                    meeting_date = datetime.fromtimestamp(ts, tz=timezone.utc).date()
                except (ValueError, OSError):
                    pass
            if not meeting_date:
                date_text = date_cell.get_text(strip=True)
                try:
                    meeting_date = datetime.strptime(date_text, "%m/%d/%Y").date()
                except ValueError:
                    pass

        if meeting_date is None:
            logger.warning("Could not parse date for meeting '%s', using today", title)
            meeting_date = date.today()

        # Extract clip_id from any link
        clip_id = self._extract_clip_id(row)
        if not clip_id:
            return None

        # Check for document links
        has_agenda = bool(
            row.find("td", headers="Agenda") and row.find("td", headers="Agenda").find("a")
        )
        has_minutes = bool(
            row.find("td", headers="Minutes") and row.find("td", headers="Minutes").find("a")
        )
        # Two ways the publisher row can advertise a video: a MediaPlayer onclick,
        # or a direct .mp4 link to archive-video.granicus.com. Either way, we link
        # the citizen UI to the player page — direct .mp4 / DownloadFile.php URLs
        # trigger a browser download instead of embedded playback.
        has_video = (
            bool(row.find("a", onclick=re.compile(r"MediaPlayer")))
            or bool(row.find("a", href=re.compile(r"archive-video\.granicus\.com")))
        )

        # Build URLs
        video_url = self._player_url(clip_id) if has_video else None

        agenda_url = self._agenda_url(clip_id) if has_agenda else None
        minutes_url = self._minutes_url(clip_id) if has_minutes else None

        return RawMeeting(
            external_id=str(clip_id),
            municipality_slug=self.municipality_slug,
            title=title,
            meeting_date=meeting_date,
            meeting_type=classify_meeting(title),
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            video_url=video_url,
            source_url=self._source_url(clip_id),
        )

    @staticmethod
    def _extract_clip_id(row) -> int | None:
        """Find a clip_id in any link in the row."""
        for link in row.find_all("a", href=True):
            match = re.search(r"clip_id=(\d+)", link["href"])
            if match:
                return int(match.group(1))
        for link in row.find_all("a", onclick=True):
            match = re.search(r"clip_id=(\d+)", link["onclick"])
            if match:
                return int(match.group(1))
        return None

    @staticmethod
    def _extract_event_id(row) -> int | None:
        """Find an event_id in any link in the row.

        Upcoming-table rows reference meetings by event_id rather than
        clip_id (the latter is assigned only when a recording exists).
        Mirrors _extract_clip_id's two-pass href/onclick search.
        """
        for link in row.find_all("a", href=True):
            match = re.search(r"event_id=(\d+)", link["href"])
            if match:
                return int(match.group(1))
        for link in row.find_all("a", onclick=True):
            match = re.search(r"event_id=(\d+)", link["onclick"])
            if match:
                return int(match.group(1))
        return None

    def _parse_upcoming_row(self, row) -> RawMeeting | None:
        """Extract meeting data from a single upcoming-table row (has event_id).

        Returns None if no event_id is present — e.g., placeholder rows where
        the agenda hasn't been published yet.

        Upcoming meetings carry an `event-{event_id}` external_id, which the
        ingest reconciliation step will later upgrade to a plain clip_id
        string once the meeting is recorded and migrates to the archive table.
        """
        event_id = self._extract_event_id(row)
        if not event_id:
            return None

        title_cell = row.find("td", headers=re.compile(r"^EventName"))
        title = title_cell.get_text(strip=True) if title_cell else ""

        date_cell = row.find("td", headers=re.compile(r"^EventDate"))
        meeting_date = None
        if date_cell:
            hidden_span = date_cell.find("span", style=re.compile(r"display:\s*none"))
            if hidden_span:
                try:
                    ts = int(hidden_span.get_text(strip=True))
                    meeting_date = datetime.fromtimestamp(ts, tz=timezone.utc).date()
                except (ValueError, OSError):
                    pass

        if meeting_date is None:
            logger.warning(
                "Could not parse date for upcoming meeting '%s', using today", title
            )
            meeting_date = date.today()

        agenda_url = self._agenda_url_by_event_id(event_id)

        return RawMeeting(
            external_id=f"event-{event_id}",
            municipality_slug=self.municipality_slug,
            title=title,
            meeting_date=meeting_date,
            meeting_type=classify_meeting(title),
            agenda_url=agenda_url,
            minutes_url=None,
            video_url=None,
            source_url=agenda_url,
        )


