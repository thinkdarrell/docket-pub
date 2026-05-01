"""Match votes to agenda items using timestamps and text heuristics.

Timestamp matching (video OCR votes):
    Ported from al-municipal-meetings vote_matcher.py (by Brennan Holzer).
    Uses bisect_right to find the nearest preceding agenda item by video
    timestamp, with gap-based confidence scoring.

Text matching (minutes text votes):
    Three-tier heuristic matching using resolution numbers, item number
    patterns in context, and keyword overlap.
"""

from __future__ import annotations

import logging
import re
from bisect import bisect_right

import psycopg2.extras

from docket.db import db, db_cursor

logger = logging.getLogger(__name__)


def compute_confidence(gap_seconds: float, *, needs_review: bool = False) -> float:
    """Confidence score based on time gap between vote and preceding agenda item.

    Ported from al-municipal-meetings/src/muni/analysis/vote_matcher.py.
    """
    if gap_seconds < 0:
        base = 0.0
    elif gap_seconds < 120:
        base = 1.0
    elif gap_seconds < 600:
        base = 0.8
    elif gap_seconds < 1800:
        base = 0.5
    else:
        base = 0.3
    return base * 0.5 if needs_review else base


def _upsert_link(
    cur,
    *,
    vote_id: int,
    agenda_item_id: int,
    association_type: str,
    match_method: str | None,
    match_confidence: float,
    excerpt_context: str | None,
    provisional: bool,
) -> None:
    """Insert or update a vote_agenda_items row.

    Respects the is_manual shield: app-level pre-check + DB-level WHERE
    on the UPDATE branch. Manual edits never get overwritten.
    """
    cur.execute(
        "SELECT is_manual FROM vote_agenda_items WHERE vote_id = %s AND agenda_item_id = %s",
        (vote_id, agenda_item_id),
    )
    existing = cur.fetchone()
    if existing and existing["is_manual"]:
        return  # human-locked, leave alone

    cur.execute(
        """INSERT INTO vote_agenda_items
            (vote_id, agenda_item_id, association_type, match_method,
             match_confidence, excerpt_context, provisional)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (vote_id, agenda_item_id) DO UPDATE
             SET association_type = EXCLUDED.association_type,
                 match_method = EXCLUDED.match_method,
                 match_confidence = EXCLUDED.match_confidence,
                 excerpt_context = EXCLUDED.excerpt_context,
                 updated_at = NOW()
             WHERE vote_agenda_items.is_manual = FALSE""",
        (
            vote_id, agenda_item_id, association_type, match_method,
            match_confidence, excerpt_context, provisional,
        ),
    )


def match_votes_by_timestamp(meeting_id: int) -> int:
    """Match video OCR votes to agenda items by timestamp proximity.

    Returns number of votes matched.
    """
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Load agenda items with timestamps, sorted
            cur.execute(
                """SELECT id, video_timestamp_seconds
                   FROM agenda_items
                   WHERE meeting_id = %s AND video_timestamp_seconds IS NOT NULL
                   ORDER BY video_timestamp_seconds""",
                (meeting_id,),
            )
            items = cur.fetchall()
            if not items:
                return 0

            item_timestamps = [r["video_timestamp_seconds"] for r in items]
            item_ids = [r["id"] for r in items]

            # Load unmatched video OCR votes with timestamps
            cur.execute(
                """SELECT id, video_timestamp, needs_review
                   FROM votes
                   WHERE meeting_id = %s AND source = 'video_ocr'
                     AND video_timestamp IS NOT NULL
                     AND agenda_item_id IS NULL""",
                (meeting_id,),
            )
            votes = cur.fetchall()
            if not votes:
                return 0

            matched = 0
            for vote in votes:
                vt = vote["video_timestamp"]
                idx = bisect_right(item_timestamps, vt) - 1
                if idx < 0:
                    continue

                gap = vt - item_timestamps[idx]
                conf = compute_confidence(gap, needs_review=vote["needs_review"])
                if conf <= 0:
                    continue

                cur.execute(
                    """UPDATE votes
                       SET agenda_item_id = %s,
                           match_confidence = %s,
                           match_method = 'timestamp'
                       WHERE id = %s""",
                    (item_ids[idx], conf, vote["id"]),
                )
                matched += 1

    return matched


def match_votes_by_text(meeting_id: int) -> int:
    """Match minutes-text votes to agenda items using text heuristics.

    Three-tier strategy:
    1. Resolution/ordinance number match (confidence 0.9)
    2. Item number from context (confidence 0.7)
    3. Keyword overlap (confidence 0.5)

    Returns number of votes matched.
    """
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Load agenda items for this meeting
            cur.execute(
                """SELECT id, item_number, title
                   FROM agenda_items WHERE meeting_id = %s""",
                (meeting_id,),
            )
            items = cur.fetchall()
            if not items:
                return 0

            # Load unmatched minutes votes
            cur.execute(
                """SELECT id, resolution_number, match_context
                   FROM votes
                   WHERE meeting_id = %s AND agenda_item_id IS NULL
                     AND source = 'minutes_text'""",
                (meeting_id,),
            )
            votes = cur.fetchall()
            if not votes:
                return 0

            matched = 0
            for vote in votes:
                result = _try_resolution_match(vote, items)
                if not result:
                    result = _try_item_number_match(vote, items)
                if not result:
                    result = _try_keyword_match(vote, items)
                if result:
                    item_id, conf, method = result
                    cur.execute(
                        """UPDATE votes
                           SET agenda_item_id = %s,
                               match_confidence = %s,
                               match_method = %s
                           WHERE id = %s""",
                        (item_id, conf, method, vote["id"]),
                    )
                    matched += 1

    return matched


def _try_resolution_match(vote, items) -> tuple[int, float, str] | None:
    """Match by resolution/ordinance number in agenda item title."""
    res_num = vote["resolution_number"]
    if not res_num:
        return None

    for item in items:
        title = item["title"] or ""
        # Look for the resolution number in the title
        if re.search(rf'\b{re.escape(res_num)}\b', title):
            return (item["id"], 0.9, "resolution_number")

    return None


def _try_item_number_match(vote, items) -> tuple[int, float, str] | None:
    """Match by item number patterns found in vote context."""
    context = vote["match_context"]
    if not context:
        return None

    # Look for "Item N", "ITEM N", "#N" patterns
    m = re.search(r'(?:Item|ITEM)\s+(?:No\.?\s*)?(\d+)', context)
    if not m:
        m = re.search(r'#(\d+)', context)
    if not m:
        return None

    target_num = m.group(1)
    for item in items:
        if item["item_number"] == target_num:
            return (item["id"], 0.7, "item_number")

    return None


def _try_keyword_match(vote, items) -> tuple[int, float, str] | None:
    """Match by keyword overlap between vote context and agenda item title."""
    context = vote["match_context"]
    if not context:
        return None

    context_words = _significant_words(context)
    if len(context_words) < 3:
        return None

    best_item_id = None
    best_overlap = 0.0

    for item in items:
        title = item["title"] or ""
        title_words = _significant_words(title)
        if not title_words:
            continue

        overlap = len(context_words & title_words) / max(len(context_words), len(title_words))
        if overlap > best_overlap:
            best_overlap = overlap
            best_item_id = item["id"]

    if best_overlap >= 0.3 and best_item_id is not None:
        return (best_item_id, round(min(0.5 + best_overlap * 0.3, 0.8), 2), "text_similarity")

    return None


_STOP_WORDS = frozenset(
    "a an the of to in for on and or by at is was be are with that this from"
    " it its no not but as has had have been do does did will shall may can"
    " upon said being hereby".split()
)


def _significant_words(text: str) -> set[str]:
    """Extract significant lowercase words from text (4+ chars, not stop words)."""
    words = set(re.findall(r'[a-z]{4,}', text.lower()))
    return words - _STOP_WORDS


def match_votes_for_meeting(meeting_id: int) -> dict:
    """Run all matching strategies for a meeting."""
    ts_matched = match_votes_by_timestamp(meeting_id)
    text_matched = match_votes_by_text(meeting_id)

    # Mark meeting as matched
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "UPDATE processing_status SET votes_matched = TRUE WHERE meeting_id = %s",
                (meeting_id,),
            )

    return {"timestamp_matched": ts_matched, "text_matched": text_matched}


def match_all_unmatched() -> dict:
    """Run matching on all meetings that have unmatched votes."""
    with db_cursor() as cur:
        cur.execute(
            """SELECT DISTINCT v.meeting_id
               FROM votes v
               WHERE v.agenda_item_id IS NULL
               ORDER BY v.meeting_id"""
        )
        meeting_ids = [r["meeting_id"] for r in cur.fetchall()]

    total_ts = 0
    total_text = 0
    for mid in meeting_ids:
        result = match_votes_for_meeting(mid)
        total_ts += result["timestamp_matched"]
        total_text += result["text_matched"]

    logger.info(
        "Matched %d by timestamp, %d by text across %d meetings",
        total_ts, total_text, len(meeting_ids),
    )
    return {
        "meetings": len(meeting_ids),
        "timestamp_matched": total_ts,
        "text_matched": total_text,
    }
