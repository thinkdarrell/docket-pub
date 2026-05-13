"""Tests for category_tally() — the all-time-indexed tally that
replaces the year-scoped category_kpis() for the v3 category landing.

Fixture: seeds a throwaway municipality + 4 v3-completed agenda items
across 3 months (Feb has 2 items, Jan + Mar have 1 each), each tagged
with the legal_settlement process badge.
"""
from __future__ import annotations

from decimal import Decimal

import psycopg2.extras
import pytest

from docket.db import db
from docket.services.query import category_tally


@pytest.fixture
def seeded_badge_city():
    """City + 4 v3-completed items across 3 months with legal_settlement
    badges. CASCADE on municipalities → meetings → agenda_items →
    agenda_item_badges handles cleanup.
    """
    _cleanup_test_tally_city()

    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO municipalities
                       (name, slug, state, adapter_class, adapter_config, active)
                   VALUES ('Test Tally City', 'test_tally', 'AL',
                           'TestAdapter', '{}'::jsonb, TRUE)
                   RETURNING id"""
            )
            city_id = cur.fetchone()["id"]

            ids = []
            for month, dollars in [(1, 50_000), (2, 100_000), (2, 250_000), (3, 500_000)]:
                cur.execute(
                    """INSERT INTO meetings
                           (municipality_id, title, meeting_date, meeting_type)
                       VALUES (%s, 'Test meeting', %s, 'council')
                       RETURNING id""",
                    (city_id, f"2026-0{month}-15"),
                )
                meeting_id = cur.fetchone()["id"]
                cur.execute(
                    """INSERT INTO agenda_items
                           (meeting_id, title, item_number, is_consent,
                            processing_status, ai_rewrite_version,
                            ai_confidence, dollars_amount)
                       VALUES (%s, 'Test item', '1', FALSE,
                               'completed', 3, 'high', %s)
                       RETURNING id""",
                    (meeting_id, dollars),
                )
                item_id = cur.fetchone()["id"]
                cur.execute(
                    """INSERT INTO agenda_item_badges
                           (agenda_item_id, city_id, badge_slug, kind,
                            confidence, source, status)
                       VALUES (%s, %s, 'legal_settlement', 'process',
                               1.0, 'deterministic', 'applied')""",
                    (item_id, city_id),
                )
                ids.append(item_id)
        conn.commit()

    yield {"city_id": city_id, "badge_slug": "legal_settlement", "item_ids": ids}

    _cleanup_test_tally_city(city_id=city_id)


def _cleanup_test_tally_city(city_id: int | None = None) -> None:
    """Tear down the test_tally city + dependents.

    The meetings→municipalities FK lacks ON DELETE CASCADE, so we
    delete in dependency order: badges → items → meetings →
    municipality.
    """
    with db() as conn:
        with conn.cursor() as cur:
            if city_id is None:
                cur.execute(
                    "SELECT id FROM municipalities WHERE slug = 'test_tally'"
                )
                row = cur.fetchone()
                if not row:
                    return
                city_id = row[0]
            cur.execute(
                """DELETE FROM agenda_item_badges
                   WHERE agenda_item_id IN (
                       SELECT ai.id FROM agenda_items ai
                       JOIN meetings m ON m.id = ai.meeting_id
                       WHERE m.municipality_id = %s
                   )""",
                (city_id,),
            )
            cur.execute(
                """DELETE FROM agenda_items
                   WHERE meeting_id IN (
                       SELECT id FROM meetings WHERE municipality_id = %s
                   )""",
                (city_id,),
            )
            cur.execute(
                "DELETE FROM meetings WHERE municipality_id = %s", (city_id,)
            )
            cur.execute("DELETE FROM municipalities WHERE id = %s", (city_id,))
        conn.commit()


class TestCategoryTally:
    def test_basic_counts(self, seeded_badge_city):
        tally = category_tally(seeded_badge_city["city_id"], seeded_badge_city["badge_slug"])
        assert tally["indexed_count"] == 4
        assert tally["total_dollars"] == Decimal("900000")
        assert tally["indexed_months"] == 3

    def test_peak_month_is_argmax(self, seeded_badge_city):
        tally = category_tally(seeded_badge_city["city_id"], seeded_badge_city["badge_slug"])
        peak = tally["peak_month"]
        assert peak is not None
        # February has 2 items, the most of any month
        assert peak["year_month"] == "2026-02"
        assert peak["items"] == 2
        assert peak["dollars"] == Decimal("350000")

    def test_empty_returns_zero_and_no_peak(self):
        tally = category_tally(99999, "nonexistent_slug")
        assert tally["indexed_count"] == 0
        assert tally["total_dollars"] == Decimal("0")
        assert tally["indexed_months"] == 0
        assert tally["peak_month"] is None
