"""Tests for Stage 1 Pydantic schemas (StructuredFacts, LocationDetail, NextSteps)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from docket.ai.extraction_schema import StructuredFacts, LocationDetail, NextSteps


class TestNextSteps:
    def test_all_fields_nullable(self):
        ns = NextSteps()
        assert ns.committee_referral is None
        assert ns.public_hearing_date is None
        assert ns.public_hearing_time is None
        assert ns.comment_period_end is None
        assert ns.implementation_date is None

    def test_populated_fields(self):
        ns = NextSteps(
            committee_referral="Public Safety Committee",
            public_hearing_date="June 5, 2026",
            public_hearing_time="6:00 PM",
        )
        assert ns.committee_referral == "Public Safety Committee"
        assert ns.public_hearing_date == "June 5, 2026"

    def test_date_fields_accept_natural_language_strings(self):
        """The tool input_schema declares date-shaped next_steps fields as strings,
        and source resolutions often use natural-language dates (e.g. 'May 5, 2026',
        'the 13th'). Pydantic must accept those verbatim rather than rejecting them
        — observed as the 2026-05-12 ai_items cron failure cluster (9 of 10 items)."""
        ns = NextSteps(
            public_hearing_date="May 5, 2026",
            comment_period_end="the 13th",
            implementation_date="next fiscal year",
        )
        assert ns.public_hearing_date == "May 5, 2026"
        assert ns.comment_period_end == "the 13th"
        assert ns.implementation_date == "next fiscal year"


class TestLocationDetail:
    def test_all_fields_nullable(self):
        loc = LocationDetail()
        assert loc.ward_or_district is None
        assert loc.parcel_id is None


class TestStructuredFacts:
    def test_minimal_valid(self):
        f = StructuredFacts(
            funding_source='unknown',
            counterparty=None,
            procurement_method='not_applicable',
            location=None,
            action_type='other',
            next_steps=NextSteps(),
            parcels_affected=None,
            acres_affected=None,
        )
        assert f.action_type == 'other'

    def test_full_substantive(self):
        f = StructuredFacts(
            funding_source='general_fund',
            counterparty='Flock Safety Inc.',
            procurement_method='sole_source',
            location=LocationDetail(ward_or_district='District 4'),
            action_type='contract_amendment',
            next_steps=NextSteps(),
            parcels_affected=None,
            acres_affected=None,
        )
        assert f.counterparty == 'Flock Safety Inc.'

    def test_funding_source_enum_strict(self):
        with pytest.raises(ValidationError):
            StructuredFacts(
                funding_source='FederalGrantPlusBond',  # not in enum
                counterparty=None,
                procurement_method='not_applicable',
                location=None,
                action_type='other',
                next_steps=NextSteps(),
                parcels_affected=None,
                acres_affected=None,
            )

    def test_action_type_includes_appointment_subtypes(self):
        for t in ['appointment_executive', 'appointment_board', 'appointment_advisory']:
            f = StructuredFacts(
                funding_source='unknown',
                counterparty=None,
                procurement_method='not_applicable',
                location=None,
                action_type=t,
                next_steps=NextSteps(),
                parcels_affected=None,
                acres_affected=None,
            )
            assert f.action_type == t

    def test_action_type_includes_v6_additions(self):
        for t in ['annexation', 'liquor_license', 'right_of_way', 'bid_rejection',
                   'weed_abatement', 'tax_abatement']:
            f = StructuredFacts(
                funding_source='unknown',
                counterparty=None,
                procurement_method='not_applicable',
                location=None,
                action_type=t,
                next_steps=NextSteps(),
                parcels_affected=None,
                acres_affected=None,
            )
            assert f.action_type == t

    def test_funding_source_includes_tif_and_capital_improvement(self):
        for fs in ['tif', 'capital_improvement']:
            f = StructuredFacts(
                funding_source=fs,
                counterparty=None,
                procurement_method='not_applicable',
                location=None,
                action_type='other',
                next_steps=NextSteps(),
                parcels_affected=None,
                acres_affected=None,
            )
            assert f.funding_source == fs

    def test_forbids_extra_keys(self):
        """Schema drift guard — unknown keys must raise (decision #94)."""
        with pytest.raises(ValidationError):
            StructuredFacts(
                funding_source='unknown',
                counterparty=None,
                procurement_method='not_applicable',
                location=None,
                action_type='other',
                next_steps=NextSteps(),
                parcels_affected=None,
                acres_affected=None,
                bond_rating='AAA',  # not in schema
            )

    def test_negative_parcels_rejected(self):
        """Hallucination guard — negative parcel/acres counts must raise."""
        with pytest.raises(ValidationError):
            StructuredFacts(
                funding_source='unknown',
                counterparty=None,
                procurement_method='not_applicable',
                location=None,
                action_type='other',
                next_steps=NextSteps(),
                parcels_affected=-5,
                acres_affected=None,
            )
        with pytest.raises(ValidationError):
            StructuredFacts(
                funding_source='unknown',
                counterparty=None,
                procurement_method='not_applicable',
                location=None,
                action_type='other',
                next_steps=NextSteps(),
                parcels_affected=None,
                acres_affected=-12.0,
            )
