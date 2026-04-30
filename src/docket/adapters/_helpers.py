"""Shared helpers for platform adapters."""

from __future__ import annotations


def classify_meeting(title: str) -> str:
    """Classify meeting type from its title."""
    t = title.lower()
    if "regular" in t:
        return "council"
    if "special" in t or "called" in t:
        return "special"
    if "budget" in t:
        return "council"
    if "work session" in t:
        return "work_session"
    if "committee" in t:
        return "committee"
    if "planning" in t or "bza" in t or "zoning" in t:
        return "planning"
    return "council"


def is_consent_item(description: str) -> bool:
    """Guess if an agenda item is part of the consent agenda."""
    return "consent" in description.lower()
