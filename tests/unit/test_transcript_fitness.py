from docket.ai.transcripts.pipeline import CLAIM_SQL, STAGE_FOR_STATUS, fitness_reason


def test_fitness_floor_catches_the_mic_check():
    assert fitness_reason(24, 300) == "word_count 24 below floor 300"
    assert fitness_reason(None, 300) == "word_count unknown"
    assert fitness_reason(300, 300) is None
    assert fitness_reason(11_300, 300) is None


def test_claim_sql_is_birmingham_newest_first_skip_locked():
    assert "mu.slug = 'birmingham'" in CLAIM_SQL
    assert "FOR UPDATE OF t SKIP LOCKED" in CLAIM_SQL
    assert "ORDER BY m.meeting_date DESC" in CLAIM_SQL
    assert "interval '24 hours'" in CLAIM_SQL
    assert "t.stage_attempts < 3" in CLAIM_SQL


def test_status_stage_map():
    assert STAGE_FOR_STATUS == {"uploaded": "speakers", "speakers_resolved": "events", "events_extracted": "compare"}


def test_claim_meeting_sql_replacement_matched():
    from docket.ai.transcripts.pipeline import CLAIM_MEETING_SQL
    assert "t.meeting_id = %s" in CLAIM_MEETING_SQL
    assert "interval '24 hours'" not in CLAIM_MEETING_SQL
    assert "t.stage_attempts < 3" not in CLAIM_MEETING_SQL


def test_budget_exhaustion_still_runs_sweep_and_stall_alert(monkeypatch):
    """I1: the sweep spends no LLM money and the stall alert must fire even on a budget-exhausted tick."""
    import contextlib
    from unittest.mock import MagicMock

    import pytest

    from docket.ai import worker as W
    from docket.ai.transcripts import alerts as A
    from docket.ai.transcripts import pipeline as P

    sweep, stalled = MagicMock(return_value=0), MagicMock()
    monkeypatch.setattr(P, "db", lambda: contextlib.nullcontext(None))
    monkeypatch.setattr(P, "reset_for_versions", lambda: 0)
    monkeypatch.setattr(P, "claim_next", lambda: (_ for _ in ()).throw(AssertionError("claimed over budget")))
    monkeypatch.setattr(W, "_today_spend", lambda conn: 10_000.0)
    monkeypatch.setattr(P, "sweep_minutes_changes", sweep)
    monkeypatch.setattr(A, "alert_if_producer_stalled", stalled)
    with pytest.raises(W.BudgetExceededError):
        P.run_transcript_pipeline(client=MagicMock())
    sweep.assert_called_once()
    stalled.assert_called_once()
