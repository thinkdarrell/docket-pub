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
    assert m.stretches == ()


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


def _assert_stretch(stretch, *, offset, start, end, windows, label=""):
    """One stretch's offset and coverage within 0.1 s and its (confirmed, counted) windows."""
    assert stretch.offset_s == pytest.approx(offset, abs=0.1), label
    assert stretch.granicus_start_s == pytest.approx(start, abs=0.1), label
    assert stretch.granicus_end_s == pytest.approx(end, abs=0.1), label
    assert (stretch.windows_confirmed, stretch.windows) == windows, label


def test_cut_recording_yields_one_stretch_per_offset():
    import transcriber.align as align

    assert align.ALIGN_METHOD_VERSION == 3 and align.ALIGN_TRUSTED_VERSION == 2
    g_samples, g = _granicus(align)
    # Two true offsets: 300 s for the first 1,200 s, 490 s for the last 310 s.
    youtube = np.concatenate([_cut(g_samples, 300, 1500), _cut(g_samples, 1690, 2000)])
    m = align.measure(g, align.features(youtube))

    assert (m.status, m.reason) == ("passed", None)
    assert len(m.stretches) == 2
    first, second = m.stretches
    # Four grid windows confirm 300.
    _assert_stretch(first, offset=300.0, start=300.0, end=1500.0, windows=(4, 4))
    # The grid window at 1,200 s and the end window at 1,210 s confirm 490.
    _assert_stretch(second, offset=490.0, start=1690.0, end=2000.0, windows=(2, 2))
    for stretch in m.stretches:
        assert stretch.score >= align.PASS_SCORE
        assert stretch.score - stretch.runner_up >= align.PASS_MARGIN
    # The measurement's own figures are the first stretch's.
    assert m.offset_s == pytest.approx(300.0, abs=0.1)
    assert (m.granicus_start_s, m.granicus_end_s) == (first.granicus_start_s, first.granicus_end_s)
    assert (m.windows_confirmed, m.windows) == (4, 4)
    assert align.describe_stretch(m, 1).startswith(
        "passed stretch 1/2 offset=300.00s covers=300.0-1500.0s")
    assert align.describe_stretch(m, 2).startswith(
        "passed stretch 2/2 offset=490.00s covers=1690.0-2000.0s")
    assert align.describe(m).count("\n") == 1
    assert align.describe(m) == "\n".join(
        [align.describe_stretch(m, 1), align.describe_stretch(m, 2)])


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


def test_offset_step_inside_the_agreement_tolerance_passes_and_a_larger_one_splits_into_two_stretches():
    import transcriber.align as align

    g_samples, g = _granicus(align)

    # 1.5 s missing from the recording: inside the 2-second tolerance.
    small = np.concatenate([_cut(g_samples, 400, 1000), _cut(g_samples, 1001.5, 1605)])
    m = align.measure(g, align.features(small))
    assert (m.status, m.reason) == ("passed", None)
    assert m.offset_s == pytest.approx(400.0, abs=0.1)
    assert (m.windows_confirmed, m.windows) == (5, 5)
    assert len(m.stretches) == 1

    # 3 s missing: outside it, so the recording sits at two offsets.
    large = np.concatenate([_cut(g_samples, 400, 1000), _cut(g_samples, 1003, 1605)])
    m = align.measure(g, align.features(large))
    assert (m.status, m.reason) == ("passed", None)
    assert len(m.stretches) == 2
    _assert_stretch(m.stretches[0], offset=400.0, start=400.0, end=1000.0, windows=(2, 2))
    _assert_stretch(m.stretches[1], offset=403.0, start=1003.0, end=1605.0, windows=(3, 3))


def test_a_replaced_window_splits_one_offset_into_two_stretches():
    import transcriber.align as align

    g_samples, g = _granicus(align)
    # The third 5-minute window is another part of the clip: a true match at
    # offset 900 in the middle of a recording that sits at offset 400.
    youtube = np.concatenate([_cut(g_samples, 400, 1000), _cut(g_samples, 1500, 1800),
                              _cut(g_samples, 1300, 1905)])
    m = align.measure(g, align.features(youtube))

    assert (m.status, m.reason) == ("passed", None)
    assert len(m.stretches) == 3
    # In order of where the coverage starts; the second and third overlap on
    # the Granicus clock, because the recording plays that part twice.
    _assert_stretch(m.stretches[0], offset=400.0, start=400.0, end=1000.0, windows=(2, 2))
    _assert_stretch(m.stretches[1], offset=400.0, start=1300.0, end=1905.0, windows=(3, 3))
    _assert_stretch(m.stretches[2], offset=900.0, start=1500.0, end=1800.0, windows=(1, 1))
    # The measurement's own window counts are the first stretch's, not the
    # 5 of 6 the whole recording has under offset 400.
    assert (m.windows_confirmed, m.windows) == (2, 2)
    for stretch in m.stretches:
        assert stretch.score >= align.PASS_SCORE
        assert stretch.score - stretch.runner_up >= align.PASS_MARGIN
        assert stretch.runner_up == m.runner_up


def test_a_quiet_window_inside_a_stretch_stays_inside_it():
    import transcriber.align as align

    g_samples, g = _granicus(align)
    # The same recording with unrelated audio in the third window: it matches
    # nowhere, so it ends no stretch.
    youtube = np.concatenate([_cut(g_samples, 400, 1000), _signal(11, 300),
                              _cut(g_samples, 1300, 1905)])
    m = align.measure(g, align.features(youtube))

    assert (m.status, m.reason) == ("passed", None)
    assert len(m.stretches) == 1
    _assert_stretch(m.stretches[0], offset=400.0, start=400.0, end=1905.0, windows=(5, 6))
    assert (m.windows_confirmed, m.windows) == (5, 6)


# ---------------------------------------------------------------------------
# The two ends of the coverage are checked in pieces
# ---------------------------------------------------------------------------
#
# A five-minute window confirms when most of it matches, so a window at the
# edge of a recording confirmed although its outer part was other audio, and
# the coverage ran over that part. The first and last stretches of the
# confirmed span are checked again in pieces of EDGE_S seconds, and the
# coverage starts at the first piece that confirms and ends with the last.
# The piece that holds the boundary can still confirm on its matching part,
# so less than one piece of other audio may stay covered.


def _start_cases(g_samples):
    """(label, seconds of other audio at the recording's start, the recording)."""
    for n in (60, 100, 140, 160):
        # The closing review's signal: the first n seconds sit at another offset.
        yield f"{n}s at another offset", n, np.concatenate(
            [_cut(g_samples, 1500, 1500 + n), _cut(g_samples, 400 + n, 1305)])
    for n in (60, 100, 160, 250):
        yield f"{n}s of unrelated audio", n, np.concatenate(
            [_signal(7, n), _cut(g_samples, 400 + n, 1305)])
    for n in (90, 150):
        yield f"{n}s of silence", n, np.concatenate(
            [np.zeros(n * SR, dtype=np.int16), _cut(g_samples, 400 + n, 1305)])


def test_other_audio_at_the_start_of_a_recording_is_not_covered():
    import transcriber.align as align

    assert align.ALIGN_METHOD_VERSION >= 2   # the edge check is a change of method
    g_samples, g = _granicus(align)
    for label, n, youtube in _start_cases(g_samples):
        m = align.measure(g, align.features(youtube))

        # The pass mark's numbers are the windows' and are not touched.
        assert (m.status, m.reason) == ("passed", None), label
        assert m.offset_s == pytest.approx(400.0, abs=0.1), label
        assert (m.windows_confirmed, m.windows) == (4, 4), label
        # The recording matches from Granicus second 400 + n. Less than one
        # piece before that is covered, and no more is given up than through
        # the piece that holds the boundary.
        pieces_given_up = -(-n // align.EDGE_S)
        assert 400 + n - align.EDGE_S < m.granicus_start_s, label
        assert m.granicus_start_s <= 400 + pieces_given_up * align.EDGE_S + 0.1, label
        assert m.granicus_end_s == pytest.approx(1305.0, abs=0.1), label


def test_other_audio_at_the_end_of_a_recording_is_not_covered():
    import transcriber.align as align

    g_samples, g = _granicus(align)
    cases = []
    for n in (60, 100):
        # A recording cut n seconds before its end: its last stretch sits at
        # another offset (the 5 extra seconds are the frame count's shortfall).
        cases.append((f"cut {n}s before the end", 300.0, 1400.0, np.concatenate(
            [_cut(g_samples, 300, 1400), _cut(g_samples, 1700, 1700 + n + 5)])))
    for n in (60, 100, 160):
        cases.append((f"last {n}s unrelated", 400.0, 1305.0 - n, np.concatenate(
            [_cut(g_samples, 400, 1305 - n), _signal(8, n)])))
    for label, offset, matches_until, youtube in cases:
        m = align.measure(g, align.features(youtube))

        assert (m.status, m.reason) == ("passed", None), label
        assert m.offset_s == pytest.approx(offset, abs=0.1), label
        assert m.granicus_start_s == pytest.approx(offset, abs=0.1), label
        # Less than one piece past the last matching second is covered, and
        # the coverage still reaches into the last matching minute.
        assert m.granicus_end_s < matches_until + align.EDGE_S, label
        assert m.granicus_end_s > matches_until - align.EDGE_S, label


def test_confirmed_span_is_none_when_no_piece_confirms():
    import transcriber.align as align

    _, g = _granicus(align)
    # A recording whose envelopes are flat, as digital silence is: a piece of
    # it has no best match, so none confirms.
    silent = np.zeros((int(600 * align.FPS), g.shape[1]), dtype=np.float32)
    assert align.confirmed_span(g, silent, 400.0, 0.0, 600.0) is None

    # The same span of a recording that does match is kept whole.
    g_samples, _ = _granicus(align)
    y = align.features(_cut(g_samples, 400, 1005))
    assert align.confirmed_span(g, y, 400.0, 0.0, 600.0) == (0.0, 600.0)


def test_recording_whose_windows_pass_and_whose_pieces_do_not_is_rejected(monkeypatch):
    import transcriber.align as align

    g_samples, g = _granicus(align)
    y = align.features(_cut(g_samples, 400, 1305))
    assert align.measure(g, y).status == "passed"

    monkeypatch.setattr(align, "confirmed_span", lambda *args: None)
    m = align.measure(g, y)
    assert (m.status, m.reason) == ("rejected", "edges")
    assert (m.granicus_start_s, m.granicus_end_s) == (None, None)
    assert m.offset_s == pytest.approx(400.0, abs=0.1)
    assert (m.windows_confirmed, m.windows) == (4, 4)
    assert m.stretches == ()
    assert align.describe(m).startswith("rejected (edges) offset=400.")
    assert "covers=none" in align.describe(m)


def test_features_refuses_audio_shorter_than_ten_seconds():
    import transcriber.align as align

    with pytest.raises(ValueError, match="shorter than 10s"):
        align.features(_signal(5, 9))


def test_verdict_reproduces_the_labelled_table():
    import transcriber.align as align

    # The nine matched pairs of the revised table in the plan
    # (plans/completed/video-links-land-on-the-moment.md, Artifacts and Notes):
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
    assert align.describe(from_files).startswith("passed stretch 1/1 offset=200.")
