"""Tests for docket.analysis.ocr.header.read_header.

read_header crops the top band of a vote frame, runs Tesseract, and
fuzzy-matches against a small keyword set to decide whether the vote is
still in progress or has reached a terminal motion state.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import pytest

from docket.analysis.ocr.header import HeaderState, read_header

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "vote_frames"


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("voting_in_progress_williams_absent.png", HeaderState.VOTING_IN_PROGRESS),
        ("motion_passes_full_council.png", HeaderState.PASSED),
        ("motion_passes_oquinn_absent.png", HeaderState.PASSED),
    ],
)
def test_read_header_on_sample_frames(filename: str, expected: HeaderState) -> None:
    frame = cv2.imread(str(FIXTURES / filename))
    assert frame is not None, f"fixture {filename} failed to load"
    assert read_header(frame) == expected


def test_header_state_values_are_stable_strings() -> None:
    """Downstream code relies on these exact string values for persistence."""
    assert HeaderState.VOTING_IN_PROGRESS.value == "voting_in_progress"
    assert HeaderState.PASSED.value == "passed"
    assert HeaderState.FAILED.value == "failed"
    assert HeaderState.TABLED.value == "tabled"
    assert HeaderState.UNKNOWN.value == "unknown"


def test_is_terminal_helper() -> None:
    assert HeaderState.PASSED.is_terminal()
    assert HeaderState.FAILED.is_terminal()
    assert HeaderState.TABLED.is_terminal()
    assert not HeaderState.VOTING_IN_PROGRESS.is_terminal()
    assert not HeaderState.UNKNOWN.is_terminal()
