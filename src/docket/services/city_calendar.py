"""Fill ``city_calendar_events`` from each city's own calendar.

A city whose ``municipalities.metadata`` carries ``calendar_url`` (Birmingham
after migration 038) has its calendar read once a day by the worker task
``city_calendar`` (05:30 America/Chicago, before ``ingest_all`` at 06:00) and
every event upserted on ``(municipality_id, source_event_id)``, so a second
run changes no row count and a changed title or time overwrites the earlier
one.

Three readers fill the table, each named by its own metadata key and each
failing alone (plan `committee-clips-named-or-hidden`, M1; the keys other
than ``calendar_url`` are migration 043's):

- the council page (``calendar_url``), which lists the next four events;
- the events search (``calendar_search_url`` with ``calendar_department_id``),
  which lists every upcoming event of the City Council department;
- the sitemap (``calendar_sitemap_url`` with ``calendar_department``), which
  lists every event page the site still serves, past ones included. The
  page of each listed address that is not already a stored ``source_url``
  is fetched, newest first, at most ``SITEMAP_MAX_PAGES`` in a run, and
  stored when its department is the city's ``calendar_department``. This is
  the backfill: the first run stores the past events, and a later run
  fetches only the pages that are new and the few the department test
  rejected, which are never stored.

The parsers and fetchers are ``docket.adapters.city_calendar``; this module
owns the transactions. The resolver (``docket.services.meeting_types``)
reads the rows to name the body of a Granicus clip the clerk titled
"Regular City Council Meeting".

Plan: plans/completed/meeting-types-name-the-body.md (M3).
"""

from __future__ import annotations

import logging

from psycopg2.extras import Json

from docket.adapters.city_calendar import (
    CalendarEvent,
    fetch_birminghamal_events,
    fetch_event_page,
    fetch_search_events,
    fetch_sitemap_event_urls,
    normalise_event_url,
)
from docket.db import db, db_cursor

log = logging.getLogger(__name__)

# Event pages fetched from the sitemap in one run, one second apart. The
# first run had 33 to read on 2026-11-11; later runs read a handful.
SITEMAP_MAX_PAGES = 60
# Event-page fetches that may fail in one run before the sitemap read ends
# for the day: a site that is down is not asked sixty times.
SITEMAP_MAX_FAILURES = 3

# A reader that reports no status (the search) leaves a stored one alone;
# the council page and the event pages report one and overwrite it.
_UPSERT_SQL = """
    INSERT INTO city_calendar_events
        (municipality_id, source_event_id, title, starts_at, ends_at, source_url, categories, event_status, fetched_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
    ON CONFLICT (municipality_id, source_event_id) DO UPDATE
       SET title        = EXCLUDED.title,
           starts_at    = EXCLUDED.starts_at,
           ends_at      = EXCLUDED.ends_at,
           source_url   = EXCLUDED.source_url,
           categories   = EXCLUDED.categories,
           event_status = COALESCE(EXCLUDED.event_status, city_calendar_events.event_status),
           fetched_at   = now()
"""


def _upsert(municipality_id: int, events: list[CalendarEvent]) -> int:
    """Upsert ``events`` for the city in one transaction; returns how many.

    One statement per event: a reader yields tens of rows at most (33 event
    pages on the sitemap's first run), far below decision 0026's concern.
    """
    if not events:
        return 0
    with db() as conn, conn.cursor() as cur:
        for ev in events:
            cur.execute(
                _UPSERT_SQL,
                (
                    municipality_id,
                    ev.source_event_id,
                    ev.title,
                    ev.starts_at,
                    ev.ends_at,
                    ev.source_url,
                    Json(list(ev.categories)),
                    ev.status,
                ),
            )
    return len(events)


def _stored_urls(municipality_id: int) -> set[str]:
    with db_cursor() as cur:
        cur.execute("SELECT source_url FROM city_calendar_events WHERE municipality_id = %s", (municipality_id,))
        return {normalise_event_url(r["source_url"]) for r in cur.fetchall()}


def _read_sitemap(municipality_id: int, sitemap_url: str, department: str) -> tuple[list[CalendarEvent], int, int]:
    """The department's events from the sitemap's unstored event pages, with how many pages were another department's and how many failed.

    A page that cannot be fetched is logged and passed over, so one removed
    page does not hide the pages after it; it is not stored, so the next
    run asks again. ``SITEMAP_MAX_FAILURES`` failures end the read.
    """
    urls = fetch_sitemap_event_urls(sitemap_url)
    stored = _stored_urls(municipality_id)
    todo = [url for url in urls if normalise_event_url(url) not in stored]
    events: list[CalendarEvent] = []
    other = failed = 0
    for url in todo[:SITEMAP_MAX_PAGES]:
        try:
            ev = fetch_event_page(url, department)
        except Exception as e:
            failed += 1
            log.warning("city_calendar: event page %s failed: %s", url, e)
            if failed >= SITEMAP_MAX_FAILURES:
                log.warning("city_calendar: %d event pages failed; the sitemap read ends for this run", failed)
                break
            continue
        if ev is None:
            other += 1
        else:
            events.append(ev)
    return events, other, failed


def refresh_city_calendar(municipality_id: int, metadata: dict) -> int:
    """Run the readers the city's ``metadata`` names and upsert what they return; returns how many upserts.

    Each reader runs inside its own ``try`` and commits its own events, so
    one source failing (the search's address changing, the sitemap timing
    out) leaves the others' rows stored; the failure is logged with its
    traceback. The sitemap reader runs last, after the other two have
    committed, so an event the search already stored is not fetched from
    its page. An event two readers return is counted once for each. When
    every reader the metadata names failed, the last failure is raised, so
    the caller logs the city as failed, as it did when there was one reader.
    """
    metadata = metadata or {}
    counts: dict[str, int] = {}
    attempted = 0
    last_error: Exception | None = None

    page_url = metadata.get("calendar_url")
    if page_url:
        attempted += 1
        try:
            counts["page"] = _upsert(municipality_id, fetch_birminghamal_events(page_url))
        except Exception as e:
            last_error = e
            log.exception("city_calendar: municipality %s: the council page reader failed", municipality_id)

    search_url = metadata.get("calendar_search_url")
    department_id = metadata.get("calendar_department_id")
    department = metadata.get("calendar_department")
    if search_url and department_id:
        attempted += 1
        try:
            counts["search"] = _upsert(
                municipality_id, fetch_search_events(search_url, str(department_id), department=department)
            )
        except Exception as e:
            last_error = e
            log.exception("city_calendar: municipality %s: the search reader failed", municipality_id)

    sitemap_url = metadata.get("calendar_sitemap_url")
    other = failed = 0
    if sitemap_url and department:
        attempted += 1
        try:
            events, other, failed = _read_sitemap(municipality_id, sitemap_url, department)
            counts["sitemap"] = _upsert(municipality_id, events)
        except Exception as e:
            last_error = e
            log.exception("city_calendar: municipality %s: the sitemap reader failed", municipality_id)

    if attempted and not counts and last_error is not None:
        raise last_error

    log.info(
        "city_calendar: municipality %s: page %s, search %s, sitemap %s (event pages of another department %d, failed %d)",
        municipality_id,
        counts.get("page", "not read"),
        counts.get("search", "not read"),
        counts.get("sitemap", "not read"),
        other,
        failed,
    )
    return sum(counts.values())


def refresh_all() -> int:
    """Refresh every active city whose metadata names a ``calendar_url``; returns how many were refreshed.

    A failure for one city is logged and does not block the others, as
    ``_do_ingest_all`` does for ingest.
    """
    with db_cursor() as cur:
        cur.execute(
            """SELECT id, slug, metadata
                 FROM municipalities
                WHERE active = TRUE AND metadata ? 'calendar_url'
                ORDER BY slug"""
        )
        cities = cur.fetchall()

    refreshed = 0
    for city in cities:
        try:
            n = refresh_city_calendar(city["id"], city["metadata"])
        except Exception:
            log.exception("city_calendar: %s failed", city["slug"])
            continue
        log.info("city_calendar: %s %d events upserted", city["slug"], n)
        refreshed += 1
    return refreshed
