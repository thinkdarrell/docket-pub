"""The city's own calendar, read into ``CalendarEvent`` values from three places.

A domain module: no database and no services import. Birmingham's council
page, https://www.birminghamal.gov/government/city-council, is a
server-rendered Next.js page whose ``<script id="__NEXT_DATA__">`` holds, at
``props.pageProps.nodeResource.events.results``, the next four events the
city lists (the council meeting and its committees' meetings). Each result
carries ``id``, ``title``, ``path``, ``startDate.time`` (an ISO instant in
UTC), ``endDate.time``, ``eventCategories``, and ``eventStatus``; the title
is the body's name, the categories are not (the Transportation and
Infrastructure Committee's event carried the category "Public Safety
Committee" on 2026-10-21), so the resolver reads the title and the
categories are kept only as what the page said.

The same result object comes from two other places (plan
`committee-clips-named-or-hidden`, M1). The site's events search,
``/api/search/events``, answers with every upcoming event of one department
at ``graphqlEventsSearchWww.results`` (ten to a page, ``pageInfo.total`` in
all, and no ``eventStatus``); it holds no past event. The sitemap,
``/sitemap.xml``, lists every event page the site still serves, past ones
included, and each event page holds its event at
``props.pageProps.nodeResource`` together with ``department.name``. Only
the sitemap reaches back, so the past calendar is read one event page at a
time, and only an event of the named department is returned: another
department's committee (the Framework Plan Implementation Committee is
Planning's) is not the council's.

Every request waits until one second has passed since this module's
previous one, which ``GOALS.md`` requires of a scraper.

The service layer (``docket.services.city_calendar``) fetches and stores;
this module parses. A missing or malformed block is an empty list and a
warning, never an exception: the city changing its page must not fail the
morning's worker run.

Plan: plans/completed/meeting-types-name-the-body.md (M3); the search,
sitemap, and event-page readers are plan `committee-clips-named-or-hidden`, M1.
"""

from __future__ import annotations

import html as html_entities
import json
import logging
import re
import time
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

_TIMEOUT_S = 60
# GOALS.md: polite delays of at least one second between requests to a city site.
_MIN_INTERVAL_S = 1.0
# The search is read page 0 upward; ten pages of ten is far above the five
# events it held on 2026-11-11 and bounds a response whose total is wrong.
SEARCH_MAX_PAGES = 10

# A sitemap entry is worth a fetch when it is an event page whose address
# names a council body or sitting. Other departments' committees pass this
# test and are rejected by the event page's own department.
_SITEMAP_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
_SITEMAP_WORDS = ("committee", "council-meeting", "work-session")
_PATH_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")

# monotonic time of this module's last request; None before the first
_last_request_at: float | None = None


@dataclass(frozen=True)
class CalendarEvent:
    source_event_id: str
    title: str
    starts_at: datetime  # tz-aware, UTC as parsed
    ends_at: datetime | None
    source_url: str
    categories: tuple[str, ...]
    # ``eventStatus`` as the source gave it ("active" on every event read so
    # far); None when the source carries none, as the search does.
    status: str | None = None


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
    (``https://www.birminghamal.gov``). Titles have their HTML entities
    unescaped, a guard, not a repair: the page's JSON has carried a plain
    ``&`` on every read so far (a 2026-11-07 reading of ``&amp;`` in
    production was an artifact of the terminal relay, not of the data),
    but a stored ``&amp;`` would defeat the committee-name match in
    ``docket.services.meeting_types``. Whitespace is collapsed (the source
    has a double space in one). A result missing its
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

    return _events_from_results(results, base_url)


def _event_from_result(result: object, base: str) -> CalendarEvent | None:
    """One result object to a ``CalendarEvent``; None, with a warning, when it lacks an id, title, or start.

    The council page, the events search, and an event page all describe an
    event with the same object, so all three readers come through here.
    ``base`` has no trailing slash.
    """
    if not isinstance(result, dict):
        log.warning("city_calendar: skipping a non-object result")
        return None
    source_event_id = result.get("id")
    title = result.get("title")
    path = result.get("path")
    status = result.get("eventStatus")
    starts_at = _instant(result.get("startDate"))
    if not isinstance(source_event_id, str) or not source_event_id or not isinstance(title, str) or starts_at is None:
        log.warning("city_calendar: skipping result without id, title, or start: %r", source_event_id)
        return None
    return CalendarEvent(
        source_event_id=source_event_id,
        title=" ".join(html_entities.unescape(title).split()),
        starts_at=starts_at,
        ends_at=_instant(result.get("endDate")),
        source_url=base + path if isinstance(path, str) and path else base,
        categories=_category_names(result.get("eventCategories")),
        status=status if isinstance(status, str) and status else None,
    )


def _events_from_results(results: list, base_url: str) -> list[CalendarEvent]:
    base = base_url.rstrip("/")
    events = [_event_from_result(result, base) for result in results]
    return [ev for ev in events if ev is not None]


def _department_name(result: object) -> str | None:
    if not isinstance(result, dict):
        return None
    department = result.get("department")
    if isinstance(department, dict) and isinstance(department.get("name"), str):
        return department["name"]
    return None


def parse_search_page(
    payload: dict, base_url: str, *, department: str | None = None
) -> tuple[list[CalendarEvent], int, int]:
    """One page of the events search: its events, ``pageInfo.total``, and ``pageInfo.pageSize``.

    With ``department``, a result that names another department is dropped:
    the query already asks for one department by id, and this keeps the
    stored calendar the council's if the site ever ignores that parameter.
    A payload that is not the expected shape is ``([], 0, 0)`` and a warning;
    a missing ``pageInfo`` reads as zero for both numbers.
    """
    try:
        block = payload["graphqlEventsSearchWww"]
        results = block["results"]
    except (KeyError, TypeError):
        log.warning("city_calendar: the search payload has no graphqlEventsSearchWww.results")
        return [], 0, 0
    if not isinstance(results, list):
        log.warning("city_calendar: the search's results is not a list")
        return [], 0, 0

    if department is not None:
        results = [r for r in results if _department_name(r) in (None, department)]
    info = block.get("pageInfo") if isinstance(block, dict) else None
    total = info.get("total") if isinstance(info, dict) else None
    page_size = info.get("pageSize") if isinstance(info, dict) else None
    return (
        _events_from_results(results, base_url),
        total if isinstance(total, int) else 0,
        page_size if isinstance(page_size, int) else 0,
    )


def _sitemap_day(url: str) -> str:
    """The ``YYYY-MM-DD`` that opens the last path segment, or "" when there is none."""
    segment = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    match = _PATH_DATE.match(segment)
    return match.group(0) if match else ""


def parse_sitemap(xml: str) -> list[str]:
    """The sitemap's council-shaped event pages, newest first.

    Every ``<loc>`` whose path begins ``/events/`` and contains, in any
    case, ``committee``, ``council-meeting``, or ``work-session``. The order
    is by the date that opens the path's last segment, newest first, a URL
    without one last, and otherwise the sitemap's own: a run fetches a
    bounded number of pages, and the newest council events must not wait
    behind a growing set of other departments' pages. Text with no such
    entry is ``[]``.
    """
    urls: list[str] = []
    for raw in _SITEMAP_LOC.findall(xml):
        url = html_entities.unescape(raw)
        path = urlsplit(url).path
        lowered = path.lower()
        if path.startswith("/events/") and any(word in lowered for word in _SITEMAP_WORDS):
            urls.append(url)
    # a stable sort: "" (no date) is below every date, so it lands last
    urls.sort(key=_sitemap_day, reverse=True)
    return urls


def parse_event_page(html: str, base_url: str, department: str) -> CalendarEvent | None:
    """The event an event page describes, when its department is ``department``; else None.

    The event is ``props.pageProps.nodeResource`` in the page's
    ``__NEXT_DATA__`` block. A page of another department, or one that names
    no department, is None without a warning (it is the expected answer for
    the pages the sitemap's path test lets through); a page without the
    block or the event is None with one.
    """
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id=_NEXT_DATA_ID)
    if script is None:
        log.warning("city_calendar: no %s script in the event page", _NEXT_DATA_ID)
        return None
    try:
        node = json.loads(script.string or "")["props"]["pageProps"]["nodeResource"]
    except (json.JSONDecodeError, KeyError, TypeError):
        log.warning("city_calendar: the event page has no props.pageProps.nodeResource")
        return None
    if _department_name(node) != department:
        return None
    return _event_from_result(node, base_url.rstrip("/"))


def normalise_event_url(url: str) -> str:
    """One spelling for an event page's address: lower-cased scheme and host, no trailing slash, query, or fragment.

    The search stores an event under ``base_url + path`` and the sitemap
    lists the same page in its own spelling; the service compares the two
    through this function so a stored event's page is not fetched again.
    """
    parts = urlsplit(url.strip())
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}{parts.path.rstrip('/')}"


def _base_url(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _get(url: str, **kwargs) -> requests.Response:
    """One GET with the browser user agent and the timeout, no sooner than a second after the last. Raises on a non-200."""
    global _last_request_at
    if _last_request_at is not None:
        wait = _MIN_INTERVAL_S - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
    try:
        resp = requests.get(url, timeout=_TIMEOUT_S, headers={"User-Agent": _BROWSER_UA}, **kwargs)
    finally:
        _last_request_at = time.monotonic()
    resp.raise_for_status()
    return resp


def fetch_birminghamal_events(url: str) -> list[CalendarEvent]:
    """One GET of the council page, parsed. Raises on a non-200 or a network failure."""
    resp = _get(url)
    return parse_birminghamal_page(resp.text, _base_url(url))


def fetch_search_events(search_url: str, department_id: str, *, department: str | None = None) -> list[CalendarEvent]:
    """Every upcoming event the search lists for one department id, all pages. Raises on a non-200 or a network failure.

    Page 0 upward until the pages read cover ``pageInfo.total``, a page
    comes back empty, or ``SEARCH_MAX_PAGES`` have been read. The empty
    parameters are the ones the site's own events page sends.
    ``department`` is passed to ``parse_search_page``.
    """
    base_url = _base_url(search_url)
    events: list[CalendarEvent] = []
    for page in range(SEARCH_MAX_PAGES):
        resp = _get(
            search_url,
            params={"page": page, "search": "", "fromDate": "", "toDate": "",
                    "department": department_id, "category": "", "district": ""},
        )
        try:
            payload = resp.json()
        except ValueError as e:
            log.warning("city_calendar: the search's page %d is not JSON: %s", page, e)
            break
        found, total, page_size = parse_search_page(payload, base_url, department=department)
        events.extend(found)
        if not found or page_size <= 0 or (page + 1) * page_size >= total:
            break
    return events


def fetch_sitemap_event_urls(sitemap_url: str) -> list[str]:
    """One GET of the sitemap, parsed by ``parse_sitemap``. Raises on a non-200 or a network failure."""
    return parse_sitemap(_get(sitemap_url).text)


def fetch_event_page(url: str, department: str) -> CalendarEvent | None:
    """One GET of an event page, parsed by ``parse_event_page``. Raises on a non-200 or a network failure."""
    return parse_event_page(_get(url).text, _base_url(url), department)
