"""Route tests for the four /admin/members routes.

Written against ``src/docket/web/admin.py`` while its member routes still
executed their own SQL, and seen to pass there, so that the same file
passing after the statements moved into ``docket.services`` shows the
routes answer as they did (plan `admin-routes-call-services`, M1).

One city is seeded whose slug begins ``admmem_test_``, with two districts.
The autouse fixture deletes the city's members, its districts and the city
before and after every test, children before parents, so a failed assertion
leaves nothing behind. No test asserts the size of a whole table.

The add-member form (``admin/member_form.html``) does not print the
district names the route hands it, so the GET test reads them from the
template context through Flask's ``template_rendered`` signal.
"""

from __future__ import annotations

import pytest
from flask import template_rendered

from docket.db import db_cursor

PREFIX = "admmem_test_"
SLUG = PREFIX + "city"
# Stored with numbers that reverse the alphabetical order, so a read ordered
# by ``number`` and one ordered by ``name`` differ.
DISTRICT_FIRST = "Admmem Ward Zulu"
DISTRICT_SECOND = "Admmem Ward Alpha"


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


@pytest.fixture
def city():
    """The seeded city: its id and the ids of its two districts."""
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO municipalities (slug, name, adapter_class, adapter_config, active)
               VALUES (%s, 'Admin Members Test City', 'GranicusAdapter', '{}', TRUE)
               RETURNING id""",
            (SLUG,),
        )
        city_id = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO districts (municipality_id, name, number) VALUES (%s, %s, 1) RETURNING id",
            (city_id, DISTRICT_FIRST),
        )
        first_id = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO districts (municipality_id, name, number) VALUES (%s, %s, 2) RETURNING id",
            (city_id, DISTRICT_SECOND),
        )
        second_id = cur.fetchone()["id"]
    return {"id": city_id, "first": first_id, "second": second_id}


def _seed_member(city_id: int, name: str, **cols) -> int:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO council_members (municipality_id, name, email, photo_url, active)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (city_id, name, cols.get("email"), cols.get("photo_url"), cols.get("active", True)),
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


def test_add_with_a_known_district_stores_the_member_under_it(authed_admin_client, city):
    resp = authed_admin_client.post("/admin/members/add", data={
        "municipality": SLUG, "name": "  Ada Known  ", "district": DISTRICT_SECOND,
        "email": "ada@example.gov", "photo_url": "https://example.gov/ada.jpg",
    })
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/admin/members/")
    rows = _members(city["id"])
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "Ada Known"
    assert row["district_id"] == city["second"]
    assert row["email"] == "ada@example.gov"
    assert row["photo_url"] == "https://example.gov/ada.jpg"
    assert row["active"] is True


def test_add_with_an_unknown_district_stores_a_null_district(authed_admin_client, city):
    resp = authed_admin_client.post("/admin/members/add", data={
        "municipality": SLUG, "name": "Una Unknown", "district": "No Such Ward",
    })
    assert resp.status_code == 302
    rows = _members(city["id"])
    assert [r["name"] for r in rows] == ["Una Unknown"]
    assert rows[0]["district_id"] is None
    assert rows[0]["email"] is None
    assert rows[0]["photo_url"] is None


def test_add_with_no_district_field_stores_a_null_district(authed_admin_client, city):
    resp = authed_admin_client.post("/admin/members/add", data={
        "municipality": SLUG, "name": "Nell Nofield",
    })
    assert resp.status_code == 302
    rows = _members(city["id"])
    assert [r["name"] for r in rows] == ["Nell Nofield"]
    assert rows[0]["district_id"] is None
    assert rows[0]["active"] is True


def test_add_form_is_handed_the_citys_district_names_in_number_order(authed_admin_client, city):
    captured = []

    def _record(sender, template, context, **extra):
        captured.append((template.name, context))

    app = authed_admin_client.application
    with template_rendered.connected_to(_record, app):
        resp = authed_admin_client.get("/admin/members/add")
    assert resp.status_code == 200
    contexts = [ctx for name, ctx in captured if name == "admin/member_form.html"]
    assert len(contexts) == 1
    assert contexts[0]["districts_by_city"][SLUG] == [DISTRICT_FIRST, DISTRICT_SECOND]
    # The city itself is listed in the form's select.
    assert b"Admin Members Test City" in resp.data


def test_edit_changes_the_four_fields(authed_admin_client, city):
    member_id = _seed_member(city["id"], "Ed Before", email="before@example.gov",
                             photo_url="https://example.gov/before.jpg", active=False)
    other_id = _seed_member(city["id"], "Olga Other", email="olga@example.gov")
    resp = authed_admin_client.post(f"/admin/members/{member_id}/edit", data={
        "name": "  Ed After ", "email": "after@example.gov",
        "photo_url": "https://example.gov/after.jpg", "active": "on",
    })
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/admin/members/")
    row = _member(member_id)
    assert row["name"] == "Ed After"
    assert row["email"] == "after@example.gov"
    assert row["photo_url"] == "https://example.gov/after.jpg"
    assert row["active"] is True
    other = _member(other_id)
    assert other["name"] == "Olga Other"
    assert other["email"] == "olga@example.gov"


def test_edit_with_empty_email_and_photo_url_stores_null_and_inactive(authed_admin_client, city):
    member_id = _seed_member(city["id"], "Nia Nulls", email="nia@example.gov",
                             photo_url="https://example.gov/nia.jpg", active=True)
    resp = authed_admin_client.post(f"/admin/members/{member_id}/edit", data={
        "name": "Nia Nulls", "email": "", "photo_url": "  ",
    })
    assert resp.status_code == 302
    row = _member(member_id)
    assert row["email"] is None
    assert row["photo_url"] is None
    # No "active" field in the form means the checkbox was clear.
    assert row["active"] is False


def test_deactivate_sets_active_false_on_that_member_only(authed_admin_client, city):
    member_id = _seed_member(city["id"], "Dee Activate")
    other_id = _seed_member(city["id"], "Stays Active")
    resp = authed_admin_client.post(f"/admin/members/{member_id}/deactivate")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/admin/members/")
    assert _member(member_id)["active"] is False
    assert _member(other_id)["active"] is True
