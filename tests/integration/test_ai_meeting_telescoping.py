"""Meeting prompt context must contain item AI summaries (not raw titles)."""

from unittest.mock import MagicMock

import pytest

from docket.ai.client import AIClient
from docket.ai.contexts import MeetingContext
from docket.ai.pricing import Usage
from docket.ai.results import ItemAIResult, MeetingAIResult
from docket.ai.worker import run_once
from docket.db import db


@pytest.fixture
def seeded():
    state = {"items": []}
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO municipalities (slug, name, state, adapter_class, active)
                VALUES ('test_tel', 'Test', 'AL', 'granicus', TRUE)
                ON CONFLICT (slug) DO UPDATE SET active=TRUE RETURNING id
            """)
            state["muni"] = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO meetings (municipality_id, meeting_type, meeting_date, source_url, title)
                VALUES (%s, 'C', CURRENT_DATE, 'x', 'test_tel meeting') RETURNING id
            """, (state["muni"],))
            state["meeting"] = cur.fetchone()[0]
            for t in ["Authorize $4.2M road contract", "Approve 3-year IT support agreement"]:
                cur.execute("""
                    INSERT INTO agenda_items (meeting_id, title, is_consent, created_at)
                    VALUES (%s, %s, FALSE, NOW() - INTERVAL '1 hour') RETURNING id
                """, (state["meeting"], t))
                state["items"].append(cur.fetchone()[0])
        conn.commit()
    yield state
    with db() as conn:
        with conn.cursor() as cur:
            if state["items"]:
                cur.execute("DELETE FROM agenda_items WHERE id = ANY(%s)", (state["items"],))
            cur.execute("DELETE FROM meetings WHERE id = %s", (state["meeting"],))
            cur.execute("DELETE FROM municipalities WHERE id = %s", (state["muni"],))
            cur.execute("DELETE FROM ai_runs WHERE notes LIKE 'test_tel_%%'")
        conn.commit()


def test_meeting_prompt_includes_item_summaries(seeded, monkeypatch):
    """Telescoping: the meeting prompt sees ITEM SUMMARIES, not raw titles."""
    captured: list[MeetingContext] = []

    item_summaries = [
        "Approves $4.2M road resurfacing contract.",
        "Authorizes 3-year IT support agreement.",
    ]

    def fake_summarize_item(self, ctx):
        idx = 0 if "road" in ctx.title.lower() else 1
        return ItemAIResult(
            is_substantive=True,
            significance_rationale="r", significance_score=5.0,
            consent_placement_rationale="r", consent_placement_score=5.0,
            summary=item_summaries[idx], confidence="high",
        ), Usage(100, 0, 0, 50)

    def fake_summarize_meeting(self, ctx):
        captured.append(ctx)
        return MeetingAIResult(
            is_substantive=True, substantive_item_count=2,
            executive_summary="ok", phase="provisional", confidence="high",
        ), Usage(500, 0, 0, 100)

    monkeypatch.setattr(AIClient, "summarize_item", fake_summarize_item)
    monkeypatch.setattr(AIClient, "summarize_meeting", fake_summarize_meeting)
    monkeypatch.setattr("docket.ai.client.ANTHROPIC_API_KEY", "test-key", raising=False)
    # Also patch worker's import path in case it's been bound
    monkeypatch.setattr("docket.ai.worker.ANTHROPIC_API_KEY", "test-key", raising=False)
    # Raise the batch cap so our seeded rows (highest IDs in a large DB) are reached
    monkeypatch.setattr("docket.ai.worker.AI_MAX_BATCH_SIZE", 10_000)

    run_once(stage="items", limit=10_000, notes="test_tel_items", force_budget=True)
    run_once(stage="meetings", limit=10_000, notes="test_tel_meetings", force_budget=True)

    # Find the captured ctx for OUR meeting (others may have been captured too)
    our_ctx = next((c for c in captured if c.meeting_id == seeded["meeting"]), None)
    assert our_ctx is not None, f"Our meeting was not summarized; captured {len(captured)} other meetings"

    rendered = our_ctx.render_user_prompt()
    assert "Approves $4.2M road resurfacing contract." in rendered
    assert "Authorizes 3-year IT support agreement." in rendered
    # Crucially, the raw titles must NOT appear in the meeting prompt
    assert "Authorize $4.2M road contract" not in rendered
