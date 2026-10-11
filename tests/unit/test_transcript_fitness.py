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
