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

from dateutil import parser as dateparser

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
