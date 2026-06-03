"""Tests for the Substack cross-post helper."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.blog_to_substack import build_substack_markdown


@pytest.fixture
def sample_post(tmp_path: Path) -> Path:
    p = tmp_path / "birmingham" / "2026-05-15-budget.md"
    p.parent.mkdir(parents=True)
    p.write_text(
        "---\n"
        "title: Budget\n"
        "date: 2026-05-15\n"
        "city: birmingham\n"
        "summary: x\n"
        "---\n"
        "\n"
        "See ![](cover.jpg) for the chart.\n"
        "And [[item:42]] is the resolution.\n"
    )
    return p


def test_build_substack_markdown_rewrites_assets(sample_post):
    out = build_substack_markdown(
        sample_post,
        city="birmingham",
        slug="budget",
        item_titles={42: "Resolution to fund X"},
        meeting_titles={},
    )
    assert "title:" not in out  # frontmatter stripped
    assert "https://docket.pub/blog/assets/birmingham/budget/cover.jpg" in out
    assert "[Resolution to fund X](https://docket.pub/al/<unknown>/items/42/)" in out
