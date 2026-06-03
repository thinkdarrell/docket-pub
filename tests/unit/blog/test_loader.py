"""Tests for the blog loader's frontmatter parsing."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

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
            fixtures_dir / "posts_missing_summary" / "birmingham" / "2026-06-02-missing-summary.md",
            content_root=fixtures_dir / "posts_missing_summary",
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
            content_root=fixtures_dir / "posts_unknown_city",
            known_city_slugs={"birmingham"},  # homewood missing
        )


def test_load_posts_duplicate_slug_raises(fixtures_dir):
    with pytest.raises(LoaderError, match="duplicate slug"):
        load_posts_from_disk(
            content_root=fixtures_dir / "posts_dup",
            known_city_slugs={"birmingham"},
        )


from datetime import date as _date


def test_future_date_overrides_published_status(fixtures_dir):
    posts = load_posts_from_disk(
        content_root=fixtures_dir / "posts",
        known_city_slugs={"birmingham", "homewood"},
    )
    future = next(p for p in posts if p.slug == "future")
    # Per spec §3 "Status precedence (strict)": future date wins regardless of status.
    assert future.status == "scheduled"
    assert future.is_published_as_of(_date(2026, 6, 2)) is False


def test_explicit_draft_in_normal_dir(fixtures_dir):
    posts = load_posts_from_disk(
        content_root=fixtures_dir / "posts",
        known_city_slugs={"birmingham", "homewood"},
    )
    draft = next(p for p in posts if p.slug == "explicit-draft")
    assert draft.status == "draft"
    assert draft.is_published_as_of(_date(2026, 6, 2)) is False


def test_unknown_frontmatter_key_logs_warning(tmp_path, caplog):
    """F1 (spec §3 row 5): unknown frontmatter keys log a warning but don't
    crash. Forward-compat — lets us add new keys without breaking old posts."""
    p = tmp_path / "birmingham" / "2026-06-02-extra-key.md"
    p.parent.mkdir(parents=True)
    p.write_text(
        "---\n"
        "title: Has extra keys\n"
        "date: 2026-06-02\n"
        "city: birmingham\n"
        "summary: x\n"
        "totally_made_up: yes\n"
        "another_unknown: 42\n"
        "---\n"
        "Body."
    )
    with caplog.at_level("WARNING", logger="docket.blog.loader"):
        post = parse_post_file(p, content_root=tmp_path)

    # Post still loads (warning, not error).
    assert post.title == "Has extra keys"
    # Both unknown keys flagged.
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "totally_made_up" in messages
    assert "another_unknown" in messages
    # Known keys NOT mentioned in warnings.
    assert "title" not in messages
    assert "summary" not in messages


def test_known_frontmatter_keys_emit_no_warning(tmp_path, caplog):
    """All spec §3 documented keys should be silent — no false positives."""
    p = tmp_path / "birmingham" / "2026-06-02-all-keys.md"
    p.parent.mkdir(parents=True)
    p.write_text(
        "---\n"
        "title: All keys\n"
        "slug: all-keys\n"
        "date: 2026-06-02\n"
        "updated: 2026-06-04\n"
        "city: birmingham\n"
        "authors: [darrell]\n"
        "summary: All known frontmatter fields.\n"
        "tags: [test]\n"
        "cover_image: cover.jpg\n"
        "cross_posted_to:\n"
        "  substack: https://example.com\n"
        "related_items: [1]\n"
        "related_meetings: [2]\n"
        "status: published\n"
        "extra_css: [custom.css]\n"
        "---\n"
        "Body."
    )
    with caplog.at_level("WARNING", logger="docket.blog.loader"):
        parse_post_file(p, content_root=tmp_path)

    unknown_key_warnings = [
        r for r in caplog.records if "unknown frontmatter key" in r.getMessage().lower()
    ]
    assert unknown_key_warnings == []


class _EmptyCursor:
    """Stub cursor whose fetchall always returns []. Models a DB where the
    referenced item/meeting IDs don't exist."""

    def execute(self, sql, params):
        pass

    def fetchall(self):
        return []


def _write_post_with_relations(
    tmp_path: Path,
    *,
    related_items: list[int],
    related_meetings: list[int],
    authors_yaml_text: str = "darrell:\n  display_name: Darrell\n",
):
    content_root = tmp_path / "content"
    (content_root / "birmingham").mkdir(parents=True)
    items_yaml = "[" + ",".join(str(i) for i in related_items) + "]"
    meetings_yaml = "[" + ",".join(str(i) for i in related_meetings) + "]"
    (content_root / "birmingham" / "2026-06-02-test.md").write_text(
        f"---\n"
        f"title: Test\n"
        f"date: 2026-06-02\n"
        f"city: birmingham\n"
        f"summary: x\n"
        f"authors: [darrell]\n"
        f"related_items: {items_yaml}\n"
        f"related_meetings: {meetings_yaml}\n"
        f"---\n"
        f"Body."
    )
    authors_yaml = tmp_path / "authors.yaml"
    authors_yaml.write_text(authors_yaml_text)
    return content_root, authors_yaml


def test_dead_related_item_id_logs_warning(tmp_path, caplog):
    """F2 (spec §6 row 3): related_items pointing to a non-existent agenda_item
    logs a warning. The reverse index keeps the orphan entry but it never gets
    queried (item-detail page only renders for valid IDs)."""
    from docket.blog.loader import load_blog_state

    content_root, authors_yaml = _write_post_with_relations(
        tmp_path, related_items=[99999], related_meetings=[]
    )

    with patch("docket.blog.shortcodes._open_cursor") as mock_open:
        mock_open.return_value.__enter__.return_value = _EmptyCursor()
        with caplog.at_level("WARNING", logger="docket.blog.loader"):
            state = load_blog_state(
                content_root=content_root,
                authors_yaml=authors_yaml,
                known_city_slugs={"birmingham"},
            )

    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "99999" in messages
    assert "related_items" in messages
    # Post still loaded.
    assert state.posts[0].slug == "test"


def test_dead_related_meeting_id_logs_warning(tmp_path, caplog):
    from docket.blog.loader import load_blog_state

    content_root, authors_yaml = _write_post_with_relations(
        tmp_path, related_items=[], related_meetings=[88888]
    )

    with patch("docket.blog.shortcodes._open_cursor") as mock_open:
        mock_open.return_value.__enter__.return_value = _EmptyCursor()
        with caplog.at_level("WARNING", logger="docket.blog.loader"):
            load_blog_state(
                content_root=content_root,
                authors_yaml=authors_yaml,
                known_city_slugs={"birmingham"},
            )

    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "88888" in messages
    assert "related_meetings" in messages


def test_resolvable_related_ids_emit_no_warning(tmp_path, caplog):
    """When the DB returns rows for the related_* IDs, no warning should fire."""
    from docket.blog.loader import load_blog_state

    content_root, authors_yaml = _write_post_with_relations(
        tmp_path, related_items=[3421], related_meetings=[2232]
    )

    class _ResolveCursor:
        def __init__(self):
            self._next = None

        def execute(self, sql, params):
            ids = params[0]
            if "agenda_items" in sql:
                self._next = [
                    {"id": i, "title": "Item title", "city_slug": "birmingham"}
                    for i in ids
                ]
            else:
                self._next = [
                    {"id": i, "title": "Meeting title", "city_slug": "birmingham"}
                    for i in ids
                ]

        def fetchall(self):
            return self._next

    with patch("docket.blog.shortcodes._open_cursor") as mock_open:
        mock_open.return_value.__enter__.return_value = _ResolveCursor()
        with caplog.at_level("WARNING", logger="docket.blog.loader"):
            load_blog_state(
                content_root=content_root,
                authors_yaml=authors_yaml,
                known_city_slugs={"birmingham"},
            )

    dead_id_warnings = [
        r for r in caplog.records
        if "related_" in r.getMessage()
    ]
    assert dead_id_warnings == []


def test_shared_reserved_slug_rejected(tmp_path):
    """A _shared post with a slug that collides with a reserved /blog/ prefix
    is a hard error (loader-level, not request-time)."""
    p = tmp_path / "_shared" / "2026-05-01-tag.md"
    p.parent.mkdir(parents=True)
    p.write_text(
        "---\n"
        "title: Tag\n"
        "date: 2026-05-01\n"
        "city: _shared\n"
        "summary: x\n"
        "---\n"
        "Body."
    )
    with pytest.raises(LoaderError, match="reserved slug"):
        load_posts_from_disk(
            content_root=tmp_path,
            known_city_slugs=set(),
        )
