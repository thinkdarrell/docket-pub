"""Tests for partials/_facts_strip.html — inline emoji facts line.

Confirms:
- Emoji order: 👥 → 🏛 → 📋 → 📍 → 📅 → 🌳
- Location priority: address → neighborhood → ward_or_district
- Null fields are omitted (no empty <span class='fact'>)
- Each fact has aria-hidden + sr-only label
- If all facts null, the partial renders nothing (no empty container)

Reads from lifted top-level columns (item.counterparty etc.); parcels
and acres come from item.extracted_facts because those aren't lifted.

Uses BeautifulSoup; no DB.
"""
from __future__ import annotations

import pytest
from bs4 import BeautifulSoup
from flask import Flask, render_template

from docket.web.filters import register as register_filters
from tests.unit.conftest import make_agenda_item


@pytest.fixture(scope="module")
def app():
    flask_app = Flask("test_facts_strip", template_folder="src/docket/web/templates")
    register_filters(flask_app)
    return flask_app


def _render(app, **fields):
    """Render with an AgendaItem built from ``fields`` (lifted columns +
    ``extracted_facts`` for parcels/acres which aren't lifted)."""
    item = make_agenda_item(**fields)
    with app.app_context():
        return render_template("partials/_facts_strip.html", item=item)


class TestFactsLine:
    def test_all_facts_present_emoji_order(self, app):
        html = _render(
            app,
            counterparty="Axon Enterprise",
            funding_source="public_safety_fund",
            action_type="sole_source",
            location={
                "ward_or_district": "District 5",
                "neighborhood": "Eastlake",
                "address": "621 4th Ct W",
            },
            next_steps={"public_hearing_date": "2026-05-14"},
            extracted_facts={"parcels_affected": 12, "acres_affected": 0.16},
        )
        soup = BeautifulSoup(html, "html.parser")
        fact_spans = soup.find_all("span", class_="fact")
        emojis_in_order = [
            s.find("span", attrs={"aria-hidden": "true"}).text.strip()
            for s in fact_spans
        ]
        assert emojis_in_order == ["👥", "🏛", "📋", "📍", "📅", "🌳"]

    def test_location_picks_most_specific(self, app):
        html = _render(
            app,
            location={
                "ward_or_district": "District 5",
                "neighborhood": "Eastlake",
                "address": "621 4th Ct W",
            },
        )
        assert "621 4th Ct W" in html
        assert "Eastlake" not in html
        assert "District 5" not in html

    def test_location_falls_back_to_neighborhood(self, app):
        html = _render(
            app,
            location={"ward_or_district": "District 5", "neighborhood": "Eastlake"},
        )
        assert "Eastlake" in html
        assert "District 5" not in html

    def test_location_falls_back_to_district(self, app):
        html = _render(app, location={"ward_or_district": "District 5"})
        assert "District 5" in html

    def test_null_facts_omitted(self, app):
        html = _render(app, counterparty="Axon Enterprise")
        soup = BeautifulSoup(html, "html.parser")
        fact_spans = soup.find_all("span", class_="fact")
        assert len(fact_spans) == 1
        assert "Axon Enterprise" in fact_spans[0].text

    def test_all_null_renders_nothing(self, app):
        html = _render(app)
        soup = BeautifulSoup(html, "html.parser")
        assert soup.find(class_="facts-line") is None

    def test_each_fact_has_aria_hidden_and_sr_only(self, app):
        html = _render(
            app,
            counterparty="Axon Enterprise",
            funding_source="public_safety_fund",
        )
        soup = BeautifulSoup(html, "html.parser")
        fact_spans = soup.find_all("span", class_="fact")
        for fs in fact_spans:
            assert fs.find("span", attrs={"aria-hidden": "true"}), "aria-hidden emoji wrapper missing"
            assert fs.find("span", class_="sr-only"), "sr-only label missing"

    def test_land_area_prefers_acres_over_parcels(self, app):
        html = _render(
            app,
            extracted_facts={"parcels_affected": 12, "acres_affected": 0.16},
        )
        assert "0.16 acres" in html
        assert "12 parcels" not in html

    def test_land_area_falls_back_to_parcels(self, app):
        html = _render(app, extracted_facts={"parcels_affected": 3})
        assert "3 parcels" in html
