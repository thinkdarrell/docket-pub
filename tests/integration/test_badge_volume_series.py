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
                       confidence, source)
                    VALUES (%s, %s, %s, %s, %s, 'deterministic')
                    """,
                    (item_id, self.city_id, badge_slug, kind, confidence),
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


def test_route_renders_svg_with_term_band_and_title(bag, client):
    """End-to-end: GET the category landing page with seeded data —
    response must include the SVG, a mayoral term-overlay rect, and at
    least one <title> tooltip (substantive bar). Also asserts the
    fix-up structure: column-wide hit-area rect carries the <title>,
    visible segment rects carry aria-hidden="true" (S4).
    """
    yr = date.today().year
    m = bag.add_meeting(f"{yr}-04-15")
    item = bag.add_item(
        m, title="Demo render", dollars_amount=12_345, is_consent=False,
    )
    bag.add_badge(item, "blight_accountability")
    _refresh_mv()

    rv = client.get(f"/al/{bag.city_slug}/blight_accountability/")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert '<svg viewBox="0 0 800 200"' in body
    assert "term-overlay--D" in body, "expected BHM Democrat overlay band"
    assert "<title>" in body, "expected at least one tooltip on a bar"
    # Citizen-facing legend copy from the partial.
    assert "Each bar is one month" in body
    # F2 placeholder copy must NOT appear — F3 replaced it.
    assert "Visualizations coming soon" not in body

    # S4 — the fix-up moves the <title> to a column-wide hit-area rect
    # and aria-hides the visible segments. There must be at least one
    # hit-area rect and at least one aria-hidden segment.
    assert 'class="volume-bar--hit"' in body, (
        "expected column-wide hit-area rect (R1 fix-up)"
    )
    assert 'class="volume-bar volume-bar--substantive"' in body
    assert 'aria-hidden="true"' in body, (
        "visible segment rects must be aria-hidden after R1 fix-up"
    )

    # S2 — structural counts. We rendered exactly 60 monthly buckets
    # in the 5-year window (current_year-4 .. current_year), so we
    # expect exactly 60 hit-area rects regardless of how many months
    # actually have data.
    assert body.count('class="volume-bar--hit"') == 60, (
        "every bucket (including empty months) must emit a hit-area rect"
    )
    # Year-tick labels: one per calendar year in the 5-year window.
    assert body.count('class="axis-label"') == 5

    # The hit-area's <title> for the seeded April month must be
    # substring-correct (period prefix + counts).
    expected_title_substr = (
        f"{yr}-04-01: 1 total (0 on consent, 1 substantive)"
    )
    assert expected_title_substr in body, (
        f"hit-area <title> for April should contain {expected_title_substr!r}"
    )

    # Mayoral overlay claim only renders when mayoral_terms is non-empty.
    assert "Background bands show which mayor presided" in body, (
        "BHM seeds mayoral_terms — claim should render"
    )


def test_route_mixed_month_emits_three_rects_and_full_title(bag, client):
    """S1 + S5 — seed a mixed month (1 substantive + 1 consent in the
    same bucket). Exactly THREE rects are emitted for that bucket
    (substantive + consent + hit-area), in that DOM order, and the
    hit-area <title> carries period + n_items + n_consent +
    n_substantive + total_dollars.
    """
    yr = date.today().year
    m = bag.add_meeting(f"{yr}-05-15")
    sub_item = bag.add_item(
        m, title="Mixed-substantive", dollars_amount=12_000, is_consent=False,
    )
    con_item = bag.add_item(
        m, title="Mixed-consent", dollars_amount=8_000, is_consent=True,
    )
    bag.add_badge(sub_item, "blight_accountability")
    bag.add_badge(con_item, "blight_accountability")
    _refresh_mv()

    rv = client.get(f"/al/{bag.city_slug}/blight_accountability/")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)

    # The May bucket must have all three rect classes present.
    assert 'class="volume-bar volume-bar--substantive"' in body
    assert 'class="volume-bar volume-bar--consent"' in body
    assert 'class="volume-bar--hit"' in body

    # Hit-area <title>: full data summary including total_dollars.
    expected = (
        f"{yr}-05-01: 2 total (1 on consent, 1 substantive), $20,000"
    )
    assert expected in body, (
        f"mixed-month hit-area <title> should contain {expected!r}"
    )

    # S5 — DOM order: for the May bucket, the substantive rect must
    # appear before the consent rect, which must appear before the
    # hit-area rect. The hit-area going LAST is what makes SVG paint
    # stacking (and pointer-events="all") work.
    #
    # Use a regex tolerant of Jinja whitespace — class and data-period
    # land on adjacent lines in the rendered output.
    import re
    period_attr = f'data-period="{yr}-05-01"'
    assert period_attr in body, (
        "May bucket should carry data-period attribute"
    )
    rect_pattern = re.compile(
        r'class="(volume-bar--hit|volume-bar volume-bar--substantive|'
        r'volume-bar volume-bar--consent)"\s+data-period="' + re.escape(f"{yr}-05-01") + '"'
    )
    matches = [(m.start(), m.group(1)) for m in rect_pattern.finditer(body)]
    classes_in_order = [cls for _, cls in matches]
    assert "volume-bar volume-bar--substantive" in classes_in_order, (
        "substantive segment for May not rendered"
    )
    assert "volume-bar volume-bar--consent" in classes_in_order, (
        "consent segment for May not rendered"
    )
    assert "volume-bar--hit" in classes_in_order, (
        "hit-area for May not rendered"
    )
    expected_order = [
        "volume-bar volume-bar--substantive",
        "volume-bar volume-bar--consent",
        "volume-bar--hit",
    ]
    assert classes_in_order == expected_order, (
        "DOM order for May rects must be substantive → consent → "
        f"hit-area, got {classes_in_order!r}"
    )


def test_route_renders_empty_state_when_no_data(bag, client):
    """Page with zero items in the window still renders — the partial's
    empty-state branch must fire instead of an empty SVG. No internal
    pipeline jargon (no "Wave 0", "Track 1", "MV", etc.)."""
    rv = client.get(f"/al/{bag.city_slug}/blight_accountability/")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "No volume data yet for this category" in body
    for jargon in ("mv_badge_volume_monthly", "MV", "Wave 0",
                   "Track 1", "matchers", "backfill"):
        assert jargon not in body, (
            f"public empty state contains internal jargon {jargon!r}"
        )
