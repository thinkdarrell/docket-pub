"""Verify migration 035 creates the seven transcript tables idempotently."""
import pytest
from docket.config import DATABASE_URL
from docket.db import db, db_cursor
from docket.migrations import runner

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Migration test must not run against Railway prod.",
)

TABLES = {
    "transcripts", "transcript_speakers", "transcript_segments",
    "minutes_texts", "meeting_events", "minutes_discrepancies",
    "producer_heartbeats",
}


@pytest.fixture
def fresh_035():
    with db() as conn:
        runner.rollback_migration(conn, 35)
    yield
    with db() as conn:
        runner.apply_migrations(conn)


def _existing_tables() -> set[str]:
    with db_cursor() as cur:
        cur.execute("""
            SELECT table_name FROM information_schema.tables
             WHERE table_schema = 'public' AND table_name = ANY(%s)
        """, [sorted(TABLES)])
        return {r["table_name"] for r in cur.fetchall()}


def test_apply_creates_tables(fresh_035):
    with db() as conn:
        runner.apply_migrations(conn)
    assert _existing_tables() == TABLES


def test_apply_is_idempotent(fresh_035):
    with db() as conn:
        runner.apply_migrations(conn)
        runner.apply_migrations(conn)
    with db_cursor() as cur:
        cur.execute("""
            SELECT indexname FROM pg_indexes
             WHERE tablename = 'transcript_segments'
        """)
        idx = {r["indexname"] for r in cur.fetchall()}
    assert {"idx_transcript_segments_search", "idx_transcript_segments_trgm",
            "idx_transcript_segments_item"} <= idx


def test_segments_search_vector_is_generated(fresh_035):
    with db() as conn:
        runner.apply_migrations(conn)
    with db_cursor() as cur:
        cur.execute("""
            SELECT is_generated FROM information_schema.columns
             WHERE table_name = 'transcript_segments' AND column_name = 'search_vector'
        """)
        assert cur.fetchone()["is_generated"] == "ALWAYS"


def test_discrepancy_requires_one_event(fresh_035):
    import psycopg2
    with db() as conn:
        runner.apply_migrations(conn)
    with db_cursor() as cur:
        cur.execute("SELECT id FROM meetings ORDER BY id LIMIT 1")
        meeting_id = cur.fetchone()["id"]
    with pytest.raises(psycopg2.errors.CheckViolation):
        with db_cursor() as cur:
            cur.execute("""
                INSERT INTO minutes_discrepancies
                    (meeting_id, category, severity, title, description, prompt_version)
                VALUES (%s, 'sequence', 'material', 't', 'd', 200)
            """, [meeting_id])


def test_rollback_removes_tables(fresh_035):
    with db() as conn:
        runner.apply_migrations(conn)
        runner.rollback_migration(conn, 35)
    assert _existing_tables() == set()
