"""Extract resolution / ordinance numbers from a vote's raw_text.

Used by:
- analysis/minutes_parser.py (inline extraction during ingest)
- scripts/backfill_vote_resolution_numbers.py (one-shot over existing rows)

Design: prefer the rightmost identifier that appears BEFORE any vote-tally
marker, since that's the one being acted on. If no tally marker is found,
scan the full text.
"""

from __future__ import annotations

import re

_VOTE_RES_RE = re.compile(
    r"\b(?:RESOLUTION|ORDINANCE)\s+(?:NO\.?\s*)?"
    r"(?P<num>(?:R|O)?-?\d{1,5}(?:[-/]\d{2,4})?)\b",
    re.IGNORECASE,
)

_TALLY_MARKERS = (
    "the vote was as follows",
    "upon the roll being called",
    "ayes:",
    "yeas:",
    "roll call:",
    "roll being called",
)


def _truncate_at_tally(text: str) -> str:
    """Return the substring of `text` ending at the earliest tally marker.

    If no marker is present, return the full text.
    """
    lowered = text.lower()
    earliest = len(text)
    for marker in _TALLY_MARKERS:
        idx = lowered.find(marker)
        if idx != -1 and idx < earliest:
            earliest = idx
    return text[:earliest]


def extract_resolution_number(text: str | None) -> str | None:
    """Return the rightmost RESOLUTION/ORDINANCE number before the tally, or None."""
    if not text:
        return None
    pre_tally = _truncate_at_tally(text)
    matches = list(_VOTE_RES_RE.finditer(pre_tally))
    if not matches:
        return None
    return matches[-1].group("num")
