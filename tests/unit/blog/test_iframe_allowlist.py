"""Iframe allowlist tests — embed allowed hosts, strip others."""

from __future__ import annotations

from docket.blog.render import sanitize_iframes


def test_datawrapper_passes_through():
    html = '<iframe src="https://datawrapper.dwcdn.net/abc/1/" width="600" height="400"></iframe>'
    out = sanitize_iframes(html)
    assert "datawrapper.dwcdn.net" in out
    assert 'loading="lazy"' in out
    assert "sandbox=" in out
    assert 'width="600"' in out


def test_flourish_passes_through():
    html = '<iframe src="https://flo.uri.sh/visualisation/123/embed"></iframe>'
    assert "flo.uri.sh" in sanitize_iframes(html)


def test_youtube_passes_through():
    html = '<iframe src="https://www.youtube.com/embed/abc"></iframe>'
    assert "youtube.com" in sanitize_iframes(html)


def test_disallowed_host_stripped():
    html = '<p>Before</p><iframe src="https://evil.example.com/embed"></iframe><p>After</p>'
    out = sanitize_iframes(html)
    assert "evil.example.com" not in out
    assert "Before" in out and "After" in out


def test_iframe_without_src_stripped():
    out = sanitize_iframes("<iframe></iframe>x")
    assert "<iframe" not in out
    assert "x" in out
