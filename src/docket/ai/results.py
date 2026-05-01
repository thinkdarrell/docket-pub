"""Pydantic models for validated AI output."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


Confidence = Literal["high", "medium", "low"]
MeetingPhase = Literal["provisional", "adopted"]


class ItemAIResult(BaseModel):
    """Structured output for one agenda-item AI call."""

    # NOTE: rationales are listed BEFORE scores so the model produces them first
    # (rationales-first prompting / chain-of-thought grounding).
    is_substantive: bool
    significance_rationale: str = Field(min_length=1, max_length=600)
    significance_score: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    consent_placement_rationale: str = Field(min_length=1, max_length=600)
    consent_placement_score: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    summary: str = Field(max_length=400)
    confidence: Confidence

    @model_validator(mode="after")
    def _scores_match_substantive(self) -> "ItemAIResult":
        if self.is_substantive:
            if self.significance_score is None or self.consent_placement_score is None:
                raise ValueError("is_substantive=True requires non-null scores")
            if not self.summary.strip():
                raise ValueError("is_substantive=True requires a non-empty summary")
        else:
            if self.significance_score is not None or self.consent_placement_score is not None:
                raise ValueError("is_substantive=False requires both scores to be null")
        return self


class MeetingAIResult(BaseModel):
    """Structured output for one meeting executive-summary AI call."""

    is_substantive: bool
    substantive_item_count: int = Field(ge=0)
    executive_summary: str = Field(max_length=800)
    phase: MeetingPhase
    confidence: Confidence

    @model_validator(mode="after")
    def _summary_required_when_substantive(self) -> "MeetingAIResult":
        if self.is_substantive and not self.executive_summary.strip():
            raise ValueError("is_substantive=True requires a non-empty executive_summary")
        return self
