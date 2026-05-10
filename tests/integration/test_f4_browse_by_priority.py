"""Integration tests for F4 — cross-filter HTMX dropdown + Browse-by-
Priority homepage section + badge legend.

Three deliverables under test:

- F4.1: HTMX cross-filter ``<select>`` on category landing page
  (spec §6.8). Pre-selection of active filters, hx-target match on
  ``#item-list``, hx-push-url, options exclude the current badge.
- F4.2: Browse-by-Priority section on city.html (spec §6.7). Two
  grids — 4 BHM policy tiles ("this year") + 7 process tiles ("last
  30 days"). Each tile shows icon + name + count and links to the
  category landing page.
- F4.3: Badge legend on city.html (decision #74). Citizen-facing copy,
  no internal jargon.

Plus the new query helpers: ``badge_volume_year``, ``badge_volume_recent``,
``list_city_policy_badges``, ``list_process_badges``, ``list_enabled_badges``.

Reuses the ``_Bag`` test-data tracker pattern from the F2 file —
inserts via ``db()`` (commits), tracks ids, cleans up on fixture
teardown. The Flask test client is built per-module from
``create_app()``.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from docket.config import DATABASE_URL
from docket.db import db
from docket.migrations.runner import apply_migrations
from docket.services.query import (
    badge_volume_recent,
    badge_volume_year,
    list_city_policy_badges,
    list_enabled_badges,
    list_process_badges,
)
from docket.web import create_app
from docket.web import public as public_module


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run F4 tests against Railway DB.",
)


# ---------------------------------------------------------------------------
# Test data tracker — same shape as test_category_landing.py's _Bag, kept
# local so the two files don't have to share a conftest just for this.
# ---------------------------------------------------------------------------


class _Bag:
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
        processing_status: str = "completed",
    ) -> int:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agenda_items
                      (meeting_id, title, significance_score, dollars_amount,
                       processing_status)
                    VALUES (%s, %s, %s, %s,
                            %s::processing_status_enum)
                    RETURNING id
                    """,
                    (meeting_id, title, significance_score, dollars_amount,
                     processing_status),
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
                row = cur.fetchone()
                assert row is not None, f"unknown template {badge_slug}"
                kind = row[0]
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


@pytest.fixture
def bag():
    with db() as conn:
        apply_migrations(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, slug FROM municipalities WHERE slug = 'birmingham'"
            )
            row = cur.fetchone()
            assert row is not None, "Birmingham must be seeded"
            city_id, city_slug = row[0], row[1]
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
    # Bust the city_overview module-level cache before each test so a
    # cached HTML body from a previous test doesn't mask the data we're
    # asserting against. This is integration-test infrastructure — the
    # cache itself is correct in production where seed data doesn't
    # mutate within a 5-min window.
    public_module._overview_cache.clear()
    return app.test_client()


# ---------------------------------------------------------------------------
# F4 — query helpers
# ---------------------------------------------------------------------------


def test_badge_volume_year_counts_only_target_year(bag):
    yr = date.today().year
    in_yr = bag.add_meeting(f"{yr}-04-15")
    last_yr = bag.add_meeting(f"{yr - 1}-12-30")
    a = bag.add_item(in_yr, title="A", significance_score=5)
    b = bag.add_item(in_yr, title="B", significance_score=5)
    c = bag.add_item(last_yr, title="C", significance_score=5)
    for i in (a, b, c):
        bag.add_badge(i, "blight_accountability", confidence=1.0)

    assert badge_volume_year(bag.city_id, "blight_accountability", year=yr) == 2
    assert (
        badge_volume_year(bag.city_id, "blight_accountability", year=yr - 1)
        == 1
    )


def test_badge_volume_year_default_uses_current_year(bag):
    yr = date.today().year
    m = bag.add_meeting(f"{yr}-04-15")
    iid = bag.add_item(m, title="Default-year", significance_score=5)
    bag.add_badge(iid, "blight_accountability", confidence=1.0)

    # Calling without year arg should default to this year.
    assert badge_volume_year(bag.city_id, "blight_accountability") == 1


def test_badge_volume_year_respects_significance_gate(bag):
    """Policy badge with min_significance=3 — sig=2 items must NOT count."""
    yr = date.today().year
    m = bag.add_meeting(f"{yr}-04-15")
    high = bag.add_item(m, title="High", significance_score=5)
    low = bag.add_item(m, title="Low", significance_score=2)
    bag.add_badge(high, "blight_accountability", confidence=1.0)
    bag.add_badge(low, "blight_accountability", confidence=1.0)

    assert badge_volume_year(bag.city_id, "blight_accountability", year=yr) == 1


def test_badge_volume_year_excludes_low_confidence_and_pending(bag):
    yr = date.today().year
    m = bag.add_meeting(f"{yr}-04-15")
    ok = bag.add_item(m, title="ok", significance_score=5)
    low_conf = bag.add_item(m, title="lowc", significance_score=5)
    pending = bag.add_item(
        m, title="pending", significance_score=5,
        processing_status="pending",
    )
    bag.add_badge(ok, "blight_accountability", confidence=1.0)
    bag.add_badge(low_conf, "blight_accountability", confidence=0.4)
    bag.add_badge(pending, "blight_accountability", confidence=1.0)

    assert badge_volume_year(bag.city_id, "blight_accountability", year=yr) == 1


def test_badge_volume_recent_30_day_boundary(bag):
    """Verify the 30-day window: meeting on day 29, 30, 31, 32 prior.

    SQL uses ``meeting_date >= CURRENT_DATE - 30 * INTERVAL '1 day'``.
    Today and 30 days ago inclusive (31 calendar days). Items on day 31
    or older must be excluded.
    """
    today = date.today()
    # Use process badge so no significance gate.
    d29 = bag.add_meeting((today - timedelta(days=29)).isoformat())
    d30 = bag.add_meeting((today - timedelta(days=30)).isoformat())
    d31 = bag.add_meeting((today - timedelta(days=31)).isoformat())

    for m in (d29, d30, d31):
        iid = bag.add_item(m, title=f"Item-d{m}", significance_score=5)
        bag.add_badge(iid, "hidden_on_consent", confidence=1.0)

    n = badge_volume_recent(bag.city_id, "hidden_on_consent", days=30)
    # Inclusive bound: day 29 and day 30 in, day 31 out.
    assert n == 2


def test_badge_volume_recent_excludes_old_items(bag):
    today = date.today()
    old = bag.add_meeting((today - timedelta(days=400)).isoformat())
    iid = bag.add_item(old, title="ancient", significance_score=5)
    bag.add_badge(iid, "hidden_on_consent", confidence=1.0)
    assert badge_volume_recent(bag.city_id, "hidden_on_consent", days=30) == 0


def test_list_city_policy_badges_returns_bhm_seeded_four(bag):
    """Migration 013 seeds BHM into all 4 policy badges."""
    out = list_city_policy_badges(bag.city_id)
    slugs = {b["slug"] for b in out}
    assert slugs == {
        "blight_accountability",
        "housing_stability",
        "property_recovery",
        "public_safety_tech_privacy",
    }
    # Each carries the rendering keys.
    for b in out:
        assert b["name"]
        assert b["icon"]
        assert b["kind"] == "policy"
        assert "description" in b


def test_list_process_badges_returns_seven_in_alarm_order(bag):
    out = list_process_badges()
    assert len(out) == 7
    expected_order = [
        "hidden_on_consent",
        "legal_settlement",
        "contested",
        "sole_source",
        "emergency_action",
        "split_vote",
        "amends_prior_contract",
    ]
    assert [b["slug"] for b in out] == expected_order
    for b in out:
        assert b["kind"] == "process"
        assert b["icon"]
        assert b["name"]


def test_list_enabled_badges_combines_policy_and_process(bag):
    out = list_enabled_badges(bag.city_id)
    slugs = [b["slug"] for b in out]
    # 4 BHM policy + 7 process = 11.
    assert len(out) == 11
    # Process before policy.
    process_idx = [i for i, b in enumerate(out) if b["kind"] == "process"]
    policy_idx = [i for i, b in enumerate(out) if b["kind"] == "policy"]
    assert max(process_idx) < min(policy_idx)
    # Process alarm-order preserved.
    process_slugs = [s for s in slugs if s in {
        "hidden_on_consent", "legal_settlement", "contested",
        "sole_source", "emergency_action", "split_vote",
        "amends_prior_contract",
    }]
    assert process_slugs[0] == "hidden_on_consent"
    assert process_slugs[-1] == "amends_prior_contract"


# ---------------------------------------------------------------------------
# F4.1 — HTMX cross-filter dropdown on category_landing.html
# ---------------------------------------------------------------------------


def test_dropdown_present_with_htmx_attrs(bag, client):
    rv = client.get(f"/al/{bag.city_slug}/blight_accountability/")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)

    # Required HTMX wiring per spec §6.8.
    assert 'name="and"' in body
    assert 'class="cross-filter"' in body
    assert 'hx-target="#item-list"' in body
    assert 'hx-push-url="true"' in body
    assert 'hx-trigger="change"' in body


def test_item_list_section_has_swap_target_id(bag, client):
    """``#item-list`` is the hx-target for the dropdown — the page must
    expose that id on the items section.
    """
    rv = client.get(f"/al/{bag.city_slug}/blight_accountability/")
    assert rv.status_code == 200
    assert 'id="item-list"' in rv.get_data(as_text=True)


def test_dropdown_options_exclude_current_badge(bag, client):
    """Dropdown options should be every enabled badge minus the current
    one — citizens shouldn't see "filter by the badge you're on".
    """
    rv = client.get(f"/al/{bag.city_slug}/blight_accountability/")
    body = rv.get_data(as_text=True)
    # Other policy badge present as an <option>.
    assert 'value="housing_stability"' in body
    # Process badge present.
    assert 'value="hidden_on_consent"' in body
    # Current badge slug must NOT appear as an <option value>.
    # (It does appear elsewhere on the page — header, h1, etc. — so
    # we look specifically for the option-value form.)
    assert 'value="blight_accountability"' not in body


def test_dropdown_preselects_active_cross_filter(bag, client):
    import re
    rv = client.get(
        f"/al/{bag.city_slug}/blight_accountability/?and=hidden_on_consent"
    )
    body = rv.get_data(as_text=True)
    # Jinja renders ``<option value="hidden_on_consent"
    #                     selected>`` across two lines (template
    # indentation), so we use a whitespace-tolerant regex rather than
    # a strict-substring check.
    pattern = re.compile(
        r'value="hidden_on_consent"\s+selected', re.MULTILINE
    )
    assert pattern.search(body), (
        "expected hidden_on_consent option to be pre-selected"
    )
    # And the OTHER option (housing_stability) should NOT be pre-selected.
    other_pattern = re.compile(
        r'value="housing_stability"\s+selected', re.MULTILINE
    )
    assert not other_pattern.search(body), (
        "housing_stability should not be pre-selected"
    )


def test_dropdown_has_blank_default_option(bag, client):
    rv = client.get(f"/al/{bag.city_slug}/blight_accountability/")
    body = rv.get_data(as_text=True)
    # The "no filter" option should exist with empty value.
    assert 'value=""' in body
    assert "combine with another badge" in body.lower()


# ---------------------------------------------------------------------------
# F4.2 — Browse-by-Priority section on city.html
# ---------------------------------------------------------------------------


def test_city_homepage_has_browse_by_priority_section(client):
    rv = client.get("/al/birmingham/")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "browse-by-priority" in body
    assert "Browse by priority" in body


def test_city_homepage_renders_four_policy_tiles(client):
    rv = client.get("/al/birmingham/")
    body = rv.get_data(as_text=True)
    # Each BHM policy badge should have a link tile.
    for slug in ("blight_accountability", "housing_stability",
                 "property_recovery", "public_safety_tech_privacy"):
        assert f"/al/birmingham/{slug}/" in body, (
            f"policy tile link for {slug} missing"
        )


def test_city_homepage_renders_seven_process_tiles(client):
    rv = client.get("/al/birmingham/")
    body = rv.get_data(as_text=True)
    for slug in ("hidden_on_consent", "legal_settlement", "contested",
                 "sole_source", "emergency_action", "split_vote",
                 "amends_prior_contract"):
        assert f"/al/birmingham/{slug}/" in body, (
            f"process tile link for {slug} missing"
        )


def test_city_homepage_policy_tile_shows_count_with_year_label(bag, client):
    yr = date.today().year
    m = bag.add_meeting(f"{yr}-04-15")
    iid = bag.add_item(m, title="Counted-policy", significance_score=5)
    bag.add_badge(iid, "blight_accountability", confidence=1.0)

    rv = client.get("/al/birmingham/")
    body = rv.get_data(as_text=True)
    # The "this year" label is the marker that this is the policy grid.
    assert "this year" in body


def test_city_homepage_process_tile_shows_count_with_30day_label(bag, client):
    today = date.today()
    m = bag.add_meeting((today - timedelta(days=5)).isoformat())
    iid = bag.add_item(m, title="Counted-process", significance_score=5)
    bag.add_badge(iid, "hidden_on_consent", confidence=1.0)

    rv = client.get("/al/birmingham/")
    body = rv.get_data(as_text=True)
    assert "last 30 days" in body


# ---------------------------------------------------------------------------
# F4.3 — Badge legend on city.html
# ---------------------------------------------------------------------------


def test_city_homepage_has_badge_legend(client):
    rv = client.get("/al/birmingham/")
    body = rv.get_data(as_text=True)
    assert 'class="badge-legend' in body or 'class="badge-legend"' in body
    assert 'id="badge-legend"' in body


def test_badge_legend_explains_process_and_policy(client):
    rv = client.get("/al/birmingham/")
    body = rv.get_data(as_text=True)
    # Both kinds named in citizen vocabulary.
    assert "process" in body.lower()
    assert "policy" in body.lower()
    # Verification Spark callout — the ✨ emoji must appear in the
    # legend region (it appears elsewhere in the page too, so this is
    # a soft check).
    assert "✨" in body


def test_badge_legend_has_no_internal_jargon(client):
    """R2-style guard: legend must not surface pipeline vocabulary."""
    rv = client.get("/al/birmingham/")
    body = rv.get_data(as_text=True)
    # Pull the legend region and only check that.
    start = body.find('id="badge-legend"')
    assert start != -1
    end = body.find("</p>", start)
    legend_region = body[start:end]
    for jargon in ("Wave 0", "Track 1", "D2", "matchers", "backfill",
                   "Stage 0", "matcher_hints", "v3"):
        assert jargon not in legend_region, (
            f"legend contains internal jargon {jargon!r}"
        )
