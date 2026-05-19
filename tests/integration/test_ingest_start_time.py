"""Persistence of meetings.start_time via the ingest pipeline."""

from datetime import date, time

import pytest

from docket.config import DATABASE_URL
from docket.db import db, db_cursor
from docket.models.protocol import RawMeeting
from docket.services.ingest import _upsert_meetings


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Integration tests require local DB; will not run against Railway prod",
)


TEST_SLUG = "al-ingest-start-time-test"


@pytest.fixture
def municipality_id():
    """Create an isolated test municipality. Cleans up cascading rows on teardown."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO municipalities (slug, name, state, adapter_class, adapter_config, active)
                VALUES (%s, 'Ingest Start Time Test', 'AL', 'GranicusAdapter',
                        '{"view_id": 1, "base_url": "https://example.com"}'::jsonb, TRUE)
                ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
                """,
                (TEST_SLUG,),
            )
            (mid,) = cur.fetchone()
            cur.execute("DELETE FROM meetings WHERE municipality_id = %s", (mid,))
    yield mid
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE municipality_id = %s", (mid,))
            cur.execute("DELETE FROM municipalities WHERE id = %s", (mid,))


def _raw(external_id, start_time, *, municipality_slug=TEST_SLUG):
    return RawMeeting(
        external_id=external_id,
        municipality_slug=municipality_slug,
        title="Test Council",
        meeting_date=date(2026, 5, 20),
        meeting_type="council",
        agenda_url=None,
        minutes_url=None,
        video_url=None,
        source_url="https://example.com",
        start_time=start_time,
    )


def test_upsert_meetings_persists_start_time(municipality_id):
    rm = _raw("event-99999", time(17, 30))
    inserted, updated = _upsert_meetings(municipality_id, [rm])
    assert inserted == 1
    with db_cursor() as cur:
        cur.execute(
            "SELECT start_time FROM meetings WHERE municipality_id = %s AND external_id = %s",
            (municipality_id, "event-99999"),
        )
        row = cur.fetchone()
        assert row["start_time"] == time(17, 30)


def test_upsert_meetings_updates_start_time_when_provided(municipality_id):
    """Adapter posts a corrected time on re-ingest — UPDATE picks it up."""
    _upsert_meetings(municipality_id, [_raw("event-99998", time(17, 30))])
    inserted, updated = _upsert_meetings(municipality_id, [_raw("event-99998", time(18, 0))])
    assert updated == 1
    with db_cursor() as cur:
        cur.execute(
            "SELECT start_time FROM meetings WHERE municipality_id = %s AND external_id = %s",
            (municipality_id, "event-99998"),
        )
        row = cur.fetchone()
        assert row["start_time"] == time(18, 0)


def test_upsert_meetings_preserves_start_time_when_reingest_returns_null(municipality_id):
    """COALESCE — a re-ingest from an adapter that didn't capture a time must
    NOT wipe a previously-captured value."""
    _upsert_meetings(municipality_id, [_raw("event-99997", time(17, 30))])
    _upsert_meetings(municipality_id, [_raw("event-99997", None)])
    with db_cursor() as cur:
        cur.execute(
            "SELECT start_time FROM meetings WHERE municipality_id = %s AND external_id = %s",
            (municipality_id, "event-99997"),
        )
        row = cur.fetchone()
        assert row["start_time"] == time(17, 30)
