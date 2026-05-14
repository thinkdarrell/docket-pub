"""Unit tests for editorial coverage writer service."""
from __future__ import annotations

import pytest

from docket.config import DATABASE_URL
from docket.db import db


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run coverage writer tests against Railway DB.",
)


@pytest.fixture
def seeded_admin():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO admin_users (username, password_hash, display_name) "
                "VALUES (%s, %s, %s) RETURNING id",
                ('test-writer-editor', 'unused', 'Writer Test'),
            )
            user_id = cur.fetchone()[0]
        conn.commit()
    yield user_id
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM admin_users WHERE id = %s", (user_id,))
        conn.commit()


@pytest.fixture
def seeded_item():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO meetings (municipality_id, external_id, title, meeting_date) "
                "VALUES ((SELECT id FROM municipalities LIMIT 1), %s, %s, NOW()) RETURNING id",
                ('writer-mtg', 'Writer Test Meeting'),
            )
            mtg_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO agenda_items (meeting_id, title) VALUES (%s, %s) RETURNING id",
                (mtg_id, 'Writer Test Item'),
            )
            item_id = cur.fetchone()[0]
        conn.commit()
    yield (mtg_id, item_id)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM agenda_items WHERE id = %s", (item_id,))
            cur.execute("DELETE FROM meetings WHERE id = %s", (mtg_id,))
        conn.commit()


def _cleanup_entry(entry_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM coverage_entries WHERE id = %s", (entry_id,))
        conn.commit()


def test_create_note_inserts_entry_and_subjects(seeded_admin, seeded_item):
    from docket.services.coverage_writer import create_note
    _, item_id = seeded_item
    entry_id = create_note(
        author_id=seeded_admin,
        body='A short context note.',
        partner_credit=None,
        subjects=[('agenda_item', item_id, None)],
    )
    try:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT kind, status, body FROM coverage_entries WHERE id = %s",
                            (entry_id,))
                row = cur.fetchone()
                assert row[0] == 'note'
                assert row[1] == 'draft'
                assert row[2] == 'A short context note.'
                cur.execute(
                    "SELECT COUNT(*) FROM coverage_subject_links WHERE coverage_id = %s",
                    (entry_id,),
                )
                assert cur.fetchone()[0] == 1
    finally:
        _cleanup_entry(entry_id)


def test_set_status_to_published_snapshots_byline(seeded_admin, seeded_item):
    from docket.services.coverage_writer import create_note, set_status
    _, item_id = seeded_item
    entry_id = create_note(
        author_id=seeded_admin,
        body='Body text.',
        partner_credit=None,
        subjects=[('agenda_item', item_id, None)],
    )
    try:
        set_status(entry_id, 'published')
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status, byline, published_at FROM coverage_entries WHERE id = %s",
                    (entry_id,),
                )
                row = cur.fetchone()
                assert row[0] == 'published'
                assert row[1] == 'Writer Test'  # display_name of seeded_admin
                assert row[2] is not None
    finally:
        _cleanup_entry(entry_id)


def test_set_status_preserves_byline_on_republish(seeded_admin, seeded_item):
    from docket.services.coverage_writer import create_note, set_status
    _, item_id = seeded_item
    entry_id = create_note(
        author_id=seeded_admin,
        body='Body.',
        partner_credit=None,
        subjects=[('agenda_item', item_id, None)],
    )
    try:
        set_status(entry_id, 'published')
        # Now change display_name and republish — byline should NOT update
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE admin_users SET display_name = 'New Name' WHERE id = %s",
                    (seeded_admin,),
                )
            conn.commit()
        set_status(entry_id, 'draft')
        set_status(entry_id, 'published')
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT byline FROM coverage_entries WHERE id = %s", (entry_id,))
                assert cur.fetchone()[0] == 'Writer Test'  # preserved from first publish
    finally:
        _cleanup_entry(entry_id)


def test_create_citation_inserts_entry_with_outlet(seeded_admin, seeded_item):
    from docket.services.coverage_writer import create_citation
    _, item_id = seeded_item
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM outlets WHERE slug = 'birmingham-watch'")
            outlet_id = cur.fetchone()[0]
    entry_id = create_citation(
        author_id=seeded_admin,
        outlet_id=outlet_id,
        external_url='https://birminghamwatch.org/test',
        headline='Test headline',
        reporter_byline='Sam Prickett',
        excerpt='Pull quote.',
        article_published_at=None,
        subjects=[('agenda_item', item_id, None)],
    )
    try:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT kind, headline, reporter_byline FROM coverage_entries WHERE id = %s",
                    (entry_id,),
                )
                row = cur.fetchone()
                assert row[0] == 'citation'
                assert row[1] == 'Test headline'
                assert row[2] == 'Sam Prickett'
    finally:
        _cleanup_entry(entry_id)
