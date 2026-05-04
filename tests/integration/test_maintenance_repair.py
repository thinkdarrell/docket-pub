"""Integration tests for repair_empty_agendas.

These tests seed real municipality + meeting + processing_status rows,
run the repair service, and assert state — same pattern as the existing
test_ai_pipeline_e2e.py fixtures.
"""

from datetime import date, timedelta

import pytest

from docket.db import db
from docket.services.maintenance import repair_empty_agendas


@pytest.fixture
def seeded_repair():
    """Seed a test municipality and a mix of meetings exercising every branch."""
    state: dict = {}
    with db() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO municipalities (slug, name, state, adapter_class, active)
            VALUES ('test_repair', 'Test Repair', 'AL', 'granicus', TRUE)
            ON CONFLICT (slug) DO UPDATE SET active = TRUE
            RETURNING id
        """)
        muni_id = cur.fetchone()[0]
        state["muni_id"] = muni_id

        # Helper to insert a meeting + processing_status in one go.
        def mk(title: str, *, days_ago: int, has_agenda_url: bool,
               agenda_scraped: bool, with_items: int) -> int:
            cur.execute("""
                INSERT INTO meetings (municipality_id, meeting_type, meeting_date,
                                       source_url, title, agenda_url)
                VALUES (%s, 'Council', %s, 'x', %s, %s) RETURNING id
            """, (muni_id, date.today() - timedelta(days=days_ago),
                   title, "http://x" if has_agenda_url else None))
            m_id = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO processing_status (meeting_id, agenda_items_scraped, last_processed)
                VALUES (%s, %s, NOW())
            """, (m_id, agenda_scraped))
            for i in range(with_items):
                cur.execute("""
                    INSERT INTO agenda_items (meeting_id, title)
                    VALUES (%s, %s)
                """, (m_id, f"item {i}"))
            return m_id

        state["repair_target"]      = mk("Regular Meeting",          days_ago=10,    has_agenda_url=True,  agenda_scraped=True,  with_items=0)
        state["cancelled"]          = mk("Regular Meeting Cancelled", days_ago=12,    has_agenda_url=True,  agenda_scraped=True,  with_items=0)
        state["has_items"]          = mk("Regular Meeting",          days_ago=14,    has_agenda_url=True,  agenda_scraped=True,  with_items=3)
        state["no_agenda_url"]      = mk("Special Meeting",          days_ago=16,    has_agenda_url=False, agenda_scraped=True,  with_items=0)
        state["outside_window"]     = mk("Old Meeting",              days_ago=600,   has_agenda_url=True,  agenda_scraped=True,  with_items=0)
        state["already_unscraped"]  = mk("Pending Meeting",          days_ago=18,    has_agenda_url=True,  agenda_scraped=False, with_items=0)
        conn.commit()

    yield state

    # Teardown — delete in reverse dependency order
    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM agenda_items WHERE meeting_id IN (SELECT id FROM meetings WHERE municipality_id = %s)", (state["muni_id"],))
        cur.execute("DELETE FROM processing_status WHERE meeting_id IN (SELECT id FROM meetings WHERE municipality_id = %s)", (state["muni_id"],))
        cur.execute("DELETE FROM meetings WHERE municipality_id = %s", (state["muni_id"],))
        cur.execute("DELETE FROM municipalities WHERE id = %s", (state["muni_id"],))
        conn.commit()


def _scraped_flag(meeting_id: int) -> bool:
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT agenda_items_scraped FROM processing_status WHERE meeting_id = %s",
                    (meeting_id,))
        return cur.fetchone()[0]


def test_repair_clears_target_meeting(seeded_repair):
    """A meeting with agenda_url, no items, scraped=TRUE, in window → cleared."""
    cleared = repair_empty_agendas()
    assert cleared >= 1  # other test data may exist; we only assert ours
    assert _scraped_flag(seeded_repair["repair_target"]) is False


def test_repair_skips_cancelled_meetings(seeded_repair):
    repair_empty_agendas()
    assert _scraped_flag(seeded_repair["cancelled"]) is True


def test_repair_skips_meetings_with_items(seeded_repair):
    repair_empty_agendas()
    assert _scraped_flag(seeded_repair["has_items"]) is True


def test_repair_skips_meetings_without_agenda_url(seeded_repair):
    repair_empty_agendas()
    assert _scraped_flag(seeded_repair["no_agenda_url"]) is True


def test_repair_only_within_18_month_window(seeded_repair):
    repair_empty_agendas()
    assert _scraped_flag(seeded_repair["outside_window"]) is True


def test_repair_leaves_already_unscraped_alone(seeded_repair):
    """Idempotent: meetings whose flag is already FALSE shouldn't be 'cleared' again."""
    repair_empty_agendas()
    assert _scraped_flag(seeded_repair["already_unscraped"]) is False
