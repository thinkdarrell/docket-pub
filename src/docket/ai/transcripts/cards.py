# src/docket/ai/transcripts/cards.py
"""Search cards: hidden search text for an agenda item, written from the meeting's transcript.

A card is one row of `agenda_item_search_cards` (migration 041). Nothing in
a card is displayed. Its two texts, `search_b` and `search_c`, reach search
through `agenda_items.search_vector`: the trigger function
`agenda_items_search_update()` reads the item's card row whenever the item
row is written, so the writer of a card refreshes the item rows itself.

This module holds the store only: `write_cards` and `touch_search_vectors`.
"""
from __future__ import annotations

import json

from docket.db import db_cursor


def touch_search_vectors(cur, item_ids: list[int]) -> None:
    """Make the search trigger recompute these items' vectors, in one statement.

    The update changes nothing itself. It exists to fire the trigger, which
    rebuilds each vector with the item's card text, or without it when the
    card is gone. An empty list runs no statement.
    """
    ids = sorted(set(item_ids))
    if not ids:
        return
    cur.execute("UPDATE agenda_items SET search_vector = search_vector WHERE id = ANY(%s)", [ids])


def write_cards(transcript_id: int, source_uploaded_at, cards: list[dict], *, model: str, prompt_version: int) -> int:
    """Replace a transcript's cards with `cards` and refresh the affected items' search vectors.

    Each card is a dict with the keys `item_id`, `discussed`, `start_seq`,
    `end_seq`, `start_s`, `end_s`, `card`, `search_b`, and `search_c`.

    One transaction. The transcript row is locked first, and when its
    `uploaded_at` is not `source_uploaded_at` (a re-upload landed while the
    cards were being written, or the row is gone or not uploaded) nothing is
    written and -1 is returned: the `seq` values in `cards` point at segments
    that no longer exist. Otherwise the transcript's existing card rows are
    deleted, the new ones inserted, and the vectors of every item that had a
    card or has one now are recomputed, so an item that lost its card loses
    the card's words. Returns the number of rows inserted.

    Two cards for one item, or a card for an item that another transcript
    has carded, raise psycopg2's UniqueViolation and leave everything as it
    was.
    """
    with db_cursor() as cur:
        cur.execute("SELECT uploaded_at FROM transcripts WHERE id = %s FOR UPDATE", [transcript_id])
        row = cur.fetchone()
        if row is None or row["uploaded_at"] is None or row["uploaded_at"] != source_uploaded_at:
            return -1
        cur.execute("SELECT agenda_item_id FROM agenda_item_search_cards WHERE transcript_id = %s", [transcript_id])
        old_ids = [r["agenda_item_id"] for r in cur.fetchall()]
        cur.execute("DELETE FROM agenda_item_search_cards WHERE transcript_id = %s", [transcript_id])
        for c in cards:
            cur.execute(
                """INSERT INTO agenda_item_search_cards (agenda_item_id, transcript_id, source_uploaded_at, prompt_version,
                                                         model, discussed, start_seq, end_seq, start_s, end_s, card,
                                                         search_b, search_c)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)""",
                [c["item_id"], transcript_id, source_uploaded_at, prompt_version, model, c["discussed"],
                 c["start_seq"], c["end_seq"], c["start_s"], c["end_s"], json.dumps(c["card"]),
                 c["search_b"], c["search_c"]],
            )
        touch_search_vectors(cur, old_ids + [c["item_id"] for c in cards])
        return len(cards)
