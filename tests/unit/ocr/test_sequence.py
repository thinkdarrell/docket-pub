"""Tests for muni.analysis.vote_sequence — coarse-hit grouping and refine.

The sequence module owns two pure-logic helpers:

- ``group_hits`` turns a sparse list of coarse-pass timestamps into
  contiguous ``(start, end)`` spans using a gap tolerance.
- ``sequences_from_frames`` walks a ``(ts, frame)`` iterator, groups
  contiguous ``is_vote_frame`` runs, and returns ``VoteSequence`` objects
  holding every frame inside the run.

Both are tested with synthesized data so the tests run without any
OCR or video infrastructure.
"""

from __future__ import annotations

import numpy as np

from docket.analysis.ocr import sequence as vote_sequence
from docket.analysis.ocr.sequence import VoteSequence, group_hits, sequences_from_frames


def _black():
    return np.zeros((100, 1280, 3), dtype=np.uint8)


def _white():
    return np.full((100, 1280, 3), 255, dtype=np.uint8)


def _patch_classifier(monkeypatch) -> None:
    monkeypatch.setattr(
        vote_sequence,
        "is_vote_frame",
        lambda frame: bool(np.all(frame == 0)),
    )


# --- group_hits ------------------------------------------------------------


def test_group_hits_empty() -> None:
    assert group_hits([], max_gap=5.0) == []


def test_group_hits_single() -> None:
    assert group_hits([10.0], max_gap=5.0) == [(10.0, 10.0)]


def test_group_hits_two_within_gap() -> None:
    assert group_hits([10.0, 12.0], max_gap=5.0) == [(10.0, 12.0)]


def test_group_hits_two_beyond_gap() -> None:
    assert group_hits([10.0, 100.0], max_gap=5.0) == [(10.0, 10.0), (100.0, 100.0)]


def test_group_hits_mixed_clusters() -> None:
    hits = [5.0, 6.0, 7.0, 50.0, 51.0, 120.0]
    assert group_hits(hits, max_gap=3.0) == [(5.0, 7.0), (50.0, 51.0), (120.0, 120.0)]


def test_group_hits_unsorted_input_is_sorted_first() -> None:
    assert group_hits([7.0, 5.0, 6.0], max_gap=2.0) == [(5.0, 7.0)]


# --- sequences_from_frames -------------------------------------------------


def test_no_vote_frames_yields_no_sequences(monkeypatch) -> None:
    _patch_classifier(monkeypatch)
    frames = [(0.0, _white()), (1.0, _white()), (2.0, _white())]
    assert sequences_from_frames(frames) == []


def test_single_contiguous_run(monkeypatch) -> None:
    _patch_classifier(monkeypatch)
    frames = [
        (0.0, _white()),
        (1.0, _black()),
        (2.0, _black()),
        (3.0, _black()),
        (4.0, _white()),
    ]
    seqs = sequences_from_frames(frames)
    assert len(seqs) == 1
    assert seqs[0].start == 1.0
    assert seqs[0].end == 3.0
    # All three vote frames are captured, in order, with their timestamps.
    assert [ts for ts, _ in seqs[0].frames] == [1.0, 2.0, 3.0]


def test_two_sequences_with_gap(monkeypatch) -> None:
    _patch_classifier(monkeypatch)
    frames = [
        (0.0, _black()),
        (1.0, _black()),
        (2.0, _white()),
        (3.0, _white()),
        (4.0, _black()),
        (5.0, _black()),
        (6.0, _black()),
    ]
    seqs = sequences_from_frames(frames)
    assert len(seqs) == 2
    assert (seqs[0].start, seqs[0].end) == (0.0, 1.0)
    assert (seqs[1].start, seqs[1].end) == (4.0, 6.0)


def test_trailing_run_is_emitted(monkeypatch) -> None:
    """A run that never ends (iterator stops inside it) still counts."""
    _patch_classifier(monkeypatch)
    frames = [
        (0.0, _white()),
        (1.0, _black()),
        (2.0, _black()),
    ]
    seqs = sequences_from_frames(frames)
    assert len(seqs) == 1
    assert (seqs[0].start, seqs[0].end) == (1.0, 2.0)
    assert len(seqs[0].frames) == 2


def test_vote_sequence_is_frozen_dataclass() -> None:
    """VoteSequence is immutable so it can be passed between pipeline stages safely."""
    import dataclasses

    import pytest

    seq = VoteSequence(start=1.0, end=2.0, frames=())
    with pytest.raises(dataclasses.FrozenInstanceError):
        seq.start = 99.0  # type: ignore[misc]
