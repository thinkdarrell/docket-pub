"""Cross-checks the SQL predicate in query.py against the Python helper in
meeting_time.py. If these two ever drift, this test catches it."""

import os
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from docket.db import db, db_cursor
from docket.services import query
from docket.services.meeting_time import is_upcoming


pytestmark = pytest.mark.skipif(
    "railway.internal" in os.environ.get("DATABASE_URL", ""),
    reason="Skip when DATABASE_URL points at Railway VPC (test wants laptop/CI DB).",
)


CT = ZoneInfo("America/Chicago")


@pytest.fixture
def municipality_id():
    """Isolated municipality for this test only. Cleans up cascading rows."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO municipalities (slug, name, state, active, adapter_class)
                VALUES ('al-upcoming-parity-test', 'Upcoming Parity Test', 'AL', TRUE, 'granicus')
                ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
                """
            )
            (mid,) = cur.fetchone()
            conn.commit()
    yield mid
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE municipality_id = %s", (mid,))
            cur.execute("DELETE FROM municipalities WHERE id = %s", (mid,))
            conn.commit()


def _insert_meeting(muni_id, *, days_offset, start_time=None, title="T"):
    """Insert a meeting at `today (CT) + days_offset`. Returns the row's
    (id, meeting_date, start_time) tuple."""
    meeting_date = (datetime.now(CT).date() + timedelta(days=days_offset))
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO meetings (
                    municipality_id, external_id, title, meeting_date,
                    meeting_type, source_url, start_time
                ) VALUES (%s, %s, %s, %s, 'council', 'https://x', %s)
                RETURNING id, meeting_date, start_time
                """,
                (muni_id, f"parity-{days_offset}-{start_time}", title, meeting_date, start_time),
            )
            row = cur.fetchone()
            conn.commit()
            return {"id": row[0], "meeting_date": row[1], "start_time": row[2]}


def test_future_meeting_appears_in_upcoming_and_not_recent(municipality_id):
    _insert_meeting(municipality_id, days_offset=2)
    upcoming = query.list_upcoming_meetings(days=7, limit=50)
    recent = query.list_recent_meetings(days=7, limit=50)
    assert any(m["municipality_id"] == municipality_id for m in upcoming)
    assert not any(m["municipality_id"] == municipality_id for m in recent)


def test_yesterday_meeting_appears_in_recent_and_not_upcoming(municipality_id):
    _insert_meeting(municipality_id, days_offset=-1)
    upcoming = query.list_upcoming_meetings(days=7, limit=50)
    recent = query.list_recent_meetings(days=7, limit=50)
    assert not any(m["municipality_id"] == municipality_id for m in upcoming)
    assert any(m["municipality_id"] == municipality_id for m in recent)


def test_python_helper_agrees_with_sql_for_a_grid_of_cases(municipality_id):
    """Insert meetings at varied (offset, start_time) combos and assert
    is_upcoming() membership matches list_upcoming_meetings membership.

    The whole point of having TWO definitions of the rule (Python + SQL) is
    that they should never disagree. This test pins that contract."""
    cases = [
        (0, None),            # today, no time → noon+3h cutoff
        (0, time(9, 0)),      # today 9am → 12pm cutoff
        (0, time(17, 30)),    # today 5:30pm → 8:30pm cutoff
        (-1, time(17, 30)),   # yesterday — always prior
        (1, time(9, 0)),      # tomorrow — always upcoming
    ]
    inserted = [
        _insert_meeting(municipality_id, days_offset=off, start_time=st,
                        title=f"case-{off}-{st}")
        for off, st in cases
    ]
    upcoming_ids = {
        m["id"] for m in query.list_upcoming_meetings(days=7, limit=50)
    }

    now = datetime.now(CT)
    mismatches = []
    for m in inserted:
        py = is_upcoming(m["meeting_date"], m["start_time"], now)
        sql = m["id"] in upcoming_ids
        if py != sql:
            mismatches.append({
                "meeting_date": m["meeting_date"],
                "start_time": m["start_time"],
                "python": py,
                "sql": sql,
            })
    assert not mismatches, f"SQL/Python disagreement: {mismatches}"
