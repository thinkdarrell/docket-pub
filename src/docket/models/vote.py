"""Vote-related dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MemberVote:
    """A single council member's position on a single vote."""

    member_name: str
    position: str  # "yea" | "nay" | "abstain" | "absent"
    council_member_id: int | None = None


@dataclass(frozen=True)
class AgendaItemLink:
    """A single link between a vote and an agenda item, with link-level metadata.

    Stored in the vote_agenda_items join table. One vote can have many links
    (consent block) or one (substantive). is_active=False marks a "ghost"
    link kept for audit only — items pulled from a consent agenda before
    the vote.
    """

    id: int
    agenda_item_id: int
    item_number: str | None
    title: str
    is_consent: bool
    association_type: str  # 'explicit' | 'consent_named' | 'consent_implicit' | 'positional'
    match_method: str | None
    match_confidence: float
    excerpt_context: str | None
    provisional: bool
    is_manual: bool
    is_active: bool


@dataclass(frozen=True)
class Vote:
    """A persisted vote row."""

    id: int
    meeting_id: int
    agenda_item_id: int | None
    external_id: str | None
    result: str  # 'passed' | 'failed' | 'tabled'
    yeas: int | None
    nays: int | None
    abstentions: int | None
    source: str  # 'video_ocr' | 'minutes_text' | 'api' | 'manual'
    confidence: str  # 'high' | 'medium' | 'low'
    header_result: str | None
    needs_review: bool
    review_reason: str | None
    video_timestamp: float | None = None
    match_confidence: float | None = None
    match_method: str | None = None
    agenda_item_title: str | None = None
    agenda_item_number: str | None = None
    member_votes: list[MemberVote] = field(default_factory=list)

    @classmethod
    def from_row(cls, row: dict) -> Vote:
        return cls(
            id=row["id"],
            meeting_id=row["meeting_id"],
            agenda_item_id=row.get("agenda_item_id"),
            external_id=row.get("external_id"),
            result=row.get("result", ""),
            yeas=row.get("yeas"),
            nays=row.get("nays"),
            abstentions=row.get("abstentions"),
            source=row.get("source", ""),
            confidence=row.get("confidence", ""),
            header_result=row.get("header_result"),
            needs_review=bool(row.get("needs_review", False)),
            review_reason=row.get("review_reason"),
            video_timestamp=row.get("video_timestamp"),
            match_confidence=row.get("match_confidence"),
            match_method=row.get("match_method"),
            agenda_item_title=row.get("agenda_item_title"),
            agenda_item_number=row.get("agenda_item_number"),
        )
