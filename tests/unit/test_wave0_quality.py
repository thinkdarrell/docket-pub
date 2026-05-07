"""Tests for Stage 0a data-quality gate (`evaluate_data_quality`)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from docket.ai.wave0 import evaluate_data_quality


@dataclass
class FakeItem:
    """Minimal fixture matching the AgendaItem fields we read."""
    title: str | None
    description: str | None = None
    raw_text: str | None = None
    source_type: str | None = 'pdf'


class TestEvaluateDataQuality:
    def test_big_fish_overrides_empty_body(self):
        item = FakeItem(title="Settlement of Smith vs. City", description="")
        quality, priority = evaluate_data_quality(item)
        assert quality == 'ok'
        assert priority == 'high'

    def test_big_fish_overrides_no_text_layer(self):
        item = FakeItem(title="Sole-source extension: Flock cameras", description="x")
        quality, priority = evaluate_data_quality(item)
        assert quality == 'ok'
        assert priority == 'high'

    def test_empty_title(self):
        item = FakeItem(title="", description="some body")
        quality, priority = evaluate_data_quality(item)
        assert quality == 'empty'

    def test_short_title(self):
        item = FakeItem(title="ok", description="some body")
        quality, priority = evaluate_data_quality(item)
        assert quality == 'empty'

    def test_no_body(self):
        item = FakeItem(title="Approval of routine matter", description=None)
        quality, priority = evaluate_data_quality(item)
        assert quality == 'no_agenda_text'

    def test_short_body_pdf(self):
        item = FakeItem(title="Approval of routine matter", description="see attached", source_type='pdf')
        quality, priority = evaluate_data_quality(item)
        assert quality == 'no_text_layer'

    def test_body_equals_title(self):
        item = FakeItem(
            title="Approval of professional services agreement",
            description="Approval of professional services agreement",
            source_type='pdf',
        )
        quality, priority = evaluate_data_quality(item)
        assert quality == 'no_text_layer'

    def test_ok_substantive_item(self):
        item = FakeItem(
            title="Award of HVAC contract",
            description="The City Council hereby awards the contract to Acme Industries Inc. for "
                         "the replacement of the HVAC system at City Hall, including labor and "
                         "materials, for a total amount not to exceed $87,500. The contract term "
                         "is 24 months commencing June 1, 2026.",
        )
        quality, priority = evaluate_data_quality(item)
        assert quality == 'ok'
        assert priority == 'normal'

    def test_priority_high_for_million_dollar_normal_body(self):
        item = FakeItem(
            title="Award of $4,500,000 HVAC contract to Acme",
            description="Long valid body content describing the contract awards procurement process etc.",
        )
        quality, priority = evaluate_data_quality(item)
        assert quality == 'ok'
        assert priority == 'high'  # via _priority_from_title's dollar regex

    def test_long_title_with_empty_description_treats_title_as_body(self):
        """Granicus/Birmingham case: full agenda body sits in title, description is NULL.
        A substantive title (>=120 chars) should classify as 'ok', not 'no_agenda_text'."""
        item = FakeItem(
            title=(
                "A Resolution determining that the building or structure located at "
                "1701 Madison Avenue S.W., Birmingham, to be unsafe, a public nuisance, "
                "and directing that it be demolished. (Recommended by the Director of Planning)"
            ),
            description=None,
        )
        quality, priority = evaluate_data_quality(item)
        assert quality == 'ok'

    def test_short_title_with_empty_description_still_no_agenda_text(self):
        """A short title (e.g., 'CONSENT ITEM 38.') with empty body remains no_agenda_text —
        the title fallback only kicks in for titles long enough to be substantive."""
        item = FakeItem(
            title="CONSENT ITEM 38.",  # 16 chars — below the 120 threshold
            description=None,
        )
        quality, priority = evaluate_data_quality(item)
        assert quality == 'no_agenda_text'
