"""docket.services.query: two single-item reads behind the admin pages.

``get_item_for_badge_manage`` (the badge-manage page and its swap panel) and
``get_conflict_form_item`` (the three inline conflict forms) hold the
statements ``src/docket/web/admin.py`` executed itself before plan
`admin-routes-call-services`, M2.

One city is seeded whose slug begins ``admitm_test_``; the autouse fixture
deletes its meetings (items go with them) and the city before and after
every test. Each service name is imported inside the test, so the file
collects before the functions exist. Runs in the services tier (DATABASE_URL
names docket_test_*).
"""

from __future__ import annotations

import datetime
import json

import pytest

from docket.db import db_cursor

PREFIX = "admitm_test_"
SLUG = PREFIX + "city"
NO_SUCH_ID = 999999999


def _delete_seeded() -> None:
    like = (PREFIX + "%",)
    with db_cursor() as cur:
        cur.execute(
            "DELETE FROM meetings WHERE municipality_id IN "
            "(SELECT id FROM municipalities WHERE slug LIKE %s)",
            like,
        )
        cur.execute("DELETE FROM municipalities WHERE slug LIKE %s", like)


@pytest.fixture(autouse=True)
def _clean():
    _delete_seeded()
    yield
    _delete_seeded()


@pytest.fixture
def city() -> int:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO municipalities (slug, name, adapter_class, adapter_config, active)
               VALUES (%s, 'Admitm Test City', 'GranicusAdapter', '{}', TRUE) RETURNING id""",
            (SLUG,),
        )
        return cur.fetchone()["id"]


def _meeting(city_id: int, day: str) -> int:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO meetings (municipality_id, title, meeting_date)
               VALUES (%s, 'Admitm test meeting', %s) RETURNING id""",
            (city_id, day),
        )
        return cur.fetchone()["id"]


def _item(meeting_id: int, title: str, *, status: str = "pending",
          facts: dict | None = None) -> int:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO agenda_items (meeting_id, title, processing_status, extracted_facts)
               VALUES (%s, %s, %s::processing_status_enum, %s::jsonb) RETURNING id""",
            (meeting_id, title, status, json.dumps(facts) if facts is not None else None),
        )
        return cur.fetchone()["id"]


# --- get_item_for_badge_manage ----------------------------------------------


def test_get_item_for_badge_manage_returns_the_seven_columns_of_that_item(city):
    from docket.services.query import get_item_for_badge_manage

    first_meeting = _meeting(city, "2026-03-03")
    second_meeting = _meeting(city, "2026-04-15")
    _item(first_meeting, "Admitm first item")
    iid = _item(second_meeting, "Admitm second item")

    assert dict(get_item_for_badge_manage(iid)) == {
        "id": iid,
        "title": "Admitm second item",
        "municipality_id": city,
        "municipality_slug": SLUG,
        "municipality_name": "Admitm Test City",
        "meeting_id": second_meeting,
        "meeting_date": datetime.date(2026, 4, 15),
    }


def test_get_item_for_badge_manage_for_an_unknown_item_is_none(city):
    from docket.services.query import get_item_for_badge_manage

    _item(_meeting(city, "2026-04-15"), "Admitm item")
    assert get_item_for_badge_manage(NO_SUCH_ID) is None


# --- get_conflict_form_item --------------------------------------------------


def test_get_conflict_form_item_returns_id_facts_and_status_as_text(city):
    from docket.services.query import get_conflict_form_item

    meeting_id = _meeting(city, "2026-04-15")
    _item(meeting_id, "Admitm other", status="completed", facts={"counterparty": "Other LLC"})
    facts = {"counterparty": "Admitm LLC", "dollars": 125000}
    iid = _item(meeting_id, "Admitm conflicted", status="cross_stage_conflict", facts=facts)

    row = get_conflict_form_item(iid)
    assert dict(row) == {
        "id": iid,
        "extracted_facts": facts,
        "processing_status": "cross_stage_conflict",
    }
    assert type(row["processing_status"]) is str


def test_get_conflict_form_item_with_no_facts_holds_none_under_the_key(city):
    from docket.services.query import get_conflict_form_item

    iid = _item(_meeting(city, "2026-04-15"), "Admitm bare", status="completed")

    assert dict(get_conflict_form_item(iid)) == {
        "id": iid,
        "extracted_facts": None,
        "processing_status": "completed",
    }


def test_get_conflict_form_item_for_an_unknown_item_is_none(city):
    from docket.services.query import get_conflict_form_item

    _item(_meeting(city, "2026-04-15"), "Admitm item", status="cross_stage_conflict")
    assert get_conflict_form_item(NO_SUCH_ID) is None
