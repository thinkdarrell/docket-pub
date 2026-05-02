"""Tests for prompt templates and version constants."""

from docket.ai.prompts import (
    ITEM_PROMPT_VERSION,
    MEETING_PROMPT_VERSION,
    ITEM_SYSTEM,
    MEETING_SYSTEM,
    ITEM_USER_TEMPLATE,
    MEETING_USER_TEMPLATE,
)


def test_versions_are_integers():
    assert isinstance(ITEM_PROMPT_VERSION, int)
    assert isinstance(MEETING_PROMPT_VERSION, int)
    assert ITEM_PROMPT_VERSION >= 1
    assert MEETING_PROMPT_VERSION >= 1


def test_item_system_says_rationale_before_score():
    """Rationales-first instruction is present."""
    text = ITEM_SYSTEM.lower()
    rationale_idx = text.find("rationale")
    score_idx = text.find("score")
    assert rationale_idx != -1 and score_idx != -1
    assert rationale_idx < score_idx


def test_item_system_handles_procedural():
    text = ITEM_SYSTEM.lower()
    assert "is_substantive" in text or "procedural" in text


def test_meeting_system_phase_aware():
    text = MEETING_SYSTEM.lower()
    assert "adopted" in text
    assert "provisional" in text or "considered" in text


def test_item_user_template_renders():
    rendered = ITEM_USER_TEMPLATE.format(
        title="Test", description="d", sponsor="s",
        dollars_amount="$0", topic="Other", is_consent="No",
    )
    assert "Test" in rendered


def test_meeting_user_template_renders():
    rendered = MEETING_USER_TEMPLATE.format(
        meeting_type="Council", meeting_date="2026-04-01", phase="provisional",
        distinctive_count=2, distinctive_block="- a\n- b",
        routine_count=3, routine_block="- 3 public_safety items",
    )
    assert "Council" in rendered
    assert "2026-04-01" in rendered
    assert "- a" in rendered
    assert "DISTINCTIVE items (2)" in rendered
    assert "ROUTINE items (3" in rendered
