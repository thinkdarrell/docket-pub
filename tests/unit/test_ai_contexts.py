"""Tests for AgendaItemContext / MeetingContext NULL-handling at the prompt boundary."""

from datetime import date
from decimal import Decimal

from docket.ai.contexts import AgendaItemContext, MeetingContext


def test_item_all_fields_present():
    ctx = AgendaItemContext.from_row({
        "id": 42,
        "title": "Authorize $4.2M road contract",
        "description": "Resurfacing contract for downtown corridor",
        "sponsor": "Public Works Dept.",
        "dollars_amount": Decimal("4200000.00"),
        "topic": "Public Works",
        "is_consent": False,
    })
    rendered = ctx.render_user_prompt()
    assert "Authorize $4.2M road contract" in rendered
    assert "Public Works" in rendered
    assert "$4,200,000" in rendered or "4200000" in rendered
    assert "(no description provided)" not in rendered


def test_item_null_topic_renders_uncategorized():
    ctx = AgendaItemContext.from_row({
        "id": 1, "title": "ok", "description": None, "sponsor": None,
        "dollars_amount": None, "topic": None, "is_consent": False,
    })
    rendered = ctx.render_user_prompt()
    assert "Uncategorized" in rendered
    assert "(no description provided)" in rendered
    assert "(no sponsor listed)" in rendered
    assert "(none)" in rendered
    assert "None" not in rendered


def test_item_consent_flag_rendering():
    yes_ctx = AgendaItemContext.from_row({
        "id": 1, "title": "x", "description": None, "sponsor": None,
        "dollars_amount": None, "topic": None, "is_consent": True,
    })
    assert "Yes" in yes_ctx.render_user_prompt()


def test_meeting_renders_distinctive_items():
    """Distinctive item summaries appear in the rendered prompt (telescoping)."""
    ctx = MeetingContext(
        meeting_id=10,
        meeting_type="Council Meeting",
        meeting_date=date(2026, 4, 1),
        phase="provisional",
        distinctive_items=(
            "Approves $4.2M road resurfacing contract.",
            "Authorizes 3-year IT support agreement.",
        ),
        routine_clusters=(),
    )
    rendered = ctx.render_user_prompt()
    assert "Approves $4.2M road resurfacing contract." in rendered
    assert "Authorizes 3-year IT support agreement." in rendered
    assert "Phase: provisional" in rendered
    assert "DISTINCTIVE items (2)" in rendered
    assert "ROUTINE items (0" in rendered
