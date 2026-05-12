"""Policy badge matcher — hybrid LLM + deterministic.

Spec: docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md §5.3, §5.6.
"""
from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)


def deterministic_policy_match(item, facts, rewrite, hints: dict) -> tuple[bool, dict[str, Any]]:
    """Returns (matched, metadata) — metadata records WHICH trigger fired.
    Returns (False, {}) when no match. Metadata is stored in
    agenda_item_badges.matching_metadata for admin debugging.

    Note: significance gating is RENDER-time, not matcher-time (revised
    decision #61). The matcher always writes the badge row when the
    item matches. The gate lives in the SERVICE LAYER.
    """

    # Hard guard — categorical exclusions (decision #63)
    if facts.action_type in hints.get('excluded_action_types', []):
        return (False, {})

    text = f"{item.title or ''} {item.description or ''}".lower()

    # Excluded phrases guard (spec §5.6)
    for excl in hints.get('excluded_phrases', []):
        if excl.lower() in text:
            return (False, {})

    # Keyword match — supports plain strings (escaped) and {pattern, is_regex}
    matched_keywords: list[str] = []
    for entry in hints.get('keywords', []):
        if isinstance(entry, dict) and entry.get('is_regex'):
            pattern = entry['pattern']                       # raw regex (decision #60)
            display = entry.get('label', pattern)
        else:
            kw = entry if isinstance(entry, str) else entry.get('pattern', '')
            pattern = r'\b' + re.escape(kw.lower()) + r'\b'
            display = kw

        try:
            if re.search(pattern, text):
                matched_keywords.append(display)
        except re.error as e:
            log.warning("invalid regex in matcher_hints: %r (%s)", pattern, e)
            continue

    if matched_keywords:
        return (True, {'matched_keywords': matched_keywords})

    # Action-type match
    if facts.action_type in hints.get('action_types', []):
        return (True, {'matched_action_type': facts.action_type})

    # Legacy topic match
    if item.topic and item.topic in hints.get('topics', []):
        return (True, {'matched_topic': item.topic})

    return (False, {})


def decide_status_and_confidence(
    llm: bool, det: bool,
) -> tuple[str | None, float | None]:
    """Per-badge decision: status + confidence based on which sources fired.

    Refactor #2 (2026-05-11): LLM-only suggestions no longer auto-apply
    to public-facing surfaces. They land in the admin review queue
    (``status='flagged'``) so a human decides whether to promote them.
    Deterministic signals (keyword/action-type/topic match) are trusted
    enough to apply directly.

    Returns ``(None, None)`` when no row should be written.
    """
    if llm and det:
        return ('applied', 1.0)
    if det:
        return ('applied', 0.8)
    if llm:
        return ('flagged', 0.4)
    return (None, None)


def resolve_policy_badge_confidence(slug: str,
                                      llm_suggested: bool,
                                      deterministic_match: bool) -> float | None:
    """Returns confidence value, or None if neither source fired.

    Kept for the brief overlap while callers migrate to
    decide_status_and_confidence (Task A3). Routes through the new
    function so the contract stays in one place.
    """
    _, conf = decide_status_and_confidence(llm=llm_suggested, det=deterministic_match)
    return conf


def resolve_source(llm: bool, det: bool) -> str:
    if llm and det:
        return 'both'
    if llm:
        return 'llm'
    if det:
        return 'deterministic'
    raise ValueError("called for non-firing badge")


def compute_policy_badges(item, facts, rewrite, city_id: int):
    """Returns list of (slug, confidence, source, matching_metadata, status) tuples.

    Status logic (refactor #2):
      - 'applied'  — deterministic backing exists (citizen-visible)
      - 'flagged'  — LLM-only suggestion (admin review only)
    """
    from docket.services.badges import list_enabled_policy_badges

    enabled = list_enabled_policy_badges(city_id)
    out = []

    suggested = set(rewrite.suggested_badge_slugs or [])
    # Filter LLM suggestions to enabled-only (drop hallucinated disabled badges)
    suggested &= {b.slug for b in enabled}

    for badge in enabled:
        llm = badge.slug in suggested
        det, det_metadata = deterministic_policy_match(
            item, facts, rewrite, badge.matcher_hints
        )
        status, conf = decide_status_and_confidence(llm=llm, det=det)
        if status is None:
            continue

        if llm and det:
            metadata = {'both': True, **det_metadata}
        elif llm:
            metadata = {'llm_only': True}
        else:
            metadata = det_metadata

        out.append((badge.slug, conf, resolve_source(llm, det), metadata, status))

    return out
