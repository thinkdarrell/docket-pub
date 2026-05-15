"""Verify card templates no longer issue hx-get calls to deleted rail
endpoints, and cards still have a navigable click target.

Task 9 strips all ``hx-get="...rail_meeting"`` / ``hx-get="...rail_member"``
attrs from page templates because the ``#source-rail`` target element no
longer exists on any page after Task 8's redirect.

These tests use:
  - Source-text checks (fastest, no render needed) to prove the attrs are gone.
  - render_partial renders for templates with data, to confirm the rendered
    output is also clean.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Source-text checks (grep-equivalent, no render)
# ---------------------------------------------------------------------------


def _template_text(relpath: str) -> str:
    return (PROJECT_ROOT / "src/docket/web/templates" / relpath).read_text()


def test_city_html_no_dead_rail_hx_get():
    """city.html must not reference rail_meeting or #source-rail."""
    src = _template_text("city.html")
    assert "rail_meeting" not in src, "city.html still references rail_meeting"
    assert 'hx-target="#source-rail"' not in src, (
        "city.html still has hx-target=#source-rail"
    )


def test_meetings_html_no_dead_rail_hx_get():
    """meetings.html must not reference rail_meeting or #source-rail."""
    src = _template_text("meetings.html")
    assert "rail_meeting" not in src, "meetings.html still references rail_meeting"
    assert 'hx-target="#source-rail"' not in src, (
        "meetings.html still has hx-target=#source-rail"
    )


def test_search_html_no_dead_rail_hx_get():
    """search.html must not reference rail_meeting or #source-rail."""
    src = _template_text("search.html")
    assert "rail_meeting" not in src, "search.html still references rail_meeting"
    assert 'hx-target="#source-rail"' not in src, (
        "search.html still has hx-target=#source-rail"
    )


def test_topic_detail_html_no_dead_rail_hx_get():
    """topic_detail.html must not reference rail_meeting or #source-rail."""
    src = _template_text("topic_detail.html")
    assert "rail_meeting" not in src, "topic_detail.html still references rail_meeting"
    assert 'hx-target="#source-rail"' not in src, (
        "topic_detail.html still has hx-target=#source-rail"
    )


def test_council_card_no_dead_rail_hx_get():
    """council_card.html must not reference rail_member or #source-rail."""
    src = _template_text("partials/council_card.html")
    assert "rail_member" not in src, (
        "council_card.html still references rail_member"
    )
    assert 'hx-target="#source-rail"' not in src, (
        "council_card.html still has hx-target=#source-rail"
    )


def test_council_card_still_has_button_type_button():
    """council_card.html button must keep type='button' (Task 7 contract)."""
    src = _template_text("partials/council_card.html")
    assert '<button class="cc" type="button">' in src, (
        "council_card.html button element or type='button' missing"
    )


def test_meeting_detail_no_rail_include():
    """meeting_detail.html must not include rail_meeting.html anymore."""
    src = _template_text("meeting_detail.html")
    assert 'rail_meeting.html' not in src, (
        "meeting_detail.html still includes rail_meeting.html"
    )


# ---------------------------------------------------------------------------
# Render checks — confirm rendered output is also clean
# ---------------------------------------------------------------------------


def _make_municipality(**overrides):
    defaults = dict(
        slug="birmingham",
        name="Birmingham",
        state="AL",
        county="Jefferson",
        council_type="City Council",
        adapter_class="GranicusAdapter",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _sample_city_stats():
    """Minimal city_stats dict required by kpi_strip.html (P3 top-of-overview)."""
    return SimpleNamespace(
        meetings_ytd=42,
        dollars_ytd_formatted="$1.4M",
        flagged_count=7,
    )


def _make_meeting(id=1, title="City Council Regular Meeting"):
    return SimpleNamespace(
        id=id,
        title=title,
        meeting_date=datetime.date(2026, 5, 1),
        meeting_type="Regular",
        agenda_url=None,
        minutes_url=None,
        video_url=None,
        source_url=None,
        municipality_name="Birmingham",
        municipality_slug="birmingham",
    )


def test_city_html_rendered_no_rail_refs(render_partial):
    """Rendered city.html must not emit rail_meeting or #source-rail."""
    muni = _make_municipality()
    m = _make_meeting()
    html = render_partial(
        "city.html",
        municipality=muni,
        meetings=[m],
        meeting_count=1,
        topics=[],
        members=[],
        recent_meetings=[m],
        upcoming_meetings=[],
        notable_items=[],
        contested_votes=[],
        recent_votes=[],
        stats={},
        city_policy_badges=[],
        process_badges=[],
        now=datetime.datetime.now(),
        coverage_counts={},
        kpi_stats=[],
        city_stats=_sample_city_stats(),
    )
    assert "rail_meeting" not in html, "Rendered city.html emits rail_meeting"
    assert 'hx-target="#source-rail"' not in html, (
        "Rendered city.html emits hx-target=#source-rail"
    )


def test_meetings_html_rendered_no_rail_refs(render_partial):
    """Rendered meetings.html must not emit rail_meeting or #source-rail."""
    muni = _make_municipality()
    m = _make_meeting()
    html = render_partial(
        "meetings.html",
        municipality=muni,
        meetings=[m],
        meeting_count=1,
        year_filter=None,
        available_years=[2026],
    )
    assert "rail_meeting" not in html, "Rendered meetings.html emits rail_meeting"
    assert 'hx-target="#source-rail"' not in html, (
        "Rendered meetings.html emits hx-target=#source-rail"
    )


def test_city_html_recent_meetings_have_href(render_partial):
    """Recent meetings in city.html must have an <a href> to meeting_detail."""
    muni = _make_municipality()
    m = _make_meeting(id=42)
    html = render_partial(
        "city.html",
        municipality=muni,
        meetings=[m],
        meeting_count=1,
        topics=[],
        members=[],
        recent_meetings=[m],
        upcoming_meetings=[],
        notable_items=[],
        contested_votes=[],
        recent_votes=[],
        stats={},
        city_policy_badges=[],
        process_badges=[],
        now=datetime.datetime.now(),
        coverage_counts={},
        kpi_stats=[],
        city_stats=_sample_city_stats(),
    )
    # The feed-row should link to meeting_detail
    assert "/al/birmingham/meetings/42/" in html, (
        "Recent meetings feed-row has no link to meeting_detail"
    )


def test_deleted_rail_routes_return_404(client):
    """rail_default / rail_meeting / rail_member view functions were
    deleted in Task 10 (P2b). Their URL bindings must 404 now."""
    paths = [
        "/al/birmingham/_rail/default",
        "/al/birmingham/_rail/meeting/1",
        "/al/birmingham/_rail/member/1",
    ]
    for path in paths:
        resp = client.get(path)
        assert resp.status_code == 404, (
            f"{path} returned {resp.status_code}, expected 404"
        )
