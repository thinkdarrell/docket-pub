"""Integration tests: the admin sets a meeting's type by hand and the lock survives ingest (M5).

``POST /admin/meetings/<id>/type`` with ``meeting_type``, ``session_kind``,
and ``body_name`` writes the four columns with ``type_source = 'admin'`` and
a non-null ``type_locked_at`` / ``type_locked_by`` through
``meeting_types.set_override``; a later ``_upsert_meetings`` of the same
``external_id`` leaves them while the title still updates;
``POST /admin/meetings/<id>/type/unlock`` clears the lock through
``meeting_types.clear_override`` and re-resolves the row from its title; a
value outside the two vocabularies is a 400; an anonymous POST is redirected
to the login page as the other admin POSTs are.

Pattern: tests/integration/test_admin_hide_meeting.py (``_Bag``, ``admin_client``).
Plan: plans/active/meeting-types-name-the-body.md (M5).
"""

from __future__ import annotations

from datetime import date

import pytest

from docket.config import DATABASE_URL
from docket.db import db
from docket.models.protocol import RawMeeting
from docket.services.ingest import _upsert_meetings
from docket.web import create_app


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run admin meeting-type tests against Railway DB.",
)

PREFIX = "mtadmin-"


class _Bag:
    def __init__(self, city_id: int, city_slug: str):
        self.city_id = city_id
        self.city_slug = city_slug
        self.meeting_ids: list[int] = []
        self.admin_id: int | None = None

    def add_meeting(self, *, external_id: str = "1", title: str = "Regular City Council Meeting",
                    meeting_date: date | None = date(2026, 10, 13)) -> int:
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type)
                   VALUES (%s, %s, %s, %s, 'council') RETURNING id""",
                (self.city_id, PREFIX + external_id, title, meeting_date),
            )
            mid = cur.fetchone()[0]
            conn.commit()
        self.meeting_ids.append(mid)
        return mid

    def ensure_admin(self, username: str = "tester_mtype") -> int:
        from werkzeug.security import generate_password_hash
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO admin_users (username, password_hash) VALUES (%s, %s)
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
            cur.execute("DELETE FROM meetings WHERE municipality_id = %s AND external_id LIKE %s",
                        (self.city_id, PREFIX + "%"))
            if self.admin_id is not None:
                cur.execute("DELETE FROM admin_users WHERE id = %s", (self.admin_id,))
            conn.commit()


def _columns(meeting_id: int) -> dict:
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT title, meeting_type, session_kind, body_name, type_source,
                      type_locked_at, type_locked_by FROM meetings WHERE id = %s""",
            (meeting_id,),
        )
        row = cur.fetchone()
    keys = ("title", "meeting_type", "session_kind", "body_name", "type_source", "type_locked_at", "type_locked_by")
    return dict(zip(keys, row))


def _raw(external_id: str, title: str) -> RawMeeting:
    return RawMeeting(
        external_id=PREFIX + external_id, municipality_slug="birmingham", title=title,
        meeting_date=date(2026, 10, 13), meeting_type="council",
        agenda_url=f"https://example.com/agenda/{external_id}", minutes_url=None, video_url=None,
        source_url=f"https://example.com/m/{external_id}",
    )


@pytest.fixture
def bag():
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, slug FROM municipalities WHERE slug = 'birmingham'")
        row = cur.fetchone()
    assert row is not None, "City must be seeded: birmingham"
    b = _Bag(row[0], row[1])
    b.cleanup()
    try:
        yield b
    finally:
        b.cleanup()


@pytest.fixture(scope="module")
def app():
    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["SECRET_KEY"] = "test-secret-key-mtype"
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_client(app, bag):
    uid = bag.ensure_admin()
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["admin_user"] = "tester_mtype"
        sess["admin_user_id"] = uid
    return c


FORM = {"meeting_type": "committee", "session_kind": "special", "body_name": "Budget and Finance"}


def test_set_writes_the_four_columns_and_locks_the_row(admin_client, bag):
    mid = bag.add_meeting()
    rv = admin_client.post(f"/admin/meetings/{mid}/type", data=FORM, follow_redirects=False)
    assert rv.status_code in (302, 303)
    cols = _columns(mid)
    assert (cols["meeting_type"], cols["session_kind"], cols["body_name"], cols["type_source"]) == (
        "committee", "special", "Budget and Finance", "admin")
    assert cols["type_locked_at"] is not None
    assert cols["type_locked_by"] == bag.admin_id


def test_the_lock_survives_ingest_while_the_title_updates(admin_client, bag):
    mid = bag.add_meeting(external_id="2")
    admin_client.post(f"/admin/meetings/{mid}/type", data=FORM)
    inserted, updated = _upsert_meetings(bag.city_id, [_raw("2", "Special Called Finance Committee")])
    assert (inserted, updated) == (0, 1)
    cols = _columns(mid)
    assert cols["title"] == "Special Called Finance Committee"
    assert (cols["meeting_type"], cols["session_kind"], cols["body_name"], cols["type_source"]) == (
        "committee", "special", "Budget and Finance", "admin")
    assert cols["type_locked_at"] is not None


def test_unlock_clears_the_lock_and_re_resolves_from_the_title(admin_client, bag):
    mid = bag.add_meeting(external_id="3")
    admin_client.post(f"/admin/meetings/{mid}/type", data=FORM)
    rv = admin_client.post(f"/admin/meetings/{mid}/type/unlock", follow_redirects=False)
    assert rv.status_code in (302, 303)
    cols = _columns(mid)
    assert cols["type_locked_at"] is None
    assert cols["type_locked_by"] is None
    assert (cols["meeting_type"], cols["session_kind"], cols["body_name"], cols["type_source"]) == (
        "council", "regular", None, "title")


def test_a_value_outside_the_vocabulary_is_a_400(admin_client, bag):
    mid = bag.add_meeting(external_id="4")
    rv = admin_client.post(f"/admin/meetings/{mid}/type",
                           data={"meeting_type": "special", "session_kind": "regular", "body_name": ""})
    assert rv.status_code == 400
    rv = admin_client.post(f"/admin/meetings/{mid}/type",
                           data={"meeting_type": "council", "session_kind": "called", "body_name": ""})
    assert rv.status_code == 400
    assert _columns(mid)["type_source"] == "title"


def test_set_404_for_an_unknown_meeting(admin_client, bag):
    rv = admin_client.post("/admin/meetings/999999999/type", data=FORM)
    assert rv.status_code == 404


def test_anonymous_posts_are_sent_to_the_login_page(client, bag):
    mid = bag.add_meeting(external_id="5")
    for path in (f"/admin/meetings/{mid}/type", f"/admin/meetings/{mid}/type/unlock"):
        rv = client.post(path, data=FORM, follow_redirects=False)
        assert rv.status_code in (301, 302, 303, 308), path
        assert "/admin/login" in rv.headers.get("Location", ""), path
    assert _columns(mid)["type_source"] == "title"


def test_the_meeting_page_shows_the_admin_form_and_the_lock_line(admin_client, bag):
    mid = bag.add_meeting(external_id="6")
    html = admin_client.get(f"/al/birmingham/meetings/{mid}/").get_data(as_text=True)
    assert f'action="/admin/meetings/{mid}/type"' in html
    assert 'name="meeting_type"' in html and 'name="session_kind"' in html and 'name="body_name"' in html
    assert "Set by hand on" not in html
    admin_client.post(f"/admin/meetings/{mid}/type", data=FORM)
    html = admin_client.get(f"/al/birmingham/meetings/{mid}/").get_data(as_text=True)
    assert "Set by hand on" in html
    assert f'action="/admin/meetings/{mid}/type/unlock"' in html


def test_unlock_re_resolves_a_row_without_a_date(admin_client, bag):
    """Review finding: a generic-titled row with no meeting_date reached ``_as_date(None)``
    in ``resolve`` after the lock was already lifted, so the unlock half-ran and 500ed."""
    mid = bag.add_meeting(external_id="7", meeting_date=None)
    admin_client.post(f"/admin/meetings/{mid}/type", data=FORM)
    rv = admin_client.post(f"/admin/meetings/{mid}/type/unlock", follow_redirects=False)
    assert rv.status_code in (302, 303)
    cols = _columns(mid)
    assert cols["type_locked_at"] is None
    assert (cols["meeting_type"], cols["session_kind"], cols["body_name"], cols["type_source"]) == (
        "council", "regular", None, "title")
