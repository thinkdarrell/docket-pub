"""The council's YouTube channel as a meeting source: titles, grouping, and (from M4) the sync.

This module turns the channel's uploads (``docket.adapters.youtube.YouTubeVideo``)
into meeting candidates. A **candidate** is a video whose title carries a
meeting date and a meeting word. A **group** is the candidates of one date and
one body, folded into one ``Candidate`` with the longest video as its
recording: the council streams a meeting in parts (``Pt. 1``, ``Pt. 2``) and
sometimes posts short test streams under the same title before the real one.

The title functions are pure; ``sync_city`` reads and writes the database. The title shapes they accept are the ones in the
channel's inventory of 2026-10-24 (``tests/unit/test_youtube_titles.py``); a
new shape is a new test case and a regex change.

Plan: plans/active/youtube-council-channel.md (M1 the pure half; M4 ``sync_city``).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import psycopg2.extras

from docket.adapters._helpers import Classification, classify_title
from docket.adapters.youtube import YouTubeClient, YouTubeVideo
from docket.db import db
from docket.services import meeting_types

log = logging.getLogger(__name__)

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
    return ParsedTitle(meeting_date, clean_title(title), _part_of(rest))


def _part_of(text: str) -> int | None:
    part_m = _PART.search(text)
    return int(part_m.group(1)) if part_m else None


def part_number(title: str) -> int | None:
    """The ``Pt. N`` / ``Part N`` number of a channel title, or None; the
    date token is ignored, and nothing else about the title is checked
    (the meeting page labels a stored recording with it)."""
    found = _find_date(title)
    if found:
        m, _ = found
        title = title[: m.start()] + " " + title[m.end() :]
    return _part_of(title)


def body_key(clean: str) -> str:
    """A grouping key for a cleaned title: ``&`` and ``and`` alike, ``special called`` and ``joint`` ignored."""
    text = clean.lower().replace("&", " and ")
    text = re.sub(r"\bspecial\s+called\b", " ", text)
    text = re.sub(r"\bjoint\b", " ", text)
    return re.sub(r"[^a-z]", "", text)


def _looks_like_a_meeting(title: str) -> bool:
    return bool(_MEETING_WORDS.search(title)) and not _REJECT_WORDS.search(title)


def group_videos(
    videos: list[YouTubeVideo],
    *,
    today: date | None = None,
    dropped: list[tuple[YouTubeVideo, str]] | None = None,
) -> list[Candidate]:
    """Fold finished meeting videos of at least ``MIN_RECORDING_S`` into one candidate per date and body.

    The longest video of a group is its primary recording; the rest are sorted
    by part number, then duration. Live and upcoming streams, videos of unknown
    or short duration, and non-meeting titles are dropped. A finished upload
    whose title looks like a meeting but has no readable date, or whose
    duration is unknown, is appended to ``dropped`` with that reason, so the
    caller can report what it left out.
    """
    groups: dict[tuple[date, str], list[tuple[YouTubeVideo, ParsedTitle]]] = {}
    for video in videos:
        if video.broadcast != "none":
            continue
        if video.duration_s is None:
            if dropped is not None and _looks_like_a_meeting(video.title):
                dropped.append((video, "no known duration"))
            continue
        if video.duration_s < MIN_RECORDING_S:
            continue
        parsed = parse_title(video.title, today=today)
        if parsed is None:
            if dropped is not None and _looks_like_a_meeting(video.title) and (
                (found := _find_date(video.title)) is None
                or not _EARLIEST <= found[1] <= (today or date.today()) + timedelta(days=1)
            ):
                dropped.append((video, "no readable date"))
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


# --- the sync (M4) -------------------------------------------------------------
#
# ``sync_city`` matches each group to the city's meeting rows of its date:
#
#   council group     -> the day's council row (duration pair, else most items)
#   committee group   -> the day's one Granicus candidate row when there is one
#                        of each; otherwise pairs by duration, nearest first
#   no match          -> a ``yt-<video id>`` row, once the primary is
#                        CREATE_AFTER_DAYS old; until then ``defer``
#   any candidate row of the day without a stored duration -> ``no_duration``
#
# and then absorbs young ``yt-`` rows into Granicus clips that arrived later.
# Nothing here writes a classification: ``meeting_types.resolve_and_store``
# runs over every touched row and its ``video`` rung names them.

ACTIONS: tuple[str, ...] = ("attach", "create", "defer", "no_duration", "skip_seen", "absorb", "ambiguous", "unparsed")

_CITY_TZ = ZoneInfo("America/Chicago")
_WATCH_URL = "https://www.youtube.com/watch?v={}"


@dataclass
class SyncReport:
    """What one ``sync_city`` run decided, in order, with counts per action."""

    decisions: list[tuple[date, str, str]] = field(default_factory=list)
    ambiguous_days: list[date] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=lambda: {a: 0 for a in ACTIONS})
    touched_ids: list[int] = field(default_factory=list)

    def add(self, meeting_date: date, action: str, detail: str) -> None:
        self.decisions.append((meeting_date, action, detail))
        self.counts[action] = self.counts.get(action, 0) + 1

    def touch(self, meeting_id: int | None) -> None:
        if meeting_id is not None and meeting_id not in self.touched_ids:
            self.touched_ids.append(meeting_id)


def pairs(a: int | None, b: int | None) -> bool:
    """Two recordings of one meeting: within 5 minutes or a quarter of the longer, both known."""
    if a is None or b is None:
        return False
    return abs(a - b) <= max(300, 0.25 * max(a, b))


def _pair_by_duration(groups: list, rows: list[dict], duration) -> tuple[list[tuple], list, list[dict]]:
    """Greedy pairs, nearest difference first, each side used once; returns (pairs, unpaired groups, unpaired rows)."""
    options = []
    for gi, g in enumerate(groups):
        for ri, r in enumerate(rows):
            if pairs(duration(g), r["duration_s"]):
                options.append((abs(duration(g) - r["duration_s"]), gi, ri))
    options.sort()
    used_g: set[int] = set()
    used_r: set[int] = set()
    paired = []
    for _diff, gi, ri in options:
        if gi in used_g or ri in used_r:
            continue
        used_g.add(gi)
        used_r.add(ri)
        paired.append((groups[gi], rows[ri]))
    return (
        paired,
        [g for i, g in enumerate(groups) if i not in used_g],
        [r for i, r in enumerate(rows) if i not in used_r],
    )


_MUNICIPALITY_SQL = "SELECT id, metadata FROM municipalities WHERE slug = %s"

_DAY_ROWS_SQL = """
    SELECT m.id, m.external_id, m.title, m.meeting_type, m.body_name, m.minutes_url,
           m.duration_s, m.is_hidden, m.created_at,
           (SELECT count(*) FROM agenda_items a WHERE a.meeting_id = m.id) AS item_count,
           EXISTS (SELECT 1 FROM meeting_videos v
                    WHERE v.meeting_id = m.id AND v.provider = 'youtube') AS has_youtube
      FROM meetings m
     WHERE m.municipality_id = %s AND m.meeting_date = %s
     ORDER BY m.id
"""

_SEEN_SQL = "SELECT video_id, meeting_id FROM meeting_videos WHERE provider = 'youtube' AND video_id = ANY(%s)"

_INSERT_VIDEO_SQL = """
    INSERT INTO meeting_videos (meeting_id, provider, video_id, url, title, clean_title,
                                duration_s, started_at, is_primary)
    VALUES (%s, 'youtube', %s, %s, %s, %s, %s, %s,
            %s AND NOT EXISTS (SELECT 1 FROM meeting_videos
                                WHERE meeting_id = %s AND provider = 'youtube' AND is_primary))
    ON CONFLICT (provider, video_id) DO NOTHING
"""

_INSERT_MEETING_SQL = """
    INSERT INTO meetings (municipality_id, external_id, title, meeting_date,
                          meeting_type, session_kind, body_name, type_source,
                          video_url, source_url, duration_s, start_time)
    VALUES (%s, %s, %s, %s, %s, %s, %s, 'title', %s, %s, %s, %s)
    ON CONFLICT (municipality_id, external_id) DO NOTHING
    RETURNING id
"""

_YOUNG_YT_ROWS_SQL = """
    SELECT m.id, m.external_id, m.meeting_date, m.meeting_type, m.duration_s, m.created_at
      FROM meetings m
     WHERE m.municipality_id = %s
       AND m.external_id LIKE 'yt-%%'
       AND m.meeting_date >= %s AND m.meeting_date <= %s
       AND NOT EXISTS (SELECT 1 FROM agenda_items a WHERE a.meeting_id = m.id)
       AND EXISTS (SELECT 1 FROM meeting_videos v WHERE v.meeting_id = m.id AND v.provider = 'youtube')
     ORDER BY m.meeting_date, m.id
"""


def _is_granicus(row: dict) -> bool:
    return not (row["external_id"] or "").startswith("yt-")


def _committee_candidates(rows: list[dict]) -> list[dict]:
    """The day's Granicus rows a committee recording may belong to, among those holding no YouTube video yet.

    A committee-typed row with no body name, or a council-typed row with no
    agenda items and no minutes link while another council row that day has
    agenda items (a committee clip the clerk titled "Regular City Council Meeting").
    """
    out = []
    for r in rows:
        if not _is_granicus(r) or r["has_youtube"]:
            continue
        if r["meeting_type"] == "committee" and not r["body_name"]:
            out.append(r)
        elif (
            r["meeting_type"] == "council"
            and int(r["item_count"] or 0) == 0
            and not r["minutes_url"]
            and any(o["id"] != r["id"] and o["meeting_type"] == "council" and int(o["item_count"] or 0) > 0
                    for o in rows)
        ):
            out.append(r)
    return out


def _videos_of(group: Candidate) -> list[YouTubeVideo]:
    return [group.primary, *group.others]


def _describe(group: Candidate) -> str:
    parts = f" (+{len(group.others)} part{'s' if len(group.others) != 1 else ''})" if group.others else ""
    return f"{group.primary.video_id}{parts} {group.clean_title!r} {group.total_duration_s}s"


def _row_label(row: dict) -> str:
    return f"meeting {row['id']} ({row['external_id']}, {row['duration_s']}s)"


def _start_time(started_at: datetime | None):
    if started_at is None:
        return None
    return started_at.astimezone(_CITY_TZ).time().replace(microsecond=0)


class _Run:
    """One city's sync: the cursor, the report, and what this run has already claimed."""

    def __init__(self, cur, municipality_id: int, today: date, dry_run: bool, report: SyncReport):
        self.cur = cur
        self.municipality_id = municipality_id
        self.today = today
        self.dry_run = dry_run
        self.report = report
        self.seen: dict[str, int | None] = {}
        self.claimed: set[int] = set()  # rows attached to in this run (also in a dry run)
        self.created: set[str] = set()  # external ids created in this run

    # --- writes ---------------------------------------------------------------

    def _insert_videos(self, meeting_id: int, videos: list[YouTubeVideo], primary: YouTubeVideo | None) -> None:
        for v in videos:
            self.seen[v.video_id] = meeting_id
            if self.dry_run:
                continue
            self.cur.execute(
                _INSERT_VIDEO_SQL,
                (meeting_id, v.video_id, _WATCH_URL.format(v.video_id), v.title, clean_title(v.title),
                 v.duration_s, v.started_at, primary is not None and v.video_id == primary.video_id, meeting_id),
            )

    def attach(self, group: Candidate, row: dict, note: str = "") -> None:
        self._insert_videos(row["id"], _videos_of(group), group.primary)
        self.claimed.add(row["id"])
        self.report.touch(row["id"])
        self.report.add(group.meeting_date, "attach", f"{_describe(group)} -> {_row_label(row)}{note}")

    def create_or_defer(self, group: Candidate, blocked: bool) -> None:
        if blocked:
            self.report.add(group.meeting_date, "no_duration",
                            f"{_describe(group)}: a candidate clip that day has no stored duration")
            return
        if group.primary.published_at.date() > self.today - timedelta(days=CREATE_AFTER_DAYS):
            self.report.add(group.meeting_date, "defer",
                            f"{_describe(group)} published {group.primary.published_at:%Y-%m-%d}")
            return
        external_id = f"yt-{group.primary.video_id}"
        c = group.classification
        meeting_id = None
        if not self.dry_run:
            url = _WATCH_URL.format(group.primary.video_id)
            self.cur.execute(
                _INSERT_MEETING_SQL,
                (self.municipality_id, external_id, group.clean_title, group.meeting_date,
                 c.meeting_type, c.session_kind, c.body_name, url, url,
                 group.total_duration_s, _start_time(group.primary.started_at)),
            )
            got = self.cur.fetchone()
            if got is None:
                self.cur.execute(
                    "SELECT id FROM meetings WHERE municipality_id = %s AND external_id = %s",
                    (self.municipality_id, external_id),
                )
                got = self.cur.fetchone()
            meeting_id = got["id"]
            self._insert_videos(meeting_id, _videos_of(group), group.primary)
        else:
            for v in _videos_of(group):
                self.seen[v.video_id] = None
        self.created.add(external_id)
        self.report.touch(meeting_id)
        self.report.add(group.meeting_date, "create",
                        f"{external_id} {c.meeting_type}/{c.session_kind} {c.body_name!r} {group.total_duration_s}s")

    # --- one day ----------------------------------------------------------------

    def day(self, meeting_date: date, groups: list[Candidate]) -> None:
        fresh: list[Candidate] = []
        for g in groups:
            ids = [v.video_id for v in _videos_of(g)]
            held = [self.seen[i] for i in ids if i in self.seen]
            if not held:
                fresh.append(g)
                continue
            unseen = [v for v in _videos_of(g) if v.video_id not in self.seen]
            if not unseen or held[0] is None:
                self.report.add(meeting_date, "skip_seen", f"{_describe(g)} already held by meeting {held[0]}")
                continue
            # A later part of a group already attached: it joins the same row, never as primary.
            self._insert_videos(held[0], unseen, None)
            self.report.touch(held[0])
            self.report.add(meeting_date, "attach",
                            f"{', '.join(v.video_id for v in unseen)} (new parts of {g.clean_title!r}) -> meeting {held[0]}")
        if not fresh:
            return

        self.cur.execute(_DAY_ROWS_SQL, (self.municipality_id, meeting_date))
        rows = [dict(r) for r in self.cur.fetchall()]
        candidates = [r for r in _committee_candidates(rows) if r["id"] not in self.claimed]
        blocked = any(r["duration_s"] is None for r in candidates)

        council_groups = [g for g in fresh if g.classification.meeting_type == "council"]
        committee_groups = [g for g in fresh if g.classification.meeting_type != "council"]

        council_rows = [r for r in rows if r["meeting_type"] == "council" and r not in candidates]
        for g in council_groups:
            if not council_rows:
                self.create_or_defer(g, blocked)
                continue
            if len(council_rows) == 1:
                self.attach(g, council_rows[0])
                continue
            matched = [r for r in council_rows if pairs(g.total_duration_s, r["duration_s"])]
            if matched:
                row = min(matched, key=lambda r: (abs(r["duration_s"] - g.total_duration_s), r["id"]))
                how = "duration"
            else:
                row = max(council_rows, key=lambda r: (int(r["item_count"] or 0), -r["id"]))
                how = "most agenda items"
            log.info("youtube %s: council recording %s chose %s by %s among %d council rows",
                     meeting_date, g.primary.video_id, row["id"], how, len(council_rows))
            self.attach(g, row, f" by {how}")

        if not committee_groups:
            return
        if blocked:
            for g in committee_groups:
                self.create_or_defer(g, True)
            return
        if len(candidates) == 1 and len(committee_groups) == 1:
            self.attach(committee_groups[0], candidates[0])
            return
        if not candidates:
            for g in committee_groups:
                self.create_or_defer(g, False)
            return
        paired, lone_groups, lone_rows = _pair_by_duration(committee_groups, candidates,
                                                           lambda g: g.total_duration_s)
        for g, r in paired:
            self.attach(g, r, " by duration")
        for g in lone_groups:
            self.create_or_defer(g, False)
        if lone_groups or lone_rows:
            clips = ", ".join(f"{r['external_id']} ({r['duration_s']}s)" for r in lone_rows) or "none"
            videos = ", ".join(g.primary.video_id for g in lone_groups) or "none"
            log.warning("youtube %s: ambiguous committee day; unpaired clips: %s; unpaired recordings: %s",
                        meeting_date, clips, videos)
            self.report.ambiguous_days.append(meeting_date)
            self.report.add(meeting_date, "ambiguous", f"unpaired clips: {clips}; unpaired recordings: {videos}")

    # --- absorption ---------------------------------------------------------------

    def absorb_all(self) -> None:
        self.cur.execute(
            _YOUNG_YT_ROWS_SQL,
            (self.municipality_id, self.today - timedelta(days=DAILY_WINDOW_DAYS), self.today),
        )
        young = [dict(r) for r in self.cur.fetchall() if r["external_id"] not in self.created]
        by_day: dict[date, list[dict]] = {}
        for r in young:
            by_day.setdefault(r["meeting_date"], []).append(r)
        for meeting_date, yts in sorted(by_day.items()):
            self.cur.execute(_DAY_ROWS_SQL, (self.municipality_id, meeting_date))
            rows = [dict(r) for r in self.cur.fetchall()]
            committee = [r for r in _committee_candidates(rows) if r["id"] not in self.claimed]
            council = [
                r for r in rows
                if _is_granicus(r) and r["meeting_type"] == "council" and not r["has_youtube"]
                and r["id"] not in self.claimed and r not in committee
            ]
            for kind_yts, cands in (
                ([y for y in yts if y["meeting_type"] != "council"], committee),
                ([y for y in yts if y["meeting_type"] == "council"], council),
            ):
                # Only a clip that arrived after a yt- row may absorb it: a clip
                # that was already there when the row was created is one the
                # group stage declined (an unsettled day creates rather than merges).
                cands = [c for c in cands if any(c["created_at"] > y["created_at"] for y in kind_yts)]
                if not kind_yts or not cands:
                    continue
                if any(c["duration_s"] is None for c in cands):
                    log.info("youtube %s: absorption waits; a candidate clip has no stored duration", meeting_date)
                    continue
                if len(kind_yts) == 1 and len(cands) == 1:
                    matches = [(kind_yts[0], cands[0])]
                else:
                    matches, _, _ = _pair_by_duration(kind_yts, cands, lambda y: y["duration_s"])
                for yt, row in matches:
                    if row["created_at"] > yt["created_at"]:
                        self.absorb(meeting_date, yt, row)

    def absorb(self, meeting_date: date, yt: dict, row: dict) -> None:
        self.claimed.add(row["id"])
        outcome = "deleted"
        if not self.dry_run:
            self.cur.execute(
                "UPDATE meeting_videos SET meeting_id = %s WHERE meeting_id = %s AND provider = 'youtube'",
                (row["id"], yt["id"]),
            )
            self.cur.execute("SELECT 1 FROM transcripts WHERE meeting_id = %s", (yt["id"],))
            if self.cur.fetchone():
                self.cur.execute("UPDATE meetings SET is_hidden = TRUE, hidden_at = now() WHERE id = %s", (yt["id"],))
                outcome = "hidden (it has a transcript)"
            else:
                self.cur.execute("DELETE FROM meetings WHERE id = %s", (yt["id"],))
        log.warning("youtube %s: absorbed meeting %s (%s) into meeting %s (%s); the yt- row is %s",
                    meeting_date, yt["id"], yt["external_id"], row["id"], row["external_id"], outcome)
        self.report.touch(row["id"])
        self.report.add(meeting_date, "absorb",
                        f"meeting {yt['id']} ({yt['external_id']}) -> {_row_label(row)}; yt- row {outcome}")


def sync_city(
    slug: str,
    *,
    client: YouTubeClient | None,
    since: date | None,
    today: date,
    dry_run: bool = False,
) -> SyncReport:
    """Match the city's YouTube recordings to its meeting rows; write unless ``dry_run``.

    ``since=None`` reads the uploads published in the last ``DAILY_WINDOW_DAYS``
    days (the daily task); a date reads everything published since then (the
    backfill). ``client=None`` (no ``YOUTUBE_API_KEY``) or a city without
    ``youtube_channel_id`` returns an empty report with a WARNING. The writes
    are one transaction; the ladder then runs over every touched row.
    """
    report = SyncReport()
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(_MUNICIPALITY_SQL, (slug,))
        municipality = cur.fetchone()
    if municipality is None:
        raise ValueError(f"unknown city slug: {slug}")
    metadata = municipality["metadata"] or {}
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    channel_id = metadata.get("youtube_channel_id")
    if not channel_id:
        log.warning("youtube %s: no youtube_channel_id in the city's metadata; nothing read", slug)
        return report
    if client is None:
        log.warning("youtube %s: YOUTUBE_API_KEY is not set; nothing read", slug)
        return report

    if channel_id.startswith("UC"):
        playlist_id = "UU" + channel_id[2:]
    else:
        playlist_id = client.uploads_playlist_id(metadata.get("youtube_channel") or channel_id)
    cutoff_day = today - timedelta(days=DAILY_WINDOW_DAYS) if since is None else since
    published_after = datetime.combine(cutoff_day, time.min, tzinfo=timezone.utc)
    videos = client.fill_details(client.list_uploads(playlist_id, published_after=published_after))
    dropped: list[tuple[YouTubeVideo, str]] = []
    groups = group_videos(videos, today=today, dropped=dropped)
    for video, reason in dropped:
        log.info("youtube %s: left out %s %r: %s", slug, video.video_id, video.title, reason)
        report.add(video.published_at.date(), "unparsed", f"{video.video_id} {video.title!r}: {reason}")

    by_day: dict[date, list[Candidate]] = {}
    for g in groups:
        by_day.setdefault(g.meeting_date, []).append(g)

    municipality_id = int(municipality["id"])
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        run = _Run(cur, municipality_id, today, dry_run, report)
        all_ids = [v.video_id for g in groups for v in _videos_of(g)]
        if all_ids:
            cur.execute(_SEEN_SQL, (all_ids,))
            run.seen = {r["video_id"]: r["meeting_id"] for r in cur.fetchall()}
        for meeting_date in sorted(by_day):
            run.day(meeting_date, by_day[meeting_date])
        run.absorb_all()
        if dry_run:
            conn.rollback()

    if not dry_run and report.touched_ids:
        meeting_types.resolve_and_store(municipality_id, report.touched_ids)
    log.info("youtube %s: %s%s", slug, ", ".join(f"{a}={n}" for a, n in report.counts.items()),
             " (dry run)" if dry_run else "")
    return report
