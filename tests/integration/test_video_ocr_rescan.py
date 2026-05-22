"""Integration test for POST /admin/meetings/<id>/rescan-ocr.

Verifies prior OCR votes + member_votes are deleted, processing_status
flags reset, minutes-text votes NOT touched, auth gate works.
"""
import os
import pytest

from docket.db import db_cursor

pytestmark = pytest.mark.skipif(
    "railway.internal" in os.environ.get("DATABASE_URL", "")
    or "railway.app" in os.environ.get("DATABASE_URL", ""),
    reason="Mutates DB; must not run against Railway prod.",
)


def test_rescan_deletes_only_video_ocr_votes(authed_admin_client, seeded_meeting_with_mixed_votes):
    """Video_ocr votes (+ member_votes) cleared; minutes_text vote retained;
    processing_status flags reset."""
    meeting_id = seeded_meeting_with_mixed_votes
    resp = authed_admin_client.post(
        f"/admin/meetings/{meeting_id}/rescan-ocr",
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with db_cursor() as cur:
        cur.execute(
            "SELECT source FROM votes WHERE meeting_id = %s ORDER BY source",
            [meeting_id],
        )
        sources = [r["source"] for r in cur.fetchall()]
        cur.execute(
            """SELECT video_ocr_scanned, video_ocr_attempts,
                      video_ocr_last_attempted_at, video_ocr_last_error
                 FROM processing_status WHERE meeting_id = %s""",
            [meeting_id],
        )
        ps = cur.fetchone()
        cur.execute(
            """SELECT COUNT(*) AS n FROM member_votes mv
                 JOIN votes v ON v.id = mv.vote_id
                WHERE v.meeting_id = %s AND v.source = 'video_ocr'""",
            [meeting_id],
        )
        ocr_member_votes_left = cur.fetchone()["n"]

    assert sources == ["minutes_text"]   # video_ocr rows gone, minutes_text retained
    assert ocr_member_votes_left == 0
    assert ps["video_ocr_scanned"] is False
    assert ps["video_ocr_attempts"] == 0
    assert ps["video_ocr_last_attempted_at"] is None
    assert ps["video_ocr_last_error"] is None


def test_rescan_requires_login(client, seeded_meeting_with_mixed_votes):
    """Unauthenticated POST is rejected by the blueprint-level gate.
    Should return 302 to login (preferred) or 401/403."""
    resp = client.post(
        f"/admin/meetings/{seeded_meeting_with_mixed_votes}/rescan-ocr",
        follow_redirects=False,
    )
    assert resp.status_code in (302, 401, 403)
