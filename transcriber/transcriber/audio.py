"""Pull 16 kHz mono audio from a Granicus clip, a YouTube recording, or a local file with ffmpeg.

Granicus serves archive video through CloudFront, which answers 403 to
non-browser user agents. Same constant and same download endpoint as the
OCR pipeline in the main repo (src/docket/analysis/ocr/frame_io.py and
src/docket/services/video_ocr.py). Audio only: we never keep video.

A meeting whose only recording is on the council's YouTube channel carries the
external id ``yt-<video id>``. ffmpeg cannot read a YouTube page, so
``source_for`` first downloads that video's best audio track with yt-dlp into the
work directory and hands ffmpeg the file. The caller removes ``<work_dir>/<id>.*``
afterwards, since yt-dlp chooses the extension.
"""
from __future__ import annotations

import hashlib
import os
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


YOUTUBE_WATCH_URL = "https://www.youtube.com/watch?v="
YOUTUBE_PREFIX = "yt-"
# yt-dlp's own scratch files, never the finished download
_PARTIAL_SUFFIXES = (".part", ".ytdl", ".temp")


def ytdlp_options(external_id: str, work_dir: Path) -> dict:
    """yt-dlp options for one download. TRANSCRIBER_YTDLP_COOKIES names a Netscape-format
    cookie file exported from a signed-in browser, for when YouTube asks this address to
    sign in; unset, no cookies are sent."""
    opts = {"format": "bestaudio/best", "outtmpl": str(Path(work_dir) / f"{external_id}.%(ext)s"),
            "quiet": True, "noplaylist": True}
    cookies = os.environ.get("TRANSCRIBER_YTDLP_COOKIES")
    if cookies:
        opts["cookiefile"] = cookies
    return opts


def source_for(external_id: str, work_dir: Path) -> str:
    """What ffmpeg reads for a meeting: the Granicus download URL for a clip id, or, for a
    ``yt-`` id, the path of the recording's audio downloaded into ``work_dir`` by yt-dlp.
    Raises AudioFetchError when yt-dlp cannot download it."""
    if not external_id.startswith(YOUTUBE_PREFIX):
        return download_url_for(external_id)
    try:
        import yt_dlp  # only the transcriber image carries it; Granicus clips never need it
    except ImportError as e:  # an image built before yt-dlp was added: fail this meeting, not the run
        raise AudioFetchError(f"{e}; rebuild the transcriber image") from None

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    url = YOUTUBE_WATCH_URL + external_id[len(YOUTUBE_PREFIX):]
    try:
        with yt_dlp.YoutubeDL(ytdlp_options(external_id, work_dir)) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as e:
        raise AudioFetchError(f"yt-dlp could not download {url}: {e}") from None
    files = sorted(p for p in work_dir.glob(f"{external_id}.*")
                   if p.suffix not in _PARTIAL_SUFFIXES and p.suffix != ".wav")
    if not files:
        raise AudioFetchError(f"yt-dlp wrote no file for {url}")
    return str(files[0])


def remove_downloads(external_id: str, work_dir: Path) -> None:
    """Delete what source_for downloaded for a ``yt-`` id (any extension, partials too)."""
    if external_id.startswith(YOUTUBE_PREFIX):
        for p in Path(work_dir).glob(f"{external_id}.*"):
            p.unlink(missing_ok=True)


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
