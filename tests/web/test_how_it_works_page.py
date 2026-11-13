"""The "How it works" page: the path, each stop's cited rules, the open questions.

``/al/<slug>/how-it-works/`` renders the explainer that ``create_app`` loaded
from ``content/how-it-works/<slug>/explainer.yaml`` into
``app.config["HOW_IT_WORKS"]``. A city with no content directory, and a slug
that is no city, get 404. The shared footer partial ``page_sources.html``
links the page from every page that carries a municipality with an explainer.

Pattern: ``client`` from ``tests/web/conftest.py``; the page writes no
sentence from a database row, so the only rows these tests need are the
Birmingham and Mobile municipalities the migrations seed. Markup is read with
BeautifulSoup so an assertion is about structure, not about how Jinja escaped
an apostrophe.

Plan ``how-it-works-explainer``, M2.

M3 adds the journey: one real item laid onto the path, above the explanation.
Its facts are the journey file's; only its links come from the database, and
the throwaway database holds no Birmingham meetings, so the default page
shows the journey with no links but the file's own document. One test seeds
the meeting and item a journey cites, under the ids the file gives, to run
the link markup; two swap a journey built in the test into the application's
explainer to draw the states the parking-fines journey does not have.
"""

from __future__ import annotations

import dataclasses
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

PAGE = "/al/birmingham/how-it-works/"
MAIN_STOPS = [
    "Submitted",
    "Committee",
    "On the agenda",
    "First reading",
    "Final vote",
    "Mayor",
    "In effect",
]
SIDE_ROUTES = {"On the agenda": ["Consent", "Public hearing"], "First reading": ["Held over"]}
KNOWN_QUOTE = (
    "No action of any committee including the committee of the city council "
    "as a whole shall be considered final"
)


@pytest.fixture(scope="module")
def page(client):
    response = client.get(PAGE)
    assert response.status_code == 200
    return BeautifulSoup(response.get_data(as_text=True), "html.parser")


def _path(page):
    path = page.select_one("ol.hiw-path-list")
    assert path is not None, "the page has no ol.hiw-path-list"
    return path


def _explainer():
    from docket.services.how_it_works import load_explainer

    return load_explainer(Path("content/how-it-works/birmingham"))


def test_the_page_is_served_for_birmingham(client):
    assert client.get(PAGE).status_code == 200


def test_the_title_names_the_city(page):
    assert page.find("h1").get_text(" ", strip=True) == "How an item becomes a decision in Birmingham"


def test_the_hero_gives_the_date_the_sources_were_read(page):
    assert "November 12, 2026" in page.select_one("section.hero").get_text(" ", strip=True)


def test_the_path_is_an_ordered_list_of_exactly_seven_stops(page):
    stops = _path(page).find_all("li", recursive=False)
    assert len(stops) == 7


def test_the_path_names_the_seven_stops_in_order(page):
    names = [
        li.find("a", recursive=False).get_text(" ", strip=True)
        for li in _path(page).find_all("li", recursive=False)
    ]
    assert names == MAIN_STOPS


def test_the_side_routes_hang_in_nested_lists_under_the_stop_they_branch_from(page):
    found = {}
    for li in _path(page).find_all("li", recursive=False):
        nested = li.find("ul", recursive=False)
        if nested is not None:
            name = li.find("a", recursive=False).get_text(" ", strip=True)
            found[name] = [
                side.find("a", recursive=False).get_text(" ", strip=True)
                for side in nested.find_all("li", recursive=False)
            ]
    assert found == SIDE_ROUTES


def test_every_stop_on_the_path_links_to_a_section_that_exists(page):
    links = _path(page).find_all("a")
    assert len(links) == 10
    for link in links:
        href = link["href"]
        assert href.startswith("#stop-")
        section = page.find(id=href[1:])
        assert section is not None, f"{href} has no section"
        assert section.name == "section" and "feed" in section["class"]
        assert section.find("h2").get_text(" ", strip=True) == link.get_text(" ", strip=True)


def test_each_stop_section_carries_its_description_and_all_its_rules(page):
    explainer = _explainer()
    for stop in explainer.stops:
        section = page.find(id=f"stop-{stop.key}")
        text = " ".join(section.get_text(" ", strip=True).split())
        assert " ".join(stop.description.split()) in text
        rules = section.select(".hiw-rule")
        assert len(rules) == len(stop.rules)
        for drawn, rule in zip(rules, stop.rules):
            assert " ".join(drawn.select_one(".hiw-rule-statement").get_text(" ", strip=True).split()) == " ".join(
                rule.statement.split()
            )
            quote = drawn.find("blockquote")
            assert quote is not None
            assert " ".join(quote.get_text(" ", strip=True).split()) == " ".join(rule.quote.split())
            cite = drawn.select_one(".hiw-rule-cite a")
            assert cite["href"] == rule.url
            assert cite.get_text(" ", strip=True) == rule.citation


def test_a_known_quotation_and_its_citation_are_on_the_page(page):
    quotes = [" ".join(q.get_text(" ", strip=True).split()) for q in page.find_all("blockquote")]
    assert any(KNOWN_QUOTE in q for q in quotes)
    assert "§2-2-14(b)" in page.get_text()


def test_every_rule_citation_is_a_link_to_a_public_source(page):
    explainer = _explainer()
    rule_count = sum(len(stop.rules) for stop in explainer.stops)
    cites = page.select(".hiw-rule-cite a")
    assert len(cites) == rule_count
    assert all(a["href"].startswith("https://") for a in cites)


def test_the_open_questions_are_listed_under_their_heading(page):
    heading = page.find("h2", string=lambda s: s and s.strip() == "What we could not establish")
    assert heading is not None
    section = heading.find_parent("section")
    explainer = _explainer()
    drawn = [h.get_text(" ", strip=True) for h in section.find_all("h3")]
    assert drawn == [question for question, _ in explainer.open_questions]
    assert len(drawn) == 7
    text = " ".join(section.get_text(" ", strip=True).split())
    for _, body in explainer.open_questions:
        assert " ".join(body.split()) in text


def test_the_page_links_its_own_stylesheet(page):
    hrefs = [link.get("href", "") for link in page.find_all("link", rel="stylesheet")]
    assert any(href.endswith("/static/css/how_it_works.css") for href in hrefs)


def test_a_city_with_no_explainer_is_404(client):
    assert client.get("/al/mobile/how-it-works/").status_code == 404


def test_a_slug_that_is_not_a_city_is_404(client):
    assert client.get("/al/no-such-city/how-it-works/").status_code == 404


def test_a_directory_with_content_but_no_city_row_is_404(client):
    """An explainer alone does not make a page: the city must exist too."""
    explainers = client.application.config["HOW_IT_WORKS"]
    explainers["no-such-city"] = explainers["birmingham"]
    try:
        assert client.get("/al/no-such-city/how-it-works/").status_code == 404
    finally:
        del explainers["no-such-city"]


def _footer_links(client, address):
    response = client.get(address)
    assert response.status_code == 200
    soup = BeautifulSoup(response.get_data(as_text=True), "html.parser")
    nav = soup.select_one("nav.page-sources-links")
    assert nav is not None
    return {a.get_text(" ", strip=True): a["href"] for a in nav.find_all("a")}


def test_the_birmingham_city_page_links_to_the_page(client):
    links = _footer_links(client, "/al/birmingham/")
    assert links.get("How the council works") == PAGE
    assert "Source health" in links and "How we read minutes" in links


def test_a_city_page_without_an_explainer_has_no_link(client):
    links = _footer_links(client, "/al/mobile/")
    assert "How the council works" not in links
    assert "Source health" in links


def test_has_how_it_works_is_true_only_for_a_city_with_an_explainer(client):
    has = client.application.jinja_env.globals["has_how_it_works"]
    assert has("birmingham") is True
    assert has("mobile") is False
    assert has(None) is False


def _write_city(root: Path, slug: str, quote: str) -> None:
    city = root / slug
    (city / "sources").mkdir(parents=True)
    (city / "sources" / "code.txt").write_text("The council shall meet weekly.\n", encoding="utf-8")
    (city / "explainer.yaml").write_text(
        f"city: {slug}\n"
        "sources_read: 2026-11-12\n"
        "stops:\n"
        "  - key: submitted\n"
        "    name: Submitted\n"
        "    side_route_of: null\n"
        "    description: An item is submitted.\n"
        "    rules:\n"
        "      - statement: The council meets weekly.\n"
        f"        quote: {quote}\n"
        "        citation: Code 1\n"
        "        url: https://example.org/code\n"
        "        source_file: code.txt\n"
        "open_questions: []\n",
        encoding="utf-8",
    )


def test_every_city_directory_with_an_explainer_is_loaded(tmp_path):
    from docket.services.how_it_works import load_explainers

    _write_city(tmp_path, "alpha", "The council shall meet weekly.")
    _write_city(tmp_path, "beta", "shall meet weekly")
    (tmp_path / "no-explainer-here").mkdir()
    (tmp_path / "stray.txt").write_text("not a city\n", encoding="utf-8")
    loaded = load_explainers(tmp_path)
    assert sorted(loaded) == ["alpha", "beta"]
    assert loaded["alpha"].city == "alpha"


def test_a_content_root_that_does_not_exist_loads_nothing(tmp_path):
    from docket.services.how_it_works import load_explainers

    assert load_explainers(tmp_path / "absent") == {}


def test_a_broken_explainer_stops_the_application_from_starting(tmp_path, monkeypatch):
    import docket.web
    from docket.services.how_it_works import ExplainerError

    _write_city(tmp_path, "alpha", "The council shall meet monthly.")
    monkeypatch.setattr(docket.web, "HOW_IT_WORKS_ROOT", str(tmp_path), raising=False)
    with pytest.raises(ExplainerError, match=r"stops\[0\]\.rules\[0\]\.quote"):
        docket.web.create_app()


# --- the journey (plan how-it-works-explainer, M3) --------------------------

JOURNEY = "#how-it-works-journey"
REACHED = "in the record"
MISSING = "not in the record"
OFF_ROUTE = "not on this item's route"


def _text(node) -> str:
    return " ".join(node.get_text(" ", strip=True).split())


def _soup(client, address):
    response = client.get(address)
    assert response.status_code == 200, (address, response.status_code)
    return BeautifulSoup(response.get_data(as_text=True), "html.parser")


def _cards(page):
    return page.select(f"{JOURNEY} ol.hiw-timeline > li")


def _card(page, date_text: str, stop_name: str):
    for card in _cards(page):
        names = [a.get_text(" ", strip=True) for a in card.select(".hiw-event-stops a")]
        if stop_name in names and date_text in _text(card.select_one(".hiw-event-date")):
            return card
    raise AssertionError(f"no card for {stop_name} on {date_text}")


def _pills(card) -> dict[str, str]:
    return {_text(a): a["href"] for a in card.select(".hiw-links a")}


def _marks(page) -> dict[str, str]:
    """Each stop and side route on the path, by name, with the words of its mark."""
    marks = {}
    for li in _path(page).find_all("li"):
        mark = li.find("span", class_="hiw-path-mark", recursive=False)
        marks[li.find("a", recursive=False).get_text(" ", strip=True)] = _text(mark) if mark else ""
    return marks


def test_the_page_shows_the_parking_fines_journey_by_default(page):
    journey = page.select_one(JOURNEY)
    assert journey is not None
    text = _text(journey)
    assert "Parking fines ordinance" in text
    assert "Held over a week for lack of unanimous consent." in text
    assert "Section 8" in text
    assert "An Ordinance to amend Title 8, Chapter 3, Section 10" in text
    assert "Did Not Receive Unanimous Consent" in text


def test_the_journeys_title_is_drawn_as_a_quotation(page):
    quoted = page.select_one(f"{JOURNEY} blockquote.hiw-journey-title")
    assert quoted is not None
    assert _text(quoted).startswith("An Ordinance to amend Title 8, Chapter 3, Section 10")


def test_not_in_the_record_is_said_at_least_three_times(client):
    body = client.get(PAGE).get_data(as_text=True)
    assert body.count("not in the record") >= 3


def test_a_journey_named_in_the_address_is_shown(client):
    named = _soup(client, PAGE + "?journey=parking-fines")
    assert "Parking fines ordinance" in _text(named.select_one(JOURNEY))


def test_a_journey_that_does_not_exist_is_404(client):
    assert client.get(PAGE + "?journey=nope").status_code == 404
    assert client.get(PAGE + "?journey=").status_code == 404


def test_the_journey_comes_before_the_path_and_the_path_before_the_timeline(page):
    journey = page.select_one(JOURNEY)
    order = [
        node.name
        for node in journey.find_all(["header", "nav", "ol"])
        if node.name == "header" or "hiw-path" in node.get("class", []) or "hiw-timeline" in node.get("class", [])
    ]
    assert order == ["header", "nav", "ol"]
    assert _path(page).find_parent(id="how-it-works-journey") is not None
    hero = page.select_one("section.hero")
    assert hero.find_parent(id="how-it-works-journey") is None
    assert hero.find_next(id="how-it-works-journey") is journey
    assert journey.find_next("section", class_="hiw-stop") is not None
    assert page.find(id="stop-submitted").find_parent(id="how-it-works-journey") is None


def test_the_timeline_has_one_card_for_each_stop_of_the_journey_in_file_order(page):
    journey = _explainer().journeys[0]
    names = {stop.key: stop.name for stop in _explainer().stops}
    cards = _cards(page)
    assert len(cards) == len(journey.stops) == 8
    for card, stop in zip(cards, journey.stops):
        links = card.select(".hiw-event-stops a")
        assert [a["href"] for a in links] == [f"#stop-{key}" for key in stop.stops]
        assert [a.get_text(" ", strip=True) for a in links] == [names[key] for key in stop.stops]
        assert " ".join(stop.text.split()) in _text(card)
        quote = card.find("blockquote")
        if stop.quote:
            assert _text(quote) == " ".join(stop.quote.split())
        else:
            assert quote is None


def test_a_recorded_card_shows_its_date_and_a_gap_shows_not_in_the_record(page):
    cards = _cards(page)
    dates = [_text(card.select_one(".hiw-event-date")) for card in cards]
    assert dates == [
        MISSING,
        "May 11, 2026",
        "May 19, 2026",
        "May 26, 2026",
        "June 2, 2026",
        "June 2, 2026",
        MISSING,
        MISSING,
    ]
    assert cards[1].select_one("time")["datetime"] == "2026-05-11"
    assert cards[0].find("time") is None


def test_a_gap_is_drawn_as_a_gap_with_its_reason(page):
    cards = _cards(page)
    gaps = [card for card in cards if "hiw-event--gap" in card["class"]]
    assert [cards.index(card) for card in gaps] == [0, 6, 7]
    assert _text(gaps[0].select_one(".hiw-event-gap")) == "The submission date is not published."
    assert _text(gaps[1].select_one(".hiw-event-gap")) == "The site holds no record of a signature or a veto."
    assert _text(gaps[2].select_one(".hiw-event-gap")) == "The site holds no publication record."
    for card in cards:
        if card not in gaps:
            assert "hiw-event--recorded" in card["class"]
            assert card.select_one(".hiw-event-gap") is None


def test_only_the_stop_read_from_the_machine_transcript_carries_a_provenance_label(page):
    labels = {i: _text(label) for i, card in enumerate(_cards(page))
              for label in card.select(".hiw-event-provenance")}
    assert labels == {2: "from the machine transcript"}
    assert "from the video" not in _text(page.select_one(JOURNEY))


def test_the_first_reading_card_gives_both_tallies_and_the_declaration(page):
    card = _card(page, "May 26, 2026", "First reading")
    text = _text(card)
    assert "Three ayes: Gunn, Vasa, Woods." in text
    assert "Six nays: O'Quinn, Smith, Smitherman, Williams, Tate, Alexander." in text
    assert "declared the ordinance not adopted" in _text(card.find("blockquote"))


def test_without_the_citys_rows_a_stop_keeps_its_text_and_only_the_files_own_document(page):
    pills = [_pills(card) for card in _cards(page)]
    committee = pills[1]
    assert list(committee) == ["Committee minutes"]
    assert committee["Committee minutes"].startswith("https://s3.us-east-2.amazonaws.com/")
    assert all(not found for i, found in enumerate(pills) if i != 1)
    assert "Ordinance No. 26-61" in _text(_cards(page)[5])


def test_the_path_marks_each_stop_from_the_journey(page):
    assert _marks(page) == {
        "Submitted": MISSING,
        "Committee": REACHED,
        "On the agenda": REACHED,
        "Consent": "",
        "Public hearing": "",
        "First reading": REACHED,
        "Held over": REACHED,
        "Final vote": REACHED,
        "Mayor": MISSING,
        "In effect": MISSING,
    }


def test_each_mark_has_its_own_class_on_the_stop(page):
    state = {}
    for li in _path(page).find_all("li"):
        name = li.find("a", recursive=False).get_text(" ", strip=True)
        state[name] = sorted(c.rsplit("--", 1)[1] for c in li["class"] if "--" in c)
    assert state == {
        "Submitted": ["missing"],
        "Committee": ["reached"],
        "On the agenda": ["reached"],
        "Consent": ["untouched"],
        "Public hearing": ["untouched"],
        "First reading": ["reached"],
        "Held over": ["reached"],
        "Final vote": ["reached"],
        "Mayor": ["missing"],
        "In effect": ["missing"],
    }


def test_every_stop_section_links_back_to_the_journey(page):
    sections = page.select("section.hiw-stop")
    assert len(sections) == 10
    for section in sections:
        back = [a for a in section.find_all("a") if _text(a) == "Back to the journey"]
        assert len(back) == 1
        assert back[0]["href"] == JOURNEY
    assert page.select_one(JOURNEY).name == "div"


def test_no_stop_is_drawn_as_the_current_one(page):
    journey = page.select_one(JOURNEY)
    assert journey.find(attrs={"aria-current": True}) is None
    words = _text(journey).lower()
    assert "current" not in words and " now " not in f" {words} "


# --- the link markup, on the rows a journey cites ---------------------------

MEETING_ID = 2238
ITEM_ID = 59026
SEED_PREFIX = "hiwpage-"
SEED_PLAYER = "https://bhamal.granicus.com/MediaPlayer.php?view_id=2&clip_id=2238"
SEED_AGENDA = "https://example.org/hiwpage/agenda-2026-06-02.pdf"
SEED_MINUTES = "https://example.org/hiwpage/minutes-2026-06-02.pdf"


@pytest.fixture
def cited_rows():
    """Meeting 2238 and item 59026 under Birmingham, as the parking-fines file cites them.

    The ids are explicit because the page reads them from the journey file; if
    the throwaway database already holds either, the insert fails loudly.
    """
    from docket.db import db
    from tests.support import briefing_seed

    def cleanup(cur):
        cur.execute("DELETE FROM meetings WHERE external_id LIKE %s", (SEED_PREFIX + "%",))

    with db() as conn, conn.cursor() as cur:
        cleanup(cur)
        cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham'")
        city_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO meetings (id, municipality_id, external_id, title, meeting_date, meeting_type,
                                     video_url, agenda_url, minutes_url)
               VALUES (%s, %s, %s, 'Regular City Council Meeting', %s, 'council', %s, %s, %s)""",
            (MEETING_ID, city_id, SEED_PREFIX + "2238", date(2026, 6, 2), SEED_PLAYER, SEED_AGENDA, SEED_MINUTES),
        )
        cur.execute(
            """INSERT INTO agenda_items (id, meeting_id, external_id, item_number, title, processing_status)
               VALUES (%s, %s, '371088', '11', 'An Ordinance to amend Title 8, Chapter 3, Section 10', 'completed')""",
            (ITEM_ID, MEETING_ID),
        )
        conn.commit()
    briefing_seed.clear_caches()
    try:
        yield
    finally:
        with db() as conn, conn.cursor() as cur:
            cleanup(cur)
            conn.commit()
        briefing_seed.clear_caches()


def test_a_stop_whose_rows_exist_links_them_in_a_fixed_order(client, cited_rows):
    seeded = _soup(client, PAGE + "?journey=parking-fines")
    card = _card(seeded, "June 2, 2026", "Final vote")
    pills = _pills(card)

    assert list(pills) == ["Meeting", "Item", "Recording on Granicus, at this moment", "Minutes", "Agenda"]
    assert pills["Meeting"] == f"/al/birmingham/meetings/{MEETING_ID}/"
    assert pills["Item"] == f"/al/birmingham/items/{ITEM_ID}/"
    assert "meta_id=371088" in pills["Recording on Granicus, at this moment"]
    assert pills["Minutes"] == SEED_MINUTES
    assert pills["Agenda"] == SEED_AGENDA
    assert client.get(pills["Meeting"]).status_code == 200
    assert client.get(pills["Item"]).status_code == 200

    # The stops on other meetings, which the database does not hold, are unchanged.
    assert not _pills(_card(seeded, "May 26, 2026", "First reading"))
    assert list(_pills(_card(seeded, "May 11, 2026", "Committee"))) == ["Committee minutes"]


# --- states the parking-fines journey does not have -------------------------


@contextmanager
def _journeys(client, *journeys):
    """Swap the journeys of Birmingham's explainer for the length of one test."""
    explainers = client.application.config["HOW_IT_WORKS"]
    real = explainers["birmingham"]
    explainers["birmingham"] = dataclasses.replace(real, journeys=tuple(journeys))
    try:
        yield
    finally:
        explainers["birmingham"] = real


def _journey(key: str, *stops):
    from docket.services.how_it_works import Journey

    return Journey(key=key, label=f"Journey {key}", note="A note.", title="A title.", stops=tuple(stops))


def _journey_stop(*keys: str, record: str, text: str, **fields):
    from docket.services.how_it_works import JourneyStop

    values = dict(
        stops=keys, date=None, record=record, text=text, quote=None, source_file=None, meeting_id=None,
        item_id=None, seconds=None, document_label=None, document_url=None, gap=None,
    )
    values.update(fields)
    return JourneyStop(**values)


def _licence():
    return _journey(
        "licence",
        _journey_stop("submitted", record="none", text="The agenda names a submitter.", gap="No date is given."),
        _journey_stop("committee", record="committee_minutes", text="Forwarded by the chair.",
                      date=date(2026, 9, 22), meeting_id=2_000_000_001),
        _journey_stop("first_reading", record="not_on_route", text="This resolution had no first reading.",
                      gap="The agenda does not mark this resolution as a first reading."),
        _journey_stop("agenda", "hearing", "final_vote", record="video", text="Passed 8 to 0.",
                      date=date(2026, 9, 29), meeting_id=2_000_000_002),
        _journey_stop("mayor", "in_effect", record="none", text="Nothing further.", gap="The site holds no record."),
    )


def test_a_stop_not_on_the_items_route_is_a_slim_line_with_its_reason(client):
    with _journeys(client, _licence()):
        drawn = _soup(client, PAGE)
    card = _cards(drawn)[2]

    assert "hiw-event--off-route" in card["class"]
    assert _text(card.select_one(".hiw-event-date")) == OFF_ROUTE
    assert _text(card.select_one(".hiw-event-gap")) == "The agenda does not mark this resolution as a first reading."
    assert "This resolution had no first reading." in _text(card)
    assert [a["href"] for a in card.select(".hiw-event-stops a")] == ["#stop-first_reading"]
    assert card.select_one(".hiw-event-provenance") is None


def test_a_stop_read_from_the_video_says_so(client):
    with _journeys(client, _licence()):
        drawn = _soup(client, PAGE)
    labels = {i: _text(label) for i, card in enumerate(_cards(drawn))
              for label in card.select(".hiw-event-provenance")}

    assert labels == {3: "from the video"}
    assert [a.get_text(" ", strip=True) for a in _cards(drawn)[3].select(".hiw-event-stops a")] == [
        "On the agenda", "Public hearing", "Final vote"]


def test_the_path_marks_all_three_states_and_a_side_route_the_journey_took(client):
    with _journeys(client, _licence()):
        drawn = _soup(client, PAGE)

    assert _marks(drawn) == {
        "Submitted": MISSING,
        "Committee": REACHED,
        "On the agenda": REACHED,
        "Consent": "",
        "Public hearing": REACHED,
        "First reading": OFF_ROUTE,
        "Held over": "",
        "Final vote": REACHED,
        "Mayor": MISSING,
        "In effect": MISSING,
    }
    off_route = [li for li in _path(drawn).find_all("li", recursive=False) if "hiw-path-stop--off-route" in li["class"]]
    assert [li.find("a", recursive=False).get_text(" ", strip=True) for li in off_route] == ["First reading"]


def test_the_first_journey_is_the_default_and_each_is_reached_by_its_key(client):
    with _journeys(client, _licence(), _journey("other", _journey_stop(
            "submitted", "committee", "agenda", "first_reading", "final_vote", "mayor", "in_effect",
            record="none", text="Nothing at all.", gap="No record."))):
        default = _soup(client, PAGE)
        other = _soup(client, PAGE + "?journey=other")
        assert client.get(PAGE + "?journey=parking-fines").status_code == 404

    assert "Journey licence" in _text(default.select_one(JOURNEY))
    assert "Journey other" in _text(other.select_one(JOURNEY))
    assert "Journey licence" not in _text(other.select_one(JOURNEY))
    assert len(_cards(other)) == 1
    assert set(_marks(other).values()) == {MISSING, ""}


def test_a_city_with_no_journeys_still_shows_the_path_and_the_rules(client):
    with _journeys(client):
        bare = _soup(client, PAGE)
        assert client.get(PAGE + "?journey=parking-fines").status_code == 404

    assert len(_path(bare).find_all("li", recursive=False)) == 7
    assert not _cards(bare)
    assert set(_marks(bare).values()) == {""}
    assert bare.select_one("blockquote.hiw-journey-title") is None
    assert not [a for a in bare.find_all("a") if _text(a) == "Back to the journey"]
    assert len(bare.select("section.hiw-stop")) == 10
