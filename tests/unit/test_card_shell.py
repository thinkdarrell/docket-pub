"""Tests for partials/_card_shell.html — the shared compact-scan chrome.

Confirms the structural contract: every variant's chrome includes a
position-relative <article>, a single .card-link <a> inside the
headline <h3>, and the ::after-target pattern requires no nested
interactive elements that would steal focus.

Uses BeautifulSoup for structural assertions; pure-render test, no DB.
"""
from __future__ import annotations

import datetime

import pytest
from bs4 import BeautifulSoup
from flask import Flask, render_template

from docket.web.filters import register as register_filters


@pytest.fixture(scope="module")
def app():
    flask_app = Flask("test_card_shell", template_folder="src/docket/web/templates")
    register_filters(flask_app)
    # Stub the meeting_detail route so url_for resolves in the shell.
    flask_app.add_url_rule(
        "/c/<slug>/meetings/<int:meeting_id>",
        endpoint="public.meeting_detail",
        view_func=lambda slug, meeting_id: "",
    )
    return flask_app


def _render_shell(app, item, municipality=None, **kwargs):
    """Render _card_shell.html stand-alone with a minimal stub item."""
    municipality = municipality or {"slug": "birmingham", "id": 1}
    with app.test_request_context():
        return render_template(
            "partials/_card_shell.html",
            item=item,
            municipality=municipality,
            show_meeting_context=True,
            **kwargs,
        )


def _stub_item(**overrides):
    """Minimal item dict the shell needs to render — keep this small."""
    base = {
        "id": 100,
        "meeting_id": 10,
        "item_number": "28",
        "title": "Test agenda item",
        "headline": "City settles workers' comp claim",
        "why_it_matters": "Outcome confidential per legal agreement.",
        "meeting_date": datetime.date(2026, 4, 28),
        "badges": [
            {
                "kind": "process",
                "slug": "legal_settlement",
                "confidence": 1.0,
                "name": "Legal & Settlements",
                "icon": "⚖",
                "description": "Council resolutions authorizing the city to settle...",
                "accent_color": "#5a7a99",
            }
        ],
        "extracted_facts": None,
        "dollars_amount": None,
        "processing_status": "completed",
        "data_quality": "ok",
        "ai_rewrite_version": 3,
    }
    base.update(overrides)
    return base


class TestCardShellStructure:
    def test_article_has_smart_brevity_card_class(self, app):
        html = _render_shell(app, _stub_item())
        soup = BeautifulSoup(html, "html.parser")
        article = soup.find("article", class_="smart-brevity-card")
        assert article is not None, "Must render an <article class='smart-brevity-card'>"

    def test_headline_is_inside_an_anchor_with_card_link_class(self, app):
        html = _render_shell(app, _stub_item())
        soup = BeautifulSoup(html, "html.parser")
        headline_h3 = soup.find("h3", class_="card-headline")
        assert headline_h3, "Must render <h3 class='card-headline'>"
        link = headline_h3.find("a", class_="card-link")
        assert link, "Headline must contain <a class='card-link'>"
        assert link.get("href"), "card-link must have an href"
        assert "#item-100" in link["href"], (
            f"Expected #item-100 in href; got {link['href']!r}"
        )

    def test_only_one_anchor_in_the_card(self, app):
        """The pseudo-element click-surface trick depends on a single
        focusable interactive element inside the article. Nested links
        steal focus and break AT navigation.
        """
        html = _render_shell(app, _stub_item())
        soup = BeautifulSoup(html, "html.parser")
        article = soup.find("article", class_="smart-brevity-card")
        anchors = article.find_all("a")
        assert len(anchors) == 1, (
            f"Expected exactly 1 <a> in the card chrome; got {len(anchors)}: "
            f"{[a.get('href') for a in anchors]}"
        )

    def test_left_edge_accent_color_is_set_as_inline_style(self, app):
        """accent_color is set as a CSS custom property on the article."""
        html = _render_shell(app, _stub_item())
        soup = BeautifulSoup(html, "html.parser")
        article = soup.find("article", class_="smart-brevity-card")
        style = article.get("style") or ""
        assert "--accent-color" in style, (
            "Article must set --accent-color CSS custom property"
        )
        assert "#5a7a99" in style, (
            "accent_color from the primary badge must propagate into the style"
        )

    def test_no_badges_falls_back_to_gray_accent(self, app):
        item = _stub_item(badges=[])
        html = _render_shell(app, item)
        soup = BeautifulSoup(html, "html.parser")
        article = soup.find("article", class_="smart-brevity-card")
        style = article.get("style") or ""
        # Gray fallback for un-badged cards (pending variant lands here).
        assert "#c8cbc0" in style.lower()
