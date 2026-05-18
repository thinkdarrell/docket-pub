"""Verify provisional → adopted promotion overwrites the meeting summary."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from docket.ai.client import AIClient
from docket.ai.pricing import Usage
from docket.ai.results import ItemAIResult, MeetingAIResult
from docket.ai.worker import run_once
from docket.db import db


@pytest.fixture
def seeded_meeting():
    state = {"items": []}
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO municipalities (slug, name, state, adapter_class, active)
                VALUES ('test_phase', 'T', 'AL', 'granicus', TRUE)
                ON CONFLICT (slug) DO UPDATE SET active=TRUE RETURNING id
            """)
            state["muni"] = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO meetings (municipality_id, meeting_type, meeting_date, source_url, title)
                VALUES (%s, 'Council', CURRENT_DATE, 'x', 'test_phase meeting') RETURNING id
            """, (state["muni"],))
            state["meeting"] = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO agenda_items (meeting_id, title, is_consent, created_at)
                VALUES (%s, 'item', FALSE, NOW() - INTERVAL '1 hour') RETURNING id
            """, (state["meeting"],))
            state["items"].append(cur.fetchone()[0])
        conn.commit()
    yield state
    with db() as conn:
        with conn.cursor() as cur:
            if state["items"]:
                cur.execute("DELETE FROM agenda_items WHERE id = ANY(%s)", (state["items"],))
            cur.execute("DELETE FROM meetings WHERE id = %s", (state["meeting"],))
            cur.execute("DELETE FROM municipalities WHERE id = %s", (state["muni"],))
            cur.execute("DELETE FROM ai_runs WHERE notes LIKE 'phase_test_%%'")
        conn.commit()


def test_provisional_then_adopted(seeded_meeting, monkeypatch):
    m_id = seeded_meeting["meeting"]
    summaries = ["PROVISIONAL summary", "ADOPTED summary"]
    call_idx = {"n": 0}

    def fake_item(self, ctx):
        return ItemAIResult(
            is_substantive=True, significance_rationale="r", significance_score=5.0,
            consent_placement_rationale="r", consent_placement_score=5.0,
            summary="item ok", confidence="high",
        ), Usage(100, 0, 0, 50)

    def fake_meeting(self, ctx):
        # Only return our scripted summary for OUR meeting
        if ctx.meeting_id == m_id:
            out = summaries[min(call_idx["n"], 1)]
            call_idx["n"] += 1
        else:
            out = "other meeting summary"
        return MeetingAIResult(
            is_substantive=True, substantive_item_count=1,
            executive_summary=out, phase=ctx.phase, confidence="high",
        ), Usage(500, 0, 0, 100), "completed"

    monkeypatch.setattr(AIClient, "summarize_item", fake_item)
    monkeypatch.setattr(AIClient, "summarize_meeting", fake_meeting)
    monkeypatch.setattr("docket.ai.client.ANTHROPIC_API_KEY", "test-key", raising=False)
    monkeypatch.setattr("docket.ai.worker.ANTHROPIC_API_KEY", "test-key", raising=False)
    # Raise the batch cap so our seeded rows (highest IDs in a large DB) are reached
    monkeypatch.setattr("docket.ai.worker.AI_MAX_BATCH_SIZE", 10_000)

    # Phase 1: provisional
    run_once(stage="items", limit=10_000, notes="phase_test_items", force_budget=True)
    run_once(stage="meetings", limit=10_000, notes="phase_test_prov", force_budget=True)

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT executive_summary, ai_metadata FROM meetings WHERE id = %s", (m_id,))
            row = cur.fetchone()
    assert row[0] == "PROVISIONAL summary"
    assert row[1]["phase"] == "provisional"

    # Phase 2: simulate adoption sweep setting minutes_adopted_at
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE meetings SET minutes_adopted_at = %s WHERE id = %s",
                        (datetime.now(timezone.utc), m_id))
        conn.commit()

    run_once(stage="meetings", limit=10_000, notes="phase_test_adopt", force_budget=True)

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT executive_summary, ai_metadata FROM meetings WHERE id = %s", (m_id,))
            row = cur.fetchone()
    assert row[0] == "ADOPTED summary"
    assert row[1]["phase"] == "adopted"
