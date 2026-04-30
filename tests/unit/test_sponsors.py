"""Unit tests for sponsor extraction from agenda item text."""

from docket.enrichment.sponsors import clean_title, extract_recommended_by, extract_sponsor


class TestExtractSponsor:
    """Tests for extract_sponsor()."""

    def test_mayor(self):
        assert extract_sponsor("A Resolution. (Submitted by the Mayor)") == "the Mayor"

    def test_councilor_with_committee(self):
        text = "(Submitted by Councilor Smith, Chair, Arts and Parks Committee)"
        assert extract_sponsor(text) == "Councilor Smith, Chair, Arts and Parks Committee"

    def test_councilor_chairman(self):
        text = "(Submitted by Councilor Williams, Chairman, Economic and Workforce Development and Tourism Committee)"
        assert extract_sponsor(text) == "Councilor Williams, Chairman, Economic and Workforce Development and Tourism Committee"

    def test_city_attorney(self):
        assert extract_sponsor("Notice. (Submitted by the City Attorney)") == "the City Attorney"

    def test_with_recommended_after(self):
        text = "Expense accounts. (Submitted by the Mayor) (Recommended by the Director of Finance)**"
        assert extract_sponsor(text) == "the Mayor"

    def test_trailing_asterisks(self):
        text = "(Submitted by the Mayor)**"
        assert extract_sponsor(text) == "the Mayor"

    def test_no_sponsor(self):
        assert extract_sponsor("ROLL CALL") is None

    def test_consent_item_no_sponsor(self):
        assert extract_sponsor("CONSENT ITEM 12. A Resolution authorizing grant funds.") is None

    def test_empty(self):
        assert extract_sponsor("") is None

    def test_none(self):
        assert extract_sponsor(None) is None

    # --- Mobile "sponsored by" pattern ---

    def test_sponsored_by_councilmember(self):
        text = "Fix costs for demolition at 1901 Bishop Avenue (sponsored by Councilmember Carroll)."
        assert extract_sponsor(text) == "Councilmember Carroll"

    def test_sponsored_by_mayor(self):
        text = "Approve purchase order for MPD; $885,923.55 (sponsored by Mayor Stimpson)"
        assert extract_sponsor(text) == "Mayor Stimpson"

    def test_sponsored_and_submitted(self):
        """Mobile uses both 'sponsored by' and 'submitted by' — sponsor takes precedence if submitted is present."""
        text = "Authorize settlement (sponsored by Mayor Stimpson) (submitted by City Attorney)"
        assert extract_sponsor(text) is not None

    def test_clean_title_removes_sponsored(self):
        text = "Fix costs for demolition (sponsored by Councilmember Carroll)."
        cleaned = clean_title(text)
        assert "(sponsored" not in cleaned


class TestExtractRecommendedBy:
    """Tests for extract_recommended_by()."""

    def test_director(self):
        text = "(Recommended by the Director of Finance)**"
        assert extract_recommended_by(text) == "the Director of Finance"

    def test_committee(self):
        text = "(Recommended by the Arts and Parks Committee)"
        assert extract_recommended_by(text) == "the Arts and Parks Committee"

    def test_cfo(self):
        text = "(Recommended by the Chief Financial Officer)"
        assert extract_recommended_by(text) == "the Chief Financial Officer"

    def test_no_recommendation(self):
        assert extract_recommended_by("ROLL CALL") is None

    def test_none(self):
        assert extract_recommended_by(None) is None


class TestCleanTitle:
    """Tests for clean_title()."""

    def test_removes_submitted_by(self):
        text = "A Resolution. (Submitted by the Mayor)"
        assert clean_title(text) == "A Resolution."

    def test_removes_recommended_by(self):
        text = "A Resolution. (Recommended by the Director of Finance)"
        assert clean_title(text) == "A Resolution."

    def test_removes_both(self):
        text = "Expense accounts. (Submitted by the Mayor) (Recommended by the Director of Finance)**"
        assert clean_title(text) == "Expense accounts."

    def test_no_attribution(self):
        text = "CONSENT ITEM 12. A Resolution authorizing grant funds."
        assert clean_title(text) == text

    def test_preserves_other_parentheses(self):
        text = "A Resolution (Case No. ZAC2026-00001)"
        assert clean_title(text) == text

    def test_empty(self):
        assert clean_title("") == ""

    def test_none(self):
        assert clean_title(None) is None
