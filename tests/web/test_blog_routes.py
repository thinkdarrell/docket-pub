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
    template_dir = os.path.join(os.path.dirname(__file__), "..", "..", "src", "docket", "web", "templates")
    app = Flask(__name__, template_folder=template_dir)
    app.config["BLOG_CONTENT_ROOT"] = str(tmp_path)
    app.config["BLOG_STATE"] = _make_state(tmp_path)
    app.config["BLOG_PREVIEW_TOKEN"] = ""
    app.register_blueprint(blog_bp)
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
