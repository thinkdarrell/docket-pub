"""Integration tests for the F3 volume-timeline helpers.

Covers:

- ``query.badge_volume_series`` — returns dense month series with
  per-bucket counts + render-time SVG geometry, against rows in
  ``mv_badge_volume_monthly``.
- 5-year window boundary (decision #95): items in ``current_year - 5``
  excluded; items in ``current_year - 4`` included.
- Empty-series case: badge with zero items in the window returns a
  list of all-zero buckets (not ``[]``) so the SVG keeps consistent
  column spacing.
- ``bucket="week"`` raises ``NotImplementedError``.
- Render-field correctness: ``x`` increases monotonically, bar heights
  proportion the count, widths sum (within ±1px) to the plot area.
- ``query.mayoral_term_overlay`` — BHM term bands clipped to the
  visible window; positive widths only; party class normalized.
- ``query.year_ticks`` — one entry per calendar year in the window.
- Partial render: ``GET /al/birmingham/blight_accountability/`` against
  seeded data — SVG renders, contains a ``<title>`` element, contains
  a term-overlay rect.
- Empty-state path: timeline with zero data renders the empty-state
  copy, not a flat-line SVG.

Pattern mirrors ``tests/integration/test_category_landing.py`` — the
``_Bag`` fixture writes through ``db()`` (commits) and tears down by
id on exit. We refresh ``mv_badge_volume_monthly`` after seeding so
the MV reflects the test data.
"""

from __future__ import annotations

from datetime import date

import pytest

from docket.config import DATABASE_URL
from docket.db import db
from docket.migrations.runner import apply_migrations
from docket.services import query
from docket.services.query import (
    VOLUME_TIMELINE_PLOT_BOTTOM,
    VOLUME_TIMELINE_PLOT_HEIGHT,
    VOLUME_TIMELINE_PLOT_TOP,
    VOLUME_TIMELINE_WIDTH,
    badge_volume_series,
    mayoral_term_overlay,
    year_ticks,
)
from docket.web import create_app


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run F3 timeline tests against Railway DB.",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _refresh_mv() -> None:
    """Refresh mv_badge_volume_monthly so it reflects seeded test data."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("REFRESH MATERIALIZED VIEW mv_badge_volume_monthly")


class _Bag:
    """Reuses the F2 _Bag pattern. Inserts commit through db(); teardown
    deletes by id and refreshes the MV so the next test starts clean.
    """

    def __init__(self, city_id: int, city_slug: str):
        self.city_id = city_id
        self.city_slug = city_slug
        self.meeting_ids: list[int] = []
        self.item_ids: list[int] = []

    def add_meeting(self, meeting_date: str) -> int:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO meetings
                      (municipality_id, title, meeting_date, meeting_type)
                    VALUES (%s, 'Test meeting', %s, 'council')
                    RETURNING id
                    """,
                    (self.city_id, meeting_date),
                )
                mid = cur.fetchone()[0]
        self.meeting_ids.append(mid)
        return mid

    def add_item(
        self,
        meeting_id: int,
        *,
        title: str = "Test item",
        significance_score: float | None = 5,
        dollars_amount: float | None = None,
        is_consent: bool = False,
    ) -> int:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agenda_items
                      (meeting_id, title, significance_score,
                       dollars_amount, processing_status, is_consent)
                    VALUES (%s, %s, %s, %s,
                            'completed'::processing_status_enum, %s)
                    RETURNING id
                    """,
                    (meeting_id, title, significance_score,
                     dollars_amount, is_consent),
                )
                iid = cur.fetchone()[0]
        self.item_ids.append(iid)
        return iid

    def add_badge(
        self,
        item_id: int,
        badge_slug: str,
        *,
        confidence: float = 1.0,
        source: str = "deterministic",
        status: str = "applied",
    ) -> None:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT kind FROM priority_badge_templates WHERE slug = %s",
                    (badge_slug,),
                )
                kind = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO agenda_item_badges
                      (agenda_item_id, city_id, badge_slug, kind,
                       confidence, source, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (item_id, self.city_id, badge_slug, kind, confidence, source, status),
                )

    def cleanup(self) -> None:
        with db() as conn:
            with conn.cursor() as cur:
                if self.item_ids:
                    cur.execute(
                        "DELETE FROM agenda_item_badges "
                        "WHERE agenda_item_id = ANY(%s)",
                        (self.item_ids,),
                    )
                    cur.execute(
                        "DELETE FROM agenda_items WHERE id = ANY(%s)",
                        (self.item_ids,),
                    )
                if self.meeting_ids:
                    cur.execute(
                        "DELETE FROM meetings WHERE id = ANY(%s)",
                        (self.meeting_ids,),
                    )
        # Drop the test rows out of the MV before the next test runs.
        _refresh_mv()


@pytest.fixture
def bag():
    with db() as conn:
        apply_migrations(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, slug FROM municipalities WHERE slug = 'birmingham'"
            )
            city_id, city_slug = cur.fetchone()

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
    return app.test_client()


# ---------------------------------------------------------------------------
# badge_volume_series — happy path + counts
# ---------------------------------------------------------------------------


def test_badge_volume_series_returns_seeded_counts(bag):
    """Seed three items in March (1 consent, 2 substantive) + one in
    April (substantive); confirm the MV-backed query reports them."""
    yr = date.today().year
    march = bag.add_meeting(f"{yr}-03-15")
    april = bag.add_meeting(f"{yr}-04-15")
    a = bag.add_item(march, title="A", dollars_amount=10_000)
    b = bag.add_item(march, title="B", dollars_amount=20_000)
    c = bag.add_item(march, title="C", dollars_amount=5_000, is_consent=True)
    d = bag.add_item(april, title="D", dollars_amount=99_000)
    for i in (a, b, c, d):
        bag.add_badge(i, "blight_accountability", confidence=1.0)
    _refresh_mv()

    series = badge_volume_series(
        bag.city_id, "blight_accountability",
        start_date=date(yr, 1, 1), end_date=date(yr, 12, 31),
    )
    # 12 buckets, all months present.
    assert len(series) == 12
    by_period = {row["period"]: row for row in series}
    march_row = by_period[date(yr, 3, 1)]
    april_row = by_period[date(yr, 4, 1)]
    assert march_row["n_items"] == 3
    assert march_row["n_consent"] == 1
    assert march_row["n_substantive"] == 2
    assert int(march_row["total_dollars"]) == 35_000
    assert april_row["n_items"] == 1
    assert april_row["n_consent"] == 0
    assert april_row["n_substantive"] == 1


def test_badge_volume_series_empty_window_returns_zero_buckets(bag):
    """A badge with no items in the window must still return one bucket
    per month — the SVG depends on dense column spacing. Zero counts
    are emitted; render fields stay zero."""
    series = badge_volume_series(
        bag.city_id, "blight_accountability",
        start_date=date(2030, 1, 1), end_date=date(2030, 6, 30),
    )
    assert len(series) == 6
    assert all(row["n_items"] == 0 for row in series)
    assert all(row["height_substantive"] == 0 for row in series)
    assert all(row["height_consent"] == 0 for row in series)


def test_badge_volume_series_5yr_window_boundary(bag):
    """Decision #95: 5-year window is (current_year-4, 1, 1) through
    (current_year, 12, 31). Items in current_year-5 must be excluded;
    items in current_year-4 must be included. Tests against the
    rolling window directly to pin the inclusion/exclusion semantics.
    """
    current_year = date.today().year
    win_start = date(current_year - 4, 1, 1)
    win_end = date(current_year, 12, 31)

    out_of_window = bag.add_meeting(f"{current_year - 5}-06-01")
    in_window_low = bag.add_meeting(f"{current_year - 4}-01-15")
    in_window_high = bag.add_meeting(f"{current_year}-11-30")

    out_item = bag.add_item(out_of_window, title="Old", dollars_amount=1)
    low_item = bag.add_item(in_window_low, title="Edge low", dollars_amount=2)
    high_item = bag.add_item(in_window_high, title="Edge high", dollars_amount=3)
    for i in (out_item, low_item, high_item):
        bag.add_badge(i, "blight_accountability")
    _refresh_mv()

    series = badge_volume_series(
        bag.city_id, "blight_accountability",
        start_date=win_start, end_date=win_end,
    )
    counted = sum(row["n_items"] for row in series)
    # 2 in-window items, 1 out-of-window must NOT contribute.
    assert counted == 2

    # Spot-check the boundary buckets.
    by_period = {row["period"]: row for row in series}
    assert by_period[date(current_year - 4, 1, 1)]["n_items"] == 1
    assert by_period[date(current_year, 11, 1)]["n_items"] == 1


def test_badge_volume_series_bucket_week_raises(bag):
    with pytest.raises(NotImplementedError):
        badge_volume_series(
            bag.city_id, "blight_accountability",
            start_date=date(2024, 1, 1), end_date=date(2024, 12, 31),
            bucket="week",
        )


def test_badge_volume_series_low_confidence_excluded(bag):
    """The MV's WHERE clause filters confidence < 0.6 — we shouldn't
    re-apply it in Python. Verify by seeding a low-confidence badge
    and asserting the row doesn't surface in the series."""
    yr = date.today().year
    m = bag.add_meeting(f"{yr}-06-15")
    item = bag.add_item(m, title="Low conf badge", dollars_amount=999_999)
    bag.add_badge(item, "blight_accountability", confidence=0.4)
    _refresh_mv()

    series = badge_volume_series(
        bag.city_id, "blight_accountability",
        start_date=date(yr, 1, 1), end_date=date(yr, 12, 31),
    )
    # All 12 buckets exist but none have data.
    assert sum(row["n_items"] for row in series) == 0


# ---------------------------------------------------------------------------
# badge_volume_series — render-field math
# ---------------------------------------------------------------------------


def test_badge_volume_series_x_monotonic_and_bounded(bag):
    """Render fields: x increases left-to-right, every bar fits inside
    the SVG viewBox (0..VOLUME_TIMELINE_WIDTH)."""
    yr = date.today().year
    series = badge_volume_series(
        bag.city_id, "blight_accountability",
        start_date=date(yr, 1, 1), end_date=date(yr, 12, 31),
    )
    xs = [row["x"] for row in series]
    assert xs == sorted(xs), "x must increase monotonically"
    for row in series:
        assert row["x"] >= 0
        assert row["x"] + row["width"] <= VOLUME_TIMELINE_WIDTH + 1e-6


def test_badge_volume_series_bar_heights_sum_correctly(bag):
    """For a non-zero bar, height_substantive + height_consent equals
    the total bar height. The split proportions match n_substantive /
    n_items.
    """
    yr = date.today().year
    m = bag.add_meeting(f"{yr}-04-10")
    items = []
    for i in range(8):
        consent = i < 6  # 6 consent, 2 substantive
        item = bag.add_item(
            m, title=f"H-{i}", dollars_amount=100, is_consent=consent
        )
        bag.add_badge(item, "blight_accountability")
        items.append(item)
    _refresh_mv()

    series = badge_volume_series(
        bag.city_id, "blight_accountability",
        start_date=date(yr, 1, 1), end_date=date(yr, 12, 31),
    )
    april = next(r for r in series if r["period"] == date(yr, 4, 1))
    # Tallest bar uses the full plot height (it's the only month with data).
    total_h = april["height_substantive"] + april["height_consent"]
    assert abs(total_h - VOLUME_TIMELINE_PLOT_HEIGHT) < 0.5

    # 2 of 8 substantive → ~25% of the bar height.
    expected_sub = (2 / 8) * VOLUME_TIMELINE_PLOT_HEIGHT
    assert abs(april["height_substantive"] - expected_sub) < 0.5

    # Substantive segment sits AT the baseline; consent stacks above it
    # (lighter shade is the upper portion per spec §6.6 line 3144).
    assert (
        april["y_substantive"] + april["height_substantive"]
        == pytest.approx(VOLUME_TIMELINE_PLOT_BOTTOM, abs=0.5)
    )
    assert (
        april["y_consent"] + april["height_consent"]
        == pytest.approx(april["y_substantive"], abs=0.5)
    )
    # Bars never spill above the plot top (term-label band reserved).
    assert april["y_consent"] >= VOLUME_TIMELINE_PLOT_TOP - 0.5


def test_badge_volume_series_widths_cover_plot_area(bag):
    """The dense-monthly series should occupy the full SVG width within
    a px or two of slack from the inter-bar gap."""
    yr = date.today().year
    series = badge_volume_series(
        bag.city_id, "blight_accountability",
        start_date=date(yr, 1, 1), end_date=date(yr, 12, 31),
    )
    rightmost = max(row["x"] + row["width"] for row in series)
    # Within 2px of the right edge — the small slack is the inter-bar gap.
    assert abs(rightmost - VOLUME_TIMELINE_WIDTH) < 3.0


# ---------------------------------------------------------------------------
# mayoral_term_overlay
# ---------------------------------------------------------------------------


def test_mayoral_term_overlay_returns_clipped_bands_for_bhm(bag):
    """Migration 013 seeds two BHM mayoral_terms rows (Bell, Woodfin).
    With a 5-year window covering the Woodfin term, both bands should
    surface — Bell clipped at term_end, Woodfin clipped at end_date."""
    current_year = date.today().year
    win_start = date(current_year - 4, 1, 1)
    win_end = date(current_year, 12, 31)
    bands = mayoral_term_overlay(bag.city_id, win_start, win_end)
    # All bands are positive-width and inside the viewBox.
    assert bands, "expected at least one mayoral term in the 5-year window"
    for band in bands:
        assert band["width"] > 0
        assert band["x_start"] >= 0
        assert band["x_start"] + band["width"] <= VOLUME_TIMELINE_WIDTH + 1e-6
        assert band["party"] in ("D", "R", "I")
    # Woodfin (current mayor) must be present.
    mayors = {b["mayor"] for b in bands}
    assert "Randall Woodfin" in mayors


def test_mayoral_term_overlay_empty_when_window_predates_terms(bag):
    """A window in 1900 contains zero overlap with seeded terms (which
    start in 2010). Helper returns an empty list, not None."""
    out = mayoral_term_overlay(
        bag.city_id, date(1900, 1, 1), date(1901, 1, 1)
    )
    assert out == []


def test_mayoral_term_overlay_normalizes_party(bag):
    """Migration 013 seeds party='Democrat'; the helper normalizes to
    'D' so the SVG class hook .term-overlay--D fires."""
    current_year = date.today().year
    bands = mayoral_term_overlay(
        bag.city_id,
        date(current_year - 4, 1, 1),
        date(current_year, 12, 31),
    )
    parties = {b["party"] for b in bands}
    assert parties.issubset({"D", "R", "I"})
    # BHM seeds are both Democrat.
    assert "D" in parties


# ---------------------------------------------------------------------------
# year_ticks
# ---------------------------------------------------------------------------


def test_year_ticks_one_per_year_in_window():
    ticks = year_ticks(date(2022, 1, 1), date(2026, 12, 31))
    assert [t["year"] for t in ticks] == [2022, 2023, 2024, 2025, 2026]
    # x increases monotonically.
    xs = [t["x"] for t in ticks]
    assert xs == sorted(xs)
    # All x-values are inside the viewBox.
    for t in ticks:
        assert 0 <= t["x"] <= VOLUME_TIMELINE_WIDTH


def test_year_ticks_handles_partial_year():
    """A window that starts mid-year must still produce a tick for that
    year — the midpoint sits inside the visible (partial) range, not at
    the year's calendar-midpoint."""
    ticks = year_ticks(date(2022, 7, 1), date(2026, 6, 30))
    years = [t["year"] for t in ticks]
    assert 2022 in years
    assert 2026 in years


def test_year_ticks_empty_when_end_before_start():
    assert year_ticks(date(2026, 1, 1), date(2025, 1, 1)) == []


# ---------------------------------------------------------------------------
# Route render integration
# ---------------------------------------------------------------------------


# NOTE: Three end-to-end route tests removed in PR D —
#   - test_route_renders_svg_with_term_band_and_title
#   - test_route_mixed_month_emits_three_rects_and_full_title
#   - test_route_renders_empty_state_when_no_data
# They asserted the OLD volume_timeline SVG structure (mayoral
# overlay term-overlay--D, three-rect-per-month with volume-bar--hit,
# axis-label) which the compact-scan redesign drops. New coverage:
#   - tests/unit/test_volume_timeline_template.py — partial-level
#     render contract (title block, tally band, hatched empties,
#     clickable filled bars with aria-label, peak callout, footnote).
#   - tests/integration/test_category_landing_month_filter.py — full
#     route round-trip including the ?month=YYYY-MM drill-down (PR D
#     Task 10).
# The empty-state-jargon coverage moved to
# test_category_landing.py::test_empty_state_has_no_internal_jargon.


def test_volume_series_excludes_flagged_badges(bag):
    """Refactor #2 (Section B / migration 022): the volume timeline MV
    filters status='applied' so flagged (admin-review-only) rows don't
    inflate n_items, n_consent, n_substantive, or total_dollars on
    citizen-facing surfaces."""
    from datetime import date

    m = bag.add_meeting("2026-04-15")
    applied = bag.add_item(m, title="Real blight item",
                           dollars_amount=50_000)
    flagged = bag.add_item(m, title="Mis-tagged blight item",
                           dollars_amount=50_000)
    bag.add_badge(applied, "blight_accountability",
                  confidence=1.0, status="applied")
    bag.add_badge(flagged, "blight_accountability",
                  confidence=0.4, source="llm", status="flagged")
    _refresh_mv()

    series = badge_volume_series(
        bag.city_id, "blight_accountability",
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 30),
    )
    april = [r for r in series if r["period"] == date(2026, 4, 1)][0]
    assert april["n_items"] == 1
    assert int(april["total_dollars"]) == 50_000
