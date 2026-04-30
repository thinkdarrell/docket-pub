"""Agenda item dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
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
        )
