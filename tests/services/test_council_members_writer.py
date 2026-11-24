"""docket.services.council_members_writer: the admin's three roster writes.

``add_member``, ``update_member`` and ``deactivate_member`` hold the
statements the /admin/members routes executed themselves before plan
`admin-routes-call-services`, M1.

Two cities are seeded whose slugs begin ``cmw_test_``; the autouse fixture
deletes their members, their districts and the cities before and after every
test. Each service name is imported inside the test, so the file collects
before the module exists. Runs in the services tier (DATABASE_URL names
docket_test_*).
"""

from __future__ import annotations

import pytest

from docket.db import db_cursor

PREFIX = "cmw_test_"
WARD = "Cmw Ward One"
NO_SUCH_ID = 999999999


def _delete_seeded() -> None:
    with db_cursor() as cur:
        cur.execute(
            "DELETE FROM council_members WHERE municipality_id IN "
            "(SELECT id FROM municipalities WHERE slug LIKE %s)",
            (PREFIX + "%",),
        )
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


def _city(suffix: str) -> int:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO municipalities (slug, name, adapter_class, adapter_config, active)
               VALUES (%s, %s, 'GranicusAdapter', '{}', TRUE) RETURNING id""",
            (PREFIX + suffix, "Cmw test " + suffix),
        )
        return cur.fetchone()["id"]


def _district(city_id: int, name: str, number: int) -> int:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO districts (municipality_id, name, number) VALUES (%s, %s, %s) RETURNING id",
            (city_id, name, number),
        )
        return cur.fetchone()["id"]


@pytest.fixture
def cities():
    """Two cities that each have a district of the same name.

    The other city is seeded first, so a lookup that forgot the city would
    find its district, not the one asked for.
    """
    other = _city("other")
    other_ward = _district(other, WARD, 1)
    here = _city("here")
    here_ward = _district(here, WARD, 1)
    return {"here": here, "here_ward": here_ward, "other": other, "other_ward": other_ward}


def _seed_member(city_id: int, name: str, *, email=None, photo_url=None, active=True) -> int:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO council_members (municipality_id, name, email, photo_url, active)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (city_id, name, email, photo_url, active),
        )
        return cur.fetchone()["id"]


def _members(city_id: int) -> list[dict]:
    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM council_members WHERE municipality_id = %s ORDER BY id",
            (city_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def _member(member_id: int) -> dict:
    with db_cursor() as cur:
        cur.execute("SELECT * FROM council_members WHERE id = %s", (member_id,))
        return dict(cur.fetchone())


# --- add_member --------------------------------------------------------------


def test_add_member_stores_the_row_under_the_named_district_of_that_city(cities):
    from docket.services.council_members_writer import add_member

    result = add_member(
        municipality_id=cities["here"], name="Ada Added", district_name=WARD,
        email="ada@example.gov", photo_url="https://example.gov/ada.jpg",
    )
    assert result is None
    rows = _members(cities["here"])
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "Ada Added"
    assert row["district_id"] == cities["here_ward"]
    assert row["email"] == "ada@example.gov"
    assert row["photo_url"] == "https://example.gov/ada.jpg"
    assert row["active"] is True
    assert _members(cities["other"]) == []


def test_add_member_with_an_unknown_district_name_stores_a_null_district(cities):
    from docket.services.council_members_writer import add_member

    add_member(municipality_id=cities["here"], name="Una Unknown",
               district_name="No Such Ward", email=None, photo_url=None)
    rows = _members(cities["here"])
    assert [r["name"] for r in rows] == ["Una Unknown"]
    assert rows[0]["district_id"] is None
    assert rows[0]["email"] is None
    assert rows[0]["photo_url"] is None
    assert rows[0]["active"] is True


def test_add_member_with_an_empty_district_name_looks_nothing_up(cities):
    from docket.services.council_members_writer import add_member

    # A district whose name is the empty string: a lookup made for an empty
    # name would find it, and the member must not land under it.
    _district(cities["here"], "", 9)
    add_member(municipality_id=cities["here"], name="Eve Empty",
               district_name="", email=None, photo_url=None)
    rows = _members(cities["here"])
    assert [r["name"] for r in rows] == ["Eve Empty"]
    assert rows[0]["district_id"] is None


# --- update_member -----------------------------------------------------------


def test_update_member_changes_the_four_fields_of_that_member_only(cities):
    from docket.services.council_members_writer import update_member

    member_id = _seed_member(cities["here"], "Ed Before", email="before@example.gov",
                             photo_url="https://example.gov/before.jpg", active=False)
    other_id = _seed_member(cities["here"], "Olga Other", email="olga@example.gov",
                            photo_url="https://example.gov/olga.jpg", active=False)
    result = update_member(member_id, name="Ed After", email="after@example.gov",
                           photo_url="https://example.gov/after.jpg", active=True)
    assert result is None
    row = _member(member_id)
    assert row["name"] == "Ed After"
    assert row["email"] == "after@example.gov"
    assert row["photo_url"] == "https://example.gov/after.jpg"
    assert row["active"] is True
    other = _member(other_id)
    assert other["name"] == "Olga Other"
    assert other["email"] == "olga@example.gov"
    assert other["photo_url"] == "https://example.gov/olga.jpg"
    assert other["active"] is False


def test_update_member_with_none_email_and_photo_url_stores_null(cities):
    from docket.services.council_members_writer import update_member

    member_id = _seed_member(cities["here"], "Nia Nulls", email="nia@example.gov",
                             photo_url="https://example.gov/nia.jpg", active=True)
    update_member(member_id, name="Nia Nulls", email=None, photo_url=None, active=False)
    row = _member(member_id)
    assert row["email"] is None
    assert row["photo_url"] is None
    assert row["active"] is False


def test_update_member_for_an_id_with_no_row_changes_no_seeded_member(cities):
    from docket.services.council_members_writer import update_member

    member_id = _seed_member(cities["here"], "Sam Stays", email="sam@example.gov")
    before = _member(member_id)
    assert update_member(NO_SUCH_ID, name="Ghost", email=None, photo_url=None, active=False) is None
    assert _member(member_id) == before


# --- deactivate_member -------------------------------------------------------


def test_deactivate_member_sets_active_false_on_that_member_only(cities):
    from docket.services.council_members_writer import deactivate_member

    member_id = _seed_member(cities["here"], "Dee Activate", email="dee@example.gov")
    other_id = _seed_member(cities["here"], "Stays Active")
    assert deactivate_member(member_id) is None
    row = _member(member_id)
    assert row["active"] is False
    assert row["name"] == "Dee Activate"
    assert row["email"] == "dee@example.gov"
    assert _member(other_id)["active"] is True


def test_deactivate_member_for_an_id_with_no_row_changes_no_seeded_member(cities):
    from docket.services.council_members_writer import deactivate_member

    member_id = _seed_member(cities["here"], "Sam Stays")
    before = _member(member_id)
    assert deactivate_member(NO_SUCH_ID) is None
    assert _member(member_id) == before
