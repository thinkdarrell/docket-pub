"""Tests for Stage 0b procedural regex (``is_procedural``) and the
sibling withdrawal classifier (``is_withdrawn_or_deferred``)."""

from __future__ import annotations

import pytest

from docket.ai.wave0 import is_procedural, is_withdrawn_or_deferred


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
        # Withdrawn-family items are NOT procedural (own category — see
        # is_withdrawn_or_deferred). Procedural classifier must not
        # claim them, otherwise they'd land in procedural_skipped and
        # pollute that queue.
        'P(ph) ITEM 1. WITHDRAWN An Ordinance "TO AMEND THE ZONING DISTRICT MAP"',
        "CONSENT ITEM 11. WITHDRAWN PER O.C.A. A Resolution rescinding ...",
        "P ITEM 5. DEFERRED to next meeting An Ordinance authorizing",
        "P ITEM 12. POSTPONED A Resolution authorizing the Mayor to",
    ])
    def test_substantive_titles_dont_match(self, title: str):
        assert not is_procedural(title), f"Should NOT match: {title!r}"

    def test_empty_title(self):
        assert not is_procedural("")
        assert not is_procedural(None)


class TestIsWithdrawnOrDeferred:
    @pytest.mark.parametrize("title", [
        # Birmingham agenda shape: <prefix> ITEM <n>. <marker>
        'P(ph) ITEM 1. WITHDRAWN An Ordinance "TO AMEND THE ZONING DISTRICT MAP"',
        "CONSENT ITEM 11. WITHDRAWN PER O.C.A. A Resolution rescinding ...",
        "P ITEM 5. DEFERRED to next meeting An Ordinance authorizing",
        "P ITEM 12. POSTPONED A Resolution authorizing the Mayor to",
        # Case insensitive
        "P(ph) ITEM 1. withdrawn an ordinance",
        # No prefix at all, just ITEM N.
        "ITEM 7. WITHDRAWN A Resolution to do something",
    ])
    def test_withdrawn_titles_match(self, title: str):
        assert is_withdrawn_or_deferred(title), f"Should match: {title!r}"

    @pytest.mark.parametrize("title", [
        # True procedural items must NOT be claimed by this classifier.
        "Roll Call",
        "Pledge of Allegiance",
        # False-positive guards: substantive items where the marker
        # word appears in the body, not as an agenda-status marker.
        "P ITEM 5. A Resolution authorizing X\nrescinding and withdrawing prior agreement",
        "P ITEM 7. An Ordinance regarding deferred maintenance\nat municipal buildings",
        # Plain substantive titles
        "Award of HVAC contract for $87,500",
    ])
    def test_substantive_titles_dont_match(self, title: str):
        assert not is_withdrawn_or_deferred(title), f"Should NOT match: {title!r}"

    def test_empty_title(self):
        assert not is_withdrawn_or_deferred("")
        assert not is_withdrawn_or_deferred(None)
