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
from typing import NamedTuple

import psycopg2.extras

from docket.db import db

logger = logging.getLogger(__name__)


class AdoptionParseError(ValueError):
    """Raised when an adoption-pattern title cannot be resolved to a valid date."""


class DateSpan(NamedTuple):
    """Inclusive window of meeting dates. A single named date has start == end."""

    start: date
    end: date

    @property
    def is_range(self) -> bool:
        return self.start != self.end


# "Approval of Minutes from ...", "Adoption of the Minutes ...", "Approval of the
# December 5, 2024 Minutes", and the clerk's occasional "APPROVAL MINUTES FROM ...".
# "MINUTES NOT READY: ..." deliberately does not match.
_ADOPTION_TITLE_PATTERNS = [
    re.compile(r"\b(?:approval|adoption)\s+(?:of\s+)?(?:the\s+)?(?:\S+\s+){0,4}?minutes\b", re.IGNORECASE),
    re.compile(r"\bminutes from the (?:\w+\s+)?meeting of\b", re.IGNORECASE),
]

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Birmingham approves minutes in batches, so the date expression is a list
# ("May 5, 12, 19 and 26, 2026"), a range ("February 3 – 24, 2026"), or a single
# date. A month only counts when a day number follows it; a 1-2 digit number only
# counts as a day while a month is in effect.
_DATE_TOKEN_RE = re.compile(
    r"\b(?P<month>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?"
    r"|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b\.?(?=\s*\d)"
    r"|\b(?P<year>(?:19|20)\d{2})\b"
    r"|\b(?P<day>\d{1,2})\b"
    r"|(?P<range>[-–—]|\b(?:through|thru|to)\b)",
    re.IGNORECASE,
)

_LOOKBACK_MONTHS = 24


def is_adoption_title(title: str) -> bool:
    """True if the title matches any adoption pattern."""
    if not title:
        return False
    return any(p.search(title) for p in _ADOPTION_TITLE_PATTERNS)


def _parse_date_spans(title: str) -> list[DateSpan]:
    """Tokenize the date expression in a title into spans, in order of appearance.

    Days inherit the next year that follows them ("June 2, 9 & 30, 2026"). Never
    guesses a missing month or year.
    """
    entries: list[list[int | None]] = []  # [month, day, year]
    range_pairs: list[tuple[int, int]] = []
    month: int | None = None
    range_from: int | None = None
    last_was_date_part = False

    for m in _DATE_TOKEN_RE.finditer(title):
        if m.group("month"):
            month = _MONTHS[m.group("month")[:3].lower()]
            last_was_date_part = False
        elif m.group("year"):
            year = int(m.group("year"))
            for e in entries:
                if e[2] is None:
                    e[2] = year
            # Numbers after the year aren't days until another month appears.
            month = None
            last_was_date_part = bool(entries)
        elif m.group("day"):
            if month is None:
                continue
            entries.append([month, int(m.group("day")), None])
            if range_from is not None:
                range_pairs.append((range_from, len(entries) - 1))
                range_from = None
            last_was_date_part = True
        else:  # range separator — only meaningful directly after a day or year
            range_from = len(entries) - 1 if last_was_date_part else None
            last_was_date_part = False

    if not entries or any(e[2] is None for e in entries):
        raise AdoptionParseError(f"no date in title: {title!r}")

    def to_date(e: list[int | None]) -> date:
        try:
            return date(e[2], e[0], e[1])
        except ValueError as err:
            raise AdoptionParseError(f"invalid date {e[0]}/{e[1]}/{e[2]}: {err}") from err

    dates = [to_date(e) for e in entries]
    range_end_for = dict(range_pairs)
    range_ends = set(range_end_for.values())
    spans: list[DateSpan] = []
    for i, d in enumerate(dates):
        if i in range_end_for:
            end = dates[range_end_for[i]]
            if end < d:
                raise AdoptionParseError(f"invalid date range {d} – {end}")
            spans.append(DateSpan(d, end))
        elif i not in range_ends:
            spans.append(DateSpan(d, d))
    return spans


def extract_adoption_targets(title: str, *, adoption_meeting_date: date) -> list[DateSpan]:
    """Parse every adoption target named in an agenda title.

    Validates each span: real dates, not in the future, within the 24-month
    lookback window. Raises AdoptionParseError on any failure (all-or-nothing).
    """
    spans = _parse_date_spans(title)
    for span in spans:
        if span.end > adoption_meeting_date:
            raise AdoptionParseError(
                f"date {span.end} is in the future relative to adoption meeting {adoption_meeting_date}"
            )
        months_back = (
            (adoption_meeting_date.year - span.start.year) * 12
            + (adoption_meeting_date.month - span.start.month)
        )
        if months_back > _LOOKBACK_MONTHS:
            raise AdoptionParseError(
                f"date {span.start} is more than {_LOOKBACK_MONTHS} months before adoption meeting "
                f"{adoption_meeting_date} — outside window"
            )
    return spans


def extract_adoption_target(title: str, *, adoption_meeting_date: date) -> date:
    """Parse the first adoption target date from an agenda title.

    Raises AdoptionParseError on any failure.
    """
    return extract_adoption_targets(title, adoption_meeting_date=adoption_meeting_date)[0].start


def sweep_adoptions(municipality_id: int) -> list[int]:
    """Walk all adoption-pattern agenda items in this city and resolve them.

    For each passed-vote adoption agenda item, every parsed target is resolved.
    A single named date:
      - 0 candidate target meetings: log debug, leave for next sweep
      - 1 candidate: set minutes_adopted_at if currently NULL, return id
      - 2+ candidates: use the only one with a minutes document, else
        warn-log structured event and skip
    A date range ("February 3 – 24, 2026") names a window rather than meetings,
    so it flips every not-yet-adopted meeting in the window that has a minutes
    document; rows without one (placeholders, cancellations) are left alone.

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
                    spans = extract_adoption_targets(
                        c["title"],
                        adoption_meeting_date=c["adoption_meeting_date"],
                    )
                except AdoptionParseError as e:
                    logger.debug(
                        "adoption_parse_skip municipality_id=%s agenda_item_id=%s reason=%s",
                        municipality_id, c["agenda_item_id"], e,
                    )
                    continue

                for span in spans:
                    if span.is_range:
                        cur.execute(
                            """UPDATE meetings SET minutes_adopted_at = %s
                               WHERE municipality_id = %s
                                 AND meeting_date BETWEEN %s AND %s
                                 AND meeting_date < %s
                                 AND minutes_url IS NOT NULL
                                 AND minutes_adopted_at IS NULL
                               RETURNING id""",
                            (c["adoption_meeting_date"], municipality_id,
                             span.start, span.end, c["adoption_meeting_date"]),
                        )
                        flipped.extend(r["id"] for r in cur.fetchall())
                        continue

                    target_date = span.start
                    cur.execute(
                        """SELECT id, minutes_url IS NOT NULL AS has_minutes FROM meetings
                           WHERE municipality_id = %s AND meeting_date = %s""",
                        (municipality_id, target_date),
                    )
                    rows = cur.fetchall()
                    if len(rows) > 1:
                        # Duplicate clips for one date: the row with a minutes
                        # document is the meeting whose minutes were adopted.
                        with_minutes = [r for r in rows if r["has_minutes"]]
                        if len(with_minutes) == 1:
                            rows = with_minutes
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
