"""Agenda item dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
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
    # --- AI version tracking — three independent stages of the v3 pipeline.
    # Bumping each constant in src/docket/ai/prompts.py triggers re-cascade
    # of items at that stage and downstream:
    #   - ai_prompt_version      — Legacy v2 (Haiku item summary → `summary`)
    #   - ai_extraction_version  — Phase 2 / Stage 1 (LLM extraction →
    #                              `extracted_facts` JSONB)
    #   - ai_rewrite_version     — Phase 2 / Stage 2 (Smart Brevity rewrite →
    #                              `headline` + `why_it_matters`)
    # All three coexist on every item so partials can gate cleanly on a
    # single stage's version while the others stay independent.
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
    ai_extraction_version: int | None = None  # Stage 1 (extraction)
    ai_rewrite_version: int | None = None     # Stage 2 (Smart Brevity rewrite)
    ai_rewrite_voice: str | None = None       # 'upcoming' | 'completed' | NULL (legacy)
    ai_confidence: str | None = None  # TEXT enum: 'high' | 'medium' | 'low'
    headline: str | None = None
    why_it_matters: str | None = None
    source_anchor: dict | None = None
    # LEAN extracted_facts: only the keys v3 cards render. Full blob is
    # detail-page-only (out of scope for A8). See list_agenda_items()
    # in services/query.py for the jsonb_extract_path SELECT and the
    # Python-side reconstruction.
    extracted_facts: dict | None = None
    # --- Lifted v3 sub-keys (top-level aliases for `extracted_facts.*`) -------
    # Mirror the headline / why_it_matters top-level pattern so partials
    # (`_facts_strip.html`, `engagement_strip.html`) can read
    # ``item.<field>`` directly without traversing the JSONB blob. Each is
    # populated by ``from_row()`` from the matching ``extracted_facts``
    # sub-key (a typed read — non-matching shapes collapse to None so
    # malformed JSONB doesn't crash). The `extracted_facts` dict still
    # carries each value too — the lift is additive, not a move, so
    # consumers reading the lean dict keep working unchanged.
    #
    # Types mirror the Stage 1 schema (src/docket/ai/extraction_schema.py).
    # `procurement_method` and `action_type` are Literal enums in the
    # schema; widened to `str` here because the dataclass is downstream
    # of validation and can carry whatever Stage 1 emitted.
    next_steps: dict | None = None           # next_steps sub-dict (4 date fields)
    counterparty: str | None = None          # contract counterparty (e.g. vendor)
    funding_source: str | None = None        # FundingSource enum value
    procurement_method: str | None = None    # ProcurementMethod enum value
    action_type: str | None = None           # ActionType enum value
    location: dict | None = None             # LocationDetail (address/ward/etc.)
    # Aggregated agenda_item_badges rows — list of dicts shaped like
    # BadgeChip (kind, slug, name, icon, description, confidence). Empty
    # list when no badges; None when the query was run without badges.
    badges: list[dict] = field(default_factory=list)
    # Optional parent-meeting date. Populated by list_items_by_badge so
    # the category-landing meta strip can show the date inline (a card on
    # /al/birmingham/blight_accountability/ spans many meetings, unlike
    # the meeting-detail page where date is in the page chrome). Other
    # query paths that don't surface across meetings can leave this None.
    meeting_date: date | None = None
    # Optional parent-meeting and parent-municipality context. Populated
    # by cross-meeting/cross-city listings (search_agenda_items) so the
    # Smart Brevity Card chain can render meeting context + build link
    # hrefs without a separate fetch. Single-meeting consumers
    # (list_agenda_items) leave these None — the page chrome carries the
    # context. Templates that read them (rss/_macros.xml.j2,
    # member_detail.html, _card_shell.html's municipality fallback)
    # already tolerate None.
    municipality_slug: str | None = None
    municipality_name: str | None = None
    meeting_title: str | None = None

    @classmethod
    def from_row(cls, row: dict) -> AgendaItem:
        extracted_facts = row.get("extracted_facts")
        # Lift v3 sub-keys to top-level fields so the partials
        # (engagement_strip / _facts_strip) can read ``item.<field>``
        # directly without traversing the JSONB blob. Each lift is
        # type-guarded — a malformed ``extracted_facts`` (string, list,
        # missing key, JSONB null) collapses cleanly to None instead of
        # raising. Mirrors the headline / why_it_matters top-level
        # pattern. The lift is additive: ``extracted_facts`` itself stays
        # populated so consumers reading the lean dict keep working.
        ef = extracted_facts if isinstance(extracted_facts, dict) else {}
        next_steps = ef.get("next_steps") if isinstance(ef.get("next_steps"), dict) else None
        counterparty = ef.get("counterparty") if isinstance(ef.get("counterparty"), str) else None
        funding_source = ef.get("funding_source") if isinstance(ef.get("funding_source"), str) else None
        procurement_method = ef.get("procurement_method") if isinstance(ef.get("procurement_method"), str) else None
        action_type = ef.get("action_type") if isinstance(ef.get("action_type"), str) else None
        location = ef.get("location") if isinstance(ef.get("location"), dict) else None
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
            ai_rewrite_voice=row.get("ai_rewrite_voice"),
            ai_confidence=row.get("ai_confidence"),
            headline=row.get("headline"),
            why_it_matters=row.get("why_it_matters"),
            source_anchor=row.get("source_anchor"),
            extracted_facts=extracted_facts,
            next_steps=next_steps,
            counterparty=counterparty,
            funding_source=funding_source,
            procurement_method=procurement_method,
            action_type=action_type,
            location=location,
            badges=row.get("badges") or [],
            meeting_date=row.get("meeting_date"),
            municipality_slug=row.get("municipality_slug"),
            municipality_name=row.get("municipality_name"),
            meeting_title=row.get("meeting_title"),
        )
