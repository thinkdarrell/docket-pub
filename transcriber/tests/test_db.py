# transcriber/tests/test_db.py
"""Integration tests for the producer's claim/upload layer against a local Postgres
with docket migrations applied (run `python -m docket.migrations.runner` in the main
repo first)."""
import os
from datetime import date
import pytest
import psycopg2
import psycopg2.extras

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


def _transcript_row(conn, transcript_id):
    with conn.cursor() as cur:
        cur.execute("""SELECT status, compare_skipped_reason, stage_attempts, last_attempted_at,
                              needs_review_reason FROM transcripts WHERE id = %s""", [transcript_id])
        return cur.fetchone()


def test_claim_meeting_marks_uploaded_transcript_changed_and_resets_attempts(conn, bham_meeting):
    c = tdb.claim_next(conn, since=SINCE, host="legion")
    tdb.upload(conn, _output(bham_meeting))
    with conn.cursor() as cur:
        # The worker touched it an hour ago (now() would trip the 30-minute busy guard).
        cur.execute("""UPDATE transcripts SET status = 'compared', stage_attempts = 2,
                              last_attempted_at = now() - interval '1 hour', needs_review_reason = 'x'
                        WHERE id = %s""", [c.transcript_id])
    conn.commit()
    c2 = tdb.claim_meeting(conn, meeting_id=bham_meeting, host="legion")
    conn.commit()
    assert c2 is not None and c2.transcript_id == c.transcript_id and c2.status == "claimed"
    assert c2.meeting_id == bham_meeting and c2.external_id == "999901"
    status, reason, attempts, last_at, review = _transcript_row(conn, c.transcript_id)
    assert status == "claimed" and reason == "transcript_changed"
    assert attempts == 0 and last_at is None and review is None
    # A meeting with no transcripts row gets a fresh claimed row with no marker.
    with conn.cursor() as cur:
        cur.execute("DELETE FROM transcripts WHERE id = %s", [c.transcript_id])
    conn.commit()
    c3 = tdb.claim_meeting(conn, meeting_id=bham_meeting, host="legion")
    conn.commit()
    assert c3 is not None and c3.transcript_id != c.transcript_id and c3.status == "claimed"
    status, reason, attempts, last_at, review = _transcript_row(conn, c3.transcript_id)
    assert status == "claimed" and reason is None and attempts == 0
    assert tdb.claim_meeting(conn, meeting_id=-1, host="legion") is None     # not a Birmingham meeting


def test_claim_meeting_refuses_recent_worker_touch(conn, bham_meeting):
    c = tdb.claim_next(conn, since=SINCE, host="legion")
    tdb.upload(conn, _output(bham_meeting))
    with conn.cursor() as cur:
        cur.execute("UPDATE transcripts SET last_attempted_at = now() WHERE id = %s", [c.transcript_id])
    conn.commit()
    with pytest.raises(tdb.MeetingBusy):
        tdb.claim_meeting(conn, meeting_id=bham_meeting, host="legion")
    conn.rollback()
    status, reason, *_ = _transcript_row(conn, c.transcript_id)
    assert status == "uploaded" and reason is None
    with conn.cursor() as cur:
        cur.execute("UPDATE transcripts SET last_attempted_at = now() - interval '1 hour' WHERE id = %s",
                    [c.transcript_id])
    conn.commit()
    c2 = tdb.claim_meeting(conn, meeting_id=bham_meeting, host="legion")
    conn.commit()
    assert c2 is not None and c2.status == "claimed"


def _speaker_row(conn, meeting_id, label):
    with conn.cursor() as cur:
        cur.execute("""SELECT council_member_id, display_name, method, confidence, needs_review, is_manual
                         FROM transcript_speakers WHERE meeting_id = %s AND cluster_label = %s""",
                    [meeting_id, label])
        return cur.fetchone()


def test_upload_clears_model_speaker_resolution_but_keeps_manual(conn, bham_meeting):
    tdb.claim_next(conn, since=SINCE, host="legion")
    out = _output(bham_meeting)
    tdb.upload(conn, out)
    with conn.cursor() as cur:
        cur.execute("""SELECT cm.id FROM council_members cm JOIN municipalities mu ON mu.id = cm.municipality_id
                        WHERE mu.slug = 'birmingham' ORDER BY cm.id LIMIT 1""")
        member = cur.fetchone()[0]
        for label, manual in (("SPEAKER_00", False), ("SPEAKER_01", True)):
            cur.execute("""UPDATE transcript_speakers
                              SET council_member_id = %s, display_name = 'X', method = 'roll_call',
                                  confidence = 0.9, needs_review = TRUE, is_manual = %s
                            WHERE meeting_id = %s AND cluster_label = %s""",
                        [member, manual, bham_meeting, label])
        for label, manual in (("SPEAKER_77", False), ("SPEAKER_78", True)):
            cur.execute("""INSERT INTO transcript_speakers (meeting_id, cluster_label, display_name, is_manual)
                           VALUES (%s, %s, 'ghost', %s)""", [bham_meeting, label, manual])
    conn.commit()
    tdb.upload(conn, out)
    conn.commit()
    assert _speaker_row(conn, bham_meeting, "SPEAKER_00") == (None, None, None, None, False, False)
    row = _speaker_row(conn, bham_meeting, "SPEAKER_01")
    assert row[:3] == (member, "X", "roll_call") and row[3] == pytest.approx(0.9)
    assert row[4] is True and row[5] is True
    assert _speaker_row(conn, bham_meeting, "SPEAKER_77") is None
    assert _speaker_row(conn, bham_meeting, "SPEAKER_78") == (None, "ghost", None, None, False, True)


def _whole_row(conn, transcript_id):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM transcripts WHERE id = %s", [transcript_id])
        return dict(cur.fetchone())


def _status_attempted_uploaded(conn, transcript_id):
    with conn.cursor() as cur:
        cur.execute("SELECT status, last_attempted_at, uploaded_at, stage_attempts FROM transcripts WHERE id = %s",
                    [transcript_id])
        return cur.fetchone()


def test_failed_rerun_restores_the_pre_claim_row(conn, bham_meeting):
    c = tdb.claim_next(conn, since=SINCE, host="legion")
    tdb.upload(conn, _output(bham_meeting))
    with conn.cursor() as cur:
        cur.execute("""UPDATE transcripts SET status = 'compared', stage_attempts = 2,
                              last_attempted_at = now() - interval '1 hour', needs_review_reason = 'x',
                              last_error = 'y', updated_at = now() - interval '1 hour'
                        WHERE id = %s""", [c.transcript_id])
    conn.commit()
    before = _whole_row(conn, c.transcript_id)
    c2 = tdb.claim_meeting(conn, meeting_id=bham_meeting, host="legion")
    conn.commit()
    assert c2.prior == before and c2.status == "claimed"
    tdb.mark_status(conn, c2.transcript_id, "audio_fetched", audio_sha256="cd" * 32, audio_duration_s=5.0)
    conn.commit()
    status, last_at, _, _ = _status_attempted_uploaded(conn, c.transcript_id)
    assert status == "audio_fetched" and last_at is None          # the producer no longer stamps it
    tdb.restore_row(conn, c2.transcript_id, c2.prior)
    conn.commit()
    after = _whole_row(conn, c.transcript_id)
    assert after == before
    c3 = tdb.claim_meeting(conn, meeting_id=bham_meeting, host="legion")   # no busy refusal
    conn.commit()
    assert c3 is not None and c3.status == "claimed"


def test_claim_meeting_of_a_never_uploaded_row_has_no_prior(conn, bham_meeting):
    c = tdb.claim_next(conn, since=SINCE, host="legion")
    tdb.mark_status(conn, c.transcript_id, "failed", error="ffmpeg could not read: 403 Forbidden")
    conn.commit()
    c2 = tdb.claim_meeting(conn, meeting_id=bham_meeting, host="legion")
    conn.commit()
    assert c2 is not None and c2.prior is None
    tdb.mark_status(conn, c2.transcript_id, "failed", error="ffmpeg could not read: 403 Forbidden")
    conn.commit()
    status, last_at, uploaded_at, attempts = _status_attempted_uploaded(conn, c.transcript_id)
    assert status == "failed" and attempts == 1 and last_at is None and uploaded_at is None


def test_claim_meeting_after_a_crashed_rerun_has_no_prior(conn, bham_meeting):
    c = tdb.claim_next(conn, since=SINCE, host="legion")
    tdb.upload(conn, _output(bham_meeting))
    conn.commit()
    c2 = tdb.claim_meeting(conn, meeting_id=bham_meeting, host="legion")
    conn.commit()
    assert c2.prior is not None
    tdb.mark_status(conn, c2.transcript_id, "audio_fetched", audio_sha256="cd" * 32, audio_duration_s=5.0)
    conn.commit()
    # The run died here: no restore. The next claim takes no snapshot of the crashed state.
    c3 = tdb.claim_meeting(conn, meeting_id=bham_meeting, host="legion")
    conn.commit()
    assert c3.prior is None and c3.status == "claimed"
    status, _, uploaded_at, _ = _status_attempted_uploaded(conn, c.transcript_id)
    assert status == "claimed" and uploaded_at is not None
    tdb.mark_status(conn, c3.transcript_id, "failed", error="CUDA out of memory")
    conn.commit()
    status, _, uploaded_at, _ = _status_attempted_uploaded(conn, c.transcript_id)
    assert status == "failed" and uploaded_at is not None       # the one path that still makes this row


def _worker_low_speech(conn, transcript_id):
    """What mark_low_speech() in src/docket/ai/transcripts/pipeline.py writes on an uploaded row (uploaded_at
    and the segments stay); the worker's claim stamp is aged past the 30-minute busy guard."""
    with conn.cursor() as cur:
        cur.execute("""UPDATE transcripts SET status = 'low_speech', last_error = 'below floor', stage_attempts = 0,
                              last_attempted_at = now() - interval '1 hour', updated_at = now()
                        WHERE id = %s""", [transcript_id])
    conn.commit()


def test_claim_meeting_of_a_low_speech_row_clears_uploaded_at_until_the_upload(conn, bham_meeting):
    c = tdb.claim_next(conn, since=SINCE, host="legion")
    tdb.upload(conn, _output(bham_meeting))
    _worker_low_speech(conn, c.transcript_id)
    before = _whole_row(conn, c.transcript_id)
    assert before["status"] == "low_speech" and before["uploaded_at"] is not None
    c2 = tdb.claim_meeting(conn, meeting_id=bham_meeting, host="legion")
    conn.commit()
    assert c2.status == "claimed" and c2.prior == before
    status, _, uploaded_at, _ = _status_attempted_uploaded(conn, c.transcript_id)
    assert status == "claimed" and uploaded_at is None            # hidden for the run
    tdb.mark_status(conn, c2.transcript_id, "audio_fetched", audio_sha256="cd" * 32, audio_duration_s=5.0)
    conn.commit()
    assert _status_attempted_uploaded(conn, c.transcript_id)[2] is None
    tdb.restore_row(conn, c2.transcript_id, c2.prior)
    conn.commit()
    assert _whole_row(conn, c.transcript_id) == before            # uploaded_at is back with the rest
    c3 = tdb.claim_meeting(conn, meeting_id=bham_meeting, host="legion")
    conn.commit()
    assert c3.prior == before and _status_attempted_uploaded(conn, c.transcript_id)[2] is None
    tdb.upload(conn, _output(bham_meeting))
    conn.commit()
    status, _, uploaded_at, _ = _status_attempted_uploaded(conn, c.transcript_id)
    assert status == "uploaded" and uploaded_at is not None       # the new transcript is public as any upload


def test_claim_meeting_after_a_crashed_low_speech_rerun_stays_hidden(conn, bham_meeting):
    c = tdb.claim_next(conn, since=SINCE, host="legion")
    tdb.upload(conn, _output(bham_meeting))
    _worker_low_speech(conn, c.transcript_id)
    c2 = tdb.claim_meeting(conn, meeting_id=bham_meeting, host="legion")
    conn.commit()
    tdb.mark_status(conn, c2.transcript_id, "audio_fetched", audio_sha256="cd" * 32, audio_duration_s=5.0)
    conn.commit()
    # The run died here: no restore. The next claim takes no prior, and the row stays hidden.
    c3 = tdb.claim_meeting(conn, meeting_id=bham_meeting, host="legion")
    conn.commit()
    assert c3.prior is None and c3.status == "claimed"
    tdb.mark_status(conn, c3.transcript_id, "failed", error="CUDA out of memory")
    conn.commit()
    status, _, uploaded_at, _ = _status_attempted_uploaded(conn, c.transcript_id)
    assert status == "failed" and uploaded_at is None             # hidden; the held tab needs uploaded_at


# --- yt- meetings are eligible, event- placeholders are not (plan youtube-council-channel M6) ---

def _insert_meeting(conn, external_id: str, video_url: str) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug='birmingham'")
        muni = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO meetings (municipality_id, title, meeting_date, external_id, video_url, is_hidden)
               VALUES (%s, 'TDB yt test', %s, %s, %s, FALSE) RETURNING id""",
            [muni, date(2027, 3, 2), external_id, video_url],
        )
        mid = cur.fetchone()[0]
    conn.commit()
    return mid


def _delete_meeting(conn, mid: int) -> None:
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE id = %s", [mid])
    conn.commit()


@pytest.fixture
def yt_meeting(conn):
    mid = _insert_meeting(conn, "yt-tdbTEST0001", "https://www.youtube.com/watch?v=tdbTEST0001")
    yield mid
    _delete_meeting(conn, mid)


@pytest.fixture
def event_meeting(conn):
    mid = _insert_meeting(conn, "event-999902", "https://bhamal.granicus.com/MediaPlayer.php?view_id=2&event_id=999902")
    yield mid
    _delete_meeting(conn, mid)


def test_claim_next_returns_a_yt_meeting(conn, yt_meeting):
    c = tdb.claim_next(conn, since=SINCE, host="legion")
    conn.commit()
    assert c is not None and c.meeting_id == yt_meeting
    assert c.external_id == "yt-tdbTEST0001" and c.status == "claimed"


def test_claim_next_skips_an_event_placeholder(conn, event_meeting):
    c = tdb.claim_next(conn, since=SINCE, host="legion")
    conn.commit()
    assert c is None or c.meeting_id != event_meeting


def test_meeting_source_and_claim_meeting_admit_yt_ids_only(conn, yt_meeting, event_meeting):
    assert tdb.meeting_source(conn, yt_meeting) == "yt-tdbTEST0001"
    assert tdb.meeting_source(conn, event_meeting) is None
    assert tdb.claim_meeting(conn, meeting_id=event_meeting, host="legion") is None
    conn.rollback()
    c = tdb.claim_meeting(conn, meeting_id=yt_meeting, host="legion")
    conn.commit()
    assert c is not None and c.external_id == "yt-tdbTEST0001"


# --- measuring attached YouTube recordings (plan video-links-land-on-the-moment M2) ---

ALIGN_PREFIX = "tdbALIGN"      # every video id these tests insert begins with it
METHOD = 1                     # the method version the tests ask for unless they say otherwise


class _AlignRows:
    """Inserts Birmingham meetings with attached YouTube recordings and remembers the meetings,
    so the fixture can delete them (their recordings and measurements go by cascade)."""

    def __init__(self, conn):
        self.conn = conn
        self.meeting_ids: list[int] = []

    def meeting(self, external_id: str, day: int, *, hidden: bool = False, video_url: str | None = None) -> int:
        if video_url is None:
            video_url = f"https://bhamal.granicus.com/MediaPlayer.php?view_id=2&clip_id={external_id}"
        with self.conn.cursor() as cur:
            cur.execute("SELECT id FROM municipalities WHERE slug='birmingham'")
            muni = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO meetings (municipality_id, title, meeting_date, external_id, video_url, is_hidden)
                   VALUES (%s, 'TDB align test', %s, %s, %s, %s) RETURNING id""",
                [muni, date(2031, 5, day), external_id, video_url, hidden],
            )
            mid = cur.fetchone()[0]
        self.conn.commit()
        self.meeting_ids.append(mid)
        return mid

    def video(self, meeting_id: int, tag: str, *, primary: bool = False) -> int:
        video_id = ALIGN_PREFIX + tag
        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO meeting_videos (meeting_id, provider, video_id, url, title, clean_title,
                                               duration_s, is_primary)
                   VALUES (%s, 'youtube', %s, %s, 'Regular City Council Meeting 5.6.31',
                           'Regular City Council Meeting', 3443, %s) RETURNING id""",
                [meeting_id, video_id, f"https://www.youtube.com/watch?v={video_id}", primary],
            )
            vid = cur.fetchone()[0]
        self.conn.commit()
        return vid

    def measured(self, meeting_video_id: int, *, clip: str, status: str = "passed", version: int = METHOD,
                 days_ago: int = 0, reason: str | None = None) -> None:
        """A stored measurement, written as the migration's owner would (not through save_alignment).

        A `reason` that is given is stored; left out, the row gets the reason its status has by
        default (none on a passed row, `score` on a rejected one, an error text on a failed one).
        """
        span = (635.48, 635.5, 4078.7) if status == "passed" else (None, None, None)
        stored_reason = reason
        if reason is None:
            stored_reason = {"passed": None, "rejected": "score", "failed": "AudioFetchError: no audio"}[status]
        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO meeting_video_alignments
                       (meeting_video_id, granicus_clip_id, method_version, status, reason,
                        offset_s, granicus_start_s, granicus_end_s, measured_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now() - make_interval(days => %s))""",
                [meeting_video_id, clip, version, status, stored_reason, *span, days_ago],
            )
        self.conn.commit()


@pytest.fixture
def align_rows(conn):
    rows = _AlignRows(conn)
    yield rows
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE id = ANY(%s)", [rows.meeting_ids])
    conn.commit()


def _mine(candidates) -> list[str]:
    """The tags of the candidates these tests inserted, in the order returned."""
    return [c.video_id[len(ALIGN_PREFIX):] for c in candidates if c.video_id.startswith(ALIGN_PREFIX)]


def test_alignment_candidates_newest_meeting_first_primary_first_within_the_limit(conn, align_rows):
    older = align_rows.meeting("999911", 6)
    align_rows.video(older, "olderPart2")                       # inserted first, not primary
    older_primary = align_rows.video(older, "olderPart1", primary=True)
    newer = align_rows.meeting("999912", 13)
    align_rows.video(newer, "newer", primary=True)

    got = tdb.alignment_candidates(conn, method_version=METHOD, trusted_version=METHOD, limit=1000)
    assert _mine(got) == ["newer", "olderPart1", "olderPart2"]
    cand = next(c for c in got if c.video_id == ALIGN_PREFIX + "olderPart1")
    assert cand == tdb.AlignmentCandidate(
        meeting_video_id=older_primary, video_id=ALIGN_PREFIX + "olderPart1", meeting_id=older,
        external_id="999911", meeting_date=date(2031, 5, 6))

    # These meetings are dated 2031, later than anything else in the database, so the limit cuts here.
    first_two = tdb.alignment_candidates(conn, method_version=METHOD, trusted_version=METHOD, limit=2)
    assert [c.video_id[len(ALIGN_PREFIX):] for c in first_two] == ["newer", "olderPart1"]


def test_measured_rejected_hidden_and_yt_row_recordings_are_not_alignment_candidates(conn, align_rows):
    shown = align_rows.meeting("999913", 6)
    align_rows.video(shown, "unmeasured", primary=True)
    align_rows.measured(align_rows.video(shown, "passed"), clip="999913")
    # A rejected row is final however old it is; only a failure is tried again.
    align_rows.measured(align_rows.video(shown, "rejected"), clip="999913", status="rejected", days_ago=30)
    hidden = align_rows.meeting("999914", 7, hidden=True)
    align_rows.video(hidden, "hidden", primary=True)
    yt_only = align_rows.meeting("yt-tdbALIGNown", 8, video_url="https://www.youtube.com/watch?v=tdbALIGNown")
    align_rows.video(yt_only, "ytRow", primary=True)
    event = align_rows.meeting("event-999915", 9,
                               video_url="https://bhamal.granicus.com/MediaPlayer.php?view_id=2&event_id=999915")
    align_rows.video(event, "event", primary=True)

    got = tdb.alignment_candidates(conn, method_version=METHOD, trusted_version=METHOD, limit=1000)
    assert _mine(got) == ["unmeasured"]


def test_lower_version_other_clip_and_old_failure_are_alignment_candidates_again(conn, align_rows):
    newest = align_rows.meeting("999916", 20)
    align_rows.measured(align_rows.video(newest, "oldFailure", primary=True),
                        clip="999916", status="failed", days_ago=8)
    align_rows.measured(align_rows.video(newest, "freshFailure"), clip="999916", status="failed", days_ago=6)
    middle = align_rows.meeting("999917", 13)
    align_rows.measured(align_rows.video(middle, "otherClip", primary=True), clip="event-2715")
    oldest = align_rows.meeting("999918", 6)
    align_rows.measured(align_rows.video(oldest, "current", primary=True), clip="999918")
    # The version is a floor: a row from a later method is not measured again by an older producer.
    align_rows.measured(align_rows.video(oldest, "laterMethod"), clip="999918", version=METHOD + 1)

    # At the stored version: the moved recording and the week-old failure, the failure last
    # although its meeting is the newest (never-measured comes before a failure being retried).
    got = tdb.alignment_candidates(conn, method_version=METHOD, trusted_version=METHOD, limit=1000)
    assert _mine(got) == ["otherClip", "oldFailure"]
    # The retry age is the caller's to set.
    got = tdb.alignment_candidates(conn, method_version=METHOD, trusted_version=METHOD, limit=1000, retry_failed_days=5)
    assert _mine(got) == ["otherClip", "oldFailure", "freshFailure"]
    # One version up, every stored row is below the floor and all four are measured again.
    got = tdb.alignment_candidates(conn, method_version=METHOD + 1, trusted_version=METHOD + 1, limit=1000)
    assert _mine(got) == ["oldFailure", "freshFailure", "otherClip", "current"]


def _alignment_row(conn, meeting_video_id: int) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT granicus_clip_id, method_version, status, reason, offset_s, granicus_start_s,
                      granicus_end_s, score, runner_up, windows, windows_confirmed,
                      measured_at > now() - interval '1 minute' AS fresh, stretch
                 FROM meeting_video_alignments WHERE meeting_video_id = %s ORDER BY stretch""",
            [meeting_video_id])
        return [dict(r) for r in cur.fetchall()]


def test_save_alignment_twice_leaves_one_row_holding_the_second_calls_values(conn, align_rows):
    from transcriber.align import Measurement, Stretch

    meeting = align_rows.meeting("999919", 6)
    vid = align_rows.video(meeting, "saved", primary=True)
    cand = next(c for c in tdb.alignment_candidates(conn, method_version=METHOD, trusted_version=METHOD, limit=1000)
                if c.meeting_video_id == vid)
    passed = Measurement(status="passed", reason=None, offset_s=635.48, granicus_start_s=635.5,
                         granicus_end_s=4078.7, score=23.6, runner_up=6.0, windows=12, windows_confirmed=10,
                         stretches=(Stretch(offset_s=635.48, granicus_start_s=635.5, granicus_end_s=4078.7,
                                            score=23.6, runner_up=6.0, windows=12, windows_confirmed=10),))

    tdb.save_alignment(conn, cand, method_version=METHOD, status="passed", measurement=passed)
    conn.commit()
    assert _alignment_row(conn, vid) == [dict(
        granicus_clip_id="999919", method_version=METHOD, status="passed", reason=None, offset_s=635.48,
        granicus_start_s=635.5, granicus_end_s=4078.7, score=23.6, runner_up=6.0, windows=12,
        windows_confirmed=10, fresh=True, stretch=1)]
    assert _mine(tdb.alignment_candidates(conn, method_version=METHOD, trusted_version=METHOD, limit=1000)) == []

    with conn.cursor() as cur:
        cur.execute("UPDATE meeting_video_alignments SET measured_at = now() - interval '30 days' "
                    "WHERE meeting_video_id = %s", [vid])
    conn.commit()
    assert _alignment_row(conn, vid)[0]["fresh"] is False

    # The second call carries no measurement: every column takes its value, the empty ones too.
    tdb.save_alignment(conn, cand, method_version=METHOD + 1, status="failed",
                       reason="AudioFetchError: yt-dlp could not download tdbALIGNsaved")
    conn.commit()
    assert _alignment_row(conn, vid) == [dict(
        granicus_clip_id="999919", method_version=METHOD + 1, status="failed",
        reason="AudioFetchError: yt-dlp could not download tdbALIGNsaved", offset_s=None,
        granicus_start_s=None, granicus_end_s=None, score=None, runner_up=None, windows=None,
        windows_confirmed=None, fresh=True, stretch=1)]

    # A rejected measurement keeps its numbers beside its reason.
    rejected = Measurement(status="rejected", reason="score", offset_s=-84.04, granicus_start_s=None,
                           granicus_end_s=None, score=5.4, runner_up=4.3, windows=3, windows_confirmed=0)
    tdb.save_alignment(conn, cand, method_version=METHOD, status="rejected", reason="score",
                       measurement=rejected)
    conn.commit()
    row = _alignment_row(conn, vid)
    assert len(row) == 1 and (row[0]["status"], row[0]["reason"], row[0]["offset_s"], row[0]["score"],
                              row[0]["windows"], row[0]["windows_confirmed"]) == ("rejected", "score", -84.04, 5.4, 3, 0)


def test_alignment_backlog_counts_the_candidates_without_a_limit(conn, align_rows):
    before = tdb.alignment_backlog(conn, method_version=METHOD, trusted_version=METHOD)
    before_any_failure = tdb.alignment_backlog(conn, method_version=METHOD, trusted_version=METHOD, retry_failed_days=0)
    before_next_version = tdb.alignment_backlog(conn, method_version=METHOD + 1, trusted_version=METHOD + 1)
    meeting = align_rows.meeting("999920", 6)
    for tag in ("one", "two", "three"):
        align_rows.video(meeting, tag, primary=(tag == "one"))
    align_rows.measured(align_rows.video(meeting, "done"), clip="999920")
    align_rows.measured(align_rows.video(meeting, "freshFailure"), clip="999920", status="failed", days_ago=1)

    assert tdb.alignment_backlog(conn, method_version=METHOD, trusted_version=METHOD) == before + 3
    assert tdb.alignment_backlog(conn, method_version=METHOD, trusted_version=METHOD) == len(
        tdb.alignment_candidates(conn, method_version=METHOD, trusted_version=METHOD, limit=100000))
    assert len(tdb.alignment_candidates(conn, method_version=METHOD, trusted_version=METHOD, limit=1)) == 1
    assert tdb.alignment_backlog(conn, method_version=METHOD, trusted_version=METHOD, retry_failed_days=0) == before_any_failure + 4
    assert tdb.alignment_backlog(conn, method_version=METHOD + 1, trusted_version=METHOD + 1) == before_next_version + 5


def test_a_passed_row_at_the_trusted_floor_is_not_a_candidate_at_the_next_version_and_a_rejected_one_is(
        conn, align_rows):
    """Plan `youtube-links-cover-matching-stretches`, M2: a passed row stays trusted from the floor up."""
    backlog_floor = tdb.alignment_backlog(conn, method_version=METHOD + 1, trusted_version=METHOD)
    backlog_no_floor = tdb.alignment_backlog(conn, method_version=METHOD + 1, trusted_version=METHOD + 1)
    meeting = align_rows.meeting("999921", 6)
    align_rows.measured(align_rows.video(meeting, "passed", primary=True), clip="999921")
    align_rows.measured(align_rows.video(meeting, "rejected"), clip="999921", status="rejected")

    got = tdb.alignment_candidates(conn, method_version=METHOD + 1, trusted_version=METHOD, limit=1000)
    assert _mine(got) == ["rejected"]
    assert tdb.alignment_backlog(conn, method_version=METHOD + 1, trusted_version=METHOD) == backlog_floor + 1

    got = tdb.alignment_candidates(conn, method_version=METHOD + 1, trusted_version=METHOD + 1, limit=1000)
    assert _mine(got) == ["passed", "rejected"]
    assert tdb.alignment_backlog(
        conn, method_version=METHOD + 1, trusted_version=METHOD + 1) == backlog_no_floor + 2


def test_a_switched_off_row_is_not_a_candidate_until_it_is_restored(conn, align_rows):
    """Plan `youtube-links-cover-matching-stretches`, M5: a `rejected` row with reason `operator`
    is the owner's off switch. It is never a candidate, whatever its version or clip id, and the
    restore puts it back under the ordinary rules. The statements are the runbook's, narrowed to
    this test's recordings."""
    floor = dict(method_version=METHOD + 1, trusted_version=METHOD)
    backlog_before = tdb.alignment_backlog(conn, **floor)
    meeting = align_rows.meeting("999923", 6)
    off = align_rows.video(meeting, "off", primary=True)
    align_rows.measured(off, clip="999923")
    off_other_clip = align_rows.video(meeting, "off_other_clip")
    align_rows.measured(off_other_clip, clip="999900")
    align_rows.measured(align_rows.video(meeting, "windows"), clip="999923", status="rejected", reason="windows")
    no_reason = align_rows.video(meeting, "no_reason")
    align_rows.measured(no_reason, clip="999923", status="rejected")
    with conn.cursor() as cur:      # the fixture gives a rejection a reason; this one has none
        cur.execute("UPDATE meeting_video_alignments SET reason = NULL WHERE meeting_video_id = %s", [no_reason])
    conn.commit()
    assert [(r["status"], r["reason"]) for r in _alignment_row(conn, no_reason)] == [("rejected", None)]
    align_rows.measured(align_rows.video(meeting, "on"), clip="999923")

    with conn.cursor() as cur:
        cur.execute(
            """UPDATE meeting_video_alignments SET status = 'rejected', reason = 'operator'
                WHERE status = 'passed' AND meeting_video_id IN (%s, %s)""", [off, off_other_clip])
        assert cur.rowcount == 2
    conn.commit()
    assert [(r["status"], r["reason"]) for r in _alignment_row(conn, off)] == [("rejected", "operator")]

    got = _mine(tdb.alignment_candidates(conn, limit=1000, **floor))
    assert sorted(got) == ["no_reason", "windows"]
    assert tdb.alignment_backlog(conn, **floor) == backlog_before + 2

    with conn.cursor() as cur:
        cur.execute(
            """UPDATE meeting_video_alignments SET status = 'passed', reason = NULL
                WHERE status = 'rejected' AND reason = 'operator' AND meeting_video_id IN (%s, %s)""",
            [off, off_other_clip])
        assert cur.rowcount == 2
    conn.commit()
    row = _alignment_row(conn, off)
    assert len(row) == 1 and (row[0]["status"], row[0]["reason"], row[0]["offset_s"], row[0]["granicus_start_s"],
                              row[0]["granicus_end_s"]) == ("passed", None, 635.48, 635.5, 4078.7)
    # Restored, the rows are passed rows again: one stays trusted, the other is against another clip.
    got = _mine(tdb.alignment_candidates(conn, limit=1000, **floor))
    assert sorted(got) == ["no_reason", "off_other_clip", "windows"]
    assert tdb.alignment_backlog(conn, **floor) == backlog_before + 3

    # The exemption is for a `rejected` row only: a row passed by hand keeps the reason `operator`
    # (production row 832) and answers to the ordinary rules, here the changed clip id.
    align_rows.measured(align_rows.video(meeting, "by_hand"), clip="999900", reason="operator")
    got = _mine(tdb.alignment_candidates(conn, limit=1000, **floor))
    assert sorted(got) == ["by_hand", "no_reason", "off_other_clip", "windows"]


def test_save_alignment_replaces_a_recordings_stretch_rows(conn, align_rows):
    """Plan `youtube-links-cover-matching-stretches`, M2: one row per stretch, replaced whole on a re-measure."""
    from transcriber.align import Measurement, Stretch

    backlog_before = tdb.alignment_backlog(conn, method_version=METHOD + 1, trusted_version=METHOD + 1)
    meeting = align_rows.meeting("999922", 6)
    vid = align_rows.video(meeting, "stretches", primary=True)
    cand = next(c for c in tdb.alignment_candidates(conn, method_version=METHOD, trusted_version=METHOD, limit=1000)
                if c.meeting_video_id == vid)
    first = Stretch(offset_s=300.0, granicus_start_s=300.0, granicus_end_s=1500.0, score=49.5,
                    runner_up=3.7, windows=4, windows_confirmed=4)
    second = Stretch(offset_s=490.0, granicus_start_s=1690.0, granicus_end_s=2000.0, score=13.3,
                     runner_up=3.7, windows=2, windows_confirmed=2)
    passed = Measurement(status="passed", reason=None, offset_s=300.0, granicus_start_s=300.0,
                         granicus_end_s=1500.0, score=49.5, runner_up=3.7, windows=4, windows_confirmed=4,
                         stretches=(first, second))

    tdb.save_alignment(conn, cand, method_version=METHOD, status="passed", measurement=passed)
    conn.commit()
    assert _alignment_row(conn, vid) == [
        dict(granicus_clip_id="999922", method_version=METHOD, status="passed", reason=None, offset_s=300.0,
             granicus_start_s=300.0, granicus_end_s=1500.0, score=49.5, runner_up=3.7, windows=4,
             windows_confirmed=4, fresh=True, stretch=1),
        dict(granicus_clip_id="999922", method_version=METHOD, status="passed", reason=None, offset_s=490.0,
             granicus_start_s=1690.0, granicus_end_s=2000.0, score=13.3, runner_up=3.7, windows=2,
             windows_confirmed=2, fresh=True, stretch=2),
    ]
    # Two rows are one recording: it is returned once and counted once.
    got = tdb.alignment_candidates(conn, method_version=METHOD + 1, trusted_version=METHOD + 1, limit=1000)
    assert _mine(got) == ["stretches"]
    assert tdb.alignment_backlog(
        conn, method_version=METHOD + 1, trusted_version=METHOD + 1) == backlog_before + 1

    # A rejected re-measure leaves one row: the second stretch goes, the scalars stay.
    rejected = Measurement(status="rejected", reason="score", offset_s=-84.04, granicus_start_s=None,
                           granicus_end_s=None, score=5.4, runner_up=4.3, windows=3, windows_confirmed=1)
    tdb.save_alignment(conn, cand, method_version=METHOD, status="rejected", reason="score",
                       measurement=rejected)
    conn.commit()
    assert _alignment_row(conn, vid) == [dict(
        granicus_clip_id="999922", method_version=METHOD, status="rejected", reason="score", offset_s=-84.04,
        granicus_start_s=None, granicus_end_s=None, score=5.4, runner_up=4.3, windows=3,
        windows_confirmed=1, fresh=True, stretch=1)]

    # An error text is kept to its first 4,000 characters, as before the table was re-keyed.
    tdb.save_alignment(conn, cand, method_version=METHOD, status="failed", reason="AudioFetchError: " + "x" * 5000)
    conn.commit()
    row = _alignment_row(conn, vid)
    assert len(row) == 1 and (row[0]["stretch"], row[0]["status"], len(row[0]["reason"])) == (1, "failed", 4000)

    no_stretches = Measurement(status="passed", reason=None, offset_s=300.0, granicus_start_s=300.0,
                               granicus_end_s=1500.0, score=49.5, runner_up=3.7, windows=4, windows_confirmed=4)
    with pytest.raises(ValueError, match="a passed measurement has no stretches"):
        tdb.save_alignment(conn, cand, method_version=METHOD, status="passed", measurement=no_stretches)
    # Read in the same transaction, before any rollback: the refusal came before the delete.
    assert len(_alignment_row(conn, vid)) == 1, "the refused save wrote nothing"


# --- where a Granicus clip is silent (plan silent-granicus-says-so M2) ---

def _sound_rows(conn, meeting_id: int) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT meeting_id, granicus_clip_id, method_version, duration_s, silent_s, silent_spans,
                      measured_at > now() - interval '1 minute' AS fresh
                 FROM granicus_clip_sound WHERE meeting_id = %s""",
            [meeting_id])
        return [dict(r) for r in cur.fetchall()]


def test_save_clip_sound_stores_the_clip_its_version_and_its_spans(conn, align_rows):
    from transcriber.sound import ClipSound

    meeting = align_rows.meeting("999923", 6)
    vid = align_rows.video(meeting, "sound", primary=True)
    cand = next(c for c in tdb.alignment_candidates(conn, method_version=METHOD, trusted_version=METHOD, limit=1000)
                if c.meeting_video_id == vid)
    conn.rollback()
    sound = ClipSound(duration_s=6019.0, silent_s=2719.0,
                      spans=((0.0, 60.0), (120.0, 180.0), (240.0, 720.0), (780.0, 2040.0), (5160.0, 6019.0)))

    # The save does not commit: the caller's rollback takes it back.
    tdb.save_clip_sound(conn, cand, sound, method_version=1)
    conn.rollback()
    assert _sound_rows(conn, meeting) == []

    tdb.save_clip_sound(conn, cand, sound, method_version=1)
    conn.commit()
    assert _sound_rows(conn, meeting) == [dict(
        meeting_id=meeting, granicus_clip_id="999923", method_version=1, duration_s=6019.0, silent_s=2719.0,
        silent_spans=[[0.0, 60.0], [120.0, 180.0], [240.0, 720.0], [780.0, 2040.0], [5160.0, 6019.0]],
        fresh=True)]


def test_save_clip_sound_twice_leaves_one_row_holding_the_second_calls_values(conn, align_rows):
    from dataclasses import replace
    from transcriber.sound import ClipSound

    meeting = align_rows.meeting("999924", 6)
    vid = align_rows.video(meeting, "soundTwice", primary=True)
    cand = next(c for c in tdb.alignment_candidates(conn, method_version=METHOD, trusted_version=METHOD, limit=1000)
                if c.meeting_video_id == vid)
    tdb.save_clip_sound(conn, cand, ClipSound(duration_s=2516.0, silent_s=2516.0, spans=((0.0, 2516.0),)),
                        method_version=1)
    with conn.cursor() as cur:
        cur.execute("UPDATE granicus_clip_sound SET measured_at = now() - interval '30 days' "
                    "WHERE meeting_id = %s", [meeting])
    conn.commit()
    assert _sound_rows(conn, meeting)[0]["fresh"] is False

    # The second call differs in every column the writer sets, the clip id and the empty spans included.
    tdb.save_clip_sound(conn, replace(cand, external_id="999925"),
                        ClipSound(duration_s=3761.0, silent_s=0.0, spans=()), method_version=2)
    conn.commit()
    assert _sound_rows(conn, meeting) == [dict(
        meeting_id=meeting, granicus_clip_id="999925", method_version=2, duration_s=3761.0, silent_s=0.0,
        silent_spans=[], fresh=True)]
