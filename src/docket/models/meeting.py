"""Meeting dataclass — represents a persisted meeting row."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Meeting:
    id: int
    municipality_id: int
    external_id: str | None
    title: str
    meeting_date: str | None
    meeting_type: str | None
    agenda_url: str | None
    minutes_url: str | None
    video_url: str | None
    source_url: str | None
    executive_summary: str | None = None
    executive_summary_voice: str | None = None  # 'upcoming' | 'completed' | NULL
    ai_metadata: dict | None = None
    ai_prompt_version: int | None = None
    ai_generated_at: datetime | None = None

    @classmethod
    def from_row(cls, row: dict) -> Meeting:
        return cls(
            id=row["id"],
            municipality_id=row["municipality_id"],
            external_id=row.get("external_id"),
            title=row.get("title", ""),
            meeting_date=row.get("meeting_date"),
            meeting_type=row.get("meeting_type"),
            agenda_url=row.get("agenda_url"),
            minutes_url=row.get("minutes_url"),
            video_url=row.get("video_url"),
            source_url=row.get("source_url"),
            executive_summary=row.get("executive_summary"),
            executive_summary_voice=row.get("executive_summary_voice"),
            ai_metadata=row.get("ai_metadata"),
            ai_prompt_version=row.get("ai_prompt_version"),
            ai_generated_at=row.get("ai_generated_at"),
        )
