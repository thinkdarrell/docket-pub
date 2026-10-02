"""ffmpeg/ffprobe wrappers for the vote-scan pipeline.

Thin adapters around the ``ffmpeg`` and ``ffprobe`` binaries. Everything
here is pure IO: duration probing, frame extraction to a temp directory,
and streaming ``(timestamp, frame)`` tuples back to the caller. Higher
level sequence grouping lives in ``muni.analysis.vote_sequence``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

import cv2
import numpy as np

FrameWithTimestamp = tuple[float, np.ndarray]

# scan_full refuses to silently return a partial read when ffmpeg's HTTP
# stream truncates mid-download. Anything covering less than this fraction
# of the probed duration is treated as a failed scan.
_SCAN_COVERAGE_MIN_RATIO = 0.9


class IncompleteVideoScanError(RuntimeError):
    """Raised when a full-video scan covers far less than the probed duration."""


class VideoProbeError(RuntimeError):
    """Raised when ffprobe cannot read the video (the error carries ffprobe's stderr)."""


# Granicus serves archive video through CloudFront, which answers 403 to
# non-browser user agents (ffmpeg's "Lavf/…", "Python-urllib/…"). Observed
# 2026-10-02: every OCR scan since mid-June failed at the duration probe.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def _is_http(video_url: str) -> bool:
    return video_url.lower().startswith(("http://", "https://"))


def _ua_args(video_url: str) -> list[str]:
    """ffmpeg/ffprobe input options that identify as a browser for HTTP sources."""
    return ["-user_agent", BROWSER_USER_AGENT] if _is_http(video_url) else []


def probe_duration(video_url: str, timeout: int = 60) -> float:
    """Return the duration of a video (URL or local path) in seconds.

    Raises VideoProbeError, with ffprobe's own message, when the source
    can't be read (HTTP 403/404, truncated file, ...).
    """
    cmd = [
        "ffprobe",
        "-v",
        "error",
        *_ua_args(video_url),
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        video_url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    out = proc.stdout.strip()
    if proc.returncode != 0 or not out:
        raise VideoProbeError(
            f"ffprobe could not read {video_url}: {proc.stderr.strip() or 'no output'}"
        )
    return float(out)


def extract_frames_to_dir(
    video_url: str,
    out_dir: Path,
    *,
    fps_expression: str,
    pattern: str = "frame_%06d.png",
    start: float | None = None,
    duration: float | None = None,
    timeout: int = 600,
) -> list[Path]:
    """Run ffmpeg to dump frames into ``out_dir`` and return the sorted file list.

    ``fps_expression`` is whatever you'd pass to ffmpeg's ``-vf fps=...`` —
    e.g. ``"2"`` for 2 fps or ``"1/5"`` for one frame every 5 seconds.
    """
    cmd: list[str] = ["ffmpeg", *_ua_args(video_url)]
    if start is not None:
        cmd += ["-ss", str(start)]
    cmd += ["-i", video_url]
    if duration is not None:
        cmd += ["-t", str(duration)]
    cmd += [
        "-vf",
        f"fps={fps_expression}",
        str(out_dir / pattern),
        "-y",
        "-loglevel",
        "error",
    ]

    subprocess.run(cmd, check=True, timeout=timeout)
    return sorted(out_dir.glob(pattern.replace("%06d", "*").replace("%04d", "*")))


def iter_frames_from_dir(
    files: Iterable[Path], *, start: float = 0.0, step: float
) -> Iterator[FrameWithTimestamp]:
    """Read each file with ``cv2.imread`` and yield ``(timestamp, frame)``.

    Files are paired with timestamps as ``start + i * step`` for ``i`` in 0..N.
    Files that fail to decode are skipped silently.
    """
    for i, fpath in enumerate(files):
        frame = cv2.imread(str(fpath))
        if frame is None:
            continue
        yield (start + i * step, frame)


# --- High-level "scan a video for vote sequences" helpers ------------------


def scan_window(
    video_url: str,
    *,
    start: float,
    duration: float,
    fps: float,
    timeout: int = 120,
) -> Iterator[FrameWithTimestamp]:
    """Yield (timestamp, frame) for a windowed scan around a single point.

    The temp directory holding the extracted frames is cleaned up when the
    iterator is exhausted, so consumers should fully iterate (or wrap in
    ``list(...)``) before the generator goes out of scope.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)
        files = extract_frames_to_dir(
            video_url,
            out_dir,
            fps_expression=str(fps),
            pattern="frame_%04d.png",
            start=start,
            duration=duration,
            timeout=timeout,
        )
        yield from iter_frames_from_dir(files, start=start, step=1 / fps)


def scan_full(
    video_url: str,
    *,
    scan_interval: float,
    timeout: int = 600,
) -> Iterator[FrameWithTimestamp]:
    """Yield (timestamp, frame) for a full-video scan at one frame per ``scan_interval`` seconds.

    Raises ``IncompleteVideoScanError`` if the extracted frame coverage
    falls below ``_SCAN_COVERAGE_MIN_RATIO`` of the probed duration —
    ffmpeg returns success when an HTTP source truncates mid-stream, so
    without this check a partial read looks identical to a meeting that
    legitimately had no vote frames.
    """
    expected = probe_duration(video_url)
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)
        files = extract_frames_to_dir(
            video_url,
            out_dir,
            fps_expression=f"1/{scan_interval}",
            pattern="scan_%06d.png",
            timeout=timeout,
        )
        covered = len(files) * scan_interval
        if expected > 0 and covered < expected * _SCAN_COVERAGE_MIN_RATIO:
            raise IncompleteVideoScanError(
                f"scan covered {covered:.1f}s of {expected:.1f}s "
                f"({covered / expected * 100:.1f}%) — download likely truncated"
            )
        yield from iter_frames_from_dir(files, start=0.0, step=scan_interval)


@contextmanager
def download_video_to_tempfile(video_url: str, timeout: int = 600) -> Iterator[Path]:
    """Download ``video_url`` to a tempfile and yield the local path.

    Recovery path for ``IncompleteVideoScanError``: local files are
    immune to the mid-stream HTTP truncation that ``scan_full`` guards
    against. The tempfile is removed on context exit.
    """
    suffix = Path(urllib.parse.urlparse(video_url).path).suffix or ".mp4"
    fd, tmppath = tempfile.mkstemp(suffix=suffix, prefix="muni_video_")
    os.close(fd)
    local = Path(tmppath)
    try:
        request = urllib.request.Request(video_url, headers={"User-Agent": BROWSER_USER_AGENT})
        with (
            urllib.request.urlopen(request, timeout=timeout) as resp,
            open(local, "wb") as out,
        ):
            shutil.copyfileobj(resp, out)
        yield local
    finally:
        local.unlink(missing_ok=True)
