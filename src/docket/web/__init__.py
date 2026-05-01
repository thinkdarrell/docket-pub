"""Flask application factory."""

from __future__ import annotations

from flask import Flask

from docket.config import FLASK_ENV, SECRET_KEY


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    app.config["SECRET_KEY"] = SECRET_KEY

    # Production cookie security
    if FLASK_ENV != "development":
        app.config["SESSION_COOKIE_SECURE"] = True
        app.config["SESSION_COOKIE_HTTPONLY"] = True
        app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    # Register blueprints
    from docket.web.admin import bp as admin_bp
    from docket.web.auth import bp as auth_bp
    from docket.web.public import bp as public_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)

    return app
