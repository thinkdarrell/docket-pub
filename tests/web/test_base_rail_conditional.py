"""Verify page_sources renders on every page; KPI section only on overview.

P2b dropped the rail entirely in favor of a page-bottom 'page_sources'
block. Provenance (Platform / Adapter / Records + Source documents
links) renders on every page with a municipality in context. KPI
explainer stack renders only where the view function passes kpi_stats.

These tests render templates via ``render_partial`` (no live DB) to
verify the structural contract of the new page_sources pattern.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# base.html structural contract (source-text checks)
# ---------------------------------------------------------------------------


def test_base_html_has_page_sources_include():
    """base.html must include page_sources.html unconditionally between
    content and footer — replacing the old rail block pattern."""
    base_html = (PROJECT_ROOT / "src/docket/web/templates/base.html").read_text()
    assert '{% include "partials/page_sources.html" %}' in base_html, (
        "base.html must include page_sources.html"
    )


def test_base_html_no_rail_block():
    """base.html must NOT declare {% block rail %} — dropped in P2b."""
    base_html = (PROJECT_ROOT / "src/docket/web/templates/base.html").read_text()
    assert "{% block rail %}" not in base_html, (
        "base.html still has {% block rail %} — should be dropped in P2b"
    )


def test_base_html_no_mobile_chrome_block():
    """base.html must NOT declare {% block mobile_chrome %} — dropped in P2b."""
    base_html = (PROJECT_ROOT / "src/docket/web/templates/base.html").read_text()
    assert "{% block mobile_chrome %}" not in base_html, (
        "base.html still has {% block mobile_chrome %} — should be dropped in P2b"
    )


def test_base_html_still_has_bottom_tabs():
    """bottom_tabs.html must remain unconditional in base.html —
    primary mobile nav must be site-wide."""
    base_html = (PROJECT_ROOT / "src/docket/web/templates/base.html").read_text()
    assert '{% include "partials/bottom_tabs.html" %}' in base_html, (
        "bottom_tabs.html was removed from base.html — it must stay site-wide"
    )


# ---------------------------------------------------------------------------
# city.html structural contract (source-text checks)
# ---------------------------------------------------------------------------


def test_city_html_no_rail_block_override():
    """city.html must NOT override {% block rail %} — dropped in P2b."""
    city_html = (PROJECT_ROOT / "src/docket/web/templates/city.html").read_text()
    assert "{% block rail %}" not in city_html, (
        "city.html still has {% block rail %} override — should be removed in P2b"
    )


def test_city_html_no_source_sheet_include():
    """city.html must NOT include source_sheet.html — no rail to mirror."""
    city_html = (PROJECT_ROOT / "src/docket/web/templates/city.html").read_text()
    assert "source_sheet.html" not in city_html, (
        "city.html still includes source_sheet.html — should be retired in P2b"
    )


# ---------------------------------------------------------------------------
# page_sources.html partial render tests
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
            "label": "Meetings tracked",
            "value": "1,003",
            "sub": None,
        },
        {
            "label": "Agenda items YTD",
            "value": "14,212",
            "sub": None,
        },
    ]


def _sample_city_stats():
    """Minimal city_stats dict required by kpi_strip.html (P3 top-of-overview)."""
    from types import SimpleNamespace
    return SimpleNamespace(
        meetings_ytd=42,
        dollars_ytd_formatted="$1.4M",
        flagged_count=7,
    )


def test_page_sources_renders_provenance(render_partial):
    """page_sources.html renders the provenance block when municipality is in context."""
    muni = _make_municipality()
    html = render_partial(
        "partials/page_sources.html",
        municipality=muni,
        meeting_count=1003,
    )
    assert 'class="page-sources"' in html
    assert "SOURCE OF TRUTH" in html
    assert "Birmingham" in html
    assert "GranicusAdapter" in html
    assert "1003 meetings" in html


def test_page_sources_renders_kpi_stack_when_provided(render_partial):
    """page_sources.html renders the KPI explainer stack when kpi_stats is passed."""
    muni = _make_municipality()
    html = render_partial(
        "partials/page_sources.html",
        municipality=muni,
        meeting_count=1003,
        kpi_stats=_sample_kpi_stats(),
    )
    assert "page-sources-kpis" in html, "KPI section not rendered when kpi_stats provided"
    assert "Meetings tracked" in html
    assert "Agenda items YTD" in html


def test_page_sources_omits_kpi_stack_without_kpi_stats(render_partial):
    """page_sources.html hides KPI section when kpi_stats is absent (non-overview pages)."""
    muni = _make_municipality()
    html = render_partial(
        "partials/page_sources.html",
        municipality=muni,
        meeting_count=503,
    )
    assert "page-sources-kpis" not in html, (
        "KPI stack should be absent when kpi_stats not in context"
    )
    # Provenance block still renders
    assert "SOURCE OF TRUTH" in html


def test_page_sources_omits_block_when_no_municipality(render_partial):
    """page_sources.html renders nothing when municipality is absent (e.g. homepage)."""
    html = render_partial("partials/page_sources.html")
    # No municipality — entire aside should be absent
    assert 'class="page-sources"' not in html
    assert "SOURCE OF TRUTH" not in html


def test_city_html_page_sources_rendered_with_kpis(render_partial):
    """city.html inherits page_sources from base.html — overview context
    includes kpi_stats so the KPI grid appears."""
    import datetime
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
        now=datetime.datetime.now(),
        coverage_counts={},
        kpi_stats=_sample_kpi_stats(),
        city_stats=_sample_city_stats(),
    )
    assert 'class="page-sources"' in html, "page-sources block missing from city.html render"
    assert "SOURCE OF TRUTH" in html
    assert "page-sources-kpis" in html, "KPI stack missing when kpi_stats provided"
    # No rail
    assert 'id="source-rail"' not in html, "source-rail should be gone in P2b"
    assert 'class="app-rail"' not in html, "app-rail should be gone in P2b"


def test_city_html_no_source_sheet_rendered(render_partial):
    """city.html no longer renders source_sheet dialog — mobile_chrome block dropped."""
    import datetime
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
        now=datetime.datetime.now(),
        coverage_counts={},
        kpi_stats=[],
        city_stats=_sample_city_stats(),
    )
    assert 'id="source-sheet"' not in html, (
        "source_sheet dialog should not render — mobile_chrome block removed in P2b"
    )


def test_city_html_bottom_tabs_still_present(render_partial):
    """city.html inherits bottom_tabs from base.html — must remain unconditional."""
    import datetime
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
        now=datetime.datetime.now(),
        coverage_counts={},
        kpi_stats=[],
        city_stats=_sample_city_stats(),
    )
    assert 'class="bottom-tabs"' in html, (
        "bottom_tabs must be site-wide — should appear in city.html via base.html include"
    )
