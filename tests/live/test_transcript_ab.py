# tests/live/test_transcript_ab.py
"""LIVE: the A/B harness runs both models on the 2543 fixture and writes a report (spec Section 6, live test 4). ~$0.25."""
import os

import pytest

from docket.ai.transcripts.ab import render_report, run_ab
from docket.ai.transcripts.client import StructuredClient
from docket.db import db_cursor
from tests.support.transcript_fixtures import install_bundle, load_bundle

pytestmark = pytest.mark.live
DUMMY = "test-dummy-key-not-for-real-api-calls"


def test_ab_runs_both_models_and_records_runs():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or key == DUMMY:
        pytest.skip("real ANTHROPIC_API_KEY not set")
    inst = install_bundle(load_bundle("transcript_2543"), status="compared")
    try:
        results = run_ab([inst.meeting_id], client=StructuredClient(api_key=key), notes_prefix="live_ab")
        report = render_report(results)
        print(report)
        assert results[0]["skipped"] is None and 0.0 <= results[0]["haiku"]["recall"] <= 1.0
        with db_cursor() as cur:
            cur.execute("SELECT model, cost_usd FROM ai_runs WHERE notes IN ('live_ab_sonnet', 'live_ab_haiku') ORDER BY id DESC LIMIT 2")
            rows = cur.fetchall()
        assert {r["model"] for r in rows} == {"claude-sonnet-5-5", "claude-haiku-4-5-20251001"} and all(r["cost_usd"] > 0 for r in rows)
        assert "Verdict" in report
    finally:
        inst.cleanup()
        with db_cursor() as cur:
            cur.execute("DELETE FROM ai_runs WHERE notes IN ('live_ab_sonnet', 'live_ab_haiku')")
