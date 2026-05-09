"""Integration tests for ``list_items_by_badge`` (Phase 2 / F1).

Covers the spec §6.5 contract + decision #61 render-time significance gate:

- Confidence floor (default 0.6 vs override).
- Significance gate ON for policy badges (default), OFF when
  ``include_low_significance=True``.
- Process badges have NO significance gate ever (regardless of
  ``include_low_significance``).
- ``processing_status = 'completed'`` filter (pending/failed items hidden).
- City scoping (items in another city with the same badge slug not
  returned).
- Cross-filter AND semantics — single and multiple cross slugs.
- Empty ``cross_filter_slugs`` (default) leaves results unfiltered.
- Ordering: ``meeting_date DESC, dollars_amount DESC NULLS LAST``.
- Pagination: limit + offset.
- Unknown badge slug returns an empty list.
- Helper ``resolve_significance_threshold`` returns the right type per kind.

Test isolation strategy: each test's fixture inserts data through the
``db()`` context manager (which commits on success — the service
function under test opens its own connection so data must be visible
across connections). The fixture tracks every inserted id and deletes
them at teardown. ``agenda_item_badges``, ``agenda_items``, and any
test-only ``meetings`` rows we created are torn down in dependency
order; ``priority_badges_config`` overrides written by tests are
restored at teardown via the saved-then-restored value.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from docket.config import DATABASE_URL
from docket.db import db
from docket.migrations.runner import apply_migrations
from docket.models.agenda import AgendaItem
from docket.services.query import (
    list_items_by_badge,
    resolve_significance_threshold,
)


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run badge-listing tests against Railway DB.",
)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


class _Bag:
    """Track ids inserted by a single test so the fixture can clean up.

    Tests grab the bag, call ``add_meeting / add_item / add_badge`` on it
    (which open their own ``db()`` cm so writes commit and become visible
    to the service-under-test), and the fixture deletes everything by id
    at teardown.
    """

    def __init__(self, city_id: int, other_city_id: int):
        self.city_id = city_id
        self.other_city_id = other_city_id
        self.meeting_ids: list[int] = []
        self.item_ids: list[int] = []
        # (city_id, template_slug, original_override_jsonb_or_None)
        self.config_restore: list[tuple[int, str, str | None]] = []

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
        kind: str | None = None,
    ) -> None:
        if kind is None:
            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT kind FROM priority_badge_templates WHERE slug = %s",
                        (badge_slug,),
                    )
                    row = cur.fetchone()
            assert row is not None, f"unknown template {badge_slug}"
            kind = row[0]
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agenda_item_badges
                      (agenda_item_id, city_id, badge_slug, kind,
                       confidence, source)
                    VALUES (%s, %s, %s, %s, %s, 'deterministic')
                    """,
                    (item_id, city_id, badge_slug, kind, confidence),
                )

    def override_min_significance(
        self, city_id: int, template_slug: str, value: int
    ) -> None:
        """Set ``min_significance`` on the city's config row, remembering
        the original ``matcher_hints_override`` so teardown can restore it.
        """
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT matcher_hints_override::text
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
                self.config_restore.append((city_id, template_slug, row[0]))
                cur.execute(
                    """
                    UPDATE priority_badges_config
                    SET matcher_hints_override = %s::jsonb
                    WHERE city_id = %s AND template_slug = %s
                    """,
                    (
                        f'{{"min_significance": {value}}}',
                        city_id,
                        template_slug,
                    ),
                )

    # -- teardown -------------------------------------------------------------

    def cleanup(self) -> None:
        with db() as conn:
            with conn.cursor() as cur:
                # Restore overrides first (idempotent regardless of order).
                for city_id, slug, original in self.config_restore:
                    cur.execute(
                        """
                        UPDATE priority_badges_config
                        SET matcher_hints_override = %s::jsonb
                        WHERE city_id = %s AND template_slug = %s
                        """,
                        (original, city_id, slug),
                    )
                # Badges cascade-delete with agenda_items, but explicit
                # delete keeps the test loud if the FK ever changes.
                if self.item_ids:
                    cur.execute(
                        "DELETE FROM agenda_item_badges WHERE agenda_item_id = ANY(%s)",
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
    """Yield a clean ``_Bag`` for the test. Migrations are applied on
    entry; data inserted through the bag is deleted on exit.
    """
    with db() as conn:
        apply_migrations(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM municipalities WHERE slug = 'birmingham'"
            )
            row = cur.fetchone()
            assert row is not None, (
                "Birmingham must be seeded by migration 002"
            )
            city_id = row[0]

            cur.execute(
                "SELECT id FROM municipalities "
                "WHERE slug != 'birmingham' LIMIT 1"
            )
            other = cur.fetchone()
            if other is None:
                cur.execute(
                    """
                    INSERT INTO municipalities
                      (slug, name, state, council_type, active)
                    VALUES ('test-other-city', 'Test Other City', 'AL',
                            'city_council', TRUE)
                    RETURNING id
                    """
                )
                other_city_id = cur.fetchone()[0]
            else:
                other_city_id = other[0]

    b = _Bag(city_id, other_city_id)
    try:
        yield b
    finally:
        b.cleanup()


# ---------------------------------------------------------------------------
# Helper: resolve_significance_threshold
# ---------------------------------------------------------------------------


def test_resolve_threshold_policy_returns_min_significance(bag):
    # blight_accountability seeds with min_significance=3 in migration 013
    assert resolve_significance_threshold(
        bag.city_id, "blight_accountability"
    ) == 3


def test_resolve_threshold_process_returns_none(bag):
    # hidden_on_consent is a process badge — never gated
    assert (
        resolve_significance_threshold(bag.city_id, "hidden_on_consent")
        is None
    )


def test_resolve_threshold_unknown_slug_returns_none(bag):
    assert resolve_significance_threshold(bag.city_id, "no_such_badge") is None


def test_resolve_threshold_honors_city_override(bag):
    bag.override_min_significance(bag.city_id, "blight_accountability", 7)
    assert resolve_significance_threshold(
        bag.city_id, "blight_accountability"
    ) == 7


# ---------------------------------------------------------------------------
# list_items_by_badge — happy path + ordering
# ---------------------------------------------------------------------------


def test_happy_path_returns_items_with_badge_in_city(bag):
    m = bag.add_meeting(bag.city_id, "2026-04-15")
    a = bag.add_item(m, title="Demolition order", significance_score=5)
    b = bag.add_item(m, title="Unrelated item", significance_score=5)
    bag.add_badge(a, bag.city_id, "blight_accountability", confidence=1.0)
    # b has no badge — should be excluded

    items = list_items_by_badge(bag.city_id, "blight_accountability")
    ids = [it.id for it in items]
    assert a in ids
    assert b not in ids


def test_orders_by_date_desc_then_dollars_desc_nulls_last(bag):
    m_old = bag.add_meeting(bag.city_id, "2026-01-10")
    m_new = bag.add_meeting(bag.city_id, "2026-04-20")
    big = bag.add_item(
        m_new, title="Big", dollars_amount=1_000_000, significance_score=5
    )
    small = bag.add_item(
        m_new, title="Small", dollars_amount=10_000, significance_score=5
    )
    null_dollars = bag.add_item(
        m_new, title="No dollars", dollars_amount=None, significance_score=5
    )
    older = bag.add_item(
        m_old, title="Older", dollars_amount=500_000_000, significance_score=5
    )
    for i in (big, small, null_dollars, older):
        bag.add_badge(i, bag.city_id, "blight_accountability", confidence=1.0)

    items = list_items_by_badge(bag.city_id, "blight_accountability")
    # Filter to just the items this test created — other tests may have
    # left rows around if a previous run aborted before teardown.
    test_ids = {big, small, null_dollars, older}
    ordered = [it.id for it in items if it.id in test_ids]
    assert ordered == [big, small, null_dollars, older]


# ---------------------------------------------------------------------------
# Confidence floor
# ---------------------------------------------------------------------------


def test_confidence_floor_default_excludes_below_06(bag):
    m = bag.add_meeting(bag.city_id, "2026-04-15")
    high = bag.add_item(m, title="High conf", significance_score=5)
    low = bag.add_item(m, title="Low conf", significance_score=5)
    bag.add_badge(high, bag.city_id, "blight_accountability", confidence=1.0)
    bag.add_badge(low, bag.city_id, "blight_accountability", confidence=0.4)

    ids = [
        it.id
        for it in list_items_by_badge(bag.city_id, "blight_accountability")
    ]
    assert high in ids
    assert low not in ids


def test_confidence_floor_zero_includes_low_confidence(bag):
    m = bag.add_meeting(bag.city_id, "2026-04-15")
    low = bag.add_item(m, title="Low conf", significance_score=5)
    bag.add_badge(low, bag.city_id, "blight_accountability", confidence=0.4)

    ids = [
        it.id
        for it in list_items_by_badge(
            bag.city_id, "blight_accountability", min_confidence=0.0
        )
    ]
    assert low in ids


# ---------------------------------------------------------------------------
# Significance gate (policy badges)
# ---------------------------------------------------------------------------


def test_significance_gate_excludes_low_sig_policy_default(bag):
    m = bag.add_meeting(bag.city_id, "2026-04-15")
    above = bag.add_item(m, title="Sig 5", significance_score=5)
    below = bag.add_item(m, title="Sig 2", significance_score=2)
    bag.add_badge(above, bag.city_id, "blight_accountability", confidence=1.0)
    bag.add_badge(below, bag.city_id, "blight_accountability", confidence=1.0)

    ids = [
        it.id
        for it in list_items_by_badge(bag.city_id, "blight_accountability")
    ]
    assert above in ids
    assert below not in ids


def test_include_low_significance_disables_policy_gate(bag):
    m = bag.add_meeting(bag.city_id, "2026-04-15")
    below = bag.add_item(m, title="Sig 1", significance_score=1)
    bag.add_badge(below, bag.city_id, "blight_accountability", confidence=1.0)

    ids = [
        it.id
        for it in list_items_by_badge(
            bag.city_id, "blight_accountability",
            include_low_significance=True,
        )
    ]
    assert below in ids


def test_process_badge_has_no_significance_gate(bag):
    m = bag.add_meeting(bag.city_id, "2026-04-15")
    low_sig = bag.add_item(m, title="Sig 1", significance_score=1)
    null_sig = bag.add_item(m, title="Sig NULL", significance_score=None)
    bag.add_badge(low_sig, bag.city_id, "hidden_on_consent", confidence=1.0)
    bag.add_badge(null_sig, bag.city_id, "hidden_on_consent", confidence=1.0)

    # Process badges always-on; both should appear regardless of the flag.
    for flag in (False, True):
        ids = [
            it.id
            for it in list_items_by_badge(
                bag.city_id, "hidden_on_consent",
                include_low_significance=flag,
            )
        ]
        assert low_sig in ids
        assert null_sig in ids


# ---------------------------------------------------------------------------
# processing_status filter
# ---------------------------------------------------------------------------


def test_processing_status_pending_excluded(bag):
    m = bag.add_meeting(bag.city_id, "2026-04-15")
    completed = bag.add_item(
        m, title="Done", significance_score=5,
        processing_status="completed",
    )
    pending = bag.add_item(
        m, title="Pending", significance_score=5,
        processing_status="pending",
    )
    bag.add_badge(
        completed, bag.city_id, "blight_accountability", confidence=1.0
    )
    bag.add_badge(
        pending, bag.city_id, "blight_accountability", confidence=1.0
    )

    ids = [
        it.id
        for it in list_items_by_badge(bag.city_id, "blight_accountability")
    ]
    assert completed in ids
    assert pending not in ids


# ---------------------------------------------------------------------------
# City scoping
# ---------------------------------------------------------------------------


def test_other_city_items_not_returned(bag):
    m_bhm = bag.add_meeting(bag.city_id, "2026-04-15")
    m_other = bag.add_meeting(bag.other_city_id, "2026-04-15")
    bhm_item = bag.add_item(m_bhm, title="BHM", significance_score=5)
    other_item = bag.add_item(m_other, title="Other", significance_score=5)
    bag.add_badge(
        bhm_item, bag.city_id, "blight_accountability", confidence=1.0
    )
    # Note: agenda_item_badges has its own city_id column, so we tag
    # other_item to the other city — exactly how production would.
    bag.add_badge(
        other_item, bag.other_city_id, "blight_accountability",
        confidence=1.0,
    )

    ids = [
        it.id
        for it in list_items_by_badge(bag.city_id, "blight_accountability")
    ]
    assert bhm_item in ids
    assert other_item not in ids


# ---------------------------------------------------------------------------
# Cross-filter
# ---------------------------------------------------------------------------


def test_cross_filter_single_slug_requires_both_badges(bag):
    m = bag.add_meeting(bag.city_id, "2026-04-15")
    both = bag.add_item(m, title="Both badges", significance_score=5)
    only_primary = bag.add_item(
        m, title="Only blight", significance_score=5
    )
    bag.add_badge(both, bag.city_id, "blight_accountability", confidence=1.0)
    bag.add_badge(both, bag.city_id, "hidden_on_consent", confidence=1.0)
    bag.add_badge(
        only_primary, bag.city_id, "blight_accountability", confidence=1.0
    )

    ids = [
        it.id
        for it in list_items_by_badge(
            bag.city_id,
            "blight_accountability",
            cross_filter_slugs=("hidden_on_consent",),
        )
    ]
    assert both in ids
    assert only_primary not in ids


def test_cross_filter_multiple_slugs_and_semantics(bag):
    m = bag.add_meeting(bag.city_id, "2026-04-15")
    all_three = bag.add_item(m, title="3 badges", significance_score=5)
    two_of_three = bag.add_item(
        m, title="missing legal_settlement", significance_score=5
    )
    bag.add_badge(
        all_three, bag.city_id, "blight_accountability", confidence=1.0
    )
    bag.add_badge(all_three, bag.city_id, "hidden_on_consent", confidence=1.0)
    bag.add_badge(all_three, bag.city_id, "legal_settlement", confidence=1.0)
    bag.add_badge(
        two_of_three, bag.city_id, "blight_accountability", confidence=1.0
    )
    bag.add_badge(
        two_of_three, bag.city_id, "hidden_on_consent", confidence=1.0
    )

    ids = [
        it.id
        for it in list_items_by_badge(
            bag.city_id,
            "blight_accountability",
            cross_filter_slugs=("hidden_on_consent", "legal_settlement"),
        )
    ]
    assert all_three in ids
    assert two_of_three not in ids


def test_empty_cross_filter_no_extra_constraint(bag):
    m = bag.add_meeting(bag.city_id, "2026-04-15")
    item = bag.add_item(m, title="Just primary", significance_score=5)
    bag.add_badge(item, bag.city_id, "blight_accountability", confidence=1.0)

    ids_default = {
        it.id
        for it in list_items_by_badge(bag.city_id, "blight_accountability")
    }
    ids_explicit = {
        it.id
        for it in list_items_by_badge(
            bag.city_id, "blight_accountability", cross_filter_slugs=()
        )
    }
    assert item in ids_default
    assert ids_default == ids_explicit


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_pagination_limit_offset(bag):
    # 5 items same date, descending dollar amounts so the ORDER BY is
    # deterministic and we don't lean on insert order.
    m = bag.add_meeting(bag.city_id, "2026-04-15")
    ids_in_order = []
    for dollars in (5_000_000, 4_000_000, 3_000_000, 2_000_000, 1_000_000):
        i = bag.add_item(
            m,
            title=f"Item ${dollars}",
            dollars_amount=dollars,
            significance_score=5,
        )
        bag.add_badge(i, bag.city_id, "blight_accountability", confidence=1.0)
        ids_in_order.append(i)

    page = list_items_by_badge(
        bag.city_id, "blight_accountability", limit=2, offset=2
    )
    # Filter to this test's ids in case prior tests left rows on the
    # same date (their ORDER tie-break depends on dollars too).
    test_id_set = set(ids_in_order)
    filtered = [it.id for it in page if it.id in test_id_set]
    # We asked for items 3-4 (zero-indexed 2,3). With this test's items
    # being the only ones in the test_id_set, they're the slice [2:4].
    assert filtered == ids_in_order[2:4]


# ---------------------------------------------------------------------------
# Unknown slug
# ---------------------------------------------------------------------------


def test_unknown_badge_slug_returns_empty(bag):
    items = list_items_by_badge(bag.city_id, "this_slug_does_not_exist")
    assert items == []


# ---------------------------------------------------------------------------
# Return type sanity
# ---------------------------------------------------------------------------


def test_return_type_is_agenda_item(bag):
    m = bag.add_meeting(bag.city_id, "2026-04-15")
    i = bag.add_item(
        m, title="Sample", dollars_amount=12345, significance_score=5
    )
    bag.add_badge(i, bag.city_id, "blight_accountability", confidence=1.0)

    items = list_items_by_badge(bag.city_id, "blight_accountability")
    matching = [it for it in items if it.id == i]
    assert matching, "expected the freshly-inserted item to appear"
    item = matching[0]
    assert isinstance(item, AgendaItem)
    assert item.title == "Sample"
    assert item.dollars_amount == Decimal("12345")
    assert item.processing_status == "completed"
