"""Verify migration 036: has-event CHECK dropped, minutes_texts.last_checked_at added; down restores; re-up works."""
import pytest
from docket.config import DATABASE_URL
from docket.db import db, db_cursor
from docket.migrations import runner

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Migration test must not run against Railway prod.",
)


@pytest.fixture
def fresh_036():
    with db() as conn:
        runner.apply_migrations(conn)
        runner.rollback_migration(conn, 36)
    yield
    with db() as conn:
        runner.apply_migrations(conn)


def _constraint() -> dict | None:
    with db_cursor() as cur:
        cur.execute("""SELECT conname, convalidated FROM pg_constraint
                        WHERE conrelid = 'minutes_discrepancies'::regclass AND conname = 'minutes_discrepancies_has_event'""")
        row = cur.fetchone()
        return dict(row) if row else None


def _has_column() -> bool:
    with db_cursor() as cur:
        cur.execute("""SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'minutes_texts' AND column_name = 'last_checked_at'""")
        return cur.fetchone() is not None


def test_up_drops_constraint_and_adds_column(fresh_036):
    with db() as conn:
        runner.apply_migrations(conn)
    assert _constraint() is None
    assert _has_column()


def test_down_restores_constraint_not_valid_and_drops_column(fresh_036):
    with db() as conn:
        runner.apply_migrations(conn)
        runner.rollback_migration(conn, 36)
    c = _constraint()
    assert c is not None and c["convalidated"] is False
    assert not _has_column()


def test_down_tolerates_null_anchored_rows_and_reup_works(fresh_036):
    with db() as conn:
        runner.apply_migrations(conn)
    with db_cursor() as cur:
        cur.execute("SELECT id FROM meetings ORDER BY id LIMIT 1")
        meeting_id = cur.fetchone()["id"]
        cur.execute("""INSERT INTO minutes_discrepancies (meeting_id, category, severity, title, description, review_state,
                                                          prompt_version)
                       VALUES (%s, 'addition', 'minor', 'pytest-036', 'd', 'stale', 200) RETURNING id""", [meeting_id])
        did = cur.fetchone()["id"]
    try:
        with db() as conn:
            runner.rollback_migration(conn, 36)      # NOT VALID: the NULL-anchored stale row does not block the down
            runner.apply_migrations(conn)
        assert _constraint() is None and _has_column()
    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM minutes_discrepancies WHERE id = %s", [did])
