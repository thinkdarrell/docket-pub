"""Crawler policy routes: ``/robots.txt`` and the sitemap family.

The policy is: search engines and readers are welcome on public pages,
nobody is sent into the admin area, the search results page, or
query-string URLs, and crawlers that identify themselves as collecting
AI training data are kept off the whole site. The sitemap family tells
the welcome crawlers where the public pages are without making them
discover tens of thousands of item pages by following links.
"""

from __future__ import annotations

from datetime import datetime

import psycopg2.extras
import pytest

from docket.db import db
from docket.web import crawlers

CITY_SLUG = "crawltest_city"


def _cleanup() -> None:
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM agenda_items WHERE title LIKE 'CRAWL_TEST_%'")
            cur.execute("DELETE FROM meetings WHERE title LIKE 'CRAWL_TEST_%'")
            cur.execute("DELETE FROM municipalities WHERE slug = %s", (CITY_SLUG,))
        conn.commit()


@pytest.fixture
def seeded_city():
    """One city with a visible meeting (two items) and a hidden meeting (one item)."""
    _cleanup()
    crawlers.clear_cache()
    ids: dict[str, int] = {}
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO municipalities (slug, name, state, adapter_class, active)
                   VALUES (%s, 'Crawl City', 'AL',
                           'docket.adapters.granicus.GranicusAdapter', TRUE)
                   RETURNING id""",
                (CITY_SLUG,),
            )
            muni_id = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO meetings
                   (municipality_id, external_id, title, meeting_date, meeting_type, is_hidden)
                   VALUES (%s, 'crawl_visible', 'CRAWL_TEST_Visible Meeting', %s, 'regular', FALSE)
                   RETURNING id""",
                (muni_id, datetime(2026, 5, 1)),
            )
            ids["visible_meeting"] = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO meetings
                   (municipality_id, external_id, title, meeting_date, meeting_type, is_hidden)
                   VALUES (%s, 'crawl_hidden', 'CRAWL_TEST_Hidden Meeting', %s, 'regular', TRUE)
                   RETURNING id""",
                (muni_id, datetime(2026, 5, 2)),
            )
            ids["hidden_meeting"] = cur.fetchone()["id"]
            for key, meeting_key, ext in (
                ("visible_item_a", "visible_meeting", "crawl_a"),
                ("visible_item_b", "visible_meeting", "crawl_b"),
                ("hidden_item", "hidden_meeting", "crawl_h"),
            ):
                cur.execute(
                    """INSERT INTO agenda_items (meeting_id, external_id, item_number, title)
                       VALUES (%s, %s, '1', %s) RETURNING id""",
                    (ids[meeting_key], ext, f"CRAWL_TEST_{key}"),
                )
                ids[key] = cur.fetchone()["id"]
        conn.commit()
    yield ids
    _cleanup()
    crawlers.clear_cache()


# --- robots.txt --------------------------------------------------------------


def test_robots_is_plain_text(client):
    resp = client.get("/robots.txt")
    assert resp.status_code == 200
    assert resp.mimetype == "text/plain"


def test_robots_welcomes_everyone_on_public_pages(client):
    body = client.get("/robots.txt").get_data(as_text=True)
    general = body.split("User-agent: *", 1)[1].split("\n\n", 1)[0]
    assert "Allow: /" in general
    assert "Disallow: /admin/" in general
    assert "Disallow: /search" in general
    assert "Disallow: /*?" in general


@pytest.mark.parametrize(
    "agent",
    ["GPTBot", "ClaudeBot", "Google-Extended", "Applebot-Extended",
     "Bytespider", "CCBot", "PerplexityBot", "Amazonbot", "meta-externalagent"],
)
def test_robots_disallows_ai_training_crawlers(client, agent):
    body = client.get("/robots.txt").get_data(as_text=True)
    assert f"User-agent: {agent}\n" in body
    ai_block = body.split(f"User-agent: {agent}\n", 1)[1].split("\n\n", 1)[0]
    assert "Disallow: /" in ai_block
    assert "Allow:" not in ai_block


def test_robots_does_not_single_out_search_engines(client):
    body = client.get("/robots.txt").get_data(as_text=True)
    assert "User-agent: Googlebot" not in body
    assert "User-agent: Bingbot" not in body


def test_robots_points_at_absolute_sitemap(client):
    body = client.get("/robots.txt").get_data(as_text=True)
    assert "Sitemap: http://localhost/sitemap.xml" in body


# --- sitemaps ----------------------------------------------------------------


def test_sitemap_index_lists_pages_and_each_city(client, seeded_city):
    resp = client.get("/sitemap.xml")
    assert resp.status_code == 200
    assert resp.mimetype == "application/xml"
    body = resp.get_data(as_text=True)
    assert "<sitemapindex" in body
    assert "<loc>http://localhost/sitemaps/pages.xml</loc>" in body
    assert f"<loc>http://localhost/sitemaps/{CITY_SLUG}/meetings.xml</loc>" in body
    assert f"<loc>http://localhost/sitemaps/{CITY_SLUG}/items-1.xml</loc>" in body
    assert f"/sitemaps/{CITY_SLUG}/items-2.xml" not in body


def test_pages_sitemap_lists_static_public_pages(client):
    body = client.get("/sitemaps/pages.xml").get_data(as_text=True)
    assert "<urlset" in body
    assert "<loc>http://localhost/</loc>" in body
    assert "<loc>http://localhost/about/</loc>" in body


def test_city_meetings_sitemap_skips_hidden_meetings(client, seeded_city):
    body = client.get(f"/sitemaps/{CITY_SLUG}/meetings.xml").get_data(as_text=True)
    assert f"<loc>http://localhost/al/{CITY_SLUG}/</loc>" in body
    assert f"<loc>http://localhost/al/{CITY_SLUG}/meetings/{seeded_city['visible_meeting']}/</loc>" in body
    assert f"/meetings/{seeded_city['hidden_meeting']}/" not in body
    assert "<lastmod>" in body


def test_city_items_sitemap_skips_items_of_hidden_meetings(client, seeded_city):
    body = client.get(f"/sitemaps/{CITY_SLUG}/items-1.xml").get_data(as_text=True)
    assert f"<loc>http://localhost/al/{CITY_SLUG}/items/{seeded_city['visible_item_a']}/</loc>" in body
    assert f"<loc>http://localhost/al/{CITY_SLUG}/items/{seeded_city['visible_item_b']}/</loc>" in body
    assert f"/items/{seeded_city['hidden_item']}/" not in body


def test_items_sitemap_page_past_the_end_is_404(client, seeded_city):
    assert client.get(f"/sitemaps/{CITY_SLUG}/items-2.xml").status_code == 404
    assert client.get(f"/sitemaps/{CITY_SLUG}/items-0.xml").status_code == 404


def test_unknown_city_sitemaps_are_404(client):
    assert client.get("/sitemaps/no_such_city/meetings.xml").status_code == 404
    assert client.get("/sitemaps/no_such_city/items-1.xml").status_code == 404


def test_sitemaps_are_cacheable_for_a_day(client, seeded_city):
    resp = client.get(f"/sitemaps/{CITY_SLUG}/meetings.xml")
    assert resp.headers["Cache-Control"] == "public, max-age=86400"
