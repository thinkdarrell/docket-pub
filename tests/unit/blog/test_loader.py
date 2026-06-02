"""Tests for the blog loader's frontmatter parsing."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from docket.blog.loader import LoaderError, load_posts_from_disk, parse_post_file


def test_parse_valid_post(fixtures_dir: Path):
    p = parse_post_file(
        fixtures_dir / "posts" / "birmingham" / "2026-06-02-hello.md",
        content_root=fixtures_dir / "posts",
    )
    assert p.title == "Hello, Birmingham"
    assert p.slug == "hello"
    assert p.date == date(2026, 6, 2)
    assert p.city == "birmingham"
    assert p.summary == "A test post for the loader."
    assert p.tags == ["test", "blog"]
    assert "# Hello" in p.body_markdown
    assert p.source_path == "birmingham/2026-06-02-hello.md"
    # body_html / authors filled in later stages — parser leaves them empty/raw
    assert p.body_html == ""
    assert p.authors == []
    assert p.status == "published"


def test_parse_missing_summary_raises(fixtures_dir: Path):
    with pytest.raises(LoaderError, match="summary"):
        parse_post_file(
            fixtures_dir / "posts" / "_drafts" / "2026-06-02-missing-summary.md",
            content_root=fixtures_dir / "posts",
        )


def test_load_posts_skips_drafts_dir(fixtures_dir):
    posts = load_posts_from_disk(
        content_root=fixtures_dir / "posts",
        known_city_slugs={"birmingham", "homewood"},
    )
    slugs = {p.slug for p in posts}
    assert "wip" not in slugs
    assert "hello" in slugs
    assert "shared" in slugs
    assert "zoning" in slugs


def test_load_posts_unknown_city_raises(fixtures_dir):
    with pytest.raises(LoaderError, match="unknown city"):
        load_posts_from_disk(
            content_root=fixtures_dir / "posts",
            known_city_slugs={"birmingham"},  # homewood missing
        )


def test_load_posts_duplicate_slug_raises(fixtures_dir):
    with pytest.raises(LoaderError, match="duplicate slug"):
        load_posts_from_disk(
            content_root=fixtures_dir / "posts_dup",
            known_city_slugs={"birmingham"},
        )
