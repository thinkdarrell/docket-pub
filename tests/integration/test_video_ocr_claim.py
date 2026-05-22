"""Integration tests for the OCR claim pattern (spec §4 + §10).

Six scenarios:
1. Concurrent claims pick different meetings (FOR UPDATE SKIP LOCKED works).
2. Counter bumps on claim, not on completion.
3. 24h backoff after a failed claim.
4. Scan failure path doesn't propagate (uses _ocr_one_meeting from Task 14).
5. Hidden meeting never claimed.
6. 60-day window enforced.
7. event-N external_id never claimed.
"""
import os
from datetime import date, timedelta
from unittest.mock import patch

import psycopg2
import pytest

from docket.config import DATABASE_URL
from docket.db import db_cursor
from docket.services.video_ocr import (
    _claim_next_ocr_meeting,
    _CLAIM_SQL,
    _mark_ocr_failed,
)

pytestmark = pytest.mark.skipif(
    "railway.internal" in os.environ.get("DATABASE_URL", "")
    or "railway.app" in os.environ.get("DATABASE_URL", ""),
    reason="Claim test mutates DB; must not run against Railway prod.",
)


def test_concurrent_claims_pick_different_meetings(seeded_two_ocr_pending):
    """Two open connections each call _claim; together they pick BOTH meetings."""
    m1_id, m2_id = seeded_two_ocr_pending
    claimed: list[int] = []
    conn_a = psycopg2.connect(DATABASE_URL)
    conn_b = psycopg2.connect(DATABASE_URL)
    try:
        with conn_a.cursor() as ca, conn_b.cursor() as cb:
            ca.execute(_CLAIM_SQL)
            row_a = ca.fetchone()
            cb.execute(_CLAIM_SQL)
            row_b = cb.fetchone()
            conn_a.commit()
            conn_b.commit()
            if row_a:
                claimed.append(row_a[0])
            if row_b:
                claimed.append(row_b[0])
    finally:
        conn_a.close()
        conn_b.close()
    assert len(claimed) == 2
    assert claimed[0] != claimed[1]
    assert set(claimed) == {m1_id, m2_id}


def test_counter_bumps_on_claim_not_completion(seeded_one_ocr_pending):
    """Claim bumps attempts immediately; without _mark_ocr_complete the
    meeting stays scanned=FALSE with attempts=1."""
    m_id = seeded_one_ocr_pending
    claimed = _claim_next_ocr_meeting()
    assert claimed is not None
    assert claimed["id"] == m_id
    with db_cursor() as cur:
        cur.execute(
            """SELECT video_ocr_attempts, video_ocr_last_attempted_at, video_ocr_scanned
                 FROM processing_status WHERE meeting_id = %s""",
            [m_id],
        )
        row = cur.fetchone()
    assert row["video_ocr_attempts"] == 1
    assert row["video_ocr_last_attempted_at"] is not None
    assert row["video_ocr_scanned"] is False


def test_24h_backoff_after_failed_claim(seeded_one_ocr_pending):
    """Within 24h of a claim, the same meeting is NOT re-claimable."""
    _claim_next_ocr_meeting()
    second_claim = _claim_next_ocr_meeting()
    assert second_claim is None


def test_scan_failure_records_error_does_not_propagate(seeded_one_ocr_pending):
    """When scan_meeting_for_votes raises, _ocr_one_meeting catches, writes
    error, returns dict with 'error' key. Uses Task 14's _ocr_one_meeting."""
    # Lazy import: this symbol arrives in Task 14
    from docket.services.video_ocr import _ocr_one_meeting

    m_id = seeded_one_ocr_pending
    claimed = _claim_next_ocr_meeting()
    assert claimed is not None
    with patch(
        "docket.services.video_ocr.scan_meeting_for_votes",
        side_effect=RuntimeError("simulated ffmpeg crash"),
    ):
        result = _ocr_one_meeting(claimed)
    assert "error" in result
    assert "simulated ffmpeg crash" in result["error"]
    with db_cursor() as cur:
        cur.execute(
            """SELECT video_ocr_scanned, video_ocr_last_error
                 FROM processing_status WHERE meeting_id = %s""",
            [m_id],
        )
        row = cur.fetchone()
    assert row["video_ocr_scanned"] is False
    assert "simulated ffmpeg crash" in row["video_ocr_last_error"]


def test_hidden_meeting_never_claimed(seeded_one_ocr_pending_hidden):
    """is_hidden=TRUE is filtered out of the claim CTE."""
    claimed = _claim_next_ocr_meeting()
    assert claimed is None


def test_60day_window_enforced(seeded_one_ocr_pending_old):
    """Meeting 61 days old is not claimed."""
    claimed = _claim_next_ocr_meeting()
    assert claimed is None


def test_event_external_id_never_claimed(seeded_one_ocr_pending_event_id):
    """external_id 'event-12345' is filtered by the ^[0-9]+$ regex."""
    claimed = _claim_next_ocr_meeting()
    assert claimed is None
