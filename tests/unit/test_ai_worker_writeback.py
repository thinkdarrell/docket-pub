"""Tests for the worker's write-back of AI results to rows."""

import json

import pytest

from docket.ai.prompts import ITEM_PROMPT_VERSION
from docket.ai.results import ItemAIResult
from docket.ai.worker import write_item_result, mark_item_failed
from docket.db import db


@pytest.fixture
def seed_item():
    """Insert a fresh agenda item and return its id."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO municipalities (slug, name, state, adapter_class, active)
                VALUES ('test_wb', 'Test', 'AL', 'granicus', TRUE)
                ON CONFLICT (slug) DO UPDATE SET active = TRUE
                RETURNING id
            """)
            muni = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO meetings (municipality_id, meeting_type, meeting_date, source_url, title)
                VALUES (%s, 'C', CURRENT_DATE, 'x', 'test wb meeting')
                RETURNING id
            """, (muni,))
            m_id = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO agenda_items (meeting_id, title, is_consent)
                VALUES (%s, 'test', FALSE) RETURNING id
            """, (m_id,))
            item_id = cur.fetchone()[0]
        conn.commit()
    yield item_id
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM agenda_items WHERE id = %s", (item_id,))
            cur.execute("DELETE FROM meetings WHERE id IN (SELECT meeting_id FROM agenda_items WHERE id = %s)", (item_id,))
        conn.commit()


def test_write_item_result_substantive(seed_item):
    result = ItemAIResult(
        is_substantive=True,
        significance_rationale="r1", significance_score=7.5,
        consent_placement_rationale="r2", consent_placement_score=2.0,
        summary="A substantive item.",
        confidence="high",
    )
    with db() as conn:
        write_item_result(conn, seed_item, result, model="claude-haiku-4-5-20251001")
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT summary, significance_score, consent_placement_score,
                       ai_prompt_version, ai_generated_at, ai_metadata
                FROM agenda_items WHERE id = %s
            """, (seed_item,))
            row = cur.fetchone()
    assert row[0] == "A substantive item."
    assert float(row[1]) == 7.5
    assert float(row[2]) == 2.0
    assert row[3] == ITEM_PROMPT_VERSION
    assert row[4] is not None
    md = row[5]
    assert md["confidence"] == "high"
    assert md["is_substantive"] is True
    assert md["model"] == "claude-haiku-4-5-20251001"


def test_write_item_result_non_substantive(seed_item):
    result = ItemAIResult(
        is_substantive=False,
        significance_rationale="procedural", significance_score=None,
        consent_placement_rationale="n/a", consent_placement_score=None,
        summary="Motion to adjourn.",
        confidence="high",
    )
    with db() as conn:
        write_item_result(conn, seed_item, result, model="claude-haiku-4-5-20251001")
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT summary, significance_score, consent_placement_score, ai_prompt_version
                FROM agenda_items WHERE id = %s
            """, (seed_item,))
            row = cur.fetchone()
    assert row[0] == "Motion to adjourn."
    assert row[1] is None
    assert row[2] is None
    assert row[3] == ITEM_PROMPT_VERSION


def test_mark_item_failed_keeps_summary_null(seed_item):
    """Permanent failure: prompt_version bumped, summary remains NULL, confidence=low."""
    with db() as conn:
        mark_item_failed(conn, seed_item, "token cap exceeded")
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT summary, ai_prompt_version, ai_metadata
                FROM agenda_items WHERE id = %s
            """, (seed_item,))
            row = cur.fetchone()
    assert row[0] is None
    assert row[1] == ITEM_PROMPT_VERSION
    assert row[2]["confidence"] == "low"
    assert "error" in row[2]
