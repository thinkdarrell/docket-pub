"""CivicClerk platform adapter.

Scrapes meeting data from the CivicClerk API (used by Vestavia Hills, Mobile,
and other Alabama cities). Implements MunicipalSourceAdapter protocol.

API pattern: https://{tenant}.api.civicclerk.com/v1/
No authentication required for public read endpoints.

Config keys (stored in municipalities.adapter_config):
    tenant:       e.g. "vestaviahillsal"
    category_id:  e.g. 26  (city council event category)
    delay:        seconds between requests (default 0.5)
"""

from __future__ import annotations

import html
import logging
import re
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests

from docket.adapters._helpers import classify_meeting, is_consent_item
from docket.models.protocol import RawAgendaItem, RawMeeting, RawVote

logger = logging.getLogger(__name__)


class CivicClerkAdapter:
    """Adapter for cities using the CivicClerk CMS."""

    def __init__(self, municipality_slug: str, config: dict):
        self.municipality_slug = municipality_slug
        self.tenant = config["tenant"]
        self.category_id = config.get("category_id")  # None = all categories
        self.delay = config.get("delay", 0.5)
        self.base_url = f"https://{self.tenant}.api.civicclerk.com/v1"

    # --- URL builders -------------------------------------------------------

    def _portal_url(self, event_id: int | str) -> str:
        return f"https://{self.tenant}.portal.civicclerk.com/event/{event_id}"

    def _agenda_portal_url(self, event_id: int | str) -> str:
        return f"https://{self.tenant}.portal.civicclerk.com/event/{event_id}/agenda"

    def _minutes_portal_url(self, event_id: int | str) -> str:
        return f"https://{self.tenant}.portal.civicclerk.com/event/{event_id}/minutes"

    # --- HTTP helper --------------------------------------------------------

    def _get(self, endpoint: str, params: dict | None = None) -> dict | list:
        url = f"{self.base_url}/{endpoint}"
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    # --- Protocol methods ---------------------------------------------------

    def list_meetings(self, since: date | None = None) -> list[RawMeeting]:
        """Paginate through all events for the configured category."""
        all_events = []
        skip = 0
        page_size = 100

        while True:
            params: dict = {
                "$top": page_size,
                "$skip": skip,
                "$orderby": "eventDate desc",
                "$count": "true",
            }
            if self.category_id:
                params["$filter"] = f"eventCategoryId eq {self.category_id}"

            logger.info("Fetching events skip=%d from %s", skip, self.base_url)
            data = self._get("Events", params)
            events = data.get("value", [])
            total = data.get("@odata.count", len(events))
            all_events.extend(events)

            skip += page_size
            if skip >= total:
                break
            time.sleep(self.delay)

        logger.info("Found %d total events for %s", len(all_events), self.municipality_slug)

        meetings = []
        for event in all_events:
            meeting = self._event_to_meeting(event)
            if meeting is None:
                continue
            if since and meeting.meeting_date < since:
                continue
            meetings.append(meeting)

        logger.info("Parsed %d meetings", len(meetings))
        return meetings

    def fetch_agenda_items(self, meeting: RawMeeting) -> list[RawAgendaItem]:
        """Fetch and flatten hierarchical agenda items for a meeting."""
        event_id = meeting.external_id

        try:
            data = self._get(f"Meetings/{event_id}")
        except requests.RequestException as e:
            logger.warning("Failed to fetch meeting detail for %s: %s", event_id, e)
            return []

        item_list = data.get("items") or data.get("meetingItems") or []
        items: list[RawAgendaItem] = []
        self._flatten_items(item_list, items, meeting.external_id, index=0)

        time.sleep(self.delay)
        return items

    def fetch_minutes_text(self, meeting: RawMeeting) -> str | None:
        """CivicClerk API doesn't expose minutes text directly."""
        return None

    def fetch_votes(self, meeting: RawMeeting) -> list[RawVote]:
        """CivicClerk doesn't provide structured vote data."""
        return []

    # --- Internal helpers ---------------------------------------------------

    def _event_to_meeting(self, event: dict) -> RawMeeting | None:
        """Convert a CivicClerk event dict to a RawMeeting."""
        event_id = event.get("eventId") or event.get("id")
        if event_id is None:
            return None

        event_date_str = event.get("eventDate", "")
        meeting_date = None
        start_time = None
        if event_date_str:
            # Accepts both 'YYYY-MM-DD' and ISO 8601 datetime ('YYYY-MM-DDTHH:MM:SS(.fff)?(Z|±HH:MM)?').
            # CivicClerk's eventDate is naive local time in practice; the Z/offset branch is defensive
            # — if the API ever returns a tz-aware datetime we normalize to America/Chicago before
            # extracting the clock time so start_time is always CT wall-clock.
            try:
                if "T" in event_date_str:
                    dt = datetime.fromisoformat(event_date_str.replace("Z", "+00:00"))
                    if dt.tzinfo is not None:
                        dt = dt.astimezone(ZoneInfo("America/Chicago"))
                    meeting_date = dt.date()
                    start_time = dt.time().replace(microsecond=0)
                else:
                    meeting_date = datetime.strptime(event_date_str[:10], "%Y-%m-%d").date()
            except ValueError:
                pass
        if meeting_date is None:
            meeting_date = date.today()

        title = event.get("eventName") or event.get("name") or ""
        has_agenda = bool(event.get("hasAgenda"))
        has_minutes = bool(event.get("hasMinutes"))

        return RawMeeting(
            external_id=str(event_id),
            municipality_slug=self.municipality_slug,
            title=title,
            meeting_date=meeting_date,
            meeting_type=classify_meeting(title),
            agenda_url=self._agenda_portal_url(event_id) if has_agenda else None,
            minutes_url=self._minutes_portal_url(event_id) if has_minutes else None,
            video_url=None,
            source_url=self._portal_url(event_id),
            start_time=start_time,
        )

    def _flatten_items(
        self,
        item_list: list[dict],
        result: list[RawAgendaItem],
        meeting_external_id: str,
        index: int = 0,
    ) -> int:
        """Recursively flatten hierarchical agenda items into a flat list."""
        for item in item_list:
            name = (
                item.get("agendaObjectItemName")
                or item.get("name")
                or item.get("itemName")
                or ""
            )
            desc = item.get("description") or ""
            item_number = (
                item.get("agendaObjectItemNumber")
                or item.get("itemNumber")
                or item.get("outlineNumber")
                or ""
            )

            # Strip HTML tags and entities
            name = html.unescape(re.sub(r"<[^>]+>", "", name)).strip()
            desc = html.unescape(re.sub(r"<[^>]+>", "", desc)).strip()

            full_title = f"{item_number} {name}".strip()
            truncated_desc = desc[:300] if desc else None

            # Detect section headers (not real agenda items)
            is_section = item.get("isSection") or (
                not item.get("agendaObjectItemNumber")
                and item.get("childItems")
                and len(item.get("childItems", [])) > 0
            )

            if not is_section and full_title:
                item_id = item.get("id") or item.get("itemId")
                result.append(
                    RawAgendaItem(
                        external_id=str(item_id) if item_id else f"{meeting_external_id}-{index}",
                        meeting_external_id=meeting_external_id,
                        item_number=str(item_number) if item_number else None,
                        title=full_title,
                        description=truncated_desc,
                        section=None,
                        is_consent=is_consent_item(full_title),
                        sponsor=None,
                    )
                )
                index += 1

            children = item.get("childItems") or item.get("children") or []
            if children:
                index = self._flatten_items(children, result, meeting_external_id, index)

        return index
