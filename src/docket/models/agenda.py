"""Agenda item dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class AgendaItem:
    """A persisted agenda item row."""

    id: int
    meeting_id: int
    external_id: str | None
    item_number: str | None
    title: str
    description: str | None
    section: str | None
    is_consent: bool
    sponsor: str | None
    dollars_amount: Decimal | None
    topic: str | None
    significance_score: float | None  # 0-10
    consent_placement_score: float | None  # 0-10
    summary: str | None = None
    ai_metadata: dict | None = None
    ai_prompt_version: int | None = None
    ai_generated_at: datetime | None = None
    # --- v3 columns from migration 013 (Phase 1 + Phase 2) -------------------
    # All Optional. Items predating v3 processing have NULL. The Smart Brevity
    # Card dispatcher (partials/smart_brevity_card.html) gates routing on
    # `processing_status`, `data_quality`, and `ai_rewrite_version`; the v3
    # cards downstream render `headline`, `why_it_matters`, `source_anchor`,
    # plus selected keys of `extracted_facts` (LEAN list-page shape — only
    # the keys the v3 cards render are pulled, not the full JSONB blob).
    data_quality: str | None = None
    data_debt_priority: str | None = None
    processing_status: str | None = None
    ai_extraction_version: int | None = None
    ai_rewrite_version: int | None = None
    ai_confidence: str | None = None  # TEXT enum: 'high' | 'medium' | 'low'
    headline: str | None = None
    why_it_matters: str | None = None
    source_anchor: dict | None = None
    # LEAN extracted_facts: only the keys v3 cards render. Full blob is
    # detail-page-only (out of scope for A8). See list_agenda_items()
    # in services/query.py for the jsonb_extract_path SELECT and the
    # Python-side reconstruction.
    extracted_facts: dict | None = None
    # Aggregated agenda_item_badges rows — list of dicts shaped like
    # BadgeChip (kind, slug, name, icon, description, confidence). Empty
    # list when no badges; None when the query was run without badges.
    badges: list[dict] = field(default_factory=list)

    @classmethod
    def from_row(cls, row: dict) -> AgendaItem:
        return cls(
            id=row["id"],
            meeting_id=row["meeting_id"],
            external_id=row.get("external_id"),
            item_number=row.get("item_number"),
            title=row.get("title", ""),
            description=row.get("description"),
            section=row.get("section"),
            is_consent=bool(row.get("is_consent", False)),
            sponsor=row.get("sponsor"),
            dollars_amount=row.get("dollars_amount"),
            topic=row.get("topic"),
            significance_score=row.get("significance_score"),
            consent_placement_score=row.get("consent_placement_score"),
            summary=row.get("summary"),
            ai_metadata=row.get("ai_metadata"),
            ai_prompt_version=row.get("ai_prompt_version"),
            ai_generated_at=row.get("ai_generated_at"),
            data_quality=row.get("data_quality"),
            data_debt_priority=row.get("data_debt_priority"),
            processing_status=row.get("processing_status"),
            ai_extraction_version=row.get("ai_extraction_version"),
            ai_rewrite_version=row.get("ai_rewrite_version"),
            ai_confidence=row.get("ai_confidence"),
            headline=row.get("headline"),
            why_it_matters=row.get("why_it_matters"),
            source_anchor=row.get("source_anchor"),
            extracted_facts=row.get("extracted_facts"),
            badges=row.get("badges") or [],
        )
