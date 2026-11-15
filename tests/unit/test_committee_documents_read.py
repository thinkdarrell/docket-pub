"""Tests for docket.adapters.committee_documents: a committee page's listing
and a document's own header (plan `committee-documents`, M1).

The fixtures in tests/fixtures/committee_documents/ are the city's own files,
saved unchanged on 2026-11-13; that directory's README.md says where each was
listed and why it was chosen. Every PDF is read the way the service will read
it, with ``extract_text_from_pdf``, so an expected value here is what the
code sees and not what a person reads off the page.

The symbols under test are imported inside each test, so the file collects
and reads as failing, not as a collection error, before the module exists.
"""

from datetime import date
from functools import lru_cache
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "fixtures" / "committee_documents"
PAGE_URL = (
    "https://www.birminghamal.gov/government/city-council/council/"
    "council-committees-2025-2027/planning-zoning-committee"
)
COW = "Committee of the Whole / Administration & Governmental Affairs"


@lru_cache(maxsize=None)
def _text(name: str) -> str:
    from docket.analysis.minutes_parser import extract_text_from_pdf

    return extract_text_from_pdf((FIXTURES / name).read_bytes())


def _listing(heading, name="A DOCUMENT.pdf"):
    from docket.adapters.committee_documents import Listing

    return Listing(
        url="https://s3.us-east-2.amazonaws.com/assets.birminghamal.gov/s3fs-public/x.pdf",
        listed_name=name,
        listed_heading=heading,
        page_url=PAGE_URL,
    )


# --- the committee page ----------------------------------------------------


def test_page_yields_27_listings_under_15_headings():
    from docket.adapters.committee_documents import parse_committee_page

    html = (FIXTURES / "page_planning_zoning.html").read_text(encoding="utf-8")
    listings = parse_committee_page(html, PAGE_URL)

    assert len(listings) == 27
    assert len({item.listed_heading for item in listings}) == 15
    assert len({item.url for item in listings}) == 27
    assert all(item.page_url == PAGE_URL for item in listings)
    assert all(item.url.lower().endswith(".pdf") for item in listings)

    first = listings[0]
    assert first.listed_heading == "OCTOBER 13, 2026"
    assert first.listed_name == "PLANNING AND ZONING COMMITTEE MEETING AGENDA, October 13, 2026.pdf"

    tail = "PLANNING%20AND%20ZONING%20COMMITTEE%20MEETING%2C%20September%208%2C%202026.pdf"
    september = [item for item in listings if item.url.endswith(tail)]
    assert len(september) == 1
    assert september[0].listed_heading == "SEPTEMBER 8, 2026"


def _page(body: str) -> str:
    import json

    data = {"props": {"pageProps": {"nodeResource": {"content": [{"body": {"processed": body}}]}}}}
    return (
        '<html><body><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(data).replace("</", "<\\/")
        + "</script></body></html>"
    )


def _article(name: str, file: str) -> str:
    return f'<article class="media media--type-document media--view-mode-" name="{name}" file="{file}"></article>'


def test_page_keeps_a_repeated_address_once_and_only_the_citys_pdfs():
    from docket.adapters.committee_documents import parse_committee_page

    bucket = "https://s3.us-east-2.amazonaws.com/assets.birminghamal.gov/s3fs-public/2026-01/"
    body = (
        _article("BEFORE ANY HEADING.pdf", bucket + "before.pdf")
        + "<h4>JANUARY 5, 2026</h4>"
        + _article("ARTS &amp;amp; PARKS AGENDA.pdf", bucket + "a.PDF")
        + _article("THE SAME ADDRESS AGAIN.pdf", bucket + "a.PDF")
        + _article("ON THE CITY'S OWN SITE.pdf", "https://www.birminghamal.gov/files/b.pdf")
        + _article("ELSEWHERE.pdf", "https://example.com/c.pdf")
        + _article("NOT A PDF", bucket + "d.docx")
        + '<article class="media media--type-image" name="A PICTURE.pdf" file="' + bucket + 'e.pdf"></article>'
        + "<h4>JANUARY 19, 2026</h4>"
        + _article("LATER.pdf", bucket + "f.pdf")
    )
    listings = parse_committee_page(_page(body), PAGE_URL)

    assert [(item.url.rsplit("/", 1)[1], item.listed_heading) for item in listings] == [
        ("before.pdf", None),
        ("a.PDF", "JANUARY 5, 2026"),
        ("b.pdf", "JANUARY 5, 2026"),
        ("f.pdf", "JANUARY 19, 2026"),
    ]
    assert listings[1].listed_name == "ARTS & PARKS AGENDA.pdf"


def test_page_without_its_data_block_yields_nothing():
    from docket.adapters.committee_documents import parse_committee_page

    assert parse_committee_page("<html><body><p>Not found</p></body></html>", PAGE_URL) == []
    assert parse_committee_page('<script id="__NEXT_DATA__">{not json</script>', PAGE_URL) == []


# --- dates -----------------------------------------------------------------


def test_read_date_spellings():
    from docket.adapters.committee_documents import read_date

    assert read_date("MAY12, 2026") == (2026, 5, 12)
    assert read_date("Tuesday, November 18th") == (None, 11, 18)
    assert read_date("TUESDAY, May 26, 2O26") == (2026, 5, 26)
    assert read_date("MONDAY") is None
    assert read_date("WEDNESDAY, SEPTEBMBER 8, 2026 | 3:00 PM") == (2026, 9, 8)
    assert read_date("MONDAY, OCTOBER 12, 2026 | 3:30 PM") == (2026, 10, 12)
    assert read_date("Tuesday, June 2") == (None, 6, 2)


# --- committees ------------------------------------------------------------


def test_committee_tuple_equals_the_services_list():
    from docket.adapters.committee_documents import COMMITTEE_SLUGS, COMMITTEES
    from docket.services.meeting_types import BIRMINGHAM_COMMITTEES

    assert COMMITTEES == BIRMINGHAM_COMMITTEES
    assert tuple(COMMITTEE_SLUGS) == COMMITTEES
    assert COMMITTEE_SLUGS["Budget and Finance"] == "budget-finance-committee"
    assert COMMITTEE_SLUGS[COW] == "committee-whole-administration-governmental-affairs"
    assert COMMITTEE_SLUGS["Economic and Workforce Development / Tourism"] == (
        "economic-workforce-development-tourism-committee"
    )


def test_committees_named_in_the_order_found():
    from docket.adapters.committee_documents import committees_named

    assert committees_named("Budget & Finance Committee") == ("Budget and Finance",)
    assert committees_named("Economic Development & Tourism Committee Work Session") == (
        "Economic and Workforce Development / Tourism",
    )
    assert committees_named("ADMINISTRATION & GOVERNMENTAL  AFFAIRS COMMITTEE") == (COW,)
    assert committees_named("Committee of the Whole and Public Safety") == (COW, "Public Safety")
    assert committees_named("REGULAR MEETING") == ()


# --- a document's own header ------------------------------------------------


def test_budget_minutes_header():
    from docket.adapters.committee_documents import read_header

    header = read_header(_text("bf_minutes_2026-10-12.pdf"))
    assert header.committees == ("Budget and Finance",)
    assert header.date == (2026, 10, 12)
    assert header.is_minutes is True
    assert header.special is False
    assert header.work_session is False
    assert header.lines[0] == "BUDGET AND FINANCE COMMITTEE MEETING"
    assert header.lines[-1] == "Councilor(s) Present: Woods, Alexander, Smitherman, O’Quinn"


def test_planning_minutes_header_reads_a_misspelled_month():
    from docket.adapters.committee_documents import read_header

    text = _text("pz_minutes_2026-09-08.pdf")
    assert "SEPTEBMBER" in text
    header = read_header(text)
    assert header.committees == ("Planning & Zoning",)
    assert header.date == (2026, 9, 8)
    assert header.is_minutes is True


def test_joint_minutes_header_names_both_committees_in_order():
    from docket.adapters.committee_documents import read_header

    header = read_header(_text("ps_cow_joint_minutes_2025-11-25.pdf"))
    assert header.committees == ("Public Safety", COW)
    assert header.date == (2025, 11, 25)
    assert header.is_minutes is True
    assert header.special is True
    assert header.work_session is False


def test_minutes_posted_on_another_committees_page_keep_their_own_facts():
    from docket.adapters.committee_documents import read_header, resolve

    header = read_header(_text("cd_minutes_2026-05-04_posted_under_bf.pdf"))
    facts = resolve(_listing("JUNE 22, 2026"), "Budget and Finance", header)
    assert facts.committees == ("Community Development",)
    assert facts.kind == "minutes"
    assert facts.meeting_date == date(2026, 5, 4)
    assert facts.date_source == "header"
    assert facts.listing_disagrees is True


def test_agenda_with_no_year_takes_the_headings_year_only_when_the_day_agrees():
    from docket.adapters.committee_documents import read_header, resolve

    header = read_header(_text("ed_agenda_june_2_no_year.pdf"))
    assert header.date == (None, 6, 2)
    assert header.is_minutes is False
    assert header.committees == ("Economic and Workforce Development / Tourism",)

    page = "Economic and Workforce Development / Tourism"
    same = resolve(_listing("JUNE 2, 2026"), page, header)
    assert same.kind == "agenda"
    assert same.meeting_date == date(2026, 6, 2)
    assert same.date_source == "heading"
    assert same.listing_disagrees is False

    other = resolve(_listing("JUNE 16, 2026"), page, header)
    assert other.kind == "agenda"
    assert other.meeting_date is None
    assert other.date_source is None


def test_agenda_with_minutes_appended_reads_as_an_agenda():
    from docket.adapters.committee_documents import read_header, resolve

    text = _text("pz_agenda_2026-01-27_with_minutes_appended.pdf")
    assert "Action Taken" in text
    header = read_header(text)
    assert header.is_minutes is False
    assert header.date == (2026, 1, 27)
    assert header.committees == ("Planning & Zoning",)

    facts = resolve(_listing("JANUARY 27, 2026"), "Planning & Zoning", header)
    assert facts.kind == "agenda"
    assert facts.meeting_date == date(2026, 1, 27)
    assert facts.date_source == "header"
    assert facts.listing_disagrees is False


def test_scanned_agenda_takes_everything_from_its_listing():
    from docket.adapters.committee_documents import resolve

    text = _text("ps_agenda_2026-09-22_scanned.pdf")
    assert len("".join(text.split())) < 200

    listing = _listing(
        "SEPTEMBER 22, 2026",
        "PUBLIC SAFETY COMMITTEE MEETING AGENDA, September 22, 2026.pdf",
    )
    facts = resolve(listing, "Public Safety", None)
    assert facts.committees == ("Public Safety",)
    assert facts.kind == "agenda"
    assert facts.meeting_date == date(2026, 9, 22)
    assert facts.date_source == "heading"
    assert facts.listing_disagrees is False
    assert facts.special is False
    assert facts.work_session is False


def test_no_text_kind_comes_from_the_listed_name():
    from docket.adapters.committee_documents import resolve

    minutes = resolve(_listing("MAY 5, 2026", "PUBLIC SAFETY COMMITTEE MEETING MINUTES.pdf"), "Public Safety", None)
    assert minutes.kind == "minutes"
    neither = resolve(_listing("MAY 5, 2026", "PUBLIC SAFETY COMMITTEE MEETING.pdf"), "Public Safety", None)
    assert neither.kind is None
    unnamed = resolve(_listing("MAY 5, 2026", None), "Public Safety", None)
    assert unnamed.kind is None
    # A heading with no year, or none at all, dates nothing.
    assert resolve(_listing("MAY 5", "AGENDA.pdf"), "Public Safety", None).meeting_date is None
    assert resolve(_listing(None, "AGENDA.pdf"), "Public Safety", None).meeting_date is None


def test_council_agenda_is_not_a_committee_document():
    from docket.adapters.committee_documents import read_header

    text = "\n".join(
        [
            "REGULAR MEETING OF THE COUNCIL",
            "CITY OF BIRMINGHAM, ALABAMA",
            "TUESDAY, OCTOBER 13, 2026",
            "PUBLIC SAFETY COMMITTEE ITEMS FOLLOW",
            "1. CALL TO ORDER",
        ]
    )
    assert read_header(text) is None


def test_header_stops_at_the_first_heading_line_and_at_twenty_lines():
    from docket.adapters.committee_documents import read_header

    text = "\n".join(
        [
            "",
            "  BUDGET AND FINANCE COMMITTEE WORK SESSION  ",
            "",
            "MONDAY, MARCH 2, 2026",
            "Agenda",
            "1) Call to Order",
            "MINUTES",
            "PUBLIC SAFETY COMMITTEE",
            "TUESDAY, MARCH 3, 2026",
        ]
    )
    header = read_header(text)
    assert header.lines == ("BUDGET AND FINANCE COMMITTEE WORK SESSION", "MONDAY, MARCH 2, 2026", "Agenda")
    assert header.committees == ("Budget and Finance",)
    assert header.date == (2026, 3, 2)
    assert header.is_minutes is False
    assert header.work_session is True
    assert header.special is False

    long = "\n".join(["ARTS AND PARKS COMMITTEE MEETING"] + ["A LINE OF NOISE"] * 19 + ["MINUTES", "MAY 5, 2026"])
    header = read_header(long)
    assert len(header.lines) == 20
    assert header.is_minutes is False
    assert header.date is None

    # The first line that gives a date is the header's date.
    two = read_header("PUBLIC SAFETY COMMITTEE\nTuesday, June 2\nJUNE 9, 2026\nMinutes of the meeting\nMINUTES")
    assert two.date == (None, 6, 2)
    assert two.is_minutes is True


def test_resolve_falls_back_to_the_listing_fact_by_fact():
    from docket.adapters.committee_documents import Header, resolve

    def header(committees=(), when=None, minutes=False):
        return Header(
            committees=committees,
            date=when,
            is_minutes=minutes,
            special=True,
            work_session=True,
            lines=("x",),
        )

    # A header that names no committee and no date: the page and the heading.
    facts = resolve(_listing("MAY 5, 2026", "MINUTES.pdf"), "Public Safety", header())
    assert facts.committees == ("Public Safety",)
    assert facts.kind == "agenda"
    assert facts.meeting_date == date(2026, 5, 5)
    assert facts.date_source == "heading"
    assert facts.listing_disagrees is False
    assert facts.special is True
    assert facts.work_session is True

    # No header date and a heading with no year: no date.
    facts = resolve(_listing("MAY 5", "x.pdf"), "Public Safety", header())
    assert facts.meeting_date is None
    assert facts.date_source is None

    # A full header date wins, and a different full heading date is a disagreement.
    facts = resolve(_listing("MAY 12, 2026"), "Public Safety", header(("Public Safety",), (2026, 5, 5), True))
    assert facts.kind == "minutes"
    assert facts.meeting_date == date(2026, 5, 5)
    assert facts.date_source == "header"
    assert facts.listing_disagrees is True

    # The same date under a heading that does not parse: no disagreement.
    facts = resolve(_listing("SOMETIME"), "Public Safety", header(("Public Safety",), (2026, 5, 5)))
    assert facts.meeting_date == date(2026, 5, 5)
    assert facts.listing_disagrees is False

    # A joint meeting listed on one of its committees' pages does not disagree.
    facts = resolve(_listing("MAY 5, 2026"), COW, header(("Public Safety", COW), (2026, 5, 5)))
    assert facts.committees == ("Public Safety", COW)
    assert facts.listing_disagrees is False

    # A header date that is no day of the calendar dates nothing.
    facts = resolve(_listing("MAY 5, 2026"), "Public Safety", header(("Public Safety",), (2026, 2, 30)))
    assert facts.meeting_date is None
    assert facts.date_source is None
