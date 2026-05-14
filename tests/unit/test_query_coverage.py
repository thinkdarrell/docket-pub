# tests/unit/test_query_coverage.py
"""Unit tests for editorial coverage read helpers."""
from __future__ import annotations

from datetime import datetime

from docket.models.coverage import CoverageEntry, Outlet


def test_coverage_entry_display_byline_uses_snapshot_when_set():
    entry = CoverageEntry(
        id=1, kind='note', status='published', source='manual',
        body='test', partner_credit=None,
        outlet_id=None, external_url=None, headline=None,
        reporter_byline=None, excerpt=None, article_published_at=None,
        author_id=1, byline='Darrell Nance',
        created_at=datetime.now(), updated_at=datetime.now(),
        published_at=datetime.now(), featured_until=None,
        author_display_name='changed-after-publish', author_username='darrell',
    )
    assert entry.display_byline() == 'Darrell Nance'


def test_coverage_entry_display_byline_falls_back_to_display_name_when_null():
    entry = CoverageEntry(
        id=1, kind='note', status='draft', source='manual',
        body='test', partner_credit=None,
        outlet_id=None, external_url=None, headline=None,
        reporter_byline=None, excerpt=None, article_published_at=None,
        author_id=1, byline=None,
        created_at=datetime.now(), updated_at=datetime.now(),
        published_at=None, featured_until=None,
        author_display_name='Darrell Nance', author_username='darrell',
    )
    assert entry.display_byline() == 'Darrell Nance'


def test_coverage_entry_display_byline_falls_back_to_username_when_no_display_name():
    entry = CoverageEntry(
        id=1, kind='note', status='draft', source='manual',
        body='test', partner_credit=None,
        outlet_id=None, external_url=None, headline=None,
        reporter_byline=None, excerpt=None, article_published_at=None,
        author_id=1, byline=None,
        created_at=datetime.now(), updated_at=datetime.now(),
        published_at=None, featured_until=None,
        author_display_name=None, author_username='darrell',
    )
    assert entry.display_byline() == 'darrell'


import pytest

from docket.config import DATABASE_URL
from docket.db import db


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run editorial-coverage tests against Railway DB.",
)


@pytest.fixture
def seeded_admin():
    """Create a test admin user; clean up after."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO admin_users (username, password_hash, display_name) "
                "VALUES (%s, %s, %s) RETURNING id",
                ('test-editor', 'unused', 'Test Editor'),
            )
            user_id = cur.fetchone()[0]
        conn.commit()
    yield user_id
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM admin_users WHERE id = %s", (user_id,))
        conn.commit()


@pytest.fixture
def seeded_meeting():
    """Insert a throwaway meeting+item; clean up."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO meetings (municipality_id, external_id, title, meeting_date) "
                "VALUES ((SELECT id FROM municipalities LIMIT 1), %s, %s, NOW()) RETURNING id",
                ('test-mtg-coverage', 'Test Meeting for Coverage'),
            )
            mtg_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO agenda_items (meeting_id, title) VALUES (%s, %s) RETURNING id",
                (mtg_id, 'Test Item for Coverage'),
            )
            item_id = cur.fetchone()[0]
        conn.commit()
    yield (mtg_id, item_id)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM agenda_items WHERE id = %s", (item_id,))
            cur.execute("DELETE FROM meetings WHERE id = %s", (mtg_id,))
        conn.commit()


def test_coverage_for_subject_returns_empty_when_none_attached(seeded_meeting):
    from docket.services.query import coverage_for_subject
    _, item_id = seeded_meeting
    assert coverage_for_subject('agenda_item', subject_id=item_id) == []


def test_coverage_for_subject_returns_published_note_with_byline(seeded_admin, seeded_meeting):
    from docket.services.query import coverage_for_subject
    _, item_id = seeded_meeting
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO coverage_entries
                   (kind, status, body, author_id, byline, published_at)
                   VALUES ('note', 'published', 'Important context.', %s,
                           'Test Editor', NOW())
                   RETURNING id""",
                (seeded_admin,),
            )
            entry_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO coverage_subject_links
                   (coverage_id, subject_type, subject_id)
                   VALUES (%s, 'agenda_item', %s)""",
                (entry_id, item_id),
            )
        conn.commit()
    try:
        entries = coverage_for_subject('agenda_item', subject_id=item_id)
        assert len(entries) == 1
        assert entries[0].body == 'Important context.'
        assert entries[0].display_byline() == 'Test Editor'
    finally:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM coverage_entries WHERE id = %s", (entry_id,))
            conn.commit()


def test_coverage_for_subject_excludes_drafts(seeded_admin, seeded_meeting):
    from docket.services.query import coverage_for_subject
    _, item_id = seeded_meeting
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO coverage_entries
                   (kind, status, body, author_id)
                   VALUES ('note', 'draft', 'Not yet ready.', %s)
                   RETURNING id""",
                (seeded_admin,),
            )
            entry_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO coverage_subject_links
                   (coverage_id, subject_type, subject_id)
                   VALUES (%s, 'agenda_item', %s)""",
                (entry_id, item_id),
            )
        conn.commit()
    try:
        assert coverage_for_subject('agenda_item', subject_id=item_id) == []
    finally:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM coverage_entries WHERE id = %s", (entry_id,))
            conn.commit()
