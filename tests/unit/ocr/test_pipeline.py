"""Tests for the Stage E cross-verification in docket.analysis.ocr.pipeline.

``_cross_verify`` is the pure function that decides whether a detected
vote needs human review. A terminal frame whose header does not read as
passed, failed, or tabled has no readable result, so it is flagged with
the reason ``header_not_terminal`` before any count check runs; the
stored result for that case is ``unknown``.
"""

from __future__ import annotations

import numpy as np

from docket.analysis.ocr.header import HeaderState
from docket.analysis.ocr.layout import CouncilLayout
from docket.analysis.ocr.pipeline import _analyze_terminal_frame, _cross_verify

NON_TERMINAL_COUNTS = {"yeas": 7, "nays": None, "abstentions": None}


def test_cross_verify_non_terminal_header_is_review() -> None:
    assert _cross_verify(HeaderState.VOTING_IN_PROGRESS, NON_TERMINAL_COUNTS, {}) == (
        True,
        "header_not_terminal",
    )


def test_cross_verify_unknown_header_is_review() -> None:
    assert _cross_verify(HeaderState.UNKNOWN, NON_TERMINAL_COUNTS, {}) == (
        True,
        "header_not_terminal",
    )


def test_cross_verify_terminal_header_with_agreeing_counts_is_clean() -> None:
    counts = {"yeas": 7, "nays": 1, "abstentions": 0}
    positions = {f"Member {i}": "yes" for i in range(7)}
    positions["Member 7"] = "no"
    assert _cross_verify(HeaderState.PASSED, counts, positions) == (False, None)


def test_analyze_terminal_frame_stores_unknown_with_review(monkeypatch) -> None:
    """The shape of the five production rows: a 7-yea frame whose second
    header read is not terminal must come out flagged, not clean."""
    monkeypatch.setattr(
        "docket.analysis.ocr.pipeline.read_header", lambda frame: HeaderState.UNKNOWN
    )
    monkeypatch.setattr(
        "docket.analysis.ocr.pipeline.extract_counts",
        lambda frame: dict(NON_TERMINAL_COUNTS),
    )
    monkeypatch.setattr("docket.analysis.ocr.pipeline.extract_vote_text", lambda frame: "")
    monkeypatch.setattr(
        "docket.analysis.ocr.pipeline.detect_member_rows", lambda frame, layout: {}
    )
    layout = CouncilLayout(city="birmingham", rows=(), max_members=0)

    vote = _analyze_terminal_frame(100.0, np.zeros((10, 10, 3), dtype=np.uint8), layout=layout)

    assert vote.vote_result == "unknown"
    assert vote.needs_review is True
    assert vote.review_reason == "header_not_terminal"
    assert vote.yeas == 7
    assert vote.nays is None
