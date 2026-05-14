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
