"""Snapshot tests for the Smart Brevity Card variant dispatcher.

Covers `partials/smart_brevity_card.html` — the 7-branch state machine
defined in spec §6.1. Each test builds a fake `item` dict that matches
exactly one branch and asserts the rendered HTML carries that variant's
unique `data-variant="..."` marker (and not any other variant's).
"""

from __future__ import annotations

import pytest
from flask import Flask, render_template


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
    with app.app_context():
        return render_template("partials/smart_brevity_card.html", item=item)


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
        item = {
            "id": 1,
            "title": "Resolution amending agreement #2024-12-345",
            "processing_status": "failed_permanent",
            "data_quality": None,
            "ai_rewrite_version": None,
            "summary": None,
            "extracted_facts": None,
        }
        html = _render(app, item)
        _assert_only_variant(html, "failed")
        assert "Processing Error" in html
        assert "Resolution amending agreement #2024-12-345" in html

    def test_data_quality_skipped_routes_to_degraded(self, app):
        item = {
            "id": 2,
            "title": "Resolution authorizing payment to ABC Construction Inc.",
            "processing_status": "data_quality_skipped",
            "data_quality": "no_text_layer",
            "ai_rewrite_version": None,
            "summary": None,
            "extracted_facts": None,
        }
        html = _render(app, item)
        _assert_only_variant(html, "degraded")
        assert "needs OCR" in html

    def test_data_quality_no_agenda_text_routes_to_degraded(self, app):
        item = {
            "id": 3,
            "title": "Some item with no agenda text",
            "processing_status": "data_quality_skipped",
            "data_quality": "no_agenda_text",
            "ai_rewrite_version": None,
            "summary": None,
        }
        html = _render(app, item)
        _assert_only_variant(html, "degraded")
        assert "No agenda text" in html

    def test_failed_takes_precedence_over_degraded(self, app):
        """failed_permanent + data_quality both set -> failed wins (top of dispatcher)."""
        item = {
            "id": 4,
            "title": "Both failed and degraded",
            "processing_status": "failed_permanent",
            "data_quality": "no_text_layer",
            "ai_rewrite_version": None,
            "summary": None,
        }
        html = _render(app, item)
        _assert_only_variant(html, "failed")

    def test_data_quality_ok_does_not_route_to_degraded(self, app):
        """data_quality='ok' is a happy state — should NOT trip the degraded branch."""
        item = {
            "id": 5,
            "title": "Healthy item with v2 summary",
            "processing_status": "completed",
            "data_quality": "ok",
            "ai_rewrite_version": 2,
            "summary": "v2 summary text",
        }
        html = _render(app, item)
        _assert_only_variant(html, "v2_fallback")

    def test_procedural_skipped_routes_to_procedural(self, app):
        item = {
            "id": 6,
            "title": "Roll Call",
            "processing_status": "procedural_skipped",
            "data_quality": "ok",
            "ai_rewrite_version": None,
            "summary": None,
        }
        html = _render(app, item)
        _assert_only_variant(html, "procedural")
        assert "Roll Call" in html

    def test_cross_stage_conflict_routes_to_verification_pending(self, app):
        item = {
            "id": 7,
            "title": "Flock contract amendment",
            "headline": "Sole-source: Flock licenses extended 5 years for $1.8M",
            "why_it_matters": "Higher per-camera rates affect surveillance budget.",
            "processing_status": "cross_stage_conflict",
            "data_quality": "ok",
            "ai_rewrite_version": 3,
            "summary": "older v2 summary",
            "extracted_facts": {
                "counterparty": "Flock Safety Inc.",
                "funding_source": "general_fund",
                "action_type": "contract_amendment",
            },
        }
        html = _render(app, item)
        _assert_only_variant(html, "verification_pending")
        assert "Verification in progress" in html
        # Tooltip-only — no modal / hx-get endpoint
        assert "hx-get" not in html

    def test_v3_completed_routes_to_smart_brevity(self, app):
        item = {
            "id": 8,
            "title": "Title fallback (should not show)",
            "headline": "Sole-source: Flock licenses extended 5 years for $1.8M",
            "why_it_matters": "Higher per-camera rates affect surveillance budget in Wards 4-7.",
            "processing_status": "completed",
            "data_quality": "ok",
            "ai_rewrite_version": 3,
            "summary": None,
            "dollars_amount": 1800000,
            "extracted_facts": {
                "counterparty": "Flock Safety Inc.",
                "funding_source": "general_fund",
                "procurement_method": "sole_source",
                "action_type": "contract_amendment",
                "location": {
                    "ward_or_district": "Wards 4-7",
                },
            },
        }
        html = _render(app, item)
        _assert_only_variant(html, "smart_brevity")
        # Headline preferred over title
        assert "Sole-source: Flock licenses extended" in html
        assert "Title fallback" not in html
        # Facts strip pulls from extracted_facts
        assert "Flock Safety Inc." in html
        # Dollar tier rendered (red tier for $1.8M).
        # E5 changed the rendered format: amounts >= $1M abbreviate to
        # ``$N.NM`` (decision #71). Triple-redundant WCAG signal: color
        # class + symbol + sr-only label.
        assert "dollars--red" in html
        assert "$1.8M" in html
        assert "($$$$)" in html

    def test_v3_smart_brevity_falls_back_to_title_when_no_headline(self, app):
        """ai_rewrite_version=3 but headline missing — render title in headline slot."""
        item = {
            "id": 9,
            "title": "Some council action",
            "headline": None,
            "why_it_matters": None,
            "processing_status": "completed",
            "data_quality": "ok",
            "ai_rewrite_version": 3,
            "summary": None,
            "extracted_facts": {},
        }
        html = _render(app, item)
        _assert_only_variant(html, "smart_brevity")
        assert "Some council action" in html

    def test_v2_summary_routes_to_v2_fallback(self, app):
        item = {
            "id": 10,
            "title": "Resolution authorizing payment to ABC Construction Inc.",
            "processing_status": "completed",
            "data_quality": "ok",
            "ai_rewrite_version": 2,
            "summary": "Resolution authorizing payment to ABC Construction Inc. for landscape services.",
        }
        html = _render(app, item)
        _assert_only_variant(html, "v2_fallback")
        assert "summary updating" in html

    def test_no_outputs_routes_to_pending(self, app):
        item = {
            "id": 11,
            "title": "Brand new item, not yet processed",
            "processing_status": "pending",
            "data_quality": None,
            "ai_rewrite_version": None,
            "summary": None,
        }
        html = _render(app, item)
        _assert_only_variant(html, "pending")
        assert "awaiting summary" in html

    def test_missing_fields_safe_default(self, app):
        """A barebones dict (no AI columns at all) still renders — defaults to pending."""
        item = {
            "id": 12,
            "title": "Item with only a title",
        }
        html = _render(app, item)
        _assert_only_variant(html, "pending")

    def test_dispatcher_order_failed_beats_v3(self, app):
        """processing_status='failed_permanent' wins even if ai_rewrite_version=3."""
        item = {
            "id": 13,
            "title": "Edge case",
            "processing_status": "failed_permanent",
            "data_quality": "ok",
            "ai_rewrite_version": 3,
            "headline": "Should not show",
            "why_it_matters": "Should not show",
            "summary": "Should not show",
        }
        html = _render(app, item)
        _assert_only_variant(html, "failed")
        assert "Should not show" not in html

    def test_dispatcher_order_degraded_beats_procedural(self, app):
        """data_quality != 'ok' beats procedural_skipped (degraded is checked first)."""
        item = {
            "id": 14,
            "title": "Roll Call but document is missing",
            "processing_status": "procedural_skipped",
            "data_quality": "no_agenda_text",
            "ai_rewrite_version": None,
            "summary": None,
        }
        html = _render(app, item)
        _assert_only_variant(html, "degraded")


# --- Review-fix coverage -----------------------------------------------------


class TestV2FallbackFields:
    """v2 fallback must render the pre-E1 fields (topic / sponsor /
    description / dollars_amount with tier color). Production today is
    overwhelmingly v2, so this is the dominant rendering case — the
    E1 partial regressed it by only showing title + summary."""

    def test_v2_fallback_renders_topic_sponsor_description_dollars(self, app):
        item = {
            "id": 100,
            "title": "Resolution authorizing payment to ABC Construction Inc.",
            "processing_status": "completed",
            "data_quality": "ok",
            "ai_rewrite_version": 2,
            "summary": "Payment for landscape services.",
            "topic": "contracts",
            "sponsor": "Council President Smith",
            "description": "ABC Construction completed grounds maintenance for Q1.",
            "dollars_amount": 75000,
        }
        html = _render(app, item)
        _assert_only_variant(html, "v2_fallback")
        # Topic chip
        assert "contracts" in html
        # Sponsor line
        assert "Council President Smith" in html
        # Description text
        assert "ABC Construction completed grounds maintenance for Q1." in html
        # Dollars + tier color (75K → yellow tier)
        assert "75,000" in html
        assert "tier-yellow" in html

    def test_v2_fallback_omits_optional_fields_when_absent(self, app):
        """When topic/sponsor/description/dollars are missing, v2 fallback
        should still render cleanly (no 'None' placeholders, no broken markup)."""
        item = {
            "id": 101,
            "title": "Bare-bones v2 item",
            "processing_status": "completed",
            "data_quality": "ok",
            "ai_rewrite_version": 2,
            "summary": "Short v2 summary.",
        }
        html = _render(app, item)
        _assert_only_variant(html, "v2_fallback")
        assert "Short v2 summary." in html
        # Don't leak None
        assert "None" not in html


class TestSourceLinkSchemeValidation:
    """The `_source_link_stub.html` partial must reject any URL whose
    scheme isn't http://, https://, or / (relative). javascript: URLs
    are an XSS vector — they must be omitted entirely (not rendered as
    a clickable link)."""

    def test_javascript_url_is_omitted(self, app):
        item = {
            "id": 200,
            "title": "Item with malicious source URL",
            "processing_status": "failed_permanent",
            "source_anchor": {"url": "javascript:alert(1)"},
        }
        html = _render(app, item)
        _assert_only_variant(html, "failed")
        # Link must not be emitted at all
        assert 'href="javascript:' not in html
        assert "javascript:alert" not in html
        assert "view-source" not in html

    def test_https_url_is_rendered_with_target_blank(self, app):
        item = {
            "id": 201,
            "title": "Item with valid https source URL",
            "processing_status": "failed_permanent",
            "source_anchor": {"url": "https://example.com/agenda.pdf"},
        }
        html = _render(app, item)
        _assert_only_variant(html, "failed")
        assert 'href="https://example.com/agenda.pdf"' in html
        assert 'target="_blank"' in html
        assert 'rel="noopener noreferrer"' in html
        assert "view-source" in html

    def test_http_url_is_rendered(self, app):
        item = {
            "id": 202,
            "title": "Item with http source",
            "processing_status": "pending",
            "source_anchor": {"url": "http://example.com/doc"},
        }
        html = _render(app, item)
        _assert_only_variant(html, "pending")
        assert 'href="http://example.com/doc"' in html

    def test_relative_url_is_rendered(self, app):
        item = {
            "id": 203,
            "title": "Item with site-relative source",
            "processing_status": "pending",
            "source_anchor": {"url": "/uploads/agenda-2024.pdf"},
        }
        html = _render(app, item)
        _assert_only_variant(html, "pending")
        assert 'href="/uploads/agenda-2024.pdf"' in html

    def test_data_url_is_omitted(self, app):
        """data: URLs are also not in the allowlist — must be omitted."""
        item = {
            "id": 204,
            "title": "Item with data: URL",
            "processing_status": "pending",
            "source_anchor": {"url": "data:text/html,<script>alert(1)</script>"},
        }
        html = _render(app, item)
        _assert_only_variant(html, "pending")
        assert "data:text/html" not in html
        assert "view-source" not in html

    def test_protocol_relative_url_is_omitted(self, app):
        """Protocol-relative //host/path URLs resolve off-origin on HTTPS
        pages — same XSS/phishing risk as javascript: and data:. The
        allowlist must reject them even though they start with '/'."""
        item = {
            "id": 205,
            "title": "Item with protocol-relative URL",
            "processing_status": "failed_permanent",
            "source_anchor": {"url": "//evil.example/x"},
        }
        html = _render(app, item)
        _assert_only_variant(html, "failed")
        assert 'href="//evil.example' not in html
        assert "view-source" not in html


class TestVerificationPendingContent:
    """Per spec §6.1, the verification-pending variant DOES render the
    v3 outputs (headline + why_it_matters + facts strip + source link).
    Only the verification PILL is tooltip-only — the content is
    full-fidelity. The original E1 partial left the facts/source as
    TODO comments, which broke citizen click-through."""

    def test_verification_pending_renders_facts_and_source_link(self, app):
        item = {
            "id": 300,
            "title": "Flock contract amendment",
            "headline": "Sole-source: Flock licenses extended 5 years for $1.8M",
            "why_it_matters": "Higher per-camera rates affect surveillance budget.",
            "processing_status": "cross_stage_conflict",
            "data_quality": "ok",
            "ai_rewrite_version": 3,
            "dollars_amount": 1800000,
            "extracted_facts": {
                "counterparty": "Flock Safety Inc.",
                "funding_source": "general_fund",
                "action_type": "contract_amendment",
            },
            "source_anchor": {"url": "https://example.com/flock-amendment.pdf"},
        }
        html = _render(app, item)
        _assert_only_variant(html, "verification_pending")
        # Pill stays
        assert "Verification in progress" in html
        # Facts strip rendered (counterparty, dollars, funding).
        # E5: dollar amounts >= $1M abbreviate to ``$N.NM`` and now
        # carry WCAG markup (color class + symbol + sr-only label).
        assert "Flock Safety Inc." in html
        assert "dollars--red" in html
        assert "$1.8M" in html
        assert "($$$$)" in html
        assert "General Fund" in html
        # Source link rendered with target / rel
        assert 'href="https://example.com/flock-amendment.pdf"' in html
        assert 'target="_blank"' in html
        assert 'rel="noopener noreferrer"' in html
        assert "view-source" in html
        # Still no modal / hx-get
        assert "hx-get" not in html
