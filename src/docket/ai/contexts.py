"""Dataclasses that mediate between DB rows and prompt strings.

Each context's from_row() factory normalizes NULL columns so rendered
prompts never contain the literal string "None".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Sequence

from docket.ai.results import MeetingPhase


def _format_dollars(amount: Decimal | None) -> str:
    if amount is None:
        return "(none)"
    return f"${amount:,.2f}"


@dataclass(frozen=True)
class AgendaItemContext:
    item_id: int
    title: str
    description: str
    sponsor: str
    dollars_amount: str
    topic: str
    is_consent_label: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "AgendaItemContext":
        return cls(
            item_id=row["id"],
            title=row["title"],
            description=row["description"] or "(no description provided)",
            sponsor=row["sponsor"] or "(no sponsor listed)",
            dollars_amount=_format_dollars(row["dollars_amount"]),
            topic=row["topic"] or "Uncategorized",
            is_consent_label="Yes" if row["is_consent"] else "No",
        )

    def render_user_prompt(self) -> str:
        from docket.ai.prompts import ITEM_USER_TEMPLATE
        return ITEM_USER_TEMPLATE.format(
            title=self.title,
            description=self.description,
            sponsor=self.sponsor,
            dollars_amount=self.dollars_amount,
            topic=self.topic,
            is_consent=self.is_consent_label,
        )


@dataclass(frozen=True)
class MeetingContext:
    meeting_id: int
    meeting_type: str
    meeting_date: date
    phase: MeetingPhase
    item_summaries: Sequence[str]

    def render_user_prompt(self) -> str:
        from docket.ai.prompts import MEETING_USER_TEMPLATE
        items_block = "\n".join(f"- {s}" for s in self.item_summaries)
        return MEETING_USER_TEMPLATE.format(
            meeting_type=self.meeting_type,
            meeting_date=self.meeting_date.isoformat(),
            phase=self.phase,
            count=len(self.item_summaries),
            items_block=items_block,
        )
