"""scripts/coming_up_reading_sheet.py: the sheet a person reads against the city's PDF.

The sheet is built from the checked-in Birmingham schedule with a fixed day
and a made-up commit name, so what is asserted does not move with the
calendar. The script is imported inside each test, so the file collects
before it exists. No database.

Pattern: scripts/how_it_works_reading_sheet.py has no test file; this one
follows tests/unit/test_backfill_hearings_script.py in calling ``main`` with
an argument list. Plan `birmingham-coming-up`, M5.
"""

from __future__ import annotations

import dataclasses
import re
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BIRMINGHAM = REPO / "content" / "coming-up" / "birmingham"
RUNBOOK = REPO / "docs" / "runbooks" / "coming-up-reading-birmingham.md"
NOV_17 = date(2026, 11, 17)
BOX = re.compile(r"^- \[ \] ", re.M)


def _script():
    from scripts import coming_up_reading_sheet

    return coming_up_reading_sheet


def _schedule():
    from docket.services.neighborhood_schedule import load_schedule

    return load_schedule(BIRMINGHAM)


def _sheet(today: date = NOV_17, schedule=None) -> str:
    return _script().sheet("birmingham", schedule or _schedule(), "abc1234 2026-11-17", today)


def _block(text: str, name: str) -> list[str]:
    """The box line of ``name`` and the indented lines under it."""
    lines = text.split("\n")
    start = next(i for i, line in enumerate(lines) if line.startswith(f"- [ ] **{name}**: "))
    block = [lines[start]]
    for line in lines[start + 1:]:
        if not line.startswith("  - "):
            break
        block.append(line)
    return block


def test_the_sheet_has_one_box_line_per_association_in_the_files_order():
    schedule = _schedule()
    text = _sheet()
    assert len(BOX.findall(text)) == 99
    names = re.findall(r"^- \[ \] \*\*(.+?)\*\*: ", text, re.M)
    assert names == [a.name for a in schedule.associations]
    assert "## The 99 associations" in text


def test_the_header_names_the_source_the_digest_the_commit_and_the_day():
    schedule = _schedule()
    head = _sheet().split("## The 99 associations")[0]
    assert head.startswith("# Reading sheet: the neighborhood meeting schedule for birmingham\n")
    assert "`scripts/coming_up_reading_sheet.py birmingham`" in head
    assert "from `content/coming-up/birmingham/` as of commit abc1234 2026-11-17, on 2026-11-17." in head
    assert f"- Source: {schedule.title}\n" in head
    assert "- Revised: 2026-02-03\n" in head
    assert f"- Public address: {schedule.url}\n" in head
    assert f"- Saved copy: `content/coming-up/birmingham/{schedule.file}`, read 2026-11-17\n" in head
    assert f"- SHA-256 of the saved copy: `{schedule.sha256}`\n" in head
    assert "- Year the rules are expanded over: 2026\n" in head
    assert "`content/coming-up/birmingham/neighborhood-schedule.yaml`" in head
    assert "`checked`" in head


def test_acipco_finleys_block_is_the_row_and_what_was_made_of_it():
    assert _block(_sheet(), "Acipco-Finley") == [
        '- [ ] **Acipco-Finley**: "First Wednesday of each month @ 5:30 p.m."',
        "  - Read as: first Wednesday, every month, 5:30 p.m.",
        '  - Type: "In-Person", read as: in_person',
        "  - Place: Acipco Finley Community Room, 453 38th Ave W, Birmingham, AL 35207",
        "  - Call-in: none",
        "  - Next dates: Wednesday, December 2, 2026",
    ]


def test_the_next_dates_are_three_counted_from_the_day_given():
    block = _block(_sheet(date(2026, 1, 7)), "Acipco-Finley")
    assert block[-1] == (
        "  - Next dates: Wednesday, January 7, 2026; Wednesday, February 4, 2026; Wednesday, March 4, 2026"
    )
    block = _block(_sheet(date(2026, 1, 8)), "Acipco-Finley")
    assert block[-1] == (
        "  - Next dates: Wednesday, February 4, 2026; Wednesday, March 4, 2026; Wednesday, April 1, 2026"
    )


def test_an_association_with_no_date_left_says_so():
    assert _block(_sheet(date(2026, 12, 3)), "Acipco-Finley")[-1] == "  - Next dates: none left in 2026 from 2026-12-03"
    assert _block(_sheet(date(2027, 3, 1)), "Huffman")[-1] == "  - Next dates: none left in 2026 from 2027-03-01"


def test_overtons_block_names_its_months():
    block = _block(_sheet(), "Overton")
    assert block[1] == (
        "  - Read as: first Tuesday, in February, April, June, August, October and December, 6:00 p.m."
    )
    assert block[-1] == "  - Next dates: Tuesday, December 1, 2026"


def test_the_two_undated_rows_print_their_reason_and_no_date():
    text = _sheet()
    assert _block(text, "Bridlewood") == [
        '- [ ] **Bridlewood**: "First Tuesday of each month @ 6:00 p.m."',
        "  - Read as: no dates. The schedule says: No Meetings",
        '  - Type: "No Meetings", read as: no mode',
        "  - Place: none",
        "  - Call-in: none",
        "  - Next dates: none, because the rule is given no dates",
    ]
    glen_iris = _block(text, "Glen Iris")
    assert glen_iris[0] == '- [ ] **Glen Iris**: "First Monday of this month @ 6:30 pm"'
    assert glen_iris[1] == "  - Read as: no dates. The schedule says: First Monday of this month @ 6:30 pm"
    assert glen_iris[-1] == "  - Next dates: none, because the rule is given no dates"


def test_a_row_with_call_in_details_and_several_modes_prints_them():
    schedule = _schedule()
    both = next(a for a in schedule.associations if a.place and a.remote and len(a.modes) > 1)
    block = _block(_sheet(), both.name)
    assert block[2] == f'  - Type: "{both.type_text}", read as: {", ".join(both.modes)}'
    assert block[3] == f"  - Place: {both.place}"
    assert block[4] == f"  - Call-in: {both.remote}"


def test_a_rule_with_no_time_says_no_time():
    schedule = _schedule()
    first = dataclasses.replace(schedule.associations[0], time=None)
    schedule = dataclasses.replace(schedule, associations=(first,) + schedule.associations[1:])
    assert _block(_sheet(schedule=schedule), "Acipco-Finley")[1] == "  - Read as: first Wednesday, every month, no time"


@pytest.mark.parametrize(
    "hhmm, printed",
    [
        ("17:30", "5:30 p.m."),
        ("10:00", "10:00 a.m."),
        ("12:00", "12:00 p.m."),
        ("12:45", "12:45 p.m."),
        ("00:15", "12:15 a.m."),
        ("11:59", "11:59 a.m."),
        ("13:05", "1:05 p.m."),
        ("23:00", "11:00 p.m."),
    ],
)
def test_a_time_is_printed_on_the_twelve_hour_clock(hhmm, printed):
    assert _script()._clock(hhmm) == printed


def test_the_sheet_ends_with_a_record_to_fill_in():
    text = _sheet()
    assert text.endswith(
        '\n## Record of the reading\n\n- Read by:\n- Date:\n- Corrections made (commits), or "none":\n'
    )


def test_main_prints_the_sheet_for_the_content_commit_and_todays_date(capsys, monkeypatch):
    script = _script()
    monkeypatch.setattr(script, "_today", lambda: NOV_17)
    assert script.main(["coming_up_reading_sheet.py", "birmingham"]) == 0
    out = capsys.readouterr().out
    commit = re.search(r"as of commit ([0-9a-f]{7,}) (\d{4}-\d{2}-\d{2}), on 2026-11-17\.", out)
    assert commit, out[:400]
    assert out == script.sheet("birmingham", _schedule(), f"{commit.group(1)} {commit.group(2)}", NOV_17)


def test_today_is_a_date():
    assert isinstance(_script()._today(), date)


def test_main_without_a_city_prints_the_usage_and_exits_2(capsys):
    script = _script()
    assert script.main(["coming_up_reading_sheet.py"]) == 2
    assert script.main(["coming_up_reading_sheet.py", "birmingham", "extra"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "coming_up_reading_sheet.py birmingham" in captured.err


def test_main_for_a_city_with_no_schedule_exits_1_and_prints_no_sheet(capsys):
    assert _script().main(["coming_up_reading_sheet.py", "mobile"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no schedule file" in captured.err and "mobile" in captured.err


def test_the_saved_runbook_has_one_box_per_association():
    text = RUNBOOK.read_text(encoding="utf-8")
    boxes = re.findall(r"^- \[[ x]\] \*\*(.+?)\*\*: ", text, re.M)
    assert boxes == [a.name for a in _schedule().associations]
    assert re.search(r"as of commit [0-9a-f]{7,} \d{4}-\d{2}-\d{2}, on \d{4}-\d{2}-\d{2}\.", text)
