"""Tests for the Post and Author dataclasses."""

from __future__ import annotations

from datetime import date

from docket.blog.types import Author, Post


def test_post_has_required_fields():
    p = Post(
        title="Hello",
        slug="hello",
        date=date(2026, 6, 2),
        city="birmingham",
        summary="A test post.",
        body_markdown="# Hi",
        body_html="<h1>Hi</h1>",
        authors=[],
        tags=[],
        cover_image_url=None,
        cross_posted_to={},
        related_item_ids=[],
        related_meeting_ids=[],
        status="published",
        extra_css=[],
        updated=None,
        reading_time_minutes=1,
        word_count=1,
        source_path="birmingham/2026-06-02-hello.md",
    )
    assert p.is_published_as_of(date(2026, 6, 3)) is True
    assert p.is_published_as_of(date(2026, 6, 1)) is False  # future date


def test_post_draft_never_published():
    p = Post(
        title="Hello",
        slug="hello",
        date=date(2026, 1, 1),
        city="birmingham",
        summary="A test post.",
        body_markdown="# Hi",
        body_html="<h1>Hi</h1>",
        authors=[],
        tags=[],
        cover_image_url=None,
        cross_posted_to={},
        related_item_ids=[],
        related_meeting_ids=[],
        status="draft",
        extra_css=[],
        updated=None,
        reading_time_minutes=1,
        word_count=1,
        source_path="birmingham/2026-01-01-hello.md",
    )
    assert p.is_published_as_of(date(2026, 6, 3)) is False


def test_author_basic():
    a = Author(
        key="darrell",
        display_name="Darrell Nance",
        bio="Civic data nerd.",
        avatar_url="/static/blog/authors/darrell.jpg",
        links={"bluesky": "https://bsky.app/profile/x"},
    )
    assert a.display_name == "Darrell Nance"
