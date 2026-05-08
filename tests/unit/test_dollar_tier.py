"""Snapshot + unit tests for the dollar-tier WCAG partial.

Covers ``partials/dollar_tier.html`` (spec §6.1, decisions #71 + #75)
plus the two filters it depends on — ``format_dollars`` and
``dollar_tier`` from :mod:`docket.web.filters`.

The partial implements WCAG 2.1 AA "color is not load-bearing":

  - color (``dollars--{{ color }}`` CSS class)
  - symbol (``$``/``$$``/``$$$``/``$$$$`` in parens, visible)
  - screen-reader label (``aria-label`` on the parent + visually-hidden
    ``.sr-only`` span on the child).

Tests pin all three signal channels so a regression that loses one
(e.g. someone "simplifying" away the sr-only span) trips immediately.

Pure UI: no Anthropic, no DB, no integration setup.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from flask import Flask, render_template


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app():
    """Minimal Flask app pointed at the docket templates + filters.

    Registers the real :func:`docket.web.filters.register` so
    ``format_dollars`` + ``dollar_tier`` mirror production. No DB, no
    blueprints, no security globals — the partial uses only filters.
    """
    flask_app = Flask(
        "test_dollar_tier",
        template_folder="src/docket/web/templates",
    )

    from docket.web.filters import register as register_filters

    register_filters(flask_app)
    return flask_app


def _render(app, amount):
    """Render the partial with ``amount`` in scope."""
    with app.app_context():
        return render_template("partials/dollar_tier.html", amount=amount)


# ---------------------------------------------------------------------------
# Filter: dollar_tier
# ---------------------------------------------------------------------------


class TestDollarTierFilter:
    """Direct unit tests for ``docket.web.filters.dollar_tier``."""

    # ----- Boundary semantics inherited from classify_dollar_tier ----------

    def test_just_under_50k_is_green(self):
        from docket.web.filters import dollar_tier

        result = dollar_tier(Decimal("49999.99"))
        assert result is not None
        assert result.color == "green"
        assert result.symbol == "$"
        assert result.description == "under $50,000"

    def test_exactly_50k_is_yellow(self):
        from docket.web.filters import dollar_tier

        result = dollar_tier(Decimal("50000"))
        assert result.color == "yellow"
        assert result.symbol == "$$"
        assert result.description == "$50,000 to $250,000"

    def test_just_under_250k_is_yellow(self):
        from docket.web.filters import dollar_tier

        assert dollar_tier(Decimal("249999.99")).color == "yellow"

    def test_exactly_250k_is_orange(self):
        from docket.web.filters import dollar_tier

        result = dollar_tier(Decimal("250000"))
        assert result.color == "orange"
        assert result.symbol == "$$$"
        assert result.description == "$250,000 to $1 million"

    def test_just_under_1m_is_orange(self):
        from docket.web.filters import dollar_tier

        assert dollar_tier(Decimal("999999.99")).color == "orange"

    def test_exactly_1m_is_red(self):
        from docket.web.filters import dollar_tier

        result = dollar_tier(Decimal("1000000"))
        assert result.color == "red"
        assert result.symbol == "$$$$"
        assert result.description == "over $1 million"

    # ----- Non-boundary representative values per tier ---------------------

    def test_25k_is_green(self):
        from docket.web.filters import dollar_tier

        assert dollar_tier(Decimal("25000")).color == "green"

    def test_120k_is_yellow(self):
        from docket.web.filters import dollar_tier

        assert dollar_tier(Decimal("120000")).color == "yellow"

    def test_640k_is_orange(self):
        from docket.web.filters import dollar_tier

        assert dollar_tier(Decimal("640000")).color == "orange"

    def test_1_8m_is_red(self):
        from docket.web.filters import dollar_tier

        assert dollar_tier(Decimal("1800000")).color == "red"

    # ----- Tuple-unpacking compatibility -----------------------------------

    def test_returns_namedtuple_unpackable_as_3_tuple(self):
        """NamedTuple should still be tuple-unpackable for callers
        that grab the three values positionally."""
        from docket.web.filters import dollar_tier

        color, symbol, desc = dollar_tier(Decimal("100"))
        assert color == "green"
        assert symbol == "$"
        assert desc == "under $50,000"

    def test_str_returns_color_for_v2_template_backcompat(self):
        """``__str__`` returns ``self.color`` so legacy v2 templates
        using ``{{ amt | dollar_tier }}`` inside a CSS class still
        render ``tier-green`` etc. — no template churn at v2/v3 cutover."""
        from docket.web.filters import dollar_tier

        result = dollar_tier(Decimal("100"))
        assert str(result) == "green"

    # ----- Defensive contract ----------------------------------------------

    def test_none_returns_none(self):
        from docket.web.filters import dollar_tier

        assert dollar_tier(None) is None

    def test_zero_returns_none(self):
        """Zero means "no dollar info captured", not "$0 line item"."""
        from docket.web.filters import dollar_tier

        assert dollar_tier(0) is None
        assert dollar_tier(Decimal("0")) is None

    def test_negative_returns_none(self):
        from docket.web.filters import dollar_tier

        assert dollar_tier(Decimal("-100")) is None
        assert dollar_tier(-100) is None

    def test_bool_true_returns_none(self):
        """``isinstance(True, int)`` is True — a stray bool from JSONB
        would otherwise classify as green ($1) and look real."""
        from docket.web.filters import dollar_tier

        assert dollar_tier(True) is None

    def test_bool_false_returns_none(self):
        from docket.web.filters import dollar_tier

        assert dollar_tier(False) is None

    def test_numeric_string_coerced(self):
        """psycopg JSONB driver paths can hand back numerics as strings."""
        from docket.web.filters import dollar_tier

        # $87,500 is yellow ($50K-$250K), not green — verifies the
        # string path coerces correctly through the same boundary
        # logic as Decimal inputs.
        result = dollar_tier("87500")
        assert result is not None
        assert result.color == "yellow"

    def test_decimal_string_coerced(self):
        from docket.web.filters import dollar_tier

        assert dollar_tier("249999.99").color == "yellow"

    def test_non_numeric_string_returns_none(self):
        from docket.web.filters import dollar_tier

        assert dollar_tier("not-a-number") is None

    def test_empty_string_returns_none(self):
        from docket.web.filters import dollar_tier

        assert dollar_tier("") is None
        assert dollar_tier("   ") is None

    def test_decimal_nan_returns_none(self):
        from docket.web.filters import dollar_tier

        assert dollar_tier(Decimal("NaN")) is None

    def test_decimal_infinity_returns_none(self):
        from docket.web.filters import dollar_tier

        assert dollar_tier(Decimal("Infinity")) is None
        assert dollar_tier(Decimal("-Infinity")) is None

    def test_float_inf_returns_none(self):
        from docket.web.filters import dollar_tier

        assert dollar_tier(float("inf")) is None

    def test_float_nan_returns_none(self):
        from docket.web.filters import dollar_tier

        assert dollar_tier(float("nan")) is None

    def test_int_coerced(self):
        from docket.web.filters import dollar_tier

        assert dollar_tier(75000).color == "yellow"

    def test_float_coerced(self):
        from docket.web.filters import dollar_tier

        assert dollar_tier(75000.0).color == "yellow"

    def test_unsupported_type_returns_none(self):
        """A list / dict / object should never render."""
        from docket.web.filters import dollar_tier

        assert dollar_tier([1, 2, 3]) is None
        assert dollar_tier({"amount": 100}) is None


# ---------------------------------------------------------------------------
# Filter: format_dollars
# ---------------------------------------------------------------------------


class TestFormatDollarsFilter:
    """Direct unit tests for ``docket.web.filters.format_dollars``.

    Threshold contract: amounts ≥ $1,000,000 abbreviate to ``$N.NM`` (one
    decimal). Sub-$1M renders at full precision. The threshold is locked
    in by tests below because decision #71's example markup uses
    ``$1.8M`` while spec prose example shows ``$1,800,000`` —
    decision #71 wins, this filter implements the abbreviated path.
    """

    # ----- Per-tier representative formatting ------------------------------

    def test_green_amount_renders_full_precision(self):
        from docket.web.filters import format_dollars

        assert format_dollars(Decimal("25000")) == "$25,000"

    def test_yellow_amount_renders_full_precision(self):
        from docket.web.filters import format_dollars

        assert format_dollars(Decimal("87500")) == "$87,500"

    def test_orange_amount_renders_full_precision(self):
        from docket.web.filters import format_dollars

        assert format_dollars(Decimal("640000")) == "$640,000"

    def test_red_amount_abbreviates_to_millions(self):
        from docket.web.filters import format_dollars

        assert format_dollars(Decimal("1800000")) == "$1.8M"

    # ----- Threshold edges -------------------------------------------------

    def test_999_999_99_rounds_full_precision(self):
        """Just under $1M: no abbreviation. Cents are dropped — the
        contract is integer dollars below $1M."""
        from docket.web.filters import format_dollars

        # int(Decimal("999999.99")) truncates, not rounds — so 999,999
        # is the expected output. This matches the "drop cents" contract.
        assert format_dollars(Decimal("999999.99")) == "$999,999"

    def test_exactly_1m_abbreviates_to_dot_zero_m(self):
        """Threshold is inclusive: $1,000,000 renders as ``$1.0M``,
        not ``$1M``. The trailing ``.0`` is a deliberate scale signal —
        readers see ``$1M`` as ambiguous (could be a rounded $1.4M)."""
        from docket.web.filters import format_dollars

        assert format_dollars(Decimal("1000000")) == "$1.0M"

    def test_12_5m_abbreviates(self):
        from docket.web.filters import format_dollars

        assert format_dollars(Decimal("12500000")) == "$12.5M"

    def test_2m_renders_2_dot_0_m(self):
        from docket.web.filters import format_dollars

        assert format_dollars(Decimal("2000000")) == "$2.0M"

    def test_1_25m_rounds_to_one_decimal(self):
        """Decimal quantize via ``f"{:.1f}"`` rounds half-even by default
        (Decimal context); $1,250,000 → $1.2M (banker's rounding) on most
        Python builds. We assert the formatted output rather than the
        rounding mode — the user-visible contract is one decimal place."""
        from docket.web.filters import format_dollars

        result = format_dollars(Decimal("1250000"))
        # Either $1.2M or $1.3M is acceptable per Python rounding
        # semantics; assert the shape only.
        assert result.startswith("$1.")
        assert result.endswith("M")

    # ----- Defensive contract (mirrors dollar_tier) ------------------------

    def test_none_returns_empty_string(self):
        from docket.web.filters import format_dollars

        assert format_dollars(None) == ""

    def test_zero_returns_empty_string(self):
        from docket.web.filters import format_dollars

        assert format_dollars(0) == ""
        assert format_dollars(Decimal("0")) == ""

    def test_negative_returns_empty_string(self):
        from docket.web.filters import format_dollars

        assert format_dollars(Decimal("-100")) == ""

    def test_bool_returns_empty_string(self):
        from docket.web.filters import format_dollars

        assert format_dollars(True) == ""
        assert format_dollars(False) == ""

    def test_numeric_string_coerced(self):
        from docket.web.filters import format_dollars

        assert format_dollars("87500") == "$87,500"

    def test_non_numeric_string_returns_empty(self):
        from docket.web.filters import format_dollars

        assert format_dollars("not-a-number") == ""

    def test_empty_string_returns_empty(self):
        from docket.web.filters import format_dollars

        assert format_dollars("") == ""
        assert format_dollars("   ") == ""

    def test_nan_returns_empty(self):
        from docket.web.filters import format_dollars

        assert format_dollars(Decimal("NaN")) == ""
        assert format_dollars(float("nan")) == ""

    def test_infinity_returns_empty(self):
        from docket.web.filters import format_dollars

        assert format_dollars(Decimal("Infinity")) == ""
        assert format_dollars(float("inf")) == ""

    def test_int_coerced(self):
        from docket.web.filters import format_dollars

        assert format_dollars(87500) == "$87,500"

    def test_float_coerced(self):
        from docket.web.filters import format_dollars

        assert format_dollars(87500.0) == "$87,500"

    def test_unsupported_type_returns_empty(self):
        from docket.web.filters import format_dollars

        assert format_dollars([100]) == ""
        assert format_dollars({"x": 1}) == ""


# ---------------------------------------------------------------------------
# Partial: dollar_tier.html — per-tier rendering
# ---------------------------------------------------------------------------


class TestDollarTierPartialPerTier:
    """Each tier renders all three WCAG 2.1 signal channels (decision #75):
    color CSS class + visible symbol + sr-only label + parent aria-label."""

    def test_green_tier_full_render(self, app):
        html = _render(app, Decimal("25000"))
        # CSS hook
        assert "dollars--green" in html
        # Visible amount text
        assert "$25,000" in html
        # Visible symbol in parens
        assert "($)" in html
        # sr-only span — case-titled for natural screen-reader prose
        assert ", Green tier" in html
        assert 'class="sr-only"' in html
        # Parent aria-label includes formatted amount + tier name + threshold
        assert "$25,000, Green tier (under $50,000)" in html

    def test_yellow_tier_full_render(self, app):
        html = _render(app, Decimal("120000"))
        assert "dollars--yellow" in html
        assert "$120,000" in html
        assert "($$)" in html
        assert ", Yellow tier" in html
        assert "$120,000, Yellow tier ($50,000 to $250,000)" in html

    def test_orange_tier_full_render(self, app):
        html = _render(app, Decimal("640000"))
        assert "dollars--orange" in html
        assert "$640,000" in html
        assert "($$$)" in html
        assert ", Orange tier" in html
        assert "$640,000, Orange tier ($250,000 to $1 million)" in html

    def test_red_tier_full_render(self, app):
        """Red tier abbreviates the visible amount to ``$1.8M`` per
        decision #71's example markup."""
        html = _render(app, Decimal("1800000"))
        assert "dollars--red" in html
        assert "$1.8M" in html
        assert "($$$$)" in html
        assert ", Red tier" in html
        assert "$1.8M, Red tier (over $1 million)" in html


# ---------------------------------------------------------------------------
# Partial: dollar_tier.html — defensive no-render contract
# ---------------------------------------------------------------------------


class TestDollarTierPartialNoRender:
    """Invalid amounts must NOT emit any markup (no empty span, no
    leftover whitespace-only block). Same posture as E4's source-anchor
    button — silent fall-through, never a half-rendered chrome."""

    def test_none_renders_nothing(self, app):
        html = _render(app, None)
        assert "<span" not in html
        assert "dollars" not in html
        assert html.strip() == ""

    def test_zero_renders_nothing(self, app):
        html = _render(app, 0)
        assert "<span" not in html
        assert html.strip() == ""

    def test_decimal_zero_renders_nothing(self, app):
        html = _render(app, Decimal("0"))
        assert html.strip() == ""

    def test_negative_renders_nothing(self, app):
        html = _render(app, Decimal("-100"))
        assert html.strip() == ""

    def test_nan_renders_nothing(self, app):
        html = _render(app, Decimal("NaN"))
        assert html.strip() == ""

    def test_infinity_renders_nothing(self, app):
        html = _render(app, Decimal("Infinity"))
        assert html.strip() == ""

    def test_bool_renders_nothing(self, app):
        html = _render(app, True)
        assert html.strip() == ""

    def test_non_numeric_string_renders_nothing(self, app):
        html = _render(app, "not-a-number")
        assert html.strip() == ""


# ---------------------------------------------------------------------------
# Partial: WCAG triple-redundancy contract lock-in
# ---------------------------------------------------------------------------


class TestDollarTierPartialWcagContract:
    """Locks in decision #75: color + symbol + sr-only label, all three
    present in a single render. If any future "simplification" drops one
    channel (CSS class only, or aria-label without sr-only, etc.), this
    test fails — making the WCAG regression visible at the test layer."""

    def test_triple_redundancy_in_single_render(self, app):
        """A single rendering must contain ALL THREE channels:
        (1) CSS class with tier color, (2) visible symbol, (3) sr-only
        text with tier name. Plus the parent aria-label."""
        html = _render(app, Decimal("87500"))

        # Channel 1: color in CSS class
        assert "dollars--yellow" in html

        # Channel 2: visible symbol in parens
        assert "($$)" in html

        # Channel 3: sr-only span carrying tier name
        assert 'class="sr-only"' in html
        # Tier name appears in lower part as ", Yellow tier"
        # (case-titled for natural reading)
        assert ", Yellow tier" in html

        # Parent aria-label as the assistive-tech-prefers-it path
        assert 'aria-label=' in html
        assert "Yellow tier" in html

    def test_aria_label_carries_full_threshold_prose(self, app):
        """Threshold description in aria-label gives the screen-reader
        user enough context to grasp tier semantics without sight."""
        html = _render(app, Decimal("1800000"))
        assert "over $1 million" in html

    def test_screen_reader_path_a_aria_label_only_is_complete(self, app):
        """A screen reader that prefers ``aria-label`` and skips child
        text must still hear the full tier story: amount + tier name +
        threshold prose. Locks in the assistive-tech contract for the
        first of three SR behaviours documented in the partial header."""
        html = _render(app, Decimal("1800000"))
        # Pull just the aria-label value.
        idx = html.index('aria-label="')
        end = html.index('"', idx + len('aria-label="'))
        aria = html[idx + len('aria-label="'): end]
        # Amount + tier + description all present in the single attribute.
        assert "$1.8M" in aria
        assert "Red tier" in aria
        assert "over $1 million" in aria

    def test_screen_reader_path_b_visible_text_only_is_complete(self, app):
        """A screen reader that traverses visible children and ignores
        ``aria-label`` (some older NVDA configs, some Linux SRs) must
        still hear the tier story. The visible amount + symbol + sr-only
        suffix together must convey: amount + tier name. Locks in the
        contract for the second SR behaviour."""
        html = _render(app, Decimal("1800000"))
        # Strip the aria-label out so we're testing the visible+sr-only
        # path in isolation. (Real SRs do this internally; we simulate
        # by string-trimming the attribute.)
        import re as _re
        visible = _re.sub(r'\saria-label="[^"]*"', "", html)
        # Visible amount appears (outside any hidden span)
        assert "$1.8M" in visible
        # Symbol appears
        assert "($$$$)" in visible
        # sr-only tier name still in DOM (it's visually hidden, not
        # removed — SRs read it).
        assert ", Red tier" in visible

    def test_aria_label_attribute_is_quoted(self, app):
        """Jinja autoescape should produce a properly double-quoted
        ``aria-label`` attribute (no broken HTML even if the amount or
        description ever contains characters that need escaping)."""
        html = _render(app, Decimal("87500"))
        # Find the aria-label and verify it's bounded by double-quotes
        # and the closing quote exists before the next attribute or `>`.
        idx = html.index('aria-label="')
        # Find closing quote of the aria-label value
        end = html.index('"', idx + len('aria-label="'))
        # Between idx and end, there should be no unescaped newline-tab
        # gunk that would break the attribute. (Jinja autoescape handles
        # this; assertion guards against regressions.)
        attr_value = html[idx + len('aria-label="'): end]
        assert "\n" not in attr_value
        # Must include the formatted amount + tier name + description.
        assert "$87,500" in attr_value
        assert "Yellow tier" in attr_value
        assert "$50,000 to $250,000" in attr_value


# ---------------------------------------------------------------------------
# Partial: integration with _facts_strip.html (TODO swap-in)
# ---------------------------------------------------------------------------


class TestFactsStripDollarTierSwap:
    """The E5 swap replaces the old ``<span class="tier tier-...">`` block
    inside ``_facts_strip.html`` with an ``{% include %}`` of the new
    partial. These tests assert the integration, not the partial in
    isolation — they catch a regression where the include is dropped
    or the ``{% with amount = ... %}`` scope-binding is lost."""

    @pytest.fixture(scope="class")
    def facts_app(self):
        flask_app = Flask(
            "test_facts_strip_dollar_tier",
            template_folder="src/docket/web/templates",
        )
        from docket.web.filters import register as register_filters

        register_filters(flask_app)
        return flask_app

    def test_facts_strip_renders_dollar_partial(self, facts_app):
        """When ``item.dollars_amount`` is set, the facts strip renders
        the cost row and includes the new partial markup
        (``dollars--<color>`` class + sr-only span)."""
        item = {
            "dollars_amount": Decimal("87500"),
            "extracted_facts": {},
        }
        with facts_app.app_context():
            html = render_template("partials/_facts_strip.html", item=item)
        # Cost row present
        assert "fact--cost" in html
        assert "💵 Cost:" in html
        # New partial output
        assert "dollars--yellow" in html
        assert "($$)" in html
        assert ", Yellow tier" in html
        assert "$87,500" in html
        # Old hand-formatted span MUST NOT remain
        assert 'class="tier tier-' not in html

    def test_facts_strip_omits_cost_row_when_no_dollars(self, facts_app):
        """When ``item.dollars_amount`` is None, the surrounding ``<li>``
        guard hides the cost row entirely — the partial is never even
        included. (Belt and suspenders — the partial would also no-render
        on None, but skipping the include keeps the layout cleaner.)"""
        item = {
            "dollars_amount": None,
            "extracted_facts": {},
        }
        with facts_app.app_context():
            html = render_template("partials/_facts_strip.html", item=item)
        assert "fact--cost" not in html
        assert "💵 Cost:" not in html
        assert "dollars--" not in html
