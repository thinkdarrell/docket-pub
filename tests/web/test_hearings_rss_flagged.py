"""``/al/<slug>/upcoming-hearings.rss`` for a city that has the coming-up page, and for one that has not.

For a city whose metadata carries ``"coming_up": true`` the feed lists the
hearing entries of the coming-up page: one ``<item>`` per stored hearing in
the window, titled by its kind and the hearing's date, linked to its article
on the page. Every other city keeps the older list, every upcoming agenda
line or meeting title containing the word "hearing". The last two route
tests tell the two paths apart from both sides.

Rows are seeded through ``tests/support/coming_up_seed.py`` and deleted
before and after every test. ``coming_up._today`` is 2026-11-16 in every
test; the older query reads the server's date, so a row meant for it is
dated from the real day. The route keeps its rendered text for an hour, so
each request here is made on an emptied cache unless the test is about the
cache. The template has no ``<pubDate>``: an entry does not carry the day
its hearing was first read.

Plan `birmingham-coming-up`, M8b.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, timedelta

import pytest
from bs4 import BeautifulSoup

from tests.support import coming_up_seed as seed

FEED = "/al/birmingham/upcoming-hearings.rss"
MOBILE_FEED = "/al/mobile/upcoming-hearings.rss"
PAGE = "/al/birmingham/coming-up/"
PAGE_URL = "http://localhost/al/birmingham/coming-up/"
ATOM_LINK = "{http://www.w3.org/2005/Atom}link"
OLD_TITLE = "COMINGUP_TEST_ Public Hearing on a plan"


@pytest.fixture(autouse=True)
def _a_fixed_day_and_no_leftover_rows(monkeypatch):
    from docket.services import coming_up

    seed.delete_seeded()
    monkeypatch.setattr(coming_up, "_today", lambda: seed.TODAY)
    yield
    seed.delete_seeded()


def _get(client, path: str = FEED):
    from docket.web import public

    public._rss_cache.clear()
    response = client.get(path)
    assert response.status_code == 200, path
    return response


def _channel(client, path: str = FEED) -> ET.Element:
    root = ET.fromstring(_get(client, path).get_data(as_text=True))
    assert root.tag == "rss"
    channel = root.find("channel")
    assert channel is not None
    return channel


def _items(client, path: str = FEED) -> list[ET.Element]:
    return _channel(client, path).findall("item")


def _titles(client, path: str = FEED) -> list[str]:
    return [item.findtext("title") or "" for item in _items(client, path)]


def _old_path_meeting(city: str) -> int:
    """A meeting 14 days from the real today whose title says "hearing", with no hearing stored."""
    return seed.upcoming_row(
        date.today() + timedelta(days=14), title=" Public Hearing on a plan", city=city
    )


def _render(entries, **context) -> ET.Element:
    """The template alone, on hand-built entries, as the route calls it."""
    from flask import render_template

    from docket.web import create_app

    app = create_app()
    with app.test_request_context("/al/birmingham/upcoming-hearings.rss"):
        from docket.web import public

        text = render_template(
            "rss/scheduled_hearings.xml.j2",
            entries=entries,
            municipality={"name": "Birmingham", "slug": "birmingham"},
            feed_url="http://localhost/al/birmingham/upcoming-hearings.rss",
            page_url=PAGE_URL,
            absolute=public._absolute_url,
            **context,
        )
    return ET.fromstring(text).find("channel")


def _entry(**changes):
    from dataclasses import replace

    from docket.services.coming_up import Entry

    made = Entry(
        kind="hearing",
        uid="hearing-7@docket.pub",
        on=date(2026, 12, 8),
        starts_at=None,
        ends_at=None,
        title="Zoning hearing",
        detail=("to consider a rezoning",),
        links=(
            ("City agenda", "https://example.gov/agenda?a=1&b=2"),
            ("On the agenda of October 13, 2026", "/al/birmingham/items/5/"),
        ),
        source_url="https://example.gov/agenda?a=1&b=2",
        place=None,
        badge="zoning",
        badge_label="Zoning",
        cancelled=False,
        cancelled_by=(),
        attend=(),
        association=None,
    )
    return replace(made, **changes)


# --- the flagged city's feed ------------------------------------------------


def test_a_stored_zoning_hearing_is_one_item_titled_by_kind_and_date(client):
    hearing_id, item_id = seed.hearing(seed.TITLES[63046])  # set for November 24, 2026

    items = _items(client)

    assert len(items) == 1
    item = items[0]
    assert item.findtext("title") == "Zoning hearing, November 24, 2026"
    link = item.findtext("link")
    assert link.endswith(f"/al/birmingham/coming-up/#hearing-{hearing_id}")
    assert link == f"{PAGE_URL}#hearing-{hearing_id}"
    description = item.findtext("description")
    assert description.count(seed.AGENDA) == 1
    assert f"City agenda: {seed.AGENDA}" in description.split("\n")
    assert f"http://localhost/al/birmingham/items/{item_id}/" in description
    assert "localhost/http" not in description


def test_the_feed_has_one_item_per_hearing_article_of_the_page(client):
    seed.upcoming_row(seed.NOV_17)  # a meeting: on the page, not in this feed
    seed.hearing(seed.TITLES[63046])
    seed.hearing(seed.TITLES[62882], seed.OCT_26)  # weed lots, set for November 17, 2026

    items = _items(client)
    page = BeautifulSoup(client.get(PAGE).get_data(as_text=True), "html.parser")
    articles = page.select('article[data-entry-kind="hearing"]')

    assert len(articles) == 2
    assert len(items) == len(articles)
    guids = {item.findtext("guid") for item in items}
    assert len(guids) == len(articles)
    assert guids == {f"{PAGE_URL}#{article['id']}" for article in articles}
    assert len(page.select("article[data-entry-kind]")) > len(articles)


def test_a_title_that_only_says_hearing_is_not_in_the_flagged_citys_feed(client):
    _old_path_meeting("birmingham")

    assert _items(client) == []
    assert OLD_TITLE not in _get(client).get_data(as_text=True)


def test_the_same_title_is_in_the_feed_of_a_city_without_the_flag(client):
    meeting_id = _old_path_meeting("mobile")

    items = [item for item in _items(client, MOBILE_FEED) if item.findtext("title") == OLD_TITLE]

    assert len(items) == 1
    assert items[0].findtext("guid").endswith(f"#hearing-meeting-{meeting_id}")
    assert items[0].find("pubDate") is not None


def test_a_stored_hearing_of_the_flagged_city_is_not_in_another_citys_feed(client):
    seed.hearing(seed.TITLES[63046])

    assert "Zoning hearing, November 24, 2026" in _titles(client)
    assert "Zoning hearing, November 24, 2026" not in _titles(client, MOBILE_FEED)


def test_the_items_are_in_the_order_of_their_hearings(client):
    seed.hearing(seed.TITLES[63046])
    seed.hearing(seed.TITLES[62882], seed.OCT_26)

    assert _titles(client) == [
        "Hearing on overgrown lots, November 17, 2026",
        "Zoning hearing, November 24, 2026",
    ]


def test_a_weed_lot_hearings_description_says_how_many_properties(client):
    seed.hearing(seed.TITLES[62882], seed.OCT_26)

    lines = _items(client)[0].findtext("description").split("\n")

    assert lines[0] == "212 properties listed in a resolution as having noxious or dangerous weeds"
    assert lines[1] == f"City agenda: {seed.AGENDA}"
    assert lines[2].startswith("On the agenda of October 26, 2026: http://localhost/al/birmingham/items/")
    assert len(lines) == 3


def test_the_envelope_is_the_older_feeds_with_its_own_description(client):
    seed.hearing(seed.TITLES[63046])

    channel = _channel(client)
    old = _channel(client, MOBILE_FEED)

    assert channel.findtext("title") == "Birmingham upcoming hearings — docket.pub"
    assert old.findtext("title") == "Mobile upcoming hearings — docket.pub"
    assert channel.findtext("link") == "http://localhost/al/birmingham/"
    assert channel.findtext("language") == old.findtext("language") == "en-us"
    assert channel.findtext("lastBuildDate")
    assert channel.findtext("description") == (
        "Public hearings the Birmingham council has scheduled, by the date of the hearing."
    )
    assert old.findtext("description") == "Upcoming public hearings on the Mobile agenda."
    self_link = channel.find(ATOM_LINK)
    assert self_link.get("href") == "http://localhost/al/birmingham/upcoming-hearings.rss"
    assert self_link.get("rel") == "self"
    assert self_link.get("type") == "application/rss+xml"
    assert [child.tag for child in channel][:6] == [
        "title", "link", "description", "language", "lastBuildDate", ATOM_LINK,
    ]  # fmt: skip


def test_an_item_has_no_date_of_publication_and_a_permanent_guid_that_is_its_link(client):
    seed.hearing(seed.TITLES[63046])

    item = _items(client)[0]

    assert [child.tag for child in item] == ["title", "link", "description", "guid"]
    assert item.find("guid").get("isPermaLink") == "true"
    assert item.findtext("guid") == item.findtext("link")


def test_the_flagged_feed_is_served_as_rss_with_the_hours_cache_header(client):
    response = _get(client)

    assert response.mimetype == "application/rss+xml"
    assert response.headers["Cache-Control"] == "public, max-age=3600"
    assert response.get_data(as_text=True).startswith('<?xml version="1.0" encoding="UTF-8"?>\n<rss ')


def test_a_flagged_city_with_no_hearing_in_the_window_has_a_feed_with_no_item(client):
    channel = _channel(client)

    assert channel.findall("item") == []
    assert channel.findtext("title") == "Birmingham upcoming hearings — docket.pub"


def test_the_flagged_feed_is_kept_for_the_hour_under_the_citys_key(client):
    from docket.web import public

    first = _get(client).get_data(as_text=True)
    assert "upcoming-hearings:birmingham" in public._rss_cache
    seed.hearing(seed.TITLES[63046])

    kept = client.get(FEED).get_data(as_text=True)
    assert kept == first
    assert "<item>" not in kept

    assert len(_items(client)) == 1  # `_items` empties the cache first


def test_a_city_that_loses_the_flag_returns_to_the_title_test(client, monkeypatch):
    from docket.services import coming_up

    seed.hearing(seed.TITLES[63046])
    _old_path_meeting("birmingham")
    monkeypatch.setattr(coming_up, "is_coming_up_city", lambda municipality: False)

    titles = _titles(client)

    assert OLD_TITLE in titles
    assert "Zoning hearing, November 24, 2026" not in titles


def test_the_route_asks_the_service_for_the_citys_entries_and_keeps_the_hearings(client, monkeypatch):
    from docket.services import coming_up

    asked = []

    def entries(municipality, **kwargs):
        asked.append((municipality["slug"], kwargs))
        return [
            _entry(),
            _entry(kind="meeting", uid="meeting-3@docket.pub", title="City Council meeting"),
            _entry(kind="neighborhood", uid="na-x-20261208@docket.pub", title="X Neighborhood Association"),
        ]

    monkeypatch.setattr(coming_up, "list_entries", entries)

    assert _titles(client) == ["Zoning hearing, December 8, 2026"]
    assert asked == [("birmingham", {})]


# --- the template, on hand-built entries ------------------------------------


def test_a_title_and_an_address_with_an_ampersand_are_well_formed_and_read_back_whole():
    channel = _render([_entry(title="Streets & alleys hearing", uid="hearing-9@docket.pub")])

    item = channel.find("item")
    assert item.findtext("title") == "Streets & alleys hearing, December 8, 2026"
    assert item.findtext("link") == f"{PAGE_URL}#hearing-9"
    assert "City agenda: https://example.gov/agenda?a=1&b=2" in item.findtext("description").split("\n")


def test_the_description_is_the_detail_lines_then_each_link_one_to_a_line():
    channel = _render([_entry(detail=("first line", "second line"))])

    assert channel.find("item").findtext("description").split("\n") == [
        "first line",
        "second line",
        "City agenda: https://example.gov/agenda?a=1&b=2",
        "On the agenda of October 13, 2026: http://localhost/al/birmingham/items/5/",
    ]


def test_an_entry_with_no_detail_has_a_description_of_its_links_alone():
    channel = _render([_entry(detail=())])

    assert channel.find("item").findtext("description").split("\n") == [
        "City agenda: https://example.gov/agenda?a=1&b=2",
        "On the agenda of October 13, 2026: http://localhost/al/birmingham/items/5/",
    ]


def test_a_subject_that_holds_the_end_of_a_cdata_section_does_not_end_the_description():
    channel = _render([_entry(detail=("lots [[1]]> and <b>others</b> & more",))])

    assert channel.find("item").findtext("description").split("\n")[0] == "lots [[1]]> and <b>others</b> & more"


def test_a_day_below_ten_is_written_without_a_leading_zero():
    channel = _render([_entry(on=date(2026, 12, 8)), _entry(on=date(2027, 1, 5), uid="hearing-8@docket.pub")])

    assert [item.findtext("title") for item in channel.findall("item")] == [
        "Zoning hearing, December 8, 2026",
        "Zoning hearing, January 5, 2027",
    ]


def test_the_guid_is_the_part_of_the_uid_before_its_at_sign():
    channel = _render([_entry(uid="hearing-41@docket.pub")])

    assert channel.find("item").findtext("guid") == f"{PAGE_URL}#hearing-41"
