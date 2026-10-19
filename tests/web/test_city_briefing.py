"""The Birmingham briefing page, section by section, against the seeded city.

Every test renders ``/al/birmingham/`` through the Flask test client after
``tests/support/briefing_seed.py`` has inserted the rows for the state under
test (full, partial, or empty) and clears the overview cache before and
after, since the city page is cached per slug for five minutes. Runs in the
web tier against the throwaway database (``DATABASE_URL`` names
``docket_test_*``).

M2 covers the opener, the search field, and the meetings list; M3 the money
door, the disagreement door, and the ``order=amount`` search page; later
milestones add their doors here.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

import pytest

from docket.db import db
from docket.services import briefing
from docket.web import create_app
from tests.support import briefing_seed


@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config["TESTING"] = True
    briefing_seed.clear_caches()
    with app.test_client() as c:
        yield c
    briefing_seed.clear_caches()


@pytest.fixture
def seeded(request):
    """Seed Birmingham with the options in ``request.param`` (default: full state)."""
    options = getattr(request, "param", {})
    with db() as conn:
        ids = briefing_seed.seed(conn, **options)
    briefing_seed.clear_caches()
    try:
        yield ids
    finally:
        with db() as conn:
            briefing_seed.cleanup(conn)
        briefing_seed.clear_caches()


@pytest.fixture
def facts(seeded):
    """The seeded rows plus Birmingham's precomputed facts, as the worker task leaves them."""
    briefing.recompute_city_facts(seeded["municipality_id"])
    briefing_seed.clear_caches()
    return seeded


@pytest.fixture
def unseeded():
    """No Birmingham rows at all (the empty state)."""
    with db() as conn:
        briefing_seed.cleanup(conn)
    briefing_seed.clear_caches()
    yield
    briefing_seed.clear_caches()


def _page(client, slug="birmingham") -> str:
    resp = client.get(f"/al/{slug}/")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def _opener(html: str) -> str:
    start = html.index('<section class="brf-opener"')
    return html[start: html.index("</section>", start)]


class _Beats(HTMLParser):
    """Collects the opener's two ``<p>`` beats as lists of (kind, text, href)."""

    def __init__(self):
        super().__init__()
        self.beats: list[list[tuple[str, str, str | None]]] = []
        self._in_p = False
        self._href = None
        self._buf = ""

    def handle_starttag(self, tag, attrs):
        if tag == "p":
            self._in_p = True
            self.beats.append([])
        elif tag == "a" and self._in_p:
            self._flush()
            self._href = dict(attrs).get("href")

    def handle_endtag(self, tag):
        if tag == "a" and self._in_p:
            self._flush()
            self._href = None
        elif tag == "p":
            self._flush()
            self._in_p = False

    def handle_data(self, data):
        if self._in_p:
            self._buf += data

    def _flush(self):
        if self._buf:
            self.beats[-1].append(("link" if self._href else "text", self._buf, self._href))
        self._buf = ""


def _beats(html: str):
    parser = _Beats()
    parser.feed(_opener(html))
    return parser.beats


def _beat_text(beat) -> str:
    return "".join(t for _, t, _ in beat)


# --- the opener ------------------------------------------------------------


def test_opener_full_state_sentences_and_links(client, seeded):
    html = _page(client)
    op = _opener(html)
    assert "acted on 4 items" in op
    assert "$10.1 million" in op
    assert f'href="/al/birmingham/items/{seeded["items"]["A"]}/"' in op
    assert "with <a" in op and "Hunter Williams</a> voting no" in op
    assert f'href="/al/birmingham/council/{seeded["nay_member_id"]}/"' in op
    assert "Read the" in op
    # The KultureCity item's stored $39.5 million fails the dollar check and
    # must not be quoted anywhere in the opener.
    assert "39.5" not in op
    meta = re.search(r'<meta name="description" content="([^"]*)"', html)
    assert meta, "meta description missing"
    assert "acted on 4 items" in meta.group(1)
    assert "$10.1 million" in meta.group(1)
    assert "→" not in meta.group(1)
    assert len(meta.group(1)) <= 300


def test_opener_empty_state_sentence(client, unseeded):
    html = _page(client)
    assert "has not indexed a Birmingham meeting yet" in _opener(html)
    assert "acted on" not in _opener(html)


@pytest.mark.parametrize("seeded", [{"upcoming": False}], indirect=True)
def test_opener_partial_no_upcoming(client, seeded):
    op = _opener(_page(client))
    assert "No agenda is posted yet for the next meeting" in op
    assert "See the agenda" not in op
    assert "acted on 4 items" in op


@pytest.mark.parametrize("seeded", [{"dollars": False}], indirect=True)
def test_opener_drops_dollar_clause_when_no_item_passes(client, seeded):
    op = _opener(_page(client))
    assert "The largest was" not in op
    assert "acted on" in op


@pytest.mark.parametrize("seeded", [{"votes": "unanimous"}], indirect=True)
def test_opener_unanimous_and_video_label(client, seeded):
    op = _opener(_page(client))
    assert "Every vote was unanimous." in op
    assert "vote split" not in op
    # The seed's chosen source is the minutes, so no "from the video" label;
    # the review-flagged video vote with three nays is excluded.
    assert "from the video" not in op
    assert f'href="/al/birmingham/meetings/{seeded["past_meeting_id"]}/"' in op


def test_opener_each_beat_has_at_most_three_links_none_adjacent(client, seeded):
    beats = _beats(_page(client))
    assert len(beats) == 2
    for beat in beats:
        links = [(t, h) for k, t, h in beat if k == "link"]
        assert 1 <= len(links) <= 3, beat
        hrefs = [h for _, h in links]
        assert len(hrefs) == len(set(hrefs)), f"two links share an href: {hrefs}"
        for i in range(1, len(beat)):
            prev, cur = beat[i - 1], beat[i]
            if prev[0] == "link" and cur[0] == "link":
                pytest.fail(f"adjacent links: {prev[1]!r} and {cur[1]!r}")
            if prev[0] == "link" and cur[0] == "text" and i + 1 < len(beat) and beat[i + 1][0] == "link":
                assert cur[1].strip(), f"only whitespace between {prev[1]!r} and {beat[i + 1][1]!r}"


@pytest.mark.parametrize("seeded", [{"votes": "many_splits"}], indirect=True)
def test_opener_many_splits_sentence_is_plain_and_action_link_anchors(client, seeded):
    beats = _beats(_page(client))
    first = beats[0]
    text = _beat_text(first)
    assert "Three votes split." in text
    plain = [t for k, t, _ in first if k == "text"]
    assert any("Three votes split." in t for t in plain), "the many-splits sentence must be plain text"
    action = [h for k, t, h in first if k == "link" and t.startswith("Read the")]
    assert action == [
        f"/al/birmingham/meetings/{seeded['past_meeting_id']}/#vote-{seeded['votes']['split']}"
    ]


@pytest.mark.parametrize(
    "seeded", [{}, {"votes": "many_splits"}, {"votes": "unanimous"}, {"upcoming": False}], indirect=True
)
def test_opener_sentences_at_most_25_words(client, seeded):
    for beat in _beats(_page(client)):
        text = _beat_text(beat).replace("→", "").strip()
        for sentence in re.split(r"(?<=[.;])\s+", text):
            words = sentence.split()
            assert len(words) <= 25, f"{len(words)} words: {sentence!r}"


# --- the meetings list -----------------------------------------------------


def test_meetings_list_rows_and_ghost_excluded(client, seeded):
    html = _page(client)
    section = html[html.index("brf-meetings-section"):]
    rows = section.count('<li class="brf-meeting">')
    assert 1 <= rows <= 6
    assert "Regular City Council Meeting" not in section, "the ghost meeting must not be listed"
    assert f'href="/al/birmingham/meetings/{seeded["past_meeting_id"]}/"' in section
    assert f'href="/al/birmingham/meetings/{seeded["upcoming_meeting_id"]}/"' in section
    assert "upcoming" in section
    assert "4 items" in section
    assert "1 split vote" in section
    assert "agenda · minutes · video" in section
    assert "All meetings →" in section
    assert "upcoming hearings (RSS)" in section
    assert "/al/birmingham/upcoming-hearings.rss" in section
    assert "/al/birmingham/blog/feed.xml" in section
    assert "/coverage.rss" in section


def test_meetings_list_empty_state_for_city_without_meetings(client):
    briefing_seed.clear_caches()
    html = _page(client, "homewood")
    section = html[html.index("brf-meetings-section"):]
    assert '<li class="brf-meeting">' not in section
    assert "has not indexed a Homewood meeting yet" in section
    assert "All meetings →" in section


# --- the search field ------------------------------------------------------


def test_search_field_scoped_to_city(client, unseeded):
    html = _page(client)
    assert 'class="brf-search"' in html
    assert '<input type="hidden" name="city" value="birmingham">' in html
    assert "Search Birmingham's agendas, minutes, and transcripts" in html
    assert 'action="/search"' in html


# --- the money door --------------------------------------------------------


def _section(html: str, cls: str) -> str | None:
    """The ``<section class="... cls ...">`` element's markup, or None when absent."""
    marker = f'<section class="brf-door {cls}"'
    if marker not in html:
        return None
    start = html.index(marker)
    return html[start: html.index("</section>", start)]


MORE_MONEY_ITEMS = [
    {"item_number": "5", "title": briefing_seed.PREFIX + "Sidewalk repair contract",
     "description": "Contract for sidewalk repair in the amount of $2,300,000.",
     "headline": "$2.3 million sidewalk repair contract", "dollars_amount": 2_300_000,
     "is_consent": True, "topic": "public_works"},
    {"item_number": "6", "title": briefing_seed.PREFIX + "Library roof replacement",
     "description": "Roof replacement at the central library for $850,000.",
     "headline": "$850,000 library roof replacement", "dollars_amount": 850_000,
     "is_consent": False, "topic": "contracts"},
]


def _add_money_items(seeded) -> list[int]:
    """Two more items on the past meeting whose text backs their amount (cleaned with the meeting)."""
    ids = []
    with db() as conn:
        with briefing_seed._cur(conn) as cur:
            for spec in MORE_MONEY_ITEMS:
                ids.append(briefing_seed._insert_item(cur, seeded["past_meeting_id"], spec))
        conn.commit()
    briefing_seed.clear_caches()
    return ids


def test_money_door_full_three_lines_in_amount_order(client, seeded):
    sidewalk, roof = _add_money_items(seeded)
    door = _section(_page(client), "brf-door-money")
    assert door is not None
    assert "Where the money went" in door
    assert door.count('<li class="brf-door-line">') == 3
    a = door.index(f'href="/al/birmingham/items/{seeded["items"]["A"]}/"')
    b = door.index(f'href="/al/birmingham/items/{sidewalk}/"')
    c = door.index(f'href="/al/birmingham/items/{roof}/"')
    assert a < b < c, "lines must be in descending amount order"
    assert "$10.1 million" in door and "$2.3 million" in door and "$850,000" in door
    assert "passed on the consent agenda" in door
    assert 'href="/search?city=birmingham&amp;order=amount"' in door
    assert "More →" in door


def test_money_door_skips_item_failing_dollar_check(client, seeded):
    door = _section(_page(client), "brf-door-money")
    assert door is not None
    assert f'href="/al/birmingham/items/{seeded["items"]["A"]}/"' in door
    assert f'href="/al/birmingham/items/{seeded["items"]["B"]}/"' not in door
    assert "39.5" not in door and "KultureCity" not in door


def test_money_door_partial_fewer_than_three(client, seeded):
    door = _section(_page(client), "brf-door-money")
    assert door is not None
    assert door.count('<li class="brf-door-line">') == 1
    assert "$10.1 million" in door
    # The amount is printed once, not repeated from the headline.
    assert door.count("$10.1 million") == 1


@pytest.mark.parametrize("seeded", [{"dollars": False}], indirect=True)
def test_money_door_absent_without_items(client, seeded):
    html = _page(client)
    assert _section(html, "brf-door-money") is None
    assert "Where the money went" not in html


# --- the disagreement door -------------------------------------------------


def test_disagreed_full_lists_split_with_dissenter_links(client, facts):
    door = _section(_page(client), "brf-door-disagreed")
    assert door is not None
    assert "Where they disagreed" in door
    assert door.count('<li class="brf-door-line">') == 1
    assert f'href="/al/birmingham/items/{facts["items"]["A"]}/"' in door
    assert "passed 8 to 1" in door
    assert f'<a href="/al/birmingham/council/{facts["nay_member_id"]}/">Hunter Williams</a>' in door
    assert "from the video" not in door
    assert 'href="/al/birmingham/split_vote/"' in door
    assert "More →" in door


@pytest.mark.parametrize("seeded", [{"votes": "unanimous", "old_split": True}], indirect=True)
def test_disagreed_unanimity_sentence_with_last_split(client, facts):
    door = _section(_page(client), "brf-door-disagreed")
    assert door is not None
    assert "Every recorded vote since" in door
    assert "was unanimous." in door
    assert "The last split was" in door
    assert f'href="/al/birmingham/items/{facts["items"]["E"]}/"' in door
    assert "7 to 2" in door
    assert '<li class="brf-door-line">' not in door
    assert "More →" not in door


@pytest.mark.parametrize("seeded", [{"votes": "none"}], indirect=True)
def test_disagreed_absent_without_votes(client, facts):
    html = _page(client)
    assert _section(html, "brf-door-disagreed") is None
    assert "Where they disagreed" not in html


def test_disagreed_absent_without_facts_row(client, seeded):
    html = _page(client)
    assert _section(html, "brf-door-disagreed") is None
    assert "Where they disagreed" not in html


# --- the order=amount search page ------------------------------------------


def test_search_order_amount_lists_city_items(client, seeded):
    resp = client.get("/search?city=birmingham&order=amount")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Where the money went in Birmingham, last 90 days" in html
    assert f'id="item-{seeded["items"]["A"]}"' in html
    assert "Type a query above to search" not in html


def test_search_order_amount_skips_item_failing_dollar_check(client, seeded):
    sidewalk, roof = _add_money_items(seeded)
    html = client.get("/search?city=birmingham&order=amount").get_data(as_text=True)
    assert f'id="item-{seeded["items"]["B"]}"' not in html
    a = html.index(f'id="item-{seeded["items"]["A"]}"')
    assert a < html.index(f'id="item-{sidewalk}"') < html.index(f'id="item-{roof}"')
