"""Render tests for partials/_vote_result_block.html.

Exercises each branch of the Vote Result block (banner with/without
history, no-vote branches keyed off processing_status) so a template
syntax error or missing attribute is caught in CI, not in production.
The branch logic is the part this ship is most likely to regress —
the resolution rule itself is covered by
``tests/unit/test_query_get_vote_for_item.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class _FakeVote:
    """Stand-in for query.VoteEntry — only the fields the partial reads."""
    vote_id: int = 1
    meeting_id: int = 100
    result: str = "passed"
    yeas: int | None = 9
    nays: int | None = 0
    abstentions: int | None = 0
    meeting_date: object = field(default_factory=lambda: date(2026, 5, 1))
    association_type: str = "explicit"
    provisional: bool = False
    is_manual: bool = False
    source: str = "minutes_text"
    video_timestamp: float | None = None
    video_url: str | None = None
    minutes_url: str | None = None

    @property
    def is_consent_block(self) -> bool:
        return self.association_type.startswith("consent_")


@dataclass
class _FakeData:
    prevailing: _FakeVote
    history: list = field(default_factory=list)


@dataclass
class _FakeItem:
    id: int = 42
    meeting_id: int = 100
    processing_status: str | None = "completed"


@dataclass
class _FakeMeeting:
    id: int = 100
    meeting_date: object = field(default_factory=lambda: date(2026, 5, 1))
    minutes_url: str | None = None


_MUNI = {"slug": "birmingham", "name": "Birmingham"}


def _render(render_partial, **overrides):
    """Render the partial with sensible defaults so each test only passes
    what it cares about. ``vote_data`` may be passed explicitly (even as
    None to exercise the no-vote branch)."""
    ctx = {
        "item": _FakeItem(),
        "meeting": _FakeMeeting(),
        "municipality": _MUNI,
        "vote_data": _FakeData(prevailing=_FakeVote()),
    }
    ctx.update(overrides)
    return render_partial("partials/_vote_result_block.html", **ctx)


# ── Banner ────────────────────────────────────────────────────────────────


def test_passed_substantive_renders_banner_with_tally(render_partial):
    html = _render(
        render_partial,
        vote_data=_FakeData(prevailing=_FakeVote(result="passed", yeas=9, nays=0)),
    )
    assert "vote-block" in html
    assert "is-pass" in html
    assert "passed" in html
    assert "9–0" in html


def test_failed_substantive_renders_is_fail_modifier(render_partial):
    html = _render(
        render_partial,
        vote_data=_FakeData(prevailing=_FakeVote(result="failed", yeas=4, nays=5)),
    )
    assert "is-fail" in html
    assert "4–5" in html


def test_consent_provisional_shows_provisional_pill(render_partial):
    html = _render(
        render_partial,
        vote_data=_FakeData(
            prevailing=_FakeVote(
                association_type="consent_named", provisional=True
            )
        ),
    )
    assert "provisional · consent" in html
    assert "is-warn" in html


def test_consent_adopted_shows_adopted_pill(render_partial):
    html = _render(
        render_partial,
        vote_data=_FakeData(
            prevailing=_FakeVote(
                association_type="consent_named", provisional=False
            )
        ),
    )
    assert "adopted · consent" in html
    assert "is-good" in html


def test_manual_shield_shows_manually_linked_chip(render_partial):
    html = _render(
        render_partial,
        vote_data=_FakeData(prevailing=_FakeVote(is_manual=True)),
    )
    assert "manually linked" in html


# ── Source-link priority ──────────────────────────────────────────────────


def test_source_link_prefers_video_timestamp(render_partial):
    html = _render(
        render_partial,
        vote_data=_FakeData(
            prevailing=_FakeVote(
                video_timestamp=123.4,
                video_url="https://example.test/video.mp4",
                minutes_url="https://example.test/minutes.pdf",
            )
        ),
    )
    assert "Watch this vote" in html
    assert "https://example.test/video.mp4#t=123" in html
    # Minutes link must NOT be the primary action when video is present.
    assert "Read minutes" not in html


def test_source_link_falls_back_to_minutes_when_no_timestamp(render_partial):
    html = _render(
        render_partial,
        vote_data=_FakeData(
            prevailing=_FakeVote(
                video_timestamp=None,
                video_url=None,
                minutes_url="https://example.test/minutes.pdf",
            )
        ),
    )
    assert "Read minutes" in html
    assert "https://example.test/minutes.pdf" in html


def test_source_link_final_fallback_to_meeting_anchor(render_partial):
    html = _render(
        render_partial,
        vote_data=_FakeData(
            prevailing=_FakeVote(
                vote_id=7,
                meeting_id=100,
                video_timestamp=None,
                video_url=None,
                minutes_url=None,
            )
        ),
    )
    assert "Vote in meeting context" in html
    assert "#vote-7" in html


# ── History disclosure ────────────────────────────────────────────────────


def test_history_disclosure_hidden_when_only_one_vote(render_partial):
    html = _render(
        render_partial,
        vote_data=_FakeData(prevailing=_FakeVote(), history=[]),
    )
    assert "vote-history" not in html
    assert "View vote history" not in html


def test_history_disclosure_appears_with_count_when_multiple_votes(render_partial):
    history = [
        _FakeVote(vote_id=2, result="passed", yeas=5, nays=4),
        _FakeVote(vote_id=3, result="failed", yeas=4, nays=5),
    ]
    html = _render(
        render_partial,
        vote_data=_FakeData(prevailing=_FakeVote(vote_id=1), history=history),
    )
    assert "View vote history (2)" in html
    assert "vote-history" in html


# ── No-vote branches ──────────────────────────────────────────────────────


def test_no_vote_withdrawn_copy(render_partial):
    html = _render(
        render_partial,
        item=_FakeItem(processing_status="withdrawn"),
        vote_data=None,
    )
    assert "withdrawn" in html
    assert "no-vote-block" in html


def test_no_vote_procedural_copy(render_partial):
    html = _render(
        render_partial,
        item=_FakeItem(processing_status="procedural_skipped"),
        vote_data=None,
    )
    assert "procedural" in html


def test_no_vote_substantive_unmatched_links_to_minutes_when_available(
    render_partial,
):
    html = _render(
        render_partial,
        item=_FakeItem(processing_status="completed"),
        meeting=_FakeMeeting(minutes_url="https://example.test/minutes.pdf"),
        vote_data=None,
    )
    assert "couldn't match" in html
    assert "https://example.test/minutes.pdf" in html
    assert "View full minutes" in html


def test_no_vote_substantive_unmatched_falls_back_to_meeting_when_no_minutes(
    render_partial,
):
    html = _render(
        render_partial,
        item=_FakeItem(id=42, meeting_id=100, processing_status="pending"),
        meeting=_FakeMeeting(minutes_url=None),
        vote_data=None,
    )
    assert "couldn't match" in html
    assert "#item-42" in html
    assert "View full meeting" in html


def test_no_vote_null_processing_status_renders_generic_fallback(render_partial):
    """Legacy items pre-Wave 0 may have NULL processing_status. The
    generic else branch must render so the block is never empty."""
    html = _render(
        render_partial,
        item=_FakeItem(processing_status=None),
        vote_data=None,
    )
    assert "No vote was recorded" in html


def test_no_vote_unknown_processing_status_renders_generic_fallback(
    render_partial,
):
    """Unrecognized future-status enum values fall through to the generic
    else branch rather than rendering an empty block."""
    html = _render(
        render_partial,
        item=_FakeItem(processing_status="some_future_status"),
        vote_data=None,
    )
    assert "No vote was recorded" in html
