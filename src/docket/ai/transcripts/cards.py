# src/docket/ai/transcripts/cards.py
"""Search cards: hidden search text for an agenda item, written from the meeting's transcript.

A card is one row of `agenda_item_search_cards` (migration 041). Nothing in
a card is displayed. Its two texts, `search_b` and `search_c`, reach search
through `agenda_items.search_vector`: the trigger function
`agenda_items_search_update()` reads the item's card row whenever the item
row is written, so the writer of a card refreshes the item rows itself.

This module holds the whole card stage:

- `load_card_items` reads the placed items of a transcript, and
  `render_cards_input` writes the meeting as the user message `CARDS_SYSTEM`
  (prompts.py) describes, with one marker block per placed item;
- `validate_cards` turns a parsed reply (`CardList`, schemas.py) into rows for
  the store, dropping what the citation guard cannot find and bounds far from
  the item's placement, and `search_texts` builds a card's two search texts;
- `write_cards` and `touch_search_vectors` are the store;
- `run_cards` is the runner: it claims transcripts that have passed the events
  stage and have no current card run (`CLAIM_CARDS_SQL`), calls the model once
  per meeting (`build_for_transcript`), and records each attempt in
  `transcript_card_runs` and in `ai_runs` under the stage `transcript_cards`.
  It never writes the `transcripts` table. The daily `transcript_pipeline`
  tick calls it (pipeline.py) and so does `scripts/build_search_cards.py`,
  whose `--count` line `count_card_runs` supplies.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from pydantic import ValidationError

from docket.ai.exceptions import (
    AIFatalError,
    AIPermanentRowError,
    AIRateLimited,
    AITransientError,
    TranscriptHeld,
)
from docket.ai.pricing import PRICING, Usage, usage_capture
from docket.ai.transcripts.events import _label, _meeting, load_segments_with_speakers
from docket.ai.transcripts.guard import find_citation
from docket.ai.transcripts.prompts import CARDS_PROMPT_VERSION, CARDS_SYSTEM
from docket.ai.transcripts.schemas import CARDS_SCHEMA, CardList, SearchCard
from docket.ai.transcripts.shared import speaker_ordinals
from docket.ai.transcripts.speakers import hms
from docket.config import (
    AI_DAILY_BUDGET_USD,
    AI_TRANSCRIPT_CARDS_MODEL,
    TRANSCRIPT_TOKEN_CEILING,
)
from docket.db import db, db_cursor

log = logging.getLogger(__name__)

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

RUN_NAME = "transcript_cards"  # the `ai_runs` stage; /admin/ai lists every stage whose name begins `transcript_`

# Which transcripts can be carded at all. The two statuses mean "the events stage has run", which is the
# stage that settles placement, and both are public: `low_speech` is not among them and `uploaded_at` is
# required. Only Birmingham meetings with a numeric Granicus id, as in `pipeline.CLAIM_SQL`: a `yt-`
# committee meeting has no agenda items and so nothing to card.
_CARDABLE_SQL = """
          FROM transcripts t
          JOIN meetings m        ON m.id  = t.meeting_id
          JOIN municipalities mu ON mu.id = m.municipality_id
          LEFT JOIN transcript_card_runs r ON r.transcript_id = t.id
         WHERE mu.slug = 'birmingham'
           AND m.external_id ~ '^[0-9]+$'
           AND m.is_hidden = FALSE
           AND t.uploaded_at IS NOT NULL
           AND t.status IN ('events_extracted', 'compared')"""

# Which of those lack a current card run: never run, run from an earlier upload, run under an older prompt
# (a floor, decision 0014), or an attempt that did not finish and has tries and its 24 hours behind it.
_WAITING_SQL = """(r.transcript_id IS NULL
                OR r.source_uploaded_at <> t.uploaded_at
                OR r.prompt_version < %(version)s
                OR (r.status IN ('claimed', 'failed') AND r.attempts < 3
                    AND (r.last_attempted_at IS NULL OR r.last_attempted_at < now() - interval '24 hours')))"""

_NAMED_SQL = "t.meeting_id = %(meeting_id)s"


def _claim_sql(eligible: str) -> str:
    """The claim: one candidate, locked, newest meeting first, its attempt counted in `transcript_card_runs`.

    The pattern is `pipeline.CLAIM_SQL`'s, but the bookkeeping is the card
    stage's own table and nothing is written to `transcripts`. A run row that
    described another upload or an older prompt starts again at one attempt.
    """
    return f"""
    WITH candidate AS (
        SELECT t.id, t.meeting_id, t.uploaded_at{_CARDABLE_SQL}
           AND {eligible}
         ORDER BY m.meeting_date DESC, t.id
         LIMIT 1
         FOR UPDATE OF t SKIP LOCKED
    )
    INSERT INTO transcript_card_runs AS r (transcript_id, meeting_id, source_uploaded_at, prompt_version,
                                           status, attempts, last_attempted_at)
    SELECT id, meeting_id, uploaded_at, %(version)s, 'claimed', 1, now() FROM candidate
    ON CONFLICT (transcript_id) DO UPDATE
       SET attempts = CASE WHEN r.source_uploaded_at = EXCLUDED.source_uploaded_at
                            AND r.prompt_version = EXCLUDED.prompt_version THEN r.attempts + 1 ELSE 1 END,
           source_uploaded_at = EXCLUDED.source_uploaded_at, prompt_version = EXCLUDED.prompt_version,
           status = 'claimed', last_attempted_at = now(), last_error = NULL, updated_at = now()
    RETURNING r.transcript_id, r.meeting_id, r.source_uploaded_at, r.attempts
    """


def _peek_sql(eligible: str) -> str:
    """What the claim would take next, read and not taken: a dry run's candidate."""
    return f"""
    SELECT t.id AS transcript_id, t.meeting_id, t.uploaded_at AS source_uploaded_at, 0 AS attempts{_CARDABLE_SQL}
       AND {eligible}
       AND t.id <> ALL(%(seen)s)
     ORDER BY m.meeting_date DESC, t.id
     LIMIT 1
    """


CLAIM_CARDS_SQL = _claim_sql(_WAITING_SQL)
# A named meeting is claimed whatever its run row says, so an operator can rebuild it.
CLAIM_CARDS_MEETING_SQL = _claim_sql(_NAMED_SQL)

# The partition `scripts/build_search_cards.py --count` prints. Every public transcript past the events
# stage is in exactly one of the last four: `current` (a done run for this upload and prompt), `held`,
# `failed` (out of attempts), or `waiting` (the claim will take it, now or once its 24 hours are up).
COUNT_CARDS_SQL = """
SELECT count(*) AS public,
       count(*) FILTER (WHERE past) AS past_events,
       count(*) FILTER (WHERE past AND is_current AND run_status = 'done') AS current,
       count(*) FILTER (WHERE past AND NOT (is_current AND (run_status IN ('done', 'held') OR attempts >= 3))) AS waiting,
       count(*) FILTER (WHERE past AND is_current AND run_status = 'held') AS held,
       count(*) FILTER (WHERE past AND is_current AND run_status IN ('claimed', 'failed') AND attempts >= 3) AS failed
  FROM (SELECT t.status IN ('events_extracted', 'compared') AS past,
               (r.transcript_id IS NOT NULL AND r.source_uploaded_at = t.uploaded_at
                AND r.prompt_version >= %(version)s) AS is_current,
               r.status AS run_status, r.attempts
          FROM transcripts t
          JOIN meetings m        ON m.id  = t.meeting_id
          JOIN municipalities mu ON mu.id = m.municipality_id
          LEFT JOIN transcript_card_runs r ON r.transcript_id = t.id
         WHERE mu.slug = 'birmingham'
           AND m.external_id ~ '^[0-9]+$'
           AND m.is_hidden = FALSE
           AND t.uploaded_at IS NOT NULL
           AND t.status <> 'low_speech') x
"""


@dataclass
class CardsSummary:
    """What one `run_cards` call did. `built` counts runs that ended `done`; `reports` holds a line per validated reply."""
    built: int = 0
    failed: int = 0
    held: int = 0
    stopped_reason: str | None = None
    reports: list[str] = field(default_factory=list)


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


def claim_cards(meeting_id: int | None = None) -> dict | None:
    """Claim the next transcript that lacks a current card run, or the named meeting's whatever its run says.

    Returns the run (`transcript_id`, `meeting_id`, `source_uploaded_at`,
    `attempts`), or None when nothing can be claimed.
    """
    sql = CLAIM_CARDS_SQL if meeting_id is None else CLAIM_CARDS_MEETING_SQL
    with db_cursor() as cur:
        cur.execute(sql, {"version": CARDS_PROMPT_VERSION, "meeting_id": meeting_id})
        row = cur.fetchone()
        return dict(row) if row else None


def peek_cards(meeting_id: int | None = None, seen: list[int] | None = None) -> dict | None:
    """The run `claim_cards` would return, without claiming it or writing anything; `seen` transcripts are passed over."""
    sql = _peek_sql(_WAITING_SQL if meeting_id is None else _NAMED_SQL)
    with db_cursor() as cur:
        cur.execute(sql, {"version": CARDS_PROMPT_VERSION, "meeting_id": meeting_id, "seen": list(seen or [])})
        row = cur.fetchone()
        return dict(row) if row else None


def count_card_runs() -> dict:
    """Read-only counts of Birmingham's public transcripts by where they stand with the card stage (`COUNT_CARDS_SQL`)."""
    with db_cursor() as cur:
        cur.execute(COUNT_CARDS_SQL, {"version": CARDS_PROMPT_VERSION})
        return dict(cur.fetchone())


def build_for_transcript(run: dict, *, client, dry_run: bool = False) -> dict:
    """Write the cards of one claimed transcript: one model call, validated, stored. Returns the counts.

    The counts are `validate_cards`'s eleven plus `written`: the rows
    `write_cards` stored, 0 when nothing was written (a dry run, a reply that
    carded nothing, a meeting with no placed item), and -1 when a re-upload
    landed during the call and `write_cards` refused. A meeting with no placed
    item returns `placed: 0` and calls the model not at all. A reply that
    carded nothing is not written, because `write_cards` replaces a
    transcript's cards and must not wipe the ones already there.

    Raises `TranscriptHeld` when the meeting is over `TRANSCRIPT_TOKEN_CEILING`
    or the reply does not fit `CardList`, and whatever the client raises.
    """
    tid, mid = run["transcript_id"], run["meeting_id"]
    items = load_card_items(mid, tid)
    if not items:
        return {**dict.fromkeys(COUNT_KEYS, 0), "written": 0}
    segments = load_segments_with_speakers(tid)
    user = render_cards_input(_meeting(mid), segments, items, speaker_ordinals(tid))
    model = AI_TRANSCRIPT_CARDS_MODEL
    tokens = client.count_tokens(model=model, system=CARDS_SYSTEM, user=user)
    if tokens > TRANSCRIPT_TOKEN_CEILING:
        raise TranscriptHeld("token_ceiling", f"{tokens} tokens > ceiling {TRANSCRIPT_TOKEN_CEILING}")
    res = client.call(model=model, system=CARDS_SYSTEM, user=user, schema=CARDS_SCHEMA, max_tokens=64000,
                      effort="medium")
    try:
        parsed = CardList.model_validate(res.data)
    except ValidationError as e:
        raise TranscriptHeld("schema_invalid", f"cards response failed validation: {e}") from e
    rows, counts = validate_cards(parsed, items=items, segments=segments)
    written = 0
    if rows and not dry_run:
        written = write_cards(tid, run["source_uploaded_at"], rows, model=model, prompt_version=CARDS_PROMPT_VERSION)
    return {**counts, "written": written}


def format_report(run: dict, counts: dict, usage: Usage, cost_usd: float) -> str:
    """The one line a build reports: what was placed, carded, kept, and dropped, and what the call cost."""
    tokens_in = usage.input_tokens + usage.cache_creation_input_tokens + usage.cache_read_input_tokens
    return (f"cards: meeting {run['meeting_id']} transcript {run['transcript_id']}: "
            f"{counts['placed']} placed, {counts['cards']} cards ({counts['discussed']} discussed, "
            f"{counts['missing']} missing, {counts['extra']} extra), "
            f"details {counts['details_kept']} kept {counts['details_repointed']} re-pointed "
            f"{counts['details_dropped']} dropped, "
            f"bounds {counts['bounds_kept']} kept {counts['bounds_dropped']} dropped, "
            f"{counts['starts_moved']} starts moved {START_MOVED_S:g} s or more, "
            f"{tokens_in} in {usage.output_tokens} out, ${cost_usd:.4f}")


def _finish_run(transcript_id: int, status: str, *, error: str | None, counts: dict | None, model: str | None) -> None:
    """Record how a claimed attempt ended. The row then describes that attempt and no earlier one."""
    with db_cursor() as cur:
        cur.execute("""UPDATE transcript_card_runs
                          SET status = %s, last_error = %s, counts = %s::jsonb, model = %s, updated_at = now()
                        WHERE transcript_id = %s""",
                    [status, error[:2000] if error else None, json.dumps(counts or {}), model, transcript_id])


def _hand_back(transcript_id: int, detail: str) -> None:
    """A 429 is the API's problem, not the meeting's: return the attempt the claim counted.

    The row stays `claimed` with `last_attempted_at` as the claim set it, so
    it waits out its 24 hours and is then claimed again.
    """
    with db_cursor() as cur:
        cur.execute("""UPDATE transcript_card_runs
                          SET last_error = %s, attempts = GREATEST(attempts - 1, 0), updated_at = now()
                        WHERE transcript_id = %s""", [detail[:2000], transcript_id])


def process_run(run: dict, *, client, notes: str, dry_run: bool = False) -> tuple[str, str | None]:
    """Build one run inside an `ai_runs` row and record how it ended. Returns the outcome and its report line.

    The outcome is `done`, `failed`, `held`, or `rate_limited`. `done` needs a
    card for every placed item; a reply that skipped one is `failed` with a
    `last_error` beginning `incomplete:`, its other cards written, and is
    retried by the claim's own rule. A hold is not retried until a new upload
    or a prompt bump. `AIFatalError` propagates with the attempt left claimed.
    A dry run records nothing but its `ai_runs` row, since its call is paid for.
    """
    from docket.ai.transcripts.pipeline import _cost
    from docket.ai.worker import RunSummary, _close_run, _open_run

    tid, mid, model = run["transcript_id"], run["meeting_id"], AI_TRANSCRIPT_CARDS_MODEL
    with db() as conn:
        run_id = _open_run(conn, RUN_NAME, model, notes)
    summary = RunSummary(stage=RUN_NAME)
    emissions: list[tuple[str, Usage]] = []
    status, error, counts, report = "failed", None, None, None
    try:
        try:
            with usage_capture() as emissions:
                counts = build_for_transcript(run, client=client, dry_run=dry_run)
        finally:
            summary.cost_usd, summary.usage = _cost(emissions)
        if counts["placed"]:
            report = format_report(run, counts, summary.usage, summary.cost_usd)
            log.info("%s", report)
        if counts["written"] < 0:
            error = "transcript changed during the run"
        elif counts["missing"]:
            error = f"incomplete: {counts['cards']} of {counts['placed']} placed items carded"
        else:
            status = "done"
    except TranscriptHeld as e:
        status, error = "held", f"{e.reason}: {e}"
    except AIPermanentRowError as e:
        status, error = "held", f"permanent: {e}"
    except AIRateLimited as e:
        status, error = "rate_limited", f"rate limited: {e}"
    except AITransientError as e:
        error = str(e)
    except AIFatalError:
        raise
    except Exception as e:  # a bug in the build must not take the tick down
        log.exception("cards: meeting %s transcript %s crashed", mid, tid)
        error = f"{type(e).__name__}: {e}"
    finally:
        summary.rows_processed, summary.rows_failed = (1, 0) if status == "done" else (0, 1)
        with db() as conn:
            _close_run(conn, run_id, summary)
    if status != "done":
        log.warning("cards: meeting %s transcript %s: %s (%s)", mid, tid, status, error)
    if not dry_run:
        if status == "rate_limited":
            _hand_back(tid, error)
        else:
            _finish_run(tid, status, error=error, counts=counts,
                        model=model if counts and counts["placed"] else None)
    return status, report


def run_cards(*, limit: int, notes: str = "cron_cards", force_budget: bool = False, client=None,
              meeting_ids: list[int] | None = None, dry_run: bool = False) -> CardsSummary:
    """Build search cards for up to `limit` meetings, newest first, inside the daily AI budget.

    Without `meeting_ids` it takes transcripts that lack a current card run
    (`CLAIM_CARDS_SQL`). With them it takes those meetings, in the order
    given and still no more than `limit`, whatever their run rows say; a named
    meeting that cannot be carded (no public Birmingham transcript past the
    events stage) is passed over with a warning. The day's spend is read
    before each meeting and the loop stops, `stopped_reason = "budget"`, once
    it has reached `AI_DAILY_BUDGET_USD`, unless `force_budget`. A rate limit
    stops the loop too. With `dry_run` nothing is claimed and no card or run
    row is written; the model is still called and its `ai_runs` row written.

    Raises `AIFatalError` when the model has no `PRICING` entry or the client
    cannot be built, before anything is claimed.
    """
    from docket.ai.transcripts.client import StructuredClient
    from docket.ai.worker import _today_spend

    if AI_TRANSCRIPT_CARDS_MODEL not in PRICING:
        raise AIFatalError(f"cards model {AI_TRANSCRIPT_CARDS_MODEL!r} has no PRICING entry; add it before running")
    client = client or StructuredClient()
    s = CardsSummary()
    targets: list[int | None] = list(meeting_ids)[:max(limit, 0)] if meeting_ids else [None] * max(limit, 0)
    seen: list[int] = []
    for meeting_id in targets:
        with db() as conn:
            spent = _today_spend(conn)
        if spent >= AI_DAILY_BUDGET_USD and not force_budget:
            s.stopped_reason = "budget"
            break
        run = peek_cards(meeting_id, seen) if dry_run else claim_cards(meeting_id)
        if run is None:
            if meeting_id is None:
                break
            log.warning("cards: meeting %s: nothing to build (it needs a public Birmingham transcript "
                        "past the events stage)", meeting_id)
            continue
        seen.append(run["transcript_id"])
        outcome, report = process_run(run, client=client, notes=notes, dry_run=dry_run)
        if report:
            s.reports.append(report)
        if outcome == "rate_limited":
            s.stopped_reason = "rate_limited"
            break
        if outcome == "done":
            s.built += 1
        elif outcome == "held":
            s.held += 1
        else:
            s.failed += 1
    return s
