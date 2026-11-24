"""Route tests for GET /admin/profile and POST /admin/profile/display-name.

Written against ``src/docket/web/admin.py`` while the two routes still
executed their own SQL, and seen to pass there (plan
`admin-routes-call-services`, M1).

The session here holds the seeded row's integer id under ``admin_user``.
That is the shape ``tests/integration/test_admin_coverage.py`` uses and it
is NOT how a login fills the session: ``docket.web.auth`` stores the
username under that key and the id under ``admin_user_id``. The two routes
compare the value with ``admin_users.id``, so this file follows the mismatch
the plan carries unchanged; it does not show the routes work after a real
login.

One ``admin_users`` row is seeded whose username begins ``admprof_test_``;
the autouse fixture deletes by that prefix before and after every test.
"""

from __future__ import annotations

import pytest

from docket.db import db_cursor

PREFIX = "admprof_test_"
USERNAME = PREFIX + "operator"


def _delete_seeded() -> None:
    with db_cursor() as cur:
        cur.execute("DELETE FROM admin_users WHERE username LIKE %s", (PREFIX + "%",))


@pytest.fixture(autouse=True)
def _clean():
    _delete_seeded()
    yield
    _delete_seeded()


@pytest.fixture
def profile_client(client):
    """A client whose session holds the seeded admin's integer id."""
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO admin_users (username, password_hash, display_name) "
            "VALUES (%s, 'unused', 'Profile Test Byline') RETURNING id",
            (USERNAME,),
        )
        uid = cur.fetchone()["id"]
    with client.session_transaction() as sess:
        sess["admin_user"] = uid
    return client, uid


def _display_name(uid: int):
    with db_cursor() as cur:
        cur.execute("SELECT display_name FROM admin_users WHERE id = %s", (uid,))
        return cur.fetchone()["display_name"]


def test_profile_page_shows_the_username_and_the_display_name(profile_client):
    client, _ = profile_client
    resp = client.get("/admin/profile")
    assert resp.status_code == 200
    assert USERNAME.encode() in resp.data
    assert b"Profile Test Byline" in resp.data


def test_an_empty_display_name_stores_null(profile_client):
    client, uid = profile_client
    resp = client.post("/admin/profile/display-name", data={"display_name": "   "})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/admin/profile")
    assert _display_name(uid) is None


def test_a_display_name_is_stored_stripped(profile_client):
    client, uid = profile_client
    resp = client.post("/admin/profile/display-name", data={"display_name": "  New Byline "})
    assert resp.status_code == 302
    assert _display_name(uid) == "New Byline"
