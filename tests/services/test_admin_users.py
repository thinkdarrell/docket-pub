"""docket.services.admin_users.set_display_name: the admin's byline write.

The one statement POST /admin/profile/display-name executed itself before
plan `admin-routes-call-services`, M1. The function takes the id as given,
with no conversion (the plan carries the admin session-key mismatch
unchanged), so these tests pass the integer id the table holds.

Two ``admin_users`` rows are seeded whose usernames begin ``admusr_test_``
and are deleted before and after every test. The service's name is imported
inside each test, so the file collects before the module exists. Runs in the
services tier (DATABASE_URL names docket_test_*).
"""

from __future__ import annotations

import pytest

from docket.db import db_cursor

PREFIX = "admusr_test_"


def _delete_seeded() -> None:
    with db_cursor() as cur:
        cur.execute("DELETE FROM admin_users WHERE username LIKE %s", (PREFIX + "%",))


@pytest.fixture(autouse=True)
def _clean():
    _delete_seeded()
    yield
    _delete_seeded()


def _user(suffix: str, display_name) -> int:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO admin_users (username, password_hash, display_name) "
            "VALUES (%s, 'unused', %s) RETURNING id",
            (PREFIX + suffix, display_name),
        )
        return cur.fetchone()["id"]


def _row(uid: int) -> dict:
    with db_cursor() as cur:
        cur.execute(
            "SELECT username, password_hash, display_name FROM admin_users WHERE id = %s",
            (uid,),
        )
        return dict(cur.fetchone())


def test_set_display_name_stores_the_name_on_that_user_only():
    from docket.services.admin_users import set_display_name

    uid = _user("one", "Old Byline")
    other = _user("two", "Other Byline")
    assert set_display_name(uid, "New Byline") is None
    assert _row(uid) == {"username": PREFIX + "one", "password_hash": "unused",
                         "display_name": "New Byline"}
    assert _row(other)["display_name"] == "Other Byline"


def test_set_display_name_with_none_stores_null():
    from docket.services.admin_users import set_display_name

    uid = _user("one", "Old Byline")
    other = _user("two", "Other Byline")
    set_display_name(uid, None)
    assert _row(uid)["display_name"] is None
    assert _row(other)["display_name"] == "Other Byline"


def test_set_display_name_for_an_id_with_no_row_changes_no_seeded_user():
    from docket.services.admin_users import set_display_name

    uid = _user("one", "Old Byline")
    assert set_display_name(999999999, "Ghost") is None
    assert _row(uid)["display_name"] == "Old Byline"
