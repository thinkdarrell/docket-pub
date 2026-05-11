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


def resolve_policy_badge_confidence(slug: str,
                                      llm_suggested: bool,
                                      deterministic_match: bool) -> float | None:
    """Returns confidence value, or None if neither source fired."""
    if llm_suggested and deterministic_match:
        return 1.0
    if llm_suggested or deterministic_match:
        return 0.6
    return None


def resolve_source(llm: bool, det: bool) -> str:
    if llm and det:
        return 'both'
    if llm:
        return 'llm'
    if det:
        return 'deterministic'
    raise ValueError("called for non-firing badge")


def compute_policy_badges(item, facts, rewrite, city_id: int):
    """Returns list of (slug, confidence, source, matching_metadata) tuples."""
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
        conf = resolve_policy_badge_confidence(badge.slug, llm, det)
        if conf is None:
            continue

        if llm and det:
            metadata = {'both': True, **det_metadata}
        elif llm:
            metadata = {'llm_only': True}
        else:
            metadata = det_metadata

        out.append((badge.slug, conf, resolve_source(llm, det), metadata))

    return out
