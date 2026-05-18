"""Bumping ITEM_PROMPT_VERSION re-runs items; meetings auto-cascade afterward."""

from unittest.mock import MagicMock

import pytest

from docket.ai.client import AIClient
from docket.ai.pricing import Usage
from docket.ai.results import ItemAIResult, MeetingAIResult
from docket.db import db


@pytest.fixture
def seeded_minor():
    state = {"items": []}
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO municipalities (slug, name, state, adapter_class, active)
                VALUES ('test_bump', 'T', 'AL', 'granicus', TRUE)
                ON CONFLICT (slug) DO UPDATE SET active=TRUE RETURNING id
            """)
            state["muni"] = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO meetings (municipality_id, meeting_type, meeting_date, source_url, title)
                VALUES (%s, 'C', CURRENT_DATE, 'x', 'test_bump meeting') RETURNING id
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
            cur.execute("DELETE FROM ai_runs WHERE notes LIKE 'bump_%%'")
        conn.commit()


def test_item_version_bump_recascades(seeded_minor, monkeypatch):
    """Version-agnostic: read the live constants, run "before", bump by one, run "after"."""
    iid = seeded_minor["items"][0]
    mid = seeded_minor["meeting"]

    from docket.ai import prompts as prompts_mod
    item_v_before = prompts_mod.ITEM_PROMPT_VERSION
    meeting_v_before = prompts_mod.MEETING_PROMPT_VERSION
    item_v_after = item_v_before + 1
    meeting_v_after = meeting_v_before + 1

    def fake_item_before(self, ctx):
        return ItemAIResult(
            is_substantive=True, significance_rationale="r", significance_score=5.0,
            consent_placement_rationale="r", consent_placement_score=5.0,
            summary="before", confidence="high",
        ), Usage(100, 0, 0, 50)

    def fake_meeting_before(self, ctx):
        out = "m-before" if ctx.meeting_id == mid else "other"
        return MeetingAIResult(
            is_substantive=True, substantive_item_count=1,
            executive_summary=out, phase="provisional", confidence="high",
        ), Usage(500, 0, 0, 100), "completed"

    monkeypatch.setattr(AIClient, "summarize_item", fake_item_before)
    monkeypatch.setattr(AIClient, "summarize_meeting", fake_meeting_before)
    monkeypatch.setattr("docket.ai.client.ANTHROPIC_API_KEY", "test-key", raising=False)
    monkeypatch.setattr("docket.ai.worker.ANTHROPIC_API_KEY", "test-key", raising=False)
    monkeypatch.setattr("docket.ai.worker.AI_MAX_BATCH_SIZE", 10_000)

    from docket.ai import worker as worker_mod
    worker_mod.run_once(stage="items", limit=10_000, notes="bump_before", force_budget=True)
    worker_mod.run_once(stage="meetings", limit=10_000, notes="bump_beforem", force_budget=True)

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT summary, ai_prompt_version FROM agenda_items WHERE id = %s", (iid,))
            r = cur.fetchone()
            assert r[0] == "before" and r[1] == item_v_before
            cur.execute("SELECT executive_summary FROM meetings WHERE id = %s", (mid,))
            assert cur.fetchone()[0] == "m-before"

    # Bump constants in both places they're referenced
    monkeypatch.setattr("docket.ai.prompts.ITEM_PROMPT_VERSION", item_v_after)
    monkeypatch.setattr("docket.ai.prompts.MEETING_PROMPT_VERSION", meeting_v_after)
    monkeypatch.setattr("docket.ai.worker.ITEM_PROMPT_VERSION", item_v_after)
    monkeypatch.setattr("docket.ai.worker.MEETING_PROMPT_VERSION", meeting_v_after)

    def fake_item_after(self, ctx):
        return ItemAIResult(
            is_substantive=True, significance_rationale="r", significance_score=6.0,
            consent_placement_rationale="r", consent_placement_score=6.0,
            summary="after", confidence="high",
        ), Usage(100, 0, 0, 50)

    def fake_meeting_after(self, ctx):
        out = "m-after" if ctx.meeting_id == mid else "other"
        return MeetingAIResult(
            is_substantive=True, substantive_item_count=1,
            executive_summary=out, phase="provisional", confidence="high",
        ), Usage(500, 0, 0, 100), "completed"

    monkeypatch.setattr(AIClient, "summarize_item", fake_item_after)
    monkeypatch.setattr(AIClient, "summarize_meeting", fake_meeting_after)

    s_items = worker_mod.run_once(stage="items", limit=10_000, notes="bump_after", force_budget=True)
    assert s_items.rows_processed >= 1

    s_meetings = worker_mod.run_once(stage="meetings", limit=10_000, notes="bump_afterm", force_budget=True)
    assert s_meetings.rows_processed >= 1

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT summary, ai_prompt_version FROM agenda_items WHERE id = %s", (iid,))
            row = cur.fetchone()
            assert row[0] == "after"
            assert row[1] == item_v_after
            cur.execute("SELECT executive_summary, ai_prompt_version FROM meetings WHERE id = %s", (mid,))
            row = cur.fetchone()
            assert row[0] == "m-after"
            assert row[1] == meeting_v_after
