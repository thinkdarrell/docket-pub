"""Ingest reads a reader city's minutes files, and the operator's script runs the same read.

Plan `mobile-votes-from-minutes`, M4. No test here reaches a city's site.
`get_adapter` (of `docket.services.ingest`, and of
`docket.services.minutes_votes` for the script) is replaced by an adapter that
lists the meetings and the Minutes files a test gives it and serves each file
as bytes; the reader's `pages_from_pdf` is replaced by one that cuts those
bytes back into the pages the test wrote, in an invented style, so no PDF is
built. Everything else is the real code against the throwaway database
(DATABASE_URL names docket_test_*) for the seeded city ``mobile``, whose
``adapter_config`` each test sets and the fixture restores. Every meeting a
test makes has an external id that begins ``ims-test-`` and every file an id
that begins ``ims-test-``; both are deleted before and after each test.

The script and `read_city` are imported inside the tests, so that before they
exist each of their tests fails on that import and the file collects.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date

import pytest
import requests

from docket.db import db_cursor
from docket.models.protocol import AgendaNotReady, RawAgendaItem, RawMeeting, RawMinutesFile

PREFIX = "ims-test-"
SLUG = "mobile"
BASE = {"tenant": "mobileal", "category_id": 26}
DECLARED = "The vote was then announced by the City Clerk, whereupon the Presiding Officer declared the thing adopted."
MOTION = "Councilmember Alpha moved to adopt it, which was seconded by Councilmember Beta and the vote was as follows:"

FIRST = date(2029, 3, 6)
SECOND = date(2029, 3, 13)


# ---------------------------------------------------------------------------
# Seeding and reading back
# ---------------------------------------------------------------------------

def _delete_test_rows() -> None:
    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE external_id LIKE %s", (PREFIX + "%",))
        cur.execute("DELETE FROM minutes_files WHERE file_id LIKE %s", (PREFIX + "%",))


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """Delete this file's rows, put the city's settings back, and stand in for the PDF reading."""
    from docket.analysis import mobile_minutes

    monkeypatch.setattr(mobile_minutes, "pages_from_pdf", _pages_of)
    with db_cursor() as cur:
        cur.execute("SELECT adapter_config FROM municipalities WHERE slug = %s", (SLUG,))
        saved = cur.fetchone()["adapter_config"]
    _delete_test_rows()
    try:
        yield
    finally:
        _delete_test_rows()
        with db_cursor() as cur:
            cur.execute(
                "UPDATE municipalities SET adapter_config = %s::jsonb WHERE slug = %s", (json.dumps(saved), SLUG)
            )


def _configure(**settings) -> None:
    with db_cursor() as cur:
        cur.execute(
            "UPDATE municipalities SET adapter_config = %s::jsonb WHERE slug = %s",
            (json.dumps({**BASE, **settings}), SLUG),
        )


def _city_id() -> int:
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug = %s", (SLUG,))
        return cur.fetchone()["id"]


def _url(tag: str) -> str:
    return f"https://mobileal.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId={tag},plainText=false)"


def _meeting(tag: str, day: date, minutes: str | None = None) -> RawMeeting:
    """A listed meeting; `minutes` is the tag of the file its listing links, or None."""
    return RawMeeting(
        external_id=PREFIX + tag,
        municipality_slug=SLUG,
        title="City Council Meeting",
        meeting_date=day,
        meeting_type="council",
        agenda_url=f"https://example.com/agenda/{tag}",
        minutes_url=_url(minutes) if minutes else None,
        video_url=None,
        source_url=f"https://example.com/event/{tag}",
    )


def _file(tag: str, event: str, event_date: date) -> RawMinutesFile:
    return RawMinutesFile(file_id=PREFIX + tag, url=_url(tag), event_external_id=PREFIX + event, event_date=event_date)


def _text(heading: str | None, *votes: dict) -> list[str]:
    """One page of minutes in an invented style: a heading line and one block per vote."""
    lines = []
    if heading is not None:
        lines.append(f"MUNICIPAL BUILDING, MOBILE, ALABAMA, {heading}")
    lines.append("The Council met in the Auditorium.")
    for vote in votes:
        if vote.get("code"):
            lines.append("A THING. The following resolution was introduced by Councilmember Alpha.")
            lines.append(f"RESOLUTION: {vote['code']}")
        lines.append(MOTION)
        lines.append(f"Ayes: {vote.get('ayes', 'Penn')}")
        lines.append("Nays: None")
        lines.append(DECLARED)
    return ["\n".join(lines)]


def _pdf(pages: list[str]) -> bytes:
    return b"%PDF-" + "\f".join(pages).encode()


def _pages_of(pdf_bytes: bytes) -> list[str]:
    assert pdf_bytes.startswith(b"%PDF-")
    return pdf_bytes[5:].decode().split("\f")


class _Adapter:
    """Lists the meetings and files it was given and serves each file; records what it was asked."""

    def __init__(self, meetings, files=(), pages=None, items=None, listing_error=None, files_error=None):
        self.meetings = list(meetings)
        self.files = list(files)
        self.pages = {_url(tag): value for tag, value in (pages or {}).items()}
        self.items = items or {}
        self.listing_error = listing_error
        self.files_error = files_error
        self.since_calls: list[date | None] = []
        self.listed_files_calls = 0
        self.fetched_files: list[str] = []
        self.votes_asked: list[str] = []

    def list_meetings(self, since=None):
        self.since_calls.append(since)
        if self.listing_error is not None:
            raise self.listing_error
        return list(self.meetings)

    def fetch_agenda_items(self, meeting):
        title = self.items.get(meeting.external_id.removeprefix(PREFIX))
        if title is None:
            raise AgendaNotReady("no agenda in this test")
        return [
            RawAgendaItem(
                external_id=f"{meeting.external_id}-1",
                meeting_external_id=meeting.external_id,
                item_number="1",
                title=title,
                description=None,
                section=None,
                is_consent=False,
                sponsor=None,
            )
        ]

    def fetch_votes(self, meeting):
        self.votes_asked.append(meeting.external_id.removeprefix(PREFIX))
        return []

    def fetch_minutes_text(self, meeting):
        return None

    def listed_minutes_files(self):
        self.listed_files_calls += 1
        if self.files_error is not None:
            raise self.files_error
        return list(self.files)

    def fetch_file(self, url):
        self.fetched_files.append(url)
        value = self.pages[url]
        if isinstance(value, Exception):
            raise value
        return _pdf(value)


def _use(monkeypatch, adapter) -> None:
    from docket.services import ingest

    monkeypatch.setattr(ingest, "get_adapter", lambda adapter_class, slug, config: adapter)


def _use_for_script(monkeypatch, adapter) -> list[tuple]:
    """Stand in for the adapter the script's service builds; returns the calls made to build one."""
    from docket.services import minutes_votes

    built: list[tuple] = []

    def get_adapter(adapter_class, slug, config):
        built.append((adapter_class, slug, config))
        return adapter

    monkeypatch.setattr(minutes_votes, "get_adapter", get_adapter)
    return built


def _row(tag: str) -> dict | None:
    """A meeting of this file: its id, its minutes link and whether its votes are marked scanned."""
    with db_cursor() as cur:
        cur.execute(
            """SELECT m.id, m.minutes_url, ps.votes_scanned
                 FROM meetings m LEFT JOIN processing_status ps ON ps.meeting_id = m.id
                WHERE m.external_id = %s""",
            (PREFIX + tag,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def _votes(tag: str) -> list[dict]:
    with db_cursor() as cur:
        cur.execute(
            """SELECT v.* FROM votes v JOIN meetings m ON m.id = v.meeting_id
                WHERE m.external_id = %s ORDER BY v.id""",
            (PREFIX + tag,),
        )
        return [dict(r) for r in cur.fetchall()]


def _links(vote_id: int) -> list[dict]:
    with db_cursor() as cur:
        cur.execute(
            """SELECT x.association_type, x.match_method, x.is_active, ai.title
                 FROM vote_agenda_items x JOIN agenda_items ai ON ai.id = x.agenda_item_id
                WHERE x.vote_id = %s""",
            (vote_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def _file_rows() -> dict[str, str]:
    """This city's minutes_files rows of this file: tag -> status."""
    with db_cursor() as cur:
        cur.execute("SELECT file_id, status FROM minutes_files WHERE file_id LIKE %s", (PREFIX + "%",))
        return {r["file_id"].removeprefix(PREFIX): r["status"] for r in cur.fetchall()}


def _all_file_rows() -> int:
    with db_cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM minutes_files")
        return cur.fetchone()["n"]


def _state() -> dict:
    """Everything the read can write, read whole."""
    out: dict = {}
    with db_cursor() as cur:
        for table in ("votes", "member_votes", "vote_agenda_items", "minutes_files"):
            cur.execute(f"SELECT * FROM {table} ORDER BY id")
            out[table] = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT id, minutes_url, updated_at FROM meetings ORDER BY id")
        out["meetings"] = [dict(r) for r in cur.fetchall()]
    return out


def _seed_meeting(tag: str, day: date, *, minutes_url: str | None = None, votes_scanned: bool = False) -> int:
    """A stored meeting with its status row, as an earlier ingest left it."""
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type, minutes_url) "
            "VALUES (%s, %s, 'City Council Meeting', %s, 'council', %s) RETURNING id",
            (_city_id(), PREFIX + tag, day, minutes_url),
        )
        meeting_id = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO processing_status (meeting_id, votes_scanned) VALUES (%s, %s)", (meeting_id, votes_scanned)
        )
        return meeting_id


def _seed_item(meeting_id: int, title: str) -> None:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO agenda_items (meeting_id, external_id, item_number, title, is_consent) "
            "VALUES (%s, %s, '1', %s, FALSE)",
            (meeting_id, f"{PREFIX}item-{meeting_id}", title),
        )


def _lines(caplog, start: str) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith(start)]


def _two_meetings_two_files() -> _Adapter:
    """Meeting 1 is linked to file f1 by its listing and has an agenda item coded 40-948;
    meeting 2 is an imported event, so its listing gives no link, and file f2 sits on it."""
    return _Adapter(
        [_meeting("1", FIRST, minutes="f1"), _meeting("2", SECOND)],
        files=[_file("f1", "1", FIRST), _file("f2", "2", SECOND)],
        pages={
            "f1": _text("MARCH 6, 2029", {"code": "40-948-2029"}, {"ayes": "Penn and Small"}),
            "f2": _text("MARCH 13, 2029", {}),
        },
        items={"1": "40-948 Declare the structure a public nuisance."},
    )


# ---------------------------------------------------------------------------
# The stage of ingest
# ---------------------------------------------------------------------------

def test_a_reader_city_gets_its_votes_from_one_ingest_run_a_scanned_meeting_included(monkeypatch, caplog):
    """`votes_scanned` is not consulted by the reader (debt row D181 c)."""
    from docket.services.ingest import ingest_municipality

    _seed_meeting("1", FIRST, minutes_url=_url("f1"), votes_scanned=True)
    adapter = _two_meetings_two_files()
    _use(monkeypatch, adapter)
    _configure(minutes_reader="mobile")

    with caplog.at_level(logging.INFO, logger="docket.services.ingest"):
        result = ingest_municipality(SLUG)

    assert result.errors == []
    assert result.meetings_found == 2
    assert result.votes_inserted == 3
    assert adapter.listed_files_calls == 1
    # newest event first
    assert adapter.fetched_files == [_url("f2"), _url("f1")]

    first, second = _votes("1"), _votes("2")
    assert [v["external_id"] for v in first] == [f"{PREFIX}1-mv-1", f"{PREFIX}1-mv-2"]
    assert [v["external_id"] for v in second] == [f"{PREFIX}2-mv-1"]
    assert {(v["source"], v["minutes_reader"]) for v in first + second} == {("minutes_text", "mobile")}
    assert [v["resolution_number"] for v in first] == ["40-948-2029", None]
    assert (first[1]["yeas"], first[1]["nays"]) == (2, 0)

    assert _row("1")["minutes_url"] == _url("f1")
    assert _row("2")["minutes_url"] == _url("f2")
    assert _file_rows() == {"f1": "paired", "f2": "paired"}

    # The coded vote is attached to the item ingest stored in this same run.
    assert _links(first[0]["id"]) == [
        {
            "association_type": "explicit",
            "match_method": "minutes_code",
            "is_active": True,
            "title": "40-948 Declare the structure a public nuisance.",
        }
    ]
    assert _links(first[1]["id"]) == []

    assert _lines(caplog, "Minutes files:") == [
        "Minutes files: read=2 paired=2 superseded=0 not_minutes=0 no_meeting=0 errors=0 votes=3 waiting=0"
    ]
    assert _lines(caplog, "Minutes votes linked by code:") == ["Minutes votes linked by code: 1"]


def test_the_paired_link_survives_a_second_run_whose_listing_gives_that_meeting_no_link(monkeypatch, caplog):
    from docket.services.ingest import ingest_municipality

    adapter = _two_meetings_two_files()
    _use(monkeypatch, adapter)
    _configure(minutes_reader="mobile")

    assert ingest_municipality(SLUG).errors == []
    assert _row("2")["minutes_url"] == _url("f2")
    # Stage 4 passed meeting 2 by in the first run: its listing gave it no link then.
    assert adapter.votes_asked == ["1"]
    assert _row("2")["votes_scanned"] is not True
    before = [v["id"] for v in _votes("1") + _votes("2")]

    with caplog.at_level(logging.INFO, logger="docket.services.ingest"):
        result = ingest_municipality(SLUG)

    assert result.errors == []
    assert result.votes_inserted == 0
    assert _row("1")["minutes_url"] == _url("f1")
    assert _row("2")["minutes_url"] == _url("f2")
    # Nothing was read again and no vote was replaced.
    assert adapter.fetched_files == [_url("f2"), _url("f1")]
    assert [v["id"] for v in _votes("1") + _votes("2")] == before
    assert _lines(caplog, "Minutes files:") == [
        "Minutes files: read=0 paired=0 superseded=0 not_minutes=0 no_meeting=0 errors=0 votes=0 waiting=0"
    ]
    assert _lines(caplog, "Minutes votes linked by code:") == ["Minutes votes linked by code: 0"]
    # Stage 4 is as it was: with the paired link it asks the adapter, which has
    # no vote, and marks the meeting scanned. The reader's votes stand.
    assert adapter.votes_asked == ["1", "2"]
    assert _row("2")["votes_scanned"] is True


def test_a_listed_link_to_a_file_that_is_not_minutes_goes_and_stays_gone(monkeypatch):
    """The listing links meeting 1 to a file that prints no heading date (an agenda
    under the Minutes label): the link is cleared when the file is read, and the
    next run's listing does not write it back."""
    from docket.services.ingest import ingest_municipality

    adapter = _Adapter(
        [_meeting("1", FIRST, minutes="f1")],
        files=[_file("f1", "1", FIRST)],
        pages={"f1": _text(None, {})},
    )
    _use(monkeypatch, adapter)
    _configure(minutes_reader="mobile")

    assert ingest_municipality(SLUG).errors == []
    assert _file_rows() == {"f1": "not_minutes"}
    assert _row("1")["minutes_url"] is None
    assert _votes("1") == []

    result = ingest_municipality(SLUG)
    assert result.errors == []
    assert _row("1")["minutes_url"] is None
    assert adapter.fetched_files == [_url("f1")]
    # Stage 4 never saw a link for it in the second run.
    assert adapter.votes_asked == ["1"]


def test_a_city_without_the_key_ingests_exactly_as_before(monkeypatch, caplog):
    from docket.services import minutes_votes
    from docket.services.ingest import ingest_municipality

    def refuse(*args, **kwargs):
        raise AssertionError("the reader was reached for a city that names none")

    for name in ("with_paired_links", "read_listed", "link_votes_by_code"):
        monkeypatch.setattr(minutes_votes, name, refuse)

    adapter = _two_meetings_two_files()
    _use(monkeypatch, adapter)
    # A cap alone names no reader.
    _configure(minutes_read_cap=5)
    rows_before = _all_file_rows()

    with caplog.at_level(logging.INFO, logger="docket.services.ingest"):
        result = ingest_municipality(SLUG)

    assert result.errors == []
    assert result.votes_inserted == 0
    assert adapter.listed_files_calls == 0
    assert adapter.fetched_files == []
    assert _all_file_rows() == rows_before
    assert _votes("1") == [] and _votes("2") == []
    # The listing's own links are what is stored.
    assert _row("1")["minutes_url"] == _url("f1")
    assert _row("2")["minutes_url"] is None
    assert adapter.votes_asked == ["1"]
    assert _lines(caplog, "Minutes") == []


@pytest.mark.parametrize(
    "settings, key",
    [
        ({"minutes_reader": "birmingham"}, "minutes_reader"),
        ({"minutes_reader": 7}, "minutes_reader"),
        ({"minutes_reader": "mobile", "minutes_read_cap": -1}, "minutes_read_cap"),
        ({"minutes_reader": "mobile", "minutes_read_cap": True}, "minutes_read_cap"),
        ({"minutes_reader": "mobile", "minutes_read_cap": "3"}, "minutes_read_cap"),
    ],
)
def test_a_bad_reader_setting_is_the_one_error_before_any_request(monkeypatch, settings, key):
    from docket.services.ingest import ingest_municipality
    from docket.services.minutes_votes import reader_settings

    adapter = _two_meetings_two_files()
    _use(monkeypatch, adapter)
    _configure(**settings)
    with pytest.raises(ValueError) as reason:
        reader_settings({**BASE, **settings})
    assert key in str(reason.value)

    result = ingest_municipality(SLUG)

    assert result.errors == [f"Bad adapter_config for mobile: {reason.value}"]
    assert not result.success
    assert (result.meetings_found, result.meetings_inserted, result.meetings_updated) == (0, 0, 0)
    assert (result.agenda_items_inserted, result.votes_inserted) == (0, 0)
    assert adapter.since_calls == []
    assert adapter.listed_files_calls == 0
    assert _row("1") is None


def test_an_unknown_slug_returns_its_error():
    """Debt row D184: this return passed six values to a result of seven fields."""
    from docket.services.ingest import ingest_municipality

    result = ingest_municipality("ims-test-no-such-city")

    assert result.municipality_slug == "ims-test-no-such-city"
    assert result.errors == ["Municipality 'ims-test-no-such-city' not found"]
    assert not result.success
    assert (result.meetings_found, result.meetings_inserted, result.meetings_updated) == (0, 0, 0)
    assert (result.agenda_items_inserted, result.votes_inserted) == (0, 0)


def test_a_failed_listing_returns_its_error(monkeypatch):
    """Debt row D184, the second return."""
    from docket.services.ingest import ingest_municipality

    adapter = _Adapter([], listing_error=RuntimeError("the site did not answer"))
    _use(monkeypatch, adapter)
    _configure(minutes_reader="mobile")

    result = ingest_municipality(SLUG)

    assert result.municipality_slug == SLUG
    assert result.errors == ["Failed to scrape meetings: the site did not answer"]
    assert not result.success
    assert (result.meetings_found, result.meetings_inserted, result.meetings_updated) == (0, 0, 0)
    assert (result.agenda_items_inserted, result.votes_inserted) == (0, 0)
    assert adapter.since_calls == [None]
    assert adapter.listed_files_calls == 0


def test_a_file_that_cannot_be_fetched_is_one_error_and_the_run_goes_on(monkeypatch, caplog):
    from docket.services.ingest import ingest_municipality

    adapter = _two_meetings_two_files()
    adapter.pages[_url("f2")] = requests.RequestException("no answer after 3 attempts")
    _use(monkeypatch, adapter)
    _configure(minutes_reader="mobile")

    with caplog.at_level(logging.INFO, logger="docket.services.ingest"):
        result = ingest_municipality(SLUG)

    assert result.errors == [f"Minutes file {PREFIX}f2: no answer after 3 attempts"]
    assert result.votes_inserted == 2
    assert _file_rows() == {"f1": "paired", "f2": "error"}
    assert len(_votes("1")) == 2 and _votes("2") == []
    assert _lines(caplog, "Minutes files:") == [
        "Minutes files: read=2 paired=1 superseded=0 not_minutes=0 no_meeting=0 errors=1 votes=2 waiting=0"
    ]
    # The code join still ran.
    assert _lines(caplog, "Minutes votes linked by code:") == ["Minutes votes linked by code: 1"]


def test_a_failure_of_the_stage_is_one_error_and_the_run_ends_as_usual(monkeypatch, caplog):
    from docket.services.ingest import ingest_municipality

    adapter = _two_meetings_two_files()
    adapter.files_error = RuntimeError("boom")
    _use(monkeypatch, adapter)
    _configure(minutes_reader="mobile")

    with caplog.at_level(logging.INFO, logger="docket.services.ingest"):
        result = ingest_municipality(SLUG)

    assert result.errors == ["Minutes files: boom"]
    assert result.meetings_found == 2
    assert result.votes_inserted == 0
    assert _row("1")["minutes_url"] == _url("f1")
    assert _lines(caplog, "Minutes files:") == []
    assert _lines(caplog, "adoption_sweep") != []


def test_the_cap_bounds_what_one_run_reads_and_zero_reads_none(monkeypatch, caplog):
    from docket.services.ingest import ingest_municipality

    adapter = _two_meetings_two_files()
    _use(monkeypatch, adapter)

    _configure(minutes_reader="mobile", minutes_read_cap=0)
    with caplog.at_level(logging.INFO, logger="docket.services.ingest"):
        result = ingest_municipality(SLUG)
    assert result.errors == [] and result.votes_inserted == 0
    assert adapter.fetched_files == []
    assert adapter.listed_files_calls == 1
    assert _file_rows() == {}
    assert _lines(caplog, "Minutes files:") == [
        "Minutes files: read=0 paired=0 superseded=0 not_minutes=0 no_meeting=0 errors=0 votes=0 waiting=2"
    ]

    caplog.clear()
    _configure(minutes_reader="mobile", minutes_read_cap=1)
    with caplog.at_level(logging.INFO, logger="docket.services.ingest"):
        result = ingest_municipality(SLUG)
    assert result.errors == [] and result.votes_inserted == 1
    assert adapter.fetched_files == [_url("f2")]
    assert _file_rows() == {"f2": "paired"}
    assert _lines(caplog, "Minutes files:") == [
        "Minutes files: read=1 paired=1 superseded=0 not_minutes=0 no_meeting=0 errors=0 votes=1 waiting=1"
    ]

    result = ingest_municipality(SLUG)
    assert result.errors == [] and result.votes_inserted == 2
    assert adapter.fetched_files == [_url("f2"), _url("f1")]
    assert _file_rows() == {"f1": "paired", "f2": "paired"}


def test_the_statuses_are_each_counted_in_the_log_line(monkeypatch, caplog):
    """One file of each kind in one run: paired, superseded, not minutes, no meeting."""
    from docket.services.ingest import ingest_municipality

    third = date(2029, 3, 20)
    adapter = _Adapter(
        [_meeting("1", FIRST), _meeting("2", SECOND), _meeting("3", third)],
        files=[_file("own", "1", FIRST), _file("other", "2", SECOND), _file("agenda", "3", third)],
        pages={
            "own": _text("MARCH 6, 2029", {}, {}),
            "other": _text("MARCH 6, 2029", {}, {}),
            "agenda": _text(None, {}),
        },
    )
    adapter.files.append(_file("early", "1", date(2029, 3, 5)))
    adapter.pages[_url("early")] = _text("JANUARY 2, 2029", {})
    _use(monkeypatch, adapter)
    _configure(minutes_reader="mobile")

    with caplog.at_level(logging.INFO, logger="docket.services.ingest"):
        result = ingest_municipality(SLUG)

    assert result.errors == []
    assert _file_rows() == {"own": "paired", "other": "superseded", "agenda": "not_minutes", "early": "no_meeting"}
    # `other` is read first (newer event) and paired, then `own` takes the meeting:
    # the votes counted are those each file stored when it was read.
    assert _lines(caplog, "Minutes files:") == [
        "Minutes files: read=4 paired=2 superseded=0 not_minutes=1 no_meeting=1 errors=0 votes=4 waiting=0"
    ]
    assert result.votes_inserted == 4
    assert len(_votes("1")) == 2


# ---------------------------------------------------------------------------
# read_city and the operator's script
# ---------------------------------------------------------------------------

def _script_setup(monkeypatch, *, floor: str | None = "2021-11-01", reader: bool = True):
    """Three stored meetings, three listed files; the script's `--limit 2` leaves one waiting."""
    third = date(2029, 3, 20)
    first_id = _seed_meeting("1", FIRST)
    _seed_meeting("2", SECOND)
    _seed_meeting("3", third)
    _seed_item(first_id, "40-948 Declare the structure a public nuisance.")
    adapter = _Adapter(
        [_meeting("1", FIRST), _meeting("2", SECOND), _meeting("3", third)],
        files=[_file("f1", "1", FIRST), _file("f2", "2", SECOND), _file("f3", "3", third)],
        pages={
            "f1": _text("MARCH 6, 2029", {"code": "40-948-2029"}, {}),
            "f2": _text("MARCH 13, 2029", {}),
            "f3": _text("MARCH 20, 2029", {}, {}, {}),
        },
    )
    built = _use_for_script(monkeypatch, adapter)
    settings = {}
    if reader:
        settings["minutes_reader"] = "mobile"
    if floor:
        settings["backlog_floor"] = floor
    _configure(**settings)
    return adapter, built


def test_the_script_dry_run_prints_each_file_and_changes_nothing(monkeypatch, capsys):
    from scripts.read_minutes_votes import main

    adapter, built = _script_setup(monkeypatch)
    before = _state()

    code = main(["--city", SLUG, "--limit", "2"])

    out = capsys.readouterr().out.splitlines()
    assert code == 0
    assert re.fullmatch(r"database: [^/\s:@]+/docket_test_\w+", out[0]), out[0]
    assert out[1:] == [
        f"file {PREFIX}f3 on event {PREFIX}3 names 2029-03-20 -> paired, 3 votes",
        f"file {PREFIX}f2 on event {PREFIX}2 names 2029-03-13 -> paired, 1 votes",
        "read: 2  paired: 2  superseded: 0  not_minutes: 0  no_meeting: 0  errors: 0  votes: 4  waiting: 1",
        "dry run: nothing changed",
    ]
    assert _state() == before
    # The city's own adapter, built from its row, lists from the floor.
    assert [(cls, slug) for cls, slug, _ in built] == [("CivicClerkAdapter", SLUG)]
    assert built[0][2]["tenant"] == "mobileal"
    assert adapter.since_calls == [date(2021, 11, 1)]
    assert adapter.fetched_files == [_url("f3"), _url("f2")]


def test_the_script_with_apply_stores_and_joins_by_code(monkeypatch, capsys):
    from scripts.read_minutes_votes import main

    adapter, _ = _script_setup(monkeypatch, floor=None)

    code = main(["--city", SLUG, "--limit", "3", "--apply"])

    out = capsys.readouterr().out.splitlines()
    assert code == 0
    assert out[1:] == [
        f"file {PREFIX}f3 on event {PREFIX}3 names 2029-03-20 -> paired, 3 votes",
        f"file {PREFIX}f2 on event {PREFIX}2 names 2029-03-13 -> paired, 1 votes",
        f"file {PREFIX}f1 on event {PREFIX}1 names 2029-03-06 -> paired, 2 votes",
        "read: 3  paired: 3  superseded: 0  not_minutes: 0  no_meeting: 0  errors: 0  votes: 6  waiting: 0",
        "applied",
    ]
    assert adapter.since_calls == [None]
    assert _file_rows() == {"f1": "paired", "f2": "paired", "f3": "paired"}
    assert [len(_votes(tag)) for tag in ("1", "2", "3")] == [2, 1, 3]
    assert _row("3")["minutes_url"] == _url("f3")
    coded = _votes("1")[0]
    assert [link["match_method"] for link in _links(coded["id"])] == ["minutes_code"]

    # A second run has nothing to read.
    assert main(["--city", SLUG, "--limit", "3", "--apply"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[1:] == [
        "read: 0  paired: 0  superseded: 0  not_minutes: 0  no_meeting: 0  errors: 0  votes: 0  waiting: 0",
        "applied",
    ]


def test_the_script_dry_run_does_not_join_by_code(monkeypatch):
    """A dry run rolls its votes back; a join run after it would write for votes stored earlier."""
    from docket.services import minutes_votes
    from scripts.read_minutes_votes import main

    _script_setup(monkeypatch)
    assert main(["--city", SLUG, "--limit", "3", "--apply"]) == 0
    coded = _votes("1")[0]
    with db_cursor() as cur:
        cur.execute("DELETE FROM vote_agenda_items WHERE vote_id = %s", (coded["id"],))

    joined: list[int] = []
    real = minutes_votes.link_votes_by_code
    monkeypatch.setattr(minutes_votes, "link_votes_by_code", lambda city: joined.append(city) or real(city))

    assert main(["--city", SLUG, "--limit", "3"]) == 0
    assert joined == [] and _links(coded["id"]) == []
    assert main(["--city", SLUG, "--limit", "3", "--apply"]) == 0
    assert joined == [_city_id()] and len(_links(coded["id"])) == 1


def test_the_script_prints_every_kind_of_outcome(monkeypatch, capsys):
    from scripts.read_minutes_votes import main

    adapter, _ = _script_setup(monkeypatch)
    adapter.pages[_url("f3")] = requests.RequestException("no answer after 3 attempts")
    adapter.pages[_url("f2")] = _text(None, {})
    adapter.pages[_url("f1")] = _text("OCTOBER 5, 2021", {})

    assert main(["--city", SLUG, "--limit", "9"]) == 0

    out = capsys.readouterr().out.splitlines()
    assert out[1:] == [
        f"file {PREFIX}f3 on event {PREFIX}3 -> error: no answer after 3 attempts",
        f"file {PREFIX}f2 on event {PREFIX}2 -> not_minutes",
        f"file {PREFIX}f1 on event {PREFIX}1 names 2021-10-05 -> no_meeting",
        "read: 3  paired: 0  superseded: 0  not_minutes: 1  no_meeting: 1  errors: 1  votes: 0  waiting: 0",
        "dry run: nothing changed",
    ]


def test_the_script_refuses_a_city_that_names_no_reader(monkeypatch, capsys):
    from scripts.read_minutes_votes import main

    adapter, built = _script_setup(monkeypatch, reader=False)
    before = _state()

    for argv in (["--city", SLUG, "--limit", "2"], ["--city", SLUG, "--limit", "2", "--apply"]):
        code = main(argv)
        captured = capsys.readouterr()
        assert code == 2
        assert re.fullmatch(r"database: \S+/docket_test_\w+\n", captured.out), captured.out
        assert captured.err == "adapter_config of mobile names no minutes_reader\n"

    # Refused before an adapter is built or a request made.
    assert built == []
    assert adapter.since_calls == []
    assert _state() == before


def test_the_script_refuses_an_unknown_city_and_a_bad_setting(monkeypatch, capsys):
    from scripts.read_minutes_votes import main

    adapter, built = _script_setup(monkeypatch)

    assert main(["--city", "ims-test-no-such-city", "--limit", "2"]) == 2
    assert capsys.readouterr().err == "Municipality 'ims-test-no-such-city' not found\n"

    _configure(minutes_reader="birmingham")
    assert main(["--city", SLUG, "--limit", "2"]) == 2
    assert "minutes_reader" in capsys.readouterr().err

    _configure(minutes_reader="mobile", backlog_floor="yesterday")
    assert main(["--city", SLUG, "--limit", "2"]) == 2
    assert "backlog_floor" in capsys.readouterr().err

    assert built == []
    assert adapter.since_calls == []


@pytest.mark.parametrize("argv", [["--city", SLUG], ["--city", SLUG, "--limit", "-1"], ["--limit", "2"]])
def test_the_script_requires_a_city_and_a_limit_of_zero_or_more(monkeypatch, capsys, argv):
    from scripts.read_minutes_votes import main

    _, built = _script_setup(monkeypatch)
    with pytest.raises(SystemExit) as raised:
        main(argv)
    assert raised.value.code == 2
    assert built == []
    # Refused before the database is named: nothing was connected to.
    assert capsys.readouterr().out == ""


def test_read_city_returns_the_report_of_the_read(monkeypatch):
    from docket.services.minutes_votes import read_city

    _script_setup(monkeypatch)

    report = read_city(SLUG, limit=1, apply=False)
    assert [(o.file_id, o.status, o.votes) for o in report.files] == [(PREFIX + "f3", "paired", 3)]
    assert report.waiting == 2
    assert _file_rows() == {}

    report = read_city(SLUG, limit=0, apply=True)
    assert report.files == [] and report.waiting == 3

    report = read_city(SLUG, limit=1, apply=True)
    assert [(o.file_id, o.status, o.votes) for o in report.files] == [(PREFIX + "f3", "paired", 3)]
    assert _file_rows() == {"f3": "paired"}

    with pytest.raises(ValueError, match="names no minutes_reader"):
        _configure()
        read_city(SLUG, limit=1, apply=True)
    with pytest.raises(ValueError, match="not found"):
        read_city("ims-test-no-such-city", limit=1, apply=True)
