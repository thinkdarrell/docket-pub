"""The audio matcher (transcriber/transcriber/align.py) on synthetic audio.

No real recording is committed. Each signal is white noise under a loudness
envelope that takes a new random level five times a second, which is the kind
of structure the matcher's band-energy envelopes follow in speech. The
"Granicus" side is 2,000 seconds of it; each "YouTube" side is cut from it, so
every test knows the true offset.

A signal's frame count falls just short of its length (2,000 seconds is 49,999
frames), so the pieces below are a few seconds longer than a whole number of
5-minute windows: each case can then say plainly which windows are grid
windows and which is the end window.

``align`` is imported inside each test so that this file collects, and each
test fails on its own, when the module is missing.
"""
import functools
import wave

import numpy as np
import pytest

SR = 8000  # the matcher's sample rate, stated here independently of align.SR
GRANICUS_SECONDS = 2000


@functools.lru_cache(maxsize=None)
def _signal(seed: int, seconds: int) -> np.ndarray:
    """`seconds` of enveloped white noise as 16-bit samples at 8 kHz. Read-only: it is cached."""
    rng = np.random.default_rng(seed)
    n = seconds * SR
    levels = rng.random(seconds * 5 + 2) ** 2
    envelope = np.interp(np.arange(n) / (SR / 5), np.arange(len(levels)), levels)
    noise = rng.standard_normal(n, dtype=np.float32)
    out = np.clip(noise * envelope * 6000.0, -32768, 32767).astype(np.int16)
    out.setflags(write=False)
    return out


def _cut(samples: np.ndarray, start_s: float, end_s: float) -> np.ndarray:
    return samples[int(round(start_s * SR)):int(round(end_s * SR))]


_GRANICUS_FEATURES: dict = {}


def _granicus(align):
    """The Granicus samples and their features, computed once for the file."""
    samples = _signal(1, GRANICUS_SECONDS)
    if "features" not in _GRANICUS_FEATURES:
        _GRANICUS_FEATURES["features"] = align.features(samples)
    return samples, _GRANICUS_FEATURES["features"]


def _write_wav(path, samples: np.ndarray, *, rate: int = SR, channels: int = 1, width: int = 2):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    return path


def test_shifted_noisy_copy_recovers_its_offset_and_passes():
    import transcriber.align as align

    g_samples, g = _granicus(align)
    copy = _cut(g_samples, 400, 1305).astype(np.float64) * 0.5
    noise = np.random.default_rng(2).standard_normal(len(copy)) * copy.std()
    m = align.measure(g, align.features((copy + noise).astype(np.int16)))

    assert (m.status, m.reason) == ("passed", None)
    assert m.offset_s == pytest.approx(400.0, abs=0.1)
    # Three grid windows and the end window, which starts about 605 s in.
    assert (m.windows_confirmed, m.windows) == (4, 4)
    assert m.granicus_start_s == pytest.approx(400.0, abs=0.1)
    # Without the end window coverage would stop at 1300.0.
    assert m.granicus_end_s == pytest.approx(1305.0, abs=0.1)
    assert m.score >= align.PASS_SCORE
    assert m.score - m.runner_up >= align.PASS_MARGIN


def test_unrelated_audio_is_rejected_on_score():
    import transcriber.align as align

    _, g = _granicus(align)
    m = align.measure(g, align.features(_signal(3, 905)))

    assert (m.status, m.reason) == ("rejected", "score")
    assert m.score < align.PASS_SCORE


def test_recording_that_starts_before_the_clip_counts_only_windows_inside_it():
    import transcriber.align as align

    g_samples, g = _granicus(align)
    youtube = np.concatenate([_signal(99, 200), _cut(g_samples, 0, 905)])
    m = align.measure(g, align.features(youtube))

    assert (m.status, m.reason) == ("passed", None)
    assert m.offset_s == pytest.approx(-200.0, abs=0.1)
    # The grid window at 0 s maps before the clip's start and is not counted;
    # the grid windows at 300 and 600 s and the end window are.
    assert (m.windows_confirmed, m.windows) == (3, 3)
    # No start window mirrors the end window: the clip's first 100 s, which
    # the recording does hold, stay uncovered.
    assert m.granicus_start_s == pytest.approx(100.0, abs=0.1)
    assert m.granicus_end_s == pytest.approx(905.0, abs=0.1)


def test_cut_recording_is_rejected():
    import transcriber.align as align

    g_samples, g = _granicus(align)
    # Two true offsets: 300 s for the first 1,200 s, 490 s for the last 310 s.
    youtube = np.concatenate([_cut(g_samples, 300, 1500), _cut(g_samples, 1690, 2000)])
    m = align.measure(g, align.features(youtube))

    assert (m.status, m.reason) == ("rejected", "conflict")
    assert m.offset_s == pytest.approx(300.0, abs=0.1)
    # Four windows confirm 300; the fifth grid window and the end window both
    # match strongly at 490.
    assert (m.windows_confirmed, m.windows) == (4, 6)


def test_recording_that_runs_past_the_clip_is_covered_to_the_clips_end():
    import transcriber.align as align

    g_samples, g = _granicus(align)
    youtube = np.concatenate([_cut(g_samples, 1250, 2000), _signal(4, 200)])
    m = align.measure(g, align.features(youtube))

    assert (m.status, m.reason) == ("passed", None)
    assert m.offset_s == pytest.approx(1250.0, abs=0.1)
    # Grid windows at 0 and 300 s; the grid window at 600 s maps past the
    # clip's end and is not counted; the end window ends at the clip's last frame.
    assert (m.windows_confirmed, m.windows) == (3, 3)
    assert m.granicus_start_s == pytest.approx(1250.0, abs=0.1)
    # An end window anchored to the end of the recording, not of the overlap,
    # would fall outside the clip and leave coverage at 1850.0.
    assert m.granicus_end_s == pytest.approx(2000.0, abs=0.1)


def test_offset_step_inside_the_agreement_tolerance_passes_and_a_larger_one_is_rejected():
    import transcriber.align as align

    g_samples, g = _granicus(align)

    # 1.5 s missing from the recording: inside the 2-second tolerance.
    small = np.concatenate([_cut(g_samples, 400, 1000), _cut(g_samples, 1001.5, 1605)])
    m = align.measure(g, align.features(small))
    assert (m.status, m.reason) == ("passed", None)
    assert m.offset_s == pytest.approx(400.0, abs=0.1)
    assert (m.windows_confirmed, m.windows) == (5, 5)

    # 3 s missing: outside it.
    large = np.concatenate([_cut(g_samples, 400, 1000), _cut(g_samples, 1003, 1605)])
    m = align.measure(g, align.features(large))
    assert m.status == "rejected"
    assert m.reason in ("windows", "conflict")


def test_features_refuses_audio_shorter_than_ten_seconds():
    import transcriber.align as align

    with pytest.raises(ValueError, match="shorter than 10s"):
        align.features(_signal(5, 9))


def test_verdict_reproduces_the_labelled_table():
    import transcriber.align as align

    # The nine matched pairs of the revised table in the plan
    # (plans/active/video-links-land-on-the-moment.md, Artifacts and Notes):
    # score, runner-up, windows counted, windows confirmed, conflicts.
    matched = [
        (23.6, 6.0, 12, 10, 0),    # clip 2026, FR84h22hQvA
        (27.1, 5.5, 21, 16, 0),    # clip 2024, uvqFjIfPLLU
        (12.3, 5.3, 7, 7, 0),      # clip 2017, ara-4Ve6XCU
        (25.7, 5.1, 18, 16, 0),    # clip 2016, 5i-rbOW2ngw
        (18.5, 5.6, 19, 13, 0),    # clip 2004, vj6zL48MllY
        (108.6, 3.4, 18, 18, 0),   # clip 1831, 96jZkW4zv7U
        (108.5, 3.4, 18, 18, 0),   # clip 1831, E0cpl0Snx20
        (93.3, 4.0, 15, 15, 0),    # clip 1530, m1dWfXzbpdI
        (130.4, 5.0, 25, 25, 0),   # clip 942, kxKL-StwTPg
    ]
    for row in matched:
        assert align.verdict(*row) == ("passed", None), row

    # The checks, in the order they are made.
    assert align.verdict(30.0, 5.0, 0, 0, 0) == ("rejected", "no_window")
    assert align.verdict(5.0, 4.9, 0, 0, 1) == ("rejected", "no_window")
    assert align.verdict(7.3, 5.8, 17, 3, 0) == ("rejected", "score")    # clip 2016 against vj6zL48MllY
    assert align.verdict(5.4, 4.7, 7, 3, 0) == ("rejected", "score")     # clip 1530 against ara-4Ve6XCU
    assert align.verdict(12.0, 9.0, 10, 10, 0) == ("rejected", "margin")
    assert align.verdict(12.0, 5.0, 10, 5, 0) == ("rejected", "windows")
    assert align.verdict(30.0, 5.0, 10, 10, 1) == ("rejected", "conflict")


def test_read_wav_refuses_anything_but_8khz_mono_16_bit(tmp_path):
    import transcriber.align as align

    samples = _signal(6, 12)
    good = _write_wav(tmp_path / "good.wav", samples)
    assert np.array_equal(align.read_wav(good), samples)

    with pytest.raises(ValueError, match="8 kHz"):
        align.read_wav(_write_wav(tmp_path / "16k.wav", samples, rate=16000))
    with pytest.raises(ValueError, match="8 kHz"):
        align.read_wav(_write_wav(tmp_path / "stereo.wav", samples, channels=2))
    with pytest.raises(ValueError, match="8 kHz"):
        align.read_wav(_write_wav(tmp_path / "8bit.wav", samples.astype(np.int8), width=1))


def test_measure_files_matches_measure(tmp_path):
    import transcriber.align as align

    g_samples, _ = _granicus(align)
    granicus = _cut(g_samples, 0, 900)
    youtube = _cut(g_samples, 200, 820)
    from_arrays = align.measure(align.features(granicus), align.features(youtube))
    from_files = align.measure_files(
        _write_wav(tmp_path / "granicus.wav", granicus),
        _write_wav(tmp_path / "youtube.wav", youtube),
    )

    assert from_files == from_arrays
    assert from_files.status == "passed"
    assert from_files.offset_s == pytest.approx(200.0, abs=0.1)
    assert align.describe(from_files).startswith("passed offset=200.")
