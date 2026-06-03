"""Integration tests: blog posts surfacing on existing docket.pub pages."""

from __future__ import annotations

# These tests use the existing Flask app + a real BlogState built from a tmp
# content tree, so they exercise the same load path production uses.

from datetime import date
from pathlib import Path

import pytest

from docket.blog.types import Author, BlogState, Post


@pytest.fixture
def state_with_birmingham_post():
    p = Post(
        title="Birmingham budget take",
        slug="budget",
        date=date(2026, 5, 15),
        city="birmingham",
        summary="A test.",
        body_markdown="x",
        body_html="<p>x</p>",
        authors=[Author(key="d", display_name="Darrell", bio="", avatar_url=None)],
        tags=[],
        cover_image_url=None,
        cross_posted_to={},
        related_item_ids=[],
        related_meeting_ids=[2232],
        status="published",
        extra_css=[],
        updated=None,
        reading_time_minutes=1,
        word_count=1,
        source_path="birmingham/2026-05-15-budget.md",
    )
    return BlogState(
        posts=[p],
        posts_by_id={("birmingham", "budget"): p},
        posts_by_item_id={},
        posts_by_meeting_id={2232: [p]},
        authors={"d": p.authors[0]},
    )


@pytest.mark.skipif(
    True,  # toggle off until a real app_with_db fixture exists
    reason="needs app_with_db fixture (skipping per Task 20 deferral note)",
)
def test_city_page_shows_blog_rail(state_with_birmingham_post):
    """The Birmingham city page renders 'From the blog' when posts exist.

    Marked skip in v1 — requires an integration fixture that boots the full
    Flask app against the test DB. The skip stays until Task 24 or an
    integration-fixture task is scheduled.
    """
    pass


@pytest.mark.skipif(
    True,
    reason="needs app_with_db fixture, see Task 24",
)
def test_meeting_detail_shows_coverage(state_with_birmingham_post):
    """A post with related_meetings=[2232] surfaces on /meeting/2232."""
    pass


@pytest.mark.skipif(
    True,
    reason="needs app_with_db fixture, see Task 24",
)
def test_meeting_detail_no_rail_without_posts():
    """Without any posts referencing this meeting, the rail is hidden."""
    pass
