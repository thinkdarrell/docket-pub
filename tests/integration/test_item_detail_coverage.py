"""Integration tests for the item-detail coverage block."""
from __future__ import annotations

import pytest

from docket.config import DATABASE_URL
from docket.db import db
from docket.services.coverage_writer import create_note, set_status
from docket.web import create_app


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run item-detail coverage tests against Railway DB.",
)


@pytest.fixture
def app():
    a = create_app()
    a.config['TESTING'] = True
    return a


@pytest.fixture
def seeded():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, slug FROM municipalities ORDER BY id LIMIT 1"
            )
            mu = cur.fetchone()
            cur.execute(
                "INSERT INTO admin_users (username, password_hash, display_name) "
                "VALUES (%s, %s, %s) RETURNING id",
                ('detail-cov-admin', 'x', 'Detail Tester'),
            )
            uid = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO meetings (municipality_id, external_id, title, meeting_date) "
                "VALUES (%s, %s, %s, NOW()) RETURNING id",
                (mu[0], 'detail-cov-mtg', 'Detail Cov Meeting'),
            )
            mtg_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO agenda_items (meeting_id, title) VALUES (%s, %s) RETURNING id",
                (mtg_id, 'Detail Cov Item'),
            )
            item_id = cur.fetchone()[0]
        conn.commit()
    yield {'uid': uid, 'mtg_id': mtg_id, 'item_id': item_id, 'city_slug': mu[1]}
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM coverage_entries WHERE author_id = %s", (uid,))
            cur.execute("DELETE FROM agenda_items WHERE id = %s", (item_id,))
            cur.execute("DELETE FROM meetings WHERE id = %s", (mtg_id,))
            cur.execute("DELETE FROM admin_users WHERE id = %s", (uid,))
        conn.commit()


def test_item_detail_renders_published_note(app, seeded):
    entry_id = create_note(
        author_id=seeded['uid'],
        body='An important contextual note for this item.',
        partner_credit=None,
        subjects=[('agenda_item', seeded['item_id'], None)],
    )
    set_status(entry_id, 'published')
    with app.test_client() as c:
        resp = c.get(f"/al/{seeded['city_slug']}/items/{seeded['item_id']}/")
        assert resp.status_code == 200
        assert b'An important contextual note for this item.' in resp.data
        assert b'Editorial coverage' in resp.data


def test_item_detail_omits_block_when_no_coverage(app, seeded):
    with app.test_client() as c:
        resp = c.get(f"/al/{seeded['city_slug']}/items/{seeded['item_id']}/")
        assert resp.status_code == 200
        assert b'Editorial coverage' not in resp.data


def test_item_detail_omits_draft_coverage(app, seeded):
    create_note(  # status='draft' by default
        author_id=seeded['uid'],
        body='Should not render — still a draft.',
        partner_credit=None,
        subjects=[('agenda_item', seeded['item_id'], None)],
    )
    with app.test_client() as c:
        resp = c.get(f"/al/{seeded['city_slug']}/items/{seeded['item_id']}/")
        assert b'Should not render' not in resp.data
