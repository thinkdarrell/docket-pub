"""Integration tests for /admin/coverage CRUD."""
from __future__ import annotations

import pytest

from docket.config import DATABASE_URL
from docket.db import db
from docket.web import create_app


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run admin coverage tests against Railway DB.",
)


@pytest.fixture
def app():
    app = create_app()
    app.config['TESTING'] = True
    return app


@pytest.fixture
def client_logged_in(app):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO admin_users (username, password_hash, display_name) "
                "VALUES (%s, %s, %s) RETURNING id",
                ('admin-cov-test', 'unused', 'Test Admin'),
            )
            uid = cur.fetchone()[0]
        conn.commit()
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['admin_user'] = uid
            sess['admin_username'] = 'admin-cov-test'
        yield c, uid
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM coverage_entries WHERE author_id = %s", (uid,))
            cur.execute("DELETE FROM admin_users WHERE id = %s", (uid,))
        conn.commit()


def test_admin_coverage_list_renders_empty(client_logged_in):
    c, _ = client_logged_in
    resp = c.get('/admin/coverage')
    assert resp.status_code == 200
    assert b'Editorial coverage' in resp.data


@pytest.fixture
def seeded_note(client_logged_in):
    """Create a draft note via the writer service. Cleaned up after test."""
    from docket.services.coverage_writer import create_note
    _, uid = client_logged_in
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO meetings (municipality_id, external_id, title, meeting_date) "
                "VALUES ((SELECT id FROM municipalities LIMIT 1), %s, %s, NOW()) RETURNING id",
                ('admin-cov-mtg', 'Admin Cov Meeting'),
            )
            mtg_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO agenda_items (meeting_id, title) VALUES (%s, %s) RETURNING id",
                (mtg_id, 'Admin Cov Item'),
            )
            item_id = cur.fetchone()[0]
        conn.commit()
    entry_id = create_note(
        author_id=uid, body='Test note body.', partner_credit=None,
        subjects=[('agenda_item', item_id, None)],
    )
    yield entry_id, item_id, mtg_id
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM coverage_entries WHERE id = %s", (entry_id,))
            cur.execute("DELETE FROM agenda_items WHERE id = %s", (item_id,))
            cur.execute("DELETE FROM meetings WHERE id = %s", (mtg_id,))
        conn.commit()


def test_publish_route_transitions_to_published(client_logged_in, seeded_note):
    c, _ = client_logged_in
    entry_id, _, _ = seeded_note
    resp = c.post(f'/admin/coverage/{entry_id}/publish', follow_redirects=False)
    assert resp.status_code in (302, 303)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status, byline FROM coverage_entries WHERE id = %s",
                        (entry_id,))
            row = cur.fetchone()
            assert row[0] == 'published'
            assert row[1] == 'Test Admin'


def test_unpublish_route_returns_to_draft(client_logged_in, seeded_note):
    from docket.services.coverage_writer import set_status
    c, _ = client_logged_in
    entry_id, _, _ = seeded_note
    set_status(entry_id, 'published')
    c.post(f'/admin/coverage/{entry_id}/unpublish')
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM coverage_entries WHERE id = %s", (entry_id,))
            assert cur.fetchone()[0] == 'draft'
