"""Flask application factory."""

from __future__ import annotations

from flask import Flask

from docket.config import SECRET_KEY


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    app.config["SECRET_KEY"] = SECRET_KEY

    # Register blueprints
    from docket.web.public import bp as public_bp

    app.register_blueprint(public_bp)

    return app
