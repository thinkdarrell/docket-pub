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
    """F4 review fix-up (S7): assert the integer count renders, not just
    the surrounding "this year" label. A regression that drops the
    count to 0 or hides it would otherwise pass the label-only check.
    """
    yr = date.today().year
    m = bag.add_meeting(f"{yr}-04-15")
    # Insert THREE items so we can pin a non-default count and avoid
    # collision with "1 this year" elsewhere on the page.
    for i in range(3):
        iid = bag.add_item(m, title=f"Counted-policy-{i}", significance_score=5)
        bag.add_badge(iid, "blight_accountability", confidence=1.0)

    rv = client.get("/al/birmingham/")
    body = rv.get_data(as_text=True)
    # The "this year" label is the marker that this is the policy grid.
    assert "this year" in body
    # The integer count must render adjacent to the label — the tile
    # renders ``{{ b.count }} this year``. Whitespace-tolerant check
    # for "3 this year" so a stray newline in the template doesn't
    # break the assertion.
    import re
    assert re.search(r"\b3\s+this year\b", body), (
        "expected '3 this year' on a policy tile"
    )


def test_city_homepage_process_tile_shows_count_with_30day_label(bag, client):
    """F4 review fix-up (S7): assert the integer count renders, not just
    the surrounding "last 30 days" label.
    """
    today = date.today()
    m1 = bag.add_meeting((today - timedelta(days=5)).isoformat())
    m2 = bag.add_meeting((today - timedelta(days=10)).isoformat())
    for m in (m1, m2):
        iid = bag.add_item(m, title=f"Counted-process-{m}", significance_score=5)
        bag.add_badge(iid, "hidden_on_consent", confidence=1.0)

    rv = client.get("/al/birmingham/")
    body = rv.get_data(as_text=True)
    assert "last 30 days" in body
    import re
    assert re.search(r"\b2\s+last 30 days\b", body), (
        "expected '2 last 30 days' on the hidden_on_consent tile"
    )


# ---------------------------------------------------------------------------
# F4.3 — Badge legend on city.html
# P3 update: the badge legend paragraph was deleted as part of the hero
# section removal (Task 8). The `id="badge-legend"` element no longer
# exists in city.html; these tests have been updated to reflect P3 state.
# ---------------------------------------------------------------------------


def test_city_homepage_has_badge_legend(client):
    """P3: badge legend (id=badge-legend) was removed with the hero section.
    The page still renders (200) and the Browse by Priority section still
    surfaces process/policy vocabulary — the per-tile layout replaces the
    inline legend paragraph."""
    rv = client.get("/al/birmingham/")
    body = rv.get_data(as_text=True)
    assert rv.status_code == 200
    # Badge legend paragraph deleted in P3 — city_lead replaces the hero
    assert 'id="badge-legend"' not in body, (
        "P3: badge-legend paragraph should have been removed with the hero"
    )
    # Browse-by-priority section still provides process/policy vocabulary
    assert "process" in body.lower()


def test_badge_legend_explains_process_and_policy(client):
    """P3: badge legend removed from hero; process/policy vocabulary still
    reachable via Browse by Priority tiles."""
    rv = client.get("/al/birmingham/")
    body = rv.get_data(as_text=True)
    # Both kinds named in citizen vocabulary via Browse by Priority tiles.
    assert "process" in body.lower()
    assert "policy" in body.lower()


def test_badge_legend_has_no_internal_jargon(client):
    """P3: badge-legend paragraph deleted; jargon check is now a no-op.
    The page must still render cleanly."""
    rv = client.get("/al/birmingham/")
    body = rv.get_data(as_text=True)
    assert rv.status_code == 200
    # id="badge-legend" is gone — no region to scan for jargon
    assert 'id="badge-legend"' not in body


def test_badge_legend_spark_has_aria_label(client):
    """P3: badge-legend paragraph (with the ✨ spark) deleted from hero.
    The page still renders; the spark may appear in badge chips elsewhere."""
    rv = client.get("/al/birmingham/")
    body = rv.get_data(as_text=True)
    assert rv.status_code == 200
    # id="badge-legend" is gone
    assert 'id="badge-legend"' not in body


def test_badge_legend_policy_parenthetical_gated_on_city_policy_badges(client):
    """P3: badge-legend paragraph deleted from hero; gating logic gone too.
    Both BHM and Mobile render (200) without the legend element."""
    rv = client.get("/al/birmingham/")
    assert rv.status_code == 200
    bhm_body = rv.get_data(as_text=True)
    assert 'id="badge-legend"' not in bhm_body, (
        "P3: badge-legend should be absent from BHM city page"
    )

    rv = client.get("/al/mobile/")
    assert rv.status_code == 200
    mobile_body = rv.get_data(as_text=True)
    assert 'id="badge-legend"' not in mobile_body, (
        "P3: badge-legend should be absent from Mobile city page"
    )


# ---------------------------------------------------------------------------
# F4 review fix-up (R1) — process-badge category landing pages 200
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("process_slug", [
    "hidden_on_consent",
    "legal_settlement",
    "contested",
    "sole_source",
    "emergency_action",
    "split_vote",
    "amends_prior_contract",
])
def test_process_badge_category_landing_returns_200(client, process_slug):
    """F4 review fix-up (R1): every process-badge category landing
    page must 200 on every deployed city. Process badges are always-on
    per spec §4.2 / decision #11; the strict-config gate that 404'd
    every process URL was a F2 bug.

    This test pins the always-on contract — a future regression that
    re-introduces the strict-config gate would 404 these URLs and
    fail every parametrized case.
    """
    for city in ("birmingham", "mobile", "vestavia_hills", "homewood"):
        rv = client.get(f"/al/{city}/{process_slug}/")
        assert rv.status_code == 200, (
            f"/al/{city}/{process_slug}/ returned {rv.status_code}, expected 200"
        )


# ---------------------------------------------------------------------------
# F4 review fix-up (R2) — HX-Request partial-render path
# ---------------------------------------------------------------------------


def test_htmx_cross_filter_returns_partial_only(bag, client):
    """F4 review fix-up (R2): when the cross-filter dropdown fires its
    HTMX request, the route returns ONLY the item-list partial — no
    base template chrome (``<!DOCTYPE>``, ``<html>``, masthead, rail).
    This saves ~5 DB queries per filter swap and keeps the dropdown
    DOM in place (resolves S9 post-swap unsync).
    """
    yr = date.today().year
    m = bag.add_meeting(f"{yr}-04-15")
    iid = bag.add_item(m, title="Partial-target", significance_score=5)
    bag.add_badge(iid, "blight_accountability", confidence=1.0)

    rv = client.get(
        f"/al/{bag.city_slug}/blight_accountability/",
        headers={"HX-Request": "true"},
    )
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)

    # Partial response: no base-template wrappers.
    assert "<!DOCTYPE" not in body
    assert "<html" not in body
    assert "<body" not in body

    # Partial DOES carry the item-list swap target.
    assert 'id="item-list"' in body


def test_htmx_response_smaller_than_full_page(bag, client):
    """F4 review fix-up (R2): the partial-render response is materially
    smaller than the full-page render — sanity check the bytes saved.
    The partial drops the base shell (~10-30 KB), header/KPI strip,
    timeline SVG, dropdown, and chip row.
    """
    yr = date.today().year
    m = bag.add_meeting(f"{yr}-04-15")
    iid = bag.add_item(m, title="Sized-item", significance_score=5)
    bag.add_badge(iid, "blight_accountability", confidence=1.0)

    full = client.get(f"/al/{bag.city_slug}/blight_accountability/")
    partial = client.get(
        f"/al/{bag.city_slug}/blight_accountability/",
        headers={"HX-Request": "true"},
    )
    assert full.status_code == 200
    assert partial.status_code == 200

    full_size = len(full.get_data())
    partial_size = len(partial.get_data())
    # Partial should be < 50% of the full page — base.html shell +
    # KPI strip + timeline SVG account for >50% of the bytes alone.
    assert partial_size < 0.5 * full_size, (
        f"partial {partial_size} bytes >= 50% of full {full_size} bytes"
    )


def test_htmx_response_carries_cross_filter_results(bag, client):
    """F4 review fix-up (R2): the partial render still applies the
    cross-filter — items returned must reflect the ``?and=`` arg, not
    just dump the full unfiltered list.
    """
    yr = date.today().year
    m = bag.add_meeting(f"{yr}-04-15")
    matched = bag.add_item(m, title="MATCHED-ITEM", significance_score=5)
    unmatched = bag.add_item(m, title="UNMATCHED-ITEM", significance_score=5)
    bag.add_badge(matched, "blight_accountability", confidence=1.0)
    bag.add_badge(matched, "hidden_on_consent", confidence=1.0)
    bag.add_badge(unmatched, "blight_accountability", confidence=1.0)

    rv = client.get(
        f"/al/{bag.city_slug}/blight_accountability/?and=hidden_on_consent",
        headers={"HX-Request": "true"},
    )
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "MATCHED-ITEM" in body
    assert "UNMATCHED-ITEM" not in body


# ---------------------------------------------------------------------------
# F4 review fix-up (S5) — cross-filter slug validation
# ---------------------------------------------------------------------------


def test_route_drops_unknown_cross_filter_slugs(bag, client):
    """F4 review fix-up (S5): typo'd or disabled cross-filter slugs
    must be silently dropped — they don't get passed into the EXISTS
    predicate where they'd produce an empty result set. Spec §6.8
    requires "validates against enabled badges."
    """
    yr = date.today().year
    m = bag.add_meeting(f"{yr}-04-15")
    iid = bag.add_item(m, title="Survives-bad-filter", significance_score=5)
    bag.add_badge(iid, "blight_accountability", confidence=1.0)

    # Combine a real slug with garbage slugs — only the real one applies.
    rv = client.get(
        f"/al/{bag.city_slug}/blight_accountability/?and=no_such_badge,xyz123"
    )
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    # Item still renders — bad slugs were dropped, not used as filters.
    assert "Survives-bad-filter" in body
    # The "Showing items also tagged" header (which renders only when
    # cross_filters is non-empty) should NOT appear — validated list
    # is empty.
    assert "Showing items also tagged" not in body


# ---------------------------------------------------------------------------
# F4 review fix-up (S11) — link-crawler smoke test
# ---------------------------------------------------------------------------


def test_link_crawler_homepage_links_resolve_to_200(client):
    """F4 review fix-up (S11): for every deployed city, walk the
    homepage and follow every link that targets a category landing
    page (matching ``/al/<city>/<slug>/``). Each link must return 200.

    This would have caught R1 — every homepage Browse-by-Priority tile
    pointed at a category URL that 404'd. Catches the next R1 too.

    The crawler does NOT mock — it actually issues GETs through the
    Flask test client and asserts each response status. Limits to the
    category-landing slug pattern so we don't recurse into meeting
    pages or counterparts.
    """
    import re
    cities = ("birmingham", "mobile", "vestavia_hills", "homewood")
    href_pattern = re.compile(r'href="(/al/([^/]+)/([^/?#"]+)/)"')

    for city in cities:
        rv = client.get(f"/al/{city}/")
        assert rv.status_code == 200, f"/al/{city}/ failed"
        body = rv.get_data(as_text=True)

        # Reserved second-segment values that aren't badge slugs.
        # ``meetings`` / ``council`` are real route prefixes; skip them.
        reserved = {"meetings", "council", "_rail"}

        seen: set[tuple[str, str]] = set()
        for match in href_pattern.finditer(body):
            full_path, link_city, slug = match.group(1), match.group(2), match.group(3)
            if link_city != city:
                continue
            if slug in reserved:
                continue
            if (link_city, slug) in seen:
                continue
            seen.add((link_city, slug))

            sub = client.get(full_path)
            assert sub.status_code == 200, (
                f"link {full_path} from /al/{city}/ returned {sub.status_code}"
            )

        # Sanity: we should have crawled at least one badge URL on each
        # city — process tiles always render, so 7 process slugs
        # minimum on every city after R1.
        assert len(seen) >= 7, (
            f"/al/{city}/ crawler found only {len(seen)} category links: {seen}"
        )
