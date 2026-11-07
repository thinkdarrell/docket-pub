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
vote could belong to (GitHub issue #142).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from docket.db import db_cursor


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
