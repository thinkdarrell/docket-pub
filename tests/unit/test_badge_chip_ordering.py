"""Unit tests for E2: badge_chip partial + order_badges filter.

Two layers:

1. ``order_badges()`` — pure-Python sort helper. Verifies process badges
   come first in alarm-level order (with unknown slugs sinking to 999),
   then policy badges by descending confidence and alphabetical slug.

2. ``partials/badge_chip.html`` — Jinja render. Verifies the
   Verification Spark (✨) only appears at confidence>=1.0, the
   ``badge-conf-high`` / ``badge-conf-medium`` class flips at 1.0, the
   ``badge-meta`` vote-count span renders for split_vote /contested
   only when ``vote_count`` is provided, and the ``· AI-verified`` title
   suffix is gated by confidence.

Tests are self-contained: no DB, no Flask app — just a Jinja Environment
pointed at the templates dir.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

from docket.web.filters import order_badges, process_alarm_order


# ---------------------------------------------------------------------------
# order_badges()
# ---------------------------------------------------------------------------


def _process(slug: str, confidence: float = 1.0) -> dict:
    return {
        "kind": "process",
        "slug": slug,
        "confidence": confidence,
        "name": slug,
        "icon": "!",
        "description": f"process {slug}",
    }


def _policy(slug: str, confidence: float) -> dict:
    return {
        "kind": "policy",
        "slug": slug,
        "confidence": confidence,
        "name": slug,
        "icon": "*",
        "description": f"policy {slug}",
    }


def test_order_badges_empty():
    assert order_badges([]) == []


def test_order_badges_process_first_then_policy():
    badges = [
        _policy("climate_resilience", 0.9),
        _process("split_vote"),
        _policy("affordable_housing", 0.95),
        _process("contested"),
    ]
    out = order_badges(badges)

    # First two must be process, in alarm order: contested (idx 2) before
    # split_vote (idx 5).
    kinds = [b["kind"] for b in out]
    assert kinds == ["process", "process", "policy", "policy"]
    assert out[0]["slug"] == "contested"
    assert out[1]["slug"] == "split_vote"


def test_order_badges_process_alarm_levels():
    """All seven known process slugs sort by their position in
    process_alarm_order, not alphabetically and not by confidence."""
    # Insert in scrambled order; expect the canonical order back.
    scrambled = [
        _process("amends_prior_contract"),
        _process("hidden_on_consent"),
        _process("emergency_action"),
        _process("legal_settlement"),
        _process("split_vote"),
        _process("contested"),
        _process("sole_source"),
    ]
    out = order_badges(scrambled)
    assert [b["slug"] for b in out] == process_alarm_order


def test_order_badges_unknown_process_slug_goes_last_among_process():
    badges = [
        _process("zzz_brand_new_alarm"),  # not in process_alarm_order
        _process("contested"),
        _process("split_vote"),
    ]
    out = order_badges(badges)
    # Known process slugs come first in alarm order, unknown lands at 999.
    assert [b["slug"] for b in out] == [
        "contested",
        "split_vote",
        "zzz_brand_new_alarm",
    ]


def test_order_badges_policy_sorted_by_confidence_desc_then_slug():
    badges = [
        _policy("climate_resilience", 0.7),
        _policy("affordable_housing", 0.95),
        _policy("public_safety", 0.95),
        _policy("walkability", 0.5),
    ]
    out = order_badges(badges)
    # Highest confidence first; tie at 0.95 broken alphabetically.
    assert [b["slug"] for b in out] == [
        "affordable_housing",
        "public_safety",
        "climate_resilience",
        "walkability",
    ]


def test_order_badges_mixed_keeps_groups_separate():
    """A high-confidence policy badge does NOT leapfrog a low-confidence
    process badge — process always wins regardless of confidence."""
    badges = [
        _policy("climate_resilience", 1.0),
        _process("amends_prior_contract", confidence=0.5),
    ]
    out = order_badges(badges)
    assert out[0]["kind"] == "process"
    assert out[1]["kind"] == "policy"


def test_order_badges_tolerates_malformed_rows():
    """A single row missing kind/slug/confidence must not crash the sort.

    Defensive contract (I2): rows whose ``kind`` is neither 'process' nor
    'policy' (including missing ``kind``) are dropped — the badge_chip
    template can't render them anyway. Process/policy rows with missing
    ``slug`` or ``confidence`` are kept and treated as None / 0 / empty.
    """
    badges = [
        {},  # missing kind — dropped
        {"kind": "process"},  # missing slug — kept, ranked 999
        {"kind": "process", "slug": "unknown_slug"},  # unknown slug — ranked 999
        {"kind": "process", "slug": "contested", "confidence": 1.0},  # known
        {"kind": "policy", "slug": "climate_resilience"},  # missing confidence
        {"kind": "policy", "slug": "affordable_housing", "confidence": 0.9},
    ]
    # Should not raise.
    out = order_badges(badges)

    # Empty {} dropped; the other five survive.
    assert len(out) == 5

    # Process group comes first; 'contested' (known, rank 2) before the two
    # rank-999 entries.
    kinds = [b.get("kind") for b in out]
    assert kinds == ["process", "process", "process", "policy", "policy"]
    assert out[0].get("slug") == "contested"

    # Policy: confidence=0.9 ('affordable_housing') beats missing-confidence
    # ('climate_resilience' coerced to 0).
    assert out[3].get("slug") == "affordable_housing"
    assert out[4].get("slug") == "climate_resilience"


# ---------------------------------------------------------------------------
# partials/badge_chip.html render
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def jinja_env():
    """Jinja env rooted at the templates dir; no Flask, no app context."""
    repo_root = Path(__file__).resolve().parents[2]
    templates_dir = repo_root / "src" / "docket" / "web" / "templates"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html"]),
    )
    return env


def _render_chip(env, chip):
    tpl = env.get_template("partials/badge_chip.html")
    return tpl.render(chip=chip)


def test_chip_high_confidence_has_spark_and_ai_verified_title(jinja_env):
    chip = {
        "kind": "process",
        "slug": "split_vote",
        "confidence": 1.0,
        "name": "Split vote",
        "icon": "🤝",
        "description": "Council was divided",
    }
    html = _render_chip(jinja_env, chip)

    assert "badge-conf-high" in html
    assert "badge-conf-medium" not in html
    assert 'class="badge-spark"' in html
    assert "✨" in html
    assert 'aria-label="AI-verified"' in html
    # Title suffix gated on confidence>=1.0
    assert "· AI-verified" in html


def test_chip_medium_confidence_no_spark(jinja_env):
    chip = {
        "kind": "policy",
        "slug": "climate_resilience",
        "confidence": 0.85,
        "name": "Climate",
        "icon": "🌿",
        "description": "Affects climate goals",
    }
    html = _render_chip(jinja_env, chip)

    assert "badge-conf-medium" in html
    assert "badge-conf-high" not in html
    assert "badge-spark" not in html
    assert "✨" not in html
    # No AI-verified suffix on the title attribute
    assert "AI-verified" not in html


def test_chip_split_vote_with_vote_count_renders_meta(jinja_env):
    chip = {
        "kind": "process",
        "slug": "split_vote",
        "confidence": 1.0,
        "name": "Split vote",
        "icon": "🤝",
        "description": "Council was divided",
        "vote_count": {"yes": 5, "no": 4},
    }
    html = _render_chip(jinja_env, chip)
    assert 'class="badge-meta"' in html
    assert "5-4" in html


def test_chip_split_vote_without_vote_count_omits_meta(jinja_env):
    chip = {
        "kind": "process",
        "slug": "split_vote",
        "confidence": 1.0,
        "name": "Split vote",
        "icon": "🤝",
        "description": "Council was divided",
    }
    html = _render_chip(jinja_env, chip)
    assert "badge-meta" not in html


def test_chip_non_split_slug_does_not_render_meta_even_with_vote_count(jinja_env):
    """Only split_vote / contested slugs honor vote_count; other slugs
    must not render a badge-meta span even if vote_count is present."""
    chip = {
        "kind": "policy",
        "slug": "climate_resilience",
        "confidence": 0.9,
        "name": "Climate",
        "icon": "🌿",
        "description": "Affects climate goals",
        "vote_count": {"yes": 5, "no": 4},
    }
    html = _render_chip(jinja_env, chip)
    assert "badge-meta" not in html


def test_chip_class_includes_kind_and_slug(jinja_env):
    chip = {
        "kind": "process",
        "slug": "contested",
        "confidence": 1.0,
        "name": "Contested",
        "icon": "⚠️",
        "description": "Multiple sponsors disagreed",
    }
    html = _render_chip(jinja_env, chip)
    assert "badge-process" in html
    assert "badge-slug-contested" in html


def test_chip_none_confidence_renders_medium_no_spark(jinja_env):
    """I1 defensive: a chip with confidence=None must not crash the
    >= 1.0 comparison. It should render as `badge-conf-medium`, no
    Verification Spark, and no `· AI-verified` title suffix."""
    chip = {
        "kind": "policy",
        "slug": "climate_resilience",
        "confidence": None,
        "name": "Climate",
        "icon": "🌿",
        "description": "Affects climate goals",
    }
    html = _render_chip(jinja_env, chip)
    assert "badge-conf-medium" in html
    assert "badge-conf-high" not in html
    assert "badge-spark" not in html
    assert "✨" not in html
    assert "AI-verified" not in html
