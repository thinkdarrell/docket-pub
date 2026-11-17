"""The calendar feed: ``/al/<slug>/coming-up.ics``, its narrowed forms, and the page's ways to subscribe.

The feed and the page are built from one call of ``coming_up.list_entries``,
so the central test here asks for both from the same seeded rows and finds
one event per article, with the same identifiers. What the calendar text
looks like line by line belongs to ``tests/unit/test_ics.py``.

Rows are seeded through ``tests/support/coming_up_seed.py`` under Birmingham
and deleted before and after every test. Every test replaces
``coming_up._today`` with 2026-11-16 and seeds on fixed dates after it: the
checked-in schedule gives no neighborhood meeting after 2026-12-31, and
these tests must pass whenever they are run. Flask's test client asks as
host ``localhost`` and the application sets no ``SERVER_NAME``.

Plan `birmingham-coming-up`, M8.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timezone
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from bs4 import BeautifulSoup

from tests.support import briefing_seed
from tests.support import coming_up_seed as seed

PAGE = "/al/birmingham/coming-up/"
FEED = "/al/birmingham/coming-up.ics"
WEBCAL = "webcal://localhost/al/birmingham/coming-up.ics"
NOV_17 = seed.NOV_17
DEC_1 = date(2026, 12, 1)
DEC_8 = date(2026, 12, 8)


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
    council_event = seed.event(
        seed.at(NOV_17, 9, 30), seed.COUNCIL_EVENT, ends=seed.at(NOV_17, 12, 0)
    )
    seed.upcoming_row(NOV_17, start=time(11, 0), event_id=council_event)
    off_event = seed.event(
        seed.at(DEC_1, 9, 30),
        "BIRMINGHAM CITY COUNCIL MEETING, December 1, 2026",
        status="cancelled",
    )
    seed.upcoming_row(DEC_1, event_id=off_event)
    untimed_row = seed.upcoming_row(DEC_8, start=None)
    zoning, zoning_item = seed.hearing(seed.TITLES[63046])  # set for November 24, 2026
    weeds, _ = seed.hearing(
        seed.TITLES[62882], seed.OCT_26
    )  # set for November 17, 2026; 212 lots
    return SimpleNamespace(
        council=f"calendar-{council_event}@docket.pub",
        off=f"calendar-{off_event}@docket.pub",
        untimed=f"meeting-{untimed_row}@docket.pub",
        zoning=f"hearing-{zoning}@docket.pub",
        zoning_item=zoning_item,
        weeds=f"hearing-{weeds}@docket.pub",
    )


def _feed(client, path: str = FEED) -> str:
    response = client.get(path)
    assert response.status_code == 200, path
    return response.get_data(as_text=True)


def _page(client, path: str = PAGE) -> BeautifulSoup:
    response = client.get(path)
    assert response.status_code == 200
    return BeautifulSoup(response.get_data(as_text=True), "html.parser")


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ")).strip()


def _unfold(text: str) -> list[str]:
    out: list[str] = []
    for line in text.split("\r\n"):
        if line.startswith(" "):
            out[-1] += line[1:]
        elif line:
            out.append(line)
    return out


def _unescape(value: str) -> str:
    out, i = [], 0
    while i < len(value):
        if value[i] == "\\" and i + 1 < len(value):
            out.append("\n" if value[i + 1] in "nN" else value[i + 1])
            i += 2
        else:
            out.append(value[i])
            i += 1
    return "".join(out)


def _events(text: str) -> dict[str, list[str]]:
    """Each event's lines, by its UID."""
    events: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            current = []
        elif line == "END:VEVENT":
            (uid,) = [
                entry.split(":", 1)[1] for entry in current if entry.startswith("UID:")
            ]
            assert uid not in events, f"two events with the UID {uid}"
            events[uid] = current
            current = None
        elif current is not None:
            current.append(line)
    return events


def _value(event: list[str], name: str) -> str:
    found = [line for line in event if line.split(":", 1)[0].split(";", 1)[0] == name]
    assert len(found) == 1, f"{len(found)} {name} lines"
    return found[0].split(":", 1)[1]


def _calendar_name(text: str) -> str:
    (line,) = [line for line in _unfold(text) if line.startswith("X-WR-CALNAME:")]
    return _unescape(line.split(":", 1)[1])


def _uids_on_page(page, kind: str | None = None) -> set[str]:
    return {
        a["data-entry-uid"]
        for a in page.select("article[data-entry-uid]")
        if kind is None or a["data-entry-kind"] == kind
    }


# --- the address ------------------------------------------------------------


def test_the_feed_is_served_for_birmingham_as_a_calendar(client):
    response = client.get(FEED)

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/calendar")
    assert response.headers["Content-Type"] == "text/calendar; charset=utf-8"
    assert response.headers["Cache-Control"] == "public, max-age=3600"
    assert (
        response.headers["Content-Disposition"]
        == 'inline; filename="birmingham-coming-up.ics"'
    )


def test_a_city_without_the_flag_has_no_feed(client):
    assert client.get("/al/mobile/coming-up.ics").status_code == 404


def test_a_slug_that_is_no_city_has_no_feed(client):
    assert client.get("/al/nowhere/coming-up.ics").status_code == 404


def test_the_route_is_the_feed_and_not_the_badge_catch_all(client):
    adapter = client.application.url_map.bind("localhost")
    endpoint, args = adapter.match(FEED)

    assert endpoint == "public.coming_up_ics"
    assert args == {"slug": "birmingham"}


def test_the_feed_opens_as_a_calendar_named_for_the_city(client, seeded):
    body = _feed(client)

    assert body.split("\r\n")[:3] == [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//docket.pub//Coming up//EN",
    ]
    assert body.endswith("END:VCALENDAR\r\n")
    assert _calendar_name(body) == "Birmingham coming up"


# --- one event per entry on the page ----------------------------------------


def test_the_feed_has_one_event_per_article_of_the_page_with_the_same_uids(
    client, seeded
):
    page_body = client.get(PAGE).get_data(as_text=True)
    lines = _unfold(_feed(client))

    on_page = page_body.count('data-entry-uid="')
    assert on_page > 100  # the seeded five and the schedule's neighborhood meetings
    assert lines.count("BEGIN:VEVENT") == on_page
    assert lines.count("END:VEVENT") == on_page
    uids = [line.split(":", 1)[1] for line in lines if line.startswith("UID:")]
    assert len(uids) == len(set(uids)) == on_page
    assert set(uids) == _uids_on_page(BeautifulSoup(page_body, "html.parser"))
    assert {
        seeded.council,
        seeded.off,
        seeded.untimed,
        seeded.zoning,
        seeded.weeds,
    } <= set(uids)


def test_the_events_are_in_the_services_order(client, seeded):
    from docket.services import coming_up

    listed = coming_up.list_entries(seed.city_row(), today=seed.TODAY)
    uids = [
        line.split(":", 1)[1]
        for line in _unfold(_feed(client))
        if line.startswith("UID:")
    ]

    assert uids == [entry.uid for entry in listed]


def test_every_event_is_stamped_with_the_time_of_the_request(client, seeded):
    before = datetime.now(timezone.utc).replace(microsecond=0)
    events = _events(_feed(client))
    after = datetime.now(timezone.utc)

    stamps = {_value(event, "DTSTAMP") for event in events.values()}
    assert len(stamps) == 1
    stamp = datetime.strptime(stamps.pop(), "%Y%m%dT%H%M%SZ").replace(
        tzinfo=timezone.utc
    )
    assert before <= stamp <= after


# --- what an event holds ----------------------------------------------------


def test_a_hearing_is_an_all_day_event_with_a_url(client, seeded):
    event = _events(_feed(client))[seeded.zoning]

    assert "DTSTART;VALUE=DATE:20261124" in event
    assert "DTEND;VALUE=DATE:20261125" in event
    assert _value(event, "URL") == seed.AGENDA
    assert _value(event, "SUMMARY") == "Zoning hearing"
    assert _value(event, "CATEGORIES") == "Public hearing"


def test_the_merged_meeting_starts_when_the_calendar_event_does_in_utc(client, seeded):
    event = _events(_feed(client))[seeded.council]

    # the calendar's 9:30 a.m. Chicago, not the video site's 11:00
    assert _value(event, "DTSTART") == "20261117T153000Z"
    assert _value(event, "DTEND") == "20261117T180000Z"


def test_a_meeting_with_no_time_is_an_all_day_event(client, seeded):
    event = _events(_feed(client))[seeded.untimed]

    assert "DTSTART;VALUE=DATE:20261208" in event
    assert "DTEND;VALUE=DATE:20261209" in event


def test_a_hearings_description_holds_the_city_agenda_as_seeded_and_its_item_page_made_absolute(
    client, seeded
):
    body = _feed(client)
    description = _unescape(_value(_events(body)[seeded.zoning], "DESCRIPTION"))
    lines = description.split("\n")

    assert description.count(seed.AGENDA) == 1
    assert f"City agenda: {seed.AGENDA}" in lines
    item_page = f"http://localhost/al/birmingham/items/{seeded.zoning_item}/"
    assert f"On the agenda of October 13, 2026: {item_page}" in lines
    assert lines[-1] == "From docket.pub: http://localhost/al/birmingham/coming-up/"
    assert "localhost/http" not in body


def test_a_cancelled_meeting_is_in_the_feed_and_its_summary_says_so(client, seeded):
    events = _events(_feed(client))
    off = events[seeded.off]

    assert _value(off, "SUMMARY") == "Cancelled: City Council meeting"
    assert _unescape(_value(off, "DESCRIPTION")).startswith(
        "Cancelled, according to the city calendar."
    )
    assert _value(events[seeded.council], "SUMMARY") == "City Council meeting"
    assert not [
        line for event in events.values() for line in event if line.startswith("STATUS")
    ]


def test_a_neighborhood_meeting_carries_where_and_how_to_call_in(client, monkeypatch):
    association = seed.association(
        "Acipco-Finley", place="A Test Hall, 1 Main St", remote="Dial: 205-555-0100"
    )
    seed.use_schedule(monkeypatch, association)
    (event,) = _events(_feed(client)).values()

    assert _value(event, "UID") == "na-acipco-finley-20261202@docket.pub"
    assert _unescape(_value(event, "LOCATION")) == "A Test Hall, 1 Main St"
    lines = _unescape(_value(event, "DESCRIPTION")).split("\n")
    assert "Where: A Test Hall, 1 Main St" in lines
    assert "Call-in: Dial: 205-555-0100" in lines
    assert lines.index("Call-in: Dial: 205-555-0100") < lines.index(
        f"City schedule (PDF): {seed.PDF}"
    )
    assert _value(event, "URL") == seed.PDF
    assert _value(event, "CATEGORIES") == "Neighborhood association"
    assert not [
        line for line in event if line.startswith("DTEND")
    ]  # the schedule gives no end


def test_no_line_of_the_real_feed_is_over_75_bytes_and_every_line_ends_cr_lf(
    client, seeded
):
    body = _feed(client)

    assert "\n" not in body.replace("\r\n", "")
    for line in body.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75, line


# --- narrowing --------------------------------------------------------------


def test_each_kind_narrows_the_feed_to_the_pages_articles_of_that_kind(client, seeded):
    page = _page(client)
    whole = set(_events(_feed(client)))
    by_kind = {
        kind: set(_events(_feed(client, f"{FEED}?kind={kind}")))
        for kind in ("meeting", "hearing", "neighborhood")
    }

    for kind, uids in by_kind.items():
        assert uids == _uids_on_page(page, kind), kind
        assert uids  # the seeding gives every kind something
    assert by_kind["hearing"] == {seeded.zoning, seeded.weeds}
    assert by_kind["meeting"] == {seeded.council, seeded.off, seeded.untimed}
    assert (
        by_kind["meeting"] | by_kind["hearing"] | by_kind["neighborhood"]
        == whole
        == _uids_on_page(page)
    )
    assert sum(len(uids) for uids in by_kind.values()) == len(whole)


def test_an_association_narrows_the_feed_to_its_own_meetings(client, seeded):
    uids = set(_events(_feed(client, f"{FEED}?association=acipco-finley")))

    assert uids
    assert all(uid.startswith("na-acipco-finley-") for uid in uids)
    assert (
        "na-acipco-finley-20261202@docket.pub" in uids
    )  # the first Wednesday of December, worked by hand
    assert uids == {
        uid
        for uid in _uids_on_page(_page(client))
        if uid.startswith("na-acipco-finley-")
    }


def test_an_unknown_kind_and_an_unknown_association_are_404(client, seeded):
    assert client.get(f"{FEED}?kind=council").status_code == 404
    assert client.get(f"{FEED}?association=nowhere").status_code == 404
    # a known value of one does not excuse an unknown value of the other
    assert client.get(f"{FEED}?kind=meeting&association=nowhere").status_code == 404
    assert (
        client.get(f"{FEED}?kind=council&association=acipco-finley").status_code == 404
    )


def test_a_parameter_given_with_no_value_is_an_unknown_value(client):
    assert client.get(f"{FEED}?kind=").status_code == 404
    assert client.get(f"{FEED}?association=").status_code == 404


def test_a_kind_is_matched_as_written(client):
    assert client.get(f"{FEED}?kind=Hearing").status_code == 404
    assert client.get(f"{FEED}?kind=hearings").status_code == 404


def test_an_association_of_the_schedule_that_has_no_dates_has_no_feed(client):
    """Bridlewood is in the schedule and `association_feeds` leaves it out: it has no rule to compute dates from."""
    from docket.services import coming_up

    assert coming_up.association_slug("Bridlewood") == "bridlewood"
    assert client.get(f"{FEED}?association=bridlewood").status_code == 404


def test_a_kind_and_an_association_that_exclude_each_other_are_an_empty_calendar(
    client, seeded
):
    body = _feed(client, f"{FEED}?kind=meeting&association=acipco-finley")

    assert "BEGIN:VEVENT" not in body
    assert body.startswith("BEGIN:VCALENDAR\r\n")
    assert body.endswith("END:VCALENDAR\r\n")


def test_a_kind_with_nothing_in_the_window_is_an_empty_calendar_and_not_a_404(client):
    body = _feed(client, f"{FEED}?kind=hearing")  # nothing seeded

    assert "BEGIN:VEVENT" not in body
    assert body.endswith("END:VCALENDAR\r\n")


def test_an_unknown_parameter_changes_nothing(client, seeded):
    assert set(_events(_feed(client, f"{FEED}?today=2027-03-01&type=council"))) == set(
        _events(_feed(client))
    )


@pytest.mark.parametrize(
    ("query", "name"),
    [
        ("", "Birmingham coming up"),
        ("?kind=meeting", "Birmingham meetings"),
        ("?kind=hearing", "Birmingham public hearings"),
        ("?kind=neighborhood", "Birmingham neighborhood meetings"),
        ("?association=acipco-finley", "Acipco-Finley Neighborhood Association"),
        (
            "?kind=neighborhood&association=acipco-finley",
            "Acipco-Finley Neighborhood Association",
        ),
        (
            "?kind=meeting&association=acipco-finley",
            "Acipco-Finley Neighborhood Association",
        ),
    ],
)
def test_the_calendar_is_named_for_what_it_holds(client, query, name):
    assert _calendar_name(_feed(client, FEED + query)) == name


# --- the ways to subscribe, on the page -------------------------------------


def _subscribe(page):
    (block,) = page.select(".cu-subscribe")
    return block


def _link(block, words: str):
    (link,) = [a for a in block.select("a") if _text(a) == words]
    return link


def test_the_page_offers_the_webcal_address_the_google_link_and_the_file(client):
    response = client.get(PAGE)
    body = response.get_data(as_text=True)
    block = _subscribe(BeautifulSoup(body, "html.parser"))

    assert WEBCAL in body
    assert _link(block, "Subscribe in your calendar")["href"] == WEBCAL
    google = _link(block, "Add to Google Calendar")["href"]
    assert google.startswith(
        "https://calendar.google.com/calendar/render?cid=webcal%3A%2F%2Flocalhost%2Fal%2Fbirmingham%2Fcoming-up.ics"
    )
    assert google == "https://calendar.google.com/calendar/render?cid=" + quote(
        WEBCAL, safe=""
    )
    assert _link(block, "Calendar file (.ics)")["href"] == FEED
    assert [_text(a) for a in block.select("a")][:3] == [
        "Subscribe in your calendar",
        "Add to Google Calendar",
        "Calendar file (.ics)",
    ]


def test_the_one_subscribe_link_of_before_is_gone(client):
    assert [
        a for a in _page(client).select("a") if _text(a) == "Subscribe to this calendar"
    ] == []


def test_the_page_offers_each_kind_alone_as_a_webcal_address(client):
    block = _subscribe(_page(client))
    (only,) = [p for p in block.select("p") if _text(p).startswith("Only:")]

    assert [(_text(a), a["href"]) for a in only.select("a")] == [
        ("meetings", WEBCAL + "?kind=meeting"),
        ("public hearings", WEBCAL + "?kind=hearing"),
        ("neighborhood meetings", WEBCAL + "?kind=neighborhood"),
    ]


def test_the_page_offers_every_dated_association_its_own_feed_under_one_summary(client):
    from docket.services import coming_up

    feeds = coming_up.association_feeds("birmingham")
    body = client.get(PAGE).get_data(as_text=True)
    block = _subscribe(BeautifulSoup(body, "html.parser"))
    (details,) = block.select("details")

    assert (
        _text(details.select_one("summary"))
        == "One neighborhood association (2026 schedule)"
    )
    assert "One neighborhood association (2026 schedule)" in body
    assert body.count("?association=") == len(feeds) == 97
    assert [(_text(a), a["href"]) for a in details.select("a")] == [
        (name, f"{WEBCAL}?association={slug}") for name, slug in feeds
    ]
    assert ("Acipco-Finley", "acipco-finley") in feeds
    # an association with no dates is offered no feed
    assert "?association=bridlewood" not in body


def test_every_narrowed_address_the_page_offers_is_answered(client, seeded):
    """Each `webcal` link, asked for over the scheme the test client speaks, is a calendar."""
    block = _subscribe(_page(client))
    offered = [
        a["href"] for a in block.select("a") if a["href"].startswith(WEBCAL + "?")
    ]

    assert len(offered) == 3 + 97
    for address in offered[:3] + offered[3::16]:
        response = client.get(address.removeprefix("webcal://localhost"))
        assert response.status_code == 200, address
        assert response.headers["Content-Type"].startswith("text/calendar")


def test_the_year_in_the_summary_is_the_schedules(client, monkeypatch):
    from dataclasses import replace

    from docket.services import neighborhood_schedule

    real = neighborhood_schedule.get_schedule("birmingham")
    later = replace(real, year=2027)
    monkeypatch.setattr(
        neighborhood_schedule,
        "get_schedule",
        lambda slug: later if slug == "birmingham" else None,
    )
    (details,) = _subscribe(_page(client)).select("details")

    assert (
        _text(details.select_one("summary"))
        == "One neighborhood association (2027 schedule)"
    )


def test_a_flagged_city_with_no_schedule_is_offered_no_association_feed(
    client, monkeypatch
):
    from docket.services import neighborhood_schedule

    monkeypatch.setattr(neighborhood_schedule, "get_schedule", lambda slug: None)
    block = _subscribe(_page(client))

    assert block.select("details") == []
    assert "One neighborhood association" not in _text(block)
    assert _link(block, "Subscribe in your calendar")["href"] == WEBCAL
    assert len([a for a in block.select("a") if "?kind=" in a["href"]]) == 3


def test_the_webcal_address_names_the_host_the_reader_asked(client):
    response = client.get(PAGE, headers={"Host": "docket.example"})
    block = _subscribe(BeautifulSoup(response.get_data(as_text=True), "html.parser"))

    assert (
        _link(block, "Subscribe in your calendar")["href"]
        == "webcal://docket.example/al/birmingham/coming-up.ics"
    )
    assert _link(block, "Add to Google Calendar")["href"].endswith(
        quote("webcal://docket.example/al/birmingham/coming-up.ics", safe="")
    )


# --- the city page's "Follow:" line -----------------------------------------


def test_the_follow_line_of_a_flagged_city_links_the_calendar_and_anothers_does_not(
    render_partial,
):
    flagged = render_partial(
        "partials/briefing/meetings.html",
        municipality=seed.city_row("birmingham"),
        briefing_meetings=[],
    )
    plain = render_partial(
        "partials/briefing/meetings.html",
        municipality=seed.city_row("mobile"),
        briefing_meetings=[],
    )

    follow = BeautifulSoup(flagged, "html.parser").select_one("p.brf-follow")
    assert [(_text(a), a["href"]) for a in follow.select("a")] == [
        ("upcoming hearings (RSS)", "/al/birmingham/upcoming-hearings.rss"),
        ("calendar (.ics)", FEED),
        ("coverage", "/coverage.rss"),
    ]
    assert (
        _text(follow) == "Follow: upcoming hearings (RSS) · calendar (.ics) · coverage"
    )
    other = BeautifulSoup(plain, "html.parser").select_one("p.brf-follow")
    assert [_text(a) for a in other.select("a")] == [
        "upcoming hearings (RSS)",
        "coverage",
    ]
    assert "coming-up" not in plain


def test_the_birmingham_city_page_links_the_feed(client):
    briefing_seed.clear_caches()
    response = client.get("/al/birmingham/")
    briefing_seed.clear_caches()
    page = BeautifulSoup(response.get_data(as_text=True), "html.parser")

    (link,) = [a for a in page.select("a") if a.get("href") == FEED]
    assert _text(link) == "calendar (.ics)"
    assert link.find_parent("p")["class"] == ["brf-follow"]


# --- the route asks the service and nothing else ------------------------------


def test_the_absolute_helper_leaves_a_full_address_alone_and_prefixes_a_path(client):
    from docket.web import public

    with client.application.test_request_context("/al/birmingham/coming-up.ics"):
        assert (
            public._absolute_url("/al/birmingham/items/5/")
            == "http://localhost/al/birmingham/items/5/"
        )
        assert public._absolute_url(seed.AGENDA) == seed.AGENDA
        assert public._absolute_url("http://example.org/a") == "http://example.org/a"
    with client.application.test_request_context("/x", base_url="https://docket.pub"):
        assert (
            public._absolute_url("/al/birmingham/")
            == "https://docket.pub/al/birmingham/"
        )
