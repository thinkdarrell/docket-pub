"""The meeting page shows a committee's own documents and what it took up.

``docket.services.committee_documents.for_meeting`` reads a meeting's
attached ``committee_documents`` rows and the items of its primary minutes;
``meeting_detail`` passes the result to the template as ``committee_record``
and ``partials/committee_record.html`` prints it after the hero's strip.

Nothing is fetched and no PDF is read: every meeting, document and item is a
row the test inserts, as a reading and ``attach`` would have left it, under
Birmingham and dated in the last month. The meetings have an ``external_id``
beginning ``cdpage-`` and the documents an address under ``cdpage/``; all are
deleted after. The service's name is imported inside each test, so the file
collects before it exists. Runs in the web tier against the throwaway
database (DATABASE_URL names docket_test_*).

Plan `committee-documents`, M5.
"""

from __future__ import annotations

import html as html_lib
import itertools
import re
from datetime import date, timedelta

import pytest

from docket.db import db_cursor
from tests.support import briefing_seed

PREFIX = "cdpage-"
ROOT = "https://www.birminghamal.gov/government/city-council/council/council-committees-2025-2027/"
BUCKET = "https://s3.us-east-2.amazonaws.com/assets.birminghamal.gov/cdpage/"
BF = "Budget and Finance"

DAY = date.today() - timedelta(days=12)

OTHER_ACTION = "Applicant Not Present for Meeting."
CONSENT_ACTION = (
    "Councilor Alexander Motioned to Recommend. Councilor Woods Seconded. "
    "Item Recommended to the City Council Consent Agenda."
)

_serial = itertools.count(1)


def _city() -> int:
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham'")
        return cur.fetchone()["id"]


def _delete_all() -> None:
    with db_cursor() as cur:
        cur.execute("DELETE FROM committee_documents WHERE url LIKE %s", (BUCKET + "%",))
        cur.execute("DELETE FROM meetings WHERE external_id LIKE %s", (PREFIX + "%",))
    briefing_seed.clear_caches()


@pytest.fixture(autouse=True)
def clean():
    _delete_all()
    yield
    _delete_all()


def _meeting(*, meeting_type: str = "committee", title: str = "Budget and Finance Committee Meeting",
             body_name: str | None = "Budget and Finance Committee") -> int:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type,
                                     session_kind, body_name, type_source)
               VALUES (%s, %s, %s, %s, %s, 'regular', %s, 'title') RETURNING id""",
            (_city(), f"{PREFIX}{next(_serial)}", title, DAY, meeting_type, body_name),
        )
        return cur.fetchone()["id"]


def _doc(meeting_id: int | None, kind: str | None = "minutes", *, status: str = "read", disagrees: bool = False,
         present: str | None = None) -> tuple[int, str]:
    """One document as a reading and ``attach`` leave it; its id and address."""
    url = f"{BUCKET}{kind}-{next(_serial)}.pdf"
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO committee_documents
                      (municipality_id, url, page_url, page_committee, status, kind, committees, meeting_date,
                       date_source, listing_disagrees, present, parser_version, meeting_id, attached_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'header', %s, %s, 1, %s, %s) RETURNING id""",
            (_city(), url, ROOT + "budget-finance-committee", BF, status, kind, [BF], DAY, disagrees, present,
             meeting_id, "matched" if meeting_id else None),
        )
        return cur.fetchone()["id"], url


def _item(document_id: int, position: int, name: str, category: str, action: str, *, body: str = "",
          group: str | None = None, moved_by: str | None = None, seconded_by: str | None = None) -> None:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO committee_items
                      (document_id, position, heading_label, heading_text, owns_heading, group_text, name, body,
                       action_text, action_category, moved_by, seconded_by)
               VALUES (%s, %s, NULL, NULL, FALSE, %s, %s, %s, %s, %s, %s, %s)""",
            (document_id, position, group, name, body, action, category, moved_by, seconded_by),
        )


def _three_items(document_id: int) -> None:
    """The plan's three: the minutes approved first, as minutes print it."""
    _item(document_id, 1, "APPROVAL OF MINUTES", "minutes_approved", "Minutes were Approved as Recorded.",
          moved_by="Woods", seconded_by="Tate")
    _item(document_id, 2, "Friends of Avondale Park", "recommended_consent", CONSENT_ACTION,
          body="An item appropriating $4,000 to Friends of Avondale Park.", moved_by="Alexander",
          seconded_by="Woods")
    _item(document_id, 3, "Pike Road Market & Meats", "other", OTHER_ACTION)


def _seeded() -> dict:
    """A committee meeting with an agenda and minutes of three items."""
    meeting_id = _meeting()
    _, agenda_url = _doc(meeting_id, "agenda")
    minutes_id, minutes_url = _doc(meeting_id, "minutes", present="Alexander, Tate, Woods")
    _three_items(minutes_id)
    return {"meeting": meeting_id, "agenda_url": agenda_url, "minutes_url": minutes_url, "minutes": minutes_id}


def _page(client, meeting_id: int) -> str:
    resp = client.get(f"/al/birmingham/meetings/{meeting_id}/")
    assert resp.status_code == 200, resp.status_code
    return html_lib.unescape(resp.get_data(as_text=True))


def _record(page: str) -> str:
    """The committee record's own section of the page."""
    start = page.index('<section class="committee-record"')
    return page[start:page.index("</section>", start) + len("</section>")]


def _strip(page: str) -> str:
    """The hero's strip of three figures."""
    start = page.index('<div class="kpi-strip">')
    return page[start:page.index("</section>", start)]


def _words(markup: str) -> str:
    """What a reader with no styles reads: the text, tags gone, spaces single."""
    return " ".join(re.sub(r"<[^>]+>", " ", markup).split())


# -- for_meeting ---------------------------------------------------------------


def test_for_meeting_is_none_for_a_meeting_with_no_document():
    from docket.services.committee_documents import for_meeting

    meeting_id = _meeting()
    _doc(None, "minutes")  # read, and attached to nothing
    assert for_meeting(meeting_id) is None


def test_for_meeting_gives_the_documents_primaries_first_and_the_primary_minutes_items_in_order():
    from docket.services.committee_documents import for_meeting

    meeting_id = _meeting()
    stray_id, stray_url = _doc(meeting_id, "minutes", disagrees=True, present="Nobody")
    minutes_id, minutes_url = _doc(meeting_id, "minutes", present="Alexander, Tate")
    _, agenda_url = _doc(meeting_id, "agenda", status="no_text")
    _, third_url = _doc(meeting_id, "minutes")
    _doc(meeting_id, None, status="not_committee")  # a later reading found no kind: nothing to call it
    _item(stray_id, 1, "From the other copy", "other", "Not shown.")
    _item(minutes_id, 2, "Second", "recommended", "Item Recommended to the City Council Agenda.")
    _item(minutes_id, 1, "First", "minutes_approved", "Minutes were Approved.")
    _item(minutes_id, 3, "Third", "adjourned", "Meeting Adjourned.")
    other_meeting = _meeting()
    other_id, _ = _doc(other_meeting, "minutes")
    _item(other_id, 1, "Another meeting's", "other", "Elsewhere.")

    record = for_meeting(meeting_id)

    assert [(d.kind, d.url, d.is_primary, d.has_text) for d in record.documents] == [
        ("agenda", agenda_url, True, False),
        ("minutes", minutes_url, True, True),
        ("minutes", stray_url, False, True),
        ("minutes", third_url, False, True),
    ]
    assert record.present == "Alexander, Tate"
    assert [i["name"] for i in record.items] == ["First", "Second", "Third"]
    assert [i["name"] for i in record.substantive] == ["Second"]
    assert [i["name"] for i in record.procedural] == ["First", "Third"]
    assert record.has_minutes
    assert record.minutes_url == minutes_url


def test_for_meeting_with_an_agenda_alone_has_no_minutes_no_items_and_nobody_present():
    from docket.services.committee_documents import for_meeting

    meeting_id = _meeting()
    _, agenda_url = _doc(meeting_id, "agenda")

    record = for_meeting(meeting_id)

    assert [(d.kind, d.url, d.is_primary, d.has_text) for d in record.documents] == [
        ("agenda", agenda_url, True, True)
    ]
    assert not record.has_minutes
    assert record.present is None and record.items == () and record.minutes_url is None


# -- the page ------------------------------------------------------------------


def test_the_page_shows_the_documents_and_what_the_committee_took_up(client):
    seeded = _seeded()
    page = _page(client, seeded["meeting"])
    record = _record(page)
    words = _words(record)

    assert "From the committee's own documents" in record
    assert f'href="{seeded["agenda_url"]}"' in record
    assert f'href="{seeded["minutes_url"]}"' in record
    assert "Agenda (PDF)" in words and "Minutes (PDF)" in words
    assert "Councilors present: Alexander, Tate, Woods" in words
    assert "What the committee took up" in record
    assert "Friends of Avondale Park" in record
    assert "Moved by Alexander, seconded by Woods" in words
    assert "Recommended to the council's consent agenda" in record
    assert f"The minutes record: {OTHER_ACTION}" in words
    assert "Pike Road Market & Meats" in words
    assert "A committee recommends; it does not decide. No committee action is final without a vote of the full " \
           "council." in words
    assert "not yet posted" not in record
    assert "Items in the minutes" in _strip(page)


def test_the_record_follows_the_strip_and_comes_before_the_source_links(client):
    seeded = _seeded()
    page = _page(client, seeded["meeting"])
    strip_end = page.index("</section>", page.index('<div class="kpi-strip">'))
    between = page[strip_end + len("</section>"):page.index('<section class="committee-record"')]
    assert between.strip() == ""
    assert page.index('<section class="committee-record"') < page.index('<section class="mtg-sources">')


def test_a_label_is_printed_as_written_and_the_minutes_words_are_escaped(client):
    seeded = _seeded()
    raw = client.get(f"/al/birmingham/meetings/{seeded['meeting']}/").get_data(as_text=True)
    assert "Recommended to the council's consent agenda" in raw
    assert "Pike Road Market &amp; Meats" in raw and "Pike Road Market & Meats" not in raw


def test_each_document_opens_the_citys_address_in_a_new_tab(client):
    seeded = _seeded()
    record = _record(_page(client, seeded["meeting"]))
    links = re.findall(r"<a [^>]*>", record)
    assert len(links) == 2
    for url, link in zip((seeded["agenda_url"], seeded["minutes_url"]), links):
        assert f'href="{url}"' in link and 'target="_blank"' in link and 'rel="noopener"' in link
    assert f'<blockquote cite="{seeded["minutes_url"]}">' in record


def test_procedural_items_come_last_and_closed(client):
    seeded = _seeded()
    record = _record(_page(client, seeded["meeting"]))
    assert record.index("APPROVAL OF MINUTES") > record.index("Procedural") > record.index("Pike Road Market")
    assert record.index("Friends of Avondale Park") < record.index("Pike Road Market")
    assert "<summary>Procedural</summary>" in record
    assert "<details open" not in record and " open>" not in record
    procedural = record[record.index("<summary>Procedural</summary>"):]
    assert "Moved by Woods, seconded by Tate" in _words(procedural)
    assert "The minutes record: Minutes were Approved as Recorded." in _words(procedural)
    # A procedural category has no label of its own.
    assert "t-mono committee-item__outcome" not in procedural


def test_the_strip_counts_the_items_that_are_not_procedural(client):
    seeded = _seeded()
    strip = _words(_strip(_page(client, seeded["meeting"])))
    assert strip.startswith("Items in the minutes 2 Votes 0 committees record motions, not roll calls Total dollars")
    assert "Agenda items" not in strip and "consent ·" not in strip and "none recorded" not in strip


def test_a_meeting_whose_minutes_are_all_procedural_keeps_its_strip(client):
    meeting_id = _meeting()
    minutes_id, _ = _doc(meeting_id, "minutes")
    _item(minutes_id, 1, "APPROVAL OF MINUTES", "minutes_approved", "Minutes were Approved.")
    page = _page(client, meeting_id)
    strip = _words(_strip(page))
    assert strip.startswith("Items in the minutes 0 Votes 0 committees record motions, not roll calls")
    record = _record(page)
    assert "What the committee took up" in record and "<summary>Procedural</summary>" in record
    assert "<ol" in record and record.count("<ol") == 1


def test_a_meeting_with_only_an_agenda_says_the_minutes_are_not_yet_posted(client):
    meeting_id = _meeting()
    _, agenda_url = _doc(meeting_id, "agenda")
    page = _page(client, meeting_id)
    record = _record(page)
    assert f'href="{agenda_url}"' in record
    assert ("The committee's minutes for this meeting are not yet posted. The agenda shows what was planned; "
            "it does not show what the committee did.") in _words(record)
    assert "What the committee took up" not in record
    assert "Councilors present" not in record
    assert "A committee recommends; it does not decide." in record
    strip = _words(_strip(page))
    assert strip.startswith("Agenda items 0 0 consent · 0 regular Votes 0 none recorded")


def test_a_meeting_with_no_document_shows_no_record_and_its_strip_is_unchanged(client):
    meeting_id = _meeting()
    _doc(None, "minutes")
    page = _page(client, meeting_id)
    assert "From the committee's own documents" not in page
    assert 'class="committee-record"' not in page
    strip = _words(_strip(page))
    assert strip.startswith("Agenda items 0 0 consent · 0 regular Votes 0 none recorded")
    assert "Items in the minutes" not in page


def test_a_council_meetings_strip_is_unchanged(client):
    meeting_id = _meeting(meeting_type="council", title="Regular City Council Meeting", body_name=None)
    page = _page(client, meeting_id)
    strip = _words(_strip(page))
    assert strip.startswith("Agenda items 0 0 consent · 0 regular Votes 0 none recorded Total dollars $0")
    assert "Items in the minutes" not in page
    assert "From the committee's own documents" not in page


def test_a_meeting_that_has_agenda_items_keeps_the_agenda_items_figure(client):
    seeded = _seeded()
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO agenda_items (meeting_id, external_id, item_number, title) VALUES (%s, %s, '1', 'An item')",
            (seeded["meeting"], f"{PREFIX}item-{next(_serial)}"),
        )
    try:
        page = _page(client, seeded["meeting"])
        strip = _words(_strip(page))
        assert strip.startswith("Agenda items 1 0 consent · 1 regular Votes 0 none recorded")
        assert "Items in the minutes" not in strip
        assert "What the committee took up" in _record(page)
    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM agenda_items WHERE meeting_id = %s", (seeded["meeting"],))


def test_a_second_document_of_a_kind_is_another_copy_and_a_scanned_one_is_not_read(client):
    meeting_id = _meeting()
    stray_id, stray_url = _doc(meeting_id, "minutes", disagrees=True, present="Nobody")
    minutes_id, minutes_url = _doc(meeting_id, "minutes", present="Tate")
    _, agenda_url = _doc(meeting_id, "agenda", status="no_text")
    _item(stray_id, 1, "From the other copy", "other", "Not shown.")
    _item(minutes_id, 1, "Shown", "recommended", "Item Recommended to the City Council Agenda.")

    record = _record(_page(client, meeting_id))
    docs = re.findall(r"<li>(.*?)</li>", record[:record.index("</ul>")], flags=re.DOTALL)

    assert [_words(d) for d in docs] == [
        "Agenda (PDF) scanned image; not read",
        "Minutes (PDF)",
        "Minutes (PDF) another copy",
    ]
    assert [re.search(r'href="([^"]+)"', d).group(1) for d in docs] == [agenda_url, minutes_url, stray_url]
    assert "Councilors present: Tate" in _words(record)
    assert "From the other copy" not in record and "Nobody" not in record
    assert "not yet posted" not in record


def test_minutes_that_were_read_and_hold_no_item_are_still_minutes(client):
    meeting_id = _meeting()
    _doc(meeting_id, "agenda")
    _doc(meeting_id, "minutes", present="Tate")
    record = _record(_page(client, meeting_id))
    assert "Councilors present: Tate" in _words(record)
    assert "not yet posted" not in record
    assert "What the committee took up" not in record and "<ol" not in record


def test_procedural_items_show_their_group_once_too(client):
    meeting_id = _meeting()
    minutes_id, _ = _doc(meeting_id, "minutes")
    _item(minutes_id, 1, "Minutes of May", "minutes_approved", "Minutes were Approved.", group="I. OPENING")
    _item(minutes_id, 2, "Minutes of June", "minutes_approved", "Minutes were Approved.", group="I. OPENING")
    record = _record(_page(client, meeting_id))
    assert record.count("I. OPENING") == 1
    assert record.index("I. OPENING") < record.index("Minutes of May") < record.index("Minutes of June")


def test_scanned_minutes_alone_say_only_that_they_were_not_read(client):
    meeting_id = _meeting()
    _doc(meeting_id, "minutes", status="no_text")
    page = _page(client, meeting_id)
    record = _record(page)
    assert "Minutes (PDF) scanned image; not read" in _words(record)
    assert "What the committee took up" not in record
    assert "Councilors present" not in record
    assert "not yet posted" not in record
    assert "<ol" not in record and "Procedural" not in record
    assert _words(_strip(page)).startswith("Agenda items 0")


def test_an_item_shows_only_what_the_minutes_gave_it(client):
    meeting_id = _meeting()
    minutes_id, minutes_url = _doc(meeting_id, "minutes")  # nobody listed as present
    group = "C. LIQUOR LICENSES"
    _item(minutes_id, 1, "Welcome Mart", "recommended_no_quorum",
          "Item Recommended to the City Council Agenda By The Committee Chair – Lack of Quorum.", group=group,
          body="Welcome Mart\nThere are no tax delinquencies for this location.")
    _item(minutes_id, 2, "LA Cabana", "other", "", group=group, body="LA Cabana", moved_by="Tate")
    _item(minutes_id, 3, "Resolution: Motorola", "delayed", "Item Delayed.", group="D. Ordinances/Resolutions",
          seconded_by="Smith")
    _item(minutes_id, 4, "Parking <Reform> Update", "information_only", "No Action – Information Only.")

    page = client.get(f"/al/birmingham/meetings/{meeting_id}/").get_data(as_text=True)
    assert "Parking &lt;Reform&gt; Update" in page
    record = _record(html_lib.unescape(page))
    items = re.findall(r'<li class="committee-item">(.*?)</li>', record, flags=re.DOTALL)
    assert len(items) == 4
    first, second, third, fourth = items

    assert "Councilors present" not in record
    # The group, once, before the first item that has it.
    assert record.count(group) == 1 and group in first and "D. Ordinances/Resolutions" in third
    assert record.count("D. Ordinances/Resolutions") == 1
    assert "committee-item__group" not in fourth
    # The body, closed, and only when it says more than the name.
    assert "<details>" in first and "<summary>What the minutes say</summary>" in first
    assert "There are no tax delinquencies for this location." in first
    assert "<details" not in second and "<details" not in third and "<details" not in fourth
    assert record.count("What the minutes say") == 1
    # The motion: both, one, or nothing.
    assert "Moved by" not in first and "econded by" not in first
    assert "Moved by Tate" in _words(second) and "econded by" not in second
    assert "Seconded by Smith" in _words(third) and "Moved by" not in third
    # The label, and the minutes' own words; no words, no quotation.
    assert "Sent to the council by the chair; no quorum" in first
    assert "The minutes record: Item Recommended to the City Council Agenda By The Committee Chair – Lack of " \
           "Quorum." in _words(first)
    assert "The minutes record" not in second and "<blockquote" not in second
    assert "committee-item__outcome" not in second
    assert "Delayed" in third and "Information only; no action" in fourth
    # No procedural item, no "Procedural".
    assert "Procedural" not in record and record.count("<ol") == 1
    assert f'<blockquote cite="{minutes_url}">' in fourth


@pytest.mark.parametrize("category, label", [
    ("recommended", "Recommended to the council"),
    ("recommended_consent", "Recommended to the council's consent agenda"),
    ("recommended_no_quorum", "Sent to the council by the chair; no quorum"),
    ("no_recommendation", "Sent to the council with no recommendation"),
    ("recommended_deny", "Sent to the council with a recommendation to deny"),
    ("information_only", "Information only; no action"),
    ("withdrawn", "Withdrawn"),
    ("tabled", "Tabled"),
    ("delayed", "Delayed"),
])
def test_each_category_has_its_label(client, category, label):
    meeting_id = _meeting()
    minutes_id, _ = _doc(meeting_id, "minutes")
    _item(minutes_id, 1, "An item", category, "The words of the minutes.")
    record = _record(_page(client, meeting_id))
    assert f'<p class="t-mono committee-item__outcome">{label}</p>' in record


def test_no_committee_item_is_given_a_vote_or_a_tally(client):
    seeded = _seeded()
    page = _page(client, seeded["meeting"])
    for part in (_words(_record(page)), _words(_strip(page))):
        assert not re.search(r"\b(passed|failed|yeas?|nays?|ayes?)\b", part, flags=re.IGNORECASE), part
        assert not re.search(r"\b\d+\s*[–-]\s*\d+\b", part), part
        assert not re.search(r"\b\d+\s+to\s+\d+\b", part), part
