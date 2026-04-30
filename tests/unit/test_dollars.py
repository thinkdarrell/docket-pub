"""Unit tests for dollar extraction and tier classification."""

from decimal import Decimal

import pytest

from docket.enrichment.dollars import classify_dollar_tier, extract_dollars


class TestExtractDollars:
    """Tests for extract_dollars()."""

    # --- Standard US format -------------------------------------------------

    def test_standard_with_cents(self):
        assert extract_dollars("Approve $2,345,678.00 contract") == Decimal("2345678.00")

    def test_standard_no_cents(self):
        assert extract_dollars("Budget of $12,345") == Decimal("12345")

    def test_standard_small(self):
        assert extract_dollars("Filing fee of $500") == Decimal("500")

    def test_standard_with_decimal_cents(self):
        assert extract_dollars("Cost is $1,234.56 total") == Decimal("1234.56")

    def test_standard_no_commas(self):
        assert extract_dollars("Amount $50000") == Decimal("50000")

    # --- Abbreviated millions -----------------------------------------------

    def test_million_uppercase_m(self):
        assert extract_dollars("$1.2M bond issue") == Decimal("1200000")

    def test_million_word(self):
        assert extract_dollars("$2.5 million project") == Decimal("2500000")

    def test_million_bare(self):
        assert extract_dollars("$5M") == Decimal("5000000")

    def test_million_with_comma(self):
        assert extract_dollars("$1.5M renovation") == Decimal("1500000")

    # --- Abbreviated thousands ----------------------------------------------

    def test_thousand_uppercase_k(self):
        assert extract_dollars("$500K renovation") == Decimal("500000")

    def test_thousand_word(self):
        assert extract_dollars("$750 thousand grant") == Decimal("750000")

    def test_thousand_bare(self):
        assert extract_dollars("$50K") == Decimal("50000")

    # --- Largest amount wins ------------------------------------------------

    def test_largest_wins(self):
        assert extract_dollars("A $500 fee and a $2.3M contract") == Decimal("2300000")

    def test_largest_standard(self):
        assert extract_dollars("$100 plus $5,000 plus $250") == Decimal("5000")

    # --- No dollar amounts --------------------------------------------------

    def test_no_dollars(self):
        assert extract_dollars("Approve minutes") is None

    def test_empty_string(self):
        assert extract_dollars("") is None

    def test_none_input(self):
        assert extract_dollars(None) is None

    def test_roll_call(self):
        assert extract_dollars("Roll Call") is None

    def test_dollar_sign_alone(self):
        assert extract_dollars("$ sign only") is None

    # --- Edge cases ---------------------------------------------------------

    def test_match_word_not_million(self):
        """Regression: '$785,784.00 match requirement' should NOT be read as millions."""
        assert extract_dollars("($785,784.00 match requirement)") == Decimal("785784.00")

    def test_marker_word_not_thousand(self):
        """Words starting with K after a dollar amount should not trigger thousands."""
        result = extract_dollars("$500 kept in reserve")
        assert result == Decimal("500")

    def test_parenthetical(self):
        assert extract_dollars("(total: $1,234.56)") == Decimal("1234.56")

    def test_multiple_formats_mixed(self):
        assert extract_dollars("$500K for phase 1, $2.1M for phase 2") == Decimal("2100000")


class TestClassifyDollarTier:
    """Tests for classify_dollar_tier()."""

    def test_green_low(self):
        assert classify_dollar_tier(Decimal("100")) == "green"

    def test_green_boundary(self):
        assert classify_dollar_tier(Decimal("49999.99")) == "green"

    def test_yellow_boundary(self):
        assert classify_dollar_tier(Decimal("50000")) == "yellow"

    def test_yellow_mid(self):
        assert classify_dollar_tier(Decimal("100000")) == "yellow"

    def test_orange_boundary(self):
        assert classify_dollar_tier(Decimal("250000")) == "orange"

    def test_orange_mid(self):
        assert classify_dollar_tier(Decimal("500000")) == "orange"

    def test_red_boundary(self):
        assert classify_dollar_tier(Decimal("1000000")) == "red"

    def test_red_high(self):
        assert classify_dollar_tier(Decimal("50000000")) == "red"
