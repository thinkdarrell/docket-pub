"""Fill ``city_calendar_events`` from each city's own calendar page.

A city whose ``municipalities.metadata`` carries ``calendar_url`` (Birmingham
after migration 038) has its page fetched once a day by the worker task
``city_calendar`` (05:30 America/Chicago, before ``ingest_all`` at 06:00) and
every event the page lists upserted on ``(municipality_id, source_event_id)``,
so a second run of the same page changes no row count and a changed title or
time overwrites the earlier one. The page lists upcoming events only, so the
table fills from the first run onward; there is no backfill.

The parser is ``docket.adapters.city_calendar``; this module owns the
transaction. The resolver (``docket.services.meeting_types``, M4) reads the
rows to name the body of a Granicus clip the clerk titled
"Regular City Council Meeting".

Plan: plans/active/meeting-types-name-the-body.md (M3).
"""

from __future__ import annotations

import logging

from psycopg2.extras import Json

from docket.adapters.city_calendar import fetch_birminghamal_events
from docket.db import db, db_cursor

log = logging.getLogger(__name__)

_UPSERT_SQL = """
    INSERT INTO city_calendar_events
        (municipality_id, source_event_id, title, starts_at, ends_at, source_url, categories, fetched_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, now())
    ON CONFLICT (municipality_id, source_event_id) DO UPDATE
       SET title      = EXCLUDED.title,
           starts_at  = EXCLUDED.starts_at,
           ends_at    = EXCLUDED.ends_at,
           source_url = EXCLUDED.source_url,
           categories = EXCLUDED.categories,
           fetched_at = now()
"""


def refresh_city_calendar(municipality_id: int, url: str) -> int:
    """Fetch ``url`` and upsert every event it lists for the city; returns how many.

    One statement per event, in one transaction: the page holds a handful of
    rows (four on 2026-10-21), far below decision 0026's concern. A fetch or
    parse failure propagates to the caller, which isolates it per city.
    """
    events = fetch_birminghamal_events(url)
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
                ),
            )
    return len(events)


def refresh_all() -> int:
    """Refresh every active city whose metadata names a ``calendar_url``; returns how many were refreshed.

    A failure for one city is logged and does not block the others, as
    ``_do_ingest_all`` does for ingest.
    """
    with db_cursor() as cur:
        cur.execute(
            """SELECT id, slug, metadata->>'calendar_url' AS calendar_url
                 FROM municipalities
                WHERE active = TRUE AND metadata ? 'calendar_url'
                ORDER BY slug"""
        )
        cities = cur.fetchall()

    refreshed = 0
    for city in cities:
        try:
            n = refresh_city_calendar(city["id"], city["calendar_url"])
        except Exception:
            log.exception("city_calendar: %s failed", city["slug"])
            continue
        log.info("city_calendar: %s %d events upserted", city["slug"], n)
        refreshed += 1
    return refreshed
