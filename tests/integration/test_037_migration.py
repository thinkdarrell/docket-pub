"""Verify migration 037: city_briefing_facts exists and Birmingham carries the briefing flag; down removes both."""
import pytest
from docket.config import DATABASE_URL
from docket.db import db, db_cursor
from docket.migrations import runner

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Migration test must not run against Railway prod.",
)


@pytest.fixture
def fresh_037():
    with db() as conn:
        runner.apply_migrations(conn)
        runner.rollback_migration(conn, 37)
    yield
    with db() as conn:
        runner.apply_migrations(conn)


def _table_exists() -> bool:
    with db_cursor() as cur:
        cur.execute("SELECT to_regclass('public.city_briefing_facts') AS t")
        return cur.fetchone()["t"] is not None


def _birmingham_flag():
    with db_cursor() as cur:
        cur.execute("SELECT metadata -> 'briefing' AS flag FROM municipalities WHERE slug = 'birmingham'")
        return cur.fetchone()["flag"]


def test_037_up_sets_flag_and_creates_table(fresh_037):
    assert not _table_exists()
    assert _birmingham_flag() is None
    with db() as conn:
        runner.apply_migrations(conn)
    assert _table_exists()
    assert _birmingham_flag() is True
    with db_cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM municipalities WHERE metadata @> '{\"briefing\": true}'::jsonb")
        assert cur.fetchone()["n"] == 1, "only Birmingham is flagged"


def test_037_down_removes_both(fresh_037):
    with db() as conn:
        runner.apply_migrations(conn)
        runner.rollback_migration(conn, 37)
    assert not _table_exists()
    assert _birmingham_flag() is None
    with db_cursor() as cur:
        cur.execute("SELECT metadata FROM municipalities WHERE slug = 'birmingham'")
        meta = cur.fetchone()["metadata"]
    assert "council_type" in meta, "the other metadata keys survive the down"
