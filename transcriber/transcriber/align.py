"""Measure where one recording of a meeting sits on another recording's clock.

The council's meetings are recorded twice: as a Granicus clip and as a video on
the council's YouTube channel. The two do not start at the same moment. Given
both as 8 kHz mono 16-bit WAV files, this module finds the offset between them
(Granicus seconds minus YouTube seconds, so a moment at Granicus second ``g``
is at YouTube second ``g - offset``), the stretch of the Granicus clock the
YouTube recording has been confirmed to cover, and whether to trust the answer.

The method. Each recording is reduced to four log band-energy envelopes at 25
frames a second (``features``). The envelopes of the whole YouTube recording
are cross-correlated against the Granicus clip's (``xcorr_z``); the highest
peak is the offset and its z-score is the score. Then the YouTube recording is
cut into 5-minute windows, plus one more that ends where the overlap of the
two recordings ends, and each window inside the clip searches for its own best
match: a window confirms the whole-recording offset when its best match within
40 seconds of that offset lies within 2 seconds of it, and it is a conflict
when its best match anywhere is strong and lies elsewhere (the mark of a
recording that was cut or edited). ``verdict`` is the pass mark.

The constants below ARE the method. The pass mark was chosen on this exact
arithmetic from 72 labelled pairs of real recordings (decision 0078 under
docs/decisions/ and docs/specs/video-links.md; the table is in
plans/completed/video-links-land-on-the-moment.md), so a different window size,
band edge, or normalisation changes the scores the mark was chosen from. Raise
``ALIGN_METHOD_VERSION`` with any such change: stored measurements below the
current version are measured again.

Only the standard library and numpy. Nothing here downloads, converts, or
keeps audio; the caller hands in files or arrays.

    python -m transcriber.align <granicus.wav> <youtube.wav>

prints one line, ``describe()``'s text.
"""
from __future__ import annotations

import sys
import wave
from dataclasses import dataclass

import numpy as np

ALIGN_METHOD_VERSION = 1

SR, HOP, WIN = 8000, 320, 640          # sample rate; frame hop and frame length in samples
FPS = SR / HOP                         # 25 frames a second
BANDS = (300, 700, 1300, 2200, 3600)   # four bands, Hz
SMOOTH_S = 0.4                         # moving mean applied to each envelope
HIGHPASS_S = 8.0                       # a moving mean this long is removed from each envelope
WINDOW_S = 300                         # one window of the YouTube recording
LOCAL_SEARCH_S = 40.0                  # how far from the offset a window looks for its confirmation
AGREE_S = 2.0                          # a window agrees when its match is this close to the offset
RUNNER_EXCLUDE_S = 5.0                 # the runner-up is the best score farther than this from the offset
PASS_SCORE = 9.0                       # the whole-recording score a passing measurement reaches
PASS_MARGIN = 4.0                      # and exceeds the runner-up by
PASS_WINDOW_SHARE = 0.6                # the share of counted windows that must confirm
CONFLICT_SCORE = 8.0                   # a window this strong at another offset rejects the recording
MIN_AUDIO_S = 10                       # features refuses audio shorter than this

_CHUNK_FRAMES = 20000                  # frames transformed at once, to bound memory


@dataclass(frozen=True)
class Measurement:
    """Where one YouTube recording sits against one Granicus clip."""

    status: str                      # 'passed' or 'rejected'
    reason: str | None               # None when passed
    offset_s: float                  # Granicus seconds minus YouTube seconds
    granicus_start_s: float | None   # None when no window was confirmed
    granicus_end_s: float | None
    score: float
    runner_up: float
    windows: int                     # windows counted (those inside the clip)
    windows_confirmed: int


def read_wav(path) -> np.ndarray:
    """The samples of an 8 kHz mono 16-bit WAV file. ValueError for any other shape."""
    with wave.open(str(path), "rb") as w:
        rate, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        if (rate, channels, width) != (SR, 1, 2):
            raise ValueError(
                f"{path}: expected 8 kHz mono 16-bit audio, "
                f"got {rate} Hz, {channels} channel(s), {8 * width}-bit"
            )
        frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, dtype="<i2")


def _moving_mean(a: np.ndarray, seconds: float) -> np.ndarray:
    """Each column's moving mean over `seconds`, edge-padded to the input's length."""
    k = max(1, int(seconds * FPS))
    c = np.cumsum(np.vstack([np.zeros((1, a.shape[1])), a]), axis=0, dtype=np.float64)
    r = (c[k:] - c[:-k]) / k
    pad = a.shape[0] - r.shape[0]
    return np.vstack([np.repeat(r[:1], pad // 2, axis=0), r,
                      np.repeat(r[-1:], pad - pad // 2, axis=0)]).astype(np.float32)


def features(samples: np.ndarray) -> np.ndarray:
    """The (frames, 4) float32 envelopes of int16 samples at 8 kHz.

    Raises ValueError for fewer than 10 seconds of samples: a download that
    yielded a few bytes is not audio to measure.
    """
    x = samples
    if len(x) < MIN_AUDIO_S * SR:
        raise ValueError(f"audio is {len(x) / SR:.1f}s, shorter than {MIN_AUDIO_S}s")
    n = (len(x) - WIN) // HOP + 1
    window = np.hanning(WIN).astype(np.float32)
    freqs = np.fft.rfftfreq(WIN, 1 / SR)
    masks = [(freqs >= lo) & (freqs < hi) for lo, hi in zip(BANDS[:-1], BANDS[1:])]
    out = np.empty((n, len(masks)), dtype=np.float32)
    for s in range(0, n, _CHUNK_FRAMES):
        e = min(n, s + _CHUNK_FRAMES)
        idx = (np.arange(s, e)[:, None] * HOP) + np.arange(WIN)[None, :]
        spec = np.abs(np.fft.rfft(x[idx].astype(np.float32) * window, axis=1)) ** 2
        for b, m in enumerate(masks):
            out[s:e, b] = np.log(spec[:, m].sum(axis=1) + 1e3)
    out = _moving_mean(out, SMOOTH_S)
    out = out - _moving_mean(out, HIGHPASS_S)
    out -= out.mean(axis=0)
    out /= out.std(axis=0) + 1e-9
    return out


def xcorr_z(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The z-scored cross-correlation of two feature arrays, summed over bands,
    and the offset in seconds (a's clock minus b's) each entry stands for."""
    n = len(a) + len(b) - 1
    size = 1 << (n - 1).bit_length()
    total = np.zeros(n)
    for band in range(a.shape[1]):
        total += np.fft.irfft(
            np.fft.rfft(a[:, band], size) * np.fft.rfft(b[::-1, band], size), size
        )[:n]
    z = (total - total.mean()) / (total.std() + 1e-9)
    return z, (np.arange(n) - (len(b) - 1)) / FPS


def verdict(score, runner_up, windows, confirmed, conflicts) -> tuple[str, str | None]:
    """The pass mark: ('passed', None) or ('rejected', <reason>), checked in this order."""
    if windows < 1:
        return "rejected", "no_window"
    if score < PASS_SCORE:
        return "rejected", "score"
    if score - runner_up < PASS_MARGIN:
        return "rejected", "margin"
    if confirmed / windows < PASS_WINDOW_SHARE:
        return "rejected", "windows"
    if conflicts:
        return "rejected", "conflict"
    return "passed", None


def measure(granicus: np.ndarray, youtube: np.ndarray) -> Measurement:
    """Measure a YouTube recording against a Granicus clip, both as feature arrays."""
    g, y = granicus, youtube
    gdur = len(g) / FPS
    z, lags = xcorr_z(g, y)
    k = int(np.argmax(z))
    offset = float(lags[k])
    score = float(z[k])
    rest = z.copy()
    rest[np.abs(lags - offset) <= RUNNER_EXCLUDE_S] = -np.inf
    runner_up = float(rest.max())

    wl = int(WINDOW_S * FPS)
    counted = conflicts = 0
    confirmed: list[float] = []
    # The grid: whole windows from the start of the YouTube recording.
    starts = list(range(0, len(y) - wl + 1, wl))
    # The end window, which ends where the overlap of the two recordings ends:
    # at the end of the YouTube recording, or at the end of the clip when the
    # recording runs past it.
    last = min(len(y), int(round((gdur - offset) * FPS))) - wl
    if last > 0 and last not in starts:
        starts.append(last)
    for s in starts:
        ys = s / FPS
        if offset + ys < 0 or offset + ys + WINDOW_S > gdur + 1e-6:
            continue  # the window falls outside the clip
        counted += 1
        wz, wlags = xcorr_z(g, y[s:s + wl])
        wlags = wlags - ys
        kb = int(np.argmax(wz))
        near = np.abs(wlags - offset) <= LOCAL_SEARCH_S
        kn = int(np.argmax(np.where(near, wz, -np.inf)))
        if abs(wlags[kn] - offset) <= AGREE_S:
            confirmed.append(ys)
        if wz[kb] >= CONFLICT_SCORE and abs(wlags[kb] - offset) > AGREE_S:
            conflicts += 1

    # Coverage is the span from the first confirmed window to the last, on the
    # Granicus clock, clipped to the clip. The end window is not always the
    # last by start, hence min and max.
    start = max(0.0, offset + min(confirmed)) if confirmed else None
    end = min(gdur, offset + max(confirmed) + WINDOW_S) if confirmed else None
    status, reason = verdict(score, runner_up, counted, len(confirmed), conflicts)
    return Measurement(
        status=status,
        reason=reason,
        offset_s=offset,
        granicus_start_s=start,
        granicus_end_s=end,
        score=score,
        runner_up=runner_up,
        windows=counted,
        windows_confirmed=len(confirmed),
    )


def measure_files(granicus_wav, youtube_wav) -> Measurement:
    """Measure two 8 kHz mono 16-bit WAV files; the first is the Granicus clip."""
    return measure(features(read_wav(granicus_wav)), features(read_wav(youtube_wav)))


def describe(m: Measurement) -> str:
    """One line for the log, e.g.
    'passed offset=635.48s covers=635.5-4078.7s score=23.6 runner_up=6.0 windows=10/12'."""
    head = m.status if m.reason is None else f"{m.status} ({m.reason})"
    covers = (
        "none" if m.granicus_start_s is None or m.granicus_end_s is None
        else f"{m.granicus_start_s:.1f}-{m.granicus_end_s:.1f}s"
    )
    return (
        f"{head} offset={m.offset_s:.2f}s covers={covers} score={m.score:.1f} "
        f"runner_up={m.runner_up:.1f} windows={m.windows_confirmed}/{m.windows}"
    )


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("usage: python -m transcriber.align <granicus.wav> <youtube.wav>", file=sys.stderr)
        return 2
    print(describe(measure_files(args[0], args[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
