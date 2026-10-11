"""Claim order, fitness gate, index points, advance/hold/fail mapping, public predicate."""
from datetime import date
from unittest.mock import MagicMock

import pytest

from docket.ai.exceptions import AIFatalError, AIPermanentRowError, AIRateLimited, AITransientError, TranscriptHeld
from docket.ai.transcripts import pipeline as P
from docket.config import DATABASE_URL
from docket.db import db_cursor
from docket.services import transcripts as tsvc

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)


def _mk(status="uploaded", word_count=5000, meeting_date=date(2026, 9, 1), external_id="999801", *, segments=True):
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug='birmingham'")
        muni = cur.fetchone()["id"]
        cur.execute("""INSERT INTO meetings (municipality_id, title, meeting_date, external_id, video_url)
                       VALUES (%s, 'PL test', %s, %s, 'https://bhamal.granicus.com/MediaPlayer.php?view_id=2&clip_id=1')
                       RETURNING id""", [muni, meeting_date, external_id])
        mid = cur.fetchone()["id"]
        cur.execute("INSERT INTO processing_status (meeting_id) VALUES (%s)", [mid])
        cur.execute("""INSERT INTO agenda_items (meeting_id, item_number, title, external_id, video_timestamp_seconds)
                       VALUES (%s, '1', 'First', %s, 900), (%s, '2', 'Second', %s, 1500) RETURNING id""",
                    [mid, external_id + "-1", mid, external_id + "-2"])
        i1, i2 = [r["id"] for r in cur.fetchall()]
        cur.execute("""INSERT INTO transcripts (meeting_id, status, version, word_count, uploaded_at)
                       VALUES (%s, %s, 1, %s, now()) RETURNING id""", [mid, status, word_count])
        tid = cur.fetchone()["id"]
        if segments:
            cur.execute("""INSERT INTO transcript_segments (transcript_id, seq, start_s, end_s, text, cluster_label, is_silence) VALUES
                           (%s, 0, 0, 890, '', NULL, TRUE),
                           (%s, 1, 905, 910, 'Item one is up.', 'S0', FALSE),
                           (%s, 2, 1510, 1515, 'Now item two.', 'S1', FALSE)""", [tid, tid, tid])
    return {"meeting_id": mid, "transcript_id": tid, "items": (i1, i2)}


def _rm(*fx):
    with db_cursor() as cur:
        for f in fx:
            cur.execute("DELETE FROM meetings WHERE id=%s", [f["meeting_id"]])


def _row(tid):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM transcripts WHERE id=%s", [tid])
        return cur.fetchone()


def test_claim_newest_first_and_bumps_attempts():
    a = _mk(meeting_date=date(2026, 8, 1), external_id="999811")
    b = _mk(meeting_date=date(2026, 9, 15), external_id="999812")
    try:
        c = P.claim_next()
        assert c["id"] == b["transcript_id"] and c["status"] == "uploaded"
        assert _row(b["transcript_id"])["stage_attempts"] == 1
        # Backoff: the row just claimed is not claimable again inside 24h.
        c2 = P.claim_next()
        assert c2["id"] == a["transcript_id"]
        assert P.claim_next() is None
    finally:
        _rm(a, b)


def test_no_minutes_rows_are_claimable_only_once_minutes_url_exists():
    fx = _mk(status="events_extracted")
    try:
        with db_cursor() as cur:
            cur.execute("UPDATE transcripts SET compare_skipped_reason='no_minutes' WHERE id=%s", [fx["transcript_id"]])
        assert P.claim_next() is None
        with db_cursor() as cur:
            cur.execute("UPDATE meetings SET minutes_url='https://x/MinutesViewer.php?clip_id=1' WHERE id=%s", [fx["meeting_id"]])
        assert P.claim_next()["id"] == fx["transcript_id"]
    finally:
        _rm(fx)


def test_fitness_gate_moves_mic_check_to_low_speech_without_llm(monkeypatch):
    fx = _mk(word_count=24)
    client = MagicMock()
    monkeypatch.setattr(P, "_stage_fn", lambda stage: (_ for _ in ()).throw(AssertionError("stage ran")))
    try:
        claim = P.claim_next()
        assert P.process_claim(claim, client=client, notes="t") == "low_speech"
        row = _row(fx["transcript_id"])
        assert row["status"] == "low_speech" and "below floor" in row["last_error"]
        client.call.assert_not_called()
        # Not public any more; surfaced as debt even though the recording is short.
        assert tsvc.get_public_transcript(fx["meeting_id"]) is None
        with db_cursor() as cur:
            cur.execute("UPDATE transcripts SET audio_duration_s=360 WHERE id=%s", [fx["transcript_id"]])
            cur.execute("SELECT id FROM municipalities WHERE slug='birmingham'"); muni = cur.fetchone()["id"]
        debt = [d for d in tsvc.list_transcript_debt(muni) if d["meeting_id"] == fx["meeting_id"]]
        assert debt and debt[0]["friendly_label"] == "Too short to analyze (24 words)"
    finally:
        _rm(fx)


def test_index_points_assign_segments_before_speaker_stage(monkeypatch):
    fx = _mk()
    monkeypatch.setattr(P, "_stage_fn", lambda stage: (lambda claim, client: P.StageOutcome("speakers_resolved")))
    try:
        claim = P.claim_next()
        assert P.process_claim(claim, client=MagicMock(), notes="t") == "advanced"
        with db_cursor() as cur:
            cur.execute("SELECT seq, agenda_item_id, assignment_method FROM transcript_segments WHERE transcript_id=%s ORDER BY seq",
                        [fx["transcript_id"]])
            rows = cur.fetchall()
        i1, i2 = fx["items"]
        assert rows[0]["agenda_item_id"] is None            # pre-meeting silence, before the first index point
        assert (rows[1]["agenda_item_id"], rows[1]["assignment_method"]) == (i1, "index_point")
        assert (rows[2]["agenda_item_id"], rows[2]["assignment_method"]) == (i2, "index_point")
        row = _row(fx["transcript_id"])
        assert row["status"] == "speakers_resolved" and row["stage_attempts"] == 0
    finally:
        _rm(fx)


@pytest.mark.parametrize("exc,expected_status,expected_reason", [
    (TranscriptHeld("token_ceiling", "612000 tokens"), "needs_review", "token_ceiling"),
    (AIPermanentRowError("refusal: cyber"), "needs_review", "permanent"),
])
def test_holds_go_to_needs_review_with_reason(monkeypatch, exc, expected_status, expected_reason):
    fx = _mk()
    def boom(claim, client): raise exc
    monkeypatch.setattr(P, "_stage_fn", lambda stage: boom)
    try:
        assert P.process_claim(P.claim_next(), client=MagicMock(), notes="t") == "held"
        row = _row(fx["transcript_id"])
        assert row["status"] == expected_status and row["needs_review_reason"] == expected_reason
        # Uploaded transcript stays public after a worker-stage hold.
        assert tsvc.get_public_transcript(fx["meeting_id"]) is not None
    finally:
        _rm(fx)


def test_third_transient_failure_marks_failed(monkeypatch):
    fx = _mk()
    def boom(claim, client): raise AITransientError("5xx")
    monkeypatch.setattr(P, "_stage_fn", lambda stage: boom)
    try:
        with db_cursor() as cur:
            cur.execute("UPDATE transcripts SET stage_attempts=2 WHERE id=%s", [fx["transcript_id"]])
        assert P.process_claim(P.claim_next(), client=MagicMock(), notes="t") == "failed"
        row = _row(fx["transcript_id"])
        assert row["status"] == "failed" and row["stage_attempts"] == 3 and "5xx" in row["last_error"]
        assert tsvc.get_public_transcript(fx["meeting_id"]) is not None   # segments exist; page stays up
    finally:
        _rm(fx)


def test_failed_without_upload_is_still_not_public():
    fx = _mk(status="failed", segments=False)
    try:
        with db_cursor() as cur:
            cur.execute("UPDATE transcripts SET uploaded_at=NULL WHERE id=%s", [fx["transcript_id"]])
        assert tsvc.get_public_transcript(fx["meeting_id"]) is None
    finally:
        _rm(fx)


def test_each_processed_claim_writes_an_ai_run(monkeypatch):
    fx = _mk()
    monkeypatch.setattr(P, "_stage_fn", lambda stage: (lambda claim, client: P.StageOutcome("speakers_resolved")))
    try:
        P.process_claim(P.claim_next(), client=MagicMock(), notes="pytest_pipeline")
        with db_cursor() as cur:
            cur.execute("SELECT stage, model, rows_processed, finished_at FROM ai_runs WHERE notes='pytest_pipeline' ORDER BY id DESC LIMIT 1")
            run = cur.fetchone()
        assert run["stage"] == "transcript_speakers" and run["rows_processed"] == 1 and run["finished_at"] is not None
    finally:
        _rm(fx)
        with db_cursor() as cur:
            cur.execute("DELETE FROM ai_runs WHERE notes='pytest_pipeline'")


def test_reset_for_versions_is_idempotent_after_compare():
    """C2: unmatched stale/rejected rows keep their old prompt_version forever and must not re-trigger a compare."""
    from docket.ai.transcripts import compare as C
    fx = _mk(status="compared", external_id="999821")
    mid, tid = fx["meeting_id"], fx["transcript_id"]
    try:
        with db_cursor() as cur:
            cur.execute("""INSERT INTO meeting_events (meeting_id, source, seq, event_type, scope, agenda_item_refs, summary, detail,
                                                       start_s, prompt_version)
                           VALUES (%s, 'transcript', 0, 'motion', 'item', %s, 'm', '{}'::jsonb, 905, 200) RETURNING id""",
                        [mid, [fx["items"][0]]])
            ev = cur.fetchone()["id"]
            cur.execute("""INSERT INTO minutes_discrepancies (meeting_id, agenda_item_id, category, severity, title, description,
                                                              transcript_event_id, review_state, prompt_version)
                           VALUES (%s, %s, 'omission', 'minor', 'old', 'd', %s, 'stale', 199),
                                  (%s, %s, 'wording', 'minor', 'cur', 'd', %s, 'proposed', 200) RETURNING id""",
                        [mid, fx["items"][0], ev, mid, fx["items"][0], ev])
            stale_id, proposed_id = [r["id"] for r in cur.fetchall()]
        assert P.reset_for_versions() == 0
        assert _row(tid)["status"] == "compared"

        with db_cursor() as cur:
            cur.execute("UPDATE minutes_discrepancies SET prompt_version = 199 WHERE id = %s", [proposed_id])
        assert P.reset_for_versions() == 1
        assert _row(tid)["status"] == "events_extracted"

        # A (mocked) compare re-writes the live row at the current version; the unmatched stale row stays at 199.
        row = {"meeting_id": mid, "agenda_item_id": fx["items"][0], "category": "wording", "severity": "minor", "title": "cur v2",
               "description": "d", "transcript_event_id": ev, "minutes_event_id": None, "transcript_excerpt": None,
               "transcript_start_s": 905, "minutes_excerpt": None, "minutes_page": None, "citation_match": "missing",
               "confidence": 0.4, "origin": "aligner", "review_state": "proposed", "reject_reason": None,
               "prompt_version": C.COMPARE_PROMPT_VERSION}
        C.write_rows(mid, [row])
        P.advance(tid, P.StageOutcome("compared"))
        with db_cursor() as cur:
            cur.execute("SELECT id, review_state, prompt_version FROM minutes_discrepancies WHERE meeting_id = %s ORDER BY id", [mid])
            states = {r["id"]: (r["review_state"], r["prompt_version"]) for r in cur.fetchall()}
        assert states[stale_id] == ("stale", 199)
        assert P.reset_for_versions() == 0
        assert _row(tid)["status"] == "compared"
    finally:
        _rm(fx)


def test_rate_limit_hands_the_attempt_back_and_keeps_the_backoff(monkeypatch):
    """A 429 streak must never turn a healthy transcript `failed`: the attempt the claim took is returned,
    but last_attempted_at stays so the row is not re-claimed until tomorrow."""
    fx = _mk()
    def boom(claim, client): raise AIRateLimited("429")
    monkeypatch.setattr(P, "_stage_fn", lambda stage: boom)
    try:
        with db_cursor() as cur:
            cur.execute("UPDATE transcripts SET stage_attempts=2 WHERE id=%s", [fx["transcript_id"]])
        assert P.process_claim(P.claim_next(), client=MagicMock(), notes="t") == "rate_limited"
        row = _row(fx["transcript_id"])
        assert row["status"] == "uploaded" and row["stage_attempts"] == 2 and "429" in row["last_error"]
        assert row["last_attempted_at"] is not None
        assert P.claim_next() is None            # the 24-hour backoff still applies
    finally:
        _rm(fx)


def test_housekeeping_runs_even_when_model_validation_is_fatal(monkeypatch):
    calls = []
    monkeypatch.setitem(P.MODEL_FOR_STAGE, "speakers", "claude-not-a-model")
    monkeypatch.setattr(P, "sweep_minutes_changes", lambda limit=10: calls.append("sweep") or 0)
    import docket.ai.transcripts.alerts as A
    monkeypatch.setattr(A, "alert_if_producer_stalled", lambda: calls.append("stall") or False)
    with pytest.raises(AIFatalError):
        P.run_transcript_pipeline(limit=1, notes="t", client=MagicMock())
    assert calls == ["sweep", "stall"]
