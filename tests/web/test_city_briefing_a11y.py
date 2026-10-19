"""The Birmingham briefing page against the design's writing and accessibility rules.

One test per rule, each rendering ``/al/birmingham/`` through the Flask test
client against the full seed (``tests/support/briefing_seed.py`` plus the
precomputed facts row, so every section renders), in the web tier against
the throwaway database. The rules are the design's (one h1, unique headings
that say what is under them, plain words, no emoji, every link with text, a
meta description, sentences of at most 25 words); each section's own states
are tested in ``tests/web/test_city_briefing.py``.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

import pytest

from docket.db import db
from docket.services import briefing
from docket.web import create_app
from tests.support import briefing_seed

# The eight headings the design names, in page order: the six doors and the
# meetings list (design sections 3 to 9) and the blog rail (section 10).
DESIGN_HEADINGS = [
    "Where the money went",
    "Where they disagreed",
    "The council",
    "What they keep dealing with",
    "Said at the meeting",
    "Signals in the last 30 days",
    "Recent meetings",
    "From the blog",
]

# Words the design's review found on the old page that a resident would not
# know; none may appear anywhere on the rendered page.
FORBIDDEN_WORDS = ("YTD", "OCR", "tsvector", "CMS", "Provenance", "inferred")

# Emoji and pictographs (the old badge icons); arrows, middle dots, and
# dashes are punctuation, not emoji, and are allowed.
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️]")


@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config["TESTING"] = True
    briefing_seed.clear_caches()
    with app.test_client() as c:
        yield c
    briefing_seed.clear_caches()


@pytest.fixture(scope="module")
def page(client) -> str:
    """The page in its full state: the seed plus the precomputed facts row."""
    with db() as conn:
        ids = briefing_seed.seed(conn)
    briefing.recompute_city_facts(ids["municipality_id"])
    briefing_seed.clear_caches()
    try:
        resp = client.get("/al/birmingham/")
        assert resp.status_code == 200
        yield resp.get_data(as_text=True)
    finally:
        with db() as conn:
            briefing_seed.cleanup(conn)
        briefing_seed.clear_caches()


class _Headings(HTMLParser):
    """Collects (level, text) for every h1 to h6 in document order."""

    def __init__(self):
        super().__init__()
        self.headings: list[tuple[int, str]] = []
        self._level = None
        self._buf = ""

    def handle_starttag(self, tag, attrs):
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._level = int(tag[1])
            self._buf = ""

    def handle_endtag(self, tag):
        if self._level is not None and tag == f"h{self._level}":
            self.headings.append((self._level, " ".join(self._buf.split())))
            self._level = None

    def handle_data(self, data):
        if self._level is not None:
            self._buf += data


def _headings(html: str) -> list[tuple[int, str]]:
    parser = _Headings()
    parser.feed(html)
    return parser.headings


def _briefing_sections(html: str) -> list[str]:
    """Every ``<section>`` whose class carries a ``brf-`` prefix, as markup."""
    out = []
    for m in re.finditer(r'<section class="([^"]*)"', html):
        if "brf-" not in m.group(1):
            continue
        start = m.start()
        out.append(html[start: html.index("</section>", start)])
    return out


class _Links(HTMLParser):
    """Collects every ``<a>``'s href and text."""

    def __init__(self):
        super().__init__()
        self.links: list[tuple[str | None, str]] = []
        self._href = None
        self._buf = ""
        self._in_a = False

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._in_a = True
            self._href = dict(attrs).get("href")
            self._buf = ""

    def handle_endtag(self, tag):
        if tag == "a" and self._in_a:
            self.links.append((self._href, " ".join(self._buf.split())))
            self._in_a = False

    def handle_data(self, data):
        if self._in_a:
            self._buf += data


def _links(html: str) -> list[tuple[str | None, str]]:
    parser = _Links()
    parser.feed(html)
    return parser.links


def test_exactly_one_h1(page):
    assert [t for level, t in _headings(page) if level == 1] == ["Birmingham, AL"]


def test_every_h2_text_unique(page):
    h2s = [t for level, t in _headings(page) if level == 2]
    assert h2s, "no h2 on the page"
    assert len(h2s) == len(set(h2s)), f"repeated h2: {h2s}"


def test_headings_are_the_eight_the_design_names(page):
    h2s = [t for level, t in _headings(page) if level == 2]
    assert h2s == DESIGN_HEADINGS


def test_no_emoji_in_briefing_sections(page):
    sections = _briefing_sections(page)
    assert len(sections) >= 8, [s[:60] for s in sections]
    for section in sections:
        found = _EMOJI.findall(section)
        assert not found, f"emoji {found!r} in {section[:80]!r}"


def test_every_link_in_briefing_sections_has_text(page):
    sections = _briefing_sections(page)
    checked = 0
    for section in sections:
        for href, text in _links(section):
            assert text, f"link to {href!r} has no text in {section[:80]!r}"
            checked += 1
    assert checked >= 20, checked


def test_meta_description_present_and_under_300_characters(page):
    m = re.search(r'<meta name="description" content="([^"]*)">', page)
    assert m, "no meta description"
    description = m.group(1)
    assert description.strip()
    assert len(description) < 300, len(description)
    assert "Last meeting." in description


def test_opener_sentences_at_most_25_words(page):
    start = page.index('<section class="brf-opener"')
    opener = page[start: page.index("</section>", start)]
    beats = re.findall(r'<p class="brf-beat">(.*?)</p>', opener, flags=re.S)
    assert len(beats) == 2
    for beat in beats:
        text = " ".join(re.sub(r"<[^>]+>", "", beat).replace("→", "").split())
        for sentence in re.split(r"(?<=[.;])\s+", text):
            words = sentence.split()
            assert len(words) <= 25, f"{len(words)} words: {sentence!r}"


def test_forbidden_words_absent_from_page(page):
    body = re.sub(r"<!--.*?-->", "", page, flags=re.S)
    for word in FORBIDDEN_WORDS:
        hits = re.findall(rf"\b{re.escape(word)}\b", body)
        assert not hits, f"{word!r} appears {len(hits)} time(s) on the page"
