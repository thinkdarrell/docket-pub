"""Integration tests for the hide-meeting feature — admin bypass on detail
pages, hide/unhide POST routes, admin index, and meeting_detail template
toggle.

Pattern mirrors tests/integration/test_admin_badge_review.py — _Bag tracker,
app/client/admin_client fixtures, BHM seed.
"""

from __future__ import annotations

import pytest

from docket.config import DATABASE_URL
from docket.db import db
from docket.web import create_app


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run hide-meeting tests against Railway DB.",
)


class _Bag:
    def __init__(self, city_id: int, city_slug: str):
        self.city_id = city_id
        self.city_slug = city_slug
        self.meeting_ids: list[int] = []
        self.item_ids: list[int] = []
        self.admin_id: int | None = None

    def add_meeting(self, *, is_hidden: bool = False, title: str = "TEST_HIDE_meeting") -> int:
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO meetings
                  (municipality_id, title, meeting_date, meeting_type, is_hidden)
                VALUES (%s, %s, '2099-05-01', 'council', %s)
                RETURNING id
                """,
                (self.city_id, title, is_hidden),
            )
            mid = cur.fetchone()[0]
            conn.commit()
        self.meeting_ids.append(mid)
        return mid

    def add_item(self, meeting_id: int, *, title: str = "TEST_HIDE_item") -> int:
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO agenda_items
                     (meeting_id, title, item_number, processing_status)
                   VALUES (%s, %s, '1', 'pending')
                   RETURNING id""",
                (meeting_id, title),
            )
            iid = cur.fetchone()[0]
            conn.commit()
        self.item_ids.append(iid)
        return iid

    def ensure_admin(self, username: str = "tester_hide") -> int:
        from werkzeug.security import generate_password_hash
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO admin_users (username, password_hash)
                   VALUES (%s, %s)
                   ON CONFLICT (username) DO UPDATE SET password_hash = EXCLUDED.password_hash
                   RETURNING id""",
                (username, generate_password_hash("pw")),
            )
            uid = cur.fetchone()[0]
            conn.commit()
        self.admin_id = uid
        return uid

    def cleanup(self):
        with db() as conn, conn.cursor() as cur:
            if self.item_ids:
                cur.execute("DELETE FROM agenda_items WHERE id = ANY(%s)", (self.item_ids,))
            if self.meeting_ids:
                cur.execute("DELETE FROM meetings WHERE id = ANY(%s)", (self.meeting_ids,))
            if self.admin_id is not None:
                cur.execute("DELETE FROM admin_users WHERE id = %s", (self.admin_id,))
            conn.commit()


def _bag_for(slug: str = "birmingham") -> _Bag:
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, slug FROM municipalities WHERE slug = %s", (slug,))
        row = cur.fetchone()
    assert row is not None, f"City must be seeded: {slug}"
    return _Bag(row[0], row[1])


@pytest.fixture
def bag():
    b = _bag_for("birmingham")
    try:
        yield b
    finally:
        b.cleanup()


@pytest.fixture(scope="module")
def app():
    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["SECRET_KEY"] = "test-secret-key-hide"
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_client(app, bag):
    uid = bag.ensure_admin()
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["admin_user"] = "tester_hide"
        sess["admin_user_id"] = uid
    return c


# ---------------------------------------------------------------------------
# Task 8 — meeting_detail admin bypass
# ---------------------------------------------------------------------------


def test_meeting_detail_404_for_anonymous_when_hidden(client, bag):
    mid = bag.add_meeting(is_hidden=True)
    rv = client.get(f"/al/{bag.city_slug}/meetings/{mid}/")
    assert rv.status_code == 404


def test_meeting_detail_200_for_admin_when_hidden(admin_client, bag):
    mid = bag.add_meeting(is_hidden=True)
    rv = admin_client.get(f"/al/{bag.city_slug}/meetings/{mid}/")
    assert rv.status_code == 200


def test_meeting_detail_200_for_anonymous_when_visible(client, bag):
    mid = bag.add_meeting(is_hidden=False)
    rv = client.get(f"/al/{bag.city_slug}/meetings/{mid}/")
    assert rv.status_code == 200


# ---------------------------------------------------------------------------
# Task 9 — item_detail admin bypass
# ---------------------------------------------------------------------------


def test_item_detail_404_for_anonymous_when_parent_hidden(client, bag):
    mid = bag.add_meeting(is_hidden=True)
    iid = bag.add_item(mid)
    rv = client.get(f"/al/{bag.city_slug}/items/{iid}/")
    assert rv.status_code == 404


def test_item_detail_200_for_admin_when_parent_hidden(admin_client, bag):
    mid = bag.add_meeting(is_hidden=True)
    iid = bag.add_item(mid)
    rv = admin_client.get(f"/al/{bag.city_slug}/items/{iid}/")
    assert rv.status_code == 200


def test_item_detail_200_for_anonymous_when_parent_visible(client, bag):
    mid = bag.add_meeting(is_hidden=False)
    iid = bag.add_item(mid)
    rv = client.get(f"/al/{bag.city_slug}/items/{iid}/")
    assert rv.status_code == 200
