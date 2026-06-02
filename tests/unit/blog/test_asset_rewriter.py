"""Tests for relative-to-absolute asset URL rewriting."""

from __future__ import annotations

from docket.blog.render import rewrite_asset_urls


def test_relative_image_rewritten():
    html = '<p><img src="revenue.png" alt="chart"></p>'
    out = rewrite_asset_urls(html, city="birmingham", slug="budget")
    assert 'src="/blog/assets/birmingham/budget/revenue.png"' in out


def test_absolute_http_passes_through():
    html = '<img src="https://cdn.example/x.png">'
    out = rewrite_asset_urls(html, city="birmingham", slug="budget")
    assert 'src="https://cdn.example/x.png"' in out


def test_root_path_passes_through():
    html = '<img src="/static/logo.png">'
    out = rewrite_asset_urls(html, city="birmingham", slug="budget")
    assert 'src="/static/logo.png"' in out


def test_data_uri_passes_through():
    html = '<img src="data:image/png;base64,xxx">'
    out = rewrite_asset_urls(html, city="birmingham", slug="budget")
    assert 'src="data:image/png;base64,xxx"' in out


def test_frontmatter_cover_image_helper():
    from docket.blog.render import rewrite_cover_image

    assert (
        rewrite_cover_image("cover.jpg", city="birmingham", slug="budget")
        == "/blog/assets/birmingham/budget/cover.jpg"
    )
    assert (
        rewrite_cover_image("https://cdn.example/x.jpg", city="birmingham", slug="budget")
        == "https://cdn.example/x.jpg"
    )
    assert rewrite_cover_image(None, city="birmingham", slug="budget") is None
