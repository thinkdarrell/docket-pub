"""docket.services.non_meetings: the admin's hide and unhide of one meeting.

``hide_by_admin`` and ``unhide_by_admin`` hold the statements the routes
``POST /admin/meetings/<id>/hide`` and ``POST /admin/meetings/<id>/unhide``
executed themselves before plan `admin-routes-call-services`, M4. Each is one
transaction: ask whether the meeting exists, then one UPDATE.

One city is seeded whose slug begins ``admhide_test_`` and one admin user
whose username does; the autouse fixture deletes the city's meetings, the
city, and the user (in that order: ``meetings.hidden_by`` points at the
user) before and after every test. Each service name is imported inside the
test, so the file collects before the functions exist. Runs in the services
tier (DATABASE_URL names docket_test_*).
"""

from __future__ import annotations

import pytest

from docket.db import db_cursor

PREFIX = "admhide_test_"
NO_SUCH_ID = 999999999

_COLUMNS = "is_hidden, hidden_at, hidden_by, hidden_reason, keep_visible_at"


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
               VALUES (%s, 'Admhide Test City', 'GranicusAdapter', '{}', TRUE) RETURNING id""",
            (PREFIX + "city",),
        )
        return cur.fetchone()["id"]


@pytest.fixture
def admin() -> int:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO admin_users (username, password_hash) VALUES (%s, 'x') RETURNING id",
            (PREFIX + "admin",),
        )
        return cur.fetchone()["id"]


def _visible(city_id: int, *, kept: bool = False) -> int:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO meetings (municipality_id, title, meeting_date, keep_visible_at)
               VALUES (%s, 'Admhide test meeting', '2026-04-15',
                       CASE WHEN %s THEN TIMESTAMPTZ '2026-01-02 03:04:05+00' END)
               RETURNING id""",
            (city_id, kept),
        )
        return cur.fetchone()["id"]


def _hidden(city_id: int, admin_id: int, reason: str = "not_a_meeting") -> int:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO meetings
                 (municipality_id, title, meeting_date, is_hidden, hidden_at, hidden_by, hidden_reason)
               VALUES (%s, 'Admhide test meeting', '2026-04-15', TRUE,
                       TIMESTAMPTZ '2026-01-02 03:04:05+00', %s, %s)
               RETURNING id""",
            (city_id, admin_id, reason),
        )
        return cur.fetchone()["id"]


def _state(meeting_id: int) -> dict:
    with db_cursor() as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM meetings WHERE id = %s", (meeting_id,))
        return dict(cur.fetchone())


def _seconds_since(meeting_id: int, column: str) -> float:
    with db_cursor() as cur:
        cur.execute(
            f"SELECT EXTRACT(EPOCH FROM NOW() - {column})::float AS age FROM meetings WHERE id = %s",
            (meeting_id,),
        )
        return cur.fetchone()["age"]


# --- hide_by_admin -----------------------------------------------------------


def test_hide_by_admin_sets_the_flag_the_time_the_actor_and_the_reason(city, admin):
    from docket.services.non_meetings import hide_by_admin

    meeting_id = _visible(city)

    assert hide_by_admin(meeting_id, admin) is True

    state = _state(meeting_id)
    assert state["is_hidden"] is True
    assert state["hidden_by"] == admin
    assert state["hidden_reason"] == "admin"
    assert state["hidden_at"] is not None
    assert 0 <= _seconds_since(meeting_id, "hidden_at") < 60
    assert state["keep_visible_at"] is None


def test_hide_by_admin_with_no_actor_stores_a_null_hidden_by(city):
    from docket.services.non_meetings import hide_by_admin

    meeting_id = _visible(city)

    assert hide_by_admin(meeting_id, None) is True

    state = _state(meeting_id)
    assert state["is_hidden"] is True
    assert state["hidden_by"] is None
    assert state["hidden_reason"] == "admin"


def test_hide_by_admin_leaves_an_exemption_as_it_stood(city, admin):
    from docket.services.non_meetings import hide_by_admin

    meeting_id = _visible(city, kept=True)
    before = _state(meeting_id)["keep_visible_at"]
    assert before is not None

    assert hide_by_admin(meeting_id, admin) is True

    state = _state(meeting_id)
    assert state["is_hidden"] is True
    assert state["keep_visible_at"] == before


def test_hide_by_admin_touches_that_meeting_only(city, admin):
    from docket.services.non_meetings import hide_by_admin

    meeting_id = _visible(city)
    other = _visible(city)
    other_before = _state(other)

    assert hide_by_admin(meeting_id, admin) is True

    assert _state(other) == other_before
    assert _state(other)["is_hidden"] is False


def test_hide_by_admin_for_an_unknown_meeting_is_false_and_hides_nothing(city, admin):
    from docket.services.non_meetings import hide_by_admin

    seeded = _visible(city)
    before = _state(seeded)

    assert hide_by_admin(NO_SUCH_ID, admin) is False

    assert _state(seeded) == before


# --- unhide_by_admin ---------------------------------------------------------


def test_unhide_by_admin_clears_the_four_and_exempts_the_row(city, admin):
    from docket.services.non_meetings import unhide_by_admin

    meeting_id = _hidden(city, admin)
    assert _state(meeting_id)["keep_visible_at"] is None

    assert unhide_by_admin(meeting_id) is True

    state = _state(meeting_id)
    assert state["is_hidden"] is False
    assert state["hidden_at"] is None
    assert state["hidden_by"] is None
    assert state["hidden_reason"] is None
    assert state["keep_visible_at"] is not None
    assert 0 <= _seconds_since(meeting_id, "keep_visible_at") < 60


def test_unhide_by_admin_touches_that_meeting_only(city, admin):
    from docket.services.non_meetings import unhide_by_admin

    meeting_id = _hidden(city, admin)
    other = _hidden(city, admin, reason="admin")
    other_before = _state(other)

    assert unhide_by_admin(meeting_id) is True

    assert _state(other) == other_before
    assert _state(other)["is_hidden"] is True


def test_unhide_by_admin_for_an_unknown_meeting_is_false_and_unhides_nothing(city, admin):
    from docket.services.non_meetings import unhide_by_admin

    seeded = _hidden(city, admin)
    before = _state(seeded)

    assert unhide_by_admin(NO_SUCH_ID) is False

    assert _state(seeded) == before
