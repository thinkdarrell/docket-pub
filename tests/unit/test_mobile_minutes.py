"""Unit tests for the Mobile minutes reader, `docket.analysis.mobile_minutes`.

The pages come from `tests/fixtures/mobile_minutes/`: the city's own minutes
text as pdfplumber extracted it, cut down to the lines the tests need, and two
files named `invented_` that are the plan author's words and pin rules the
excerpts cannot. The readings asserted are those of plan
`mobile-votes-from-minutes`, M1 ("Expected readings").

The module is imported inside each test, so that before it exists every test
here fails on that import and the file still collects.
"""

import re
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mobile_minutes"

SEVEN = ("Penn", "Ingram", "Small", "Reynolds", "Fleming", "Woods", "Gregory")
FOUR = ("Alpha", "Beta", "Gamma", "Delta")

_PAGE_MARK = re.compile(r"^=====PAGE (\d+)=====$")
_UNSET = object()


def load_pages(name: str) -> list[str]:
    """The pages of a saved file: index 0 is page 1, a missing page is ''."""
    pages: dict[int, list[str]] = {}
    current = None
    for line in (FIXTURES / name).read_text(encoding="utf-8").split("\n"):
        mark = _PAGE_MARK.match(line)
        if mark:
            current = int(mark.group(1))
            pages[current] = []
        elif current is not None:
            pages[current].append(line)
    return ["\n".join(pages.get(n, [])) for n in range(1, max(pages) + 1)]


def read(name: str):
    from docket.analysis.mobile_minutes import read_minutes

    return read_minutes(load_pages(name))


def read_text(*pages: str):
    """Read pages written out in a test, one string per page."""
    from docket.analysis.mobile_minutes import read_minutes

    return read_minutes(list(pages))


def check(
    vote,
    *,
    page,
    ayes,
    result,
    declared,
    nays=(),
    abstain=(),
    absent=(),
    flagged=None,
    code=None,
    kind=None,
    caption=None,
    motion=_UNSET,
):
    """Assert one vote's fields. Every list not given is empty; code, kind and
    caption not given are None; a vote not said to be flagged is not flagged."""
    assert vote.page == page
    assert vote.ayes == tuple(ayes)
    assert vote.nays == tuple(nays)
    assert vote.abstain == tuple(abstain)
    assert vote.absent == tuple(absent)
    assert vote.result == result
    assert vote.declared_text == declared
    assert vote.needs_review is (flagged is not None)
    assert vote.review_reason == flagged
    assert vote.code == code
    assert vote.kind == kind
    assert vote.caption == caption
    if motion is not _UNSET:
        assert vote.motion_text == motion


# ---------------------------------------------------------------------------
# One test per saved file
# ---------------------------------------------------------------------------


def test_mobile_2026_11_03():
    reading = read("mobile_2026-11-03.txt")
    assert reading.header_date == date(2026, 11, 3)
    assert len(reading.votes) == 7
    v = reading.votes
    check(
        v[0],
        page=2,
        ayes=SEVEN,
        result="passed",
        declared="the agenda adopted",
        motion=(
            "Councilmember Penn moved to adopt the agenda, which was seconded by "
            "Councilmember Woods"
        ),
    )
    check(
        v[1],
        page=2,
        ayes=("Small", "Penn", "Ingram", "Reynolds", "Fleming", "Woods", "Gregory"),
        result="passed",
        declared="the waiver adopted",
        motion=(
            "Councilmember Ingram moved to adopt the waiver, which was seconded by "
            "Councilmember Gregory and the vote was as follows:"
        ),
    )
    check(
        v[2],
        page=5,
        ayes=SEVEN,
        result="passed",
        declared="the resolution adopted",
        code="40-948-2026",
        kind="RESOLUTION",
        caption=(
            "DECLARE THE STRUCTURE AT 906 S. BROAD STREET A PUBLIC NUISANCE AND "
            "ORDER IT DEMOLISHED"
        ),
        motion=(
            "The resolution was read by the City Clerk, whereupon Councilmember Small "
            "moved to adopt the resolution, which was seconded by Councilmember Ingram "
            "and the vote was as follows:"
        ),
    )
    check(
        v[3],
        page=19,
        ayes=SEVEN,
        result="passed",
        declared="unanimous consent granted for the items",
        motion=(
            "Reynolds moved for the suspension of the rules to consider resolutions "
            "03-1171 through 60-1178 being introduced for the first time. The motion "
            "was seconded by Councilmember Penn and the vote was as follows:"
        ),
    )
    check(
        v[4],
        page=25,
        ayes=SEVEN,
        result="passed",
        declared="the resolution adopted",
        code="08-1180-2026",
        kind="RESOLUTION",
        caption=(
            "APPROVE PURCHASE ORDER TO SOUTHERN REALTY MANAGEMENT GROUP, LLC FOR "
            "STORM DRAINAGE VEGETATION AND DEBRIS REMOVAL – 3153 HEATHER STREET TO "
            "DAUPHIN STREET; $25,000.00"
        ),
    )
    check(
        v[5],
        page=37,
        ayes=SEVEN,
        result="passed",
        declared="set the date for the public hearing as December 8, 2026",
        code="41-1198-2026",
        kind="RESOLUTION",
        caption=(
            "CALL FOR PUBLIC HEARING TO CONSIDER AMENDING THE DOWNTOWN DEVELOPMENT "
            "DISTRICT REGULATING PLAN TO UPDATE THE ZONING MAP TO REZONE PROPERTY "
            "LOCATED AT 255 CHURCH STREET FROM T-5.2 TO T-6 (SCHEDULED FOR "
            "DECEMBER 8, 2026) (DISTRICT 2)"
        ),
        motion=(
            "Councilmember Ingram moved to call for the public hearing, which was "
            "seconded by Councilmember Reynolds and the vote was as follows:"
        ),
    )
    check(
        v[6],
        page=38,
        ayes=SEVEN,
        result="passed",
        declared="the regular meeting adjourned at approximately 11:40 a.m.",
    )


def test_mobile_2021_11_23():
    reading = read("mobile_2021-11-23.txt")
    assert reading.header_date == date(2021, 11, 23)
    assert len(reading.votes) == 1
    check(
        reading.votes[0],
        page=2,
        ayes=("Penn", "Carroll", "Small", "Reynolds", "Jones", "Gregory"),
        absent=("Daves",),
        result="passed",
        declared="the meeting moved into executive session at approximately 9:26 a.m.",
        motion=(
            "Councilmember Gregory moved for the Council to enter into executive "
            "session and reconvene into the regular meeting at 10:30 a.m., which move "
            "was seconded by Councilmember Jones. Following a roll call, the vote was "
            "as follows:"
        ),
    )


def test_mobile_2024_06_18():
    reading = read("mobile_2024-06-18.txt")
    assert reading.header_date is None  # page 1 is not in the excerpt
    assert len(reading.votes) == 2
    check(
        reading.votes[0],
        page=2,
        ayes=("Penn", "Carroll", "Small", "Reynolds", "Daves", "Woods", "Gregory"),
        result="passed",
        declared="the motion to adopt the agenda adopted",
    )
    check(
        reading.votes[1],
        page=3,
        ayes=("Penn", "Carroll", "Small", "Reynolds", "Woods", "Gregory"),
        abstain=("Daves",),
        result="passed",
        declared="the waiver tabled",
        motion=(
            "Councilmember Carroll moved to table the waiver, which move was seconded "
            "by Councilmember Woods and the vote was as follows:"
        ),
    )


def test_mobile_2022_02_22():
    reading = read("mobile_2022-02-22.txt")
    assert reading.header_date is None
    assert len(reading.votes) == 2
    for vote in reading.votes:
        check(
            vote,
            page=15,
            ayes=("Penn", "Carroll", "Small", "Daves", "Gregory"),
            abstain=("Reynolds", "Jones"),
            result="unknown",
            declared=None,
            flagged="declaration_not_read",
        )
    assert reading.votes[0].motion_text == (
        "The Presiding Officer called for the vote on Councilmember Carroll’s motion "
        "to amend/hold over the ordinance for four (4) months and the vote was as "
        "follows:"
    )


def test_mobile_2022_03_15():
    reading = read("mobile_2022-03-15.txt")
    assert reading.header_date is None
    assert len(reading.votes) == 1
    check(
        reading.votes[0],
        page=9,
        ayes=("Carroll", "Daves", "Gregory"),
        abstain=("Reynolds", "Jones"),
        result="unknown",
        declared="the resolution denied",
        flagged="declaration_ambiguous",
        code="60-197-2022",
        kind="RESOLUTION",
        caption=(
            "AUTHORIZE THE COUNCIL TO HIRE A CONSULTANT TO PERFORM AND PROVIDE A "
            "RACIAL POLARIZATION STUDY"
        ),
    )


def test_mobile_2022_07_12():
    reading = read("mobile_2022-07-12.txt")
    assert reading.header_date is None
    assert len(reading.votes) == 1
    check(
        reading.votes[0],
        page=3,
        ayes=("Penn", "Carroll", "Small", "Reynolds", "Daves", "Jones", "Gregory"),
        result="passed",
        declared="The motion passed",
    )


def test_mobile_2024_07_16():
    reading = read("mobile_2024-07-16.txt")
    assert reading.header_date is None
    assert len(reading.votes) == 1
    check(
        reading.votes[0],
        page=6,
        ayes=("Penn", "Daves"),
        nays=("Carroll", "Small", "Reynolds", "Woods", "Gregory"),
        result="failed",
        declared="the ordinance failed",
        # The line before `moved` is taken: the `moved` line begins lowercase.
        motion=(
            "The ordinance was read by the Assistant City Clerk, whereupon "
            "Councilmember Penn moved to adopt the ordinance which was seconded by "
            "Councilmember Woods and the vote was as follows:"
        ),
    )


def test_mobile_2025_11_18():
    reading = read("mobile_2025-11-18.txt")
    assert reading.header_date is None
    assert len(reading.votes) == 2
    nays = ("Penn", "Ingram", "Small", "Fleming", "Woods")
    check(
        reading.votes[0],
        page=30,
        ayes=("Reynolds",),
        nays=nays,
        result="passed",
        declared="the amendment passed",
        flagged="declaration_contradicts_count",
        motion=None,
    )
    check(
        reading.votes[1],
        page=30,
        ayes=("Reynolds",),
        nays=nays,
        result="passed",
        declared="the ordinance adopted as amended",
        flagged="declaration_contradicts_count",
        motion=(
            "The Presiding Officer called for the vote on the original motion as "
            "amended and the vote was as follows:"
        ),
    )


def test_mobile_2026_11_10():
    reading = read("mobile_2026-11-10.txt")
    assert reading.header_date is None
    assert len(reading.votes) == 1
    check(
        reading.votes[0],
        page=28,
        ayes=SEVEN,
        result="passed",
        declared="the ordinance denied",
        motion=(
            "Gregory moved to deny the ordinance, which was seconded by Councilmember "
            "Reynolds and the vote was as follows:"
        ),
    )


def test_not_minutes_agenda():
    reading = read("not_minutes_agenda.txt")
    assert reading.header_date is None
    assert reading.votes == ()


def test_not_minutes_letter():
    reading = read("not_minutes_letter.txt")
    assert reading.header_date is None
    assert reading.votes == ()


def test_invented_chain():
    reading = read("invented_chain.txt")
    assert reading.header_date is None
    assert len(reading.votes) == 3
    item = dict(
        code="12-345-2029",
        kind="ORDINANCE",
        caption="WIDGET ORDINANCE HELD OVER FROM LAST WEEK",
    )
    check(
        reading.votes[0],
        page=1,
        ayes=("Alpha", "Beta", "Gamma"),
        nays=("Delta",),
        result="passed",
        declared="the amendment adopted",
        **item,
    )
    check(
        reading.votes[1],
        page=2,
        ayes=FOUR,
        result="passed",
        declared="the ordinance adopted as amended",
        **item,
    )
    check(reading.votes[2], page=2, ayes=FOUR, result="passed", declared="The motion carried")


def test_invented_closing():
    reading = read("invented_closing.txt")
    assert reading.header_date is None
    assert len(reading.votes) == 3
    check(
        reading.votes[0], page=1, ayes=FOUR, result="passed", declared="the resolution adopted"
    )
    check(
        reading.votes[1], page=1, ayes=FOUR, result="passed", declared="the meeting in recess"
    )
    check(
        reading.votes[2],
        page=1,
        ayes=("Alpha", "Beta"),
        nays=("Gamma", "Delta"),
        abstain=("Epsilon",),
        result="failed",
        declared="the resolution failed",
        code="01-102-2029",
        kind="RESOLUTION",
        caption="THIRD THING FOR THE PARKS; $1,000.00",
    )


# ---------------------------------------------------------------------------
# The rules, by name
# ---------------------------------------------------------------------------


def test_running_line_and_page_number_are_not_content():
    """Rule 1. The vote of page 37 runs on to page 38: neither the `37` that
    ends the one page nor the `MINUTES OF NOVEMBER 3, 2026` that opens the
    other is part of what the vote reads as."""
    vote = read("mobile_2026-11-03.txt").votes[5]
    assert vote.raw_text == "\n".join(
        [
            "Councilmember Ingram moved to call for the public hearing, which was seconded by",
            "Councilmember Reynolds and the vote was as follows:",
            "Ayes: Penn, Ingram, Small, Reynolds, Fleming, Woods, and Gregory",
            "Nays: None",
            "The vote was then announced by the City Clerk, whereupon the Presiding Officer set the",
            "date for the public hearing as December 8, 2026.",
        ]
    )
    # The running line is dropped whatever its case, and a number of four
    # digits is content, not a page number.
    reading = read_text(
        "Councilmember Alpha moved to adopt the plan and the vote was as follows:\n"
        "Ayes: Alpha\n"
        "Nays: None\n"
        "The vote was then announced by the City Clerk, whereupon the Presiding\n"
        "7\n",
        "Minutes of May 8, 2029\n"
        "Officer declared the plan adopted in\n"
        "2029\n"
        "as amended.\n",
    )
    assert reading.votes[0].declared_text == "the plan adopted in 2029 as amended"


def test_a_vote_is_paged_where_its_ayes_line_is_printed():
    """The `Ayes:` line is on page 37 and the declaration on page 38."""
    vote = read("mobile_2026-11-03.txt").votes[5]
    assert vote.page == 37
    assert vote.declared_text == "set the date for the public hearing as December 8, 2026"


def test_abstain_before_nays_is_read():
    for vote in read("mobile_2022-02-22.txt").votes:
        assert vote.abstain == ("Reynolds", "Jones")
        assert vote.nays == ()
        assert vote.ayes == ("Penn", "Carroll", "Small", "Daves", "Gregory")
    # `Abstained:` after `Nays:` is the same list, in any case; a block takes
    # three lines after `Ayes:` and no more.
    reading = read_text(
        "Councilmember Alpha moved to adopt the plan and the vote was as follows:\n"
        "Ayes: Alpha\n"
        "Nays: Beta.\n"
        "ABSTAINED: Gamma and Delta\n"
        "Absent: Epsilon\n"
        "Absent: Zeta.\n"
        "The Presiding Officer declared the plan adopted.\n"
    )
    vote = reading.votes[0]
    assert vote.nays == ("Beta",)
    assert vote.abstain == ("Gamma", "Delta")
    assert vote.declared_text is None
    assert vote.raw_text.endswith("Absent: Epsilon")
    # A second `Nays:` line is not part of the block.
    reading = read_text(
        "Councilmember Alpha moved to adopt the plan and the vote was as follows:\n"
        "Ayes: Alpha\n"
        "Nays: Beta\n"
        "Nays: Zeta.\n"
        "The Presiding Officer declared the plan adopted.\n"
    )
    assert reading.votes[0].nays == ("Beta",)
    assert reading.votes[0].declared_text is None


def test_a_vote_with_no_declaration_is_unknown_and_flagged():
    first, second = read("mobile_2022-02-22.txt").votes
    for vote in (first, second):
        assert vote.declared_text is None
        assert vote.result == "unknown"
        assert vote.needs_review is True
        assert vote.review_reason == "declaration_not_read"
    # No line is consumed where no declaration is read: the sentence after the
    # first vote is the second vote's motion.
    assert first.raw_text.endswith("Nays: None")
    assert second.motion_text == (
        "The Presiding Officer called for the vote on Councilmember Jones’ original "
        "motion, and the vote was as follows:"
    )
    # A sentence that does not end within four lines is not a declaration,
    # though its fifth line says `declared`.
    reading = read_text(
        "Councilmember Alpha moved to adopt the plan and the vote was as follows:\n"
        "Ayes: Alpha\n"
        "Nays: None\n"
        "The clerk then read\n"
        "a long statement\n"
        "about the plan\n"
        "and at its end\n"
        "the Presiding Officer declared the plan adopted.\n"
    )
    assert reading.votes[0].declared_text is None


def test_denied_on_a_motion_to_deny_is_passed():
    vote = read("mobile_2026-11-10.txt").votes[0]
    assert vote.declared_text == "the ordinance denied"
    assert vote.result == "passed"
    assert vote.needs_review is False
    assert vote.review_reason is None


def test_denied_on_a_motion_to_adopt_with_more_ayes_is_flagged_ambiguous():
    vote = read("mobile_2022-03-15.txt").votes[0]
    assert (len(vote.ayes), len(vote.nays)) == (3, 0)
    assert vote.declared_text == "the resolution denied"
    assert vote.result == "unknown"
    assert vote.needs_review is True
    assert vote.review_reason == "declaration_ambiguous"
    # The same declaration on a motion to adopt that drew no more ayes than
    # nays says the motion lost.
    reading = read_text(
        "Councilmember Alpha moved to adopt the plan and the vote was as follows:\n"
        "Ayes: Alpha\n"
        "Nays: Beta\n"
        "The Presiding Officer declared the plan denied.\n"
    )
    vote = reading.votes[0]
    assert vote.result == "failed"
    assert vote.needs_review is False


def test_failed_is_failed_whatever_the_count():
    lost = read("mobile_2024-07-16.txt").votes[0]
    assert (len(lost.ayes), len(lost.nays)) == (2, 5)
    assert lost.result == "failed"
    assert lost.needs_review is False
    # An ordinance needs more than a majority of those voting: four ayes to
    # two nays, declared failed, is failed and is not flagged.
    reading = read_text(
        "Councilmember Alpha moved to adopt the ordinance and the vote was as follows:\n"
        "Ayes: Alpha, Beta, Gamma, and Delta\n"
        "Nays: Epsilon and Zeta\n"
        "The vote was then announced by the City Clerk, whereupon the Presiding Officer\n"
        "declared the ordinance failed.\n"
    )
    vote = reading.votes[0]
    assert (len(vote.ayes), len(vote.nays)) == (4, 2)
    assert vote.result == "failed"
    assert vote.needs_review is False
    assert vote.review_reason is None


def test_passed_with_fewer_ayes_than_nays_is_flagged():
    for vote in read("mobile_2025-11-18.txt").votes:
        assert (len(vote.ayes), len(vote.nays)) == (1, 5)
        assert vote.result == "passed"
        assert vote.needs_review is True
        assert vote.review_reason == "declaration_contradicts_count"
    # A tie is not fewer.
    reading = read_text(
        "Councilmember Alpha moved to adopt the plan and the vote was as follows:\n"
        "Ayes: Alpha\n"
        "Nays: Beta\n"
        "The Presiding Officer declared the plan adopted.\n"
    )
    assert reading.votes[0].result == "passed"
    assert reading.votes[0].needs_review is False


def test_absent_members_come_from_the_attendance_block_in_force():
    # 2021's conference prints `Present:` then `Councilmembers:`; Daves is
    # absent, and Scott, who is listed present and not among the ayes, is not.
    vote = read("mobile_2021-11-23.txt").votes[0]
    assert vote.absent == ("Daves",)
    # `Absent: None` is nobody.
    assert all(v.absent == () for v in read("mobile_2026-11-03.txt").votes)

    motion = "Councilmember Alpha moved to adopt the plan and the vote was as follows:\n"
    declared = "The Presiding Officer declared the plan adopted.\n"
    reading = read_text(
        # The conference: `Councilmembers:` then `Present: ...`.
        "Councilmembers:\n"
        "Present: Alpha, Beta, and Gamma\n"
        "Absent: Delta and Epsilon.\n"
        + motion
        + "Ayes: Alpha and Beta\nNays: Gamma\n"
        + declared
        # A member listed absent who votes is not absent on that vote.
        + motion
        + "Ayes: Alpha, Beta, and Delta\nNays: None\n"
        + declared
        # The roll call replaces the list, for the votes after it only.
        + "Present on Roll Call:\n"
        "Chairman: Alpha\n"
        "Vice-Chairman: Beta\n"
        "Councilmembers: Gamma and Delta\n"
        "Absent: Gamma\n"
        + motion
        + "Ayes: Alpha\nNays: None\n"
        + declared
        # A roll call that prints no `Absent:` line within five lines lists nobody.
        + "Present on Roll Call:\n"
        "Chairman: Alpha\n"
        "Vice-Chairman: Beta\n"
        "Councilmembers: Gamma and Delta\n"
        "The Presiding Officer led the Pledge of Allegiance.\n"
        "The minutes were approved.\n"
        "Absent: Zeta\n"
        + motion
        + "Ayes: Alpha\nNays: None\n"
        + declared
    )
    assert [v.absent for v in reading.votes] == [
        ("Delta", "Epsilon"),
        ("Epsilon",),
        ("Gamma",),
        (),
    ]


def test_an_item_held_over_without_a_vote_gives_no_code_to_the_next_vote():
    votes = read("mobile_2026-11-03.txt").votes
    # 01-1179-2026 "was held over until" and has no vote; the vote after it is
    # on 08-1180-2026.
    assert votes[4].code == "08-1180-2026"
    # An item "held over until ... was called up" is voted.
    assert votes[2].code == "40-948-2026"
    # With nothing after the held-over item but a vote, the vote has no code;
    # `laid over` is the clerks' other spelling.
    for spelling in ("held", "laid"):
        reading = read_text(
            "FIRST THING. The following resolution was introduced by Councilmember Alpha.\n"
            "RESOLUTION: 01-100-2029\n"
            f"SECOND THING. The following resolution was {spelling} over until the regular\n"
            "meeting of May 15, 2029.\n"
            "RESOLUTION: 01-101-2029\n"
            "Councilmember Alpha moved to thank the staff and the vote was as follows:\n"
            "Ayes: Alpha\n"
            "Nays: None\n"
            "The Presiding Officer declared the staff thanked.\n"
        )
        assert reading.votes[0].code is None
        assert reading.votes[0].caption is None


def test_a_pending_item_carries_across_an_amendment_and_ends_at_a_heading():
    amendment, original, after_heading = read("invented_chain.txt").votes
    assert amendment.code == original.code == "12-345-2029"
    assert amendment.caption == original.caption == "WIDGET ORDINANCE HELD OVER FROM LAST WEEK"
    assert original.page == 2
    assert after_heading.code is None
    assert after_heading.kind is None
    assert after_heading.caption is None
    # A heading printed with a colon or a period ends the item too, and so
    # does a heading of the `RESOLUTIONS BEING INTRODUCED` family.
    for heading in (
        "APPEALS:",
        "PUBLIC HEARINGS.",
        "CIP RESOLUTIONS HELD OVER",
        "CONSENT ORDINANCES BEING INTRODUCED FOR THE FIRST TIME",
    ):
        reading = read_text(
            "FIRST THING. The following resolution was introduced by Councilmember Alpha.\n"
            "RESOLUTION: 01-100-2029\n"
            f"{heading}\n"
            "Councilmember Alpha moved to thank the staff and the vote was as follows:\n"
            "Ayes: Alpha\n"
            "Nays: None\n"
            "The Presiding Officer declared the staff thanked.\n"
        )
        assert reading.votes[0].code is None, heading


def test_a_malformed_code_line_is_not_read_and_the_item_before_it_does_not_leak():
    first = read("invented_closing.txt").votes[0]
    assert first.code is None
    assert first.kind is None
    assert first.caption is None
    # The item before the malformed line was introduced, not held over, and
    # has a code of its own; the sentence that opens the next item ends it,
    # also where `The` and `following` sit on two lines.
    for opening in (
        "SECOND THING. The following resolution was introduced by Councilmember Alpha.\n",
        "SECOND THING. The\nfollowing ordinance was introduced by Councilmember Alpha.\n",
    ):
        reading = read_text(
            "FIRST THING. The following resolution was introduced by Councilmember Alpha.\n"
            "RESOLUTION: 01-100-2029\n"
            "BE IT RESOLVED that the first thing is done.\n"
            + opening
            + "RESOLUTION: 1-101-2029\n"
            "BE IT RESOLVED that the second thing is done.\n"
            "Councilmember Alpha moved to adopt the resolution and the vote was as follows:\n"
            "Ayes: Alpha\n"
            "Nays: None\n"
            "The Presiding Officer declared the resolution adopted.\n"
        )
        assert reading.votes[0].code is None, opening


def test_a_procedural_motion_takes_no_code_and_the_item_keeps_it():
    _, recess, third = read("invented_closing.txt").votes
    assert recess.motion_text.startswith("Councilmember Beta moved to recess the meeting")
    assert recess.code is None
    assert recess.caption is None
    assert third.code == "01-102-2029"
    # The motion to suspend the rules on page 19 follows the pending item
    # 21-1141-2026 with no heading between and does not take it.
    suspend = read("mobile_2026-11-03.txt").votes[3]
    assert "suspension of the rules" in suspend.motion_text
    assert suspend.code is None
    # Each kind of procedural motion, with an item pending.
    for motion in (
        "moved to adjourn the meeting",
        "moved to enter Executive Session",
        "moved to adopt the agenda",
        "moved to suspend the rules",
        "moved for the suspension of the rules",
        "moved to recess",
    ):
        reading = read_text(
            "FIRST THING. The following resolution was introduced by Councilmember Alpha.\n"
            "RESOLUTION: 01-100-2029\n"
            f"Councilmember Alpha {motion} and the vote was as follows:\n"
            "Ayes: Alpha\n"
            "Nays: None\n"
            "The Presiding Officer declared it so.\n"
            "Councilmember Alpha moved to adopt the resolution and the vote was as follows:\n"
            "Ayes: Alpha\n"
            "Nays: None\n"
            "The Presiding Officer declared the resolution adopted.\n"
        )
        assert [v.code for v in reading.votes] == [None, "01-100-2029"], motion


def test_code_without_a_colon_and_with_a_space_is_normalised():
    first = read("invented_chain.txt").votes[0]
    # Printed `ORDINANCE 12- 345-2029`.
    assert first.code == "12-345-2029"
    assert first.kind == "ORDINANCE"


def test_a_letter_and_an_agenda_have_no_header_date():
    assert read("not_minutes_letter.txt").header_date is None
    assert read("not_minutes_agenda.txt").header_date is None
    # Heading lines that name two dates give none; one without its comma, in
    # another case, still names its date.
    assert read_text(
        "MUNICIPAL BUILDING, MOBILE, ALABAMA, MAY 8, 2029\n",
        "MUNICIPAL BUILDING, MOBILE, ALABAMA, MAY 15, 2029\n",
    ).header_date is None
    assert read_text(
        "Municipal Building, Mobile, Alabama May 8,2029\n"
    ).header_date == date(2029, 5, 8)
    # A heading that names a day no month has is not a date.
    assert read_text(
        "MUNICIPAL BUILDING, MOBILE, ALABAMA, FEBRUARY 30, 2029\n"
    ).header_date is None


def test_pages_from_pdf_keeps_an_empty_page():
    from docket.analysis import mobile_minutes

    def page(text):
        mock = MagicMock()
        mock.extract_text.return_value = text
        return mock

    pdf = MagicMock()
    pdf.pages = [page("first"), page(None), page(""), page("fourth")]
    pdf.__enter__.return_value = pdf
    with patch.object(mobile_minutes.pdfplumber, "open", return_value=pdf) as opened:
        pages = mobile_minutes.pages_from_pdf(b"%PDF-1.7 not a real file")
    assert pages == ["first", "", "", "fourth"]
    assert opened.call_args.args[0].read() == b"%PDF-1.7 not a real file"
