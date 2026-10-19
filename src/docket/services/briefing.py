"""Briefing facts for the city page.

The city page at /al/<slug>/ opens with a briefing for the cities whose
``municipalities.metadata`` carries ``"briefing": true`` (migration 037 sets
it for Birmingham). This module owns three things the page depends on:

* the source-per-meeting rule (``chosen_source_cte``): for each meeting the
  chosen vote source is ``minutes_text`` when the meeting has any
  non-review vote from the minutes, otherwise ``manual``, then ``api``, then
  ``video_ocr``; every count on the page joins votes through that choice
  and excludes ``needs_review`` votes, so a fact from the video and a fact
  from the minutes are never merged (docs/PRINCIPLES.md, keep the sources
  apart);
* the dollar check (``passes_dollar_check``): an item's stored amount is
  used in prose only when the item's own text or headline backs it;
* the precomputed heavy facts: the split votes of the last 180 days, the
  newest split ever, and each member's twelve-month roll-call counts, in
  the table ``city_briefing_facts`` (one row per city per fact set),
  rebuilt by the worker task ``briefing_facts`` with one upsert per city
  and read by the route in one query.

Imports nothing from docket.web or docket.worker.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta, timezone

from docket.analysis.structured_facts import extract_dollar_amounts
from docket.db import db_cursor
from docket.services.query import _UPCOMING_PREDICATE_MT

FACT_SETS = ("split_votes", "member_counts")
SPLIT_WINDOW_DAYS = 180
MEMBER_WINDOW_DAYS = 365
FACTS_STALE_AFTER = timedelta(hours=48)
SPLITS_KEPT = 5

# Plain-words labels for the process badges the signals list shows (M5).
SIGNAL_LABELS: dict[str, str] = {
    "hidden_on_consent": "Passed without discussion, on the consent agenda",
    "legal_settlement": "Legal settlements",
    "sole_source": "Contracts awarded without competing bids",
    "emergency_action": "Emergency actions",
    "amends_prior_contract": "Changes to earlier contracts",
}


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def is_briefing_city(municipality: dict | None) -> bool:
    """True when the municipality row's metadata carries ``"briefing": true``."""
    if not municipality:
        return False
    meta = municipality.get("metadata")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except ValueError:
            return False
    return isinstance(meta, dict) and meta.get("briefing") is True


def clip_words(text: str | None, n: int) -> str:
    """The first ``n`` whitespace-separated words of ``text``, "…" appended when cut."""
    words = (text or "").split()
    if n < 1:
        n = 1
    if len(words) <= n:
        return " ".join(words)
    return " ".join(words[:n]) + "…"


def _largest_power_of_ten(amount: float) -> float:
    """The largest power of ten that divides ``amount`` (in dollars; cents allowed).

    $10,100,000 → 100,000; $7,000,000 → 1,000,000; $1,234.56 → 0.01.
    """
    cents = int(round(amount * 100))
    if cents <= 0:
        return 1.0
    p = 1
    while cents % (p * 10) == 0:
        p *= 10
    return p / 100.0


def passes_dollar_check(
    title: str | None,
    description: str | None,
    headline: str | None,
    dollars_amount,
) -> bool:
    """Whether the stored amount may be quoted in prose.

    Passes when the item's title and description together hold exactly one
    dollar amount and it equals the stored amount, or when some amount ``h``
    in the headline is within ``min(p / 2, h / 10)`` of the stored amount,
    ``p`` being the largest power of ten dividing ``h`` (so a headline
    "$10.1 million" accepts a stored 10,125,000 and "$10 million" accepts
    9,600,000 but not 14,000,000). Anything else fails, and the item is
    left out of the prose rather than shown with a number its own text does
    not back.
    """
    if dollars_amount is None:
        return False
    stored = float(dollars_amount)
    text_amounts = extract_dollar_amounts(f"{title or ''} {description or ''}")
    if len(text_amounts) == 1:
        (only,) = text_amounts
        if math.isclose(only, stored, abs_tol=0.005):
            return True
    for h in extract_dollar_amounts(headline):
        p = _largest_power_of_ten(h)
        if abs(h - stored) <= min(p / 2, h / 10):
            return True
    return False


# ---------------------------------------------------------------------------
# The source-per-meeting rule
# ---------------------------------------------------------------------------


def chosen_source_cte(scope: str) -> str:
    """The CTE body naming each meeting's chosen vote source, scoped by the caller.

    ``scope`` is a SQL condition on ``v.meeting_id`` (``v.meeting_id = %s``,
    or ``v.meeting_id IN (SELECT id FROM meetings WHERE ...)``) so the
    aggregate never groups votes outside the meetings the query is about;
    its parameters come first in the caller's parameter list. Use it as::

        WITH <chosen_source_cte(scope)>
        SELECT ... FROM votes v
        JOIN meeting_vote_source s
          ON s.meeting_id = v.meeting_id AND s.chosen_source = v.source
         AND v.needs_review = FALSE
    """
    return f"""meeting_vote_source AS (
        SELECT v.meeting_id,
               CASE WHEN bool_or(v.source = 'minutes_text') THEN 'minutes_text'
                    WHEN bool_or(v.source = 'manual') THEN 'manual'
                    WHEN bool_or(v.source = 'api') THEN 'api'
                    ELSE 'video_ocr' END AS chosen_source
          FROM votes v
         WHERE v.needs_review = FALSE AND ({scope})
         GROUP BY v.meeting_id
    )"""


_CHOSEN_JOIN = """
    JOIN meeting_vote_source s
      ON s.meeting_id = v.meeting_id
     AND s.chosen_source = v.source
     AND v.needs_review = FALSE
"""


# ---------------------------------------------------------------------------
# Precompute
# ---------------------------------------------------------------------------


# One split vote as the payload and the opener both carry it: the vote's
# tally, how many active item links it has, the first linked item (used
# only when the count is one), and the members who voted nay or abstained.
# ``c`` is a row of a ``chosen`` CTE carrying the vote columns and
# ``meeting_date``.
_SPLIT_ROW_COLUMNS = """
               c.id AS vote_id, c.meeting_id, c.meeting_date, c.source, c.result,
               c.yeas, c.nays, c.abstentions,
               (SELECT count(*) FROM vote_agenda_items l
                 WHERE l.vote_id = c.id AND l.is_active) AS linked_item_count,
               (SELECT json_build_object('id', ai.id, 'label', COALESCE(ai.headline, ai.title))
                  FROM vote_agenda_items l JOIN agenda_items ai ON ai.id = l.agenda_item_id
                 WHERE l.vote_id = c.id AND l.is_active
                 ORDER BY ai.id LIMIT 1) AS item_one,
               (SELECT json_agg(json_build_object(
                           'member_name', mv.member_name,
                           'council_member_id', mv.council_member_id,
                           'position', CASE WHEN mv.position IN ('nay', 'no') THEN 'nay'
                                            ELSE mv.position END)
                       ORDER BY mv.id)
                  FROM member_votes mv
                 WHERE mv.vote_id = c.id AND mv.position IN ('nay', 'no', 'abstain')) AS dissenters
"""

_SPLIT_VOTES_SQL = (
    "WITH "
    + chosen_source_cte(
        "v.meeting_id IN (SELECT id FROM meetings WHERE municipality_id = %s AND is_hidden = FALSE)"
    )
    + """,
    chosen AS (
        SELECT v.id, v.meeting_id, m.meeting_date, v.source, v.result,
               v.yeas, v.nays, v.abstentions
          FROM votes v
    """
    + _CHOSEN_JOIN
    + """
          JOIN meetings m ON m.id = v.meeting_id
    ),
    splits AS (
        SELECT """
    + _SPLIT_ROW_COLUMNS
    + """
          FROM chosen c
         WHERE c.nays > 0 OR c.abstentions > 0
         ORDER BY c.meeting_date DESC, c.id DESC
         LIMIT %s
    )
    SELECT (SELECT count(*) FROM chosen WHERE meeting_date >= %s) AS votes_in_window,
           (SELECT json_agg(row_to_json(s)) FROM splits s) AS splits
    """
)

_MEMBER_COUNTS_SQL = (
    "WITH "
    + chosen_source_cte(
        "v.meeting_id IN (SELECT id FROM meetings WHERE municipality_id = %s"
        " AND is_hidden = FALSE AND meeting_date >= %s)"
    )
    + """
    SELECT mv.council_member_id,
           count(*) AS roll_calls,
           count(*) FILTER (WHERE mv.position <> 'absent') AS attended,
           count(*) FILTER (
               WHERE mv.position <> 'absent'
                 AND NOT ((mv.position IN ('yea', 'yes') AND v.result = 'passed')
                       OR (mv.position IN ('nay', 'no') AND v.result = 'failed'))
           ) AS against
      FROM votes v
    """
    + _CHOSEN_JOIN
    + """
      JOIN member_votes mv ON mv.vote_id = v.id
     WHERE mv.council_member_id IS NOT NULL
     GROUP BY mv.council_member_id
    """
)

_UPSERT_SQL = """
    INSERT INTO city_briefing_facts (municipality_id, fact_set, payload, computed_at)
    VALUES (%s, 'split_votes', %s::jsonb, now()),
           (%s, 'member_counts', %s::jsonb, now())
    ON CONFLICT (municipality_id, fact_set)
    DO UPDATE SET payload = EXCLUDED.payload, computed_at = EXCLUDED.computed_at
"""


def _json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


def _shape_split(row: dict) -> dict:
    item = row.get("item_one") if row.get("linked_item_count") == 1 else None
    return {
        "vote_id": row["vote_id"],
        "meeting_id": row["meeting_id"],
        "meeting_date": row["meeting_date"],
        "source": row["source"],
        "result": row["result"],
        "yeas": row["yeas"],
        "nays": row["nays"],
        "abstentions": row["abstentions"],
        "item": item,
        "linked_item_count": row["linked_item_count"],
        "dissenters": row.get("dissenters") or [],
    }


def recompute_city_facts(municipality_id: int) -> dict:
    """Rebuild both fact sets for one city: two SELECTs and one upsert.

    Returns ``{"split_votes": payload, "member_counts": payload}``.
    """
    today = date.today()
    split_since = today - timedelta(days=SPLIT_WINDOW_DAYS)
    member_since = today - timedelta(days=MEMBER_WINDOW_DAYS)

    with db_cursor() as cur:
        cur.execute(_SPLIT_VOTES_SQL, (municipality_id, SPLITS_KEPT, split_since))
        row = cur.fetchone()
        all_splits = [_shape_split(r) for r in (row["splits"] or [])]
        for s in all_splits:
            # row_to_json renders a DATE as 'YYYY-MM-DD'; keep that form.
            s["meeting_date"] = str(s["meeting_date"])
        in_window = [s for s in all_splits if s["meeting_date"] >= split_since.isoformat()]
        split_votes = {
            "window_days": SPLIT_WINDOW_DAYS,
            "since": split_since.isoformat(),
            "splits": in_window[:SPLITS_KEPT],
            "last_split": all_splits[0] if all_splits else None,
            "votes_in_window": int(row["votes_in_window"] or 0),
        }

        cur.execute(_MEMBER_COUNTS_SQL, (municipality_id, member_since))
        members = {
            str(r["council_member_id"]): {
                "roll_calls": int(r["roll_calls"]),
                "attended": int(r["attended"]),
                "against": int(r["against"]),
            }
            for r in cur.fetchall()
        }
        member_counts = {
            "window_days": MEMBER_WINDOW_DAYS,
            "since": member_since.isoformat(),
            "members": members,
        }

        cur.execute(
            _UPSERT_SQL,
            (
                municipality_id,
                json.dumps(split_votes, default=_json_default),
                municipality_id,
                json.dumps(member_counts, default=_json_default),
            ),
        )

    return {"split_votes": split_votes, "member_counts": member_counts}


def recompute_all_flagged() -> int:
    """Rebuild the facts of every active city flagged ``briefing``; returns how many."""
    with db_cursor() as cur:
        cur.execute(
            """SELECT id FROM municipalities
                WHERE active = TRUE AND metadata @> '{"briefing": true}'::jsonb
                ORDER BY id"""
        )
        ids = [r["id"] for r in cur.fetchall()]
    for mid in ids:
        recompute_city_facts(mid)
    return len(ids)


def get_city_facts(municipality_id: int) -> dict[str, dict]:
    """Both fact rows for a city in one query: ``{fact_set: {"payload", "computed_at"}}``.

    Empty when the task has never run for the city.
    """
    with db_cursor() as cur:
        cur.execute(
            "SELECT fact_set, payload, computed_at FROM city_briefing_facts WHERE municipality_id = %s",
            (municipality_id,),
        )
        return {
            r["fact_set"]: {"payload": r["payload"], "computed_at": r["computed_at"]}
            for r in cur.fetchall()
        }


def facts_freshness(facts: dict | None) -> dict:
    """``{"state": "good"|"warn"|"unknown", "computed_at", "label"}`` for a facts dict.

    ``warn`` once the oldest row is more than 48 hours old; ``unknown`` when
    there is no row at all.
    """
    stamps = [v.get("computed_at") for v in (facts or {}).values() if v.get("computed_at")]
    if not stamps:
        return {"state": "unknown", "computed_at": None, "label": "Not computed yet"}
    oldest = min(
        s.replace(tzinfo=timezone.utc) if s.tzinfo is None else s for s in stamps
    )
    age = datetime.now(timezone.utc) - oldest
    if age > FACTS_STALE_AFTER:
        return {"state": "warn", "computed_at": oldest, "label": "Stale"}
    return {"state": "good", "computed_at": oldest, "label": "Computed"}


# ---------------------------------------------------------------------------
# The opener (M2): the first screen of a flagged city's page
# ---------------------------------------------------------------------------

OPENER_SENTENCE_WORDS = 25   # the design's ceiling per sentence
OPENER_CLIP_FLOOR = 4        # a clipped clause keeps at least this many words
OPENER_STALE_DAYS = 14       # "last met on" wording past this age
OPENER_TEXT_MAX = 300        # the meta description's ceiling, in characters
OPENER_BIGGEST_SCAN = 20     # items with an amount examined for the dollar check

_NUMBER_WORDS = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
    "nineteen", "twenty",
]


def number_word(n: int) -> str:
    """``3`` → ``"three"``; numbers past twenty stay as digits."""
    if 0 <= n < len(_NUMBER_WORDS):
        return _NUMBER_WORDS[n]
    return str(n)


def amount_in_words(amount) -> str:
    """``10100000`` → ``"$10.1 million"``; ``2000000`` → ``"$2 million"``; ``850000`` → ``"$850,000"``."""
    value = float(amount)
    for unit, name in ((1_000_000_000, "billion"), (1_000_000, "million")):
        if value >= unit:
            scaled = round(value / unit, 1)
            text = f"{scaled:.1f}".rstrip("0").rstrip(".")
            return f"${text} {name}"
    return f"${int(round(value)):,}"


_LEADING_AMOUNT = re.compile(
    r"^\$\s?\d[\d,]*(?:\.\d+)?\s*(?:billion|million|thousand|[bmk])?\b[\s:,\-–—]*",
    re.IGNORECASE,
)


def _headline_without_leading_amount(headline: str) -> str:
    """Strip a dollar figure that opens the headline, so the opener's own
    amount is not printed twice ("a $10.1 million $10.1 million contract")."""
    stripped = _LEADING_AMOUNT.sub("", headline or "", count=1).strip()
    return stripped or (headline or "").strip()


def _long_date(d: date, *, today: date | None = None) -> str:
    """``Tuesday, October 14``, with the year appended when it is not this year."""
    today = today or date.today()
    text = d.strftime("%A, %B ") + str(d.day)
    if d.year != today.year:
        text += f", {d.year}"
    return text


def _short_date(d: date) -> str:
    """``October 14``."""
    return d.strftime("%B ") + str(d.day)


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


_UPCOMING_MT = "(" + _UPCOMING_PREDICATE_MT + ")"

_LAST_MEETING_SQL = f"""
    SELECT mt.id, mt.meeting_date, mt.start_time,
           (SELECT count(*) FROM agenda_items ai WHERE ai.meeting_id = mt.id) AS item_count
      FROM meetings mt
     WHERE mt.municipality_id = %s
       AND mt.is_hidden = FALSE
       AND mt.meeting_type = 'council'
       AND mt.meeting_date IS NOT NULL
       AND NOT {_UPCOMING_MT}
       AND EXISTS (SELECT 1 FROM agenda_items ai WHERE ai.meeting_id = mt.id)
     ORDER BY mt.meeting_date DESC, mt.id DESC
     LIMIT 1
"""

_NEXT_MEETING_SQL = f"""
    SELECT mt.id, mt.meeting_date, mt.start_time,
           (SELECT count(*) FROM agenda_items ai WHERE ai.meeting_id = mt.id) AS item_count
      FROM meetings mt
     WHERE mt.municipality_id = %s
       AND mt.is_hidden = FALSE
       AND mt.meeting_type = 'council'
       AND mt.meeting_date IS NOT NULL
       AND {_UPCOMING_MT}
     ORDER BY mt.meeting_date ASC, mt.start_time ASC NULLS LAST, mt.id ASC
     LIMIT 1
"""

_BIGGEST_ITEMS_SQL = """
    SELECT ai.id, ai.title, ai.description, ai.headline, ai.dollars_amount
      FROM agenda_items ai
     WHERE ai.meeting_id = %s AND ai.dollars_amount IS NOT NULL
     ORDER BY ai.dollars_amount DESC, ai.id ASC
     LIMIT %s
"""

_MEETING_SPLITS_SQL = (
    "WITH "
    + chosen_source_cte("v.meeting_id = %s")
    + """,
    chosen AS (
        SELECT v.id, v.meeting_id, m.meeting_date, v.source, v.result,
               v.yeas, v.nays, v.abstentions
          FROM votes v
    """
    + _CHOSEN_JOIN
    + """
          JOIN meetings m ON m.id = v.meeting_id
    ),
    splits AS (
        SELECT """
    + _SPLIT_ROW_COLUMNS
    + """
          FROM chosen c
         WHERE c.nays > 0 OR c.abstentions > 0
         ORDER BY c.id ASC
    )
    SELECT (SELECT chosen_source FROM meeting_vote_source) AS chosen_source,
           (SELECT count(*) FROM chosen) AS vote_count,
           (SELECT json_agg(row_to_json(s)) FROM splits s) AS splits
    """
)


def opener_facts(municipality: dict) -> dict | None:
    """The counted rows the opener is written from, or None for an unflagged city.

    ``{"last": {...} | None, "next": {...} | None, "beats": [...]}``. ``last``
    holds ``meeting_id``, ``meeting_date``, ``item_count``, ``stale``,
    ``biggest`` (``{item_id, amount, headline}`` or None), ``splits``
    (``{"count", "first"}``), ``vote_count``, and ``source_label`` ("" or
    "from the video"). ``next`` holds ``meeting_id``, ``meeting_date``,
    ``item_count``. ``beats`` is what the template renders (see
    :func:`opener_beats`). At most four queries.
    """
    if not is_briefing_city(municipality):
        return None
    mid = municipality["id"]
    today = date.today()
    last = None
    nxt = None
    with db_cursor() as cur:
        cur.execute(_LAST_MEETING_SQL, (mid,))
        row = cur.fetchone()
        if row:
            meeting_date = _as_date(row["meeting_date"])
            last = {
                "meeting_id": row["id"],
                "meeting_date": meeting_date,
                "item_count": int(row["item_count"] or 0),
                "stale": (today - meeting_date).days > OPENER_STALE_DAYS,
                "biggest": None,
                "splits": {"count": 0, "first": None},
                "vote_count": 0,
                "source_label": "",
            }
            cur.execute(_BIGGEST_ITEMS_SQL, (row["id"], OPENER_BIGGEST_SCAN))
            for item in cur.fetchall():
                if passes_dollar_check(
                    item["title"], item["description"], item["headline"], item["dollars_amount"]
                ):
                    last["biggest"] = {
                        "item_id": item["id"],
                        "amount": item["dollars_amount"],
                        "headline": item["headline"] or item["title"],
                    }
                    break
            cur.execute(_MEETING_SPLITS_SQL, (row["id"],))
            votes = cur.fetchone()
            splits = [_shape_split(r) for r in (votes["splits"] or [])]
            last["vote_count"] = int(votes["vote_count"] or 0)
            last["splits"] = {"count": len(splits), "first": splits[0] if splits else None}
            last["source_label"] = "from the video" if votes["chosen_source"] == "video_ocr" else ""
        cur.execute(_NEXT_MEETING_SQL, (mid,))
        row = cur.fetchone()
        if row:
            nxt = {
                "meeting_id": row["id"],
                "meeting_date": _as_date(row["meeting_date"]),
                "item_count": int(row["item_count"] or 0),
            }
    facts = {"last": last, "next": nxt}
    facts["beats"] = opener_beats(facts, municipality)
    return facts


def _seg(text: str, href: str | None = None, kind: str = "text") -> dict:
    return {"text": text, "href": href, "kind": kind}


def _budget(rest: str) -> int:
    """Words left for a clipped clause once ``rest`` of the sentence is counted."""
    return max(OPENER_CLIP_FLOOR, OPENER_SENTENCE_WORDS - len(rest.split()))


def _split_item_clause(split: dict, meeting_date: date) -> str:
    if split.get("item"):
        return split["item"]["label"] or ""
    n = int(split.get("linked_item_count") or 0)
    if n > 1:
        return f"a consent-agenda vote covering {n} items"
    return f"a vote at the {_short_date(meeting_date)} meeting"


def _split_sentence(last: dict, slug: str) -> tuple[list[dict], str | None]:
    """The split sentence's segments and, when the dissenter phrase links to
    the vote's anchor, that anchor (so the action link does not repeat it)."""
    splits = last["splits"]
    count = splits["count"]
    suffix = f" {last['source_label']}" if last["source_label"] else ""
    if count == 0:
        if last["vote_count"] > 0:
            return [_seg(f"Every vote was unanimous{suffix}. ")], None
        return [], None
    first = splits["first"]
    meeting_href = f"/al/{slug}/meetings/{last['meeting_id']}/"
    anchor = f"{meeting_href}#vote-{first['vote_id']}"
    if count > 1:
        return [_seg(f"{number_word(count).capitalize()} votes split{suffix}. ")], None
    verb = "passed" if first["result"] == "passed" else "failed"
    tally = f"{verb} {first['yeas']} to {first['nays']},"
    dissenters = first.get("dissenters") or []
    named = [d for d in dissenters if d.get("council_member_id") and d.get("member_name")]
    if len(dissenters) == 1 and len(named) == 1:
        d = named[0]
        action = "abstaining" if d["position"] == "abstain" else "voting no"
        rest = f"One vote split: {tally} with {d['member_name']} {action}{suffix}."
        clause = clip_words(_split_item_clause(first, last["meeting_date"]), _budget(rest))
        return [
            _seg(f"One vote split: {clause} {tally} with "),
            _seg(d["member_name"], f"/al/{slug}/council/{d['council_member_id']}/"),
            _seg(f" {action}{suffix}. "),
        ], None
    positions = {d.get("position") for d in dissenters}
    action = "abstaining" if positions == {"abstain"} else "voting no"
    how_many = number_word(len(dissenters)) if dissenters else "some"
    phrase = f"with {how_many} members {action}"
    rest = f"One vote split: {tally} {phrase}{suffix}."
    clause = clip_words(_split_item_clause(first, last["meeting_date"]), _budget(rest))
    return [
        _seg(f"One vote split: {clause} {tally} "),
        _seg(phrase, anchor),
        _seg(f"{suffix}. "),
    ], anchor


def opener_beats(facts: dict | None, municipality: dict) -> list[list[dict]]:
    """The opener as two beats of segments ``{"text", "href", "kind"}``.

    ``kind`` is ``"text"``, ``"link"`` (a fact linked to its source), or
    ``"action"`` (the beat's closing arrow link, left out of the plain
    text). Each sentence is at most 25 words: the headline and the split
    item clause are clipped to what the rest of their sentence leaves.
    """
    slug = municipality["slug"]
    name = municipality.get("name") or slug
    beats: list[list[dict]] = []

    last = (facts or {}).get("last")
    beat: list[dict] = []
    if not last:
        beat.append(_seg(f"docket.pub has not indexed a {name} meeting yet."))
    else:
        when = _long_date(last["meeting_date"])
        verb = "last met" if last["stale"] else "met"
        n = last["item_count"]
        beat.append(_seg(
            f"Last meeting. The council {verb} on {when} and acted on {n} "
            f"item{'s' if n != 1 else ''}. "
        ))
        biggest = last.get("biggest")
        if biggest:
            amount = amount_in_words(biggest["amount"])
            rest = f"The largest was a {amount}."
            headline = clip_words(_headline_without_leading_amount(biggest["headline"]), _budget(rest))
            beat.append(_seg("The largest was a "))
            beat.append(_seg(f"{amount} {headline}", f"/al/{slug}/items/{biggest['item_id']}/", "link"))
            beat.append(_seg(". "))
        split_segs, used_anchor = _split_sentence(last, slug)
        for s in split_segs:
            if s["href"]:
                s["kind"] = "link"
        beat.extend(split_segs)
        meeting_href = f"/al/{slug}/meetings/{last['meeting_id']}/"
        first = last["splits"]["first"]
        if first and not used_anchor:
            action_href = f"{meeting_href}#vote-{first['vote_id']}"
        else:
            action_href = meeting_href
        beat.append(_seg(f"Read the {_short_date(last['meeting_date'])} meeting →", action_href, "action"))
    beats.append(beat)

    nxt = (facts or {}).get("next")
    beat = []
    if not nxt:
        beat.append(_seg(
            "No agenda is posted yet for the next meeting; agendas usually appear a few days before."
        ))
    else:
        n = nxt["item_count"]
        sentence = f"Next meeting. {_long_date(nxt['meeting_date'])}"
        if n > 0:
            sentence += f", with {n} item{'s' if n != 1 else ''} on the agenda"
        beat.append(_seg(sentence + ". "))
        beat.append(_seg("See the agenda →", f"/al/{slug}/meetings/{nxt['meeting_id']}/", "action"))
    beats.append(beat)
    return beats


_BEAT_LABELS = ("Last meeting.", "Next meeting.")


def opener_text(facts: dict | None, municipality: dict) -> str:
    """The opener as plain text for the page's meta description.

    The beats' sentences joined by a space, action links left out, cut at
    the last full stop before 300 characters when longer.
    """
    beats = (facts or {}).get("beats") or opener_beats(facts, municipality)
    parts = []
    for beat in beats:
        text = "".join(s["text"] for s in beat if s["kind"] != "action").strip()
        if text:
            parts.append(text)
    text = " ".join(parts)
    if len(text) > OPENER_TEXT_MAX:
        cut = text.rfind(".", 0, OPENER_TEXT_MAX)
        text = text[: cut + 1] if cut > 0 else text[:OPENER_TEXT_MAX]
        # A beat label left dangling by the cut ("... voting no. Next
        # meeting.") says nothing on its own.
        for label in _BEAT_LABELS:
            if text.endswith(label) and len(text) > len(label):
                text = text[: -len(label)].rstrip()
    return text


# ---------------------------------------------------------------------------
# The meetings list (M2)
# ---------------------------------------------------------------------------

_BRIEFING_MEETINGS_SQL = (
    f"""
    WITH scoped AS (
        SELECT mt.*
          FROM meetings mt
          JOIN municipalities m ON m.id = mt.municipality_id
         WHERE m.slug = %s
           AND mt.is_hidden = FALSE
           AND (mt.agenda_url IS NOT NULL OR mt.minutes_url IS NOT NULL OR mt.video_url IS NOT NULL
                OR EXISTS (SELECT 1 FROM agenda_items ai WHERE ai.meeting_id = mt.id))
         ORDER BY mt.meeting_date DESC NULLS LAST, mt.id DESC
         LIMIT %s
    ),
    """
    + chosen_source_cte("v.meeting_id IN (SELECT id FROM scoped)")
    + f""",
    chosen AS (
        SELECT v.id, v.meeting_id, v.nays, v.abstentions
          FROM votes v
    """
    + _CHOSEN_JOIN
    + f"""
    )
    SELECT mt.id, mt.title, mt.meeting_date, mt.start_time,
           mt.agenda_url, mt.minutes_url, mt.video_url,
           {_UPCOMING_MT} AS upcoming,
           (SELECT count(*) FROM agenda_items ai WHERE ai.meeting_id = mt.id) AS item_count,
           (SELECT sum(ai.dollars_amount) FROM agenda_items ai WHERE ai.meeting_id = mt.id) AS total_dollars,
           (SELECT count(*) FROM chosen c WHERE c.meeting_id = mt.id) AS vote_count,
           (SELECT count(*) FROM chosen c
             WHERE c.meeting_id = mt.id AND (c.nays > 0 OR c.abstentions > 0)) AS split_count
      FROM scoped mt
     ORDER BY mt.meeting_date DESC NULLS LAST, mt.id DESC
    """
)


def list_briefing_meetings(slug: str, limit: int = 6) -> list[dict]:
    """The newest meetings that have an agenda item or a document link, past or upcoming.

    Each row: ``id, title, meeting_date, start_time, upcoming, item_count,
    total_dollars`` (None when no item has an amount, else with
    ``total_dollars_text``), ``split_count`` (None when the meeting has no
    chosen-source votes), ``agenda_url, minutes_url, video_url``, and
    ``date_text`` (``Tuesday, October 14``, year added when not this year).
    """
    with db_cursor() as cur:
        cur.execute(_BRIEFING_MEETINGS_SQL, (slug, limit))
        rows = [dict(r) for r in cur.fetchall()]
    out = []
    for r in rows:
        total = r.pop("total_dollars")
        vote_count = int(r.pop("vote_count") or 0)
        r["item_count"] = int(r["item_count"] or 0)
        r["upcoming"] = bool(r["upcoming"])
        r["total_dollars"] = total
        r["total_dollars_text"] = amount_in_words(total) if total else None
        r["split_count"] = int(r["split_count"] or 0) if vote_count else None
        r["date_text"] = _long_date(_as_date(r["meeting_date"])) if r["meeting_date"] else ""
        out.append(r)
    return out


# ---------------------------------------------------------------------------
# The money door (M3): the largest items of the last 90 days
# ---------------------------------------------------------------------------

MONEY_WINDOW_DAYS = 90
MONEY_SCAN = 40      # items with an amount examined for the dollar check
MONEY_LINES = 3

_MONEY_ITEMS_SQL = """
    SELECT ai.id, ai.title, ai.description, ai.headline, ai.dollars_amount,
           ai.is_consent, ai.meeting_id, mt.meeting_date
      FROM agenda_items ai
      JOIN meetings mt ON ai.meeting_id = mt.id
     WHERE mt.municipality_id = %s
       AND mt.is_hidden = FALSE
       AND mt.meeting_date >= CURRENT_DATE - %s * INTERVAL '1 day'
       AND ai.dollars_amount IS NOT NULL
     ORDER BY ai.dollars_amount DESC, mt.meeting_date DESC, ai.id ASC
     LIMIT %s
"""


def money_items(municipality_id: int, days: int = MONEY_WINDOW_DAYS, limit: int = MONEY_LINES) -> list[dict]:
    """The largest items of the last ``days`` days whose text backs their amount.

    Scans at most forty rows ordered by amount and keeps the first ``limit``
    that pass :func:`passes_dollar_check`. Each row: ``item_id, amount,
    amount_text, headline`` (a leading dollar figure stripped, since the
    line prints the amount itself), ``meeting_id, meeting_date, date_text,
    is_consent``.
    """
    with db_cursor() as cur:
        cur.execute(_MONEY_ITEMS_SQL, (municipality_id, days, MONEY_SCAN))
        rows = [dict(r) for r in cur.fetchall()]
    out: list[dict] = []
    for r in rows:
        if not passes_dollar_check(r["title"], r["description"], r["headline"], r["dollars_amount"]):
            continue
        meeting_date = _as_date(r["meeting_date"])
        out.append({
            "item_id": r["id"],
            "amount": r["dollars_amount"],
            "amount_text": amount_in_words(r["dollars_amount"]),
            "headline": _headline_without_leading_amount(r["headline"] or r["title"]),
            "meeting_id": r["meeting_id"],
            "meeting_date": meeting_date,
            "date_text": _short_date(meeting_date),
            "is_consent": bool(r["is_consent"]),
        })
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# The disagreement door (M3): the precomputed split votes, shaped for the page
# ---------------------------------------------------------------------------


def _disagreement_line(split: dict, slug: str) -> dict:
    """One split of the ``split_votes`` payload as the door prints it."""
    meeting_date = _as_date(split["meeting_date"])
    meeting_href = f"/al/{slug}/meetings/{split['meeting_id']}/"
    anchor = f"{meeting_href}#vote-{split['vote_id']}"
    clause = _split_item_clause(split, meeting_date)
    clause_href = f"/al/{slug}/items/{split['item']['id']}/" if split.get("item") else anchor
    dissenters = []
    for d in split.get("dissenters") or []:
        name = d.get("member_name") or ""
        if not name:
            continue
        member_id = d.get("council_member_id")
        dissenters.append({
            "name": name,
            "href": f"/al/{slug}/council/{member_id}/" if member_id else None,
            "abstained": d.get("position") == "abstain",
        })
    return {
        "vote_id": split["vote_id"],
        "meeting_id": split["meeting_id"],
        "meeting_date": meeting_date,
        "date_text": _short_date(meeting_date),
        "clause": clause,
        "clause_href": clause_href,
        "verb": "passed" if split["result"] == "passed" else "failed",
        "yeas": split["yeas"],
        "nays": split["nays"],
        "abstentions": split.get("abstentions") or 0,
        "dissenters": dissenters,
        "from_video": split.get("source") == "video_ocr",
    }


def disagreement(facts: dict | None, municipality: dict | None = None) -> dict | None:
    """The ``split_votes`` payload shaped for ``partials/briefing/door_disagreed.html``.

    ``None`` when the city has no facts row (the task never ran) or no
    chosen-source vote at all, so the door renders nothing. Otherwise
    ``{"mode", "since", "since_text", "splits", "last_split",
    "votes_in_window"}`` where ``mode`` is ``"splits"`` (the window holds
    split votes, listed newest first), ``"unanimous"`` (no split in the
    window, the newest split ever carried as ``last_split``), or
    ``"unanimous_only"`` (votes in the window, no split ever).
    """
    row = (facts or {}).get("split_votes")
    if not row:
        return None
    payload = row.get("payload") or {}
    slug = (municipality or {}).get("slug") or ""
    splits = payload.get("splits") or []
    last_split = payload.get("last_split")
    votes_in_window = int(payload.get("votes_in_window") or 0)
    if not splits and not last_split and votes_in_window == 0:
        return None
    since = _as_date(payload["since"]) if payload.get("since") else None
    shaped_splits = [_disagreement_line(s, slug) for s in splits[:SPLITS_KEPT]]
    shaped_last = _disagreement_line(last_split, slug) if last_split else None
    if shaped_splits:
        mode = "splits"
    elif shaped_last:
        mode = "unanimous"
    elif votes_in_window > 0:
        mode = "unanimous_only"
    else:
        return None
    return {
        "mode": mode,
        "since": since,
        "since_text": _long_date(since).split(", ", 1)[-1] if since else "",
        "splits": shaped_splits,
        "last_split": shaped_last,
        "votes_in_window": votes_in_window,
    }


# ---------------------------------------------------------------------------
# The council door (M4): the roster with the precomputed twelve-month counts
# ---------------------------------------------------------------------------


def council_cards(members: list[dict], facts: dict | None, municipality: dict | None = None) -> list[dict]:
    """Each roster row with a ``briefing`` key: the member's twelve-month
    counts from the ``member_counts`` payload, or None.

    ``briefing`` is ``{"roll_calls", "attended", "against", "since" (date),
    "since_iso", "dissent_href"}``; ``dissent_href`` is the member page's
    Dissent filter from the payload's ``since`` date, which counts the same
    votes under the same source rule, and it is None when ``against`` is
    zero (no door onto a zero). A member with no chosen-source roll call in
    the window has no entry in the payload and gets ``briefing = None``.
    """
    payload = ((facts or {}).get("member_counts") or {}).get("payload") or {}
    counts = payload.get("members") or {}
    since = _as_date(payload["since"]) if payload.get("since") else None
    slug = (municipality or {}).get("slug") or ""
    out = []
    for m in members:
        row = dict(m)
        c = counts.get(str(m["id"])) if since else None
        if c and int(c.get("roll_calls") or 0) > 0:
            against = int(c.get("against") or 0)
            row["briefing"] = {
                "roll_calls": int(c["roll_calls"]),
                "attended": int(c.get("attended") or 0),
                "against": against,
                "since": since,
                "since_iso": since.isoformat(),
                "dissent_href": (
                    f"/al/{slug}/council/{m['id']}/?filter=dissent&since={since.isoformat()}"
                    if against > 0 else None
                ),
            }
        else:
            row["briefing"] = None
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# The topics door (M4): the tracked priorities and the busiest topics
# ---------------------------------------------------------------------------

TOPICS_WINDOW_DAYS = 90
TOPICS_LINES = 5

# The newest item carrying a policy badge, under the gates
# ``query.badge_volume_recent`` counts with (applied, confidence, completed,
# the city's significance threshold), so the example and the count agree.
_PRIORITY_LATEST_SQL = """
    SELECT ai.id, COALESCE(ai.headline, ai.title) AS label, mt.meeting_date
      FROM agenda_item_badges aib
      JOIN agenda_items ai ON ai.id = aib.agenda_item_id
      JOIN meetings mt ON mt.id = ai.meeting_id
     WHERE aib.city_id = %s
       AND aib.badge_slug = %s
       AND aib.confidence >= 0.6
       AND aib.status = 'applied'
       AND ai.processing_status = 'completed'
       AND mt.is_hidden = FALSE
       {significance}
     ORDER BY mt.meeting_date DESC, ai.id DESC
     LIMIT 1
"""

_BUSIEST_TOPICS_SQL = """
    WITH counted AS (
        SELECT ai.topic, count(*) AS count
          FROM agenda_items ai
          JOIN meetings mt ON mt.id = ai.meeting_id
         WHERE mt.municipality_id = %s
           AND mt.is_hidden = FALSE
           AND mt.meeting_date >= %s
           AND ai.topic IS NOT NULL
           AND ai.topic <> 'routine'
           AND ai.processing_status::text <> 'withdrawn'
         GROUP BY ai.topic
         ORDER BY count DESC, ai.topic ASC
         LIMIT %s
    )
    SELECT c.topic, c.count, ex.id AS item_id, ex.label, ex.meeting_date
      FROM counted c
      LEFT JOIN LATERAL (
          SELECT ai.id, COALESCE(ai.headline, ai.title) AS label, mt.meeting_date
            FROM agenda_items ai
            JOIN meetings mt ON mt.id = ai.meeting_id
           WHERE mt.municipality_id = %s
             AND mt.is_hidden = FALSE
             AND mt.meeting_date >= %s
             AND ai.topic = c.topic
             AND ai.processing_status::text <> 'withdrawn'
           ORDER BY mt.meeting_date DESC, ai.id DESC
           LIMIT 1
      ) ex ON TRUE
     ORDER BY c.count DESC, c.topic ASC
"""


def _example(row: dict | None) -> dict | None:
    """One item row (``id`` or ``item_id``, ``label``, ``meeting_date``) as a door line's example."""
    item_id = (row or {}).get("item_id", (row or {}).get("id"))
    if item_id is None:
        return None
    meeting_date = _as_date(row["meeting_date"])
    return {
        "item_id": item_id,
        "headline": row["label"] or "",
        "meeting_date": meeting_date,
        "date_text": _short_date(meeting_date),
        "date_long": _short_date(meeting_date) + f", {meeting_date.year}",
    }


def topics_door(municipality: dict, days: int = TOPICS_WINDOW_DAYS) -> dict:
    """``{"priorities", "topics", "since", "since_text"}`` for
    ``partials/briefing/door_topics.html``.

    ``priorities`` is the city's policy badges (``query.list_city_policy_badges``)
    with ``count`` from ``query.badge_volume_recent`` over the window and
    ``example`` (the newest counted item) when the count is positive, else
    ``latest`` (the newest item ever under the same gates); a priority with
    no qualifying item ever is left out, since its landing page would be
    empty. ``topics`` is the five topics with the most items in non-hidden
    meetings dated in the window, ``routine`` and NULL excluded, each with
    its newest item as ``example``. Both lists are empty for a city with no
    items, and the section renders only when one is not.
    """
    from docket.enrichment.topics import get_topic_display_name
    from docket.services import query

    mid = municipality["id"]
    since = date.today() - timedelta(days=days)
    priorities = []
    for badge in query.list_city_policy_badges(mid):
        count = query.badge_volume_recent(mid, badge["slug"], days=days)
        threshold = query.resolve_significance_threshold(mid, badge["slug"])
        params: list = [mid, badge["slug"]]
        significance = ""
        if threshold is not None:
            significance = "AND ai.significance_score >= %s"
            params.append(threshold)
        with db_cursor() as cur:
            cur.execute(_PRIORITY_LATEST_SQL.format(significance=significance), params)
            row = cur.fetchone()
        newest = _example(dict(row)) if row else None
        if newest is None:
            continue
        priorities.append({
            "slug": badge["slug"],
            "name": badge["name"],
            "count": count,
            "since": since,
            "example": newest if count > 0 else None,
            "latest": None if count > 0 else newest,
        })

    topics = []
    with db_cursor() as cur:
        cur.execute(_BUSIEST_TOPICS_SQL, (mid, since, TOPICS_LINES, mid, since))
        rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        topics.append({
            "slug": r["topic"],
            "name": get_topic_display_name(r["topic"]) or r["topic"],
            "count": int(r["count"]),
            "since": since,
            "example": _example(r),
        })

    return {
        "priorities": priorities,
        "topics": topics,
        "since": since,
        "since_text": _short_date(since),
    }


# ---------------------------------------------------------------------------
# The signals list and the page's provenance (M5)
# ---------------------------------------------------------------------------

SIGNALS_WINDOW_DAYS = 30
PROVENANCE_TTL_SECONDS = 300

# Per-city cache for ``city_provenance``: {municipality_id: (monotonic, dict)}.
# Cleared by ``tests.support.briefing_seed.clear_caches`` beside the route's
# ``_overview_cache``, so a render before seeding cannot leave a zero count
# for the tests after it.
_provenance_cache: dict[int, tuple[float, dict]] = {}


def signals(municipality_id: int, days: int = SIGNALS_WINDOW_DAYS) -> list[dict]:
    """``[{"slug", "label", "count"}]`` for ``partials/briefing/signals.html``:
    the process badges of ``SIGNAL_LABELS``, in that order, whose count over
    the last ``days`` days (``query.badge_volume_recent``, the same gates as
    the category landing pages) is above zero. A zero is left out, so the
    section renders only when something was signalled."""
    from docket.services import query

    out = []
    for slug, label in SIGNAL_LABELS.items():
        count = query.badge_volume_recent(municipality_id, slug, days=days)
        if count > 0:
            out.append({"slug": slug, "label": label, "count": int(count)})
    return out


_NEWEST_SOURCE_URL_SQL = """
    SELECT source_url FROM meetings
    WHERE municipality_id = %s AND source_url IS NOT NULL AND is_hidden = FALSE
    ORDER BY meeting_date DESC, id DESC LIMIT 1
"""


def _source_host(url: str | None) -> str | None:
    from urllib.parse import urlparse

    if not url:
        return None
    try:
        return urlparse(url).hostname or None
    except ValueError:
        return None


def city_provenance(municipality_id: int) -> dict:
    """``{"last_ingest_at", "meeting_count", "source_host", "source_url"}``:
    the one owner of the facts the freshness chip, the source panel, and the
    footer state (``query.most_recent_ingest_at``, ``query.count_meetings_lifetime``,
    and the hostname of the newest non-hidden meeting's ``source_url``),
    cached per city for ``PROVENANCE_TTL_SECONDS``."""
    import time

    from docket.services import query

    now = time.monotonic()
    cached = _provenance_cache.get(municipality_id)
    if cached and now - cached[0] < PROVENANCE_TTL_SECONDS:
        return cached[1]
    with db_cursor() as cur:
        cur.execute(_NEWEST_SOURCE_URL_SQL, (municipality_id,))
        row = cur.fetchone()
    source_url = row["source_url"] if row else None
    result = {
        "last_ingest_at": query.most_recent_ingest_at(municipality_id),
        "meeting_count": query.count_meetings_lifetime(municipality_id),
        "source_host": _source_host(source_url),
        "source_url": source_url,
    }
    _provenance_cache[municipality_id] = (now, result)
    return result
