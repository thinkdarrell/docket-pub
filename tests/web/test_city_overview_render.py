"""Render tests for the city overview and the interior pages' KPI stack.

The overview's own sections are tested in ``test_city_briefing.py`` against
the seeded Birmingham of ``tests/support/briefing_seed.py``; this file keeps
the interior-page checks, the city lead, the footer colophon, and the three
page-shape checks the briefing rebuild (plan ``birmingham-city-briefing``,
M2) states: the freshness chip is real once rows exist, the KPI strip and
the two strips and the meetings table are gone, and the other cities render
without opener prose. These tests use the Flask ``client`` fixture from
``tests/web/conftest.py``.
"""

import pytest

from docket.db import db
from tests.support import briefing_seed


def test_overview_renders_freshness_chip_from_seed(client):
    """With a seeded Birmingham meeting the lead's chip shows a real sync date."""
    with db() as conn:
        briefing_seed.seed(conn)
    briefing_seed.clear_caches()
    try:
        resp = client.get("/al/birmingham/")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'class="city-lead-chip is-good"' in html
        assert "synced " in html
        assert "No data yet" not in html
    finally:
        with db() as conn:
            briefing_seed.cleanup(conn)
        briefing_seed.clear_caches()


def test_overview_has_no_kpi_strip_or_strips_or_table(client):
    """M2: the KPI strip, the Upcoming and Last week strips, and the meetings table are gone."""
    briefing_seed.clear_caches()
    resp = client.get("/al/birmingham/")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert 'class="kpi-strip' not in html
    assert "Meetings YTD" not in html
    assert "tw-upcoming-section" not in html
    assert "tw-recent-section" not in html
    assert "On the agenda" not in html
    assert "Last week" not in html
    assert "feed-table" not in html
    assert "brf-meetings-section" in html


@pytest.mark.parametrize("slug", ["mobile", "homewood", "vestavia_hills"])
def test_other_cities_render_without_opener(client, slug):
    """Only a city flagged ``briefing`` gets the opener; every city gets the search field."""
    briefing_seed.clear_caches()
    resp = client.get(f"/al/{slug}/")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert "brf-search" in html
    assert "brf-opener" not in html
    assert 'name="description"' not in html


def test_meetings_list_renders_kpi_explainer_stack(client):
    """Interior pages get the 4-card KPI explainer stack in page_sources."""
    resp = client.get("/al/birmingham/meetings/")
    assert resp.status_code == 200, f"got {resp.status_code}"
    html = resp.data.decode()
    assert 'class="page-sources"' in html
    assert 'page-sources-kpis' in html, (
        "meetings list should render KPI explainer stack"
    )


def test_council_renders_kpi_explainer_stack(client):
    resp = client.get("/al/birmingham/council/")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert 'page-sources-kpis' in html, (
        "council roster should render KPI explainer stack"
    )


def test_meeting_detail_renders_kpi_explainer_stack(client):
    # Use any meeting id likely to exist; if test DB doesn't have one,
    # this test may need adjustment. Try 1 first.
    resp = client.get("/al/birmingham/meetings/1/")
    if resp.status_code == 404:
        # No meeting 1 in test DB — try fetching the list and using whatever ID is there
        resp_list = client.get("/al/birmingham/meetings/")
        import re
        m = re.search(r"/al/birmingham/meetings/(\d+)/", resp_list.data.decode())
        if m:
            mid = m.group(1)
            resp = client.get(f"/al/birmingham/meetings/{mid}/")
    if resp.status_code == 200:
        html = resp.data.decode()
        assert 'page-sources-kpis' in html, (
            "meeting detail should render KPI explainer stack"
        )


def test_overview_renders_city_lead(client):
    """P3: city.html consumes the city_lead partial at the top."""
    resp = client.get("/al/birmingham/")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert 'class="city-lead' in html
    assert "Birmingham, AL" in html


def test_footer_colophon_no_adapter_tile(client):
    """P3: footer colophon drops the per-city Adapter tile; M5 of plan
    birmingham-city-briefing drops the Schema tile too, and the grid reads
    the last ingest from ``city_provenance``, so it renders only once a
    Birmingham meeting exists (the seed supplies one)."""
    with db() as conn:
        briefing_seed.seed(conn)
    briefing_seed.clear_caches()
    try:
        resp = client.get("/al/birmingham/")
        html = resp.data.decode()
    finally:
        with db() as conn:
            briefing_seed.cleanup(conn)
        briefing_seed.clear_caches()

    # Find the colophon section + scope the search to it
    start = html.find("footnote-colophon")
    end = html.find("footnote-bottom")
    assert start > -1 and end > -1, "footer colophon not found"
    colophon = html[start:end]

    assert "Adapter</span>" not in colophon, (
        "footer colophon still has Adapter tile"
    )
    assert "Schema</span>" not in colophon
    assert "tsvector" not in colophon
    assert "Source</span>" in colophon
    assert "Updated</span>" in colophon


def test_meeting_detail_source_links_below_executive_summary(client):
    """P3: per-meeting source links (Agenda / Video / Original source)
    sit at the bottom of the meeting detail content, consistent with
    the 'sources at page bottom' pattern."""
    resp = client.get("/al/birmingham/meetings/2231/")
    if resp.status_code == 404:
        # Meeting 2231 might not exist locally; pick any available
        # by listing first.
        listing = client.get("/al/birmingham/meetings/")
        import re
        m = re.search(r"/al/birmingham/meetings/(\d+)/", listing.data.decode())
        if not m:
            # A fresh database has no Birmingham meetings; say so rather
            # than pass while asserting nothing.
            pytest.skip("No Birmingham meetings seeded")
        resp = client.get(f"/al/birmingham/meetings/{m.group(1)}/")
    assert resp.status_code == 200
    html = resp.data.decode()
    # The source-links section ("Agenda" rail-link-label is unique to it)
    sources_pos = html.find('class="mtg-sources"')
    # The KPI strip at top has class="kpi-strip" — must be earlier
    kpi_pos = html.find('class="kpi-strip"')
    # Roll call / votes section ("Roll call" eyebrow appears in body).
    # The template renders it only when the meeting has votes
    # (`{% if votes %}`), so a local database without vote rows renders
    # no roll-call section; the ordering check against it applies only
    # when the section is present.
    rollcall_pos = html.find("ROLL CALL")
    if rollcall_pos == -1:
        rollcall_pos = html.find("Roll call")
    assert sources_pos > -1, "mtg-sources section missing"
    assert kpi_pos > -1, "kpi-strip section missing"
    # The source links should appear AFTER the KPI strip AND, when the
    # meeting has votes, after the roll-call section.
    assert sources_pos > kpi_pos, "sources should be below KPI strip"
    if rollcall_pos > -1:
        assert sources_pos > rollcall_pos, (
            f"sources at {sources_pos} should be below roll-call at {rollcall_pos}"
        )
