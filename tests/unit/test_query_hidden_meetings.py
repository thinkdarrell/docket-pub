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


# ---------------------------------------------------------------------------
# Task 5 — cross-city recent/upcoming + search_meetings
# ---------------------------------------------------------------------------


def test_list_recent_meetings_cross_city_excludes_hidden(hidden_meeting_seed):
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE meetings SET meeting_date = CURRENT_DATE - 1 WHERE id IN (%s, %s)",
            (hidden_meeting_seed["visible_id"], hidden_meeting_seed["hidden_id"]),
        )
        conn.commit()
    rows = query.list_recent_meetings(days=7, limit=50)
    ids = {r["id"] for r in rows}
    assert hidden_meeting_seed["visible_id"] in ids
    assert hidden_meeting_seed["hidden_id"] not in ids


def test_list_upcoming_meetings_cross_city_excludes_hidden(hidden_meeting_seed):
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE meetings SET meeting_date = CURRENT_DATE + 3 WHERE id IN (%s, %s)",
            (hidden_meeting_seed["visible_id"], hidden_meeting_seed["hidden_id"]),
        )
        conn.commit()
    rows = query.list_upcoming_meetings(days=14, limit=50)
    ids = {r["id"] for r in rows}
    assert hidden_meeting_seed["visible_id"] in ids
    assert hidden_meeting_seed["hidden_id"] not in ids


def test_search_meetings_excludes_hidden(hidden_meeting_seed):
    # Seed sets titles to TEST_HIDE_visible / TEST_HIDE_hidden — search for the
    # shared substring. Hidden one must not appear in results.
    results = query.search_meetings("TEST_HIDE", municipality_slug=hidden_meeting_seed["slug"])
    ids = {r["id"] for r in results}
    assert hidden_meeting_seed["visible_id"] in ids
    assert hidden_meeting_seed["hidden_id"] not in ids


# ---------------------------------------------------------------------------
# Task 6 — item-level queries
# ---------------------------------------------------------------------------


def _seed_item(meeting_id: int, *, title: str = "TEST_HIDE_item", topic: str = "housing",
               sponsor: str = "TEST_HIDE_sponsor") -> int:
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO agenda_items
                 (meeting_id, title, topic, sponsor, item_number, processing_status)
               VALUES (%s, %s, %s, %s, '1', 'pending') RETURNING id""",
            (meeting_id, title, topic, sponsor),
        )
        iid = cur.fetchone()[0]
        conn.commit()
    return iid


def test_get_agenda_item_returns_none_when_parent_hidden(hidden_meeting_seed):
    # Item belongs to the hidden meeting — public read path must return None.
    iid = _seed_item(hidden_meeting_seed["hidden_id"])
    assert query.get_agenda_item(iid) is None


def test_get_agenda_item_returns_visible(hidden_meeting_seed):
    iid = _seed_item(hidden_meeting_seed["visible_id"])
    item = query.get_agenda_item(iid)
    assert item is not None and item.id == iid


def test_search_agenda_items_excludes_hidden_parent(hidden_meeting_seed):
    visible_item_id = _seed_item(
        hidden_meeting_seed["visible_id"], title="TEST_HIDE_search visible"
    )
    hidden_item_id = _seed_item(
        hidden_meeting_seed["hidden_id"], title="TEST_HIDE_search hidden"
    )
    results = query.search_agenda_items(
        "TEST_HIDE_search", municipality_slug=hidden_meeting_seed["slug"]
    )
    ids = {r.id for r in results}
    assert visible_item_id in ids
    assert hidden_item_id not in ids


def test_list_agenda_items_by_topic_excludes_hidden_parent(hidden_meeting_seed):
    visible_item_id = _seed_item(
        hidden_meeting_seed["visible_id"], topic="TEST_HIDE_topic"
    )
    hidden_item_id = _seed_item(
        hidden_meeting_seed["hidden_id"], topic="TEST_HIDE_topic"
    )
    results = query.list_agenda_items_by_topic(
        "TEST_HIDE_topic", municipality_slug=hidden_meeting_seed["slug"]
    )
    ids = {r["id"] for r in results}
    assert visible_item_id in ids
    assert hidden_item_id not in ids


def test_list_related_items_by_topic_excludes_hidden_parent(hidden_meeting_seed):
    # Seed: visible meeting has the seed item; another visible meeting has a
    # match; the hidden meeting has a would-be match that must NOT surface.
    with db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type, is_hidden)
               VALUES (%s, %s, '2099-04-03', 'council', FALSE) RETURNING id""",
            (hidden_meeting_seed["muni_id"], "TEST_HIDE_other_visible"),
        )
        other_visible_id = cur.fetchone()["id"]
        conn.commit()

    seed_item_id = _seed_item(
        hidden_meeting_seed["visible_id"], topic="TEST_HIDE_rel"
    )
    other_visible_item_id = _seed_item(other_visible_id, topic="TEST_HIDE_rel")
    hidden_item_id = _seed_item(
        hidden_meeting_seed["hidden_id"], topic="TEST_HIDE_rel"
    )

    related = query.list_related_items_by_topic(seed_item_id, limit=10)
    ids = {r["id"] for r in related}
    assert other_visible_item_id in ids
    assert hidden_item_id not in ids


def test_list_related_items_by_sponsor_excludes_hidden_parent(hidden_meeting_seed):
    seed_item_id = _seed_item(
        hidden_meeting_seed["visible_id"], sponsor="TEST_HIDE_sponsor_X"
    )
    hidden_item_id = _seed_item(
        hidden_meeting_seed["hidden_id"], sponsor="TEST_HIDE_sponsor_X"
    )
    # Add a second visible match so the function returns at least one result.
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type, is_hidden)
               VALUES (%s, %s, '2099-04-04', 'council', FALSE) RETURNING id""",
            (hidden_meeting_seed["muni_id"], "TEST_HIDE_sponsor_match"),
        )
        match_meeting_id = cur.fetchone()[0]
        conn.commit()
    visible_match_id = _seed_item(match_meeting_id, sponsor="TEST_HIDE_sponsor_X")

    related = query.list_related_items_by_sponsor(seed_item_id, limit=10)
    ids = {r["id"] for r in related}
    assert visible_match_id in ids
    assert hidden_item_id not in ids
