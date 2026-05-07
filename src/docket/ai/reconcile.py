"""Stage 3 — Cross-stage reconciliation.

Catches high-confidence Stage 1 extractions being silently dropped by
Stage 2 procedural verdicts.  Default: auto-retry once with an override
instruction injected into the Stage 2 prompt, then escalate.

Spec: docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md §3.7
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from docket.ai.extraction_schema import StructuredFacts
from docket.ai.floors import SUBJECT_MATTER_PATTERNS
from docket.ai.rewrite_schema import ItemRewrite


@dataclass
class ReconciliationResult:
    action: Literal['accept', 'retry_stage2_with_override', 'mark_cross_stage_conflict']
    conflicts: list[str]
    override_instruction: str | None = None  # injected into Stage 2 retry prompt


def reconcile_stages(facts: StructuredFacts,
                      rewrite: ItemRewrite,
                      item: Any,
                      already_retried: bool = False) -> ReconciliationResult:
    """Catch high-confidence Stage 1 extractions being silently dropped by
    Stage 2 procedural verdicts. Default: auto-retry once, then escalate."""
    conflicts: list[str] = []

    # Stage 2 says procedural BUT Stage 1 found substance
    if not rewrite.is_substantive:
        if facts.counterparty:
            conflicts.append('stage1_has_counterparty_but_stage2_procedural')
        if facts.funding_source not in ('unknown', None):
            conflicts.append('stage1_has_funding_source_but_stage2_procedural')
        if (item.dollars_amount or 0) >= 50_000:  # Yellow tier or above
            conflicts.append('yellow_tier_dollars_but_stage2_procedural')
        if facts.action_type in ('settlement', 'tax_abatement', 'annexation',
                                   'emergency_procurement', 'liquor_license',
                                   'right_of_way', 'zoning',
                                   'appointment_executive', 'appointment_board'):
            conflicts.append(f'high_attention_action_type_but_stage2_procedural:{facts.action_type}')

        # Subject-matter regex check — surveillance/police/eminent-domain titles
        # should never silently fall through to procedural even when action_type
        # is generic (contract_award, ordinance, etc.)
        haystack = f"{item.title or ''} {item.description or ''}"
        for matter, pattern in SUBJECT_MATTER_PATTERNS.items():
            if pattern.search(haystack):
                conflicts.append(f'subject_matter_match_but_stage2_procedural:{matter}')
                break

    if not conflicts:
        return ReconciliationResult(action='accept', conflicts=[])

    if already_retried:
        # Second attempt also failed — escalate
        return ReconciliationResult(
            action='mark_cross_stage_conflict',
            conflicts=conflicts,
        )

    # First retry: re-prompt Stage 2 with explicit override instruction
    override = (
        "PREVIOUS ATTEMPT INCORRECTLY classified this as procedural despite "
        "Stage 1 extracting these substantive facts: "
        f"counterparty={facts.counterparty!r}, funding={facts.funding_source!r}, "
        f"action_type={facts.action_type!r}, dollars=${item.dollars_amount or 0:,}. "
        "If those facts are accurate, this item IS substantive. Re-classify "
        "and write a headline + why-it-matters."
    )
    return ReconciliationResult(
        action='retry_stage2_with_override',
        conflicts=conflicts,
        override_instruction=override,
    )
