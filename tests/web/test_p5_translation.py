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
