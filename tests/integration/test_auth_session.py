"""Integration test for /admin/login session population.

Verifies that on successful login the auth blueprint populates BOTH
``session['admin_user']`` (the username) AND ``session['admin_user_id']``
(the FK that downstream features key off — see hide-non-real-meetings
plan, Task 2).
"""

from __future__ import annotations

import pytest
from werkzeug.security import generate_password_hash

from docket.config import DATABASE_URL
from docket.db import db
from docket.web import create_app


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run admin auth session tests against Railway DB.",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_TEST_USERNAME = "task2_session_test_user"
_TEST_PASSWORD = "task2-session-test-pw-do-not-reuse"


@pytest.fixture(scope="module")
def app():
    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["SECRET_KEY"] = "test-secret-key-auth-session"
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_user():
    """Seed a fresh admin user with a known password; tear down after.

    Yields the user's row id so the test can assert
    ``session['admin_user_id']`` matches.
    """
    pw_hash = generate_password_hash(_TEST_PASSWORD)
    with db() as conn:
        with conn.cursor() as cur:
            # Defensive cleanup in case a prior aborted run left the row.
            cur.execute(
                "DELETE FROM admin_users WHERE username = %s",
                (_TEST_USERNAME,),
            )
            cur.execute(
                """
                INSERT INTO admin_users (username, password_hash)
                VALUES (%s, %s)
                RETURNING id
                """,
                (_TEST_USERNAME, pw_hash),
            )
            user_id = cur.fetchone()[0]
    try:
        yield {"id": user_id, "username": _TEST_USERNAME}
    finally:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM admin_users WHERE id = %s",
                    (user_id,),
                )


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


def test_login_populates_admin_user_and_admin_user_id(client, admin_user):
    """POST /admin/login with valid creds → both session keys populated.

    Task 2 of hide-non-real-meetings: downstream features need the FK,
    not just the username. Both must land on a successful login.
    """
    rv = client.post(
        "/admin/login",
        data={
            "username": admin_user["username"],
            "password": _TEST_PASSWORD,
        },
    )
    assert rv.status_code in (301, 302, 303, 308), (
        f"Expected redirect on successful login, got {rv.status_code}"
    )

    with client.session_transaction() as sess:
        assert sess.get("admin_user") == admin_user["username"]
        assert sess.get("admin_user_id") == admin_user["id"]
