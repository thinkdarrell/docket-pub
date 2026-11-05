# tests/live/test_transcript_cards_live.py
"""LIVE: the search-card stage on meeting 2543's real rows, one model call (decisions 0027 and 0028).

Run, with a real key, on a disposable database:

    DATABASE_URL=$(tools/test-db) ANTHROPIC_API_KEY=<key> venv/bin/python -m pytest -m live \
        tests/live/test_transcript_cards_live.py -v -s -p no:cacheprovider; tools/test-db --drop

It prints the stage's report line: how many placed items were carded, how many
spoken details the citation guard kept, re-pointed, and dropped, how many
starts moved, the tokens, and the dollars. Plan:
plans/active/search-finds-what-was-said.md (M4, operator step 1).
"""
import os

import pytest

from docket.ai.transcripts import pipeline as P
from docket.ai.transcripts.client import StructuredClient
from docket.ai.transcripts.guard import find_citation
from docket.db import db_cursor
from tests.support.transcript_fixtures import install_bundle, load_bundle

pytestmark = pytest.mark.live

DUMMY = "test-dummy-key-not-for-real-api-calls"
NOTES = "live_cards"
NEIGHBOURS = 2   # a quote may sit in its cited segment or the two on either side


@pytest.fixture
def client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or key == DUMMY:
        pytest.skip("real ANTHROPIC_API_KEY not set")
    return StructuredClient(api_key=key)


def test_meeting_2543_gets_cards_whose_quotes_are_in_the_transcript(client):
    from docket.ai.transcripts import cards as C  # inside the test: the runner is M4's

    inst = install_bundle(load_bundle("transcript_2543"), external_id="999544", status="events_extracted")
    try:
        P.assign_index_points(inst.transcript_id, inst.meeting_id)
        summary = C.run_cards(limit=1, meeting_ids=[inst.meeting_id], notes=NOTES, client=client)
        print("\n" + "\n".join(summary.reports))
        with db_cursor() as cur:
            cur.execute("SELECT status, last_error, counts FROM transcript_card_runs WHERE transcript_id = %s",
                        [inst.transcript_id])
            run = cur.fetchone()
            cur.execute("SELECT agenda_item_id, card FROM agenda_item_search_cards WHERE transcript_id = %s",
                        [inst.transcript_id])
            cards = [dict(r) for r in cur.fetchall()]
            cur.execute("""SELECT seq, text FROM transcript_segments
                            WHERE transcript_id = %s AND is_silence = FALSE ORDER BY seq""", [inst.transcript_id])
            spoken = [dict(r) for r in cur.fetchall()]
        assert run is not None and run["status"] == "done", run
        assert len(summary.reports) == 1 and summary.built == 1
        assert cards, "at least one card row"
        position = {s["seq"]: n for n, s in enumerate(spoken)}
        details = 0
        for card in cards:
            for d in card["card"]["spoken_details"]:
                at = position[d["seq"]]
                window = " ".join((s["text"] or "").strip() for s in spoken[max(0, at - NEIGHBOURS):at + NEIGHBOURS + 1])
                assert find_citation(d["quote"], window).kind != "missing", (card["agenda_item_id"], d)
                details += 1
        print(f"{len(cards)} cards, {details} spoken details, every quote found at its segment or beside it")
    finally:
        inst.cleanup()
        with db_cursor() as cur:
            cur.execute("DELETE FROM ai_runs WHERE notes = %s", [NOTES])
