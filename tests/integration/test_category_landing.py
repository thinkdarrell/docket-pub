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


def test_get_resolved_badge_no_city_config_returns_none(bag):
    """A process badge like ``hidden_on_consent`` is NOT seeded into
    ``priority_badges_config`` for Birmingham (migration 013 only seeds
    the 4 BHM policy badges). The template exists, but the city hasn't
    opted in — helper must return None.
    """
    assert get_resolved_badge(bag.city_id, "hidden_on_consent") is None


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


def test_route_404_badge_not_opted_in(bag, client):
    """Process badges (like ``hidden_on_consent``) are NOT seeded into
    Birmingham's priority_badges_config. Route should 404 even though
    the template exists.
    """
    rv = client.get(f"/al/{bag.city_slug}/hidden_on_consent/")
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
    """An empty ``?and=`` should not produce a phantom filter slug."""
    m = bag.add_meeting(bag.city_id, "2026-04-15")
    item = bag.add_item(m, title="Solo", significance_score=5)
    bag.add_badge(item, bag.city_id, "blight_accountability", confidence=1.0)

    rv = client.get(f"/al/{bag.city_slug}/blight_accountability/?and=")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Solo" in body
