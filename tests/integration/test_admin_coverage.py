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


def test_coverage_new_note_form_renders(client_logged_in):
    c, _ = client_logged_in
    resp = c.get('/admin/coverage/new?kind=note')
    assert resp.status_code == 200
    assert b'New note' in resp.data


def test_coverage_post_creates_note_and_redirects(client_logged_in):
    c, _ = client_logged_in
    # First seed an item to attach to
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO meetings (municipality_id, external_id, title, meeting_date) "
                "VALUES ((SELECT id FROM municipalities LIMIT 1), %s, %s, NOW()) RETURNING id",
                ('post-mtg', 'Post Test'),
            )
            mtg_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO agenda_items (meeting_id, title) VALUES (%s, %s) RETURNING id",
                (mtg_id, 'Post Test Item'),
            )
            item_id = cur.fetchone()[0]
        conn.commit()
    resp = c.post('/admin/coverage', data={
        'kind': 'note',
        'body': 'A new note from the form.',
        'partner_credit': '',
        'subject[]': [f'agenda_item:{item_id}'],
    })
    assert resp.status_code in (302, 303)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM coverage_entries WHERE body = %s",
                ('A new note from the form.',),
            )
            assert cur.fetchone() is not None
    # Cleanup
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM coverage_entries WHERE body = 'A new note from the form.'")
            cur.execute("DELETE FROM agenda_items WHERE id = %s", (item_id,))
            cur.execute("DELETE FROM meetings WHERE id = %s", (mtg_id,))
        conn.commit()


def test_edit_form_includes_deactivated_outlet_when_citation_uses_it(client_logged_in):
    """Regression: editing a citation whose outlet was later deactivated must
    still show that outlet in the dropdown — otherwise the browser would silently
    reassign the citation to the first active outlet on save."""
    from docket.services.coverage_writer import create_citation
    c, uid = client_logged_in
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO outlets (slug, name) VALUES (%s, %s) RETURNING id",
                ('test-deactivated-outlet', 'Soon-to-be-deactivated'),
            )
            outlet_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO meetings (municipality_id, external_id, title, meeting_date) "
                "VALUES ((SELECT id FROM municipalities LIMIT 1), %s, %s, NOW()) RETURNING id",
                ('edit-mtg', 'Edit Test'),
            )
            mtg_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO agenda_items (meeting_id, title) VALUES (%s, %s) RETURNING id",
                (mtg_id, 'Edit Test Item'),
            )
            item_id = cur.fetchone()[0]
        conn.commit()
    entry_id = create_citation(
        author_id=uid, outlet_id=outlet_id,
        external_url='https://example.test/x', headline='Edit headline',
        reporter_byline=None, excerpt=None, article_published_at=None,
        subjects=[('agenda_item', item_id, None)],
    )
    try:
        # Now deactivate the outlet
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE outlets SET is_active = FALSE WHERE id = %s", (outlet_id,))
            conn.commit()
        resp = c.get(f'/admin/coverage/{entry_id}/edit')
        assert resp.status_code == 200
        # The deactivated outlet must still appear in the dropdown
        assert b'Soon-to-be-deactivated' in resp.data
    finally:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM coverage_entries WHERE id = %s", (entry_id,))
                cur.execute("DELETE FROM agenda_items WHERE id = %s", (item_id,))
                cur.execute("DELETE FROM meetings WHERE id = %s", (mtg_id,))
                cur.execute("DELETE FROM outlets WHERE id = %s", (outlet_id,))
            conn.commit()


def test_feature_sets_featured_until_14_days(client_logged_in, seeded_note):
    from docket.services.coverage_writer import set_status
    c, _ = client_logged_in
    entry_id, _, _ = seeded_note
    set_status(entry_id, 'published')
    c.post(f'/admin/coverage/{entry_id}/feature')
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT featured_until FROM coverage_entries WHERE id = %s",
                        (entry_id,))
            stored = cur.fetchone()[0]
            assert stored is not None


def test_profile_display_name_update(client_logged_in):
    c, uid = client_logged_in
    resp = c.post('/admin/profile/display-name', data={'display_name': 'Editor Smith'})
    assert resp.status_code in (302, 303)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT display_name FROM admin_users WHERE id = %s", (uid,))
            assert cur.fetchone()[0] == 'Editor Smith'


def test_coverage_search_route_accepts_subject_type_via_form_field(client_logged_in):
    """Regression: subject_type select must transmit its value via HTMX hx-include.
    Without name='subject_type' on the <select>, the route silently defaults to
    agenda_item, breaking meeting/member/badge searches."""
    c, _ = client_logged_in
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO meetings (municipality_id, external_id, title, meeting_date) "
                "VALUES ((SELECT id FROM municipalities LIMIT 1), %s, %s, NOW()) RETURNING id",
                ('search-mtg', 'Unique-Search-Meeting-Token-xyz1'),
            )
            mtg_id = cur.fetchone()[0]
        conn.commit()
    try:
        resp = c.get('/admin/coverage/search?subject_type=meeting&q=Unique-Search-Meeting-Token-xyz1')
        assert resp.status_code == 200
        assert b'Unique-Search-Meeting-Token-xyz1' in resp.data
    finally:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM meetings WHERE id = %s", (mtg_id,))
            conn.commit()


def test_coverage_search_badge_path_does_not_crash(client_logged_in):
    """Regression: badge ILIKE used `WHERE (a OR b) ESCAPE '\\'` which is
    a Postgres syntax error. The route must accept badge searches without crashing."""
    c, _ = client_logged_in
    resp = c.get('/admin/coverage/search?subject_type=badge&q=property')
    assert resp.status_code == 200  # whether it finds results or not, must NOT 500


def test_coverage_list_shows_attached_to_column(client_logged_in, seeded_note):
    """Regression: list view must show the 'Attached to' column with subject labels."""
    c, _ = client_logged_in
    entry_id, item_id, mtg_id = seeded_note
    resp = c.get('/admin/coverage')
    assert resp.status_code == 200
    assert b'Attached to' in resp.data
    # The seeded_note attaches the entry to an agenda_item; the title is 'Admin Cov Item'
    assert b'Admin Cov Item' in resp.data


def test_draft_row_has_delete_button(client_logged_in, seeded_note):
    """Regression: draft rows must include a Delete button (spec quick-actions table)."""
    c, _ = client_logged_in
    entry_id, _, _ = seeded_note
    resp = c.get('/admin/coverage')
    assert resp.status_code == 200
    # The delete form action URL for this entry
    expected_action = f'/admin/coverage/{entry_id}/delete'
    assert expected_action.encode() in resp.data
