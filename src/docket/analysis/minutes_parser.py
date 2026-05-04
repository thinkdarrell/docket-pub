"""Parse Birmingham council meeting minutes PDFs for attendance and votes.

Birmingham minutes follow a consistent format:
- Roll call near the top lists Present/Absent members
- Vote records appear as "Ayes: Name1, Name2 / Nays: None" blocks
- Resolution/ordinance numbers appear before each vote
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field

import pdfplumber
import requests

logger = logging.getLogger(__name__)


PRE_VOTE_WINDOW = 1500
POST_VOTE_WINDOW = 200

CONSENT_BLOCK_PHRASES = (
    "the resolutions and ordinances introduced as consent agenda matters",
    "consent agenda matters were read by the city clerk",
    "all items on the consent agenda",
    "items on consent",
)


def _contains_consent_phrase(text: str) -> bool:
    """True if the text contains any canonical consent-block phrase."""
    lowered = text.lower()
    return any(phrase in lowered for phrase in CONSENT_BLOCK_PHRASES)


@dataclass
class AttendanceRecord:
    """Roll call attendance for a meeting."""

    present: list[str]
    absent: list[str]
    meeting_date: str | None = None


@dataclass
class ParsedVote:
    """A single vote extracted from minutes text."""

    ayes: list[str]
    nays: list[str]
    abstentions: list[str]
    result: str  # 'passed' | 'failed' | 'tabled'
    resolution_number: str | None = None
    context: str = ""        # full pre-vote window (was: trailing 200 chars)
    raw_text: str = ""       # full pre + vote block + post window
    is_likely_consent: bool = False


@dataclass
class MinutesParseResult:
    """Full parse result from a minutes PDF."""

    attendance: list[AttendanceRecord]
    votes: list[ParsedVote]
    full_text: str = ""
    errors: list[str] = field(default_factory=list)


def download_minutes_pdf(url: str) -> bytes | None:
    """Download a minutes PDF from a URL (follows redirects)."""
    try:
        resp = requests.get(url, timeout=30, allow_redirects=True)
        resp.raise_for_status()
        if not resp.content[:5] == b"%PDF-":
            logger.warning("URL did not return a PDF: %s", url)
            return None
        return resp.content
    except requests.RequestException as e:
        logger.error("Failed to download minutes from %s: %s", url, e)
        return None


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract all text from a PDF."""
    pages = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    return "\n".join(pages)


def parse_minutes(text: str) -> MinutesParseResult:
    """Parse attendance and votes from Birmingham minutes text."""
    errors: list[str] = []
    attendance = _parse_attendance(text)
    votes = _parse_votes(text)

    return MinutesParseResult(
        attendance=attendance,
        votes=votes,
        full_text=text,
        errors=errors,
    )


# --- Attendance parsing -------------------------------------------------------

# Match "Present on Roll Call:" block followed by names, then optionally "Absent:"
_ROLL_CALL_RE = re.compile(
    r"Present\s+on\s+Roll\s+Call:\s*"
    r"(?:Council\s+President\s+)?"
    r"(.*?)"
    r"(?:Absent:\s*(.*?))?"
    r"(?:\n\n|\nThe\s|\nPre-Council|\nCouncilmember\s+\w+\s+arrived)",
    re.DOTALL | re.IGNORECASE,
)


def _parse_attendance(text: str) -> list[AttendanceRecord]:
    """Extract roll call attendance records from minutes text."""
    records = []

    for match in _ROLL_CALL_RE.finditer(text):
        present_raw = match.group(1)
        absent_raw = match.group(2) or ""

        present = _extract_names(present_raw)
        absent = _extract_names(absent_raw)

        if present:
            records.append(AttendanceRecord(present=present, absent=absent))

    return records


def _extract_names(text: str) -> list[str]:
    """Extract council member last names from a block of text.

    Handles formats like:
    - "Council President Alexander"
    - "Councilmembers Gunn, Smith, Vasa"
    - "Councilmembers Gunn\n Smith\n Vasa"
    - "O'Quinn" (names with apostrophes)
    """
    # Remove role prefixes
    cleaned = re.sub(
        r"Council\s*(?:President|member|members)\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Remove parenthetical notes like "(Arrived as herein indicated)"
    cleaned = re.sub(r"\([^)]*\)", "", cleaned)

    # Split on commas and newlines
    parts = re.split(r"[,\n]+", cleaned)

    names = []
    for part in parts:
        name = part.strip()
        # Valid last name: starts with uppercase letter, may contain apostrophe
        if name and re.match(r"^[A-Z][A-Za-z'\u2019\u2018'-]+$", name):
            names.append(name)

    return names


# --- Vote parsing -------------------------------------------------------------

# Match "Ayes: name1, name2\nNays: ..." blocks
_VOTE_BLOCK_RE = re.compile(
    r"(?:the\s+vote\s+was\s+as\s+follows|upon\s+the\s+roll\s+being\s+called)"
    r"[:\s]*\n?"
    r"\s*Ayes?:\s*(.+?)\n"
    r"\s*Nays?:\s*(.+?)\n"
    r"(?:\s*Abstain(?:ing|ed)?:\s*(.+?)\n)?",
    re.DOTALL | re.IGNORECASE,
)

# Simpler fallback: just Ayes/Nays without the preamble
_AYES_NAYS_RE = re.compile(
    r"Ayes?:\s*(.+?)\n"
    r"\s*Nays?:\s*(.+?)\n"
    r"(?:\s*Abstain(?:ing|ed)?:\s*(.+?)\n)?",
    re.IGNORECASE,
)

# Resolution/ordinance number before a vote
_RESOLUTION_RE = re.compile(
    r"(?:RESOLUTION|ORDINANCE)\s+(?:NO\.\s*)?(\d[\d-]*)",
    re.IGNORECASE,
)


def _parse_votes(text: str) -> list[ParsedVote]:
    """Extract all vote records from minutes text."""
    votes = []
    seen_positions: set[int] = set()

    # Try the full pattern first (with preamble)
    for match in _VOTE_BLOCK_RE.finditer(text):
        seen_positions.add(match.start())
        vote = _build_vote(text, match)
        if vote:
            votes.append(vote)

    # Fallback: bare Ayes/Nays blocks not already captured
    for match in _AYES_NAYS_RE.finditer(text):
        # Skip if we already captured this from the full pattern
        if any(abs(match.start() - pos) < 50 for pos in seen_positions):
            continue
        seen_positions.add(match.start())
        vote = _build_vote(text, match)
        if vote:
            votes.append(vote)

    return votes


def _build_vote(text: str, match: re.Match) -> ParsedVote | None:
    ayes_raw = match.group(1).strip().rstrip(",")
    nays_raw = match.group(2).strip().rstrip(",")
    abstain_raw = (match.group(3) or "").strip().rstrip(",")

    ayes = _parse_vote_names(ayes_raw)
    nays = _parse_vote_names(nays_raw)
    abstentions = _parse_vote_names(abstain_raw)

    if not ayes and not nays:
        return None

    if len(ayes) > len(nays):
        result = "passed"
    elif len(nays) > len(ayes):
        result = "failed"
    else:
        result = "passed"  # ties go to passed in Birmingham (president breaks)

    pre_start = max(0, match.start() - PRE_VOTE_WINDOW)
    post_end = min(len(text), match.end() + POST_VOTE_WINDOW)
    context = text[pre_start:match.start()].strip()
    raw_text = text[pre_start:post_end].strip()

    res_matches = _RESOLUTION_RE.findall(context)
    resolution_number = res_matches[-1] if res_matches else None

    return ParsedVote(
        ayes=ayes,
        nays=nays,
        abstentions=abstentions,
        result=result,
        resolution_number=resolution_number,
        context=context,
        raw_text=raw_text,
        is_likely_consent=_contains_consent_phrase(raw_text),
    )


def _parse_vote_names(raw: str) -> list[str]:
    """Parse names from a vote line like 'Gunn, Smith, Vasa, Alexander'."""
    if not raw or raw.strip().lower() == "none":
        return []

    parts = re.split(r"[,\s]+", raw)
    names = []
    for part in parts:
        name = part.strip().rstrip(",.")
        if name and re.match(r"^[A-Z][A-Za-z'\u2019\u2018'-]+$", name):
            names.append(name)
    return names
