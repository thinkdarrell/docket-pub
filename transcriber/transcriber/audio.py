"""Pull 16 kHz mono audio from a Granicus clip (or a local file) with ffmpeg.

Granicus serves archive video through CloudFront, which answers 403 to
non-browser user agents. Same constant and same download endpoint as the
OCR pipeline in the main repo (src/docket/analysis/ocr/frame_io.py and
src/docket/services/video_ocr.py). Audio only: we never keep video.
"""
from __future__ import annotations

import hashlib
import subprocess
import time
from pathlib import Path

GRANICUS_DOWNLOAD_URL = "https://bhamal.granicus.com/DownloadFile.php?view_id=2"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class AudioFetchError(RuntimeError):
    """ffmpeg could not produce audio; message carries ffmpeg's stderr."""


def download_url_for(external_id: str) -> str:
    return f"{GRANICUS_DOWNLOAD_URL}&clip_id={external_id}"


def _is_http(src: str) -> bool:
    return src.lower().startswith(("http://", "https://"))


def _ua_args(src: str) -> list[str]:
    return ["-user_agent", BROWSER_USER_AGENT] if _is_http(src) else []


def probe_duration(source: str, runner=subprocess.run, timeout_s: int = 120) -> float:
    cmd = ["ffprobe", *_ua_args(source), "-v", "error", "-show_entries",
           "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", source]
    proc = runner(cmd, capture_output=True, text=True, timeout=timeout_s)
    if proc.returncode != 0:
        raise AudioFetchError(f"ffprobe failed: {proc.stderr.strip() or 'no output'}")
    try:
        return float(proc.stdout.strip().splitlines()[0])
    except (IndexError, ValueError):
        raise AudioFetchError(f"ffprobe gave no duration: {proc.stdout!r}") from None


def fetch_audio(
    source: str,
    out_wav: Path,
    *,
    attempts: int = 3,
    delay_s: float = 5.0,
    timeout_s: int = 3600,
    runner=subprocess.run,
) -> Path:
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *_ua_args(source),
           "-i", source, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
           str(out_wav)]
    last_err = ""
    for i in range(attempts):
        proc = runner(cmd, capture_output=True, text=True, timeout=timeout_s)
        if proc.returncode == 0 and out_wav.exists() and out_wav.stat().st_size > 44:
            return out_wav
        last_err = proc.stderr.strip() or f"exit {proc.returncode}"
        if i < attempts - 1:
            time.sleep(delay_s)
    raise AudioFetchError(f"ffmpeg could not read {source}: {last_err}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
