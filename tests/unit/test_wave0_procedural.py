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
        # Issue #34: colon-prefix variants where a name or date follows
        "INVOCATION: Minister Jeanetta Perdue, New Life Church of God",
        "PLEDGE OF ALLEGIANCE: Council Pro-Tempore LaTonya A. Tate",
        "MINUTES NOT READY:  February 3, 2026 – May 5, 2026",
        # Issue #34: bare BHM section headers
        "COMMUNICATIONS FROM THE MAYOR",
        "COMMUNICATIONS FROM THE COUNCIL",
        "PRESENTATIONS",
        "PRESENTATION",  # singular
        "OLD AND NEW BUSINESS",
        "OLD BUSINESS",
        "NEW BUSINESS",
        "REQUEST FROM THE PUBLIC",
        "REQUESTS FROM THE PUBLIC",
        "CONSIDERATION OF ORDINANCES AND RESOLUTIONS FOR FINAL PASSAGE",
        "CONSIDERATION OF ORDINANCES",
        "CONSIDERATION OF RESOLUTIONS",
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
        # Withdrawn-family titles (WITHDRAWN/DEFERRED/POSTPONED) are
        # routed by ``is_withdrawn_or_deferred`` BEFORE the procedural
        # classifier runs — see ``wave0.run_wave_0``. Their positive
        # coverage lives in ``TestIsWithdrawnOrDeferred`` below.
        assert not is_procedural(title), f"Should NOT match: {title!r}"

    def test_empty_title(self):
        assert not is_procedural("")
        assert not is_procedural(None)


class TestIsWithdrawnOrDeferred:
    @pytest.mark.parametrize("title", [
        # Shape A: <prefix> ITEM <n>. <marker>
        'P(ph) ITEM 1. WITHDRAWN An Ordinance "TO AMEND THE ZONING DISTRICT MAP"',
        "CONSENT ITEM 11. WITHDRAWN PER O.C.A. A Resolution rescinding ...",
        "P ITEM 5. DEFERRED to next meeting An Ordinance authorizing",
        "P ITEM 12. POSTPONED A Resolution authorizing the Mayor to",
        # Case insensitive
        "P(ph) ITEM 1. withdrawn an ordinance",
        # No prefix at all, just ITEM N.
        "ITEM 7. WITHDRAWN A Resolution to do something",
        # Shape B: <marker> <prefix> ITEM <n>. — real Birmingham prod shapes
        "WITHDRAWN ITEM 19. A Resolution approving the agreement with The Norwood Resource Center",
        "WITHDRAWN CONSENT ITEM 22. A Resolution (1) finding that the request by ...",
        "WITHDRAWN CONSENT               ITEM 62. A Resolution determining that the building",
        "WITHDRAWN ADDENDUM ITEM 76. A Resolution determining that the retreat ...",
        "WITHDRAWN CONSENT(ph)   ITEM 5. A Resolution revoking the Certificates",
        "WITHDRAWN P             ITEM 6. An Ordinance repealing Section 5",
        # Shape B with body wrapped to next line after "ITEM N."
        "WITHDRAWN ITEM 8.\r\nA Resolution authorizing the Mayor",
        # Shape B with DEFERRED / POSTPONED markers (synthetic but follows the same form)
        "DEFERRED ITEM 4. A Resolution authorizing the Mayor to execute",
        "POSTPONED CONSENT ITEM 9. A Resolution determining ...",
        # Case insensitive marker-first
        "withdrawn item 7. a resolution to do something",
        # Shape (a): parenthesized marker after item number — real Birmingham shape
        "ITEM 5. (WITHDRAWN) A Resolution authorizing the Mayor",
        "CONSENT ITEM 22. (WITHDRAWN) A Resolution determining",
        "P(ph) ITEM 14. (DEFERRED) An Ordinance amending Chapter 5",
        "ITEM 9. ( WITHDRAWN ) A Resolution with extra spaces in parens",
        "item 11. (postponed) a resolution lowercase",
        # Shape (b): "REQUESTED TO BE WITHDRAWN" phrase between item
        # number and marker — Birmingham administrative shape.
        "(ph) ITEM 12. REQUESTED TO BE WITHDRAWN An Ordinance amending",
        "ITEM 5. REQUESTED TO BE DEFERRED A Resolution authorizing",
        "CONSENT ITEM 22. REQUESTED TO BE POSTPONED A Resolution determining",
        "item 9. requested to be withdrawn a resolution lowercase",
        # Shape (c): marker sandwiched between prefix and item number —
        # Birmingham agenda exports occasionally put the prefix before
        # the marker rather than after it.
        "CONSENT(ph) WITHDRAWN ITEM 8. A Resolution authorizing",
        "P(ph) DEFERRED ITEM 14. An Ordinance amending Chapter 5",
        "CONSENT POSTPONED ITEM 22. A Resolution determining",
        "p(ph) withdrawn item 9. a resolution lowercase",
        # Shape (d): dash (not whitespace) between item number and marker.
        # Birmingham exports occasionally write "ITEM 22.- WITHDRAWN".
        "CONSENT(ph) ITEM 22.- WITHDRAWN A Resolution determining",
        "P(ph) ITEM 14.-DEFERRED An Ordinance amending Chapter 5",
        "ITEM 5. - POSTPONED A Resolution authorizing the Mayor",
        # Unicode en-dash and em-dash variants
        "ITEM 7.– WITHDRAWN A Resolution rescinding the certificate",
        "ITEM 9.— DEFERRED A Resolution authorizing",
        "item 11.- postponed a resolution lowercase",
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
        # Marker-first guard: previously-deferred history reference is NOT a
        # marker-first withdrawal. The marker word appears in the body, not
        # at the start, and the title shape begins with "ITEM N.".
        "ITEM 29. A Resolution amending The World Games 2021 Agreement.  (Deferred from 12/11/18 to 12/18/18)",
        # Marker-first guard: starts with marker word but has no "ITEM N."
        # structure — ambiguous, so we conservatively decline.
        "WITHDRAWN MOTION TO RECONSIDER — pending further notice",
        # Shape (a) guard: parenthesized text after an item number that
        # ISN'T the marker word stays substantive.
        "ITEM 5. (UPDATED) A Resolution authorizing the Mayor",
        "ITEM 8. (revised) A Resolution awarding the contract",
    ])
    def test_substantive_titles_dont_match(self, title: str):
        assert not is_withdrawn_or_deferred(title), f"Should NOT match: {title!r}"

    def test_empty_title(self):
        assert not is_withdrawn_or_deferred("")
        assert not is_withdrawn_or_deferred(None)
