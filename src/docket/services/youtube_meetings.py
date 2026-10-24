"""The council's YouTube channel as a meeting source: titles, grouping, and (from M4) the sync.

This module turns the channel's uploads (``docket.adapters.youtube.YouTubeVideo``)
into meeting candidates. A **candidate** is a video whose title carries a
meeting date and a meeting word. A **group** is the candidates of one date and
one body, folded into one ``Candidate`` with the longest video as its
recording: the council streams a meeting in parts (``Pt. 1``, ``Pt. 2``) and
sometimes posts short test streams under the same title before the real one.

The functions here are pure. The title shapes they accept are the ones in the
channel's inventory of 2026-10-24 (``tests/unit/test_youtube_titles.py``); a
new shape is a new test case and a regex change.

Plan: plans/active/youtube-council-channel.md (M1 the pure half; M4 ``sync_city``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from docket.adapters._helpers import Classification, classify_title
from docket.adapters.youtube import YouTubeVideo

MIN_RECORDING_S = 300
CREATE_AFTER_DAYS = 3
DAILY_WINDOW_DAYS = 30

_EARLIEST = date(2008, 1, 1)

# M.D.YY or M.D.YYYY with . or / separators, anywhere in the title, not part of
# a longer run of digits and separators.
_DATE_TOKEN = re.compile(r"(?<![\d./])(\d{1,2})[./](\d{1,2})[./](\d{4}|\d{2})(?![\d./])")
_PART = re.compile(r"\b(?:pt\.?|part)\s*(\d+)\b", re.IGNORECASE)
_MEETING_WORDS = re.compile(r"meeting|committee|council|hearing", re.IGNORECASE)
_REJECT_WORDS = re.compile(r"\b(?:highlights|recap|tease|test|edition)\b", re.IGNORECASE)
_EDGE_PUNCT = " \t-–—:;,.|/"


@dataclass(frozen=True)
class ParsedTitle:
    meeting_date: date
    clean_title: str
    part: int | None


@dataclass(frozen=True)
class Candidate:
    """One meeting as the channel recorded it: a date, a body, and its videos."""

    meeting_date: date
    clean_title: str
    classification: Classification
    primary: YouTubeVideo
    others: list[YouTubeVideo]

    @property
    def total_duration_s(self) -> int | None:
        """The summed duration of the primary and every part; None when any is unknown."""
        total = 0
        for video in (self.primary, *self.others):
            if video.duration_s is None:
                return None
            total += video.duration_s
        return total


def _find_date(title: str) -> tuple[re.Match, date] | None:
    m = _DATE_TOKEN.search(title)
    if not m:
        return None
    month, day, year = int(m.group(1)), int(m.group(2)), m.group(3)
    year_n = 2000 + int(year) if len(year) == 2 else int(year)
    try:
        return m, date(year_n, month, day)
    except ValueError:
        return None


def _tidy(text: str) -> str:
    return " ".join(text.split()).strip(_EDGE_PUNCT).strip()


def clean_title(title: str) -> str:
    """The title without its date token or part marker, edges and spaces tidied, ``&`` kept."""
    found = _find_date(title)
    text = title
    if found:
        m, _ = found
        text = text[: m.start()] + " " + text[m.end() :]
    text = _PART.sub(" ", text)
    return _tidy(text)


def parse_title(title: str, *, today: date | None = None) -> ParsedTitle | None:
    """Read a meeting date, a cleaned title, and a part number out of a channel title.

    Returns None for a title with no date token, a date before 2008 or after
    tomorrow, no meeting word, or a word that marks a non-meeting
    (highlights, recap, tease, test, edition).
    """
    found = _find_date(title)
    if not found:
        return None
    m, meeting_date = found
    today = today or date.today()
    if meeting_date < _EARLIEST or meeting_date > today + timedelta(days=1):
        return None
    rest = title[: m.start()] + " " + title[m.end() :]
    if not _MEETING_WORDS.search(rest) or _REJECT_WORDS.search(rest):
        return None
    part_m = _PART.search(rest)
    part = int(part_m.group(1)) if part_m else None
    return ParsedTitle(meeting_date, clean_title(title), part)


def body_key(clean: str) -> str:
    """A grouping key for a cleaned title: ``&`` and ``and`` alike, ``special called`` and ``joint`` ignored."""
    text = clean.lower().replace("&", " and ")
    text = re.sub(r"\bspecial\s+called\b", " ", text)
    text = re.sub(r"\bjoint\b", " ", text)
    return re.sub(r"[^a-z]", "", text)


def group_videos(videos: list[YouTubeVideo], *, today: date | None = None) -> list[Candidate]:
    """Fold finished meeting videos of at least ``MIN_RECORDING_S`` into one candidate per date and body.

    The longest video of a group is its primary recording; the rest are sorted
    by part number, then duration. Live and upcoming streams, videos of unknown
    or short duration, and non-meeting titles are dropped.
    """
    groups: dict[tuple[date, str], list[tuple[YouTubeVideo, ParsedTitle]]] = {}
    for video in videos:
        if video.broadcast != "none" or video.duration_s is None or video.duration_s < MIN_RECORDING_S:
            continue
        parsed = parse_title(video.title, today=today)
        if parsed is None:
            continue
        groups.setdefault((parsed.meeting_date, body_key(parsed.clean_title)), []).append((video, parsed))

    candidates = []
    for (meeting_date, _key), members in groups.items():
        members.sort(key=lambda vp: (-(vp[0].duration_s or 0), vp[0].video_id))
        primary, primary_parsed = members[0]
        rest = sorted(
            members[1:],
            key=lambda vp: (vp[1].part is None, vp[1].part or 0, vp[0].duration_s or 0, vp[0].video_id),
        )
        candidates.append(
            Candidate(
                meeting_date=meeting_date,
                clean_title=primary_parsed.clean_title,
                classification=classify_title(primary_parsed.clean_title),
                primary=primary,
                others=[v for v, _ in rest],
            )
        )
    candidates.sort(key=lambda c: (c.meeting_date, c.clean_title, c.primary.video_id))
    return candidates
