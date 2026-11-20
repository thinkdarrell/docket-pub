"""Ingest reads a city's backlog floor and per-run cap, and honours "not ready".

No test here reaches a city's site. `docket.services.ingest.get_adapter` is
replaced by an adapter that lists the meetings a test gives it and records
what it was asked. The whole of `ingest_municipality` then runs against the
throwaway database (DATABASE_URL names docket_test_*) for the seeded city
``mobile``, whose ``adapter_config`` each test sets and the fixture restores.
Every meeting a test creates has a title beginning ``BACKLOG_TEST_`` and is
deleted before and after every test. The meetings, their ids and their links
are built here; none is a row a city sent.

Plan `mobile-agendas-flow-again`, M3.
"""

from __future__ import annotations

import json
import logging
from datetime import date

import pytest

from docket.db import db_cursor
from docket.models.protocol import AgendaNotReady, RawAgendaItem, RawMeeting

PREFIX = "BACKLOG_TEST_"
SLUG = "mobile"
BASE = {"tenant": "mobileal", "category_id": 26}
PAGE_LINK = "https://mobileal.portal.civicclerk.com/event/900001/agenda"
FILE_LINK = "https://mobileal.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=900001,plainText=false)"


def _delete_seeded() -> None:
    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE title LIKE %s", (PREFIX + "%",))


@pytest.fixture(autouse=True)
def _clean():
    """Delete this file's meetings and put the city's settings back."""
    with db_cursor() as cur:
        cur.execute("SELECT adapter_config FROM municipalities WHERE slug = %s", (SLUG,))
        saved = cur.fetchone()["adapter_config"]
    _delete_seeded()
    yield
    _delete_seeded()
    with db_cursor() as cur:
        cur.execute(
            "UPDATE municipalities SET adapter_config = %s::jsonb WHERE slug = %s",
            (json.dumps(saved), SLUG),
        )


def _configure(**settings) -> None:
    with db_cursor() as cur:
        cur.execute(
            "UPDATE municipalities SET adapter_config = %s::jsonb WHERE slug = %s",
            (json.dumps({**BASE, **settings}), SLUG),
        )


def _meeting(external_id: str, meeting_date: date, agenda_url: str | None = None) -> RawMeeting:
    return RawMeeting(
        external_id=external_id,
        municipality_slug=SLUG,
        title=PREFIX + "City Council Meeting",
        meeting_date=meeting_date,
        meeting_type="council",
        agenda_url=agenda_url or f"https://example.com/agenda/{external_id}",
        minutes_url=None,
        video_url=None,
        source_url=f"https://example.com/event/{external_id}",
    )


class _Adapter:
    """Lists the meetings it was given; one item a meeting, or what `raises` says."""

    def __init__(self, meetings: list[RawMeeting], raises: dict[str, Exception] | None = None):
        self.meetings = meetings
        self.raises = raises or {}
        self.since_calls: list[date | None] = []
        self.fetched: list[str] = []

    def list_meetings(self, since=None):
        self.since_calls.append(since)
        return list(self.meetings)

    def fetch_agenda_items(self, meeting):
        self.fetched.append(meeting.external_id)
        if meeting.external_id in self.raises:
            raise self.raises[meeting.external_id]
        return [
            RawAgendaItem(
                external_id=f"{meeting.external_id}-1",
                meeting_external_id=meeting.external_id,
                item_number="1",
                title="40-1225 Declare the structure a public nuisance.",
                description=None,
                section=None,
                is_consent=False,
                sponsor=None,
            )
        ]


class _AdapterWithoutTimestamps(_Adapter):
    items_carry_video_timestamps = False


def _use(monkeypatch, adapter) -> None:
    from docket.services import ingest

    monkeypatch.setattr(ingest, "get_adapter", lambda adapter_class, slug, config: adapter)


def _marked() -> set[str]:
    """The external ids of this file's meetings whose agenda is marked fetched."""
    with db_cursor() as cur:
        cur.execute(
            """SELECT m.external_id
                 FROM meetings m JOIN processing_status ps ON ps.meeting_id = m.id
                WHERE m.title LIKE %s AND ps.agenda_items_scraped IS TRUE""",
            (PREFIX + "%",),
        )
        return {r["external_id"] for r in cur.fetchall()}


def _item_counts() -> dict[str, int]:
    with db_cursor() as cur:
        cur.execute(
            """SELECT m.external_id, count(a.id) AS n
                 FROM meetings m LEFT JOIN agenda_items a ON a.meeting_id = m.id
                WHERE m.title LIKE %s GROUP BY 1""",
            (PREFIX + "%",),
        )
        return {r["external_id"]: r["n"] for r in cur.fetchall()}


def _fetch_lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("Agenda fetches:")]


# Five meetings on five dates, listed in an order that is neither by date
# nor by id, so "newest first" and "the adapter's order" give different walks.
FIVE = [
    _meeting("900003", date(2026, 3, 3)),
    _meeting("900005", date(2026, 5, 5)),
    _meeting("900001", date(2026, 1, 6)),
    _meeting("900004", date(2026, 4, 7)),
    _meeting("900002", date(2026, 2, 3)),
]


def test_backlog_floor_is_passed_to_the_adapter_as_since(monkeypatch):
    from docket.services.ingest import ingest_municipality

    adapter = _Adapter([_meeting("900001", date(2026, 1, 6))])
    _use(monkeypatch, adapter)
    _configure(backlog_floor="2021-11-01")

    result = ingest_municipality(SLUG)

    assert result.errors == []
    assert adapter.since_calls == [date(2021, 11, 1)]
    # the floor alone sets no cap: the waiting meeting is fetched
    assert adapter.fetched == ["900001"]


def test_an_explicit_since_wins_over_the_floor(monkeypatch):
    from docket.services.ingest import ingest_municipality

    adapter = _Adapter([_meeting("900001", date(2026, 1, 6))])
    _use(monkeypatch, adapter)
    _configure(backlog_floor="2021-11-01")

    result = ingest_municipality(SLUG, since=date(2025, 1, 1))

    assert result.errors == []
    assert adapter.since_calls == [date(2025, 1, 1)]


def test_cap_fetches_the_newest_waiting_meetings_first(monkeypatch, caplog):
    from docket.services.ingest import ingest_municipality

    adapter = _Adapter(FIVE)
    _use(monkeypatch, adapter)
    _configure(agenda_fetch_cap=2)

    with caplog.at_level(logging.INFO, logger="docket.services.ingest"):
        result = ingest_municipality(SLUG)

    assert result.errors == []
    assert adapter.fetched == ["900005", "900004"]
    assert _marked() == {"900005", "900004"}
    assert result.agenda_items_inserted == 2
    assert result.meetings_found == 5
    assert _fetch_lines(caplog) == ["Agenda fetches: 2 of cap 2, 3 still waiting"]

    # a cap of 0 lists the meetings and fetches no agenda
    _delete_seeded()
    adapter = _Adapter(FIVE)
    _use(monkeypatch, adapter)
    _configure(agenda_fetch_cap=0)
    caplog.clear()

    with caplog.at_level(logging.INFO, logger="docket.services.ingest"):
        result = ingest_municipality(SLUG)

    assert result.errors == []
    assert result.meetings_inserted == 5
    assert adapter.fetched == []
    assert _marked() == set()
    assert _fetch_lines(caplog) == ["Agenda fetches: 0 of cap 0, 5 still waiting"]

    # two meetings on one date are taken in the adapter's order
    _delete_seeded()
    tied = [
        _meeting("900007", date(2026, 6, 2)),
        _meeting("900009", date(2026, 6, 9)),
        _meeting("900006", date(2026, 6, 2)),
        _meeting("900008", date(2026, 6, 9)),
    ]
    adapter = _Adapter(tied)
    _use(monkeypatch, adapter)
    _configure(agenda_fetch_cap=3)

    ingest_municipality(SLUG)

    assert adapter.fetched == ["900009", "900008", "900007"]


def test_a_second_run_takes_the_next_meetings(monkeypatch, caplog):
    from docket.services.ingest import ingest_municipality

    adapter = _Adapter(FIVE)
    _use(monkeypatch, adapter)
    _configure(agenda_fetch_cap=2)

    ingest_municipality(SLUG)
    adapter.fetched.clear()
    with caplog.at_level(logging.INFO, logger="docket.services.ingest"):
        result = ingest_municipality(SLUG)

    assert result.errors == []
    assert adapter.fetched == ["900003", "900002"]
    assert _marked() == {"900005", "900004", "900003", "900002"}
    assert _fetch_lines(caplog) == ["Agenda fetches: 2 of cap 2, 1 still waiting"]

    # the third run takes the one left and the fourth has nothing to take
    adapter.fetched.clear()
    ingest_municipality(SLUG)
    assert adapter.fetched == ["900001"]
    adapter.fetched.clear()
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="docket.services.ingest"):
        ingest_municipality(SLUG)
    assert adapter.fetched == []
    assert _fetch_lines(caplog) == ["Agenda fetches: 0 of cap 2, 0 still waiting"]


def test_a_meeting_not_ready_is_left_unmarked_unreported_and_uncounted(monkeypatch, caplog):
    from docket.services.ingest import ingest_municipality

    three = [
        _meeting("900001", date(2026, 1, 6)),
        _meeting("900003", date(2026, 3, 3)),
        _meeting("900002", date(2026, 2, 3)),
    ]
    adapter = _AdapterWithoutTimestamps(three, raises={"900003": AgendaNotReady("no agenda yet")})
    _use(monkeypatch, adapter)
    _configure(agenda_fetch_cap=2)

    with caplog.at_level(logging.INFO, logger="docket.services.ingest"):
        result = ingest_municipality(SLUG)

    assert result.errors == []
    assert result.success is True
    assert adapter.fetched == ["900003", "900002", "900001"]
    assert _marked() == {"900002", "900001"}
    assert _item_counts() == {"900001": 1, "900002": 1, "900003": 0}
    assert _fetch_lines(caplog) == ["Agenda fetches: 2 of cap 2, 1 still waiting"]

    # with no cap, the city's own order, the same: asked, unmarked, unreported
    adapter.fetched.clear()
    _configure()
    caplog.clear()

    with caplog.at_level(logging.INFO, logger="docket.services.ingest"):
        result = ingest_municipality(SLUG)

    assert result.errors == []
    assert adapter.fetched == ["900003"]
    assert _marked() == {"900002", "900001"}
    assert _fetch_lines(caplog) == []


def test_a_failed_fetch_is_reported_left_unmarked_and_counted(monkeypatch):
    from docket.services.ingest import ingest_municipality

    three = [
        _meeting("900001", date(2026, 1, 6)),
        _meeting("900003", date(2026, 3, 3)),
        _meeting("900002", date(2026, 2, 3)),
    ]
    adapter = _Adapter(three, raises={"900003": RuntimeError("the city did not answer")})
    _use(monkeypatch, adapter)
    _configure(agenda_fetch_cap=2)

    result = ingest_municipality(SLUG)

    assert result.errors == ["Agenda items for 900003: the city did not answer"]
    assert adapter.fetched == ["900003", "900002"]
    assert _marked() == {"900002"}
    assert result.agenda_items_inserted == 1


def test_a_stored_agenda_is_not_fetched_again_when_items_carry_no_timestamps(monkeypatch):
    from docket.services.ingest import ingest_municipality

    two = [_meeting("900002", date(2026, 2, 3)), _meeting("900001", date(2026, 1, 6))]

    # an adapter that says its items carry no video timestamps
    adapter = _AdapterWithoutTimestamps(two)
    _use(monkeypatch, adapter)
    _configure()
    ingest_municipality(SLUG)
    assert adapter.fetched == ["900002", "900001"]
    assert _marked() == {"900002", "900001"}

    adapter.fetched.clear()
    result = ingest_municipality(SLUG)
    assert result.errors == []
    assert adapter.fetched == []
    assert result.agenda_items_inserted == 0

    # the same under a cap
    _configure(agenda_fetch_cap=5)
    ingest_municipality(SLUG)
    assert adapter.fetched == []

    # an adapter that says nothing is asked again, as before: the stored item
    # has a number and no timestamp
    silent = _Adapter(two)
    _use(monkeypatch, silent)
    _configure()
    ingest_municipality(SLUG)
    assert silent.fetched == ["900002", "900001"]

    # and under a cap a stored agenda is asked again without counting: with a
    # cap of 1 the two stored agendas and the one waiting are all asked
    silent.fetched.clear()
    silent.meetings = [*two, _meeting("900000", date(2025, 12, 2))]
    _configure(agenda_fetch_cap=1)
    ingest_municipality(SLUG)
    assert silent.fetched == ["900002", "900001", "900000"]
    assert _marked() == {"900002", "900001", "900000"}


def test_a_listed_file_link_replaces_a_stored_page_link(monkeypatch):
    from docket.services.ingest import ingest_municipality

    adapter = _AdapterWithoutTimestamps([_meeting("900001", date(2026, 1, 6), agenda_url=PAGE_LINK)])
    _use(monkeypatch, adapter)
    _configure(agenda_fetch_cap=10)
    ingest_municipality(SLUG)

    def stored() -> str:
        with db_cursor() as cur:
            cur.execute("SELECT agenda_url FROM meetings WHERE title LIKE %s", (PREFIX + "%",))
            rows = cur.fetchall()
        assert len(rows) == 1
        return rows[0]["agenda_url"]

    assert stored() == PAGE_LINK

    adapter.meetings = [_meeting("900001", date(2026, 1, 6), agenda_url=FILE_LINK)]
    result = ingest_municipality(SLUG)

    assert result.errors == []
    assert result.meetings_updated == 1
    assert stored() == FILE_LINK


def test_a_city_with_neither_setting_ingests_as_before(monkeypatch, caplog):
    from docket.services.ingest import ingest_municipality

    adapter = _Adapter(FIVE)
    _use(monkeypatch, adapter)
    _configure()

    with caplog.at_level(logging.INFO, logger="docket.services.ingest"):
        result = ingest_municipality(SLUG)

    assert result.errors == []
    assert adapter.since_calls == [None]
    assert adapter.fetched == ["900003", "900005", "900001", "900004", "900002"]
    assert _marked() == {"900001", "900002", "900003", "900004", "900005"}
    assert result.agenda_items_inserted == 5
    assert _fetch_lines(caplog) == []


def test_a_bad_setting_is_reported_and_nothing_is_fetched(monkeypatch):
    from docket.services.ingest import ingest_municipality

    adapter = _Adapter(FIVE)
    _use(monkeypatch, adapter)
    _configure(agenda_fetch_cap="ten")

    result = ingest_municipality(SLUG)

    assert len(result.errors) == 1
    assert result.errors[0].startswith("Bad adapter_config for mobile: ")
    assert "agenda_fetch_cap" in result.errors[0]
    assert result.success is False
    assert (result.meetings_found, result.meetings_inserted, result.agenda_items_inserted) == (0, 0, 0)
    assert adapter.since_calls == []
    assert adapter.fetched == []

    # every other value that is not a date, or not a whole number of 0 or more
    from docket.services.ingest import _backlog_settings

    for bad in (
        {"agenda_fetch_cap": True},
        {"agenda_fetch_cap": False},
        {"agenda_fetch_cap": -1},
        {"agenda_fetch_cap": 2.0},
        {"agenda_fetch_cap": "10"},
        {"backlog_floor": "2021-13-01"},
        {"backlog_floor": "November 2021"},
        {"backlog_floor": 20211101},
    ):
        with pytest.raises(ValueError) as raised:
            _backlog_settings({**BASE, **bad})
        assert next(iter(bad)) in str(raised.value)
        _configure(**bad)
        result = ingest_municipality(SLUG)
        assert len(result.errors) == 1 and result.errors[0].startswith("Bad adapter_config for mobile: ")
        assert adapter.since_calls == []

    # and what a good row gives
    assert _backlog_settings(BASE) == (None, None)
    assert _backlog_settings({**BASE, "backlog_floor": "2021-11-01", "agenda_fetch_cap": 10}) == (date(2021, 11, 1), 10)
    assert _backlog_settings({"agenda_fetch_cap": 0}) == (None, 0)
    assert _backlog_settings({"backlog_floor": None, "agenda_fetch_cap": None}) == (None, None)
