"""Verify migration 049: Mobile's council roster with term dates, from the city's minutes and council page.

Pattern: tests/integration/test_048_migration.py. Plan `mobile-agendas-flow-again`, M5.
The migration module and the runner's list are read inside the test functions, so the file
collects before the migration exists.

The roll calls below are the ones the plan's author read in the city's minutes (the migration's
docstring gives each with its event id, file id and words). Every row whose name begins `M049 `
is built by a test and is not a member any city seated.
"""
import importlib
from datetime import date

import pytest
from docket.config import DATABASE_URL
from docket.db import db, db_cursor
from docket.migrations import runner
from docket.services.member_votes import load_roster_index

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Migration test must not run against Railway prod.",
)

MODULE = "docket.migrations.049_mobile_council_terms"
TEST_NAMES = "M049 %"

# name, district number, term_start, term_end, active: what the migration leaves, by district then term.
EXPECTED = [
    ("Cory Penn", 1, date(2021, 11, 2), None, True),
    ("William Carroll", 2, date(2021, 11, 2), date(2025, 11, 4), False),
    ("Samantha Ingram", 2, date(2025, 11, 4), None, True),
    ("C.J. Small", 3, date(2021, 11, 2), None, True),
    ("Ben Reynolds", 4, date(2021, 11, 2), None, True),
    ("Joel Daves", 5, date(2021, 11, 2), date(2025, 11, 4), False),
    ("Beau Fleming", 5, date(2025, 11, 4), None, True),
    ("Scott Jones", 6, date(2021, 11, 2), date(2023, 8, 8), False),
    ("Josh Woods", 6, date(2023, 8, 8), None, True),
    ("Gina Gregory", 7, date(2021, 11, 2), None, True),
]

# What migration 005 seeded, which the down restores.
SEEDED = [
    ("Cory Penn", 1, None, None, True),
    ("William Carroll", 2, None, None, True),
    ("C.J. Small", 3, None, None, True),
    ("Ben Reynolds", 4, None, None, True),
    ("Beau Fleming", 5, None, None, True),
    ("Josh Woods", 6, None, None, True),
    ("Gina Gregory", 7, None, None, True),
]

# The roll call of each date, by surname, as the city's minutes print it. On 2021-11-02 the minutes
# print "Scott" for the seventh member; see test_049_names_that_must_not_resolve.
_SIX = ["Penn", "Carroll", "Small", "Reynolds", "Daves", "Gregory"]
_WITH_JONES = _SIX + ["Jones"]
_WITH_WOODS = ["Penn", "Carroll", "Small", "Reynolds", "Daves", "Woods", "Gregory"]
_SEATED = ["Penn", "Ingram", "Small", "Reynolds", "Fleming", "Woods", "Gregory"]
ROLL_CALLS = {
    date(2021, 11, 2): _SIX,
    date(2022, 9, 13): _WITH_JONES,
    date(2023, 3, 28): _WITH_JONES,
    date(2023, 8, 8): _WITH_WOODS,
    date(2025, 10, 28): _WITH_WOODS,
    date(2025, 11, 4): _SEATED,
    date(2026, 11, 3): _SEATED,
}


def _city_id(slug: str) -> int:
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug = %s", (slug,))
        return cur.fetchone()["id"]


def _roster(slug: str = "mobile") -> list[tuple]:
    with db_cursor() as cur:
        cur.execute(
            "SELECT cm.name, d.number, cm.term_start, cm.term_end, cm.active "
            "FROM council_members cm JOIN municipalities mu ON mu.id = cm.municipality_id "
            "LEFT JOIN districts d ON d.id = cm.district_id "
            "WHERE mu.slug = %s ORDER BY d.number, cm.term_start NULLS FIRST, cm.name",
            (slug,),
        )
        return [(r["name"], r["number"], r["term_start"], r["term_end"], r["active"]) for r in cur.fetchall()]


def _names_by_id() -> dict[int, str]:
    with db_cursor() as cur:
        cur.execute("SELECT id, name FROM council_members WHERE municipality_id = %s", (_city_id("mobile"),))
        return {r["id"]: r["name"] for r in cur.fetchall()}


def _delete_test_rows() -> None:
    with db_cursor() as cur:
        cur.execute("DELETE FROM council_members WHERE name LIKE %s", (TEST_NAMES,))


@pytest.fixture
def applied_049():
    """Every migration applied before the test and again after it."""
    _delete_test_rows()
    with db() as conn:
        runner.apply_migrations(conn)
    yield
    _delete_test_rows()
    with db() as conn:
        runner.apply_migrations(conn)


def test_049_a_second_run_adds_no_row_and_changes_none(applied_049):
    versions = [int(m.rsplit(".", 1)[-1].split("_")[0]) for m in runner.MIGRATIONS]
    assert MODULE in runner.MIGRATIONS and versions == sorted(versions)
    assert _roster() == EXPECTED
    other_cities_before = [_roster(slug) for slug in ("birmingham", "vestavia_hills", "homewood")]

    with db_cursor() as cur:
        cur.execute(importlib.import_module(MODULE).SQL_UP)

    assert _roster() == EXPECTED
    assert [_roster(slug) for slug in ("birmingham", "vestavia_hills", "homewood")] == other_cities_before


def test_049_the_seated_seven_are_the_active_members(applied_049):
    active = [(name, district) for name, district, _start, _end, is_active in _roster() if is_active]
    assert len(active) == 7
    assert [district for _name, district in active] == [1, 2, 3, 4, 5, 6, 7]
    for (name, _district), surname in zip(active, _SEATED):
        assert name.endswith(" " + surname), (name, surname)
    # The members who left since November 2021 are kept, dated and inactive.
    assert [(name, district, end) for name, district, _start, end, is_active in _roster() if not is_active] == [
        ("William Carroll", 2, date(2025, 11, 4)),
        ("Joel Daves", 5, date(2025, 11, 4)),
        ("Scott Jones", 6, date(2023, 8, 8)),
    ]


def test_049_every_surname_of_the_saved_roll_calls_resolves_on_its_date(applied_049):
    index = load_roster_index(_city_id("mobile"))
    names = _names_by_id()
    for meeting_date, surnames in ROLL_CALLS.items():
        resolved = [index.resolve(surname, meeting_date) for surname in surnames]
        assert None not in resolved, (meeting_date, surnames, resolved)
        assert len(set(resolved)) == len(surnames), (meeting_date, resolved)
        for surname, member_id in zip(surnames, resolved):
            assert names[member_id].endswith(" " + surname), (meeting_date, surname, names[member_id])


def test_049_names_that_must_not_resolve(applied_049):
    """A member is seated when term_start <= date < term_end, so nobody answers outside their term.

    "Scott" is how the minutes of 2021-11-02 print the seventh member. It is probably Scott Jones
    written by his first name; no document read says so. The resolver answers to a surname or an
    initial with a surname, never to a first name, so the row `Scott Jones` does not answer to it,
    and the stage that reads Mobile's minutes for votes must settle it.
    """
    index = load_roster_index(_city_id("mobile"))
    for name, meeting_date in [
        ("Carroll", date(2025, 11, 4)),
        ("Daves", date(2025, 11, 4)),
        ("Ingram", date(2025, 10, 28)),
        ("Fleming", date(2025, 10, 28)),
        ("Woods", date(2023, 3, 28)),
        ("Jones", date(2023, 8, 8)),
        ("Scott", date(2021, 11, 2)),
    ]:
        assert index.resolve(name, meeting_date) is None, (name, meeting_date)
    # The day before each boundary, the member who is leaving still answers.
    names = _names_by_id()
    assert names[index.resolve("Jones", date(2023, 8, 7))] == "Scott Jones"
    assert names[index.resolve("Carroll", date(2025, 11, 3))] == "William Carroll"
    assert names[index.resolve("Daves", date(2025, 11, 3))] == "Joel Daves"
    # Nobody answers before the first roll call read.
    for surname in _WITH_JONES:
        assert index.resolve(surname, date(2021, 11, 1)) is None, surname


def test_049_down_restores_the_seeded_roster_and_the_up_applies_again(applied_049):
    assert MODULE in runner.MIGRATIONS
    mobile, vestavia = _city_id("mobile"), _city_id("vestavia_hills")
    renamed: dict[int, str] = {}
    try:
        # Rows of other names and of another city, which neither direction may touch.
        with db_cursor() as cur:
            cur.execute(
                "INSERT INTO council_members (municipality_id, name, term_start, term_end, active) VALUES "
                "(%s, 'M049 Jones', '2020-01-01', NULL, TRUE), "
                "(%s, 'M049 Carroll', NULL, NULL, TRUE), "
                "(%s, 'M049 Pennington', '2020-01-01', NULL, TRUE), "
                "(%s, 'M049 Underwoods', '2020-01-01', '2020-06-01', TRUE)",
                (vestavia, vestavia, mobile, mobile),
            )
        bystanders = [
            ("M049 Carroll", None, None, None, True),
            ("M049 Jones", None, date(2020, 1, 1), None, True),
        ]
        strangers = [
            ("M049 Pennington", None, date(2020, 1, 1), None, True),
            ("M049 Underwoods", None, date(2020, 1, 1), date(2020, 6, 1), True),
        ]

        def test_rows(slug: str) -> list[tuple]:
            return sorted(row for row in _roster(slug) if row[0].startswith("M049 "))

        def city_rows() -> list[tuple]:
            return [row for row in _roster() if not row[0].startswith("M049 ")]

        with db() as conn:
            runner.rollback_migration(conn, 49)
        with db() as conn:
            assert 49 not in runner.applied_versions(conn)
        assert city_rows() == SEEDED
        assert test_rows("vestavia_hills") == bystanders and test_rows("mobile") == strangers
        # The down is harmless to repeat.
        with db_cursor() as cur:
            cur.execute(importlib.import_module(MODULE).SQL_DOWN)
        assert city_rows() == SEEDED

        # A first name spelled another way, a suffix after the surname, a surname alone, and a
        # start date already stored: the up finds each row by its whole-word surname.
        with db_cursor() as cur:
            for surname, new_name in [("Carroll", "Bill Carroll Jr."), ("Small", "CJ Small"),
                                      ("Woods", "Woods"), ("Fleming", "Beau Fleming III")]:
                cur.execute(
                    "UPDATE council_members SET name = %s WHERE municipality_id = %s AND name LIKE %s "
                    "RETURNING id, (SELECT name FROM council_members o WHERE o.id = council_members.id) AS old",
                    (new_name, mobile, "%" + surname),
                )
                row = cur.fetchone()
                renamed[row["id"]] = row["old"]
            cur.execute(
                "UPDATE council_members SET term_start = '2019-11-05' "
                "WHERE municipality_id = %s AND name = 'Gina Gregory'", (mobile,))
            # A member the up would insert, already present under another first name.
            cur.execute(
                "INSERT INTO council_members (municipality_id, name, active) VALUES (%s, 'M049 Ingram', TRUE)",
                (mobile,))
        assert len(renamed) == 4

        with db() as conn:
            runner.apply_migrations(conn)

        respelled = {"William Carroll": "Bill Carroll Jr.", "C.J. Small": "CJ Small",
                     "Josh Woods": "Woods", "Beau Fleming": "Beau Fleming III"}
        expected = [
            (respelled.get(name, name), district, date(2019, 11, 5) if name == "Gina Gregory" else start, end, active)
            for name, district, start, end, active in EXPECTED if name != "Samantha Ingram"
        ]
        assert sorted(city_rows(), key=lambda r: (r[1], r[2])) == sorted(expected, key=lambda r: (r[1], r[2]))
        assert test_rows("mobile") == [("M049 Ingram", None, None, None, True)] + strangers
        assert test_rows("vestavia_hills") == bystanders
    finally:
        with db_cursor() as cur:
            for member_id, old_name in renamed.items():
                cur.execute("UPDATE council_members SET name = %s WHERE id = %s", (old_name, member_id))
        _delete_test_rows()
        with db() as conn:
            runner.rollback_migration(conn, 49)
            runner.apply_migrations(conn)

    assert _roster() == EXPECTED
