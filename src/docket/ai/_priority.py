"""Shared priority and Big Fish helpers for Stage 0a.

`_priority_from_title()` classifies an item into 'low' / 'normal' / 'high'
based on title keywords + dollar regex. Used to set
`agenda_items.data_debt_priority` and to drive sorting in admin queues
(/admin/data-debt, /admin/errors).

`_is_big_fish()` is the Big Fish Override (decision #86): items whose
title alone signals high impact bypass the data-quality gate even if
their body is missing or unreadable.

Spec: docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md
sections 2.1, decision #86.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Literal

from docket.enrichment.dollars import extract_dollars

DataDebtPriority = Literal['low', 'normal', 'high']


HIGH_KEYWORDS = (
    'settlement', 'sole source', 'sole-source', 'no-bid', 'no bid',
    'emergency', 'flock', 'surveillance', 'litigation',
    'department head', 'police chief', 'city attorney',
    'annexation', 'rezoning', 'variance', 'easement',
)

LOW_KEYWORDS = (
    'fleet', 'fuel', 'tires', 'maintenance', 'office supplies',
    'mileage', 'travel reimbursement', 'minutes',
    'travel authorization', 'membership dues', 'notary bond',
)


def _priority_from_title(title: str | None) -> DataDebtPriority:
    """Classify a title as 'low', 'normal', or 'high' priority."""
    if not title:
        return 'normal'
    t = title.lower()

    dollars = extract_dollars(title)
    if dollars is not None and dollars >= Decimal("1_000_000"):
        return 'high'
    if any(kw in t for kw in HIGH_KEYWORDS):
        return 'high'
    if any(kw in t for kw in LOW_KEYWORDS):
        return 'low'
    return 'normal'


def _is_big_fish(title: str | None) -> bool:
    """Big Fish Override (decision #86): title alone signals high impact.

    Returns True if the title contains a HIGH_KEYWORD or any dollar
    amount of $1M+. Used by Stage 0a to bypass `data_quality !=
    'ok'` flags so high-impact items are never buried by OCR failures.
    """
    if not title:
        return False
    t = title.lower()
    if any(kw in t for kw in HIGH_KEYWORDS):
        return True
    dollars = extract_dollars(title)
    if dollars is not None and dollars >= Decimal("1_000_000"):
        return True
    return False
