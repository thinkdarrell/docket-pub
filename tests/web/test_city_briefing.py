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
from datetime import datetime
from html.parser import HTMLParser

import pytest
from markupsafe import escape

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
    assert "<span>upcoming</span>" in section
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
    for key in ("$10.1M", "$2.3M", "$850,000"):
        assert f'<span class="brf-key t-mono">{key}</span>' in door
    assert "$10.1 million" not in door
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
    assert '<span class="brf-key t-mono">$10.1M</span>' in door
    assert "$10.1 million" not in door
    # The amount is printed once, not repeated from the headline.
    assert door.count("$10.1M") == 1


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
    assert '<span class="brf-key t-mono">8–1</span>' in door
    assert "passed 8 to 1" not in door
    assert f'against: <a href="/al/birmingham/council/{facts["nay_member_id"]}/">Hunter Williams</a>' in door
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


# --- the council door (M4) ---------------------------------------------------


def _council(html: str) -> str | None:
    marker = '<section class="council brf-council"'
    if marker not in html:
        return None
    start = html.index(marker)
    return html[start: html.index("</section>", start)]


def test_council_door_nine_cards_in_district_order_with_numbers(client, facts):
    html = _page(client)
    section = _council(html)
    assert section is not None
    assert "The council" in section
    assert section.count('class="cc-district-num') == 9
    numbers = re.findall(r'cc-district-num t-display">District (\d)<', section)
    assert numbers == [str(n) for n in range(1, 10)], "cards must be in district order"
    assert "members</div>" not in section, "the old member-count header must be gone"
    # Two chosen-source roll calls on the past meeting (the review-flagged
    # video vote is excluded): Hunter Williams voted no once; Clinton P.
    # Woods was absent once.
    assert section.count("Attended 2 of 2 roll calls</div>") == 8
    assert "Attended 1 of 2 roll calls</div>" in section
    assert section.count("Against the outcome 1 time<") == 1
    assert section.count("Against the outcome 0 times") == 8
    # The window is stated once under the grid, not on every card
    # (plan city-page-less-narrow-less-dense, M3).
    assert section.count("Roll calls counted over the last 12 months.") == 1
    assert "in the last 12 months</div>" not in section
    assert "photo · placeholder" not in section
    assert section.count("View record →") == 9


def test_council_door_numbers_omitted_without_facts_row(client, seeded):
    section = _council(_page(client))
    assert section is not None
    assert section.count('class="cc-district-num') == 9
    assert "roll calls" not in section
    assert "cc-stats" not in section
    assert "Against the outcome" not in section
    assert "Roll calls counted" not in section


def test_council_card_links_dissent_since_and_member_page_matches_count(client, facts):
    section = _council(_page(client))
    assert section is not None
    since = (briefing.get_city_facts(facts["municipality_id"])["member_counts"]["payload"]["since"])
    href = f'/al/birmingham/council/{facts["nay_member_id"]}/?filter=dissent&amp;since={since}'
    assert f'<a class="cc-dissent" href="{href}">Against the outcome 1 time</a>' in section
    # A zero is not a door: the other eight members' second line has no link.
    assert section.count('class="cc-dissent"') == 1
    # The roster page shares the card without the numbers, carries no window
    # note, and is not the city page's section (its phone list is scoped to
    # brf-council, plan city-page-less-narrow-less-dense, M3).
    resp = client.get("/al/birmingham/council/")
    assert resp.status_code == 200
    roster = resp.get_data(as_text=True)
    assert "Roll calls counted" not in roster
    assert "brf-council" not in roster

    resp = client.get(href.replace("&amp;", "&"))
    assert resp.status_code == 200
    page = resp.get_data(as_text=True)
    assert page.count('class="member-history-row vote-row"') == 1
    assert f"#vote-{facts['votes']['split']}" in page
    assert "Showing votes since" in page and "one source per meeting" in page

    # A member who dissented only on the review-flagged video vote: the dated
    # view counts none, as the card said.
    names = list(facts["members"])
    other = facts["members"][names[3]]
    resp = client.get(f"/al/birmingham/council/{other}/?filter=dissent&since={since}")
    assert resp.status_code == 200
    assert 'class="member-history-row vote-row"' not in resp.get_data(as_text=True)
    # Without ``since`` the history lists every row, the flagged video vote
    # included, so the Dissent predicate finds that no on a motion that passed.
    resp = client.get(f"/al/birmingham/council/{other}/?filter=dissent")
    assert resp.status_code == 200
    assert resp.get_data(as_text=True).count('class="member-history-row vote-row"') == 1


def test_council_door_absent_without_roster(client):
    # Every seeded city has a roster (migration 005), so the state is made
    # by marking Homewood's members inactive for the test's duration.
    with db() as conn:
        with briefing_seed._cur(conn) as cur:
            cur.execute(
                """UPDATE council_members SET active = FALSE
                    WHERE active = TRUE AND municipality_id = (SELECT id FROM municipalities WHERE slug = 'homewood')
                RETURNING id"""
            )
            ids = [r["id"] for r in cur.fetchall()]
        conn.commit()
    briefing_seed.clear_caches()
    try:
        html = _page(client, "homewood")
    finally:
        with db() as conn:
            with briefing_seed._cur(conn) as cur:
                cur.execute("UPDATE council_members SET active = TRUE WHERE id = ANY(%s)", (ids,))
            conn.commit()
        briefing_seed.clear_caches()
    assert _council(html) is None
    assert "The council" not in html
    assert "cc-district-num" not in html


# --- the topics door (M4) ----------------------------------------------------


def test_topics_door_priorities_and_busiest_excluding_routine(client, seeded):
    door = _section(_page(client), "brf-door-topics")
    assert door is not None
    assert "What they keep dealing with" in door
    assert "Tracked in Birmingham · since " in door
    assert "Busiest topics · since " in door
    # Item A carries blight_accountability (confidence 0.9, significance 5);
    # the row is its count as the key figure and its linked name, with no
    # example headline (plan city-page-less-narrow-less-dense, M2).
    assert 'href="/al/birmingham/blight_accountability/"' in door
    assert "Blight Accountability" in door
    assert '<span class="brf-key t-mono">1 item</span>' in door
    assert "/al/birmingham/items/" not in door
    # The other three priorities have no qualifying item ever, so no line.
    for slug in ("housing_stability", "property_recovery", "public_safety_tech_privacy"):
        assert f"/al/birmingham/{slug}/" not in door
    assert "last item" not in door
    # The busiest topics: the past meeting's three non-routine topics and the
    # upcoming agenda's two, each with its newest item; routine is excluded.
    for slug, name in (("public_works", "Public Works"), ("contracts", "Contracts &amp; Procurement"),
                       ("grants", "Grants &amp; Federal Funding"), ("budget", "Budget &amp; Finance"),
                       ("zoning", "Zoning &amp; Land Use")):
        assert f'href="/topics/{slug}/?city=birmingham"' in door, slug
        assert name in door
    assert "/topics/routine/" not in door
    assert "Routine" not in door
    assert door.count('<li class="brf-door-line">') == 6


@pytest.mark.parametrize("seeded", [{"old_split": True}], indirect=True)
def test_topics_door_quiet_priority_shows_last_item(client, seeded):
    # housing_stability's only item is E, on the meeting 200 days back:
    # nothing in the window, so the line says when it last came up.
    with db() as conn:
        with briefing_seed._cur(conn) as cur:
            briefing_seed._insert_badge(
                cur, seeded["items"]["E"], seeded["municipality_id"],
                "housing_stability", "policy", "llm", 0.9,
            )
        conn.commit()
    briefing_seed.clear_caches()
    door = _section(_page(client), "brf-door-topics")
    assert door is not None
    old = seeded["old_meeting_date"]
    at = door.index('href="/al/birmingham/housing_stability/"')
    line = door[door.rindex('<li class="brf-door-line">', 0, at):]
    line = line[: line.index("</li>")]
    assert "Housing Stability" in line
    assert f"last item {old.strftime('%B')} {old.day}, {old.year}" in line
    assert "/items/" not in line
    assert "since" not in line
    assert '<span class="brf-key t-mono">0 items</span>' in line
    # The window's priority is unchanged beside it.
    assert '<span class="brf-key t-mono">1 item</span>' in door


def test_topics_door_absent_without_items(client):
    briefing_seed.clear_caches()
    html = _page(client, "homewood")
    assert _section(html, "brf-door-topics") is None
    assert "What they keep dealing with" not in html


# ---------------------------------------------------------------------------
# M5: the signals list, the source panel, the footer, and the skip link
# ---------------------------------------------------------------------------


def _aside(html: str) -> str:
    start = html.index('<aside class="page-sources"')
    return html[start: html.index("</aside>", start)]


def _colophon(html: str) -> str:
    start = html.index("footnote-colophon")
    return html[start: html.index("footnote-bottom", start)]


def test_signals_only_nonzero_in_plain_words(client, seeded):
    # The seed badges item C ``hidden_on_consent`` on a meeting seven days
    # back; no other process badge exists, so the list is that one line.
    html = _page(client)
    section = _section(html, "brf-signals")
    assert section is not None
    assert "Signals in the last 30 days" in section
    lines = re.findall(
        r'<li class="brf-door-line">\s*<span class="brf-key t-mono">([^<]+)</span>'
        r'\s*<a class="brf-row-link" href="([^"]+)">([^<]+)</a>',
        section,
    )
    assert lines == [("1 item", "/al/birmingham/hidden_on_consent/",
                      "Passed without discussion, on the consent agenda")]
    assert "Legal settlements" not in section
    assert "hidden_on_consent —" not in section  # the slug never shows; the label does


@pytest.mark.parametrize("seeded", [{"badges": False}], indirect=True)
def test_signals_absent_when_all_zero(client, seeded):
    html = _page(client)
    assert _section(html, "brf-signals") is None
    assert "Signals in the last 30 days" not in html


def test_bands_hold_the_doors_in_order(client, facts):
    """The page wraps money with disagreed in one band and topics with
    signals over the quote in a second (plan city-page-less-narrow-less-dense,
    M2), the council between them and the meetings list after; the order of
    the sections is money, disagreed, council, topics, signals, said, meetings.
    """
    html = _page(client)
    band1 = html.index('<div class="brf-band">')
    money = html.index("brf-door-money", band1)
    disagreed = html.index("brf-door-disagreed", money)
    council = html.index('class="council brf-council"', disagreed)
    band2 = html.index('<div class="brf-band">', council)
    topics = html.index("brf-door-topics", band2)
    col = html.index('<div class="brf-band-col">', topics)
    signals = html.index("brf-signals", col)
    said = html.index("brf-door-said", signals)
    meetings = html.index("brf-meetings-section", said)
    assert band1 < money < disagreed < council < band2 < topics < col < signals < said < meetings
    assert html.count('<div class="brf-band">') == 2


def test_page_sources_names_host_count_and_date(client, seeded):
    # Three non-hidden seeded meetings (past, upcoming, ghost), created now,
    # the newest dated one (upcoming) carrying no source_url and the past
    # meeting the Granicus one.
    html = _page(client)
    aside = _aside(html)
    assert "Where these records come from" in aside
    assert ('The records on this page come from <a class="page-sources-host" '
            'href="https://birminghamal.granicus.com/ViewPublisher.php?view_id=1" '
            'rel="external noopener">birminghamal.granicus.com</a>.') in aside
    assert "docket.pub has indexed 3 Birmingham meetings" in aside
    today = datetime.now().strftime("%B %-d, %Y")
    assert f"; the last was added {today}." in aside
    assert 'href="/al/birmingham/source-health/"' in aside or "source-health" in aside or "source_health" in aside
    assert ">Source health</a>" in aside
    assert ">How we read minutes</a>" in aside


def test_page_sources_has_no_adapter_or_schema_rows_and_no_h2(client, unseeded):
    html = _page(client)
    aside = _aside(html)
    assert "<h2" not in aside
    for word in ("adapter_class", "GranicusAdapter", "Adapter", "Platform", "Schema",
                 "SOURCE OF TRUTH", "tsvector", "src/docket"):
        assert word not in aside, word
    # Without an ingest the date clause is dropped, never defaulted.
    assert "docket.pub has indexed 0 Birmingham meetings." in aside
    assert "the last was added" not in aside


def test_footer_updated_equals_chip_date(client, seeded):
    html = _page(client)
    chip = re.search(r"synced ([A-Z][a-z]{2} \d{2})", html)
    assert chip, "freshness chip shows no synced date"
    updated = re.search(r"Updated</span><div>([A-Z][a-z]{2} \d{2}), \d{4}</div>", _colophon(html))
    assert updated, "footer grid shows no Updated date"
    assert chip.group(1) == updated.group(1)
    colophon = _colophon(html)
    assert "Schema</span>" not in colophon
    assert "Source</span><div>birminghamal.granicus.com · public domain</div>" in colophon


def test_footer_grid_absent_without_municipality(client):
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "footnote-grid" not in html
    assert "Updated</span>" not in html
    assert 'class="page-sources"' not in html


def test_base_has_skip_link_to_main(client, unseeded):
    html = _page(client)
    body = html[html.index("<body>") + len("<body>"):]
    assert body.lstrip().startswith('<a class="skip-link" href="#main">Skip to main content</a>')
    assert html.count('id="main"') == 1
    assert '<main class="app-main" id="main">' in html


# --- the transcript door (M6) -----------------------------------------------


def test_said_full_with_resolved_speaker(client, seeded):
    # The seed's transcript tags three segments to item A ($10.1 million,
    # passes the dollar check); item B is larger but fails it. The first
    # segment's cluster is resolved to Hunter Williams at confidence 0.9.
    html = _page(client)
    section = _section(html, "brf-door-said")
    assert section is not None
    assert "Said at the meeting" in section
    quote = re.search(r'<blockquote class="brf-quote"><p>([^<]+)</p></blockquote>', section)
    assert quote, section
    assert quote.group(1).startswith("I want to be clear that I cannot support this contract")
    assert "The department has answered" not in section  # the first turn only
    assert (f'<a href="/al/birmingham/council/{seeded["nay_member_id"]}/">Hunter Williams</a>'
            ", during discussion of") in section
    assert (f'<a href="/al/birmingham/items/{seeded["items"]["A"]}/">'
            "$10.1 million contract for citywide road resurfacing</a>") in section
    date_text = seeded["past_meeting_date"].strftime("%B ") + str(seeded["past_meeting_date"].day)
    assert f"at the {date_text} meeting." in section
    assert (f'<a href="/al/birmingham/meetings/{seeded["past_meeting_id"]}/transcript/#t-1">'
            "Read the transcript →</a>") in section
    assert "SPEAKER_0" not in section and "Speaker 1" not in section


@pytest.mark.parametrize("seeded", [{"resolved_speaker": False}], indirect=True)
def test_said_unnamed_when_cluster_unresolved(client, seeded):
    html = _page(client)
    section = _section(html, "brf-door-said")
    assert section is not None
    assert "I want to be clear that I cannot support this contract" in section
    assert "During discussion of" in section
    assert "Hunter Williams" not in section
    assert "/council/" not in section
    # Neither fallback label the transcript service produces reaches the page.
    assert "Speaker 1" not in section and "SPEAKER_01" not in section and "Unknown speaker" not in section
    assert f'/meetings/{seeded["past_meeting_id"]}/transcript/#t-1' in section


@pytest.mark.parametrize("seeded", [{"transcript": False}], indirect=True)
def test_said_absent_without_transcript(client, seeded):
    html = _page(client)
    assert _section(html, "brf-door-said") is None
    assert "Said at the meeting" not in html


# --- M7: the money window's upper bound and the against-the-outcome count ---


UPCOMING_MONEY_ITEM = {
    "item_number": "3", "title": briefing_seed.PREFIX + "Sidewalk repair program",
    "description": "Sidewalk repair program in the amount of $3,000,000.",
    "headline": "$3 million sidewalk repair program", "dollars_amount": 3_000_000,
    "is_consent": True, "topic": "public_works",
}


def _add_upcoming_money_item(seeded) -> int:
    """A consent item with an amount on the seeded upcoming meeting (cleaned with the meeting)."""
    with db() as conn:
        with briefing_seed._cur(conn) as cur:
            item_id = briefing_seed._insert_item(cur, seeded["upcoming_meeting_id"], UPCOMING_MONEY_ITEM)
        conn.commit()
    briefing_seed.clear_caches()
    return item_id


def _meeting_row(html: str, meeting_id: int) -> str:
    """The ``<li class="brf-meeting">`` whose date links to ``meeting_id``."""
    section = html[html.index("brf-meetings-section"):]
    rows = section.split('<li class="brf-meeting">')[1:]
    href = f'href="/al/birmingham/meetings/{meeting_id}/"'
    matches = [r[: r.index("</li>")] for r in rows if href in r]
    assert len(matches) == 1, f"expected one row for meeting {meeting_id}, found {len(matches)}"
    return matches[0]


def test_money_door_excludes_upcoming_meeting_items(client, seeded):
    new = _add_upcoming_money_item(seeded)
    html = _page(client)
    door = _section(html, "brf-door-money")
    assert door is not None
    assert door.count('<li class="brf-door-line">') == 1
    assert f'href="/al/birmingham/items/{seeded["items"]["A"]}/"' in door
    assert f'href="/al/birmingham/items/{new}/"' not in door
    assert "$3 million" not in door
    assert "passed on the consent agenda" not in door, "no outcome before the meeting"
    row = _meeting_row(html, seeded["upcoming_meeting_id"])
    assert "<span>upcoming</span>" in row
    assert "3 items" in row


def test_search_order_amount_excludes_upcoming_meeting_items(client, seeded):
    new = _add_upcoming_money_item(seeded)
    html = client.get("/search?city=birmingham&order=amount").get_data(as_text=True)
    assert f'id="item-{new}"' not in html
    assert f'id="item-{seeded["items"]["A"]}"' in html


def _add_tabled_and_abstention_votes(seeded) -> str:
    """Two more minutes votes on the past meeting: a 9 to 0 motion the council
    tabled (every member yea) and an 8 to 0 that passed with one abstention;
    returns the abstainer's name (a member whose other votes are aligned yeas)."""
    roster = seeded["members"]
    names = list(roster)
    # Not the seed's dissenter or absentee, and not one of the three members
    # (names[2:5]) who vote no on its review-flagged video vote, which the
    # undated Dissent view still counts: the abstainer's other votes must all
    # be aligned yeas.
    abstainer = next(n for i, n in enumerate(names)
                     if n not in (briefing_seed.MEMBER_NAY, briefing_seed.MEMBER_ABSENT) and not 2 <= i < 5)
    with db() as conn:
        with briefing_seed._cur(conn) as cur:
            briefing_seed._insert_vote(cur, seeded["past_meeting_id"], result="tabled", yeas=9, nays=0,
                                       roster=roster)
            briefing_seed._insert_vote(cur, seeded["past_meeting_id"], result="passed", yeas=8, nays=0,
                                       abstentions=1, roster=roster, positions={abstainer: "abstain"})
        conn.commit()
    return abstainer


def _card(section: str, name: str) -> str:
    cards = [c for c in section.split('<article class="cc">')[1:] if f">{name}</a>" in c]
    assert len(cards) == 1, f"expected one card for {name}, found {len(cards)}"
    return cards[0]


def _dissent_rows(client, member_id: int, since: str | None) -> int:
    url = f"/al/birmingham/council/{member_id}/?filter=dissent"
    if since:
        url += f"&since={since}"
    resp = client.get(url)
    assert resp.status_code == 200
    return resp.get_data(as_text=True).count('class="member-history-row vote-row"')


def test_council_card_count_matches_dated_dissent_view_with_abstention_and_tabled(client, facts):
    abstainer = _add_tabled_and_abstention_votes(facts)
    briefing.recompute_city_facts(facts["municipality_id"])
    briefing_seed.clear_caches()
    section = _council(_page(client))
    assert section is not None
    assert section.count("Against the outcome 1 time<") == 1
    assert section.count("Against the outcome 0 times") == 8
    assert "Attended 4 of 4 roll calls</div>" in _card(section, abstainer)
    assert section.count('class="cc-dissent"') == 1
    since = briefing.get_city_facts(facts["municipality_id"])["member_counts"]["payload"]["since"]
    # The card's one against-the-outcome vote is the one row of the dated Dissent view.
    assert _dissent_rows(client, facts["nay_member_id"], since) == 1
    # The abstainer's dated view counts none, as the card said ...
    abstainer_id = facts["members"][abstainer]
    assert _dissent_rows(client, abstainer_id, since) == 0
    # ... and the undated view, under the same predicate, counts none (decision 0066).
    assert _dissent_rows(client, abstainer_id, None) == 0


# --- M8: the interaction-table states the tests never rendered ------------


@pytest.mark.parametrize("seeded", [{"past_days": 20}], indirect=True)
def test_opener_stale_last_met_phrasing(client, seeded):
    html = _page(client)
    op = _opener(html)
    assert "The council last met on" in op
    assert "The council met on" not in op
    meta = re.search(r'<meta name="description" content="([^"]*)"', html)
    assert meta, "meta description missing"
    assert "last met on" in meta.group(1)
    # The meeting is still listed; only the opener's wording changes.
    assert _meeting_row(html, seeded["past_meeting_id"])


@pytest.mark.parametrize("seeded", [{"votes": "tally_only"}], indirect=True)
def test_disagreed_partial_tally_only_no_names(client, facts):
    html = _page(client)
    door = _section(html, "brf-door-disagreed")
    assert door is not None
    assert door.count('<li class="brf-door-line">') == 1
    assert f'href="/al/birmingham/items/{facts["items"]["A"]}/"' in door
    assert '<span class="brf-key t-mono">8–1</span>' in door
    assert "passed 8 to 1" not in door
    assert "/council/" not in door
    assert "abstained" not in door
    assert 'class="brf-row-rest"' not in door
    # The opener's split sentence ends at the tally, and the beat's action
    # link carries the vote's anchor.
    first = _beats(html)[0]
    text = _beat_text(first)
    assert "passed 8 to 1. Read the" in text
    assert "with " not in text[text.index("passed 8 to 1."):]
    action = [h for k, t, h in first if k == "link" and t.startswith("Read the")]
    assert action == [
        f"/al/birmingham/meetings/{facts['past_meeting_id']}/#vote-{facts['votes']['split']}"
    ]


@pytest.mark.parametrize("seeded", [{"votes": "video"}], indirect=True)
def test_disagreed_video_sourced_vote_carries_label(client, facts):
    html = _page(client)
    door = _section(html, "brf-door-disagreed")
    assert door is not None
    assert door.count('<li class="brf-door-line">') == 1
    assert '· from the video</span>' in door
    assert f'<a href="/al/birmingham/council/{facts["nay_member_id"]}/">Hunter Williams</a>' in door
    assert "voting no from the video." in _opener(html)
    assert "1 split vote" in _meeting_row(html, facts["past_meeting_id"])


def test_disagreed_failed_tone_and_abstainer_clause(client, facts):
    """A failed vote's key carries the bad tone and the word; an abstainer gets
    its own clause after the nays; a passed vote with abstentions prints a
    three-part tally and no word."""
    names = list(facts["members"])
    with db() as conn:
        with briefing_seed._cur(conn) as cur:
            briefing_seed._insert_vote(
                cur, facts["past_meeting_id"], result="failed", yeas=1, nays=6,
                item_ids=[facts["items"]["B"]], roster=facts["members"],
                positions={**{n: "nay" for n in names[1:7]}, **{n: "absent" for n in names[7:9]}},
            )
            briefing_seed._insert_vote(
                cur, facts["past_meeting_id"], result="passed", yeas=8, nays=0, abstentions=1,
                roster=facts["members"], positions={names[7]: "abstain"},
            )
        conn.commit()
    briefing.recompute_city_facts(facts["municipality_id"])
    briefing_seed.clear_caches()
    door = _section(_page(client), "brf-door-disagreed")
    assert door is not None
    assert door.count('<li class="brf-door-line">') == 3
    assert '<span class="brf-key t-mono brf-key--bad">1–6 failed</span>' in door
    assert '<span class="brf-key t-mono">8–0–1</span>' in door
    assert f'<a href="/al/birmingham/council/{facts["members"][names[7]]}/">{escape(names[7])}</a> abstained' in door
    assert "failed 1 to 6" not in door
    assert "(abstained)" not in door


@pytest.mark.parametrize("seeded", [{"transcript": "low_speech"}], indirect=True)
def test_said_absent_when_transcript_low_speech(client, seeded):
    html = _page(client)
    assert _section(html, "brf-door-said") is None
    assert "Said at the meeting" not in html
    assert "acted on 4 items" in _opener(html)


@pytest.mark.parametrize("seeded", [{"undocumented": True}], indirect=True)
def test_meetings_list_row_without_documents_says_so(client, seeded):
    html = _page(client)
    row = _meeting_row(html, seeded["undocumented_meeting_id"])
    assert "no documents linked" in row
    assert "1 item" in row
    assert "agenda · minutes · video" in _meeting_row(html, seeded["past_meeting_id"])
    section = html[html.index("brf-meetings-section"):]
    assert "Regular City Council Meeting" not in section, "the ghost meeting must not be listed"


def test_council_card_without_roll_calls_shows_name_alone(client, facts):
    names = list(facts["members"])
    quiet = names[4]
    with db() as conn:
        with briefing_seed._cur(conn) as cur:
            cur.execute(
                """DELETE FROM member_votes
                    WHERE council_member_id = %s
                      AND vote_id IN (SELECT v.id FROM votes v JOIN meetings m ON m.id = v.meeting_id
                                       WHERE position(%s IN m.title) = 1)""",
                (facts["members"][quiet], briefing_seed.PREFIX),
            )
        conn.commit()
    briefing.recompute_city_facts(facts["municipality_id"])
    briefing_seed.clear_caches()
    section = _council(_page(client))
    assert section is not None
    # The fifth seeded name holds an apostrophe, which the page escapes.
    card = _card(section, str(escape(quiet)))
    assert "cc-stats" not in card
    assert "roll calls" not in card
    assert section.count("roll calls</div>") == 8


# --- M9: cancelled meetings, withdrawn items, the tabled verb, and the empty window ---


@pytest.mark.parametrize("seeded", [{"cancelled": True}], indirect=True)
def test_cancelled_meeting_is_not_the_last_meeting(client, seeded):
    html = _page(client)
    opener = _opener(html)
    assert "acted on 4 items" in opener
    # The action link carries the split vote's anchor, so the href is matched
    # without its closing quote.
    assert f'href="/al/birmingham/meetings/{seeded["past_meeting_id"]}/' in opener
    assert f'href="/al/birmingham/meetings/{seeded["cancelled_meeting_id"]}/' not in opener
    assert "$12 million" not in opener
    door = _section(html, "brf-door-money")
    assert door is not None
    assert door.count('<li class="brf-door-line">') == 1
    assert f'href="/al/birmingham/items/{seeded["items"]["A"]}/"' in door
    assert f'href="/al/birmingham/items/{seeded["items"]["cancelled"]}/"' not in door
    assert "$12 million" not in door
    row = _meeting_row(html, seeded["cancelled_meeting_id"])
    assert "<span>cancelled</span>" in row
    assert "agenda · video" in row
    assert "1 item" not in row
    assert "$12 million" not in row
    assert "split vote" not in row
    search = client.get("/search?city=birmingham&order=amount").get_data(as_text=True)
    assert f'id="item-{seeded["items"]["cancelled"]}"' not in search
    assert f'id="item-{seeded["items"]["A"]}"' in search


@pytest.mark.parametrize("seeded", [{"cancelled": "upcoming"}], indirect=True)
def test_cancelled_upcoming_meeting_is_not_the_next_meeting(client, seeded):
    html = _page(client)
    opener = _opener(html)
    assert f'href="/al/birmingham/meetings/{seeded["upcoming_meeting_id"]}/"' in opener
    assert "with 2 items on the agenda" in opener
    assert f'href="/al/birmingham/meetings/{seeded["cancelled_meeting_id"]}/"' not in opener
    row = _meeting_row(html, seeded["cancelled_meeting_id"])
    assert "<span>cancelled</span>" in row
    assert "upcoming" not in row


@pytest.mark.parametrize("seeded", [{"votes": "unanimous"}], indirect=True)
def test_withdrawn_item_is_never_the_largest(client, seeded):
    with db() as conn:
        with briefing_seed._cur(conn) as cur:
            cur.execute("UPDATE agenda_items SET processing_status = 'withdrawn' WHERE id = %s",
                        (seeded["items"]["A"],))
        conn.commit()
    briefing_seed.clear_caches()
    html = _page(client)
    opener = _opener(html)
    assert "acted on 4 items" in opener
    assert "The largest was" not in opener
    assert _section(html, "brf-door-money") is None, "no other seeded item passes the dollar check"
    search = client.get("/search?city=birmingham&order=amount").get_data(as_text=True)
    assert f'id="item-{seeded["items"]["A"]}"' not in search


@pytest.mark.parametrize("seeded", [{"votes": "none"}], indirect=True)
def test_tabled_split_is_written_tabled(client, facts):
    names = list(facts["members"])
    with db() as conn:
        with briefing_seed._cur(conn) as cur:
            briefing_seed._insert_vote(
                cur, facts["past_meeting_id"], result="tabled", yeas=5, nays=4,
                item_ids=[facts["items"]["B"]], roster=facts["members"],
                positions={n: "nay" for n in names[:4]},
            )
        conn.commit()
    briefing.recompute_city_facts(facts["municipality_id"])
    briefing_seed.clear_caches()
    html = _page(client)
    # The dissenter phrase is a link, so the sentence is read as the beat's text.
    first_beat = _beat_text(_beats(html)[0])
    assert "tabled 5 to 4, with four members voting no." in first_beat
    assert "failed" not in _opener(html)
    door = _section(html, "brf-door-disagreed")
    assert door is not None
    assert '<span class="brf-key t-mono">5–4 tabled</span>' in door
    assert "brf-key--bad" not in door
    assert "failed" not in door


@pytest.mark.parametrize("seeded", [{"votes": "none", "old_split": True}], indirect=True)
def test_disagreement_door_absent_with_no_vote_in_window(client, facts):
    html = _page(client)
    assert _section(html, "brf-door-disagreed") is None
    assert "was unanimous" not in html
    assert "acted on 4 items" in _opener(html)


# --- M10: the topics partial state, the consent label, and the row's video label ---


@pytest.mark.parametrize("seeded", [{"upcoming": False}], indirect=True)
def test_topics_door_partial_fewer_than_five_topics(client, seeded):
    # Without the upcoming agenda only the past meeting's items count: A, B,
    # and C carry public_works, contracts, and grants; D is routine and
    # excluded. One priority line (item A's badge) plus three topic lines.
    door = _section(_page(client), "brf-door-topics")
    assert door is not None
    for slug in ("public_works", "contracts", "grants"):
        assert f'href="/topics/{slug}/?city=birmingham"' in door, slug
    assert "/topics/budget/" not in door
    assert "/topics/zoning/" not in door
    assert door.count('<li class="brf-door-line">') == 4


@pytest.mark.parametrize("seeded", [{"votes": "many_splits"}], indirect=True)
def test_many_item_split_is_a_consent_vote_only_when_every_item_is_consent(client, facts):
    # The two-item split covers C (consent) and D (not), so it is a plain vote.
    door = _section(_page(client), "brf-door-disagreed")
    assert door is not None
    assert "a vote covering 2 items" in door
    assert "consent-agenda vote" not in door
    # Once every linked item is on the consent agenda, the label says so.
    with db() as conn:
        with briefing_seed._cur(conn) as cur:
            cur.execute("UPDATE agenda_items SET is_consent = TRUE WHERE id = %s",
                        (facts["items"]["D"],))
        conn.commit()
    briefing.recompute_city_facts(facts["municipality_id"])
    briefing_seed.clear_caches()
    door = _section(_page(client), "brf-door-disagreed")
    assert door is not None
    assert "a consent-agenda vote covering 2 items" in door


@pytest.mark.parametrize("seeded", [{"votes": "video"}], indirect=True)
def test_meetings_row_video_sourced_split_count_carries_label(client, facts):
    row = _meeting_row(_page(client), facts["past_meeting_id"])
    assert "1 split vote</span> · <span>from the video</span>" in row
    # The default seed's chosen source is the minutes: the count stands alone.
    with db() as conn:
        briefing_seed.cleanup(conn)
        default = briefing_seed.seed(conn)
    briefing.recompute_city_facts(default["municipality_id"])
    briefing_seed.clear_caches()
    row = _meeting_row(_page(client), default["past_meeting_id"])
    assert "1 split vote" in row
    assert "from the video" not in row
