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
       AND m.external_id ~ '^[0-9]+$'
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


def mark_status(conn, transcript_id: int, status: str, *, error: str | None = None, **fields) -> None:
    bad = set(fields) - _UPDATABLE
    if bad:
        raise ValueError(f"not updatable: {sorted(bad)}")
    sets = ["status = %s", "updated_at = now()", "last_attempted_at = now()"]
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
