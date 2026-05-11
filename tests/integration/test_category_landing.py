"""Integration tests for the category landing route + helpers (F2).

Covers:

- ``query.get_resolved_badge`` — name/description override application,
  None for unknown templates, None for missing config rows, None for
  disabled config rows.
- ``query.category_kpis`` — year filter, NULL dollars, empty result.
- ``/al/<slug>/<badge_slug>/`` route:
    - 200 happy path
    - 404 on unknown city, unknown badge, disabled badge config
    - cross-filter wiring (verifies items filter correctly)
    - pagination + offset sanitization (negative, non-numeric)
    - empty-state rendering
    - next_offset semantics

Test isolation reuses the ``_Bag`` pattern from
``test_list_items_by_badge.py``: each test inserts through ``db()``
(which commits), tracks ids in a bag, and tears down on fixture exit.
The Flask ``test_client`` is built per-module from ``create_app()``.
"""

from __future__ import annotations

import pytest

from docket.config import DATABASE_URL
from docket.db import db
from docket.migrations.runner import apply_migrations
from docket.services.query import (
    category_kpis,
    get_resolved_badge,
    list_items_by_badge,
    resolve_badges,
)
from docket.web import create_app


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run category-landing tests against Railway DB.",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _Bag:
    """Test-data tracker — mirrors the F1 pattern in
    ``test_list_items_by_badge.py``. Inserts through ``db()`` so writes
    commit and become visible to the route's own connection. Teardown
    deletes everything by id.
    """

    def __init__(self, city_id: int, city_slug: str):
        self.city_id = city_id
        self.city_slug = city_slug
        self.meeting_ids: list[int] = []
        self.item_ids: list[int] = []
        # (city_id, template_slug) for inserted-only config rows.
        # We DON'T touch the migration-013-seeded BHM rows.
        self.inserted_config_rows: list[tuple[int, str]] = []
        # (city_id, template_slug, original_enabled) for rows we toggled
        # to disabled — restore on teardown.
        self.config_enabled_restore: list[tuple[int, str, bool]] = []
        # (city_id, template_slug, original_overrides_jsonb_or_None)
        self.config_override_restore: list[
            tuple[int, str, str | None, str | None]
        ] = []

    # -- inserts --------------------------------------------------------------

    def add_meeting(self, city_id: int, meeting_date: str) -> int:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO meetings
                      (municipality_id, title, meeting_date, meeting_type)
                    VALUES (%s, 'Test meeting', %s, 'council')
                    RETURNING id
                    """,
                    (city_id, meeting_date),
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
        item_number: str | None = None,
    ) -> int:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agenda_items
                      (meeting_id, title, significance_score, dollars_amount,
                       processing_status, item_number)
                    VALUES (%s, %s, %s, %s,
                            %s::processing_status_enum, %s)
                    RETURNING id
                    """,
                    (meeting_id, title, significance_score, dollars_amount,
                     processing_status, item_number),
                )
                iid = cur.fetchone()[0]
        self.item_ids.append(iid)
        return iid

    def add_badge(
        self,
        item_id: int,
        city_id: int,
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
                    (item_id, city_id, badge_slug, kind, confidence),
                )

    def insert_config_row(
        self,
        city_id: int,
        template_slug: str,
        *,
        enabled: bool = True,
        name_override: str | None = None,
        description_override: str | None = None,
    ) -> None:
        """Insert a fresh priority_badges_config row.

        Only used for cities/templates that don't already have a row
        seeded by migration 013 (i.e. non-BHM cities or non-BHM-seeded
        templates). For cities that DO have a seeded row, use
        ``override_config`` / ``set_enabled`` instead so teardown can
        restore values.
        """
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO priority_badges_config
                      (city_id, template_slug, enabled,
                       name_override, description_override, added_by)
                    VALUES (%s, %s, %s, %s, %s, 'test')
                    """,
                    (city_id, template_slug, enabled,
                     name_override, description_override),
                )
        self.inserted_config_rows.append((city_id, template_slug))

    def set_enabled(
        self, city_id: int, template_slug: str, enabled: bool
    ) -> None:
        """Toggle the ``enabled`` flag, remembering the original."""
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT enabled FROM priority_badges_config
                    WHERE city_id = %s AND template_slug = %s
                    """,
                    (city_id, template_slug),
                )
                row = cur.fetchone()
                assert row is not None, (
                    f"no priority_badges_config row for "
                    f"city_id={city_id}, template={template_slug}"
                )
                self.config_enabled_restore.append(
                    (city_id, template_slug, row[0])
                )
                cur.execute(
                    """
                    UPDATE priority_badges_config
                    SET enabled = %s
                    WHERE city_id = %s AND template_slug = %s
                    """,
                    (enabled, city_id, template_slug),
                )

    def override_config(
        self,
        city_id: int,
        template_slug: str,
        *,
        name_override: str | None,
        description_override: str | None,
    ) -> None:
        """Set name/description overrides on the seeded config row.

        Saves the original values so teardown restores them.
        """
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT name_override, description_override
                    FROM priority_badges_config
                    WHERE city_id = %s AND template_slug = %s
                    """,
                    (city_id, template_slug),
                )
                row = cur.fetchone()
                assert row is not None, (
                    f"no priority_badges_config row for "
                    f"city_id={city_id}, template={template_slug}"
                )
                self.config_override_restore.append(
                    (city_id, template_slug, row[0], row[1])
                )
                cur.execute(
                    """
                    UPDATE priority_badges_config
                    SET name_override = %s,
                        description_override = %s
                    WHERE city_id = %s AND template_slug = %s
                    """,
                    (name_override, description_override,
                     city_id, template_slug),
                )

    # -- teardown -------------------------------------------------------------

    def cleanup(self) -> None:
        with db() as conn:
            with conn.cursor() as cur:
                # Restore enabled flags first.
                for city_id, slug, original in self.config_enabled_restore:
                    cur.execute(
                        """
                        UPDATE priority_badges_config
                        SET enabled = %s
                        WHERE city_id = %s AND template_slug = %s
                        """,
                        (original, city_id, slug),
                    )
                # Restore name/description overrides.
                for city_id, slug, name_orig, desc_orig in self.config_override_restore:
                    cur.execute(
                        """
                        UPDATE priority_badges_config
                        SET name_override = %s,
                            description_override = %s
                        WHERE city_id = %s AND template_slug = %s
                        """,
                        (name_orig, desc_orig, city_id, slug),
                    )
                # Drop test-only inserted config rows.
                for city_id, slug in self.inserted_config_rows:
                    cur.execute(
                        """
                        DELETE FROM priority_badges_config
                        WHERE city_id = %s AND template_slug = %s
                        """,
                        (city_id, slug),
                    )
                # Items + badges + meetings.
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
    """Yield a clean ``_Bag`` for the test."""
    with db() as conn:
        apply_migrations(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, slug FROM municipalities WHERE slug = 'birmingham'"
            )
            row = cur.fetchone()
            assert row is not None, (
                "Birmingham must be seeded by migration 002"
            )
            city_id, city_slug = row[0], row[1]

    b = _Bag(city_id, city_slug)
    try:
        yield b
    finally:
        b.cleanup()


@pytest.fixture(scope="module")
def app():
    """Real Flask app via ``create_app()``. Same factory production uses."""
    flask_app = create_app()
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Helper: get_resolved_badge
# ---------------------------------------------------------------------------


def test_get_resolved_badge_seeded_bhm_policy_badge(bag):
    """blight_accountability is seeded enabled for Birmingham (migration
    013). With no overrides, name + description come from the template.
    """
    badge = get_resolved_badge(bag.city_id, "blight_accountability")
    assert badge is not None
    assert badge["slug"] == "blight_accountability"
    assert badge["name"] == "Blight Accountability"
    assert badge["kind"] == "policy"
    assert badge["enabled"] is True
    assert badge["icon"]  # non-empty


def test_get_resolved_badge_applies_name_override(bag):
    bag.override_config(
        bag.city_id,
        "blight_accountability",
        name_override="BHM Blight Watch",
        description_override=None,
    )
    badge = get_resolved_badge(bag.city_id, "blight_accountability")
    assert badge is not None
    assert badge["name"] == "BHM Blight Watch"
    # Description still comes from template since override is None.
    assert "Blight" in badge["description"] or "blight" in badge["description"]


def test_get_resolved_badge_applies_description_override(bag):
    bag.override_config(
        bag.city_id,
        "blight_accountability",
        name_override=None,
        description_override="Custom city description for blight enforcement.",
    )
    badge = get_resolved_badge(bag.city_id, "blight_accountability")
    assert badge is not None
    assert badge["description"] == (
        "Custom city description for blight enforcement."
    )
    # Name still comes from template since override is None.
    assert badge["name"] == "Blight Accountability"


def test_get_resolved_badge_unknown_template_returns_none(bag):
    assert get_resolved_badge(bag.city_id, "no_such_badge") is None


def test_get_resolved_badge_process_resolves_template_only(bag):
    """Process badges are always-on across cities (spec §4.2 / decision
    #11). They are NOT seeded into ``priority_badges_config`` per-city
    by design — the template's existence is itself the enable signal.

    F4 review fix-up (R1): the prior contract required a config row
    for *every* badge, which 404'd every process-badge category landing
    page. The LEFT-JOIN + ``kind = 'process' OR enabled = TRUE`` clause
    matches the always-on contract.
    """
    badge = get_resolved_badge(bag.city_id, "hidden_on_consent")
    assert badge is not None
    assert badge["slug"] == "hidden_on_consent"
    assert badge["kind"] == "process"
    # Template defaults flow through (no config row → no overrides).
    assert badge["name"]
    assert badge["icon"]
    # ``enabled`` defaults to TRUE for process badges via COALESCE.
    assert badge["enabled"] is True


def test_get_resolved_badge_policy_no_city_config_returns_none(bag):
    """Policy badges remain city-opt-in. Without a config row for the
    city, a policy badge resolves to None (so the route 404s, matching
    the citizen contract).

    Asserted against the seed: migration 013 enables BHM into all 4
    policy badges, but Mobile is not seeded for, e.g.,
    ``blight_accountability`` — fetch the Mobile city id and verify.
    """
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM municipalities WHERE slug = 'mobile'")
            row = cur.fetchone()
    assert row is not None, "Mobile must be seeded by migration 002"
    mobile_id = row[0]
    assert get_resolved_badge(mobile_id, "blight_accountability") is None


def test_get_resolved_badge_disabled_config_returns_none(bag):
    bag.set_enabled(bag.city_id, "blight_accountability", False)
    assert get_resolved_badge(bag.city_id, "blight_accountability") is None


# ---------------------------------------------------------------------------
# Helper: category_kpis
# ---------------------------------------------------------------------------


def test_category_kpis_counts_only_year_items(bag):
    in_2026 = bag.add_meeting(bag.city_id, "2026-04-15")
    in_2025 = bag.add_meeting(bag.city_id, "2025-06-10")
    a = bag.add_item(in_2026, title="A", dollars_amount=10_000, significance_score=5)
    b = bag.add_item(in_2026, title="B", dollars_amount=5_000, significance_score=5)
    c = bag.add_item(in_2025, title="C", dollars_amount=999_000, significance_score=5)
    for i in (a, b, c):
        bag.add_badge(i, bag.city_id, "blight_accountability", confidence=1.0)

    kpis = category_kpis(bag.city_id, "blight_accountability", year=2026)
    assert kpis["item_count"] == 2
    # Decimal arithmetic — compare numerically.
    assert int(kpis["total_dollars"]) == 15_000
    assert kpis["mayor_priority_quote"] is None


def test_category_kpis_handles_null_dollars(bag):
    m = bag.add_meeting(bag.city_id, "2026-04-15")
    a = bag.add_item(m, title="No dollars", dollars_amount=None, significance_score=5)
    b = bag.add_item(m, title="With dollars", dollars_amount=42_000, significance_score=5)
    bag.add_badge(a, bag.city_id, "blight_accountability", confidence=1.0)
    bag.add_badge(b, bag.city_id, "blight_accountability", confidence=1.0)

    kpis = category_kpis(bag.city_id, "blight_accountability", year=2026)
    assert kpis["item_count"] == 2
    assert int(kpis["total_dollars"]) == 42_000


def test_category_kpis_zero_when_no_items(bag):
    # Use a year that we deliberately won't seed items in.
    kpis = category_kpis(bag.city_id, "blight_accountability", year=1999)
    assert kpis["item_count"] == 0
    assert int(kpis["total_dollars"]) == 0
    assert kpis["mayor_priority_quote"] is None


def test_category_kpis_excludes_low_confidence_and_pending(bag):
    """Mirrors the listing render contract: confidence >= 0.6 and
    processing_status = 'completed' only.
    """
    m = bag.add_meeting(bag.city_id, "2026-04-15")
    high_conf = bag.add_item(
        m, title="High conf", dollars_amount=10_000, significance_score=5
    )
    low_conf = bag.add_item(
        m, title="Low conf", dollars_amount=999_999, significance_score=5
    )
    pending = bag.add_item(
        m, title="Pending", dollars_amount=999_999, significance_score=5,
        processing_status="pending",
    )
    bag.add_badge(high_conf, bag.city_id, "blight_accountability", confidence=1.0)
    bag.add_badge(low_conf, bag.city_id, "blight_accountability", confidence=0.4)
    bag.add_badge(pending, bag.city_id, "blight_accountability", confidence=1.0)

    kpis = category_kpis(bag.city_id, "blight_accountability", year=2026)
    assert kpis["item_count"] == 1
    assert int(kpis["total_dollars"]) == 10_000


# ---------------------------------------------------------------------------
# Route: /al/<slug>/<badge_slug>/
# ---------------------------------------------------------------------------


def test_route_200_happy_path(bag, client):
    m = bag.add_meeting(bag.city_id, "2026-04-15")
    item = bag.add_item(
        m, title="Demolition order", dollars_amount=12_345, significance_score=5
    )
    bag.add_badge(item, bag.city_id, "blight_accountability", confidence=1.0)

    rv = client.get(
        f"/al/{bag.city_slug}/blight_accountability/"
    )
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Blight Accountability" in body
    # The item title should appear as part of the rendered card (the
    # smart_brevity_card dispatcher will route to card_pending for a
    # v3-pre item, which still surfaces the title somewhere in markup).
    assert "Demolition order" in body


def test_category_landing_renders_meeting_date_and_item_number(bag, client):
    """Section A regression: every card on a category landing must show
    its meeting date + Item-#N reference. Without these the cards have
    no temporal context (cards span many meetings on this surface,
    unlike meeting-detail)."""
    m = bag.add_meeting(bag.city_id, "2026-04-15")
    item = bag.add_item(
        m, title="Demolition order", dollars_amount=12_345,
        significance_score=5, item_number="42",
    )
    bag.add_badge(item, bag.city_id, "blight_accountability", confidence=1.0)

    rv = client.get(f"/al/{bag.city_slug}/blight_accountability/")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "April 15, 2026" in body
    assert "Item #42" in body


def test_category_landing_meta_strip_omitted_when_neither_field_present(
    bag, client
):
    """The strip's whole-block guard collapses when no date AND no item
    number — keeps an empty meta block from rendering."""
    m = bag.add_meeting(bag.city_id, "2026-04-15")
    item = bag.add_item(
        m, title="No-context item", significance_score=5, item_number=None,
    )
    bag.add_badge(item, bag.city_id, "blight_accountability", confidence=1.0)

    rv = client.get(f"/al/{bag.city_slug}/blight_accountability/")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    # Date is still there from the meeting itself — meta strip should render
    # date alone, but not the empty "Item #" reference.
    assert "April 15, 2026" in body
    assert "Item #None" not in body


def test_route_404_unknown_city(client):
    rv = client.get("/al/no-such-city-99/blight_accountability/")
    assert rv.status_code == 404


def test_route_404_unknown_badge(bag, client):
    rv = client.get(f"/al/{bag.city_slug}/no_such_badge/")
    assert rv.status_code == 404


def test_route_404_disabled_badge(bag, client):
    bag.set_enabled(bag.city_id, "blight_accountability", False)
    rv = client.get(f"/al/{bag.city_slug}/blight_accountability/")
    assert rv.status_code == 404


def test_route_404_policy_badge_not_opted_in(bag, client):
    """Policy badges remain city-opt-in (spec §4.2 / decision #11) — a
    policy badge with no ``enabled=TRUE`` row in ``priority_badges_config``
    for the city must 404 even though the template exists.

    Mobile is not seeded for ``blight_accountability`` (migration 013
    only enables BHM into the 4 policy badges).

    F4 review fix-up (R1): process badges flipped to always-on, but
    policy badges stay gated; this test pins the policy gate so a
    future relaxation doesn't silently make every policy slug active
    on every city.
    """
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT slug FROM municipalities WHERE slug = 'mobile'")
            row = cur.fetchone()
    assert row is not None
    rv = client.get(f"/al/{row[0]}/blight_accountability/")
    assert rv.status_code == 404


def test_route_cross_filter_filters_items(bag, client):
    """Verify cross-filter wires through to ``list_items_by_badge``:
    items without the cross-filter badge must NOT render.
    """
    m = bag.add_meeting(bag.city_id, "2026-04-15")
    both = bag.add_item(m, title="Both badges", significance_score=5)
    only_primary = bag.add_item(m, title="Only blight", significance_score=5)
    bag.add_badge(both, bag.city_id, "blight_accountability", confidence=1.0)
    bag.add_badge(both, bag.city_id, "housing_stability", confidence=1.0)
    bag.add_badge(only_primary, bag.city_id, "blight_accountability", confidence=1.0)

    rv = client.get(
        f"/al/{bag.city_slug}/blight_accountability/"
        "?and=housing_stability"
    )
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Both badges" in body
    assert "Only blight" not in body


def test_route_pagination_offset(bag, client):
    """offset=N uses the offset; we add 26 items so the first page hits
    the limit (25) and ``next_offset`` becomes truthy.
    """
    m = bag.add_meeting(bag.city_id, "2026-04-15")
    titles = []
    for i in range(26):
        title = f"Item-Number-{i:02d}"
        iid = bag.add_item(
            m, title=title, dollars_amount=1_000_000 - i,  # distinct ordering
            significance_score=5,
        )
        bag.add_badge(iid, bag.city_id, "blight_accountability", confidence=1.0)
        titles.append(title)

    # First page: should hit 25-item limit; load-more link must appear.
    rv = client.get(f"/al/{bag.city_slug}/blight_accountability/")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "offset=25" in body, "expected load-more link with offset=25"

    # Second page: offset=25 returns the remaining 1 item; no load-more
    # because len(items) < 25.
    rv2 = client.get(
        f"/al/{bag.city_slug}/blight_accountability/?offset=25"
    )
    assert rv2.status_code == 200
    body2 = rv2.get_data(as_text=True)
    assert "offset=50" not in body2


def test_route_offset_non_numeric_clamped_to_zero(bag, client):
    """Bad input becomes 0, no 500."""
    bag.add_meeting(bag.city_id, "2026-04-15")  # ensure db isn't empty
    rv = client.get(
        f"/al/{bag.city_slug}/blight_accountability/?offset=notanumber"
    )
    assert rv.status_code == 200


def test_route_offset_negative_clamped_to_zero(bag, client):
    """Negative offset doesn't underflow into a SQL error."""
    bag.add_meeting(bag.city_id, "2026-04-15")
    rv = client.get(
        f"/al/{bag.city_slug}/blight_accountability/?offset=-99"
    )
    assert rv.status_code == 200


def test_route_empty_state_renders_gracefully(bag, client):
    """Valid badge with zero matching items should still 200, not 500."""
    rv = client.get(f"/al/{bag.city_slug}/blight_accountability/")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    # Either "No items yet" or "0 items" — accept either as long as
    # the page renders without crashing.
    assert rv.status_code == 200
    assert "Blight Accountability" in body


def test_route_empty_cross_filter_string_ignored(bag, client):
    """An empty ``?and=`` should not produce a phantom filter slug.

    F4 review fix-up (Opus#2-S4): the route now 302s to the canonical
    no-filter URL when the user submits the blank "(none)" option, so
    the final rendered page ends up at the clean URL with no dangling
    ``?and=`` query param. ``follow_redirects=True`` walks the chain.
    """
    m = bag.add_meeting(bag.city_id, "2026-04-15")
    item = bag.add_item(m, title="Solo", significance_score=5)
    bag.add_badge(item, bag.city_id, "blight_accountability", confidence=1.0)

    rv = client.get(
        f"/al/{bag.city_slug}/blight_accountability/?and=",
        follow_redirects=True,
    )
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Solo" in body
    # Final URL is the canonical no-filter form (no trailing ?and=).
    assert rv.request.path.endswith("/blight_accountability/")
    assert rv.request.query_string == b""


# ---------------------------------------------------------------------------
# F2 review fix-up: KPI / list parity, citizen copy, behaviors
# ---------------------------------------------------------------------------


def _current_year() -> int:
    """Helper — KPIs are computed against ``date.today().year`` in the
    route. Tests that insert items at "this year" must align with that.
    """
    from datetime import date as _date
    return _date.today().year


def test_kpis_respect_significance_gate(bag):
    """R1: ``category_kpis`` must apply the same per-badge significance
    gate that ``list_items_by_badge`` does, so KPI ``item_count`` and
    rendered card count agree on policy badges with ``min_significance``.

    ``blight_accountability`` is a policy badge with ``min_significance=3``
    (migration 013 seeds). An item at significance 2 would be counted
    by the original (broken) ``category_kpis`` but excluded from the
    listing — divergent strings on screen.
    """
    yr = _current_year()
    m = bag.add_meeting(bag.city_id, f"{yr}-04-15")
    high = bag.add_item(m, title="High sig", dollars_amount=10_000, significance_score=5)
    low = bag.add_item(m, title="Low sig", dollars_amount=99_000, significance_score=2)
    bag.add_badge(high, bag.city_id, "blight_accountability", confidence=1.0)
    bag.add_badge(low, bag.city_id, "blight_accountability", confidence=1.0)

    listed = list_items_by_badge(
        bag.city_id, "blight_accountability", min_confidence=0.6
    )
    kpis = category_kpis(bag.city_id, "blight_accountability", year=yr)
    # Listing excludes the sig=2 item; KPI must match.
    assert len(listed) == 1
    assert kpis["item_count"] == 1
    # Total dollars must reflect only the gated set, not the
    # ungated 109_000 sum.
    assert int(kpis["total_dollars"]) == 10_000


def test_kpis_respect_cross_filter(bag):
    """R1 (extension): ``category_kpis`` accepts ``cross_filter_slugs``
    and applies the same EXISTS predicate ``list_items_by_badge`` does.
    """
    yr = _current_year()
    m = bag.add_meeting(bag.city_id, f"{yr}-04-15")
    both = bag.add_item(m, title="Both", dollars_amount=10_000, significance_score=5)
    only_blight = bag.add_item(
        m, title="Only blight", dollars_amount=99_000, significance_score=5
    )
    bag.add_badge(both, bag.city_id, "blight_accountability", confidence=1.0)
    bag.add_badge(both, bag.city_id, "housing_stability", confidence=1.0)
    bag.add_badge(only_blight, bag.city_id, "blight_accountability", confidence=1.0)

    no_cross = category_kpis(bag.city_id, "blight_accountability", year=yr)
    with_cross = category_kpis(
        bag.city_id, "blight_accountability", year=yr,
        cross_filter_slugs=("housing_stability",),
    )
    assert no_cross["item_count"] == 2
    assert with_cross["item_count"] == 1
    assert int(with_cross["total_dollars"]) == 10_000


def test_kpis_match_listing_count_at_render_time(bag, client):
    """R1: cross-task contract test — KPI count rendered on the page
    matches the rendered card count. Pins the F1↔F2 contract that
    cross-model review caught.

    Inserts a mix of high- and low-significance items. Renders the
    route. Reads the KPI ``item_count`` value out of the HTML and the
    number of items rendered in the listing, asserts equality.
    """
    yr = _current_year()
    m = bag.add_meeting(bag.city_id, f"{yr}-04-15")
    counted_items = []
    for i in range(3):
        iid = bag.add_item(
            m, title=f"Render-Match-Visible-{i}",
            dollars_amount=10_000 + i, significance_score=5,
        )
        bag.add_badge(iid, bag.city_id, "blight_accountability", confidence=1.0)
        counted_items.append(f"Render-Match-Visible-{i}")
    # Below-threshold item that must not contribute to either count.
    excluded = bag.add_item(
        m, title="Render-Match-Excluded",
        dollars_amount=999_999, significance_score=1,
    )
    bag.add_badge(excluded, bag.city_id, "blight_accountability", confidence=1.0)

    rv = client.get(f"/al/{bag.city_slug}/blight_accountability/")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)

    # KPI strip wins on the same set the listing rendered.
    kpis = category_kpis(bag.city_id, "blight_accountability", year=yr)
    assert kpis["item_count"] == 3

    # All three counted items rendered as cards; the excluded one did not.
    for title in counted_items:
        assert title in body, f"expected {title!r} on the page"
        assert "Render-Match-Excluded" not in body

    # The rendered KPI value should match too — surfaced as
    # ">3<" inside the .kpi-value div.
    assert ">3<" in body, "KPI value 3 must appear in HTML"


def test_empty_state_has_no_internal_jargon(bag, client):
    """R2: citizen-visible empty state must not surface internal pipeline
    vocabulary (Wave 0 / Track 1 / D2 / matchers / backfill).
    """
    rv = client.get(f"/al/{bag.city_slug}/blight_accountability/")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    for jargon in ("Wave 0", "Track 1", "D2", "matchers", "backfill"):
        assert jargon not in body, (
            f"public empty state contains internal jargon {jargon!r}"
        )


def test_cross_filter_strips_whitespace(bag, client):
    """S1: URL-encoded space inside ``?and=`` (e.g., ``blight,%20housing``)
    must yield clean slugs — leading/trailing whitespace stripped, no
    phantom ``" housing"`` token.
    """
    yr = _current_year()
    m = bag.add_meeting(bag.city_id, f"{yr}-04-15")
    both = bag.add_item(m, title="Whitespace-Both", significance_score=5)
    bag.add_badge(both, bag.city_id, "blight_accountability", confidence=1.0)
    bag.add_badge(both, bag.city_id, "housing_stability", confidence=1.0)
    only_primary = bag.add_item(m, title="Whitespace-Only", significance_score=5)
    bag.add_badge(only_primary, bag.city_id, "blight_accountability", confidence=1.0)

    # Real users hit URLs like this when copy-pasting from the address
    # bar. The space encodes as %20.
    rv = client.get(
        f"/al/{bag.city_slug}/blight_accountability/?and=blight_accountability,%20housing_stability"
    )
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    # Cross-filter resolved as expected — the only item with both
    # badges should appear; the one with only blight should not.
    assert "Whitespace-Both" in body
    assert "Whitespace-Only" not in body


def test_pagination_no_phantom_load_more_at_exact_25(bag, client):
    """S3: LIMIT 26 sentinel — exactly 25 items in the dataset must NOT
    surface a "load more" link; a 26th would. The original off-by-one
    set ``next_offset = offset + 25 if len(items) == 25 else None``,
    which would point at an empty page when total = 25 exactly.
    """
    yr = _current_year()
    m = bag.add_meeting(bag.city_id, f"{yr}-04-15")
    for i in range(25):
        iid = bag.add_item(
            m, title=f"Exact25-Item-{i:02d}",
            dollars_amount=1_000_000 - i, significance_score=5,
        )
        bag.add_badge(iid, bag.city_id, "blight_accountability", confidence=1.0)

    rv = client.get(f"/al/{bag.city_slug}/blight_accountability/")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    # No "offset=25" load-more link — would mean a phantom page 2.
    assert "offset=25" not in body, (
        "exactly 25 items should not produce a load-more link"
    )


def test_load_more_link_preserves_cross_filters(bag, client):
    """Verification: when 26+ items match and a cross-filter is active,
    the rendered load-more link must include the cross-filter slugs in
    its href so navigating to page 2 keeps the filter applied.
    """
    yr = _current_year()
    m = bag.add_meeting(bag.city_id, f"{yr}-04-15")
    for i in range(26):
        iid = bag.add_item(
            m, title=f"Preserve-Item-{i:02d}",
            dollars_amount=1_000_000 - i, significance_score=5,
        )
        bag.add_badge(iid, bag.city_id, "blight_accountability", confidence=1.0)
        bag.add_badge(iid, bag.city_id, "housing_stability", confidence=1.0)

    rv = client.get(
        f"/al/{bag.city_slug}/blight_accountability/?and=housing_stability"
    )
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    # Load-more href must carry both the cross-filter and the new offset.
    assert "and=housing_stability" in body
    assert "offset=25" in body


def test_resolve_badges_batch(bag):
    """S5: batch resolver returns only valid + enabled rows.

    - Valid + enabled → present
    - Valid + disabled (toggled off) → absent
    - Unknown slug → absent
    """
    bag.set_enabled(bag.city_id, "housing_stability", False)

    out = resolve_badges(
        bag.city_id,
        ["blight_accountability", "housing_stability", "no_such_badge"],
    )
    assert "blight_accountability" in out
    assert out["blight_accountability"]["name"] == "Blight Accountability"
    assert out["blight_accountability"]["kind"] == "policy"
    assert "housing_stability" not in out
    assert "no_such_badge" not in out


def test_resolve_badges_empty_input_returns_empty_dict():
    """Empty input shouldn't hit the DB. We can't directly assert no
    round-trip, but we can pass a city_id that wouldn't match anything
    and confirm the helper returns ``{}`` cleanly.
    """
    assert resolve_badges(999_999_999, []) == {}
    assert resolve_badges(0, ()) == {}


def test_chip_label_uses_resolved_name_override(bag, client):
    """S5: cross-filter chip uses ``name_override`` when set on the
    city's config row. Visible name should be the override, not the
    title-cased slug.
    """
    yr = _current_year()
    bag.override_config(
        bag.city_id,
        "housing_stability",
        name_override="Housing Justice Watch",
        description_override=None,
    )
    m = bag.add_meeting(bag.city_id, f"{yr}-04-15")
    iid = bag.add_item(m, title="Chip-Label-Item", significance_score=5)
    bag.add_badge(iid, bag.city_id, "blight_accountability", confidence=1.0)
    bag.add_badge(iid, bag.city_id, "housing_stability", confidence=1.0)

    rv = client.get(
        f"/al/{bag.city_slug}/blight_accountability/?and=housing_stability"
    )
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Housing Justice Watch" in body, (
        "chip should render the configured name override"
    )
