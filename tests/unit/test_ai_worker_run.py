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


# --- meetings stage over v3 items ----------------------------------------
#
# The v3 item pipeline writes headline / why_it_matters, never the v2
# agenda_items.summary column. From the 2026-05-14 cutover until this
# fix the meeting stage saw every new meeting as empty.


@pytest.fixture
def seed_v3_meeting():
    """A far-future meeting (so newest-first claiming picks it first) with one
    substantive v3 item, one legacy v2 item and one procedural item."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO municipalities (slug, name, state, adapter_class, active)
                VALUES ('test_run_v3', 'Test', 'AL', 'granicus', TRUE)
                ON CONFLICT (slug) DO UPDATE SET active = TRUE RETURNING id
            """)
            muni = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO meetings (municipality_id, meeting_type, meeting_date, source_url, title)
                VALUES (%s, 'council', DATE '2099-06-01', 'x', 'test run v3 meeting') RETURNING id
            """, (muni,))
            m = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO agenda_items (meeting_id, title, is_consent, topic, processing_status,
                                          headline, why_it_matters, significance_score)
                VALUES (%s, 'Stadium lease', FALSE, 'contracts', 'completed',
                        'City signs 30-year stadium lease',
                        'Commits $12M a year of general fund money.', 8.5)
                RETURNING id
            """, (m,))
            v3_item = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO agenda_items (meeting_id, title, is_consent, topic, processing_status,
                                          summary, significance_score, ai_metadata)
                VALUES (%s, 'Paving contract', FALSE, 'contracts', 'completed',
                        'Legacy Haiku summary of a paving contract.', 7.0,
                        '{"is_substantive": true}'::jsonb)
                RETURNING id
            """, (m,))
            v2_item = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO agenda_items (meeting_id, title, is_consent, processing_status)
                VALUES (%s, 'Roll call', FALSE, 'procedural_skipped') RETURNING id
            """, (m,))
            proc_item = cur.fetchone()[0]
        conn.commit()
    yield m
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM agenda_items WHERE id IN (%s, %s, %s)",
                        (v3_item, v2_item, proc_item))
            cur.execute("DELETE FROM meetings WHERE id = %s", (m,))
            cur.execute("DELETE FROM ai_runs WHERE notes LIKE 'test_run_v3%%'")
        conn.commit()


def _meeting_client(captured):
    from docket.ai.results import MeetingAIResult

    def summarize(ctx):
        captured.append(ctx)
        result = MeetingAIResult(
            is_substantive=True, substantive_item_count=ctx.total_substantive_count,
            executive_summary="exec", phase=ctx.phase, confidence="high",
        )
        return result, Usage(100, 0, 0, 50), "completed"

    client = MagicMock()
    client.summarize_meeting.side_effect = summarize
    client.item_model = "claude-haiku-4-5-20251001"
    client.meeting_model = "claude-sonnet-4-6"
    return client


def test_run_once_meetings_reads_v3_items(seed_v3_meeting, monkeypatch):
    captured = []
    monkeypatch.setattr("docket.ai.worker._make_client", lambda: _meeting_client(captured))
    monkeypatch.setattr("docket.ai.worker.IMPACT_FIRST_ENABLED", True)

    run_once(stage="meetings", limit=1, notes="test_run_v3_items", force_budget=True)

    assert len(captured) == 1
    ctx = captured[0]
    assert ctx.meeting_id == seed_v3_meeting
    assert ctx.total_substantive_count == 2
    joined = "\n".join(ctx.distinctive_items)
    assert "City signs 30-year stadium lease" in joined
    assert "Commits $12M a year" in joined
    assert "Legacy Haiku summary" in joined
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT executive_summary FROM meetings WHERE id = %s", (seed_v3_meeting,))
            assert cur.fetchone()[0] == "exec"


def test_run_once_meetings_adopted_empty_meeting_leaves_queue(monkeypatch):
    """Adopted meeting, nothing to summarize, old summary present: the pass must
    record phase=adopted (so it isn't re-claimed tomorrow) and keep the summary."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO municipalities (slug, name, state, adapter_class, active)
                VALUES ('test_run_v3', 'Test', 'AL', 'granicus', TRUE)
                ON CONFLICT (slug) DO UPDATE SET active = TRUE RETURNING id
            """)
            muni = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO meetings (municipality_id, meeting_type, meeting_date, source_url, title,
                                      minutes_adopted_at, executive_summary, ai_metadata)
                VALUES (%s, 'council', DATE '2099-06-02', 'x', 'test run v3 empty',
                        NOW(), 'older summary', '{"phase": "provisional"}'::jsonb)
                RETURNING id
            """, (muni,))
            m = cur.fetchone()[0]
        conn.commit()
    captured = []
    monkeypatch.setattr("docket.ai.worker._make_client", lambda: _meeting_client(captured))
    monkeypatch.setattr("docket.ai.worker.IMPACT_FIRST_ENABLED", True)
    try:
        run_once(stage="meetings", limit=1, notes="test_run_v3_empty", force_budget=True)
        assert captured == []
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT executive_summary, ai_metadata FROM meetings WHERE id = %s", (m,))
                row = cur.fetchone()
        assert row[0] == "older summary"
        assert row[1]["phase"] == "adopted"
    finally:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM meetings WHERE id = %s", (m,))
                cur.execute("DELETE FROM ai_runs WHERE notes LIKE 'test_run_v3%%'")
            conn.commit()
