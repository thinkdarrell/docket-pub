"""Where a clip's audio is silent (plan silent-granicus-says-so, M1).

Every test builds its own samples with numpy at 8,000 a second: zeros for silence, seeded
noise of about -30 dBFS for sound. Nothing is downloaded. `transcriber.sound` is imported
inside each test so the file collects before the module exists.
"""
from __future__ import annotations

import numpy as np
import pytest

RATE = 8000


def _zeros(seconds: int) -> np.ndarray:
    return np.zeros(seconds * RATE, dtype="<i2")


def _noise(seconds: int) -> np.ndarray:
    return np.random.default_rng(0).normal(0, 1000, seconds * RATE).astype("<i2")


def _constant(value: int, seconds: int) -> np.ndarray:
    return np.full(seconds * RATE, value, dtype="<i2")


def test_ten_minutes_of_zeros_are_one_silent_span_from_end_to_end():
    from transcriber import sound

    measured = sound.measure(_zeros(600))

    assert measured.duration_s == 600.0
    assert measured.silent_s == 600.0
    assert measured.spans == ((0.0, 600.0),)


def test_ten_minutes_of_noise_have_no_silent_span():
    from transcriber import sound

    measured = sound.measure(_noise(600))

    assert measured.duration_s == 600.0
    assert measured.silent_s == 0.0
    assert measured.spans == ()


def test_neighbouring_silent_blocks_are_joined_and_spans_come_in_order():
    from transcriber import sound

    samples = np.concatenate([_noise(300), _zeros(1500), _noise(3600), _zeros(600)])

    measured = sound.measure(samples)

    assert measured.duration_s == 6000.0
    assert measured.spans == ((300.0, 1800.0), (5400.0, 6000.0))
    assert measured.silent_s == 2100.0


def test_a_block_is_silent_below_minus_60_dbfs_and_not_at_minus_59_94():
    from transcriber import sound

    # 20 * log10(33 / 32768) is -59.94 and 20 * log10(32 / 32768) is -60.21
    assert sound.measure(_constant(33, 60)).spans == ()
    assert sound.measure(_constant(32, 60)).spans == ((0.0, 60.0),)
    # the level is the whole 60-second block's: half noise and half zeros is one audible block
    assert sound.measure(np.concatenate([_noise(30), _zeros(30)])).spans == ()


def test_a_tail_shorter_than_ten_seconds_joins_the_block_before_it():
    from transcriber import sound

    measured = sound.measure(_zeros(605))

    assert measured.duration_s == 605.0
    assert measured.spans == ((0.0, 605.0),)
    assert measured.silent_s == 605.0
    # five silent seconds after ten minutes of noise are part of the last, audible block
    assert sound.measure(np.concatenate([_noise(600), _zeros(5)])).spans == ()


def test_a_tail_of_ten_seconds_or_more_is_a_block_of_its_own():
    from transcriber import sound

    measured = sound.measure(np.concatenate([_zeros(600), _noise(15)]))

    assert measured.duration_s == 615.0
    assert measured.spans == ((0.0, 600.0),)
    assert measured.silent_s == 600.0


def test_a_clip_shorter_than_the_tail_floor_is_one_block():
    from transcriber import sound

    measured = sound.measure(_zeros(5))

    assert measured.duration_s == 5.0
    assert measured.spans == ((0.0, 5.0),)


def test_no_samples_raise_value_error():
    from transcriber import sound

    with pytest.raises(ValueError):
        sound.measure(np.zeros(0, dtype="<i2"))
