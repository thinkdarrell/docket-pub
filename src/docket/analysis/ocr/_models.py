"""Vote-related dataclasses crossing module boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MemberVote:
    """A single council member's position on a single vote."""

    member_name: str
    position: str  # "yes" | "no" | "abstain" | "absent"


@dataclass
class DetectedVote:
    """A vote pulled from a video frame, before it has been matched to an agenda item.

    ``header_result`` is the raw header text state read from the terminal
    frame ("passed" | "failed" | "tabled" | "unknown"). ``needs_review``
    is set by Stage E cross-verification when the three independent
    signals (header, count boxes, summed member votes) disagree.
    ``review_reason`` is a short machine-readable code describing which
    check failed.
    """

    timestamp: float
    vote_result: str  # "passed" | "failed" | "tied" | "tabled" | "unknown"
    yeas: int | None
    nays: int | None
    abstentions: int | None
    raw_text: str
    member_votes: list[MemberVote] = field(default_factory=list)
    header_result: str | None = None
    needs_review: bool = False
    review_reason: str | None = None


__all__ = ["DetectedVote", "MemberVote"]
