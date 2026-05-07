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

The module exposes :func:`register` which the Flask app factory calls
to wire ``order_badges`` and ``format_date`` into
``app.jinja_env.filters``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime

from flask import Flask


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


def register(app: Flask) -> None:
    """Register custom Jinja filters on ``app``."""
    app.jinja_env.filters["order_badges"] = order_badges
    app.jinja_env.filters["format_date"] = format_date
