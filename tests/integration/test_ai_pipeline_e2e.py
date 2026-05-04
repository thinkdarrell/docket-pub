"""End-to-end: seed mixed meetings/items, run worker, verify outcomes + ai_runs."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from docket.ai.pricing import Usage
from docket.ai.results import ItemAIResult, MeetingAIResult
from docket.ai.worker import run_once
from docket.db import db


@pytest.fixture
def seeded_e2e():
    state = {"meetings": [], "items": []}
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO municipalities (slug, name, state, adapter_class, active)
                VALUES ('test_e2e', 'Test E2E', 'AL', 'granicus', TRUE)
                ON CONFLICT (slug) DO UPDATE SET active=TRUE RETURNING id
            """)
            state["muni"] = cur.fetchone()[0]

            for n in range(5):
                cur.execute("""
                    INSERT INTO meetings (municipality_id, meeting_type, meeting_date, source_url, title)
                    VALUES (%s, 'Council', CURRENT_DATE - %s, 'x', %s) RETURNING id
                """, (state["muni"], n, f"test_e2e meeting {n}"))
                m_id = cur.fetchone()[0]
                state["meetings"].append(m_id)
                if n == 4:
                    continue   # meeting #4 is empty (no items)
                for k in range(4):
                    cur.execute("""
                        INSERT INTO agenda_items (meeting_id, title, is_consent, created_at)
                        VALUES (%s, %s, %s, NOW() - INTERVAL '1 hour') RETURNING id
                    """, (m_id, f"Item {n}-{k}", k % 2 == 0))
                    state["items"].append(cur.fetchone()[0])
        conn.commit()
    yield state
    with db() as conn:
        with conn.cursor() as cur:
            if state["items"]:
                cur.execute("DELETE FROM agenda_items WHERE id = ANY(%s)", (state["items"],))
            if state["meetings"]:
                cur.execute("DELETE FROM meetings WHERE id = ANY(%s)", (state["meetings"],))
            cur.execute("DELETE FROM municipalities WHERE id = %s", (state["muni"],))
            cur.execute("DELETE FROM ai_runs WHERE notes LIKE 'test_e2e_%%'")
        conn.commit()


def _stub_item():
    return ItemAIResult(
        is_substantive=True,
        significance_rationale="r", significance_score=5.0,
        consent_placement_rationale="r", consent_placement_score=5.0,
        summary="ok", confidence="high",
    ), Usage(100, 0, 0, 50)


def _stub_meeting(item_summaries):
    return MeetingAIResult(
        is_substantive=True,
        substantive_item_count=len(item_summaries),
        executive_summary="meeting ok",
        phase="provisional",
        confidence="high",
    ), Usage(500, 0, 0, 100)


def test_end_to_end(seeded_e2e, monkeypatch):
    fake_client = MagicMock()
    fake_client.item_model = "claude-haiku-4-5-20251001"
    fake_client.meeting_model = "claude-sonnet-4-6"
    fake_client.summarize_item.side_effect = lambda ctx: _stub_item()
    fake_client.summarize_meeting.side_effect = lambda ctx: _stub_meeting(list(ctx.distinctive_items))

    monkeypatch.setattr("docket.ai.worker._make_client", lambda: fake_client)
    # Raise the batch cap so our seeded rows (highest IDs in a large DB) are reached
    monkeypatch.setattr("docket.ai.worker.AI_MAX_BATCH_SIZE", 10_000)

    # Note: limit must be small enough not to claim other unprocessed items in
    # the local DB. Our seeded items are at the highest IDs, so a tight limit
    # equal to our 16 seeded items is correct, but other tests' leftover
    # unprocessed rows might appear in the claim. Use a limit that's at least
    # our seed count and assert on our specific rows.
    items_summary = run_once(stage="items", limit=10_000, notes="test_e2e_items", force_budget=True)
    # Must have processed at least our 16 seeded items
    assert items_summary.rows_processed >= 16
    assert items_summary.cost_usd > 0

    # Verify our seeded items have the canned summary
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM agenda_items
                 WHERE id = ANY(%s) AND summary = 'ok'
            """, (seeded_e2e["items"],))
            assert cur.fetchone()[0] == 16

    meetings_summary = run_once(stage="meetings", limit=10_000, notes="test_e2e_meetings", force_budget=True)
    # 5 of our seeded meetings (4 substantive + 1 empty); empty is auto-handled.
    # Meetings_summary.rows_processed could include meetings from other tests' leftovers.
    assert meetings_summary.rows_processed >= 5

    # The empty meeting should be marked is_substantive=false with no API call
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ai_metadata FROM meetings WHERE id = %s
            """, (seeded_e2e["meetings"][4],))
            md = cur.fetchone()[0]
    assert md["is_substantive"] is False
    assert md["substantive_item_count"] == 0
