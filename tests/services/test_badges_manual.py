"""docket.services.badges: the admin's manual badge add and remove.

``add_manual_badge`` and ``remove_manual_badge`` hold the statements the
routes ``POST /admin/badges/<id>/add/<slug>`` and
``POST /admin/badges/<id>/remove/<slug>`` executed themselves before plan
`admin-routes-call-services`, M2. Each is one transaction, and each writes
its audit row through ``record_badge_action`` of the same module.

One city is seeded whose slug begins ``bdgman_test_``; the autouse fixture
deletes the badge audit rows of its items (that foreign key sets NULL
instead of cascading), then its meetings (items and their badges go with
them), then the city, before and after every test. The two slugs used are
templates the migrations seed, one of each kind. Each service name is
imported inside the test, so the file collects before the functions exist.
Runs in the services tier (DATABASE_URL names docket_test_*).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from docket.db import db_cursor

PREFIX = "bdgman_test_"
NO_SUCH_ID = 999999999
ACTOR = "bdgman-operator"
POLICY_SLUG = "blight_accountability"
PROCESS_SLUG = "contested"
NO_SUCH_SLUG = "bdgman_test_no_such_slug"

_ITEMS_OF_PREFIX = (
    "(SELECT ai.id FROM agenda_items ai "
    "JOIN meetings mt ON mt.id = ai.meeting_id "
    "JOIN municipalities m ON m.id = mt.municipality_id "
    "WHERE m.slug LIKE %s)"
)


def _delete_seeded() -> None:
    like = (PREFIX + "%",)
    with db_cursor() as cur:
        cur.execute(
            "DELETE FROM agenda_item_badges_audit WHERE agenda_item_id IN " + _ITEMS_OF_PREFIX,
            like,
        )
        cur.execute(
            "DELETE FROM agenda_item_badges_audit WHERE badge_slug = %s", (NO_SUCH_SLUG,)
        )
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


def _city(suffix: str) -> int:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO municipalities (slug, name, adapter_class, adapter_config, active)
               VALUES (%s, %s, 'GranicusAdapter', '{}', TRUE) RETURNING id""",
            (PREFIX + suffix, "Bdgman test " + suffix),
        )
        return cur.fetchone()["id"]


def _item(city_id: int) -> int:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO meetings (municipality_id, title, meeting_date)
               VALUES (%s, 'Bdgman test meeting', '2026-04-15') RETURNING id""",
            (city_id,),
        )
        meeting_id = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO agenda_items (meeting_id, title) VALUES (%s, 'Bdgman test item') RETURNING id",
            (meeting_id,),
        )
        return cur.fetchone()["id"]


def _attach(item_id: int, city_id: int, slug: str) -> None:
    """A badge the pipeline attached, with no audit row."""
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO agenda_item_badges
                 (agenda_item_id, city_id, badge_slug, kind, confidence, source)
               VALUES (%s, %s, %s, 'policy', 0.80, 'llm')""",
            (item_id, city_id, slug),
        )


def _badges(item_id: int) -> list[dict]:
    with db_cursor() as cur:
        cur.execute(
            """SELECT city_id, badge_slug, kind, confidence, source,
                      matching_metadata, status
                 FROM agenda_item_badges WHERE agenda_item_id = %s
                ORDER BY badge_slug""",
            (item_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def _audit_rows(item_id: int) -> list[dict]:
    with db_cursor() as cur:
        cur.execute(
            """SELECT badge_slug, action, actor, actor_role, reason
                 FROM agenda_item_badges_audit
                WHERE agenda_item_id = %s ORDER BY id""",
            (item_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def _audit_reading() -> tuple[int, int]:
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n, COALESCE(MAX(id), 0) AS top FROM agenda_item_badges_audit")
        row = cur.fetchone()
        return row["n"], row["top"]


def _template_kind(slug: str) -> str:
    with db_cursor() as cur:
        cur.execute("SELECT kind FROM priority_badge_templates WHERE slug = %s", (slug,))
        return cur.fetchone()["kind"]


# --- add_manual_badge --------------------------------------------------------


def test_the_two_slugs_are_templates_of_different_kinds():
    assert _template_kind(POLICY_SLUG) == "policy"
    assert _template_kind(PROCESS_SLUG) == "process"


@pytest.mark.parametrize("slug,kind", [(POLICY_SLUG, "policy"), (PROCESS_SLUG, "process")])
def test_add_manual_badge_writes_the_badge_and_one_audit_row(slug, kind):
    from docket.services.badges import add_manual_badge

    _city("other")
    city_id = _city("city")
    iid = _item(city_id)

    assert add_manual_badge(iid, slug, ACTOR) is True

    assert _badges(iid) == [{
        "city_id": city_id,
        "badge_slug": slug,
        "kind": kind,
        "confidence": Decimal("0.95"),
        "source": "manual",
        "matching_metadata": {"manual": True, "added_by": ACTOR},
        "status": "applied",
    }]
    assert _audit_rows(iid) == [{
        "badge_slug": slug,
        "action": "added",
        "actor": ACTOR,
        "actor_role": "admin",
        "reason": None,
    }]


def test_add_manual_badge_repeated_is_false_with_no_second_audit_row():
    from docket.services.badges import add_manual_badge

    city_id = _city("city")
    iid = _item(city_id)
    assert add_manual_badge(iid, POLICY_SLUG, ACTOR) is True

    assert add_manual_badge(iid, POLICY_SLUG, "someone-else") is False

    badges = _badges(iid)
    assert len(badges) == 1
    assert badges[0]["matching_metadata"] == {"manual": True, "added_by": ACTOR}
    assert len(_audit_rows(iid)) == 1


def test_add_manual_badge_over_a_pipeline_badge_is_false_and_leaves_it():
    from docket.services.badges import add_manual_badge

    city_id = _city("city")
    iid = _item(city_id)
    _attach(iid, city_id, POLICY_SLUG)
    before = _badges(iid)

    assert add_manual_badge(iid, POLICY_SLUG, ACTOR) is False

    assert _badges(iid) == before
    assert _audit_rows(iid) == []


def test_add_manual_badge_touches_that_item_only():
    from docket.services.badges import add_manual_badge

    city_id = _city("city")
    other = _item(city_id)
    iid = _item(city_id)

    add_manual_badge(iid, POLICY_SLUG, ACTOR)

    assert _badges(other) == []
    assert _audit_rows(other) == []


def test_add_manual_badge_for_an_unknown_item_is_none_and_writes_nothing():
    from docket.services.badges import add_manual_badge

    before = _audit_reading()

    assert add_manual_badge(NO_SUCH_ID, POLICY_SLUG, ACTOR) is None

    assert _audit_reading() == before
    assert _badges(NO_SUCH_ID) == []


def test_add_manual_badge_for_an_unknown_slug_is_none_and_writes_nothing():
    from docket.services.badges import add_manual_badge

    iid = _item(_city("city"))
    before = _audit_reading()

    assert add_manual_badge(iid, NO_SUCH_SLUG, ACTOR) is None

    assert _audit_reading() == before
    assert _badges(iid) == []


# --- remove_manual_badge -----------------------------------------------------


def test_remove_manual_badge_deletes_that_badge_and_writes_one_audit_row():
    from docket.services.badges import remove_manual_badge

    city_id = _city("city")
    iid = _item(city_id)
    _attach(iid, city_id, POLICY_SLUG)
    _attach(iid, city_id, PROCESS_SLUG)
    other = _item(city_id)
    _attach(other, city_id, POLICY_SLUG)

    assert remove_manual_badge(iid, POLICY_SLUG, ACTOR) is True

    # The other badge of the item and the same badge on another item stay.
    assert [b["badge_slug"] for b in _badges(iid)] == [PROCESS_SLUG]
    assert [b["badge_slug"] for b in _badges(other)] == [POLICY_SLUG]
    assert _audit_rows(iid) == [{
        "badge_slug": POLICY_SLUG,
        "action": "removed",
        "actor": ACTOR,
        "actor_role": "admin",
        "reason": None,
    }]
    assert _audit_rows(other) == []


def test_remove_manual_badge_not_attached_is_false_with_no_audit_row():
    from docket.services.badges import remove_manual_badge

    city_id = _city("city")
    iid = _item(city_id)
    _attach(iid, city_id, PROCESS_SLUG)
    before = _audit_reading()

    assert remove_manual_badge(iid, POLICY_SLUG, ACTOR) is False

    assert _audit_reading() == before
    assert [b["badge_slug"] for b in _badges(iid)] == [PROCESS_SLUG]


def test_remove_manual_badge_for_an_unknown_item_is_false_with_no_audit_row():
    from docket.services.badges import remove_manual_badge

    before = _audit_reading()

    assert remove_manual_badge(NO_SUCH_ID, POLICY_SLUG, ACTOR) is False

    assert _audit_reading() == before
