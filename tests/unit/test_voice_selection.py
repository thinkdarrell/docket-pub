"""Layer 2 voice-selection helpers — `select_item_voice` and `select_meeting_voice`.

Spec: docs/superpowers/specs/2026-05-18-upcoming-meeting-forward-voice-design.md
"""
from __future__ import annotations

import datetime as _dt
from types import SimpleNamespace

import pytest

from docket.ai.client import select_meeting_voice
from docket.ai.prompts import (
    MEETING_PROMPT_UPCOMING_VERSION,
    MEETING_PROMPT_VERSION,
    MEETING_SYSTEM,
    MEETING_SYSTEM_UPCOMING,
)
from docket.ai.rewrite import (
    ITEM_REWRITE_PROMPT_UPCOMING_VERSION,
    ITEM_REWRITE_PROMPT_VERSION,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_UPCOMING,
    select_item_voice,
)


# --- select_item_voice ------------------------------------------------------


def test_select_item_voice_future_returns_upcoming():
    item = SimpleNamespace(meeting_date=_dt.date.today() + _dt.timedelta(days=2))
    prompt, voice, version = select_item_voice(item)
    assert voice == "upcoming"
    assert version == ITEM_REWRITE_PROMPT_UPCOMING_VERSION
    assert prompt is SYSTEM_PROMPT_UPCOMING


def test_select_item_voice_today_returns_upcoming():
    """Meeting day stays in forward voice — recast fires next morning."""
    item = SimpleNamespace(meeting_date=_dt.date.today())
    prompt, voice, version = select_item_voice(item)
    assert voice == "upcoming"


def test_select_item_voice_past_returns_completed():
    item = SimpleNamespace(meeting_date=_dt.date.today() - _dt.timedelta(days=7))
    prompt, voice, version = select_item_voice(item)
    assert voice == "completed"
    assert version == ITEM_REWRITE_PROMPT_VERSION
    assert prompt is SYSTEM_PROMPT


def test_select_item_voice_missing_date_returns_completed():
    item = SimpleNamespace(meeting_date=None)
    _, voice, _ = select_item_voice(item)
    assert voice == "completed"


def test_select_item_voice_missing_attribute_returns_completed():
    """Defensive: an item with no meeting_date attribute degrades to completed."""
    item = SimpleNamespace()
    _, voice, _ = select_item_voice(item)
    assert voice == "completed"


# --- select_meeting_voice ---------------------------------------------------


def test_select_meeting_voice_future_returns_upcoming():
    prompt, voice = select_meeting_voice(_dt.date.today() + _dt.timedelta(days=2))
    assert voice == "upcoming"
    assert prompt is MEETING_SYSTEM_UPCOMING


def test_select_meeting_voice_today_returns_upcoming():
    prompt, voice = select_meeting_voice(_dt.date.today())
    assert voice == "upcoming"


def test_select_meeting_voice_past_returns_completed():
    prompt, voice = select_meeting_voice(_dt.date.today() - _dt.timedelta(days=7))
    assert voice == "completed"
    assert prompt is MEETING_SYSTEM


def test_select_meeting_voice_none_date_returns_completed():
    prompt, voice = select_meeting_voice(None)
    assert voice == "completed"


# --- prompt content guards --------------------------------------------------


def test_upcoming_item_prompt_forbids_past_tense_verbs():
    """Prompt-engineering guardrail: forward-voice prompt must explicitly forbid
    past-tense decision verbs so the model rewrites them in conditional voice."""
    forbidden = ["approved", "passed", "enacted", "adopted", "awarded", "decided"]
    for verb in forbidden:
        assert verb in SYSTEM_PROMPT_UPCOMING.lower(), \
            f"forbidden-verb '{verb}' must be called out in upcoming prompt"


def test_upcoming_meeting_prompt_forbids_past_tense_verbs():
    forbidden = ["approved", "passed", "enacted", "adopted", "awarded", "decided"]
    for verb in forbidden:
        assert verb in MEETING_SYSTEM_UPCOMING.lower(), \
            f"forbidden-verb '{verb}' must be called out in upcoming meeting prompt"


def test_upcoming_prompts_mention_forward_voice_phrasings():
    for prompt in (SYSTEM_PROMPT_UPCOMING, MEETING_SYSTEM_UPCOMING):
        text = prompt.lower()
        assert "will consider" in text or "would" in text, \
            "upcoming prompts must teach forward-voice phrasings"
