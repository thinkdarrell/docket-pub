"""Tests for query.list_related_items_by_topic + list_related_items_by_sponsor.

Pattern mirrors test_query_list_votes.py: real DB, TEST_REL_ prefixed rows,
idempotent fixture cleanup.
"""

import pytest
import psycopg2.extras

from docket.db import db
from docket.services.query import (
    list_related_items_by_topic,
    list_related_items_by_sponsor,
)


def _cleanup() -> None:
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE title LIKE 'TEST_REL_%'")
        conn.commit()


@pytest.fixture
def related_items_seed():
    """Three meetings in one city, one item per meeting + extras.

    Meeting A: seed item (topic=housing, sponsor='Wardine Alexander')
               sibling item (topic=housing, same meeting — must be excluded)
    Meeting B: matching item (topic=housing, sponsor='Wardine Alexander')
    Meeting C: matching item (topic=housing, different sponsor)
               + withdrawn item (topic=housing — must be excluded)

    Plus a different-topic distractor item in Meeting B.
    """
    _cleanup()
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id FROM municipalities ORDER BY id LIMIT 1")
            muni_id = cur.fetchone()["id"]

            meetings = []
            for label, mdate in [("A", "2099-01-01"), ("B", "2099-02-01"), ("C", "2099-03-01")]:
                cur.execute(
                    """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type)
                       VALUES (%s, %s, %s, 'council') RETURNING id""",
                    (muni_id, f"TEST_REL_{label}", mdate),
                )
                meetings.append(cur.fetchone()["id"])
            mA, mB, mC = meetings

            cur.execute(
                """INSERT INTO agenda_items
                       (meeting_id, title, topic, sponsor, item_number, processing_status)
                   VALUES
                       (%s, 'seed item',     'housing',  'Wardine Alexander', '1', 'pending'),
                       (%s, 'A sibling',     'housing',  'Other Person',      '2', 'pending'),
                       (%s, 'B match',       'housing',  'Wardine Alexander', '1', 'pending'),
                       (%s, 'B distractor',  'public_safety', 'Wardine Alexander', '2', 'pending'),
                       (%s, 'C match',       'housing',  'Different Sponsor', '1', 'pending'),
                       (%s, 'C withdrawn',   'housing',  'Wardine Alexander', '2', 'withdrawn')
                   RETURNING id, title""",
                (mA, mA, mB, mB, mC, mC),
            )
            rows = cur.fetchall()
        conn.commit()

    by_title = {r["title"]: r["id"] for r in rows}
    yield {"seed_id": by_title["seed item"], "ids": by_title}
    _cleanup()


def test_list_related_items_by_topic_basic(related_items_seed):
    seed_id = related_items_seed["seed_id"]
    rows = list_related_items_by_topic(seed_id, limit=10)

    titles = [r["title"] for r in rows]
    assert "B match" in titles
    assert "C match" in titles
    # excludes seed itself
    assert "seed item" not in titles
    # excludes sibling from same meeting
    assert "A sibling" not in titles
    # excludes different-topic distractor
    assert "B distractor" not in titles
    # excludes withdrawn
    assert "C withdrawn" not in titles


def test_list_related_items_by_topic_orders_by_recent(related_items_seed):
    seed_id = related_items_seed["seed_id"]
    rows = list_related_items_by_topic(seed_id, limit=10)
    # meeting_date DESC → C (2099-03) first, then B (2099-02)
    assert rows[0]["title"] == "C match"
    assert rows[1]["title"] == "B match"


def test_list_related_items_by_topic_respects_limit(related_items_seed):
    seed_id = related_items_seed["seed_id"]
    rows = list_related_items_by_topic(seed_id, limit=1)
    assert len(rows) == 1
    assert rows[0]["title"] == "C match"  # most recent


def test_list_related_items_by_topic_no_topic_returns_empty():
    """Seed with no topic → return []."""
    _cleanup()
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id FROM municipalities ORDER BY id LIMIT 1")
            muni_id = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type)
                   VALUES (%s, 'TEST_REL_notopic', '2099-04-01', 'council') RETURNING id""",
                (muni_id,),
            )
            mid = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO agenda_items (meeting_id, title, topic, item_number)
                   VALUES (%s, 'no-topic seed', NULL, '1') RETURNING id""",
                (mid,),
            )
            seed_id = cur.fetchone()["id"]
        conn.commit()

    assert list_related_items_by_topic(seed_id) == []
    _cleanup()


def test_list_related_items_by_topic_unknown_id_returns_empty():
    assert list_related_items_by_topic(-1) == []


def test_list_related_items_by_sponsor_basic(related_items_seed):
    seed_id = related_items_seed["seed_id"]
    rows = list_related_items_by_sponsor(seed_id, limit=10)

    titles = [r["title"] for r in rows]
    assert "B match" in titles  # same sponsor "Wardine Alexander"
    # Note: "B distractor" is also same sponsor (different topic), should also match
    assert "B distractor" in titles
    # excludes seed
    assert "seed item" not in titles
    # excludes sibling-in-same-meeting (different sponsor in fixture)
    assert "A sibling" not in titles
    # excludes different-sponsor C match
    assert "C match" not in titles
    # excludes withdrawn even if sponsor matches
    assert "C withdrawn" not in titles


def test_list_related_items_by_sponsor_no_sponsor_returns_empty():
    _cleanup()
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id FROM municipalities ORDER BY id LIMIT 1")
            muni_id = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type)
                   VALUES (%s, 'TEST_REL_nosponsor', '2099-04-01', 'council') RETURNING id""",
                (muni_id,),
            )
            mid = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO agenda_items (meeting_id, title, sponsor, item_number)
                   VALUES (%s, 'no-sponsor seed', NULL, '1') RETURNING id""",
                (mid,),
            )
            seed_id = cur.fetchone()["id"]
        conn.commit()

    assert list_related_items_by_sponsor(seed_id) == []
    _cleanup()


def test_list_related_items_by_sponsor_unknown_id_returns_empty():
    assert list_related_items_by_sponsor(-1) == []
