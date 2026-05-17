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
- Consent-items branch has its own (smaller-font, no `is_consent` badge,
  no `description` block) v2 markup that's separately gated.
- Drift detection: the ``_REGULAR_LOOP_BODY`` and ``_CONSENT_LOOP_BODY``
  constants must stay byte-identical to the corresponding `{% else %}`
  branches in ``meeting_detail.html`` (enforced via marker comments in
  the template).

The flag itself only affects rendering — A8 already lifted v3 columns
on ``AgendaItem`` so the dispatcher can read ``item.processing_status``
etc. unconditionally. E6 is the gate; flipping it is a separate
operational step (env var change in the Railway dashboard).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
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


# We snip the ``regular_items`` and ``consent_items`` loop bodies verbatim
# from ``meeting_detail.html`` so we can render them in isolation without
# needing the full meeting / votes / municipality / hero context. The gate
# logic (the ``{% if config.SMART_BREVITY_UI %}`` branching) is what we're
# testing — render the loop body with a list of one item under each flag
# state and verify the v2 vs. v3 markers.
#
# DRIFT WARNING: this string MUST be kept byte-identical to the
# regular-items {% else %} branch in src/docket/web/templates/meeting_detail.html
# (currently around lines 220-270, between the
# ``{# E6-LOOP-BODY-START regular #}`` / ``{# E6-LOOP-BODY-END regular #}``
# markers). When you edit the template's else branch, update this constant
# in lockstep, OR the rendering tests below will start exercising stale
# code. The drift-detection test
# ``test_loop_body_constants_match_template`` enforces this contract — see
# end of file.
_REGULAR_LOOP_BODY = """\
{% for item in regular_items %}
    {% if config.SMART_BREVITY_UI %}
        {% include 'partials/smart_brevity_card.html' %}
    {% else %}
        <div id="item-{{ item.id }}" class="notable-row" style="cursor: default;">
            <div class="notable-num t-mono">
                {% if item.item_number %}{{ item.item_number }}{% else %}—{% endif %}
            </div>
            <div>
                <div class="notable-title">{{ item.title }}</div>
                {% if item.summary %}
                <p class="item-summary">{{ item.summary }}</p>
                {% if item.ai_metadata and item.ai_metadata.confidence == 'low' %}
                <span class="badge badge-review badge-inline">Auto summary — under review</span>
                {% endif %}
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


# DRIFT WARNING: same as above, but for the consent-items {% else %} branch
# in meeting_detail.html (currently around lines 287-330, between the
# ``{# E6-LOOP-BODY-START consent #}`` / ``{# E6-LOOP-BODY-END consent #}``
# markers). The consent branch is intentionally different from the regular
# branch:
#   - smaller-font, muted title (`style="font-size: 13px; ..."`)
#   - no `is_consent` "Consent" badge (every item is consent here)
#   - no `description` block (consent items render terse)
# Spec compliance review flagged this divergence as intentional design.
# Drift-detection test below enforces lockstep.
_CONSENT_LOOP_BODY = """\
{% for item in consent_items %}
    {% if config.SMART_BREVITY_UI %}
        {% include 'partials/smart_brevity_card.html' %}
    {% else %}
        <div id="item-{{ item.id }}" class="notable-row" style="cursor: default;">
            <div class="notable-num t-mono">
                {% if item.item_number %}{{ item.item_number }}{% else %}—{% endif %}
            </div>
            <div>
                <div class="notable-title" style="font-size: 13px; font-weight: 400; color: var(--ink-2);">{{ item.title }}</div>
                {% if item.summary %}
                <p class="item-summary">{{ item.summary }}</p>
                {% if item.ai_metadata and item.ai_metadata.confidence == 'low' %}
                <span class="badge badge-review badge-inline">Auto summary — under review</span>
                {% endif %}
                {% endif %}
                <div class="notable-meta">
                    {% if item.topic %}
                    <span class="chip"><span class="dot"></span>{{ item.topic | topic_name }}</span>
                    {% endif %}
                    {% if item.sponsor %}
                    <span class="t-meta">{{ item.sponsor }}</span>
                    {% endif %}
                </div>
            </div>
            <div class="notable-right">
                {% if item.dollars_amount %}
                <span class="tier tier-{{ item.dollars_amount | dollar_tier }}">
                    ${{ "{:,.0f}".format(item.dollars_amount) }}
                </span>
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


def _render_loop(app, items, *, body=_REGULAR_LOOP_BODY, var="regular_items"):
    """Render a meeting_detail loop body inside ``app``'s context.

    PR C: cards now use url_for('public.meeting_detail', slug=..., meeting_id=...)
    inside the shell, so the test app needs a stub route + the rendered
    context needs ``municipality``.
    """
    existing = {r.endpoint for r in app.url_map.iter_rules()}
    if "public.meeting_detail" not in existing:
        app.add_url_rule(
            "/c/<slug>/meetings/<int:meeting_id>",
            endpoint="public.meeting_detail",
            view_func=lambda slug, meeting_id: "",
        )
    if "public.item_detail" not in existing:
        app.add_url_rule(
            "/c/<slug>/items/<int:item_id>",
            endpoint="public.item_detail",
            view_func=lambda slug, item_id: "",
        )
    with app.test_request_context("/"):
        return render_template_string(
            body,
            **{var: items},
            municipality={"slug": "birmingham", "id": 1},
        )


@pytest.fixture
def app_flag_off():
    return _create_with_env(None)


@pytest.fixture
def app_flag_on():
    return _create_with_env("true")


# --- Rendering tests: regular-items loop -------------------------------------


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


# --- Rendering tests: consent-items loop -------------------------------------


class TestConsentLoopGate:
    """Mirrors TestRendering but for the consent-items branch.

    The consent loop has divergent v2 markup (smaller font, no
    `is_consent` badge, no description block) — so the gate must be
    tested independently. Spec-compliance review caught that the regular
    and consent branches are not byte-identical and should not be
    collapsed.
    """

    def test_consent_flag_off_renders_v2_consent_markup(self, app_flag_off):
        item = make_agenda_item(
            id=20,
            item_number="C-1",
            title="Routine consent: minor purchase",
            topic="contracts",
            summary="Consent summary.",
            description="A description that the consent branch should NOT render.",
            is_consent=True,
        )
        html = _render_loop(
            app_flag_off, [item], body=_CONSENT_LOOP_BODY, var="consent_items"
        )
        assert V2_MARKER in html
        # Consent-loop signature: smaller font on the title.
        assert "font-size: 13px" in html
        # The consent loop intentionally drops the `is_consent` badge —
        # there's no "Consent" pill on each item because every item in
        # this section is consent already.
        assert "badge-consent" not in html
        # The consent loop intentionally drops the `description` block.
        assert "A description that the consent branch should NOT render." not in html
        # No v3 markers leaked through.
        for marker in V3_VARIANT_MARKERS:
            assert marker not in html, (
                f"v3 marker {marker!r} leaked into v2 consent-rendered HTML"
            )

    def test_consent_flag_on_invokes_dispatcher(self, app_flag_on):
        item = make_agenda_item(
            id=21,
            title="Roll Call (consent)",
            processing_status="procedural_skipped",
            data_quality="ok",
            is_consent=True,
        )
        html = _render_loop(
            app_flag_on, [item], body=_CONSENT_LOOP_BODY, var="consent_items"
        )
        assert 'data-variant="procedural"' in html
        # v2 consent wrapper must NOT appear when the flag is on.
        assert V2_MARKER not in html

    def test_consent_flag_off_with_v3_data_still_renders_v2_consent(
        self, app_flag_off
    ):
        """Same lockdown as the regular branch: populated v3 columns must
        not leak into the v2 consent rendering."""
        item = make_agenda_item(
            id=22,
            item_number="C-7",
            title="Consent block: monthly demolitions",
            summary="Legacy consent summary.",
            topic="housing",
            is_consent=True,
            # v3 columns populated — must be ignored under flag-off.
            processing_status="completed",
            data_quality="ok",
            ai_rewrite_version=3,
            headline="Six demolitions cleared at $42K total",
            why_it_matters="Routine batch; no policy shift.",
        )
        html = _render_loop(
            app_flag_off, [item], body=_CONSENT_LOOP_BODY, var="consent_items"
        )
        assert V2_MARKER in html
        assert "Legacy consent summary." in html
        assert "Six demolitions cleared" not in html
        assert "Routine batch" not in html
        for marker in V3_VARIANT_MARKERS:
            assert marker not in html


# --- Drift detection ---------------------------------------------------------


_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "docket"
    / "web"
    / "templates"
    / "meeting_detail.html"
)


def _extract_else_branch(template_text: str, marker_name: str) -> str:
    """Extract text between the E6-LOOP-BODY-{START,END} markers.

    Returns the body verbatim, NOT including the marker comments
    themselves, but INCLUDING surrounding whitespace/indentation between
    them. The constants above are compared against this with their
    surrounding indentation normalized away (see test below).
    """
    pattern = (
        r"\{#\s*E6-LOOP-BODY-START\s+" + re.escape(marker_name) + r"\s*#\}"
        r"(.*?)"
        r"\{#\s*E6-LOOP-BODY-END\s+" + re.escape(marker_name) + r"\s*#\}"
    )
    match = re.search(pattern, template_text, re.DOTALL)
    assert match is not None, (
        f"E6-LOOP-BODY markers for {marker_name!r} not found in "
        f"meeting_detail.html — did the template lose its drift-detection "
        f"markers? See test_loop_body_constants_match_template docstring."
    )
    return match.group(1)


def _normalize(s: str) -> str:
    """Collapse leading whitespace on each non-empty line.

    The template indents the v2 markup by 16 spaces (inside `<section>` →
    `<div class="notable-list">` → `{% for %}` → `{% else %}`). The test
    constant indents by 8 spaces (inside `{% for %}` → `{% else %}`).
    Compare them with leading whitespace stripped per line.
    """
    return "\n".join(line.lstrip() for line in s.splitlines() if line.strip())


def test_loop_body_constants_match_template():
    """Enforce that ``_REGULAR_LOOP_BODY`` and ``_CONSENT_LOOP_BODY``
    stay byte-identical to the corresponding ``{% else %}`` branches in
    ``meeting_detail.html``.

    The template marks the bodies with ``{# E6-LOOP-BODY-START regular #}``
    / ``{# E6-LOOP-BODY-END regular #}`` (and likewise for ``consent``).
    This test extracts what's between them and asserts that the inner v2
    markup is a substring of the corresponding test constant — modulo
    leading-whitespace differences (the template's branch is more deeply
    nested than the test constant, but the inner markup is the same).

    If you edit the template's ``{% else %}`` branch and this test
    fails, update the constants above to match. That's the contract:
    the test is rendering the same code that ships.
    """
    template_text = _TEMPLATE_PATH.read_text()

    regular_body = _extract_else_branch(template_text, "regular")
    consent_body = _extract_else_branch(template_text, "consent")

    # Each constant is the full `{% for %}{% if %}{% include %}{% else %}…{% endif %}{% endfor %}`
    # wrapping. The template body between markers is just the v2 inner
    # markup (the `{% else %}` body), NOT the for/if/include scaffolding.
    # So we assert the normalized template body appears in the normalized
    # constant.
    normalized_regular_constant = _normalize(_REGULAR_LOOP_BODY)
    normalized_regular_template = _normalize(regular_body)
    assert normalized_regular_template in normalized_regular_constant, (
        "Drift detected: the regular-items {% else %} branch in "
        "meeting_detail.html no longer matches _REGULAR_LOOP_BODY in "
        "test_smart_brevity_ui_flag.py. Update the constant in lockstep "
        "with the template."
    )

    normalized_consent_constant = _normalize(_CONSENT_LOOP_BODY)
    normalized_consent_template = _normalize(consent_body)
    assert normalized_consent_template in normalized_consent_constant, (
        "Drift detected: the consent-items {% else %} branch in "
        "meeting_detail.html no longer matches _CONSENT_LOOP_BODY in "
        "test_smart_brevity_ui_flag.py. Update the constant in lockstep "
        "with the template."
    )
