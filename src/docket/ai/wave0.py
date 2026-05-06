"""Wave 0: non-LLM pre-pass that classifies every agenda item into
`procedural_skipped`, `data_quality_skipped`, or `pending`.

Two stages:
  - Stage 0a: data-quality gate (this module's `evaluate_data_quality`)
  - Stage 0b: relevance regex (this module's `is_procedural`)

Wave 0 is non-LLM (no API calls), idempotent over re-runs, and produces
the actual LLM-eligible item count that Wave 1+ budgets are based on.

Spec: docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md
sections 2.1, 2.2, 7.1, decision #78.
"""

from __future__ import annotations

import re
from typing import Literal, Protocol

from docket.ai._priority import _is_big_fish, _priority_from_title

DataQuality = Literal['ok', 'no_text_layer', 'no_agenda_text', 'empty', 'foreign_language']
DataDebtPriority = Literal['low', 'normal', 'high']


class _ItemView(Protocol):
    """Minimal duck-type — anything with these fields works."""
    title: str | None
    description: str | None
    raw_text: str | None
    source_type: str | None


def _is_likely_foreign_language(text: str) -> bool:
    """Cheap heuristic: high non-ASCII ratio suggests non-English content.
    Conservative — only fires on clearly non-Latin-script content."""
    if not text:
        return False
    non_ascii = sum(1 for c in text if ord(c) > 127)
    return non_ascii > len(text) * 0.4


def evaluate_data_quality(item: _ItemView) -> tuple[DataQuality, DataDebtPriority]:
    """Classify an item's data quality and priority.

    Big Fish Override (decision #86) checks first — high-impact titles
    bypass body-content gates so they're not buried in the OCR queue.
    """
    # Big Fish Override
    if _is_big_fish(item.title):
        return ('ok', 'high')

    # Empty / too-short title
    if not item.title or len(item.title.strip()) < 5:
        return ('empty', _priority_from_title(item.title))

    body = item.description or item.raw_text or ''
    body_clean = body.strip()

    # No body
    if not body_clean:
        return ('no_agenda_text', _priority_from_title(item.title))

    # Short body on a PDF source
    if len(body_clean) < 50 and (item.source_type == 'pdf'):
        return ('no_text_layer', _priority_from_title(item.title))

    # Body equals title (PDF parser fell back to title-only)
    if (body_clean.lower() == (item.title or '').lower().strip()
            and len(body_clean) < 200):
        return ('no_text_layer', _priority_from_title(item.title))

    if _is_likely_foreign_language(body_clean):
        return ('foreign_language', _priority_from_title(item.title))

    return ('ok', _priority_from_title(item.title))
