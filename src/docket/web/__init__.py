"""Flask application factory."""

from __future__ import annotations

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

    # Production cookie security
    if FLASK_ENV != "development":
        app.config["SESSION_COOKIE_SECURE"] = True
        app.config["SESSION_COOKIE_HTTPONLY"] = True
        app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    # Register Jinja filters (order_badges, etc.)
    from . import filters

    filters.register(app)

    # Source-anchor URL safety: combine static platform allowlist with
    # dynamic municipality hosts read from `municipalities.adapter_config`.
    # If the DB is unavailable at app init (tests, broken connection),
    # fall back to the static set — production logs will surface real
    # connection problems on the first request anyway.
    from docket.db import db_cursor
    from docket.web import source_security

    try:
        allowlist = source_security.build_allowlist(db_cursor)
    except Exception:
        allowlist = source_security.STATIC_ALLOWED_DOMAINS

    app.config["SOURCE_DOMAIN_ALLOWLIST"] = allowlist
    app.jinja_env.globals["is_source_url_safe"] = (
        lambda url: source_security.is_url_safe(url, allowlist)
    )

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
