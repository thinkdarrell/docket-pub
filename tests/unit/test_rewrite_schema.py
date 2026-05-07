"""Tests for Stage 2 ItemRewrite schema with procedural_consistency validator."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from docket.ai.rewrite_schema import ItemRewrite


def base_substantive():
    return dict(
        is_substantive=True,
        headline="Council awards $4.2M HVAC contract to Acme",
        why_it_matters="Higher utility reliability for residents in Wards 4-7 starting July 2026.",
        significance_rationale="Major capital expenditure with long-term operational impact.",
        significance_score=7,
        consent_placement_rationale="High-dollar contract should not be on consent.",
        consent_placement_score=2,
        suggested_badge_slugs=[],
        confidence='high',
    )


class TestItemRewriteSubstantive:
    def test_valid_substantive(self):
        m = ItemRewrite(**base_substantive())
        assert m.is_substantive is True

    def test_headline_too_long_rejected(self):
        d = base_substantive()
        d['headline'] = "x" * 61
        with pytest.raises(ValidationError):
            ItemRewrite(**d)

    def test_why_it_matters_too_long_rejected(self):
        d = base_substantive()
        d['why_it_matters'] = "x" * 201
        with pytest.raises(ValidationError):
            ItemRewrite(**d)

    def test_headline_density_short_rejected(self):
        """Headline must be >= 10 chars (decision #87)."""
        d = base_substantive()
        d['headline'] = "Approved"  # 8 chars
        with pytest.raises(ValidationError):
            ItemRewrite(**d)

    def test_headline_whitespace_rejected(self):
        d = base_substantive()
        d['headline'] = "          "  # whitespace only
        with pytest.raises(ValidationError):
            ItemRewrite(**d)

    def test_why_it_matters_whitespace_rejected(self):
        d = base_substantive()
        d['why_it_matters'] = "   "
        with pytest.raises(ValidationError):
            ItemRewrite(**d)


class TestItemRewriteProcedural:
    def test_valid_procedural(self):
        m = ItemRewrite(
            is_substantive=False,
            headline=None,
            why_it_matters=None,
            significance_rationale="",
            significance_score=None,
            consent_placement_rationale="",
            consent_placement_score=None,
            suggested_badge_slugs=[],
            confidence='high',
        )
        assert m.is_substantive is False

    def test_procedural_with_populated_headline_rejected(self):
        with pytest.raises(ValidationError):
            ItemRewrite(
                is_substantive=False,
                headline="Should be null",
                why_it_matters=None,
                significance_rationale="",
                significance_score=None,
                consent_placement_rationale="",
                consent_placement_score=None,
                suggested_badge_slugs=[],
                confidence='medium',
            )
