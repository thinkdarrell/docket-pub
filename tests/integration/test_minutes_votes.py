"""The service that reads a city's minutes files, pairs each to a meeting, and stores its votes.

`docket.services.minutes_votes`, plan `mobile-votes-from-minutes`, M3. No test
here reaches the city's site: the adapter is a list of files, and the pages of
each come from `tests/fixtures/mobile_minutes/` (the city's own text, cut down)
or from text written in the test in an invented style. The roster is the one
the migrations seed for Mobile. Every meeting a test builds has an external id
that begins `mv-test-`, every file an id that begins `mv-test-`; both are
deleted before and after each test, and Mobile's `adapter_config` is put back.

The service and `RawMinutesFile` are imported inside the tests and helpers, so
that before they exist every test fails on that import and the file collects.
"""

from __future__ import annotations

import json
from datetime import date

import psycopg2
import psycopg2.extras
import pytest

from docket.config import DATABASE_URL
from docket.db import db_cursor
from docket.models.protocol import RawMeeting
from tests.unit.test_mobile_minutes import load_pages

PREFIX = "mv-test-"
FLOOR = "2021-11-01"
DECLARED = "The vote was then announced by the City Clerk, whereupon the Presiding Officer declared the thing adopted."
MOTION = "Councilmember Alpha moved to adopt it, which was seconded by Councilmember Beta and the vote was as follows:"


# ---------------------------------------------------------------------------
# Seeding and reading back
# ---------------------------------------------------------------------------

def _delete_test_rows() -> None:
    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE external_id LIKE %s", (PREFIX + "%",))
        cur.execute("DELETE FROM minutes_files WHERE file_id LIKE %s", (PREFIX + "%",))


def _city_id(slug: str = "mobile") -> int:
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug = %s", (slug,))
        return cur.fetchone()["id"]


def _set_config(slug: str, **keys) -> None:
    """Merge keys into a city's adapter_config; a key given None is removed."""
    with db_cursor() as cur:
        cur.execute("SELECT adapter_config FROM municipalities WHERE slug = %s", (slug,))
        config = dict(cur.fetchone()["adapter_config"] or {})
        for key, value in keys.items():
            if value is None:
                config.pop(key, None)
            else:
                config[key] = value
        cur.execute("UPDATE municipalities SET adapter_config = %s WHERE slug = %s", (json.dumps(config), slug))


@pytest.fixture(autouse=True)
def mobile():
    """Mobile with a reader named and the floor set; its id. Everything is put back after."""
    _delete_test_rows()
    with db_cursor() as cur:
        cur.execute("SELECT adapter_config FROM municipalities WHERE slug = 'mobile'")
        before = cur.fetchone()["adapter_config"]
    _set_config("mobile", minutes_reader="mobile", backlog_floor=FLOOR)
    try:
        yield _city_id()
    finally:
        with db_cursor() as cur:
            cur.execute("UPDATE municipalities SET adapter_config = %s WHERE slug = 'mobile'", (json.dumps(before),))
        _delete_test_rows()


def _meeting(tag: str, day: date, *, slug: str = "mobile", minutes_url: str | None = None) -> int:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type, minutes_url) "
            "VALUES (%s, %s, 'City Council', %s, 'council', %s) RETURNING id",
            (_city_id(slug), PREFIX + tag, day, minutes_url),
        )
        return cur.fetchone()["id"]


def _item(meeting_id: int, tag: str, title: str, *, is_consent: bool = False) -> int:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO agenda_items (meeting_id, external_id, item_number, title, is_consent) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (meeting_id, tag, tag, title, is_consent),
        )
        return cur.fetchone()["id"]


def _file(tag: str, event: str, event_date: date = date(2026, 11, 3)):
    """A listed file: id `mv-test-<tag>`, on the event whose meeting is `mv-test-<event>`."""
    from docket.models.protocol import RawMinutesFile

    return RawMinutesFile(
        file_id=PREFIX + tag,
        url=_url(tag),
        event_external_id=PREFIX + event,
        event_date=event_date,
    )


def _url(tag: str) -> str:
    return f"https://city.invalid/files/{tag}"


def _text(heading: str | None, *votes: dict) -> list[str]:
    """One page of minutes in an invented style: a heading line and one block per vote."""
    lines = []
    if heading is not None:
        lines.append(f"MUNICIPAL BUILDING, MOBILE, ALABAMA, {heading}")
    lines.append("The Council met in the Auditorium.")
    for vote in votes:
        if vote.get("code"):
            lines.append(f"{vote.get('caption', 'A THING')}. The following resolution was introduced by Councilmember Alpha.")
            lines.append(f"RESOLUTION: {vote['code']}")
        lines.append(MOTION)
        lines.append(f"Ayes: {vote.get('ayes', 'Penn')}")
        lines.append(f"Nays: {vote.get('nays', 'None')}")
        if vote.get("abstain"):
            lines.append(f"Abstain: {vote['abstain']}")
        if vote.get("declared", True):
            lines.append(DECLARED)
    return ["\n".join(lines)]


class _Adapter:
    """What the service asks of an adapter: the listed files. It must not be asked to fetch."""

    def __init__(self, files):
        self.files = list(files)

    def listed_minutes_files(self):
        return list(self.files)

    def fetch_file(self, url):  # pragma: no cover - a test that reaches it has failed
        raise AssertionError(f"fetch_file({url!r}) was called although fetch_pages was given")


class _Pages:
    """`fetch_pages`: file id -> pages, or an exception to raise; records the ids asked for."""

    def __init__(self, by_tag: dict, on_fetch=None):
        self.by_file_id = {PREFIX + tag: value for tag, value in by_tag.items()}
        self.calls: list[str] = []
        self.on_fetch = on_fetch

    def __call__(self, file):
        self.calls.append(file.file_id)
        if self.on_fetch is not None:
            self.on_fetch(file, len(self.calls))
        value = self.by_file_id[file.file_id]
        if isinstance(value, Exception):
            raise value
        return value


def _run(city_id: int, files, pages, *, cap: int = 10, dry_run: bool = False):
    from docket.services.minutes_votes import read_listed

    return read_listed(city_id, _Adapter(files), cap=cap, dry_run=dry_run, fetch_pages=pages)


def _votes(meeting_id: int) -> list[dict]:
    with db_cursor() as cur:
        cur.execute("SELECT * FROM votes WHERE meeting_id = %s ORDER BY id", (meeting_id,))
        return [dict(r) for r in cur.fetchall()]


def _member_votes(vote_id: int) -> list[tuple[str, str, str | None]]:
    """(name as printed, position, the roster name it resolved to) in stored order."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT mv.member_name, mv.position, cm.name FROM member_votes mv "
            "LEFT JOIN council_members cm ON cm.id = mv.council_member_id WHERE mv.vote_id = %s ORDER BY mv.id",
            (vote_id,),
        )
        return [(r["member_name"], r["position"], r["name"]) for r in cur.fetchall()]


def _file_row(tag: str) -> dict | None:
    with db_cursor() as cur:
        cur.execute("SELECT * FROM minutes_files WHERE file_id = %s", (PREFIX + tag,))
        row = cur.fetchone()
        return dict(row) if row else None


def _minutes_url(meeting_id: int) -> str | None:
    with db_cursor() as cur:
        cur.execute("SELECT minutes_url FROM meetings WHERE id = %s", (meeting_id,))
        return cur.fetchone()["minutes_url"]


def _links(vote_id: int) -> list[dict]:
    with db_cursor() as cur:
        cur.execute("SELECT * FROM vote_agenda_items WHERE vote_id = %s ORDER BY id", (vote_id,))
        return [dict(r) for r in cur.fetchall()]


def _state() -> dict:
    """Everything the service can write, read whole."""
    out: dict = {}
    with db_cursor() as cur:
        for table in ("votes", "member_votes", "vote_agenda_items", "minutes_files"):
            cur.execute(f"SELECT * FROM {table} ORDER BY id")
            out[table] = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT id, minutes_url, updated_at FROM meetings ORDER BY id")
        out["meetings"] = [dict(r) for r in cur.fetchall()]
    return out


def _statuses(report) -> list[tuple[str, str, int]]:
    return [(o.file_id.removeprefix(PREFIX), o.status, o.votes) for o in report.files]


# ---------------------------------------------------------------------------
# Pairing and storing
# ---------------------------------------------------------------------------

def test_a_file_is_paired_to_the_one_meeting_its_first_page_dates_and_its_votes_are_stored(mobile):
    """The file of 2026-11-03, attached to another event, lands on the meeting of that date."""
    meeting = _meeting("e499", date(2026, 11, 3))
    other = _meeting("e500", date(2026, 11, 10))
    in_birmingham = _meeting("b1", date(2026, 11, 3), slug="birmingham")

    report = _run(mobile, [_file("3854", "e500")], _Pages({"3854": load_pages("mobile_2026-11-03.txt")}))

    assert report.waiting == 0
    [outcome] = report.files
    assert (outcome.file_id, outcome.event_external_id) == (PREFIX + "3854", PREFIX + "e500")
    assert (outcome.header_date, outcome.status, outcome.meeting_id) == (date(2026, 11, 3), "paired", meeting)
    assert (outcome.votes, outcome.error) == (7, None)

    assert _minutes_url(meeting) == _url("3854")
    assert _minutes_url(other) is None and _votes(other) == []
    assert _minutes_url(in_birmingham) is None and _votes(in_birmingham) == []

    votes = _votes(meeting)
    assert [v["external_id"] for v in votes] == [f"{PREFIX}e499-mv-{n}" for n in range(1, 8)]
    assert {v["source"] for v in votes} == {"minutes_text"}
    assert {v["minutes_reader"] for v in votes} == {"mobile"}
    assert [v["source_page"] for v in votes] == [2, 2, 5, 19, 25, 37, 38]
    assert [v["resolution_number"] for v in votes] == [
        None, None, "40-948-2026", None, "08-1180-2026", "41-1198-2026", None,
    ]

    third = votes[2]
    assert third["result"] == "passed"
    assert (third["yeas"], third["nays"], third["abstentions"]) == (7, 0, 0)
    assert (third["confidence"], third["needs_review"], third["review_reason"]) == ("high", False, None)
    assert third["caption"] == "DECLARE THE STRUCTURE AT 906 S. BROAD STREET A PUBLIC NUISANCE AND ORDER IT DEMOLISHED"
    assert third["motion_text"] == (
        "The resolution was read by the City Clerk, whereupon Councilmember Small moved to adopt the resolution, "
        "which was seconded by Councilmember Ingram and the vote was as follows:"
    )
    assert third["declared_text"] == "the resolution adopted"
    assert third["raw_text"].startswith("The resolution was read by the City Clerk")
    assert third["raw_text"].endswith("the resolution adopted.")
    assert third["video_timestamp"] is None and third["header_result"] is None
    assert _member_votes(third["id"]) == [
        ("Penn", "yea", "Cory Penn"), ("Ingram", "yea", "Samantha Ingram"), ("Small", "yea", "C.J. Small"),
        ("Reynolds", "yea", "Ben Reynolds"), ("Fleming", "yea", "Beau Fleming"), ("Woods", "yea", "Josh Woods"),
        ("Gregory", "yea", "Gina Gregory"),
    ]

    row = _file_row("3854")
    assert (row["municipality_id"], row["url"], row["event_external_id"]) == (mobile, _url("3854"), PREFIX + "e500")
    assert (row["status"], row["meeting_id"], row["header_date"]) == ("paired", meeting, date(2026, 11, 3))
    assert (row["page_count"], row["votes_stored"], row["reader_version"]) == (38, 7, 1)
    assert (row["attempts"], row["error"]) == (1, None)


def test_every_position_is_stored_and_a_flagged_vote_is_medium_and_marked(mobile):
    """Nay, abstain and absent are stored beside yea; the count columns are the lengths of the lists."""
    meeting = _meeting("e1", date(2021, 11, 23))
    pages = load_pages("mobile_2021-11-23.txt")
    pages.append("\n".join([
        MOTION, "Ayes: Penn, Carroll, and Small", "Nays: Reynolds and Gregory", "Abstain: Jones", DECLARED,
        MOTION, "Ayes: Penn", "Nays: None",
    ]))

    report = _run(mobile, [_file("160", "e1")], _Pages({"160": pages}))

    assert _statuses(report) == [("160", "paired", 3)]
    first, second, third = _votes(meeting)
    assert _member_votes(first["id"]) == [
        ("Penn", "yea", "Cory Penn"), ("Carroll", "yea", "William Carroll"), ("Small", "yea", "C.J. Small"),
        ("Reynolds", "yea", "Ben Reynolds"), ("Jones", "yea", "Scott Jones"), ("Gregory", "yea", "Gina Gregory"),
        ("Daves", "absent", "Joel Daves"),
    ]
    assert (second["yeas"], second["nays"], second["abstentions"]) == (3, 2, 1)
    assert _member_votes(second["id"]) == [
        ("Penn", "yea", "Cory Penn"), ("Carroll", "yea", "William Carroll"), ("Small", "yea", "C.J. Small"),
        ("Reynolds", "nay", "Ben Reynolds"), ("Gregory", "nay", "Gina Gregory"),
        ("Jones", "abstain", "Scott Jones"), ("Daves", "absent", "Joel Daves"),
    ]
    assert (second["confidence"], second["needs_review"]) == ("high", False)
    assert (third["result"], third["declared_text"]) == ("unknown", None)
    assert (third["confidence"], third["needs_review"], third["review_reason"]) == (
        "medium", True, "declaration_not_read",
    )
    assert third["external_id"] == PREFIX + "e1-mv-3"
    assert third["source_page"] == 3 and third["caption"] is None and third["resolution_number"] is None


def test_member_votes_are_resolved_against_the_roster_on_the_meeting_date(mobile):
    """`Scott` and `Jones` are one member in 2021; a name not seated that day is kept as printed."""
    meeting = _meeting("e185", date(2021, 11, 9))
    pages = _text("NOVEMBER 9, 2021", {"ayes": "Penn, Scott, Ingram, and Richardson"}, {"ayes": "Penn and Jones"})

    _run(mobile, [_file("185", "e185")], _Pages({"185": pages}))

    first, second = _votes(meeting)
    assert _member_votes(first["id"]) == [
        ("Penn", "yea", "Cory Penn"), ("Scott", "yea", "Scott Jones"),
        ("Ingram", "yea", None), ("Richardson", "yea", None),
    ]
    assert _member_votes(second["id"]) == [("Penn", "yea", "Cory Penn"), ("Jones", "yea", "Scott Jones")]


def test_a_file_with_no_heading_date_is_not_minutes_and_stores_nothing(mobile):
    meeting = _meeting("e1", date(2022, 10, 25))

    report = _run(mobile, [_file("449", "e1")], _Pages({"449": load_pages("not_minutes_letter.txt")}))

    [outcome] = report.files
    assert (outcome.status, outcome.header_date, outcome.meeting_id, outcome.votes) == ("not_minutes", None, None, 0)
    assert _votes(meeting) == [] and _minutes_url(meeting) is None
    row = _file_row("449")
    assert (row["status"], row["meeting_id"], row["header_date"]) == ("not_minutes", None, None)
    assert (row["page_count"], row["votes_stored"], row["attempts"], row["error"]) == (1, 0, 1, None)


def test_a_file_dated_before_the_floor_is_no_meeting(mobile):
    """The floor decides, not the absence of a meeting: the same file pairs once the floor is gone."""
    before = _meeting("e0", date(2021, 9, 14))
    on_the_floor = _meeting("e1", date(2021, 11, 1))
    files = [_file("433", "e9"), _file("434", "e9")]
    pages = {"433": _text("SEPTEMBER 14, 2021", {}), "434": _text("NOVEMBER 1, 2021", {})}

    report = _run(mobile, files, _Pages(pages))

    assert sorted(_statuses(report)) == [("433", "no_meeting", 0), ("434", "paired", 1)]
    assert _votes(before) == [] and _minutes_url(before) is None
    assert len(_votes(on_the_floor)) == 1
    row = _file_row("433")
    assert (row["status"], row["meeting_id"], row["header_date"]) == ("no_meeting", None, date(2021, 9, 14))
    assert (row["votes_stored"], row["page_count"]) == (0, 1)

    _delete_test_rows()
    before = _meeting("e0", date(2021, 9, 14))
    _set_config("mobile", backlog_floor=None)
    report = _run(mobile, files[:1], _Pages(pages))
    assert _statuses(report) == [("433", "paired", 1)]
    assert len(_votes(before)) == 1


def test_a_date_with_no_meeting_or_two_is_no_meeting(mobile):
    """Only this city's meetings count, and exactly one is asked for."""
    twin_a = _meeting("e1", date(2026, 12, 22))
    twin_b = _meeting("e2", date(2026, 12, 22))
    elsewhere = _meeting("b1", date(2026, 12, 29), slug="birmingham")
    here = _meeting("e3", date(2027, 1, 5))
    also_elsewhere = _meeting("b2", date(2027, 1, 5), slug="birmingham")
    files = [_file("two", "e1"), _file("none", "e1"), _file("one", "e1")]
    pages = {
        "two": _text("DECEMBER 22, 2026", {}),
        "none": _text("DECEMBER 29, 2026", {}),
        "one": _text("JANUARY 5, 2027", {}),
    }

    report = _run(mobile, files, _Pages(pages))

    assert sorted(_statuses(report)) == [("none", "no_meeting", 0), ("one", "paired", 1), ("two", "no_meeting", 0)]
    for meeting in (twin_a, twin_b, elsewhere, also_elsewhere):
        assert _votes(meeting) == [] and _minutes_url(meeting) is None
    assert len(_votes(here)) == 1
    assert [o.meeting_id for o in report.files if o.status == "no_meeting"] == [None, None]
    assert _file_row("two")["header_date"] == date(2026, 12, 22)


def test_a_second_file_for_a_paired_meeting_is_superseded(mobile):
    """Neither file is on the meeting's own event, so the first one read keeps the meeting."""
    meeting = _meeting("e1", date(2022, 3, 15))
    first = _file("211", "e7")
    second = _file("625", "e8")
    pages = _Pages({
        "211": _text("MARCH 15, 2022", {"ayes": "Penn"}, {"ayes": "Small"}),
        "625": _text("MARCH 15, 2022", {"ayes": "Gregory"}),
    })

    assert _statuses(_run(mobile, [first], pages)) == [("211", "paired", 2)]
    kept = [v["id"] for v in _votes(meeting)]
    report = _run(mobile, [first, second], pages)

    [outcome] = report.files
    assert (outcome.file_id, outcome.status, outcome.votes) == (PREFIX + "625", "superseded", 0)
    assert (outcome.header_date, outcome.meeting_id) == (date(2022, 3, 15), meeting)
    assert [v["id"] for v in _votes(meeting)] == kept
    assert _minutes_url(meeting) == _url("211")
    assert _file_row("211")["status"] == "paired"
    row = _file_row("625")
    assert (row["status"], row["meeting_id"], row["header_date"], row["votes_stored"]) == (
        "superseded", meeting, date(2022, 3, 15), 0,
    )


def test_a_file_on_the_meetings_own_event_replaces_the_first_files_votes(mobile):
    """And once it holds the meeting, a later file on another event does not take it back."""
    meeting = _meeting("e1", date(2022, 3, 15))
    first, own, third = _file("211", "e7"), _file("625", "e1"), _file("999", "e7")
    pages = _Pages({
        "211": _text("MARCH 15, 2022", {"ayes": "Penn"}, {"ayes": "Small"}),
        "625": _text("MARCH 15, 2022", {"ayes": "Gregory", "code": "40-100-2022"}),
        "999": _text("MARCH 15, 2022", {"ayes": "Daves"}),
    })

    _run(mobile, [first], pages)
    old = _votes(meeting)
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO votes (meeting_id, result, source) VALUES (%s, 'passed', 'video_ocr') RETURNING id", (meeting,))
        from_video = cur.fetchone()["id"]
    report = _run(mobile, [first, own], pages)

    assert _statuses(report) == [("625", "paired", 1)]
    [vote] = [v for v in _votes(meeting) if v["id"] != from_video]
    assert [v["id"] for v in _votes(meeting) if v["minutes_reader"] is None] == [from_video]
    assert vote["id"] not in [v["id"] for v in old]
    assert (vote["external_id"], vote["resolution_number"]) == (PREFIX + "e1-mv-1", "40-100-2022")
    assert _member_votes(vote["id"]) == [("Gregory", "yea", "Gina Gregory")]
    assert _member_votes(old[0]["id"]) == []
    assert _minutes_url(meeting) == _url("625")
    assert (_file_row("211")["status"], _file_row("211")["meeting_id"]) == ("superseded", meeting)
    assert (_file_row("625")["status"], _file_row("625")["votes_stored"]) == ("paired", 1)

    assert _statuses(_run(mobile, [first, own, third], pages)) == [("999", "superseded", 0)]
    assert [v["id"] for v in _votes(meeting)] == [from_video, vote["id"]]
    assert _minutes_url(meeting) == _url("625")


def test_a_pairing_supersedes_any_other_paired_row_of_its_meeting(mobile):
    """A paired row the listing no longer holds still gives way; a meeting never has two."""
    meeting = _meeting("e1", date(2022, 3, 15))
    untouched = _meeting("e2", date(2022, 3, 22))
    with db_cursor() as cur:
        for tag, target in (("gone", meeting), ("other", untouched)):
            cur.execute(
                "INSERT INTO minutes_files (municipality_id, file_id, url, event_external_id, status, meeting_id, "
                "reader_version) VALUES (%s, %s, %s, %s, 'paired', %s, 1)",
                (mobile, PREFIX + tag, _url(tag), PREFIX + "e7", target),
            )

    report = _run(mobile, [_file("625", "e1")], _Pages({"625": _text("MARCH 15, 2022", {})}))

    assert _statuses(report) == [("625", "paired", 1)]
    assert (_file_row("gone")["status"], _file_row("gone")["meeting_id"]) == ("superseded", meeting)
    assert _file_row("other")["status"] == "paired"
    assert _file_row("625")["status"] == "paired"


def test_a_file_that_is_not_minutes_clears_the_link_that_named_it(mobile):
    """So do a file with no meeting and a superseded one; only this city, only that address."""
    paired = _meeting("e1", date(2022, 3, 15))
    held_letter = _meeting("e2", date(2024, 10, 22), minutes_url=_url("869"))
    held_undated = _meeting("e3", date(2024, 10, 29), minutes_url=_url("nowhere"))
    held_second = _meeting("e4", date(2024, 11, 5), minutes_url=_url("625"))
    keeps_its_own = _meeting("e5", date(2024, 11, 12), minutes_url=_url("unread"))
    in_birmingham = _meeting("b1", date(2024, 10, 22), slug="birmingham", minutes_url=_url("869"))
    files = [
        _file("211", "e7", date(2026, 1, 5)), _file("625", "e8", date(2026, 1, 4)),
        _file("869", "e2", date(2026, 1, 3)), _file("nowhere", "e3", date(2026, 1, 2)),
    ]
    pages = _Pages({
        "211": _text("MARCH 15, 2022", {}),
        "625": _text("MARCH 15, 2022", {}),
        "869": load_pages("not_minutes_agenda.txt"),
        "nowhere": _text("JULY 4, 2023", {}),
    })

    report = _run(mobile, files, pages)

    assert _statuses(report) == [
        ("211", "paired", 1), ("625", "superseded", 0), ("869", "not_minutes", 0), ("nowhere", "no_meeting", 0),
    ]
    assert _minutes_url(paired) == _url("211")
    assert _minutes_url(held_letter) is None
    assert _minutes_url(held_undated) is None
    assert _minutes_url(held_second) is None
    assert _minutes_url(keeps_its_own) == _url("unread")
    assert _minutes_url(in_birmingham) == _url("869")


# ---------------------------------------------------------------------------
# Which files a run reads
# ---------------------------------------------------------------------------

def test_a_fetch_that_raises_is_an_error_and_is_tried_again_until_three(mobile):
    """The run goes on past it; the fourth run does not ask for the file."""
    meeting = _meeting("e1", date(2022, 3, 15))
    files = [_file("bad", "e9", date(2026, 1, 2)), _file("211", "e1", date(2026, 1, 1))]
    pages = _Pages({"bad": RuntimeError("the city answered 503"), "211": _text("MARCH 15, 2022", {})})

    report = _run(mobile, files, pages)

    assert _statuses(report) == [("bad", "error", 0), ("211", "paired", 1)]
    bad = report.files[0]
    assert (bad.error, bad.header_date, bad.meeting_id) == ("the city answered 503", None, None)
    assert report.files[1].error is None
    row = _file_row("bad")
    assert (row["status"], row["attempts"], row["error"]) == ("error", 1, "the city answered 503")
    assert (row["meeting_id"], row["header_date"], row["page_count"], row["votes_stored"]) == (None, None, None, 0)
    assert (row["url"], row["event_external_id"], row["reader_version"]) == (_url("bad"), PREFIX + "e9", 1)
    assert len(_votes(meeting)) == 1

    assert _statuses(_run(mobile, files, pages)) == [("bad", "error", 0)]
    assert _file_row("bad")["attempts"] == 2
    assert _statuses(_run(mobile, files, pages)) == [("bad", "error", 0)]
    assert _file_row("bad")["attempts"] == 3
    assert pages.calls == [PREFIX + "bad", PREFIX + "211", PREFIX + "bad", PREFIX + "bad"]

    report = _run(mobile, files, pages)
    assert report.files == [] and report.waiting == 0
    assert len(pages.calls) == 4
    assert _file_row("bad")["attempts"] == 3


def test_a_file_that_failed_and_then_reads_is_stored_with_its_attempts(mobile):
    meeting = _meeting("e1", date(2022, 3, 15))
    files = [_file("211", "e1")]

    _run(mobile, files, _Pages({"211": ValueError()}))
    row = _file_row("211")
    assert (row["status"], row["attempts"], row["error"]) == ("error", 1, "ValueError")

    from docket.models.protocol import RawMinutesFile

    moved = RawMinutesFile(PREFIX + "211", _url("211-moved"), PREFIX + "e5", date(2026, 11, 3))
    report = _run(mobile, [moved], _Pages({"211": _text("MARCH 15, 2022", {})}))

    assert _statuses(report) == [("211", "paired", 1)]
    first_read_at = row["read_at"]
    row = _file_row("211")
    assert (row["status"], row["attempts"], row["error"], row["meeting_id"]) == ("paired", 2, None, meeting)
    assert (row["url"], row["event_external_id"]) == (_url("211-moved"), PREFIX + "e5")
    assert row["read_at"] > first_read_at
    assert _minutes_url(meeting) == _url("211-moved")


def test_a_second_run_with_nothing_new_reads_nothing_and_writes_nothing(mobile):
    _meeting("e1", date(2022, 3, 15))
    files = [_file("211", "e1"), _file("449", "e1"), _file("nowhere", "e1")]
    pages = _Pages({
        "211": _text("MARCH 15, 2022", {}),
        "449": load_pages("not_minutes_letter.txt"),
        "nowhere": _text("JULY 4, 2023", {}),
    })
    first = _run(mobile, files, pages)
    assert sorted(_statuses(first)) == [("211", "paired", 1), ("449", "not_minutes", 0), ("nowhere", "no_meeting", 0)]
    before = _state()
    asked = len(pages.calls)

    report = _run(mobile, files, pages)

    assert report.files == [] and report.waiting == 0
    assert len(pages.calls) == asked
    assert _state() == before


def test_at_most_cap_files_are_read_newest_event_first(mobile):
    files = [
        _file("old", "e1", date(2024, 1, 2)), _file("new", "e2", date(2026, 1, 2)),
        _file("mid", "e3", date(2025, 1, 2)),
    ]
    pages = _Pages({tag: _text("JULY 4, 2023", {}) for tag in ("old", "new", "mid")})

    nothing = _run(mobile, files, pages, cap=0)
    assert (nothing.files, nothing.waiting, pages.calls) == ([], 3, [])

    report = _run(mobile, files, pages, cap=2)
    assert _statuses(report) == [("new", "no_meeting", 0), ("mid", "no_meeting", 0)]
    assert report.waiting == 1
    assert pages.calls == [PREFIX + "new", PREFIX + "mid"]
    assert _file_row("old") is None

    report = _run(mobile, files, pages, cap=2)
    assert _statuses(report) == [("old", "no_meeting", 0)] and report.waiting == 0


def test_a_reread_under_a_newer_version_starts_its_attempts_again(mobile, monkeypatch):
    """Three failures under version 1 end the tries; version 2 reads the file again, from one."""
    from docket.analysis import mobile_minutes

    meeting = _meeting("e1", date(2022, 3, 15))
    files = [_file("211", "e1"), _file("625", "e9")]
    failing = _Pages({"211": RuntimeError("no"), "625": RuntimeError("no")})
    for _ in range(3):
        _run(mobile, files, failing)
    assert (_file_row("211")["attempts"], _file_row("625")["attempts"]) == (3, 3)
    assert _run(mobile, files, failing).files == []

    monkeypatch.setattr(mobile_minutes, "READER_VERSION", 2)
    report = _run(mobile, files, _Pages({"211": _text("MARCH 15, 2022", {}), "625": RuntimeError("still no")}))

    assert sorted(_statuses(report)) == [("211", "paired", 1), ("625", "error", 0)]
    row = _file_row("211")
    assert (row["status"], row["attempts"], row["error"], row["reader_version"]) == ("paired", 1, None, 2)
    assert row["meeting_id"] == meeting
    row = _file_row("625")
    assert (row["status"], row["attempts"], row["error"], row["reader_version"]) == ("error", 1, "still no", 2)

    report = _run(mobile, files, _Pages({"625": RuntimeError("still no")}))
    assert _statuses(report) == [("625", "error", 0)]
    assert _file_row("625")["attempts"] == 2


def test_a_paired_file_read_again_under_a_newer_version_pairs_again_and_replaces_its_votes(mobile, monkeypatch):
    from docket.analysis import mobile_minutes

    meeting = _meeting("e1", date(2022, 3, 15))
    files = [_file("211", "e7")]
    _run(mobile, files, _Pages({"211": _text("MARCH 15, 2022", {"ayes": "Penn"}, {"ayes": "Small"})}))
    old = [v["id"] for v in _votes(meeting)]

    monkeypatch.setattr(mobile_minutes, "READER_VERSION", 2)
    report = _run(mobile, files, _Pages({"211": _text("MARCH 15, 2022", {"ayes": "Gregory"})}))

    assert _statuses(report) == [("211", "paired", 1)]
    [vote] = _votes(meeting)
    assert vote["id"] not in old and vote["external_id"] == PREFIX + "e1-mv-1"
    row = _file_row("211")
    assert (row["status"], row["reader_version"], row["votes_stored"], row["attempts"]) == ("paired", 2, 1, 1)
    assert _minutes_url(meeting) == _url("211")


def test_a_file_that_no_longer_pairs_takes_its_votes_and_its_link_with_it(mobile, monkeypatch):
    """Read again under a newer version, the date now has two meetings: no vote stays without its file."""
    from docket.analysis import mobile_minutes

    meeting = _meeting("e1", date(2022, 3, 15))
    other = _meeting("e2", date(2022, 3, 22))
    files = [_file("211", "e7"), _file("300", "e7")]
    pages = _Pages({"211": _text("MARCH 15, 2022", {}), "300": _text("MARCH 22, 2022", {})})
    _run(mobile, files, pages)
    assert len(_votes(meeting)) == 1 and len(_votes(other)) == 1

    _meeting("e3", date(2022, 3, 15))
    monkeypatch.setattr(mobile_minutes, "READER_VERSION", 2)
    report = _run(mobile, files, pages)

    assert sorted(_statuses(report)) == [("211", "no_meeting", 0), ("300", "paired", 1)]
    assert _votes(meeting) == [] and _minutes_url(meeting) is None
    assert len(_votes(other)) == 1 and _minutes_url(other) == _url("300")
    assert (_file_row("211")["status"], _file_row("211")["meeting_id"]) == ("no_meeting", None)


def test_a_file_that_now_names_another_meeting_moves_its_votes_and_its_link(mobile, monkeypatch):
    """Read again under a newer version the heading gives another date: the first meeting keeps nothing of it."""
    from docket.analysis import mobile_minutes

    was = _meeting("e1", date(2022, 3, 15))
    now = _meeting("e2", date(2022, 3, 22))
    files = [_file("211", "e7")]
    _run(mobile, files, _Pages({"211": _text("MARCH 15, 2022", {})}))
    assert len(_votes(was)) == 1 and _minutes_url(was) == _url("211")

    monkeypatch.setattr(mobile_minutes, "READER_VERSION", 2)
    report = _run(mobile, files, _Pages({"211": _text("MARCH 22, 2022", {}, {}) + [""]}))

    assert _statuses(report) == [("211", "paired", 2)]
    assert _votes(was) == [] and _minutes_url(was) is None
    assert len(_votes(now)) == 2 and _minutes_url(now) == _url("211")
    row = _file_row("211")
    assert (row["meeting_id"], row["header_date"], row["page_count"]) == (now, date(2022, 3, 22), 2)


def test_a_superseded_file_that_no_longer_names_the_meeting_leaves_the_paired_files_votes(mobile, monkeypatch):
    """Only the file that holds a meeting takes votes with it; a row that merely names the meeting does not."""
    from docket.analysis import mobile_minutes

    meeting = _meeting("e1", date(2022, 3, 15))
    holder, second = _file("211", "e1"), _file("625", "e8")
    _run(mobile, [holder, second], _Pages({"211": _text("MARCH 15, 2022", {}), "625": _text("MARCH 15, 2022", {})}))
    assert (_file_row("211")["status"], _file_row("625")["status"]) == ("paired", "superseded")
    kept = [v["id"] for v in _votes(meeting)]

    monkeypatch.setattr(mobile_minutes, "READER_VERSION", 2)
    report = _run(mobile, [second], _Pages({"625": _text("JULY 4, 2023", {})}))

    assert _statuses(report) == [("625", "no_meeting", 0)]
    assert [v["id"] for v in _votes(meeting)] == kept
    assert _minutes_url(meeting) == _url("211")


def test_a_files_votes_and_its_member_votes_are_two_insert_statements(mobile, monkeypatch):
    """Seven votes and forty-nine member votes go in as one statement each, not one a row."""
    real = psycopg2.extras.execute_values
    sent: list[tuple[int, int]] = []

    def counting(cur, sql, argslist, template=None, page_size=100, fetch=False):
        sent.append((len(argslist), page_size))
        return real(cur, sql, argslist, template=template, page_size=page_size, fetch=fetch)

    monkeypatch.setattr(psycopg2.extras, "execute_values", counting)
    _meeting("e499", date(2026, 11, 3))

    _run(mobile, [_file("3854", "e499")], _Pages({"3854": load_pages("mobile_2026-11-03.txt")}))

    assert [rows for rows, _ in sent] == [7, 49]
    assert all(page_size >= rows for rows, page_size in sent)


def test_a_minutes_file_with_no_vote_is_paired_and_gives_its_meeting_the_link(mobile):
    meeting = _meeting("e1", date(2022, 3, 15))

    report = _run(mobile, [_file("211", "e7")], _Pages({"211": _text("MARCH 15, 2022")}))

    assert _statuses(report) == [("211", "paired", 0)]
    assert _votes(meeting) == [] and _minutes_url(meeting) == _url("211")
    assert (_file_row("211")["status"], _file_row("211")["votes_stored"]) == ("paired", 0)


def test_only_a_paired_row_holds_a_meeting(mobile):
    """A superseded or failed row that names the meeting does not keep another file from it."""
    meeting = _meeting("e1", date(2022, 3, 15))
    with db_cursor() as cur:
        for tag, status in (("lost", "superseded"), ("failed", "error")):
            cur.execute(
                "INSERT INTO minutes_files (municipality_id, file_id, url, event_external_id, status, meeting_id, "
                "reader_version, attempts) VALUES (%s, %s, %s, %s, %s, %s, 1, 3)",
                (mobile, PREFIX + tag, _url(tag), PREFIX + "e7", status, meeting),
            )

    report = _run(mobile, [_file("211", "e7")], _Pages({"211": _text("MARCH 15, 2022", {})}))

    assert _statuses(report) == [("211", "paired", 1)]
    assert (_file_row("lost")["status"], _file_row("failed")["status"]) == ("superseded", "error")


def test_a_failed_reread_leaves_what_the_file_stored(mobile, monkeypatch):
    """A fetch that fails says nothing about the file, so the meeting keeps its votes and the row its pairing."""
    from docket.analysis import mobile_minutes

    meeting = _meeting("e1", date(2022, 3, 15))
    files = [_file("211", "e7")]
    _run(mobile, files, _Pages({"211": _text("MARCH 15, 2022", {})}))
    kept = [v["id"] for v in _votes(meeting)]

    monkeypatch.setattr(mobile_minutes, "READER_VERSION", 2)
    report = _run(mobile, files, _Pages({"211": RuntimeError("no")}))

    [outcome] = report.files
    assert (outcome.status, outcome.error, outcome.votes) == ("error", "no", 0)
    assert (outcome.meeting_id, outcome.header_date) == (meeting, date(2022, 3, 15))
    assert [v["id"] for v in _votes(meeting)] == kept
    assert _minutes_url(meeting) == _url("211")
    row = _file_row("211")
    assert (row["status"], row["attempts"], row["error"], row["reader_version"]) == ("error", 1, "no", 2)
    assert (row["meeting_id"], row["header_date"], row["page_count"], row["votes_stored"]) == (
        meeting, date(2022, 3, 15), 1, 1,
    )


def test_a_file_that_pairs_to_another_meeting_clears_its_address_from_the_meeting_that_listed_it(mobile):
    """The listing gave the file to its event's meeting; its heading dates another. One meeting links it, not two."""
    listed_on = _meeting("e1", date(2022, 3, 22), minutes_url=_url("211"))
    dated = _meeting("e2", date(2022, 3, 15))
    elsewhere = _meeting("b1", date(2022, 3, 22), slug="birmingham", minutes_url=_url("211"))

    report = _run(mobile, [_file("211", "e1")], _Pages({"211": _text("MARCH 15, 2022", {})}))

    assert _statuses(report) == [("211", "paired", 1)]
    assert _file_row("211")["meeting_id"] == dated
    assert _minutes_url(dated) == _url("211")
    assert _minutes_url(listed_on) is None
    assert _minutes_url(elsewhere) == _url("211")  # another city's meeting is not this city's to clear


def test_a_failed_reread_and_then_a_read_that_no_longer_pairs_takes_the_votes_and_the_link(mobile, monkeypatch):
    """The row is `error` between the two, and still holds its meeting: the votes do not outlast the file."""
    from docket.analysis import mobile_minutes

    meeting = _meeting("e1", date(2022, 3, 15))
    files = [_file("211", "e7")]
    _run(mobile, files, _Pages({"211": _text("MARCH 15, 2022", {})}))
    monkeypatch.setattr(mobile_minutes, "READER_VERSION", 2)
    _run(mobile, files, _Pages({"211": RuntimeError("no")}))
    assert _file_row("211")["status"] == "error" and len(_votes(meeting)) == 1

    report = _run(mobile, files, _Pages({"211": _text(None, {})}))

    assert _statuses(report) == [("211", "not_minutes", 0)]
    assert _votes(meeting) == [] and _minutes_url(meeting) is None
    row = _file_row("211")
    assert (row["status"], row["meeting_id"], row["votes_stored"]) == ("not_minutes", None, 0)


def test_a_failed_reread_and_then_a_read_that_names_another_meeting_moves_the_votes_and_the_link(mobile, monkeypatch):
    from docket.analysis import mobile_minutes

    was = _meeting("e1", date(2022, 3, 15))
    now = _meeting("e2", date(2022, 3, 22))
    files = [_file("211", "e7")]
    _run(mobile, files, _Pages({"211": _text("MARCH 15, 2022", {})}))
    monkeypatch.setattr(mobile_minutes, "READER_VERSION", 2)
    _run(mobile, files, _Pages({"211": RuntimeError("no")}))

    report = _run(mobile, files, _Pages({"211": _text("MARCH 22, 2022", {}, {})}))

    assert _statuses(report) == [("211", "paired", 2)]
    assert _votes(was) == [] and _minutes_url(was) is None
    assert len(_votes(now)) == 2 and _minutes_url(now) == _url("211")


def test_a_failed_row_whose_meeting_another_file_has_taken_takes_nothing_with_it(mobile, monkeypatch):
    """An `error` row holds its meeting only while the meeting's link is still its address."""
    from docket.analysis import mobile_minutes

    meeting = _meeting("e1", date(2022, 3, 15))
    first, taker = _file("211", "e7"), _file("625", "e1")
    _run(mobile, [first], _Pages({"211": _text("MARCH 15, 2022", {})}))
    monkeypatch.setattr(mobile_minutes, "READER_VERSION", 2)
    _run(mobile, [first], _Pages({"211": RuntimeError("no")}))
    _run(mobile, [taker], _Pages({"625": _text("MARCH 15, 2022", {}, {})}))
    assert (_file_row("211")["status"], _file_row("625")["status"]) == ("error", "paired")
    kept = [v["id"] for v in _votes(meeting)]
    assert len(kept) == 2

    report = _run(mobile, [first], _Pages({"211": _text(None, {})}))

    assert _statuses(report) == [("211", "not_minutes", 0)]
    assert [v["id"] for v in _votes(meeting)] == kept
    assert _minutes_url(meeting) == _url("625")


def test_two_failed_rows_name_a_meeting_and_only_the_one_that_held_it_takes_its_votes(mobile, monkeypatch):
    """The holder and a superseded file both fail a re-read; the superseded one, read later, deletes nothing."""
    from docket.analysis import mobile_minutes

    meeting = _meeting("e1", date(2022, 3, 15))
    holder, second = _file("211", "e1"), _file("625", "e8")
    _run(mobile, [holder, second], _Pages({"211": _text("MARCH 15, 2022", {}), "625": _text("MARCH 15, 2022", {})}))
    monkeypatch.setattr(mobile_minutes, "READER_VERSION", 2)
    _run(mobile, [holder, second], _Pages({"211": RuntimeError("no"), "625": RuntimeError("no")}))
    assert (_file_row("211")["status"], _file_row("625")["status"]) == ("error", "error")
    kept = [v["id"] for v in _votes(meeting)]

    report = _run(mobile, [second], _Pages({"625": _text(None, {})}))

    assert _statuses(report) == [("625", "not_minutes", 0)]
    assert [v["id"] for v in _votes(meeting)] == kept
    assert _minutes_url(meeting) == _url("211")


def test_without_fetch_pages_the_adapter_fetches_and_the_reader_pages(mobile, monkeypatch):
    from docket.analysis import mobile_minutes
    from docket.services.minutes_votes import read_listed

    meeting = _meeting("e1", date(2022, 3, 15))
    asked: list[str] = []

    class Adapter(_Adapter):
        def fetch_file(self, url):
            asked.append(url)
            return b"%PDF-the bytes"

    monkeypatch.setattr(
        mobile_minutes, "pages_from_pdf",
        lambda pdf_bytes: _text("MARCH 15, 2022", {}) if pdf_bytes == b"%PDF-the bytes" else [],
    )

    report = read_listed(mobile, Adapter([_file("211", "e1")]), cap=10)

    assert _statuses(report) == [("211", "paired", 1)]
    assert asked == [_url("211")]
    assert len(_votes(meeting)) == 1


def test_a_city_that_names_no_reader_is_refused(mobile):
    _set_config("mobile", minutes_reader=None)
    pages = _Pages({"211": _text("MARCH 15, 2022", {})})

    with pytest.raises(ValueError, match="minutes_reader"):
        _run(mobile, [_file("211", "e1")], pages)

    assert pages.calls == [] and _file_row("211") is None


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

def test_a_dry_run_leaves_every_table_as_it_was(mobile):
    """It reports what a real run would store, having run the statements, and keeps none of it."""
    meeting = _meeting("e499", date(2026, 11, 3))
    held = _meeting("e2", date(2024, 10, 22), minutes_url=_url("869"))
    files = [
        _file("3854", "e499", date(2026, 1, 4)), _file("869", "e2", date(2026, 1, 3)),
        _file("bad", "e2", date(2026, 1, 2)), _file("second", "e9", date(2026, 1, 1)),
    ]
    pages = _Pages({
        "3854": load_pages("mobile_2026-11-03.txt"),
        "869": load_pages("not_minutes_agenda.txt"),
        "bad": RuntimeError("no"),
        "second": _text("NOVEMBER 3, 2026", {}),
    })
    before = _state()

    report = _run(mobile, files, pages, dry_run=True)

    assert _statuses(report) == [
        ("3854", "paired", 7), ("869", "not_minutes", 0), ("bad", "error", 0), ("second", "superseded", 0),
    ]
    assert report.files[0].meeting_id == meeting and report.waiting == 0
    assert _state() == before
    assert _minutes_url(held) == _url("869") and _votes(meeting) == []

    again = _run(mobile, files, pages, dry_run=True)
    assert _statuses(again) == _statuses(report)
    assert _state() == before


@pytest.mark.parametrize("dry_run", [True, False])
def test_no_transaction_is_open_while_a_file_is_fetched(mobile, dry_run):
    """While the second file is fetched, another connection locks the first file's meeting and sees no row."""
    first_meeting = _meeting("e1", date(2022, 3, 15), minutes_url=_url("old-link"))
    _meeting("e2", date(2022, 3, 22))
    files = [_file("211", "e1", date(2026, 1, 2)), _file("300", "e2", date(2026, 1, 1))]
    seen: list = []

    def during_fetch(file, nth):
        if nth != 2:
            return
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM meetings WHERE id = %s FOR UPDATE NOWAIT", (first_meeting,))
                seen.append(cur.fetchone()[0])
                cur.execute("SELECT count(*) FROM minutes_files WHERE file_id LIKE %s", (PREFIX + "%",))
                seen.append(cur.fetchone()[0])
        finally:
            conn.rollback()
            conn.close()

    pages = _Pages({"211": _text("MARCH 15, 2022", {}), "300": _text("MARCH 22, 2022", {})}, on_fetch=during_fetch)

    report = _run(mobile, files, pages, dry_run=dry_run)

    assert pages.calls == [PREFIX + "211", PREFIX + "300"]
    assert seen == [1, 0]
    assert _statuses(report) == [("211", "paired", 1), ("300", "paired", 1)]
    assert (_file_row("211") is None) is dry_run


def _store_failing_for(monkeypatch, tag: str, message: str) -> None:
    """Make the store of one file's reading fail after a statement of its own; its `error` row is still writable."""
    from docket.services import minutes_votes

    real = minutes_votes._store

    def failing(cur, municipality_id, reader_name, version, floor, roster, read):
        if read.file.file_id == PREFIX + tag and read.reading is not None:
            cur.execute("UPDATE meetings SET minutes_url = 'half' WHERE municipality_id = %s", (municipality_id,))
            raise RuntimeError(message)
        return real(cur, municipality_id, reader_name, version, floor, roster, read)

    monkeypatch.setattr(minutes_votes, "_store", failing)


def test_a_reading_that_cannot_be_stored_is_that_files_error_and_the_run_goes_on(mobile, monkeypatch):
    """Nothing of the failed store is kept, the file has a row with its try counted, and the file after it is stored."""
    first = _meeting("e1", date(2022, 3, 15))
    second = _meeting("e2", date(2022, 3, 22))
    third = _meeting("e3", date(2022, 3, 29))
    files = [
        _file("211", "e1", date(2026, 1, 3)), _file("300", "e2", date(2026, 1, 2)), _file("400", "e3", date(2026, 1, 1)),
    ]
    pages = _Pages({
        "211": _text("MARCH 15, 2022", {}), "300": _text("MARCH 22, 2022", {}), "400": _text("MARCH 29, 2022", {}),
    })
    _store_failing_for(monkeypatch, "300", "this text cannot be stored")

    report = _run(mobile, files, pages)

    assert _statuses(report) == [("211", "paired", 1), ("300", "error", 0), ("400", "paired", 1)]
    assert report.files[1].error == "this text cannot be stored"
    assert len(_votes(first)) == 1 and len(_votes(third)) == 1
    assert _votes(second) == [] and _minutes_url(second) is None
    assert (_minutes_url(first), _minutes_url(third)) == (_url("211"), _url("400"))
    row = _file_row("300")
    assert (row["status"], row["attempts"], row["error"], row["meeting_id"], row["page_count"]) == (
        "error", 1, "this text cannot be stored", None, 1,
    )

    again = _run(mobile, files, pages)
    assert _statuses(again) == [("300", "error", 0)]
    assert _file_row("300")["attempts"] == 2
    _run(mobile, files, pages)
    assert _file_row("300")["attempts"] == 3
    assert _run(mobile, files, pages).files == []


def test_a_dry_run_reports_a_reading_that_cannot_be_stored_and_keeps_nothing(mobile, monkeypatch):
    _meeting("e1", date(2022, 3, 15))
    _meeting("e2", date(2022, 3, 22))
    _meeting("e3", date(2022, 3, 29))
    files = [
        _file("211", "e1", date(2026, 1, 3)), _file("300", "e2", date(2026, 1, 2)), _file("400", "e3", date(2026, 1, 1)),
    ]
    pages = _Pages({
        "211": _text("MARCH 15, 2022", {}), "300": _text("MARCH 22, 2022", {}), "400": _text("MARCH 29, 2022", {}),
    })
    _store_failing_for(monkeypatch, "300", "this text cannot be stored")
    before = _state()

    report = _run(mobile, files, pages, dry_run=True)

    assert _statuses(report) == [("211", "paired", 1), ("300", "error", 0), ("400", "paired", 1)]
    assert _state() == before


@pytest.mark.parametrize("dry_run", [True, False])
def test_a_page_with_a_nul_character_is_that_files_error(mobile, dry_run):
    """The reader takes the text and the database refuses it: one file's fault, not the run's."""
    _meeting("e1", date(2022, 3, 15))
    later = _meeting("e2", date(2022, 3, 22))
    files = [_file("211", "e1", date(2026, 1, 2)), _file("300", "e2", date(2026, 1, 1))]
    [page] = _text("MARCH 15, 2022", {})
    pages = _Pages({"211": [page.replace("moved to adopt", "moved\x00 to adopt")], "300": _text("MARCH 22, 2022", {})})

    report = _run(mobile, files, pages, dry_run=dry_run)

    assert _statuses(report) == [("211", "error", 0), ("300", "paired", 1)]
    assert "NUL" in report.files[0].error
    if not dry_run:
        assert (_file_row("211")["status"], _file_row("211")["attempts"]) == ("error", 1)
        assert len(_votes(later)) == 1


def test_a_real_run_commits_each_file_on_its_own(mobile, monkeypatch):
    """A file whose store fails and whose `error` row cannot be written either stops the run; the first file stays stored."""
    from docket.services import minutes_votes

    meeting = _meeting("e1", date(2022, 3, 15))
    _meeting("e2", date(2022, 3, 22))
    files = [_file("211", "e1", date(2026, 1, 2)), _file("300", "e2", date(2026, 1, 1))]
    pages = _Pages({"211": _text("MARCH 15, 2022", {}), "300": _text("MARCH 22, 2022", {})})
    real = minutes_votes._store

    def failing(cur, municipality_id, reader_name, version, floor, roster, read):
        if read.file.file_id == PREFIX + "300":
            cur.execute("UPDATE meetings SET minutes_url = 'half' WHERE external_id = %s", (PREFIX + "e2",))
            raise RuntimeError("the database went away")
        return real(cur, municipality_id, reader_name, version, floor, roster, read)

    monkeypatch.setattr(minutes_votes, "_store", failing)

    with pytest.raises(RuntimeError, match="went away"):
        _run(mobile, files, pages)

    assert _file_row("211")["status"] == "paired" and len(_votes(meeting)) == 1
    assert _file_row("300") is None
    with db_cursor() as cur:
        cur.execute("SELECT minutes_url FROM meetings WHERE external_id = %s", (PREFIX + "e2",))
        assert cur.fetchone()["minutes_url"] is None


# ---------------------------------------------------------------------------
# The code join
# ---------------------------------------------------------------------------

def _read_2026_11_03(mobile) -> tuple[int, dict[str | None, dict]]:
    """The meeting of 2026-11-03 with its seven reader votes; the coded ones by code."""
    meeting = _meeting("e499", date(2026, 11, 3))
    _run(mobile, [_file("3854", "e499")], _Pages({"3854": load_pages("mobile_2026-11-03.txt")}))
    return meeting, {v["resolution_number"]: v for v in _votes(meeting) if v["resolution_number"]}


def test_link_votes_by_code_attaches_a_coded_vote_to_the_one_item_that_opens_with_its_code(mobile):
    from docket.services.minutes_votes import link_votes_by_code

    meeting, coded = _read_2026_11_03(mobile)
    other_meeting = _meeting("e500", date(2026, 11, 10))
    item = _item(meeting, "i1", "40-948 Declare the structure at 906 S. Broad Street a public nuisance")
    _item(meeting, "i2", "40-9481 A code one digit longer")
    _item(meeting, "i3", "Regarding 40-948, a title that does not open with the code")
    _item(meeting, "i4", "08-1180 Approve purchase order")
    _item(meeting, "i5", "08-1180 Approve purchase order, listed twice")
    _item(other_meeting, "i6", "41-1198 Call for public hearing, on another meeting")
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO votes (meeting_id, result, source, resolution_number) "
            "VALUES (%s, 'passed', 'minutes_text', '40-948-2026') RETURNING id",
            (meeting,),
        )
        not_a_readers = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO votes (meeting_id, result, source, resolution_number, minutes_reader) "
            "VALUES (%s, 'passed', 'minutes_text', '40-9482-2026', 'mobile') RETURNING id",
            (meeting,),
        )
        four_digits = cur.fetchone()["id"]
    _item(meeting, "i7", "40-94821 A number that only begins with a four-digit code")

    assert link_votes_by_code(mobile) == 1
    assert [row["agenda_item_id"] for row in _links(four_digits)] == []

    [link] = _links(coded["40-948-2026"]["id"])
    assert link["agenda_item_id"] == item
    assert (link["association_type"], link["match_method"], link["match_confidence"]) == (
        "explicit", "minutes_code", 1.0,
    )
    assert (link["provisional"], link["is_manual"], link["is_active"]) == (False, False, True)
    assert _links(coded["08-1180-2026"]["id"]) == []
    assert _links(coded["41-1198-2026"]["id"]) == []
    assert _links(not_a_readers) == []
    for vote in _votes(meeting):
        if vote["resolution_number"] is None:
            assert _links(vote["id"]) == []

    assert link_votes_by_code(mobile) == 0
    assert len(_links(coded["40-948-2026"]["id"])) == 1


def test_link_votes_by_code_leaves_a_vote_that_has_any_link_and_another_citys_votes(mobile):
    """A link an admin removed is not put back, and the join is one city's."""
    from docket.services.minutes_votes import link_votes_by_code

    meeting, coded = _read_2026_11_03(mobile)
    _item(meeting, "i1", "40-948 Declare the structure")
    elsewhere = _item(meeting, "i2", "An item an admin once attached and then removed")
    _item(meeting, "i3", "41-1198 Call for public hearing")
    vote = coded["40-948-2026"]["id"]
    in_birmingham = _meeting("b1", date(2026, 11, 3), slug="birmingham")
    _item(in_birmingham, "i1", "40-948 The same code in another city")
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO vote_agenda_items (vote_id, agenda_item_id, association_type, match_confidence, is_active) "
            "VALUES (%s, %s, 'explicit', 1.0, FALSE)",
            (vote, elsewhere),
        )
        cur.execute(
            "INSERT INTO votes (meeting_id, result, source, resolution_number, minutes_reader) "
            "VALUES (%s, 'passed', 'minutes_text', '40-948-2026', 'mobile') RETURNING id",
            (in_birmingham,),
        )
        other_citys = cur.fetchone()["id"]

    assert link_votes_by_code(mobile) == 1

    assert [(row["agenda_item_id"], row["is_active"]) for row in _links(vote)] == [(elsewhere, False)]
    assert len(_links(coded["41-1198-2026"]["id"])) == 1
    assert _links(other_citys) == []


def _coded(code: str, **more) -> dict:
    return {"code": code, **more}


def _remove_by_hand(vote_id: int) -> None:
    with db_cursor() as cur:
        cur.execute("UPDATE vote_agenda_items SET is_active = FALSE, is_manual = TRUE WHERE vote_id = %s", (vote_id,))


def test_a_link_removed_by_hand_survives_the_file_that_takes_the_meeting(mobile):
    """A file on the meeting's own event replaces the votes; the removed link goes with the vote of the same code."""
    from docket.services.minutes_votes import link_votes_by_code

    meeting = _meeting("e1", date(2022, 3, 15))
    item = _item(meeting, "i1", "40-948 Declare the structure")
    pages = _text("MARCH 15, 2022", _coded("40-948-2022"), _coded("41-100-2022"))
    _run(mobile, [_file("211", "e7")], _Pages({"211": pages}))
    assert link_votes_by_code(mobile) == 1
    [old] = [v for v in _votes(meeting) if v["resolution_number"] == "40-948-2022"]
    _remove_by_hand(old["id"])

    report = _run(mobile, [_file("625", "e1")], _Pages({"625": pages}))

    assert _statuses(report) == [("625", "paired", 2)]
    [new] = [v for v in _votes(meeting) if v["resolution_number"] == "40-948-2022"]
    assert new["id"] != old["id"]
    assert [(r["agenda_item_id"], r["is_active"], r["is_manual"]) for r in _links(new["id"])] == [(item, False, True)]
    assert link_votes_by_code(mobile) == 0
    assert [(r["agenda_item_id"], r["is_active"]) for r in _links(new["id"])] == [(item, False)]


def test_a_link_set_by_hand_on_a_vote_with_no_code_survives_a_reread_by_the_votes_own_words(mobile, monkeypatch):
    from docket.analysis import mobile_minutes

    meeting = _meeting("e1", date(2022, 3, 15))
    item = _item(meeting, "i1", "An item with no code")
    files = [_file("211", "e7")]
    pages = _text("MARCH 15, 2022", {"ayes": "Penn"}, {"ayes": "Small"})
    _run(mobile, files, _Pages({"211": pages}))
    first, second = _votes(meeting)
    assert first["raw_text"] != second["raw_text"]
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO vote_agenda_items (vote_id, agenda_item_id, association_type, match_method, "
            "match_confidence, provisional, is_manual) VALUES (%s, %s, 'explicit', 'manual', 1.0, FALSE, TRUE)",
            (second["id"], item),
        )

    monkeypatch.setattr(mobile_minutes, "READER_VERSION", 2)
    _run(mobile, files, _Pages({"211": pages}))

    new_first, new_second = _votes(meeting)
    assert new_second["id"] != second["id"]
    assert _links(new_first["id"]) == []
    [link] = _links(new_second["id"])
    assert (link["agenda_item_id"], link["is_manual"], link["is_active"], link["match_method"]) == (
        item, True, True, "manual",
    )


def test_a_hand_link_is_not_carried_to_a_vote_that_cannot_be_told_from_another(mobile, monkeypatch):
    """Two votes with the same words and no code: the link is dropped, not guessed onto one of them."""
    from docket.analysis import mobile_minutes

    meeting = _meeting("e1", date(2022, 3, 15))
    item = _item(meeting, "i1", "An item with no code")
    files = [_file("211", "e7")]
    pages = _text("MARCH 15, 2022", {}, {})
    _run(mobile, files, _Pages({"211": pages}))
    first, second = _votes(meeting)
    assert first["raw_text"] == second["raw_text"]
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO vote_agenda_items (vote_id, agenda_item_id, association_type, match_confidence, is_manual) "
            "VALUES (%s, %s, 'explicit', 1.0, TRUE)",
            (second["id"], item),
        )

    monkeypatch.setattr(mobile_minutes, "READER_VERSION", 2)
    _run(mobile, files, _Pages({"211": pages}))

    assert [_links(v["id"]) for v in _votes(meeting)] == [[], []]


def test_a_link_the_join_made_is_made_again_by_the_join_and_not_carried(mobile, monkeypatch):
    from docket.analysis import mobile_minutes
    from docket.services.minutes_votes import link_votes_by_code

    meeting = _meeting("e1", date(2022, 3, 15))
    _item(meeting, "i1", "40-948 Declare the structure")
    files = [_file("211", "e7")]
    pages = _text("MARCH 15, 2022", _coded("40-948-2022"))
    _run(mobile, files, _Pages({"211": pages}))
    assert link_votes_by_code(mobile) == 1

    monkeypatch.setattr(mobile_minutes, "READER_VERSION", 2)
    _run(mobile, files, _Pages({"211": pages}))

    [vote] = _votes(meeting)
    assert _links(vote["id"]) == []
    assert link_votes_by_code(mobile) == 1


def test_the_adoption_sweep_attaches_nothing_to_a_reader_vote(mobile):
    """The sweep finds Mobile's approval of minutes and marks the meeting; the matcher it calls passes over."""
    from docket.services.minutes_adoption import sweep_adoptions

    target = _meeting("e1", date(2026, 10, 27))
    adopting = _meeting("e2", date(2026, 11, 3))
    files = [_file("t", "e1"), _file("a", "e2")]
    pages = _Pages({
        "t": _text("OCTOBER 27, 2026", {"ayes": "Penn, Small"}, {"ayes": "Penn", "code": "40-100-2026"}),
        "a": _text("NOVEMBER 3, 2026", {"ayes": "Penn, Small"}),
    })
    _run(mobile, files, pages)
    _item(target, "i1", "Consent resolution one", is_consent=True)
    _item(target, "i2", "Consent resolution two", is_consent=True)
    _item(target, "i3", "Resolution 40-100-2026 a thing")
    _item(adopting, "i1", "Approval of the minutes of October 27, 2026")
    reader_votes = _votes(target) + _votes(adopting)
    assert len(reader_votes) == 3 and all(v["result"] == "passed" for v in reader_votes)

    flipped = sweep_adoptions(mobile)

    assert flipped == [target]
    with db_cursor() as cur:
        cur.execute("SELECT minutes_adopted_at FROM meetings WHERE id = %s", (target,))
        assert cur.fetchone()["minutes_adopted_at"].date() == date(2026, 11, 3)
    for vote in reader_votes:
        assert _links(vote["id"]) == []


# ---------------------------------------------------------------------------
# The stored link, and the settings
# ---------------------------------------------------------------------------

def _raw(tag: str, minutes_url: str | None) -> RawMeeting:
    return RawMeeting(
        external_id=PREFIX + tag, municipality_slug="mobile", title="City Council",
        meeting_date=date(2022, 3, 15), meeting_type="council", agenda_url="https://city.invalid/agenda",
        minutes_url=minutes_url, video_url=None, source_url="https://city.invalid/event",
    )


def test_with_paired_links_lets_the_table_decide_a_meetings_minutes_link(mobile):
    from docket.services.minutes_votes import with_paired_links

    paired = _meeting("e1", date(2022, 3, 15))
    _meeting("e2", date(2022, 3, 22))
    birmingham = _city_id("birmingham")
    with db_cursor() as cur:
        for city, tag, status, meeting_id in (
            (mobile, "paired", "paired", paired),
            (mobile, "failed", "error", None),
            (mobile, "letter", "not_minutes", None),
            (mobile, "undated", "no_meeting", None),
            (mobile, "second", "superseded", paired),
            (birmingham, "theirs", "not_minutes", None),
        ):
            cur.execute(
                "INSERT INTO minutes_files (municipality_id, file_id, url, event_external_id, status, meeting_id, "
                "reader_version) VALUES (%s, %s, %s, %s, %s, %s, 1)",
                (city, PREFIX + tag, _url(tag), PREFIX + "e9", status, meeting_id),
            )
    listed = [
        _raw("e1", None),                 # an imported event: the listing gives no link, the table does
        _raw("e2", _url("paired")),       # the listing says e1's file is e2's
        _raw("e3", _url("unread")),       # a file with no row yet
        _raw("e4", _url("failed")),       # a file that failed to read
        _raw("e5", _url("letter")),
        _raw("e6", _url("undated")),
        _raw("e7", _url("second")),
        _raw("e8", None),
        _raw("e9", _url("theirs")),       # another city's row says nothing about this city's link
    ]

    decided = with_paired_links(mobile, listed)

    assert [m.minutes_url for m in decided] == [
        _url("paired"), None, _url("unread"), _url("failed"), None, None, None, None, _url("theirs"),
    ]
    assert [m.external_id for m in decided] == [m.external_id for m in listed]
    assert all(isinstance(m, RawMeeting) for m in decided)
    assert listed[0].minutes_url is None and listed[1].minutes_url == _url("paired")
    assert decided[0] == _raw("e1", _url("paired"))


def test_with_paired_links_gives_a_listed_paired_meeting_the_paired_file_not_the_listed_one(mobile):
    from docket.services.minutes_votes import with_paired_links

    meeting = _meeting("e1", date(2022, 3, 15))
    _run(mobile, [_file("625", "e1")], _Pages({"625": _text("MARCH 15, 2022", {})}))
    assert _minutes_url(meeting) == _url("625")

    [decided] = with_paired_links(mobile, [_raw("e1", _url("a-newer-file-not-yet-read"))])

    assert decided.minutes_url == _url("625")
    assert with_paired_links(mobile, []) == []


def test_with_paired_links_keeps_the_stored_link_of_a_meeting_whose_file_failed_a_reread(mobile, monkeypatch):
    """The two halves joined: the row is `error`, the meeting keeps its votes, and ingest does not blank its link."""
    from docket.analysis import mobile_minutes
    from docket.services.minutes_votes import with_paired_links

    meeting = _meeting("e1", date(2022, 3, 15))
    files = [_file("211", "e7")]
    _run(mobile, files, _Pages({"211": _text("MARCH 15, 2022", {})}))
    monkeypatch.setattr(mobile_minutes, "READER_VERSION", 2)
    _run(mobile, files, _Pages({"211": RuntimeError("no")}))
    assert _file_row("211")["status"] == "error" and len(_votes(meeting)) == 1

    [decided] = with_paired_links(mobile, [_raw("e1", None)])

    assert decided.minutes_url == _url("211")


def test_with_paired_links_gives_no_link_from_a_failed_row_that_never_held_its_meeting(mobile):
    """An `error` row that names a meeting whose stored link is not its address decides nothing."""
    from docket.services.minutes_votes import with_paired_links

    meeting = _meeting("e1", date(2022, 3, 15), minutes_url=_url("holder"))
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO minutes_files (municipality_id, file_id, url, event_external_id, status, meeting_id, "
            "reader_version) VALUES (%s, %s, %s, %s, 'error', %s, 1)",
            (mobile, PREFIX + "second", _url("second"), PREFIX + "e9", meeting),
        )

    [decided] = with_paired_links(mobile, [_raw("e1", None)])

    assert decided.minutes_url is None


def test_reader_settings_reads_the_reader_and_the_cap():
    from docket.services.minutes_votes import reader_settings

    assert reader_settings({}) == (None, 0)
    assert reader_settings(None) == (None, 0)
    assert reader_settings({"minutes_reader": None, "minutes_read_cap": 4}) == (None, 0)
    assert reader_settings({"minutes_reader": "mobile"}) == ("mobile", 10)
    assert reader_settings({"minutes_reader": "mobile", "minutes_read_cap": None}) == ("mobile", 10)
    assert reader_settings({"minutes_reader": "mobile", "minutes_read_cap": 0}) == ("mobile", 0)
    assert reader_settings({"minutes_reader": "mobile", "minutes_read_cap": 60}) == ("mobile", 60)


@pytest.mark.parametrize(
    ("config", "key"),
    [
        ({"minutes_reader": "birmingham"}, "minutes_reader"),
        ({"minutes_reader": ""}, "minutes_reader"),
        ({"minutes_reader": ["mobile"]}, "minutes_reader"),
        ({"minutes_reader": True}, "minutes_reader"),
        ({"minutes_reader": "mobile", "minutes_read_cap": -1}, "minutes_read_cap"),
        ({"minutes_reader": "mobile", "minutes_read_cap": True}, "minutes_read_cap"),
        ({"minutes_reader": "mobile", "minutes_read_cap": False}, "minutes_read_cap"),
        ({"minutes_reader": "mobile", "minutes_read_cap": "5"}, "minutes_read_cap"),
        ({"minutes_reader": "mobile", "minutes_read_cap": 1.5}, "minutes_read_cap"),
    ],
)
def test_reader_settings_refuses_a_bad_value_naming_its_key(config, key):
    from docket.services.minutes_votes import reader_settings

    with pytest.raises(ValueError, match=key) as raised:
        reader_settings(config)
    other = {"minutes_reader", "minutes_read_cap"} - {key}
    assert not any(name in str(raised.value) for name in other)
