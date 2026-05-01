"""Tests for the worker's claim queries (item readiness, meeting two-phase)."""

from datetime import datetime, timedelta, timezone

import pytest

from docket.ai.prompts import ITEM_PROMPT_VERSION, MEETING_PROMPT_VERSION
from docket.ai.worker import claim_items_sql, claim_meetings_sql
from docket.db import db


@pytest.fixture
def fresh_db():
    """Clean agenda_items / meetings rows before each test."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM vote_agenda_items")
            cur.execute("DELETE FROM member_votes")
            cur.execute("DELETE FROM votes")
            cur.execute("DELETE FROM agenda_items")
            cur.execute("DELETE FROM meetings WHERE municipality_id IN (SELECT id FROM municipalities WHERE slug LIKE 'test_%')")
        conn.commit()
        yield conn


def _seed_item(conn, *, meeting_id, title="t", created_minutes_ago=10,
                ai_prompt_version=None):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO agenda_items (meeting_id, title, is_consent, ai_prompt_version, created_at)
            VALUES (%s, %s, FALSE, %s, NOW() - (%s || ' minutes')::interval)
            RETURNING id
        """, (meeting_id, title, ai_prompt_version, created_minutes_ago))
        return cur.fetchone()[0]


def _seed_meeting(conn, *, slug="test_city", minutes_adopted_at=None, ai_prompt_version=None,
                   ai_metadata=None):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO municipalities (slug, name, state, adapter_class, active)
            VALUES (%s, %s, 'AL', 'GranicusAdapter', TRUE)
            ON CONFLICT (slug) DO UPDATE SET active = TRUE
            RETURNING id
        """, (slug, slug.replace("_", " ").title()))
        muni_id = cur.fetchone()[0]
        cur.execute("""
            INSERT INTO meetings (municipality_id, title, meeting_type, meeting_date, source_url,
                                   minutes_adopted_at, ai_prompt_version, ai_metadata)
            VALUES (%s, 'Test Meeting', 'Council Meeting', CURRENT_DATE, 'https://x', %s, %s, %s)
            RETURNING id
        """, (muni_id, minutes_adopted_at, ai_prompt_version, ai_metadata))
        return cur.fetchone()[0]


def test_claim_items_skips_recent_rows(fresh_db):
    """Items younger than 5 min are not claimed (debounce)."""
    m_id = _seed_meeting(fresh_db)
    young = _seed_item(fresh_db, meeting_id=m_id, created_minutes_ago=2)
    old = _seed_item(fresh_db, meeting_id=m_id, created_minutes_ago=30)
    fresh_db.commit()

    with fresh_db.cursor() as cur:
        cur.execute(claim_items_sql(), (ITEM_PROMPT_VERSION, 5, 100))
        ids = [row[0] for row in cur.fetchall()]
    assert old in ids
    assert young not in ids


def test_claim_items_skips_already_current(fresh_db):
    """Items at current ai_prompt_version are not re-claimed."""
    m_id = _seed_meeting(fresh_db)
    pending = _seed_item(fresh_db, meeting_id=m_id, ai_prompt_version=None)
    current = _seed_item(fresh_db, meeting_id=m_id, ai_prompt_version=ITEM_PROMPT_VERSION)
    stale = _seed_item(fresh_db, meeting_id=m_id, ai_prompt_version=ITEM_PROMPT_VERSION - 1) if ITEM_PROMPT_VERSION > 1 else None
    fresh_db.commit()

    with fresh_db.cursor() as cur:
        cur.execute(claim_items_sql(), (ITEM_PROMPT_VERSION, 5, 100))
        ids = [row[0] for row in cur.fetchall()]
    assert pending in ids
    if stale is not None:
        assert stale in ids
    assert current not in ids


def test_claim_meetings_provisional_phase(fresh_db):
    """Meeting with all items processed and minutes_adopted_at NULL is claimable for provisional pass."""
    m_id = _seed_meeting(fresh_db, slug="test_provisional", minutes_adopted_at=None)
    _seed_item(fresh_db, meeting_id=m_id, ai_prompt_version=ITEM_PROMPT_VERSION)
    fresh_db.commit()

    with fresh_db.cursor() as cur:
        cur.execute(claim_meetings_sql(), (MEETING_PROMPT_VERSION, ITEM_PROMPT_VERSION, 100000))
        ids = [row[0] for row in cur.fetchall()]
    assert m_id in ids


def test_claim_meetings_blocked_by_pending_items(fresh_db):
    """A meeting with one item not yet AI-processed is NOT claimable."""
    m_id = _seed_meeting(fresh_db, slug="test_blocked")
    _seed_item(fresh_db, meeting_id=m_id, ai_prompt_version=ITEM_PROMPT_VERSION)
    _seed_item(fresh_db, meeting_id=m_id, ai_prompt_version=None)   # blocker
    fresh_db.commit()

    with fresh_db.cursor() as cur:
        cur.execute(claim_meetings_sql(), (MEETING_PROMPT_VERSION, ITEM_PROMPT_VERSION, 100000))
        ids = [row[0] for row in cur.fetchall()]
    assert m_id not in ids


def test_claim_meetings_adopted_phase_overrides(fresh_db):
    """Meeting with minutes_adopted_at set and phase=provisional is re-claimable."""
    import json
    m_id = _seed_meeting(
        fresh_db, slug="test_adopted",
        minutes_adopted_at=datetime.now(timezone.utc),
        ai_prompt_version=MEETING_PROMPT_VERSION,
        ai_metadata=json.dumps({"phase": "provisional"}),
    )
    _seed_item(fresh_db, meeting_id=m_id, ai_prompt_version=ITEM_PROMPT_VERSION)
    fresh_db.commit()

    with fresh_db.cursor() as cur:
        cur.execute(claim_meetings_sql(), (MEETING_PROMPT_VERSION, ITEM_PROMPT_VERSION, 100000))
        ids = [row[0] for row in cur.fetchall()]
    assert m_id in ids
