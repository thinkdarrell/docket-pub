# tests/live/test_transcript_chaotic.py
"""LIVE: public-comment stretch of the real 2543 transcript yields no action events (spec Section 6, live test 3). ~$0.15.

Set CHAOTIC_SEQ_RANGE="<first>-<last>" to the public-comment segment range of meeting 2543
(find it on the transcript page); the test skips when unset.
"""
import os

import pytest

from docket.ai.transcripts import events as EV
from docket.ai.transcripts.client import StructuredClient
from docket.db import db_cursor
from tests.support.transcript_fixtures import install_bundle, load_bundle

pytestmark = pytest.mark.live
DUMMY = "test-dummy-key-not-for-real-api-calls"


def test_public_comment_slice_has_no_fabricated_actions():
    key, rng = os.environ.get("ANTHROPIC_API_KEY"), os.environ.get("CHAOTIC_SEQ_RANGE")
    if not key or key == DUMMY or not rng:
        pytest.skip("needs a real ANTHROPIC_API_KEY and CHAOTIC_SEQ_RANGE")
    lo, hi = (int(x) for x in rng.split("-"))
    b = load_bundle("transcript_2543")
    b.segments = [s for s in b.segments if lo <= s["seq"] <= hi]
    b.speakers = [sp for sp in b.speakers if sp["cluster_label"] in {s["cluster_label"] for s in b.segments}]
    inst = install_bundle(b, status="speakers_resolved")
    try:
        with db_cursor() as cur:
            cur.execute("UPDATE meetings SET minutes_url=NULL WHERE id=%s", [inst.meeting_id])
        claim = {"id": inst.transcript_id, "meeting_id": inst.meeting_id, "status": "speakers_resolved", "version": 1, "word_count": 5000, "compare_skipped_reason": None}
        EV.run_events_stage(claim, client=StructuredClient(api_key=key))
        with db_cursor() as cur:
            cur.execute("SELECT event_type, count(*) AS n FROM meeting_events WHERE meeting_id=%s GROUP BY 1", [inst.meeting_id])
            counts = {r["event_type"]: r["n"] for r in cur.fetchall()}
        print(counts)
        assert not ({"motion", "vote", "amendment", "executive_session_motion", "item_deferred"} & set(counts)), counts
    finally:
        inst.cleanup()
