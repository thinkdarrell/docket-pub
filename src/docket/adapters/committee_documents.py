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

Minutes share one shape across the eight committees: the header, then items,
each ending with a line "Action Taken:" and the action. ``parse_minutes_items``
reads that shape into what the committee took up and what it did, by fixed
rules and patterns. A committee records a motion and a second, never a roll
call, so an action is kept as the minutes' own words and one of a closed list
of categories and is never a vote.

The readers are pure functions of their arguments. ``fetch_page`` and
``fetch_pdf`` are the only two that reach the network; they share one pause,
so a request to the city's site or to its Amazon bucket is never sooner than
a second after the last to either. Nothing here is stored:
``docket.services.committee_documents`` does that.

Plan `committee-documents`, M1 (the listing and the header), M2 (the items
of minutes) and M3 (the two fetches).
"""

from __future__ import annotations

import html as html_entities
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date

import requests
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

# The browser string adapters/city_calendar.py sends as _BROWSER_UA, copied:
# one adapter does not reach into another's private names.
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
_TIMEOUT_S = 60
# GOALS.md: polite delays of at least one second between requests to a city
# site. The PDFs are on the city's Amazon bucket, another host; one pause for
# both is the stricter choice.
_MIN_INTERVAL_S = 1.0
# A committee PDF is a few hundred kilobytes; anything past this is not one.
_MAX_PDF_BYTES = 40 * 1024 * 1024
_PDF_MARK = b"%PDF-"
_CHUNK_BYTES = 64 * 1024

# monotonic time of this module's last request; None before the first
_last_request_at: float | None = None

# A heading line inside a document: a number, Roman numeral or letter, then a
# full stop or closing bracket ("VI.", "4)", "a."). The lower-case l is in
# the numeral set because the minutes print "Ill." for "III.".
_HEADING_LINE = re.compile(r"^(?:[IVXLivxl]{1,6}|\d{1,2}|[A-Za-z])[.)]\s+\S")
# The same line, split into its label ("VI.") and its text.
_HEADING_PARTS = re.compile(r"^((?:[IVXLivxl]{1,6}|\d{1,2}|[A-Za-z])[.)])\s+(\S.*)$")

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


# --- minutes ---------------------------------------------------------------

# The two lines every page of minutes ends with.
_PAGE_NUMBER = re.compile(r"^Page \d+ of \d+$", re.IGNORECASE)
_TRANSCRIPTION = "FULL TRANSCRIPTION AVAILABLE UPON REQUEST"

# The header line that says who was there; what follows it is the list.
_PRESENT = re.compile(r"^Councilor\(s\):?\s*Present\s*:?\s*(.*)$", re.IGNORECASE)

# The line an action begins at; anything after the colon is its first line.
_ACTION_TAKEN = re.compile(r"^Action Taken\s*:?\s*(.*)$", re.IGNORECASE)

# The wordings an action ends with, in the minutes' own spellings
# ("Recommeded", "Agena"). An action's lines, joined, end with one of these
# and then only full stops and spaces.
_OUTCOME_ENDINGS = (
    (
        r"items? recomm\w* to the city council(?: consent)?(?: agen\w*)?"
        r"(?: by the committee chair\s*[–-]\s*lack of quorum"
        r"| with (?:a )?no recommendation| with a recommendation to deny| for approval)?"
    ),
    r"(?:forwarded|forward item) to the city council agen\w* with(?:out)? a (?:no )?recommendation",
    r"no action\s*[–-]\s*information\w* only",
    r"item withdrawn(?: by (?:the )?administration)?",
    r"item tabled",
    r"item delayed",
    r"minutes were approved(?: as recorded| with said corrections)?",
    r"meeting adjourned",
)
_OUTCOME_ENDING = re.compile(r"(?:" + "|".join(_OUTCOME_ENDINGS) + r")[.\s]*$", re.IGNORECASE)

# How far past the first outcome ending to look for a longer one.
_ENDING_LOOKAHEAD = 2

# What the committee did, as one of a closed list. The first pattern found
# anywhere in the action's words decides, so the order matters: "Approval of
# Minute Delayed – Lack of Quorum." has no "recomm" and is a delay.
_CATEGORIES: tuple[tuple[str, re.Pattern], ...] = tuple(
    (category, re.compile(pattern, re.IGNORECASE))
    for category, pattern in (
        ("minutes_approved", r"minutes were approved"),
        ("recommended_no_quorum", r"recomm\w*.*lack of quorum"),
        ("recommended_deny", r"recommendation to deny"),
        ("no_recommendation", r"(?:with\s+(?:a\s+)?no|without\s+a)\s+recommendation"),
        ("recommended_consent", r"recomm\w*\s+to\s+the\s+city\s+council\s+consent"),
        ("recommended", r"recomm\w*\s+(?:item\s+)?to\s+the\s+city\s+council"),
        ("information_only", r"no\s+action\s*[–-]\s*information"),
        ("withdrawn", r"\bwithdrawn\b"),
        ("tabled", r"\btabled\b"),
        ("delayed", r"\bdelayed\b"),
        ("adjourned", r"\badjourned\b"),
    )
)
_OTHER = "other"

_MOVED_BY = re.compile(r"Councilor(?: Pro Tem| President)? ([A-Z][\w’'-]+) Motioned")
_SECONDED_BY = re.compile(r"Councilor(?: Pro Tem| President)? ([A-Z][\w’'-]+) Seconded")


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


@dataclass(frozen=True)
class MinutesItem:
    """One thing a committee took up, and what the minutes say it did."""

    heading_label: str | None
    heading_text: str | None
    owns_heading: bool
    group: str | None
    name: str
    body: str
    action_text: str
    action_category: str
    moved_by: str | None
    seconded_by: str | None


@dataclass(frozen=True)
class MinutesFacts:
    """What a minutes document records: who was present, and its items."""

    present: str | None
    items: tuple[MinutesItem, ...]
    trailing_lines: int


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


def _header_lines(lines: list[str]) -> list[str]:
    """The lines before the first heading line, and at most the first twenty."""
    header: list[str] = []
    for line in lines[:_HEADER_MAX_LINES]:
        if _HEADING_LINE.match(line):
            break
        header.append(line)
    return header


def read_header(text: str) -> Header | None:
    """What the document's first lines say it is.

    The header is the lines before the first heading line, and at most the
    first twenty. None when the text has no line at all, or when the header
    says the document is a meeting of the full council.
    """
    header = _header_lines(_lines(text))
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


# --- minutes ---------------------------------------------------------------


def _action_end(lines: list[str], another_action_follows: bool) -> int:
    """How many of ``lines`` are the action. ``lines`` is the action's first
    line, when the "Action Taken" line carries one, and its stretch: the
    lines up to the next heading line, the next "Action Taken" line or the
    end.

    The action ends at the first line after which its words end with an
    outcome ending, or one or two lines later when the same ending, begun at
    the same word, is still what they end with (an ending wrapped onto the
    next line). With no outcome ending, the whole stretch is the action
    unless another action follows it; then the stretch also holds the next
    item's lines, and the action is its first sentence.
    """
    for count in range(1, len(lines) + 1):
        ending = _OUTCOME_ENDING.search(" ".join(lines[:count]))
        if ending is None:
            continue
        end = count
        for longer in range(count + 1, min(count + _ENDING_LOOKAHEAD, len(lines)) + 1):
            wrapped = _OUTCOME_ENDING.search(" ".join(lines[:longer]))
            # The next item's lines can end like an outcome too; only the
            # ending already found, read further, extends the action.
            if wrapped is not None and wrapped.start() == ending.start():
                end = longer
        return end
    if not another_action_follows:
        return len(lines)
    for count, line in enumerate(lines, start=1):
        if line.endswith("."):
            return count
    return min(1, len(lines))


def _category(action_text: str) -> str:
    for category, pattern in _CATEGORIES:
        if pattern.search(action_text):
            return category
    return _OTHER


def _captured(pattern: re.Pattern, action_text: str) -> str | None:
    match = pattern.search(action_text)
    return match.group(1) if match else None


def parse_minutes_items(text: str) -> MinutesFacts:
    """A minutes document's text, read into who was present and the items:
    each thing the committee took up, with the action the minutes record.

    An item is the lines since the previous action's end and the action that
    follows them. It is named by its heading when it alone has that heading,
    and by its own first line, with the heading as its group, when several
    actions share one (licence applications listed under "C. LIQUOR
    LICENSES"). Lines after the last action belong to no item and are only
    counted.
    """
    lines = _lines(text)
    header = _header_lines(lines)

    present = None
    for line in header:
        match = _PRESENT.match(line)
        if match:
            present = match.group(1).strip() or None
            break

    # The page number, the transcription line and the header repeated at the
    # top of every page are not the committee's business.
    repeated = set(header)
    rest = [
        line
        for line in lines[len(header) :]
        if not _PAGE_NUMBER.match(line) and line.upper() != _TRANSCRIPTION and line not in repeated
    ]

    # Each action with the lines before it: (the lines, the action's lines,
    # the index among ``headings`` of the heading the item has, whether that
    # heading is among its own lines).
    headings: list[tuple[str, str]] = []
    found: list[tuple[list[str], list[str], int | None, bool]] = []
    pending: list[str] = []
    current: int | None = None
    owns = False
    trailing = 0  # lines, heading lines among them, since the last action's end
    index = 0
    while index < len(rest):
        line = rest[index]
        action = _ACTION_TAKEN.match(line)
        if action is None:
            parts = _HEADING_PARTS.match(line)
            if parts:
                headings.append((parts.group(1), parts.group(2).strip()))
                current = len(headings) - 1
                owns = True
            else:
                pending.append(line)
            trailing += 1
            index += 1
            continue

        stop = index + 1
        while stop < len(rest) and not _HEADING_LINE.match(rest[stop]) and not _ACTION_TAKEN.match(rest[stop]):
            stop += 1
        another_action_follows = stop < len(rest) and bool(_ACTION_TAKEN.match(rest[stop]))
        first = action.group(1).strip()
        candidates = ([first] if first else []) + rest[index + 1 : stop]
        end = _action_end(candidates, another_action_follows)

        found.append((pending, candidates[:end], current, owns))
        pending = []
        owns = False
        trailing = 0
        index += 1 + end - (1 if first else 0)

    shared: dict[int, int] = {}
    for _pending, _action, heading, _owns in found:
        if heading is not None:
            shared[heading] = shared.get(heading, 0) + 1

    items = []
    for body_lines, action_lines, heading, owns_heading in found:
        label, heading_text = headings[heading] if heading is not None else (None, None)
        if heading is not None and shared[heading] == 1:
            name, group = heading_text, None
        else:
            # Several actions under one heading, or no heading at all: the
            # item's own first line names it. With no line of its own, the
            # heading's text is all there is to call it.
            name = body_lines[0] if body_lines else (heading_text or "")
            group = f"{label} {heading_text}" if heading is not None else None
        action_text = " ".join(action_lines)
        items.append(
            MinutesItem(
                heading_label=label,
                heading_text=heading_text,
                owns_heading=owns_heading,
                group=group,
                name=name,
                body="\n".join(body_lines),
                action_text=action_text,
                action_category=_category(action_text),
                moved_by=_captured(_MOVED_BY, action_text),
                seconded_by=_captured(_SECONDED_BY, action_text),
            )
        )

    return MinutesFacts(present=present, items=tuple(items), trailing_lines=trailing)


# --- fetching --------------------------------------------------------------


def _get(url: str, **kwargs) -> requests.Response:
    """One GET with the browser user agent and the timeout, no sooner than a
    second after this module's last. Raises on an HTTP error."""
    global _last_request_at
    if _last_request_at is not None:
        wait = _MIN_INTERVAL_S - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
    try:
        resp = requests.get(url, timeout=_TIMEOUT_S, headers={"User-Agent": _BROWSER_UA}, **kwargs)
    finally:
        _last_request_at = time.monotonic()
    resp.raise_for_status()
    return resp


def fetch_page(url: str) -> str:
    """A committee page's HTML. Raises when the request fails."""
    return _get(url).text


def fetch_pdf(url: str) -> bytes | None:
    """A PDF's bytes, or None when there is no PDF to be had: the request
    failed, the body is past 40 MB (the read stops there), or the body does
    not begin with the PDF mark (an error page served with a 200)."""
    try:
        resp = _get(url, stream=True)
    except requests.RequestException as exc:
        log.warning("committee document %s: fetch failed: %s", url, exc)
        return None
    try:
        chunks: list[bytes] = []
        size = 0
        for chunk in resp.iter_content(chunk_size=_CHUNK_BYTES):
            size += len(chunk)
            if size > _MAX_PDF_BYTES:
                log.warning("committee document %s: past %d bytes, not read", url, _MAX_PDF_BYTES)
                return None
            chunks.append(chunk)
    except requests.RequestException as exc:
        log.warning("committee document %s: fetch failed part-way: %s", url, exc)
        return None
    finally:
        resp.close()
    body = b"".join(chunks)
    if not body.startswith(_PDF_MARK):
        log.warning("committee document %s: the body is not a PDF", url)
        return None
    return body
