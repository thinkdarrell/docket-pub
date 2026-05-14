"""Integration tests for /coverage listing + permalink."""
from __future__ import annotations

import pytest

from docket.config import DATABASE_URL
from docket.db import db
from docket.services.coverage_writer import create_note, create_citation, set_status
from docket.web import create_app


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run listing tests against Railway DB.",
)


@pytest.fixture
def app():
    a = create_app()
    a.config['TESTING'] = True
    return a


@pytest.fixture
def published_entries():
    """Create 3 published notes for the listing tests."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO admin_users (username, password_hash, display_name) "
                "VALUES (%s, %s, %s) RETURNING id",
                ('list-admin', 'x', 'List Tester'),
            )
            uid = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO meetings (municipality_id, external_id, title, meeting_date) "
                "VALUES ((SELECT id FROM municipalities LIMIT 1), %s, %s, NOW()) RETURNING id",
                ('list-mtg', 'List Test'),
            )
            mtg_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO agenda_items (meeting_id, title) VALUES (%s, %s) RETURNING id",
                (mtg_id, 'List Test Item'),
            )
            item_id = cur.fetchone()[0]
        conn.commit()
    entry_ids = []
    for i in range(3):
        eid = create_note(
            author_id=uid,
            body=f'List body {i} unique-token-list42.',
            partner_credit=None,
            subjects=[('agenda_item', item_id, None)],
        )
        set_status(eid, 'published')
        entry_ids.append(eid)
    yield {'uid': uid, 'item_id': item_id, 'mtg_id': mtg_id, 'entry_ids': entry_ids}
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM coverage_entries WHERE author_id = %s", (uid,))
            cur.execute("DELETE FROM agenda_items WHERE id = %s", (item_id,))
            cur.execute("DELETE FROM meetings WHERE id = %s", (mtg_id,))
            cur.execute("DELETE FROM admin_users WHERE id = %s", (uid,))
        conn.commit()


def test_listing_renders_published(app, published_entries):
    with app.test_client() as c:
        resp = c.get('/coverage/')
        assert resp.status_code == 200
        assert b'List body 0 unique-token-list42' in resp.data
        assert b'List body 1 unique-token-list42' in resp.data
        assert b'List body 2 unique-token-list42' in resp.data


def test_listing_fts_search_filters(app, published_entries):
    with app.test_client() as c:
        resp = c.get('/coverage/?q=unique-token-list42')
        assert resp.status_code == 200
        assert b'List body 0 unique-token-list42' in resp.data


def test_listing_pagination(app, published_entries):
    with app.test_client() as c:
        resp = c.get('/coverage/?page=999')
        assert resp.status_code == 200  # empty page, not 404


def test_listing_council_member_subject_renders_as_text(app):
    """Regression: council_member subject renders as text (no BuildError for missing route).

    Creates a coverage note attached to a council_member subject, renders the
    listing page, and asserts no 500, the note body appears, and the member's
    name appears (i.e. the CASE-discriminated hydrator returns the correct label).
    """
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO admin_users (username, password_hash, display_name) "
                "VALUES (%s, %s, %s) RETURNING id",
                ('cm-listing-admin', 'x', 'CM Listing Tester'),
            )
            uid = cur.fetchone()[0]
            # council_members requires a municipality_id
            cur.execute("SELECT id FROM municipalities LIMIT 1")
            muni_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO council_members (municipality_id, name) "
                "VALUES (%s, %s) RETURNING id",
                (muni_id, 'Unique-Coalesce-Test-Member-zx9'),
            )
            cm_id = cur.fetchone()[0]
        conn.commit()

    eid = create_note(
        author_id=uid,
        body='Council member subject regression note.',
        partner_credit=None,
        subjects=[('council_member', cm_id, None)],
    )
    set_status(eid, 'published')

    try:
        with app.test_client() as c:
            resp = c.get('/coverage/')
            # Must not 500 — the footer must not raise BuildError for missing
            # public.council_member route.
            assert resp.status_code == 200
            # The note body must appear (entry renders successfully)
            assert b'Council member subject regression note.' in resp.data
            # The member's name must appear in the rendered HTML — this verifies
            # that _hydrate_subjects_for_entries correctly resolves the label from
            # council_members (not from agenda_items, as the old COALESCE could do
            # when IDs collide).
            assert b'Unique-Coalesce-Test-Member-zx9' in resp.data
            # The subjects footer must render as text, not a link — verified by
            # ensuring no url_for('public.council_member') BuildError was raised
            # (a BuildError would have caused the 500 guard above to fail).
    finally:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM coverage_entries WHERE id = %s", (eid,))
                cur.execute("DELETE FROM council_members WHERE id = %s", (cm_id,))
                cur.execute("DELETE FROM admin_users WHERE id = %s", (uid,))
            conn.commit()


def test_permalink_renders_note(app, published_entries):
    eid = published_entries['entry_ids'][0]
    with app.test_client() as c:
        resp = c.get(f"/coverage/{eid}")
        assert resp.status_code == 200
        assert b'unique-token-list42' in resp.data


def test_permalink_404_for_unpublished(app, published_entries):
    from docket.services.coverage_writer import set_status
    eid = published_entries['entry_ids'][0]
    set_status(eid, 'draft')
    with app.test_client() as c:
        resp = c.get(f"/coverage/{eid}")
        assert resp.status_code == 404


def test_permalink_404_for_citation(app):
    """Citations don't get internal permalinks — they link out."""
    # Create a citation, try to GET its permalink → 404
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO admin_users (username, password_hash) VALUES (%s, %s) RETURNING id",
                ('perma-admin', 'x'),
            )
            uid = cur.fetchone()[0]
            cur.execute("SELECT id FROM outlets WHERE slug='al-com'")
            outlet_row = cur.fetchone()
            if outlet_row:
                outlet_id = outlet_row[0]
            else:
                # Create a test outlet if al-com doesn't exist
                cur.execute(
                    "INSERT INTO outlets (name, slug, base_url) "
                    "VALUES (%s, %s, %s) RETURNING id",
                    ('AL.com', 'al-com', 'https://al.com'),
                )
                outlet_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO meetings (municipality_id, external_id, title, meeting_date) "
                "VALUES ((SELECT id FROM municipalities LIMIT 1), %s, %s, NOW()) RETURNING id",
                ('perma-mtg', 'Perma'),
            )
            mtg_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO agenda_items (meeting_id, title) VALUES (%s, %s) RETURNING id",
                (mtg_id, 'Perma Item'),
            )
            item_id = cur.fetchone()[0]
        conn.commit()
    from docket.services.coverage_writer import create_citation, set_status
    eid = create_citation(
        author_id=uid, outlet_id=outlet_id,
        external_url='https://al.com/perma',
        headline='Perma Headline',
        reporter_byline=None, excerpt=None, article_published_at=None,
        subjects=[('agenda_item', item_id, None)],
    )
    set_status(eid, 'published')
    try:
        with app.test_client() as c:
            resp = c.get(f"/coverage/{eid}")
            assert resp.status_code == 404
    finally:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM coverage_entries WHERE id = %s", (eid,))
                cur.execute("DELETE FROM agenda_items WHERE id = %s", (item_id,))
                cur.execute("DELETE FROM meetings WHERE id = %s", (mtg_id,))
                cur.execute("DELETE FROM admin_users WHERE id = %s", (uid,))
            conn.commit()


def test_listing_renders_published_citation(app, published_entries):
    """Regression: listing must render citation cards (template ``{% else %}`` branch
    of partials/coverage_citation.html), not just notes."""
    uid = published_entries['uid']
    item_id = published_entries['item_id']
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM outlets WHERE slug='al-com'")
            outlet_id = cur.fetchone()[0]
    cit_id = create_citation(
        author_id=uid, outlet_id=outlet_id,
        external_url='https://al.com/listing-cit',
        headline='Unique-Listing-Citation-token-7g',
        reporter_byline=None, excerpt=None, article_published_at=None,
        subjects=[('agenda_item', item_id, None)],
    )
    set_status(cit_id, 'published')
    try:
        with app.test_client() as c:
            resp = c.get('/coverage/')
            assert resp.status_code == 200
            assert b'Unique-Listing-Citation-token-7g' in resp.data
            assert b'coverage-citation' in resp.data
    finally:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM coverage_entries WHERE id = %s", (cit_id,))
            conn.commit()


def test_listing_filter_tab_notes_only(app, published_entries):
    """Regression: ?kind=note filter must exclude citations from the listing."""
    uid = published_entries['uid']
    item_id = published_entries['item_id']
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM outlets WHERE slug='al-com'")
            outlet_id = cur.fetchone()[0]
    cit_id = create_citation(
        author_id=uid, outlet_id=outlet_id,
        external_url='https://al.com/filter-test',
        headline='Filter-Tab-Citation-token-9h',
        reporter_byline=None, excerpt=None, article_published_at=None,
        subjects=[('agenda_item', item_id, None)],
    )
    set_status(cit_id, 'published')
    try:
        with app.test_client() as c:
            resp = c.get('/coverage/?kind=note')
            assert resp.status_code == 200
            assert b'Filter-Tab-Citation-token-9h' not in resp.data
            resp_cit = c.get('/coverage/?kind=citation')
            assert b'Filter-Tab-Citation-token-9h' in resp_cit.data
    finally:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM coverage_entries WHERE id = %s", (cit_id,))
            conn.commit()


def test_permalink_404_for_nonexistent_id(app):
    """Regression: GET /coverage/<nonexistent> returns 404."""
    with app.test_client() as c:
        resp = c.get('/coverage/999999999')
        assert resp.status_code == 404
