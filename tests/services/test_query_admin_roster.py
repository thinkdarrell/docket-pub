"""docket.services.query: three reads behind the admin roster pages.

``get_admin_profile`` (the profile page), ``list_district_names`` (the
add-member form) and ``list_outlets`` (the outlet list) hold the statements
``src/docket/web/admin.py`` executed itself before plan
`admin-routes-call-services`, M1.

Seeded rows carry the prefix ``admros_test_`` (usernames, city slugs, outlet
slugs) and are deleted before and after every test. ``list_outlets`` reads a
whole table that other tests and the migrations also fill, so its tests
assert only on the rows seeded here. Each service name is imported inside
the test, so the file collects before the functions exist. Runs in the
services tier (DATABASE_URL names docket_test_*).
"""

from __future__ import annotations

import pytest

from docket.db import db_cursor

PREFIX = "admros_test_"


def _delete_seeded() -> None:
    with db_cursor() as cur:
        cur.execute("DELETE FROM admin_users WHERE username LIKE %s", (PREFIX + "%",))
        cur.execute("DELETE FROM outlets WHERE slug LIKE %s", (PREFIX + "%",))
        cur.execute(
            "DELETE FROM districts WHERE municipality_id IN "
            "(SELECT id FROM municipalities WHERE slug LIKE %s)",
            (PREFIX + "%",),
        )
        cur.execute("DELETE FROM municipalities WHERE slug LIKE %s", (PREFIX + "%",))


@pytest.fixture(autouse=True)
def _clean():
    _delete_seeded()
    yield
    _delete_seeded()


# --- get_admin_profile -------------------------------------------------------


def _user(suffix: str, display_name) -> int:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO admin_users (username, password_hash, display_name) "
            "VALUES (%s, 'unused', %s) RETURNING id",
            (PREFIX + suffix, display_name),
        )
        return cur.fetchone()["id"]


def test_get_admin_profile_returns_the_username_and_display_name_of_that_id():
    from docket.services.query import get_admin_profile

    _user("first", "First Byline")
    uid = _user("second", "Second Byline")
    profile = get_admin_profile(uid)
    assert dict(profile) == {"username": PREFIX + "second", "display_name": "Second Byline"}


def test_get_admin_profile_with_no_display_name_holds_none_under_the_key():
    from docket.services.query import get_admin_profile

    uid = _user("plain", None)
    assert dict(get_admin_profile(uid)) == {"username": PREFIX + "plain", "display_name": None}


def test_get_admin_profile_for_an_id_with_no_row_is_none():
    from docket.services.query import get_admin_profile

    _user("first", "First Byline")
    assert get_admin_profile(999999999) is None


# --- list_district_names -----------------------------------------------------


def _city(suffix: str) -> int:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO municipalities (slug, name, adapter_class, adapter_config, active)
               VALUES (%s, %s, 'GranicusAdapter', '{}', TRUE) RETURNING id""",
            (PREFIX + suffix, "Admros test " + suffix),
        )
        return cur.fetchone()["id"]


def _district(city_id: int, name: str, number: int) -> None:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO districts (municipality_id, name, number) VALUES (%s, %s, %s)",
            (city_id, name, number),
        )


def test_list_district_names_is_that_citys_names_in_number_order():
    from docket.services.query import list_district_names

    here = _city("here")
    other = _city("other")
    # Inserted out of number order, and named so that alphabetical order
    # is the reverse of number order.
    _district(here, "Admros Ward B", 2)
    _district(here, "Admros Ward C", 1)
    _district(here, "Admros Ward A", 3)
    _district(other, "Admros Elsewhere", 1)
    names = list_district_names(here)
    assert names == ["Admros Ward C", "Admros Ward B", "Admros Ward A"]
    assert all(isinstance(n, str) for n in names)
    assert list_district_names(other) == ["Admros Elsewhere"]


def test_list_district_names_for_a_city_with_no_district_is_an_empty_list():
    from docket.services.query import list_district_names

    assert list_district_names(_city("bare")) == []


# --- list_outlets ------------------------------------------------------------


def _outlet(suffix: str, name: str, *, homepage=None, is_active=True) -> int:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO outlets (slug, name, homepage, is_active) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (PREFIX + suffix, name, homepage, is_active),
        )
        return cur.fetchone()["id"]


def test_list_outlets_holds_the_five_columns_of_a_seeded_outlet_active_or_not():
    from docket.services.query import list_outlets

    before = [o for o in list_outlets() if o["slug"].startswith(PREFIX)]
    assert before == []
    active_id = _outlet("active", "Admros Active Outlet", homepage="https://active.example.org")
    inactive_id = _outlet("inactive", "Admros Inactive Outlet", is_active=False)
    mine = {o["slug"]: dict(o) for o in list_outlets() if o["slug"].startswith(PREFIX)}
    assert mine == {
        PREFIX + "active": {
            "id": active_id, "slug": PREFIX + "active", "name": "Admros Active Outlet",
            "homepage": "https://active.example.org", "is_active": True,
        },
        PREFIX + "inactive": {
            "id": inactive_id, "slug": PREFIX + "inactive", "name": "Admros Inactive Outlet",
            "homepage": None, "is_active": False,
        },
    }


def test_list_outlets_is_ordered_by_name():
    from docket.services.query import list_outlets

    # Inserted so that id order and slug order both differ from name order.
    _outlet("a", "Admros Outlet Mmm")
    _outlet("b", "Admros Outlet Zzz")
    _outlet("c", "Admros Outlet Aaa")
    mine = [o["name"] for o in list_outlets() if o["slug"].startswith(PREFIX)]
    assert mine == ["Admros Outlet Aaa", "Admros Outlet Mmm", "Admros Outlet Zzz"]
