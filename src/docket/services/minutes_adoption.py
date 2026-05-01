"""Detect and resolve council adoption of prior-meeting minutes.

Approach: stateless sweep over each city's agenda items. Idempotent —
re-running doesn't change resolved adoptions but picks up newly-ingested
target meetings. Triggers strict re-parse on each flip.

This module exposes the pattern-detection layer (is_adoption_title,
extract_adoption_target). The sweep service wraps it.
"""

from __future__ import annotations

import logging
import re
from datetime import date

import psycopg2.extras
from dateutil import parser as dateparser

from docket.db import db

logger = logging.getLogger(__name__)


class AdoptionParseError(ValueError):
    """Raised when an adoption-pattern title cannot be resolved to a valid date."""


_ADOPTION_PATTERNS = [
    re.compile(r"approval of (?:the )?minutes from .*?(?P<date>\w+\s+\d{1,2},?\s+\d{4})", re.IGNORECASE),
    re.compile(r"adoption of (?:the )?minutes from .*?(?P<date>\w+\s+\d{1,2},?\s+\d{4})", re.IGNORECASE),
    re.compile(r"approval of (?:the )?(?P<date>\w+\s+\d{1,2},?\s+\d{4}) minutes", re.IGNORECASE),
    re.compile(r"minutes from the (?:\w+\s+)?meeting of (?P<date>\w+\s+\d{1,2},?\s+\d{4})", re.IGNORECASE),
]

_LOOKBACK_MONTHS = 24


def is_adoption_title(title: str) -> bool:
    """True if the title matches any adoption pattern."""
    if not title:
        return False
    return any(p.search(title) for p in _ADOPTION_PATTERNS)


def _extract_date_string(title: str) -> str | None:
    for p in _ADOPTION_PATTERNS:
        m = p.search(title)
        if m:
            return m.group("date")
    return None


def extract_adoption_target(title: str, *, adoption_meeting_date: date) -> date:
    """Parse the adoption target date from an agenda title.

    Validates: real date, not in future, within 24-month lookback window.
    Raises AdoptionParseError on any failure.
    """
    date_str = _extract_date_string(title)
    if date_str is None:
        raise AdoptionParseError(f"no date in title: {title!r}")

    try:
        parsed = dateparser.parse(date_str).date()
    except (ValueError, TypeError) as e:
        raise AdoptionParseError(f"invalid date {date_str!r}: {e}") from e

    if parsed > adoption_meeting_date:
        raise AdoptionParseError(
            f"date {parsed} is in the future relative to adoption meeting {adoption_meeting_date}"
        )

    months_back = (adoption_meeting_date.year - parsed.year) * 12 + (adoption_meeting_date.month - parsed.month)
    if months_back > _LOOKBACK_MONTHS:
        raise AdoptionParseError(
            f"date {parsed} is more than {_LOOKBACK_MONTHS} months before adoption meeting "
            f"{adoption_meeting_date} — outside window"
        )

    return parsed


def sweep_adoptions(municipality_id: int) -> list[int]:
    """Walk all adoption-pattern agenda items in this city and resolve them.

    For each passed-vote adoption agenda item with a parsed target date:
      - 0 candidate target meetings: log debug, leave for next sweep
      - 1 candidate: set minutes_adopted_at if currently NULL, return id
      - 2+ candidates: warn-log structured event, skip

    Returns: list of meeting ids whose minutes_adopted_at flipped from NULL → date.
    """
    flipped: list[int] = []
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Use EXISTS rather than JOIN votes so each agenda item appears once,
            # not once per passed vote in its meeting (which would replay the
            # same adoption resolution 20-30 times per meeting and flood the
            # warn-log with adoption_already_recorded events).
            cur.execute(
                """SELECT ai.id AS agenda_item_id, ai.title, m.id AS meeting_id,
                          m.meeting_date AS adoption_meeting_date
                   FROM agenda_items ai
                   JOIN meetings m ON m.id = ai.meeting_id
                   WHERE m.municipality_id = %s
                     AND EXISTS (
                       SELECT 1 FROM votes v
                       WHERE v.meeting_id = m.id AND v.result = 'passed'
                     )""",
                (municipality_id,),
            )
            candidates = cur.fetchall()

            for c in candidates:
                if not is_adoption_title(c["title"]):
                    continue
                try:
                    target_date = extract_adoption_target(
                        c["title"],
                        adoption_meeting_date=c["adoption_meeting_date"],
                    )
                except AdoptionParseError as e:
                    logger.debug(
                        "adoption_parse_skip municipality_id=%s agenda_item_id=%s reason=%s",
                        municipality_id, c["agenda_item_id"], e,
                    )
                    continue

                cur.execute(
                    """SELECT id FROM meetings
                       WHERE municipality_id = %s AND meeting_date = %s""",
                    (municipality_id, target_date),
                )
                rows = cur.fetchall()
                if len(rows) == 0:
                    logger.debug(
                        "adoption_target_missing municipality_id=%s agenda_item_id=%s target_date=%s",
                        municipality_id, c["agenda_item_id"], target_date,
                    )
                    continue
                if len(rows) > 1:
                    logger.warning(
                        "adoption_multi_match municipality_id=%s agenda_item_id=%s "
                        "parsed_date=%s candidate_meeting_ids=%s",
                        municipality_id, c["agenda_item_id"], target_date,
                        [r["id"] for r in rows],
                    )
                    continue

                target_id = rows[0]["id"]
                cur.execute(
                    "SELECT minutes_adopted_at FROM meetings WHERE id = %s",
                    (target_id,),
                )
                if cur.fetchone()["minutes_adopted_at"] is not None:
                    logger.warning(
                        "adoption_already_recorded target_meeting_id=%s adoption_meeting_id=%s",
                        target_id, c["meeting_id"],
                    )
                    continue

                cur.execute(
                    "UPDATE meetings SET minutes_adopted_at = %s WHERE id = %s",
                    (c["adoption_meeting_date"], target_id),
                )
                flipped.append(target_id)
        conn.commit()

    # Trigger strict re-parse on each newly-flipped meeting (outside the txn).
    # Each meeting may have provisional consent links to promote; failures are
    # logged but do not break the overall sweep.
    if flipped:
        from docket.analysis.vote_matcher import strict_reparse_meeting
        for mid in flipped:
            try:
                strict_reparse_meeting(mid)
            except Exception as e:
                logger.warning("strict_reparse failed for meeting %s after sweep: %s", mid, e)

    return flipped
