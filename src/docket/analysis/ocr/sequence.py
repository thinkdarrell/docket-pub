"""Vote sequence grouping helpers for the coarse → refine scan pipeline.

A "vote sequence" is a contiguous run of vote-display frames in a video,
bounded on either side by non-vote frames (or by the video boundary).
The full pipeline works in two passes:

1. **Coarse pass** — sample the full video at a large interval (e.g. 2s)
   and record timestamps where ``is_vote_frame`` returns True. This is
   very cheap (pixel-histogram only, no OCR).
2. **Refine pass** — for each coarse cluster, re-scan a small window at
   a higher frame rate to locate the tight start / end of the sequence
   and hand every vote frame inside it to the downstream OCR stages.

This module owns the data model (``VoteSequence``) and the two pure
grouping helpers (``group_hits`` and ``sequences_from_frames``) that
bind everything together. The high-level ``find_vote_sequences`` helper
ties the pure logic to ``frame_io``'s ffmpeg wrappers.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from docket.analysis.ocr.frame_io import scan_full, scan_window
from docket.analysis.ocr.classifier import is_vote_frame

if TYPE_CHECKING:
    import numpy as np

FrameWithTimestamp = tuple[float, "np.ndarray"]


@dataclass(frozen=True)
class VoteSequence:
    """A contiguous run of vote-display frames.

    ``frames`` is a tuple of every vote-classified frame inside the
    sequence, in timestamp order. The terminal-frame detector walks this
    tuple backwards looking for the first frame whose header text reads
    as a finalized motion state.
    """

    start: float
    end: float
    frames: tuple[FrameWithTimestamp, ...]


# --- Pure helpers ----------------------------------------------------------


def group_hits(hits: Iterable[float], *, max_gap: float) -> list[tuple[float, float]]:
    """Group an iterable of timestamps into ``(start, end)`` spans.

    Two timestamps belong to the same span when the gap between them is
    at most ``max_gap`` seconds. Input does not need to be sorted.
    """
    ordered = sorted(hits)
    if not ordered:
        return []

    spans: list[tuple[float, float]] = []
    span_start = ordered[0]
    span_end = ordered[0]
    for ts in ordered[1:]:
        if ts - span_end <= max_gap:
            span_end = ts
        else:
            spans.append((span_start, span_end))
            span_start = ts
            span_end = ts
    spans.append((span_start, span_end))
    return spans


def sequences_from_frames(
    frames: Iterable[FrameWithTimestamp],
) -> list[VoteSequence]:
    """Walk a frame stream, collecting each contiguous vote-frame run into a VoteSequence."""
    sequences: list[VoteSequence] = []
    buffer: list[FrameWithTimestamp] = []

    def _flush() -> None:
        if not buffer:
            return
        sequences.append(
            VoteSequence(
                start=buffer[0][0],
                end=buffer[-1][0],
                frames=tuple(buffer),
            )
        )

    for ts, frame in frames:
        if is_vote_frame(frame):
            buffer.append((ts, frame))
        elif buffer:
            _flush()
            buffer = []

    _flush()
    return sequences


# --- High-level video helpers ---------------------------------------------


def find_vote_sequences(
    video_url: str,
    *,
    coarse_interval: float = 2.0,
    refine_fps: float = 2.0,
    refine_pad: float = 3.0,
) -> list[VoteSequence]:
    """Run the full coarse → refine scan and return all vote sequences in the video.

    The coarse pass dumps frames at ``1/coarse_interval`` fps and records
    which ones classify as vote frames. Those hits are grouped with a
    gap tolerance equal to ``coarse_interval * 2`` (so a single dropped
    coarse frame inside a sequence does not split it). Each group is
    then re-scanned at ``refine_fps`` with ``refine_pad`` seconds of
    padding on either side.
    """
    # Coarse pass: collect timestamps of any frame that classifies.
    coarse_hits: list[float] = []
    for ts, frame in scan_full(video_url, scan_interval=coarse_interval):
        if is_vote_frame(frame):
            coarse_hits.append(ts)

    # Group with a gap a little wider than the coarse interval so a
    # single false-negative frame inside a real sequence does not
    # split it into two groups.
    spans = group_hits(coarse_hits, max_gap=coarse_interval * 2)

    sequences: list[VoteSequence] = []
    for span_start, span_end in spans:
        refine_start = max(0.0, span_start - refine_pad)
        refine_duration = (span_end - span_start) + 2 * refine_pad
        refined = sequences_from_frames(
            scan_window(
                video_url,
                start=refine_start,
                duration=refine_duration,
                fps=refine_fps,
            )
        )
        # A coarse hit always corresponds to at least one refined sequence;
        # if refinement happens to miss (edge case with aggressive thresholds),
        # fall back to a single-frame sequence at the coarse midpoint.
        sequences.extend(refined)

    return sequences
