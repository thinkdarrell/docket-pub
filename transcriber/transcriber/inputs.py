"""The archive's copy of what the GPU stages consumed and produced, so a later run can skip them.

Per meeting, beside transcript.json under the archive folder:

    audio.flac        the 16 kHz mono audio, lossless; a re-run decodes it instead of
                      downloading from Granicus again
    raw.json          Whisper's chunks before cleaning (text, avg_logprob, no_speech_prob,
                      word timestamps) plus the prompt, duration, sha and model names
    diarization.json  pyannote's turns and per-cluster embeddings

raw.json and diarization.json are what build_output() takes, so a post-processing change
can be replayed on every archived meeting on the CPU (``--replay``), with no download and
no GPU. Nothing here is uploaded; migration 035 keeps word timestamps out of Postgres.
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from .audio import AudioFetchError, fetch_audio
from .engine import DiarTurn, RawSegment, Word

log = logging.getLogger(__name__)

INPUTS_VERSION = 1


def audio_path(archive_dir: Path, meeting_id: int) -> Path:
    return archive_dir / str(meeting_id) / "audio.flac"


def raw_path(archive_dir: Path, meeting_id: int) -> Path:
    return archive_dir / str(meeting_id) / "raw.json"


def diarization_path(archive_dir: Path, meeting_id: int) -> Path:
    return archive_dir / str(meeting_id) / "diarization.json"


def _ffmpeg(args: list[str], runner, timeout_s: int) -> None:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args]
    proc = runner(cmd, capture_output=True, text=True, timeout=timeout_s)
    if proc.returncode != 0:
        raise AudioFetchError(f"ffmpeg {' '.join(args[:2])}: {proc.stderr.strip() or proc.returncode}")


def store_flac(wav: Path, flac: Path, *, runner=subprocess.run, timeout_s: int = 1800) -> Path:
    """Encode the work WAV to FLAC beside the transcript; written to a temp name and renamed,
    so an interrupted encode never leaves a truncated audio.flac that a later run would trust."""
    flac.parent.mkdir(parents=True, exist_ok=True)
    tmp = flac.with_name(flac.name + ".part")
    _ffmpeg(["-i", str(wav), "-c:a", "flac", "-f", "flac", str(tmp)], runner, timeout_s)
    tmp.replace(flac)
    return flac


def get_audio(source: str, wav: Path, flac: Path, *, fetch=fetch_audio,
              runner=subprocess.run, timeout_s: int = 1800) -> bool:
    """Put the meeting's 16 kHz mono PCM WAV at ``wav``. Decode audio.flac when it exists,
    otherwise fetch from ``source`` and keep a FLAC copy. Returns True when the cache served it.

    A cached FLAC that fails to decode is deleted and the audio fetched again; a FLAC that
    cannot be written is logged and skipped. Only the fetch itself can raise."""
    if flac.exists():
        try:
            wav.parent.mkdir(parents=True, exist_ok=True)
            _ffmpeg(["-i", str(flac), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)],
                    runner, timeout_s)
            return True
        except (AudioFetchError, OSError, subprocess.TimeoutExpired) as e:
            log.warning("cached %s unreadable (%s); fetching again", flac, e)
            flac.unlink(missing_ok=True)
    fetch(source, wav)
    try:
        store_flac(wav, flac, runner=runner, timeout_s=timeout_s)
    except (AudioFetchError, OSError, subprocess.TimeoutExpired) as e:
        # the cache is a convenience; a meeting never fails because its copy could not be kept
        log.warning("could not keep %s (%s)", flac, e)
    return False


def write_raw(path: Path, raw: list[RawSegment], *, meeting_id: int, initial_prompt: str,
              audio_duration_s: float, audio_sha256: str, engine) -> None:
    doc = {
        "inputs_version": INPUTS_VERSION, "meeting_id": meeting_id,
        "engine": engine.name, "asr_model": engine.asr_model,
        "diarization_model": getattr(engine, "diarization_model", None),
        "initial_prompt": initial_prompt, "audio_duration_s": audio_duration_s,
        "audio_sha256": audio_sha256,
        "chunks": [{"s": r.start_s, "e": r.end_s, "text": r.text, "lp": r.avg_logprob,
                    "nsp": r.no_speech_prob,
                    "words": [{"s": w.start_s, "e": w.end_s, "w": w.text, "p": w.probability}
                              for w in r.words]} for r in raw],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))


def read_raw(path: Path) -> tuple[dict, list[RawSegment]]:
    doc = json.loads(path.read_text())
    raw = [RawSegment(c["s"], c["e"], c["text"], c["lp"], c["nsp"],
                      words=[Word(w["s"], w["e"], w["w"], w["p"]) for w in c["words"]])
           for c in doc.pop("chunks")]
    return doc, raw


def write_diarization(path: Path, turns: list[DiarTurn], embeddings: dict[str, list[float]]) -> None:
    doc = {"inputs_version": INPUTS_VERSION,
           "turns": [{"s": t.start_s, "e": t.end_s, "label": t.label} for t in turns],
           "embeddings": embeddings}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))


def read_diarization(path: Path) -> tuple[list[DiarTurn], dict[str, list[float]]]:
    doc = json.loads(path.read_text())
    return [DiarTurn(t["s"], t["e"], t["label"]) for t in doc["turns"]], doc["embeddings"]


class _ReplayEngine:
    """The model names build_output() stamps on the output, taken from raw.json."""
    def __init__(self, meta: dict):
        self.name = meta["engine"]
        self.asr_model = meta["asr_model"]
        self.diarization_model = meta["diarization_model"]


def replay(archive_dir: Path, meeting_id: int, version: int):
    """build_output() over the archived inputs of one meeting; no audio, GPU, or database."""
    from .engine import build_output
    meta, raw = read_raw(raw_path(archive_dir, meeting_id))
    turns, emb = read_diarization(diarization_path(archive_dir, meeting_id))
    return build_output(meeting_id, version, _ReplayEngine(meta), raw, turns, emb,
                        meta["audio_duration_s"], meta["audio_sha256"], None,
                        initial_prompt=meta["initial_prompt"])
