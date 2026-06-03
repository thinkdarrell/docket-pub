"""Dataclasses for the blog subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

PostStatus = Literal["published", "draft", "scheduled"]


@dataclass(frozen=True)
class Author:
    key: str
    display_name: str
    bio: str
    avatar_url: str | None
    links: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Post:
    title: str
    slug: str
    date: date
    city: str  # city slug, or "_shared"
    summary: str
    body_markdown: str
    body_html: str
    authors: list[Author]
    tags: list[str]
    cover_image_url: str | None  # already rewritten to /blog/assets/... or external
    cross_posted_to: dict[str, str]
    related_item_ids: list[int]
    related_meeting_ids: list[int]
    status: PostStatus
    extra_css: list[str]
    updated: date | None
    reading_time_minutes: int
    word_count: int
    source_path: str  # relative to content/blog/, e.g. "birmingham/2026-06-02-hello.md"
    # Internal: raw author keys from frontmatter, used by the loader to resolve
    # against AuthorsRegistry. Never read from request handlers.
    _author_keys: list[str] = field(default_factory=list)

    def is_published_as_of(self, today: date) -> bool:
        """True if this post should be visible to the public on the given day."""
        if self.status == "draft":
            return False
        return self.date <= today


@dataclass(frozen=True)
class BlogState:
    """In-memory snapshot of every post, plus reverse indexes for fast lookups."""

    posts: list[Post]
    posts_by_id: dict[tuple[str, str], Post]  # (city, slug) → Post
    posts_by_item_id: dict[int, list[Post]]  # for "Editorial coverage" rails
    posts_by_meeting_id: dict[int, list[Post]]
    authors: dict[str, Author]
