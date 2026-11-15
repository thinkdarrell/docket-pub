"""Verify migration 046: `meeting_video_alignments` keyed on recording and stretch, the rows rejected at method version 2 deleted; down keeps each recording's first stretch and restores the single-column key.

Pattern: tests/integration/test_044_migration.py. Plan `youtube-links-cover-matching-stretches`, M2.
The runner's list is read inside the test functions so the file collects before the migration exists.
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

PREFIX = "m046-"
MODULE = "docket.migrations.046_alignment_stretches"


def _delete_test_meetings() -> None:
    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE external_id LIKE %s", (PREFIX + "%",))


@pytest.fixture
def fresh_046():
    """Every migration applied, then 046 rolled back; the teardown re-applies it."""
    _delete_test_meetings()
    with db() as conn:
        runner.apply_migrations(conn)
        runner.rollback_migration(conn, 46)
    yield
    _delete_test_meetings()
    with db() as conn:
        runner.apply_migrations(conn)


@pytest.fixture
def applied_046():
    _delete_test_meetings()
    with db() as conn:
        runner.apply_migrations(conn)
    yield
    _delete_test_meetings()
    with db() as conn:
        runner.apply_migrations(conn)


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


def _measure(meeting_video_id: int, *, status: str = "passed", method_version: int = 2, reason: str | None = None,
             offset_s=300.0, start_s=300.0, end_s=1500.0, stretch: int | None = None) -> None:
    """One stored row; `stretch` is named only when given, so the 042 shape still inserts."""
    columns = ["meeting_video_id", "granicus_clip_id", "method_version", "status", "reason",
               "offset_s", "granicus_start_s", "granicus_end_s", "score", "runner_up", "windows", "windows_confirmed"]
    values = [meeting_video_id, "2026", method_version, status, reason, offset_s, start_s, end_s, 49.5, 3.7, 4, 4]
    if stretch is not None:
        columns.append("stretch")
        values.append(stretch)
    with db_cursor() as cur:
        cur.execute(
            f"INSERT INTO meeting_video_alignments ({', '.join(columns)}) "
            f"VALUES ({', '.join(['%s'] * len(values))})",
            values,
        )


def _rows(meeting_video_id: int) -> list[tuple]:
    """(stretch, status, reason, method_version, offset_s) of a recording's rows, by stretch."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT stretch, status, reason, method_version, offset_s FROM meeting_video_alignments "
            "WHERE meeting_video_id = %s ORDER BY stretch", (meeting_video_id,))
        return [(r["stretch"], r["status"], r["reason"], r["method_version"], r["offset_s"]) for r in cur.fetchall()]


def _has_stretch_column() -> bool:
    with db_cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM information_schema.columns "
            "WHERE table_name = 'meeting_video_alignments' AND column_name = 'stretch'")
        return cur.fetchone()["n"] == 1


def test_046_up_keys_rows_on_recording_and_stretch_and_deletes_the_version_2_rejections(fresh_046):
    versions = [int(m.rsplit(".", 1)[-1].split("_")[0]) for m in runner.MIGRATIONS]
    assert MODULE in runner.MIGRATIONS and versions == sorted(versions)
    assert not _has_stretch_column()
    _, a = _recording("A")
    _measure(a)
    _, b = _recording("B")
    _measure(b, status="rejected", reason="windows")
    _, c = _recording("C")
    _measure(c, status="failed", reason="AudioFetchError: HTTP 404", offset_s=None, start_s=None, end_s=None)
    _, d = _recording("D")
    _measure(d, reason="operator", offset_s=948.84, start_s=948.84, end_s=3648.84)
    # Only the version the stretch rule can improve is deleted: a rejection at another version stays.
    _, e = _recording("E")
    _measure(e, status="rejected", method_version=3, reason="score")
    _, f = _recording("F")
    _measure(f, status="rejected", method_version=1, reason="conflict")

    with db() as conn:
        runner.apply_migrations(conn)

    assert _rows(a) == [(1, "passed", None, 2, 300.0)]
    assert _rows(b) == [], "a row rejected at version 2 is deleted, so the recording is measured again"
    assert _rows(c) == [(1, "failed", "AudioFetchError: HTTP 404", 2, None)]
    assert _rows(d) == [(1, "passed", "operator", 2, 948.84)], "the row passed by hand survives untouched"
    assert _rows(e) == [(1, "rejected", "score", 3, 300.0)]
    assert _rows(f) == [(1, "rejected", "conflict", 1, 300.0)]

    _measure(a, offset_s=490.0, start_s=1690.0, end_s=2000.0, stretch=2)
    assert _rows(a) == [(1, "passed", None, 2, 300.0), (2, "passed", None, 2, 490.0)]
    with pytest.raises(psycopg2.errors.UniqueViolation):
        _measure(a, offset_s=900.0, start_s=1500.0, end_s=1800.0, stretch=2)
    with pytest.raises(psycopg2.errors.CheckViolation):
        _measure(a, stretch=0)
    with pytest.raises(psycopg2.errors.CheckViolation):
        _measure(a, start_s=1500.0, end_s=1500.0, stretch=3)   # 042's passed-has-span CHECK still holds
    assert len(_rows(a)) == 2


def test_046_up_keeps_a_switched_off_row(fresh_046):
    """Plan `youtube-links-cover-matching-stretches`, M5: a `rejected` row with reason `operator`
    is a passed row the owner switched off, and the DELETE leaves it; a rejection with any other
    reason, or none, goes."""
    _, off = _recording("OFF")
    _measure(off, status="rejected", reason="operator", offset_s=635.48, start_s=635.5, end_s=4078.7)
    _, windows = _recording("WIN")
    _measure(windows, status="rejected", reason="windows")
    _, no_reason = _recording("NUL")
    _measure(no_reason, status="rejected", reason=None)

    with db() as conn:
        runner.apply_migrations(conn)

    assert _rows(off) == [(1, "rejected", "operator", 2, 635.48)]
    assert _rows(windows) == []
    assert _rows(no_reason) == []


def test_046_down_keeps_the_first_stretch_and_restores_the_single_key(applied_046):
    _, a = _recording("A")
    _measure(a, stretch=1)
    _measure(a, offset_s=490.0, start_s=1690.0, end_s=2000.0, stretch=2)

    with db() as conn:
        runner.rollback_migration(conn, 46)

    assert not _has_stretch_column()
    with db_cursor() as cur:
        cur.execute("SELECT offset_s FROM meeting_video_alignments WHERE meeting_video_id = %s", (a,))
        assert [r["offset_s"] for r in cur.fetchall()] == [300.0], "the first stretch is the one kept"
    with pytest.raises(psycopg2.errors.UniqueViolation):
        _measure(a, offset_s=490.0, start_s=1690.0, end_s=2000.0)

    with db() as conn:
        runner.apply_migrations(conn)

    assert _has_stretch_column()
    assert _rows(a) == [(1, "passed", None, 2, 300.0)]


def test_046_the_meeting_takes_every_stretch_along(applied_046):
    meeting_id, a = _recording("A")
    _measure(a, stretch=1)
    _measure(a, offset_s=490.0, start_s=1690.0, end_s=2000.0, stretch=2)
    assert len(_rows(a)) == 2

    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE id = %s", (meeting_id,))
        cur.execute("SELECT count(*) AS n FROM meeting_video_alignments WHERE meeting_video_id = %s", (a,))
        assert cur.fetchone()["n"] == 0
