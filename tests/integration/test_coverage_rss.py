"""Integration tests for /coverage.rss feed."""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from docket.config import DATABASE_URL
from docket.db import db
from docket.services.coverage_writer import create_note, create_citation, set_status
from docket.web import create_app


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run RSS tests against Railway DB.",
)


@pytest.fixture
def app():
    a = create_app()
    a.config['TESTING'] = True
    return a


@pytest.fixture
def rss_entries():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO admin_users (username, password_hash, display_name) "
                "VALUES (%s, %s, %s) RETURNING id",
                ('rss-admin', 'x', 'RSS Tester'),
            )
            uid = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO meetings (municipality_id, external_id, title, meeting_date) "
                "VALUES ((SELECT id FROM municipalities LIMIT 1), %s, %s, NOW()) RETURNING id",
                ('rss-mtg', 'RSS'),
            )
            mtg_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO agenda_items (meeting_id, title) VALUES (%s, %s) RETURNING id",
                (mtg_id, 'RSS Item'),
            )
            item_id = cur.fetchone()[0]
            cur.execute("SELECT id FROM outlets WHERE slug='al-com'")
            outlet_id = cur.fetchone()[0]
        conn.commit()
    note_id = create_note(
        author_id=uid, body='RSS note body unique-rss-token.',
        partner_credit=None, subjects=[('agenda_item', item_id, None)],
    )
    set_status(note_id, 'published')
    cit_id = create_citation(
        author_id=uid, outlet_id=outlet_id,
        external_url='https://al.com/rss-test',
        headline='RSS citation headline',
        reporter_byline=None, excerpt=None, article_published_at=None,
        subjects=[('agenda_item', item_id, None)],
    )
    set_status(cit_id, 'published')
    yield {'uid': uid, 'note_id': note_id, 'cit_id': cit_id, 'item_id': item_id, 'mtg_id': mtg_id}
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM coverage_entries WHERE author_id = %s", (uid,))
            cur.execute("DELETE FROM agenda_items WHERE id = %s", (item_id,))
            cur.execute("DELETE FROM meetings WHERE id = %s", (mtg_id,))
            cur.execute("DELETE FROM admin_users WHERE id = %s", (uid,))
        conn.commit()


def test_rss_feed_valid_xml(app, rss_entries):
    with app.test_client() as c:
        resp = c.get('/coverage.rss')
        assert resp.status_code == 200
        assert resp.mimetype in ('application/rss+xml', 'application/xml', 'text/xml')
        root = ET.fromstring(resp.data)
        assert root.tag == 'rss'


def test_rss_feed_includes_published_note_and_citation(app, rss_entries):
    with app.test_client() as c:
        resp = c.get('/coverage.rss')
        assert b'unique-rss-token' in resp.data
        assert b'RSS citation headline' in resp.data


def test_rss_citation_link_points_to_external_url(app, rss_entries):
    with app.test_client() as c:
        resp = c.get('/coverage.rss')
        assert b'https://al.com/rss-test' in resp.data


def test_rss_excludes_drafts(app, rss_entries):
    from docket.services.coverage_writer import set_status
    set_status(rss_entries['note_id'], 'draft')
    with app.test_client() as c:
        resp = c.get('/coverage.rss')
        assert b'unique-rss-token' not in resp.data
