"""Test the worker run loop: claim, process, write back, accumulate ai_runs."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from docket.ai.pricing import Usage
from docket.ai.results import ItemAIResult
from docket.ai.worker import run_once
from docket.db import db


@pytest.fixture
def seed_two_items():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO municipalities (slug, name, state, adapter_class, active)
                VALUES ('test_run', 'Test', 'AL', 'granicus', TRUE)
                ON CONFLICT (slug) DO UPDATE SET active = TRUE RETURNING id
            """)
            muni = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO meetings (municipality_id, meeting_type, meeting_date, source_url, title)
                VALUES (%s, 'C', CURRENT_DATE, 'x', 'test run meeting') RETURNING id
            """, (muni,))
            m = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO agenda_items (meeting_id, title, is_consent, created_at)
                VALUES (%s, 'a', FALSE, NOW() - INTERVAL '1 hour') RETURNING id
            """, (m,))
            id1 = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO agenda_items (meeting_id, title, is_consent, created_at)
                VALUES (%s, 'b', FALSE, NOW() - INTERVAL '1 hour') RETURNING id
            """, (m,))
            id2 = cur.fetchone()[0]
        conn.commit()
    yield (m, id1, id2)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM agenda_items WHERE id IN (%s, %s)", (id1, id2))
            cur.execute("DELETE FROM meetings WHERE id = %s", (m,))
            cur.execute("DELETE FROM ai_runs WHERE notes LIKE 'test_run_%%'")
        conn.commit()


def _stub_item_result():
    return ItemAIResult(
        is_substantive=True,
        significance_rationale="r1", significance_score=5.0,
        consent_placement_rationale="r2", consent_placement_score=5.0,
        summary="ok", confidence="high",
    ), Usage(input_tokens=100, cache_creation_input_tokens=0,
             cache_read_input_tokens=0, output_tokens=50)


def test_run_once_processes_pending_items(seed_two_items, monkeypatch):
    _, id1, id2 = seed_two_items

    fake_client = MagicMock()
    # Use side_effect that ignores all positional args (run_once may pass different shapes)
    fake_client.summarize_item.side_effect = lambda ctx: _stub_item_result()
    fake_client.item_model = "claude-haiku-4-5-20251001"
    fake_client.meeting_model = "claude-sonnet-4-6"

    monkeypatch.setattr("docket.ai.worker._make_client", lambda: fake_client)

    # Use a tight LIMIT and rely on ID ordering — unprocessed items may exist
    # in the DB but ours are at the highest IDs, so a large LIMIT picks them up.
    summary = run_once(stage="items", limit=10000, notes="test_run_basic", force_budget=True)

    # Our two items must be processed; assertion focuses on them, not on total
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT summary FROM agenda_items WHERE id = %s", (id1,))
            assert cur.fetchone()[0] == "ok"
            cur.execute("SELECT summary FROM agenda_items WHERE id = %s", (id2,))
            assert cur.fetchone()[0] == "ok"
            cur.execute("SELECT cost_usd, rows_processed FROM ai_runs WHERE notes = 'test_run_basic'")
            row = cur.fetchone()
            assert row[1] >= 2
            assert float(row[0]) > 0


def test_run_once_refuses_over_budget(seed_two_items, monkeypatch):
    """If today's spend exceeds AI_DAILY_BUDGET_USD, run_once raises unless force_budget=True."""
    from docket.ai.worker import BudgetExceededError
    monkeypatch.setattr("docket.ai.worker.AI_DAILY_BUDGET_USD", 0.001)

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ai_runs (started_at, finished_at, stage, model, cost_usd)
                VALUES (NOW(), NOW(), 'items', 'claude-haiku-4-5-20251001', 1.0)
            """)
        conn.commit()

    try:
        with pytest.raises(BudgetExceededError):
            run_once(stage="items", limit=10, notes="test_run_budget")
    finally:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ai_runs WHERE cost_usd = 1.0 AND notes IS NULL")
            conn.commit()


def test_run_once_force_budget_overrides(seed_two_items, monkeypatch):
    from docket.ai.worker import BudgetExceededError
    monkeypatch.setattr("docket.ai.worker.AI_DAILY_BUDGET_USD", 0.001)

    fake_client = MagicMock()
    fake_client.summarize_item.side_effect = lambda ctx: _stub_item_result()
    fake_client.item_model = "claude-haiku-4-5-20251001"
    fake_client.meeting_model = "claude-sonnet-4-6"
    monkeypatch.setattr("docket.ai.worker._make_client", lambda: fake_client)

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ai_runs (started_at, finished_at, stage, model, cost_usd)
                VALUES (NOW(), NOW(), 'items', 'claude-haiku-4-5-20251001', 1.0)
            """)
        conn.commit()

    try:
        summary = run_once(stage="items", limit=10000, notes="test_run_force",
                           force_budget=True)
        assert summary.rows_processed >= 2
    finally:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ai_runs WHERE cost_usd = 1.0 AND notes IS NULL")
            conn.commit()
