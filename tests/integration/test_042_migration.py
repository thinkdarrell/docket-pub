"""Verify migration 042: `meeting_video_alignments`, its two CHECK constraints, one row per recording, and the cascade; down drops the table.

Pattern: tests/integration/test_040_migration.py. Plan: plans/completed/video-links-land-on-the-moment.md (M2).
"""
from datetime import date

import psycopg2.errors
import pytest
from docket.config import DATABASE_URL
from docket.db import db, db_cursor
from docket.migrations import runner

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Migration test must not run against Railway prod.",
)

PREFIX = "m042-"


def _delete_test_meetings() -> None:
    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE external_id LIKE %s", (PREFIX + "%",))


@pytest.fixture
def fresh_042():
    """Every migration applied, then 042 rolled back; the teardown re-applies it."""
    with db() as conn:
        runner.apply_migrations(conn)
        runner.rollback_migration(conn, 42)
    yield
    with db() as conn:
        runner.apply_migrations(conn)
    _delete_test_meetings()


@pytest.fixture
def applied_042():
    with db() as conn:
        runner.apply_migrations(conn)
    yield
    _delete_test_meetings()


def _table_exists() -> bool:
    with db_cursor() as cur:
        cur.execute("SELECT to_regclass('public.meeting_video_alignments') AS t")
        return cur.fetchone()["t"] is not None


def _recording(tag: str) -> tuple[int, int]:
    """One Birmingham meeting with one attached YouTube recording: (meeting id, meeting_videos id)."""
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham'")
        muni = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type) "
            "VALUES (%s, %s, 'Regular City Council Meeting', %s, 'council') RETURNING id",
            (muni, PREFIX + tag, date(2026, 10, 27)),
        )
        meeting_id = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO meeting_videos (meeting_id, provider, video_id, url, title, clean_title, duration_s, is_primary) "
            "VALUES (%s, 'youtube', %s, %s, 'Regular City Council Meeting 10.27.26', "
            "'Regular City Council Meeting', 3443, TRUE) RETURNING id",
            (meeting_id, PREFIX + tag, f"https://www.youtube.com/watch?v={PREFIX}{tag}"),
        )
        return meeting_id, cur.fetchone()["id"]


def _measure(meeting_video_id: int, *, status: str = "passed", offset_s=635.48,
             start_s=635.5, end_s=4078.7) -> None:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO meeting_video_alignments (meeting_video_id, granicus_clip_id, method_version, status, "
            "offset_s, granicus_start_s, granicus_end_s, score, runner_up, windows, windows_confirmed) "
            "VALUES (%s, '2026', 1, %s, %s, %s, %s, 23.6, 6.0, 12, 10)",
            (meeting_video_id, status, offset_s, start_s, end_s),
        )


def test_042_up_creates_the_table_and_its_checks_refuse_bad_rows(fresh_042):
    assert not _table_exists()

    with db() as conn:
        runner.apply_migrations(conn)

    assert _table_exists()
    _, passed = _recording("passed")
    _measure(passed)
    with db_cursor() as cur:
        cur.execute(
            "SELECT status, offset_s, granicus_start_s, granicus_end_s, measured_at IS NOT NULL AS stamped "
            "FROM meeting_video_alignments WHERE meeting_video_id = %s", (passed,))
        row = cur.fetchone()
    assert (row["status"], row["offset_s"], row["granicus_start_s"], row["granicus_end_s"]) == (
        "passed", 635.48, 635.5, 4078.7)
    assert row["stamped"], "measured_at defaults to now()"

    _, other = _recording("other")
    with pytest.raises(psycopg2.errors.CheckViolation):
        _measure(other, status="measured")           # a status outside the three
    with pytest.raises(psycopg2.errors.CheckViolation):
        _measure(other, offset_s=None)               # passed with no offset
    with pytest.raises(psycopg2.errors.CheckViolation):
        _measure(other, end_s=None)                  # passed with half a span
    with pytest.raises(psycopg2.errors.CheckViolation):
        _measure(other, start_s=4078.7, end_s=635.5)  # passed with an empty span
    # A rejected or failed row needs no offset and no span.
    _measure(other, status="failed", offset_s=None, start_s=None, end_s=None)


def test_042_one_row_per_recording_and_the_meeting_takes_it_along(applied_042):
    meeting_id, video = _recording("cascade")
    _measure(video, status="rejected")
    with pytest.raises(psycopg2.errors.UniqueViolation):
        _measure(video)

    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE id = %s", (meeting_id,))
        cur.execute("SELECT count(*) AS n FROM meeting_video_alignments WHERE meeting_video_id = %s", (video,))
        assert cur.fetchone()["n"] == 0


def test_042_down_drops_the_table_and_up_restores_it(fresh_042):
    with db() as conn:
        runner.apply_migrations(conn)
    _, video = _recording("down")
    _measure(video)

    with db() as conn:
        runner.rollback_migration(conn, 42)
    assert not _table_exists()
    with db_cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM meeting_videos WHERE id = %s", (video,))
        assert cur.fetchone()["n"] == 1, "the down takes the measurements and leaves the recordings"

    with db() as conn:
        runner.apply_migrations(conn)
    assert _table_exists()
    with db_cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM meeting_video_alignments")
        assert cur.fetchone()["n"] == 0
