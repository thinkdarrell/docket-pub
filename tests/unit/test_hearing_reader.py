"""The hearing reader, on twenty-five stored Birmingham agenda titles.

Plan `birmingham-coming-up`, M1. The fixture
tests/fixtures/hearings/birmingham_titles.json holds 25 agenda item titles as
production stored them on 2026-11-16 (`title` is the first 420 characters of
the stored title, `len` its full length). The table EXPECTED is what
`docket.enrichment.hearings.read_hearing` must read from each; the pair tests
are the cases that decide whether two items set one hearing.

The reader is imported inside each test, so the file collects without it.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent.parent / "fixtures" / "hearings" / "birmingham_titles.json"
TITLES = {row["id"]: row["title"] for row in json.loads(FIXTURE.read_text(encoding="utf-8"))}

# id -> None (no reading), or (hearing date or None, kind, property count or None)
EXPECTED = {
    730: (date(2026, 4, 7), "other", None),
    746: (None, "other", None),
    1152: (date(2026, 2, 10), "vacation", None),
    1153: (date(2026, 2, 10), "vacation", None),
    1680: (date(2025, 12, 9), "zoning", None),
    1681: (date(2025, 12, 9), "zoning", None),
    2116: (date(2025, 11, 4), "zoning", None),
    3131: (date(2025, 7, 15), "zoning", None),
    3167: (None, "vacation", None),
    3238: (None, "budget", None),
    3296: (None, "other", None),
    3297: (date(2025, 6, 10), "vacation", None),
    3339: (date(2025, 6, 10), "vacation", None),
    4412: None,
    4425: (date(2025, 2, 4), "zoning", None),
    58869: (date(2026, 6, 9), "zoning", None),
    58878: (None, "budget", None),
    59096: None,
    62182: (date(2026, 11, 17), "vacation", None),
    62830: (date(2026, 11, 17), "vacation", None),
    62882: (date(2026, 11, 17), "weed_lots", 212),
    63046: (date(2026, 11, 24), "zoning", None),
    63108: (date(2026, 12, 8), "zoning", None),
    63109: (date(2026, 12, 8), "weed_lots", 136),
    63166: (date(2026, 12, 15), "weed_lots", 136),
}

ZONING_SHARED_KEY = "toconsidertheadoptionofanordinancetoamendthezoningdistrictmapofthecityofbirmingham"


def _read(item_id):
    from docket.enrichment.hearings import read_hearing

    return read_hearing(TITLES[item_id])


def test_fixture_holds_the_25_titles():
    assert len(TITLES) == 25
    assert set(TITLES) == set(EXPECTED)


@pytest.mark.parametrize("item_id", sorted(EXPECTED))
def test_expected_reading(item_id):
    reading = _read(item_id)
    expected = EXPECTED[item_id]
    if expected is None:
        assert reading is None
        return
    assert reading is not None
    assert (reading.hearing_date, reading.kind, reading.property_count) == expected


def test_constants():
    from docket.enrichment import hearings

    assert hearings.RULE_VERSION == 1
    assert hearings.KINDS == ("zoning", "weed_lots", "vacation", "budget", "other")
    assert hearings.KIND_LABELS == {
        "zoning": "Zoning",
        "weed_lots": "Weed lots",
        "vacation": "Street or right-of-way",
        "budget": "Budget",
        "other": "Other",
    }
    assert hearings.PREFIX_MIN == 90


# --- the four pair cases ---------------------------------------------------


def test_pair_3297_3339_same_hearing_by_opening_text():
    from docket.enrichment.hearings import same_hearing

    short, long_ = _read(3297), _read(3339)
    assert short.hearing_date == long_.hearing_date
    assert short.kind == long_.kind
    assert len(short.subject_key) == 101
    assert long_.subject_key.startswith(short.subject_key)
    assert len(long_.subject_key) > len(short.subject_key)
    assert same_hearing(short.subject_key, long_.subject_key)
    assert same_hearing(long_.subject_key, short.subject_key)
    # A case number could not have been the key: neither stored title reaches it.
    assert "Case No" not in TITLES[3297]
    assert "Case No" not in TITLES[3339]


def test_pair_1152_1153_different_vacations_of_one_day():
    from docket.enrichment.hearings import same_hearing

    a, b = _read(1152), _read(1153)
    shared = "toconsidertheadoptionofaresolutionassentingtothevacationof"
    assert a.subject_key.startswith(shared + "36000")
    assert b.subject_key.startswith(shared + "1185")
    assert not same_hearing(a.subject_key, b.subject_key)


def test_pair_1680_1681_different_zoning_cases_of_one_day():
    from docket.enrichment.hearings import same_hearing

    a, b = _read(1680), _read(1681)
    assert a.subject_key.startswith(ZONING_SHARED_KEY + "casenozac202500013")
    assert b.subject_key.startswith(ZONING_SHARED_KEY + "casenozac202500022")
    assert not same_hearing(a.subject_key, b.subject_key)


def test_pair_62182_62830_different_hearings_of_one_day():
    from docket.enrichment.hearings import same_hearing

    a, b = _read(62182), _read(62830)
    assert a.hearing_date == b.hearing_date
    assert a.subject_key.startswith("toconsidertheclosureof")
    assert b.subject_key.startswith("toconsidertheadoptionof")
    assert not same_hearing(a.subject_key, b.subject_key)


# --- rules the fixture cannot reach -----------------------------------------


def test_third_date_form_to_be_held_on():
    from docket.enrichment.hearings import read_hearing

    reading = read_hearing(
        "A Resolution setting a public hearing to consider a moratorium to be held "
        "at the regular meeting of the Council in the Council Chambers on March 3, 2026"
    )
    assert reading.hearing_date == date(2026, 3, 3)
    assert reading.subject.startswith("to consider a moratorium")


def test_impossible_date_is_no_date():
    from docket.enrichment.hearings import read_hearing

    reading = read_hearing(
        "A Resolution setting a public hearing February 30, 2026, to consider a moratorium."
    )
    assert reading is not None
    assert reading.hearing_date is None


def test_2116_subject_is_cut_at_the_first_date_whatever_the_correction_did():
    reading = _read(2116)
    assert reading.subject.startswith("to consider the adoption of an Ordinance")
    assert len(reading.subject_key) == 100
    assert reading.subject_key.endswith("zac202500019")
    assert "november" not in reading.subject_key


def test_same_hearing_refuses_the_wording_every_zoning_hearing_shares():
    from docket.enrichment.hearings import same_hearing

    key = _read(1680).subject_key
    assert len(ZONING_SHARED_KEY) == 82
    assert key.startswith(ZONING_SHARED_KEY)
    assert not same_hearing(ZONING_SHARED_KEY, key)
    assert not same_hearing(key, ZONING_SHARED_KEY)


def test_same_hearing_prefix_needs_90_characters():
    from docket.enrichment.hearings import same_hearing

    key = _read(1680).subject_key
    assert len(key) > 90
    assert not same_hearing(key[:89], key)
    assert not same_hearing(key, key[:89])
    assert same_hearing(key[:90], key)
    assert same_hearing(key, key[:90])


def test_no_title_no_reading():
    from docket.enrichment.hearings import read_hearing

    assert read_hearing(None) is None
    assert read_hearing("") is None


def test_reader_imports_nothing_from_docket():
    """The layer rule: enrichment's reader is standard library only."""
    from docket.enrichment import hearings

    source = Path(hearings.__file__).read_text(encoding="utf-8")
    assert "import docket" not in source
    assert "from docket" not in source


# --- rules pinned after the removal check -----------------------------------
#
# Each test below was added after taking one rule out of a copy of the reader
# left every earlier test passing. The sentences are constructed, not stored
# titles; each differs from a fixture title only in the clause it pins.

SETS = "A Resolution setting a public hearing "


def _date_of(title):
    from docket.enrichment.hearings import read_hearing

    reading = read_hearing(title)
    assert reading is not None
    return reading.hearing_date


def _kind_of(title):
    from docket.enrichment.hearings import read_hearing

    return read_hearing(title).kind


def test_whitespace_runs_are_one_space_before_any_rule_reads():
    title = "A Resolution setting a\tpublic\n hearing November  17,\n2026, to consider a plan"
    assert _date_of(title) == date(2026, 11, 17)


def test_trigger_reads_the_public_hearing():
    title = "A Resolution providing for the public hearing November 17, 2026, to hear objections"
    assert _date_of(title) == date(2026, 11, 17)


def test_trigger_and_date_ignore_case():
    title = "A RESOLUTION SETTING A PUBLIC HEARING NOVEMBER 17, 2026, TO CONSIDER A PLAN"
    assert _date_of(title) == date(2026, 11, 17)


def test_trigger_starts_at_a_word():
    from docket.enrichment.hearings import read_hearing

    assert read_hearing("A Resolution resetting a public hearing November 17, 2026") is None


def test_trigger_is_the_first_match():
    title = (
        SETS + "November 17, 2026, to consider a plan, and providing for a public "
        "hearing December 1, 2026, to hear objections"
    )
    assert _date_of(title) == date(2026, 11, 17)


def test_date_comma_is_optional():
    assert _date_of(SETS + "November 17 2026 to consider a plan") == date(2026, 11, 17)


def test_date_year_is_four_digits_and_no_more():
    assert _date_of(SETS + "November 17, 20266 to consider a plan") is None


def test_first_form_allows_on_between_trigger_and_date():
    from docket.enrichment.hearings import read_hearing

    reading = read_hearing(SETS + "on November 17, 2026, to consider a plan")
    assert reading.hearing_date == date(2026, 11, 17)
    assert reading.subject == "to consider a plan"


def test_second_form_reads_only_after_the_trigger():
    title = (
        "A Resolution, further to notice given on the 3rd day of March, 2026, "
        "setting a public hearing to consider a plan"
    )
    assert _date_of(title) is None


def test_second_form_is_tried_before_the_third():
    title = (
        SETS + "to consider a plan, to be held on March 3, 2026, notice having "
        "been given on the 7th day of April, 2026"
    )
    assert _date_of(title) == date(2026, 4, 7)


@pytest.mark.parametrize("stop", [".", ";"])
def test_third_form_stops_at_a_full_stop_or_semicolon(stop):
    title = (
        SETS + "to consider a plan to be held in the Council Chambers" + stop
        + " The plan was filed on March 3, 2026"
    )
    assert _date_of(title) is None


def test_third_form_needs_the_to_be_held_clause():
    assert _date_of(SETS + "to consider the plan filed on March 3, 2026") is None


def test_third_form_reads_only_after_the_trigger():
    title = (
        "The meeting to be held on March 3, 2026, having been called off, a "
        "Resolution setting a public hearing to consider a plan"
    )
    assert _date_of(title) is None


def test_change_note_moves_only_the_date_it_names():
    title = (
        "[CHANGE HEARING DATE FROM OCTOBER 21, 2025 TO NOVEMBER 4, 2025] "
        + SETS + "October 28, 2025 to consider a plan"
    )
    assert _date_of(title) == date(2025, 10, 28)


def test_kind_zoning_by_zone_district_and_by_rezon():
    assert _kind_of(SETS + "November 17, 2026, to change zone district boundaries") == "zoning"
    assert _kind_of(SETS + "November 17, 2026, to rezone the property at 1 Main Street") == "zoning"


def test_kind_vacation_by_each_of_its_words():
    assert _kind_of(SETS + "November 17, 2026, to consider the vacation of an alley") == "vacation"
    assert _kind_of(SETS + "November 17, 2026, to consider a fence in the right-of-way") == "vacation"
    assert _kind_of(SETS + "November 17, 2026, to consider a fence in the right of way") == "vacation"


def test_kind_is_the_first_that_fits():
    weeds_and_zoning = (
        "A Resolution finding that (3) properties have noxious or dangerous weeds "
        "growing thereon contrary to the Zoning Ordinance and providing for a public "
        "hearing November 17, 2026"
    )
    assert _kind_of(weeds_and_zoning) == "weed_lots"
    assert _kind_of(SETS + "November 17, 2026, to rezone a lot after the vacation of an alley") == "zoning"
    assert _kind_of(SETS + "November 17, 2026, to consider the closure of Budget Lane") == "vacation"


def test_property_count_is_the_first_in_the_text():
    from docket.enrichment.hearings import read_hearing

    reading = read_hearing(
        "A Resolution finding that (212) properties have noxious or dangerous weeds, "
        "(3) properties of them owned by the City, and providing for a public hearing "
        "November 17, 2026"
    )
    assert reading.property_count == 212
    assert reading.subject_key == "weeds:212"


def test_weed_lot_key_is_the_property_count():
    from docket.enrichment.hearings import same_hearing

    assert _read(62882).subject_key == "weeds:212"
    assert _read(63109).subject_key == "weeds:136"
    assert _read(63166).subject_key == "weeds:136"
    assert same_hearing("weeds:136", "weeds:136")
    assert not same_hearing("weeds:212", "weeds:136")


def test_a_count_makes_the_key_only_for_a_weed_lot_hearing():
    from docket.enrichment.hearings import read_hearing

    reading = read_hearing(SETS + "November 17, 2026, to rezone the (3) properties at 1 Main Street")
    assert reading.kind == "zoning"
    assert reading.property_count == 3
    assert reading.subject_key == "torezonethe3propertiesat1mainstreet"


def test_key_drops_bracket_groups():
    key = _read(62182).subject_key
    assert "[First Reading]" in TITLES[62182]
    assert key.endswith("deteriorationconditionoftheroadway")


def test_key_is_cut_at_submitted_by_and_recommended_by():
    from docket.enrichment.hearings import read_hearing

    assert "(Submitted by" in TITLES[3167]
    assert _read(3167).subject_key.endswith("fromneighboringbusinesses")
    recommended = read_hearing(
        SETS + "November 17, 2026, to consider a plan. (RECOMMENDED BY THE BUDGET COMMITTEE)"
    )
    assert recommended.subject_key == "toconsideraplan"


def test_same_hearing_needs_the_shorter_key_to_open_the_longer():
    from docket.enrichment.hearings import same_hearing

    key = _read(1680).subject_key
    inside = key[5:100]
    assert len(inside) == 95 and inside in key
    assert not same_hearing(inside, key)
