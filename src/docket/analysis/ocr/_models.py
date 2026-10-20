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
    ``review_reason`` is one of exactly five codes:

    - ``header_not_terminal``: the terminal frame's header did not read
      as passed, failed, or tabled; the stored result is ``unknown``.
    - ``extraction_failed``: the count-box OCR and the member extractor
      both came up empty, so the frame was a false-positive terminal
      screen.
    - ``counts_mismatch``: the summed member positions do not equal the
      OCR'd count boxes.
    - ``header_counts_disagree``: the header's outcome contradicts the
      yea and nay totals.
    - ``header_inferred_from_counts``: no terminal frame with readable
      counts was found (no header read as terminal, or the terminal
      frame's three counts were all empty), and the result was inferred
      from a frame whose counts and member positions agree
      (``_build_inferred_vote``).
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
