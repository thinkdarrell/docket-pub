"""Tests for Stage 0b procedural regex (`is_procedural`)."""

from __future__ import annotations

import pytest

from docket.ai.wave0 import is_procedural


class TestIsProcedural:
    @pytest.mark.parametrize("title", [
        "Roll Call",
        "Pledge of Allegiance",
        "Invocation",
        "Moment of Silence",
        "Motion to Adjourn",
        "Adjournment",
        "Recess",
        "Approval of Minutes from May 1, 2026",
        "Approval of prior minutes",
        "Reading of the Minutes",
        "Minutes Not Yet Ready",
        "Minutes not received",
        "Public Comment Period",
        "Call to Public Comments",
        "Opening of Public Comments",
        "Executive Session",
        "Vouchers for Payment",
        "Bills for Payment",
        "Payroll for Payment",
        "Approval of Claims",
        "Recognition of Visitors",
        "Recognition of Guests",
        "Awards and Presentations",
        "Awards and Presentation",  # singular
        "Reading of Communications",
        "Reading of Petitions",
    ])
    def test_procedural_titles_match(self, title: str):
        assert is_procedural(title), f"Should match: {title!r}"

    @pytest.mark.parametrize("title", [
        "Award of HVAC contract for $87,500",
        "Settlement of Smith vs. City",
        "Approval of professional services agreement",
        "Resolution authorizing emergency repair",
        "Annual report on police staffing",
        "Award of liquor license for 234 Elm St",
        # Pattern #10 false-positive guards: substantive items mentioning minutes
        "Approval of meeting minutes available online",
        "Resolution to make minutes available for download",
    ])
    def test_substantive_titles_dont_match(self, title: str):
        assert not is_procedural(title), f"Should NOT match: {title!r}"

    def test_empty_title(self):
        assert not is_procedural("")
        assert not is_procedural(None)
