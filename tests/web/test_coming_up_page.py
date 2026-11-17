"""The coming-up page: ``/al/<slug>/coming-up/``, its link on the city page, its line in the sitemap.

The page prints what ``coming_up.list_entries`` returns and nothing else, so
these tests are about markup: which entries are on the page, what each
article holds, and where. What an entry *is* belongs to
``tests/services/test_coming_up.py``.

Rows are seeded through ``tests/support/coming_up_seed.py`` under Birmingham
and deleted before and after every test. Every test replaces
``coming_up._today`` with 2026-11-16 and seeds on fixed dates after it: the
checked-in schedule gives no neighborhood meeting after 2026-12-31, and
these tests must pass whenever they are run. Markup is read with
BeautifulSoup, so an assertion is about structure and not about how Jinja
escaped an apostrophe.

Plan `birmingham-coming-up`, M7.
"""

from __future__ import annotations

import re
from datetime import date, time
from pathlib import Path
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup

from tests.support import briefing_seed
from tests.support import coming_up_seed as seed

PAGE = "/al/birmingham/coming-up/"
NOV_17 = seed.NOV_17
DEC_1 = date(2026, 12, 1)
DEC_8 = date(2026, 12, 8)
CSS = Path(__file__).parents[2] / "src" / "docket" / "web" / "static" / "css" / "coming_up.css"
BADGES = ("meeting", "zoning", "weed-lots", "vacation", "budget", "hearing", "neighborhood")


@pytest.fixture(autouse=True)
def _a_fixed_day_and_no_leftover_rows(monkeypatch):
    from docket.services import coming_up

    seed.delete_seeded()
    monkeypatch.setattr(coming_up, "_today", lambda: seed.TODAY)
    yield
    seed.delete_seeded()


@pytest.fixture
def seeded():
    """A council meeting both sources list, one the calendar calls cancelled, one with no time, two hearings."""
    council_event = seed.event(seed.at(NOV_17, 9, 30), seed.COUNCIL_EVENT, ends=seed.at(NOV_17, 12, 0))
    council_row = seed.upcoming_row(NOV_17, start=time(11, 0), event_id=council_event)
    off_event = seed.event(
        seed.at(DEC_1, 9, 30), "BIRMINGHAM CITY COUNCIL MEETING, December 1, 2026", status="cancelled"
    )
    off_row = seed.upcoming_row(DEC_1, event_id=off_event)
    untimed_row = seed.upcoming_row(DEC_8, start=None)
    zoning, zoning_item = seed.hearing(seed.TITLES[63046])  # set for November 24, 2026
    weeds, weeds_item = seed.hearing(seed.TITLES[62882], seed.OCT_26)  # set for November 17, 2026; 212 lots
    return SimpleNamespace(
        council=f"calendar-{council_event}@docket.pub",
        council_event=council_event,
        council_row=council_row,
        off=f"calendar-{off_event}@docket.pub",
        off_row=off_row,
        untimed=f"meeting-{untimed_row}@docket.pub",
        zoning=f"hearing-{zoning}@docket.pub",
        zoning_id=zoning,
        zoning_item=zoning_item,
        weeds=f"hearing-{weeds}@docket.pub",
        weeds_id=weeds,
        weeds_item=weeds_item,
    )


def _body(client, path: str = PAGE) -> str:
    response = client.get(path)
    assert response.status_code == 200
    return response.get_data(as_text=True)


def _page(client, path: str = PAGE) -> BeautifulSoup:
    return BeautifulSoup(_body(client, path), "html.parser")


def _article(page, uid: str):
    found = [a for a in page.select("article[data-entry-uid]") if a["data-entry-uid"] == uid]
    assert len(found) == 1, f"{len(found)} articles for {uid}"
    return found[0]


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ")).strip()


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _listed(today: date = seed.TODAY):
    from docket.services import coming_up

    return coming_up.list_entries(seed.city_row(), today=today)


def _hearing_subject(hearing_id: int) -> str:
    from docket.db import db_cursor

    with db_cursor() as cur:
        cur.execute("SELECT subject FROM public_hearings WHERE id = %s", (hearing_id,))
        return cur.fetchone()["subject"]


def _association_with_call_in():
    """The first dated association of the checked-in schedule whose call-in details the schedule gives."""
    from docket.services import neighborhood_schedule

    schedule = neighborhood_schedule.get_schedule("birmingham")
    found = next((a for a in schedule.associations if a.remote is not None and a.ordinal is not None), None)
    assert found is not None, "no dated association of the schedule has call-in details"
    return found


# --- the address ------------------------------------------------------------


def test_the_page_is_served_for_birmingham(client):
    assert client.get(PAGE).status_code == 200


def test_a_city_without_the_flag_has_no_page(client):
    assert client.get("/al/mobile/coming-up/").status_code == 404


def test_a_slug_that_is_no_city_has_no_page(client):
    assert client.get("/al/nowhere/coming-up/").status_code == 404


def test_the_route_is_the_coming_up_page_and_not_the_badge_catch_all(client):
    """`/al/<slug>/<badge_slug>/` matches the same address; the fixed segment must win."""
    adapter = client.application.url_map.bind("localhost")
    endpoint, args = adapter.match(PAGE)

    assert endpoint == "public.coming_up_page"
    assert args == {"slug": "birmingham"}


# --- one article per entry --------------------------------------------------


def test_the_page_has_one_article_per_entry_of_the_service(client, seeded):
    body = _body(client)
    listed = _listed()

    assert len(listed) > 100  # the seeded five and the schedule's neighborhood meetings
    assert body.count('data-entry-uid="') == len(listed)
    page = BeautifulSoup(body, "html.parser")
    on_page = [a["data-entry-uid"] for a in page.select("article[data-entry-uid]")]
    assert len(on_page) == len(set(on_page))
    assert set(on_page) == {entry.uid for entry in listed}


def test_every_article_names_its_kind_and_has_the_uid_before_its_at_sign_as_its_id(client, seeded):
    page = _page(client)
    by_uid = {entry.uid: entry for entry in _listed()}

    for article in page.select("article[data-entry-uid]"):
        entry = by_uid[article["data-entry-uid"]]
        assert article["data-entry-kind"] == entry.kind
        assert article["id"] == entry.uid.split("@")[0]
    assert _article(page, seeded.zoning)["id"] == f"hearing-{seeded.zoning_id}"


def test_the_route_takes_no_date_from_the_address(client, seeded):
    plain = {a["data-entry-uid"] for a in _page(client).select("article[data-entry-uid]")}

    for query in ("?today=2027-03-01", "?date=2027-03-01", "?on=2027-03-01"):
        asked = {a["data-entry-uid"] for a in _page(client, PAGE + query).select("article[data-entry-uid]")}
        assert asked == plain


# --- the head of the page ---------------------------------------------------


def test_the_heading_names_the_city(client):
    page = _page(client)

    (h1,) = page.select("h1")
    assert _text(h1) == "What's coming up in Birmingham"
    assert _text(page.select_one("title")).startswith("What's coming up in Birmingham")


def test_the_lede_says_sixty_days_and_that_every_entry_is_linked_to_its_document(client):
    lede = _text(_page(client).select_one(".cu-lede"))

    assert "the next 60 days" in lede
    assert "links to the city document it came from" in lede


def test_the_subscribe_link_is_the_feeds_address(client):
    (link,) = [a for a in _page(client).select("a") if _text(a) == "Subscribe to this calendar"]

    assert link["href"] == "/al/birmingham/coming-up.ics"


def test_the_page_links_its_own_stylesheet(client):
    hrefs = [link["href"] for link in _page(client).select('link[rel="stylesheet"]')]

    assert any(href.endswith("/static/css/coming_up.css") for href in hrefs)


# --- dates ------------------------------------------------------------------


def test_each_date_is_a_section_with_the_long_date_as_its_heading_in_date_order(client, seeded):
    page = _page(client)
    sections = page.select("section.cu-day")
    headings = [_text(section.select_one("h2")) for section in sections]
    days = sorted({entry.on for entry in _listed()})

    assert headings == [f"{day:%A}, {day:%B} {day.day}, {day.year}" for day in days]
    assert "Tuesday, November 17, 2026" in headings
    assert "Wednesday, December 2, 2026" in headings  # no leading zero


def test_an_entry_sits_in_the_section_of_its_own_date(client, seeded):
    page = _page(client)
    by_uid = {entry.uid: entry for entry in _listed()}

    for section in page.select("section.cu-day"):
        heading = _text(section.select_one("h2"))
        for article in section.select("article[data-entry-uid]"):
            day = by_uid[article["data-entry-uid"]].on
            assert heading == f"{day:%A}, {day:%B} {day.day}, {day.year}"


def test_a_days_neighborhood_meetings_sit_together_under_one_summary_after_the_rest(client, seeded):
    page = _page(client)
    listed = _listed()
    (section,) = [s for s in page.select("section.cu-day") if _text(s.select_one("h2")) == "Tuesday, November 17, 2026"]
    expected = [e.uid for e in listed if e.on == NOV_17 and e.kind == "neighborhood"]
    assert len(expected) > 1

    (details,) = section.select("details")
    assert _text(details.select_one("summary")) == f"{len(expected)} neighborhood association meetings"
    inside = [a["data-entry-uid"] for a in details.select("article[data-entry-uid]")]
    assert inside == expected  # the service's order, kept
    assert all(a["data-entry-kind"] == "neighborhood" for a in details.select("article"))

    outside = [a for a in section.select("article[data-entry-uid]") if a["data-entry-uid"] not in inside]
    assert {a["data-entry-uid"] for a in outside} == {seeded.council, seeded.weeds}
    assert [a["data-entry-uid"] for a in outside] == [seeded.council, seeded.weeds]  # the service's order
    # The summary follows the day's meetings and hearings in the document.
    order = [node for node in section.find_all(["article", "details"]) if node.find_parent("details") is None]
    assert order[-1] is details


def test_no_meeting_or_hearing_is_inside_a_summary_block_and_every_neighborhood_meeting_is(client, seeded):
    page = _page(client)

    for article in page.select("article[data-entry-uid]"):
        inside = article.find_parent("details") is not None
        assert inside == (article["data-entry-kind"] == "neighborhood"), article["data-entry-uid"]


def test_a_day_with_one_neighborhood_meeting_says_meeting_and_a_day_with_none_has_no_summary(
    client, seeded, monkeypatch
):
    seed.use_schedule(monkeypatch, seed.association("Acipco-Finley"))  # December 2 alone, in the window
    page = _page(client)
    by_heading = {_text(s.select_one("h2")): s for s in page.select("section.cu-day")}

    (details,) = by_heading["Wednesday, December 2, 2026"].select("details")
    assert _text(details.select_one("summary")) == "1 neighborhood association meeting"
    assert by_heading["Tuesday, November 17, 2026"].select("details") == []
    assert len(page.select("details")) == 1


def test_a_window_with_nothing_in_it_says_so(client, monkeypatch):
    """No seeded row, and a day past the schedule's year."""
    from docket.services import coming_up

    monkeypatch.setattr(coming_up, "_today", lambda: date(2027, 3, 1))
    page = _page(client)

    assert page.select("article[data-entry-uid]") == []
    assert page.select("section.cu-day") == []
    assert "Nothing is listed for the next 60 days." in _text(page)


def test_a_window_with_entries_does_not_say_nothing_is_listed(client, seeded):
    assert "Nothing is listed" not in _text(_page(client))


# --- what an article holds --------------------------------------------------


def test_a_timed_meeting_prints_its_time_its_title_and_its_links_in_order(client, seeded):
    article = _article(_page(client), seeded.council)

    (when,) = article.select("time")
    assert _text(when) == "9:30 a.m. to 12:00 p.m."
    assert when["datetime"] == "2026-11-17T09:30:00-06:00"
    assert _text(article.select_one(".cu-entry-title")) == "City Council meeting"
    links = [(_text(a), a["href"]) for a in article.select(".cu-links a")]
    assert links == [
        ("City calendar", seed.source_url(seeded.council_event)),
        ("Agenda", seed.AGENDA),
        ("Meeting on docket.pub", f"/al/birmingham/meetings/{seeded.council_row}/"),
    ]


def test_a_meeting_with_a_start_and_no_end_prints_the_start_alone(client, seeded):
    article = _article(_page(client), seeded.off)

    (when,) = article.select("time")
    assert _text(when) == "9:30 a.m."


def test_an_afternoon_time_reads_p_m(client):
    event = seed.event(seed.at(seed.NOV_23, 15, 30), seed.COMMITTEE_EVENT, status="active")

    article = _article(_page(client), f"calendar-{event}@docket.pub")

    assert _text(article.select_one("time")) == "3:30 p.m."
    assert _text(article.select_one(".cu-entry-title")) == "Budget and Finance"


def test_an_entry_with_no_time_has_no_time_element(client, seeded):
    page = _page(client)

    for uid in (seeded.untimed, seeded.zoning, seeded.weeds):
        assert _article(page, uid).select("time") == []
        assert "<time" not in str(_article(page, uid))
    # and every article that has one is an entry that has a start
    by_uid = {entry.uid: entry for entry in _listed()}
    for article in page.select("article[data-entry-uid]"):
        assert bool(article.select("time")) == (by_uid[article["data-entry-uid"]].starts_at is not None)


def test_a_link_to_a_city_document_is_marked_external_and_one_to_docket_pub_is_not(client, seeded):
    article = _article(_page(client), seeded.council)
    by_label = {_text(a): a for a in article.select(".cu-links a")}

    assert by_label["City calendar"].get("rel") == ["external", "noopener"]
    assert by_label["Agenda"].get("rel") == ["external", "noopener"]
    assert by_label["Meeting on docket.pub"].get("rel") is None


def test_a_hearings_article_links_its_item_page_and_says_on_the_agenda_of(client, seeded):
    article = _article(_page(client), seeded.zoning)
    links = [(_text(a), a["href"]) for a in article.select(".cu-links a")]

    assert links == [
        ("City agenda", seed.AGENDA),
        ("On the agenda of October 13, 2026", f"/al/birmingham/items/{seeded.zoning_item}/"),
    ]
    assert _text(article.select_one(".cu-entry-title")) == "Zoning hearing"
    # the subject, as the service cut it, is the detail line
    (entry,) = [e for e in _listed() if e.uid == seeded.zoning]
    assert [_text(p) for p in article.select(".cu-detail")] == list(entry.detail)
    assert entry.detail[0].startswith("to consider the adoption of an Ordinance")


def test_a_weed_lot_hearing_says_how_many_properties_and_not_its_subject(client, seeded):
    article = _article(_page(client), seeded.weeds)
    text = _text(article)

    assert [_text(p) for p in article.select(".cu-detail")] == ["212 properties"]
    subject = _hearing_subject(seeded.weeds_id)
    assert subject and subject not in text
    assert "to hear and" not in text
    assert _text(article.select_one(".cu-entry-title")) == "Weed lots hearing"


def test_every_article_has_exactly_one_label_of_its_kind(client, seeded):
    page = _page(client)
    by_uid = {entry.uid: entry for entry in _listed()}

    for article in page.select("article[data-entry-uid]"):
        entry = by_uid[article["data-entry-uid"]]
        kinds = [
            span
            for span in article.select("span.cu-badge")
            if not any(c == "cu-badge--cancelled" for c in span["class"])
        ]
        assert len(kinds) == 1, article["data-entry-uid"]
        assert kinds[0]["class"] == ["cu-badge", f"cu-badge--{entry.badge}"]
        assert entry.badge in BADGES
        assert _text(kinds[0]) == entry.badge_label
    (zoning,) = _article(page, seeded.zoning).select("span.cu-badge")
    assert zoning["class"] == ["cu-badge", "cu-badge--zoning"]
    assert _text(zoning) == "Zoning"
    assert _text(_article(page, seeded.weeds).select_one("span.cu-badge")) == "Weed lots"
    assert _text(_article(page, seeded.council).select_one("span.cu-badge")) == "Meeting"


def test_the_label_comes_first_in_the_article_then_the_time_then_the_title(client, seeded):
    article = _article(_page(client), seeded.council)
    marked = article.find_all(lambda tag: tag.name == "time" or "cu-badge" in tag.get("class", [])
                              or "cu-entry-title" in tag.get("class", []) or "cu-links" in tag.get("class", []))

    assert [tag.name for tag in marked] == ["span", "time", "h3", "ul"]


def test_a_meeting_the_calendar_calls_cancelled_is_one_article_marked_cancelled_with_the_source_named(
    client, seeded
):
    page = _page(client)
    article = _article(page, seeded.off)

    assert article["data-entry-cancelled"] == "true"
    spans = article.select("span.cu-badge")
    assert [span["class"] for span in spans] == [["cu-badge", "cu-badge--meeting"], ["cu-badge", "cu-badge--cancelled"]]
    assert _text(spans[1]) == "Cancelled"
    assert [_text(p) for p in article.select(".cu-detail")] == [
        "Cancelled, according to the city calendar.",
        "The council's video site still lists it.",
    ]
    assert "according to the city calendar" in _text(article)
    # the pair is one article: the row has none of its own
    uids = {a["data-entry-uid"] for a in page.select("article[data-entry-uid]")}
    assert f"meeting-{seeded.off_row}@docket.pub" not in uids
    # its title and time are what they would have been
    assert _text(article.select_one(".cu-entry-title")) == "City Council meeting"
    assert _text(article.select_one("time")) == "9:30 a.m."


def test_no_other_article_is_marked_cancelled(client, seeded):
    page = _page(client)

    marked = [a["data-entry-uid"] for a in page.select("article[data-entry-cancelled]")]
    assert marked == [seeded.off]
    with_span = [
        span.find_parent("article")["data-entry-uid"] for span in page.select("span.cu-badge--cancelled")
    ]
    assert with_span == [seeded.off]


def test_a_neighborhood_meeting_with_call_in_details_shows_them_once_under_how_to_attend(client, seeded):
    from docket.services import coming_up

    association = _association_with_call_in()
    slug = coming_up.association_slug(association.name)
    page = _page(client)
    articles = [a for a in page.select("article[data-entry-uid]") if a["data-entry-uid"].startswith(f"na-{slug}-")]
    assert articles

    for article in articles:
        text = _text(article)
        assert text.count("How to attend") == 1
        assert text.count(_norm(association.remote)) == 1
        (block,) = article.select("div.cu-attend")
        labels = [_text(span) for span in block.select(".cu-attend-label")]
        assert labels[-1] == "Call-in"
        assert _norm(association.remote) in _text(block)
        if association.place is not None:
            assert labels == ["Where", "Call-in"]
            assert text.count(_norm(association.place)) == 1
        else:
            assert labels == ["Call-in"]


def test_the_attend_block_follows_the_detail_lines_and_holds_each_pair_as_label_then_text(client, monkeypatch):
    seed.use_schedule(
        monkeypatch,
        seed.association("Acipco-Finley", place="The hall", remote="Dial: 555 0100", modes=("in_person", "phone")),
    )
    (article,) = _page(client).select("article[data-entry-uid]")

    (block,) = article.select("div.cu-attend")
    assert _text(block) == "How to attend Where The hall Call-in Dial: 555 0100"
    assert [(_text(line.select_one(".cu-attend-label")), _text(line.select_one(".cu-attend-text")))
            for line in block.select(".cu-attend-line")] == [("Where", "The hall"), ("Call-in", "Dial: 555 0100")]
    assert _text(article).count("The hall") == 1  # the place is in the block and not a second time
    assert article.select(".cu-place") == []
    marked = article.find_all(lambda tag: any(c in ("cu-detail", "cu-attend", "cu-links") for c in tag.get("class", [])))
    assert [tag["class"][0] for tag in marked] == ["cu-detail", "cu-attend", "cu-links"]


def test_an_association_with_neither_place_nor_call_in_has_no_attend_block(client, monkeypatch):
    seed.use_schedule(monkeypatch, seed.association("Acipco-Finley", place=None, remote=None))
    (article,) = _page(client).select("article[data-entry-uid]")

    assert article.select(".cu-attend") == []
    assert "How to attend" not in _text(article)


def test_gate_city_has_where_alone_and_says_call_in_details_are_not_in_the_schedule(client):
    (article,) = [
        a for a in _page(client).select("article[data-entry-uid]") if a["data-entry-uid"].startswith("na-gate-city-")
    ]

    assert [_text(span) for span in article.select(".cu-attend-label")] == ["Where"]
    assert "Call-in details are not in the schedule" in [_text(p) for p in article.select(".cu-detail")]


def test_a_meeting_and_a_hearing_have_no_how_to_attend(client, seeded):
    page = _page(client)

    for uid in (seeded.council, seeded.off, seeded.untimed, seeded.zoning, seeded.weeds):
        article = _article(page, uid)
        assert "How to attend" not in _text(article)
        assert article.select(".cu-attend") == []


def test_a_neighborhood_article_carries_the_schedule_pdf_and_the_association_name(client):
    page = _page(client)
    (article,) = [
        a for a in page.select("article[data-entry-uid]") if a["data-entry-uid"] == "na-acipco-finley-20261202@docket.pub"
    ]

    assert [(_text(a), a["href"]) for a in article.select(".cu-links a")] == [("City schedule (PDF)", seed.PDF)]
    assert _text(article.select_one(".cu-entry-title")) == "Acipco-Finley Neighborhood Association"
    assert _text(article.select_one("time")) == "5:30 p.m."
    assert _text(article.select_one("span.cu-badge")) == "Neighborhood"
    assert [_text(p) for p in article.select(".cu-detail")] == ["In-Person"]


# --- under the list ---------------------------------------------------------


def test_where_these_dates_come_from_names_each_source_and_what_is_not_reflected(client):
    page = _page(client)
    (section,) = page.select("section.cu-sources")

    assert _text(section.select_one("h2")) == "Where these dates come from"
    text = _text(section)
    for words in (
        "the council's video site and the city's calendar",
        "shown marked cancelled, with the one that says so named",
        "read by docket.pub from the text of a resolution on a council agenda, without a language model",
        "may not yet have been adopted",
        "may still show on its first date",
        "computed by docket.pub from the monthly rule",
        "covers 2026 only",
        "moved for a holiday is not reflected",
        "revised February 3, 2026",
    ):
        assert words in text, words
    (link,) = [a for a in section.select("a") if a["href"] == seed.PDF]
    assert _text(link) == (
        "City of Birmingham Community Resource Services Division Neighborhood Association Meeting Schedule"
    )


def test_the_undated_associations_are_named_with_the_schedules_own_words(client):
    lines = [
        (_text(li.select_one(".cu-undated-name")), _text(li.select_one(".cu-undated-reason")))
        for li in _page(client).select(".cu-undated li")
    ]

    assert lines == [
        ("Bridlewood", "The schedule says: No Meetings"),
        ("Glen Iris", "The schedule says: First Monday of this month @ 6:30 pm"),
    ]


def test_a_schedule_that_dates_every_association_prints_no_undated_list(client, monkeypatch):
    seed.use_schedule(monkeypatch, seed.association("Acipco-Finley"))

    assert _page(client).select(".cu-undated") == []


# --- the city page and the sitemap ------------------------------------------


def test_the_birmingham_city_page_links_the_page_and_mobiles_does_not(client):
    briefing_seed.clear_caches()
    birmingham = _page(client, "/al/birmingham/")
    briefing_seed.clear_caches()
    mobile = _body(client, "/al/mobile/")

    (link,) = [a for a in birmingham.select("a") if a.get("href") == PAGE]
    assert _text(link) == "What's coming up →"
    assert link.find_parent("p")["class"] == ["brf-meetings-foot"]
    assert [_text(a) for a in link.find_parent("p").select("a")] == ["All meetings →", "What's coming up →"]
    assert "coming-up" not in mobile


def test_the_partial_draws_the_link_for_a_flagged_city_alone(render_partial):
    """Mobile's city page does not draw this partial at all, so the gate is tried on the partial itself."""
    flagged = render_partial(
        "partials/briefing/meetings.html", municipality=seed.city_row("birmingham"), briefing_meetings=[]
    )
    plain = render_partial("partials/briefing/meetings.html", municipality=seed.city_row("mobile"), briefing_meetings=[])

    assert 'href="/al/birmingham/coming-up/"' in flagged
    assert "coming-up" not in plain
    assert "All meetings →" in plain
    # the "Follow:" line is as it was
    for html in (flagged, plain):
        follow = BeautifulSoup(html, "html.parser").select_one("p.brf-follow")
        assert [_text(a) for a in follow.select("a")] == ["upcoming hearings (RSS)", "coverage"]


def test_the_sitemap_lists_the_page_for_birmingham_and_not_for_mobile(client):
    from docket.web import crawlers

    crawlers.clear_cache()
    birmingham = _body(client, "/sitemaps/birmingham/meetings.xml")
    mobile = _body(client, "/sitemaps/mobile/meetings.xml")
    crawlers.clear_cache()

    assert birmingham.count("<loc>http://localhost/al/birmingham/coming-up/</loc>") == 1
    assert "coming-up" not in mobile
    # among the first entries, after the three every city has
    first = re.findall(r"<loc>([^<]+)</loc>", birmingham)[:4]
    assert first == [
        "http://localhost/al/birmingham/",
        "http://localhost/al/birmingham/meetings/",
        "http://localhost/al/birmingham/council/",
        "http://localhost/al/birmingham/coming-up/",
    ]


def test_sitemap_has_coming_up_reads_the_flag():
    from docket.services import sitemap

    assert sitemap.has_coming_up("birmingham") is True
    assert sitemap.has_coming_up("mobile") is False
    assert sitemap.has_coming_up("nowhere") is False


def test_the_template_global_reads_the_flag(client):
    has = client.application.jinja_env.globals["has_coming_up"]

    assert has(seed.city_row("birmingham")) is True
    assert has(seed.city_row("mobile")) is False
    assert has(None) is False


# --- the labels' colours ----------------------------------------------------


def _luminance(colour: str) -> float:
    parts = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in parts]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(a: str, b: str) -> float:
    lighter, darker = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _badge_rules() -> dict[str, dict[str, str]]:
    """Each `.cu-badge--<token>` rule of the stylesheet, as its declarations."""
    rules: dict[str, dict[str, str]] = {}
    for token, body in re.findall(r"\.cu-badge--([a-z-]+)\s*\{([^}]*)\}", CSS.read_text()):
        assert token not in rules, f"two rules for cu-badge--{token}"
        rules[token] = {
            name.strip(): value.strip() for name, value in (d.split(":", 1) for d in body.split(";") if d.strip())
        }
    return rules


def test_each_of_the_eight_labels_has_its_own_two_colours_and_nothing_else():
    rules = _badge_rules()

    assert set(rules) == {*BADGES, "cancelled"}
    for token, declarations in rules.items():
        # only colour differs between kinds: none is larger, bolder, or placed differently
        assert set(declarations) == {"background", "color"}, token
        for value in declarations.values():
            assert re.fullmatch(r"#[0-9a-f]{6}", value), f"{token}: {value}"
    pairs = [(d["background"], d["color"]) for d in rules.values()]
    assert len(set(pairs)) == 8
    assert len({background for background, _ in pairs}) == 8


@pytest.mark.parametrize("token", [*BADGES, "cancelled"])
def test_a_labels_text_has_a_contrast_of_at_least_4_5_against_its_background(token):
    declarations = _badge_rules()[token]

    assert _contrast(declarations["background"], declarations["color"]) >= 4.5


def test_the_contrast_arithmetic_is_the_standard_one():
    assert round(_contrast("#000000", "#ffffff"), 2) == 21.0
    assert round(_contrast("#777777", "#ffffff"), 2) == 4.48  # the well-known just-failing grey
    assert _contrast("#ffffff", "#000000") == _contrast("#000000", "#ffffff")


def test_the_stylesheet_carries_no_dark_theme_and_neither_do_the_styles_it_sits_on():
    """M7: a dark theme in the base styles would oblige a second pair per label. There is none."""
    static = CSS.parents[1]
    for sheet in (CSS, static / "styles.css", static / "layout.css", static / "css" / "how_it_works.css"):
        assert "prefers-color-scheme" not in sheet.read_text(), sheet.name
