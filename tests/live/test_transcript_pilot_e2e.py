# tests/live/test_transcript_pilot_e2e.py
"""LIVE: full worker pass on the pilot fixture; asserts the two hand-verified discrepancies (spec Section 6, live test 2). ~$1."""
import os

import pytest

from docket.ai.transcripts import pipeline as P
from docket.ai.transcripts.client import StructuredClient
from docket.ai.transcripts.guard import canonical_statute, normalize
from docket.db import db_cursor
from tests.support.transcript_fixtures import install_bundle, pilot_bundle

pytestmark = pytest.mark.live
DUMMY = "test-dummy-key-not-for-real-api-calls"


@pytest.fixture
def client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or key == DUMMY:
        pytest.skip("real ANTHROPIC_API_KEY not set")
    return StructuredClient(api_key=key)


def test_pilot_reproduces_sequence_and_wording_discrepancies(client):
    inst = install_bundle(pilot_bundle(), external_id="999015", status="uploaded")
    try:
        with db_cursor() as cur:   # the pilot clip has one cluster and 650 words; skip the fitness floor for this test
            cur.execute("UPDATE transcripts SET word_count=5000 WHERE id=%s", [inst.transcript_id])
        outcomes = P.run_for_meeting(inst.meeting_id, client=client, notes="live_pilot_e2e")
        assert outcomes == ["advanced", "advanced", "advanced"], outcomes
        with db_cursor() as cur:
            cur.execute("""SELECT category, severity, review_state, title, description, transcript_excerpt, minutes_excerpt, citation_match
                             FROM minutes_discrepancies WHERE meeting_id=%s AND review_state='proposed'""", [inst.meeting_id])
            rows = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT summary, detail FROM meeting_events WHERE meeting_id=%s AND source='transcript' AND event_type='statement'", [inst.meeting_id])
            statements = [dict(r) for r in cur.fetchall()]
        print("\n".join(f"{r['category']}/{r['severity']}/{r['citation_match']}: {r['title']}" for r in rows))
        cats = {r["category"] for r in rows if r["severity"] == "material"}
        assert "sequence" in cats and "wording" in cats
        wording = [r for r in rows if r["category"] == "wording" and r["severity"] == "material"]
        blob = " ".join(canonical_statute(" ".join(filter(None, [r["title"], r["description"], r["transcript_excerpt"]]))) for r in wording)
        assert "3625a7a4" in blob, "the (a)(4) ground must appear on the transcript side"
        assert any("pending litigation" in normalize(r["minutes_excerpt"] or r["description"]) for r in wording)
        assert all(r["citation_match"] in ("exact", "fuzzy") for r in rows if r["severity"] == "material")
        assert any("packet" in normalize(s["summary"] + " " + str(s["detail"])) for s in statements), "O'Quinn's 'not in the packet' statement"
    finally:
        inst.cleanup()
        with db_cursor() as cur:
            cur.execute("DELETE FROM ai_runs WHERE notes='live_pilot_e2e'")
