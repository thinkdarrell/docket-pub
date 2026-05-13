"""Snapshot tests for the Smart Brevity Card variant dispatcher.

Covers `partials/smart_brevity_card.html` — the 7-branch state machine
defined in spec §6.1. Each test builds a fake `item` dict that matches
exactly one branch and asserts the rendered HTML carries that variant's
unique `data-variant="..."` marker (and not any other variant's).
"""

from __future__ import annotations

import pytest
from flask import Flask, render_template

from tests.unit.conftest import make_agenda_item


# Variants and their unique data-variant markers (set on the root <article>
# of each variant partial). Must stay in sync with each card_*.html.
ALL_MARKERS = {
    "failed",
    "degraded",
    "procedural",
    "verification_pending",
    "smart_brevity",
    "v2_fallback",
    "pending",
}


@pytest.fixture(scope="module")
def app():
    """Minimal Flask app pointed at the docket templates + filters.

    We register only the dollar_tier / topic_name template filters that
    the partials depend on. No DB, no blueprints.
    """
    flask_app = Flask(
        "test_smart_brevity_dispatcher",
        template_folder="src/docket/web/templates",
    )

    # Register the real Jinja filters (order_badges, format_date,
    # format_timestamp, format_dollars, dollar_tier) — production parity.
    # E5 added ``format_dollars`` + reshaped ``dollar_tier`` to return a
    # NamedTuple; the new ``_facts_strip.html`` partial pulls in the
    # WCAG dollar tier sub-partial which requires both filters.
    from docket.web import source_security
    from docket.web.filters import register as register_filters

    register_filters(flask_app)

    @flask_app.template_filter("topic_name")
    def _topic_name(slug):
        return slug or ""

    # The card variants transitively include source_anchor_button.html
    # which calls the is_source_url_safe Jinja global. Use a permissive
    # test allowlist (production wires this via create_app from the DB).
    flask_app.jinja_env.globals["is_source_url_safe"] = (
        lambda url: source_security.is_url_safe(
            url,
            frozenset({"example.com", "birminghamal.gov"}),
        )
    )

    return flask_app


def _render(app, item):
    # PR C: shell-based variants use url_for('public.meeting_detail', ...)
    # which needs a request context + a stub route + a municipality.
    if "public.meeting_detail" not in {r.endpoint for r in app.url_map.iter_rules()}:
        app.add_url_rule(
            "/c/<slug>/meetings/<int:meeting_id>",
            endpoint="public.meeting_detail",
            view_func=lambda slug, meeting_id: "",
        )
    with app.test_request_context():
        return render_template(
            "partials/smart_brevity_card.html",
            item=item,
            municipality={"slug": "birmingham", "id": 1},
        )


def _assert_only_variant(html: str, expected: str) -> None:
    """Assert the rendered HTML has exactly the expected variant marker."""
    assert (
        f'data-variant="{expected}"' in html
    ), f"expected data-variant={expected!r} in:\n{html}"
    for other in ALL_MARKERS - {expected}:
        assert (
            f'data-variant="{other}"' not in html
        ), f"unexpected data-variant={other!r} leaked into {expected} variant:\n{html}"


# --- Per-variant tests -------------------------------------------------------


class TestDispatcher:
    def test_failed_permanent_routes_to_card_failed(self, app):
        item = make_agenda_item(
            id=1,
            title="Resolution amending agreement #2024-12-345",
            processing_status="failed_permanent",
        )
        html = _render(app, item)
        _assert_only_variant(html, "failed")
        # PR C: pill text is lowercase per the compact-scan design.
        assert "processing error" in html
        assert "Resolution amending agreement #2024-12-345" in html

    def test_data_quality_skipped_routes_to_degraded(self, app):
        item = make_agenda_item(
            id=2,
            title="Resolution authorizing payment to ABC Construction Inc.",
            processing_status="data_quality_skipped",
            data_quality="no_text_layer",
        )
        html = _render(app, item)
        _assert_only_variant(html, "degraded")
        # PR C: phrasing changed to "OCR needed".
        assert "OCR needed" in html

    def test_data_quality_no_agenda_text_routes_to_degraded(self, app):
        item = make_agenda_item(
            id=3,
            title="Some item with no agenda text",
            processing_status="data_quality_skipped",
            data_quality="no_agenda_text",
        )
        html = _render(app, item)
        _assert_only_variant(html, "degraded")
        # PR C: pill text lowercase.
        assert "no agenda text" in html

    def test_failed_takes_precedence_over_degraded(self, app):
        """failed_permanent + data_quality both set -> failed wins (top of dispatcher)."""
        item = make_agenda_item(
            id=4,
            title="Both failed and degraded",
            processing_status="failed_permanent",
            data_quality="no_text_layer",
        )
        html = _render(app, item)
        _assert_only_variant(html, "failed")

    def test_data_quality_ok_does_not_route_to_degraded(self, app):
        """data_quality='ok' is a happy state — should NOT trip the degraded branch."""
        item = make_agenda_item(
            id=5,
            title="Healthy item with v2 summary",
            processing_status="completed",
            data_quality="ok",
            ai_rewrite_version=2,
            summary="v2 summary text",
        )
        html = _render(app, item)
        _assert_only_variant(html, "v2_fallback")

    def test_procedural_skipped_routes_to_procedural(self, app):
        item = make_agenda_item(
            id=6,
            title="Roll Call",
            processing_status="procedural_skipped",
            data_quality="ok",
        )
        html = _render(app, item)
        _assert_only_variant(html, "procedural")
        assert "Roll Call" in html

    def test_cross_stage_conflict_routes_to_verification_pending(self, app):
        item = make_agenda_item(
            id=7,
            title="Flock contract amendment",
            headline="Sole-source: Flock licenses extended 5 years for $1.8M",
            why_it_matters="Higher per-camera rates affect surveillance budget.",
            processing_status="cross_stage_conflict",
            data_quality="ok",
            ai_rewrite_version=3,
            summary="older v2 summary",
            counterparty="Flock Safety Inc.",
            funding_source="general_fund",
            action_type="contract_amendment",
        )
        html = _render(app, item)
        _assert_only_variant(html, "verification_pending")
        assert "Verification in progress" in html
        # Tooltip-only — no modal / hx-get endpoint
        assert "hx-get" not in html

    def test_v3_completed_routes_to_smart_brevity(self, app):
        item = make_agenda_item(
            id=8,
            title="Title fallback (should not show)",
            headline="Sole-source: Flock licenses extended 5 years for $1.8M",
            why_it_matters="Higher per-camera rates affect surveillance budget in Wards 4-7.",
            processing_status="completed",
            data_quality="ok",
            ai_rewrite_version=3,
            dollars_amount=1800000,
            counterparty="Flock Safety Inc.",
            funding_source="general_fund",
            procurement_method="sole_source",
            action_type="contract_amendment",
            location={"ward_or_district": "Wards 4-7"},
        )
        html = _render(app, item)
        _assert_only_variant(html, "smart_brevity")
        # Headline preferred over title
        assert "Sole-source: Flock licenses extended" in html
        assert "Title fallback" not in html
        # Facts strip pulls from extracted_facts (counterparty rendered).
        assert "Flock Safety Inc." in html
        # NOTE: Dollar-tier markup assertions are temporarily relaxed during
        # PR C transition — PR C moves the dollar chip from the facts strip
        # to the shell's meta line. The `$1.8M` chip will re-appear once
        # card_smart_brevity.html adopts _card_shell.html (PR C Task 3),
        # at which point assertions on `dollar-chip--red` + `$1.8M` get
        # re-added here.

    def test_v3_smart_brevity_falls_back_to_title_when_no_headline(self, app):
        """ai_rewrite_version=3 but headline missing — render title in headline slot."""
        item = make_agenda_item(
            id=9,
            title="Some council action",
            processing_status="completed",
            data_quality="ok",
            ai_rewrite_version=3,
            extracted_facts={},
        )
        html = _render(app, item)
        _assert_only_variant(html, "smart_brevity")
        assert "Some council action" in html

    def test_v2_summary_routes_to_v2_fallback(self, app):
        item = make_agenda_item(
            id=10,
            title="Resolution authorizing payment to ABC Construction Inc.",
            processing_status="completed",
            data_quality="ok",
            ai_rewrite_version=2,
            summary="Resolution authorizing payment to ABC Construction Inc. for landscape services.",
        )
        html = _render(app, item)
        _assert_only_variant(html, "v2_fallback")
        # PR C: v2_fallback no longer renders a pill. The summary itself
        # is truncated to 80 chars and rendered as the headline.
        assert "Resolution authorizing payment to ABC Construction" in html

    def test_no_outputs_routes_to_pending(self, app):
        item = make_agenda_item(
            id=11,
            title="Brand new item, not yet processed",
            processing_status="pending",
        )
        html = _render(app, item)
        _assert_only_variant(html, "pending")
        # PR C: pending pill says "summary updating" now.
        assert "summary updating" in html

    def test_missing_fields_safe_default(self, app):
        """A barebones AgendaItem (no AI columns at all) still renders — defaults to pending."""
        item = make_agenda_item(
            id=12,
            title="Item with only a title",
        )
        html = _render(app, item)
        _assert_only_variant(html, "pending")

    def test_dispatcher_order_failed_beats_v3(self, app):
        """processing_status='failed_permanent' wins even if ai_rewrite_version=3."""
        item = make_agenda_item(
            id=13,
            title="Edge case",
            processing_status="failed_permanent",
            data_quality="ok",
            ai_rewrite_version=3,
            headline="Should not show",
            why_it_matters="Should not show",
            summary="Should not show",
        )
        html = _render(app, item)
        _assert_only_variant(html, "failed")
        assert "Should not show" not in html

    def test_dispatcher_order_degraded_beats_procedural(self, app):
        """data_quality != 'ok' beats procedural_skipped (degraded is checked first)."""
        item = make_agenda_item(
            id=14,
            title="Roll Call but document is missing",
            processing_status="procedural_skipped",
            data_quality="no_agenda_text",
        )
        html = _render(app, item)
        _assert_only_variant(html, "degraded")


# --- Review-fix coverage -----------------------------------------------------


class TestV2FallbackFields:
    """v2 fallback in PR C is a compact-scan card like all others: the
    legacy summary is truncated to 80 chars and rendered as the headline
    link; topic / sponsor / description / dollars chrome is intentionally
    removed (clicking the headline takes the citizen to meeting_detail
    where the full v2 context is rendered). The class is retained for
    the omission test which still guards against `None` leaking into
    the rendered output."""

    def test_v2_fallback_omits_optional_fields_when_absent(self, app):
        """When topic/sponsor/description/dollars are missing, v2 fallback
        should still render cleanly (no 'None' placeholders, no broken markup)."""
        item = make_agenda_item(
            id=101,
            title="Bare-bones v2 item",
            processing_status="completed",
            data_quality="ok",
            ai_rewrite_version=2,
            summary="Short v2 summary.",
        )
        html = _render(app, item)
        _assert_only_variant(html, "v2_fallback")
        assert "Short v2 summary." in html
        # Don't leak None
        assert "None" not in html


# NOTE: TestSourceLinkSchemeValidation removed in PR C — the cards no
# longer render `_source_link_stub.html`; the source-anchor button
# affordance lives on the meeting_detail page reached via the headline
# link. The XSS protection contract (javascript:, data:, protocol-
# relative URL rejection) is fully covered by:
#   - tests/unit/test_source_anchor.py (rendering of the partial)
#   - tests/unit/test_source_security.py (is_url_safe helper)


class TestVerificationPendingContent:
    """Per spec §6.1, the verification-pending variant renders the v3
    headline + why + facts at full fidelity, with only the verifying
    pill as a status hint. The source-link assertion moved out of this
    class in PR C — cards no longer carry source-anchor buttons; that
    affordance lives on the meeting_detail page reached via the
    headline link. Source-link XSS protection coverage is in
    test_source_anchor.py + test_source_security.py.
    """

    def test_verification_pending_renders_facts_at_full_fidelity(self, app):
        item = make_agenda_item(
            id=300,
            title="Flock contract amendment",
            headline="Sole-source: Flock licenses extended 5 years for $1.8M",
            why_it_matters="Higher per-camera rates affect surveillance budget.",
            processing_status="cross_stage_conflict",
            data_quality="ok",
            ai_rewrite_version=3,
            dollars_amount=1800000,
            counterparty="Flock Safety Inc.",
            funding_source="general_fund",
            action_type="contract_amendment",
        )
        html = _render(app, item)
        _assert_only_variant(html, "verification_pending")
        # Pill stays
        assert "Verification in progress" in html
        # Facts strip rendered (counterparty, funding).
        assert "Flock Safety Inc." in html
        assert "General Fund" in html
        # Headline + why_it_matters still render
        assert "Sole-source: Flock licenses extended" in html
        assert "surveillance budget" in html
        # Still no modal / hx-get
        assert "hx-get" not in html
