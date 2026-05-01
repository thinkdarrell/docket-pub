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
import math
import re
from bisect import bisect_right

import psycopg2.extras

from docket.analysis.minutes_parser import CONSENT_BLOCK_PHRASES
from docket.db import db, db_cursor

logger = logging.getLogger(__name__)


NAMED_CALLOUT_FLOOR = 2
NAMED_CALLOUT_CAP = 3
NAMED_CALLOUT_RATIO = 0.6


def _named_callout_threshold(n_significant_words: int) -> int | None:
    """Required word-overlap count for the consent named-callout heuristic.

    Returns None if the title is too short (1 significant word) — skip keyword pass.
    Otherwise: max(NAMED_CALLOUT_FLOOR, min(NAMED_CALLOUT_CAP, ceil(0.6 * N))).
    """
    if n_significant_words < 2:
        return None
    return max(
        NAMED_CALLOUT_FLOOR,
        min(NAMED_CALLOUT_CAP, math.ceil(NAMED_CALLOUT_RATIO * n_significant_words)),
    )


def _extract_snippet(haystack: str, needle: str, window: int = 100) -> str | None:
    """Return ~200 chars of haystack centered on the first occurrence of needle (case-insensitive)."""
    if not needle:
        return None
    idx = haystack.lower().find(needle.lower())
    if idx == -1:
        return None
    start = max(0, idx - window)
    end = min(len(haystack), idx + len(needle) + window)
    return haystack[start:end]


def _classify_vote(vote_row) -> str:
    """Return 'substantive' or 'consent_block' for a vote.

    Reads raw_text first (preferred), falls back to match_context for
    legacy votes ingested before the parser was widened. Accepts dict-like
    or psycopg2 RealDictRow.
    """
    haystack = (vote_row.get("raw_text") or "") + " " + (vote_row.get("match_context") or "")
    haystack = haystack.lower()
    if any(phrase in haystack for phrase in CONSENT_BLOCK_PHRASES):
        return "consent_block"
    return "substantive"


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

    Inserts to vote_agenda_items via _upsert_link.
    Returns number of votes matched.
    """
    matched = 0
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT id, video_timestamp_seconds FROM agenda_items
                   WHERE meeting_id = %s AND video_timestamp_seconds IS NOT NULL
                   ORDER BY video_timestamp_seconds""",
                (meeting_id,),
            )
            items = cur.fetchall()
            if not items:
                return 0
            item_timestamps = [r["video_timestamp_seconds"] for r in items]
            item_ids = [r["id"] for r in items]

            cur.execute(
                """SELECT v.id, v.video_timestamp, v.needs_review
                   FROM votes v
                   LEFT JOIN vote_agenda_items vai ON vai.vote_id = v.id AND vai.is_active
                   WHERE v.meeting_id = %s AND v.source = 'video_ocr'
                     AND v.video_timestamp IS NOT NULL
                     AND vai.id IS NULL""",
                (meeting_id,),
            )
            votes = cur.fetchall()
            for vote in votes:
                vt = vote["video_timestamp"]
                idx = bisect_right(item_timestamps, vt) - 1
                if idx < 0:
                    continue
                gap = vt - item_timestamps[idx]
                conf = compute_confidence(gap, needs_review=vote["needs_review"])
                if conf <= 0:
                    continue
                _upsert_link(
                    cur,
                    vote_id=vote["id"],
                    agenda_item_id=item_ids[idx],
                    association_type="explicit",
                    match_method="timestamp",
                    match_confidence=conf,
                    excerpt_context=None,
                    provisional=False,
                )
                matched += 1
        conn.commit()
    return matched


def _match_substantive(meeting_id: int) -> int:
    """Match substantive (1:1) minutes votes via 3-tier heuristics."""
    matched = 0
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, item_number, title, COALESCE(description, '') AS description "
                "FROM agenda_items WHERE meeting_id = %s",
                (meeting_id,),
            )
            items = cur.fetchall()
            if not items:
                return 0

            cur.execute(
                """SELECT v.id, v.resolution_number, v.match_context, v.raw_text
                   FROM votes v
                   LEFT JOIN vote_agenda_items vai ON vai.vote_id = v.id AND vai.is_active
                   WHERE v.meeting_id = %s AND v.source = 'minutes_text'
                     AND vai.id IS NULL""",
                (meeting_id,),
            )
            votes = cur.fetchall()
            for vote in votes:
                if _classify_vote(vote) != "substantive":
                    continue
                result = (
                    _try_resolution_match(vote, items)
                    or _try_item_number_match(vote, items)
                    or _try_keyword_match(vote, items)
                )
                if result:
                    item_id, conf, method = result
                    _upsert_link(
                        cur,
                        vote_id=vote["id"],
                        agenda_item_id=item_id,
                        association_type="explicit",
                        match_method=method,
                        match_confidence=conf,
                        excerpt_context=(vote.get("match_context") or "")[:300] or None,
                        provisional=False,
                    )
                    matched += 1
        conn.commit()
    return matched


def _match_consent_block(meeting_id: int) -> int:
    """Match consent-block (1:N) votes by named callout + default fill.

    For each consent-block vote in the meeting, link to all is_consent=TRUE
    agenda items: items named in the vote's raw_text get consent_named/1.0;
    remaining is_consent items get consent_implicit/0.8. All start provisional.
    """
    matched = 0
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, item_number, title FROM agenda_items "
                "WHERE meeting_id = %s AND is_consent = TRUE",
                (meeting_id,),
            )
            consent_items = cur.fetchall()
            if not consent_items:
                return 0

            cur.execute(
                """SELECT v.id, v.raw_text, v.match_context, v.resolution_number
                   FROM votes v
                   LEFT JOIN vote_agenda_items vai ON vai.vote_id = v.id AND vai.is_active
                   WHERE v.meeting_id = %s AND v.source = 'minutes_text'
                     AND vai.id IS NULL""",
                (meeting_id,),
            )
            votes = cur.fetchall()

            for vote in votes:
                if _classify_vote(vote) != "consent_block":
                    continue
                vote_text = ((vote.get("raw_text") or "") + " " + (vote.get("match_context") or "")).lower()
                if not vote_text.strip():
                    continue

                # Named callout pass
                named_ids: set[int] = set()
                for item in consent_items:
                    title = item["title"] or ""
                    item_num = item["item_number"] or ""

                    item_num_pattern = (
                        rf"\b(?:item|ITEM)\s+(?:no\.?\s*)?{re.escape(item_num)}\b"
                        if item_num else None
                    )
                    if item_num and item_num_pattern and re.search(item_num_pattern, vote_text, re.IGNORECASE):
                        named_ids.add(item["id"])
                        _upsert_link(
                            cur, vote_id=vote["id"], agenda_item_id=item["id"],
                            association_type="consent_named",
                            match_method="consent_block_named",
                            match_confidence=1.0,
                            excerpt_context=_extract_snippet(vote.get("raw_text") or "", item_num),
                            provisional=True,
                        )
                        matched += 1
                        continue

                    title_words = _significant_words(title)
                    threshold = _named_callout_threshold(len(title_words))
                    if threshold is None:
                        continue
                    text_words = _significant_words(vote_text)
                    overlap = len(title_words & text_words)
                    if overlap >= threshold:
                        named_ids.add(item["id"])
                        snippet_word = next(iter(title_words & text_words), None)
                        _upsert_link(
                            cur, vote_id=vote["id"], agenda_item_id=item["id"],
                            association_type="consent_named",
                            match_method="consent_block_named",
                            match_confidence=1.0,
                            excerpt_context=_extract_snippet(vote.get("raw_text") or "", snippet_word or ""),
                            provisional=True,
                        )
                        matched += 1

                # Default fill pass
                for item in consent_items:
                    if item["id"] in named_ids:
                        continue
                    _upsert_link(
                        cur, vote_id=vote["id"], agenda_item_id=item["id"],
                        association_type="consent_implicit",
                        match_method="consent_block_default",
                        match_confidence=0.8,
                        excerpt_context=None,
                        provisional=True,
                    )
                    matched += 1
        conn.commit()
    return matched


def _try_resolution_match(vote, items) -> tuple[int, float, str] | None:
    """Match by resolution/ordinance number in agenda item title or description."""
    res_num = vote["resolution_number"]
    if not res_num:
        return None
    for item in items:
        haystack = (item["title"] or "") + " " + (item.get("description") or "")
        if re.search(rf"\b{re.escape(res_num)}\b", haystack):
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
    sub_matched = _match_substantive(meeting_id)
    consent_matched = _match_consent_block(meeting_id)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE processing_status SET votes_matched = TRUE WHERE meeting_id = %s",
                (meeting_id,),
            )
        conn.commit()
    return {
        "timestamp_matched": ts_matched,
        "substantive_matched": sub_matched,
        "consent_matched": consent_matched,
    }


def match_all_unmatched() -> dict:
    """Run matching on all meetings that have unmatched votes."""
    with db_cursor() as cur:
        cur.execute(
            """SELECT DISTINCT v.meeting_id
               FROM votes v
               LEFT JOIN vote_agenda_items vai ON vai.vote_id = v.id AND vai.is_active
               WHERE vai.id IS NULL
               ORDER BY v.meeting_id"""
        )
        meeting_ids = [r["meeting_id"] for r in cur.fetchall()]

    total_ts = 0
    total_sub = 0
    total_consent = 0
    for mid in meeting_ids:
        result = match_votes_for_meeting(mid)
        total_ts += result["timestamp_matched"]
        total_sub += result["substantive_matched"]
        total_consent += result["consent_matched"]

    logger.info(
        "Matched %d by timestamp, %d substantive, %d consent across %d meetings",
        total_ts, total_sub, total_consent, len(meeting_ids),
    )
    return {
        "meetings": len(meeting_ids),
        "timestamp_matched": total_ts,
        "substantive_matched": total_sub,
        "consent_matched": total_consent,
    }
