# tests/integration/test_compare_stage.py
"""Comparison stage on the pilot fixture with mocked judge/hunter answers."""
from unittest.mock import MagicMock

import pytest

from docket.ai.exceptions import TranscriptHeld
from docket.ai.pricing import Usage
from docket.ai.transcripts import compare as C
from docket.ai.transcripts.client import StructuredResult
from docket.ai.transcripts.pipeline import advance
from docket.config import DATABASE_URL
from docket.db import db_cursor
from tests.support.transcript_fixtures import install_bundle, pilot_bundle

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)


@pytest.fixture
def pilot():
    i = install_bundle(pilot_bundle(), external_id="999015", status="events_extracted")
    yield i
    i.cleanup()


def _seed_events(inst):
    """Hand-written timelines reproducing the pilot: exec session before the vote on video, after it in the minutes."""
    item = inst.item_ids[1501]
    with db_cursor() as cur:
        cur.execute("SELECT id, seq, start_s, text FROM transcript_segments WHERE transcript_id=%s ORDER BY seq", [inst.transcript_id])
        segs = cur.fetchall()
        exec_seg = next(s for s in segs if "executive session" in s["text"].lower())
        vote_seg = next(s for s in segs if "passes" in s["text"].lower())
        cur.execute("SELECT text FROM minutes_texts WHERE meeting_id=%s", [inst.meeting_id])
        mtext = cur.fetchone()["text"]
        adopted_off = mtext.index("said ordinance adopted") if "said ordinance adopted" in mtext else mtext.lower().index("ordinance adopted")
        exec_off = mtext.index("go into Executive Session")
        rows = [("transcript", 0, "motion", [item], None, exec_seg["start_s"] - 60, None, None, None, {"action": "approve"}),
                ("transcript", 1, "executive_session_motion", [item], None, exec_seg["start_s"], None, None, exec_seg["id"],
                 {"stated_reason": "security plans and measures", "statute_cite": "36, 25, a seven a four", "quote": exec_seg["text"]}),
                ("transcript", 2, "vote", [item], None, vote_seg["start_s"], None, None, vote_seg["id"],
                 {"result": "passed", "method": "voice", "quote": vote_seg["text"]}),
                ("minutes", 0, "motion", [item], None, None, 1, adopted_off - 200, None, {"action": "approve"}),
                ("minutes", 1, "vote", [item], None, None, 1, adopted_off, None, {"result": "passed", "quote": "said ordinance adopted"}),
                ("minutes", 2, "executive_session_motion", [item], None, None, 1, exec_off, None,
                 {"stated_reason": "pending litigation, controversies not yet litigated", "mover": "O'Quinn", "seconder": "Tate",
                  "quote": "go into Executive Session at the recommendation of the City Attorney"})]
        import json
        for src, seq, et, refs, actor, start_s, page, off, seg_id, detail in rows:
            cur.execute("""INSERT INTO meeting_events (meeting_id, source, seq, event_type, scope, agenda_item_refs, actor_member_id,
                                                       summary, detail, start_s, page, char_offset, segment_id, prompt_version)
                           VALUES (%s, %s, %s, %s, 'item', %s, %s, %s, %s::jsonb, %s, %s, %s, %s, 200)""",
                        [inst.meeting_id, src, seq, et, refs, actor, f"{et}", json.dumps(detail), start_s, page, off, seg_id])
    return {"item": item, "exec_text": exec_seg["text"], "vote_text": vote_seg["text"]}


def _client(verdicts_fn, hunted=None, tokens=90_000):
    c = MagicMock()
    c.count_tokens.return_value = tokens

    def call(**kw):
        if kw["schema"] is C.JUDGE_SCHEMA:
            cands = kw["user"]
            return StructuredResult({"verdicts": verdicts_fn(cands)}, Usage(1000, 0, 0, 200), "claude-opus-5-5", "end_turn")
        return StructuredResult({"discrepancies": hunted or []}, Usage(1000, 0, 0, 100), "claude-opus-5-5", "end_turn")
    c.call.side_effect = call
    return c


def _claim(inst, reason=None):
    return {"id": inst.transcript_id, "meeting_id": inst.meeting_id, "status": "events_extracted", "version": 1,
            "word_count": 650, "compare_skipped_reason": reason}


def _ids_in_prompt(user):
    import re
    return [int(x) for x in re.findall(r"### Candidate (\d+)", user)]


def test_pilot_candidates_become_proposed_rows_with_verified_citations(pilot):
    info = _seed_events(pilot)

    def verdicts(user):
        out = []
        for cid in _ids_in_prompt(user):
            block = user.split(f"### Candidate {cid}")[1].split("### Candidate")[0]
            if "sequence" in block.split("\n")[0]:
                out.append({"candidate_id": cid, "is_real": True, "category": "sequence", "severity": "material",
                            "title": "Executive session before the vote on video, after it in the minutes",
                            "description": "The video shows the executive session motion before the vote. The minutes record it after adoption.",
                            "transcript_quote": info["exec_text"], "minutes_quote": "said ordinance adopted", "confidence": 0.9,
                            "dismiss_reason": None})
            elif "wording" in block.split("\n")[0]:
                out.append({"candidate_id": cid, "is_real": True, "category": "wording", "severity": "material",
                            "title": "Different statutory ground for the executive session",
                            "description": "On video the attorney cites security plans. The minutes cite pending litigation.",
                            "transcript_quote": info["exec_text"], "minutes_quote": "go into Executive Session at the recommendation of the City Attorney",
                            "confidence": 0.85, "dismiss_reason": None})
            else:
                out.append({"candidate_id": cid, "is_real": False, "category": None, "severity": None, "title": None, "description": None,
                            "transcript_quote": None, "minutes_quote": None, "confidence": 0.7, "dismiss_reason": "same action, different words"})
        return out

    out = C.run_compare_stage(_claim(pilot), client=_client(verdicts))
    assert out.next_status == "compared"
    with db_cursor() as cur:
        cur.execute("""SELECT category, severity, review_state, citation_match, confidence, origin, agenda_item_id,
                              transcript_event_id, minutes_event_id, transcript_start_s, minutes_page, prompt_version
                         FROM minutes_discrepancies WHERE meeting_id=%s ORDER BY category""", [pilot.meeting_id])
        rows = [dict(r) for r in cur.fetchall()]
    proposed = [r for r in rows if r["review_state"] == "proposed"]
    assert sorted(r["category"] for r in proposed) == ["sequence", "wording"]
    assert all(r["severity"] == "material" and r["citation_match"] in ("exact", "fuzzy") for r in proposed)
    assert all(r["agenda_item_id"] == info["item"] and r["prompt_version"] == 200 and r["origin"] == "aligner" for r in proposed)
    assert all(r["transcript_event_id"] and r["minutes_event_id"] for r in proposed)
    assert all(r["transcript_start_s"] and r["minutes_page"] >= 1 for r in proposed)   # page from page_offsets, not the seeded 1
    advance(pilot.transcript_id, out)      # the pipeline, not the stage, moves transcripts.status
    with db_cursor() as cur:
        cur.execute("SELECT status, compare_skipped_reason FROM transcripts WHERE id=%s", [pilot.transcript_id])
        assert tuple(cur.fetchone().values()) == ("compared", None)


def test_unfound_quote_is_kept_as_missing_with_halved_confidence(pilot):
    _seed_events(pilot)

    def verdicts(user):
        return [{"candidate_id": cid, "is_real": True, "category": "wording", "severity": "minor", "title": "t", "description": "d",
                 "transcript_quote": "words nobody said at this meeting", "minutes_quote": "words not in the minutes either",
                 "confidence": 0.8, "dismiss_reason": None} for cid in _ids_in_prompt(user)]

    C.run_compare_stage(_claim(pilot), client=_client(verdicts))
    with db_cursor() as cur:
        cur.execute("SELECT citation_match, confidence, review_state FROM minutes_discrepancies WHERE meeting_id=%s", [pilot.meeting_id])
        rows = cur.fetchall()
    assert rows and all(r["citation_match"] == "missing" and r["review_state"] == "proposed" for r in rows)
    assert all(abs(r["confidence"] - 0.4) < 1e-6 for r in rows)          # Review Focus 2


def test_dismissed_candidates_are_stored_with_reason(pilot):
    _seed_events(pilot)
    verdicts = lambda user: [{"candidate_id": cid, "is_real": False, "category": None, "severity": None, "title": None, "description": None,
                              "transcript_quote": None, "minutes_quote": None, "confidence": 0.6, "dismiss_reason": "aligner pairing mistake"}
                             for cid in _ids_in_prompt(user)]
    C.run_compare_stage(_claim(pilot), client=_client(verdicts))
    with db_cursor() as cur:
        cur.execute("SELECT review_state, reject_reason FROM minutes_discrepancies WHERE meeting_id=%s", [pilot.meeting_id])
        rows = cur.fetchall()
    assert rows and all(r["review_state"] == "dismissed_by_model" and r["reject_reason"] == "aligner pairing mistake" for r in rows)


def test_hunter_rows_are_model_initiated_and_linked_to_nearest_event(pilot):
    info = _seed_events(pilot)
    hunted = [{"category": "omission", "severity": "material", "title": "Attorney's LPR explanation not minuted",
               "description": "The attorney explained what the agreement gives Alabama Power access to; the minutes do not record it.",
               "agenda_item_refs": [info["item"]], "transcript_quote": info["exec_text"], "transcript_segment_seq": None,
               "minutes_quote": None, "minutes_page": None, "confidence": 0.7}]
    verdicts = lambda user: [{"candidate_id": cid, "is_real": False, "category": None, "severity": None, "title": None, "description": None,
                              "transcript_quote": None, "minutes_quote": None, "confidence": 0.5, "dismiss_reason": "x"} for cid in _ids_in_prompt(user)]
    C.run_compare_stage(_claim(pilot), client=_client(verdicts, hunted))
    with db_cursor() as cur:
        cur.execute("""SELECT origin, category, transcript_event_id, minutes_event_id, citation_match, transcript_start_s
                         FROM minutes_discrepancies WHERE meeting_id=%s AND origin='model_initiated'""", [pilot.meeting_id])
        (row,) = cur.fetchall()
    assert row["category"] == "omission" and row["transcript_event_id"] is not None and row["minutes_event_id"] is None
    assert row["citation_match"] == "exact" and row["transcript_start_s"] is not None


def test_candidate_cap_holds_the_transcript(pilot, monkeypatch):
    _seed_events(pilot)
    monkeypatch.setattr(C, "TRANSCRIPT_CANDIDATE_CAP", 1)
    c = _client(lambda user: [])
    with pytest.raises(TranscriptHeld) as ei:
        C.run_compare_stage(_claim(pilot), client=c)
    assert ei.value.reason == "candidate_cap"
    c.call.assert_not_called()


def test_vote_outcome_rows_are_deterministic_and_skip_the_judge(pilot):
    info = _seed_events(pilot)
    with db_cursor() as cur:
        cur.execute("""INSERT INTO votes (meeting_id, result, yeas, nays, source, raw_text) VALUES (%s, 'failed', 3, 5, 'minutes_text',
                       'upon the roll being called the vote was as follows ... the motion failed') RETURNING id""", [pilot.meeting_id])
        vid = cur.fetchone()["id"]
        cur.execute("""INSERT INTO vote_agenda_items (vote_id, agenda_item_id, association_type, match_confidence)
                       VALUES (%s, %s, 'explicit', 1.0)""", [vid, info["item"]])
    seen = {}
    def verdicts(user):
        seen["user"] = user
        return [{"candidate_id": cid, "is_real": False, "category": None, "severity": None, "title": None, "description": None,
                 "transcript_quote": None, "minutes_quote": None, "confidence": 0.5, "dismiss_reason": "x"} for cid in _ids_in_prompt(user)]
    C.run_compare_stage(_claim(pilot), client=_client(verdicts))
    assert "vote_outcome" not in seen["user"].split("Transcript timeline")[0]     # not sent to the judge
    with db_cursor() as cur:
        cur.execute("""SELECT title, severity, review_state, minutes_excerpt, transcript_event_id, minutes_event_id
                         FROM minutes_discrepancies WHERE meeting_id=%s AND category='vote_outcome'""", [pilot.meeting_id])
        (row,) = cur.fetchall()
    assert row["severity"] == "material" and row["review_state"] == "proposed"
    assert "motion failed" in row["minutes_excerpt"] and row["transcript_event_id"] and row["minutes_event_id"] is None


def _no_real(user):
    return [{"candidate_id": cid, "is_real": False, "category": None, "severity": None, "title": None, "description": None,
             "transcript_quote": None, "minutes_quote": None, "confidence": 0.5, "dismiss_reason": "x"} for cid in _ids_in_prompt(user)]


def test_paired_vote_event_mismatch_is_deterministic_and_skips_the_judge(pilot):
    import json
    info = _seed_events(pilot)
    with db_cursor() as cur:
        cur.execute("""UPDATE meeting_events SET detail = detail || %s::jsonb
                        WHERE meeting_id=%s AND source='transcript' AND event_type='vote'""",
                    [json.dumps({"result": "passed", "yeas": 8, "nays": 0}), pilot.meeting_id])
        cur.execute("""UPDATE meeting_events SET detail = detail || %s::jsonb
                        WHERE meeting_id=%s AND source='minutes' AND event_type='vote'""",
                    [json.dumps({"result": "passed", "yeas": 9, "nays": 0}), pilot.meeting_id])
    seen = {}

    def verdicts(user):
        seen["user"] = user
        return _no_real(user)
    C.run_compare_stage(_claim(pilot), client=_client(verdicts))
    assert "vote_outcome" not in seen["user"].split("Transcript timeline")[0]
    with db_cursor() as cur:
        cur.execute("""SELECT review_state, severity, confidence, minutes_event_id, transcript_event_id
                         FROM minutes_discrepancies WHERE meeting_id=%s AND category='vote_outcome'""", [pilot.meeting_id])
        (row,) = cur.fetchall()
    assert row["review_state"] == "proposed" and row["severity"] == "material" and abs(row["confidence"] - 0.9) < 1e-6
    assert row["minutes_event_id"] and row["transcript_event_id"]


def _hunt(info, **kw):
    h = {"category": "omission", "severity": "material", "title": "t", "description": "d", "agenda_item_refs": [info["item"]],
         "transcript_quote": None, "transcript_segment_seq": None, "minutes_quote": None, "minutes_page": None, "confidence": 0.8}
    h.update(kw)
    return h


def test_hunter_unknown_agenda_ref_is_nulled_not_fatal(pilot):
    info = _seed_events(pilot)
    hunted = [_hunt(info, agenda_item_refs=[999999999], transcript_quote=info["exec_text"])]
    C.run_compare_stage(_claim(pilot), client=_client(_no_real, hunted))
    with db_cursor() as cur:
        cur.execute("SELECT agenda_item_id FROM minutes_discrepancies WHERE meeting_id=%s AND origin='model_initiated'", [pilot.meeting_id])
        (row,) = cur.fetchall()
    assert row["agenda_item_id"] is None


def test_hunter_unfound_quote_keeps_row_anchored_with_missing_citation(pilot):
    info = _seed_events(pilot)
    hunted = [_hunt(info, transcript_quote="words nobody said at this meeting")]
    C.run_compare_stage(_claim(pilot), client=_client(_no_real, hunted))
    with db_cursor() as cur:
        cur.execute("""SELECT citation_match, confidence, transcript_event_id, minutes_event_id, agenda_item_id
                         FROM minutes_discrepancies WHERE meeting_id=%s AND origin='model_initiated'""", [pilot.meeting_id])
        (row,) = cur.fetchall()
    assert row["citation_match"] == "missing" and abs(row["confidence"] - 0.4) < 1e-6
    assert (row["transcript_event_id"] or row["minutes_event_id"]) and row["agenda_item_id"] == info["item"]
