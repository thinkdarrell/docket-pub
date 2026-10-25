"""Desktop producer entry point.

    python -m transcriber.cli --since 2025-10-28 --limit 5 --max-hours 3
    python -m transcriber.cli --dry-run /archive/clips/item15.mp4   # no DB, CPU ok
    python -m transcriber.cli --meeting-id 2543                     # re-run one meeting
    python -m transcriber.cli --cache-audio 2543 1 2                # keep audio.flac, no GPU
    python -m transcriber.cli --capture-inputs 2543                 # raw.json + diarization.json, no DB writes
    python -m transcriber.cli --replay 2543                         # replay.json from saved inputs, CPU only

Per meeting: claim -> fetch audio (or decode the archive's audio.flac, keeping a
copy when fetched) -> transcribe (raw.json) -> diarize (diarization.json) -> write
JSON (status transcribed) -> upload (status uploaded) -> delete the work WAV. Ctrl-C
finishes the current meeting and exits.
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import subprocess
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from . import __version__
from . import db as tdb
from . import inputs
from .inputs import get_audio
from .audio import (AudioFetchError, fetch_audio, probe_duration, remove_downloads, sha256_file,
                    source_for)
from .contract import TranscriptOutput
from .engine import (TRANSCRIPT_VERSION, Engine, build_output, clean_segments, is_low_speech,
                     speech_seconds)
from .prompt import PromptBudgetError, build_initial_prompt

log = logging.getLogger("transcriber")


@dataclass
class Config:
    since: date
    limit: int
    max_hours: float | None
    host: str
    work_dir: Path
    archive_dir: Path
    dry_run_file: str | None
    version: str
    max_consecutive_failures: int = 5
    retry_failed: bool = False
    meeting_id: int | None = None       # --meeting-id: re-transcribe this one meeting and stop


class _Stop:
    def __init__(self):
        self.requested = False
        signal.signal(signal.SIGINT, self._on)
        signal.signal(signal.SIGTERM, self._on)

    def _on(self, *_):
        log.warning("stop requested; finishing current meeting")
        self.requested = True


def _archive_path(cfg: Config, meeting_id: int) -> Path:
    return cfg.archive_dir / str(meeting_id) / "transcript.json"


def _end_without_upload(conn, claim: tdb.Claim, status: str, *, error: str | None = None, **fields) -> str:
    """A failed or low_speech end. A re-run of an uploaded meeting (claim.prior set) puts the
    row back as it was before the claim, so the old transcript is as visible as it was (public,
    or hidden when the row rested at low_speech, decision 0050) and the Railway side never sees
    a producer failure with uploaded_at set; the reason goes to the log."""
    if claim.prior is not None:
        tdb.restore_row(conn, claim.transcript_id, claim.prior)
        log.warning("meeting %s re-run ended %s (%s); transcripts row restored to its pre-claim values",
                    claim.meeting_id, status, error)
    else:
        tdb.mark_status(conn, claim.transcript_id, status, error=error, **fields)
    conn.commit()
    return status


def _upload_or_fail(conn, claim: tdb.Claim, out: TranscriptOutput) -> str:
    try:
        tdb.upload(conn, out)
        conn.commit()
    except Exception as e:  # noqa: BLE001 — an upload error is a per-meeting failure
        log.exception("upload failed for meeting %s", claim.meeting_id)
        conn.rollback()
        return _end_without_upload(conn, claim, "failed", error=f"upload: {type(e).__name__}: {e}")
    return "uploaded"


def _fetch_for(external_id: str, work_dir: Path):
    """The ``fetch`` that get_audio calls only when the archive holds no audio.flac: it
    resolves the meeting's source then (a ``yt-`` id downloads its recording through
    yt-dlp, which a cached FLAC spares) and reads it with fetch_audio."""
    def fetch(_source, wav):
        return fetch_audio(source_for(external_id, work_dir), wav)
    return fetch


def process_claim(conn, engine: Engine, claim: tdb.Claim, cfg: Config) -> str:
    json_path = _archive_path(cfg, claim.meeting_id)
    if claim.status == "transcribed" and json_path.exists():
        out = TranscriptOutput.from_json(json_path.read_text())
        return _upload_or_fail(conn, claim, out)

    wav = cfg.work_dir / f"{claim.meeting_id}.wav"
    try:
        if get_audio(claim.external_id, wav, inputs.audio_path(cfg.archive_dir, claim.meeting_id),
                     fetch=_fetch_for(claim.external_id, cfg.work_dir)):
            log.info("meeting %s: audio from the archive's audio.flac", claim.meeting_id)
        duration = probe_duration(str(wav))
        sha = sha256_file(wav)
        tdb.mark_status(conn, claim.transcript_id, "audio_fetched",
                        audio_sha256=sha, audio_duration_s=duration)
        conn.commit()
    except (AudioFetchError, subprocess.TimeoutExpired) as e:
        conn.rollback()
        _end_without_upload(conn, claim, "failed", error=str(e))
        wav.unlink(missing_ok=True)
        remove_downloads(claim.external_id, cfg.work_dir)
        return "failed"
    remove_downloads(claim.external_id, cfg.work_dir)   # the wav is all the rest of the run reads

    try:
        roster = tdb.roster_for_meeting(conn, claim.meeting_id)
        try:
            prompt = build_initial_prompt(roster)
        except PromptBudgetError as e:
            log.warning("prompt budget: %s; using vocabulary only", e)
            prompt = build_initial_prompt([])
        raw = engine.transcribe(wav, prompt)
        inputs.write_raw(inputs.raw_path(cfg.archive_dir, claim.meeting_id), raw, meeting_id=claim.meeting_id,
                         initial_prompt=prompt, audio_duration_s=duration, audio_sha256=sha, engine=engine)
        raw, dropped = clean_segments(raw, prompt)
        log.info("meeting %s: dropped %s", claim.meeting_id, dropped)
        sp_s = speech_seconds(raw)
        if is_low_speech(sp_s):
            return _end_without_upload(conn, claim, "low_speech", error=f"{sp_s:.0f}s of speech detected",
                                       speech_ratio=sp_s / max(duration, 1))
        turns, emb = engine.diarize(wav)
        inputs.write_diarization(inputs.diarization_path(cfg.archive_dir, claim.meeting_id), turns, emb)
        words_path = None
        if getattr(engine, "last_words", None):
            import json
            wp = json_path.with_name("words.json")
            wp.parent.mkdir(parents=True, exist_ok=True)
            wp.write_text(json.dumps(engine.last_words))
            words_path = str(wp)
        out = build_output(claim.meeting_id, TRANSCRIPT_VERSION, engine, raw, turns, emb, duration, sha,
                           words_path, initial_prompt=prompt)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(out.to_json())
        tdb.mark_status(conn, claim.transcript_id, "transcribed", raw_output_path=str(json_path),
                        speech_ratio=out.speech_ratio, word_count=out.word_count,
                        engine=engine.name, asr_model=engine.asr_model,
                        diarization_model=engine.diarization_model)
        conn.commit()
    except Exception as e:  # noqa: BLE001 — any GPU/model failure is a per-meeting failure
        conn.rollback()
        log.exception("meeting %s failed", claim.meeting_id)
        return _end_without_upload(conn, claim, "failed", error=f"{type(e).__name__}: {e}")
    finally:
        wav.unlink(missing_ok=True)

    return _upload_or_fail(conn, claim, out)


def run_loop(conn, engine: Engine, cfg: Config, *, clock=time.monotonic, stop_flag=None) -> dict:
    counts = {"uploaded": 0, "failed": 0, "low_speech": 0}
    started = clock()
    consecutive_failures = 0
    stop = stop_flag or _Stop()
    tdb.heartbeat(conn, cfg.host, "started", None, cfg.version)
    conn.commit()
    for _ in range(1 if cfg.meeting_id is not None else cfg.limit):
        if stop.requested:
            break
        if cfg.max_hours is not None and (clock() - started) > cfg.max_hours * 3600:
            log.info("max-hours reached; stopping")
            break
        if cfg.meeting_id is not None:
            try:
                claim = tdb.claim_meeting(conn, meeting_id=cfg.meeting_id, host=cfg.host)
            except tdb.MeetingBusy as e:
                conn.rollback()
                log.error("meeting %s was touched at %s; wait 30 minutes", e.meeting_id, e.touched_at)
                break
            conn.commit()
            if claim is None:
                log.error("meeting %s is not an eligible Birmingham meeting", cfg.meeting_id)
                break
        else:
            claim = tdb.claim_next(conn, since=cfg.since, host=cfg.host, retry_failed=cfg.retry_failed)
            conn.commit()
            if claim is None:
                log.info("nothing to claim")
                break
        tdb.heartbeat(conn, cfg.host, "processing", claim.meeting_id, cfg.version)
        conn.commit()
        log.info("meeting %s (%s) %s", claim.meeting_id, claim.meeting_date, claim.title)
        status = process_claim(conn, engine, claim, cfg)
        counts[status] += 1
        tdb.heartbeat(conn, cfg.host, status, claim.meeting_id, cfg.version)
        conn.commit()
        consecutive_failures = consecutive_failures + 1 if status == "failed" else 0
        if consecutive_failures >= cfg.max_consecutive_failures:
            log.warning("%d consecutive failures; stopping", consecutive_failures)
            break
    tdb.heartbeat(conn, cfg.host, "exited", None, cfg.version)
    conn.commit()
    return counts


def dry_run(engine: Engine, source: str, cfg: Config) -> Path:
    """Transcribe one local file or URL to JSON without touching the database."""
    wav = cfg.work_dir / "dry_run.wav"
    fetch_audio(source, wav)
    duration = probe_duration(str(wav))
    prompt = build_initial_prompt([])
    raw = engine.transcribe(wav, prompt)
    turns, emb = engine.diarize(wav)
    out = build_output(0, TRANSCRIPT_VERSION, engine, raw, turns, emb, duration, sha256_file(wav), None,
                       initial_prompt=prompt)
    path = cfg.archive_dir / "dry_run" / (Path(source).stem + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(out.to_json())
    wav.unlink(missing_ok=True)
    return path


def cache_audio(conn, cfg: Config, meeting_id: int) -> str:
    """Download one meeting's audio into the archive as audio.flac. No GPU, no database write."""
    flac = inputs.audio_path(cfg.archive_dir, meeting_id)
    if flac.exists():
        return "cached"
    external_id = tdb.meeting_source(conn, meeting_id)
    if external_id is None:
        log.error("meeting %s is not an eligible Birmingham meeting", meeting_id)
        return "ineligible"
    wav = cfg.work_dir / f"{meeting_id}.wav"
    try:
        fetch_audio(source_for(external_id, cfg.work_dir), wav)
        inputs.store_flac(wav, flac)
    except (AudioFetchError, OSError, subprocess.TimeoutExpired) as e:
        log.error("meeting %s: %s", meeting_id, e)
        return "failed"
    finally:
        wav.unlink(missing_ok=True)
        remove_downloads(external_id, cfg.work_dir)
    return "fetched"


def capture_inputs(conn, engine: Engine, cfg: Config, meeting_id: int) -> str:
    """Run speech recognition and diarization on one meeting and write raw.json and
    diarization.json to its archive folder, without claiming, uploading, or writing to the
    database. Audio comes from audio.flac when present (fetched and kept otherwise)."""
    external_id = tdb.meeting_source(conn, meeting_id)
    if external_id is None:
        log.error("meeting %s is not an eligible Birmingham meeting", meeting_id)
        return "ineligible"
    wav = cfg.work_dir / f"{meeting_id}.wav"
    try:
        get_audio(external_id, wav, inputs.audio_path(cfg.archive_dir, meeting_id),
                  fetch=_fetch_for(external_id, cfg.work_dir))
        duration = probe_duration(str(wav))
        sha = sha256_file(wav)
        try:
            prompt = build_initial_prompt(tdb.roster_for_meeting(conn, meeting_id))
        except PromptBudgetError:
            prompt = build_initial_prompt([])
        conn.rollback()  # read-only; end the transaction before the long GPU work
        raw = engine.transcribe(wav, prompt)
        inputs.write_raw(inputs.raw_path(cfg.archive_dir, meeting_id), raw, meeting_id=meeting_id,
                         initial_prompt=prompt, audio_duration_s=duration, audio_sha256=sha, engine=engine)
        turns, emb = engine.diarize(wav)
        inputs.write_diarization(inputs.diarization_path(cfg.archive_dir, meeting_id), turns, emb)
    except Exception:  # noqa: BLE001 — one meeting's failure does not stop the pass
        log.exception("meeting %s capture failed", meeting_id)
        return "failed"
    finally:
        wav.unlink(missing_ok=True)
        remove_downloads(external_id, cfg.work_dir)
    return "captured"


def replay_meeting(cfg: Config, meeting_id: int) -> Path:
    """build_output() over the archived raw.json and diarization.json; writes replay.json beside
    transcript.json (never over it). CPU only; no audio, model, or database."""
    out = inputs.replay(cfg.archive_dir, meeting_id, TRANSCRIPT_VERSION)
    path = cfg.archive_dir / str(meeting_id) / "replay.json"
    path.write_text(out.to_json())
    speech = [s for s in out.segments if not s.is_silence]
    log.info("meeting %s: replayed %d segments, %d speakers -> %s",
             meeting_id, len(speech), len(out.speakers), path)
    return path


def exit_code(counts: dict, meeting_id: int | None) -> int:
    """--meeting-id promises one upload; anything else, not eligible, busy, failed, or low_speech, is exit 1."""
    return 1 if meeting_id is not None and counts["uploaded"] == 0 else 0


def main(argv=None) -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description="docket.pub transcript producer")
    ap.add_argument("--since", default=os.environ.get("TRANSCRIBER_SINCE", "2025-10-28"))
    ap.add_argument("--limit", type=int, default=int(os.environ.get("TRANSCRIBER_LIMIT", "100")))
    ap.add_argument("--max-hours", type=float, default=None)
    ap.add_argument("--dry-run", metavar="FILE_OR_URL", default=None)
    ap.add_argument("--max-consecutive-failures", type=int,
                    default=int(os.environ.get("TRANSCRIBER_MAX_CONSECUTIVE_FAILURES", "5")))
    ap.add_argument("--retry-failed", action="store_true",
                    default=os.environ.get("TRANSCRIBER_RETRY_FAILED", "").lower() in ("1", "true", "yes"),
                    help="re-queue meetings marked failed")
    ap.add_argument("--meeting-id", type=int, default=None,
                    help="re-transcribe this one meeting, whatever its status; ignores --since and --limit")
    modes = ap.add_mutually_exclusive_group()
    modes.add_argument("--cache-audio", type=int, nargs="+", metavar="MEETING_ID",
                       help="download these meetings' audio into the archive as audio.flac; no GPU, no DB writes")
    modes.add_argument("--capture-inputs", type=int, nargs="+", metavar="MEETING_ID",
                       help="write raw.json and diarization.json for these meetings; no claim, upload, or DB writes")
    modes.add_argument("--replay", type=int, nargs="+", metavar="MEETING_ID",
                       help="rebuild replay.json from the archived inputs on the CPU; no audio, GPU, or DB")
    ap.add_argument("--model", default=os.environ.get("TRANSCRIBER_MODEL", "large-v3"))
    ap.add_argument("--device", default=os.environ.get("TRANSCRIBER_DEVICE", "cuda"))
    ap.add_argument("--compute-type", default=os.environ.get("TRANSCRIBER_COMPUTE", "float16"))
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config(
        since=date.fromisoformat(args.since), limit=args.limit, max_hours=args.max_hours,
        host=os.environ.get("TRANSCRIBER_HOST", socket.gethostname()),
        work_dir=Path(os.environ.get("TRANSCRIBER_WORK_DIR", "/archive/work")),
        archive_dir=Path(os.environ.get("TRANSCRIBER_ARCHIVE_DIR", "/archive/transcripts")),
        dry_run_file=args.dry_run, version=__version__,
        max_consecutive_failures=args.max_consecutive_failures,
        retry_failed=args.retry_failed, meeting_id=args.meeting_id,
    )
    cfg.work_dir.mkdir(parents=True, exist_ok=True)

    if args.replay:
        failed = 0
        for mid in args.replay:
            try:
                replay_meeting(cfg, mid)
            except (OSError, KeyError, ValueError) as e:
                log.error("meeting %s: cannot replay (%s)", mid, e)
                failed += 1
        log.info("replay done: %d ok, %d failed", len(args.replay) - failed, failed)
        return 1 if failed else 0

    url = os.environ.get("TRANSCRIBER_DATABASE_URL")
    if not args.dry_run:
        if not url:
            ap.error("TRANSCRIBER_DATABASE_URL is not set")
        if "sslmode=require" not in url:
            ap.error("TRANSCRIBER_DATABASE_URL must include sslmode=require")

    if args.cache_audio:
        conn = tdb.connect(url)
        try:
            results = {mid: cache_audio(conn, cfg, mid) for mid in args.cache_audio}
        finally:
            conn.close()
        log.info("cache-audio done %s", results)
        return 1 if any(r in ("failed", "ineligible") for r in results.values()) else 0

    from .engine import FasterWhisperEngine
    engine = FasterWhisperEngine(model_size=args.model, device=args.device,
                                 compute_type=args.compute_type,
                                 hf_token=os.environ.get("HF_TOKEN"))

    if args.dry_run:
        print(dry_run(engine, args.dry_run, cfg))
        return 0

    if args.capture_inputs:
        conn = tdb.connect(url)
        try:
            results = {mid: capture_inputs(conn, engine, cfg, mid) for mid in args.capture_inputs}
        finally:
            conn.close()
        log.info("capture-inputs done %s oom_fallbacks=%s", results, getattr(engine, "oom_fallbacks", 0))
        return 1 if any(r != "captured" for r in results.values()) else 0

    conn = tdb.connect(url)
    try:
        counts = run_loop(conn, engine, cfg)
    finally:
        conn.close()
    log.info("done %s oom_fallbacks=%s", counts, getattr(engine, "oom_fallbacks", 0))
    return exit_code(counts, args.meeting_id)


if __name__ == "__main__":
    raise SystemExit(main())
