"""Integration tests: blog posts surfacing on existing docket.pub pages.

These tests boot the full Flask app via ``create_app()`` (the production
factory) and swap in an in-memory ``BlogState`` so the assertions cover the
real route → template → rail chain without writing files to disk.

The integration DB is the live local ``docket_db`` (per the project's
``tests/integration/conftest.py`` convention — no global rollback).
``Birmingham`` is seeded by migration 002 and is what the tests target.
"""

from __future__ import annotations

from datetime import date

import pytest

from docket.blog.types import Author, BlogState, Post


def _make_post(*, city: str, related_meetings: list[int] | None = None,
               related_items: list[int] | None = None,
               title: str = "Birmingham budget take",
               slug: str = "budget") -> Post:
    return Post(
        title=title,
        slug=slug,
        date=date(2026, 5, 15),
        city=city,
        summary="A test.",
        body_markdown="x",
        body_html="<p>x</p>",
        authors=[Author(key="d", display_name="Darrell", bio="", avatar_url=None)],
        tags=[],
        cover_image_url=None,
        cross_posted_to={},
        related_item_ids=list(related_items or []),
        related_meeting_ids=list(related_meetings or []),
        status="published",
        extra_css=[],
        updated=None,
        reading_time_minutes=1,
        word_count=1,
        source_path=f"{city}/2026-05-15-{slug}.md",
    )


def _state_with(post: Post | None = None) -> BlogState:
    """Build a BlogState containing zero or one post, with the reverse
    indexes wired so meeting / item rails will surface it."""
    if post is None:
        return BlogState(
            posts=[], posts_by_id={}, posts_by_item_id={},
            posts_by_meeting_id={}, authors={},
        )
    by_meeting: dict[int, list[Post]] = {}
    for mid in post.related_meeting_ids:
        by_meeting.setdefault(mid, []).append(post)
    by_item: dict[int, list[Post]] = {}
    for iid in post.related_item_ids:
        by_item.setdefault(iid, []).append(post)
    return BlogState(
        posts=[post],
        posts_by_id={(post.city, post.slug): post},
        posts_by_item_id=by_item,
        posts_by_meeting_id=by_meeting,
        authors={a.key: a for a in post.authors},
    )


@pytest.fixture
def app_with_db():
    """The production Flask app, wired against the local DB. Per the
    integration conftest convention, this fixture does NOT create or
    rollback DB rows — callers own that lifecycle (see ``seeded_*``
    fixtures in conftest)."""
    from docket.web import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def override_blog_state(app_with_db):
    """Helper that temporarily replaces ``app_with_db.config['BLOG_STATE']``
    and restores the original after the test, so a flaky test can't leak its
    BlogState into subsequent tests sharing the same app instance."""
    original = app_with_db.config.get("BLOG_STATE")

    def _swap(new_state: BlogState) -> None:
        app_with_db.config["BLOG_STATE"] = new_state

    yield _swap
    app_with_db.config["BLOG_STATE"] = original


def test_city_page_shows_blog_rail(app_with_db, override_blog_state, seeded_birmingham):
    """The Birmingham overview renders the 'From the blog' rail when at
    least one published post tagged ``birmingham`` exists."""
    override_blog_state(_state_with(_make_post(city="birmingham")))

    with app_with_db.test_client() as c:
        r = c.get("/al/birmingham/")
    assert r.status_code == 200
    assert b"From the blog" in r.data
    assert b"Birmingham budget take" in r.data


def test_meeting_detail_shows_coverage(
    app_with_db, override_blog_state, seeded_bham_meeting_2026
):
    """A post with ``related_meetings=[<id>]`` surfaces in the Editorial
    coverage rail on that meeting's detail page."""
    meeting_id = seeded_bham_meeting_2026
    post = _make_post(city="birmingham", related_meetings=[meeting_id])
    override_blog_state(_state_with(post))

    with app_with_db.test_client() as c:
        r = c.get(f"/al/birmingham/meetings/{meeting_id}/")
    assert r.status_code == 200
    assert b"Editorial coverage" in r.data
    assert b"Birmingham budget take" in r.data


def test_meeting_detail_no_rail_without_posts(
    app_with_db, override_blog_state, seeded_bham_meeting_2026
):
    """Empty BlogState → no Editorial coverage rail on the meeting page."""
    meeting_id = seeded_bham_meeting_2026
    override_blog_state(_state_with(None))

    with app_with_db.test_client() as c:
        r = c.get(f"/al/birmingham/meetings/{meeting_id}/")
    assert r.status_code == 200
    # The rail header should be absent — only the post-title we never set is
    # not enough on its own because the template may render other "coverage"
    # strings; the rail's distinctive header is what we check.
    assert b"Editorial coverage" not in r.data
