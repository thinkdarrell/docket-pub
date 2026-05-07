"""Stage 1 Pydantic schemas — structured fact extraction output.

Spec: docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md
section 2.3, decisions #36-39, #86.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

FundingSource = Literal[
    'general_fund', 'arpa', 'esser', 'cares', 'state_grant',
    'federal_grant', 'bond', 'special_tax', 'private', 'sponsorship',
    'tif', 'capital_improvement',
    'mixed', 'unknown',
]

ProcurementMethod = Literal[
    'competitive', 'sole_source', 'no_bid', 'rfp',
    'emergency', 'unknown', 'not_applicable',
]

ActionType = Literal[
    'contract_award', 'contract_amendment', 'ordinance', 'resolution',
    'appointment_executive', 'appointment_board', 'appointment_advisory',
    'zoning', 'demolition',
    'weed_abatement', 'tax_abatement',
    'settlement', 'emergency_procurement',
    'appropriation', 'budget_amendment',
    'proclamation', 'public_hearing_set',
    'annexation', 'liquor_license', 'right_of_way', 'bid_rejection',
    'other',
]


class LocationDetail(BaseModel):
    ward_or_district: str | None = None
    neighborhood: str | None = None
    address: str | None = None
    parcel_id: str | None = None  # County tax-assessor PIN


class NextSteps(BaseModel):
    committee_referral: str | None = None
    public_hearing_date: date | None = None
    public_hearing_time: str | None = None  # e.g. "6:00 PM"
    comment_period_end: date | None = None
    implementation_date: date | None = None


class StructuredFacts(BaseModel):
    funding_source: FundingSource
    counterparty: str | None
    procurement_method: ProcurementMethod
    location: LocationDetail | None
    action_type: ActionType
    next_steps: NextSteps
    parcels_affected: int | None = Field(default=None, ge=0)
    acres_affected: float | None = Field(default=None, ge=0)

    model_config = {
        'extra': 'forbid',  # Reject unknown keys to catch schema drift early
    }
