"""Video votes and the agenda items they are attached to: the listing the
operator reads against transcripts, and the bounded re-match that moves
stored attachments to where match_votes_by_timestamp now puts them.
Reads and writes are this module's; scripts/sample_near_cue_votes.py and
scripts/rematch_near_cue_votes.py print what it returns.

A video vote is a ``votes`` row with ``source = 'video_ocr'`` and a
``video_timestamp`` (seconds on the Granicus clip's clock). A cue point is
``agenda_items.video_timestamp_seconds``, the second at which the clerk
marked the item as beginning in the player. A timestamp link is a
``vote_agenda_items`` row with ``match_method = 'timestamp'``, written by
``docket.analysis.vote_matcher.match_votes_by_timestamp``. The listing here
reports, for each active non-manual timestamp link of a city's video votes,
the gap from the vote to its item's cue point and the latest item of the
meeting with a strictly earlier cue second, which is the other item the
vote could belong to (GitHub issue #142). The re-match computes, for each
listed link, the item ``match_votes_by_timestamp`` would attach the vote to
today (``item_index_for_vote``: the latest cue at or before the vote, or,
within ``NEAR_CUE_S`` seconds of it, the latest item with a strictly
earlier cue second) and moves only the links whose stored item differs:
the old row is deactivated, never deleted, and the new one is upserted on
the table's unique key ``(vote_id, agenda_item_id)``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from docket.analysis.vote_matcher import compute_confidence, item_index_for_vote
from docket.db import db, db_cursor

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TimestampLink:
    link_id: int
    vote_id: int
    meeting_id: int
    meeting_date: date | None
    vote_timestamp: float
    result: str
    yeas: int | None
    nays: int | None
    needs_review: bool
    item_id: int
    item_number: str | None
    item_title: str
    item_cue: float
    gap: float
    is_latest_cue: bool
    earlier_item_id: int | None
    earlier_item_number: str | None
    earlier_item_title: str | None
    earlier_cue: float | None
    item_active_video_votes: int
    earlier_active_video_votes: int | None
    has_transcript: bool


_LIST_SQL = """
    SELECT vai.id AS link_id,
           v.id AS vote_id,
           v.meeting_id,
           m.meeting_date,
           v.video_timestamp AS vote_timestamp,
           v.result, v.yeas, v.nays, v.needs_review,
           a.id AS item_id,
           a.item_number,
           a.title AS item_title,
           a.video_timestamp_seconds AS item_cue,
           v.video_timestamp - a.video_timestamp_seconds AS gap,
           COALESCE(a.video_timestamp_seconds = latest.cue, FALSE) AS is_latest_cue,
           e.id AS earlier_item_id,
           e.item_number AS earlier_item_number,
           e.title AS earlier_item_title,
           e.video_timestamp_seconds AS earlier_cue,
           (SELECT count(*) FROM vote_agenda_items x
              JOIN votes xv ON xv.id = x.vote_id
             WHERE x.agenda_item_id = a.id AND x.is_active
               AND xv.source = 'video_ocr') AS item_active_video_votes,
           CASE WHEN e.id IS NULL THEN NULL ELSE
           (SELECT count(*) FROM vote_agenda_items x
              JOIN votes xv ON xv.id = x.vote_id
             WHERE x.agenda_item_id = e.id AND x.is_active
               AND xv.source = 'video_ocr') END AS earlier_active_video_votes,
           EXISTS (SELECT 1 FROM transcripts t WHERE t.meeting_id = v.meeting_id) AS has_transcript
      FROM vote_agenda_items vai
      JOIN votes v ON v.id = vai.vote_id
      JOIN agenda_items a ON a.id = vai.agenda_item_id
      JOIN meetings m ON m.id = v.meeting_id
      LEFT JOIN LATERAL (
           SELECT max(video_timestamp_seconds) AS cue
             FROM agenda_items
            WHERE meeting_id = v.meeting_id
              AND video_timestamp_seconds <= v.video_timestamp
      ) latest ON TRUE
      LEFT JOIN LATERAL (
           SELECT id, item_number, title, video_timestamp_seconds
             FROM agenda_items
            WHERE meeting_id = v.meeting_id
              AND video_timestamp_seconds < a.video_timestamp_seconds
            ORDER BY video_timestamp_seconds DESC, id DESC
            LIMIT 1
      ) e ON TRUE
     WHERE m.municipality_id = %(municipality_id)s
       AND vai.is_active
       AND vai.is_manual = FALSE
       AND vai.match_method = 'timestamp'
       AND v.source = 'video_ocr'
       AND v.video_timestamp IS NOT NULL
       AND a.video_timestamp_seconds IS NOT NULL
       AND (%(within_s)s::real IS NULL
            OR v.video_timestamp - a.video_timestamp_seconds <= %(within_s)s::real)
     ORDER BY m.meeting_date, m.id, v.video_timestamp, v.id
"""


def list_timestamp_links(slug: str, *, within_s: float | None = None) -> list[TimestampLink]:
    """Every active, non-manual timestamp link of a video vote in the city
    whose municipality slug is ``slug``, with the gap from the vote to its
    item's cue point and the meeting's latest item with a strictly earlier
    cue second (ties by the highest item id; all four earlier fields None
    when there is none).

    ``is_latest_cue`` says whether the stored item's cue is the greatest cue
    at or before the vote among the meeting's items, which is what the
    original matcher picks; False means cue points changed after the vote
    was matched. ``item_active_video_votes`` and
    ``earlier_active_video_votes`` count the active links of video votes on
    each candidate item (the second is None when there is no earlier item).
    ``has_transcript`` is whether a ``transcripts`` row exists for the
    meeting. With ``within_s`` only links whose gap is at most that many
    seconds are returned. Ordered by meeting date, meeting id, vote
    timestamp, vote id. Reads only. Raises ValueError for an unknown slug.
    """
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug = %s", (slug,))
        muni = cur.fetchone()
        if muni is None:
            raise ValueError(f"Municipality '{slug}' not found")
        cur.execute(_LIST_SQL, {"municipality_id": muni["id"], "within_s": within_s})
        rows = cur.fetchall()
    return [TimestampLink(**row) for row in rows]


def transcript_window(meeting_id: int, start_s: float, end_s: float) -> list[tuple[float, str]]:
    """``(start_s, text)`` for every non-silence segment of the meeting's
    transcript that overlaps the window (segment start before ``end_s`` and
    segment end after ``start_s``), in ``seq`` order; empty when the meeting
    has no transcript. Reads only."""
    with db_cursor() as cur:
        cur.execute(
            """SELECT s.start_s, s.text
                 FROM transcript_segments s
                 JOIN transcripts t ON t.id = s.transcript_id
                WHERE t.meeting_id = %s
                  AND NOT s.is_silence
                  AND s.start_s < %s
                  AND s.end_s > %s
                ORDER BY s.seq""",
            (meeting_id, end_s, start_s),
        )
        rows = cur.fetchall()
    return [(row["start_s"], row["text"]) for row in rows]


@dataclass(frozen=True)
class Move:
    link: TimestampLink
    reason: str                    # 'near_cue' or 'cue_changed'
    new_item_id: int | None        # None for cue_changed
    new_item_number: str | None
    new_cue: float | None
    new_gap: float | None
    new_confidence: float | None


_DEACTIVATE_SQL = """
    UPDATE vote_agenda_items
       SET is_active = FALSE, updated_at = NOW()
     WHERE id = ANY(%s) AND is_active AND is_manual = FALSE AND match_method = 'timestamp'
"""

_UPSERT_SQL = """
    INSERT INTO vote_agenda_items
        (vote_id, agenda_item_id, association_type, match_method, match_confidence, provisional)
    SELECT * FROM unnest(%s::int[], %s::int[], %s::text[], %s::text[], %s::real[], %s::boolean[])
    ON CONFLICT (vote_id, agenda_item_id) DO UPDATE
      SET is_active = TRUE,
          association_type = EXCLUDED.association_type,
          match_method = EXCLUDED.match_method,
          match_confidence = EXCLUDED.match_confidence,
          provisional = EXCLUDED.provisional,
          updated_at = NOW()
    WHERE vote_agenda_items.is_manual = FALSE
"""


def rematch_near_cue_links(slug: str, *, dry_run: bool = False) -> list[Move]:
    """Move the city's stored timestamp attachments to where the matcher's
    rule now puts them, and return what was (or would be) done.

    For every link ``list_timestamp_links`` returns, the meeting's cued
    items (ordered by cue second, then id) are read once and
    ``item_index_for_vote`` names the item the rule picks today. A link
    whose stored item is that item, or shares its cue second with it (the
    clerk clicked them as one; the gap and the confidence are the same),
    is unchanged and not returned. A link whose stored item is no longer
    the latest cue at or before the vote (``is_latest_cue`` False: cue
    points changed after the vote was matched) is returned with reason
    ``cue_changed`` and never written. Every other differing link is
    returned with reason ``near_cue``, its new item, gap, and confidence.

    Unless ``dry_run``, the ``near_cue`` moves are written in one
    transaction with two statements: an UPDATE that deactivates the old
    rows (only while still active, non-manual, and ``timestamp``) and an
    INSERT ... ON CONFLICT that writes the new rows as ``explicit``,
    ``timestamp``, ``provisional`` FALSE, reviving an inactive row for the
    same vote and target when one exists and leaving a manual one alone.
    Nothing is deleted. Returns the ``near_cue`` moves in listing order,
    then the ``cue_changed`` ones. Raises ValueError for an unknown slug.
    """
    links = list_timestamp_links(slug)
    by_meeting: dict[int, list[TimestampLink]] = {}
    for link in links:
        by_meeting.setdefault(link.meeting_id, []).append(link)

    near_cue: list[Move] = []
    cue_changed: list[Move] = []
    with db_cursor() as cur:
        for meeting_id, meeting_links in by_meeting.items():
            cur.execute(
                """SELECT id, item_number, video_timestamp_seconds AS cue
                     FROM agenda_items
                    WHERE meeting_id = %s AND video_timestamp_seconds IS NOT NULL
                    ORDER BY video_timestamp_seconds, id""",
                (meeting_id,),
            )
            items = cur.fetchall()
            cues = [row["cue"] for row in items]
            for link in meeting_links:
                idx = item_index_for_vote(cues, link.vote_timestamp)
                if idx is not None and cues[idx] == link.item_cue:
                    continue
                if not link.is_latest_cue or idx is None:
                    cue_changed.append(Move(link, "cue_changed", None, None, None, None, None))
                    continue
                target = items[idx]
                new_gap = link.vote_timestamp - target["cue"]
                near_cue.append(Move(
                    link, "near_cue", target["id"], target["item_number"], target["cue"],
                    new_gap, compute_confidence(new_gap, needs_review=link.needs_review),
                ))

    if near_cue and not dry_run:
        n = len(near_cue)
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(_DEACTIVATE_SQL, ([m.link.link_id for m in near_cue],))
                cur.execute(_UPSERT_SQL, (
                    [m.link.vote_id for m in near_cue],
                    [m.new_item_id for m in near_cue],
                    ["explicit"] * n,
                    ["timestamp"] * n,
                    [m.new_confidence for m in near_cue],
                    [False] * n,
                ))

    logger.info(
        "vote_rematch: %d moves on %d meetings, %d left alone (cue changed)%s",
        len(near_cue), len({m.link.meeting_id for m in near_cue}), len(cue_changed),
        ", dry run" if dry_run else "",
    )
    return near_cue + cue_changed
