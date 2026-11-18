"""Where a clip's audio is silent.

Some Granicus clips have no sound, for all of their length or for part of it. A YouTube
recording cannot be matched against such a stretch, because the match is made from the
sound, and a reader sent to the Granicus player there hears nothing. This module measures
which stretches of a clip are silent, from the samples the measuring pass has already read.

The samples are cut into consecutive blocks of ``BLOCK_S`` seconds. What is left after the
last whole block is a block of its own when it holds at least ``MIN_TAIL_S`` seconds, and
is otherwise part of the block before it (the only block, when there is none before it). A
block is silent when its level, 20 times the base-10 logarithm of its root-mean-square
sample value over 32768, is below ``SILENCE_FLOOR_DBFS``; a block of zeros is silent.
Neighbouring silent blocks are one span.

It imports numpy and nothing else of the project. Plan silent-granicus-says-so, M1.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SOUND_METHOD_VERSION = 1       # raised when the arithmetic or a constant below changes
BLOCK_S = 60                   # one block of the clip, in seconds
SILENCE_FLOOR_DBFS = -60.0     # a block whose level is below this is silent
MIN_TAIL_S = 10                # a shorter remainder joins the block before it

_FULL_SCALE = 32768.0          # the largest magnitude a 16-bit sample holds


@dataclass(frozen=True)
class ClipSound:
    """How much of one clip is silent, and where, in seconds from the clip's start."""

    duration_s: float
    silent_s: float                          # the spans' total, never more than duration_s
    spans: tuple[tuple[float, float], ...]   # (start, end) of each silent run, in order


def _is_silent(block: np.ndarray) -> bool:
    values = block.astype(np.float64)
    rms = float(np.sqrt(np.mean(values * values)))
    if rms == 0.0:
        return True
    return 20.0 * np.log10(rms / _FULL_SCALE) < SILENCE_FLOOR_DBFS


def measure(samples: np.ndarray, rate: int = 8000) -> ClipSound:
    """The silent spans of 16-bit mono ``samples`` at ``rate`` a second.

    Raises ValueError when there are no samples.
    """
    total = len(samples)
    if total == 0:
        raise ValueError("no samples to measure")
    duration_s = total / rate
    block = BLOCK_S * rate

    starts = list(range(0, total, block))
    if len(starts) > 1 and total - starts[-1] < MIN_TAIL_S * rate:
        starts.pop()                         # the short tail joins the block before it
    ends = starts[1:] + [total]

    spans: list[tuple[float, float]] = []
    for start, end in zip(starts, ends):
        if not _is_silent(samples[start:end]):
            continue
        start_s, end_s = start / rate, min(end / rate, duration_s)
        if spans and spans[-1][1] == start_s:
            spans[-1] = (spans[-1][0], end_s)
        else:
            spans.append((start_s, end_s))

    silent_s = min(duration_s, sum(end_s - start_s for start_s, end_s in spans))
    return ClipSound(duration_s=duration_s, silent_s=silent_s, spans=tuple(spans))
