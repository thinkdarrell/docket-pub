"""Stage 2 ItemRewrite Pydantic schema with procedural_consistency validator.

Spec: section 3.3, decisions #5, #50, #87.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ItemRewrite(BaseModel):
    is_substantive: bool
    # Prompt v4 raised caps from 60→80 / 200→280 (2026-05-11). Dense
    # items (vendor + amount + purpose) frequently needed every char;
    # tight cap was forcing truncation on ~16% of items in the FINAL-3
    # verification cron. Cards have layout breathing room for these
    # lengths (max two-line headline / three-line why_it_matters).
    headline: str | None = Field(None, max_length=80)
    why_it_matters: str | None = Field(None, max_length=280)
    significance_rationale: str = Field("", max_length=1500)
    significance_score: float | None = Field(None, ge=0.0, le=10.0)
    consent_placement_rationale: str = Field("", max_length=1500)
    consent_placement_score: float | None = Field(None, ge=0.0, le=10.0)
    suggested_badge_slugs: list[str] = Field(default_factory=list)
    confidence: Literal['high', 'medium', 'low']

    @model_validator(mode='after')
    def procedural_consistency(self):
        if not self.is_substantive:
            assert self.headline is None, "procedural items must have null headline"
            assert self.why_it_matters is None, "procedural items must have null why_it_matters"
            assert self.significance_score is None
            assert self.consent_placement_score is None
            assert self.suggested_badge_slugs == []
        else:
            # Density validation (decision #87): headline must be >= 10 chars
            assert self.headline and len(self.headline.strip()) >= 10, \
                "substantive items must have a headline >= 10 chars"
            assert self.why_it_matters and len(self.why_it_matters.strip()) > 0, \
                "substantive items must have a non-empty why_it_matters"
            assert self.significance_score is not None
            assert self.consent_placement_score is not None
        return self
