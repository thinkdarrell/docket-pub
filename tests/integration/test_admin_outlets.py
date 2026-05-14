"""Integration tests for /admin/outlets CRUD."""
from __future__ import annotations

import pytest

from docket.config import DATABASE_URL
from docket.db import db
from docket.web import create_app


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run admin outlets tests against Railway DB.",
)


@pytest.fixture
def client_logged_in():
    app = create_app()
    app.config['TESTING'] = True
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO admin_users (username, password_hash) "
                "VALUES (%s, %s) RETURNING id",
                ('admin-outlet-test', 'unused'),
            )
            uid = cur.fetchone()[0]
        conn.commit()
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['admin_user'] = uid
            sess['admin_username'] = 'admin-outlet-test'
        yield c, uid
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM admin_users WHERE id = %s", (uid,))
        conn.commit()


def test_outlets_list_includes_seed(client_logged_in):
    c, _ = client_logged_in
    resp = c.get('/admin/outlets')
    assert resp.status_code == 200
    assert b'Birmingham Watch' in resp.data


def test_outlet_create(client_logged_in):
    c, _ = client_logged_in
    resp = c.post('/admin/outlets', data={
        'slug': 'test-outlet-xyz',
        'name': 'Test Outlet XYZ',
        'homepage': 'https://example.com',
    })
    assert resp.status_code in (302, 303)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM outlets WHERE slug = %s", ('test-outlet-xyz',))
            row = cur.fetchone()
            assert row is not None
            cur.execute("DELETE FROM outlets WHERE id = %s", (row[0],))
        conn.commit()
