"""Layer 1 tests for upcoming-meeting forward voice — template-only gates.

Suppresses completed-action AI text on upcoming meetings (headline,
why_it_matters, executive_summary, legacy summary) and flips the
hardcoded consent calendar blurb to forward voice. Pairs with PR #68's
existing Upcoming chip work; this is the body-text companion.

Spec: docs/superpowers/specs/2026-05-18-upcoming-meeting-forward-voice-design.md
"""
from __future__ import annotations

import datetime as _dt
from types import SimpleNamespace

import pytest
from flask import Flask, render_template, render_template_string

from docket.web import create_app
from docket.web.filters import register as register_filters


# --- Fixtures ----------------------------------------------------------------


@pytest.fixture(scope="module")
def app():
    """Real create_app() — gets the `today` context processor (Chicago-anchored)."""
    return create_app()


@pytest.fixture(scope="module")
def app_no_today():
    """Bare Flask app without the today context processor, for the
    `today is defined` test-app safety guard."""
    bare = Flask("test_no_today", template_folder="src/docket/web/templates")
    register_filters(bare)
    bare.add_url_rule(
        "/c/<slug>/meetings/<int:meeting_id>",
        endpoint="public.meeting_detail",
        view_func=lambda slug, meeting_id: "",
    )
    bare.add_url_rule(
        "/c/<slug>/items/<int:item_id>",
        endpoint="public.item_detail",
        view_func=lambda slug, item_id: "",
    )
    return bare


# --- Stub builders -----------------------------------------------------------


def _stub_item(meeting_date, **overrides):
    base = {
        "id": 200,
        "meeting_id": 2232,
        "item_number": "7",
        "title": "Authorize $1.2M contract with Acme Co.",
        "headline": "Council approved $1.2M Acme contract",
        "why_it_matters": "Residents can now access expanded recycling.",
        "summary": None,
        "description": None,
        "topic": None,
        "sponsor": None,
        "section": None,
        "is_consent": False,
        "dollars_amount": None,
        "ai_rewrite_version": 4,
        "ai_metadata": None,
        "processing_status": "completed",
        "data_quality": "ok",
        "extracted_facts": None,
        "meeting_date": meeting_date,
        "municipality_slug": "birmingham",
        "badges": [],
    }
    base.update(overrides)
    return base


def _stub_meeting(meeting_date, **overrides):
    base = dict(
        id=2232,
        title="Regular City Council Meeting",
        meeting_type="regular",
        meeting_date=meeting_date,
        agenda_url="https://bhamal.granicus.com/AgendaViewer.php?view_id=2&event_id=2692",
        minutes_url=None,
        video_url=None,
        source_url=None,
        executive_summary="The council approved a $1.2M contract with Acme.",
        ai_metadata={"phase": "provisional", "confidence": "high"},
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# --- Section snippets --------------------------------------------------------
# Render just the executive-summary block and the consent-blurb block in
# isolation. The full meeting_detail.html requires heavy context (rail,
# masthead, route resolution); these snippets carry the gate logic we're
# verifying. They MUST stay byte-identical to the corresponding blocks in
# `src/docket/web/templates/meeting_detail.html` — drift is a regression.

EXEC_SUMMARY_SNIPPET = """
{% set _is_upcoming = today is defined and meeting.meeting_date and meeting.meeting_date >= today %}
{% if _is_upcoming %}
<section class="exec-summary exec-summary--upcoming">
  <h2 class="exec-summary-heading">Agenda published</h2>
  <p class="exec-summary-body">
    This agenda was published by the city. The meeting hasn't happened yet, so no
    summary of what was decided is available.
    {% if meeting.agenda_url %}
    <a class="link" href="{{ meeting.agenda_url }}" target="_blank" rel="noreferrer">View the agenda ↗</a>
    {% endif %}
  </p>
</section>
{% elif meeting.executive_summary %}
<section class="exec-summary">
  <h2 class="exec-summary-heading">Executive Summary</h2>
  <p class="exec-summary-body">{{ meeting.executive_summary }}</p>
</section>
{% endif %}
"""

CONSENT_BLURB_SNIPPET = """
<p class="t-meta">
    {% if today is defined and meeting.meeting_date and meeting.meeting_date >= today %}
    Items expected to pass as a group without individual discussion unless pulled by a council member.
    {% else %}
    Items passed as a group without individual discussion unless pulled by a council member.
    {% endif %}
</p>
"""


# --- _card_shell upcoming gate (headline + why) ------------------------------


def test_card_shell_upcoming_hides_headline_text(app):
    """On an upcoming meeting, the headline link falls back to item.title."""
    future = _dt.date.today() + _dt.timedelta(days=2)
    item = _stub_item(meeting_date=future)
    with app.test_request_context():
        html = render_template(
            "partials/_card_shell.html",
            item=item,
            municipality={"slug": "birmingham", "id": 1},
            show_meeting_context=False,
            coverage_counts={},
        )
    assert "Authorize $1.2M contract with Acme Co." in html
    assert "Council approved $1.2M Acme contract" not in html


def test_card_shell_upcoming_hides_why_it_matters(app):
    """On an upcoming meeting, the why-it-matters paragraph is suppressed."""
    future = _dt.date.today() + _dt.timedelta(days=2)
    item = _stub_item(meeting_date=future)
    with app.test_request_context():
        html = render_template(
            "partials/_card_shell.html",
            item=item,
            municipality={"slug": "birmingham", "id": 1},
            show_meeting_context=False,
            coverage_counts={},
        )
    assert "Residents can now access expanded recycling." not in html


def test_card_shell_past_meeting_unchanged(app):
    """On a past meeting, headline + why render exactly as before."""
    past = _dt.date.today() - _dt.timedelta(days=7)
    item = _stub_item(meeting_date=past)
    with app.test_request_context():
        html = render_template(
            "partials/_card_shell.html",
            item=item,
            municipality={"slug": "birmingham", "id": 1},
            show_meeting_context=False,
            coverage_counts={},
        )
    assert "Council approved $1.2M Acme contract" in html
    assert "Residents can now access expanded recycling." in html


def test_card_shell_today_undefined_safe(app_no_today):
    """Test-app safety: when `today` is not injected, render baseline (no error).

    Mirrors the same defensive pattern PR #68 used for the Upcoming chip:
    `{% if today is defined and ... %}` so standalone test apps don't blow
    up with UndefinedError.
    """
    future = _dt.date.today() + _dt.timedelta(days=2)
    item = _stub_item(meeting_date=future)
    with app_no_today.test_request_context():
        html = render_template(
            "partials/_card_shell.html",
            item=item,
            municipality={"slug": "birmingham", "id": 1},
            show_meeting_context=False,
            coverage_counts={},
        )
    # No UndefinedError; baseline (past-meeting) rendering — headline shows.
    assert "Council approved $1.2M Acme contract" in html


# --- meeting_detail.html exec-summary gate -----------------------------------


def test_meeting_detail_upcoming_exec_summary_replaced(app):
    """Upcoming meeting renders a static notice in place of executive summary."""
    future = _dt.date.today() + _dt.timedelta(days=2)
    meeting = _stub_meeting(meeting_date=future)
    with app.test_request_context():
        html = render_template_string(EXEC_SUMMARY_SNIPPET, meeting=meeting)
    assert "The council approved a $1.2M contract with Acme." not in html
    assert "hasn't happened yet" in html.lower()
    assert "View the agenda" in html


def test_meeting_detail_past_exec_summary_unchanged(app):
    """Past meeting renders the Sonnet executive_summary unchanged."""
    past = _dt.date.today() - _dt.timedelta(days=7)
    meeting = _stub_meeting(meeting_date=past)
    with app.test_request_context():
        html = render_template_string(EXEC_SUMMARY_SNIPPET, meeting=meeting)
    assert "The council approved a $1.2M contract with Acme." in html


# --- meeting_detail.html consent blurb gate ----------------------------------


def test_meeting_detail_upcoming_consent_blurb_forward(app):
    """Upcoming meeting renders the forward-voice consent calendar blurb."""
    future = _dt.date.today() + _dt.timedelta(days=2)
    meeting = _stub_meeting(meeting_date=future)
    with app.test_request_context():
        html = render_template_string(CONSENT_BLURB_SNIPPET, meeting=meeting)
    assert "expected to pass" in html.lower()
    assert "items passed as a group" not in html.lower()


def test_meeting_detail_past_consent_blurb_completed(app):
    """Past meeting keeps the existing past-tense consent blurb."""
    past = _dt.date.today() - _dt.timedelta(days=7)
    meeting = _stub_meeting(meeting_date=past)
    with app.test_request_context():
        html = render_template_string(CONSENT_BLURB_SNIPPET, meeting=meeting)
    assert "items passed as a group" in html.lower()
    assert "expected to pass" not in html.lower()


# --- card_v2_fallback upcoming gate -----------------------------------------


def test_card_v2_fallback_upcoming_uses_title(app):
    """v2-fallback variant (ai_rewrite_version < 3) — on upcoming meetings,
    the headline falls back to item.title instead of the legacy summary."""
    future = _dt.date.today() + _dt.timedelta(days=2)
    item = _stub_item(
        meeting_date=future,
        ai_rewrite_version=None,
        summary="The council awarded a contract that will benefit residents.",
        headline=None,
    )
    with app.test_request_context():
        html = render_template(
            "partials/card_v2_fallback.html",
            item=item,
            municipality={"slug": "birmingham", "id": 1},
            show_meeting_context=False,
            coverage_counts={},
        )
    assert "Authorize $1.2M contract with Acme Co." in html
    assert "The council awarded a contract" not in html


def test_card_v2_fallback_past_uses_summary(app):
    """v2-fallback past meeting — uses the legacy summary as the headline."""
    past = _dt.date.today() - _dt.timedelta(days=7)
    item = _stub_item(
        meeting_date=past,
        ai_rewrite_version=None,
        summary="The council awarded a contract benefiting residents.",
        headline=None,
    )
    with app.test_request_context():
        html = render_template(
            "partials/card_v2_fallback.html",
            item=item,
            municipality={"slug": "birmingham", "id": 1},
            show_meeting_context=False,
            coverage_counts={},
        )
    assert "The council awarded a contract benefiting residents." in html
