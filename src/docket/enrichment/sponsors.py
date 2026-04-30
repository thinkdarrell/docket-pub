"""Sponsor extraction from agenda item text.

Extracts sponsor attribution patterns found in Alabama city council agendas:
  - Birmingham: "(Submitted by the Mayor)" / "(Recommended by ...)"
  - Mobile: "(sponsored by Councilmember Carroll)" / "(submitted by Mayor Stimpson)"

The extracted value maps to the sponsor field on agenda_items.
"""

from __future__ import annotations

import re

# Match (Submitted by ...) — Birmingham pattern
_SUBMITTED_RE = re.compile(
    r"\(Submitted by\s+(.+?)\)",
    re.IGNORECASE,
)

# Match (sponsored by ...) — Mobile pattern
_SPONSORED_RE = re.compile(
    r"\(sponsored by\s+(.+?)\)",
    re.IGNORECASE,
)

# Match (Recommended by ...) — captured for context but not stored as sponsor
_RECOMMENDED_RE = re.compile(
    r"\(Recommended by\s+(.+?)\)",
    re.IGNORECASE,
)

# Clean up parenthetical attribution from titles
_ATTRIBUTION_RE = re.compile(
    r"\s*\((?:Submitted|Recommended|sponsored) by\s+[^)]+\)\s*",
    re.IGNORECASE,
)


def extract_sponsor(text: str) -> str | None:
    """Extract the sponsor (Submitted by) from agenda item text.

    Returns the sponsor name/role, or None if not found.

    Examples:
        "...for the Library. (Submitted by the Mayor)" -> "the Mayor"
        "...(Submitted by Councilor Smith, Chair, Arts Committee)" -> "Councilor Smith, Chair, Arts Committee"
    """
    if not text:
        return None

    # Try Birmingham pattern first, then Mobile pattern
    match = _SUBMITTED_RE.search(text) or _SPONSORED_RE.search(text)
    if match:
        return match.group(1).strip().rstrip("*")

    return None


def extract_recommended_by(text: str) -> str | None:
    """Extract the recommender from agenda item text.

    Returns the recommender name/role, or None if not found.
    """
    if not text:
        return None

    match = _RECOMMENDED_RE.search(text)
    if match:
        return match.group(1).strip().rstrip("*")

    return None


def clean_title(text: str) -> str:
    """Remove (Submitted by ...) and (Recommended by ...) from title text.

    These parentheticals clutter the display title. The data is
    preserved in the sponsor field instead.
    """
    if not text:
        return text

    cleaned = _ATTRIBUTION_RE.sub(" ", text).strip()
    # Clean up trailing punctuation artifacts
    cleaned = re.sub(r"\s*\*+\s*$", "", cleaned)
    return cleaned
