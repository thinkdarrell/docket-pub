"""Extract high-signal structured facts from vote raw_text.

Two extractors:
- extract_dollar_amounts: numeric dollar values (all amounts, as a set of floats)
- extract_proper_nouns: multi-token capitalized phrases (filtered against
  council surnames, procedural phrases, and month names)

Used by the structured-fact tier of the substantive vote matcher.

Note on dollars: docket.enrichment.dollars.extract_dollars() returns only the
*maximum* Decimal for display purposes. Here we need *all* amounts for matching,
so we re-parse the text directly using the same regex patterns.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


# ---------------------------------------------------------------------------
# Dollar extraction — all amounts (not just max)
# ---------------------------------------------------------------------------

_STANDARD_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{1,2})?)")
_MILLION_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{1,2})?)\s*(?:million)", re.IGNORECASE)
_MILLION_SHORT_RE = re.compile(r"\$\s*([\d,]+(?:\.\d)?)\s*M\b")
_THOUSAND_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{1,2})?)\s*(?:thousand)", re.IGNORECASE)
_THOUSAND_SHORT_RE = re.compile(r"\$\s*([\d,]+(?:\.\d)?)\s*K\b")


def _parse_decimal(raw: str) -> Decimal | None:
    """Parse a number string (with possible commas) into a Decimal."""
    stripped = raw.strip()
    if not stripped:
        return None
    # Handle trailing ,XX (cents written with comma instead of period)
    if re.match(r".*,\d{2}$", stripped) and "." not in stripped:
        stripped = stripped[:-3] + "." + stripped[-2:]
    cleaned = stripped.replace(",", "")
    try:
        value = Decimal(cleaned)
        if value <= 0:
            return None
        return value
    except InvalidOperation:
        return None


def extract_dollar_amounts(text: str | None) -> set[float]:
    """Return the set of all dollar amounts in text as floats.

    Unlike enrichment.dollars.extract_dollars() which returns only the max,
    this returns every distinct amount found — needed for vote-matching
    where we want to check if amounts overlap.
    """
    if not text or "$" not in text:
        return set()

    amounts: set[float] = set()

    for match in _MILLION_RE.finditer(text):
        d = _parse_decimal(match.group(1))
        if d is not None:
            amounts.add(float(d * Decimal("1000000")))

    for match in _MILLION_SHORT_RE.finditer(text):
        d = _parse_decimal(match.group(1))
        if d is not None:
            amounts.add(float(d * Decimal("1000000")))

    for match in _THOUSAND_RE.finditer(text):
        d = _parse_decimal(match.group(1))
        if d is not None:
            amounts.add(float(d * Decimal("1000")))

    for match in _THOUSAND_SHORT_RE.finditer(text):
        d = _parse_decimal(match.group(1))
        if d is not None:
            amounts.add(float(d * Decimal("1000")))

    # Standard format — skip matches that are part of abbreviated patterns
    for match in _STANDARD_RE.finditer(text):
        raw = match.group(1)
        end_pos = match.end()
        suffix = text[end_pos:end_pos + 10].strip().lower()
        if re.match(r"^(m\b|k\b|b\b|million|thousand|billion)", suffix):
            continue
        d = _parse_decimal(raw)
        if d is not None:
            amounts.add(float(d))

    return amounts


# ---------------------------------------------------------------------------
# Proper-noun extraction
# ---------------------------------------------------------------------------

# Matches sequences of capitalized words, optionally joined by & (with spaces).
# Strategy: scan for runs of Title-cased tokens (possibly separated by & or
# &-with-spaces), capturing multi-word proper-noun phrases.
#
# Pattern breakdown:
#   [A-Z][a-zA-Z]+ — a capitalized word (at least 2 chars, no digits)
#   (?:                — optionally followed by:
#     \s+&\s+          —   " & " separator
#     [A-Z][a-zA-Z]+   —   another capitalized word
#   )?
#   (?:\s+[A-Z][a-zA-Z]+)*  — zero or more additional capitalized words
#
# This approach: findall runs of capitalized tokens (greedy), then filter.

_CAP_TOKEN_RE = re.compile(
    r"[A-Z][a-zA-Z]+"
    r"(?:"
        r"(?:\s+&\s+|\s+)"
        r"[A-Z][a-zA-Z]+"
    r"){1,6}"
)

_PROCEDURAL_DENYLIST = frozenset({
    "City Clerk",
    "Presiding Officer",
    "Council Chamber",
    "City Council",
    "City Hall",
    "Mayor's Office",
    "The City",
    "The Council",
    "The Mayor",
    "City of",
    "City of Birmingham",
    "Birmingham As Made",
    "Roll Call",
    "Roll Being",
    "Roll Being Called",
    "Unanimous Consent",
    "Ayes None",
    "Nays None",
    "Councilmember Smitherman",
    "Councilmember Tate",
    "Presiding Officer declared",
})

_MONTH_NAMES = frozenset({
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
})


def _contains_surname(phrase: str, council_surnames: set[str]) -> bool:
    """Return True if any token in phrase is a council surname."""
    tokens = phrase.split()
    return any(tok in council_surnames for tok in tokens)


def _contains_month(phrase: str) -> bool:
    """Return True if any token in phrase is a month name."""
    tokens = phrase.split()
    return any(tok in _MONTH_NAMES for tok in tokens)


def _is_procedural(phrase: str) -> bool:
    """Return True if phrase (or any prefix) matches the procedural denylist."""
    return phrase in _PROCEDURAL_DENYLIST


def _candidate_subphrases(phrase: str) -> list[str]:
    """Return all right-aligned sub-phrases (2+ tokens) of a matched phrase.

    This handles sentence-initial capitalization: "Pay Shield Property Solutions"
    should yield "Shield Property Solutions" as well as the full phrase.
    All sub-phrases of length ≥ 2 tokens starting at each token position are
    returned so filtering can act on the smallest meaningful unit.
    """
    tokens = phrase.split()
    candidates = []
    # All starting positions (including i=0 = full phrase)
    for start in range(len(tokens)):
        sub = tokens[start:]
        if len(sub) >= 2:
            candidates.append(" ".join(sub))
    return candidates


def extract_proper_nouns(text: str | None, *, council_surnames: set[str]) -> set[str]:
    """Return multi-token capitalized phrases, filtered for noise.

    Filters applied:
    - Single-token phrases (must be 2+ words)
    - Council surnames (any token match)
    - Procedural denylist (full-phrase match)
    - Month names (any token match)

    For each regex match, sub-phrases (all right-aligned slices of 2+ tokens)
    are also considered, so that sentence-initial capitalized words (e.g. "Pay"
    in "Pay Shield Property Solutions") do not suppress the legitimate phrase.
    """
    if not text:
        return set()

    raw_matches = [m.group(0) for m in _CAP_TOKEN_RE.finditer(text)]

    # Build candidate set: each match + all its right-aligned sub-phrases
    candidates: set[str] = set()
    for phrase in raw_matches:
        for sub in _candidate_subphrases(phrase):
            candidates.add(sub)

    result: set[str] = set()
    for phrase in candidates:
        tokens = phrase.split()
        if len(tokens) < 2:
            continue
        if _is_procedural(phrase):
            continue
        if _contains_surname(phrase, council_surnames):
            continue
        if _contains_month(phrase):
            continue
        result.add(phrase)

    return result
