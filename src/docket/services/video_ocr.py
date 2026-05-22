"""Video OCR orchestration service.

This module owns the worker-task seam:
- `persist_detected_votes` — DetectedVote(s) + member_map → votes + member_votes
- (later tasks) `_claim_next_ocr_meeting`, `_ocr_one_meeting`

OCR detection itself lives in `docket.analysis.ocr.pipeline`; this module
is the thin layer that ties it to Postgres.
"""

from __future__ import annotations

import logging
from typing import Iterable

from docket.analysis.ocr._models import DetectedVote
from docket.db import db_cursor

log = logging.getLogger(__name__)


def persist_detected_votes(
    meeting_id: int,
    detected: Iterable[DetectedVote],
    *,
    member_map: dict[str, int],
) -> int:
    """Persist each DetectedVote as one votes row + N member_votes rows.

    Idempotent via the partial unique index
    `idx_votes_ocr_unique (meeting_id, video_timestamp, source='video_ocr')`:
    re-runs with the same timestamps skip via ON CONFLICT DO NOTHING.

    Returns the number of NEW votes rows inserted (NOT including rows skipped
    by the conflict).

    Member positions whose OCR-name keys are absent from `member_map` are
    logged at WARNING and inserted with `council_member_id = NULL` — the
    `member_votes.member_name` column still captures the OCR'd string for
    audit, so the row isn't lost.

    Confidence mapping (spec §6): `needs_review=True` → 'medium', clean
    scan → 'high'. The column default ('high') would otherwise silently
    misrepresent cross-verification failures.
    """
    inserted = 0
    with db_cursor() as cur:
        for vote in detected:
            confidence = "medium" if vote.needs_review else "high"
            cur.execute(
                """
                INSERT INTO votes (
                    meeting_id, video_timestamp, result,
                    yeas, nays, abstentions,
                    header_result, needs_review, review_reason,
                    raw_text, confidence, source
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'video_ocr')
                ON CONFLICT (meeting_id, video_timestamp, source)
                WHERE source = 'video_ocr'
                DO NOTHING
                RETURNING id
                """,
                [
                    meeting_id,
                    vote.timestamp,
                    vote.vote_result,
                    vote.yeas, vote.nays, vote.abstentions,
                    vote.header_result,
                    vote.needs_review,
                    vote.review_reason,
                    vote.raw_text,
                    confidence,
                ],
            )
            row = cur.fetchone()
            if row is None:
                # Conflict — vote already persisted; skip member_votes too.
                continue
            vote_id = row["id"]
            inserted += 1

            for mv in vote.member_votes:
                ocr_name = mv.member_name
                position = mv.position
                member_id = member_map.get(ocr_name)
                if member_id is None:
                    log.warning(
                        "video_ocr: unmatched member name '%s' on meeting %s vote %s — inserting with NULL council_member_id",
                        ocr_name, meeting_id, vote_id,
                    )
                cur.execute(
                    """
                    INSERT INTO member_votes (vote_id, council_member_id, member_name, position)
                    VALUES (%s, %s, %s, %s)
                    """,
                    [vote_id, member_id, ocr_name, position],
                )
    return inserted


# Spec §4: claim pattern. Inner CTE locks rows passing the FULL filter
# set with FOR UPDATE SKIP LOCKED, so concurrent workers don't deadlock
# or claim the same meeting and we don't accidentally lock rows that the
# outer WHERE would reject. The outer UPDATE bumps attempts before any
# scan runs so a process crash mid-scan still consumes one attempt.
_CLAIM_SQL = """
    WITH candidate AS (
        SELECT ps.meeting_id
          FROM processing_status ps
          JOIN meetings m        ON m.id  = ps.meeting_id
          JOIN municipalities mu ON mu.id = m.municipality_id
         WHERE mu.slug = 'birmingham'
           AND m.external_id ~ '^[0-9]+$'
           AND m.is_hidden = FALSE
           AND m.meeting_date >= now() - interval '60 days'
           AND ps.video_ocr_scanned = FALSE
           AND ps.video_ocr_attempts < 3
           AND (
                ps.video_ocr_last_attempted_at IS NULL
                OR ps.video_ocr_last_attempted_at < now() - interval '24 hours'
           )
         ORDER BY ps.video_ocr_last_attempted_at NULLS FIRST, m.meeting_date DESC
         LIMIT 1
         FOR UPDATE OF ps SKIP LOCKED
    )
    UPDATE processing_status ps
       SET video_ocr_attempts         = ps.video_ocr_attempts + 1,
           video_ocr_last_attempted_at = now()
      FROM candidate
      JOIN meetings m ON m.id = candidate.meeting_id
     WHERE ps.meeting_id = candidate.meeting_id
     RETURNING m.id, m.external_id, m.meeting_date
"""


def _claim_next_ocr_meeting() -> dict | None:
    """Atomically claim the next BHM meeting needing OCR.

    Returns a dict with keys (id, external_id, meeting_date), or None if no
    meeting is currently eligible. The claim commits immediately; the
    long OCR scan that follows runs without any DB connection held.
    """
    with db_cursor() as cur:
        cur.execute(_CLAIM_SQL)
        row = cur.fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "external_id": row["external_id"],
        "meeting_date": row["meeting_date"],
    }


def _mark_ocr_complete(meeting_id: int) -> None:
    """Set video_ocr_scanned=TRUE and clear last error."""
    with db_cursor() as cur:
        cur.execute(
            """UPDATE processing_status
                  SET video_ocr_scanned = TRUE,
                      video_ocr_last_error = NULL
                WHERE meeting_id = %s""",
            [meeting_id],
        )


def _mark_ocr_failed(meeting_id: int, error: str) -> None:
    """Record error text on processing_status; leave video_ocr_scanned=FALSE
    so the 24h backoff applies and the meeting is eligible again on retry."""
    with db_cursor() as cur:
        cur.execute(
            """UPDATE processing_status
                  SET video_ocr_last_error = %s
                WHERE meeting_id = %s""",
            [error[:2000], meeting_id],
        )
