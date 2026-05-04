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

            # Build council_surnames for the structured-fact tier.
            # council_members.name is a full name; take the last word as the surname.
            cur.execute(
                """SELECT cm.name FROM council_members cm
                   JOIN meetings m ON m.municipality_id = cm.municipality_id
                   WHERE m.id = %s
                     AND cm.active = TRUE
                     AND (cm.term_start IS NULL OR cm.term_start <= m.meeting_date)
                     AND (cm.term_end IS NULL OR cm.term_end >= m.meeting_date)""",
                (meeting_id,),
            )
            council_surnames = {
                r["name"].split()[-1] for r in cur.fetchall() if r["name"] and r["name"].split()
            }

            for vote in votes:
                if _classify_vote(vote) != "substantive":
                    continue
                result = (
                    _try_resolution_match(vote, items)
                    or _try_item_number_match(vote, items)
                    or _try_structured_fact_match(vote, items, council_surnames=council_surnames)
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

                # Hoisted: vote_text is constant per vote, so its significant words
                # are computed once instead of once per consent agenda item.
                text_words = _significant_words(vote_text)

                # Named callout pass
                named_ids: set[int] = set()
                for item in consent_items:
                    title = item["title"] or ""
                    item_num = item["item_number"] or ""

                    if item_num:
                        item_num_pattern = rf"\b(?:item|ITEM)\s+(?:no\.?\s*)?{re.escape(item_num)}\b"
                        if re.search(item_num_pattern, vote_text, re.IGNORECASE):
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
                    overlap_words = title_words & text_words
                    if len(overlap_words) >= threshold:
                        named_ids.add(item["id"])
                        # Deterministic snippet anchor: alphabetically first overlapping word
                        # so excerpt_context is stable across runs (sets are unordered).
                        snippet_word = min(overlap_words) if overlap_words else None
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
    """Match by item number patterns found in vote raw_text."""
    text = vote.get("raw_text") or vote.get("match_context") or ""
    if not text:
        return None

    m = re.search(r'(?:Item|ITEM)\s+(?:No\.?\s*)?(\d+)', text)
    if not m:
        m = re.search(r'#(\d+)', text)
    if not m:
        return None

    target_num = m.group(1)
    for item in items:
        if item["item_number"] == target_num:
            return (item["id"], 0.7, "item_number")

    return None


def _try_structured_fact_match(
    vote, items, *, council_surnames: set[str]
) -> tuple[int, float, str] | None:
    """Match by proper-noun + optional dollar overlap.

    High-precision tier requiring at least one proper-noun anchor.
    Returns (item_id, confidence, method) or None.
    """
    from docket.analysis.structured_facts import (
        extract_dollar_amounts,
        extract_proper_nouns,
    )

    text = vote.get("raw_text") or vote.get("match_context") or ""
    if not text:
        return None

    vote_proper_nouns = extract_proper_nouns(text, council_surnames=council_surnames)
    if not vote_proper_nouns:
        return None
    vote_dollars = extract_dollar_amounts(text)

    best_item_id = None
    best_proper_noun_count = 0
    best_has_dollar = False

    for item in items:
        haystack = (item["title"] or "") + " " + (item.get("description") or "")
        item_proper_nouns = extract_proper_nouns(haystack, council_surnames=council_surnames)
        item_dollars = extract_dollar_amounts(haystack)

        proper_noun_overlap = vote_proper_nouns & item_proper_nouns
        if not proper_noun_overlap:
            continue

        has_dollar = bool(vote_dollars & item_dollars)

        # Prefer more proper-noun overlap; tie-breaker is dollar match.
        if (
            len(proper_noun_overlap) > best_proper_noun_count
            or (len(proper_noun_overlap) == best_proper_noun_count and has_dollar and not best_has_dollar)
        ):
            best_item_id = item["id"]
            best_proper_noun_count = len(proper_noun_overlap)
            best_has_dollar = has_dollar
        elif len(proper_noun_overlap) == best_proper_noun_count and has_dollar == best_has_dollar:
            # Genuine tie — defer.
            return None

    if best_item_id is None:
        return None

    conf = 0.9 if best_has_dollar else 0.8
    return (best_item_id, conf, "structured_fact")


def _try_keyword_match(vote, items) -> tuple[int, float, str] | None:
    """Match by keyword overlap between vote raw_text and agenda item title.

    Rank-aware: requires the best item to beat the second-best by margin,
    else defers (Task 8 implements this; for Tier 0 alone, today's behavior
    is preserved).
    """
    text = vote.get("raw_text") or vote.get("match_context") or ""
    if not text:
        return None

    text_words = _significant_words(text)
    if len(text_words) < 3:
        return None

    best_item_id = None
    best_overlap = 0.0

    for item in items:
        title = item["title"] or ""
        title_words = _significant_words(title)
        if not title_words:
            continue
        overlap = len(text_words & title_words) / len(title_words)
        if overlap > best_overlap:
            best_overlap = overlap
            best_item_id = item["id"]

    if best_overlap >= 0.3 and best_item_id is not None:
        return (best_item_id, round(min(0.5 + best_overlap * 0.3, 0.8), 2), "text_similarity")

    return None


_STOP_WORDS = frozenset(
    "a an the of to in for on and or by at is was be are with that this from"
    " it its no not but as has had have been do does did will shall may can"
    " upon said being hereby"
    # v2: procedural noise from the wider raw_text window
    " councilmember councilmembers motion seconded ordinance resolution mayor"
    " ayes nays council presiding officer chairperson whereupon thereupon"
    " adopted approved granted item agenda".split()
)


def _significant_words(text: str) -> set[str]:
    """Extract significant lowercase words from text (4+ chars, not stop words)."""
    words = set(re.findall(r'[a-z]{4,}', text.lower()))
    return words - _STOP_WORDS


_ENUM_RESOLUTION_RE = re.compile(
    r"(?:RESOLUTION|ORDINANCE)\s+(?:NO\.\s*)?(?P<num>\d[\d-]*)\s+(?P<desc>[^\n\r]{0,200})",
    re.IGNORECASE,
)


def _parse_enumerated_consent_list(minutes_text: str) -> list[tuple[str, str]]:
    """Extract (resolution_number, description) tuples from the consent enumeration.

    Looks for "RESOLUTION 1854-25 A Resolution authorizing..." lines that typically
    appear in Birmingham minutes before the consent-vote roll call.
    """
    return [(m.group("num"), m.group("desc").strip()) for m in _ENUM_RESOLUTION_RE.finditer(minutes_text)]


def _resolve_enumerated_to_agenda_items(
    cur, meeting_id: int, enumerated: list[tuple[str, str]]
) -> set[int]:
    """For each enumerated entry, return matching agenda_item ids (is_consent=TRUE).

    Match by resolution number occurrence in the title/description first;
    otherwise by significant-word overlap with the description (>=3 words).
    """
    cur.execute(
        "SELECT id, item_number, title, COALESCE(description, '') AS description "
        "FROM agenda_items WHERE meeting_id = %s AND is_consent = TRUE",
        (meeting_id,),
    )
    items = cur.fetchall()
    resolved: set[int] = set()
    for res_num, desc in enumerated:
        # Resolution-number match
        for item in items:
            haystack = (item["title"] or "") + " " + item["description"]
            if re.search(rf"\b{re.escape(res_num)}\b", haystack):
                resolved.add(item["id"])
                break
        else:
            # Keyword fallback
            desc_words = _significant_words(desc)
            if len(desc_words) < 3:
                continue
            best_id, best_overlap = None, 0
            for item in items:
                title_words = _significant_words(item["title"] or "")
                overlap = len(desc_words & title_words)
                if overlap >= 3 and overlap > best_overlap:
                    best_overlap = overlap
                    best_id = item["id"]
            if best_id is not None:
                resolved.add(best_id)
    return resolved


def _fetch_vote_for_classify(cur, vote_id: int) -> dict:
    cur.execute("SELECT raw_text, match_context FROM votes WHERE id = %s", (vote_id,))
    return cur.fetchone() or {}


def strict_reparse_meeting(meeting_id: int, *, minutes_text: str | None = None) -> dict:
    """Promote provisional consent links to official; deactivate pulled-from-consent links.

    minutes_text: pass-through for tests. In production, callers fetch the PDF and pass the text.
    Respects is_manual=TRUE on every UPDATE.
    """
    if minutes_text is None:
        from docket.analysis.minutes_parser import (
            download_minutes_pdf, extract_text_from_pdf,
        )
        with db_cursor() as cur:
            cur.execute("SELECT minutes_url FROM meetings WHERE id = %s", (meeting_id,))
            row = cur.fetchone()
        if not row or not row["minutes_url"]:
            logger.warning("strict_reparse: no minutes_url for meeting %s", meeting_id)
            return {"promoted": 0, "deactivated": 0}
        pdf = download_minutes_pdf(row["minutes_url"])
        if not pdf:
            return {"promoted": 0, "deactivated": 0}
        minutes_text = extract_text_from_pdf(pdf)

    enumerated = _parse_enumerated_consent_list(minutes_text)
    if not enumerated:
        logger.warning("strict_reparse: no enumerated list found for meeting %s", meeting_id)
        return {"promoted": 0, "deactivated": 0}

    promoted = 0
    deactivated = 0
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            target_item_ids = _resolve_enumerated_to_agenda_items(cur, meeting_id, enumerated)

            # Critical safety check: if the enumerated list resolved to NO agenda items
            # (e.g., resolution numbers don't appear in any agenda title and the
            # description-keyword fallback couldn't find ≥3-word overlaps), short-circuit.
            # Otherwise the deactivate UPDATE's NOT (... = ANY(empty_array)) would evaluate
            # TRUE for every active consent link, silently deactivating all of them.
            if not target_item_ids:
                logger.warning(
                    "strict_reparse: parsed %d enumerated entries but none resolved to "
                    "agenda_items for meeting %s — aborting reconciliation to avoid mass deactivation",
                    len(enumerated), meeting_id,
                )
                return {"promoted": 0, "deactivated": 0}

            # Promote: items in enumerated set that are linked -> flip provisional
            cur.execute(
                """UPDATE vote_agenda_items
                   SET provisional = FALSE,
                       match_confidence = 1.0,
                       match_method = 'consent_enumerated',
                       association_type = 'consent_named',
                       updated_at = NOW()
                   FROM votes v
                   WHERE v.id = vote_agenda_items.vote_id
                     AND v.meeting_id = %s
                     AND vote_agenda_items.is_manual = FALSE
                     AND vote_agenda_items.agenda_item_id = ANY(%s)
                     AND vote_agenda_items.association_type IN ('consent_named', 'consent_implicit')""",
                (meeting_id, list(target_item_ids)),
            )
            promoted = cur.rowcount

            # Deactivate: linked items NOT in enumerated set (pulled from consent)
            cur.execute(
                """UPDATE vote_agenda_items
                   SET is_active = FALSE, updated_at = NOW()
                   FROM votes v
                   WHERE v.id = vote_agenda_items.vote_id
                     AND v.meeting_id = %s
                     AND vote_agenda_items.is_manual = FALSE
                     AND vote_agenda_items.is_active = TRUE
                     AND vote_agenda_items.association_type IN ('consent_named', 'consent_implicit')
                     AND NOT (vote_agenda_items.agenda_item_id = ANY(%s))""",
                (meeting_id, list(target_item_ids)),
            )
            deactivated = cur.rowcount

            # Insert any enumerated items that weren't previously linked
            for item_id in target_item_ids:
                cur.execute(
                    """SELECT v.id AS vote_id FROM votes v
                       LEFT JOIN vote_agenda_items vai
                         ON vai.vote_id = v.id AND vai.agenda_item_id = %s
                       WHERE v.meeting_id = %s AND v.source = 'minutes_text'
                         AND vai.id IS NULL""",
                    (item_id, meeting_id),
                )
                for r in cur.fetchall():
                    if _classify_vote(_fetch_vote_for_classify(cur, r["vote_id"])) == "consent_block":
                        _upsert_link(
                            cur, vote_id=r["vote_id"], agenda_item_id=item_id,
                            association_type="consent_named",
                            match_method="consent_enumerated",
                            match_confidence=1.0,
                            excerpt_context=None,
                            provisional=False,
                        )

            # Substantive safety pass — defensive no-op for healthy data.
            # Substantive matches are inserted with provisional=FALSE in the first place,
            # so this UPDATE typically affects 0 rows. It exists as a guardrail in case
            # a future code path ever inserts an explicit link as provisional; this
            # ensures the meeting reaches a consistent post-adoption state.
            cur.execute(
                """UPDATE vote_agenda_items
                   SET provisional = FALSE, updated_at = NOW()
                   FROM votes v
                   WHERE v.id = vote_agenda_items.vote_id
                     AND v.meeting_id = %s
                     AND vote_agenda_items.is_manual = FALSE
                     AND vote_agenda_items.association_type = 'explicit'
                     AND vote_agenda_items.provisional = TRUE""",
                (meeting_id,),
            )
        conn.commit()

    return {"promoted": promoted, "deactivated": deactivated}


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
            cur.execute(
                "SELECT minutes_adopted_at FROM meetings WHERE id = %s",
                (meeting_id,),
            )
            row = cur.fetchone()
        conn.commit()

    reparse_result = {"promoted": 0, "deactivated": 0}
    if row and row[0] is not None:
        # Adoption already recorded — promote provisional links immediately
        try:
            reparse_result = strict_reparse_meeting(meeting_id)
        except Exception as e:
            logger.warning("strict_reparse failed for meeting %s: %s", meeting_id, e)

    return {
        "timestamp_matched": ts_matched,
        "substantive_matched": sub_matched,
        "consent_matched": consent_matched,
        "promoted": reparse_result["promoted"],
        "deactivated": reparse_result["deactivated"],
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
