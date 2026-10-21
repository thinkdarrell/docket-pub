"""Shared helpers for platform adapters."""

from __future__ import annotations

import re
from dataclasses import dataclass

_TITLE_SUFFIX_MARKERS = (
    " - cancelled",
    " - rescheduled",
    " - postponed",
    " - deferred",
)
_NON_WORD_OR_SPACE = re.compile(r"[^\w\s]")


# The vocabulary of a meeting's classification. These two tuples are the one
# owner: every CHECK constraint, select element, and test imports them.
# meeting_type names the body that met; session_kind names the sitting.
MEETING_TYPES: tuple[str, ...] = ("council", "committee", "planning", "board", "other")
SESSION_KINDS: tuple[str, ...] = ("regular", "special", "work_session", "budget_hearing")

# A title that is only a date ("April 23, 2024") names no body.
_BARE_DATE = re.compile(r"^\s*[a-z]+\s+\d{1,2},?\s+\d{4}\s*$")
_OTHER_KEYWORDS = ("election", "press conference", "granicus test")
_PLANNING_KEYWORDS = (
    "planning commission",
    "planning and zoning commission",
    "planning & zoning commission",
    "zoning adjustment",
    "bza",
)
# "parks and recreation": Vestavia Hills' parks board titles its work
# sessions without the word "board" ("Parks and Recreation Work Session").
_BOARD_KEYWORDS = ("board", "commission", "parks and recreation")
# Trailing words stripped from a body name, longest first.
_BODY_NAME_TRAILERS = (
    " special work session",
    " work session",
    " special meeting",
    " regular meeting",
    " meeting",
)


@dataclass(frozen=True)
class Classification:
    """What a title says about a meeting: the body, the sitting, the body's name."""

    meeting_type: str
    session_kind: str
    body_name: str | None


def _session_kind(t: str) -> str:
    if "work session" in t:
        return "work_session"
    if "budget hearing" in t or "budget meeting" in t:
        return "budget_hearing"
    if "special" in t or "called" in t:
        return "special"
    return "regular"


def _meeting_type(t: str, kind: str) -> str:
    if not t.strip() or any(k in t for k in _OTHER_KEYWORDS) or _BARE_DATE.match(t):
        return "other"
    if "committee" in t:
        return "committee"
    if any(k in t for k in _PLANNING_KEYWORDS):
        return "planning"
    if any(k in t for k in _BOARD_KEYWORDS) and "council" not in t:
        return "board"
    # A title that names a sitting but no body ("Special Called Meeting",
    # "Budget Work Session") is the council's: every feed here is the
    # council department's.
    if "council" in t or "budget" in t or kind != "regular":
        return "council"
    return "other"


def _body_name(title: str) -> str:
    name = title
    idx = name.find(" - ")
    if idx != -1:
        name = name[:idx]
    name = re.sub(r"\s*\(bza\)\s*$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"^\s*special called ", "", name, flags=re.IGNORECASE)
    lowered = name.lower().rstrip()
    for trailer in _BODY_NAME_TRAILERS:
        if lowered.endswith(trailer):
            name = name.rstrip()[: -len(trailer)]
            break
    return " ".join(name.split())


def classify_title(title: str) -> Classification:
    """Classify a meeting title into its body, its sitting, and the body's name.

    Pure keyword rules on the lowercased title; the body name is cut from
    the original title (case kept) and is None for the council and for
    `other`, since neither has a name a source supplied.
    """
    t = title.lower()
    kind = _session_kind(t)
    body = _meeting_type(t, kind)
    name = _body_name(title) if body in ("committee", "planning", "board") else None
    return Classification(body, kind, name or None)


def classify_meeting(title: str) -> str:
    """Classify meeting type (the body) from its title."""
    return classify_title(title).meeting_type


_COUNCIL_LABELS = {
    "regular": "City Council meeting",
    "special": "Special called council meeting",
    "work_session": "Council work session",
    "budget_hearing": "Budget hearing",
}
_UNNAMED_LABELS = {
    "committee": "Council committee meeting",
    "planning": "Planning commission meeting",
    "board": "Board meeting",
}


def label_for(
    meeting_type: str,
    session_kind: str,
    body_name: str | None,
    title: str,
    *,
    cancelled: bool,
) -> str:
    """Build the display label a reader sees in place of the clip name.

    `cancelled` is decided by the caller: the pattern that defines a
    cancelled title is owned by docket.services.query (is_cancelled_title),
    which this module may not import. An `other` meeting is labelled by its
    title itself and takes no suffix.
    """
    if meeting_type == "other":
        return title
    if meeting_type == "council":
        label = _COUNCIL_LABELS.get(session_kind, _COUNCIL_LABELS["regular"])
    else:
        label = body_name or _UNNAMED_LABELS.get(meeting_type, "Meeting")
        if session_kind == "special":
            label += " (special called)"
        elif session_kind == "work_session":
            label += " (work session)"
    if cancelled:
        label += " (cancelled)"
    return label


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
