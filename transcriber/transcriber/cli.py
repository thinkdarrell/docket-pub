"""Desktop producer entry point.

    python -m transcriber.cli --since 2025-10-28 --limit 5 --max-hours 3
    python -m transcriber.cli --dry-run /archive/clips/item15.mp4   # no DB, CPU ok

Per meeting: claim -> fetch audio -> transcribe -> diarize -> write JSON
(status transcribed) -> upload (status uploaded) -> delete audio. Ctrl-C
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
from .audio import AudioFetchError, download_url_for, fetch_audio, probe_duration, sha256_file
from .contract import TranscriptOutput
from .engine import Engine, build_output, is_low_speech, speech_seconds
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


def _upload_or_fail(conn, claim: tdb.Claim, out: TranscriptOutput) -> str:
    try:
        tdb.upload(conn, out)
        conn.commit()
    except Exception as e:  # noqa: BLE001 — an upload error is a per-meeting failure
        log.exception("upload failed for meeting %s", claim.meeting_id)
        conn.rollback()
        tdb.mark_status(conn, claim.transcript_id, "failed", error=f"upload: {type(e).__name__}: {e}")
        conn.commit()
        return "failed"
    return "uploaded"


def process_claim(conn, engine: Engine, claim: tdb.Claim, cfg: Config) -> str:
    json_path = _archive_path(cfg, claim.meeting_id)
    if claim.status == "transcribed" and json_path.exists():
        out = TranscriptOutput.from_json(json_path.read_text())
        return _upload_or_fail(conn, claim, out)

    wav = cfg.work_dir / f"{claim.meeting_id}.wav"
    source = download_url_for(claim.external_id)
    try:
        fetch_audio(source, wav)
        duration = probe_duration(str(wav))
        sha = sha256_file(wav)
        tdb.mark_status(conn, claim.transcript_id, "audio_fetched",
                        audio_sha256=sha, audio_duration_s=duration)
        conn.commit()
    except (AudioFetchError, subprocess.TimeoutExpired) as e:
        conn.rollback()
        tdb.mark_status(conn, claim.transcript_id, "failed", error=str(e))
        conn.commit()
        wav.unlink(missing_ok=True)
        return "failed"

    try:
        roster = tdb.roster_for_meeting(conn, claim.meeting_id)
        try:
            prompt = build_initial_prompt(roster)
        except PromptBudgetError as e:
            log.warning("prompt budget: %s; using vocabulary only", e)
            prompt = build_initial_prompt([])
        raw = engine.transcribe(wav, prompt)
        sp_s = speech_seconds(raw)
        if is_low_speech(sp_s):
            tdb.mark_status(conn, claim.transcript_id, "low_speech",
                            error=f"{sp_s:.0f}s of speech detected", speech_ratio=sp_s / max(duration, 1))
            conn.commit()
            return "low_speech"
        turns, emb = engine.diarize(wav)
        words_path = None
        if getattr(engine, "last_words", None):
            import json
            wp = json_path.with_name("words.json")
            wp.parent.mkdir(parents=True, exist_ok=True)
            wp.write_text(json.dumps(engine.last_words))
            words_path = str(wp)
        out = build_output(claim.meeting_id, 1, engine, raw, turns, emb, duration, sha, words_path)
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
        tdb.mark_status(conn, claim.transcript_id, "failed", error=f"{type(e).__name__}: {e}")
        conn.commit()
        return "failed"
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
    for _ in range(cfg.limit):
        if stop.requested:
            break
        if cfg.max_hours is not None and (clock() - started) > cfg.max_hours * 3600:
            log.info("max-hours reached; stopping")
            break
        claim = tdb.claim_next(conn, since=cfg.since, host=cfg.host)
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
    raw = engine.transcribe(wav, build_initial_prompt([]))
    turns, emb = engine.diarize(wav)
    out = build_output(0, 1, engine, raw, turns, emb, duration, sha256_file(wav), None)
    path = cfg.archive_dir / "dry_run" / (Path(source).stem + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(out.to_json())
    wav.unlink(missing_ok=True)
    return path


def main(argv=None) -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description="docket.pub transcript producer")
    ap.add_argument("--since", default=os.environ.get("TRANSCRIBER_SINCE", "2025-10-28"))
    ap.add_argument("--limit", type=int, default=int(os.environ.get("TRANSCRIBER_LIMIT", "100")))
    ap.add_argument("--max-hours", type=float, default=None)
    ap.add_argument("--dry-run", metavar="FILE_OR_URL", default=None)
    ap.add_argument("--max-consecutive-failures", type=int,
                    default=int(os.environ.get("TRANSCRIBER_MAX_CONSECUTIVE_FAILURES", "5")))
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
    )
    cfg.work_dir.mkdir(parents=True, exist_ok=True)

    from .engine import FasterWhisperEngine
    engine = FasterWhisperEngine(model_size=args.model, device=args.device,
                                 compute_type=args.compute_type,
                                 hf_token=os.environ.get("HF_TOKEN"))

    if args.dry_run:
        print(dry_run(engine, args.dry_run, cfg))
        return 0

    url = os.environ.get("TRANSCRIBER_DATABASE_URL")
    if not url:
        ap.error("TRANSCRIBER_DATABASE_URL is not set")
    if "sslmode=require" not in url:
        ap.error("TRANSCRIBER_DATABASE_URL must include sslmode=require")
    conn = tdb.connect(url)
    try:
        counts = run_loop(conn, engine, cfg)
    finally:
        conn.close()
    log.info("done %s oom_fallbacks=%s", counts, getattr(engine, "oom_fallbacks", 0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
