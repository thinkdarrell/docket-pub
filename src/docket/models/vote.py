"""Vote-related dataclasses."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_SAYS_FAILED = re.compile(r"\b(failed|denied)\b", re.IGNORECASE)
_SAYS_NOT_DECIDED = re.compile(r"\b(tabled|held\s+over|laid\s+over|withdrawn)\b", re.IGNORECASE)


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
    # What a minutes reader stores (`votes.minutes_reader` and the four columns beside it);
    # None on a row from any other writer. `minutes_page_url` is not a column: the page's
    # query builds it from the meeting's minutes link with `page_link`.
    minutes_reader: str | None = None
    source_page: int | None = None
    caption: str | None = None
    motion_text: str | None = None
    declared_text: str | None = None
    minutes_page_url: str | None = None

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


def vote_label(result: str, declared_text: str | None) -> str:
    """The declaration when the row has one, else the stored result."""
    return declared_text or result


def vote_tone(result: str, declared_text: str | None) -> str:
    """How a page colours a vote: 'pass', 'fail', or '' for neither.

    'fail' when the result is failed or the declaration says failed or denied;
    '' when the declaration says tabled, held over, laid over or withdrawn, or the
    result is neither passed nor failed; 'pass' when the result is passed otherwise.
    Each word is matched whole, ignoring case. The first that applies decides, so a
    motion to deny that carried (result passed, "the waiver denied") is 'fail': the
    tone is about the thing voted on, as the declaration is.
    """
    declared = declared_text or ""
    if result == "failed" or _SAYS_FAILED.search(declared):
        return "fail"
    if _SAYS_NOT_DECIDED.search(declared) or result != "passed":
        return ""
    return "pass"


def page_link(url: str | None, page: int | None) -> str | None:
    """url with any fragment removed and '#page=<page>' added; None unless both are given."""
    if not url or page is None:
        return None
    return f"{url.split('#', 1)[0]}#page={page}"
