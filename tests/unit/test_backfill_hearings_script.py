"""scripts/backfill_hearings.py: the operator's dry run and fill of a city's hearings.

The script's ``main`` is called with an argument list. Rows are seeded under
Birmingham: meetings dated in March 2031 (a month no other test seeds, so
the totals a run prints are this file's rows alone) whose titles begin
``HEARINGS_TEST_``, and items whose titles are the saved production titles
of ``tests/fixtures/hearings/birmingham_titles.json``. The meetings, and the
hearings their items were linked to, are deleted before and after every
test. The script is imported inside each test, so the file collects before
it exists. Reads and writes the throwaway database (DATABASE_URL names
docket_test_*).

Pattern: tests/unit/test_backfill_committee_documents_script.py.
Plan `birmingham-coming-up`, M3.
"""

from __future__ import annotations

import itertools
import json
import re
from datetime import date
from pathlib import Path

import pytest

from docket.db import db_cursor

FIXTURE = Path(__file__).parent.parent / "fixtures" / "hearings" / "birmingham_titles.json"
TITLES = {row["id"]: row["title"] for row in json.loads(FIXTURE.read_text())}
PREFIX = "HEARINGS_TEST_"
MAR_3 = date(2031, 3, 3)
MAR_17 = date(2031, 3, 17)
RANGE = ["--since", "2031-03-01", "--until", "2031-03-31"]

_serial = itertools.count(1)


def _delete_seeded() -> None:
    with db_cursor() as cur:
        cur.execute(
            """DELETE FROM public_hearings WHERE id IN (
                   SELECT phi.hearing_id FROM public_hearing_items phi
                     JOIN agenda_items ai ON ai.id = phi.agenda_item_id
                     JOIN meetings mt ON mt.id = ai.meeting_id
                    WHERE mt.title LIKE %s)""",
            (PREFIX + "%",),
        )
        cur.execute("DELETE FROM meetings WHERE title LIKE %s", (PREFIX + "%",))


@pytest.fixture(autouse=True)
def _clean():
    _delete_seeded()
    yield
    _delete_seeded()


def _meeting(day: date) -> int:
    n = next(_serial)
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type)
               VALUES ((SELECT id FROM municipalities WHERE slug = 'birmingham'), %s, %s, %s, 'council')
               RETURNING id""",
            (f"hearings-script-{n}", PREFIX + "Regular meeting", day),
        )
        return cur.fetchone()["id"]


def _item(meeting_id: int, title: str) -> int:
    n = next(_serial)
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO agenda_items (meeting_id, external_id, title) VALUES (%s, %s, %s) RETURNING id",
            (meeting_id, f"hearings-script-item-{n}", title),
        )
        return cur.fetchone()["id"]


def _counts() -> tuple[int, int]:
    with db_cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM public_hearings")
        hearings = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM public_hearing_items")
        return hearings, cur.fetchone()["n"]


def _seed() -> dict[str, int]:
    """Two items setting one vacation hearing, a weed-lot item, an item with no date, and an item with no trigger."""
    first, second = _meeting(MAR_3), _meeting(MAR_17)
    return {
        "vacation": _item(first, TITLES[62830]),
        "weeds": _item(first, TITLES[62882]),
        "undated": _item(first, TITLES[3238]),
        "untriggered": _item(first, TITLES[59096]),
        "vacation_again": _item(second, TITLES[62830]),
    }


def test_without_since_the_script_refuses_and_names_the_bound(capsys):
    from scripts import backfill_hearings as script

    with pytest.raises(SystemExit) as exit_info:
        script.main(["--city", "birmingham", "--dry-run"])

    assert exit_info.value.code not in (0, None)
    assert "--since" in capsys.readouterr().err


def test_without_city_the_script_refuses(capsys):
    from scripts import backfill_hearings as script

    with pytest.raises(SystemExit) as exit_info:
        script.main(["--since", "2031-03-01", "--dry-run"])

    assert exit_info.value.code not in (0, None)
    assert "--city" in capsys.readouterr().err


def test_a_date_that_is_not_one_is_refused(capsys):
    from scripts import backfill_hearings as script

    with pytest.raises(SystemExit) as exit_info:
        script.main(["--city", "birmingham", "--since", "March 2031", "--dry-run"])

    assert exit_info.value.code not in (0, None)
    assert "--since" in capsys.readouterr().err


def test_an_unknown_city_exits_with_an_error_and_writes_nothing(capsys):
    from scripts import backfill_hearings as script

    _seed()
    before = _counts()
    with pytest.raises(SystemExit) as exit_info:
        script.main(["--city", "atlantis", *RANGE])

    assert exit_info.value.code not in (0, None)
    assert "atlantis" in capsys.readouterr().err
    assert _counts() == before


def test_a_dry_run_calls_neither_refresh_nor_any_write(capsys, monkeypatch):
    from docket.services import hearings
    from scripts import backfill_hearings as script

    _seed()
    before = _counts()
    called = []
    monkeypatch.setattr(hearings, "refresh_hearings", lambda *a, **k: called.append((a, k)))
    # `db` is the service's writing connection; `find_readings` reads through `db_cursor`.
    monkeypatch.setattr(hearings, "db", lambda *a, **k: called.append("db"))

    script.main(["--city", "birmingham", *RANGE, "--dry-run"])

    assert called == []
    assert _counts() == before
    out = capsys.readouterr().out
    assert "created=" not in out and "linked=" not in out


def test_a_dry_run_prints_a_line_per_item_then_per_hearing_then_the_totals(capsys):
    from scripts import backfill_hearings as script

    ids = _seed()

    script.main(["--city", "birmingham", *RANGE, "--dry-run"])

    vacation_title = TITLES[62830][:70]
    weeds_title = TITLES[62882][:70]
    budget_title = TITLES[3238].replace("\n", " ")[:70]
    assert capsys.readouterr().out.splitlines() == [
        f"{ids['vacation']}  2031-03-03  2026-11-17  vacation  -  {vacation_title}",
        f"{ids['weeds']}  2031-03-03  2026-11-17  weed_lots  212  {weeds_title}",
        f"{ids['undated']}  2031-03-03  no date  budget  -  {budget_title}",
        f"{ids['vacation_again']}  2031-03-17  2026-11-17  vacation  -  {vacation_title}",
        f"hearing 2026-11-17 vacation items={ids['vacation']},{ids['vacation_again']}",
        f"hearing 2026-11-17 weed_lots items={ids['weeds']}",
        "matched=4 dated=3 undated=1 hearings=2",
    ]


def test_an_item_line_holds_the_first_seventy_characters_of_the_title_with_its_whitespace_collapsed(capsys):
    from scripts import backfill_hearings as script

    # Stored as production stores it: "P", two tabs, "ITEM 25.", a newline.
    item = _item(_meeting(MAR_3), TITLES[1680])

    script.main(["--city", "birmingham", *RANGE, "--dry-run"])

    line = capsys.readouterr().out.splitlines()[0]
    shown = "P ITEM 25. A Resolution setting a public hearing December 9, 2025, to "
    assert len(shown) == 70
    assert line == f"{item}  2031-03-03  2025-12-09  zoning  -  {shown}"
    assert not re.search(r"[\t\n]", line)


def test_without_dry_run_the_script_prints_the_same_then_writes_and_says_what(capsys):
    from scripts import backfill_hearings as script

    ids = _seed()
    before = _counts()
    script.main(["--city", "birmingham", *RANGE, "--dry-run"])
    dry = capsys.readouterr().out.splitlines()

    script.main(["--city", "birmingham", *RANGE])

    out = capsys.readouterr().out.splitlines()
    assert out[:-1] == dry
    assert out[-1] == "created=2 linked=3"
    after = _counts()
    assert (after[0] - before[0], after[1] - before[1]) == (2, 3)
    with db_cursor() as cur:
        cur.execute(
            "SELECT agenda_item_id FROM public_hearing_items WHERE agenda_item_id = ANY(%s) ORDER BY 1",
            (list(ids.values()),),
        )
        assert [r["agenda_item_id"] for r in cur.fetchall()] == sorted(
            [ids["vacation"], ids["weeds"], ids["vacation_again"]]
        )


def test_a_second_run_creates_nothing(capsys):
    from scripts import backfill_hearings as script

    _seed()
    script.main(["--city", "birmingham", *RANGE])
    after_first = _counts()
    capsys.readouterr()

    script.main(["--city", "birmingham", *RANGE])

    assert capsys.readouterr().out.splitlines()[-1] == "created=0 linked=3"
    assert _counts() == after_first


def test_until_bounds_the_meetings_read_and_since_alone_does_not(capsys):
    from scripts import backfill_hearings as script

    ids = _seed()

    script.main(["--city", "birmingham", "--since", "2031-03-01", "--until", "2031-03-10", "--dry-run"])
    bounded = capsys.readouterr().out.splitlines()
    script.main(["--city", "birmingham", "--since", "2031-03-10", "--dry-run"])
    late = capsys.readouterr().out.splitlines()

    assert bounded[-1] == "matched=3 dated=2 undated=1 hearings=2"
    assert f"hearing 2026-11-17 vacation items={ids['vacation']}" in bounded
    assert late[-1] == "matched=1 dated=1 undated=0 hearings=1"
    assert late[-2] == f"hearing 2026-11-17 vacation items={ids['vacation_again']}"


def test_the_range_is_passed_to_the_write_as_given(monkeypatch, capsys):
    from docket.services import hearings
    from scripts import backfill_hearings as script

    seen = []
    real = hearings.refresh_hearings

    def spy(*args, **kwargs):
        seen.append((args[1:], kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(hearings, "refresh_hearings", spy)

    script.main(["--city", "birmingham", *RANGE])
    script.main(["--city", "birmingham", "--since", "2031-03-01"])

    assert [(a, k) for a, k in seen] == [
        ((date(2031, 3, 1), date(2031, 3, 31)), {}),
        ((date(2031, 3, 1), None), {}),
    ]
