"""The minutes page viewer (plan `minutes-open-at-the-vote-page`, M3).

`GET /al/<slug>/meetings/<id>/minutes/page/<n>/` shows page n of the meeting's
minutes as a picture inside a docket.pub page, beside a link to the city's own
file. The route reads the address stored on the meeting and never one from the
request; the city's fetch is faked here (`minutes_viewer._fetch`), so no test
sends a city anything.

The meetings are seeded under external ids that begin `mv-test-` and removed
before and after.
"""

from __future__ import annotations

import base64
import logging
import re
from pathlib import Path

import psycopg2.extras
import pytest

from docket.adapters import source_file
from docket.db import db
from docket.services import minutes_viewer
from docket.web import create_app

PREFIX = "mv-test-"
MINUTES_URL = (
    "https://mobileal.api.civicclerk.com/v1/Meetings/"
    "GetMeetingFileStream(fileId=3854,plainText=false)"
)
HTTP_URL = "http://" + MINUTES_URL[len("https://"):]
UNSAFE_URL = "https://minutes.example.org/file.pdf"
BHAM_URL = "https://bhamal.granicus.com/DocumentViewer.php?file=mv-test.pdf"

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/committee_documents/ps_minutes_2026-09-22.pdf"  # four pages
LAYOUT_CSS = ROOT / "src/docket/web/static/layout.css"


def _cleanup() -> None:
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE external_id LIKE %s", (PREFIX + "%",))
        conn.commit()


def _meeting(cur, slug, ext, minutes_url=None, hidden=False) -> int:
    cur.execute(
        """INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type,
                                 minutes_url, is_hidden)
           SELECT id, %s, %s, '2026-11-03', 'council', %s, %s FROM municipalities WHERE slug = %s
           RETURNING id""",
        (PREFIX + ext, "MVTEST council " + ext, minutes_url, hidden, slug),
    )
    return cur.fetchone()["id"]


@pytest.fixture
def seeded():
    """Five Mobile meetings and a Birmingham one, each a state the viewer answers for.

    `good`: the city's `https` minutes address. `none`: no minutes address.
    `unsafe`: an address outside the allowlist. `http`: the good address over
    `http`. `hidden`: the good address on a hidden meeting. `bham`: a
    Birmingham meeting with an address on the static allowlist.
    """
    _cleanup()
    ids: dict[str, int] = {}
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            ids["good"] = _meeting(cur, "mobile", "good", MINUTES_URL)
            ids["none"] = _meeting(cur, "mobile", "none")
            ids["unsafe"] = _meeting(cur, "mobile", "unsafe", UNSAFE_URL)
            ids["http"] = _meeting(cur, "mobile", "http", HTTP_URL)
            ids["hidden"] = _meeting(cur, "mobile", "hidden", MINUTES_URL, hidden=True)
            ids["bham"] = _meeting(cur, "birmingham", "bham", BHAM_URL)
        conn.commit()
    yield ids
    _cleanup()


@pytest.fixture(autouse=True)
def fetched(monkeypatch):
    """The city's fetch faked: the addresses asked for, each answered with the fixture."""
    minutes_viewer.clear()
    calls: list[str] = []
    data = FIXTURE.read_bytes()

    def fake_fetch(url):
        calls.append(url)
        return data

    monkeypatch.setattr(minutes_viewer, "_fetch", fake_fetch)
    monkeypatch.setattr(minutes_viewer, "_sleep", lambda seconds: None)
    yield calls
    minutes_viewer.clear()


@pytest.fixture
def admin_client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key-minutes-viewer"
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["admin_user"] = "mv-test-admin"
    return client


def _path(meeting_id, page, slug="mobile") -> str:
    return f"/al/{slug}/meetings/{meeting_id}/minutes/page/{page}/"


def _tags(body: str, name: str, cls: str) -> list[str]:
    """Every opening `<name ...>` tag of the body whose class list holds `cls`."""
    found = []
    for tag in re.findall(rf"<{name}\b[^>]*>", body):
        classes = re.search(r'class="([^"]*)"', tag)
        if classes and cls in classes.group(1).split():
            found.append(tag)
    return found


def _one(body: str, name: str, cls: str) -> str:
    tags = _tags(body, name, cls)
    assert len(tags) == 1, tags
    return tags[0]


def _hrefs(body: str) -> list[str]:
    return re.findall(r'<a\b[^>]*\bhref="([^"]*)"', body)


# --- the page ----------------------------------------------------------------


def test_a_page_of_the_minutes_is_shown_inline_with_the_citys_link(client, seeded, fetched):
    resp = client.get(_path(seeded["good"], 2))
    assert resp.status_code == 200
    assert "Content-Disposition" not in resp.headers
    assert resp.headers["X-Robots-Tag"] == "noindex"
    assert resp.headers["Cache-Control"] == "private, max-age=600"
    assert resp.mimetype == "text/html"

    body = resp.get_data(as_text=True)
    assert "Minutes, page 2 of 4" in body
    assert '<meta name="robots" content="noindex">' in body
    title = re.search(r"<title>Minutes, page 2 — (.+) — docket\.pub</title>", body)
    assert title, "the title names the page and the meeting"
    assert "Minutes · November 3, 2026" in body
    # The meeting is named after the link back to it.
    assert re.search(
        r"← Back to the meeting</a>\s*· " + re.escape(title.group(1)) + r"\s*</p>", body
    )

    city = _one(body, "a", "minutes-city-file")
    assert f'href="{MINUTES_URL}#page=2"' in city
    assert 'target="_blank"' in city
    assert 'rel="noreferrer"' in city
    assert re.search(re.escape(city) + r"The city's own file \(PDF\) ↗</a>", body)
    assert (
        "This is page 2 as docket.pub drew it from the city's file; "
        "the city's file is the record." in body
    )
    assert "could not open the city's file" not in body

    image = _one(body, "img", "minutes-page-image")
    src = re.search(r'src="([^"]*)"', image).group(1)
    assert src.startswith("data:image/webp;base64,")
    assert base64.b64decode(src.split(",", 1)[1])[:4] == b"RIFF"
    assert 'width="1200"' in image
    assert 'height="1553"' in image
    assert (
        'alt="Page 2 of the minutes of the November 3, 2026 meeting, as the city published it"'
        in image
    )

    hrefs = _hrefs(body)
    assert _path(seeded["good"], 1) in hrefs
    assert _path(seeded["good"], 3) in hrefs
    back = re.search(r'<a class="link" href="([^"]*)">← Back to the meeting</a>', body)
    assert back.group(1) == f"/al/mobile/meetings/{seeded['good']}/"

    assert fetched == [MINUTES_URL]


def test_the_two_navs_are_named_for_a_screen_reader(client, seeded):
    body = client.get(_path(seeded["good"], 2)).get_data(as_text=True)
    navs = re.findall(r"<nav\b[^>]*>", body)
    viewer_navs = [nav for nav in navs if "minutes-page-nav" in nav]
    assert len(viewer_navs) == 2
    assert 'aria-label="Minutes pages"' in viewer_navs[0]
    assert 'aria-label="Minutes pages, below the page"' in viewer_navs[1]
    # The picture sits between them.
    assert body.index(viewer_navs[0]) < body.index("minutes-page-image") < body.index(viewer_navs[1])
    # Each nav has its two links, marked for a crawler.
    prev = _tags(body, "a", "minutes-page-prev")
    nxt = _tags(body, "a", "minutes-page-next")
    assert len(prev) == 2 and len(nxt) == 2
    assert all('rel="prev nofollow"' in tag for tag in prev)
    assert all('rel="next nofollow"' in tag for tag in nxt)
    assert "← Page 1" in body and "Page 3 →" in body


def test_the_first_page_has_no_page_before_and_the_last_none_after(client, seeded):
    first = client.get(_path(seeded["good"], 1)).get_data(as_text=True)
    assert "Minutes, page 1 of 4" in first
    assert _path(seeded["good"], 0) not in _hrefs(first)
    assert _tags(first, "a", "minutes-page-prev") == []
    assert _path(seeded["good"], 2) in _hrefs(first)

    last = client.get(_path(seeded["good"], 4)).get_data(as_text=True)
    assert "Minutes, page 4 of 4" in last
    assert _path(seeded["good"], 5) not in _hrefs(last)
    assert _tags(last, "a", "minutes-page-next") == []
    assert _path(seeded["good"], 3) in _hrefs(last)


def test_a_second_page_of_one_file_sends_the_city_nothing_more(client, seeded, fetched):
    assert client.get(_path(seeded["good"], 2)).status_code == 200
    assert client.get(_path(seeded["good"], 3)).status_code == 200
    assert fetched == [MINUTES_URL]


def test_an_address_in_the_request_is_ignored(client, seeded, fetched):
    plain = client.get(_path(seeded["good"], 2)).get_data(as_text=True)
    resp = client.get(_path(seeded["good"], 2) + "?url=https://evil.example/x.pdf&page=3")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Minutes, page 2 of 4" in body
    assert body == plain
    assert "evil.example" not in body
    assert fetched and all(url == MINUTES_URL for url in fetched)


def test_the_route_is_not_keyed_on_one_city(client, seeded, fetched):
    resp = client.get(_path(seeded["bham"], 1, slug="birmingham"))
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Minutes, page 1 of 4" in body
    city = _one(body, "a", "minutes-city-file")
    assert f'href="{BHAM_URL}#page=1"' in city
    assert fetched == [BHAM_URL]


# --- not found ---------------------------------------------------------------


@pytest.mark.parametrize("page", ["0", "2001", "-1", "abc"])
def test_a_page_outside_the_bound_is_not_found_and_nothing_is_fetched(client, seeded, fetched, page):
    resp = client.get(_path(seeded["good"], page))
    assert resp.status_code == 404
    assert "minutes-city-file" not in resp.get_data(as_text=True)  # the site's plain 404
    assert fetched == []


def test_a_page_past_the_files_end_is_not_found_but_still_shows_the_citys_file(
    client, seeded, fetched
):
    resp = client.get(_path(seeded["good"], 5))
    assert resp.status_code == 404
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.headers["X-Robots-Tag"] == "noindex"
    assert "Content-Disposition" not in resp.headers
    assert fetched == [MINUTES_URL]

    body = resp.get_data(as_text=True)
    assert ">Minutes, page 5</h1>" in body
    assert "Minutes, page 5 of" not in body
    assert "The city's file ends at page 4; there is no page 5." in body
    assert "The city may have replaced the file since docket.pub read it." in body
    city = _one(body, "a", "minutes-city-file")
    assert f'href="{MINUTES_URL}"' in city  # the stored address, no page added
    assert "#page=" not in body
    last = _one(body, "a", "minutes-page-last")
    assert f'href="{_path(seeded["good"], 4)}"' in last
    assert 'rel="nofollow"' in last
    assert "Go to page 4" in body
    assert _tags(body, "img", "minutes-page-image") == []
    assert "minutes-page-nav" not in body


def test_a_file_with_no_pages_offers_no_last_page(client, seeded, monkeypatch):
    def no_pages(url, page):
        raise minutes_viewer.NoSuchPage("page 1 of 0", page_count=0)

    monkeypatch.setattr(minutes_viewer, "page_view", no_pages)
    resp = client.get(_path(seeded["good"], 1))
    assert resp.status_code == 404
    body = resp.get_data(as_text=True)
    assert "The city's file ends at page 0; there is no page 1." in body
    assert len(_tags(body, "a", "minutes-city-file")) == 1
    assert "minutes-page-last" not in body
    assert _path(seeded["good"], 0) not in _hrefs(body)


@pytest.mark.parametrize("key", ["none", "unsafe", "http"])
def test_a_meeting_whose_minutes_the_viewer_may_not_fetch_is_not_found(
    client, seeded, fetched, key
):
    assert client.get(_path(seeded[key], 2)).status_code == 404
    assert fetched == []


def test_a_hidden_meeting_is_not_found_without_a_sign_in(client, seeded, fetched):
    assert client.get(_path(seeded["hidden"], 2)).status_code == 404
    assert fetched == []


def test_a_meeting_under_another_citys_address_is_not_found(client, seeded, fetched):
    assert client.get(_path(seeded["good"], 2, slug="birmingham")).status_code == 404
    assert client.get(_path(seeded["good"], 2, slug="no-such-city")).status_code == 404
    assert fetched == []


def test_an_unknown_meeting_is_not_found(client, seeded, fetched):
    assert client.get(_path(2_000_000_000, 2)).status_code == 404
    assert fetched == []


# --- the hidden meeting, signed in -------------------------------------------


def test_a_hidden_meetings_page_is_shown_to_an_admin_and_is_not_stored(
    admin_client, seeded, fetched
):
    resp = admin_client.get(_path(seeded["hidden"], 2))
    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.headers["X-Robots-Tag"] == "noindex"
    body = resp.get_data(as_text=True)
    assert "Minutes, page 2 of 4" in body
    assert len(_tags(body, "img", "minutes-page-image")) == 1
    assert fetched == [MINUTES_URL]


def test_a_hidden_meetings_page_past_the_end_is_not_stored_either(admin_client, seeded):
    resp = admin_client.get(_path(seeded["hidden"], 5))
    assert resp.status_code == 404
    assert resp.headers["Cache-Control"] == "no-store"


# --- the unavailable state ---------------------------------------------------


def test_a_file_that_cannot_be_fetched_shows_the_citys_link_alone(
    client, seeded, monkeypatch, caplog
):
    calls: list[str] = []

    def failing_fetch(url):
        calls.append(url)
        raise source_file.SourceFileError("status 503", host_down=True)

    monkeypatch.setattr(minutes_viewer, "_fetch", failing_fetch)
    with caplog.at_level(logging.WARNING):
        resp = client.get(_path(seeded["good"], 2))

    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.headers["X-Robots-Tag"] == "noindex"
    assert "Content-Disposition" not in resp.headers
    assert calls == [MINUTES_URL]

    body = resp.get_data(as_text=True)
    assert ">Minutes, page 2</h1>" in body
    assert "of 4" not in body
    city = _one(body, "a", "minutes-city-file")
    assert f'href="{MINUTES_URL}#page=2"' in city
    assert "docket.pub could not open the city's file just now. Open it and go to page 2." in body
    assert "as docket.pub drew it" not in body
    assert _tags(body, "img", "minutes-page-image") == []
    assert "minutes-page-nav" not in body
    assert "minutes-page-last" not in body
    assert '<meta name="robots" content="noindex">' in body

    routes = [
        record for record in caplog.records
        if record.name == "docket.web.public"
        and record.getMessage().startswith("minutes viewer: unavailable")
    ]
    assert len(routes) == 1
    assert routes[0].levelno == logging.WARNING
    message = routes[0].getMessage()
    assert "mobile" in message
    assert str(seeded["good"]) in message
    assert "page=2" in message


def test_an_unavailable_page_of_a_hidden_meeting_is_not_stored(
    admin_client, seeded, monkeypatch
):
    def failing_fetch(url):
        raise source_file.SourceFileError("status 404")

    monkeypatch.setattr(minutes_viewer, "_fetch", failing_fetch)
    resp = admin_client.get(_path(seeded["hidden"], 2))
    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "no-store"


# --- the stylesheet and the template global ----------------------------------


def test_the_stylesheet_fits_the_picture_and_keeps_the_next_link_at_the_right():
    css = re.sub(r"\s+", " ", LAYOUT_CSS.read_text(encoding="utf-8"))
    image = re.search(r"\.minutes-page-image \{([^}]*)\}", css).group(1)
    assert "width: 100%;" in image
    assert "height: auto;" in image
    assert "max-width: 1200px;" in image
    # Three columns; each link names its own, so the link to the next page
    # is at the right edge on page 1, where it has no link at the left.
    nav = re.search(r"\.minutes-page-nav \{([^}]*)\}", css).group(1)
    assert "grid-template-columns: 1fr auto 1fr;" in nav
    assert ".minutes-page-prev { grid-column: 1; justify-self: start; }" in css
    assert ".minutes-page-next { grid-column: 3; justify-self: end; }" in css
    # A link a thumb can hit.
    step = re.search(r"\.minutes-page-step \{([^}]*)\}", css).group(1)
    assert "min-height: 44px;" in step


def test_each_nav_says_which_page_of_how_many(client, seeded):
    body = client.get(_path(seeded["good"], 2)).get_data(as_text=True)
    assert body.count('<span class="minutes-page-count">Page 2 of 4</span>') == 2


def test_the_viewer_predicate_is_a_template_global():
    from docket.web import source_security

    app = create_app()
    assert app.jinja_env.globals["is_minutes_viewer_url"] is source_security.is_viewer_url


# --- the link that leads here (plan `minutes-open-at-the-vote-page`, M4) ------


def test_the_meeting_pages_link_opens_a_viewer_page_that_answers(client, seeded, fetched):
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO votes (meeting_id, source, result, yeas, nays, abstentions,
                                      confidence, needs_review, minutes_reader, source_page,
                                      declared_text)
                   VALUES (%s, 'minutes_text', 'passed', 7, 0, 0, 'high', FALSE, 'mobile', 2,
                           'the agenda adopted')
                   RETURNING id""",
                (seeded["good"],),
            )
            vote_id = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO member_votes (vote_id, council_member_id, member_name, position) "
                "VALUES (%s, NULL, 'Penn', 'yea')",
                (vote_id,),
            )
        conn.commit()

    meeting = client.get(f"/al/mobile/meetings/{seeded['good']}/")
    assert meeting.status_code == 200
    links = re.findall(r'<a\b[^>]*\bhref="([^"]*)"[^>]*>\s*Minutes, page 2\s*</a>',
                       meeting.get_data(as_text=True))
    assert links == [_path(seeded["good"], 2)]
    assert fetched == [], "printing the link asks the city for nothing"

    resp = client.get(links[0])
    assert resp.status_code == 200
    assert "Minutes, page 2 of 4" in resp.get_data(as_text=True)
    assert fetched == [MINUTES_URL]
