"""Measure where one recording of a meeting sits on another recording's clock.

The council's meetings are recorded twice: as a Granicus clip and as a video on
the council's YouTube channel. The two do not start at the same moment. Given
both as 8 kHz mono 16-bit WAV files, this module finds the offset between them
(Granicus seconds minus YouTube seconds, so a moment at Granicus second ``g``
is at YouTube second ``g - offset``), the stretches of the Granicus clock the
YouTube recording has been confirmed to cover, and whether to trust the answer.

The method. Each recording is reduced to four log band-energy envelopes at 25
frames a second (``features``). The envelopes of the whole YouTube recording
are cross-correlated against the Granicus clip's (``xcorr_z``); the highest
peak is the first offset to try. The YouTube recording is cut into 5-minute
windows, and each window's own best match against the clip is found once. A
recording that dropped and resumed, or that was stitched from two pieces,
sits at more than one offset, so the offsets tried are the whole-recording
peak and then the offset of every window that matches strongly somewhere
else, strongest first, ``MAX_OFFSETS`` at most.

Under each offset the windows inside the clip, plus one more that ends where
the overlap of the two recordings ends, are classed in this order: a conflict
when the window's best match anywhere is strong and lies elsewhere; agreeing
when its best match within 40 seconds of the offset lies within 2 seconds of
it; quiet otherwise. A stretch is one contiguous run of the recording that
matches the clip at one offset: a run of windows with no conflict in it,
trimmed to its first and last agreeing window. A conflict window ends a
stretch; it does not reject the recording. A stretch's score is the
whole-recording cross-correlation at its offset, and the runner-up is the
best score away from every offset that confirmed a stretch. ``verdict`` is
the pass mark, and it is applied to each stretch, not to the recording: a
recording passes when at least one stretch does, and each passing stretch
has its own offset, coverage, and figures (``Stretch``).

A window confirms when most of it matches, so the windows alone cannot say
where, inside the first and the last of them, the match begins and ends. The
two ends of each stretch are therefore checked again in pieces of
``EDGE_S`` seconds, each by the test a window gets, and the coverage runs
from the first piece that confirms to the last (``confirmed_span``). The
pieces move the coverage only: the offset, the score, and the window counts
the pass mark reads are the windows'.

The constants below ARE the method. The pass mark was chosen on the windows'
arithmetic from 72 labelled pairs of real recordings (decision 0078 under
docs/decisions/ and docs/specs/video-links.md; the table is in
plans/completed/video-links-land-on-the-moment.md), so a different window size,
band edge, or normalisation changes the scores the mark was chosen from. The
pieces were added afterwards and checked on the same recordings (decision
0081), the stretches after that (plan ``youtube-links-cover-matching-stretches``).
Raise ``ALIGN_METHOD_VERSION`` with any such change: a stored rejection below
the current version is measured again, and a stored pass stays trusted from
``ALIGN_TRUSTED_VERSION`` up.

Only the standard library and numpy. Nothing here downloads, converts, or
keeps audio; the caller hands in files or arrays.

    python -m transcriber.align <granicus.wav> <youtube.wav>

prints ``describe()``'s text: one line per stretch, or the one rejected line.
"""
from __future__ import annotations

import sys
import wave
from dataclasses import dataclass

import numpy as np

ALIGN_METHOD_VERSION = 3               # 3: coverage in stretches, one per offset; a conflict window ends a stretch
# The version from which a passed row stays trusted by the candidate query
# (transcriber/transcriber/db.py): the stretch rule gives a single-offset
# recording the row it had at version 2. MIN_METHOD_VERSION in
# src/docket/services/video_links.py is the same figure for the site.
ALIGN_TRUSTED_VERSION = 2

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
CONFLICT_SCORE = 8.0                   # a window this strong at another offset ends a stretch
MAX_OFFSETS = 4                        # offsets tried per recording: the whole-recording peak and up to three more the windows point at
EDGE_S = 60                            # the ends of the confirmed span are checked in pieces this long
MIN_AUDIO_S = 10                       # features refuses audio shorter than this

_CHUNK_FRAMES = 20000                  # frames transformed at once, to bound memory


@dataclass(frozen=True)
class Stretch:
    """One contiguous run of a YouTube recording that matches the clip at one offset."""

    offset_s: float                  # Granicus seconds minus YouTube seconds
    granicus_start_s: float          # the coverage on the Granicus clock, start included
    granicus_end_s: float            # end excluded
    score: float                     # the whole-recording cross-correlation at this offset
    runner_up: float                 # the best score outside every confirmed offset
    windows: int                     # windows counted in this stretch
    windows_confirmed: int           # of them, those that agree with the offset


@dataclass(frozen=True)
class Measurement:
    """Where one YouTube recording sits against one Granicus clip.

    Passed: `stretches` holds every passing stretch in order of where its
    coverage starts, and the seven figures are the first stretch's. Rejected:
    the figures are the whole recording's under its best offset, there is no
    span, and `stretches` is empty."""

    status: str                      # 'passed' or 'rejected'
    reason: str | None               # None when passed
    offset_s: float                  # passed: the first stretch's; rejected: the whole-recording peak
    granicus_start_s: float | None   # passed: the first stretch's; rejected: None
    granicus_end_s: float | None
    score: float
    runner_up: float
    windows: int                     # passed: the first stretch's; rejected: counted under the peak
    windows_confirmed: int
    stretches: tuple[Stretch, ...] = ()   # every stretch in start order; empty when rejected


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
    """The pass mark: ('passed', None) or ('rejected', <reason>), checked in this order.

    `measure` applies it to each stretch with no conflicts, since a conflict
    window ends a stretch, and adds one reason of its own, 'edges', for a
    recording whose best run meets the mark and has no piece left to cover."""
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


def _piece_confirms(g: np.ndarray, piece: np.ndarray, ys: float, offset: float) -> bool:
    """A window's test on a shorter piece of the YouTube recording that starts at
    YouTube second `ys`: its best match within LOCAL_SEARCH_S of the offset lies
    within AGREE_S of it. Only the stretch of the clip the search can reach is read."""
    at = int(round((offset + ys) * FPS))
    reach = int(LOCAL_SEARCH_S * FPS)
    lo, hi = max(0, at - reach), min(len(g), at + len(piece) + reach)
    if hi - lo < len(piece):
        return False
    z, lags = xcorr_z(g[lo:hi], piece)
    lags = lags + lo / FPS - ys
    near = np.abs(lags - offset) <= LOCAL_SEARCH_S
    kn = int(np.argmax(np.where(near, z, -np.inf)))
    return bool(abs(lags[kn] - offset) <= AGREE_S)


def confirmed_span(g: np.ndarray, y: np.ndarray, offset: float,
                   start_s: float, end_s: float) -> tuple[float, float] | None:
    """The span the windows confirmed, in YouTube seconds, with each end moved
    inward to the first piece of EDGE_S seconds that confirms the offset.

    Pieces are counted forward from `start_s` until one confirms, then backward
    from `end_s` until one confirms. None when no piece does. The piece that
    holds the boundary between other audio and the match can confirm on its
    matching part, so less than one piece of other audio may stay inside the
    span, and a piece of other audio confirms by accident about one time in
    twenty (AGREE_S against LOCAL_SEARCH_S).
    """
    n = int(EDGE_S * FPS)
    a, b = int(round(start_s * FPS)), min(len(y), int(round(end_s * FPS)))
    s = a
    while s + n <= b and not _piece_confirms(g, y[s:s + n], s / FPS, offset):
        s += n
    if s + n > b:
        return None
    e = b
    while e - n > s and not _piece_confirms(g, y[e - n:e], (e - n) / FPS, offset):
        e -= n
    return s / FPS, e / FPS


def measure(granicus: np.ndarray, youtube: np.ndarray) -> Measurement:
    """Measure a YouTube recording against a Granicus clip, both as feature arrays."""
    g, y = granicus, youtube
    gdur = len(g) / FPS
    z, lags = xcorr_z(g, y)
    k = int(np.argmax(z))
    peak = float(lags[k])
    peak_score = float(z[k])

    wl = int(WINDOW_S * FPS)
    # The grid: whole windows from the start of the YouTube recording.
    grid = list(range(0, len(y) - wl + 1, wl))
    cache: dict[int, tuple[np.ndarray, np.ndarray]] = {}

    def win(s: int) -> tuple[np.ndarray, np.ndarray]:
        """One window's cross-correlation against the clip, computed once, with
        its lags on the recording's clock."""
        if s not in cache:
            wz, wlags = xcorr_z(g, y[s:s + wl])
            cache[s] = (wz, wlags - s / FPS)
        return cache[s]

    def starts_for(o: float) -> list[int]:
        """The grid plus this offset's end window, which ends where the overlap
        of the two recordings ends: at the end of the YouTube recording, or at
        the end of the clip when the recording runs past it."""
        starts = list(grid)
        last = min(len(y), int(round((gdur - o) * FPS))) - wl
        if last > 0 and last not in starts:
            starts.append(last)
        return sorted(starts)

    # The offsets to try: the whole-recording peak, then the best offset of
    # every window that matches strongly, strongest first, unless it lies
    # within AGREE_S of one already taken.
    cands = [peak]
    strong = []
    for s in starts_for(peak):
        wz, wlags = win(s)
        kb = int(np.argmax(wz))
        if wz[kb] >= CONFLICT_SCORE:
            strong.append((float(wz[kb]), float(wlags[kb])))
    for _, off in sorted(strong, reverse=True):
        if all(abs(off - c) > AGREE_S for c in cands) and len(cands) < MAX_OFFSETS:
            cands.append(off)

    def z_at(o: float) -> float:
        return float(z[int(np.argmin(np.abs(lags - o)))])

    def classify(o: float) -> list[tuple[float, str]]:
        """(window start in YouTube seconds, 'conflict' | 'agree' | 'quiet') for
        each window that lies inside the clip under offset `o`."""
        rows = []
        for s in starts_for(o):
            ys = s / FPS
            if o + ys < 0 or o + ys + WINDOW_S > gdur + 1e-6:
                continue  # the window falls outside the clip
            wz, wlags = win(s)
            kb = int(np.argmax(wz))
            near = np.abs(wlags - o) <= LOCAL_SEARCH_S
            kn = int(np.argmax(np.where(near, wz, -np.inf)))
            if wz[kb] >= CONFLICT_SCORE and abs(wlags[kb] - o) > AGREE_S:
                kind = "conflict"
            elif abs(wlags[kn] - o) <= AGREE_S:
                kind = "agree"
            else:
                kind = "quiet"
            rows.append((ys, kind))
        return rows

    def runs(rows: list[tuple[float, str]]) -> list[list[tuple[float, str]]]:
        """The rows cut at every conflict, each run trimmed to its first and
        last agreeing window; a run with no agreeing window is dropped."""
        out, cur = [], []
        for ys, kind in rows:
            if kind == "conflict":
                if cur:
                    out.append(cur)
                cur = []
            else:
                cur.append((ys, kind))
        if cur:
            out.append(cur)
        trimmed = []
        for r in out:
            idx = [i for i, (_, kind) in enumerate(r) if kind == "agree"]
            if idx:
                trimmed.append(r[idx[0]:idx[-1] + 1])
        return trimmed

    def tally(r: list[tuple[float, str]]) -> tuple[int, int]:
        return len(r), sum(1 for _, kind in r if kind == "agree")

    # A run is kept when enough of its windows agree and the pieces confirm a
    # span inside it: (offset, counted, agreed, span in YouTube seconds).
    peak_rows = classify(peak)
    peak_runs = runs(peak_rows)
    found = []
    for o in cands:
        for r in (peak_runs if o == peak else runs(classify(o))):
            counted, agreed = tally(r)
            if agreed / counted < PASS_WINDOW_SHARE:
                continue
            span = confirmed_span(g, y, o, r[0][0], r[-1][0] + WINDOW_S)
            if span is None:
                continue
            found.append((o, counted, agreed, span))

    # The runner-up is the best score away from every offset that kept a run,
    # and away from the peak alone when none did.
    rest = z.copy()
    for o in (sorted({o for o, _, _, _ in found}) or [peak]):
        rest[np.abs(lags - o) <= RUNNER_EXCLUDE_S] = -np.inf
    runner_up = float(rest.max())

    # The pass mark, per stretch. Coverage is on the Granicus clock, clipped
    # to the clip.
    stretches = []
    for o, counted, agreed, span in found:
        status, _ = verdict(z_at(o), runner_up, counted, agreed, 0)
        if status == "passed":
            stretches.append(Stretch(
                offset_s=o,
                granicus_start_s=max(0.0, o + span[0]),
                granicus_end_s=min(gdur, o + span[1]),
                score=z_at(o),
                runner_up=runner_up,
                windows=counted,
                windows_confirmed=agreed,
            ))
    stretches.sort(key=lambda t: (t.granicus_start_s, t.offset_s))

    if stretches:
        first = stretches[0]
        return Measurement(
            status="passed",
            reason=None,
            offset_s=first.offset_s,
            granicus_start_s=first.granicus_start_s,
            granicus_end_s=first.granicus_end_s,
            score=first.score,
            runner_up=first.runner_up,
            windows=first.windows,
            windows_confirmed=first.windows_confirmed,
            stretches=tuple(stretches),
        )

    # No stretch passed. The reason is the first check the peak's best run
    # fails (the run with the most windows, the earliest on a tie; every
    # counted window with none agreeing when the peak has no run), and
    # 'edges' when it fails none: its windows met the mark and no piece of
    # their span confirmed, so there is nothing to cover.
    counted, agreed = tally(max(peak_runs, key=len)) if peak_runs else (len(peak_rows), 0)
    status, reason = verdict(peak_score, runner_up, counted, agreed, 0)
    if status == "passed":
        reason = "edges"
    whole_counted, whole_agreed = tally(peak_rows)
    return Measurement(
        status="rejected",
        reason=reason,
        offset_s=peak,
        granicus_start_s=None,
        granicus_end_s=None,
        score=peak_score,
        runner_up=runner_up,
        windows=whole_counted,
        windows_confirmed=whole_agreed,
    )


def measure_files(granicus_wav, youtube_wav) -> Measurement:
    """Measure two 8 kHz mono 16-bit WAV files; the first is the Granicus clip."""
    return measure(features(read_wav(granicus_wav)), features(read_wav(youtube_wav)))


def _figures(offset_s, start_s, end_s, score, runner_up, confirmed, counted) -> str:
    covers = "none" if start_s is None or end_s is None else f"{start_s:.1f}-{end_s:.1f}s"
    return (
        f"offset={offset_s:.2f}s covers={covers} score={score:.1f} "
        f"runner_up={runner_up:.1f} windows={confirmed}/{counted}"
    )


def describe_stretch(m: Measurement, k: int) -> str:
    """One line for stretch `k` of a passed measurement, counted from 1, e.g.
    'passed stretch 1/2 offset=300.00s covers=300.0-1500.0s score=49.5 runner_up=3.7 windows=4/4'."""
    if not 1 <= k <= len(m.stretches):
        raise IndexError(f"stretch {k} of {len(m.stretches)}")
    t = m.stretches[k - 1]
    return f"passed stretch {k}/{len(m.stretches)} " + _figures(
        t.offset_s, t.granicus_start_s, t.granicus_end_s, t.score, t.runner_up,
        t.windows_confirmed, t.windows)


def describe(m: Measurement) -> str:
    """The text for the log: one `describe_stretch` line per stretch, joined by
    newlines, or the one line of a measurement that has no stretches, e.g.
    'rejected (score) offset=-84.04s covers=none score=5.1 runner_up=4.7 windows=1/3'."""
    if m.stretches:
        return "\n".join(describe_stretch(m, k) for k in range(1, len(m.stretches) + 1))
    head = m.status if m.reason is None else f"{m.status} ({m.reason})"
    return f"{head} " + _figures(
        m.offset_s, m.granicus_start_s, m.granicus_end_s, m.score, m.runner_up,
        m.windows_confirmed, m.windows)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("usage: python -m transcriber.align <granicus.wav> <youtube.wav>", file=sys.stderr)
        return 2
    print(describe(measure_files(args[0], args[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
