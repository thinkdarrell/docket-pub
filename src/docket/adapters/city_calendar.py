"""The city's own calendar page, read into ``CalendarEvent`` values.

A domain module: no database and no services import. Birmingham's council
page, https://www.birminghamal.gov/government/city-council, is a
server-rendered Next.js page whose ``<script id="__NEXT_DATA__">`` holds, at
``props.pageProps.nodeResource.events.results``, the upcoming events the
city lists (the council meeting and its committees' meetings). Each result
carries ``id``, ``title``, ``path``, ``startDate.time`` (an ISO instant in
UTC), ``endDate.time``, and ``eventCategories``; the title is the body's
name, the categories are not (the Transportation and Infrastructure
Committee's event carried the category "Public Safety Committee" on
2026-10-21), so the resolver reads the title and the categories are kept
only as what the page said.

The service layer (``docket.services.city_calendar``) fetches and stores;
this module parses. A missing or malformed block is an empty list and a
warning, never an exception: the city changing its page must not fail the
morning's worker run.

Plan: plans/active/meeting-types-name-the-body.md (M3).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# The same browser string services/archived_meetings.py sends; the city site
# answered a plain curl default too on 2026-10-21, so either works.
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

_NEXT_DATA_ID = "__NEXT_DATA__"


@dataclass(frozen=True)
class CalendarEvent:
    source_event_id: str
    title: str
    starts_at: datetime  # tz-aware, UTC as parsed
    ends_at: datetime | None
    source_url: str
    categories: tuple[str, ...]


def _instant(block: object) -> datetime | None:
    """``{"time": "2026-10-21T20:30:00+00:00", ...}`` to a tz-aware datetime, else None."""
    if not isinstance(block, dict):
        return None
    raw = block.get("time")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _category_names(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    names: list[str] = []
    for entry in raw:
        if isinstance(entry, dict) and isinstance(entry.get("name"), str):
            names.append(entry["name"])
    return tuple(names)


def parse_birminghamal_page(html: str, base_url: str) -> list[CalendarEvent]:
    """Every event in the page's ``__NEXT_DATA__`` block, in the page's order.

    ``base_url`` is the scheme and host the result paths are relative to
    (``https://www.birminghamal.gov``). Titles have their whitespace
    collapsed (the source has a double space in one). A result missing its
    id, title, or start instant is skipped with a warning; a page missing
    the block, or a block that is not the expected shape, yields ``[]``.
    """
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id=_NEXT_DATA_ID)
    if script is None:
        log.warning("city_calendar: no %s script in the page", _NEXT_DATA_ID)
        return []
    try:
        data = json.loads(script.string or "")
    except json.JSONDecodeError as e:
        log.warning("city_calendar: %s is not JSON: %s", _NEXT_DATA_ID, e)
        return []

    try:
        results = data["props"]["pageProps"]["nodeResource"]["events"]["results"]
    except (KeyError, TypeError):
        log.warning("city_calendar: %s has no props.pageProps.nodeResource.events.results", _NEXT_DATA_ID)
        return []
    if not isinstance(results, list):
        log.warning("city_calendar: events.results is not a list")
        return []

    base = base_url.rstrip("/")
    events: list[CalendarEvent] = []
    for result in results:
        if not isinstance(result, dict):
            log.warning("city_calendar: skipping a non-object result")
            continue
        source_event_id = result.get("id")
        title = result.get("title")
        path = result.get("path")
        starts_at = _instant(result.get("startDate"))
        if not isinstance(source_event_id, str) or not source_event_id or not isinstance(title, str) or starts_at is None:
            log.warning("city_calendar: skipping result without id, title, or start: %r", source_event_id)
            continue
        events.append(
            CalendarEvent(
                source_event_id=source_event_id,
                title=" ".join(title.split()),
                starts_at=starts_at,
                ends_at=_instant(result.get("endDate")),
                source_url=base + path if isinstance(path, str) and path else base,
                categories=_category_names(result.get("eventCategories")),
            )
        )
    return events


def fetch_birminghamal_events(url: str) -> list[CalendarEvent]:
    """One GET of the council page, parsed. Raises on a non-200 or a network failure."""
    resp = requests.get(url, timeout=60, headers={"User-Agent": _BROWSER_UA})
    resp.raise_for_status()
    parts = urlsplit(url)
    base_url = f"{parts.scheme}://{parts.netloc}"
    return parse_birminghamal_page(resp.text, base_url)
