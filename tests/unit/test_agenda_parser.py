"""Unit tests for the agenda PDF parser.

Birmingham council agenda PDFs follow a consistent format:
- Items are introduced by `ITEM N.`, `CONSENT ITEM N.`, or `CONSENT(ph) ITEM N.`
- Item body extends from the marker to the next marker
- Sponsor in `(Submitted by ...)` parenthetical
- Page headers `Agenda – Month DD, YYYY N` appear between items and are noise

Tests run against the real 5/19/2026 BHM agenda PDF (102 items) as fixture.
"""

from pathlib import Path

import pytest

from docket.analysis.agenda_parser import ParsedAgendaItem, parse_agenda
from docket.analysis.minutes_parser import extract_text_from_pdf


FIXTURE = Path(__file__).parent.parent / "fixtures" / "granicus_bham_agenda_2026_05_19.pdf"


@pytest.fixture(scope="module")
def fixture_text() -> str:
    """Real BHM 5/19 agenda PDF text. Loaded once per test module."""
    return extract_text_from_pdf(FIXTURE.read_bytes())


@pytest.fixture(scope="module")
def items(fixture_text: str) -> list[ParsedAgendaItem]:
    return parse_agenda(fixture_text)


class TestParseAgendaCounts:
    """Item-count and id-numbering sanity."""

    def test_returns_102_items(self, items):
        # Independently verified by regex over the raw text: 5 + 12 + 85 = 102
        assert len(items) == 102

    def test_item_numbers_are_consecutive_1_to_102(self, items):
        nums = [int(i.item_number) for i in items]
        assert nums == list(range(1, 103))

    def test_item_number_is_str(self, items):
        # item_number is TEXT in the DB; keep types consistent
        assert all(isinstance(i.item_number, str) for i in items)


class TestSubstantiveItem:
    """Item 1 — substantive, sets public hearing for mayor's budget."""

    def test_item_1_marker_yields_is_consent_false(self, items):
        assert items[0].item_number == "1"
        assert items[0].is_consent is False

    def test_item_1_title_extracted(self, items):
        # First line of body is the working title
        assert "public hearing" in items[0].title.lower()
        assert items[0].title.startswith("A Resolution")

    def test_item_1_body_complete(self, items):
        body = items[0].body
        # Whole body of item 1 (single sentence)
        assert "Mayor" in body
        assert "budgets" in body
        # Body must NOT spill into item 2's content
        assert "Angels Enterprises" not in body
        assert "Beer and Wine License" not in body

    def test_item_1_sponsor_extracted(self, items):
        assert items[0].sponsor is not None
        assert "Woods" in items[0].sponsor


class TestConsentItem:
    """Item 2 — CONSENT(ph) — consent with public hearing."""

    def test_item_2_is_consent_true(self, items):
        assert items[1].item_number == "2"
        assert items[1].is_consent is True

    def test_item_2_body_extracts(self, items):
        body = items[1].body
        assert "Angels Enterprises" in body
        assert "Star Food Mart" in body

    def test_item_2_sponsor_extracted(self, items):
        assert items[1].sponsor is not None
        assert "Tate" in items[1].sponsor


class TestConsentItemNoPublicHearing:
    """Item 50 — CONSENT (no `(ph)` suffix) — most common shape."""

    def test_item_50_is_consent(self, items):
        item_50 = items[49]
        assert item_50.item_number == "50"
        assert item_50.is_consent is True

    def test_item_50_body_about_unsafe_building(self, items):
        body = items[49].body
        assert "unsafe" in body.lower()
        # Verify the page-header noise is stripped
        assert "Agenda – May 19, 2026" not in body


class TestPageHeaderStripping:
    """The PDF interleaves `Agenda – May 19, 2026 N` page headers between
    items. These must not appear in item bodies."""

    def test_no_item_body_contains_page_header(self, items):
        for item in items:
            assert "Agenda – May 19, 2026" not in item.body, (
                f"Item {item.item_number} body contains page header noise"
            )

    def test_no_item_title_contains_page_header(self, items):
        for item in items:
            assert "Agenda – May 19, 2026" not in item.title


class TestItemBoundaries:
    """Each item's body must end before the next marker — no spillover."""

    def test_item_n_body_does_not_contain_next_marker(self, items):
        for i, item in enumerate(items[:-1]):
            next_num = items[i + 1].item_number
            # The body must not contain the literal "ITEM {next_num}." marker
            assert f"ITEM {next_num}." not in item.body, (
                f"Item {item.item_number} body spills into ITEM {next_num}"
            )


class TestSponsorExtraction:
    """Sponsor is the content of (Submitted by ...). Should appear on most items."""

    def test_most_items_have_a_sponsor(self, items):
        with_sponsor = sum(1 for i in items if i.sponsor)
        # Empirical: nearly all items carry a (Submitted by ...) line
        assert with_sponsor >= len(items) * 0.9, (
            f"Only {with_sponsor}/{len(items)} items have a sponsor — too few"
        )

    def test_sponsor_does_not_include_recommended_by(self, items):
        # The PDF has both (Submitted by ...) and (Recommended by ...) — only
        # the first should be captured as sponsor.
        for item in items:
            if item.sponsor:
                assert "Recommended by" not in item.sponsor


class TestEdgeCases:
    def test_empty_input_returns_empty_list(self):
        assert parse_agenda("") == []

    def test_no_items_in_input_returns_empty_list(self):
        text = "AGENDA\nROLL CALL\nADJOURNMENT"
        assert parse_agenda(text) == []
