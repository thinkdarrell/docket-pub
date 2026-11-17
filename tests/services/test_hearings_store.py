"""docket.services.hearings: reading, grouping, storing and listing hearings.

Every row is seeded under Birmingham (one test under Mobile): meetings whose
titles begin ``HEARINGS_TEST_`` and items whose titles are the saved
production titles of ``tests/fixtures/hearings/birmingham_titles.json``.
The meetings, and the hearings their items were linked to, are deleted
before and after every test. The service's names are imported inside each
test, so the file collects before the service exists. Runs in the services
tier (DATABASE_URL names docket_test_*).

Plan `birmingham-coming-up`, M2.
"""

from __future__ import annotations

import itertools
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from docket.db import db_cursor

FIXTURE = Path(__file__).parent.parent / "fixtures" / "hearings" / "birmingham_titles.json"
TITLES = {row["id"]: row["title"] for row in json.loads(FIXTURE.read_text())}
PREFIX = "HEARINGS_TEST_"
SINCE = date(2025, 1, 1)
OCT_13 = date(2026, 10, 13)
OCT_26 = date(2026, 10, 26)
NOV_17 = date(2026, 11, 17)

# Item 1680's title cut just after "ZAC2025-000": a key of 98 characters
# that opens both item 1680's and item 1681's.
CUT_1680 = TITLES[1680][: TITLES[1680].index("ZAC2025-000") + len("ZAC2025-000")]

_serial = itertools.count(1)


def _city(slug: str = "birmingham") -> int:
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug = %s", (slug,))
        return cur.fetchone()["id"]


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


def _meeting(day: date = OCT_13, *, title: str = "Regular meeting", hidden: bool = False, city: int | None = None,
             agenda_url: str | None = None) -> int:
    n = next(_serial)
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type, is_hidden, agenda_url)
               VALUES (%s, %s, %s, %s, 'council', %s, %s) RETURNING id""",
            (city or _city(), f"hearings-test-{n}", PREFIX + title, day, hidden, agenda_url),
        )
        return cur.fetchone()["id"]


def _item(meeting_id: int, title: str, *, status: str = "completed") -> int:
    n = next(_serial)
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO agenda_items (meeting_id, external_id, title, processing_status)
               VALUES (%s, %s, %s, %s) RETURNING id""",
            (meeting_id, f"hearings-test-item-{n}", title, status),
        )
        return cur.fetchone()["id"]


def _retitle(item_id: int, title: str) -> None:
    with db_cursor() as cur:
        cur.execute("UPDATE agenda_items SET title = %s WHERE id = %s", (title, item_id))


def _stored() -> list[dict]:
    """The hearings the seeded items are linked to, each with its item ids."""
    with db_cursor() as cur:
        cur.execute(
            """SELECT h.id, h.municipality_id, h.hearing_date, h.kind, h.subject, h.subject_key, h.property_count,
                      h.rule_version, h.created_at, h.updated_at, array_agg(phi.agenda_item_id ORDER BY phi.agenda_item_id) AS items
                 FROM public_hearings h
                 JOIN public_hearing_items phi ON phi.hearing_id = h.id
                 JOIN agenda_items ai ON ai.id = phi.agenda_item_id
                 JOIN meetings mt ON mt.id = ai.meeting_id
                WHERE mt.title LIKE %s
                GROUP BY h.id ORDER BY h.id""",
            (PREFIX + "%",),
        )
        return [dict(r) for r in cur.fetchall()]


def _count(table: str) -> int:
    with db_cursor() as cur:
        cur.execute(f"SELECT count(*) AS n FROM {table}")
        return cur.fetchone()["n"]


def _row(item_id: int, title: str, meeting_date: date = OCT_13) -> dict:
    """A row as `find_readings` returns one, for the pure grouping tests."""
    from docket.enrichment.hearings import read_hearing

    return {"item_id": item_id, "meeting_id": 1, "meeting_date": meeting_date, "reading": read_hearing(title)}


# --- find_readings ----------------------------------------------------------


def test_find_readings_returns_items_with_a_reading_in_item_order():
    from docket.services import hearings

    meeting = _meeting()
    a = _item(meeting, TITLES[62830])
    b = _item(meeting, TITLES[3238])  # a reading with no date
    _item(meeting, TITLES[59096])  # "PUBLIC HEARING ON ...": matches the SQL, has no trigger
    _item(meeting, "A Resolution approving a contract for paving.")
    c = _item(meeting, TITLES[62882])

    rows = hearings.find_readings(_city(), SINCE)

    assert [r["item_id"] for r in rows] == [a, b, c]
    assert {r["meeting_id"] for r in rows} == {meeting}
    assert {r["meeting_date"] for r in rows} == {OCT_13}
    assert rows[0]["reading"].hearing_date == NOV_17 and rows[0]["reading"].kind == "vacation"
    assert rows[1]["reading"].hearing_date is None
    assert rows[2]["reading"].property_count == 212


def test_find_readings_reads_a_title_whose_words_are_split_by_a_newline():
    from docket.services import hearings

    item = _item(_meeting(), TITLES[62830].replace("public hearing", "public\n\thearing"))

    assert [r["item_id"] for r in hearings.find_readings(_city(), SINCE)] == [item]


def test_find_readings_reads_a_show_cause_hearing():
    from docket.services import hearings

    item = _item(_meeting(), TITLES[3296])

    assert [r["item_id"] for r in hearings.find_readings(_city(), SINCE)] == [item]


def test_find_readings_is_bounded_by_meeting_date_and_city():
    from docket.services import hearings

    early = _item(_meeting(date(2026, 10, 1)), TITLES[62830])
    on_since = _item(_meeting(OCT_13), TITLES[62830])
    on_until = _item(_meeting(OCT_26), TITLES[62830])
    _item(_meeting(date(2026, 10, 27)), TITLES[62830])
    _item(_meeting(OCT_13, city=_city("mobile")), TITLES[62830])

    assert [r["item_id"] for r in hearings.find_readings(_city(), OCT_13, OCT_26)] == [on_since, on_until]
    assert early not in [r["item_id"] for r in hearings.find_readings(_city(), OCT_13)]
    assert len(hearings.find_readings(_city(), OCT_13)) == 3
    assert len(hearings.find_readings(_city("mobile"), SINCE)) == 1


# --- group_readings (pure) --------------------------------------------------


def test_group_two_items_with_one_text_are_one_hearing():
    from docket.services import hearings

    groups = hearings.group_readings([_row(7, TITLES[62830]), _row(3, TITLES[62830], OCT_26)])

    assert len(groups) == 1
    assert groups[0]["item_ids"] == [3, 7]
    assert groups[0]["hearing_date"] == NOV_17 and groups[0]["kind"] == "vacation"


def test_group_leaves_out_an_undated_reading():
    from docket.services import hearings

    assert hearings.group_readings([_row(1, TITLES[3238])]) == []


def test_group_keeps_the_longest_key_and_its_subject_whatever_the_item_order():
    from docket.enrichment.hearings import read_hearing
    from docket.services import hearings

    long = read_hearing(TITLES[3339])
    for rows in ([_row(1, TITLES[3297]), _row(2, TITLES[3339])], [_row(1, TITLES[3339]), _row(2, TITLES[3297])]):
        groups = hearings.group_readings(rows)
        assert len(groups) == 1
        assert groups[0]["subject_key"] == long.subject_key
        assert groups[0]["subject"] == long.subject
        assert groups[0]["item_ids"] == [1, 2]


def test_group_a_short_key_that_opens_two_hearings_joins_neither():
    from docket.services import hearings

    groups = hearings.group_readings([_row(1, CUT_1680), _row(2, TITLES[1680]), _row(3, TITLES[1681])])

    assert sorted(g["item_ids"] for g in groups) == [[1], [2], [3]]


def test_group_a_short_key_that_opens_one_hearing_joins_it():
    from docket.services import hearings

    groups = hearings.group_readings([_row(1, CUT_1680), _row(2, TITLES[1680])])

    assert [g["item_ids"] for g in groups] == [[1, 2]]


def test_group_a_key_under_the_minimum_joins_nothing():
    """An 82-character key (the words every zoning hearing shares) opens item 1680's and stands alone."""
    from docket.enrichment.hearings import PREFIX_MIN, read_hearing
    from docket.services import hearings

    shared = TITLES[1680][: TITLES[1680].index(" (Case No.")]
    assert len(read_hearing(shared).subject_key) == 82 < PREFIX_MIN

    groups = hearings.group_readings([_row(1, shared), _row(2, TITLES[1680])])

    assert sorted(g["item_ids"] for g in groups) == [[1], [2]]


def test_group_a_key_joins_only_a_hearing_of_its_own_date_and_kind():
    from dataclasses import replace

    from docket.services import hearings

    base = _row(1, TITLES[62830])
    other_date = dict(_row(2, TITLES[62830]), reading=replace(base["reading"], hearing_date=date(2026, 11, 24)))
    other_kind = dict(_row(3, TITLES[62830]), reading=replace(base["reading"], kind="other"))
    short = _row(4, TITLES[62830][:300])  # opens the others' key
    short_other_date = dict(_row(5, TITLES[62830][:300]), reading=replace(short["reading"], hearing_date=date(2026, 11, 24)))

    groups = hearings.group_readings([base, other_date, other_kind, short, short_other_date])

    assert sorted(g["item_ids"] for g in groups) == [[1, 4], [2, 5], [3]]


def test_group_weed_lot_resolutions_of_one_day_and_count_are_one_hearing():
    from docket.services import hearings

    groups = hearings.group_readings([_row(1, TITLES[62882]), _row(2, TITLES[62882], OCT_26), _row(3, TITLES[63109])])

    assert [(g["hearing_date"], g["kind"], g["property_count"], g["item_ids"]) for g in groups] == [
        (NOV_17, "weed_lots", 212, [1, 2]),
        (date(2026, 12, 8), "weed_lots", 136, [3]),
    ]


def test_group_keeps_the_first_property_count_seen():
    from dataclasses import replace

    from docket.services import hearings

    without = _row(1, TITLES[62830])  # the group's first row: equal keys are taken in item order
    with_count = _row(2, TITLES[62830])
    with_count["reading"] = replace(with_count["reading"], property_count=4)
    another = _row(3, TITLES[62830])
    another["reading"] = replace(another["reading"], property_count=9)

    assert hearings.group_readings([another, with_count, without])[0]["property_count"] == 4
    assert hearings.group_readings([without, another])[0]["property_count"] == 9


def test_groups_are_ordered_by_date_then_first_item():
    from docket.services import hearings

    groups = hearings.group_readings(
        [_row(1, TITLES[63108]), _row(2, TITLES[62882]), _row(3, TITLES[62182]), _row(4, TITLES[62830])]
    )

    assert [g["item_ids"] for g in groups] == [[2], [3], [4], [1]]


# --- refresh_hearings -------------------------------------------------------


def test_two_items_on_two_meetings_make_one_hearing_with_two_links():
    from docket.enrichment.hearings import RULE_VERSION, read_hearing
    from docket.services import hearings

    a = _item(_meeting(OCT_13), TITLES[62830])
    b = _item(_meeting(OCT_26), TITLES[62830])

    report = hearings.refresh_hearings(_city(), SINCE)

    stored = _stored()
    assert len(stored) == 1
    reading = read_hearing(TITLES[62830])
    assert stored[0]["items"] == [a, b]
    assert stored[0]["municipality_id"] == _city()
    assert stored[0]["hearing_date"] == NOV_17
    assert stored[0]["kind"] == "vacation"
    assert stored[0]["subject"] == reading.subject
    assert stored[0]["subject_key"] == reading.subject_key
    assert stored[0]["property_count"] is None
    assert stored[0]["rule_version"] == RULE_VERSION
    assert report == hearings.HearingReport(matched=2, dated=2, undated=0, hearings=1, created=1, linked=2)


def test_three_subjects_on_one_date_make_three_hearings():
    from docket.services import hearings

    meeting = _meeting()
    closure = _item(meeting, TITLES[62182])
    vacation = _item(meeting, TITLES[62830])
    weeds = _item(meeting, TITLES[62882])

    report = hearings.refresh_hearings(_city(), SINCE)

    stored = _stored()
    assert [(h["hearing_date"], h["kind"], h["property_count"], h["items"]) for h in stored] == [
        (NOV_17, "vacation", None, [closure]),
        (NOV_17, "vacation", None, [vacation]),
        (NOV_17, "weed_lots", 212, [weeds]),
    ]
    assert (report.hearings, report.created, report.linked) == (3, 3, 3)


def test_a_second_refresh_changes_no_count():
    from docket.services import hearings

    meeting = _meeting()
    for fixture_id in (62182, 62830, 62882, 3238):
        _item(meeting, TITLES[fixture_id])
    _item(_meeting(OCT_26), TITLES[62830])

    first = hearings.refresh_hearings(_city(), SINCE)
    before = (_stored(), _count("public_hearings"), _count("public_hearing_items"))
    second = hearings.refresh_hearings(_city(), SINCE)

    assert (_stored(), _count("public_hearings"), _count("public_hearing_items")) == before
    assert first == hearings.HearingReport(matched=5, dated=4, undated=1, hearings=3, created=3, linked=4)
    assert second == hearings.HearingReport(matched=5, dated=4, undated=1, hearings=3, created=0, linked=4)


def test_setting_and_amending_items_make_one_hearing_with_the_longer_key():
    from docket.enrichment.hearings import read_hearing
    from docket.services import hearings

    meeting = _meeting(date(2025, 5, 13))
    setting = _item(meeting, TITLES[3339])
    amending = _item(_meeting(date(2025, 5, 20)), TITLES[3297])

    hearings.refresh_hearings(_city(), SINCE)

    stored = _stored()
    assert len(stored) == 1
    assert stored[0]["items"] == [setting, amending]
    assert stored[0]["hearing_date"] == date(2025, 6, 10)
    assert stored[0]["subject_key"] == read_hearing(TITLES[3339]).subject_key


def test_a_stored_short_key_is_lengthened_when_the_longer_title_arrives():
    """The amending item is stored first, alone; the setting item's longer key then replaces the stored one."""
    from docket.enrichment.hearings import read_hearing
    from docket.services import hearings

    amending = _item(_meeting(date(2025, 5, 20)), TITLES[3297])
    hearings.refresh_hearings(_city(), SINCE)
    first = _stored()
    assert first[0]["subject_key"] == read_hearing(TITLES[3297]).subject_key

    setting = _item(_meeting(date(2025, 5, 27)), TITLES[3339])
    report = hearings.refresh_hearings(_city(), SINCE)

    stored = _stored()
    long = read_hearing(TITLES[3339])
    assert [h["id"] for h in stored] == [first[0]["id"]], "the same stored hearing, not a new one"
    assert stored[0]["items"] == [amending, setting]
    assert stored[0]["subject_key"] == long.subject_key
    assert stored[0]["subject"] == long.subject
    assert report.created == 0
    assert first[0]["updated_at"] == first[0]["created_at"]
    assert stored[0]["created_at"] == first[0]["created_at"]
    assert stored[0]["updated_at"] > first[0]["updated_at"], "the lengthening is stamped"


def test_a_stored_long_key_is_kept_when_only_the_short_title_is_read():
    """The setting item's meeting is before `since`; the run reads the amending item alone and finds the stored hearing."""
    from docket.enrichment.hearings import read_hearing
    from docket.services import hearings

    setting = _item(_meeting(date(2025, 5, 13)), TITLES[3339])
    hearings.refresh_hearings(_city(), SINCE)
    amending = _item(_meeting(date(2025, 5, 20)), TITLES[3297])

    report = hearings.refresh_hearings(_city(), date(2025, 5, 20))

    stored = _stored()
    assert len(stored) == 1
    assert stored[0]["items"] == [setting, amending]
    assert stored[0]["subject_key"] == read_hearing(TITLES[3339]).subject_key
    assert stored[0]["subject"] == read_hearing(TITLES[3339]).subject
    assert report.created == 0


def test_a_short_key_that_two_stored_hearings_accept_is_stored_on_its_own():
    from docket.services import hearings

    meeting = _meeting(date(2025, 11, 18))
    _item(meeting, TITLES[1680])
    _item(meeting, TITLES[1681])
    hearings.refresh_hearings(_city(), SINCE)
    cut = _item(_meeting(date(2025, 11, 25)), CUT_1680)

    report = hearings.refresh_hearings(_city(), date(2025, 11, 25))

    stored = _stored()
    assert len(stored) == 3
    assert [h["items"] for h in stored if cut in h["items"]] == [[cut]]
    assert report.created == 1


def test_an_exact_stored_key_is_matched_before_a_prefix():
    """Two stored hearings, one key opening the other; a run that reads only the short title finds its own."""
    from docket.services import hearings

    meeting = _meeting(date(2025, 11, 18))
    whole = _item(meeting, TITLES[1680])
    hearings.refresh_hearings(_city(), SINCE)
    # Stored on its own, as the test above leaves a cut title beside two hearings.
    cut = _item(_meeting(date(2025, 11, 25)), CUT_1680)
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO public_hearings (municipality_id, hearing_date, kind, subject, subject_key, rule_version)
               SELECT municipality_id, hearing_date, kind, 'cut', left(subject_key, 98), rule_version
                 FROM public_hearings WHERE id = %s RETURNING id""",
            (_stored()[0]["id"],),
        )
        own = cur.fetchone()["id"]
        cur.execute("INSERT INTO public_hearing_items (agenda_item_id, hearing_id) VALUES (%s, %s)", (cut, own))

    report = hearings.refresh_hearings(_city(), date(2025, 11, 25))

    stored = {h["id"]: h["items"] for h in _stored()}
    assert stored[own] == [cut]
    assert sorted(stored.values()) == sorted([[whole], [cut]])
    assert report.created == 0


def test_an_item_that_loses_its_trigger_loses_its_link_and_its_hearing():
    from docket.services import hearings

    meeting = _meeting()
    kept = _item(meeting, TITLES[62182])
    edited = _item(meeting, TITLES[62830])
    hearings.refresh_hearings(_city(), SINCE)
    assert len(_stored()) == 2

    _retitle(edited, "A Resolution accepting the minutes of the public hearing held November 17, 2026.")
    report = hearings.refresh_hearings(_city(), SINCE)

    assert [h["items"] for h in _stored()] == [[kept]]
    assert _count("public_hearings") == 1, "the hearing left with no link is deleted"
    assert (report.matched, report.hearings) == (1, 1)


def test_an_item_retitled_to_an_unrelated_sentence_loses_its_link_and_its_hearing():
    from docket.services import hearings

    edited = _item(_meeting(), TITLES[62830])
    hearings.refresh_hearings(_city(), SINCE)
    assert len(_stored()) == 1

    _retitle(edited, "A Resolution approving a contract for paving.")
    report = hearings.refresh_hearings(_city(), SINCE)

    assert _stored() == []
    assert _count("public_hearings") == 0
    assert _count("public_hearing_items") == 0
    assert report == hearings.HearingReport(matched=0, dated=0, undated=0, hearings=0, created=0, linked=0)


def test_an_item_that_loses_its_date_loses_its_link():
    from docket.services import hearings

    edited = _item(_meeting(), TITLES[62830])
    hearings.refresh_hearings(_city(), SINCE)

    _retitle(edited, TITLES[3238])
    report = hearings.refresh_hearings(_city(), SINCE)

    assert _stored() == []
    assert (report.matched, report.dated, report.undated) == (1, 0, 1)


def test_an_item_whose_date_changes_moves_to_a_new_hearing():
    from docket.services import hearings

    edited = _item(_meeting(), TITLES[62830])
    hearings.refresh_hearings(_city(), SINCE)

    _retitle(edited, TITLES[62830].replace("November 17, 2026", "November 24, 2026"))
    hearings.refresh_hearings(_city(), SINCE)

    stored = _stored()
    assert [(h["hearing_date"], h["items"]) for h in stored] == [(date(2026, 11, 24), [edited])]
    assert _count("public_hearings") == 1 and _count("public_hearing_items") == 1


def test_an_item_before_since_keeps_its_link_through_a_run_that_does_not_read_it():
    from docket.services import hearings

    old = _item(_meeting(date(2026, 9, 1)), TITLES[62182])
    new = _item(_meeting(OCT_13), TITLES[62830])
    hearings.refresh_hearings(_city(), SINCE)
    assert len(_stored()) == 2

    hearings.refresh_hearings(_city(), date(2026, 10, 1))

    assert sorted(h["items"] for h in _stored()) == sorted([[old], [new]])


def test_an_item_after_until_keeps_its_link_through_a_run_that_does_not_read_it():
    from docket.services import hearings

    early = _item(_meeting(date(2026, 9, 1)), TITLES[62182])
    late = _item(_meeting(OCT_26), TITLES[62830])
    hearings.refresh_hearings(_city(), SINCE)

    report = hearings.refresh_hearings(_city(), SINCE, date(2026, 9, 30))

    assert sorted(h["items"] for h in _stored()) == sorted([[early], [late]])
    assert report.matched == 1


def test_a_run_leaves_another_citys_links_and_hearings_alone():
    from docket.services import hearings

    mobile = _city("mobile")
    theirs = _item(_meeting(city=mobile), TITLES[62830])
    hearings.refresh_hearings(mobile, SINCE)
    ours = _item(_meeting(), TITLES[62830])
    hearings.refresh_hearings(_city(), SINCE)
    assert sorted((h["municipality_id"], h["items"]) for h in _stored()) == sorted([(mobile, [theirs]), (_city(), [ours])])

    _retitle(ours, "A Resolution approving a contract for paving.")
    hearings.refresh_hearings(_city(), SINCE)

    assert [(h["municipality_id"], h["items"]) for h in _stored()] == [(mobile, [theirs])]


def test_two_zoning_cases_and_a_title_cut_inside_the_case_number_make_three_hearings():
    from docket.services import hearings

    meeting = _meeting(date(2025, 11, 18))
    a = _item(meeting, TITLES[1680])
    b = _item(meeting, TITLES[1681])
    cut = _item(meeting, CUT_1680)

    hearings.refresh_hearings(_city(), SINCE)

    assert sorted(h["items"] for h in _stored()) == [[a], [b], [cut]]


def test_one_zoning_case_and_the_cut_title_make_one_hearing_with_two_links():
    """The accepted limit: with one candidate the short key joins it."""
    from docket.enrichment.hearings import read_hearing
    from docket.services import hearings

    meeting = _meeting(date(2025, 11, 18))
    a = _item(meeting, TITLES[1680])
    cut = _item(meeting, CUT_1680)
    assert len(read_hearing(CUT_1680).subject_key) == 98

    hearings.refresh_hearings(_city(), SINCE)

    stored = _stored()
    assert [h["items"] for h in stored] == [[a, cut]]
    assert stored[0]["subject_key"] == read_hearing(TITLES[1680]).subject_key


def test_an_undated_reading_stores_nothing():
    from docket.services import hearings

    _item(_meeting(), TITLES[3238])

    report = hearings.refresh_hearings(_city(), SINCE)

    assert _stored() == []
    assert _count("public_hearings") == 0
    assert report == hearings.HearingReport(matched=1, dated=0, undated=1, hearings=0, created=0, linked=0)


# --- refresh_recent ---------------------------------------------------------


def test_refresh_recent_does_nothing_for_a_city_without_the_flag():
    from docket.services import hearings

    mobile = _city("mobile")
    _item(_meeting(date.today() - timedelta(days=5), city=mobile), TITLES[62830])

    assert hearings.refresh_recent(mobile) is None
    assert _stored() == []


def test_refresh_recent_does_nothing_for_an_unknown_city():
    from docket.services import hearings

    assert hearings.refresh_recent(-1) is None


def test_refresh_recent_reads_the_last_120_days_of_a_flagged_city(monkeypatch):
    from docket.services import hearings

    assert hearings.RECENT_DAYS == 120
    today = date(2026, 11, 16)
    monkeypatch.setattr(hearings, "_today", lambda: today)
    inside = _item(_meeting(today - timedelta(days=120)), TITLES[62830])
    _item(_meeting(today - timedelta(days=121)), TITLES[62182])

    report = hearings.refresh_recent(_city())

    assert [h["items"] for h in _stored()] == [[inside]]
    assert report == hearings.HearingReport(matched=1, dated=1, undated=0, hearings=1, created=1, linked=1)


def test_refresh_recent_requires_the_flag_to_be_true(monkeypatch):
    from docket.services import hearings

    mobile = _city("mobile")
    _item(_meeting(date.today() - timedelta(days=5), city=mobile), TITLES[62830])
    with db_cursor() as cur:
        cur.execute("UPDATE municipalities SET metadata = metadata || '{\"coming_up\": false}'::jsonb WHERE id = %s", (mobile,))
    try:
        assert hearings.refresh_recent(mobile) is None
        with db_cursor() as cur:
            cur.execute("UPDATE municipalities SET metadata = metadata || '{\"coming_up\": \"true\"}'::jsonb WHERE id = %s", (mobile,))
        assert hearings.refresh_recent(mobile) is None
    finally:
        with db_cursor() as cur:
            cur.execute("UPDATE municipalities SET metadata = metadata - 'coming_up' WHERE id = %s", (mobile,))


# --- list_upcoming ----------------------------------------------------------


def test_list_upcoming_returns_a_hearing_with_its_items_oldest_meeting_first():
    from docket.enrichment.hearings import read_hearing
    from docket.services import hearings

    later_meeting = _meeting(OCT_26, agenda_url="https://example.test/agenda-b")
    later = _item(later_meeting, TITLES[62830])
    earlier_meeting = _meeting(OCT_13, agenda_url="https://example.test/agenda-a")
    earlier = _item(earlier_meeting, TITLES[62830])
    hearings.refresh_hearings(_city(), SINCE)

    listed = hearings.list_upcoming(_city(), NOV_17, NOV_17)

    assert len(listed) == 1
    hearing = listed[0]
    assert set(hearing) == {"id", "hearing_date", "kind", "subject", "property_count", "items"}
    assert hearing["id"] == _stored()[0]["id"]
    assert (hearing["hearing_date"], hearing["kind"], hearing["property_count"]) == (NOV_17, "vacation", None)
    assert hearing["subject"] == read_hearing(TITLES[62830]).subject
    assert hearing["items"] == [
        {"item_id": earlier, "meeting_id": earlier_meeting, "meeting_date": OCT_13, "agenda_url": "https://example.test/agenda-a"},
        {"item_id": later, "meeting_id": later_meeting, "meeting_date": OCT_26, "agenda_url": "https://example.test/agenda-b"},
    ]


def test_list_upcoming_is_bounded_by_hearing_date_and_city_and_ordered_by_date():
    from docket.services import hearings

    meeting = _meeting()
    _item(meeting, TITLES[63166])  # December 15
    _item(meeting, TITLES[63046])  # November 24
    _item(meeting, TITLES[62882])  # November 17, 212 lots
    _item(meeting, TITLES[63109])  # December 8, 136 lots
    hearings.refresh_hearings(_city(), SINCE)

    def dates(start, end, city=None):
        return [h["hearing_date"] for h in hearings.list_upcoming(city or _city(), start, end)]

    assert dates(NOV_17, date(2026, 12, 15)) == [NOV_17, date(2026, 11, 24), date(2026, 12, 8), date(2026, 12, 15)]
    assert dates(date(2026, 11, 18), date(2026, 12, 14)) == [date(2026, 11, 24), date(2026, 12, 8)]
    assert dates(NOV_17, date(2026, 12, 15), _city("mobile")) == []
    counts = {h["hearing_date"]: h["property_count"] for h in hearings.list_upcoming(_city(), NOV_17, date(2026, 12, 15))}
    assert counts[NOV_17] == 212 and counts[date(2026, 11, 24)] is None


@pytest.mark.parametrize("case", ["withdrawn", "hidden", "cancelled"])
def test_list_upcoming_leaves_out_a_hearing_with_no_visible_link(case):
    from docket.services import hearings

    meeting = _meeting(hidden=case == "hidden", title="CANCELLED Regular meeting" if case == "cancelled" else "Regular meeting")
    _item(meeting, TITLES[62830], status="withdrawn" if case == "withdrawn" else "completed")
    _item(_meeting(), TITLES[62182])  # a visible hearing of the same day
    hearings.refresh_hearings(_city(), SINCE)
    assert len(_stored()) == 2, "both are stored; visibility is the listing's"

    listed = hearings.list_upcoming(_city(), NOV_17, NOV_17)

    assert [h["subject"][:23] for h in listed] == ["to consider the closure"]


@pytest.mark.parametrize("case", ["withdrawn", "hidden", "cancelled"])
def test_list_upcoming_returns_only_the_visible_link_of_a_hearing(case):
    from docket.services import hearings

    unseen_meeting = _meeting(
        OCT_13, hidden=case == "hidden", title="Canceled Regular meeting" if case == "cancelled" else "Regular meeting"
    )
    _item(unseen_meeting, TITLES[62830], status="withdrawn" if case == "withdrawn" else "completed")
    seen = _item(_meeting(OCT_26), TITLES[62830])
    hearings.refresh_hearings(_city(), SINCE)
    assert len(_stored()[0]["items"]) == 2

    listed = hearings.list_upcoming(_city(), NOV_17, NOV_17)

    assert [[i["item_id"] for i in h["items"]] for h in listed] == [[seen]]


def test_list_upcoming_counts_an_item_with_no_processing_status_as_visible():
    from docket.services import hearings

    item = _item(_meeting(), TITLES[62830])
    with db_cursor() as cur:
        cur.execute("UPDATE agenda_items SET processing_status = NULL WHERE id = %s", (item,))
    hearings.refresh_hearings(_city(), SINCE)

    assert [[i["item_id"] for i in h["items"]] for h in hearings.list_upcoming(_city(), NOV_17, NOV_17)] == [[item]]


# --- rules pinned after the removal check ------------------------------------
# Plan `birmingham-coming-up`, M2: each test below fails when one clause of
# the service is taken out, and no test above it did.

# Two sentences that set a hearing of one day with one subject and read as
# different kinds: the kind is tested on the whole title, the key on the
# subject alone.
_PLAIN = "A Resolution setting a public hearing November 17, 2026, to consider the renewal of a franchise for a carriage service."
_BUDGETED = "A Resolution, there being funds in the budget, " + _PLAIN[len("A Resolution "):]


def test_find_readings_ignores_case_in_its_sql_test():
    from docket.services import hearings

    item = _item(_meeting(), TITLES[62830].replace("public hearing", "PUBLIC Hearing"))

    assert [r["item_id"] for r in hearings.find_readings(_city(), SINCE)] == [item]


def test_group_a_key_that_lies_inside_another_without_opening_it_stands_alone():
    from docket.enrichment.hearings import PREFIX_MIN, read_hearing
    from docket.services import hearings

    whole = TITLES[62830]
    inside = whole.replace("to consider the adoption of a resolution ", "")
    whole_key, inside_key = read_hearing(whole).subject_key, read_hearing(inside).subject_key
    assert inside_key in whole_key and not whole_key.startswith(inside_key) and len(inside_key) >= PREFIX_MIN
    assert read_hearing(inside).kind == read_hearing(whole).kind

    groups = hearings.group_readings([_row(1, whole), _row(2, inside)])

    assert sorted(g["item_ids"] for g in groups) == [[1], [2]]


def test_a_stored_hearing_of_another_kind_with_the_same_key_is_not_matched():
    from docket.enrichment.hearings import read_hearing
    from docket.services import hearings

    plain, budgeted = read_hearing(_PLAIN), read_hearing(_BUDGETED)
    assert (plain.kind, budgeted.kind) == ("other", "budget")
    assert plain.subject_key == budgeted.subject_key and plain.hearing_date == budgeted.hearing_date
    first = _item(_meeting(date(2026, 10, 6)), _PLAIN)
    hearings.refresh_hearings(_city(), SINCE)
    second = _item(_meeting(OCT_13), _BUDGETED)

    report = hearings.refresh_hearings(_city(), OCT_13)

    assert sorted((h["kind"], h["items"]) for h in _stored()) == [("budget", [second]), ("other", [first])]
    assert report.created == 1


def test_a_stored_hearing_of_another_date_with_the_same_key_is_not_matched():
    """The run loads the stored hearings of November 17 because another of its items sets one that day."""
    from docket.services import hearings

    moved = _PLAIN.replace("November 17, 2026", "November 24, 2026")
    first = _item(_meeting(date(2026, 10, 6)), _PLAIN)
    hearings.refresh_hearings(_city(), SINCE)
    meeting = _meeting(OCT_13)
    second = _item(meeting, moved)
    third = _item(meeting, TITLES[62182])

    report = hearings.refresh_hearings(_city(), OCT_13)

    assert sorted((h["hearing_date"], h["items"]) for h in _stored()) == [
        (NOV_17, [first]),
        (NOV_17, [third]),
        (date(2026, 11, 24), [second]),
    ]
    assert report.created == 2


def test_a_stored_short_key_is_taken_by_one_of_two_longer_groups_and_not_by_both():
    """A cut title was stored alone; the two whole titles it opens then arrive. One takes the stored hearing, the other is new."""
    from docket.enrichment.hearings import read_hearing
    from docket.services import hearings

    cut = _item(_meeting(date(2025, 11, 11)), CUT_1680)
    hearings.refresh_hearings(_city(), SINCE)
    cut_hearing = _stored()[0]["id"]
    meeting = _meeting(date(2025, 11, 18))
    a = _item(meeting, TITLES[1680])
    b = _item(meeting, TITLES[1681])

    report = hearings.refresh_hearings(_city(), date(2025, 11, 18))

    stored = _stored()
    assert sorted(h["items"] for h in stored) == [[cut, a], [b]]
    taken = next(h for h in stored if h["id"] == cut_hearing)
    assert taken["items"] == [cut, a], "the first group in order takes it"
    assert taken["subject_key"] == read_hearing(TITLES[1680]).subject_key
    assert report.created == 1


def test_a_stored_hearing_matched_exactly_is_not_also_given_a_short_key():
    """One whole title is stored; a second case and a title cut inside the case number then arrive. The cut title could be either's, so it is neither's, the stored one's included."""
    from docket.services import hearings

    a = _item(_meeting(date(2025, 11, 11)), TITLES[1680])
    hearings.refresh_hearings(_city(), SINCE)
    meeting = _meeting(date(2025, 11, 18))
    b = _item(meeting, TITLES[1681])
    cut = _item(meeting, CUT_1680)

    report = hearings.refresh_hearings(_city(), SINCE)

    assert sorted(h["items"] for h in _stored()) == [[a], [b], [cut]]
    assert report.created == 2


def test_a_run_leaves_another_citys_hearing_with_no_link_alone():
    from docket.services import hearings

    mobile = _city("mobile")
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO public_hearings (municipality_id, hearing_date, kind, subject, subject_key, rule_version)
               VALUES (%s, %s, 'other', 'HEARINGS_TEST_ unlinked', 'hearingstestunlinked', 1) RETURNING id""",
            (mobile, NOV_17),
        )
        unlinked = cur.fetchone()["id"]
    try:
        _item(_meeting(), TITLES[62830])
        hearings.refresh_hearings(_city(), SINCE)
        with db_cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM public_hearings WHERE id = %s", (unlinked,))
            assert cur.fetchone()["n"] == 1
        hearings.refresh_hearings(mobile, SINCE)
        with db_cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM public_hearings WHERE id = %s", (unlinked,))
            assert cur.fetchone()["n"] == 0, "its own city's run removes it"
    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM public_hearings WHERE subject = 'HEARINGS_TEST_ unlinked'")


def test_list_upcoming_is_in_date_order_whatever_order_the_hearings_were_stored_in():
    from docket.services import hearings

    _item(_meeting(OCT_13), TITLES[63108])  # December 8, stored first
    hearings.refresh_hearings(_city(), SINCE)
    _item(_meeting(OCT_26), TITLES[62830])  # November 17, stored second
    hearings.refresh_hearings(_city(), SINCE)
    by_id = [h["hearing_date"] for h in _stored()]
    assert by_id == [date(2026, 12, 8), NOV_17]

    listed = hearings.list_upcoming(_city(), NOV_17, date(2026, 12, 8))

    assert [h["hearing_date"] for h in listed] == [NOV_17, date(2026, 12, 8)]


def test_list_upcoming_keeps_each_hearings_items_together():
    """Two hearings of one day whose items' meetings interleave: two entries, not three."""
    from docket.services import hearings

    a1 = _item(_meeting(OCT_13), TITLES[62830])
    b = _item(_meeting(date(2026, 10, 20)), TITLES[62182])
    a2 = _item(_meeting(OCT_26), TITLES[62830])
    hearings.refresh_hearings(_city(), SINCE)

    listed = hearings.list_upcoming(_city(), NOV_17, NOV_17)

    assert [[i["item_id"] for i in h["items"]] for h in listed] == [[a1, a2], [b]]
