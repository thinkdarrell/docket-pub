"""Ingest keeps a flagged city's hearings current: stage 3c of `ingest_municipality`.

No test here reaches a city's site. `docket.services.ingest.get_adapter` is
replaced by an adapter that lists one meeting, five days back, and one
agenda item whose title is a saved production title
(``tests/fixtures/hearings/birmingham_titles.json``, item 63108, which sets a
zoning hearing for 2026-12-08). The whole of `ingest_municipality` then runs
against the throwaway database (DATABASE_URL names docket_test_*). The
meeting's title begins ``HEARINGS_TEST_``; it, and the hearings its item was
linked to, are deleted before and after every test.

Plan `birmingham-coming-up`, M3.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

import pytest

from docket.db import db_cursor
from docket.models.protocol import RawAgendaItem, RawMeeting

FIXTURE = Path(__file__).parent.parent / "fixtures" / "hearings" / "birmingham_titles.json"
TITLES = {row["id"]: row["title"] for row in json.loads(FIXTURE.read_text())}
PREFIX = "HEARINGS_TEST_"
EXTERNAL_ID = "event-990001"
URL = "https://example.com/AgendaViewer.php?view_id=2&event_id=990001"


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


class _Adapter:
    """One upcoming meeting with one agenda item, and nothing else."""

    def __init__(self, slug: str, item_title: str, minutes_url: str | None = None):
        self.municipality_slug = slug
        self._item_title = item_title
        self._minutes_url = minutes_url

    def list_meetings(self, since=None):
        return [
            RawMeeting(
                external_id=EXTERNAL_ID,
                municipality_slug=self.municipality_slug,
                title=PREFIX + "Regular meeting",
                meeting_date=date.today() - timedelta(days=5),
                meeting_type="council",
                agenda_url=URL,
                minutes_url=self._minutes_url,
                video_url=None,
                source_url=URL,
            )
        ]

    def fetch_agenda_items(self, meeting):
        return [
            RawAgendaItem(
                external_id="hearings-test-item-1",
                meeting_external_id=meeting.external_id,
                item_number="1",
                title=self._item_title,
                description=None,
                section=None,
                is_consent=False,
                sponsor=None,
            )
        ]


@pytest.fixture
def adapter(monkeypatch):
    """Replace ingest's adapter for any city with the one above."""
    from docket.services import ingest

    monkeypatch.setattr(ingest, "get_adapter", lambda adapter_class, slug, config: _Adapter(slug, TITLES[63108]))


def _stored_item() -> dict | None:
    with db_cursor() as cur:
        cur.execute(
            """SELECT ai.id, ai.title, mt.id AS meeting_id
                 FROM agenda_items ai JOIN meetings mt ON mt.id = ai.meeting_id
                WHERE mt.title LIKE %s""",
            (PREFIX + "%",),
        )
        rows = cur.fetchall()
    assert len(rows) <= 1
    return dict(rows[0]) if rows else None


def _hearings_of(item_id: int) -> list[dict]:
    with db_cursor() as cur:
        cur.execute(
            """SELECT h.hearing_date, h.kind
                 FROM public_hearings h JOIN public_hearing_items phi ON phi.hearing_id = h.id
                WHERE phi.agenda_item_id = %s""",
            (item_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def test_ingest_stores_the_hearing_a_new_item_sets(adapter):
    from docket.services.ingest import ingest_municipality

    result = ingest_municipality("birmingham")

    assert result.errors == []
    assert result.agenda_items_inserted == 1
    item = _stored_item()
    assert item is not None
    assert _hearings_of(item["id"]) == [{"hearing_date": date(2026, 12, 8), "kind": "zoning"}]


def test_a_failure_of_the_hearings_step_is_reported_and_stops_nothing(adapter, monkeypatch):
    from docket.services import hearings
    from docket.services.ingest import ingest_municipality

    def broken(municipality_id):
        raise RuntimeError("the hearings step broke")

    monkeypatch.setattr(hearings, "refresh_recent", broken)

    result = ingest_municipality("birmingham")

    assert [e for e in result.errors if e.startswith("Hearings:")] == ["Hearings: the hearings step broke"]
    assert result.success is False
    assert result.meetings_inserted == 1
    assert result.agenda_items_inserted == 1
    item = _stored_item()
    assert item is not None and item["title"] == TITLES[63108]
    assert _hearings_of(item["id"]) == []


def test_ingest_logs_the_hearing_counts_of_a_flagged_city(adapter, caplog):
    from docket.services.ingest import ingest_municipality

    with caplog.at_level(logging.INFO, logger="docket.services.ingest"):
        ingest_municipality("birmingham")

    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Hearings:")]
    assert len(lines) == 1
    # Other Birmingham rows of the last 120 days may be in the database, so
    # the counts are at least this run's one item and one hearing.
    words = dict(word.split("=") for word in lines[0].removeprefix("Hearings: ").split())
    assert set(words) == {"matched", "dated", "undated", "hearings", "created", "linked"}
    assert int(words["matched"]) >= 1 and int(words["dated"]) >= 1 and int(words["hearings"]) >= 1
    assert int(words["created"]) >= 1 and int(words["linked"]) >= 1


def test_ingest_of_a_city_without_the_flag_stores_no_hearing_and_reports_no_error(adapter, caplog):
    from docket.services.ingest import ingest_municipality

    with caplog.at_level(logging.INFO, logger="docket.services.ingest"):
        result = ingest_municipality("mobile")

    assert [e for e in result.errors if e.startswith("Hearings:")] == []
    item = _stored_item()
    assert item is not None
    assert _hearings_of(item["id"]) == []
    assert [r.getMessage() for r in caplog.records if r.getMessage().startswith("Hearings:")] == []


def test_the_hearings_step_runs_after_the_meeting_types_and_before_the_votes(monkeypatch):
    """Stage 3c sits between 3b and 4. The meeting has a minutes link here, so the vote stage is reached."""
    from docket.services import hearings, ingest

    monkeypatch.setattr(
        ingest, "get_adapter", lambda adapter_class, slug, config: _Adapter(slug, TITLES[63108], minutes_url=URL)
    )

    order: list[str] = []
    real_refresh = hearings.refresh_recent
    real_resolve = ingest.meeting_types.resolve_and_store

    def refresh(municipality_id):
        order.append("hearings")
        return real_refresh(municipality_id)

    def resolve(municipality_id, ids):
        order.append("meeting types")
        return real_resolve(municipality_id, ids)

    def votes(municipality_id, adapter, raw_meeting):
        order.append("votes")
        return 0

    def sweep(municipality_id):
        order.append("adoptions")
        return []

    monkeypatch.setattr(hearings, "refresh_recent", refresh)
    monkeypatch.setattr(ingest.meeting_types, "resolve_and_store", resolve)
    monkeypatch.setattr(ingest, "_ingest_votes", votes)
    monkeypatch.setattr("docket.services.minutes_adoption.sweep_adoptions", sweep)

    ingest.ingest_municipality("birmingham")

    assert order == ["meeting types", "hearings", "votes", "adoptions"]


# --- rules pinned after the removal check ------------------------------------


def test_the_log_line_holds_each_count_of_the_report_under_its_own_name(adapter, monkeypatch, caplog):
    from docket.services import hearings
    from docket.services.ingest import ingest_municipality

    report = hearings.HearingReport(matched=6, dated=5, undated=1, hearings=4, created=3, linked=2)
    monkeypatch.setattr(hearings, "refresh_recent", lambda municipality_id: report)

    with caplog.at_level(logging.INFO, logger="docket.services.ingest"):
        ingest_municipality("birmingham")

    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Hearings:")]
    assert lines == ["Hearings: matched=6 dated=5 undated=1 hearings=4 created=3 linked=2"]
