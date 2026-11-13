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
"""

from __future__ import annotations

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
            found[name] = [side.get_text(" ", strip=True) for side in nested.find_all("li", recursive=False)]
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
