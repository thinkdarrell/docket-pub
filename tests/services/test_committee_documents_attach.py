"""docket.services.committee_documents: attaching documents to meetings, and
creating a meeting from minutes.

Nothing is fetched and nothing is read from a PDF: every document is a
``committee_documents`` row the test inserts as a reading would have left it,
and every meeting a row the test inserts, all under Birmingham (one meeting
under Mobile) and all dated in 2031, where the throwaway database holds no
other meeting. The test's own meetings have an ``external_id`` beginning
``cdattach-`` or, for the Granicus clips of a crowded day, ``99031``; the
meetings ``attach`` creates begin ``cdoc-``. All are deleted after. An autouse
fixture counts ``agenda_items`` and ``votes`` before and after every test:
this source writes to neither. The service's names are imported inside each
test, so the file collects before they exist. Runs in the services tier
(DATABASE_URL names docket_test_*).

Plan `committee-documents`, M4.
"""

from __future__ import annotations

import itertools
import logging
from datetime import date

import pytest

from docket.db import db_cursor

ROOT = "https://www.birminghamal.gov/government/city-council/council/council-committees-2025-2027/"
BUCKET = "https://s3.us-east-2.amazonaws.com/assets.birminghamal.gov/cdattach/"

BF = "Budget and Finance"
ED = "Economic and Workforce Development / Tourism"
PS = "Public Safety"
COW = "Committee of the Whole / Administration & Governmental Affairs"
AP = "Arts and Parks"

SLUGS = {
    BF: "budget-finance-committee",
    ED: "economic-workforce-development-tourism-committee",
    PS: "public-safety-committee",
    COW: "committee-whole-administration-governmental-affairs",
    AP: "arts-parks-committee",
}

DAY = date(2031, 3, 10)
TODAY = date(2031, 12, 31)

_serial = itertools.count(1)


def _city(slug: str = "birmingham") -> int:
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug = %s", (slug,))
        return cur.fetchone()["id"]


def _delete_all() -> None:
    with db_cursor() as cur:
        cur.execute("DELETE FROM committee_documents")
        cur.execute(
            "DELETE FROM meetings WHERE external_id LIKE 'cdattach-%' OR external_id LIKE 'cdoc-%' "
            "OR external_id LIKE '99031%'"
        )


def _count(table: str) -> int:
    with db_cursor() as cur:
        cur.execute(f"SELECT count(*) AS n FROM {table}")
        return cur.fetchone()["n"]


def _meeting(body_name: str | None, day: date = DAY, *, meeting_type: str = "committee", hidden: bool = False,
             video_url: str | None = None, external_id: str | None = None, city: int | None = None) -> int:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type, body_name,
                                     is_hidden, video_url)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (city or _city(), external_id or f"cdattach-{next(_serial)}", body_name or "A meeting", day,
             meeting_type, body_name, hidden, video_url),
        )
        return cur.fetchone()["id"]


def _doc(committees: tuple[str, ...] = (BF,), day: date | None = DAY, *, kind: str | None = "minutes",
         status: str = "read", date_source: str | None = "header", disagrees: bool = False, special: bool = False,
         work_session: bool = False, page_committee: str | None = None, city: int | None = None) -> int:
    page_committee = page_committee or (committees[0] if committees else BF)
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO committee_documents
                      (municipality_id, url, page_url, page_committee, status, kind, committees, meeting_date,
                       date_source, listing_disagrees, special, work_session, parser_version)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1) RETURNING id""",
            (city or _city(), f"{BUCKET}{next(_serial)}.pdf", ROOT + SLUGS[page_committee], page_committee, status,
             kind, list(committees), day, date_source if day else None, disagrees, special, work_session),
        )
        return cur.fetchone()["id"]


def _attached(document_id: int) -> tuple[int | None, str | None]:
    with db_cursor() as cur:
        cur.execute("SELECT meeting_id, attached_by FROM committee_documents WHERE id = %s", (document_id,))
        row = cur.fetchone()
        return row["meeting_id"], row["attached_by"]


def _created() -> list[dict]:
    with db_cursor() as cur:
        cur.execute("SELECT * FROM meetings WHERE external_id LIKE 'cdoc-%' ORDER BY id")
        return [dict(r) for r in cur.fetchall()]


def _counts(report) -> tuple[int, int, int, int, int]:
    return (report.matched, report.created, report.ambiguous, report.unattached_agendas, report.unattached_minutes)


@pytest.fixture(autouse=True)
def only_these_tables():
    """Clean before and after, and the counts of the two tables this source
    must never write are the same after every test as before it."""
    _delete_all()
    before = (_count("agenda_items"), _count("votes"))
    yield
    assert (_count("agenda_items"), _count("votes")) == before, "a committee document wrote council business"
    _delete_all()


# -- committee_of --------------------------------------------------------------


def test_committee_of_reads_one_committee_or_none():
    from docket.services.committee_documents import committee_of

    assert committee_of("Budget & Finance Committee") == BF
    assert committee_of("Economic Development & Tourism Committee") == ED
    assert committee_of("Economic Development & Tourism Committee Work Session") == ED
    assert committee_of("Public Safety Committee") == PS
    assert committee_of("Committee of the Whole") == COW
    assert committee_of("Joint Public Safety and Budget and Finance Committee") is None
    assert committee_of("Birmingham City Council") is None
    assert committee_of("") is None
    assert committee_of(None) is None


# -- attaching to a meeting that exists ------------------------------------------


def test_minutes_attach_to_the_committees_meeting_whatever_its_spelling():
    from docket.services.committee_documents import attach

    meeting = _meeting("Budget & Finance Committee")
    doc = _doc((BF,))
    report = attach(_city(), TODAY)
    assert _attached(doc) == (meeting, "matched")
    assert _counts(report) == (1, 0, 0, 0, 0)
    assert report.crowded_days == []
    assert _created() == []


def test_economic_minutes_attach_to_a_work_session_row_spelled_another_way():
    from docket.services.committee_documents import attach

    meeting = _meeting("Economic Development & Tourism Committee Work Session")
    doc = _doc((ED,))
    report = attach(_city(), TODAY)
    assert _attached(doc) == (meeting, "matched")
    assert _counts(report) == (1, 0, 0, 0, 0)


def test_a_scanned_agenda_attaches_and_an_agenda_dated_by_its_heading_attaches():
    from docket.services.committee_documents import attach

    meeting = _meeting("Public Safety Committee")
    scanned = _doc((PS,), kind="agenda", status="no_text", date_source="heading")
    report = attach(_city(), TODAY)
    assert _attached(scanned) == (meeting, "matched")
    assert _counts(report) == (1, 0, 0, 0, 0)


def test_a_meeting_after_today_is_still_matched():
    from docket.services.committee_documents import attach

    meeting = _meeting("Budget and Finance Committee", date(2032, 1, 12))
    agenda = _doc((BF,), date(2032, 1, 12), kind="agenda")
    attach(_city(), TODAY)
    assert _attached(agenda) == (meeting, "matched")


def test_only_a_visible_committee_meeting_of_this_city_on_that_day_is_a_candidate():
    from docket.services.committee_documents import attach

    _meeting("Budget and Finance Committee", hidden=True)
    _meeting("Budget and Finance Committee", meeting_type="council")
    _meeting("Budget and Finance Committee", date(2031, 3, 11))
    _meeting("Budget and Finance Committee", city=_city("mobile"))
    _meeting("Public Safety Committee")
    _meeting(None)
    agenda = _doc((BF,), kind="agenda")
    report = attach(_city(), TODAY)
    assert _attached(agenda) == (None, None)
    assert _counts(report) == (0, 0, 0, 1, 0)


def test_a_hidden_meeting_is_not_a_candidate_so_minutes_create_another():
    from docket.services.committee_documents import attach

    hidden = _meeting("Budget and Finance Committee", hidden=True)
    doc = _doc((BF,))
    report = attach(_city(), TODAY)
    (created,) = _created()
    assert _attached(doc) == (created["id"], "created")
    assert created["id"] != hidden
    assert _counts(report) == (0, 1, 0, 0, 0)


def test_a_council_meeting_on_the_same_date_is_not_a_candidate():
    from docket.services.committee_documents import attach

    council = _meeting("Birmingham City Council", meeting_type="council")
    doc = _doc((PS,))
    attach(_city(), TODAY)
    (created,) = _created()
    assert _attached(doc) == (created["id"], "created")
    assert created["id"] != council


def test_a_document_that_is_not_read_or_lacks_a_fact_is_left_alone():
    from docket.services.committee_documents import attach

    _meeting("Budget and Finance Committee")
    left = [
        _doc((BF,), status="listed"),
        _doc((BF,), status="fetch_failed"),
        _doc((BF,), status="not_committee"),
        _doc((BF,), kind=None),
        _doc((BF,), None),
        _doc(()),
    ]
    report = attach(_city(), TODAY)
    assert [_attached(d) for d in left] == [(None, None)] * 6
    assert _counts(report) == (0, 0, 0, 0, 0)
    assert _created() == []


def test_a_document_of_another_city_is_left_alone():
    from docket.services.committee_documents import attach

    _meeting("Budget and Finance Committee")
    other = _doc((BF,), city=_city("mobile"))
    report = attach(_city(), TODAY)
    assert _attached(other) == (None, None)
    assert _counts(report) == (0, 0, 0, 0, 0)
    assert _created() == []


def test_a_document_already_attached_is_not_moved():
    from docket.services.committee_documents import attach

    first = _meeting("Budget and Finance Committee", date(2031, 3, 11))
    doc = _doc((BF,))
    with db_cursor() as cur:
        cur.execute("UPDATE committee_documents SET meeting_id = %s, attached_by = 'matched' WHERE id = %s",
                    (first, doc))
    _meeting("Budget and Finance Committee")
    report = attach(_city(), TODAY)
    assert _attached(doc) == (first, "matched")
    assert _counts(report) == (0, 0, 0, 0, 0)


# -- several candidates ----------------------------------------------------------


def test_joint_minutes_attach_to_the_first_named_committees_meeting_and_count_as_ambiguous():
    from docket.services.committee_documents import attach

    whole = _meeting("Committee of the Whole", video_url="https://www.youtube.com/watch?v=cow")
    safety = _meeting("Public Safety Committee")
    doc = _doc((PS, COW))
    report = attach(_city(), TODAY)
    assert _attached(doc) == (safety, "matched")
    assert whole < safety
    assert _counts(report) == (1, 0, 1, 0, 0)
    assert _created() == []


def test_joint_minutes_with_no_meeting_of_the_first_named_committee_attach_to_the_others():
    from docket.services.committee_documents import attach

    whole = _meeting("Committee of the Whole")
    doc = _doc((PS, COW))
    report = attach(_city(), TODAY)
    assert _attached(doc) == (whole, "matched")
    assert _counts(report) == (1, 0, 0, 0, 0)
    assert _created() == []


def test_among_several_meetings_of_one_committee_a_recording_wins_and_then_the_lowest_id():
    from docket.services.committee_documents import attach

    _meeting("Budget and Finance Committee")
    recorded = _meeting("Budget & Finance Committee", video_url="https://www.youtube.com/watch?v=bf")
    _meeting("Budget and Finance Committee", video_url="https://www.youtube.com/watch?v=bf2")
    doc = _doc((BF,))
    report = attach(_city(), TODAY)
    assert _attached(doc) == (recorded, "matched")
    assert _counts(report) == (1, 0, 1, 0, 0)

    lowest = _meeting("Arts and Parks Committee", date(2031, 4, 1))
    _meeting("Arts and Parks Committee", date(2031, 4, 1))
    arts = _doc((AP,), date(2031, 4, 1))
    report = attach(_city(), TODAY)
    assert _attached(arts) == (lowest, "matched")
    assert _counts(report) == (1, 0, 1, 0, 0)


# -- creating a meeting from minutes ---------------------------------------------


def test_minutes_with_no_meeting_create_one_and_a_second_attach_creates_nothing():
    from docket.services.committee_documents import attach

    doc = _doc((ED,))
    report = attach(_city(), TODAY)
    (created,) = _created()
    assert created["external_id"] == "cdoc-economic-workforce-development-tourism-2031-03-10"
    assert created["municipality_id"] == _city()
    assert created["title"] == "Economic and Workforce Development / Tourism Committee Meeting"
    assert created["meeting_date"] == DAY
    assert created["meeting_type"] == "committee"
    assert created["session_kind"] == "regular"
    assert created["body_name"] == "Economic and Workforce Development / Tourism Committee"
    assert created["type_source"] == "title"
    assert created["source_url"] == ROOT + "economic-workforce-development-tourism-committee"
    assert (created["agenda_url"], created["minutes_url"], created["video_url"]) == (None, None, None)
    assert created["is_hidden"] is False
    assert _attached(doc) == (created["id"], "created")
    assert _counts(report) == (0, 1, 0, 0, 0)
    assert report.crowded_days == []

    again = attach(_city(), TODAY)
    assert [m["id"] for m in _created()] == [created["id"]]
    assert _attached(doc) == (created["id"], "created")
    assert _counts(again) == (0, 0, 0, 0, 0)
    assert again.crowded_days == []


def test_a_created_meetings_title_says_special_called_and_work_session():
    from docket.services.committee_documents import attach

    _doc((BF,), date(2031, 5, 1), special=True)
    _doc((BF,), date(2031, 5, 2), work_session=True)
    _doc((COW,), date(2031, 5, 3), special=True, work_session=True)
    attach(_city(), TODAY)
    assert [(m["external_id"], m["title"], m["session_kind"], m["meeting_type"]) for m in _created()] == [
        ("cdoc-budget-finance-2031-05-01", "Special Called Budget and Finance Committee Meeting", "special",
         "committee"),
        ("cdoc-budget-finance-2031-05-02", "Budget and Finance Committee Work Session", "work_session", "committee"),
        ("cdoc-committee-whole-administration-governmental-affairs-2031-05-03",
         "Special Called Committee of the Whole / Administration & Governmental Affairs Committee Work Session",
         "work_session", "committee"),
    ]


def test_a_created_meeting_is_the_first_named_committees_and_takes_the_documents_own_page():
    from docket.services.committee_documents import attach

    doc = _doc((PS, COW), page_committee=BF)
    attach(_city(), TODAY)
    (created,) = _created()
    assert created["external_id"] == "cdoc-public-safety-2031-03-10"
    assert created["title"] == "Public Safety Committee Meeting"
    assert created["source_url"] == ROOT + "budget-finance-committee"
    assert _attached(doc) == (created["id"], "created")


def test_two_minutes_for_one_meeting_create_it_once():
    from docket.services.committee_documents import attach

    first = _doc((ED,))
    second = _doc((ED,), disagrees=True)
    report = attach(_city(), TODAY)
    (created,) = _created()
    assert _attached(first) == (created["id"], "created")
    assert _attached(second) == (created["id"], "matched")
    assert _counts(report) == (1, 1, 0, 0, 0)


def test_an_agenda_listed_before_its_minutes_attaches_in_the_same_run():
    from docket.services.committee_documents import attach

    agenda = _doc((ED,), kind="agenda")
    minutes = _doc((ED,))
    assert agenda < minutes
    report = attach(_city(), TODAY)
    (created,) = _created()
    assert _attached(minutes) == (created["id"], "created")
    assert _attached(agenda) == (created["id"], "matched")
    assert _counts(report) == (1, 1, 0, 0, 0)


def test_an_agenda_alone_creates_nothing_and_attaches_once_its_meeting_exists():
    from docket.services.committee_documents import attach

    agenda = _doc((AP,), kind="agenda")
    report = attach(_city(), TODAY)
    assert _created() == []
    assert _attached(agenda) == (None, None)
    assert _counts(report) == (0, 0, 0, 1, 0)

    meeting = _meeting("Arts and Parks Committee")
    report = attach(_city(), TODAY)
    assert _attached(agenda) == (meeting, "matched")
    assert _counts(report) == (1, 0, 0, 0, 0)


def test_minutes_dated_after_today_create_nothing_and_minutes_dated_today_do():
    from docket.services.committee_documents import attach

    doc = _doc((BF,))
    report = attach(_city(), date(2031, 3, 9))
    assert _created() == []
    assert _attached(doc) == (None, None)
    assert _counts(report) == (0, 0, 0, 0, 1)

    report = attach(_city(), DAY)
    (created,) = _created()
    assert _attached(doc) == (created["id"], "created")
    assert _counts(report) == (0, 1, 0, 0, 0)


def test_minutes_dated_by_their_heading_create_nothing():
    from docket.services.committee_documents import attach

    doc = _doc((BF,), date_source="heading")
    scanned = _doc((PS,), status="no_text", date_source="heading")
    report = attach(_city(), TODAY)
    assert _created() == []
    assert _attached(doc) == (None, None)
    assert _attached(scanned) == (None, None)
    assert _counts(report) == (0, 0, 0, 0, 2)


def test_a_meeting_that_already_has_the_created_address_is_attached_to_and_not_made_twice():
    """The hidden row is no candidate, and it holds the address a created
    meeting would take: the insert does nothing and the document goes to it."""
    from docket.services.committee_documents import attach

    held = _meeting("Budget and Finance Committee", hidden=True, external_id="cdoc-budget-finance-2031-03-10")
    elsewhere = _meeting("Budget and Finance Committee", external_id="cdoc-budget-finance-2031-03-10",
                         city=_city("mobile"))
    doc = _doc((BF,))
    report = attach(_city(), TODAY)
    assert [m["id"] for m in _created()] == [held, elsewhere]
    assert _attached(doc) == (held, "matched")
    assert _counts(report) == (1, 0, 0, 0, 0)


# -- the report ------------------------------------------------------------------


def test_a_created_meetings_day_with_a_second_granicus_council_meeting_is_crowded():
    from docket.services.committee_documents import attach

    crowded, one_council, not_granicus, hidden_second, other_city, not_council, crowded_too = (
        date(2031, 6, d) for d in (10, 11, 12, 13, 14, 15, 9)
    )
    _meeting("Birmingham City Council", crowded, meeting_type="council", external_id="990311")
    _meeting("Birmingham City Council", crowded, meeting_type="council", external_id="990312")
    _meeting("Birmingham City Council", one_council, meeting_type="council", external_id="990313")
    _meeting("Birmingham City Council", not_granicus, meeting_type="council", external_id="990314")
    _meeting("Birmingham City Council", not_granicus, meeting_type="council")
    _meeting("Birmingham City Council", hidden_second, meeting_type="council", external_id="990315")
    _meeting("Birmingham City Council", hidden_second, meeting_type="council", external_id="990316", hidden=True)
    _meeting("Mobile City Council", other_city, meeting_type="council", external_id="990319", city=_city("mobile"))
    _meeting("Mobile City Council", other_city, meeting_type="council", external_id="9903110", city=_city("mobile"))
    _meeting("Birmingham Planning Commission", not_council, meeting_type="planning", external_id="9903111")
    _meeting("Birmingham Planning Commission", not_council, meeting_type="planning", external_id="9903112")
    _meeting("Birmingham City Council", crowded_too, meeting_type="council", external_id="9903113")
    _meeting("Birmingham City Council", crowded_too, meeting_type="council", external_id="9903114")
    for day in (not_council, other_city, hidden_second, not_granicus, one_council, crowded, crowded_too):
        _doc((PS,), day)
    report = attach(_city(), TODAY)
    assert report.created == 7
    assert report.crowded_days == [crowded_too, crowded]

    assert attach(_city(), TODAY).crowded_days == []


def test_a_matched_meetings_day_is_not_reported_as_crowded():
    from docket.services.committee_documents import attach

    _meeting("Birmingham City Council", meeting_type="council", external_id="990317")
    _meeting("Birmingham City Council", meeting_type="council", external_id="990318")
    _meeting("Public Safety Committee")
    _doc((PS,))
    report = attach(_city(), TODAY)
    assert _counts(report) == (1, 0, 0, 0, 0)
    assert report.crowded_days == []


def test_the_report_is_logged(caplog):
    from docket.services.committee_documents import attach

    _doc((ED,))
    with caplog.at_level(logging.INFO, logger="docket.services.committee_documents"):
        attach(_city(), TODAY)
    assert any("created=1" in r.getMessage() and "matched=0" in r.getMessage() for r in caplog.records)


# -- the primary document --------------------------------------------------------


@pytest.mark.parametrize("disagreeing_first", [True, False])
def test_the_primary_minutes_are_the_ones_that_agree_with_their_listing_whichever_came_first(disagreeing_first):
    from docket.services.committee_documents import attach, primary_documents

    meeting = _meeting("Budget and Finance Committee")
    if disagreeing_first:
        other = _doc((BF,), disagrees=True)
        agreeing = _doc((BF,))
    else:
        agreeing = _doc((BF,))
        other = _doc((BF,), disagrees=True)
    attach(_city(), TODAY)
    assert _attached(agreeing)[0] == _attached(other)[0] == meeting
    primary = primary_documents(meeting)
    assert set(primary) == {"minutes"}
    assert primary["minutes"]["id"] == agreeing


def test_the_primary_document_of_each_kind_is_the_lowest_id_and_a_meeting_with_none_has_none():
    from docket.services.committee_documents import attach, primary_documents

    meeting = _meeting("Budget and Finance Committee")
    empty = _meeting("Public Safety Committee")
    minutes = _doc((BF,), disagrees=True)
    _doc((BF,), disagrees=True)
    agenda = _doc((BF,), kind="agenda")
    _doc((BF,), kind="agenda")
    attach(_city(), TODAY)
    primary = primary_documents(meeting)
    assert {kind: row["id"] for kind, row in primary.items()} == {"agenda": agenda, "minutes": minutes}
    assert primary["minutes"]["kind"] == "minutes"
    assert primary["minutes"]["url"].startswith(BUCKET)
    assert "text" not in primary["minutes"] and "text" not in primary["agenda"]
    assert primary_documents(empty) == {}


def test_deleting_a_meeting_leaves_its_documents_unattached_and_they_attach_again():
    from docket.services.committee_documents import attach, primary_documents

    doc = _doc((ED,))
    attach(_city(), TODAY)
    (created,) = _created()
    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE id = %s", (created["id"],))
    assert _attached(doc)[0] is None
    assert primary_documents(created["id"]) == {}

    report = attach(_city(), TODAY)
    (again,) = _created()
    assert _attached(doc) == (again["id"], "created")
    assert report.created == 1
