"""Tests for the SMART_BREVITY_UI feature flag (Phase 2 / Track 3 / E6).

The flag gates v3 Smart Brevity Card rendering in
``meeting_detail.html``. When false (default), the meeting detail page
renders the legacy v2 ``notable-row`` markup verbatim. When true, every
agenda item is dispatched through ``partials/smart_brevity_card.html``
and routes to one of the 7 v3 variants based on Wave 0 / Phase 2
columns on ``AgendaItem``.

These tests cover:

- Default-off behavior (no env var → flag is False).
- Explicit ``"true"`` / ``"false"`` parsing.
- Whitespace-and-case tolerance (``" TRUE\\n"`` etc.).
- v2 markup ships when flag is off, even when v3 columns are populated
  (so Wave 0 / Phase 3 backfill data does NOT leak into citizen view
  before the operator flips ``SMART_BREVITY_UI=true`` in Railway).
- Dispatcher output appears when flag is on.

The flag itself only affects rendering — A8 already lifted v3 columns
on ``AgendaItem`` so the dispatcher can read ``item.processing_status``
etc. unconditionally. E6 is the gate; flipping it is a separate
operational step (env var change in the Railway dashboard).
"""

from __future__ import annotations

import os
from unittest import mock

import pytest
from flask import render_template_string

from docket.web import create_app
from tests.unit.conftest import make_agenda_item


# --- App factory helpers ------------------------------------------------------


def _create_with_env(env_value):
    """Create a Flask app with ``SMART_BREVITY_UI`` set to ``env_value``.

    ``env_value=None`` simulates an unset env var (the default-false path).
    """
    env_patch = {} if env_value is None else {"SMART_BREVITY_UI": env_value}
    # ``clear=False`` so we keep the rest of the env (DATABASE_URL etc. for
    # config import). We only want to control the SMART_BREVITY_UI key.
    with mock.patch.dict(os.environ, env_patch, clear=False):
        if env_value is None:
            os.environ.pop("SMART_BREVITY_UI", None)
        return create_app()


# --- Flag parsing -------------------------------------------------------------


class TestFlagParsing:
    """app.config['SMART_BREVITY_UI'] should be a bool driven by the env var."""

    def test_flag_unset_defaults_to_false(self):
        app = _create_with_env(None)
        assert app.config["SMART_BREVITY_UI"] is False

    def test_flag_explicitly_false(self):
        app = _create_with_env("false")
        assert app.config["SMART_BREVITY_UI"] is False

    def test_flag_explicitly_true(self):
        app = _create_with_env("true")
        assert app.config["SMART_BREVITY_UI"] is True

    def test_flag_uppercase_true(self):
        app = _create_with_env("TRUE")
        assert app.config["SMART_BREVITY_UI"] is True

    def test_flag_mixed_case_true(self):
        app = _create_with_env("True")
        assert app.config["SMART_BREVITY_UI"] is True

    def test_flag_whitespace_padded_true(self):
        # Railway dashboard sometimes carries trailing whitespace/newline.
        app = _create_with_env(" TRUE\n")
        assert app.config["SMART_BREVITY_UI"] is True

    def test_flag_one_does_not_match(self):
        # Only the literal string "true" enables — "1" / "yes" do not.
        app = _create_with_env("1")
        assert app.config["SMART_BREVITY_UI"] is False

    def test_flag_yes_does_not_match(self):
        app = _create_with_env("yes")
        assert app.config["SMART_BREVITY_UI"] is False

    def test_flag_empty_string_is_false(self):
        app = _create_with_env("")
        assert app.config["SMART_BREVITY_UI"] is False


# --- Rendering: meeting_detail iteration body --------------------------------


# We snip the ``regular_items`` loop body verbatim from
# ``meeting_detail.html`` so we can render it in isolation without needing
# the full meeting / votes / municipality / hero context. The gate logic
# (the ``{% if config.SMART_BREVITY_UI %}`` branching) is what we're
# testing — render the loop body with a list of one item under each flag
# state and verify the v2 vs. v3 markers.

_REGULAR_LOOP_BODY = """\
{% for item in regular_items %}
    {% if config.SMART_BREVITY_UI %}
        {% include 'partials/smart_brevity_card.html' %}
    {% else %}
        <div class="notable-row" style="cursor: default;">
            <div class="notable-num t-mono">
                {% if item.item_number %}{{ item.item_number }}{% else %}—{% endif %}
            </div>
            <div>
                <div class="notable-title">{{ item.title }}</div>
                {% if item.summary %}
                <p class="item-summary">{{ item.summary }}</p>
                {% endif %}
                <div class="notable-meta">
                    {% if item.topic %}
                    <span class="chip"><span class="dot"></span>{{ item.topic | topic_name }}</span>
                    {% endif %}
                    {% if item.sponsor %}
                    <span class="t-meta">{{ item.sponsor }}</span>
                    {% endif %}
                </div>
                {% if item.description %}
                <div class="t-meta" style="margin-top: 6px; line-height: 1.5;">{{ item.description }}</div>
                {% endif %}
            </div>
            <div class="notable-right">
                {% if item.dollars_amount %}
                <span class="tier tier-{{ item.dollars_amount | dollar_tier }}">
                    ${{ "{:,.0f}".format(item.dollars_amount) }}
                </span>
                {% endif %}
                {% if item.is_consent %}
                <span class="badge-consent">Consent</span>
                {% endif %}
            </div>
        </div>
    {% endif %}
{% endfor %}
"""


# Markers from card_*.html partials — see test_smart_brevity_card_dispatcher.py.
V3_VARIANT_MARKERS = (
    'data-variant="failed"',
    'data-variant="degraded"',
    'data-variant="procedural"',
    'data-variant="verification_pending"',
    'data-variant="smart_brevity"',
    'data-variant="v2_fallback"',
    'data-variant="pending"',
)

V2_MARKER = 'class="notable-row"'


def _render_loop(app, items):
    """Render the regular-items loop body inside ``app``'s context."""
    with app.test_request_context("/"):
        return render_template_string(_REGULAR_LOOP_BODY, regular_items=items)


@pytest.fixture
def app_flag_off():
    return _create_with_env(None)


@pytest.fixture
def app_flag_on():
    return _create_with_env("true")


# --- Rendering tests ----------------------------------------------------------


class TestRendering:
    def test_flag_off_by_default_renders_v2(self, app_flag_off):
        item = make_agenda_item(
            id=1,
            item_number="1",
            title="Resolution authorizing payment to ABC Construction Inc.",
            topic="contracts",
            sponsor="Council President",
            summary="Payment for landscape services.",
        )
        html = _render_loop(app_flag_off, [item])
        assert V2_MARKER in html
        assert "Resolution authorizing payment" in html
        # No v3 dispatcher markers leaked through.
        for marker in V3_VARIANT_MARKERS:
            assert marker not in html, (
                f"v3 marker {marker!r} leaked into v2-rendered HTML"
            )

    def test_flag_explicitly_false_renders_v2(self):
        app = _create_with_env("false")
        item = make_agenda_item(id=2, title="Some item")
        html = _render_loop(app, [item])
        assert V2_MARKER in html
        for marker in V3_VARIANT_MARKERS:
            assert marker not in html

    def test_flag_explicitly_true_renders_v3_dispatcher(self, app_flag_on):
        # Constructing a procedural item — dispatcher should route to
        # card_procedural.html (data-variant="procedural").
        item = make_agenda_item(
            id=3,
            title="Roll Call",
            processing_status="procedural_skipped",
            data_quality="ok",
        )
        html = _render_loop(app_flag_on, [item])
        assert 'data-variant="procedural"' in html
        # v2 wrapper must NOT appear when the flag is on.
        assert V2_MARKER not in html

    def test_flag_off_with_v3_data_still_renders_v2(self, app_flag_off):
        """Locks the contract: even if A8 / Wave 0 / Phase 3 have populated v3
        columns on the row, the v2 path renders until the operator flips
        SMART_BREVITY_UI=true. Prevents accidental leak of v3 output to
        citizens before the operational sign-off."""
        item = make_agenda_item(
            id=4,
            item_number="12",
            title="Sole-source: Flock licenses",
            summary="Legacy v2 summary.",
            topic="public_safety",
            # v3 columns populated — but flag is off, so these MUST be ignored.
            processing_status="completed",
            data_quality="ok",
            ai_rewrite_version=3,
            headline="Sole-source: Flock licenses extended 5 years for $1.8M",
            why_it_matters="Higher per-camera rates affect surveillance budget.",
        )
        html = _render_loop(app_flag_off, [item])
        assert V2_MARKER in html
        # v3 headline / why_it_matters MUST NOT render in the v2 path.
        assert "Higher per-camera rates" not in html
        # v2 path renders title + legacy summary, not the v3 headline.
        assert "Legacy v2 summary." in html
        for marker in V3_VARIANT_MARKERS:
            assert marker not in html

    def test_flag_on_renders_dispatcher_for_each_item(self, app_flag_on):
        items = [
            make_agenda_item(
                id=10,
                title="Roll Call",
                processing_status="procedural_skipped",
                data_quality="ok",
            ),
            make_agenda_item(
                id=11,
                title="Brand new item",
                processing_status="pending",
            ),
        ]
        html = _render_loop(app_flag_on, items)
        assert 'data-variant="procedural"' in html
        assert 'data-variant="pending"' in html
