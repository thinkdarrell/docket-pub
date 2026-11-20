"""CivicClerk platform adapter.

Scrapes meeting data from the CivicClerk API (used by Vestavia Hills, Mobile,
and other Alabama cities). Implements MunicipalSourceAdapter protocol.

API pattern: https://{tenant}.api.civicclerk.com/v1/
No authentication required for public read endpoints.

Config keys (stored in municipalities.adapter_config):
    tenant:       e.g. "vestaviahillsal"
    category_id:  e.g. 26  (city council event category)
    delay:        seconds between requests (default 1.0; never below 1.0,
                  whatever the row says)

Events are listed by following the server's own next-page link
(``@odata.nextLink``) to the last page. ``$top`` and ``$skip`` are never sent:
the server pages at 15 rows whatever is asked, and ``$top`` is a total, so a
walk under ``$top=100`` stops at 100 rows.
"""

from __future__ import annotations

import html
import logging
import re
import time
from datetime import date, datetime, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import requests

from docket.adapters._helpers import classify_meeting, is_consent_item
from docket.models.protocol import RawAgendaItem, RawMeeting, RawVote

logger = logging.getLogger(__name__)

CENTRAL = ZoneInfo("America/Chicago")

# Polite-delay floor, in seconds (GOALS.md Constraints).
MIN_DELAY = 1.0
# (connect, read) limits for every request, in seconds.
REQUEST_TIMEOUT = (10, 30)
# A request is tried this many times before it is an error.
MAX_ATTEMPTS = 3
# A listing longer than this many pages is an error, not a loop.
MAX_PAGES = 200


class CivicClerkAdapter:
    """Adapter for cities using the CivicClerk CMS."""

    def __init__(self, municipality_slug: str, config: dict):
        self.municipality_slug = municipality_slug
        self.tenant = config["tenant"]
        self.category_id = config.get("category_id")  # None = all categories
        self.delay = max(MIN_DELAY, float(config.get("delay", MIN_DELAY)))
        self.base_url = f"https://{self.tenant}.api.civicclerk.com/v1"
        self._session = requests.Session()
        # Event id -> the id of the event's agenda record, as last listed.
        # An agenda is a separate record with its own number; 0 means none yet.
        self._agenda_ids: dict[str, int] = {}

    # --- URL builders -------------------------------------------------------

    def _portal_url(self, event_id: int | str) -> str:
        return f"https://{self.tenant}.portal.civicclerk.com/event/{event_id}"

    def _agenda_portal_url(self, event_id: int | str) -> str:
        return f"https://{self.tenant}.portal.civicclerk.com/event/{event_id}/agenda"

    def _file_url(self, file_id: int | str) -> str:
        """The city's own file (a PDF), by the id the event's publishedFiles gives."""
        return f"{self.base_url}/Meetings/GetMeetingFileStream(fileId={file_id},plainText=false)"

    # --- HTTP helper --------------------------------------------------------

    def _get(self, endpoint: str, params: dict | None = None) -> dict | list:
        """One GET, tried up to three times.

        ``endpoint`` is either a path under the base address (sent with
        ``params``) or a full address, such as a next-page link, which is
        requested exactly as given with no params.

        A failure is a connection error or timeout, a status the server
        rejects with, or a body that is empty or is not JSON. After the first
        failure the adapter waits its delay, after the second twice its delay,
        and after the third it raises ``requests.RequestException``. A failed
        request is never an empty answer.
        """
        if endpoint.startswith(("https://", "http://")):
            url = endpoint
            params = None
        else:
            url = f"{self.base_url}/{endpoint}"

        last_error: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            if attempt:
                time.sleep(self.delay * attempt)
            try:
                resp = self._session.get(url, params=params, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                if not resp.content:
                    raise requests.RequestException("empty body")
                try:
                    return resp.json()
                except ValueError as e:
                    raise requests.RequestException(f"body is not JSON: {e}") from e
            except requests.RequestException as e:
                last_error = e
                logger.warning(
                    "CivicClerk request failed (attempt %d of %d) for %s: %s",
                    attempt + 1, MAX_ATTEMPTS, url, e,
                )
        raise requests.RequestException(
            f"CivicClerk request failed after {MAX_ATTEMPTS} attempts: {url}: {last_error}"
        ) from last_error

    def _check_next_link(self, link: str) -> None:
        """Refuse a next-page link that does not lead back to this adapter's own address."""
        parts = urlsplit(link)
        base = urlsplit(self.base_url)
        if (
            parts.scheme != "https"
            or parts.netloc.lower() != base.netloc.lower()
            or not parts.path.startswith(base.path + "/")
        ):
            raise ValueError(
                f"CivicClerk next-page link is not under {self.base_url}: {link!r}"
            )

    # --- Protocol methods ---------------------------------------------------

    def list_meetings(self, since: date | None = None) -> list[RawMeeting]:
        """List every event of the configured category, on or after ``since`` when given.

        The date filter is applied by the server, so a floor costs no extra
        pages. Pages are walked by the server's next-page link, each requested
        exactly as given, after the delay.
        """
        params: dict = {
            "$orderby": "eventDate desc",
            "$count": "true",
        }
        filters = []
        if self.category_id:
            filters.append(f"eventCategoryId eq {self.category_id}")
        if since:
            filters.append(f"eventDate ge {since.isoformat()}T00:00:00Z")
        if filters:
            params["$filter"] = " and ".join(filters)

        logger.info("Fetching events from %s (filter: %s)", self.base_url, params.get("$filter"))
        data = self._get("Events", params)
        all_events = list(data.get("value", []))
        pages = 1

        next_link = data.get("@odata.nextLink")
        while next_link:
            if pages >= MAX_PAGES:
                raise ValueError(
                    f"CivicClerk listing for {self.municipality_slug} "
                    f"did not end after {MAX_PAGES} pages"
                )
            self._check_next_link(next_link)
            time.sleep(self.delay)
            data = self._get(next_link)
            all_events.extend(data.get("value", []))
            pages += 1
            next_link = data.get("@odata.nextLink")

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
        event_id = event.get("id")
        if event_id is None:
            event_id = event.get("eventId")
        if event_id is None:
            return None
        self._agenda_ids[str(event_id)] = int(event.get("agendaId") or 0)

        event_date_str = event.get("eventDate", "")
        meeting_date = None
        start_time = None
        if event_date_str:
            # Accepts both 'YYYY-MM-DD' and ISO 8601 datetime ('YYYY-MM-DDTHH:MM:SS(.fff)?(Z|±HH:MM)?').
            # CivicClerk's eventDate is the posted local time with a false 'Z': the city's
            # minutes say "10:30 a.m." for an eventDate of 10:30:00Z. The 'Z' is dropped and
            # the time read as the city's wall clock. A numeric offset, never observed, is
            # still converted to America/Chicago so start_time is always CT wall-clock.
            try:
                if "T" in event_date_str:
                    wall = event_date_str[:-1] if event_date_str[-1] in "Zz" else event_date_str
                    dt = datetime.fromisoformat(wall)
                    if dt.tzinfo is not None:
                        dt = dt.astimezone(CENTRAL)
                    meeting_date = dt.date()
                    start_time = dt.time().replace(microsecond=0)
                else:
                    meeting_date = datetime.strptime(event_date_str[:10], "%Y-%m-%d").date()
            except ValueError:
                pass
        if meeting_date is None:
            meeting_date = date.today()

        title = event.get("eventName") or event.get("name") or ""

        # The agenda link is the city's own Agenda file when the event has one,
        # and otherwise the portal page when the event says it has an agenda.
        agenda_url = None
        agenda_file = self._latest_file(event, "Agenda")
        if agenda_file is not None:
            agenda_url = self._file_url(agenda_file["fileId"])
        elif event.get("hasAgenda"):
            agenda_url = self._agenda_portal_url(event_id)

        # The minutes link is the city's own Minutes file, and only for an event
        # the city entered on or before its own date. An event created after its
        # date is an after-the-fact import, and the Minutes file attached to one
        # is often another meeting's (docs/PRINCIPLES.md, "Source or silence").
        minutes_url = None
        minutes_file = self._latest_file(event, "Minutes")
        if minutes_file is not None and not self._is_imported(event):
            minutes_url = self._file_url(minutes_file["fileId"])

        return RawMeeting(
            external_id=str(event_id),
            municipality_slug=self.municipality_slug,
            title=title,
            meeting_date=meeting_date,
            meeting_type=classify_meeting(title),
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            video_url=None,
            source_url=self._portal_url(event_id),
            start_time=start_time,
        )

    @staticmethod
    def _latest_file(event: dict, file_type: str) -> dict | None:
        """The event's published file of one type: the latest published, the
        higher file id deciding a tie. None when it has no such file."""
        files = [
            entry
            for entry in (event.get("publishedFiles") or [])
            if entry.get("type") == file_type and entry.get("fileId")
        ]
        if not files:
            return None
        return max(
            files,
            key=lambda entry: (entry.get("publishOn") or "", int(entry.get("fileId") or 0)),
        )

    @staticmethod
    def _is_imported(event: dict) -> bool:
        """True unless the event was created on or before its own date.

        ``createdOn`` is a true UTC time; it is turned into its America/Chicago
        date before it is compared with the date of ``eventDate``, which is
        already the city's wall clock. The fraction of a second is cut off
        first: the city prints it with one to three digits and Python 3.10's
        ``fromisoformat`` refuses two. An event with no readable ``createdOn``
        or ``eventDate`` is treated as imported, so it gets no minutes link.
        """
        try:
            created = (
                datetime.strptime(str(event.get("createdOn") or "")[:19], "%Y-%m-%dT%H:%M:%S")
                .replace(tzinfo=timezone.utc)
                .astimezone(CENTRAL)
                .date()
            )
            held = date.fromisoformat(str(event.get("eventDate") or "")[:10])
        except ValueError:
            return True
        return created > held

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
