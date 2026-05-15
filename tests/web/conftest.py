"""Pytest fixtures shared across tests/web/.

``render_partial`` — renders any Jinja partial (or full template) inside a
Flask ``test_request_context()`` so that ``url_for(...)`` calls inside the
template resolve without raising ``RuntimeError``.  A bare ``app_context()``
is not sufficient because Flask's URL adapter requires a request context to
know scheme + server name.

Usage::

    def test_my_partial(render_partial):
        html = render_partial('partials/num_stat.html', label='Meetings', value=42)
        assert '42' in html
"""

from __future__ import annotations

import pytest
from flask import render_template

from docket.web import create_app


@pytest.fixture
def render_partial():
    """Return a helper that renders a Jinja template inside a request context.

    The helper signature is::

        render_partial(template_path: str, **context) -> str

    where ``template_path`` is relative to the app's template directory
    (e.g. ``'partials/num_stat.html'``).
    """
    app = create_app()

    def _render(template_path: str, **context) -> str:
        with app.test_request_context():
            return render_template(template_path, **context)

    return _render
