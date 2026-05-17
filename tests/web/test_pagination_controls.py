"""Render tests for partials/pagination_controls.html.

Exercises:
- Hidden when page=1 and has_next=False (single-page result set).
- Renders Next when has_next=True.
- Renders Previous when page > 1.
- Preserves query params other than `page` (q, city, etc.).
"""

from __future__ import annotations

from flask import render_template

from docket.web import create_app


def _render_at(url: str, **context) -> str:
    """Render the pagination partial inside a request context for ``url``
    so that ``request.args`` carries the expected query params."""
    app = create_app()
    with app.test_request_context(url):
        return render_template(
            "partials/pagination_controls.html",
            **context,
        )


def test_renders_nothing_on_single_page_result_set():
    """page=1 + no next page → no pager renders at all."""
    html = _render_at("/search?q=foo", page=1, has_next=False)
    assert "Previous" not in html
    assert "Next" not in html
    # Section element from the partial must not appear either.
    assert "pagination-section" not in html


def test_renders_next_only_on_first_page_with_more_results():
    html = _render_at("/search?q=foo", page=1, has_next=True)
    assert "Next →" in html
    assert "Previous" not in html


def test_renders_both_prev_and_next_on_middle_page():
    html = _render_at("/search?q=foo&page=2", page=2, has_next=True)
    assert "← Previous" in html
    assert "Next →" in html


def test_renders_only_prev_on_last_page():
    html = _render_at("/search?q=foo&page=3", page=3, has_next=False)
    assert "← Previous" in html
    assert "Next →" not in html


def test_preserves_query_string_params_across_pages():
    """The pager URL must carry `q=foo&city=birmingham` (or whatever
    other query params are present) so filters survive pagination."""
    html = _render_at(
        "/search?q=council&city=birmingham&page=2", page=2, has_next=True,
    )
    # Next-link href should keep q + city and bump page to 3.
    assert "q=council" in html
    assert "city=birmingham" in html
    assert "page=3" in html
    # Previous-link href bumps page back to 1.
    assert "page=1" in html


def test_url_encodes_query_param_values():
    """Multi-word search like `q=public works` must be URL-encoded so the
    next-page link doesn't break on the space."""
    html = _render_at("/search?q=public works&page=2", page=2, has_next=True)
    # Space → %20 (or +) under urlencode. Accept either canonical form.
    assert "q=public%20works" in html or "q=public+works" in html


def test_page_param_is_rewritten_not_duplicated():
    """Old `page=2` must NOT appear in the rewritten URL — only the new
    page number. Otherwise the query string has two page= entries and
    Flask picks the first one, breaking pagination."""
    html = _render_at("/search?q=foo&page=2", page=2, has_next=True)
    # Count the substring "page=" — should appear at most twice (once
    # for prev, once for next). page=2 itself MUST NOT be carried over.
    assert "page=2&" not in html
    assert "page=2'" not in html
    assert 'page=2"' not in html
