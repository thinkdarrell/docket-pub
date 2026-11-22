"""Reader for the minutes of the Mobile City Council.

Takes the text of a minutes PDF, one string per page, and returns the date its
heading lines print and one record per vote: the page the vote is printed on,
who voted which way, who was absent, the motion, what the presiding officer
declared, a result, and the code and caption of the item where the minutes
print them. The rules are those of plan `mobile-votes-from-minutes`, M1, and
are numbered here as they are there.

This module is analysis: it reads text and returns values. It opens no
database connection and sends no request; fetching a file and storing a
reading belong to the adapter and to the service that calls this.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date, datetime

import pdfplumber

# Raised when a rule changes what a file reads as; a stored file whose reading
# was made under a lower number is read again.
READER_VERSION = 1

_MONTH = (
    r"(?:JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER"
    r"|NOVEMBER|DECEMBER)"
)

# Rule 1: the line that runs along the top of every page after the first, and
# the page number alone on a line.
_RUNNING_LINE = re.compile(rf"^MINUTES OF {_MONTH} \d{{1,2}}, \d{{4}}$", re.IGNORECASE)
_PAGE_NUMBER = re.compile(r"^\d{1,3}$")

# Rule 2.
_HEADING_LINE = re.compile(
    rf"^MUNICIPAL BUILDING, MOBILE, ALABAMA,?\s+({_MONTH}\s+\d{{1,2}},\s*\d{{4}})\s*$",
    re.IGNORECASE,
)

# Rule 3.
_ABSENT_LINE = re.compile(r"^Absent:\s*(.*)$")
_ATTENDANCE_REACH = 5

# Rule 5.
_AYES_LINE = re.compile(r"^Ayes?:\s*(.*)$")
_NAYS_LINE = re.compile(r"^Nays?:\s*(.*)$")
_ABSTAIN_LINE = re.compile(r"^Abstain(?:ed|ing|s)?:\s*(.*)$", re.IGNORECASE)
_BLOCK_REACH = 3

# Rule 6.
_DECLARATION_REACH = 4
_DECLARATION = re.compile(r"\b(declared|set the date)\b", re.IGNORECASE)
_MOTION_SENTENCE = re.compile(r"^The motion (passed|carried|failed)", re.IGNORECASE)
_DECLARED_WORD = re.compile(r"\bdeclared\b", re.IGNORECASE)
_SET_THE_DATE = re.compile(r"\bset the date\b", re.IGNORECASE)

# Rule 7.
_MOTION_REACH = 8
_MOVED = re.compile(r"\bmoved\b|called for the vote")
_MOTION_WORD = re.compile(r"\b(motion|move)\b")

# Rule 9.
_CODE_LINE = re.compile(
    r"^(RESOLUTION|ORDINANCE):?\s*(\d{2})\s*-\s*(\d{3,4})\s*-\s*(\d{4})\s*$"
)
_NEW_ITEM = re.compile(r"The\s+following\s+(resolution|ordinance)\b")
_OPENING = re.compile(r"The\s+following")
_OPENING_REACH = 12
_CAPTION_REACH = 10
_HELD_OVER = re.compile(r"\bwas\s+(held|laid)\s+over\b")
_SECTION_HEADINGS = frozenset(
    {
        "ANNOUNCEMENTS",
        "APPEALS",
        "PUBLIC HEARINGS",
        "ADOPTION OF THE AGENDA",
        "APPROVAL OF MINUTES",
        "COMMUNICATIONS FROM THE MAYOR",
        "STATEMENT OF RULES BY PRESIDING OFFICER",
        "NON-AGENDA ITEMS",
        "AGENDA ITEMS",
        "CALL FOR PUBLIC HEARINGS",
        "MONTHLY FINANCE REPORT",
        "PRESENTATIONS TO THE COUNCIL",
        "PRESENTATIONS BY THE COUNCIL",
    }
)
_SECTION_PATTERN = re.compile(
    r"^(CONSENT |CIP )?(RESOLUTIONS|ORDINANCES) (HELD OVER|BEING INTRODUCED)"
    r"( FOR THE FIRST TIME)?$"
)
_PROCEDURAL = re.compile(
    r"\b(adjourn\w*|executive session|adopt the agenda|suspen\w+ (of )?the rules|recess\w*)\b",
    re.IGNORECASE,
)

# Rule 10.
_FAILED = re.compile(r"\bfailed\b", re.IGNORECASE)
_DENIED = re.compile(r"\bdenied\b", re.IGNORECASE)
_MOVED_TO_DENY = re.compile(r"\bden(y|ied)\b", re.IGNORECASE)


@dataclass(frozen=True)
class MinutesVote:
    """One vote as the minutes print it. Names are kept exactly as printed."""

    page: int
    ayes: tuple[str, ...]
    nays: tuple[str, ...]
    abstain: tuple[str, ...]
    absent: tuple[str, ...]
    motion_text: str | None
    declared_text: str | None
    result: str  # 'passed' | 'failed' | 'unknown': whether the motion carried
    needs_review: bool
    # 'declaration_not_read' | 'declaration_ambiguous' | 'declaration_contradicts_count'
    review_reason: str | None
    code: str | None  # '40-948-2026'
    kind: str | None  # 'RESOLUTION' | 'ORDINANCE'
    caption: str | None
    raw_text: str


@dataclass(frozen=True)
class MinutesReading:
    """What one file reads as: the date its heading lines agree on, and its votes."""

    header_date: date | None
    votes: tuple[MinutesVote, ...]


def pages_from_pdf(pdf_bytes: bytes) -> list[str]:
    """The text of every page in order. A page with no text is the empty
    string, so the page after it keeps its number."""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def _kept_lines(pages: list[str]) -> tuple[list[str], list[int]]:
    """Rule 1: the lines that are content, and the 1-based page of each."""
    lines: list[str] = []
    line_pages: list[int] = []
    for number, text in enumerate(pages, start=1):
        for raw in (text or "").split("\n"):
            line = raw.strip()
            if not line:
                continue
            if _RUNNING_LINE.match(line) or _PAGE_NUMBER.match(line):
                continue
            lines.append(line)
            line_pages.append(number)
    return lines, line_pages


def _header_date(lines: list[str]) -> date | None:
    """Rule 2: the one date every heading line names, or None."""
    named: set[date | None] = set()
    for line in lines:
        match = _HEADING_LINE.match(line)
        if not match:
            continue
        text = re.sub(r"\s+", " ", match.group(1).replace(",", ", ")).strip().title()
        try:
            named.add(datetime.strptime(text, "%B %d, %Y").date())
        except ValueError:
            # A heading whose date is no date agrees with nothing.
            named.add(None)
    if len(named) == 1:
        return next(iter(named))
    return None


def _names(text: str) -> tuple[str, ...]:
    """Rule 4: a printed list of names, each exactly as printed."""
    text = text.strip()
    if text.endswith("."):
        text = text[:-1]
    if text.strip() in ("", "None"):
        return ()
    parts = re.split(r",|\band\b", text)
    return tuple(part.strip() for part in parts if part.strip())


def _opens_attendance(lines: list[str], i: int) -> bool:
    """Rule 3: whether line i opens an attendance block."""
    line = lines[i]
    if line.startswith("Present on Roll Call") or line == "Present:":
        return True
    return (
        line.startswith("Councilmembers:")
        and i + 1 < len(lines)
        and lines[i + 1].startswith("Present:")
    )


def _attendance_absent(lines: list[str], i: int) -> tuple[str, ...]:
    """Rule 3: the absent list of the attendance block that opens at line i."""
    for line in lines[i : i + _ATTENDANCE_REACH + 1]:
        match = _ABSENT_LINE.match(line)
        if match:
            return _names(match.group(1))
    return ()


def _is_section_heading(line: str) -> bool:
    """Rule 9: a line that heads a section of the meeting."""
    bare = line[:-1] if line.endswith((":", ".")) else line
    return bare in _SECTION_HEADINGS or bool(_SECTION_PATTERN.match(bare))


def _strip_final_period(text: str) -> str:
    text = text.strip()
    if text.endswith(".") and not text.endswith(("a.m.", "p.m.")):
        text = text[:-1]
    return text


def _declared_text(sentence: str) -> str:
    """Rule 6: the words of the declaration a page prints."""
    declared = _DECLARED_WORD.search(sentence)
    if declared:
        text = sentence[declared.end() :]
    else:
        set_the_date = _SET_THE_DATE.search(sentence)
        text = sentence[set_the_date.start() :] if set_the_date else sentence
    return _strip_final_period(text)


def _read_declaration(lines: list[str], start: int) -> tuple[str | None, int]:
    """Rule 6: (declared text, index of its last line), or (None, start - 1)
    when the lines after a vote block hold no declaration."""
    taken: list[str] = []
    i = start
    while i < len(lines) and len(taken) < _DECLARATION_REACH:
        if _AYES_LINE.match(lines[i]):
            break
        taken.append(lines[i])
        i += 1
        if " ".join(taken).endswith("."):
            break
    sentence = " ".join(taken)
    if taken and (_DECLARATION.search(sentence) or _MOTION_SENTENCE.match(sentence)):
        return _declared_text(sentence), start + len(taken) - 1
    return None, start - 1


def _motion_start(lines: list[str], ayes_at: int, after: int) -> int | None:
    """Rule 7: the index of the motion's first line, looking back from the
    `Ayes:` line and never past `after`, the last line of the vote before."""
    floor = max(after + 1, ayes_at - _MOTION_REACH)
    start = None
    for pattern in (_MOVED, _MOTION_WORD):
        for i in range(ayes_at - 1, floor - 1, -1):
            if pattern.search(lines[i]):
                start = i
                break
        if start is not None:
            break
    if start is None:
        return None
    if lines[start][:1].islower() and start - 1 > after:
        start -= 1
    return start


def _opening_sentence(
    lines: list[str], code_at: int, after: int
) -> tuple[str | None, str | None]:
    """Rule 9: (opening sentence, caption) of the item whose code line is at
    `code_at`, read from the lines before it and never past `after`."""
    first = max(after + 1, code_at - _OPENING_REACH)
    window = lines[first:code_at]
    offsets: list[int] = []
    joined = ""
    for line in window:
        if joined:
            joined += " "
        offsets.append(len(joined))
        joined += line
    matches = list(_OPENING.finditer(joined))
    if not matches:
        return None, None
    begin = matches[-1].start()
    period = joined.find(".", begin)
    sentence = joined[begin:] if period == -1 else joined[begin : period + 1]

    holder = max(k for k, offset in enumerate(offsets) if offset <= begin)
    parts = [window[holder][: begin - offsets[holder]]]
    k = holder - 1
    while k >= 0 and holder - k <= _CAPTION_REACH:
        above = window[k]
        if (
            any(ch.islower() for ch in above)
            or _is_section_heading(above)
            or _CODE_LINE.match(above)
        ):
            break
        parts.insert(0, above)
        k -= 1
    caption = " ".join(part.strip() for part in parts if part.strip())
    if caption.endswith("."):
        caption = caption[:-1].strip()
    return sentence, caption or None


def _result(
    declared: str | None, motion: str | None, ayes: int, nays: int
) -> tuple[str, str | None]:
    """Rule 10: (result, review reason). The result says whether the motion
    carried, which the declaration alone does not: "denied" follows a motion
    to deny that carried and a motion to adopt that lost."""
    if declared is None:
        return "unknown", "declaration_not_read"
    if _FAILED.search(declared):
        return "failed", None
    if _DENIED.search(declared):
        if motion and _MOVED_TO_DENY.search(motion):
            return "passed", None
        if ayes <= nays:
            return "failed", None
        return "unknown", "declaration_ambiguous"
    if ayes < nays:
        return "passed", "declaration_contradicts_count"
    return "passed", None


def read_minutes(pages: list[str]) -> MinutesReading:
    """Read the page texts of one minutes file (index 0 is page 1)."""
    lines, line_pages = _kept_lines(pages)
    votes: list[MinutesVote] = []

    absent_in_force: tuple[str, ...] = ()
    pending: tuple[str, str, str | None] | None = None  # code, kind, caption
    previous_end = -1  # last line of the vote before: its block and declaration
    scanned_to = -1  # last line already walked for attendance and items

    i = 0
    while i < len(lines):
        ayes_match = _AYES_LINE.match(lines[i])
        if not ayes_match:
            i += 1
            continue

        # Rules 3 and 9 over the lines since the vote before.
        for j in range(scanned_to + 1, i):
            line = lines[j]
            if _opens_attendance(lines, j):
                absent_in_force = _attendance_absent(lines, j)
            if _is_section_heading(line):
                pending = None
                continue
            if j > 0:
                before = lines[j - 1]
                if _NEW_ITEM.search(before + " " + line) and not _NEW_ITEM.search(before):
                    pending = None
            code_match = _CODE_LINE.match(line)
            if code_match:
                sentence, caption = _opening_sentence(lines, j, previous_end)
                if (
                    sentence is not None
                    and _HELD_OVER.search(sentence)
                    and "called up" not in sentence
                ):
                    pending = None
                else:
                    code = "-".join(code_match.group(2, 3, 4))
                    pending = (code, code_match.group(1), caption)

        # Rule 5: the block.
        ayes = _names(ayes_match.group(1))
        nays: tuple[str, ...] = ()
        abstain: tuple[str, ...] = ()
        seen_nays = seen_abstain = False
        block_end = i
        for j in range(i + 1, min(i + 1 + _BLOCK_REACH, len(lines))):
            line = lines[j]
            nays_match = _NAYS_LINE.match(line)
            abstain_match = _ABSTAIN_LINE.match(line)
            if nays_match and not seen_nays:
                nays = _names(nays_match.group(1))
                seen_nays = True
            elif abstain_match and not seen_abstain:
                abstain = _names(abstain_match.group(1))
                seen_abstain = True
            elif _ABSENT_LINE.match(line):
                pass
            else:
                break
            block_end = j

        # Rule 6: the declaration.
        declared, vote_end = _read_declaration(lines, block_end + 1)
        vote_end = max(vote_end, block_end)

        # Rule 7: the motion.
        motion_at = _motion_start(lines, i, previous_end)
        motion = " ".join(lines[motion_at:i]) if motion_at is not None else None

        # Rule 8: absent members.
        voted = set(ayes) | set(nays) | set(abstain)
        absent = tuple(name for name in absent_in_force if name not in voted)

        # Rule 9: the item this vote is on.
        code = kind = caption = None
        if pending is not None and not (motion and _PROCEDURAL.search(motion)):
            code, kind, caption = pending

        # Rule 10: the result.
        result, reason = _result(declared, motion, len(ayes), len(nays))

        raw_from = motion_at if motion_at is not None else i
        votes.append(
            MinutesVote(
                page=line_pages[i],
                ayes=ayes,
                nays=nays,
                abstain=abstain,
                absent=absent,
                motion_text=motion,
                declared_text=declared,
                result=result,
                needs_review=reason is not None,
                review_reason=reason,
                code=code,
                kind=kind,
                caption=caption,
                raw_text="\n".join(lines[raw_from : vote_end + 1]),
            )
        )

        previous_end = vote_end
        scanned_to = vote_end
        i = vote_end + 1

    return MinutesReading(header_date=_header_date(lines), votes=tuple(votes))
