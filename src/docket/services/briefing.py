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
from datetime import date, datetime, timedelta, timezone

from docket.analysis.structured_facts import extract_dollar_amounts
from docket.db import db_cursor

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
        SELECT c.id AS vote_id, c.meeting_id, c.meeting_date, c.source, c.result,
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
