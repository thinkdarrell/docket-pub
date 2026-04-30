"""Generic CMS adapter for cities using simple website builders.

Scrapes meeting document links (agenda/minutes PDFs) from a single archive
page. Dates are extracted from filenames using the MMDDYY prefix convention.

Currently used by Homewood, AL.

Implements MunicipalSourceAdapter protocol.

Config keys (stored in municipalities.adapter_config):
    archive_url:   e.g. "https://www.cityofhomewood.com/city-council-archives"
    video_channel: optional YouTube channel URL
    delay:         seconds between requests (default 1.0)
"""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from datetime import date
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup

from docket.adapters._helpers import classify_meeting
from docket.models.protocol import RawAgendaItem, RawMeeting, RawVote

logger = logging.getLogger(__name__)

# Matches MMDDYY at the start of a filename (after URL decoding and stripping path)
_DATE_RE = re.compile(r"^(\d{2})\s*(\d{2})\s*(\d{2})")


class GenericCMSAdapter:
    """Adapter for cities that publish agenda/minutes PDFs on a simple archive page."""

    def __init__(self, municipality_slug: str, config: dict):
        self.municipality_slug = municipality_slug
        # Support both single URL and list of URLs
        if "archive_urls" in config:
            self.archive_urls = config["archive_urls"]
        else:
            self.archive_urls = [config["archive_url"]]
        self.video_channel = config.get("video_channel")
        self.delay = config.get("delay", 1.0)

    # --- Protocol methods ---------------------------------------------------

    def list_meetings(self, since: date | None = None) -> list[RawMeeting]:
        """Scrape archive pages for PDF links, group by meeting date."""
        all_links = []

        for archive_url in self.archive_urls:
            logger.info("Fetching archive page: %s", archive_url)
            try:
                resp = requests.get(
                    archive_url,
                    headers={"User-Agent": "Mozilla/5.0 (docket.pub civic data scraper)"},
                    timeout=30,
                )
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")
                links = soup.find_all("a", href=lambda h: h and ".pdf" in h.lower())
                # Tag each link with its source archive for context
                for link in links:
                    all_links.append((link, archive_url))
                logger.info("  Found %d PDF links", len(links))
            except requests.RequestException as e:
                logger.warning("Failed to fetch %s: %s", archive_url, e)

            if len(self.archive_urls) > 1:
                time.sleep(self.delay)

        links = all_links
        logger.info("Found %d total PDF links across %d archives", len(links), len(self.archive_urls))

        # Group links by meeting date + source archive
        meeting_groups: dict[str, dict] = defaultdict(lambda: {
            "meeting_date": None,
            "title": "Meeting",
            "agenda_url": None,
            "minutes_url": None,
            "video_url": None,
            "source_url": None,
        })

        for link, archive_url in links:
            href = link["href"]
            link_text = link.get_text(strip=True).upper()
            filename = unquote(href.split("/")[-1])

            meeting_date = self._parse_date_from_filename(filename)
            if meeting_date is None:
                continue
            if since and meeting_date < since:
                continue

            # Derive meeting body from archive URL path
            body = self._archive_body_name(archive_url)

            # Use body + date as key so different bodies on same date stay separate
            key = f"{meeting_date.isoformat()}-{body}"
            group = meeting_groups[key]
            group["meeting_date"] = meeting_date
            group["source_url"] = archive_url

            # Detect meeting title from archive body and filename
            fn_lower = filename.lower()
            if "special" in fn_lower:
                group["title"] = f"Special Called {body}"
            elif group["title"] == "Meeting":
                group["title"] = body

            # Assign URL by link text
            if "AGENDA" in link_text:
                group["agenda_url"] = href
            elif "MINUTE" in link_text or "INUTE" in link_text:
                group["minutes_url"] = href

        # Convert to RawMeeting objects
        meetings = []
        for key, group in sorted(meeting_groups.items(), reverse=True):
            title = group["title"]
            meetings.append(
                RawMeeting(
                    external_id=key,  # date as external_id (unique per city per date)
                    municipality_slug=self.municipality_slug,
                    title=title,
                    meeting_date=group["meeting_date"],
                    meeting_type=classify_meeting(title),
                    agenda_url=group["agenda_url"],
                    minutes_url=group["minutes_url"],
                    video_url=group["video_url"],
                    source_url=group["source_url"] or self.archive_urls[0],
                )
            )

        logger.info("Parsed %d meetings from PDF links", len(meetings))
        return meetings

    def fetch_agenda_items(self, meeting: RawMeeting) -> list[RawAgendaItem]:
        """Agenda items require PDF parsing — deferred to Phase 4."""
        return []

    def fetch_minutes_text(self, meeting: RawMeeting) -> str | None:
        """Minutes are PDFs — text extraction deferred."""
        return None

    def fetch_votes(self, meeting: RawMeeting) -> list[RawVote]:
        """No structured vote data on generic CMS pages."""
        return []

    # --- Internal helpers ---------------------------------------------------

    @staticmethod
    def _archive_body_name(archive_url: str) -> str:
        """Derive a meeting body name from the archive page URL path.

        Examples:
            /city-council-archives -> "Council Meeting"
            /bza-archives -> "Board of Zoning Adjustment"
            /planning-commission-archives -> "Planning Commission"
            /finance-committee-archives -> "Finance Committee"
        """
        path = archive_url.rstrip("/").split("/")[-1]
        path = path.replace("-archives", "").replace("-2", "")

        body_map = {
            "city-council": "Council Meeting",
            "precouncil": "Pre-Council Work Session",
            "bza": "Board of Zoning Adjustment",
            "planning-commission": "Planning Commission",
            "finance-committee": "Finance Committee",
            "public-safety-committee": "Public Safety Committee",
            "public-works-committee": "Public Works Committee",
            "planning---development-committee": "Planning & Development Committee",
            "special-issues-committee": "Special Issues Committee",
            "library-board": "Library Board",
            "historic-preservation-commission": "Historic Preservation Commission",
            "abatement-board": "Abatement Board",
            "arts-council": "Arts Council",
            "beautification-board": "Beautification Board",
            "hec": "Homewood Environmental Commission",
        }

        return body_map.get(path, path.replace("-", " ").title())

    @staticmethod
    def _parse_date_from_filename(filename: str) -> date | None:
        """Extract a date from a filename with MMDDYY prefix.

        Handles variations like:
            042726+Council+Agenda.pdf  -> 2026-04-27
            03+23+26+Council+Agenda.pdf -> 2026-03-23
            051925_Council_Agenda_.pdf -> 2025-05-19
            040824 Council Agenda .pdf -> 2024-04-08
        """
        # Strip common prefixes and clean up
        name = filename.replace("+", " ").replace("_", " ").replace("%20", " ").strip()

        # Try to extract 6 digits (MMDDYY) from the start, allowing spaces
        match = _DATE_RE.match(name)
        if not match:
            return None

        mm, dd, yy = match.groups()
        try:
            month = int(mm)
            day = int(dd)
            year = 2000 + int(yy)
            return date(year, month, day)
        except ValueError:
            return None
