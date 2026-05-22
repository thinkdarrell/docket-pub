"""Terminal-frame vote analysis orchestrator.

The pipeline runs in five stages:

    A. Coarse scan        — find candidate vote-display frames cheaply.
    B. Sequence bounding  — refine coarse hits into ``VoteSequence`` runs.
    C. Terminal frame id  — walk each sequence backwards and pick the
                             last frame whose header reads as a
                             finalized motion state. Sequences that
                             never finalize are dropped entirely.
    D. Full terminal OCR  — OCR the count boxes and spatially extract
                             member positions for the terminal frame.
    E. Cross-verify       — compare the three independent signals
                             (header, count boxes, summed member
                             positions); flag disagreements for review.

Stages A+B live in ``vote_sequence``. Stages C–E live here.
"""

from __future__ import annotations

import logging

import numpy as np

from docket.analysis.ocr.layout import CouncilLayout
from docket.analysis.ocr.header import HeaderState, read_header
from docket.analysis.ocr.layout import detect_member_rows
from docket.analysis.ocr.ocr import extract_counts, extract_vote_text
from docket.analysis.ocr.sequence import VoteSequence, find_vote_sequences
from docket.analysis.ocr._models import DetectedVote, MemberVote

logger = logging.getLogger(__name__)

FrameWithTimestamp = tuple[float, np.ndarray]


def scan_meeting_for_votes(
    video_url: str,
    layout: CouncilLayout | None = None,
    scan_interval: int = 2,
    fps: int = 1,  # noqa: ARG001  (kept for backwards-compat with batch_processor)
    meeting_date: str | None = None,  # noqa: ARG001  (kept for backwards-compat)
) -> list[DetectedVote]:
    """Scan a full meeting video and return one DetectedVote per finalized vote.

    ``layout`` is required — pass a ``CouncilLayout`` built from the live
    roster via ``docket.analysis.ocr.rosters.build_roster_for_meeting()``.
    Raises ``ValueError`` when ``None`` so callers can never silently fall
    back to a stale hardcoded roster.
    """
    if layout is None:
        raise ValueError(
            "scan_meeting_for_votes requires a CouncilLayout; "
            "callers should build one via docket.analysis.ocr.rosters.build_roster_for_meeting()"
        )
    sequences = find_vote_sequences(video_url, coarse_interval=float(scan_interval))
    logger.info("Found %d vote sequences", len(sequences))

    results: list[DetectedVote] = []
    for seq in sequences:
        vote = analyze_sequence(seq, layout=layout)
        if vote is None:
            logger.info(
                "  [%.0fs-%.0fs] sequence never reached terminal header — skipped",
                seq.start,
                seq.end,
            )
            continue
        results.append(vote)
        _log_vote(vote)
    return results


def extract_frames_at_timestamps(
    video_url: str,
    timestamps: list[tuple[float, str]],
    layout: CouncilLayout | None = None,
    window: int = 15,
    fps: int = 2,  # noqa: ARG001  (kept for backwards-compat)
    meeting_date: str | None = None,  # noqa: ARG001  (kept for backwards-compat)
) -> list[DetectedVote]:
    """Scan small windows around specific timestamps and return finalized DetectedVotes.

    Used by the timestamp-targeted entry point. Each timestamp becomes a
    narrow search window that still goes through the same
    ``find_vote_sequences`` → ``analyze_sequence`` chain.

    ``layout`` is required — raises ``ValueError`` when ``None``.
    """
    from docket.analysis.ocr.frame_io import scan_window
    from docket.analysis.ocr.sequence import sequences_from_frames

    if layout is None:
        raise ValueError(
            "extract_frames_at_timestamps requires a CouncilLayout; "
            "callers should build one via docket.analysis.ocr.rosters.build_roster_for_meeting()"
        )
    results: list[DetectedVote] = []

    for ts, _label in timestamps:
        start = max(0.0, ts - 5.0)
        duration = float(window) + 10.0
        sequences = sequences_from_frames(
            scan_window(video_url, start=start, duration=duration, fps=1.0)
        )
        for seq in sequences:
            vote = analyze_sequence(seq, layout=layout)
            if vote is not None:
                results.append(vote)

    return results


# --- Stage C: terminal frame identification --------------------------------


def analyze_sequence(
    sequence: VoteSequence,
    *,
    layout: CouncilLayout,
) -> DetectedVote | None:
    """Return the finalized DetectedVote for a sequence, or None if it never finalized.

    First tries the OCR'd terminal-header path. If that fails, falls
    back to inferring the result from the last classifier-passing
    frame whose counts and member positions agree — Birmingham's
    terminal overlay is usually composited over the chamber camera
    shot, which defeats header OCR but leaves the mid-vote counts
    intact. Inferred votes carry ``needs_review=True`` and
    ``review_reason="header_inferred_from_counts"``.
    """
    terminal = _find_terminal_frame(sequence)
    inferred = _find_inferred_terminal_frame(sequence, layout=layout)

    if terminal is not None:
        ts, frame = terminal
        vote = _analyze_terminal_frame(ts, frame, layout=layout)
        # If the OCR'd terminal frame returned no count data at all,
        # the header was likely a mis-classification (e.g., a 540p
        # "Voting in Progress" matching the "passes" keyword) and the
        # vote is unusable as-is. Prefer inference when it can find a
        # coherent frame elsewhere in the sequence; otherwise keep the
        # OCR'd vote so cross_verify's extraction_failed flag stands.
        counts_empty = vote.yeas is None and vote.nays is None and vote.abstentions is None
        if counts_empty and inferred is not None:
            ts, frame, inferred_result = inferred
            return _build_inferred_vote(ts, frame, inferred_result, layout=layout)
        return vote

    if inferred is None:
        return None
    ts, frame, inferred_result = inferred
    return _build_inferred_vote(ts, frame, inferred_result, layout=layout)


def _build_inferred_vote(
    timestamp: float,
    frame: np.ndarray,
    inferred_result: str,
    *,
    layout: CouncilLayout,
) -> DetectedVote:
    """Run full terminal-frame analysis but override vote_result with
    the inferred outcome and flag for human review."""
    vote = _analyze_terminal_frame(timestamp, frame, layout=layout)
    return DetectedVote(
        timestamp=vote.timestamp,
        vote_result=inferred_result,
        yeas=vote.yeas,
        nays=vote.nays,
        abstentions=vote.abstentions,
        raw_text=vote.raw_text,
        member_votes=vote.member_votes,
        header_result=vote.header_result,
        needs_review=True,
        review_reason="header_inferred_from_counts",
    )


def _find_inferred_terminal_frame(
    sequence: VoteSequence, *, layout: CouncilLayout
) -> tuple[float, np.ndarray, str] | None:
    """Walk backward through the sequence for a frame with coherent
    counts + member dots, and infer the vote result from the counts.

    "Coherent" means the count-box OCR returned all three values AND
    the spatially-extracted member positions sum to the same totals
    (yes/no/abstain). When both signals agree, the counts are stable
    enough to base a result on — even if the terminal header text was
    composited over a camera shot and unreadable.

    Returns ``(timestamp, frame, inferred_result)`` or ``None`` if no
    frame in the sequence is coherent (the sequence was a classifier
    false-positive — e.g. a podium camera shot the 4-signal histogram
    mis-fired on).
    """
    for ts, frame in reversed(sequence.frames):
        counts = extract_counts(frame)
        if not all(counts[k] is not None for k in ("yeas", "nays", "abstentions")):
            continue
        members = detect_member_rows(frame, layout=layout)
        m_yes = sum(1 for p in members.values() if p == "yes")
        m_no = sum(1 for p in members.values() if p == "no")
        m_abs = sum(1 for p in members.values() if p == "abstain")
        if (m_yes, m_no, m_abs) != (counts["yeas"], counts["nays"], counts["abstentions"]):
            continue
        y, n, a = counts["yeas"], counts["nays"], counts["abstentions"]
        if y > n:
            return (ts, frame, "passed")
        if n > y:
            return (ts, frame, "failed")
        if a > 0:
            # Tied with non-zero abstentions usually indicates a deferral.
            return (ts, frame, "tabled")
        # Tied with no abstentions is unusual; don't guess.
        return None
    return None


def _find_terminal_frame(sequence: VoteSequence) -> FrameWithTimestamp | None:
    """Return the best terminal frame from a sequence, or None if none exist.

    "Best" here means: a frame whose header reads as finalized AND whose
    count-box OCR produces all three values. Walking strictly backwards
    and returning the very last terminal frame is unsafe because the
    tail of a sequence is often a fade-out frame — the header text is
    still bright enough to OCR but the smaller count digits have
    dimmed past the threshold. We walk backwards across terminal
    frames and stop on the first one with fully readable counts.

    If no terminal frame has readable counts, we fall back to the
    latest terminal frame so the cross-verification flag can catch it
    as ``extraction_failed``.
    """
    terminal_frames: list[FrameWithTimestamp] = [
        (ts, frame) for ts, frame in sequence.frames if read_header(frame).is_terminal()
    ]
    if not terminal_frames:
        return None

    for ts, frame in reversed(terminal_frames):
        counts = extract_counts(frame)
        if all(counts[k] is not None for k in ("yeas", "nays", "abstentions")):
            return (ts, frame)

    return terminal_frames[-1]


# --- Stages D + E: full OCR and cross-verification -------------------------


def _analyze_terminal_frame(
    timestamp: float,
    frame: np.ndarray,
    *,
    layout: CouncilLayout,
) -> DetectedVote:
    header = read_header(frame)
    counts = extract_counts(frame)
    raw_text = extract_vote_text(frame)

    member_positions = detect_member_rows(frame, layout=layout)
    member_votes = [
        MemberVote(member_name=name, position=position)
        for name, position in member_positions.items()
    ]

    needs_review, reason = _cross_verify(header, counts, member_positions)
    vote_result = header.value if header.is_terminal() else "unknown"

    return DetectedVote(
        timestamp=timestamp,
        vote_result=vote_result,
        yeas=counts["yeas"],
        nays=counts["nays"],
        abstentions=counts["abstentions"],
        raw_text=raw_text,
        member_votes=member_votes,
        header_result=header.value,
        needs_review=needs_review,
        review_reason=reason,
    )


def _cross_verify(
    header: HeaderState,
    counts: dict[str, int | None],
    member_positions: dict[str, str],
) -> tuple[bool, str | None]:
    """Return ``(needs_review, reason)`` by comparing header / counts / members."""
    y = counts.get("yeas")
    n = counts.get("nays")
    a = counts.get("abstentions")

    m_yes = sum(1 for p in member_positions.values() if p == "yes")
    m_no = sum(1 for p in member_positions.values() if p == "no")
    m_abs = sum(1 for p in member_positions.values() if p == "abstain")

    # Check 0: extraction actually produced something usable. If both the
    # count OCR and the member extractor came up empty, the frame was a
    # false-positive terminal screen (animation / fade / transitional
    # render) — flag it so a human can eyeball the timestamp.
    counts_all_none = y is None and n is None and a is None
    if counts_all_none and not member_positions:
        return True, "extraction_failed"

    # Check 1: summed member positions match the OCR'd count boxes.
    if y is not None and n is not None and a is not None and (m_yes, m_no, m_abs) != (y, n, a):
        return True, "counts_mismatch"

    # Check 2: header outcome agrees with the count totals.
    if y is not None and n is not None:
        if header == HeaderState.PASSED and not (y > n):
            return True, "header_counts_disagree"
        if header == HeaderState.FAILED and not (n > y):
            return True, "header_counts_disagree"

    return False, None


# --- Logging ---------------------------------------------------------------


def _log_vote(vote: DetectedVote) -> None:
    ts = int(vote.timestamp)
    mins, secs = ts // 60, ts % 60
    logger.info(
        "  [%02d:%02d] VOTE: %s header=%s (Y:%s N:%s A:%s)%s",
        mins,
        secs,
        vote.vote_result,
        vote.header_result,
        vote.yeas,
        vote.nays,
        vote.abstentions,
        " [NEEDS REVIEW: " + (vote.review_reason or "?") + "]" if vote.needs_review else "",
    )


# Re-export the dataclasses for convenience; callers can also import them
# directly from docket.analysis.ocr._models.
from docket.analysis.ocr._models import DetectedVote, MemberVote  # noqa: F401, E402
