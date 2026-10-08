# transcriber/tests/test_db.py
"""Integration tests for the producer's claim/upload layer against a local Postgres
with docket migrations applied (run `python -m docket.migrations.runner` in the main
repo first)."""
import os
from datetime import date
import pytest
import psycopg2

from transcriber.contract import Segment, Speaker, TranscriptOutput
from transcriber import db as tdb

URL = os.environ.get("TRANSCRIBER_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not URL or any(h in URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="needs a local docket Postgres",
)

SINCE = date(2027, 3, 1)


@pytest.fixture
def conn():
    c = tdb.connect(URL)
    yield c
    c.rollback()
    c.close()


@pytest.fixture
def bham_meeting(conn):
    """Insert one Birmingham meeting with a numeric external_id; clean up after."""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug='birmingham'")
        muni = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO meetings (municipality_id, title, meeting_date, external_id,
                                     video_url, is_hidden)
               VALUES (%s, 'TDB test', %s, '999901',
                       'https://bhamal.granicus.com/MediaPlayer.php?view_id=2&clip_id=999901', FALSE)
               RETURNING id""",
            [muni, date(2027, 3, 1)],
        )
        mid = cur.fetchone()[0]
    conn.commit()
    yield mid
    with conn.cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE id = %s", [mid])
    conn.commit()


def _output(meeting_id: int) -> TranscriptOutput:
    return TranscriptOutput(
        meeting_id=meeting_id, version=1, engine="faster-whisper", asr_model="large-v3",
        diarization_model="pyannote/speaker-diarization-3.1", audio_duration_s=100.0,
        speech_seconds=80.0, audio_sha256="ab" * 32,
        segments=[
            Segment(0, 0.0, 3.0, "Item 15 passes.", "SPEAKER_00", -0.1, 0.01),
            Segment(1, 3.0, 6.0, "100% sure\\ttab\\there\nnewline % percent \\\\ backslash",
                    "SPEAKER_01", -0.3, 0.02),
            Segment(2, 6.0, 70.0, "", None, None, None, is_silence=True),
        ],
        speakers=[Speaker("SPEAKER_00", [0.1, 0.2]), Speaker("SPEAKER_01", None)],
    )


def test_claim_creates_row_and_returns_newest(conn, bham_meeting):
    c = tdb.claim_next(conn, since=SINCE, host="legion")
    conn.commit()
    assert c is not None and c.meeting_id == bham_meeting
    assert c.external_id == "999901" and c.status == "claimed"
    # Second claim must not return the same meeting (it is now claimed and fresh).
    assert tdb.claim_next(conn, since=SINCE, host="legion") is None
    conn.commit()


def test_claim_respects_since(conn, bham_meeting):
    assert tdb.claim_next(conn, since=date(2027, 3, 2), host="legion") is None


def test_stale_claim_is_reclaimable(conn, bham_meeting):
    c = tdb.claim_next(conn, since=SINCE, host="legion")
    with conn.cursor() as cur:
        cur.execute("UPDATE transcripts SET claimed_at = now() - interval '7 hours' WHERE id=%s",
                    [c.transcript_id])
    conn.commit()
    c2 = tdb.claim_next(conn, since=SINCE, host="legion-2")
    conn.commit()
    assert c2 is not None and c2.transcript_id == c.transcript_id


def test_transcribed_row_claims_straight_to_upload(conn, bham_meeting):
    c = tdb.claim_next(conn, since=SINCE, host="legion")
    tdb.mark_status(conn, c.transcript_id, "transcribed", raw_output_path="/archive/x.json")
    conn.commit()
    c2 = tdb.claim_next(conn, since=SINCE, host="legion")
    conn.commit()
    assert c2.transcript_id == c.transcript_id and c2.status == "transcribed"


def test_transcribed_row_is_not_claimable_by_another_host_until_stale(conn, bham_meeting):
    c = tdb.claim_next(conn, since=SINCE, host="legion")
    tdb.mark_status(conn, c.transcript_id, "transcribed", raw_output_path="/archive/x.json")
    conn.commit()
    assert tdb.claim_next(conn, since=SINCE, host="legion-2") is None      # fresh, other host: no
    c_same = tdb.claim_next(conn, since=SINCE, host="legion")
    conn.commit()
    assert c_same is not None and c_same.status == "transcribed"          # same host resumes
    with conn.cursor() as cur:
        cur.execute("UPDATE transcripts SET claimed_at = now() - interval '7 hours' WHERE id=%s",
                    [c.transcript_id])
    conn.commit()
    c_other = tdb.claim_next(conn, since=SINCE, host="legion-2")
    conn.commit()
    assert c_other is not None and c_other.transcript_id == c.transcript_id   # stale: anyone


def test_mark_failed_increments_attempts_and_keeps_error(conn, bham_meeting):
    c = tdb.claim_next(conn, since=SINCE, host="legion")
    tdb.mark_status(conn, c.transcript_id, "failed", error="ffmpeg could not read: 403 Forbidden")
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT status, stage_attempts, last_error FROM transcripts WHERE id=%s",
                    [c.transcript_id])
        status, attempts, err = cur.fetchone()
    assert status == "failed" and attempts == 1 and "403" in err


def test_upload_round_trips_awkward_text_and_is_idempotent(conn, bham_meeting):
    c = tdb.claim_next(conn, since=SINCE, host="legion")
    out = _output(bham_meeting)
    n1 = tdb.upload(conn, out)
    n2 = tdb.upload(conn, out)
    conn.commit()
    assert n1 == n2 == 3
    with conn.cursor() as cur:
        cur.execute("""SELECT s.seq, s.text, s.is_silence, sp.cluster_label
                         FROM transcript_segments s
                         LEFT JOIN transcript_speakers sp ON sp.id = s.speaker_id
                        WHERE s.transcript_id=%s ORDER BY s.seq""", [c.transcript_id])
        rows = cur.fetchall()
        cur.execute("SELECT status, word_count, uploaded_at FROM transcripts WHERE id=%s",
                    [c.transcript_id])
        status, wc, up = cur.fetchone()
        cur.execute("SELECT count(*) FROM transcript_speakers WHERE meeting_id=%s", [bham_meeting])
        n_speakers = cur.fetchone()[0]
    assert len(rows) == 3
    assert rows[1][1] == out.segments[1].text
    assert rows[2][2] is True and rows[2][3] is None
    assert rows[0][3] == "SPEAKER_00"
    assert status == "uploaded" and wc == out.word_count and up is not None
    assert n_speakers == 2


def test_heartbeat_upserts(conn):
    tdb.heartbeat(conn, "legion-test", "idle", None, "0.1.0")
    tdb.heartbeat(conn, "legion-test", "transcribing", 15, "0.1.0")
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT last_status, last_meeting_id FROM producer_heartbeats WHERE host='legion-test'")
        assert cur.fetchone() == ("transcribing", 15)
        cur.execute("DELETE FROM producer_heartbeats WHERE host='legion-test'")
    conn.commit()


def test_roster_for_meeting_returns_names(conn, bham_meeting):
    names = tdb.roster_for_meeting(conn, bham_meeting)
    assert isinstance(names, list) and all(isinstance(n, str) for n in names)


def test_failed_row_is_claimable_only_with_retry_failed(conn, bham_meeting):
    c = tdb.claim_next(conn, since=SINCE, host="legion")
    tdb.mark_status(conn, c.transcript_id, "failed", error="granicus outage")
    conn.commit()
    assert tdb.claim_next(conn, since=SINCE, host="legion") is None
    conn.commit()
    c2 = tdb.claim_next(conn, since=SINCE, host="legion-2", retry_failed=True)
    conn.commit()
    assert c2 is not None and c2.transcript_id == c.transcript_id and c2.status == "claimed"
