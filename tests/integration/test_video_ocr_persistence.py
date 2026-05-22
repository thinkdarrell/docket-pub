"""Integration tests for persist_detected_votes — DetectedVote → Postgres.

Verifies the schema mapping, idempotency, NULL-FK auditability for
unmatched OCR names, and the needs_review → confidence='medium' rule.
"""
import os

import pytest

from docket.analysis.ocr._models import DetectedVote, MemberVote
from docket.db import db_cursor
from docket.services.video_ocr import persist_detected_votes

pytestmark = pytest.mark.skipif(
    "railway.internal" in os.environ.get("DATABASE_URL", "")
    or "railway.app" in os.environ.get("DATABASE_URL", ""),
    reason="Persistence test mutates DB; must not run against Railway prod.",
)


def _mkvote(
    *,
    timestamp: float,
    vote_result: str = "passed",
    yeas: int = 8, nays: int = 0, abstentions: int = 0,
    member_positions: dict[str, str] | None = None,
    needs_review: bool = False,
    review_reason: str | None = None,
) -> DetectedVote:
    """Build a DetectedVote for tests; field names mirror the real dataclass."""
    mvs = [MemberVote(member_name=n, position=p) for n, p in (member_positions or {}).items()]
    return DetectedVote(
        timestamp=timestamp,
        vote_result=vote_result,
        yeas=yeas, nays=nays, abstentions=abstentions,
        raw_text=f"Motion {vote_result.capitalize()}",
        member_votes=mvs,
        header_result=vote_result,
        needs_review=needs_review,
        review_reason=review_reason,
    )


def test_persist_single_vote_no_members(seeded_bham_meeting_2026):
    detected = [_mkvote(timestamp=100.0)]
    n = persist_detected_votes(seeded_bham_meeting_2026, detected, member_map={})
    assert n == 1
    with db_cursor() as cur:
        cur.execute(
            "SELECT result, yeas, source FROM votes WHERE meeting_id = %s",
            [seeded_bham_meeting_2026],
        )
        rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["source"] == "video_ocr"
    assert rows[0]["yeas"] == 8


def test_persist_member_votes_via_member_map(seeded_bham_meeting_2026, bham_roster_2026):
    """member_votes rows get council_member_id from the passed map."""
    if not bham_roster_2026.member_map:
        pytest.skip("No active BHM council members on 2026-05-19 in this DB; populate via migration 005/007 to run.")
    name = next(iter(bham_roster_2026.member_map.keys()))
    detected = [_mkvote(timestamp=200.0, member_positions={name: "yes"})]
    persist_detected_votes(
        seeded_bham_meeting_2026, detected, member_map=bham_roster_2026.member_map,
    )
    with db_cursor() as cur:
        cur.execute(
            """SELECT mv.council_member_id, mv.position, mv.member_name
                 FROM member_votes mv JOIN votes v ON v.id = mv.vote_id
                WHERE v.meeting_id = %s""",
            [seeded_bham_meeting_2026],
        )
        rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["council_member_id"] == bham_roster_2026.member_map[name]
    assert rows[0]["position"] == "yes"
    assert rows[0]["member_name"] == name


def test_persist_idempotent_on_conflict(seeded_bham_meeting_2026):
    """Re-running the same (meeting_id, timestamp, source='video_ocr') does NOT duplicate."""
    detected = [_mkvote(timestamp=300.0)]
    persist_detected_votes(seeded_bham_meeting_2026, detected, member_map={})
    persist_detected_votes(seeded_bham_meeting_2026, detected, member_map={})
    with db_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM votes WHERE meeting_id = %s AND video_timestamp = 300.0",
            [seeded_bham_meeting_2026],
        )
        assert cur.fetchone()["n"] == 1


def test_persist_unmatched_member_logs_warning(seeded_bham_meeting_2026, bham_roster_2026, caplog):
    """A name not in member_map is logged + inserted with council_member_id=NULL."""
    detected = [_mkvote(timestamp=400.0, member_positions={"X. Nonexistent": "yes"})]
    persist_detected_votes(
        seeded_bham_meeting_2026, detected, member_map=bham_roster_2026.member_map,
    )
    assert "Nonexistent" in caplog.text or "X. Nonexistent" in caplog.text
    with db_cursor() as cur:
        cur.execute(
            """SELECT council_member_id, member_name FROM member_votes mv
                 JOIN votes v ON v.id = mv.vote_id
                WHERE v.meeting_id = %s AND v.video_timestamp = 400.0""",
            [seeded_bham_meeting_2026],
        )
        rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["council_member_id"] is None
    assert rows[0]["member_name"] == "X. Nonexistent"


def test_persist_needs_review_vote_marked_medium_confidence(seeded_bham_meeting_2026):
    """needs_review=True must map to confidence='medium', not the column default 'high'."""
    clean = _mkvote(timestamp=500.0, needs_review=False)
    flagged = _mkvote(timestamp=600.0, needs_review=True, review_reason="counts_mismatch")
    persist_detected_votes(seeded_bham_meeting_2026, [clean, flagged], member_map={})
    with db_cursor() as cur:
        cur.execute(
            """SELECT video_timestamp, confidence, needs_review
                 FROM votes
                WHERE meeting_id = %s
                ORDER BY video_timestamp""",
            [seeded_bham_meeting_2026],
        )
        rows = cur.fetchall()
    assert len(rows) == 2
    assert float(rows[0]["video_timestamp"]) == 500.0
    assert rows[0]["confidence"] == "high"
    assert rows[0]["needs_review"] is False
    assert float(rows[1]["video_timestamp"]) == 600.0
    assert rows[1]["confidence"] == "medium"
    assert rows[1]["needs_review"] is True
