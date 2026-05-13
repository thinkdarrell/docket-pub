"""Renders partials/volume_timeline.html with stub data; asserts the
new structural elements (centered title, tally band, backfill banner,
hatched empties, clickable bars, peak callout).
"""
from __future__ import annotations

import datetime

import pytest
from bs4 import BeautifulSoup
from flask import Flask, render_template

from docket.web.filters import register as register_filters


@pytest.fixture(scope="module")
def app():
    flask_app = Flask("test_volume_timeline", template_folder="src/docket/web/templates")
    register_filters(flask_app)
    flask_app.add_url_rule(
        "/al/<slug>/<badge_slug>/",
        endpoint="public.category_landing",
        view_func=lambda slug, badge_slug: "",
    )
    return flask_app


def _stub_context(**overrides):
    """Five years of timeline points: 54 empty + 6 with data."""
    points = []
    months_with_data = {"2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04"}
    counts = {"2025-11": 8, "2025-12": 11, "2026-01": 9, "2026-02": 14, "2026-03": 15, "2026-04": 18}
    # Build 60 distinct YYYY-MM strings by walking month-by-month from
    # 2021-05 → 2026-04 (5 years). datetime.timedelta(days=31) drifts;
    # iterate by month index instead so each point is a unique YM.
    base_year, base_month = 2021, 5
    for i in range(60):
        m = base_month + i
        year = base_year + (m - 1) // 12
        month = ((m - 1) % 12) + 1
        ym = f"{year:04d}-{month:02d}"
        n = counts.get(ym, 0)
        points.append({
            "period": ym,
            "x": i * 13,
            "y_substantive": 140,
            "height_substantive": 0,
            "y_consent": 140 - n * 5,
            "height_consent": n * 5,
            "hit_x": i * 13,
            "hit_y": 20,
            "hit_width": 12,
            "hit_height": 120,
            "width": 12,
            "n_items": n,
            "n_consent": n,
            "n_substantive": 0,
            "total_dollars": 0,
        })
    base = {
        "badge": {
            "name": "Hidden on consent",
            "slug": "hidden_on_consent",
            "chart_title": "Items the AI flagged as hidden on consent",
            "chart_footnote": "This badge filters to consent-agenda items by design; bars show consent volume only.",
            "all_consent": True,
        },
        "timeline": points,
        "tally": {
            "indexed_count": 75,
            "indexed_months": 6,
            "total_dollars": 15_900_000,
            "peak_month": {"year_month": "2026-04", "items": 18, "dollars": 4_200_000},
        },
        "backfill_ratio": 0.018,
        "year_ticks": [
            {"year": 2022, "x": 65},
            {"year": 2023, "x": 220},
            {"year": 2024, "x": 375},
            {"year": 2025, "x": 530},
            {"year": 2026, "x": 700},
        ],
        "municipality": {"slug": "birmingham", "id": 1},
    }
    base.update(overrides)
    return base


def _render(app, **ctx):
    with app.test_request_context():
        return render_template("partials/volume_timeline.html", **ctx)


class TestVolumeTimeline:
    def test_centered_title_block_with_chart_title(self, app):
        html = _render(app, **_stub_context())
        soup = BeautifulSoup(html, "html.parser")
        title = soup.find(class_="title-block")
        assert title, "Centered .title-block must render"
        assert "Items the AI flagged as hidden on consent" in title.text

    def test_tally_band_renders_three_stats(self, app):
        html = _render(app, **_stub_context())
        soup = BeautifulSoup(html, "html.parser")
        band = soup.find(class_="tally-band")
        assert band
        tallies = band.find_all(class_="tally")
        assert len(tallies) == 3
        # Peak month renders as the third stat
        assert "April 2026" in tallies[2].text or "Apr 2026" in tallies[2].text

    def test_backfill_banner_at_low_threshold(self, app):
        ctx = _stub_context(backfill_ratio=0.018)
        html = _render(app, **ctx)
        assert "most of the historical record is still being indexed" in html

    def test_backfill_banner_mid_range_shows_percent(self, app):
        ctx = _stub_context(backfill_ratio=0.42)
        html = _render(app, **ctx)
        assert "42" in html  # 42.0% appears
        assert "Hatched months are still being indexed" in html

    def test_backfill_banner_hidden_when_complete(self, app):
        ctx = _stub_context(backfill_ratio=0.96)
        html = _render(app, **ctx)
        assert "still being indexed" not in html

    def test_hatched_empty_bars_render(self, app):
        html = _render(app, **_stub_context())
        soup = BeautifulSoup(html, "html.parser")
        empties = soup.find_all("rect", class_="bar-empty")
        # 54 months with 0 items → 54 hatched empties
        assert len(empties) == 54

    def test_filled_bars_wrap_in_anchor_with_aria_label(self, app):
        html = _render(app, **_stub_context())
        soup = BeautifulSoup(html, "html.parser")
        anchors = soup.find_all("a", attrs={"hx-get": True})
        assert len(anchors) >= 6
        for a in anchors:
            assert a.get("aria-label"), f"bar anchor missing aria-label: {a}"

    def test_peak_callout_renders(self, app):
        html = _render(app, **_stub_context())
        assert "Peak" in html

    def test_per_badge_footnote_when_provided(self, app):
        html = _render(app, **_stub_context())
        assert "consent-agenda items by design" in html

    def test_no_footnote_when_badge_has_none(self, app):
        ctx = _stub_context()
        ctx["badge"]["chart_footnote"] = None
        html = _render(app, **ctx)
        soup = BeautifulSoup(html, "html.parser")
        footnote = soup.find(class_="chart-footnote")
        assert footnote is None or not footnote.text.strip()
