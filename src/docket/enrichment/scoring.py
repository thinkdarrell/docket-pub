"""Scoring stubs for agenda item analysis.

AI-powered scoring is deferred. These functions return None for now.
When AI features are enabled, replace these implementations with
LLM-based scoring that evaluates:
    - significance_score (0-10): How impactful is this agenda item?
    - consent_placement_score (0-10): Should this be on the consent agenda?
"""

from __future__ import annotations

from decimal import Decimal


def compute_significance_score(
    title: str,
    description: str | None,
    dollars: Decimal | None,
) -> float | None:
    """Score how significant an agenda item is (0-10). Returns None until AI enabled."""
    return None


def compute_consent_placement_score(
    title: str,
    description: str | None,
    is_consent: bool,
) -> float | None:
    """Score whether this item belongs on the consent agenda (0-10). Returns None until AI enabled."""
    return None
