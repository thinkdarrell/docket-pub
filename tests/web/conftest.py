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


@pytest.fixture(scope="module")
def render_partial():
    """Return a helper that renders a Jinja template inside a request context.

    The helper signature is::

        render_partial(template_path: str, **context) -> str

    where ``template_path`` is relative to the app's template directory
    (e.g. ``'partials/num_stat.html'``).

    Scope is ``module`` to match the project convention for app-creating
    fixtures (see ``tests/unit/test_card_shell.py``, etc.). ``create_app``
    is stateless across renders, so sharing one app across a module's
    tests is safe and avoids the per-test factory cost.

    Context-key safety: Flask's default ``jinja_env`` uses ``Undefined``
    (not ``StrictUndefined``), so a missing context key silently renders
    as an empty string. This is by design — many of the partials being
    tested have ``{% if optional_thing %}`` guards, and tests of those
    branches intentionally omit the key. If you want a missing key to
    raise, supply the key with an ``Undefined``-typed sentinel explicitly.
    """
    app = create_app()

    def _render(template_path: str, **context) -> str:
        with app.test_request_context():
            return render_template(template_path, **context)

    return _render


@pytest.fixture(scope="module")
def client():
    """Flask test client for route-level HTTP assertions.

    Scope is ``module`` to match ``render_partial`` — one app per module,
    shared across all tests in the file.  Routes that return 404 do so
    without DB access, so no database fixture is needed.
    """
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
