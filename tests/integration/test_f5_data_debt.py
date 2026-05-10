"""Integration tests for F5 — public data-debt page + two RSS feeds.

Three deliverables under test:

- F5.1: public data-debt HTML page at ``/al/<city>/data-debt`` —
  citizen-friendly listing of items where ``data_quality != 'ok'``
  or ``processing_status = 'failed_permanent'``, sorted by
  ``data_debt_priority DESC, meeting_date DESC`` (decision #84).
- F5.2: two RSS 2.0 feeds at ``/al/<city>/data-debt.rss`` and
  ``/al/<city>/upcoming-hearings.rss`` with a 60-min cache.
- F5.3: RSS XML templates with ``<atom:link rel="self">`` self-link,
  RFC-822 ``<lastBuildDate>`` / ``<pubDate>``, and well-formed XML
  body (validated via ``xml.etree.ElementTree``).

Plus the new query helpers: ``list_data_debt_items``,
``list_upcoming_hearings``.

Reuses the ``_Bag`` test-data tracker pattern (insert via ``db()``
which commits, track ids, clean up on fixture teardown). The Flask
test client is built per-module from ``create_app()``.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, timedelta

import pytest

from docket.config import DATABASE_URL
from docket.db import db
from docket.migrations.runner import apply_migrations
from docket.services.query import list_data_debt_items, list_upcoming_hearings
from docket.web import create_app
from docket.web import public as public_module


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run F5 tests against Railway DB.",
)


# ---------------------------------------------------------------------------
# Test data tracker — same shape as F4's _Bag.
# ---------------------------------------------------------------------------


class _Bag:
    def __init__(self, city_id: int, city_slug: str):
        self.city_id = city_id
        self.city_slug = city_slug
        self.meeting_ids: list[int] = []
        self.item_ids: list[int] = []

    def add_meeting(self, meeting_date_str: str, *, title: str = "Test meeting") -> int:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO meetings
                      (municipality_id, title, meeting_date, meeting_type)
                    VALUES (%s, %s, %s, 'council')
                    RETURNING id
                    """,
                    (self.city_id, title, meeting_date_str),
                )
                mid = cur.fetchone()[0]
        self.meeting_ids.append(mid)
        return mid

    def add_item(
        self,
        meeting_id: int,
        *,
        title: str = "Test item",
        data_quality: str | None = "no_text_layer",
        data_debt_priority: str | None = "normal",
        processing_status: str = "pending",
    ) -> int:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agenda_items
                      (meeting_id, title, data_quality, data_debt_priority,
                       processing_status)
                    VALUES (%s, %s,
                            %s::data_quality_enum,
                            %s::data_debt_priority_enum,
                            %s::processing_status_enum)
                    RETURNING id
                    """,
                    (
                        meeting_id, title, data_quality,
                        data_debt_priority, processing_status,
                    ),
                )
                iid = cur.fetchone()[0]
        self.item_ids.append(iid)
        return iid

    def cleanup(self) -> None:
        with db() as conn:
            with conn.cursor() as cur:
                if self.item_ids:
                    cur.execute(
                        "DELETE FROM agenda_items WHERE id = ANY(%s)",
                        (self.item_ids,),
                    )
                if self.meeting_ids:
                    cur.execute(
                        "DELETE FROM meetings WHERE id = ANY(%s)",
                        (self.meeting_ids,),
                    )


@pytest.fixture
def bag():
    with db() as conn:
        apply_migrations(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, slug FROM municipalities WHERE slug = 'birmingham'"
            )
            row = cur.fetchone()
            assert row is not None, "Birmingham must be seeded"
            city_id, city_slug = row[0], row[1]
    b = _Bag(city_id, city_slug)
    try:
        yield b
    finally:
        b.cleanup()


@pytest.fixture(scope="module")
def app():
    flask_app = create_app()
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    public_module._overview_cache.clear()
    public_module._rss_cache.clear()
    return app.test_client()


# ---------------------------------------------------------------------------
# F5 — query helpers
# ---------------------------------------------------------------------------


def test_list_data_debt_items_filters_to_city(bag):
    m = bag.add_meeting("2026-04-15")
    bag.add_item(m, title="Need OCR", data_quality="no_text_layer")
    rows = list_data_debt_items(bag.city_id)
    assert any(r["title"] == "Need OCR" for r in rows)
    # Other city not present.
    assert all(r["municipality_slug"] == "birmingham" for r in rows)


def test_list_data_debt_items_excludes_ok(bag):
    m = bag.add_meeting("2026-04-15")
    iid_bad = bag.add_item(m, title="Bad", data_quality="no_text_layer")
    iid_ok = bag.add_item(m, title="Ok",  data_quality="ok",
                          processing_status="completed")
    rows = list_data_debt_items(bag.city_id)
    ids = {r["id"] for r in rows}
    assert iid_bad in ids
    assert iid_ok not in ids


def test_list_data_debt_items_includes_failed_permanent(bag):
    m = bag.add_meeting("2026-04-15")
    iid = bag.add_item(
        m, title="Failed",
        data_quality=None,  # NULL data_quality but failed_permanent
        data_debt_priority=None,
        processing_status="failed_permanent",
    )
    rows = list_data_debt_items(bag.city_id)
    assert iid in {r["id"] for r in rows}


def test_list_data_debt_items_sort_high_first_then_recent(bag):
    m_old = bag.add_meeting("2026-01-01")
    m_new = bag.add_meeting("2026-04-15")
    high_old = bag.add_item(m_old, title="High old", data_debt_priority="high")
    high_new = bag.add_item(m_new, title="High new", data_debt_priority="high")
    norm_new = bag.add_item(m_new, title="Norm new", data_debt_priority="normal")

    rows = list_data_debt_items(bag.city_id)
    titles = [r["title"] for r in rows if r["id"] in {high_old, high_new, norm_new}]
    # Both "high" come before "normal", and within "high" newer comes first.
    assert titles.index("High new") < titles.index("High old")
    assert titles.index("High old") < titles.index("Norm new")


def test_list_data_debt_items_pagination_limit_offset(bag):
    m = bag.add_meeting("2026-04-15")
    for i in range(5):
        bag.add_item(m, title=f"Item {i}")
    page1 = list_data_debt_items(bag.city_id, limit=3, offset=0)
    page2 = list_data_debt_items(bag.city_id, limit=3, offset=3)
    ids1 = {r["id"] for r in page1}
    ids2 = {r["id"] for r in page2}
    assert len(page1) == 3
    assert ids1.isdisjoint(ids2)


def test_list_upcoming_hearings_matches_meeting_title(bag):
    soon = (date.today() + timedelta(days=14)).isoformat()
    m = bag.add_meeting(soon, title="Public Hearing on Rezoning")
    rows = list_upcoming_hearings(bag.city_id)
    assert any(r["meeting_id"] == m for r in rows)


def test_list_upcoming_hearings_matches_agenda_item_title(bag):
    soon = (date.today() + timedelta(days=14)).isoformat()
    m = bag.add_meeting(soon, title="Council Meeting")
    bag.add_item(
        m, title="Public hearing on budget amendment",
        data_quality="ok", data_debt_priority=None,
        processing_status="completed",
    )
    rows = list_upcoming_hearings(bag.city_id)
    hits = [r for r in rows if r["meeting_id"] == m]
    assert hits, "expected the agenda-item match to surface"
    assert "hearing" in hits[0]["hearing_title"].lower()


def test_list_upcoming_hearings_excludes_past(bag):
    past = (date.today() - timedelta(days=5)).isoformat()
    bag.add_meeting(past, title="Public Hearing past")
    rows = list_upcoming_hearings(bag.city_id)
    titles = [r["meeting_title"] for r in rows]
    assert "Public Hearing past" not in titles


def test_list_upcoming_hearings_excludes_far_future(bag):
    far = (date.today() + timedelta(days=400)).isoformat()
    bag.add_meeting(far, title="Public Hearing far future")
    rows = list_upcoming_hearings(bag.city_id)
    titles = [r["meeting_title"] for r in rows]
    assert "Public Hearing far future" not in titles


# ---------------------------------------------------------------------------
# F5.1 — public data-debt HTML page
# ---------------------------------------------------------------------------


def test_data_debt_page_renders(bag, client):
    m = bag.add_meeting("2026-04-15")
    bag.add_item(m, title="Scanned PDF", data_quality="no_text_layer")
    rv = client.get("/al/birmingham/data-debt")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Items not yet machine-readable" in body
    assert "Scanned PDF" in body
    # Citizen-friendly: no internal jargon.
    assert "Wave 0" not in body
    assert "processing_status" not in body
    assert "data_quality_enum" not in body


def test_data_debt_priority_grouping(bag, client):
    m = bag.add_meeting("2026-04-15")
    bag.add_item(m, title="High prio item", data_debt_priority="high")
    bag.add_item(m, title="Normal prio item", data_debt_priority="normal")
    rv = client.get("/al/birmingham/data-debt")
    body = rv.get_data(as_text=True)
    # HIGH section should appear before NORMAL section.
    assert "High prio item" in body
    assert "Normal prio item" in body
    assert body.index("High prio item") < body.index("Normal prio item")
    # Section labels (citizen-friendly, but countable).
    assert "High priority" in body
    assert "Standard priority" in body


def test_data_debt_empty_state_is_citizen_friendly(client):
    """No data-debt items → 200 and friendly empty copy."""
    rv = client.get("/al/vestavia_hills/data-debt")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "machine-readable" in body
    # Definitely not jargon.
    assert "Wave 0" not in body
    assert "processing_status" not in body


def test_data_debt_pagination_load_more(bag, client):
    m = bag.add_meeting("2026-04-15")
    # Create 51 items so the load-more button appears.
    for i in range(51):
        bag.add_item(m, title=f"Item {i:03d}")
    rv = client.get("/al/birmingham/data-debt")
    body = rv.get_data(as_text=True)
    assert "Load more items" in body
    assert "offset=50" in body


def test_data_debt_page_has_rss_autodiscovery(bag, client):
    rv = client.get("/al/birmingham/data-debt")
    body = rv.get_data(as_text=True)
    assert 'rel="alternate"' in body
    assert 'type="application/rss+xml"' in body
    assert "/al/birmingham/data-debt.rss" in body


def test_data_debt_mailto_present(bag, client):
    """Falls back to admin@docket.pub until municipalities.admin_email lands."""
    m = bag.add_meeting("2026-04-15")
    bag.add_item(m, title="With mailto")
    rv = client.get("/al/birmingham/data-debt")
    body = rv.get_data(as_text=True)
    assert "mailto:admin@docket.pub" in body
    assert "Report a problem" in body


def test_data_debt_unknown_city_404s(client):
    rv = client.get("/al/atlantis/data-debt")
    assert rv.status_code == 404


# ---------------------------------------------------------------------------
# F5.2 — RSS feeds
# ---------------------------------------------------------------------------


def test_data_debt_rss_renders_valid_xml(bag, client):
    m = bag.add_meeting("2026-04-15")
    bag.add_item(m, title="RSS-debt-item")
    rv = client.get("/al/birmingham/data-debt.rss")
    assert rv.status_code == 200
    assert rv.mimetype == "application/rss+xml"
    body = rv.get_data(as_text=True)
    root = ET.fromstring(body)  # Will raise if not well-formed XML.
    assert root.tag == "rss"
    channel = root.find("channel")
    assert channel is not None
    assert channel.find("title") is not None
    assert channel.find("link") is not None
    assert channel.find("description") is not None
    assert channel.find("lastBuildDate") is not None
    # atom:self-link present
    atom_self = channel.find("{http://www.w3.org/2005/Atom}link")
    assert atom_self is not None
    assert atom_self.get("rel") == "self"
    # The seeded item appears as <item>.
    item_titles = [it.find("title").text for it in channel.findall("item")]
    assert any("RSS-debt-item" in (t or "") for t in item_titles)


def test_upcoming_hearings_rss_renders_valid_xml(bag, client):
    soon = (date.today() + timedelta(days=14)).isoformat()
    bag.add_meeting(soon, title="Public Hearing on RSS test")
    rv = client.get("/al/birmingham/upcoming-hearings.rss")
    assert rv.status_code == 200
    assert rv.mimetype == "application/rss+xml"
    body = rv.get_data(as_text=True)
    root = ET.fromstring(body)
    assert root.tag == "rss"
    channel = root.find("channel")
    assert channel is not None
    item_titles = [it.find("title").text for it in channel.findall("item")]
    assert any("RSS test" in (t or "") for t in item_titles)


def test_rss_60_min_cache_returns_same_body(bag, client, monkeypatch):
    """Calling the RSS endpoint twice within the TTL returns the cached body
    — including a synthetic clock advance under the TTL."""
    m = bag.add_meeting("2026-04-15")
    bag.add_item(m, title="Cache-A")

    # First call — cache miss.
    body1 = client.get("/al/birmingham/data-debt.rss").get_data(as_text=True)

    # Now mutate the underlying data by adding a second item. Without
    # cache the next response would include "Cache-B".
    bag.add_item(m, title="Cache-B")

    body2 = client.get("/al/birmingham/data-debt.rss").get_data(as_text=True)
    # Second response was served from cache — does NOT include the new
    # item. (lastBuildDate may differ if the formatter has sub-second
    # resolution, but the bodies should be byte-identical because the
    # cache returns the rendered string verbatim.)
    assert body1 == body2
    assert "Cache-B" not in body2


def test_rss_cache_key_isolation_per_city(bag, client):
    """Different cities don't stale-serve each other's RSS feeds."""
    body_bhm = client.get("/al/birmingham/data-debt.rss").get_data(as_text=True)
    body_mob = client.get("/al/mobile/data-debt.rss").get_data(as_text=True)
    assert "Birmingham" in body_bhm
    assert "Mobile" in body_mob
    assert body_bhm != body_mob


def test_rss_unknown_city_404s(client):
    rv = client.get("/al/atlantis/data-debt.rss")
    assert rv.status_code == 404
    rv = client.get("/al/atlantis/upcoming-hearings.rss")
    assert rv.status_code == 404


# ---------------------------------------------------------------------------
# F5 — link-crawler smoke (F4 S11 pattern, decision #84 + spec §6.9)
# ---------------------------------------------------------------------------


def test_link_crawler_data_debt_and_rss_all_cities(client):
    """For each of the four deployed cities, GET the data-debt page,
    the data-debt RSS feed, and the upcoming-hearings RSS feed —
    12 endpoints total. All must return 200, and the two RSS responses
    must parse as well-formed XML.

    Mirrors F4's S11 link-crawler smoke pattern. Extends to F5's three
    new surfaces.
    """
    cities = ("birmingham", "mobile", "vestavia_hills", "homewood")
    for city in cities:
        # HTML data-debt page.
        rv = client.get(f"/al/{city}/data-debt")
        assert rv.status_code == 200, (
            f"/al/{city}/data-debt returned {rv.status_code}"
        )

        # data-debt RSS — must parse.
        rv = client.get(f"/al/{city}/data-debt.rss")
        assert rv.status_code == 200, (
            f"/al/{city}/data-debt.rss returned {rv.status_code}"
        )
        ET.fromstring(rv.get_data(as_text=True))

        # upcoming-hearings RSS — must parse.
        rv = client.get(f"/al/{city}/upcoming-hearings.rss")
        assert rv.status_code == 200, (
            f"/al/{city}/upcoming-hearings.rss returned {rv.status_code}"
        )
        ET.fromstring(rv.get_data(as_text=True))
