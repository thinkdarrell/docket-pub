"""Tests asserting every citizen-facing meeting/item query excludes
rows with meetings.is_hidden=TRUE.

One file covers Tasks 4-9 (every patched function). Seed two meetings
per scenario: one visible, one hidden. Assert only the visible one
surfaces. Cleanup is title-prefixed for idempotency.

Pattern mirrors tests/unit/test_query_related_items.py.
"""

import pytest
import psycopg2.extras

from docket.db import db
from docket.services import query


TEST_PREFIX = "TEST_HIDE_"


def _cleanup():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM agenda_items "
                "WHERE meeting_id IN (SELECT id FROM meetings WHERE title LIKE %s)",
                (f"{TEST_PREFIX}%",),
            )
            cur.execute(
                "DELETE FROM meetings WHERE title LIKE %s",
                (f"{TEST_PREFIX}%",),
            )
        conn.commit()


@pytest.fixture
def hidden_meeting_seed():
    """Two BHM meetings on consecutive dates — one visible, one hidden.

    Yields a dict with the two meeting ids and the city slug.
    """
    _cleanup()
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id, slug FROM municipalities WHERE slug = 'birmingham'")
            row = cur.fetchone()
            muni_id, slug = row["id"], row["slug"]

            cur.execute(
                """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type, is_hidden)
                   VALUES (%s, %s, '2099-04-01', 'council', FALSE) RETURNING id""",
                (muni_id, f"{TEST_PREFIX}visible"),
            )
            visible_id = cur.fetchone()["id"]

            cur.execute(
                """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type, is_hidden)
                   VALUES (%s, %s, '2099-04-02', 'council', TRUE) RETURNING id""",
                (muni_id, f"{TEST_PREFIX}hidden"),
            )
            hidden_id = cur.fetchone()["id"]
        conn.commit()
    yield {"visible_id": visible_id, "hidden_id": hidden_id, "slug": slug, "muni_id": muni_id}
    _cleanup()


# ---------------------------------------------------------------------------
# Task 4 — list_meetings + dashboard_stats + city-scoped recent/upcoming
# ---------------------------------------------------------------------------


def test_list_meetings_excludes_hidden(hidden_meeting_seed):
    result = query.list_meetings(hidden_meeting_seed["slug"], since="2099-01-01")
    ids = {m.id for m in result.meetings}
    assert hidden_meeting_seed["visible_id"] in ids
    assert hidden_meeting_seed["hidden_id"] not in ids


def test_list_meetings_count_excludes_hidden(hidden_meeting_seed):
    result = query.list_meetings(hidden_meeting_seed["slug"], since="2099-01-01")
    # Count reflects only visible; we expect exactly the one we seeded plus whatever's
    # already in the DB after 2099-01-01 (which should be zero in a clean test DB,
    # but we assert weakly to allow accidental future seeds: hidden never counted).
    visible = [m for m in result.meetings if m.title.startswith(TEST_PREFIX)]
    assert len(visible) == 1


def test_dashboard_stats_excludes_hidden_meetings_and_their_items_and_votes(hidden_meeting_seed):
    """dashboard_stats returns dict with keys 'municipalities', 'meetings',
    'agenda_items', 'votes' (verified by reading query.py:446-451). All three
    of meetings/agenda_items/votes must exclude rows belonging to hidden
    meetings, not just the meetings count itself."""
    hidden_item_id = None
    hidden_vote_id = None
    try:
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO agenda_items
                     (meeting_id, title, item_number, processing_status)
                   VALUES (%s, 'TEST_HIDE_stats_item', '1', 'pending')
                   RETURNING id""",
                (hidden_meeting_seed["hidden_id"],),
            )
            hidden_item_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO votes
                     (meeting_id, result, yeas, nays, abstentions, source, confidence)
                   VALUES (%s, 'passed', 7, 0, 0, 'test', 'high')
                   RETURNING id""",
                (hidden_meeting_seed["hidden_id"],),
            )
            hidden_vote_id = cur.fetchone()[0]
            conn.commit()

        stats = query.dashboard_stats()
        with db() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM meetings WHERE is_hidden = FALSE")
            expected_meetings = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM agenda_items ai "
                "JOIN meetings m ON ai.meeting_id = m.id "
                "WHERE m.is_hidden = FALSE"
            )
            expected_items = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM votes v "
                "JOIN meetings m ON v.meeting_id = m.id "
                "WHERE m.is_hidden = FALSE"
            )
            expected_votes = cur.fetchone()[0]
        assert stats["meetings"] == expected_meetings
        assert stats["agenda_items"] == expected_items
        assert stats["votes"] == expected_votes
    finally:
        with db() as conn, conn.cursor() as cur:
            if hidden_vote_id is not None:
                cur.execute("DELETE FROM votes WHERE id = %s", (hidden_vote_id,))
            if hidden_item_id is not None:
                cur.execute("DELETE FROM agenda_items WHERE id = %s", (hidden_item_id,))
            conn.commit()


def test_list_recent_meetings_for_city_excludes_hidden(hidden_meeting_seed):
    # The function filters by date window — we seeded 2099 dates so the recent
    # window won't include them by date alone. Re-seed with a recent date.
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE meetings SET meeting_date = CURRENT_DATE - 1 WHERE id = %s",
            (hidden_meeting_seed["visible_id"],),
        )
        cur.execute(
            "UPDATE meetings SET meeting_date = CURRENT_DATE - 1 WHERE id = %s",
            (hidden_meeting_seed["hidden_id"],),
        )
        conn.commit()
    rows = query.list_recent_meetings_for_city(
        hidden_meeting_seed["slug"], days=7, limit=20
    )
    ids = {r["id"] for r in rows}
    assert hidden_meeting_seed["visible_id"] in ids
    assert hidden_meeting_seed["hidden_id"] not in ids


def test_list_upcoming_meetings_for_city_excludes_hidden(hidden_meeting_seed):
    # Push both seeded rows into the upcoming window (future-dated, no recording yet).
    # _UPCOMING_PREDICATE_MT keys off video presence / status; the fixture inserts
    # nothing in video_url so future-dated rows fall into "upcoming".
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE meetings SET meeting_date = CURRENT_DATE + 3 WHERE id = %s",
            (hidden_meeting_seed["visible_id"],),
        )
        cur.execute(
            "UPDATE meetings SET meeting_date = CURRENT_DATE + 3 WHERE id = %s",
            (hidden_meeting_seed["hidden_id"],),
        )
        conn.commit()
    rows = query.list_upcoming_meetings_for_city(
        hidden_meeting_seed["slug"], days=14, limit=20
    )
    ids = {r["id"] for r in rows}
    assert hidden_meeting_seed["visible_id"] in ids
    assert hidden_meeting_seed["hidden_id"] not in ids
