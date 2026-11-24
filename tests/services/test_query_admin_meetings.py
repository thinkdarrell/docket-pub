"""docket.services.query: the two meeting reads behind the admin pages.

``get_meeting_city_slug`` (the city a meeting's public page lives under) and
``list_hidden_meetings`` (the index at ``/admin/meetings/hidden``) hold the
statements ``src/docket/web/admin.py`` executed itself before plan
`admin-routes-call-services`, M4.

One city is seeded whose slug begins ``admmtg_test_`` and one admin user
whose username does; the autouse fixture deletes the city's meetings, the
city, and the user (in that order: ``meetings.hidden_by`` points at the
user) before and after every test. ``list_hidden_meetings`` reads every
hidden meeting in the database, so a test looks only at the rows whose ids
it seeded. Each service name is imported inside the test, so the file
collects before the functions exist. Runs in the services tier (DATABASE_URL
names docket_test_*).
"""

from __future__ import annotations

import datetime

import pytest

from docket.db import db_cursor

PREFIX = "admmtg_test_"
SLUG = PREFIX + "city"
CITY_NAME = "Admmtg Test City"
ADMIN = PREFIX + "admin"
NO_SUCH_ID = 999999999
UTC = datetime.timezone.utc


def _delete_seeded() -> None:
    like = (PREFIX + "%",)
    with db_cursor() as cur:
        cur.execute(
            "DELETE FROM meetings WHERE municipality_id IN "
            "(SELECT id FROM municipalities WHERE slug LIKE %s)",
            like,
        )
        cur.execute("DELETE FROM municipalities WHERE slug LIKE %s", like)
        cur.execute("DELETE FROM admin_users WHERE username LIKE %s", like)


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
               VALUES (%s, %s, 'GranicusAdapter', '{}', TRUE) RETURNING id""",
            (SLUG, CITY_NAME),
        )
        return cur.fetchone()["id"]


@pytest.fixture
def admin() -> int:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO admin_users (username, password_hash) VALUES (%s, 'x') RETURNING id",
            (ADMIN,),
        )
        return cur.fetchone()["id"]


def _meeting(city_id: int, title: str, *, hidden: bool = True,
             hidden_at: datetime.datetime | None = None, hidden_by: int | None = None,
             reason: str | None = None) -> int:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO meetings
                 (municipality_id, title, meeting_date, is_hidden, hidden_at, hidden_by, hidden_reason)
               VALUES (%s, %s, '2026-04-15', %s, %s, %s, %s) RETURNING id""",
            (city_id, title, hidden, hidden_at, hidden_by, reason),
        )
        return cur.fetchone()["id"]


def _mine(rows: list[dict], ids: list[int]) -> list[dict]:
    return [r for r in rows if r["id"] in ids]


# --- get_meeting_city_slug ---------------------------------------------------


def test_get_meeting_city_slug_is_the_slug_of_that_meetings_city(city):
    from docket.services.query import get_meeting_city_slug

    meeting_id = _meeting(city, "Admmtg slug meeting", hidden=False)

    assert get_meeting_city_slug(meeting_id) == SLUG


def test_get_meeting_city_slug_for_an_unknown_meeting_is_none(city):
    from docket.services.query import get_meeting_city_slug

    _meeting(city, "Admmtg slug meeting", hidden=False)

    assert get_meeting_city_slug(NO_SUCH_ID) is None


# --- list_hidden_meetings ----------------------------------------------------


def test_list_hidden_meetings_holds_the_eight_columns_of_a_hidden_meeting(city, admin):
    from docket.services.query import list_hidden_meetings

    at = datetime.datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC)
    meeting_id = _meeting(city, "Admmtg hidden meeting", hidden_at=at, hidden_by=admin, reason="admin")

    rows = _mine(list_hidden_meetings(), [meeting_id])

    assert rows == [
        {
            "id": meeting_id,
            "title": "Admmtg hidden meeting",
            "meeting_date": datetime.date(2026, 4, 15),
            "hidden_at": at,
            "hidden_reason": "admin",
            "city_name": CITY_NAME,
            "city_slug": SLUG,
            "hidden_by_username": ADMIN,
        }
    ]
    assert type(rows[0]) is dict


def test_list_hidden_meetings_leaves_out_a_visible_meeting(city, admin):
    from docket.services.query import list_hidden_meetings

    hidden = _meeting(city, "Admmtg hidden meeting", hidden_by=admin)
    visible = _meeting(city, "Admmtg visible meeting", hidden=False)

    rows = _mine(list_hidden_meetings(), [hidden, visible])

    assert [r["id"] for r in rows] == [hidden]


def test_list_hidden_meetings_keeps_a_row_nobody_is_recorded_as_hiding(city):
    from docket.services.query import list_hidden_meetings

    meeting_id = _meeting(city, "Admmtg backfilled meeting")

    rows = _mine(list_hidden_meetings(), [meeting_id])

    assert len(rows) == 1
    assert rows[0]["hidden_by_username"] is None
    assert rows[0]["hidden_at"] is None
    assert rows[0]["hidden_reason"] is None


def test_list_hidden_meetings_is_latest_hidden_first_then_undated_then_highest_id(city):
    from docket.services.query import list_hidden_meetings

    early = datetime.datetime(2026, 1, 1, tzinfo=UTC)
    late = datetime.datetime(2026, 2, 1, tzinfo=UTC)
    # Seeded so that neither id order nor its reverse is the answer.
    undated_low = _meeting(city, "Admmtg undated low")
    late_a = _meeting(city, "Admmtg late a", hidden_at=late)
    early_one = _meeting(city, "Admmtg early", hidden_at=early)
    late_b = _meeting(city, "Admmtg late b", hidden_at=late)
    undated_high = _meeting(city, "Admmtg undated high")
    ids = [undated_low, late_a, early_one, late_b, undated_high]

    rows = _mine(list_hidden_meetings(), ids)

    assert [r["id"] for r in rows] == [late_b, late_a, early_one, undated_high, undated_low]
