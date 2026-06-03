"""Inline shortcode collection ([[item:N]], [[meeting:N]]) + batched DB resolution."""

from __future__ import annotations

import contextlib
import re
from typing import NamedTuple

from docket.db import db_cursor

ITEM_RE = re.compile(r"\[\[item:(\d+)\]\]")
MEETING_RE = re.compile(r"\[\[meeting:(\d+)\]\]")


class ResolvedItem(NamedTuple):
    """A resolved shortcode reference — title plus the city slug needed to build a URL."""

    title: str
    city_slug: str


def collect_shortcode_refs(markdown: str) -> tuple[set[int], set[int]]:
    """Return (item_ids, meeting_ids) referenced by `[[item:N]]` / `[[meeting:N]]`."""
    items = {int(m) for m in ITEM_RE.findall(markdown)}
    meetings = {int(m) for m in MEETING_RE.findall(markdown)}
    return items, meetings


@contextlib.contextmanager
def _open_cursor():
    """Indirection so tests can patch the DB layer cleanly."""
    with db_cursor() as cur:
        yield cur


def resolve_shortcode_titles(
    *, item_ids: set[int], meeting_ids: set[int]
) -> tuple[dict[int, ResolvedItem], dict[int, ResolvedItem]]:
    """Batch-fetch titles + city slugs for the collected IDs.
    Empty sets → empty dicts, no query.
    """
    item_map: dict[int, ResolvedItem] = {}
    meeting_map: dict[int, ResolvedItem] = {}

    if not item_ids and not meeting_ids:
        return item_map, meeting_map

    with _open_cursor() as cur:
        if item_ids:
            cur.execute(
                """
                SELECT ai.id, ai.title, mu.slug AS city_slug
                FROM agenda_items ai
                JOIN meetings m ON ai.meeting_id = m.id
                JOIN municipalities mu ON m.municipality_id = mu.id
                WHERE ai.id = ANY(%s)
                """,
                (list(item_ids),),
            )
            for row in cur.fetchall():
                item_map[row["id"]] = ResolvedItem(
                    title=row["title"], city_slug=row["city_slug"]
                )
        if meeting_ids:
            cur.execute(
                """
                SELECT m.id, m.title, mu.slug AS city_slug
                FROM meetings m
                JOIN municipalities mu ON m.municipality_id = mu.id
                WHERE m.id = ANY(%s)
                """,
                (list(meeting_ids),),
            )
            for row in cur.fetchall():
                meeting_map[row["id"]] = ResolvedItem(
                    title=row["title"], city_slug=row["city_slug"]
                )

    return item_map, meeting_map
