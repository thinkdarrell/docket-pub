"""The Birmingham briefing page, section by section, against the seeded city.

Every test renders ``/al/birmingham/`` through the Flask test client after
``tests/support/briefing_seed.py`` has inserted the rows for the state under
test (full, partial, or empty) and clears the overview cache before and
after, since the city page is cached per slug for five minutes. Runs in the
web tier against the throwaway database (``DATABASE_URL`` names
``docket_test_*``).

M2 covers the opener, the search field, and the meetings list; later
milestones add their doors here.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

import pytest

from docket.db import db
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
