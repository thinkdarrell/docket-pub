# src/docket/ai/transcripts/cards.py
"""Search cards: hidden search text for an agenda item, written from the meeting's transcript.

A card is one row of `agenda_item_search_cards` (migration 041). Nothing in
a card is displayed. Its two texts, `search_b` and `search_c`, reach search
through `agenda_items.search_vector`: the trigger function
`agenda_items_search_update()` reads the item's card row whenever the item
row is written, so the writer of a card refreshes the item rows itself.

This module holds everything about a card except the model call:

- `load_card_items` reads the placed items of a transcript, and
  `render_cards_input` writes the meeting as the user message `CARDS_SYSTEM`
  (prompts.py) describes, with one marker block per placed item;
- `validate_cards` turns a parsed reply (`CardList`, schemas.py) into rows for
  the store, dropping what the citation guard cannot find and bounds far from
  the item's placement, and `search_texts` builds a card's two search texts;
- `write_cards` and `touch_search_vectors` are the store.
"""
from __future__ import annotations

import json

from docket.ai.transcripts.events import _label
from docket.ai.transcripts.guard import find_citation
from docket.ai.transcripts.schemas import CardList, SearchCard
from docket.ai.transcripts.speakers import hms
from docket.db import db_cursor

CARD_SNAP_MAX_S = 600.0        # snapped bounds further than this from the item's placement are not believed
START_MOVED_S = 20.0           # a kept start this far from the placement's start is counted as moved
DESCRIPTION_CHARS = 1500       # how much of an item's description the marker block carries
DETAIL_NEIGHBOURS = 2          # a quote is looked for this many segments either side of its cited segment
MAX_ALIASES, MAX_ALIAS_WORDS = 8, 8
MAX_DETAILS = 8
MAX_IDENTIFIERS, MAX_IDENTIFIER_CHARS = 12, 40
MAX_NAMES, MAX_VARIANTS = 12, 6

COUNT_KEYS = ("placed", "cards", "missing", "extra", "discussed", "details_kept", "details_repointed",
              "details_dropped", "bounds_kept", "bounds_dropped", "starts_moved")


def load_card_items(meeting_id: int, transcript_id: int) -> list[dict]:
    """The placed items of a transcript, in the order they are first filed.

    An item is placed when at least one non-silence segment of this transcript
    is filed under it. `first_seq` is the first such segment, and
    `placed_start_s` and `placed_end_s` are the earliest start and the latest
    end among them.
    """
    with db_cursor() as cur:
        cur.execute(
            """SELECT ai.id, ai.item_number, ai.title, ai.description, ai.headline, ai.why_it_matters,
                      p.first_seq, p.placed_start_s, p.placed_end_s
                 FROM agenda_items ai
                 JOIN (SELECT s.agenda_item_id, MIN(s.seq) AS first_seq, MIN(s.start_s) AS placed_start_s,
                              MAX(s.end_s) AS placed_end_s
                         FROM transcript_segments s
                        WHERE s.transcript_id = %s AND s.is_silence = FALSE AND s.agenda_item_id IS NOT NULL
                        GROUP BY s.agenda_item_id) p ON p.agenda_item_id = ai.id
                WHERE ai.meeting_id = %s
                ORDER BY p.first_seq, ai.id""",
            [transcript_id, meeting_id],
        )
        return [dict(r) for r in cur.fetchall()]


def _one_line(value: str | None) -> str:
    """The text with every run of whitespace as one space, so a field stays on its own line."""
    return " ".join((value or "").split())


def _marker(item: dict) -> str:
    return "\n".join([
        f"=== ITEM MARKER item_id={item['id']} (Item {item.get('item_number') or '?'}) ===",
        f"agenda text: {_one_line(item.get('title')) or 'none'}",
        f"description: {_one_line(item.get('description'))[:DESCRIPTION_CHARS] or 'none'}",
        f"site headline: {_one_line(item.get('headline')) or 'none'}",
        f"site summary: {_one_line(item.get('why_it_matters')) or 'none'}",
    ])


def render_cards_input(meeting: dict, segments: list[dict], items: list[dict], ordinals: dict[str, int]) -> str:
    """The user message for one meeting: its transcript, with a marker block where each placed item begins.

    Every non-silence, non-empty segment is one line, `[seq=N t=HH:MM:SS Speaker] text`,
    in `seq` order, labelled by `events._label`, the one rule for naming a
    speaker in a stage's input. An item's marker block goes before the segment
    whose `seq` is its `first_seq`. Every item gets a marker, because the
    reply owes a card for every placed item: when an item's first segment is
    not rendered (it has no text), the marker goes before the next line, or
    after the last one.
    """
    pending = sorted(items, key=lambda i: i["first_seq"])
    lines = [f"Meeting: {meeting.get('title')} on {meeting.get('meeting_date')}", ""]
    n = 0
    for s in sorted(segments, key=lambda s: s["seq"]):
        if s.get("is_silence") or not (s.get("text") or "").strip():
            continue
        while n < len(pending) and pending[n]["first_seq"] <= s["seq"]:
            lines.append(_marker(pending[n]))
            n += 1
        lines.append(f"[seq={s['seq']} t={hms(s['start_s'])} {_label(s, ordinals)}] {s['text'].strip()}")
    lines += [_marker(item) for item in pending[n:]]
    return "\n".join(lines)


def _locate_quote(quote: str, seq: int, spoken: list[dict], position: dict[int, int]) -> int | None:
    """The `seq` of the segment a quote is found at, or None when the guard cannot find it.

    The cited segment is tried first. Failing that, the texts of the segments
    from two before it to two after it are joined by single spaces, since a
    quote of several words can straddle a segment boundary, and a quote found
    there belongs to the segment in which the match starts.
    """
    at = position[seq]
    if find_citation(quote, spoken[at]["text"] or "").kind != "missing":
        return seq
    window = spoken[max(0, at - DETAIL_NEIGHBOURS):at + DETAIL_NEIGHBOURS + 1]
    texts = [(s["text"] or "").strip() for s in window]
    match = find_citation(quote, " ".join(texts))
    if match.kind == "missing":
        return None
    found, offset = window[0]["seq"], 0
    for s, text in zip(window, texts):
        if match.start < offset:
            break
        found = s["seq"]
        offset += len(text) + 1
    return found


def _valid_details(card: SearchCard, spoken: list[dict], position: dict[int, int], counts: dict) -> list[dict]:
    kept: list[dict] = []
    for d in card.spoken_details:
        text, quote = _one_line(d.text), d.quote.strip()
        seq = None
        if text and d.seq in position and len(kept) < MAX_DETAILS:
            seq = _locate_quote(quote, d.seq, spoken, position)
        if seq is None:
            counts["details_dropped"] += 1
            continue
        counts["details_kept"] += 1
        if seq != d.seq:
            counts["details_repointed"] += 1
        kept.append({"text": text, "seq": seq, "quote": quote})
    return kept


def _valid_aliases(card: SearchCard) -> list[str]:
    kept: list[str] = []
    for alias in card.aliases:
        words = alias.lower().split()
        phrase = " ".join(words)
        if 1 <= len(words) <= MAX_ALIAS_WORDS and phrase not in kept:
            kept.append(phrase)
    return kept[:MAX_ALIASES]


def _valid_identifiers(card: SearchCard, position: dict[int, int]) -> list[dict]:
    kept: list[dict] = []
    for i in card.identifiers:
        value = _one_line(i.value)
        if value and len(value) <= MAX_IDENTIFIER_CHARS:
            kept.append({"kind": i.kind, "value": value, "seq": i.seq if i.seq in position else None})
    return kept[:MAX_IDENTIFIERS]


def _valid_names(card: SearchCard) -> list[dict]:
    kept: list[dict] = []
    for n in card.names:
        name = _one_line(n.name)
        if not name:
            continue
        variants, seen = [], {name.casefold()}
        for v in n.variants:
            variant = _one_line(v)
            if variant and variant.casefold() not in seen:
                seen.add(variant.casefold())
                variants.append(variant)
        kept.append({"name": name, "variants": variants[:MAX_VARIANTS]})
    return kept[:MAX_NAMES]


def _valid_bounds(card: SearchCard, item: dict, by_seq: dict[int, dict]) -> tuple[dict, dict] | None:
    """The start and end segments when the card's bounds can be believed, else None."""
    if not card.discussed or card.start_seq is None or card.end_seq is None or card.start_seq > card.end_seq:
        return None
    start, end = by_seq.get(card.start_seq), by_seq.get(card.end_seq)
    if start is None or end is None:
        return None
    earliest, latest = item["placed_start_s"] - CARD_SNAP_MAX_S, item["placed_end_s"] + CARD_SNAP_MAX_S
    if not earliest <= start["start_s"] <= latest or end["end_s"] > latest:
        return None
    return start, end


def search_texts(card: dict) -> tuple[str, str]:
    """A stored card's two search texts, `(search_b, search_c)`, each joined by " . ".

    `search_b` (weight B) is what a resident might type: the aliases, the
    identifier values, and the names with their variants. `search_c` (weight
    C) is what was said: the spoken detail sentences, the `refers_to`
    sentence, and the outcome word unless it is "unclear".
    """
    b = list(card.get("aliases") or [])
    b += [i["value"] for i in card.get("identifiers") or []]
    for n in card.get("names") or []:
        b += [n["name"], *(n.get("variants") or [])]
    c = [d["text"] for d in card.get("spoken_details") or []]
    if card.get("refers_to"):
        c.append(card["refers_to"]["text"])
    result = (card.get("outcome") or {}).get("result")
    if result and result != "unclear":
        c.append(result)
    return " . ".join(b), " . ".join(c)


def validate_cards(parsed: CardList, *, items: list[dict], segments: list[dict]) -> tuple[list[dict], dict]:
    """Turn a parsed reply into rows `write_cards` accepts, with counts of what was kept and dropped.

    `items` is what `load_card_items` returned and `segments` the transcript's
    segments (`seq`, `start_s`, `end_s`, `text`, `is_silence`). A `seq` counts
    as a segment only when it is a non-silence segment of this transcript.

    In order: a card for an item that is not placed, and a second card for an
    item, are dropped (`extra`); a placed item with no card is counted
    (`missing`) and gets no row. Aliases are lowercased, deduplicated, kept
    when one to eight words long, and capped at eight. A spoken detail needs a
    sentence, a cited segment, and a quote the citation guard finds at that
    segment or within two segments of it (`_locate_quote`); one found beside
    its cited segment is re-pointed there (`details_repointed`, a subset of
    `details_kept`), and at most eight are kept; every other detail is counted
    in `details_dropped`. Identifier values over 40 characters are dropped,
    twelve are kept, and a `seq` that is not a segment becomes null, as it
    does for the outcome and `refers_to`. A name needs a name; its variants
    are deduplicated and exclude the name; twelve names and six variants each
    are kept. A `refers_to` with no text is stored as null.

    Bounds are kept only when the card says discussed, both are segments in
    order, the start segment begins no more than `CARD_SNAP_MAX_S` before the
    placement's start or after its end, and the end segment ends no more than
    `CARD_SNAP_MAX_S` after the placement's end; otherwise both are null, and
    `bounds_dropped` counts the discussed cards left without bounds. Ranges
    that overlap are kept as they are: items voted as a block share an ending.
    `starts_moved` counts kept starts `START_MOVED_S` or more from the
    placement's start.

    Rows come back in the reply's order. Each row's `card` holds exactly
    `aliases`, `spoken_details`, `identifiers`, `names`, `outcome`, and
    `refers_to`, and its `search_b` and `search_c` are `search_texts(card)`.
    """
    spoken = sorted((s for s in segments if not s.get("is_silence")), key=lambda s: s["seq"])
    by_seq = {s["seq"]: s for s in spoken}
    position = {s["seq"]: n for n, s in enumerate(spoken)}
    placed = {i["id"]: i for i in items}
    counts = dict.fromkeys(COUNT_KEYS, 0)
    counts["placed"] = len(placed)
    rows: list[dict] = []
    carded: set[int] = set()
    for c in parsed.cards:
        item = placed.get(c.item_id)
        if item is None or c.item_id in carded:
            counts["extra"] += 1
            continue
        carded.add(c.item_id)
        refers_text = _one_line(c.refers_to.text)
        card = {
            "aliases": _valid_aliases(c),
            "spoken_details": _valid_details(c, spoken, position, counts),
            "identifiers": _valid_identifiers(c, position),
            "names": _valid_names(c),
            "outcome": {"result": c.outcome.result, "seq": c.outcome.seq if c.outcome.seq in position else None},
            "refers_to": ({"text": refers_text, "seq": c.refers_to.seq if c.refers_to.seq in position else None}
                          if refers_text else None),
        }
        bounds = _valid_bounds(c, item, by_seq)
        if c.discussed:
            counts["discussed"] += 1
            counts["bounds_kept" if bounds else "bounds_dropped"] += 1
        if bounds and abs(bounds[0]["start_s"] - item["placed_start_s"]) >= START_MOVED_S:
            counts["starts_moved"] += 1
        search_b, search_c = search_texts(card)
        rows.append({
            "item_id": c.item_id, "discussed": c.discussed,
            "start_seq": bounds[0]["seq"] if bounds else None, "end_seq": bounds[1]["seq"] if bounds else None,
            "start_s": bounds[0]["start_s"] if bounds else None, "end_s": bounds[1]["end_s"] if bounds else None,
            "card": card, "search_b": search_b, "search_c": search_c,
        })
    counts["cards"] = len(rows)
    counts["missing"] = len(placed) - len(carded)
    return rows, counts


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
