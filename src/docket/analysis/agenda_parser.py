"""Parse Birmingham council agenda PDFs into structured items.

The Granicus AgendaViewer page serves a PDF for upcoming meetings (before
a clip_id is assigned). Each agenda item is introduced by one of:

    ITEM N.                  — substantive, non-consent
    CONSENT ITEM N.          — on the consent agenda
    CONSENT(ph) ITEM N.      — consent with a public hearing

Item body extends from the marker to the next marker. Page headers of the
form "Agenda – Month DD, YYYY N" appear between items as noise and must
be stripped. Sponsor is the content of "(Submitted by ...)".

This module is the pre-recording counterpart to `minutes_parser.py`, which
parses the post-meeting minutes PDF for votes and attendance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from docket.analysis.minutes_approval import MONTH_PATTERN, is_adoption_title


# Item marker. Capture group 1 = item number; matches three variants:
#   ITEM N.           (substantive)
#   CONSENT ITEM N.   (consent)
#   CONSENT(ph) ITEM N.  (consent with public hearing)
# The optional leading whitespace + leading newline allows the marker to
# appear at start-of-document or after any character.
_ITEM_MARKER_RE = re.compile(
    r"((?:CONSENT(?:\([a-z]+\))?\s+)?)ITEM\s+(\d+)\.",
    re.IGNORECASE,
)

# Page header lines like "Agenda – May 19, 2026 12". The em-dash variants
# (– U+2013, — U+2014, plain hyphen) all appear in the wild depending on
# how the PDF was generated.
_PAGE_HEADER_RE = re.compile(
    r"^[ \t]*Agenda\s*[–—\-]\s*\w+\s+\d+,\s*\d{4}\s+\d+[ \t]*$",
    re.MULTILINE,
)

# Sponsor: capture text inside (Submitted by ...). Stops at the first
# closing paren so "(Recommended by ...)" isn't accidentally included.
_SPONSOR_RE = re.compile(r"\(Submitted\s+by\s+([^)]+?)\)", re.IGNORECASE)

# Title is the body up to the first parenthetical metadata (Submitted by /
# Recommended by). For the few items with no such parenthetical, title is
# the entire body.
_TITLE_CUTOFF_RE = re.compile(
    r"\s*\((?:Submitted|Recommended)\s+by\b",
    re.IGNORECASE,
)

# A wrapped continuation of the minutes-approval line holds nothing but more
# dates: day numbers, separators, "and", and month names.
_DATE_CONTINUATION_RE = re.compile(
    rf"^(?:\d|[\s,&.\-–—]|\band\b|\b(?:{MONTH_PATTERN})\b)+$",
    re.IGNORECASE,
)


_YEAR_AT_END_RE = re.compile(r"\b(?:19|20)\d{2}\.?$")


@dataclass
class ParsedAgendaItem:
    """A single agenda item extracted from the agenda PDF."""

    item_number: str
    title: str
    body: str
    sponsor: str | None
    is_consent: bool


def parse_agenda(text: str) -> list[ParsedAgendaItem]:
    """Extract agenda items from agenda PDF text.

    Returns items in agenda order. Empty list if no markers found.
    """
    if not text:
        return []

    markers = list(_ITEM_MARKER_RE.finditer(text))
    if not markers:
        return []

    items: list[ParsedAgendaItem] = []
    for i, m in enumerate(markers):
        prefix = m.group(1) or ""
        item_number = m.group(2)
        is_consent = "consent" in prefix.lower()

        # Body: from end of this marker to start of next (or end of text)
        body_start = m.end()
        body_end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        raw_body = text[body_start:body_end]

        body = _clean_body(raw_body)
        title = _extract_title(body)
        sponsor = _extract_sponsor(body)

        items.append(
            ParsedAgendaItem(
                item_number=item_number,
                title=title,
                body=body,
                sponsor=sponsor,
                is_consent=is_consent,
            )
        )

    return items


def parse_minutes_approval(text: str) -> str | None:
    """Return the un-numbered preamble line by which the council adopts earlier
    minutes, e.g. "APPROVAL OF MINUTES FROM PREVIOUS MEETINGS: February 3 – 24, 2026".

    Only the preamble (before the first item marker) is searched, so approval
    wording inside an item body is never mistaken for it. A long date list
    that wraps is rejoined. None if absent — most weeks the agenda carries
    only "MINUTES NOT READY".
    """
    if not text:
        return None

    first_item = _ITEM_MARKER_RE.search(text)
    preamble = text[: first_item.start()] if first_item else text

    lines = preamble.split("\n")
    for i, line in enumerate(lines):
        if not is_adoption_title(line):
            continue
        approval = line.strip()
        for following in lines[i + 1:]:
            # A line that already ends in a year is finished; only a list left
            # hanging (no year yet, or a trailing separator) continues below.
            if _YEAR_AT_END_RE.search(approval):
                break
            if not following.strip():
                continue
            if not _DATE_CONTINUATION_RE.match(following.strip()):
                break
            approval = f"{approval} {following.strip()}"
        return re.sub(r"\s+", " ", approval)
    return None


def _clean_body(raw: str) -> str:
    """Strip page-header noise and normalize whitespace."""
    # Remove page header lines
    cleaned = _PAGE_HEADER_RE.sub("", raw)
    # Collapse runs of internal whitespace (incl. PDF-induced line breaks
    # mid-sentence) to single spaces, then trim.
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _extract_title(body: str) -> str:
    """Title is the body up to the first sponsor/recommendation parenthetical."""
    match = _TITLE_CUTOFF_RE.search(body)
    if match:
        return body[: match.start()].strip()
    return body


def _extract_sponsor(body: str) -> str | None:
    """Capture the contents of `(Submitted by ...)`. Returns None if absent."""
    match = _SPONSOR_RE.search(body)
    if not match:
        return None
    # Normalize whitespace (PDFs often inject mid-name line breaks)
    return re.sub(r"\s+", " ", match.group(1)).strip()
