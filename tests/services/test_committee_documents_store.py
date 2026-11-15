"""docket.services.committee_documents: listing, fetching, reading and storing.

Nothing here reaches the network: the adapter's ``fetch_page`` and
``fetch_pdf`` are replaced in every test, and the PDFs and the committee page
they return are the saved ones under ``tests/fixtures/committee_documents/``.
Every row is stored under Birmingham (one under Mobile) with an address under
``/cdstore/`` and deleted after; the throwaway database holds no other
committee document. An autouse fixture counts ``agenda_items`` and ``votes``
before and after every test: this source writes to neither. The service's
names are imported inside each test, so the file collects before the service
exists. Runs in the services tier (DATABASE_URL names docket_test_*).

Plan `committee-documents`, M3.
"""

from __future__ import annotations

import hashlib
import html
import json
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from docket.db import db_cursor

FIXTURES = Path(__file__).parent.parent / "fixtures" / "committee_documents"
ROOT = "https://www.birminghamal.gov/government/city-council/council/council-committees-2025-2027/"
BUCKET = "https://s3.us-east-2.amazonaws.com/assets.birminghamal.gov/cdstore/"

PZ_PAGE = {"committee": "Planning & Zoning", "url": ROOT + "planning-zoning-committee"}
BF_PAGE = {"committee": "Budget and Finance", "url": ROOT + "budget-finance-committee"}
PS_PAGE = {"committee": "Public Safety", "url": ROOT + "public-safety-committee"}
ED_PAGE = {
    "committee": "Economic and Workforce Development / Tourism",
    "url": ROOT + "economic-workforce-development-tourism-committee",
}

BF_MINUTES = (BUCKET + "bf-minutes.pdf", "BUDGET AND FINANCE COMMITTEE MEETING MINUTES, October 12, 2026.pdf",
              "OCTOBER 12, 2026")
PS_SCANNED = (BUCKET + "ps-agenda.pdf", "PUBLIC SAFETY COMMITTEE MEETING AGENDA, September 22, 2026.pdf",
              "SEPTEMBER 22, 2026")

ITEM_COLUMNS = ("position, heading_label, heading_text, owns_heading, group_text, name, body, action_text, "
                "action_category, moved_by, seconded_by")


def _pdf(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _page(*listings: tuple[str, str, str]) -> str:
    """A committee page as the city serves one: the listings as a string of
    HTML inside the page's ``__NEXT_DATA__`` JSON. Each listing is (address,
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


def _count(table: str) -> int:
    with db_cursor() as cur:
        cur.execute(f"SELECT count(*) AS n FROM {table}")
        return cur.fetchone()["n"]


def _documents(where: str = "TRUE", params: tuple = ()) -> list[dict]:
    with db_cursor() as cur:
        cur.execute(f"SELECT * FROM committee_documents WHERE {where} ORDER BY id", params)
        return [dict(r) for r in cur.fetchall()]


def _document(url: str) -> dict:
    (row,) = _documents("url = %s", (url,))
    return row


def _items(document_id: int) -> list[tuple]:
    with db_cursor() as cur:
        cur.execute(f"SELECT {ITEM_COLUMNS} FROM committee_items WHERE document_id = %s ORDER BY position",
                    (document_id,))
        return [tuple(r.values()) for r in cur.fetchall()]


@pytest.fixture(autouse=True)
def only_these_tables():
    """Clean before and after, and the counts of the two tables this source
    must never write are the same after every test as before it."""
    _delete_all()
    before = (_count("agenda_items"), _count("votes"))
    yield
    assert (_count("agenda_items"), _count("votes")) == before, "a committee document wrote council business"
    _delete_all()


@pytest.fixture
def net(monkeypatch):
    """The adapter's two fetches, replaced. ``net.pages`` maps a page address
    to its HTML (or to an exception to raise) and ``net.pdfs`` a PDF address
    to its bytes (or None, or an exception); the mocks record their calls."""
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
    monkeypatch.setattr(adapter, "fetch_page", state.fetch_page, raising=False)
    monkeypatch.setattr(adapter, "fetch_pdf", state.fetch_pdf, raising=False)
    return state


def _listed(net, page: dict, *listings: tuple[str, str, str], city: int | None = None) -> None:
    """Put the listings on the page and sync it, so each is a ``listed`` row."""
    from docket.services import committee_documents as service

    net.pages[page["url"]] = _page(*listings)
    service.sync_listings(city or _city(), [page])


# --- sync_listings ---------------------------------------------------------


def test_syncing_the_planning_page_stores_27_listings_and_a_second_sync_stores_none(net):
    from docket.services import committee_documents as service

    net.pages[PZ_PAGE["url"]] = (FIXTURES / "page_planning_zoning.html").read_text()

    assert service.sync_listings(_city(), [PZ_PAGE]) == 27
    first = _documents()
    assert len(first) == 27
    assert {r["municipality_id"] for r in first} == {_city()}
    assert {(r["status"], r["page_committee"], r["page_url"], r["fetch_attempts"]) for r in first} == {
        ("listed", "Planning & Zoning", PZ_PAGE["url"], 0)
    }
    top = first[0]
    assert top["listed_heading"] == "OCTOBER 13, 2026"
    assert top["listed_name"] == "PLANNING AND ZONING COMMITTEE MEETING AGENDA, October 13, 2026.pdf"
    assert top["url"].startswith("https://s3.us-east-2.amazonaws.com/assets.birminghamal.gov/")
    assert top["first_seen_at"] == top["last_seen_at"]

    assert service.sync_listings(_city(), [PZ_PAGE]) == 0
    second = _documents()
    assert len(second) == 27
    assert [(r["id"], r["url"], r["first_seen_at"]) for r in second] == [
        (r["id"], r["url"], r["first_seen_at"]) for r in first
    ], "no first_seen_at changed"
    assert all(b["last_seen_at"] > a["last_seen_at"] for a, b in zip(first, second)), "each was seen again"


def test_a_known_address_takes_the_new_name_and_heading_and_keeps_everything_else(net):
    from docket.services import committee_documents as service

    url = BUCKET + "moved.pdf"
    _listed(net, BF_PAGE, (url, "AGENDA, June 22 & 23, 2026.pdf", "JUNE 22, 2026"))
    with db_cursor() as cur:
        cur.execute("UPDATE committee_documents SET status = 'read', kind = 'agenda', fetch_attempts = 2, "
                    "parser_version = 1, text = 'the text' WHERE url = %s", (url,))
    before = _document(url)
    assert before["listed_name"] == "AGENDA, June 22 & 23, 2026.pdf", "the entity in the page's attribute is decoded"

    # The same address, now on another committee's page under another heading.
    net.pages[PS_PAGE["url"]] = _page((url, "AGENDA (corrected).pdf", "JUNE 23, 2026"))
    assert service.sync_listings(_city(), [PS_PAGE]) == 0

    after = _document(url)
    assert (after["listed_name"], after["listed_heading"]) == ("AGENDA (corrected).pdf", "JUNE 23, 2026")
    assert after["last_seen_at"] > before["last_seen_at"]
    unchanged = set(before) - {"listed_name", "listed_heading", "last_seen_at"}
    assert {k: after[k] for k in unchanged} == {k: before[k] for k in unchanged}
    assert (after["page_committee"], after["page_url"], after["status"]) == ("Budget and Finance", BF_PAGE["url"],
                                                                              "read")


def test_the_same_address_under_another_city_is_another_row(net):
    from docket.services import committee_documents as service

    url = BUCKET + "shared.pdf"
    _listed(net, BF_PAGE, (url, "A.pdf", "JUNE 22, 2026"))
    assert service.sync_listings(_city("mobile"), [BF_PAGE]) == 1
    assert sorted(r["municipality_id"] for r in _documents("url = %s", (url,))) == sorted([_city(), _city("mobile")])


def test_a_page_that_fails_is_skipped_and_the_others_are_stored(net):
    import requests

    from docket.services import committee_documents as service

    net.pages[BF_PAGE["url"]] = requests.ConnectionError("no route")
    net.pages[PS_PAGE["url"]] = _page((BUCKET + "a.pdf", "A.pdf", "JUNE 22, 2026"),
                                      (BUCKET + "b.pdf", "B.pdf", "JUNE 22, 2026"))
    net.pages[ED_PAGE["url"]] = "<html><body>the site's error page</body></html>"

    assert service.sync_listings(_city(), [BF_PAGE, PS_PAGE, ED_PAGE]) == 2
    assert [r["page_committee"] for r in _documents()] == ["Public Safety", "Public Safety"]
    assert net.fetch_page.call_count == 3, "a failed page does not stop the pages after it"


def test_sync_raises_only_when_every_page_failed(net):
    import requests

    from docket.services import committee_documents as service

    net.pages[BF_PAGE["url"]] = requests.ConnectionError("no route")
    net.pages[PS_PAGE["url"]] = "<html><body>no listing here</body></html>"
    with pytest.raises(RuntimeError, match="2 of 2"):
        service.sync_listings(_city(), [BF_PAGE, PS_PAGE])
    assert _documents() == []

    assert service.sync_listings(_city(), []) == 0, "a city with no page configured has nothing to fail"


# --- read_pending and _read ------------------------------------------------


def test_reading_the_budget_minutes_stores_the_document_and_its_twelve_items(net):
    from docket.services import committee_documents as service

    _listed(net, BF_PAGE, BF_MINUTES)
    pdf = _pdf("bf_minutes_2026-10-12.pdf")
    net.pdfs[BF_MINUTES[0]] = pdf

    assert service.read_pending(_city(), 10) == 1

    row = _document(BF_MINUTES[0])
    assert (row["status"], row["kind"], row["meeting_date"], row["date_source"]) == (
        "read", "minutes", date(2026, 10, 12), "header")
    assert row["committees"] == ["Budget and Finance"]
    assert (row["listing_disagrees"], row["special"], row["work_session"]) == (False, False, False)
    assert row["pdf_sha256"] == hashlib.sha256(pdf).hexdigest()
    assert row["fetched_at"] is not None and row["fetched_at"] >= row["first_seen_at"]
    assert row["fetch_attempts"] == 0
    assert row["parser_version"] == service.PARSER_VERSION == 1
    assert "BUDGET AND FINANCE COMMITTEE" in row["text"].upper() and "Friends of Avondale Park" in row["text"]
    assert row["present"] == "Woods, Alexander, Smitherman, O’Quinn"
    assert row["trailing_lines"] == 8
    assert (row["meeting_id"], row["attached_by"]) == (None, None), "attaching is not this step's"

    items = _items(row["id"])
    assert [item[0] for item in items] == list(range(1, 13)), "numbered from 1 in the minutes' order"
    assert [item[5] for item in items][:2] == ["Approval of the Minutes – September 28, 2026",
                                               "Consideration of the Consent Agenda"]
    (avondale,) = [item for item in items if item[5] == "Friends of Avondale Park"]
    position, label, heading_text, owns, group, name, body, action_text, category, moved, seconded = avondale
    assert (position, label, heading_text, owns, group) == (5, "6)", "Friends of Avondale Park", True, None)
    assert "$4,000" in body
    assert action_text.endswith("Item Recommended to the City Council Consent Agenda.")
    assert (category, moved, seconded) == ("recommended_consent", "Alexander", "Woods")

    # Nothing is left to read, and nothing is fetched again.
    assert service.read_pending(_city(), 10) == 0
    assert net.fetch_pdf.call_count == 1


def test_a_group_is_stored_as_group_text(net):
    from docket.services import committee_documents as service

    listing = (BUCKET + "ps-minutes.pdf", "PUBLIC SAFETY COMMITTEE MEETING MINUTES, September 22, 2026_0.pdf",
               "SEPTEMBER 22, 2026")
    _listed(net, PS_PAGE, listing)
    net.pdfs[listing[0]] = _pdf("ps_minutes_2026-09-22.pdf")
    assert service.read_pending(_city(), None) == 1

    row = _document(listing[0])
    assert row["present"] == "Tate"
    items = _items(row["id"])
    assert len(items) == 11
    assert [item[4] for item in items] == [None] + ["C. LIQUOR LICENSES"] * 8 + ["D. Ordinances/Resolutions"] * 2
    welcome = items[1]
    assert (welcome[1], welcome[2], welcome[3], welcome[5]) == ("C.", "LIQUOR LICENSES", True, "Welcome Mart")
    assert items[2][3] is False, "the second licence inherits the heading the first one owns"
    assert (welcome[8], welcome[9], welcome[10]) == ("recommended_no_quorum", None, None)


def test_a_scanned_document_is_no_text_with_its_facts_from_the_listing(net):
    from docket.services import committee_documents as service

    _listed(net, PS_PAGE, PS_SCANNED)
    pdf = _pdf("ps_agenda_2026-09-22_scanned.pdf")
    net.pdfs[PS_SCANNED[0]] = pdf

    assert service.read_pending(_city(), 10) == 1

    row = _document(PS_SCANNED[0])
    assert (row["status"], row["kind"], row["meeting_date"], row["date_source"]) == (
        "no_text", "agenda", date(2026, 9, 22), "heading")
    assert row["text"] is None
    assert row["committees"] == ["Public Safety"]
    assert row["pdf_sha256"] == hashlib.sha256(pdf).hexdigest()
    assert (row["present"], row["trailing_lines"], row["parser_version"]) == (None, None, 1)
    assert _items(row["id"]) == []


def test_two_hundred_characters_is_the_line_between_no_text_and_text(net, monkeypatch):
    from docket.services import committee_documents as service

    header = "PUBLIC SAFETY COMMITTEE MEETING\nTUESDAY, SEPTEMBER 22, 2026\nMINUTES\n"
    short = (BUCKET + "short.pdf", "MINUTES.pdf", "SEPTEMBER 22, 2026")
    enough = (BUCKET + "enough.pdf", "MINUTES.pdf", "SEPTEMBER 22, 2026")
    _listed(net, PS_PAGE, short, enough)
    net.pdfs[short[0]] = b"%PDF-short"
    net.pdfs[enough[0]] = b"%PDF-enough"

    def padded(count: int) -> str:
        # The header and filler, ``count`` characters in all that are not spaces.
        filler = "x" * (count - len("".join(header.split())))
        return header + " \n ".join(filler[at : at + 10] for at in range(0, len(filler), 10)) + "\n"

    texts = {b"%PDF-short": padded(199), b"%PDF-enough": padded(200)}
    assert [len("".join(text.split())) for text in texts.values()] == [199, 200]
    assert len(texts[b"%PDF-short"]) > 200, "spaces are not counted"
    monkeypatch.setattr(service, "extract_text_from_pdf", lambda pdf: texts[pdf])

    assert service.read_pending(_city(), None) == 2

    row = _document(short[0])
    assert (row["status"], row["text"], row["kind"], row["date_source"]) == ("no_text", None, "minutes", "heading"), (
        "with too little text the header is not read: the kind is the listed name's and the date the heading's"
    )
    row = _document(enough[0])
    assert (row["status"], row["kind"], row["date_source"]) == ("read", "minutes", "header")
    assert row["text"] == texts[b"%PDF-enough"]


def test_a_full_council_agenda_is_not_committee_and_has_no_facts(net, monkeypatch):
    from docket.services import committee_documents as service

    listing = (BUCKET + "council.pdf", "PUBLIC SAFETY COMMITTEE MEETING AGENDA, March 10, 2026.pdf", "MARCH 10, 2026")
    _listed(net, PS_PAGE, listing)
    net.pdfs[listing[0]] = b"%PDF-council"
    text = ("REGULAR MEETING OF THE COUNCIL\nTUESDAY, MARCH 10, 2026\nPUBLIC SAFETY\n"
            + "\n".join(f"A resolution of the council, numbered {n}, to be considered." for n in range(12)))
    monkeypatch.setattr(service, "extract_text_from_pdf", lambda pdf: text)

    assert service.read_pending(_city(), 10) == 1

    row = _document(listing[0])
    assert (row["status"], row["text"], row["parser_version"]) == ("not_committee", text, 1)
    assert (row["kind"], row["committees"], row["meeting_date"], row["date_source"]) == (None, [], None, None)
    assert (row["listing_disagrees"], row["present"], row["trailing_lines"]) == (False, None, None)
    assert _items(row["id"]) == []


def test_an_agenda_is_read_and_has_no_items_and_the_heading_gives_its_year(net):
    from docket.services import committee_documents as service

    listing = (BUCKET + "ed-agenda.pdf",
               "ECONOMIC AND WORKFORCE DEVELOPMENT/TOURISM COMMITTEE MEETING AGENDA, June 2, 2026", "JUNE 2, 2026")
    _listed(net, ED_PAGE, listing)
    net.pdfs[listing[0]] = _pdf("ed_agenda_june_2_no_year.pdf")

    assert service.read_pending(_city(), 10) == 1

    row = _document(listing[0])
    assert (row["status"], row["kind"], row["meeting_date"], row["date_source"]) == (
        "read", "agenda", date(2026, 6, 2), "heading")
    assert row["committees"] == ["Economic and Workforce Development / Tourism"]
    assert row["text"] and (row["present"], row["trailing_lines"]) == (None, None)
    assert _items(row["id"]) == []


def test_minutes_posted_on_another_committees_page_are_what_their_header_says(net):
    from docket.services import committee_documents as service

    listing = (BUCKET + "cd-minutes.pdf", "BUDGET AND FINANCE COMMITTEE MEETING MINUTES, June 22, 2026.pdf",
               "JUNE 22, 2026")
    _listed(net, BF_PAGE, listing)
    net.pdfs[listing[0]] = _pdf("cd_minutes_2026-05-04_posted_under_bf.pdf")

    assert service.read_pending(_city(), 10) == 1

    row = _document(listing[0])
    assert (row["committees"], row["meeting_date"], row["date_source"], row["listing_disagrees"]) == (
        ["Community Development"], date(2026, 5, 4), "header", True)
    assert row["page_committee"] == "Budget and Finance"
    assert len(_items(row["id"])) == 11


def test_joint_minutes_keep_both_committees_in_the_headers_order_and_special(net):
    from docket.services import committee_documents as service

    listing = (BUCKET + "joint.pdf", "PUBLIC SAFETY COMMITTEE MEETING MINUTES, November 25, 2025.pdf",
               "NOVEMBER 25, 2025")
    _listed(net, PS_PAGE, listing)
    net.pdfs[listing[0]] = _pdf("ps_cow_joint_minutes_2025-11-25.pdf")

    assert service.read_pending(_city(), 10) == 1

    row = _document(listing[0])
    assert row["committees"] == ["Public Safety", "Committee of the Whole / Administration & Governmental Affairs"]
    assert (row["special"], row["work_session"], row["listing_disagrees"]) == (True, False, False)
    assert len(_items(row["id"])) == 10


def test_a_work_session_is_stored_as_one(net, monkeypatch):
    from docket.services import committee_documents as service

    listing = (BUCKET + "work-session.pdf", "AGENDA.pdf", "JUNE 2, 2026")
    _listed(net, ED_PAGE, listing)
    net.pdfs[listing[0]] = b"%PDF-work-session"
    text = ("ECONOMIC AND WORKFORCE DEVELOPMENT / TOURISM COMMITTEE WORK SESSION\nTUESDAY, JUNE 2, 2026\n"
            + "\n".join(f"A presentation to the committee, the {n}th of the afternoon." for n in range(12)))
    monkeypatch.setattr(service, "extract_text_from_pdf", lambda pdf: text)

    assert service.read_pending(_city(), 10) == 1

    row = _document(listing[0])
    assert (row["status"], row["kind"], row["work_session"], row["special"]) == ("read", "agenda", True, False)


def test_a_fetch_that_fails_three_times_is_not_tried_a_fourth(net, caplog):
    from docket.services import committee_documents as service

    _listed(net, BF_PAGE, BF_MINUTES)
    net.pdfs[BF_MINUTES[0]] = None

    for attempt in (1, 2, 3):
        with caplog.at_level("ERROR", logger=service.log.name):
            assert service.read_pending(_city(), 10) == 0
        assert caplog.records == [], "no PDF is an ordinary failure: nothing is read, and nothing raises to be logged"
        row = _document(BF_MINUTES[0])
        assert (row["status"], row["fetch_attempts"]) == ("fetch_failed", attempt)
        assert (row["fetched_at"], row["pdf_sha256"], row["text"], row["parser_version"]) == (None, None, None, None)
    assert net.fetch_pdf.call_count == 3

    assert service.read_pending(_city(), 10) == 0
    assert net.fetch_pdf.call_count == 3, "a fourth run does not select it"
    assert _document(BF_MINUTES[0])["fetch_attempts"] == 3


def test_a_fetch_that_failed_is_tried_again_and_read(net):
    from docket.services import committee_documents as service

    _listed(net, BF_PAGE, BF_MINUTES)
    net.pdfs[BF_MINUTES[0]] = None
    assert service.read_pending(_city(), 10) == 0
    net.pdfs[BF_MINUTES[0]] = _pdf("bf_minutes_2026-10-12.pdf")

    assert service.read_pending(_city(), 10) == 1
    row = _document(BF_MINUTES[0])
    assert (row["status"], row["fetch_attempts"]) == ("read", 1)
    assert len(_items(row["id"])) == 12


def test_a_document_that_cannot_be_read_is_a_failure_and_the_next_is_still_read(net, monkeypatch):
    from docket.services import committee_documents as service

    broken = (BUCKET + "broken.pdf", "MINUTES.pdf", "OCTOBER 12, 2026")
    raising = (BUCKET + "raising.pdf", "MINUTES.pdf", "OCTOBER 12, 2026")
    _listed(net, BF_PAGE, broken, raising, BF_MINUTES)
    with db_cursor() as cur:
        cur.execute("UPDATE committee_documents SET first_seen_at = %s WHERE url = %s",
                    (datetime(2026, 1, 1, tzinfo=timezone.utc), broken[0]))
        cur.execute("UPDATE committee_documents SET first_seen_at = %s WHERE url = %s",
                    (datetime(2026, 1, 2, tzinfo=timezone.utc), raising[0]))
    net.pdfs[broken[0]] = b"%PDF-1.7 and then nothing a reader can open"
    net.pdfs[raising[0]] = RuntimeError("the fetch itself raised")
    net.pdfs[BF_MINUTES[0]] = _pdf("bf_minutes_2026-10-12.pdf")

    assert service.read_pending(_city(), 10) == 1

    for url in (broken[0], raising[0]):
        row = _document(url)
        assert (row["status"], row["fetch_attempts"], row["text"]) == ("fetch_failed", 1, None), url
    assert _document(BF_MINUTES[0])["status"] == "read"


def test_read_pending_takes_the_oldest_first_up_to_its_limit_and_only_this_city(net):
    from docket.services import committee_documents as service

    names = ["c", "a", "b"]
    listings = [(BUCKET + f"{n}.pdf", "AGENDA.pdf", "JUNE 2, 2026") for n in names]
    _listed(net, ED_PAGE, *listings)
    _listed(net, ED_PAGE, (BUCKET + "mobile.pdf", "AGENDA.pdf", "JUNE 2, 2026"), city=_city("mobile"))
    # a and b were first seen at the same moment; a has the lower id (c, a, b is the order listed).
    seen = {"a": 1, "b": 1, "c": 3}
    with db_cursor() as cur:
        for name, day in seen.items():
            cur.execute("UPDATE committee_documents SET first_seen_at = %s WHERE url = %s",
                        (datetime(2026, 3, day, tzinfo=timezone.utc), BUCKET + f"{name}.pdf"))
        cur.execute("UPDATE committee_documents SET first_seen_at = %s WHERE url = %s",
                    (datetime(2026, 1, 1, tzinfo=timezone.utc), BUCKET + "mobile.pdf"))
    for url, _name, _heading in listings:
        net.pdfs[url] = _pdf("ed_agenda_june_2_no_year.pdf")

    def statuses() -> dict:
        return {r["url"].rsplit("/", 1)[1][0]: r["status"] for r in _documents("municipality_id = %s", (_city(),))}

    assert service.read_pending(_city(), 1) == 1
    assert statuses() == {"a": "read", "b": "listed", "c": "listed"}
    assert service.read_pending(_city(), 1) == 1
    assert statuses() == {"a": "read", "b": "read", "c": "listed"}
    assert service.read_pending(_city(), None) == 1
    assert statuses() == {"a": "read", "b": "read", "c": "read"}

    (mobile,) = _documents("municipality_id = %s", (_city("mobile"),))
    assert mobile["status"] == "listed", "another city's document is not this call's"
    assert net.fetch_pdf.call_count == 3


def test_a_failed_fetch_counts_against_the_limit(net):
    from docket.services import committee_documents as service

    listings = [(BUCKET + f"{n}.pdf", "AGENDA.pdf", "JUNE 2, 2026") for n in ("a", "b")]
    _listed(net, ED_PAGE, *listings)
    with db_cursor() as cur:
        cur.execute("UPDATE committee_documents SET first_seen_at = %s WHERE url = %s",
                    (datetime(2026, 1, 1, tzinfo=timezone.utc), listings[0][0]))
    net.pdfs[listings[0][0]] = None
    net.pdfs[listings[1][0]] = _pdf("ed_agenda_june_2_no_year.pdf")

    assert service.read_pending(_city(), 1) == 0, "the limit is on requests made, so a run's requests are bounded"
    assert net.fetch_pdf.call_count == 1


def test_read_stores_one_document_from_its_bytes_without_a_fetch(net):
    from docket.services import committee_documents as service

    _listed(net, BF_PAGE, BF_MINUTES)
    pdf = _pdf("bf_minutes_2026-10-12.pdf")

    service._read(_document(BF_MINUTES[0]), pdf)

    row = _document(BF_MINUTES[0])
    assert (row["status"], row["kind"], row["pdf_sha256"]) == ("read", "minutes", hashlib.sha256(pdf).hexdigest())
    assert row["fetched_at"] is not None
    assert len(_items(row["id"])) == 12
    net.fetch_pdf.assert_not_called()


# --- reparse ---------------------------------------------------------------


def test_reparse_rebuilds_the_same_items_from_the_stored_text_without_a_fetch(net):
    from docket.services import committee_documents as service

    _listed(net, BF_PAGE, BF_MINUTES)
    net.pdfs[BF_MINUTES[0]] = _pdf("bf_minutes_2026-10-12.pdf")
    service.read_pending(_city(), 10)
    before = _document(BF_MINUTES[0])
    items = _items(before["id"])
    assert len(items) == 12

    assert service.reparse(_city()) == 0, "a row at the current version is left alone"

    # An older reading: a lower version, an item lost, one altered, facts wrong.
    with db_cursor() as cur:
        cur.execute("DELETE FROM committee_items WHERE document_id = %s AND position = 12", (before["id"],))
        cur.execute("UPDATE committee_items SET name = 'misread' WHERE document_id = %s AND position = 5",
                    (before["id"],))
        cur.execute("UPDATE committee_documents SET parser_version = 0, kind = 'agenda', meeting_date = NULL, "
                    "date_source = NULL, committees = '{}', present = NULL, trailing_lines = NULL WHERE id = %s",
                    (before["id"],))

    assert service.reparse(_city()) == 1

    after = _document(BF_MINUTES[0])
    assert _items(after["id"]) == items, "the same 12 items at the same positions"
    assert after == before, "and the same row: the facts again, the fetch's own columns untouched"
    net.fetch_pdf.assert_called_once()

    assert service.reparse(_city()) == 0


def test_reparse_reads_only_this_citys_rows_that_have_text(net):
    from docket.services import committee_documents as service

    _listed(net, PS_PAGE, PS_SCANNED)
    net.pdfs[PS_SCANNED[0]] = _pdf("ps_agenda_2026-09-22_scanned.pdf")
    _listed(net, BF_PAGE, BF_MINUTES, city=_city("mobile"))
    net.pdfs[BF_MINUTES[0]] = _pdf("bf_minutes_2026-10-12.pdf")
    service.read_pending(_city(), 10)
    service.read_pending(_city("mobile"), 10)
    with db_cursor() as cur:
        cur.execute("UPDATE committee_documents SET parser_version = 0")

    assert service.reparse(_city()) == 0, "a scanned document has no stored text to read again"
    assert {r["parser_version"] for r in _documents()} == {0}

    assert service.reparse(_city("mobile")) == 1
    assert {r["status"]: r["parser_version"] for r in _documents()} == {"no_text": 0, "read": 1}


def test_reparse_turns_a_row_that_is_no_longer_minutes_into_one_with_no_items(net):
    from docket.services import committee_documents as service

    _listed(net, BF_PAGE, BF_MINUTES)
    net.pdfs[BF_MINUTES[0]] = _pdf("bf_minutes_2026-10-12.pdf")
    service.read_pending(_city(), 10)
    doc = _document(BF_MINUTES[0])
    # The stored text loses its MINUTES line, as if a mended rule now read it as an agenda.
    lines = doc["text"].split("\n")
    assert "MINUTES" in lines
    with db_cursor() as cur:
        cur.execute("UPDATE committee_documents SET parser_version = 0, text = %s WHERE id = %s",
                    ("\n".join(line for line in lines if line != "MINUTES"), doc["id"]))

    assert service.reparse(_city()) == 1

    row = _document(BF_MINUTES[0])
    assert (row["status"], row["kind"], row["present"], row["trailing_lines"]) == ("read", "agenda", None, None)
    assert _items(row["id"]) == []
