"""Verify migration 043: `city_calendar_events.event_status` and Birmingham's calendar-source metadata; down removes both.

Pattern: tests/integration/test_040_migration.py. Plan `committee-clips-named-or-hidden`, M1.
"""
import importlib

import pytest
from docket.config import DATABASE_URL
from docket.db import db, db_cursor
from docket.migrations import runner

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Migration test must not run against Railway prod.",
)

NEW_KEYS = {
    "calendar_search_url": "https://www.birminghamal.gov/api/search/events",
    "calendar_department_id": "55",
    "calendar_department": "City Council",
    "calendar_sitemap_url": "https://www.birminghamal.gov/sitemap.xml",
    "calendar_complete_from": "2026-10-05",
}


@pytest.fixture
def fresh_043():
    """Every migration applied, then 043 rolled back; the teardown re-applies it."""
    with db() as conn:
        runner.apply_migrations(conn)
        runner.rollback_migration(conn, 43)
    yield
    with db() as conn:
        runner.apply_migrations(conn)


def _has_status_column() -> bool:
    with db_cursor() as cur:
        cur.execute(
            "SELECT is_nullable, data_type FROM information_schema.columns "
            "WHERE table_name = 'city_calendar_events' AND column_name = 'event_status'"
        )
        row = cur.fetchone()
    return row is not None and row["is_nullable"] == "YES" and row["data_type"] == "text"


def _birmingham_meta() -> dict:
    with db_cursor() as cur:
        cur.execute("SELECT metadata FROM municipalities WHERE slug = 'birmingham'")
        return cur.fetchone()["metadata"]


def test_043_is_registered_last_or_before_a_later_number():
    versions = [int(m.rsplit(".", 1)[-1].split("_")[0]) for m in runner.MIGRATIONS]
    assert 43 in versions
    assert versions == sorted(versions)
    assert importlib.import_module("docket.migrations.043_calendar_sources").SQL_DOWN.strip()


def test_043_up_adds_the_column_and_the_metadata(fresh_043):
    assert not _has_status_column()
    assert not (set(NEW_KEYS) & set(_birmingham_meta()))

    with db() as conn:
        runner.apply_migrations(conn)

    assert _has_status_column()
    meta = _birmingham_meta()
    assert {k: meta.get(k) for k in NEW_KEYS} == NEW_KEYS
    assert meta["calendar_url"] == "https://www.birminghamal.gov/government/city-council", "038's key is untouched"
    with db_cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM municipalities WHERE metadata ?| %s AND slug <> 'birmingham'",
            (list(NEW_KEYS),),
        )
        assert cur.fetchone()["n"] == 0, "only Birmingham gains the keys"


def test_043_existing_events_have_no_status(fresh_043):
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham'")
        mid = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO city_calendar_events (municipality_id, source_event_id, title, starts_at, source_url) "
            "VALUES (%s, 'm043-before', 'X COMMITTEE MEETING', now(), 'https://example.test/e') RETURNING id",
            (mid,),
        )
    try:
        with db() as conn:
            runner.apply_migrations(conn)
        with db_cursor() as cur:
            cur.execute("SELECT event_status FROM city_calendar_events WHERE source_event_id = 'm043-before'")
            assert cur.fetchone()["event_status"] is None
    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM city_calendar_events WHERE source_event_id = 'm043-before'")


def test_043_down_removes_the_column_and_the_keys(fresh_043):
    with db() as conn:
        runner.apply_migrations(conn)
        runner.rollback_migration(conn, 43)
    assert not _has_status_column()
    meta = _birmingham_meta()
    assert not (set(NEW_KEYS) & set(meta))
    assert "calendar_url" in meta and "council_schedule" in meta, "038's keys survive the down"
    assert "youtube_channel_id" in meta, "040's key survives the down"
