# src/docket/web/csrf.py
"""Session-token CSRF for the admin_transcripts blueprint (issue #83 tracks the older admin routes).

Templates render ``<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">``;
HTMX requests may send ``X-CSRF-Token`` instead. Validation runs in the
blueprint's before_request for every state-changing method.
"""
from __future__ import annotations

import hmac
import secrets

from flask import abort, request, session

_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def csrf_token() -> str:
    tok = session.get("csrf_token")
    if not tok:
        tok = secrets.token_hex(32)
        session["csrf_token"] = tok
    return tok


def validate_csrf() -> None:
    if request.method not in _UNSAFE:
        return
    sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
    expected = session.get("csrf_token")
    if not (sent and expected and hmac.compare_digest(sent, expected)):
        abort(400, "CSRF token missing or invalid")


def register(app) -> None:
    app.jinja_env.globals["csrf_token"] = csrf_token
