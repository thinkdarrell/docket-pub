"""The measuring pass: where each attached YouTube recording sits on its Granicus clip's clock.

The council streams a meeting to YouTube as well as to Granicus, and the worker attaches the
YouTube recording to the Granicus meeting (a ``meeting_videos`` row). The two recordings do
not start at the same moment, so before the site may open YouTube at a second stored on the
Granicus clock, the offset between them has to be measured from the sound. This module does
that at the start of an ordinary producer run, before the speech model is loaded, so it needs
no graphics card.

For each recording that ``db.alignment_candidates`` returns, newest meeting first: put the
Granicus audio in the work folder at 8 kHz (decoded from the archive's ``audio.flac`` when
the meeting has one, downloaded from Granicus otherwise), download the YouTube recording's
smallest audio track, convert it to 8 kHz, let ``align.measure`` compare the two, store one
``meeting_video_alignments`` row, commit, and log one line. Both WAV files and the download
are deleted when the recording has been measured; nothing is written to the archive.

A recording whose audio cannot be fetched, converted, read, or measured gets a ``failed`` row
(tried again after seven days) and the pass goes on. Three failed fetches in a row end the
pass. Nothing the pass meets ends the run: a database error (migration 042 not applied, or
the role lacks its grants) and anything else unexpected are logged as one
``measure: skipped (...)`` warning, and the run goes on to transcription.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import psycopg2

from . import align, inputs
from . import db as tdb
from .audio import YOUTUBE_PREFIX, download_url_for, fetch_audio, remove_downloads, source_for

log = logging.getLogger(__name__)

MEASURE_PAUSE_S = 3.0                    # slept after each request to Granicus
MEASURE_MAX_CONSECUTIVE_FAILURES = 3     # failed fetches in a row (not failed rows) that end the pass
MEASURE_YTDLP_FORMAT = "worstaudio/bestaudio/worst"   # the smallest track; ffmpeg keeps only audio
MEASURE_RATE = 8000                      # what align.read_wav accepts

_LOG_ERROR_CHARS = 300                   # a yt-dlp error can run to a page; the row keeps more of it


def _reason(error: BaseException) -> str:
    """A failed row's reason: the exception's class name, a colon, and its message."""
    return f"{type(error).__name__}: {error}"


def _one_line(text: object) -> str:
    line = " ".join(str(text).split())
    return line if len(line) <= _LOG_ERROR_CHARS else line[:_LOG_ERROR_CHARS - 3] + "..."


def _halt(stop, deadline: float | None, clock) -> str | None:
    """Why the pass should stop before the next recording, or None."""
    if stop is not None and stop.requested:
        return "stop requested"
    if deadline is not None and clock() > deadline:
        return "max-hours reached"
    return None


def _granicus_features(cfg, cand: tdb.AlignmentCandidate, wav: Path, sleep):
    """The Granicus clip's features, by way of an 8 kHz WAV at ``wav`` (the caller deletes it).
    The archive's audio.flac is read when the meeting has one, which spares Granicus a
    request; it is never written, replaced, or removed here."""
    flac = inputs.audio_path(cfg.archive_dir, cand.meeting_id)
    if flac.exists():
        fetch_audio(str(flac), wav, rate=MEASURE_RATE, attempts=1)
    else:
        try:
            fetch_audio(download_url_for(cand.external_id), wav, rate=MEASURE_RATE)
        finally:
            sleep(MEASURE_PAUSE_S)       # owed for the request, whether or not it succeeded
    return align.features(align.read_wav(wav))


def _measure_recording(cfg, cand: tdb.AlignmentCandidate, granicus) -> align.Measurement:
    """Download one YouTube recording's audio, measure it against the clip's features, and
    leave nothing of it in the work folder."""
    yt_id = YOUTUBE_PREFIX + cand.video_id
    wav = Path(cfg.work_dir) / f"align-yt-{cand.video_id}.wav"
    try:
        download = source_for(yt_id, cfg.work_dir, audio_format=MEASURE_YTDLP_FORMAT)
        fetch_audio(download, wav, rate=MEASURE_RATE, attempts=1)
        return align.measure(granicus, align.features(align.read_wav(wav)))
    finally:
        wav.unlink(missing_ok=True)
        remove_downloads(yt_id, cfg.work_dir)


def _save_measured(conn, cand: tdb.AlignmentCandidate, m: align.Measurement, counts: dict) -> None:
    tdb.save_alignment(conn, cand, method_version=align.ALIGN_METHOD_VERSION,
                       status=m.status, reason=m.reason, measurement=m)
    conn.commit()
    counts[m.status] += 1
    log.info("measure meeting %s clip %s video %s: %s",
             cand.meeting_id, cand.external_id, cand.video_id, align.describe(m))


def _save_failed(conn, cand: tdb.AlignmentCandidate, error: BaseException, counts: dict) -> None:
    reason = _reason(error)
    tdb.save_alignment(conn, cand, method_version=align.ALIGN_METHOD_VERSION,
                       status="failed", reason=reason)
    conn.commit()
    counts["failed"] += 1
    log.warning("measure meeting %s clip %s video %s: failed (%s)",
                cand.meeting_id, cand.external_id, cand.video_id, _one_line(reason))


def _run(conn, cfg, counts: dict, *, limit: int, stop, deadline, clock, sleep) -> None:
    candidates = tdb.alignment_candidates(conn, method_version=align.ALIGN_METHOD_VERSION, limit=limit)
    conn.rollback()                      # read-only; end the transaction before the downloads

    # Meeting by meeting, in the order each meeting first appears: a meeting's recordings are
    # not always adjacent (a retried failure sorts after the never-measured), and its Granicus
    # audio is fetched once for all of them.
    by_meeting: dict[int, list[tdb.AlignmentCandidate]] = {}
    for cand in candidates:
        by_meeting.setdefault(cand.meeting_id, []).append(cand)

    failures = 0                         # failed fetches in a row
    ended = None                         # why the pass ended early
    for group in by_meeting.values():
        ended = _halt(stop, deadline, clock)
        if ended:
            break
        granicus_wav = Path(cfg.work_dir) / f"align-{group[0].meeting_id}.wav"
        try:
            try:
                granicus = _granicus_features(cfg, group[0], granicus_wav, sleep)
            except psycopg2.Error:
                raise
            except Exception as e:  # noqa: BLE001 — one clip's failure is its recordings' failed rows
                for cand in group:
                    _save_failed(conn, cand, e, counts)
                failures += 1            # one failed fetch, however many recordings it had
            else:
                for cand in group:
                    ended = _halt(stop, deadline, clock)
                    if ended:
                        break
                    try:
                        measurement = _measure_recording(cfg, cand, granicus)
                    except psycopg2.Error:
                        raise
                    except Exception as e:  # noqa: BLE001 — any failure here is this recording's alone
                        _save_failed(conn, cand, e, counts)
                        failures += 1
                    else:
                        _save_measured(conn, cand, measurement, counts)
                        failures = 0
                    if failures >= MEASURE_MAX_CONSECUTIVE_FAILURES:
                        break
        finally:
            granicus_wav.unlink(missing_ok=True)
        if ended:
            break
        if failures >= MEASURE_MAX_CONSECUTIVE_FAILURES:
            log.warning("measure: %d fetches failed in a row; stopping", failures)
            break
    if ended:
        log.info("measure: %s; stopping", ended)

    remaining = tdb.alignment_backlog(conn, method_version=align.ALIGN_METHOD_VERSION)
    conn.rollback()
    log.info("measure done %s remaining=%s", counts, remaining)


def measure_pass(conn, cfg, *, limit: int, stop=None, deadline: float | None = None,
                 clock=time.monotonic, sleep=time.sleep) -> dict:
    """Measure up to ``limit`` attached YouTube recordings; returns how many ended
    ``passed``, ``rejected``, and ``failed``.

    ``cfg`` supplies ``work_dir`` and ``archive_dir``. ``stop`` is an object whose
    ``requested`` turns true on Ctrl-C and ``deadline`` a reading of ``clock`` (the run's
    ``--max-hours``); either is honoured before each recording. A limit of 0 or less reads
    nothing. No exception leaves this function except KeyboardInterrupt and its kind: the
    connection is rolled back, one warning is logged, and the counts so far are returned.
    """
    counts = {"passed": 0, "rejected": 0, "failed": 0}
    if limit <= 0:
        return counts
    try:
        _run(conn, cfg, counts, limit=limit, stop=stop, deadline=deadline, clock=clock, sleep=sleep)
    except Exception as e:  # noqa: BLE001 — nothing the pass meets may keep the run from transcribing
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001 — a dead connection is the loop's to report
            pass
        # a database error's own text names the missing table or grant; anything else needs its class
        log.warning("measure: skipped (%s)", _one_line(e if isinstance(e, psycopg2.Error) else _reason(e)))
    return counts
