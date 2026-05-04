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
    """A persisted vote row, with N:M agenda-item links attached."""

    id: int
    meeting_id: int
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
    resolution_number: str | None = None
    video_timestamp: float | None = None
    agenda_links: list[AgendaItemLink] = field(default_factory=list)
    member_votes: list[MemberVote] = field(default_factory=list)

    @property
    def active_links(self) -> list[AgendaItemLink]:
        return [link for link in self.agenda_links if link.is_active]

    @property
    def is_consent_block(self) -> bool:
        return any(link.association_type.startswith("consent_") for link in self.active_links)

    @property
    def has_provisional_links(self) -> bool:
        return any(link.provisional for link in self.active_links)

    @property
    def primary_link(self) -> AgendaItemLink | None:
        active = self.active_links
        return active[0] if len(active) == 1 else None

    @property
    def excluded_links(self) -> list[AgendaItemLink]:
        return [link for link in self.agenda_links if not link.is_active]
