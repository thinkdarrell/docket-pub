"""Verify migration 034 adds the four columns and two indexes idempotently."""
import pytest
from docket.config import DATABASE_URL
from docket.db import db, db_cursor
from docket.migrations import runner


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Migration test must not run against Railway prod.",
)


@pytest.fixture
def fresh_ps_columns():
    """Roll the migration back before each test, apply fresh.

    Teardown re-applies 034 so the rest of the test suite (persistence,
    claim, rescan) always sees the columns and indexes in place.
    """
    with db() as conn:
        runner.rollback_migration(conn, 34)
    yield
    with db() as conn:
        runner.apply_migrations(conn)


def test_apply_adds_columns(fresh_ps_columns):
    with db() as conn:
        runner.apply_migrations(conn)
    with db_cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
             WHERE table_name = 'processing_status'
               AND column_name LIKE 'video_ocr%'
        """)
        cols = {r['column_name'] for r in cur.fetchall()}
    assert cols == {
        'video_ocr_scanned',
        'video_ocr_attempts',
        'video_ocr_last_attempted_at',
        'video_ocr_last_error',
    }


def test_apply_is_idempotent(fresh_ps_columns):
    with db() as conn:
        runner.apply_migrations(conn)
        runner.apply_migrations(conn)   # second apply must not raise
    with db_cursor() as cur:
        cur.execute("""
            SELECT indexname FROM pg_indexes
             WHERE tablename IN ('processing_status', 'votes')
               AND indexname IN ('idx_processing_status_ocr_pending', 'idx_votes_ocr_unique')
        """)
        idx = {r['indexname'] for r in cur.fetchall()}
    assert idx == {'idx_processing_status_ocr_pending', 'idx_votes_ocr_unique'}


def test_rollback_removes_columns_and_indexes(fresh_ps_columns):
    with db() as conn:
        runner.apply_migrations(conn)
        runner.rollback_migration(conn, 34)
    with db_cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
             WHERE table_name = 'processing_status'
               AND column_name LIKE 'video_ocr%'
        """)
        cols = [r['column_name'] for r in cur.fetchall()]
    assert cols == []

    with db_cursor() as cur:
        cur.execute("""
            SELECT indexname FROM pg_indexes
             WHERE indexname IN ('idx_processing_status_ocr_pending', 'idx_votes_ocr_unique')
        """)
        idx = [r['indexname'] for r in cur.fetchall()]
    assert idx == []
