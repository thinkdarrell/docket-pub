"""Shared helpers for platform adapters."""

from __future__ import annotations

import re

_TITLE_SUFFIX_MARKERS = (
    " - cancelled",
    " - rescheduled",
    " - postponed",
    " - deferred",
)
_NON_WORD_OR_SPACE = re.compile(r"[^\w\s]")


def classify_meeting(title: str) -> str:
    """Classify meeting type from its title."""
    t = title.lower()
    if "regular" in t and "council" in t:
        return "council"
    if "special" in t or "called" in t:
        return "special"
    if "work session" in t:
        return "work_session"
    if "planning" in t or "bza" in t or "zoning" in t:
        return "planning"
    if "board" in t and "council" not in t:
        return "board"
    if "committee" in t or "commission" in t:
        return "committee"
    if "budget" in t:
        return "council"
    if "council" in t:
        return "council"
    return "other"


def is_consent_item(description: str | None) -> bool:
    """Guess if an agenda item is part of the consent agenda."""
    return "consent" in (description or "").lower()


def normalize_title(title: str) -> str:
    """Normalize a meeting title for cross-row reconciliation.

    Aggressive enough to match a freshly-archived row against its prior
    upcoming-row counterpart despite minor edits: case differences, whitespace
    changes, punctuation, and cancellation/rescheduling suffixes (which are
    truncated along with anything that follows).

    Order: lowercase → strip suffix-and-after → drop punctuation → collapse
    whitespace. Idempotent on its own output.
    """
    t = title.lower()
    for marker in _TITLE_SUFFIX_MARKERS:
        idx = t.find(marker)
        if idx != -1:
            t = t[:idx]
            break
    t = _NON_WORD_OR_SPACE.sub("", t)
    return " ".join(t.split())
