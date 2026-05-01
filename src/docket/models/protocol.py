"""Adapter protocol and raw dataclasses for cross-platform municipal data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol


@dataclass(frozen=True)
class RawMeeting:
    """A meeting as returned by a platform adapter, before DB persistence."""

    external_id: str
    municipality_slug: str
    title: str
    meeting_date: date
    meeting_type: str  # 'council' | 'work_session' | 'bza' | 'planning' | 'special'
    agenda_url: str | None
    minutes_url: str | None
    video_url: str | None
    source_url: str


@dataclass(frozen=True)
class RawAgendaItem:
    """An agenda item as returned by a platform adapter."""

    external_id: str
    meeting_external_id: str
    item_number: str | None
    title: str
    description: str | None
    section: str | None  # 'Consent Agenda', 'New Business', etc.
    is_consent: bool
    sponsor: str | None
    video_timestamp_seconds: float | None = None


@dataclass
class RawVote:
    """A vote as returned by a platform adapter."""

    external_id: str
    meeting_external_id: str
    agenda_item_external_id: str | None
    result: str  # 'passed' | 'failed' | 'tabled'
    yeas: int | None
    nays: int | None
    abstentions: int | None
    member_votes: list[dict] = field(default_factory=list)
    # Each dict: {"member": "...", "vote": "yea|nay|abstain|absent"}
    source: str = "api"  # 'video_ocr' | 'minutes_text' | 'api' | 'manual'
    confidence: str = "high"  # 'high' | 'medium' | 'low'
    resolution_number: str | None = None
    match_context: str | None = None


class MunicipalSourceAdapter(Protocol):
    """Contract every platform adapter must implement."""

    municipality_slug: str

    def list_meetings(self, since: date | None = None) -> list[RawMeeting]: ...

    def fetch_agenda_items(self, meeting: RawMeeting) -> list[RawAgendaItem]: ...

    def fetch_minutes_text(self, meeting: RawMeeting) -> str | None: ...

    def fetch_votes(self, meeting: RawMeeting) -> list[RawVote]: ...
