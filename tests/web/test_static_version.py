"""A static file's address carries a hash of its bytes, so a deploy that
changes a stylesheet changes its address and a browser fetches the new one."""

import hashlib
import re
from pathlib import Path

from flask import url_for

from docket.web import create_app

STATIC = Path(__file__).resolve().parents[2] / "src/docket/web/static"


def test_a_static_address_carries_the_hash_of_the_file():
    app = create_app()
    with app.test_request_context():
        address = url_for("static", filename="layout.css")
    want = hashlib.sha1((STATIC / "layout.css").read_bytes()).hexdigest()[:10]
    assert address == f"/static/layout.css?v={want}"


def test_a_file_that_is_not_there_keeps_its_plain_address():
    app = create_app()
    with app.test_request_context():
        assert url_for("static", filename="no-such.css") == "/static/no-such.css"


def test_the_versioned_address_is_served():
    app = create_app()
    with app.test_request_context():
        address = url_for("static", filename="layout.css")
    resp = app.test_client().get(address)
    assert resp.status_code == 200
    assert b".minutes-page-step" in resp.data


def test_no_template_writes_a_stylesheet_or_script_address_by_hand():
    templates = STATIC.parent / "templates"
    by_hand = [
        f"{path.relative_to(templates)}: {m.group(0)}"
        for path in templates.rglob("*.html")
        for m in re.finditer(r'(?:href|src)="/static/[^"]*\.(?:css|js)"', path.read_text(encoding="utf-8"))
    ]
    assert by_hand == []
