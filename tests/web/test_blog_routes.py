"""Tests for blog blueprint routes."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from flask import Flask

from docket.blog.types import Author, BlogState, Post
from docket.web.blog import bp as blog_bp


def _make_state(tmp_path: Path) -> BlogState:
    asset_dir = tmp_path / "birmingham" / "budget"
    asset_dir.mkdir(parents=True)
    (asset_dir / "cover.jpg").write_bytes(b"\xff\xd8\xff")  # tiny JPEG marker
    p = Post(
        title="Budget",
        slug="budget",
        date=date(2026, 5, 1),
        city="birmingham",
        summary="Budget post.",
        body_markdown="Body",
        body_html="<p>Body</p>",
        authors=[Author(key="darrell", display_name="Darrell", bio="", avatar_url=None)],
        tags=["budget"],
        cover_image_url="/blog/assets/birmingham/budget/cover.jpg",
        cross_posted_to={},
        related_item_ids=[],
        related_meeting_ids=[],
        status="published",
        extra_css=[],
        updated=None,
        reading_time_minutes=1,
        word_count=2,
        source_path="birmingham/2026-05-01-budget.md",
    )
    return BlogState(
        posts=[p],
        posts_by_id={("birmingham", "budget"): p},
        posts_by_item_id={},
        posts_by_meeting_id={},
        authors={"darrell": p.authors[0]},
    )


@pytest.fixture
def app(tmp_path: Path):
    import os
    from flask import Blueprint, Response
    template_dir = os.path.join(os.path.dirname(__file__), "..", "..", "src", "docket", "web", "templates")
    app = Flask(__name__, template_folder=template_dir)
    app.config["BLOG_CONTENT_ROOT"] = str(tmp_path)
    app.config["BLOG_STATE"] = _make_state(tmp_path)
    app.config["BLOG_PREVIEW_TOKEN"] = ""
    # Stub out the `public` blueprint so base.html partials' url_for calls resolve.
    public_stub = Blueprint("public", __name__)

    @public_stub.route("/rss/coverage.xml")
    def coverage_rss():
        return Response("", content_type="application/rss+xml")

    @public_stub.route("/")
    def index():
        return Response("")

    @public_stub.route("/search")
    def search():
        return Response("")

    @public_stub.route("/topics")
    def topics_index():
        return Response("")

    @public_stub.route("/about")
    def about():
        return Response("")

    @public_stub.route("/about/methodology")
    def about_methodology():
        return Response("")

    @public_stub.route("/about/corrections")
    def about_corrections():
        return Response("")

    @public_stub.route("/councilors")
    def councilors_index():
        return Response("")

    app.register_blueprint(public_stub)
    app.register_blueprint(blog_bp)
    def _post_url(post):
        if post.city == "_shared":
            return f"/blog/{post.slug}"
        return f"/al/{post.city}/blog/{post.slug}"
    app.jinja_env.globals["post_url"] = _post_url
    return app


def test_asset_route_serves_file(app):
    client = app.test_client()
    r = client.get("/blog/assets/birmingham/budget/cover.jpg")
    assert r.status_code == 200
    assert r.data.startswith(b"\xff\xd8\xff")


def test_asset_route_404_for_missing(app):
    client = app.test_client()
    r = client.get("/blog/assets/birmingham/budget/nope.png")
    assert r.status_code == 404


def test_asset_route_blocks_traversal(app):
    client = app.test_client()
    r = client.get("/blog/assets/birmingham/budget/..%2F..%2Fetc%2Fhosts")
    assert r.status_code in (400, 404)


def test_hub_lists_published_posts(app):
    client = app.test_client()
    r = client.get("/blog")
    assert r.status_code == 200
    assert b"Budget" in r.data
    assert b"Budget post." in r.data  # summary in card


def test_hub_hides_drafts_and_scheduled(app):
    from datetime import date as _date
    from docket.blog.types import Post

    state = app.config["BLOG_STATE"]
    draft = Post(
        title="Hidden draft",
        slug="hidden",
        date=_date(2026, 5, 1),
        city="birmingham",
        summary="Don't show me.",
        body_markdown="",
        body_html="<p>x</p>",
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
        source_path="x",
    )
    app.config["BLOG_STATE"] = BlogState(
        posts=state.posts + [draft],
        posts_by_id={**state.posts_by_id, ("birmingham", "hidden"): draft},
        posts_by_item_id=state.posts_by_item_id,
        posts_by_meeting_id=state.posts_by_meeting_id,
        authors=state.authors,
    )
    client = app.test_client()
    r = client.get("/blog")
    assert b"Don't show me." not in r.data


def test_city_route_filters_to_city_and_shared(app):
    from datetime import date as _date
    from docket.blog.types import Post

    state = app.config["BLOG_STATE"]
    shared = Post(
        title="Shared",
        slug="shared",
        date=_date(2026, 4, 1),
        city="_shared",
        summary="Shared summary.",
        body_markdown="",
        body_html="<p>x</p>",
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
        source_path="x",
    )
    homewood_only = Post(
        title="Homewood thing",
        slug="hw",
        date=_date(2026, 4, 15),
        city="homewood",
        summary="HW summary.",
        body_markdown="",
        body_html="<p>y</p>",
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
        source_path="y",
    )
    new_state = BlogState(
        posts=state.posts + [shared, homewood_only],
        posts_by_id={
            **state.posts_by_id,
            ("_shared", "shared"): shared,
            ("homewood", "hw"): homewood_only,
        },
        posts_by_item_id=state.posts_by_item_id,
        posts_by_meeting_id=state.posts_by_meeting_id,
        authors=state.authors,
    )
    app.config["BLOG_STATE"] = new_state

    client = app.test_client()
    r = client.get("/al/birmingham/blog")
    assert r.status_code == 200
    assert b"Budget" in r.data
    assert b"Shared summary." in r.data
    assert b"HW summary." not in r.data


def test_post_detail_renders(app):
    client = app.test_client()
    r = client.get("/al/birmingham/blog/budget")
    assert r.status_code == 200
    assert b"Budget" in r.data
    assert b"Body" in r.data


def test_post_detail_404_for_unknown(app):
    client = app.test_client()
    assert client.get("/al/birmingham/blog/nope").status_code == 404


def test_post_detail_draft_hidden_without_token(app):
    from datetime import date as _date
    from docket.blog.types import Post

    state = app.config["BLOG_STATE"]
    draft = Post(
        title="Draft",
        slug="draft",
        date=_date(2026, 5, 1),
        city="birmingham",
        summary="x",
        body_markdown="",
        body_html="<p>secret</p>",
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
        source_path="x",
    )
    app.config["BLOG_STATE"] = BlogState(
        posts=state.posts + [draft],
        posts_by_id={**state.posts_by_id, ("birmingham", "draft"): draft},
        posts_by_item_id=state.posts_by_item_id,
        posts_by_meeting_id=state.posts_by_meeting_id,
        authors=state.authors,
    )
    client = app.test_client()
    assert client.get("/al/birmingham/blog/draft").status_code == 404


def test_shared_post_route(app):
    from datetime import date as _date
    from docket.blog.types import Post

    state = app.config["BLOG_STATE"]
    shared = Post(
        title="Methodology update",
        slug="methodology",
        date=_date(2026, 4, 1),
        city="_shared",
        summary="x",
        body_markdown="",
        body_html="<p>shared body</p>",
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
        source_path="x",
    )
    app.config["BLOG_STATE"] = BlogState(
        posts=state.posts + [shared],
        posts_by_id={**state.posts_by_id, ("_shared", "methodology"): shared},
        posts_by_item_id=state.posts_by_item_id,
        posts_by_meeting_id=state.posts_by_meeting_id,
        authors=state.authors,
    )
    client = app.test_client()
    r = client.get("/blog/methodology")
    assert r.status_code == 200
    assert b"shared body" in r.data


def test_shared_post_route_404_for_unknown(app):
    client = app.test_client()
    assert client.get("/blog/nope").status_code == 404


def test_reserved_prefix_does_not_match_shared_post(app):
    """`/blog/tag/<tag>`, `/blog/assets/...`, `/blog/feed.xml` must keep working
    even though `/blog/<slug>` exists for shared posts."""
    # NOTE: `/blog/tag/<tag>` doesn't exist yet (Task 17 adds it). For this task,
    # only verify that `/blog/assets/...` still works.
    client = app.test_client()
    r = client.get("/blog/assets/birmingham/budget/cover.jpg")
    assert r.status_code == 200  # asset route still wins over shared post route
