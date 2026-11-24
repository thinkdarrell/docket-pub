"""Route tests for GET /admin/profile and POST /admin/profile/display-name.

Written against ``src/docket/web/admin.py`` while the two routes still
executed their own SQL, and seen to pass there (plan
`admin-routes-call-services`, M1).

The fixture signs in by posting the seeded row's username and password to
``/admin/login``, as a browser does, so the session holds what a login
stores: the username under ``admin_user`` and the row's id under
``admin_user_id`` (plan `admin-profile-and-coverage-after-login`, M1). The
guard test alone builds a session by hand, because it needs one a login
cannot produce: ``admin_user`` with no ``admin_user_id``.

One ``admin_users`` row is seeded whose username begins ``admprof_test_``;
the autouse fixture deletes by that prefix before and after every test.
"""

from __future__ import annotations

import pytest
from werkzeug.security import generate_password_hash

from docket.db import db_cursor

PREFIX = "admprof_test_"
USERNAME = PREFIX + "operator"
PASSWORD = "admprof-test-pw-do-not-reuse"


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
    """A client signed in as the seeded admin through ``/admin/login``."""
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO admin_users (username, password_hash, display_name) "
            "VALUES (%s, %s, 'Profile Test Byline') RETURNING id",
            (USERNAME, generate_password_hash(PASSWORD)),
        )
        uid = cur.fetchone()["id"]
    resp = client.post("/admin/login", data={"username": USERNAME, "password": PASSWORD})
    # A failed login answers 200 with the form again.
    assert resp.status_code == 302
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


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/admin/profile"),
        ("post", "/admin/profile/display-name"),
        ("post", "/admin/coverage"),
    ],
)
def test_a_session_without_the_admin_id_is_sent_to_sign_in(client, method, path):
    with client.session_transaction() as sess:
        sess["admin_user"] = USERNAME
    resp = getattr(client, method)(path)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/admin/login")
