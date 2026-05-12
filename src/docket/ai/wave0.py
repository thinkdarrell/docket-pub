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

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Iterable, Literal, Protocol

from docket.ai._priority import _is_big_fish, _priority_from_title
from docket.db import db

log = logging.getLogger(__name__)

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
    body_from_title_fallback = False

    # Body fallback to title for adapters (e.g., Granicus/Birmingham) that
    # write the full agenda body into `title` and leave `description` NULL.
    # A substantive title (>= 120 chars) is treated as the body when no other
    # body is available — the agenda text is there, just in the wrong column.
    if not body_clean and len(item.title.strip()) >= 120:
        body_clean = item.title.strip()
        body_from_title_fallback = True

    # No body
    if not body_clean:
        return ('no_agenda_text', _priority_from_title(item.title))

    # Short body on a PDF source
    if len(body_clean) < 50 and (item.source_type == 'pdf'):
        return ('no_text_layer', _priority_from_title(item.title))

    # Body equals title (PDF parser fell back to title-only).
    # Skip this check when we *intentionally* used title as body — that's
    # not a parser failure, it's an adapter quirk we already accommodated.
    if (not body_from_title_fallback
            and body_clean.lower() == (item.title or '').lower().strip()
            and len(body_clean) < 200):
        return ('no_text_layer', _priority_from_title(item.title))

    if _is_likely_foreign_language(body_clean):
        return ('foreign_language', _priority_from_title(item.title))

    return ('ok', _priority_from_title(item.title))


PROCEDURAL_TITLE_PATTERNS = (
    r'^\s*roll\s+call',
    r'^\s*(call\s+to|opening\s+of)\s+(public\s+)?comments?',
    r'^\s*pledge\s+of\s+allegiance',
    r'^\s*invocation',
    r'^\s*moment\s+of\s+silence',
    r'^\s*motion\s+to\s+adjourn',
    r'^\s*adjournment',
    r'^\s*recess',
    r'^\s*approval\s+of\s+(prior|previous|the)?\s*minutes',
    r'^\s*minutes\s+(not\s+)?(yet\s+)?(ready|available|received)\s*$',
    r'^\s*reading\s+of\s+(the\s+)?minutes',
    r'^\s*proclamations?\s*$',
    r'^\s*public\s+comment\s+period',
    r'^\s*executive\s+session',
    # Alabama council common patterns:
    r'^\s*(vouchers?|bills?|payroll)\s+for\s+payment',
    r'^\s*approval\s+of\s+claims',
    r'^\s*recognition\s+of\s+(visitors?|guests?)',
    r'^\s*awards?\s+and\s+presentations?',
    r'^\s*reading\s+of\s+(communications?|petitions?)',
)

# WITHDRAWN / DEFERRED / POSTPONED is a different category from
# procedural. The council was prepared to act on a SUBSTANTIVE item and
# then chose not to (withdraw / defer / postpone) — there's no action
# to score or summarize, but lumping these with Roll Call / Pledge of
# Allegiance under ``procedural_skipped`` muddies the admin review
# queue (which is dominated by true procedural rows). Migration 023
# added a ``'withdrawn'`` status to ``processing_status_enum`` so Wave
# 0 can route this family to its own bucket.
#
# Two Birmingham agenda shapes carry the withdrawn-family marker:
#   Shape A (marker-after):  <prefix> ITEM <n>. <marker>
#       e.g. "P(ph) ITEM 1. WITHDRAWN An Ordinance ..."
#   Shape B (marker-first):  <marker> <prefix> ITEM <n>. ...
#       e.g. "WITHDRAWN CONSENT ITEM 22. A Resolution ..."
# Both require an ``ITEM <n>.`` token so we don't match the same word
# deep inside an ordinance body (e.g. "An Ordinance regarding deferred
# maintenance") or a history reference like "(Deferred from 12/11/18
# to 12/18/18)". The prefix accepts letters, parens, periods, slashes,
# and whitespace — covering shapes like ``P(ph)``, ``CONSENT``,
# ``ADDENDUM``, ``P``, or none at all.
WITHDRAWN_TITLE_PATTERNS = (
    r'^[a-z()./\s]*\bitem\s+\d+\.?\s+\b(?:withdrawn|deferred|postponed)\b',
    r'^\s*\b(?:withdrawn|deferred|postponed)\b[a-z()./\s]*\bitem\s+\d+\b',
)

_compiled_patterns = [re.compile(p, re.IGNORECASE) for p in PROCEDURAL_TITLE_PATTERNS]
_compiled_withdrawn_patterns = [
    re.compile(p, re.IGNORECASE) for p in WITHDRAWN_TITLE_PATTERNS
]


def is_procedural(title: str | None) -> bool:
    """Stage 0b: title-only regex check for procedural items.

    Returns True if the title matches any of the known procedural
    patterns (roll call, pledge, vouchers for payment, etc.). The
    telemetry loop (decision #26) tracks items that pass this check
    but are later judged procedural by Stage 2 — admins expand the
    pattern list over time.

    WITHDRAWN/DEFERRED/POSTPONED items are deliberately NOT included
    here — they're a separate category routed to ``processing_status=
    'withdrawn'`` via :func:`is_withdrawn_or_deferred`.
    """
    if not title:
        return False
    for pattern in _compiled_patterns:
        if pattern.search(title):
            return True
    return False


def is_withdrawn_or_deferred(title: str | None) -> bool:
    """Stage 0b: title-only check for items withdrawn / deferred /
    postponed from the agenda.

    Distinct from :func:`is_procedural` because the council had a
    substantive item ready to act on and then chose not to. Routed to
    ``processing_status='withdrawn'`` so admin queues can review them
    separately from true procedural rows.
    """
    if not title:
        return False
    for pattern in _compiled_withdrawn_patterns:
        if pattern.search(title):
            return True
    return False


@dataclass
class Wave0Report:
    """Classification counts after a Wave 0 run."""
    counts: Counter[str] = field(default_factory=Counter)
    items_processed: int = 0


def run_wave_0(city_ids: Iterable[int]) -> Wave0Report:
    """Classify every unprocessed agenda item in the given cities.

    Per-item ordering inverts the spec's section numbering: Stage 0b
    (procedural regex) runs before Stage 0a (data-quality gate) because
    procedural items are content-free by construction — gating them on
    body presence would mis-classify "Roll Call" as `no_agenda_text`.
    Both gates still run; only the order changed.

    Sets `data_quality`, `data_debt_priority`, and `processing_status`
    for every item. No LLM calls. Idempotent — safe to re-run after
    refining patterns or thresholds.

    Decision #78. Spec section 7.1.
    """
    report = Wave0Report()
    city_id_list = list(city_ids)

    with db() as conn:
        with conn.cursor() as cur:
            # Take an advisory lock so a concurrent --run-once doesn't collide
            cur.execute("SELECT pg_try_advisory_lock(hashtext('docket.wave_0'))")
            if not cur.fetchone()[0]:
                log.warning("wave_0 already running, skipping")
                return report

            try:
                # agenda_items has no raw_text or source_type column; PDF source
                # is the dominant input shape, so we hard-code 'pdf' for the
                # data-quality gate's PDF-specific heuristics.
                cur.execute("""
                    SELECT ai.id, ai.title, ai.description
                    FROM agenda_items ai
                    JOIN meetings m ON m.id = ai.meeting_id
                    WHERE m.municipality_id = ANY(%s)
                      AND ai.ai_extraction_version IS NULL
                    ORDER BY m.meeting_date DESC NULLS LAST
                """, [city_id_list])

                rows = cur.fetchall()
                log.info(
                    "wave_0: classifying %d items across %d cities",
                    len(rows),
                    len(city_id_list),
                )

                # N+1 UPDATEs are intentional. Wave 0 is a daily cron;
                # latency isn't critical, and per-row UPDATEs keep the
                # routing logic readable. Revisit with UPDATE...FROM
                # (VALUES) only if batch sizes exceed ~100K.
                for row in rows:
                    item_id, title, description = row

                    if is_withdrawn_or_deferred(title):
                        # Substantive item the council removed from the
                        # agenda — no action to score or summarize.
                        # Distinct from procedural (decision: see
                        # is_withdrawn_or_deferred docstring).
                        cur.execute("""
                            UPDATE agenda_items
                            SET data_quality = 'ok'::data_quality_enum,
                                data_debt_priority = 'normal'::data_debt_priority_enum,
                                processing_status = 'withdrawn'::processing_status_enum
                            WHERE id = %s
                        """, [item_id])
                        report.counts['withdrawn'] += 1
                        continue

                    if is_procedural(title):
                        cur.execute("""
                            UPDATE agenda_items
                            SET data_quality = 'ok'::data_quality_enum,
                                data_debt_priority = 'normal'::data_debt_priority_enum,
                                processing_status = 'procedural_skipped'::processing_status_enum
                            WHERE id = %s
                        """, [item_id])
                        report.counts['procedural_skipped'] += 1
                        continue

                    view = SimpleNamespace(
                        title=title,
                        description=description,
                        raw_text=None,
                        source_type='pdf',
                    )
                    quality, priority = evaluate_data_quality(view)

                    if quality != 'ok':
                        cur.execute("""
                            UPDATE agenda_items
                            SET data_quality = %s::data_quality_enum,
                                data_debt_priority = %s::data_debt_priority_enum,
                                processing_status = 'data_quality_skipped'::processing_status_enum
                            WHERE id = %s
                        """, [quality, priority, item_id])
                        report.counts['data_quality_skipped'] += 1
                        continue

                    if quality == 'ok':
                        cur.execute("""
                            UPDATE agenda_items
                            SET data_quality = 'ok'::data_quality_enum,
                                data_debt_priority = %s::data_debt_priority_enum,
                                processing_status = 'pending'::processing_status_enum
                            WHERE id = %s
                        """, [priority, item_id])
                        report.counts['pending'] += 1
                        report.items_processed += 1
                    else:
                        # Unreachable by construction; tripwire for future refactors.
                        log.error("wave_0: item %s missed all branches (quality=%r)", item_id, quality)
                        report.counts['unknown'] += 1

                log.info("wave_0 complete: %s", dict(report.counts))
            except Exception:
                log.exception("wave_0 failed")
                raise
            finally:
                cur.execute("SELECT pg_advisory_unlock(hashtext('docket.wave_0'))")

    return report
