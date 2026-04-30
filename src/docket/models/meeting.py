"""Meeting dataclass — represents a persisted meeting row."""

from __future__ import annotations

from dataclasses import dataclass


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
        )
