"""Integration tests for coverage chips on item cards across surfaces."""
from __future__ import annotations

import pytest

from docket.config import DATABASE_URL
from docket.db import db
from docket.services.coverage_writer import create_note, set_status
from docket.web import create_app


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run chip tests against Railway DB.",
)


@pytest.fixture
def app():
    a = create_app()
    a.config['TESTING'] = True
    # Enable Smart Brevity UI so item cards render via _card_shell.html,
    # which is where the coverage chip include lives.
    a.config['SMART_BREVITY_UI'] = True
    return a


@pytest.fixture
def covered_item():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, slug FROM municipalities ORDER BY id LIMIT 1")
            mu = cur.fetchone()
            cur.execute(
                "INSERT INTO admin_users (username, password_hash, display_name) "
                "VALUES (%s, %s, %s) RETURNING id",
                ('chip-admin', 'x', 'Chip Tester'),
            )
            uid = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO meetings (municipality_id, external_id, title, meeting_date) "
                "VALUES (%s, %s, %s, NOW()) RETURNING id",
                (mu[0], 'chip-mtg', 'Chip Test Meeting'),
            )
            mtg_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO agenda_items (meeting_id, title) VALUES (%s, %s) RETURNING id",
                (mtg_id, 'Chip Test Item'),
            )
            item_id = cur.fetchone()[0]
        conn.commit()
    entry_id = create_note(
        author_id=uid, body='Chip note.', partner_credit=None,
        subjects=[('agenda_item', item_id, None)],
    )
    set_status(entry_id, 'published')
    yield {'item_id': item_id, 'mtg_id': mtg_id, 'city_slug': mu[1]}
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM coverage_entries WHERE author_id = %s", (uid,))
            cur.execute("DELETE FROM agenda_items WHERE id = %s", (item_id,))
            cur.execute("DELETE FROM meetings WHERE id = %s", (mtg_id,))
            cur.execute("DELETE FROM admin_users WHERE id = %s", (uid,))
        conn.commit()


def test_meeting_detail_shows_chip_on_covered_item(app, covered_item):
    with app.test_client() as c:
        resp = c.get(f"/al/{covered_item['city_slug']}/meetings/{covered_item['mtg_id']}/")
        assert resp.status_code == 200
        assert b'coverage-chip' in resp.data
