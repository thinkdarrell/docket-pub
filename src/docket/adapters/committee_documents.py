"""The Birmingham council committees' own documents: what a committee page
lists, and what a document's first lines say it is.

A domain module: no database and no services import. Each of the eight
standing committees has a page under
https://www.birminghamal.gov/government/city-council/council/council-committees-2025-2027/
listing its agenda and minutes PDFs. The page is a server-rendered Next.js
page; its listings are strings of HTML inside ``<script id="__NEXT_DATA__">``,
in which each meeting date is an ``<h4>`` and each document under it an
``<article class="media media--type-document">`` carrying the listed name in
its ``name`` attribute and the PDF's address in its ``file`` attribute.

What a document is (which committee, which date, agenda or minutes) is read
from the document's own first lines, its header. The page it is listed on,
the date heading it is listed under and its listed name are the fallback,
used only for a fact the header does not give: documents are posted under
the wrong heading, on the wrong committee's page, and under file names with
the wrong year, and the document's own header was right in every case read
by hand (plan `committee-documents`, Decision Log).

Everything here is a pure function of its arguments. Nothing is fetched and
nothing is stored.

Plan `committee-documents`, M1.
"""

from __future__ import annotations

import html as html_entities
import json
import logging
import re
from dataclasses import dataclass
from datetime import date

from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# The eight standing committees, by the names services/meeting_types.py
# gives them in BIRMINGHAM_COMMITTEES. An adapter may not import a service,
# so the names are held here and tests/unit/test_committee_documents_read.py
# asserts the two tuples are equal. Each has the slug of its page and the one
# pattern that finds it in upper-cased text.
_COMMITTEE_TABLE: tuple[tuple[str, str, str], ...] = (
    ("Arts and Parks", "arts-parks-committee", r"ARTS"),
    ("Budget and Finance", "budget-finance-committee", r"BUDGET"),
    (
        "Committee of the Whole / Administration & Governmental Affairs",
        "committee-whole-administration-governmental-affairs",
        r"COMMITTEE\s+OF\s+THE\s+WHOLE|GOVERNMENTAL\s+AFFAIRS",
    ),
    ("Community Development", "community-development-committee", r"COMMUNITY\s+DEVELOPMENT"),
    (
        "Economic and Workforce Development / Tourism",
        "economic-workforce-development-tourism-committee",
        r"ECONOMIC",
    ),
    ("Planning & Zoning", "planning-zoning-committee", r"PLANNING"),
    ("Public Safety", "public-safety-committee", r"PUBLIC\s+SAFETY"),
    ("Transportation & Infrastructure", "transportation-infrastructure-committee", r"TRANSPORTATION"),
)

COMMITTEES: tuple[str, ...] = tuple(name for name, _slug, _pattern in _COMMITTEE_TABLE)
COMMITTEE_SLUGS: dict[str, str] = {name: slug for name, slug, _pattern in _COMMITTEE_TABLE}
_COMMITTEE_PATTERNS = tuple((name, re.compile(pattern)) for name, _slug, pattern in _COMMITTEE_TABLE)

# The two places the city keeps a committee PDF: its Amazon bucket and its
# own site.
_PDF_PREFIXES = (
    "https://s3.us-east-2.amazonaws.com/assets.birminghamal.gov/",
    "https://www.birminghamal.gov/",
)

_DOCUMENT_CLASS = "media--type-document"

# A heading line inside a document: a number, Roman numeral or letter, then a
# full stop or closing bracket ("VI.", "4)", "a."). The lower-case l is in
# the numeral set because the minutes print "Ill." for "III.".
_HEADING_LINE = re.compile(r"^(?:[IVXLivxl]{1,6}|\d{1,2}|[A-Za-z])[.)]\s+\S")

_HEADER_MAX_LINES = 20
_NOT_A_COMMITTEE = "REGULAR MEETING OF THE COUNCIL"

_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}  # fmt: skip

# A word, a day, and perhaps a year. Whether the word is a month is decided
# afterwards from its first three letters. The year's four characters may be
# digits or the letter O ("2O26").
_DATE = re.compile(
    r"(?<![A-Za-z])([A-Za-z]{3,12})\.?\s*"
    r"(\d{1,2})(?!\d)(?:st|nd|rd|th)?"
    r"(?:\s*,?\s*([12][0-9Oo]{3})(?![0-9A-Za-z]))?"
)


@dataclass(frozen=True)
class Listing:
    """One PDF link on a committee page, with what the page says about it."""

    url: str
    listed_name: str | None
    listed_heading: str | None
    page_url: str


@dataclass(frozen=True)
class Header:
    """What a document's own first lines say."""

    committees: tuple[str, ...]
    date: tuple[int | None, int, int] | None
    is_minutes: bool
    special: bool
    work_session: bool
    lines: tuple[str, ...]


@dataclass(frozen=True)
class DocumentFacts:
    """What a document is, the document first and its listing second."""

    committees: tuple[str, ...]
    kind: str | None  # 'agenda' | 'minutes' | None
    meeting_date: date | None
    date_source: str | None  # 'header' | 'heading' | None
    listing_disagrees: bool
    special: bool
    work_session: bool


def committees_named(text: str) -> tuple[str, ...]:
    """The canonical committees whose pattern is found in ``text``, ordered
    by where each is first found."""
    upper = (text or "").upper()
    found = []
    for name, pattern in _COMMITTEE_PATTERNS:
        match = pattern.search(upper)
        if match:
            found.append((match.start(), name))
    return tuple(name for _start, name in sorted(found, key=lambda pair: pair[0]))


def _document_html_strings(node) -> list[str]:
    """Every string in the page's data that holds a document listing, in the
    order the data holds them."""
    if isinstance(node, str):
        return [node] if _DOCUMENT_CLASS in node else []
    if isinstance(node, dict):
        node = list(node.values())
    if isinstance(node, list):
        return [found for child in node for found in _document_html_strings(child)]
    return []


def parse_committee_page(html: str, page_url: str) -> list[Listing]:
    """The PDF listings of one committee page, in the page's order.

    A page with no data block, or one that is not JSON, is an empty list and
    a warning, never an exception: the city changing a page must not fail the
    run that reads the other seven.
    """
    script = BeautifulSoup(html or "", "html.parser").find("script", id="__NEXT_DATA__")
    if script is None:
        log.warning("committee page %s has no __NEXT_DATA__ block", page_url)
        return []
    try:
        data = json.loads(script.string or script.get_text())
    except (TypeError, ValueError) as exc:
        log.warning("committee page %s: __NEXT_DATA__ is not JSON: %s", page_url, exc)
        return []

    listings: list[Listing] = []
    seen: set[str] = set()
    for fragment in _document_html_strings(data):
        heading = None
        for element in BeautifulSoup(fragment, "html.parser").find_all(["h4", "article"]):
            if element.name == "h4":
                heading = " ".join(element.get_text().split()) or None
                continue
            if _DOCUMENT_CLASS not in (element.get("class") or []):
                continue
            url = (element.get("file") or "").strip()
            if not url.startswith(_PDF_PREFIXES) or not url.lower().endswith(".pdf"):
                continue
            if url in seen:
                continue
            seen.add(url)
            name = element.get("name")
            listings.append(
                Listing(
                    url=url,
                    listed_name=html_entities.unescape(name).strip() if name else None,
                    listed_heading=heading,
                    page_url=page_url,
                )
            )
    return listings


def read_date(text: str) -> tuple[int | None, int, int] | None:
    """The first month word, day and optional year in ``text``, as
    ``(year or None, month, day)``.

    The month is known by its first three letters alone, so "SEPTEBMBER" is
    September; a word that is not a month ("MONDAY", "ROOMS") is skipped and
    the search goes on. The letter O in a year is read as zero.
    """
    for match in _DATE.finditer(text or ""):
        month = _MONTHS.get(match.group(1)[:3].upper())
        if month is None:
            continue
        day = int(match.group(2))
        if not 1 <= day <= 31:
            continue
        year = None
        if match.group(3):
            digits = match.group(3).upper().replace("O", "0")
            if digits[:2] in ("19", "20"):
                year = int(digits)
        return (year, month, day)
    return None


def _lines(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def read_header(text: str) -> Header | None:
    """What the document's first lines say it is.

    The header is the lines before the first heading line, and at most the
    first twenty. None when the text has no line at all, or when the header
    says the document is a meeting of the full council.
    """
    header: list[str] = []
    for line in _lines(text)[:_HEADER_MAX_LINES]:
        if _HEADING_LINE.match(line):
            break
        header.append(line)
    if not header:
        return None

    joined = " ".join(header).upper()
    if _NOT_A_COMMITTEE in joined:
        return None

    when = None
    for line in header:
        when = read_date(line)
        if when is not None:
            break

    return Header(
        committees=committees_named(joined),
        date=when,
        is_minutes=any(line.upper() == "MINUTES" for line in header),
        special="SPECIAL CALLED" in joined,
        work_session="WORK SESSION" in joined,
        lines=tuple(header),
    )


def _calendar_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def resolve(listing: Listing, page_committee: str, header: Header | None) -> DocumentFacts:
    """Combine what the document says with what its listing says, the
    document first. ``header`` is None for a document with no text."""
    heading = read_date(listing.listed_heading or "")
    listed_name = (listing.listed_name or "").upper()

    if header is not None and header.committees:
        committees = header.committees
    else:
        committees = (page_committee,)

    if header is not None:
        kind = "minutes" if header.is_minutes else "agenda"
    elif "MINUTES" in listed_name:
        kind = "minutes"
    elif "AGENDA" in listed_name:
        kind = "agenda"
    else:
        kind = None

    printed = header.date if header is not None else None
    meeting_date = None
    date_source = None
    if printed is not None and printed[0] is not None:
        meeting_date = _calendar_date(*printed)
        date_source = "header"
    elif printed is not None:
        # A month and a day with no year: the heading supplies the year only
        # when it names the same day.
        if heading is not None and heading[0] is not None and heading[1:] == printed[1:]:
            meeting_date = _calendar_date(*heading)
            date_source = "heading"
    elif heading is not None and heading[0] is not None:
        meeting_date = _calendar_date(*heading)
        date_source = "heading"
    if meeting_date is None:
        date_source = None

    dates_differ = (
        printed is not None
        and printed[0] is not None
        and heading is not None
        and heading[0] is not None
        and printed != heading
    )
    another_committee = header is not None and bool(header.committees) and page_committee not in header.committees

    return DocumentFacts(
        committees=committees,
        kind=kind,
        meeting_date=meeting_date,
        date_source=date_source,
        listing_disagrees=dates_differ or another_committee,
        special=header.special if header is not None else False,
        work_session=header.work_session if header is not None else False,
    )
