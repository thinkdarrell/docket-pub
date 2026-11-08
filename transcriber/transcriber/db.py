"""Producer-side Postgres access. Connects ONLY as the `transcriber` role.

Claiming is serialized with a transaction-scoped advisory lock instead of
SELECT ... FOR UPDATE, because FOR UPDATE on `meetings` would need UPDATE
privilege the role does not have. Two producers can run at once; the lock
makes the "find newest eligible" + "insert claim" pair atomic.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date

import psycopg2
import psycopg2.extras

from .contract import TranscriptOutput

_UPDATABLE = {"audio_sha256", "audio_duration_s", "raw_output_path", "speech_ratio",
              "word_count", "engine", "asr_model", "diarization_model"}


@dataclass(frozen=True)
class Claim:
    transcript_id: int
    meeting_id: int
    external_id: str
    title: str
    meeting_date: date
    status: str
    prior: dict | None = None      # the whole pre-claim row when claim_meeting re-claimed an uploaded
                                   # meeting resting at uploaded or a worker status (never a producer
                                   # status: that is a crashed re-run); restore_row() writes it back


@dataclass(frozen=True)
class AlignmentCandidate:
    """One attached YouTube recording that needs measuring against its meeting's Granicus clip."""
    meeting_video_id: int
    video_id: str
    meeting_id: int
    external_id: str          # the Granicus clip id
    meeting_date: date


def connect(url: str):
    return psycopg2.connect(url)


_CANDIDATE_SQL = """
    SELECT m.id AS meeting_id, m.external_id, m.title, m.meeting_date,
           t.id AS transcript_id, t.status
      FROM meetings m
      JOIN municipalities mu ON mu.id = m.municipality_id
      LEFT JOIN transcripts t ON t.meeting_id = m.id
     WHERE mu.slug = 'birmingham'
       AND m.video_url IS NOT NULL
       AND m.is_hidden = FALSE
       AND (m.external_id ~ '^[0-9]+$' OR m.external_id LIKE 'yt-%%')
       AND m.meeting_date >= %(since)s
       AND (
            t.id IS NULL
         OR (t.status = 'transcribed'
             AND (t.producer_host = %(host)s
                  OR t.claimed_at < now() - make_interval(hours => %(stale)s)))
         OR (t.status = 'failed' AND %(retry_failed)s)
         OR (t.status IN ('claimed', 'audio_fetched')
             AND t.claimed_at < now() - make_interval(hours => %(stale)s))
       )
     ORDER BY m.meeting_date DESC, m.id DESC
     LIMIT 1
"""


def claim_next(conn, *, since: date, host: str, stale_after_hours: int = 6,
               retry_failed: bool = False) -> Claim | None:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext('transcriber_claim'))")
        cur.execute(_CANDIDATE_SQL, {"since": since, "stale": stale_after_hours, "host": host,
                                    "retry_failed": retry_failed})
        row = cur.fetchone()
        if row is None:
            return None
        if row["transcript_id"] is None:
            cur.execute(
                """INSERT INTO transcripts (meeting_id, status, producer_host, claimed_at)
                   VALUES (%s, 'claimed', %s, now()) RETURNING id, status""",
                [row["meeting_id"], host],
            )
        else:
            new_status = "transcribed" if row["status"] == "transcribed" else "claimed"
            cur.execute(
                """UPDATE transcripts
                      SET status = %s, producer_host = %s, claimed_at = now(), updated_at = now()
                    WHERE id = %s RETURNING id, status""",
                [new_status, host, row["transcript_id"]],
            )
        t = cur.fetchone()
    return Claim(t["id"], row["meeting_id"], row["external_id"], row["title"],
                 row["meeting_date"], t["status"])


_MEETING_SQL = """
    SELECT m.id AS meeting_id, m.external_id, m.title, m.meeting_date,
           t.id AS transcript_id, t.status, t.uploaded_at, t.last_attempted_at,
           (t.last_attempted_at > now() - interval '30 minutes') AS busy
      FROM meetings m
      JOIN municipalities mu ON mu.id = m.municipality_id
      LEFT JOIN transcripts t ON t.meeting_id = m.id
     WHERE m.id = %(meeting_id)s
       AND mu.slug = 'birmingham'
       AND m.video_url IS NOT NULL
       AND m.is_hidden = FALSE
       AND (m.external_id ~ '^[0-9]+$' OR m.external_id LIKE 'yt-%%')
"""


def meeting_source(conn, meeting_id: int) -> str | None:
    """The clip id or yt- id of an eligible Birmingham meeting (the same filter as
    _MEETING_SQL), or None. Read-only: the cache and capture passes never claim."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT m.external_id
                 FROM meetings m
                 JOIN municipalities mu ON mu.id = m.municipality_id
                WHERE m.id = %s
                  AND mu.slug = 'birmingham'
                  AND m.video_url IS NOT NULL
                  AND m.is_hidden = FALSE
                  AND (m.external_id ~ '^[0-9]+$' OR m.external_id LIKE 'yt-%%')""",
            [meeting_id],
        )
        row = cur.fetchone()
        return row[0] if row else None


class MeetingBusy(Exception):
    """The worker's claim stamped this transcript's row within the last 30 minutes (a stage may
    be in flight; its `advance()` would overwrite our claim and a finishing compare would clear
    the `transcript_changed` marker). The worker's `CLAIM_SQL` is the only writer of a timestamp
    into `last_attempted_at` (every other writer resets it to NULL); the producer's `mark_status()`
    never writes it, so a re-run right after a failed one is not refused."""

    def __init__(self, meeting_id: int, touched_at):
        super().__init__(f"meeting {meeting_id} was touched at {touched_at}")
        self.meeting_id = meeting_id
        self.touched_at = touched_at


def claim_meeting(conn, *, meeting_id: int, host: str) -> Claim | None:
    """Re-claim one meeting whatever its status (the `--meeting-id` re-run path).

    Returns None when the meeting is not an eligible Birmingham meeting. A row that was
    uploaded before (`uploaded_at` set) and rests at `uploaded` or a worker status is first
    read whole and carried on the returned `Claim` as `prior`, so that a re-run ending
    `failed` or `low_speech` can hand it to `restore_row()` and leave the row exactly as it
    was before the claim; a row resting at a producer status (`claimed`, `audio_fetched`,
    `transcribed`) is one a previous re-run died on, and that crashed state is never taken as
    `prior`. A row resting at `low_speech` is re-claimed with `uploaded_at` NULL: the worker's
    fitness gate leaves `uploaded_at` and the segments on such a row and the public predicate
    hides it by status alone, so the claim's `status = 'claimed'` would otherwise publish it for
    the run; `prior` keeps the original value for `restore_row()`, and `upload()` sets it anew
    (decision 0050). Such a row is marked `compare_skipped_reason = 'transcript_changed'` so the
    worker's compare stage treats the re-upload as changed input (decision 0045); a
    never-uploaded row keeps its stored reason and has no `prior`. Stage counters and errors
    are reset so the worker starts clean.
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext('transcriber_claim'))")
        cur.execute(_MEETING_SQL, {"meeting_id": meeting_id})
        row = cur.fetchone()
        if row is None:
            return None
        if row["busy"]:
            raise MeetingBusy(meeting_id, row["last_attempted_at"])
        prior = None
        if (row["transcript_id"] is not None and row["uploaded_at"] is not None
                and row["status"] not in ("claimed", "audio_fetched", "transcribed")):
            # The row lock keeps a worker write from landing between this snapshot and the UPDATE
            # below, which must read the same row version (decision 0051).
            cur.execute("SELECT * FROM transcripts WHERE id = %s FOR UPDATE", [row["transcript_id"]])
            prior = dict(cur.fetchone())
        if row["transcript_id"] is None:
            cur.execute(
                """INSERT INTO transcripts (meeting_id, status, producer_host, claimed_at)
                   VALUES (%s, 'claimed', %s, now()) RETURNING id, status""",
                [row["meeting_id"], host],
            )
        else:
            cur.execute(
                """UPDATE transcripts
                      SET status = 'claimed', producer_host = %s, claimed_at = now(), updated_at = now(),
                          stage_attempts = 0, last_attempted_at = NULL, needs_review_reason = NULL,
                          last_error = NULL,
                          uploaded_at = CASE WHEN status = 'low_speech' THEN NULL ELSE uploaded_at END,
                          compare_skipped_reason = CASE WHEN uploaded_at IS NOT NULL THEN 'transcript_changed'
                                                        ELSE compare_skipped_reason END
                    WHERE id = %s RETURNING id, status""",
                [host, row["transcript_id"]],
            )
        t = cur.fetchone()
    return Claim(t["id"], row["meeting_id"], row["external_id"], row["title"],
                 row["meeting_date"], t["status"], prior=prior)


def restore_row(conn, transcript_id: int, prior: dict) -> None:
    """Write a `Claim.prior` snapshot back, every column except id and meeting_id, so a
    re-run that ends without an upload leaves the row exactly as it was before the claim."""
    cols = [c for c in prior if c not in ("id", "meeting_id")]
    with conn.cursor() as cur:
        cur.execute(f"UPDATE transcripts SET {', '.join(f'{c} = %s' for c in cols)} WHERE id = %s",
                    [prior[c] for c in cols] + [transcript_id])


def mark_status(conn, transcript_id: int, status: str, *, error: str | None = None, **fields) -> None:
    bad = set(fields) - _UPDATABLE
    if bad:
        raise ValueError(f"not updatable: {sorted(bad)}")
    sets = ["status = %s", "updated_at = now()"]
    params: list = [status]
    if error is not None:
        sets.append("last_error = %s")
        params.append(error[:4000])
    if status == "failed":
        sets.append("stage_attempts = stage_attempts + 1")
    for k, v in fields.items():
        sets.append(f"{k} = %s")
        params.append(v)
    params.append(transcript_id)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE transcripts SET {', '.join(sets)} WHERE id = %s", params)


def heartbeat(conn, host: str, status: str, meeting_id: int | None, version: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO producer_heartbeats (host, last_seen_at, last_status, last_meeting_id, producer_version)
               VALUES (%s, now(), %s, %s, %s)
               ON CONFLICT (host) DO UPDATE
                 SET last_seen_at = now(), last_status = EXCLUDED.last_status,
                     last_meeting_id = EXCLUDED.last_meeting_id,
                     producer_version = EXCLUDED.producer_version""",
            [host, status, meeting_id, version],
        )


def roster_for_meeting(conn, meeting_id: int) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT cm.name
                 FROM council_members cm
                 JOIN meetings m ON m.municipality_id = cm.municipality_id
                WHERE m.id = %s
                  AND (cm.term_start IS NULL OR cm.term_start <= m.meeting_date)
                  AND (cm.term_end   IS NULL OR cm.term_end   >= m.meeting_date)
                ORDER BY cm.name""",
            [meeting_id],
        )
        return [r[0] for r in cur.fetchall()]


def _copy_escape(s: str) -> str:
    return (s.replace("\\", "\\\\").replace("\t", "\\t")
             .replace("\n", "\\n").replace("\r", "\\r"))


def upload(conn, out: TranscriptOutput) -> int:
    out.validate()
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM transcripts WHERE meeting_id = %s", [out.meeting_id])
        row = cur.fetchone()
        if row is None:
            raise RuntimeError(f"no transcripts row for meeting {out.meeting_id}; claim first")
        transcript_id = row[0]

        cur.execute("DELETE FROM transcript_segments WHERE transcript_id = %s", [transcript_id])

        speaker_ids: dict[str, int] = {}
        for sp in out.speakers:
            cur.execute(
                """INSERT INTO transcript_speakers (meeting_id, cluster_label, embedding)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (meeting_id, cluster_label) DO UPDATE
                     SET embedding = COALESCE(EXCLUDED.embedding, transcript_speakers.embedding)
                   RETURNING id""",
                [out.meeting_id, sp.cluster_label, sp.embedding],
            )
            speaker_ids[sp.cluster_label] = cur.fetchone()[0]

        # A re-run: drop the model's rows for clusters this output no longer has (ghost rows),
        # then clear the model's resolution on the rest so the page never shows an old cluster's
        # name on a new cluster that reuses its label. Manual rows are left alone (D54).
        cur.execute(
            """DELETE FROM transcript_speakers
                WHERE meeting_id = %s AND is_manual = FALSE AND NOT (cluster_label = ANY(%s))""",
            [out.meeting_id, [sp.cluster_label for sp in out.speakers]],
        )
        cur.execute(
            """UPDATE transcript_speakers
                  SET council_member_id = NULL, display_name = NULL, role = NULL, confidence = NULL,
                      method = NULL, needs_review = FALSE
                WHERE meeting_id = %s AND is_manual = FALSE""",
            [out.meeting_id],
        )

        buf = io.StringIO()
        for s in out.segments:
            sid = speaker_ids.get(s.cluster_label) if s.cluster_label else None
            buf.write("\t".join([
                str(transcript_id), str(s.seq), repr(float(s.start_s)), repr(float(s.end_s)),
                _copy_escape(s.text),
                s.cluster_label if s.cluster_label else "\\N",
                str(sid) if sid is not None else "\\N",
                repr(float(s.avg_logprob)) if s.avg_logprob is not None else "\\N",
                repr(float(s.no_speech_prob)) if s.no_speech_prob is not None else "\\N",
                "t" if s.is_silence else "f",
            ]) + "\n")
        buf.seek(0)
        cur.copy_expert(
            """COPY transcript_segments
                 (transcript_id, seq, start_s, end_s, text, cluster_label, speaker_id,
                  avg_logprob, no_speech_prob, is_silence)
               FROM STDIN WITH (FORMAT text)""",
            buf,
        )

        cur.execute(
            """UPDATE transcripts
                  SET status = 'uploaded', uploaded_at = now(), updated_at = now(),
                      version = %s, engine = %s, asr_model = %s, diarization_model = %s,
                      audio_duration_s = %s, speech_ratio = %s, word_count = %s,
                      audio_sha256 = %s, last_error = NULL
                WHERE id = %s""",
            [out.version, out.engine, out.asr_model, out.diarization_model,
             out.audio_duration_s, out.speech_ratio, out.word_count, out.audio_sha256,
             transcript_id],
        )
    return len(out.segments)


# --- measuring attached YouTube recordings (meeting_video_alignments, migration 042) ---

# A measurement counts only at or above the method version asked for (a floor, never equality)
# and against the clip the meeting row names today; anything else is as good as no measurement.
_ALIGNMENT_UNMEASURED = """(a.meeting_video_id IS NULL
            OR a.method_version < %(method_version)s
            OR a.granicus_clip_id <> m.external_id)"""

_ALIGNMENT_FROM_WHERE = f"""
      FROM meeting_videos v
      JOIN meetings m ON m.id = v.meeting_id
      JOIN municipalities mu ON mu.id = m.municipality_id
      LEFT JOIN meeting_video_alignments a ON a.meeting_video_id = v.id
     WHERE v.provider = 'youtube'
       AND mu.slug = 'birmingham'
       AND m.is_hidden = FALSE
       AND m.external_id ~ '^[0-9]+$'
       AND strpos(m.video_url, 'MediaPlayer.php') > 0
       AND ({_ALIGNMENT_UNMEASURED}
            OR (a.status = 'failed'
                AND a.measured_at < now() - make_interval(days => %(retry_failed_days)s)))
"""

_ALIGNMENT_CANDIDATES_SQL = f"""
    SELECT v.id AS meeting_video_id, v.video_id, m.id AS meeting_id, m.external_id, m.meeting_date
    {_ALIGNMENT_FROM_WHERE}
     ORDER BY CASE WHEN {_ALIGNMENT_UNMEASURED} THEN 0 ELSE 1 END,
              m.meeting_date DESC, m.id DESC, v.is_primary DESC, v.id
     LIMIT %(limit)s
"""

_ALIGNMENT_REASON_MAX = 4000    # an error text is kept to this length, as mark_status keeps last_error


def alignment_candidates(conn, *, method_version: int, limit: int,
                         retry_failed_days: int = 7) -> list[AlignmentCandidate]:
    """The attached YouTube recordings to measure next, at most `limit`.

    A candidate is a `youtube` recording on a Birmingham meeting that is not hidden and is a
    Granicus clip (an all-digit `external_id` and a `MediaPlayer.php` `video_url`), with no
    measurement, or one below `method_version`, or one made against another clip id, or a
    `failed` one older than `retry_failed_days`. A `passed` or `rejected` row at the current
    version and clip is final. Recordings never measured (the first three cases) come before
    failures being retried; within each, newest meeting first, the primary recording first.
    Read-only; the caller ends the transaction.
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(_ALIGNMENT_CANDIDATES_SQL, {"method_version": method_version, "limit": limit,
                                                "retry_failed_days": retry_failed_days})
        return [AlignmentCandidate(r["meeting_video_id"], r["video_id"], r["meeting_id"],
                                   r["external_id"], r["meeting_date"]) for r in cur.fetchall()]


def alignment_backlog(conn, *, method_version: int, retry_failed_days: int = 7) -> int:
    """How many recordings `alignment_candidates` would return with no limit."""
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) {_ALIGNMENT_FROM_WHERE}",
                    {"method_version": method_version, "retry_failed_days": retry_failed_days})
        return cur.fetchone()[0]


def save_alignment(conn, cand: AlignmentCandidate, *, method_version: int, status: str,
                   reason: str | None = None, measurement=None) -> None:
    """Store one recording's measurement, replacing any row it already has. Does not commit.

    `status` is `passed`, `rejected`, or `failed`; `reason` is the verdict's reason for a
    rejected row and the error text for a failed one. `measurement` is a
    `transcriber.align.Measurement` (read by attribute, so this module does not import numpy)
    or None when nothing was measured. Every column is written on a re-measure, so a row that
    once held an offset does not keep it under a later `failed`; `granicus_clip_id` is the
    candidate's `external_id` and `measured_at` is the time of this call.
    """
    def _num(name: str, kind):
        value = getattr(measurement, name, None)
        return None if value is None else kind(value)

    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO meeting_video_alignments
                   (meeting_video_id, granicus_clip_id, method_version, status, reason,
                    offset_s, granicus_start_s, granicus_end_s, score, runner_up,
                    windows, windows_confirmed, measured_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
               ON CONFLICT (meeting_video_id) DO UPDATE
                 SET granicus_clip_id = EXCLUDED.granicus_clip_id,
                     method_version = EXCLUDED.method_version,
                     status = EXCLUDED.status,
                     reason = EXCLUDED.reason,
                     offset_s = EXCLUDED.offset_s,
                     granicus_start_s = EXCLUDED.granicus_start_s,
                     granicus_end_s = EXCLUDED.granicus_end_s,
                     score = EXCLUDED.score,
                     runner_up = EXCLUDED.runner_up,
                     windows = EXCLUDED.windows,
                     windows_confirmed = EXCLUDED.windows_confirmed,
                     measured_at = EXCLUDED.measured_at""",
            [cand.meeting_video_id, cand.external_id, method_version, status,
             reason[:_ALIGNMENT_REASON_MAX] if reason is not None else None,
             _num("offset_s", float), _num("granicus_start_s", float), _num("granicus_end_s", float),
             _num("score", float), _num("runner_up", float),
             _num("windows", int), _num("windows_confirmed", int)],
        )
