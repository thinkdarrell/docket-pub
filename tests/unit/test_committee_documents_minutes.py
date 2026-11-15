"""Tests for docket.adapters.committee_documents.parse_minutes_items: a
minutes document's text read into what the committee took up and what it did
(plan `committee-documents`, M2).

The fixtures in tests/fixtures/committee_documents/ are the city's own files,
saved unchanged on 2026-11-13; that directory's README.md says where each was
listed and why it was chosen. Every PDF is read the way the service will read
it, with ``extract_text_from_pdf``. The expected values were read from the
extracted text line by line.

The symbol under test is imported inside each test, so the file collects and
reads as failing, not as a collection error, before the function exists.
"""

from collections import Counter
from functools import lru_cache
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "fixtures" / "committee_documents"

NO_QUORUM = "Item Recommended to the City Council Agenda By The Committee Chair – Lack of Quorum."

# A header as the minutes print one, for the texts written out in this file.
HEADER = "\n".join(
    [
        "BUDGET AND FINANCE COMMITTEE MEETING",
        "MONDAY, OCTOBER 12, 2026 | 3:30 PM",
        "CITY COUNCIL CHAMBERS",
        "MINUTES",
        "Councilor(s) Present: Woods, Alexander",
    ]
)


@lru_cache(maxsize=None)
def _facts(name: str):
    from docket.adapters.committee_documents import parse_minutes_items
    from docket.analysis.minutes_parser import extract_text_from_pdf

    return parse_minutes_items(extract_text_from_pdf((FIXTURES / name).read_bytes()))


def _parse(*lines: str):
    from docket.adapters.committee_documents import parse_minutes_items

    return parse_minutes_items(HEADER + "\n" + "\n".join(lines))


# --- the fixtures ----------------------------------------------------------


def test_public_safety_minutes_without_a_quorum():
    facts = _facts("ps_minutes_2026-09-22.pdf")

    assert facts.present == "Tate"
    assert [(item.name, item.action_category) for item in facts.items] == [
        ("APPROVAL OF MINUTES – September 8, 2026", "delayed"),
        ("Welcome Mart", "recommended_no_quorum"),
        ("LA Cabana", "recommended_no_quorum"),
        ("Bargoods", "recommended_no_quorum"),
        ("Bargoods", "recommended_no_quorum"),
        ("Rock N Roll Sushi 280", "recommended_no_quorum"),
        ("Pike Road Market & Meats", "other"),
        ("Graymont Foods", "recommended_no_quorum"),
        ("Legion Field", "recommended_no_quorum"),
        ("Resolution: Motorola Solutions, Inc.", "recommended_no_quorum"),
        (
            "Resolution: University of Alabama Health Services Foundation, P.C.",
            "recommended_no_quorum",
        ),
    ]
    assert [item.group for item in facts.items] == (
        [None] + ["C. LIQUOR LICENSES"] * 8 + ["D. Ordinances/Resolutions"] * 2
    )

    first = facts.items[0]
    assert (first.heading_label, first.heading_text, first.owns_heading) == (
        "B.",
        "APPROVAL OF MINUTES – September 8, 2026",
        True,
    )
    assert first.action_text == "Approval of Minute Delayed – Lack of Quorum."

    # The outcome sentence wraps onto a second line and is kept whole.
    second = facts.items[1]
    assert second.action_text == NO_QUORUM
    assert (second.heading_label, second.heading_text, second.owns_heading) == (
        "C.",
        "LIQUOR LICENSES",
        True,
    )

    # The repeated page header falls inside the third item and is dropped,
    # with the page number and the transcription line before it.
    third = facts.items[2]
    assert "There are no tax delinquencies for this location." in third.body
    assert "PUBLIC SAFETY COMMITTEEMEETING" not in third.body
    assert "Page 1 of 4" not in third.body
    assert "FULL TRANSCRIPTION" not in third.body
    assert (third.heading_label, third.heading_text, third.owns_heading) == (
        "C.",
        "LIQUOR LICENSES",
        False,
    )
    assert third.body.splitlines()[0] == "LA Cabana"

    # An action with words before its outcome runs to the outcome.
    assert facts.items[3].action_text == (
        "The Committee Chair recommended the applicant speak Detective Campbell regarding "
        "the Connect System. " + NO_QUORUM
    )

    # A free-text action stops at its first sentence when another action
    # follows, and the next licence starts the next item.
    assert facts.items[6].action_text == "Applicant Not Present for Meeting."
    assert facts.items[7].name == "Graymont Foods"
    assert facts.items[7].body.splitlines()[0] == "Graymont Foods"

    assert facts.items[9].owns_heading is True
    assert facts.items[10].owns_heading is False
    assert "$731,643.37" in facts.items[9].body

    assert all(item.moved_by is None and item.seconded_by is None for item in facts.items)
    # "E. Old/New Business", "None", "F. Adjournment" and its one line.
    assert facts.trailing_lines == 4


def test_planning_minutes_with_lettered_sub_items():
    facts = _facts("pz_minutes_2026-09-08.pdf")

    assert facts.present == "O’Quinn, Tate, Woods"
    assert [
        (item.name, item.action_category, item.moved_by, item.seconded_by) for item in facts.items
    ] == [
        (
            "APPROVAL OF THE MINUTES – July 28, 2026 & August 25, 2026",
            "minutes_approved",
            "Woods",
            "Tate",
        ),
        ("ZONING CASES", "recommended", "O’Quinn", "Tate"),
        ("Birmingham Planning Commission, PEP Staff", "recommended", "O’Quinn", "Tate"),
        (
            "Birmingham Historical Commission, Lauren Havard, PEP- Urban Design",
            "recommended",
            "Woods",
            "Tate",
        ),
    ]
    assert all(item.group is None for item in facts.items)
    assert all(item.owns_heading for item in facts.items)

    assert "ZAC2026-08007" in facts.items[1].body
    assert "ZONING CASES" not in facts.items[1].body

    # An action runs to its outcome ending and not to its first full stop.
    third = facts.items[2]
    assert third.action_text.endswith(
        "The terms will expire in 2032. Item Recommended to the City Council Agenda."
    )
    assert third.heading_label == "a."
    assert third.body.splitlines() == ["• Charles Miller", "• Daniel Christiansen", "• D'Rondrell Hamner"]

    # The page header repeated between the third action and item b. is not
    # in the action, and the heading's second line is the item's body.
    assert "PLANNING AND ZONING COMMITTEE MEETING" not in third.action_text
    assert facts.items[3].body.splitlines()[0] == "Administrator"

    # The adjournment has no "Action Taken".
    assert facts.trailing_lines == 6


def test_transportation_minutes_with_roman_numerals():
    facts = _facts("ti_minutes_2026-05-11.pdf")

    assert facts.present == "O’Quinn, Smith"
    assert [item.action_category for item in facts.items] == [
        "minutes_approved",
        "recommended",
        "recommended",
        "recommended",
        "recommended",
        "information_only",
    ]

    fifth = facts.items[4]
    assert fifth.name == "Parking Reform Update"
    assert fifth.heading_label == "VI."
    assert (fifth.moved_by, fifth.seconded_by) == ("O’Quinn", "Smith")
    assert (
        "including the amendment increasing the fine under Section 10-9-16(A) to $60 for commercial vehicles"
        in fifth.action_text
    )
    assert fifth.action_text.endswith("Item Recommended to the City Council Agenda.")
    assert "gtechna" in fifth.body
    assert "Page 2 of 4" not in fifth.body

    sixth = facts.items[5]
    assert sixth.action_text == "No Action – Information Only."
    assert (sixth.moved_by, sixth.seconded_by) == (None, None)

    # An approval worded "approved with said correction." is no outcome
    # ending; its action is everything up to the next heading line.
    assert facts.items[0].action_text.endswith("Meeting Minutes were approved with said correction.")
    assert (facts.items[0].moved_by, facts.items[0].seconded_by) == ("Smith", "O’Quinn")


def test_budget_minutes_with_a_consent_block():
    facts = _facts("bf_minutes_2026-10-12.pdf")

    assert facts.present == "Woods, Alexander, Smitherman, O’Quinn"
    assert len(facts.items) == 12
    assert Counter(item.action_category for item in facts.items) == {
        "minutes_approved": 1,
        "recommended_consent": 9,
        "recommended": 2,
    }
    by_name = {item.name: item for item in facts.items}
    assert len(by_name) == 12

    # "... Minutes were Approved" ends one line and "as Recorded." is the
    # next: the longer ending is taken.
    approval = facts.items[0]
    assert approval.name == "Approval of the Minutes – September 28, 2026"
    assert approval.heading_label == "2)"
    assert approval.action_text.endswith("Meeting Minutes were Approved as Recorded.")

    park = by_name["Friends of Avondale Park"]
    assert park.action_category == "recommended_consent"
    assert (park.moved_by, park.seconded_by) == ("Alexander", "Woods")
    assert "$4,000" in park.body
    assert park.action_text == (
        "Councilor Alexander Motioned to Approve. Councilor Woods Seconded the Motion. "
        "Item Recommended to the City Council Consent Agenda."
    )

    consent = by_name["Consideration of the Consent Agenda"]
    assert consent.action_category == "recommended_consent"
    assert consent.action_text.endswith("Items Recommended to the City Council Consent Agenda.")

    space = by_name["Space One Eleven"]
    assert "Page 2 of 6" not in space.body
    assert "MINUTES" not in space.body.splitlines()
    assert "an amount not to exceed $6,000." in space.body

    assert by_name["BJCTA Service Agreement"].action_category == "recommended"
    assert all(item.group is None and item.owns_heading for item in facts.items)


def test_joint_minutes_have_ten_items():
    facts = _facts("ps_cow_joint_minutes_2025-11-25.pdf")

    assert facts.present == "Tate, Moore"
    assert len(facts.items) == 10
    assert [item.group for item in facts.items] == [None] + ["C. LIQUOR LICENSES:"] * 8 + [None]
    assert facts.items[7].name == "LA Katrina"
    assert facts.items[7].action_text.startswith("Correction - Suite 101 Councilor Vasa Motioned")
    assert facts.items[9].name == "Ordinance/Resolutions"


# --- where an action ends --------------------------------------------------


def test_action_text_on_the_action_taken_line_is_its_first_line():
    facts = _parse(
        "1) Call to Order",
        "2) A Grant",
        "ACTION TAKEN: Councilor Woods Motioned to Approve.",
        "Item Recommended to the City Council Agenda.",
        "3) Another",
        "Action Taken Item Tabled.",
    )
    assert [item.action_text for item in facts.items] == [
        "Councilor Woods Motioned to Approve. Item Recommended to the City Council Agenda.",
        "Item Tabled.",
    ]
    assert [item.action_category for item in facts.items] == ["recommended", "tabled"]
    assert facts.trailing_lines == 0


def test_an_ending_split_over_three_lines_is_kept_whole():
    facts = _parse(
        "A. LICENSES",
        "First Shop",
        "Action Taken:",
        "Item Recommended to the City Council Agenda",
        "By The Committee Chair –",
        "Lack of Quorum.",
        "Second Shop",
        "Action Taken:",
        "Item Recommended to the City Council Agenda",
        "By The Committee Chair – Lack of Quorum.",
        "Third Shop",
        "9 Main Street",
        "Action Taken:",
        "Item Delayed.",
    )
    assert [item.action_text for item in facts.items] == [NO_QUORUM, NO_QUORUM, "Item Delayed."]
    assert [item.name for item in facts.items] == ["First Shop", "Second Shop", "Third Shop"]
    assert [item.action_category for item in facts.items] == [
        "recommended_no_quorum",
        "recommended_no_quorum",
        "delayed",
    ]


def test_a_free_text_action_before_another_action():
    facts = _parse(
        "A. LICENSES",
        "First Shop",
        "Action Taken:",
        "The applicant was asked to return",
        "with a site plan.",
        "Second Shop",
        "Action Taken:",
        "Held over",
        "Third Shop",
        "Action Taken:",
        "Item Withdrawn by the Administration.",
    )
    # Through the first line ending with a full stop; the first line when
    # none does.
    assert [item.action_text for item in facts.items] == [
        "The applicant was asked to return with a site plan.",
        "Held over",
        "Item Withdrawn by the Administration.",
    ]
    assert [item.name for item in facts.items] == ["First Shop", "Second Shop", "Third Shop"]
    assert [item.action_category for item in facts.items] == ["other", "other", "withdrawn"]


def test_a_free_text_action_before_a_heading_or_the_end_is_the_whole_stretch():
    facts = _parse(
        "1) A Report",
        "Action Taken:",
        "The committee heard the report.",
        "Staff will return in May",
        "2) Another Report",
        "Action Taken:",
        "Nothing was decided.",
        "The chair thanked staff",
    )
    assert [item.action_text for item in facts.items] == [
        "The committee heard the report. Staff will return in May",
        "Nothing was decided. The chair thanked staff",
    ]
    assert facts.trailing_lines == 0


def test_each_outcome_ending_ends_an_action():
    endings = [
        "Item Recommeded to the City Council Agena.",
        "Item Recommended to the City Council.",
        "Item Recommended to the City Council Agenda with a No Recommendation.",
        "Item Recommended to the City Council Agenda with No Recommendation.",
        "Item Recommended to the City Council Agenda with a Recommendation to Deny.",
        "Item Recommended to the City Council Consent Agenda for Approval.",
        "Forwarded to the City Council Agenda without a Recommendation.",
        "Forward Item to the City Council Agenda with a No Recommendation.",
        "No Action - Informational Only.",
        "Item Withdrawn.",
        "Item Withdrawn by Administration.",
        "Item Tabled.",
        "Item Delayed",
        "The Minutes were Approved with Said Corrections.",
        "Meeting Adjourned.",
    ]
    lines = ["A. BUSINESS"]
    for number, ending in enumerate(endings):
        lines += [f"Matter {number}", "Action Taken:", ending]
    lines += ["Matter last", "Action Taken:", "Item Tabled."]

    facts = _parse(*lines)

    # Each action stops at its ending, so the next matter's name is not
    # swallowed by a free-text action running on to a full stop.
    assert [item.action_text for item in facts.items] == endings + ["Item Tabled."]
    assert [item.name for item in facts.items] == [
        f"Matter {number}" for number in range(len(endings))
    ] + ["Matter last"]
    assert [item.action_category for item in facts.items] == [
        "recommended",
        "recommended",
        "no_recommendation",
        "no_recommendation",
        "recommended_deny",
        "recommended_consent",
        "no_recommendation",
        "no_recommendation",
        "information_only",
        "withdrawn",
        "withdrawn",
        "tabled",
        "delayed",
        "minutes_approved",
        "adjourned",
        "tabled",
    ]


# --- categories, mover and seconder ---------------------------------------


def test_category_order():
    from docket.adapters.committee_documents import parse_minutes_items

    def category(action: str) -> str:
        facts = parse_minutes_items(HEADER + "\n1) A Matter\nAction Taken:\n" + action)
        assert len(facts.items) == 1
        return facts.items[0].action_category

    # No "recomm": a delay for lack of a quorum is a delay.
    assert category("Approval of Minute Delayed – Lack of Quorum.") == "delayed"
    assert category(NO_QUORUM) == "recommended_no_quorum"
    assert category("Items Recommended to the City Council Consent Agenda By The Committee Chair - Lack of Quorum.") == (
        "recommended_no_quorum"
    )
    assert category("The Minutes were Approved as Recorded. Item Delayed.") == "minutes_approved"
    assert category("Item Recommended to the City Council Agenda with a Recommendation to Deny.") == (
        "recommended_deny"
    )
    assert category("Item Recommended to the City Council Consent Agenda with a No Recommendation.") == (
        "no_recommendation"
    )
    assert category("Forwarded to the City Council Agenda without a Recommendation.") == "no_recommendation"
    assert category("Item Recommended to the City Council Consent Agenda.") == "recommended_consent"
    assert category("Councilor Woods recommended item to the city council agenda.") == "recommended"
    assert category("NO ACTION – INFORMATION ONLY.") == "information_only"
    assert category("Item Withdrawn; it will be delayed.") == "withdrawn"
    assert category("Item Tabled. It was delayed.") == "tabled"
    assert category("Item Delayed until the meeting is adjourned.") == "delayed"
    assert category("Meeting Adjourned.") == "adjourned"
    assert category("Applicant Not Present for Meeting.") == "other"
    # A word that only contains a category's word is not that category.
    assert category("The item was undelayed.") == "other"
    assert category("The matter was stabled.") == "other"


def test_mover_and_seconder():
    facts = _parse(
        "1) First",
        "Action Taken:",
        "Councilor Pro Tem Alexander Motioned to Approve.",
        "Councilor President O’Quinn Seconded the Motion.",
        "Councilor Woods Motioned to Amend.",
        "Item Recommended to the City Council Agenda.",
        "2) Second",
        "Action Taken:",
        "Councilor Smith-Jones Motioned to Approve.",
        "Item Recommended to the City Council Agenda.",
        "3) Third",
        "Action Taken:",
        "Councilor Tate Seconded the Motion.",
        "Item Recommended to the City Council Agenda.",
    )
    assert [(item.moved_by, item.seconded_by) for item in facts.items] == [
        ("Alexander", "O’Quinn"),
        ("Smith-Jones", None),
        (None, "Tate"),
    ]


# --- items, names and groups ----------------------------------------------


def test_names_and_groups_follow_how_many_actions_share_a_heading():
    facts = _parse(
        "I. CALL TO ORDER",
        "The meeting was called to order.",
        "II. ONE MATTER",
        "Its text.",
        "Action Taken:",
        "Item Tabled.",
        "III. TWO MATTERS",
        "The first",
        "its text",
        "Action Taken:",
        "Item Delayed.",
        "The second",
        "Action Taken:",
        "Item Withdrawn.",
        "Action Taken:",
        "Item Tabled.",
        "IV. LAST",
        "x) Sub-matter",
        "Action Taken:",
        "Meeting Adjourned.",
        "V. AFTER",
        "Nothing more.",
    )
    assert [
        (item.heading_label, item.heading_text, item.owns_heading, item.group, item.name)
        for item in facts.items
    ] == [
        ("II.", "ONE MATTER", True, None, "ONE MATTER"),
        ("III.", "TWO MATTERS", True, "III. TWO MATTERS", "The first"),
        ("III.", "TWO MATTERS", False, "III. TWO MATTERS", "The second"),
        # No line of its own: the heading's text is all there is to call it.
        ("III.", "TWO MATTERS", False, "III. TWO MATTERS", "TWO MATTERS"),
        ("x)", "Sub-matter", True, None, "Sub-matter"),
    ]
    assert [item.body for item in facts.items] == [
        "The meeting was called to order.\nIts text.",
        "The first\nits text",
        "The second",
        "",
        "",
    ]
    assert facts.trailing_lines == 2


def test_an_item_before_any_heading_is_named_by_its_first_line():
    from docket.adapters.committee_documents import parse_minutes_items

    # The header is at most twenty lines; with no heading line in the text,
    # what follows the twentieth is the first item's.
    header = [f"HEADER LINE {number}" for number in range(1, 21)]
    facts = parse_minutes_items(
        "\n".join(
            header
            + [
                "A matter with no heading",
                "and a second line",
                "HEADER LINE 3",
                "Action Taken:",
                "Item Tabled.",
            ]
        )
    )
    (item,) = facts.items
    assert (item.heading_label, item.heading_text, item.owns_heading, item.group) == (None, None, False, None)
    assert item.name == "A matter with no heading"
    assert item.body == "A matter with no heading\nand a second line"


def test_minutes_with_no_action_have_no_item():
    facts = _parse("1) Call to Order", "The meeting was called to order.", "2) Adjournment")
    assert facts.items == ()
    assert facts.trailing_lines == 3
    assert facts.present == "Woods, Alexander"


# --- the lines that are dropped, and who was present ------------------------


def test_page_lines_and_the_repeated_header_are_dropped_only_when_they_are_whole_lines():
    facts = _parse(
        "1) A Matter",
        "See Page 2 of 6 of the report",
        "Page 2 of 6",
        "full transcription available upon request",
        "BUDGET AND FINANCE COMMITTEE MEETING",
        "MINUTES",
        "The minutes of the last meeting were read",
        "Action Taken:",
        "Item Tabled.",
        "Page 12 of 12",
        "CITY COUNCIL CHAMBERS",
    )
    (item,) = facts.items
    assert item.body == "See Page 2 of 6 of the report\nThe minutes of the last meeting were read"
    assert item.action_text == "Item Tabled."
    assert facts.trailing_lines == 0


def test_present_spellings():
    from docket.adapters.committee_documents import parse_minutes_items

    def present(line: str):
        return parse_minutes_items("PUBLIC SAFETY COMMITTEE MEETING\nMINUTES\n" + line + "\nA. CALL TO ORDER").present

    assert present("Councilor(s) Present: Tate") == "Tate"
    assert present("COUNCILOR(S) PRESENT: O’Quinn, Smith") == "O’Quinn, Smith"
    assert present("Councilor(s): Present: Tate, Moore") == "Tate, Moore"
    assert present("Councilor(s) Present Tate") == "Tate"
    assert present("Councilor(s) Present:") is None
    assert present("COUNCILOR LATONYA A. TATE, COMMITTEE CHAIR") is None
    # Only a header line says who was present.
    after_header = parse_minutes_items(
        "PUBLIC SAFETY COMMITTEE MEETING\nMINUTES\nA. CALL TO ORDER\nCouncilor(s) Present: Tate"
    )
    assert after_header.present is None
