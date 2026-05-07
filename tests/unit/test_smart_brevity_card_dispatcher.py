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

    # The card_smart_brevity partial uses the `dollar_tier` filter.
    from docket.enrichment.dollars import classify_dollar_tier

    @flask_app.template_filter("dollar_tier")
    def _dollar_tier(amount):
        if amount is None:
            return ""
        return classify_dollar_tier(amount)

    @flask_app.template_filter("topic_name")
    def _topic_name(slug):
        return slug or ""

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
        # Dollar tier rendered (red tier for $1.8M)
        assert "1,800,000" in html

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
