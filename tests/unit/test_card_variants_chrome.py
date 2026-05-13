"""Tests that every variant partial extends _card_shell.html and renders
the expected status pill (or none).

Pure render tests; no DB.
"""
from __future__ import annotations

import datetime

import pytest
from bs4 import BeautifulSoup
from flask import Flask, render_template

from docket.web.filters import register as register_filters


@pytest.fixture(scope="module")
def app():
    flask_app = Flask("test_card_variants", template_folder="src/docket/web/templates")
    register_filters(flask_app)
    flask_app.add_url_rule(
        "/c/<slug>/meetings/<int:meeting_id>",
        endpoint="public.meeting_detail",
        view_func=lambda slug, meeting_id: "",
    )
    return flask_app


def _stub_item(**overrides):
    base = {
        "id": 200,
        "meeting_id": 20,
        "item_number": "10",
        "title": "Test agenda item",
        "headline": None,
        "why_it_matters": None,
        "meeting_date": datetime.date(2026, 4, 28),
        "badges": [],
        "extracted_facts": None,
        "dollars_amount": None,
        "summary": None,
        "data_quality": "ok",
        "processing_status": "pending",
        "ai_rewrite_version": None,
        "counterparty": None,
        "funding_source": None,
        "action_type": None,
        "location": None,
        "next_steps": None,
    }
    base.update(overrides)
    return base


def _render_variant(app, template_name, item):
    municipality = {"slug": "birmingham", "id": 1}
    with app.test_request_context():
        return render_template(
            template_name,
            item=item,
            municipality=municipality,
            show_meeting_context=True,
        )


class TestVariantChrome:
    def test_smart_brevity_has_no_status_pill(self, app):
        item = _stub_item(
            headline="A real headline",
            ai_rewrite_version=3,
            processing_status="completed",
        )
        html = _render_variant(app, "partials/card_smart_brevity.html", item)
        soup = BeautifulSoup(html, "html.parser")
        assert soup.find("a", class_="card-link"), "Headline link must render"
        assert soup.find(class_="status-pill") is None, "v3 card has no status pill"
        assert 'data-variant="smart_brevity"' in html

    def test_pending_has_pending_pill_and_italic_headline(self, app):
        item = _stub_item(processing_status="pending")
        html = _render_variant(app, "partials/card_pending.html", item)
        soup = BeautifulSoup(html, "html.parser")
        pill = soup.find(class_="status-pill--pending")
        assert pill, "pending pill must render"
        assert "summary updating" in pill.text
        link = soup.find("a", class_="card-link")
        assert "is-italic" in link.get("class", []), "headline link gets is-italic class"
        assert 'data-variant="pending"' in html

    def test_failed_pill_renders(self, app):
        item = _stub_item(processing_status="failed_permanent")
        html = _render_variant(app, "partials/card_failed.html", item)
        soup = BeautifulSoup(html, "html.parser")
        pill = soup.find(class_="status-pill--failed")
        assert pill, "failed pill must render"
        assert "processing error" in pill.text
        assert 'data-variant="failed"' in html

    def test_degraded_pill_varies_by_data_quality(self, app):
        # no_text_layer → OCR needed
        item = _stub_item(
            data_quality="no_text_layer", processing_status="data_quality_skipped"
        )
        html = _render_variant(app, "partials/card_degraded.html", item)
        assert "OCR needed" in html
        # no_agenda_text
        item = _stub_item(
            data_quality="no_agenda_text", processing_status="data_quality_skipped"
        )
        html = _render_variant(app, "partials/card_degraded.html", item)
        assert "no agenda text" in html
        assert 'data-variant="degraded"' in html

    def test_verification_pending_pill(self, app):
        item = _stub_item(
            processing_status="cross_stage_conflict",
            headline="Maybe legit; needs review",
        )
        html = _render_variant(app, "partials/card_verification_pending.html", item)
        soup = BeautifulSoup(html, "html.parser")
        pill = soup.find(class_="status-pill--verifying")
        assert pill, "verifying pill must render"
        assert "Verification in progress" in pill.text
        assert 'data-variant="verification_pending"' in html

    def test_v2_fallback_uses_summary_as_headline(self, app):
        item = _stub_item(
            summary="A pre-v3 summary that's somewhat long but under the cap."
        )
        html = _render_variant(app, "partials/card_v2_fallback.html", item)
        soup = BeautifulSoup(html, "html.parser")
        link = soup.find("a", class_="card-link")
        assert "A pre-v3 summary" in link.text
        assert 'data-variant="v2_fallback"' in html

    def test_v2_fallback_truncates_long_summary(self, app):
        long_summary = "A" * 200
        item = _stub_item(summary=long_summary)
        html = _render_variant(app, "partials/card_v2_fallback.html", item)
        # Truncated at 80 + ellipsis (the headline-text macro emits "…")
        assert "…" in html
        # Full 200-char string must NOT appear in the headline.
        assert long_summary not in html
