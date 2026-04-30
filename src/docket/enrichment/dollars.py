"""Dollar amount extraction from agenda item text.

Extracts monetary values from titles and descriptions using regex patterns.
Returns the largest dollar amount found (the most significant figure).

Tier thresholds for display:
    Green:  < $50,000
    Yellow: $50,000 - $250,000
    Orange: $250,000 - $1,000,000
    Red:    > $1,000,000
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# Pattern 1: Standard US dollar format — $1,234,567.89 or $1234567
_STANDARD_RE = re.compile(
    r"\$\s*([\d,]+(?:\.\d{1,2})?)"
)

# Pattern 2: Abbreviated millions — $1.2M, $1.2 million
_MILLION_RE = re.compile(
    r"\$\s*([\d,.]+)\s*(?:M\b|million)",
    re.IGNORECASE,
)

# Pattern 3: Abbreviated thousands — $500K, $500 thousand
_THOUSAND_RE = re.compile(
    r"\$\s*([\d,.]+)\s*(?:K\b|thousand)",
    re.IGNORECASE,
)

# Tier boundaries
_TIER_GREEN = Decimal("50000")
_TIER_YELLOW = Decimal("250000")
_TIER_ORANGE = Decimal("1000000")


def extract_dollars(text: str) -> Decimal | None:
    """Extract the largest dollar amount from text.

    Returns None if no dollar amounts found.
    """
    if not text or "$" not in text:
        return None

    amounts: list[Decimal] = []

    # Check abbreviated forms first (they're more specific)
    for match in _MILLION_RE.finditer(text):
        amount = _parse_number(match.group(1))
        if amount is not None:
            amounts.append(amount * Decimal("1000000"))

    for match in _THOUSAND_RE.finditer(text):
        amount = _parse_number(match.group(1))
        if amount is not None:
            amounts.append(amount * Decimal("1000"))

    # Then standard format (skip matches already captured by abbreviated patterns)
    for match in _STANDARD_RE.finditer(text):
        raw = match.group(1)
        # Skip if this is part of an abbreviated match (e.g. "$1.2M")
        end_pos = match.end()
        suffix = text[end_pos:end_pos + 10].strip().lower()
        if re.match(r"^(m\b|k\b|b\b|million|thousand|billion)", suffix):
            continue
        amount = _parse_number(raw)
        if amount is not None:
            amounts.append(amount)

    if not amounts:
        return None

    return max(amounts)


def classify_dollar_tier(amount: Decimal) -> str:
    """Classify a dollar amount into a display tier.

    Returns: "green", "yellow", "orange", or "red"
    """
    if amount < _TIER_GREEN:
        return "green"
    if amount < _TIER_YELLOW:
        return "yellow"
    if amount < _TIER_ORANGE:
        return "orange"
    return "red"


def _parse_number(raw: str) -> Decimal | None:
    """Parse a number string (with possible commas) into a Decimal."""
    cleaned = raw.replace(",", "").strip()
    if not cleaned:
        return None
    try:
        value = Decimal(cleaned)
        if value <= 0:
            return None
        return value
    except InvalidOperation:
        return None
