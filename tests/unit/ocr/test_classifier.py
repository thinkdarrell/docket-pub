"""Tests for docket.analysis.ocr.classifier.is_vote_frame.

The classifier is a four-signal histogram check: the frame must be mostly
black AND contain saturated green, red, and blue pixel clusters (the three
count boxes that are always on-screen during a Birmingham vote, regardless
of the tally). Missing any one of the four signals rejects the frame.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from docket.analysis.ocr.classifier import is_vote_frame

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "vote_frames"


# --- Real-frame positives --------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    [
        "voting_in_progress_williams_absent.png",
        "motion_passes_full_council.png",
        "motion_passes_oquinn_absent.png",
    ],
)
def test_sample_vote_frames_are_classified_as_votes(filename: str) -> None:
    frame = cv2.imread(str(FIXTURES / filename))
    assert frame is not None, f"fixture {filename} failed to load"
    assert is_vote_frame(frame) is True


# --- Synthetic negatives ---------------------------------------------------


def test_all_black_frame_rejected_without_color_clusters() -> None:
    """A pure black frame has no color clusters → not a vote frame."""
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    assert is_vote_frame(frame) is False


def test_all_white_frame_rejected() -> None:
    frame = np.full((720, 1280, 3), 255, dtype=np.uint8)
    assert is_vote_frame(frame) is False


def test_chambers_fill_frame_rejected() -> None:
    """A mid-gray / brown fill (stand-in for chambers footage) is rejected."""
    frame = np.full((720, 1280, 3), (60, 80, 110), dtype=np.uint8)  # muted brown
    assert is_vote_frame(frame) is False


def _black_frame_with_boxes(colors: list[tuple[int, int, int]]) -> np.ndarray:
    """Build an otherwise-black 720p frame with 80x80 BGR boxes along the top band."""
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    for i, bgr in enumerate(colors):
        x = 200 + i * 200
        frame[220:300, x : x + 80, :] = bgr
    return frame


def test_black_frame_missing_blue_cluster_rejected() -> None:
    """Only green + red clusters present → not a vote frame (AND-of-three)."""
    green = (0, 200, 0)
    red = (0, 0, 200)
    frame = _black_frame_with_boxes([green, red])
    assert is_vote_frame(frame) is False


def test_black_frame_missing_red_cluster_rejected() -> None:
    green = (0, 200, 0)
    blue = (200, 0, 0)
    frame = _black_frame_with_boxes([green, blue])
    assert is_vote_frame(frame) is False


def test_black_frame_missing_green_cluster_rejected() -> None:
    red = (0, 0, 200)
    blue = (200, 0, 0)
    frame = _black_frame_with_boxes([red, blue])
    assert is_vote_frame(frame) is False


def test_black_frame_with_all_three_clusters_accepted() -> None:
    """AND-of-four satisfied → vote frame, even synthetic."""
    green = (0, 200, 0)
    red = (0, 0, 200)
    blue = (200, 0, 0)
    frame = _black_frame_with_boxes([green, red, blue])
    assert is_vote_frame(frame) is True


def test_single_stray_colored_pixel_does_not_satisfy_cluster() -> None:
    """A lone saturated pixel per color is below the minimum pixel-count gate."""
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    frame[100, 100] = (0, 200, 0)  # one green pixel
    frame[100, 200] = (0, 0, 200)  # one red pixel
    frame[100, 300] = (200, 0, 0)  # one blue pixel
    assert is_vote_frame(frame) is False
