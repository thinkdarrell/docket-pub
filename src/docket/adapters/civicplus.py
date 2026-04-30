"""CivicPlus platform adapter.

Scrapes meeting data from CivicPlus AgendaCenter pages (used by Hoover and
other Alabama cities). Uses the civic-scraper library to handle the
AJAX-heavy CivicPlus frontend.

Implements MunicipalSourceAdapter protocol.

Config keys (stored in municipalities.adapter_config):
    site_url:  e.g. "https://hooveralabama.gov/AgendaCenter"
    delay:     seconds between requests (default 1.0)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date

from civic_scraper.platforms import CivicPlusSite

from docket.adapters._helpers import classify_meeting
from docket.models.protocol import RawAgendaItem, RawMeeting, RawVote

logger = logging.getLogger(__name__)


class CivicPlusAdapter:
    """Adapter for cities using the CivicPlus CMS."""

    def __init__(self, municipality_slug: str, config: dict):
        self.municipality_slug = municipality_slug
        self.site_url = config["site_url"]
        self.delay = config.get("delay", 1.0)

    # --- Protocol methods ---------------------------------------------------

    def list_meetings(self, since: date | None = None) -> list[RawMeeting]:
        """Scrape the CivicPlus AgendaCenter for meeting assets.

        civic-scraper returns individual assets (agenda PDF, minutes PDF, etc.)
        grouped by meeting. We group these by meeting_id + meeting_date into
        deduplicated RawMeeting objects.
        """
        logger.info("Scraping CivicPlus site: %s", self.site_url)

        site = CivicPlusSite(self.site_url)
        kwargs = {}
        if since:
            kwargs["start_date"] = since.strftime("%Y-%m-%d")

        assets = site.scrape(**kwargs)
        logger.info("Found %d assets from CivicPlus", len(assets))

        # Group assets by meeting (using meeting_id or date + committee)
        meeting_groups: dict[str, dict] = defaultdict(lambda: {
            "title": "",
            "meeting_date": None,
            "agenda_url": None,
            "minutes_url": None,
            "video_url": None,
            "source_url": None,
            "committee": None,
        })

        for asset in assets:
            meeting_date = asset.meeting_date.date() if asset.meeting_date else None
            if since and meeting_date and meeting_date < since:
                continue

            # Build a grouping key from meeting_id or date + committee
            key = asset.meeting_id or f"{meeting_date}-{asset.committee_name or 'unknown'}"
            group = meeting_groups[key]

            group["meeting_date"] = meeting_date or group["meeting_date"]
            group["committee"] = asset.committee_name or group["committee"]

            if not group["title"] and asset.committee_name:
                group["title"] = asset.committee_name

            # Assign URL by asset type
            asset_type = (asset.asset_type or "").lower()
            if "agenda" in asset_type and asset.url:
                group["agenda_url"] = asset.url
            elif "minutes" in asset_type and asset.url:
                group["minutes_url"] = asset.url
            elif ("video" in asset_type or "audio" in asset_type) and asset.url:
                group["video_url"] = asset.url

            if asset.url and not group["source_url"]:
                group["source_url"] = asset.url

        # Convert groups to RawMeeting objects
        meetings = []
        for key, group in meeting_groups.items():
            title = group["title"] or "Meeting"
            meetings.append(
                RawMeeting(
                    external_id=str(key),
                    municipality_slug=self.municipality_slug,
                    title=title,
                    meeting_date=group["meeting_date"] or date.today(),
                    meeting_type=classify_meeting(title),
                    agenda_url=group["agenda_url"],
                    minutes_url=group["minutes_url"],
                    video_url=group["video_url"],
                    source_url=group["source_url"] or self.site_url,
                )
            )

        logger.info("Parsed %d meetings from %d assets", len(meetings), len(assets))
        return meetings

    def fetch_agenda_items(self, meeting: RawMeeting) -> list[RawAgendaItem]:
        """CivicPlus AgendaCenter provides documents, not structured items.

        Structured agenda items will come from PDF parsing in a later phase.
        """
        return []

    def fetch_minutes_text(self, meeting: RawMeeting) -> str | None:
        """Minutes are PDFs on CivicPlus — text extraction deferred."""
        return None

    def fetch_votes(self, meeting: RawMeeting) -> list[RawVote]:
        """CivicPlus doesn't provide structured vote data."""
        return []
