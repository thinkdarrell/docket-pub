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

        soup = BeautifulSoup(resp.text, "html.parser")

        archive_table = soup.find("table", id="archive")
        if not archive_table:
            tables = soup.find_all("table")
            archive_table = tables[1] if len(tables) > 1 else tables[0]

        rows = archive_table.find_all("tr", class_=re.compile(r"^(even|odd)$"))
        logger.info("Found %d meeting rows", len(rows))

        meetings = []
        for row in rows:
            meeting = self._parse_meeting_row(row)
            if meeting is None:
                continue
            if since and meeting.meeting_date < since:
                continue
            meetings.append(meeting)

        logger.info("Parsed %d meetings", len(meetings))
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
                        is_consent=_is_consent_item(description),
                        sponsor=None,
                    )
                )

        time.sleep(self.delay)
        return items

    def fetch_minutes_text(self, meeting: RawMeeting) -> str | None:
        """Fetch minutes text if available. Returns None if not available."""
        if meeting.minutes_url is None:
            return None

        try:
            resp = requests.get(meeting.minutes_url, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            content = soup.find("div", id="minutes-content") or soup.find("body")
            return content.get_text(separator="\n", strip=True) if content else None
        except requests.RequestException as e:
            logger.warning("Failed to fetch minutes for %s: %s", meeting.external_id, e)
            return None

    def fetch_votes(self, meeting: RawMeeting) -> list[RawVote]:
        """Granicus doesn't expose structured votes via HTML.

        Vote data for Granicus comes from video OCR (handled separately by
        the analysis pipeline). This method returns an empty list.
        """
        return []

    # --- Row parsing --------------------------------------------------------

    def _parse_meeting_row(self, row) -> RawMeeting | None:
        """Extract meeting data from a single HTML table row."""
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
        has_video = bool(row.find("a", onclick=re.compile(r"MediaPlayer")))

        # Build URLs
        video_url = None
        mp4_link = row.find("a", href=re.compile(r"archive-video\.granicus\.com"))
        if mp4_link:
            video_url = mp4_link["href"]
        elif has_video:
            video_url = self._download_url(clip_id)

        agenda_url = self._agenda_url(clip_id) if has_agenda else None
        minutes_url = self._minutes_url(clip_id) if has_minutes else None

        return RawMeeting(
            external_id=str(clip_id),
            municipality_slug=self.municipality_slug,
            title=title,
            meeting_date=meeting_date,
            meeting_type=_classify_meeting(title),
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


# --- Helpers ----------------------------------------------------------------


def _classify_meeting(title: str) -> str:
    """Classify meeting type from its title."""
    t = title.lower()
    if "regular" in t:
        return "council"
    if "special" in t or "called" in t:
        return "special"
    if "budget" in t:
        return "council"
    if "work session" in t:
        return "work_session"
    if "committee" in t:
        return "committee"
    if "planning" in t or "bza" in t or "zoning" in t:
        return "planning"
    return "council"


def _is_consent_item(description: str) -> bool:
    """Guess if an agenda item is part of the consent agenda."""
    d = description.lower()
    return "consent" in d
