"""Tests for ItemAIResult / MeetingAIResult Pydantic validation."""

import pytest
from pydantic import ValidationError

from docket.ai.results import ItemAIResult, MeetingAIResult


def test_item_substantive_valid():
    result = ItemAIResult(
        is_substantive=True,
        significance_rationale="Approves $4.2M road contract",
        significance_score=7.5,
        consent_placement_rationale="Routine procurement",
        consent_placement_score=2.0,
        summary="Approves $4.2M road resurfacing contract.",
        confidence="high",
    )
    assert result.significance_score == 7.5


def test_item_non_substantive_must_have_null_scores():
    """is_substantive=False with non-null scores → validation error."""
    with pytest.raises(ValidationError, match="is_substantive=False"):
        ItemAIResult(
            is_substantive=False,
            significance_rationale="Procedural",
            significance_score=3.0,
            consent_placement_rationale="N/A",
            consent_placement_score=None,
            summary="Motion to adjourn.",
            confidence="high",
        )


def test_item_substantive_must_have_non_null_scores():
    """is_substantive=True with null scores → validation error."""
    with pytest.raises(ValidationError, match="is_substantive=True"):
        ItemAIResult(
            is_substantive=True,
            significance_rationale="Approves $4.2M road contract",
            significance_score=None,
            consent_placement_rationale="Routine",
            consent_placement_score=2.0,
            summary="Approves $4.2M road resurfacing contract.",
            confidence="high",
        )


def test_score_range():
    with pytest.raises(ValidationError):
        ItemAIResult(
            is_substantive=True,
            significance_rationale="x",
            significance_score=11.0,
            consent_placement_rationale="x",
            consent_placement_score=0.0,
            summary="ok",
            confidence="high",
        )


def test_summary_length_cap_item():
    """Item summary > 400 chars rejected."""
    with pytest.raises(ValidationError):
        ItemAIResult(
            is_substantive=True,
            significance_rationale="x",
            significance_score=5.0,
            consent_placement_rationale="x",
            consent_placement_score=5.0,
            summary="x" * 401,
            confidence="high",
        )


def test_summary_empty_when_substantive():
    with pytest.raises(ValidationError, match="summary"):
        ItemAIResult(
            is_substantive=True,
            significance_rationale="x",
            significance_score=5.0,
            consent_placement_rationale="x",
            consent_placement_score=5.0,
            summary="",
            confidence="high",
        )


def test_confidence_enum():
    with pytest.raises(ValidationError):
        ItemAIResult(
            is_substantive=True,
            significance_rationale="x",
            significance_score=5.0,
            consent_placement_rationale="x",
            consent_placement_score=5.0,
            summary="ok",
            confidence="excellent",
        )


def test_meeting_summary_length_cap():
    """Meeting summary > 1500 chars rejected."""
    with pytest.raises(ValidationError):
        MeetingAIResult(
            is_substantive=True,
            substantive_item_count=5,
            executive_summary="x" * 1501,
            phase="provisional",
            confidence="high",
        )


def test_meeting_non_substantive():
    """Non-substantive meeting allows empty summary."""
    result = MeetingAIResult(
        is_substantive=False,
        substantive_item_count=0,
        executive_summary="",
        phase="provisional",
        confidence="high",
    )
    assert result.executive_summary == ""


def test_item_non_substantive_allows_empty_summary_and_rationales():
    """Procedural items: empty summary + empty rationales + null scores is the desired shape.
    Title is self-explanatory; a paraphrase would be noise. (Prompt v2 behavior.)"""
    result = ItemAIResult(
        is_substantive=False,
        significance_rationale="",
        significance_score=None,
        consent_placement_rationale="",
        consent_placement_score=None,
        summary="",
        confidence="high",
    )
    assert result.summary == ""
    assert result.significance_rationale == ""
    assert result.consent_placement_rationale == ""


def test_item_substantive_requires_non_empty_rationales():
    """Substantive items must have non-empty rationales (chain-of-thought grounding)."""
    with pytest.raises(ValidationError, match="non-empty rationales"):
        ItemAIResult(
            is_substantive=True,
            significance_rationale="",
            significance_score=5.0,
            consent_placement_rationale="",
            consent_placement_score=5.0,
            summary="ok",
            confidence="high",
        )
