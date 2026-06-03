"""ProxyFix is applied in create_app so X-Forwarded-Proto from Railway's edge
becomes the scheme in request.url_root.

Without this, the Atom feed's self/entry links serialise as http://docket.pub/...
because Railway terminates TLS at its edge proxy and the upstream container
sees plain HTTP. Atom readers chase the redirect so the feed works, but the
canonical URLs in <id>/<link href> tags should be https.
"""

from __future__ import annotations

from werkzeug.middleware.proxy_fix import ProxyFix

from docket.web import create_app


def test_create_app_wraps_wsgi_app_in_proxy_fix():
    app = create_app()
    assert isinstance(app.wsgi_app, ProxyFix)


def test_request_url_root_honors_x_forwarded_proto():
    """End-to-end behavioral check: a request carrying X-Forwarded-Proto: https
    should make request.url_root render as https://, which is what the Atom
    feed template interpolates as the base."""
    from flask import request

    app = create_app()

    @app.route("/_proxy_fix_probe")
    def _probe():
        return request.url_root

    client = app.test_client()
    r = client.get(
        "/_proxy_fix_probe",
        headers={"X-Forwarded-Proto": "https"},
    )
    assert r.status_code == 200
    assert r.data.decode().startswith("https://")
