"""Tests for docket.analysis.ocr.layout.detect_member_rows.

detect_member_rows OCRs the names band of a vote frame, locates the
colored indicator dots by saturation + chromatic-spread filtering, and
spatially associates each name with the nearest dot on the correct side.
Absent members simply don't appear in the returned dict — Birmingham's
vote screen only renders members who have cast a vote.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from docket.analysis.ocr.layout import CouncilLayout, LayoutRow, detect_member_rows

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "vote_frames"

# TODO(Task 11): Replace this inline layout construction with
# ``from docket.analysis.ocr.rosters import get_layout`` once Task 11
# introduces the runtime roster builder.  The values here match LAYOUT_2025
# from al-municipal-meetings (the 2025-10-28+ Birmingham council seating).
_LAYOUT_2025 = CouncilLayout(
    city="birmingham",
    rows=(
        LayoutRow(left="B. Gunn", right="H. Williams"),
        LayoutRow(left="D. OQuinn", right="C. Woods"),
        LayoutRow(left="S. Smith", right="L. Tate"),
        LayoutRow(left="C. Smitherman", right="W. Alexander"),
        LayoutRow(left="J. Vasa"),
    ),
    max_members=9,
)


def _load(name: str):
    frame = cv2.imread(str(FIXTURES / name))
    assert frame is not None, f"fixture {name} missing"
    return frame


def test_voting_in_progress_missing_williams() -> None:
    """8 members shown, H. Williams not yet voted → not in the dict at all."""
    frame = _load("voting_in_progress_williams_absent.png")
    result = detect_member_rows(frame, layout=_LAYOUT_2025)

    expected = {
        "B. Gunn": "yes",
        "D. OQuinn": "yes",
        "S. Smith": "yes",
        "C. Smitherman": "yes",
        "J. Vasa": "yes",
        "C. Woods": "yes",
        "L. Tate": "yes",
        "W. Alexander": "yes",
    }
    assert result == expected
    assert "H. Williams" not in result


def test_motion_passes_full_council() -> None:
    """Full 9-member council, all yes."""
    frame = _load("motion_passes_full_council.png")
    result = detect_member_rows(frame, layout=_LAYOUT_2025)

    expected = {
        "B. Gunn": "yes",
        "D. OQuinn": "yes",
        "S. Smith": "yes",
        "C. Smitherman": "yes",
        "J. Vasa": "yes",
        "H. Williams": "yes",
        "C. Woods": "yes",
        "L. Tate": "yes",
        "W. Alexander": "yes",
    }
    assert result == expected


def test_motion_passes_oquinn_absent_reflows() -> None:
    """D. OQuinn is absent — names in the left column reflow upward."""
    frame = _load("motion_passes_oquinn_absent.png")
    result = detect_member_rows(frame, layout=_LAYOUT_2025)

    expected = {
        "B. Gunn": "yes",
        "S. Smith": "yes",
        "C. Smitherman": "yes",
        "J. Vasa": "yes",
        "H. Williams": "yes",
        "C. Woods": "yes",
        "L. Tate": "yes",
        "W. Alexander": "yes",
    }
    assert result == expected
    assert "D. OQuinn" not in result


def test_empty_layout_returns_empty() -> None:
    """Defensive: non-birmingham frame or missing layout yields an empty dict."""
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    result = detect_member_rows(frame, layout=_LAYOUT_2025)
    assert result == {}
