"""Enrichment service — extract dollars and compute scores for agenda items.

Provides both inline enrichment (called during ingest) and batch backfill
(for existing data). All DB transactions owned here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from docket.db import db, db_cursor
from docket.enrichment.dollars import extract_dollars
from docket.enrichment.scoring import (
    compute_consent_placement_score,
    compute_significance_score,
)

logger = logging.getLogger(__name__)


@dataclass
class BackfillResult:
    municipality_slug: str
    items_processed: int
    items_enriched: int
    errors: list[str]


def enrich_agenda_item(
    title: str,
    description: str | None,
    is_consent: bool,
) -> dict:
    """Enrich a single agenda item with dollars and scores.

    Returns a dict with keys: dollars_amount, significance_score,
    consent_placement_score. Any value may be None.
    """
    # Combine title and description for dollar extraction
    text = title
    if description:
        text = f"{title} {description}"

    dollars = extract_dollars(text)
    significance = compute_significance_score(title, description, dollars)
    consent_score = compute_consent_placement_score(title, description, is_consent)

    return {
        "dollars_amount": dollars,
        "significance_score": significance,
        "consent_placement_score": consent_score,
    }


def backfill_municipality(slug: str) -> BackfillResult:
    """Re-enrich all agenda items for a municipality."""
    errors: list[str] = []

    with db_cursor() as cur:
        cur.execute(
            "SELECT id FROM municipalities WHERE slug = %s",
            (slug,),
        )
        muni = cur.fetchone()

    if muni is None:
        return BackfillResult(slug, 0, 0, [f"Municipality '{slug}' not found"])

    municipality_id = muni["id"]

    # Fetch all agenda items for this municipality
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT ai.id, ai.title, ai.description, ai.is_consent
            FROM agenda_items ai
            JOIN meetings m ON ai.meeting_id = m.id
            WHERE m.municipality_id = %s
            """,
            (municipality_id,),
        )
        items = cur.fetchall()

    if not items:
        return BackfillResult(slug, 0, 0, [])

    enriched_count = 0

    with db() as conn:
        with conn.cursor() as cur:
            for item in items:
                try:
                    result = enrich_agenda_item(
                        item["title"],
                        item["description"],
                        item["is_consent"],
                    )
                    cur.execute(
                        """
                        UPDATE agenda_items
                        SET dollars_amount = %s,
                            significance_score = %s,
                            consent_placement_score = %s
                        WHERE id = %s
                        """,
                        (
                            result["dollars_amount"],
                            result["significance_score"],
                            result["consent_placement_score"],
                            item["id"],
                        ),
                    )
                    if result["dollars_amount"] is not None:
                        enriched_count += 1
                except Exception as e:
                    errors.append(f"Item {item['id']}: {e}")

    logger.info(
        "Backfill %s: %d items processed, %d enriched with dollars",
        slug,
        len(items),
        enriched_count,
    )

    return BackfillResult(
        municipality_slug=slug,
        items_processed=len(items),
        items_enriched=enriched_count,
        errors=errors,
    )


def backfill_meeting(meeting_id: int) -> int:
    """Re-enrich all agenda items for a single meeting. Returns count enriched."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT id, title, description, is_consent FROM agenda_items WHERE meeting_id = %s",
            (meeting_id,),
        )
        items = cur.fetchall()

    if not items:
        return 0

    enriched_count = 0

    with db() as conn:
        with conn.cursor() as cur:
            for item in items:
                result = enrich_agenda_item(
                    item["title"],
                    item["description"],
                    item["is_consent"],
                )
                cur.execute(
                    """
                    UPDATE agenda_items
                    SET dollars_amount = %s,
                        significance_score = %s,
                        consent_placement_score = %s
                    WHERE id = %s
                    """,
                    (
                        result["dollars_amount"],
                        result["significance_score"],
                        result["consent_placement_score"],
                        item["id"],
                    ),
                )
                if result["dollars_amount"] is not None:
                    enriched_count += 1

    return enriched_count
