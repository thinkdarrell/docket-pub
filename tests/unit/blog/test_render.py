"""Tests for the markdown rendering pipeline."""

from __future__ import annotations

from docket.blog.render import render_markdown


def test_basic_markdown():
    html = render_markdown("# Hello\n\nA paragraph.")
    assert "<h1" in html and "Hello</h1>" in html
    assert "<p>A paragraph.</p>" in html


def test_fenced_code():
    md = "```python\nprint('hi')\n```"
    html = render_markdown(md)
    # pymdownx.superfences wraps in <div class="highlight"> or emits a <pre><code>
    # depending on whether pygments is installed; both are valid.
    assert "print" in html and ("<pre" in html or "<code" in html)


def test_table():
    md = "| a | b |\n| - | - |\n| 1 | 2 |\n"
    html = render_markdown(md)
    assert "<table>" in html
    assert "<th>a</th>" in html


def test_attr_list_class():
    # attr_list requires the attribute dict on a new line for block elements
    md = "A callout.\n{.callout}"
    html = render_markdown(md)
    assert 'class="callout"' in html


def test_admonition():
    md = '!!! note "Heads up"\n    Body text.'
    html = render_markdown(md)
    assert 'class="admonition note"' in html
    assert "Heads up" in html


def test_mermaid_fence_emits_div():
    md = "```mermaid\ngraph TD; A-->B\n```"
    html = render_markdown(md)
    assert 'class="mermaid"' in html
    assert "graph TD" in html


def test_render_full_pipeline_expands_shortcodes():
    from docket.blog.render import render_post_html

    md = "See [[item:42]] for details."
    item_titles = {42: "Resolution to fund X"}
    html = render_post_html(
        md, city="birmingham", slug="budget",
        item_titles=item_titles, meeting_titles={},
    )
    assert "Resolution to fund X" in html
    assert 'href="/item/42"' in html


def test_render_full_pipeline_missing_shortcode_renders_plain():
    from docket.blog.render import render_post_html

    md = "Missing: [[item:9999]]."
    html = render_post_html(
        md, city="birmingham", slug="x",
        item_titles={}, meeting_titles={},
    )
    assert "[item:9999]" in html
