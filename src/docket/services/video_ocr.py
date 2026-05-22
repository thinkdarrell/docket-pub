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
