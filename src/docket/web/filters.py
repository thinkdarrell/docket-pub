"""Custom Jinja2 filters for the Flask app.

Currently exposes:

- ``order_badges(badges)`` — Sort a mixed list of process+policy badge
  chips so process badges (alarm-level signals like split_vote /
  contested / sole_source) always render before policy badges, then
  policy badges sort by descending confidence and alphabetic slug.

  Spec §6.2, decision #64. Mirrors the helper in
  ``docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md``
  but uses dict-style access since ``BadgeChip`` rows are served via
  psycopg's ``RealDictCursor``.

- ``format_date(value)`` — Render a ``date`` / ``datetime`` (or ``None``)
  as a human-readable "Month D, YYYY" string (e.g. "May 15, 2026").
  Returns the empty string for ``None`` so missing values produce no
  text rather than crashing the template. Used by the engagement strip
  partial (spec §6.3) for ``next_steps.public_hearing_date``,
  ``comment_period_end``, and ``implementation_date``.

- ``format_timestamp(seconds)`` — Render an integer second count as
  ``H:MM:SS`` (1+ hour) or ``M:SS`` (under an hour). Spec §6.4 uses it
  to label video deep links (e.g. ``View Source: video at 1:23:45``).
  Returns the empty string for ``None`` / negative / non-numeric input
  so a malformed anchor doesn't crash the page.

- ``format_dollars(amount)`` — Render a ``Decimal`` / ``float`` / ``int``
  (or ``None``) as a US-formatted dollar string. Amounts under $1,000,000
  render at full precision (``$87,500``); amounts ≥ $1M abbreviate to
  ``$N.NM`` (``$1.8M``) for scannability — matches decision #71's
  example markup. Returns the empty string for ``None`` / 0 / negative /
  ``bool`` / ``NaN`` / ``Infinity`` / non-numeric input. Used by the
  dollar-tier partial (spec §6.1, decisions #71 + #75).

- ``dollar_tier(amount)`` — Return a :class:`DollarTier` NamedTuple
  ``(color, symbol, description)`` for use by ``partials/dollar_tier.html``,
  or ``None`` for missing/invalid input so the partial can short-circuit.
  Reuses :func:`docket.enrichment.dollars.classify_dollar_tier` for the
  color so the threshold constants live in one place.

  Backward compatibility: ``DollarTier.__str__`` returns ``self.color``
  so existing v2 templates that use ``{{ amt | dollar_tier }}`` inside
  a CSS class (``class="tier tier-{{ amt | dollar_tier }}"``) continue
  to render ``tier-green`` etc. — no template churn needed at the v2/v3
  cutover. New v3 partial uses dotted attribute access
  (``tier_data.color``).

The module exposes :func:`register` which the Flask app factory calls
to wire all filters into ``app.jinja_env.filters``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import NamedTuple

from flask import Flask

from docket.enrichment.dollars import classify_dollar_tier


# Process-badge alarm ordering (decision #64). Lower index = higher alarm.
# Slugs not in this list fall to position 999 — still grouped before policy
# badges, but after the seven known alarm levels.
process_alarm_order: list[str] = [
    "hidden_on_consent",
    "legal_settlement",
    "contested",
    "sole_source",
    "emergency_action",
    "split_vote",
    "amends_prior_contract",
]

# O(1) lookup built once at import — saves a linear ``list.index`` scan per
# badge per render. Private; tests rely on ``process_alarm_order``.
_PROCESS_RANK: dict[str, int] = {
    slug: i for i, slug in enumerate(process_alarm_order)
}


def order_badges(badges: Sequence[Mapping]) -> list[Mapping]:
    """Return ``badges`` sorted process-first, then policy.

    Process badges sort by their slug's index in :data:`process_alarm_order`
    (unknown slugs go to position 999). Policy badges sort by
    ``(-confidence, slug)`` — highest confidence first, ties broken
    alphabetically.

    Defensive against malformed rows: missing ``kind`` / ``slug`` /
    ``confidence`` keys are tolerated (treated as None / 0 / empty) so a
    single bad row from the DB does not crash the entire feed render.
    Rows without a recognised ``kind`` (neither 'process' nor 'policy')
    are dropped entirely — the badge_chip template can't render them.
    """
    process = sorted(
        [b for b in badges if b.get("kind") == "process"],
        key=lambda b: _PROCESS_RANK.get(b.get("slug"), 999),
    )
    policy = sorted(
        [b for b in badges if b.get("kind") == "policy"],
        key=lambda b: (-(b.get("confidence") or 0), b.get("slug") or ""),
    )
    return process + policy


def format_date(value: date | datetime | str | None) -> str:
    """Return ``value`` rendered as ``"%B %-d, %Y"`` (e.g. "May 15, 2026").

    Defensive against missing or malformed inputs:

    - ``None`` → ``""`` (empty string, so the template emits no text).
    - ``date`` / ``datetime`` → formatted directly via ``strftime``.
    - ``str`` → parsed as ISO-8601: tries ``date.fromisoformat`` first
      (handles ``YYYY-MM-DD``), then falls back to
      ``datetime.fromisoformat`` (handles full datetimes). The
      date-first order matters on Python 3.10, where
      ``datetime.fromisoformat`` rejects bare date strings — see
      https://docs.python.org/3.10/library/datetime.html#datetime.datetime.fromisoformat.
      If both parses fail the original string is returned untouched so
      the reader at least sees the raw value rather than a crash or
      empty cell. JSONB next_steps fields can round-trip through psycopg
      as ISO-8601 strings depending on the driver, so this is a real
      path.

    Other types (int, etc.) fall through to ``str(value)`` for safety.
    """
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.strftime("%B %-d, %Y")
    if isinstance(value, str):
        try:
            return date.fromisoformat(value).strftime("%B %-d, %Y")
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(value).strftime("%B %-d, %Y")
        except ValueError:
            return value
    return str(value)


def format_timestamp(value: int | float | str | None) -> str:
    """Return ``value`` (seconds) rendered as ``H:MM:SS`` or ``M:SS``.

    - 0 → ``"0:00"``
    - 65 → ``"1:05"``
    - 3600 → ``"1:00:00"``
    - 3725 → ``"1:02:05"``

    Defensive against missing or malformed inputs:

    - ``None`` → ``""`` (empty string).
    - Negative → ``""`` (negative durations are nonsensical).
    - Non-numeric / unparseable string → ``""``.
    - ``bool`` → ``""`` (``isinstance(True, int)`` is True in Python; we
      reject explicitly because a stray boolean from JSONB would format
      as ``"0:01"`` / ``"0:00"`` and look like a real timestamp).
    - ``float`` → coerced to ``int`` (truncates fractional seconds).
    - Numeric string → coerced via ``int(...)``, stripping a trailing
      ``.0`` if present (psycopg can hand back JSONB integers as strings
      depending on the driver path).

    Used by :file:`partials/source_anchor_button.html` (spec §6.4) to
    label video deep-link buttons.
    """
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, str):
        try:
            value = int(value)
        except (ValueError, OverflowError, TypeError):
            try:
                value = int(float(value))
            except (ValueError, OverflowError, TypeError):
                return ""
    if isinstance(value, float):
        # Reject inf / nan before int() raises OverflowError / ValueError —
        # math.isfinite is the cheapest catch-all.
        try:
            value = int(value)
        except (ValueError, OverflowError):
            return ""
    if not isinstance(value, int):
        return ""
    if value < 0:
        return ""
    hours, rem = divmod(value, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


# Million-dollar abbreviation threshold. Amounts >= this render as ``$N.NM``
# instead of full precision. Chosen at $1M because:
#  - it matches decision #71's example (``$1.8M ($$$$)``),
#  - it aligns with the Red-tier boundary so abbreviation only kicks in for
#    the highest-impact items (where one decimal place is enough to convey
#    scale and the extra digits hurt scannability in a card layout),
#  - the spec text on line 2536 shows full precision for $1.8M but
#    decision #71 (the canonical entry in the decisions log) shows
#    ``$1.8M``; decisions trump prose examples.
# Stored as a Decimal so equality boundaries with Decimal inputs are exact
# (no float rounding surprises).
_ABBREVIATE_AT = Decimal("1000000")


def _coerce_amount(value: object) -> Decimal | None:
    """Coerce an arbitrary value to a usable positive ``Decimal`` or None.

    Shared between :func:`format_dollars` and :func:`dollar_tier` so both
    apply the exact same defensive contract:

    - ``None`` → None.
    - ``bool`` → None (Python booleans are ints; ``format_dollars(True)``
      would otherwise render ``$1`` and look real — same trap as
      ``format_timestamp``).
    - ``Decimal('NaN')`` / ``Decimal('Infinity')`` → None
      (``Decimal.is_finite`` catches both with a single guard).
    - ``float('nan')`` / ``float('inf')`` → None (``math.isfinite``).
    - Numeric string → coerced via ``Decimal(stripped)``. JSONB
      driver paths can hand back numerics as strings.
    - Non-numeric string → None.
    - ``int`` / ``float`` / ``Decimal`` → coerced to Decimal.
    - Zero / negative → None. A negative dollar amount on an agenda
      item is nonsensical; zero means "no dollar info" not "$0 line
      item" — the column is NULL when extraction found nothing, but
      defending against 0 as well covers buggy enrichment runs.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, int):
        amount = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            return None
        # Round-trip through str to avoid float-binary-repr noise
        # (Decimal(0.1) is verbose; Decimal(str(0.1)) is exact).
        try:
            amount = Decimal(str(value))
        except InvalidOperation:
            return None
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            amount = Decimal(stripped)
        except InvalidOperation:
            return None
    else:
        return None

    if not amount.is_finite():
        return None
    if amount <= 0:
        return None
    return amount


def format_dollars(value: Decimal | float | int | str | None) -> str:
    """Return ``value`` rendered as a US-formatted dollar string.

    - Amounts < $1,000,000 render at full integer precision:
      ``Decimal("87500")`` → ``"$87,500"``.
    - Amounts ≥ $1,000,000 abbreviate to one decimal place:
      ``Decimal("1800000")`` → ``"$1.8M"``,
      ``Decimal("1000000")`` → ``"$1.0M"``,
      ``Decimal("12500000")`` → ``"$12.5M"``.

    The $1M abbreviation threshold matches decision #71's canonical
    example markup. See the ``_ABBREVIATE_AT`` module constant for the
    rationale.

    Cents are intentionally dropped — agenda-item dollar amounts are
    not invoiced totals; a $87,500.42 contract reads as $87,500 to a
    reader scanning a feed. The structured ``extracted_facts`` JSONB
    preserves precision if it ever matters.

    Defensive contract (delegates to :func:`_coerce_amount`):

    - ``None`` → ``""`` (empty string, consistent with
      :func:`format_date`'s missing-value contract).
    - ``0`` / ``Decimal("0")`` / negative → ``""``.
    - ``bool`` → ``""``.
    - ``Decimal("NaN")`` / ``Decimal("Infinity")`` / ``float('inf')``
      → ``""``.
    - Empty / non-numeric string → ``""``.
    - Numeric string → coerced.

    Used by :file:`partials/dollar_tier.html` (spec §6.1, decision #71).
    """
    amount = _coerce_amount(value)
    if amount is None:
        return ""
    if amount >= _ABBREVIATE_AT:
        # quantize keeps Decimal arithmetic exact (no float intermediate)
        # and drops the trailing zeros only when integer-valued; otherwise
        # one decimal place. ``$1,000,000 → $1.0M`` (not $1M) because
        # the ".0" is a deliberate scale signal — readers see "$1M" as
        # ambiguous (could be $1.499M rounded down).
        millions = amount / _ABBREVIATE_AT
        return f"${millions:.1f}M"
    # Full precision for sub-$1M, dropping cents. ``:,`` adds thousands
    # separators; ``int(...)`` truncates fractional dollars.
    return f"${int(amount):,}"


class DollarTier(NamedTuple):
    """Tier metadata for a dollar amount — color, symbol, threshold prose.

    Returned by :func:`dollar_tier`. NamedTuple (not a plain 3-tuple)
    so the partial reads ``{{ tier_data.color }}`` instead of
    ``{{ tier_data[0] }}`` — easier to grep, easier to extend if a
    fourth dimension (e.g. WCAG contrast ratio) ever lands. Still
    tuple-unpackable in tests: ``color, symbol, desc = dollar_tier(amt)``.

    ``__str__`` returns ``self.color`` so the legacy v2 template idiom
    ``class="tier tier-{{ amt | dollar_tier }}"`` keeps working. v3
    partials use attribute access.
    """

    color: str         # 'green' | 'yellow' | 'orange' | 'red'
    symbol: str        # '$' | '$$' | '$$$' | '$$$$'
    description: str   # 'under $50,000', '$50,000 to $250,000', etc.

    def __str__(self) -> str:  # pragma: no cover - exercised via Jinja
        return self.color


# Tier symbol + threshold prose, keyed by the colour string returned from
# :func:`docket.enrichment.dollars.classify_dollar_tier`. Single source of
# truth for the threshold constants lives in ``enrichment/dollars.py``;
# this dict only carries the WCAG-presentation metadata layered on top.
#
# When ``_TIER_GREEN`` / ``_TIER_YELLOW`` / ``_TIER_ORANGE`` thresholds
# change in ``enrichment/dollars.py``, update the prose strings here too.
# The tests in ``tests/unit/test_dollar_tier.py`` assert these strings
# verbatim, so CI catches drift.
_TIER_METADATA: dict[str, tuple[str, str]] = {
    "green":  ("$",    "under $50,000"),
    "yellow": ("$$",   "$50,000 to $250,000"),
    "orange": ("$$$",  "$250,000 to $1 million"),
    "red":    ("$$$$", "over $1 million"),
}


def dollar_tier(value: Decimal | float | int | str | None) -> DollarTier | None:
    """Return tier metadata for ``value`` as a :class:`DollarTier`, or None.

    Reuses :func:`docket.enrichment.dollars.classify_dollar_tier` to
    map the amount to a colour (so the threshold constants live in one
    place — see ``enrichment/dollars.py``). This filter layers the
    WCAG-presentation metadata on top: tier symbol (``$``/``$$``/``$$$``/
    ``$$$$``) and human-readable threshold description (used as the
    parenthetical in the parent ``aria-label``).

    Boundary semantics (inherited from ``classify_dollar_tier``):

    - amount < $50,000           → ``("green",  "$",    "under $50,000")``
    - $50,000 ≤ a < $250,000     → ``("yellow", "$$",   "$50,000 to $250,000")``
    - $250,000 ≤ a < $1,000,000  → ``("orange", "$$$",  "$250,000 to $1 million")``
    - a ≥ $1,000,000             → ``("red",    "$$$$", "over $1 million")``

    Defensive contract (delegates to :func:`_coerce_amount`): same
    rejection rules as :func:`format_dollars` — ``None`` / 0 /
    negative / ``bool`` / ``NaN`` / ``Infinity`` / non-numeric strings
    all return ``None`` so :file:`partials/dollar_tier.html` can
    short-circuit with ``{% if tier_data %}``.

    Used by :file:`partials/dollar_tier.html` (spec §6.1, decisions
    #71 + #75).
    """
    amount = _coerce_amount(value)
    if amount is None:
        return None
    color = classify_dollar_tier(amount)
    metadata = _TIER_METADATA.get(color)
    if metadata is None:
        # Defence in depth — if a future change to classify_dollar_tier
        # adds a new tier without updating this map, fail closed
        # (no render) rather than emit a broken aria-label.
        return None
    symbol, description = metadata
    return DollarTier(color=color, symbol=symbol, description=description)


def register(app: Flask) -> None:
    """Register custom Jinja filters on ``app``."""
    app.jinja_env.filters["order_badges"] = order_badges
    app.jinja_env.filters["format_date"] = format_date
    app.jinja_env.filters["format_timestamp"] = format_timestamp
    app.jinja_env.filters["format_dollars"] = format_dollars
    app.jinja_env.filters["dollar_tier"] = dollar_tier
