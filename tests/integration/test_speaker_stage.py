"""Speaker stage against the real meeting 2543 rows with a mocked model."""
import json
from unittest.mock import MagicMock

import pytest

from docket.ai.exceptions import TranscriptHeld
from docket.ai.pricing import Usage
from docket.ai.transcripts import speakers as SP
from docket.ai.transcripts.client import StructuredResult
from docket.config import DATABASE_URL
from docket.db import db_cursor
from tests.support.transcript_fixtures import install_bundle, load_bundle

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)


@pytest.fixture
def inst():
    i = install_bundle(load_bundle("transcript_2543"))
    yield i
    i.cleanup()


def _client(assignments, tokens=50_000):
    c = MagicMock()
    c.count_tokens.return_value = tokens
    c.call.return_value = StructuredResult({"assignments": assignments}, Usage(100, 0, 0, 50), "claude-sonnet-5-5", "end_turn")
    return c


def _claim(inst):
    return {"id": inst.transcript_id, "meeting_id": inst.meeting_id, "status": "uploaded", "version": 1,
            "word_count": 11_300, "compare_skipped_reason": None}


def _cluster_texts(inst):
    segs = SP.load_speech_segments(inst.transcript_id)
    by = {}
    for s in segs:
        by.setdefault(s["cluster_label"], []).append(s["text"])
    return {k: " ".join(v) for k, v in by.items()}


def test_stage_writes_every_cluster_and_merges_two_clusters_to_one_member(inst):
    texts = _cluster_texts(inst)
    labels = list(texts)
    member_id = next(iter(inst.member_ids.values()))
    quote_a = texts[labels[0]].split(".")[0][:80]
    quote_b = texts[labels[1]].split(".")[0][:80]
    assignments = [{"cluster_label": labels[0], "council_member_id": member_id, "display_name": None, "role": "council",
                    "confidence": 0.9, "method": "roll_call", "evidence_quote": quote_a, "evidence_quote_2": None},
                   {"cluster_label": labels[1], "council_member_id": member_id, "display_name": None, "role": "council",
                    "confidence": 0.9, "method": "addressed_by_chair", "evidence_quote": quote_b, "evidence_quote_2": None}]
    assignments += [{"cluster_label": l, "council_member_id": None, "display_name": None, "role": "unknown",
                     "confidence": 0.3, "method": "sample_inference", "evidence_quote": "x", "evidence_quote_2": None}
                    for l in labels[2:]]
    out = SP.run_speaker_stage(_claim(inst), client=_client(assignments))
    assert out.next_status == "speakers_resolved"
    with db_cursor() as cur:
        cur.execute("""SELECT cluster_label, council_member_id, confidence, method, needs_review
                         FROM transcript_speakers WHERE meeting_id=%s ORDER BY cluster_label""", [inst.meeting_id])
        rows = {r["cluster_label"]: r for r in cur.fetchall()}
    assert rows[labels[0]]["council_member_id"] == member_id and rows[labels[1]]["council_member_id"] == member_id
    # One verified signal each -> capped at 0.75 (medium), still displayed (floor 0.6).
    assert rows[labels[0]]["confidence"] == pytest.approx(0.75) and rows[labels[0]]["method"] == "roll_call"
    assert rows[labels[2]]["method"] == "llm_inference" and rows[labels[2]]["needs_review"] is True
    assert all(rows[l]["confidence"] <= 0.55 for l in labels[2:])        # "x" never verifies (I3: 8-char minimum)
    # Every non-silence segment is linked to its cluster's speaker row.
    with db_cursor() as cur:
        cur.execute("""SELECT count(*) AS n FROM transcript_segments WHERE transcript_id=%s AND is_silence=FALSE AND speaker_id IS NULL""",
                    [inst.transcript_id])
        assert cur.fetchone()["n"] == 0


def test_unverified_quote_downgrades_and_two_verified_quotes_reach_high(inst):
    texts = _cluster_texts(inst)
    labels = list(texts)
    member_id = next(iter(inst.member_ids.values()))
    sentences = [s.strip() for s in texts[labels[0]].split(".") if len(s.split()) >= 4]
    good = [{"cluster_label": labels[0], "council_member_id": member_id, "display_name": None, "role": "council",
             "confidence": 0.95, "method": "roll_call", "evidence_quote": sentences[0][:80], "evidence_quote_2": sentences[1][:80]}]
    bad = [{"cluster_label": labels[1], "council_member_id": member_id, "display_name": None, "role": "council",
            "confidence": 0.95, "method": "roll_call", "evidence_quote": "this sentence was never said by anyone",
            "evidence_quote_2": None}]
    rest = [{"cluster_label": l, "council_member_id": None, "display_name": None, "role": "unknown", "confidence": 0.2,
             "method": "sample_inference", "evidence_quote": "x", "evidence_quote_2": None} for l in labels[2:]]
    SP.run_speaker_stage(_claim(inst), client=_client(good + bad + rest))
    with db_cursor() as cur:
        cur.execute("SELECT cluster_label, confidence, method FROM transcript_speakers WHERE meeting_id=%s", [inst.meeting_id])
        rows = {r["cluster_label"]: r for r in cur.fetchall()}
    assert rows[labels[0]]["confidence"] == pytest.approx(0.95)
    assert rows[labels[1]]["confidence"] == pytest.approx(0.55) and rows[labels[1]]["method"] == "llm_inference"
    assert all(rows[l]["confidence"] <= 0.55 for l in labels[2:])


def test_manual_rows_are_never_overwritten(inst):
    texts = _cluster_texts(inst)
    labels = list(texts)
    with db_cursor() as cur:
        cur.execute("""UPDATE transcript_speakers SET is_manual=TRUE, display_name='City Attorney', role='attorney',
                              confidence=1.0, method='manual' WHERE meeting_id=%s AND cluster_label=%s""",
                    [inst.meeting_id, labels[0]])
    assignments = [{"cluster_label": l, "council_member_id": None, "display_name": "Wrong Name", "role": "public",
                    "confidence": 0.9, "method": "self_identification", "evidence_quote": texts[l].split(".")[0][:80],
                    "evidence_quote_2": None}
                   for l in labels]
    SP.run_speaker_stage(_claim(inst), client=_client(assignments))
    with db_cursor() as cur:
        cur.execute("SELECT display_name, role, is_manual FROM transcript_speakers WHERE meeting_id=%s AND cluster_label=%s",
                    [inst.meeting_id, labels[0]])
        row = cur.fetchone()
    assert (row["display_name"], row["role"], row["is_manual"]) == ("City Attorney", "attorney", True)


def test_member_id_outside_roster_is_dropped(inst):
    texts = _cluster_texts(inst)
    labels = list(texts)
    sentences = {l: [x.strip() for x in texts[l].split(".") if len(x.strip()) >= 8] for l in labels}
    assignments = [{"cluster_label": l, "council_member_id": 999_999, "display_name": None, "role": "council",
                    "confidence": 0.95, "method": "addressed_by_chair", "evidence_quote": sentences[l][0][:80],
                    "evidence_quote_2": sentences[l][1][:80] if len(sentences[l]) > 1 else None} for l in labels]
    SP.run_speaker_stage(_claim(inst), client=_client(assignments))
    with db_cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM transcript_speakers WHERE meeting_id=%s AND council_member_id IS NOT NULL", [inst.meeting_id])
        assert cur.fetchone()["n"] == 0
        cur.execute("SELECT confidence, method FROM transcript_speakers WHERE meeting_id=%s", [inst.meeting_id])
        rows = cur.fetchall()
    # I3: a dropped off-roster id keeps no confidence from its (verified) quotes.
    assert rows and all(r["confidence"] <= 0.55 and r["method"] == "llm_inference" for r in rows)


def test_short_quote_does_not_verify_unless_roll_call(inst):
    texts = _cluster_texts(inst)
    labels = list(texts)
    member_id = next(iter(inst.member_ids.values()))
    word = next(w for w in texts[labels[0]].split() if len(w.strip(".,?!")) >= 3).strip(".,?!")   # a short substring of real text
    assignments = [{"cluster_label": labels[0], "council_member_id": member_id, "display_name": None, "role": "council",
                    "confidence": 0.9, "method": "addressed_by_chair", "evidence_quote": word[:5], "evidence_quote_2": None}]
    assignments += [{"cluster_label": l, "council_member_id": None, "display_name": None, "role": "unknown", "confidence": 0.2,
                     "method": "sample_inference", "evidence_quote": "", "evidence_quote_2": None} for l in labels[1:]]
    SP.run_speaker_stage(_claim(inst), client=_client(assignments))
    with db_cursor() as cur:
        cur.execute("SELECT confidence, method FROM transcript_speakers WHERE meeting_id=%s AND cluster_label=%s",
                    [inst.meeting_id, labels[0]])
        row = cur.fetchone()
    assert row["confidence"] == pytest.approx(0.55) and row["method"] == "llm_inference"


def test_roll_call_short_response_still_verifies():
    a = SP.SpeakerAssignment(cluster_label="S9", council_member_id=1, display_name=None, role="council", confidence=0.9,
                             method="roll_call", evidence_quote="Here.", evidence_quote_2=None)
    conf, method, verified = SP.apply_confidence_rules(a, {"S9": "Here. Present and ready."}, {1})
    assert verified and method == "roll_call" and conf == pytest.approx(0.75)
    short = a.model_copy(update={"method": "addressed_by_chair"})
    conf, method, verified = SP.apply_confidence_rules(short, {"S9": "Here. Present and ready."}, {1})
    assert not verified and method == "llm_inference" and conf == pytest.approx(0.55)
    off = a.model_copy(update={"council_member_id": 2, "evidence_quote": "Present and ready", "method": "addressed_by_chair"})
    conf, method, _ = SP.apply_confidence_rules(off, {"S9": "Here. Present and ready."}, {1})
    assert conf == pytest.approx(0.55) and method == "llm_inference"


def test_token_ceiling_holds_before_calling(inst):
    c = _client([], tokens=600_000)
    with pytest.raises(TranscriptHeld) as ei:
        SP.run_speaker_stage(_claim(inst), client=c)
    assert ei.value.reason == "token_ceiling"
    c.call.assert_not_called()


def test_schema_invalid_response_is_held(inst):
    c = _client([{"cluster_label": "S0", "confidence": "high"}])
    with pytest.raises(TranscriptHeld) as ei:
        SP.run_speaker_stage(_claim(inst), client=c)
    assert ei.value.reason == "schema_invalid"


def test_prompt_contains_every_cluster_and_silence_is_excluded(inst):
    c = _client([])
    try:
        SP.run_speaker_stage(_claim(inst), client=c)
    except TranscriptHeld:
        pass   # zero assignments for 24 clusters is schema-valid but incomplete: held as schema_invalid
    user = c.call.call_args.kwargs["user"]
    for label in _cluster_texts(inst):
        assert f"\n{label}:" in user
    assert "No speech detected" not in user
    assert c.call.call_args.kwargs["schema"]["properties"]["assignments"]
