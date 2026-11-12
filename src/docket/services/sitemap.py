"""Read-only queries behind the sitemap routes in :mod:`docket.web.crawlers`.

Every function returns only what a reader could already reach on the public
site: active cities, meetings that are not hidden, and the agenda items of
those meetings. ``lastmod`` values come from ``meetings.updated_at`` because
``agenda_items`` has no update timestamp of its own.
"""

from __future__ import annotations

import math

from docket.db import db_cursor

#: Item URLs per items sitemap file. The sitemap protocol caps a file at
#: 50,000 URLs; 10,000 keeps each file small enough to render in well under
#: a second and leaves room for the largest city to grow.
ITEMS_PER_SITEMAP = 10_000


def list_cities() -> list[dict]:
    """Active cities with the count of visible agenda items each one has.

    Each row carries ``slug``, ``item_count`` and ``item_pages`` (how many
    items sitemap files the city needs; zero when it has no items).
    """
    with db_cursor() as cur:
        cur.execute("""
            SELECT m.slug,
                   COUNT(ai.id) AS item_count
            FROM municipalities m
            LEFT JOIN meetings mt
              ON mt.municipality_id = m.id
             AND mt.is_hidden = FALSE
            LEFT JOIN agenda_items ai
              ON ai.meeting_id = mt.id
            WHERE m.active = TRUE
            GROUP BY m.slug
            ORDER BY m.slug
        """)
        rows = [dict(row) for row in cur.fetchall()]
    for row in rows:
        row["item_pages"] = math.ceil(row["item_count"] / ITEMS_PER_SITEMAP)
    return rows


def city_exists(slug: str) -> bool:
    with db_cursor() as cur:
        cur.execute(
            "SELECT 1 FROM municipalities WHERE slug = %s AND active = TRUE",
            (slug,),
        )
        return cur.fetchone() is not None


def list_meetings(slug: str) -> list[dict]:
    """Visible meetings of one active city: ``id`` and ``updated_at``."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT mt.id, mt.updated_at
            FROM meetings mt
            JOIN municipalities m ON m.id = mt.municipality_id
            WHERE m.slug = %s
              AND m.active = TRUE
              AND mt.is_hidden = FALSE
            ORDER BY mt.id
        """, (slug,))
        return [dict(row) for row in cur.fetchall()]


def list_items(slug: str, page: int) -> list[dict]:
    """One page of visible agenda items for a city, ``page`` counting from 1.

    Rows carry ``id`` and ``updated_at`` (the parent meeting's). An empty
    list means the page is past the end.
    """
    if page < 1:
        return []
    with db_cursor() as cur:
        cur.execute("""
            SELECT ai.id, mt.updated_at
            FROM agenda_items ai
            JOIN meetings mt ON mt.id = ai.meeting_id
            JOIN municipalities m ON m.id = mt.municipality_id
            WHERE m.slug = %s
              AND m.active = TRUE
              AND mt.is_hidden = FALSE
            ORDER BY ai.id
            LIMIT %s OFFSET %s
        """, (slug, ITEMS_PER_SITEMAP, (page - 1) * ITEMS_PER_SITEMAP))
        return [dict(row) for row in cur.fetchall()]
