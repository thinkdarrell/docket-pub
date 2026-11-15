"""docket.services.committee_documents: the daily refresh and the backfill.

``refresh_city`` runs the four steps in order (list, read, read again, attach)
for one city; ``refresh_all`` runs it for every active city whose metadata
names its committee pages; ``backfill`` is what the operator's script calls,
and with ``dry_run`` leaves nothing behind.

Nothing here reaches the network: the adapter's ``fetch_page`` and
``fetch_pdf`` are replaced in every test, and the PDFs they return are the
saved ones under ``tests/fixtures/committee_documents/``. Every document has
an address under ``/cdrefresh/`` and is deleted after, with the ``cdoc-``
meetings the calls create and the ``cdrefresh-`` meetings a test inserts. The
service's names are imported inside each test, so the file collects before
they exist. Runs in the services tier (DATABASE_URL names docket_test_*).

Plan `committee-documents`, M6.
"""

from __future__ import annotations

import html
import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from docket.db import db_cursor

FIXTURES = Path(__file__).parent.parent / "fixtures" / "committee_documents"
ROOT = "https://www.birminghamal.gov/government/city-council/council/council-committees-2025-2027/"
BUCKET = "https://s3.us-east-2.amazonaws.com/assets.birminghamal.gov/cdrefresh/"

BF_PAGE = {"committee": "Budget and Finance", "url": ROOT + "budget-finance-committee"}
PS_PAGE = {"committee": "Public Safety", "url": ROOT + "public-safety-committee"}
TI_PAGE = {"committee": "Transportation & Infrastructure", "url": ROOT + "transportation-infrastructure-committee"}

BF_MINUTES = (BUCKET + "bf-minutes.pdf", "BUDGET AND FINANCE COMMITTEE MEETING MINUTES, October 12, 2026.pdf",
              "OCTOBER 12, 2026")
PS_SCANNED = (BUCKET + "ps-agenda.pdf", "PUBLIC SAFETY COMMITTEE MEETING AGENDA, September 22, 2026.pdf",
              "SEPTEMBER 22, 2026")
TI_MINUTES = (BUCKET + "ti-minutes.pdf", "TRANSPORTATION COMMITTEE MEETING MINUTES, May 11, 2026.pdf",
              "MAY 11, 2026")

TODAY = date(2026, 11, 15)
TABLES = ("committee_documents", "committee_items", "meetings")


def _pdf(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _page(*listings: tuple[str, str, str]) -> str:
    """A committee page as the city serves one. Each listing is (address,
    listed name, heading)."""
    fragment = "".join(
        f'<h4>{html.escape(heading)}</h4>'
        f'<article class="media media--type-document" name="{html.escape(name)}" file="{html.escape(url)}"></article>'
        for url, name, heading in listings
    )
    data = {"props": {"pageProps": {"body": fragment}}}
    return f'<html><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></body></html>'


def _city(slug: str = "birmingham") -> int:
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug = %s", (slug,))
        return cur.fetchone()["id"]


def _delete_all() -> None:
    with db_cursor() as cur:
        cur.execute("DELETE FROM committee_documents")
        cur.execute("DELETE FROM meetings WHERE external_id LIKE 'cdoc-%' OR external_id LIKE 'cdrefresh-%'")


def _counts() -> tuple[int, ...]:
    with db_cursor() as cur:
        out = []
        for table in TABLES:
            cur.execute(f"SELECT count(*) AS n FROM {table}")
            out.append(cur.fetchone()["n"])
        return tuple(out)


def _documents() -> list[dict]:
    with db_cursor() as cur:
        cur.execute("SELECT * FROM committee_documents ORDER BY id")
        return [dict(r) for r in cur.fetchall()]


def _cdoc_meetings() -> list[str]:
    with db_cursor() as cur:
        cur.execute("SELECT external_id FROM meetings WHERE external_id LIKE 'cdoc-%' ORDER BY external_id")
        return [r["external_id"] for r in cur.fetchall()]


@pytest.fixture(autouse=True)
def clean():
    _delete_all()
    yield
    _delete_all()


@pytest.fixture
def net(monkeypatch):
    """The adapter's two fetches, replaced. ``net.pages`` maps a page address
    to its HTML (or to an exception to raise) and ``net.pdfs`` a PDF address
    to its bytes (or None); a page not in the table fails, as a page the city
    no longer serves would."""
    from docket.adapters import committee_documents as adapter

    class Net:
        pass

    state = Net()
    state.pages = {}
    state.pdfs = {}

    def answer(table):
        def fetch(url):
            value = table[url]
            if isinstance(value, Exception):
                raise value
            return value

        return fetch

    state.fetch_page = MagicMock(side_effect=answer(state.pages))
    state.fetch_pdf = MagicMock(side_effect=answer(state.pdfs))
    monkeypatch.setattr(adapter, "fetch_page", state.fetch_page)
    monkeypatch.setattr(adapter, "fetch_pdf", state.fetch_pdf)
    return state


@pytest.fixture
def budget(net):
    """The Budget and Finance page lists its minutes of 2026-10-12."""
    net.pages[BF_PAGE["url"]] = _page(BF_MINUTES)
    net.pdfs[BF_MINUTES[0]] = _pdf("bf_minutes_2026-10-12.pdf")
    return net


def _metadata(*pages: dict) -> dict:
    return {"committee_document_pages": list(pages)}


# --- refresh_city -------------------------------------------------------------


def test_refresh_city_lists_reads_and_attaches_in_one_call_and_a_second_call_does_nothing(budget):
    from docket.services import committee_documents as service

    first = service.refresh_city(_city(), _metadata(BF_PAGE), TODAY, None)

    assert (first.new_listings, first.read, first.reparsed) == (1, 1, 0)
    assert (first.attach.matched, first.attach.created) == (0, 1)
    (doc,) = _documents()
    assert (doc["status"], doc["kind"], doc["attached_by"]) == ("read", "minutes", "created")
    assert _cdoc_meetings() == ["cdoc-budget-finance-2026-10-12"]
    before = _counts()

    second = service.refresh_city(_city(), _metadata(BF_PAGE), TODAY, None)

    assert (second.new_listings, second.read, second.reparsed) == (0, 0, 0)
    assert (second.attach.matched, second.attach.created, second.attach.ambiguous) == (0, 0, 0)
    assert (second.attach.unattached_agendas, second.attach.unattached_minutes) == (0, 0)
    assert _counts() == before
    assert budget.fetch_pdf.call_count == 1, "a document already read is not fetched again"


def test_refresh_city_runs_the_four_steps_in_order(budget, monkeypatch):
    from docket.services import committee_documents as service

    calls = []
    for name in ("sync_listings", "read_pending", "reparse", "attach"):
        real = getattr(service, name)

        def spy(*args, _name=name, _real=real, **kwargs):
            calls.append((_name, args, kwargs))
            return _real(*args, **kwargs)

        monkeypatch.setattr(service, name, spy)

    service.refresh_city(_city(), _metadata(BF_PAGE), TODAY, 7)

    assert [c[0] for c in calls] == ["sync_listings", "read_pending", "reparse", "attach"]
    assert calls[0][1:] == ((_city(), [BF_PAGE]), {})
    limit = calls[1][2].get("limit", calls[1][1][-1])
    assert limit == 7
    assert TODAY in calls[3][1] or calls[3][2].get("today") == TODAY


def test_a_document_read_again_under_a_new_rule_is_attached_in_the_same_call(budget):
    """reparse comes before attach: a reading mended by a rule change finds
    its meeting on the run that mends it."""
    from docket.services import committee_documents as service

    service.refresh_city(_city(), _metadata(BF_PAGE), TODAY, None)
    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE external_id LIKE 'cdoc-%'")
        cur.execute("UPDATE committee_documents SET kind = NULL, meeting_date = NULL, parser_version = 0")

    report = service.refresh_city(_city(), _metadata(BF_PAGE), TODAY, None)

    assert (report.new_listings, report.read, report.reparsed) == (0, 0, 1)
    assert report.attach.created == 1
    (doc,) = _documents()
    assert (doc["kind"], doc["meeting_date"], doc["attached_by"]) == ("minutes", date(2026, 10, 12), "created")
    assert budget.fetch_pdf.call_count == 1, "reading again fetches nothing"


def test_a_read_limit_of_one_reads_one_document_per_call(net):
    from docket.services import committee_documents as service

    net.pages[BF_PAGE["url"]] = _page(BF_MINUTES)
    net.pages[PS_PAGE["url"]] = _page(PS_SCANNED)
    net.pdfs[BF_MINUTES[0]] = _pdf("bf_minutes_2026-10-12.pdf")
    net.pdfs[PS_SCANNED[0]] = _pdf("ps_agenda_2026-09-22_scanned.pdf")
    metadata = _metadata(BF_PAGE, PS_PAGE)

    first = service.refresh_city(_city(), metadata, TODAY, 1)
    assert (first.new_listings, first.read) == (2, 1)
    assert net.fetch_pdf.call_count == 1
    assert sorted(d["status"] for d in _documents()) == ["listed", "read"]

    second = service.refresh_city(_city(), metadata, TODAY, 1)
    assert (second.new_listings, second.read) == (0, 1)
    assert net.fetch_pdf.call_count == 2
    assert sorted(d["status"] for d in _documents()) == ["no_text", "read"]

    third = service.refresh_city(_city(), metadata, TODAY, 1)
    assert third.read == 0
    assert net.fetch_pdf.call_count == 2


def test_no_read_limit_reads_every_pending_document(net):
    from docket.services import committee_documents as service

    net.pages[BF_PAGE["url"]] = _page(BF_MINUTES)
    net.pages[PS_PAGE["url"]] = _page(PS_SCANNED)
    net.pdfs[BF_MINUTES[0]] = _pdf("bf_minutes_2026-10-12.pdf")
    net.pdfs[PS_SCANNED[0]] = _pdf("ps_agenda_2026-09-22_scanned.pdf")

    report = service.refresh_city(_city(), _metadata(BF_PAGE, PS_PAGE), TODAY, None)

    assert report.read == 2
    # The scanned agenda has no meeting and, being an agenda, makes none.
    assert (report.attach.created, report.attach.unattached_agendas) == (1, 1)


def test_a_page_that_fails_is_skipped_and_the_others_are_stored(budget):
    from docket.services import committee_documents as service

    budget.pages[PS_PAGE["url"]] = RuntimeError("503")

    report = service.refresh_city(_city(), _metadata(PS_PAGE, BF_PAGE), TODAY, None)

    assert (report.new_listings, report.read) == (1, 1)
    assert [d["url"] for d in _documents()] == [BF_MINUTES[0]]
    assert budget.fetch_page.call_count == 2


def test_when_every_page_fails_refresh_city_raises_and_no_later_step_runs(net, monkeypatch):
    from docket.services import committee_documents as service

    later = MagicMock()
    for name in ("read_pending", "reparse", "attach"):
        monkeypatch.setattr(service, name, later)
    net.pages[BF_PAGE["url"]] = RuntimeError("503")

    with pytest.raises(RuntimeError, match="gave no listing"):
        service.refresh_city(_city(), _metadata(BF_PAGE), TODAY, None)

    later.assert_not_called()


def test_a_city_with_no_pages_configured_fetches_nothing(net):
    from docket.services import committee_documents as service

    report = service.refresh_city(_city("mobile"), {}, TODAY, None)

    assert (report.new_listings, report.read, report.reparsed, report.attach.created) == (0, 0, 0, 0)
    net.fetch_page.assert_not_called()


# --- refresh_all ---------------------------------------------------------------


@pytest.fixture
def mobile_pages():
    """Mobile given one committee page for the length of a test."""
    page = {"committee": "Transportation & Infrastructure", "url": "https://www.birminghamal.gov/cdrefresh/mobile"}
    with db_cursor() as cur:
        cur.execute(
            "UPDATE municipalities SET metadata = jsonb_set(metadata, '{committee_document_pages}', %s::jsonb) "
            "WHERE slug = 'mobile'",
            (json.dumps([page]),),
        )
    yield page
    with db_cursor() as cur:
        cur.execute("UPDATE municipalities SET metadata = metadata - 'committee_document_pages', active = TRUE "
                    "WHERE slug = 'mobile'")


def test_refresh_all_runs_every_city_that_names_its_pages_with_a_limit_of_twenty_five(budget, monkeypatch):
    from docket.services import committee_documents as service

    limits = []
    real = service.read_pending

    def spy(municipality_id, limit):
        limits.append((municipality_id, limit))
        return real(municipality_id, limit)

    monkeypatch.setattr(service, "read_pending", spy)

    assert service.refresh_all(TODAY) == 1

    assert limits == [(_city(), 25)]
    # Birmingham's eight pages were asked for, seven failed, and the one that answered was stored.
    assert budget.fetch_page.call_count == 8
    assert {c.args[0] for c in budget.fetch_page.call_args_list} >= {BF_PAGE["url"], PS_PAGE["url"], TI_PAGE["url"]}
    assert _cdoc_meetings() == ["cdoc-budget-finance-2026-10-12"]
    (doc,) = _documents()
    assert doc["municipality_id"] == _city()


def test_refresh_all_passes_over_a_city_that_is_not_active(budget, mobile_pages):
    from docket.services import committee_documents as service

    budget.pages[mobile_pages["url"]] = _page(TI_MINUTES)
    budget.pdfs[TI_MINUTES[0]] = _pdf("ti_minutes_2026-05-11.pdf")
    with db_cursor() as cur:
        cur.execute("UPDATE municipalities SET active = FALSE WHERE slug = 'mobile'")

    assert service.refresh_all(TODAY) == 1

    assert mobile_pages["url"] not in {c.args[0] for c in budget.fetch_page.call_args_list}
    assert {d["municipality_id"] for d in _documents()} == {_city()}


def test_a_city_that_fails_does_not_stop_the_next_and_the_call_then_raises(net, mobile_pages):
    """Birmingham comes first by slug and every page of it fails; Mobile is
    still read, and the failure is raised at the end so the task reports it."""
    from docket.services import committee_documents as service

    net.pages[mobile_pages["url"]] = _page(TI_MINUTES)
    net.pdfs[TI_MINUTES[0]] = _pdf("ti_minutes_2026-05-11.pdf")

    with pytest.raises(RuntimeError, match="birmingham"):
        service.refresh_all(TODAY)

    (doc,) = _documents()
    assert (doc["municipality_id"], doc["status"], doc["attached_by"]) == (_city("mobile"), "read", "created")


# --- backfill ------------------------------------------------------------------


def test_backfill_writes_and_reports_what_it_did(budget):
    from docket.services import committee_documents as service

    before = _counts()

    report = service.backfill("birmingham", TODAY)

    assert report.dry_run is False and report.tables_created is False
    assert (report.refresh.new_listings, report.refresh.read, report.refresh.attach.created) == (1, 1, 1)
    assert [(m["external_id"], m["title"], m["meeting_date"]) for m in report.created_meetings] == [
        ("cdoc-budget-finance-2026-10-12", "Budget and Finance Committee Meeting", date(2026, 10, 12))
    ]
    assert report.documents == [("read", "minutes", 1)]
    assert report.date_sources == {"header": 1, "heading": 0, "none": 0}
    assert report.listing_disagrees == 0
    assert dict(report.items_by_category) == {"minutes_approved": 1, "recommended_consent": 9, "recommended": 2}
    assert [n for _, n in report.items_by_category] == [9, 2, 1], "the commonest category first"
    after = _counts()
    assert (after[0] - before[0], after[1] - before[1], after[2] - before[2]) == (1, 12, 1)


def test_a_dry_run_reports_the_same_and_leaves_nothing_behind(budget):
    from docket.services import committee_documents as service

    before = _counts()

    report = service.backfill("birmingham", TODAY, dry_run=True)

    assert report.dry_run is True
    assert (report.refresh.new_listings, report.refresh.read, report.refresh.attach.created) == (1, 1, 1)
    assert [m["external_id"] for m in report.created_meetings] == ["cdoc-budget-finance-2026-10-12"]
    assert report.documents == [("read", "minutes", 1)]
    assert sum(n for _, n in report.items_by_category) == 12
    assert _counts() == before
    assert _documents() == [] and _cdoc_meetings() == []

    # The dry run has ended: the next call writes again.
    service.backfill("birmingham", TODAY)
    assert _cdoc_meetings() == ["cdoc-budget-finance-2026-10-12"]


def test_a_dry_run_rolls_back_when_the_run_fails_too(net):
    from docket.services import committee_documents as service

    before = _counts()
    with pytest.raises(RuntimeError, match="gave no listing"):
        service.backfill("birmingham", TODAY, dry_run=True)
    assert _counts() == before

    net.pages[BF_PAGE["url"]] = _page(BF_MINUTES)
    net.pdfs[BF_MINUTES[0]] = _pdf("bf_minutes_2026-10-12.pdf")
    service.backfill("birmingham", TODAY)
    assert len(_documents()) == 1, "after a failed dry run the service commits again"


def test_in_a_dry_run_a_document_that_cannot_be_stored_does_not_undo_the_others(net, monkeypatch):
    """One transaction holds the whole dry run, so a statement the database
    refuses must be undone alone, as its own transaction would have been."""
    from docket.services import committee_documents as service

    net.pages[BF_PAGE["url"]] = _page(BF_MINUTES, TI_MINUTES)
    net.pdfs[BF_MINUTES[0]] = _pdf("bf_minutes_2026-10-12.pdf")
    net.pdfs[TI_MINUTES[0]] = _pdf("ti_minutes_2026-05-11.pdf")
    real = service._store_reading

    def refuse_the_first(cur, row, text):
        if row["url"] == BF_MINUTES[0]:
            cur.execute("UPDATE committee_documents SET status = 'not a status' WHERE id = %s", (row["id"],))
        return real(cur, row, text)

    monkeypatch.setattr(service, "_store_reading", refuse_the_first)

    report = service.backfill("birmingham", TODAY, dry_run=True)

    assert (report.refresh.new_listings, report.refresh.read) == (2, 1)
    assert sorted(report.documents) == [("fetch_failed", None, 1), ("read", "minutes", 1)]
    assert [m["external_id"] for m in report.created_meetings] == ["cdoc-transportation-infrastructure-2026-05-11"]
    assert _documents() == []


def test_backfill_limit_bounds_the_documents_read(net):
    from docket.services import committee_documents as service

    net.pages[BF_PAGE["url"]] = _page(BF_MINUTES, TI_MINUTES)
    net.pdfs[BF_MINUTES[0]] = _pdf("bf_minutes_2026-10-12.pdf")
    net.pdfs[TI_MINUTES[0]] = _pdf("ti_minutes_2026-05-11.pdf")

    report = service.backfill("birmingham", TODAY, limit=1)

    assert (report.refresh.new_listings, report.refresh.read) == (2, 1)
    assert sorted(report.documents) == [("listed", None, 1), ("read", "minutes", 1)]


def test_backfill_refuses_a_city_it_does_not_know_or_that_names_no_pages(net):
    from docket.services import committee_documents as service

    with pytest.raises(ValueError, match="no city"):
        service.backfill("atlantis", TODAY)
    with pytest.raises(ValueError, match="committee_document_pages"):
        service.backfill("mobile", TODAY)
    net.fetch_page.assert_not_called()


def test_the_per_committee_table_counts_meetings_from_2026_on(budget):
    """One row per canonical committee, in the canonical order. Budget and
    Finance has: the meeting the minutes create (minutes, items, a document
    and no recording), a recorded meeting with no document, and one in 2025
    that is not counted; a hidden meeting and a council meeting are no
    committee's."""
    from docket.adapters import committee_documents as adapter
    from docket.services import committee_documents as service

    def meeting(n, day, body, *, video=None, hidden=False, meeting_type="committee"):
        with db_cursor() as cur:
            cur.execute(
                """INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type, body_name,
                                         is_hidden, video_url)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (_city(), f"cdrefresh-{n}", body, day, meeting_type, body, hidden, video),
            )

    meeting(1, date(2026, 9, 14), "Budget & Finance Committee", video="https://youtu.be/x")
    meeting(2, date(2025, 12, 8), "Budget and Finance Committee", video="https://youtu.be/y")
    meeting(3, date(2026, 9, 15), "Budget and Finance Committee", video="https://youtu.be/z", hidden=True)
    meeting(4, date(2026, 9, 16), "Budget and Finance Committee", video="https://youtu.be/w", meeting_type="council")
    meeting(5, date(2026, 1, 1), "Public Safety Committee")

    report = service.backfill("birmingham", TODAY)

    assert [row["committee"] for row in report.committees] == list(adapter.COMMITTEES)
    by_name = {row["committee"]: row for row in report.committees}
    assert by_name["Budget and Finance"] == {
        "committee": "Budget and Finance", "meetings": 2, "with_agenda": 0, "with_minutes": 1, "with_items": 1,
        "document_no_video": 1, "video_no_document": 1,
    }
    assert by_name["Public Safety"] == {
        "committee": "Public Safety", "meetings": 1, "with_agenda": 0, "with_minutes": 0, "with_items": 0,
        "document_no_video": 0, "video_no_document": 0,
    }
    assert by_name["Arts and Parks"]["meetings"] == 0


def test_the_per_committee_table_counts_an_agenda_and_minutes_that_hold_no_item(net):
    from docket.services import committee_documents as service

    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type, body_name,
                                     video_url)
               VALUES (%s, 'cdrefresh-9', 'Public Safety Committee', '2026-09-22', 'committee',
                       'Public Safety Committee', 'https://youtu.be/v')""",
            (_city(),),
        )
    net.pages[PS_PAGE["url"]] = _page(PS_SCANNED)
    net.pdfs[PS_SCANNED[0]] = _pdf("ps_agenda_2026-09-22_scanned.pdf")

    report = service.backfill("birmingham", TODAY)

    assert report.refresh.attach.matched == 1
    assert report.documents == [("no_text", "agenda", 1)]
    assert report.date_sources == {"header": 0, "heading": 1, "none": 0}
    row = {r["committee"]: r for r in report.committees}["Public Safety"]
    assert (row["meetings"], row["with_agenda"], row["with_minutes"], row["with_items"]) == (1, 1, 0, 0)
    assert (row["document_no_video"], row["video_no_document"]) == (0, 0)


# --- the worker task ---------------------------------------------------------


def test_the_worker_task_refreshes_every_city_as_of_today_in_the_workers_timezone(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from docket import config
    from docket.services import committee_documents as service
    from docket.worker import tasks

    refresh_all = MagicMock(return_value=1)
    monkeypatch.setattr(service, "refresh_all", refresh_all)

    tasks._do_committee_documents()

    refresh_all.assert_called_once_with(datetime.now(ZoneInfo(config.WORKER_TIMEZONE)).date())
    assert tasks.TASKS["committee_documents"] is tasks.task_committee_documents
