"""Flask application factory."""

from __future__ import annotations

import os

from flask import Flask

from docket.config import ADMIN_EMAIL, FLASK_ENV, SECRET_KEY


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    app.config["SECRET_KEY"] = SECRET_KEY
    app.config["ADMIN_EMAIL"] = ADMIN_EMAIL

    # E6 — SMART_BREVITY_UI feature flag. Defaults to false. Set to "true"
    # in Railway env vars to flip v3 card rendering on. The dispatcher
    # itself (partials/smart_brevity_card.html) only fires when this flag
    # is true AND A8 has exposed the v3 columns on AgendaItem (already
    # done as of commit ab48fa2). Flag-off path is byte-identical to
    # current production v2 rendering.
    #
    # ``.strip().lower()`` is defensive against ``" TRUE\n"`` or similar
    # values from the Railway dashboard. Only the literal string "true"
    # (case-insensitive, whitespace-trimmed) enables v3 — "1", "yes",
    # "True ", etc. all evaluate to false except "True".
    app.config["SMART_BREVITY_UI"] = (
        os.environ.get("SMART_BREVITY_UI", "").strip().lower() == "true"
    )

    # Production cookie security
    if FLASK_ENV != "development":
        app.config["SESSION_COOKIE_SECURE"] = True
        app.config["SESSION_COOKIE_HTTPONLY"] = True
        app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    # Register Jinja filters (order_badges, etc.)
    from . import filters

    filters.register(app)

    # Source-anchor URL safety: ``is_url_safe`` resolves the domain
    # allowlist lazily through :func:`source_security.get_allowlist`
    # (TTL-cached, 10-minute refresh from ``municipalities.adapter_config``).
    # Replaces the previous eager build at app-init that required a
    # Railway redeploy whenever a new municipality was added. The admin
    # endpoint ``POST /admin/source-security/refresh`` invalidates the
    # cache for instant onboarding.
    from docket.web import source_security

    app.jinja_env.globals["is_source_url_safe"] = source_security.is_url_safe

    # Register blueprints
    from docket.web.admin import bp as admin_bp
    from docket.web.auth import bp as auth_bp
    from docket.web.public import bp as public_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)

    # Strict-Transport-Security: pin browsers to HTTPS once they've successfully
    # connected. 1 year (31536000s). includeSubDomains is intentionally omitted
    # until www.docket.pub is also Railway-served with its own cert; otherwise
    # browsers would force-upgrade www to HTTPS and fail to connect.
    if FLASK_ENV != "development":
        @app.after_request
        def _add_hsts(response):
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000"
            )
            return response

    return app
