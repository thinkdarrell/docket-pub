"""Inline shortcode collection ([[item:N]], [[meeting:N]]) + batched DB resolution."""

from __future__ import annotations

import contextlib
import re

from docket.db import db_cursor

ITEM_RE = re.compile(r"\[\[item:(\d+)\]\]")
MEETING_RE = re.compile(r"\[\[meeting:(\d+)\]\]")


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
) -> tuple[dict[int, str], dict[int, str]]:
    """Batch-fetch titles for the collected IDs. Empty sets → empty dicts, no query."""
    item_titles: dict[int, str] = {}
    meeting_titles: dict[int, str] = {}

    if not item_ids and not meeting_ids:
        return item_titles, meeting_titles

    with _open_cursor() as cur:
        if item_ids:
            cur.execute(
                "SELECT id, title FROM agenda_items WHERE id = ANY(%s)",
                (list(item_ids),),
            )
            for row in cur.fetchall():
                item_titles[row["id"]] = row["title"]
        if meeting_ids:
            cur.execute(
                "SELECT id, title FROM meetings WHERE id = ANY(%s)",
                (list(meeting_ids),),
            )
            for row in cur.fetchall():
                meeting_titles[row["id"]] = row["title"]

    return item_titles, meeting_titles
