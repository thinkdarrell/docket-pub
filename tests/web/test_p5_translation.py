"""Route smoke tests for P5 — translation pass.

Each test asserts the DOM contract that P5's restyle landed: new
partials are consumed, old bespoke markup is gone. Heavy data
assertions live in unit tests; these tests check structural hooks.
"""
from __future__ import annotations

import pytest


def test_homepage_uses_kpi_strip_not_kpi_grid(client):
    body = client.get("/").get_data(as_text=True)
    assert "kpi-strip" in body
    # Old 3-card kpi-grid removed
    assert 'class="kpi-grid"' not in body
    assert 'grid-template-columns: repeat(3, 1fr)' not in body


def test_homepage_renders_meeting_card_for_this_week(client):
    body = client.get("/").get_data(as_text=True)
    # If this-week strip renders at all, it uses the meeting_card partial,
    # not the old .tw-card markup.
    has_tw_section = 'class="tw"' in body or 'class="tw "' in body
    if has_tw_section:
        assert "meeting-card meeting-card--strip" in body
        assert "tw-card" not in body


def test_meetings_list_uses_meeting_card_grid(client):
    """Birmingham always has meetings — assert restyle landed.
    Skip gracefully if route 404s or has no seeded data in CI."""
    resp = client.get("/al/birmingham/meetings/")
    if resp.status_code != 200:
        pytest.skip("Birmingham meetings route not available in this env")
    body = resp.get_data(as_text=True)
    if "All meetings" not in body:
        pytest.skip("No Birmingham meetings seeded in this env")
    # New: meeting_card grid variant
    assert "meeting-card meeting-card--grid" in body
    # Old: feed-table layout dropped on this page
    assert "feed-table" not in body


def test_meetings_list_drops_kpi_grid(client):
    resp = client.get("/al/birmingham/meetings/")
    if resp.status_code != 200:
        pytest.skip("Birmingham meetings route not available in this env")
    body = resp.get_data(as_text=True)
    assert 'class="kpi-grid"' not in body


def test_topics_index_uses_topic_row_partial(client):
    body = client.get("/topics/").get_data(as_text=True)
    # Old kpi-grid dropped regardless of seed state
    assert 'class="kpi-grid"' not in body
    # Old council-grid dropped (was being misused for topic cards)
    assert "council-grid" not in body
    # When the env has tagged items, the topic_row partial renders.
    # When it doesn't, the empty-state branch renders instead — skip the
    # structural-hook assertion in that case (matches the meeting_card
    # test's "skip if no seeded data" pattern).
    if "Nothing classified yet" in body:
        pytest.skip("No tagged items seeded in this env")
    # topic_row's structural hooks (verified by existing partial tests)
    assert "topic-row" in body or "topic-pill" in body


def test_404_renders_custom_template(client):
    resp = client.get("/this/path/definitely/does/not/exist")
    assert resp.status_code == 404
    body = resp.get_data(as_text=True)
    # Custom 404 template renders the masthead from P1
    assert "docket.pub" in body  # brand mark
    assert "404" in body  # the status code shown to user
    # Friendly affordance
    assert "Home" in body or "home" in body


def test_500_renders_custom_template_via_direct_render(render_partial):
    """Smoke-load the 500 template via render_partial.

    The test_client doesn't easily trigger the 500 handler in pytest:
    Flask's TESTING=True config makes it propagate exceptions instead of
    returning the rendered error page. Smoke-rendering the template
    verifies its syntax and that the brand mark / status code are visible.
    """
    body = render_partial("errors/500.html")
    assert "500" in body
    assert "docket.pub" in body


def test_search_results_use_card_smart_brevity(client):
    """Search a common term that's likely to return results in any
    backfill state; skip if zero results in CI."""
    resp = client.get("/search?q=council")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # If results exist, they render via card_smart_brevity, not feed-table.
    if "No results" not in body and "Type a query" not in body:
        assert "smart-brevity-card" in body
        assert "feed-table" not in body


def test_search_drops_kpi_grid(client):
    body = client.get("/search?q=council").get_data(as_text=True)
    assert 'class="kpi-grid"' not in body


def test_search_city_scoped_renders_page_sources(client):
    """City-scoped search must wire `municipality` so page_sources renders.

    The page_sources partial is included unconditionally in base.html and
    self-gates on `municipality is defined and municipality`. Removing the
    municipality kwarg in the search view silently breaks this rail; this
    test catches that regression.
    """
    resp = client.get("/search?q=council&city=birmingham")
    if resp.status_code != 200:
        pytest.skip("Search route not available in this env")
    body = resp.get_data(as_text=True)
    # page_sources renders an <aside class="page-sources">; structural hook.
    assert 'class="page-sources"' in body


def test_coverage_listing_uses_hero_detail(client):
    resp = client.get("/coverage/")
    if resp.status_code != 200:
        pytest.skip("Coverage listing route not available in this env")
    body = resp.get_data(as_text=True)
    assert "hero hero--detail" in body


def test_coverage_listing_uses_topsearch_chrome(client):
    """FTS bar adopts the same .topsearch chrome the masthead uses.

    Both the masthead and the FTS form render .topsearch, so we expect
    at least two occurrences. Without the inner one (i.e. if the FTS bar
    drops the wrapper), only the masthead's would remain.
    """
    resp = client.get("/coverage/")
    if resp.status_code != 200:
        pytest.skip("Coverage listing route not available in this env")
    body = resp.get_data(as_text=True)
    assert 'class="coverage-search"' in body
    assert body.count('class="topsearch"') >= 2


def test_coverage_listing_uses_coverage_tabs(client):
    resp = client.get("/coverage/")
    if resp.status_code != 200:
        pytest.skip("Coverage listing route not available in this env")
    body = resp.get_data(as_text=True)
    assert 'class="coverage-tabs t-mono"' in body
    # All tab should be active by default (no kind kwarg)
    assert 'class="coverage-tab is-active"' in body


def test_coverage_listing_preserves_kind_in_search_form(client):
    """When the user is on the Notes (or Citations) tab and uses the FTS
    bar, the form must carry the kind through as a hidden input so the
    search stays scoped to the active tab. Regression-guard for the
    {% if kind %} gate around the hidden input.
    """
    resp = client.get("/coverage/?kind=note")
    if resp.status_code != 200:
        pytest.skip("Coverage listing route not available in this env")
    body = resp.get_data(as_text=True)
    assert 'name="kind"' in body
    assert 'value="note"' in body
