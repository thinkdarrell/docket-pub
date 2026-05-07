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

The module exposes :func:`register` which the Flask app factory calls
to wire ``order_badges`` into ``app.jinja_env.filters``.
"""

from __future__ import annotations

from typing import Mapping, Sequence

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


def order_badges(badges: Sequence[Mapping]) -> list[Mapping]:
    """Return ``badges`` sorted process-first, then policy.

    Process badges sort by their slug's index in :data:`process_alarm_order`
    (unknown slugs go to position 999). Policy badges sort by
    ``(-confidence, slug)`` — highest confidence first, ties broken
    alphabetically.
    """
    process = sorted(
        [b for b in badges if b["kind"] == "process"],
        key=lambda b: (
            process_alarm_order.index(b["slug"])
            if b["slug"] in process_alarm_order
            else 999
        ),
    )
    policy = sorted(
        [b for b in badges if b["kind"] == "policy"],
        key=lambda b: (-b["confidence"], b["slug"]),
    )
    return process + policy


def register(app: Flask) -> None:
    """Register custom Jinja filters on ``app``."""
    app.jinja_env.filters["order_badges"] = order_badges
