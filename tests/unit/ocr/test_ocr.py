"""Tests for docket.analysis.ocr.ocr — count OCR and debug text extraction.

Public API:
- ``extract_counts(frame)`` returns ``{"yeas": int|None, "nays": int|None,
  "abstentions": int|None}`` from the three colored count boxes.
- ``extract_vote_text(frame)`` returns white-on-black frame text as a string
  (debug/logging only — not consumed by the pipeline).
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from docket.analysis.ocr.ocr import extract_counts, extract_vote_text

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "vote_frames"


# --- extract_counts: real-frame positives ----------------------------------


@pytest.mark.parametrize(
    "filename",
    [
        "motion_passes_full_council.png",
        "motion_passes_oquinn_absent.png",
    ],
)
def test_extract_counts_returns_dict_with_three_keys(filename: str) -> None:
    """extract_counts always returns a dict with yeas/nays/abstentions keys."""
    frame = cv2.imread(str(FIXTURES / filename))
    assert frame is not None, f"fixture {filename} failed to load"
    result = extract_counts(frame)
    assert set(result.keys()) == {"yeas", "nays", "abstentions"}


@pytest.mark.parametrize(
    "filename",
    [
        "motion_passes_full_council.png",
        "motion_passes_oquinn_absent.png",
    ],
)
def test_extract_counts_on_terminal_frames_returns_ints_or_none(filename: str) -> None:
    """Each value is either a non-negative int or None (never a silent zero for unreadable)."""
    frame = cv2.imread(str(FIXTURES / filename))
    assert frame is not None, f"fixture {filename} failed to load"
    result = extract_counts(frame)
    for key, value in result.items():
        assert value is None or isinstance(value, int), (
            f"{key} should be int|None, got {type(value)}"
        )
        if isinstance(value, int):
            assert 0 <= value <= 20, f"{key}={value} out of plausible council range"


def test_extract_counts_on_voting_in_progress_returns_dict() -> None:
    """Even a non-terminal frame returns the three-key dict (counts may be None)."""
    frame = cv2.imread(str(FIXTURES / "voting_in_progress_williams_absent.png"))
    assert frame is not None, "fixture failed to load"
    result = extract_counts(frame)
    assert set(result.keys()) == {"yeas", "nays", "abstentions"}


# --- extract_counts: synthetic edge cases ----------------------------------


def test_extract_counts_on_black_frame_returns_all_none() -> None:
    """A pure black frame has no colored boxes → all counts None."""
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    result = extract_counts(frame)
    assert result == {"yeas": None, "nays": None, "abstentions": None}


def test_extract_counts_on_white_frame_returns_all_none() -> None:
    """A white frame has no saturated color boxes → all counts None."""
    frame = np.full((720, 1280, 3), 255, dtype=np.uint8)
    result = extract_counts(frame)
    assert result == {"yeas": None, "nays": None, "abstentions": None}


def test_extract_counts_values_never_exceed_council_size() -> None:
    """Parsed digit is clamped to 0–20; anything outside returns None."""
    # Construct a frame with a green box in the count band containing a large number.
    # We can't reliably OCR synthetic digits, but we verify the return shape is safe.
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    # Place a bright green box in the count band (22-42% of height)
    y1, y2 = int(720 * 0.22), int(720 * 0.42)
    frame[y1:y2, 300:500] = (0, 220, 0)  # BGR green
    result = extract_counts(frame)
    # Each value must be int in [0,20] or None — never something larger
    for key, value in result.items():
        assert value is None or (isinstance(value, int) and 0 <= value <= 20), (
            f"{key}={value!r} is out of bounds"
        )


# --- extract_vote_text: smoke tests ----------------------------------------


@pytest.mark.parametrize(
    "filename",
    [
        "voting_in_progress_williams_absent.png",
        "motion_passes_full_council.png",
        "motion_passes_oquinn_absent.png",
    ],
)
def test_extract_vote_text_returns_string(filename: str) -> None:
    """extract_vote_text returns a str (possibly empty) for any valid frame."""
    frame = cv2.imread(str(FIXTURES / filename))
    assert frame is not None, f"fixture {filename} failed to load"
    result = extract_vote_text(frame)
    assert isinstance(result, str)


def test_extract_vote_text_on_black_frame_returns_string() -> None:
    """extract_vote_text never raises — returns str even on pathological input."""
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    result = extract_vote_text(frame)
    assert isinstance(result, str)
