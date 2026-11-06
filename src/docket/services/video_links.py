"""Timed video links: which site a link into a meeting's video opens, and where.

Every time the database stores for a Granicus meeting is on the Granicus
clock, seconds from the start of the clip: an agenda item's cue point
(``agenda_items.video_timestamp_seconds``), a vote read off the video, a
transcript segment. This module turns "this meeting, this second, this
chapter id" into the link a reader should get, at the moment the link is
built; nothing is stored converted.

Two sites can be opened.

Granicus. The player page (``MediaPlayer.php``) ignores HTML5-native
``#t=NNN`` fragments and every other way of naming a time. It can only jump
to a chapter: ``&meta_id=N``, where N is the ``id`` of one of the player's
cue points. The Granicus adapter stores those ids as
``agenda_items.external_id`` (granicus.py builds RawAgendaItem with
``external_id=meta_id``). :func:`chapter_url` builds that link.

YouTube. The council streams the same meetings to YouTube, whose player
opens at any second (``&t=Ns``). A recording attached to a Granicus meeting
(``meeting_videos``) does not start when the clip does, so it is used only
when the transcriber has measured where it sits on the clip's clock
(``meeting_video_alignments``, migration 042): the measurement passed, was
made by a method version this module trusts, was made against the clip the
meeting has now, and covers the second. The offset is Granicus seconds
minus YouTube seconds, so a moment at Granicus second g is at YouTube second
g minus the offset. Everything else falls back to the Granicus chapter.

A consent item links to the start of the consent agenda: the clerk reads the
consent items out in one quick run, so their own cue points land seconds
apart inside that reading. :func:`consent_block` finds the run and
:func:`item_moment` applies the rule.

The functions above the "Database reads" line are pure. The three below it
read through :func:`docket.db.db_cursor` and write nothing.

Plan: plans/completed/video-links-land-on-the-moment.md (M4).
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import parse_qs, parse_qsl, quote, urlencode, urlparse, urlunparse

from docket.db import db_cursor

# The lowest method version (``meeting_video_alignments.method_version``,
# written from the transcriber's ``ALIGN_METHOD_VERSION``) the site trusts.
# A floor, not an equality: a later method's measurement is used as it is.
# 2, because method 1 covered the outer parts of a recording's first and last
# windows without checking them (decision 0081).
MIN_METHOD_VERSION = 2

# The consent block: the largest run of consent cue points whose neighbours
# are at most CONSENT_GAP_S apart, when it holds at least CONSENT_MIN_ITEMS.
CONSENT_GAP_S = 120.0
CONSENT_MIN_ITEMS = 3

_YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"})
_YOUTUBE_SHORT_HOSTS = frozenset({"youtu.be", "www.youtu.be"})
_YOUTUBE_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")


@dataclass(frozen=True)
class Recording:
    """One YouTube recording of a Granicus meeting whose measurement passed."""

    video_id: str
    offset_s: float   # Granicus seconds minus YouTube seconds
    start_s: float    # the stretch of the Granicus clock it covers: start included,
    end_s: float      # end excluded


@dataclass(frozen=True)
class ConsentBlock:
    """The reading of the consent agenda, on the meeting's own clock."""

    start_s: float
    end_s: float
    chapter_id: str | None


@dataclass(frozen=True)
class MeetingVideo:
    """What a link into one meeting's video is built from."""

    video_url: str | None
    recordings: tuple[Recording, ...] = ()
    consent: ConsentBlock | None = None


@dataclass(frozen=True)
class VideoLink:
    """A finished link: where it goes and what it may say about itself."""

    url: str
    site: str             # 'youtube', 'granicus', or 'other'
    label: str | None     # 'YouTube', 'Granicus', or None
    seconds: int | None   # the second the link opens at on YouTube; None otherwise
    timed: bool           # True when the link lands on a second or a chapter

    @property
    def phrase(self) -> str:
        """Name the site, and say "chapter" only when the link carries one."""
        if self.site == "youtube":
            return "video on YouTube"
        if self.site == "granicus":
            return "video chapter on Granicus" if self.timed else "video on Granicus"
        return "video"


def chapter_url(video_url: str | None, meta_id: object) -> str | None:
    """Return ``video_url`` deep-linked to a specific chapter, when supported.

    Falls back to ``video_url`` unchanged when the player doesn't support
    deep links or when ``meta_id`` is missing / non-numeric. Returns
    ``None`` when ``video_url`` is None.

    Currently only Granicus ``MediaPlayer.php`` URLs are recognized; the
    rendered URL appends ``meta_id`` as a query param so Granicus's JS
    player seeks to the matching cuepoint on load.
    """
    if not video_url:
        return None
    if meta_id is None:
        return video_url
    meta_id_str = str(meta_id)
    if not meta_id_str.isdigit():
        return video_url
    if "MediaPlayer.php" not in video_url:
        return video_url

    parsed = urlparse(video_url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params["meta_id"] = meta_id_str
    return urlunparse(parsed._replace(query=urlencode(params), fragment=""))


def _is_chapter_id(meta_id: object) -> bool:
    """True for an id :func:`chapter_url` will put in a link (the same test it makes)."""
    return meta_id is not None and str(meta_id).isdigit()


def youtube_id(url: str | None) -> str | None:
    """Return the video id of a ``watch?v=<id>`` or ``youtu.be/<id>`` address, else None."""
    if not url:
        return None
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    if host in _YOUTUBE_HOSTS and parsed.path.rstrip("/") == "/watch":
        candidate = (parse_qs(parsed.query).get("v") or [""])[0]
    elif host in _YOUTUBE_SHORT_HOSTS:
        candidate = parsed.path.strip("/")
    else:
        return None
    if not candidate or not set(candidate) <= _YOUTUBE_ID_CHARS:
        return None
    return candidate


def _watch_url(video_id: str, seconds: int | None) -> str:
    """The one place a YouTube link is spelled: built from the id, never from a stored URL."""
    url = "https://www.youtube.com/watch?v=" + quote(video_id, safe="")
    return url if seconds is None else f"{url}&t={seconds}s"


def _number(value: object) -> float | None:
    """Read ``value`` as a finite number of seconds, or None when it is not one."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def consent_block(cues: Iterable[tuple[float, str | None]]) -> ConsentBlock | None:
    """Find the reading of the consent agenda among consent items' cue points.

    ``cues`` are ``(cue seconds, external_id)`` of a meeting's consent items.
    The block is the largest run in which neighbouring cue points are at most
    ``CONSENT_GAP_S`` apart, and there is one only when that run holds at
    least ``CONSENT_MIN_ITEMS``; of two runs of one size the earlier wins. An
    item pulled off consent and discussed later keeps its ``is_consent`` flag,
    which is why the block is a run and not the span of every consent cue.

    The block's chapter id is the id of the first cue point in the run that
    :func:`chapter_url` can use (all digits), and the run's first id when
    none is.
    """
    points = [(s, ext) for s, ext in ((_number(s), ext) for s, ext in cues) if s is not None]
    # Stable, so cue points that share a second keep the order they came in
    # (the loader's: row id).
    points.sort(key=lambda point: point[0])

    best: list[tuple[float, str | None]] = []
    run: list[tuple[float, str | None]] = []
    for point in points:
        if run and point[0] - run[-1][0] > CONSENT_GAP_S:
            run = []
        run.append(point)
        if len(run) > len(best):     # strictly: a later run of equal size does not replace it
            best = run
    if len(best) < CONSENT_MIN_ITEMS:
        return None

    chapter_id = next((ext for _, ext in best if _is_chapter_id(ext)), best[0][1])
    return ConsentBlock(start_s=best[0][0], end_s=best[-1][0],
                        chapter_id=None if chapter_id is None else str(chapter_id))


def item_moment(video: MeetingVideo | None, *, is_consent: bool, cue_s: float | None,
                external_id: str | None) -> tuple[float | None, str | None]:
    """Return ``(seconds, chapter id)`` for a link that stands for an agenda item.

    A consent item whose cue point lies inside the meeting's consent block, or
    that has no cue point, gets the block's start and chapter. Every other
    item gets its own cue point and id: a non-consent item always, and a
    consent item whose cue point is outside the block (pulled and discussed
    separately) or whose meeting has no block. A consent item with no cue
    point in a meeting with no block has no moment: ``(None, None)``.
    """
    block = video.consent if video is not None else None
    if is_consent:
        if cue_s is None:
            return (block.start_s, block.chapter_id) if block is not None else (None, None)
        if block is not None and block.start_s <= cue_s <= block.end_s:
            return (block.start_s, block.chapter_id)
    return (cue_s, external_id)


def link_for(video: MeetingVideo | None, *, seconds: object = None, chapter_id: object = None,
             url: str | None = None) -> VideoLink | None:
    """Build the link for one moment of one meeting's video.

    The base URL is ``video.video_url``, or ``url`` when ``video`` is None
    (the source button, which has only an anchor's URL). With no base URL
    there is no link. ``seconds`` is on the meeting's own clock; a value that
    cannot be read as a number is treated as absent.

    - The meeting's own video is on YouTube (a ``yt-`` row): that video at the
      floor of the second, with no conversion, or the plain watch URL when
      there is no second.
    - A Granicus player page: YouTube at the converted second when a recording
      covers it (``start_s <= seconds < end_s``, the first such recording in
      order whose converted second is not negative); otherwise
      ``chapter_url(base, chapter_id)``, ``timed`` exactly when the chapter id
      was applied.
    - Any other address, a YouTube one with no readable video id included:
      returned unchanged, with no label.
    """
    base = video.video_url if video is not None else url
    if not base:
        return None
    moment = _number(seconds)

    own_video = youtube_id(base)
    if own_video is not None:
        at = math.floor(moment) if moment is not None and moment >= 0 else None
        return VideoLink(url=_watch_url(own_video, at), site="youtube", label="YouTube",
                         seconds=at, timed=at is not None)

    if "MediaPlayer.php" in base:
        if moment is not None and video is not None:
            for recording in video.recordings:
                if recording.start_s <= moment < recording.end_s:
                    at = math.floor(moment - recording.offset_s)
                    if at >= 0:
                        return VideoLink(url=_watch_url(recording.video_id, at), site="youtube",
                                         label="YouTube", seconds=at, timed=True)
        return VideoLink(url=chapter_url(base, chapter_id), site="granicus", label="Granicus",
                         seconds=None, timed=_is_chapter_id(chapter_id))

    return VideoLink(url=base, site="other", label=None, seconds=None, timed=False)


# ---------------------------------------------------------------------------
# Database reads
# ---------------------------------------------------------------------------

def for_meetings(meeting_ids: Iterable[int]) -> dict[int, MeetingVideo]:
    """Load what links into each meeting's video are built from.

    Returns one entry per meeting that exists, also for a meeting with no
    ``video_url`` (:func:`link_for` then builds no link). Three reads: the
    meetings; their recordings whose measurement passed, at a trusted method
    version, against the clip the meeting has now, primary first; and their
    consent items' cue points. No read replaces a NULL with a default.
    """
    ids = sorted({int(meeting_id) for meeting_id in meeting_ids})
    if not ids:
        return {}
    with db_cursor() as cur:
        cur.execute("SELECT id, video_url FROM meetings WHERE id = ANY(%s)", (ids,))
        urls = {row["id"]: row["video_url"] for row in cur.fetchall()}

        cur.execute(
            """
            SELECT mv.meeting_id, mv.video_id, a.offset_s, a.granicus_start_s, a.granicus_end_s
              FROM meeting_videos mv
              JOIN meetings m ON m.id = mv.meeting_id
              JOIN meeting_video_alignments a ON a.meeting_video_id = mv.id
             WHERE mv.meeting_id = ANY(%s)
               AND mv.provider = 'youtube'
               AND a.status = 'passed'
               AND a.method_version >= %s
               AND a.granicus_clip_id = m.external_id
             ORDER BY mv.is_primary DESC, mv.id
            """,
            (ids, MIN_METHOD_VERSION),
        )
        recordings: dict[int, list[Recording]] = {}
        for row in cur.fetchall():
            recordings.setdefault(row["meeting_id"], []).append(Recording(
                video_id=row["video_id"], offset_s=row["offset_s"],
                start_s=row["granicus_start_s"], end_s=row["granicus_end_s"]))

        # Ordered by cue second and then row id; item_number is text and
        # would put "10" before "2".
        cur.execute(
            """
            SELECT meeting_id, video_timestamp_seconds, external_id
              FROM agenda_items
             WHERE meeting_id = ANY(%s)
               AND is_consent
               AND video_timestamp_seconds IS NOT NULL
             ORDER BY video_timestamp_seconds, id
            """,
            (ids,),
        )
        cues: dict[int, list[tuple[float, str | None]]] = {}
        for row in cur.fetchall():
            cues.setdefault(row["meeting_id"], []).append((row["video_timestamp_seconds"], row["external_id"]))

    return {
        meeting_id: MeetingVideo(video_url=video_url,
                                 recordings=tuple(recordings.get(meeting_id, ())),
                                 consent=consent_block(cues.get(meeting_id, ())))
        for meeting_id, video_url in urls.items()
    }


def for_meeting(meeting_id: int) -> MeetingVideo | None:
    """:func:`for_meetings` for one meeting; None when the meeting does not exist."""
    return for_meetings([meeting_id]).get(meeting_id)


def item_links(meeting_id: int) -> dict[int, VideoLink]:
    """Return each agenda item's link into its meeting's video, by agenda item id.

    Every item of a meeting that has a video gets a link: at the item's
    moment under the consent rule (:func:`item_moment`) when it has one, and
    otherwise the plain link, whose ``timed`` is false and whose phrase does
    not say "chapter". A meeting with no video, or no such meeting, gives an
    empty dict.
    """
    video = for_meeting(meeting_id)
    if video is None or not video.video_url:
        return {}
    with db_cursor() as cur:
        cur.execute(
            "SELECT id, is_consent, video_timestamp_seconds, external_id "
            "FROM agenda_items WHERE meeting_id = %s ORDER BY id",
            (meeting_id,),
        )
        rows = cur.fetchall()
    links: dict[int, VideoLink] = {}
    for row in rows:
        seconds, chapter_id = item_moment(
            video, is_consent=row["is_consent"], cue_s=row["video_timestamp_seconds"],
            external_id=row["external_id"])
        link = link_for(video, seconds=seconds, chapter_id=chapter_id)
        if link is not None:
            links[row["id"]] = link
    return links
