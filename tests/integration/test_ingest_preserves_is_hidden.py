"""Regression test: _upsert_meetings does not touch meetings.is_hidden.

The daily ingest cron must NOT reset the operator hide. Migration 033's
column list and _upsert_meetings' enumerated UPDATE statement together
guarantee this — but the contract is critical, so pin it with a test.

Pattern mirrors tests/integration/test_ingest_reconciliation.py.
"""

from datetime import date

import pytest

from docket.config import DATABASE_URL
from docket.db import db
from docket.models.protocol import RawMeeting
from docket.services.ingest import _upsert_meetings


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Integration tests require local DB; will not run against Railway prod",
)


TEST_SLUG = "test_hide_preserve"


@pytest.fixture
def muni_id():
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO municipalities (slug, name, state, adapter_class, adapter_config, active)
            VALUES (%s, 'Test Hide Preserve', 'AL', 'GranicusAdapter',
                    '{"view_id": 1, "base_url": "https://example.com"}'::jsonb, TRUE)
            ON CONFLICT (slug) DO UPDATE SET active = TRUE
            RETURNING id
            """,
            (TEST_SLUG,),
        )
        mid = cur.fetchone()[0]
        cur.execute("DELETE FROM meetings WHERE municipality_id = %s", (mid,))
        conn.commit()
    yield mid
    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE municipality_id = %s", (mid,))
        conn.commit()


def _raw(external_id: str, title: str) -> RawMeeting:
    return RawMeeting(
        external_id=external_id,
        municipality_slug=TEST_SLUG,
        title=title,
        meeting_date=date(2026, 5, 18),
        meeting_type="council",
        agenda_url="https://example.com/a",
        minutes_url=None,
        video_url=None,
        source_url=f"https://example.com/m/{external_id}",
        start_time=None,
    )


def test_reingest_preserves_is_hidden(muni_id):
    # Ingest once → row exists with is_hidden=FALSE (default).
    _upsert_meetings(muni_id, [_raw("clip-1", "TEST_HIDE Preserve")])

    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE meetings SET is_hidden = TRUE WHERE municipality_id = %s "
            "RETURNING id, is_hidden",
            (muni_id,),
        )
        row = cur.fetchone()
        meeting_id = row[0]
        assert row[1] is True
        conn.commit()

    # Re-ingest the same external_id with a different title to force an UPDATE.
    _upsert_meetings(muni_id, [_raw("clip-1", "TEST_HIDE Preserve (revised title)")])

    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT is_hidden, title FROM meetings WHERE id = %s",
            (meeting_id,),
        )
        is_hidden, title = cur.fetchone()
    assert is_hidden is True, "is_hidden must survive re-ingest"
    assert "revised" in title, "title must have updated (proves ingest actually ran)"
