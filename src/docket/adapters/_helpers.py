"""Shared helpers for platform adapters."""

from __future__ import annotations


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


def is_consent_item(description: str) -> bool:
    """Guess if an agenda item is part of the consent agenda."""
    return "consent" in description.lower()
