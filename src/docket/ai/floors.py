"""Stage 2.5 — Deterministic score floors and ceilings.

Runs after the Stage 2 LLM rewrite.  Applies rule-based significance floors
(only ever raises) and consent_placement ceilings (only ever lowers) based on
dollar amount, action type, procurement method, and subject-matter keywords.

Spec: docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md §3.4
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from docket.ai.extraction_schema import StructuredFacts
from docket.ai.rewrite_schema import ItemRewrite


# ---------------------------------------------------------------------------
# Output value object
# ---------------------------------------------------------------------------

@dataclass
class ScoreOverrides:
    original_ai_significance: int | None
    final_significance: int | None
    original_ai_consent: int | None
    final_consent: int | None
    triggers: list[dict]


# ---------------------------------------------------------------------------
# FloorTrigger definition
# ---------------------------------------------------------------------------

@dataclass
class FloorTrigger:
    name: str  # human-readable identifier, e.g. "red_tier_dollars"
    predicate: Callable[[Any, StructuredFacts, ItemRewrite], bool]
    score_field: Literal['significance', 'consent_placement']
    bound: int  # MIN for significance, MAX for consent_placement


# ---------------------------------------------------------------------------
# Significance floors
# ---------------------------------------------------------------------------

SIGNIFICANCE_FLOORS: list[FloorTrigger] = [
    # Dollar tiers
    FloorTrigger("red_plus_10m", lambda i, f, a: (i.dollars_amount or 0) >= 10_000_000,
                 'significance', 9),
    FloorTrigger("red_1m", lambda i, f, a: (i.dollars_amount or 0) >= 1_000_000,
                 'significance', 7),
    # Orange tier × triggers
    FloorTrigger("orange_sole_source",
                 lambda i, f, a: (i.dollars_amount or 0) >= 250_000
                              and f.procurement_method == 'sole_source',
                 'significance', 7),
    FloorTrigger("orange_settlement",
                 lambda i, f, a: (i.dollars_amount or 0) >= 250_000
                              and f.action_type == 'settlement',
                 'significance', 8),
    # Yellow tier × triggers
    FloorTrigger("yellow_sole_source",
                 lambda i, f, a: (i.dollars_amount or 0) >= 50_000
                              and f.procurement_method == 'sole_source',
                 'significance', 6),
    FloorTrigger("yellow_settlement",
                 lambda i, f, a: (i.dollars_amount or 0) >= 50_000
                              and f.action_type == 'settlement',
                 'significance', 6),
    # Action-type-only triggers
    FloorTrigger("any_settlement", lambda i, f, a: f.action_type == 'settlement',
                 'significance', 6),
    FloorTrigger("zoning_large",
                 lambda i, f, a: f.action_type == 'zoning'
                              and ((f.parcels_affected or 0) >= 5
                                   or (f.acres_affected or 0) >= 10),
                 'significance', 7),
    FloorTrigger("emergency_proc",
                 lambda i, f, a: f.action_type == 'emergency_procurement',
                 'significance', 7),
    FloorTrigger("appt_executive",
                 lambda i, f, a: f.action_type == 'appointment_executive',
                 'significance', 7),
    FloorTrigger("appt_board",
                 lambda i, f, a: f.action_type == 'appointment_board',
                 'significance', 5),
    FloorTrigger("tax_abatement_orange",
                 lambda i, f, a: f.action_type == 'tax_abatement'
                              and (i.dollars_amount or 0) >= 250_000,
                 'significance', 7),
]


# ---------------------------------------------------------------------------
# Subject-matter patterns and floors
# ---------------------------------------------------------------------------

SUBJECT_MATTER_PATTERNS = {
    'surveillance_alpr': re.compile(
        r'\b(flock|alpr|license\s+plate\s+reader|predictive\s+policing|'
        r'facial\s+recognit|surveillance\s+camera|gunshot\s+detect|'
        r'shotspotter|audit\s+log)\b',
        re.IGNORECASE,
    ),
    'police_oversight': re.compile(
        r'\b(citizen\s+review\s+board|use\s+of\s+force|police\s+misconduct|'
        r'complaint\s+review|police\s+(accountab|oversight)|internal\s+affairs)\b',
        re.IGNORECASE,
    ),
    'eminent_domain': re.compile(
        r'\b(eminent\s+domain|condemnation\s+for\s+public\s+use|'
        r'compulsory\s+acquisition|taking\s+by\s+the\s+city)\b',
        re.IGNORECASE,
    ),
}

SUBJECT_MATTER_FLOORS: list[FloorTrigger] = [
    FloorTrigger("surveillance_alpr_significance",
                 lambda i, f, a: (
                     SUBJECT_MATTER_PATTERNS['surveillance_alpr'].search(
                         f"{i.title or ''} {i.description or ''}"
                     ) is not None
                     or 'public_safety_tech_privacy' in (a.suggested_badge_slugs or [])
                 ),
                 'significance', 7),
    FloorTrigger("surveillance_alpr_consent",
                 lambda i, f, a: i.is_consent and (
                     SUBJECT_MATTER_PATTERNS['surveillance_alpr'].search(
                         f"{i.title or ''} {i.description or ''}"
                     ) is not None
                     or 'public_safety_tech_privacy' in (a.suggested_badge_slugs or [])
                 ),
                 'consent_placement', 2),

    FloorTrigger("police_oversight_significance",
                 lambda i, f, a: SUBJECT_MATTER_PATTERNS['police_oversight'].search(
                     f"{i.title or ''} {i.description or ''}"
                 ) is not None,
                 'significance', 8),
    FloorTrigger("police_oversight_consent",
                 lambda i, f, a: i.is_consent and SUBJECT_MATTER_PATTERNS['police_oversight'].search(
                     f"{i.title or ''} {i.description or ''}"
                 ) is not None,
                 'consent_placement', 2),

    FloorTrigger("eminent_domain_significance",
                 lambda i, f, a: SUBJECT_MATTER_PATTERNS['eminent_domain'].search(
                     f"{i.title or ''} {i.description or ''}"
                 ) is not None,
                 'significance', 8),
    FloorTrigger("eminent_domain_consent",
                 lambda i, f, a: i.is_consent and SUBJECT_MATTER_PATTERNS['eminent_domain'].search(
                     f"{i.title or ''} {i.description or ''}"
                 ) is not None,
                 'consent_placement', 2),
]


# ---------------------------------------------------------------------------
# Consent placement ceilings
# ---------------------------------------------------------------------------

CONSENT_PLACEMENT_CEILINGS: list[FloorTrigger] = [
    FloorTrigger("red_consent",
                 lambda i, f, a: (i.dollars_amount or 0) >= 1_000_000 and i.is_consent,
                 'consent_placement', 2),
    FloorTrigger("sole_source_consent",
                 lambda i, f, a: f.procurement_method == 'sole_source' and i.is_consent,
                 'consent_placement', 2),
    FloorTrigger("settlement_consent",
                 lambda i, f, a: f.action_type == 'settlement' and i.is_consent,
                 'consent_placement', 1),
    FloorTrigger("appt_executive_consent",
                 lambda i, f, a: f.action_type == 'appointment_executive' and i.is_consent,
                 'consent_placement', 2),
]


# ---------------------------------------------------------------------------
# Per-city override lookup
# ---------------------------------------------------------------------------

def _resolve_threshold(
    cur,
    city_id: int,
    trigger_name: str,
    default_threshold: int | None,
    default_bound: int,
) -> tuple[int | None, int]:
    """Per-city override lookup against city_score_floor_overrides.

    Empty table in v1 returns defaults unchanged.
    """
    cur.execute(
        """
        SELECT override_threshold_amount, override_min_score
          FROM city_score_floor_overrides
         WHERE city_id = %s AND trigger_name = %s
        """,
        (city_id, trigger_name),
    )
    row = cur.fetchone()
    if row is None:
        return default_threshold, default_bound
    override_threshold, override_min_score = row
    return (
        int(override_threshold) if override_threshold is not None else default_threshold,
        int(override_min_score) if override_min_score is not None else default_bound,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def apply_score_floors(
    cur,
    item: Any,
    facts: StructuredFacts,
    ai: ItemRewrite,
    city_id: int,
) -> ScoreOverrides:
    """Boost significance, lower consent_placement. Never the reverse.

    Returns an audit record (ScoreOverrides) for storage in score_overrides JSONB.
    Per-city overrides resolved via _resolve_threshold().

    Significance is monotonically non-decreasing: floors only raise the score.
    Consent placement is monotonically non-increasing: ceilings only lower the score.
    """
    fired: list[dict] = []

    # --- Significance: action-type, dollar-tier, AND subject-matter floors ---
    final_sig = ai.significance_score
    for trig in SIGNIFICANCE_FLOORS + SUBJECT_MATTER_FLOORS:
        if trig.score_field != 'significance':
            continue
        if trig.predicate(item, facts, ai):
            _, effective_bound = _resolve_threshold(
                cur, city_id, trig.name, None, trig.bound
            )
            if final_sig is None or effective_bound > final_sig:
                fired.append({
                    'trigger': trig.name,
                    'field': 'significance',
                    'pre': final_sig,
                    'post': effective_bound,
                })
                final_sig = effective_bound

    # --- Consent placement: ceilings AND subject-matter floors ---
    final_consent = ai.consent_placement_score
    for trig in CONSENT_PLACEMENT_CEILINGS + SUBJECT_MATTER_FLOORS:
        if trig.score_field != 'consent_placement':
            continue
        if trig.predicate(item, facts, ai):
            _, effective_bound = _resolve_threshold(
                cur, city_id, trig.name, None, trig.bound
            )
            if final_consent is None or effective_bound < final_consent:
                fired.append({
                    'trigger': trig.name,
                    'field': 'consent_placement',
                    'pre': final_consent,
                    'post': effective_bound,
                })
                final_consent = effective_bound

    return ScoreOverrides(
        original_ai_significance=ai.significance_score,
        final_significance=final_sig,
        original_ai_consent=ai.consent_placement_score,
        final_consent=final_consent,
        triggers=fired,
    )
