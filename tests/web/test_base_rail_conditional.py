"""Verify rail is overview-only after P2b.

base.html now declares empty `block rail` and `block mobile_chrome`;
city.html overrides them to include source_rail + source_sheet.
bottom_tabs.html stays as an unconditional site-wide include — gating
it would trap mobile users on sub-pages.

These tests render templates directly (no live DB) to verify the
structural contract of the block override pattern.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from datetime import date as date_cls

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# base.html structural contract
# ---------------------------------------------------------------------------


def test_base_html_has_empty_rail_block():
    """base.html must declare `{% block rail %}{% endblock %}` (empty by
    default). The old unconditional <aside id="source-rail"> must be gone."""
    base_html = (PROJECT_ROOT / "src/docket/web/templates/base.html").read_text()
    # Must declare the rail block
    assert "{% block rail %}" in base_html, "base.html missing {% block rail %}"
    # Must NOT have the unconditional aside with source-rail ID
    assert 'id="source-rail"' not in base_html, (
        "base.html still has unconditional source-rail aside — "
        "should have moved to city.html override"
    )


def test_base_html_has_empty_mobile_chrome_block():
    """base.html must declare `{% block mobile_chrome %}{% endblock %}` (empty
    by default). The old unconditional source_sheet include must be gone."""
    base_html = (PROJECT_ROOT / "src/docket/web/templates/base.html").read_text()
    assert "{% block mobile_chrome %}" in base_html, (
        "base.html missing {% block mobile_chrome %}"
    )
    # source_sheet.html must NOT be unconditionally included in base.html
    assert 'source_sheet.html' not in base_html, (
        "base.html still has unconditional source_sheet include"
    )


def test_base_html_still_has_bottom_tabs():
    """bottom_tabs.html must remain unconditional in base.html —
    primary mobile nav must be site-wide."""
    base_html = (PROJECT_ROOT / "src/docket/web/templates/base.html").read_text()
    assert '{% include "partials/bottom_tabs.html" %}' in base_html, (
        "bottom_tabs.html was removed from base.html — it must stay site-wide"
    )


# ---------------------------------------------------------------------------
# city.html structural contract
# ---------------------------------------------------------------------------


def test_city_html_overrides_rail_block():
    """city.html must override `block rail` and include source_rail.html
    inside an <aside id='source-rail'> wrapper."""
    city_html = (PROJECT_ROOT / "src/docket/web/templates/city.html").read_text()
    assert "{% block rail %}" in city_html, "city.html missing {% block rail %} override"
    assert 'id="source-rail"' in city_html, (
        "city.html's rail block must contain <aside id='source-rail'>"
    )
    assert 'source_rail.html' in city_html, (
        "city.html must include partials/source_rail.html inside the rail block"
    )


def test_city_html_overrides_mobile_chrome_block():
    """city.html must override `block mobile_chrome` and include
    source_sheet.html."""
    city_html = (PROJECT_ROOT / "src/docket/web/templates/city.html").read_text()
    assert "{% block mobile_chrome %}" in city_html, (
        "city.html missing {% block mobile_chrome %} override"
    )
    assert 'source_sheet.html' in city_html, (
        "city.html mobile_chrome block must include source_sheet.html"
    )


# ---------------------------------------------------------------------------
# Template render: overview has rail, non-overview pages do not
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


def _sample_kpi_stats():
    return [
        {
            "label": "Meetings (lifetime)",
            "value": "1,003",
            "sub": "Since 2017",
            "sql_display": "SELECT count(*) FROM meetings WHERE municipality_id = 1",
        },
        {
            "label": "Agenda items YTD",
            "value": "14,212",
            "sub": None,
            "sql_display": "SELECT count(*) FROM agenda_items ai JOIN meetings m ...",
        },
        {
            "label": "Votes YTD",
            "value": "892",
            "sub": None,
            "sql_display": "SELECT count(*) FROM votes v JOIN meetings m ...",
        },
        {
            "label": "Dollars (pending / settled)",
            "value": "$48.2M / $112.0M",
            "sub": None,
            "sql_display": "SELECT sum(dollars_amount) FILTER ... FROM agenda_items ...",
        },
    ]


def test_overview_renders_source_rail(render_partial):
    """city.html rendered via render_partial contains the source rail
    with KPI explainer stack when kpi_stats is provided."""
    muni = _make_municipality()
    html = render_partial(
        "city.html",
        municipality=muni,
        meetings=[],
        meeting_count=1003,
        topics=[],
        members=[],
        recent_meetings=[],
        upcoming_meetings=[],
        notable_items=[],
        contested_votes=[],
        recent_votes=[],
        stats={},
        city_policy_badges=[],
        process_badges=[],
        now=__import__("datetime").datetime.now(),
        coverage_counts={},
        kpi_stats=_sample_kpi_stats(),
    )
    assert 'id="source-rail"' in html, "source-rail aside not rendered in city.html"
    assert "source-rail-kpis" in html, "kpi_stats not rendered into rail (missing source-rail-kpis)"
    assert "Meetings (lifetime)" in html
    assert "Agenda items YTD" in html


def test_overview_renders_source_sheet_mobile_chrome(render_partial):
    """city.html renders source_sheet (mobile chrome) inside mobile_chrome block.

    source_sheet.html renders a <dialog id="source-sheet"> — that specific
    element is the gate. The masthead also uses 'source-sheet-*' prefixed
    class names for its mobile menu, so we check for the dialog ID specifically.
    """
    muni = _make_municipality()
    html = render_partial(
        "city.html",
        municipality=muni,
        meetings=[],
        meeting_count=0,
        topics=[],
        members=[],
        recent_meetings=[],
        upcoming_meetings=[],
        notable_items=[],
        contested_votes=[],
        recent_votes=[],
        stats={},
        city_policy_badges=[],
        process_badges=[],
        now=__import__("datetime").datetime.now(),
        coverage_counts={},
        kpi_stats=[],
    )
    # source_sheet renders a <dialog id="source-sheet"> (see source_sheet.html).
    # Note: masthead also uses `source-sheet-*` class prefixes for its mobile
    # menu — check for the dialog ID specifically, not class substring.
    assert 'id="source-sheet"' in html, (
        "city.html should render source_sheet dialog (id='source-sheet') via mobile_chrome block"
    )


def test_overview_has_bottom_tabs(render_partial):
    """city.html inherits bottom_tabs from base.html (unconditional)."""
    muni = _make_municipality()
    html = render_partial(
        "city.html",
        municipality=muni,
        meetings=[],
        meeting_count=0,
        topics=[],
        members=[],
        recent_meetings=[],
        upcoming_meetings=[],
        notable_items=[],
        contested_votes=[],
        recent_votes=[],
        stats={},
        city_policy_badges=[],
        process_badges=[],
        now=__import__("datetime").datetime.now(),
        coverage_counts={},
        kpi_stats=[],
    )
    assert 'class="bottom-tabs"' in html, (
        "bottom_tabs must be site-wide — should appear in city.html via base.html include"
    )


def test_non_city_template_has_no_source_rail(render_partial):
    """A non-city template (e.g. a bare base.html render) must NOT have
    id='source-rail' — the block rail override is city-only."""
    # Render base.html with content block only — no rail override
    # We use a minimal template that just extends base.html to verify
    # the empty default blocks produce no rail markup.
    # Since we can't render base.html directly without a child, we
    # check base.html source text instead (already done above).
    # Here we verify source_rail.html itself doesn't self-render the aside:
    from pathlib import Path
    source_rail_text = (PROJECT_ROOT / "src/docket/web/templates/partials/source_rail.html").read_text()
    # source_rail.html should NOT wrap itself in an aside — city.html does that
    assert 'id="source-rail"' not in source_rail_text, (
        "source_rail.html must not contain id='source-rail' — "
        "the aside wrapper belongs in city.html's rail block override"
    )
