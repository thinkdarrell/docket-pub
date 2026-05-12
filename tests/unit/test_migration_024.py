"""Tests for migration 024 — category-landing presentation columns.

Asserts the post-migration state of priority_badge_templates:
  - Three new columns exist (accent_color, chart_title, chart_footnote).
  - Every badge row has a non-null accent_color (decision #6).
  - The hidden_on_consent description is the new copy, not the old.
  - chart_title is set for every badge (per migration body, all 11
    badges get chart_title — decision validated below).

These tests presume the migration has already been applied to the
local docket_db. CI / local dev runs `python -m docket.migrations.runner`
before pytest.
"""
from __future__ import annotations

import psycopg2.extras

from docket.db import db


def test_priority_badge_templates_has_new_columns():
    """All three migration-024 columns exist on priority_badge_templates."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT column_name
                   FROM information_schema.columns
                   WHERE table_name = 'priority_badge_templates'
                     AND column_name IN ('accent_color', 'chart_title', 'chart_footnote')
                   ORDER BY column_name"""
            )
            columns = [r[0] for r in cur.fetchall()]
    assert columns == ['accent_color', 'chart_footnote', 'chart_title']


def test_every_badge_has_an_accent_color():
    """Every v1 badge row must have a non-null accent_color.
    Required by PR C — Smart Brevity Card reads this column for the
    3px left-edge border. A NULL would render an invisible border.
    """
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT slug, accent_color FROM priority_badge_templates ORDER BY slug"
            )
            rows = cur.fetchall()

    null_slugs = [r["slug"] for r in rows if not r["accent_color"]]
    assert not null_slugs, f"Badges missing accent_color: {null_slugs}"
    assert len(rows) == 11, f"Expected 11 badges, got {len(rows)}"


def test_hidden_on_consent_description_grammar_fix():
    """The original copy had a singular-noun grammar bug; migration 024
    rewrites it. Asserting on the new copy is more specific than just
    'description is non-null' — it catches a future regression that
    re-applies the broken original (e.g., a misguided rollback).
    """
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT description FROM priority_badge_templates WHERE slug = 'hidden_on_consent'"
            )
            desc = cur.fetchone()[0]

    assert desc.startswith("Items the AI flagged as high-public-interest"), (
        f"Expected new description starting 'Items the AI flagged...'; got: {desc!r}"
    )
    assert "Item the AI judged should NOT" not in desc, (
        "Pre-migration broken copy must not be in place."
    )


def test_chart_title_set_for_every_badge():
    """All 11 v1 badges have a chart_title override. Future badges may
    omit this and rely on the template-side fallback; this test only
    pins the v1 set.
    """
    expected_slugs_with_chart_title = {
        'amends_prior_contract', 'blight_accountability', 'contested',
        'emergency_action', 'hidden_on_consent', 'housing_stability',
        'legal_settlement', 'property_recovery',
        'public_safety_tech_privacy', 'sole_source', 'split_vote',
    }
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT slug FROM priority_badge_templates WHERE chart_title IS NOT NULL"
            )
            slugs_with_title = {r["slug"] for r in cur.fetchall()}
    assert slugs_with_title == expected_slugs_with_chart_title


def test_chart_footnote_set_only_for_quirky_badges():
    """Only badges whose predicate has a citizen-visible quirk get a
    footnote. v1 set: hidden_on_consent (consent-only), split_vote +
    contested (roll-call-only). Other 8 are NULL.
    """
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT slug FROM priority_badge_templates WHERE chart_footnote IS NOT NULL ORDER BY slug"
            )
            slugs_with_footnote = [r["slug"] for r in cur.fetchall()]
    assert slugs_with_footnote == ['contested', 'hidden_on_consent', 'split_vote']
