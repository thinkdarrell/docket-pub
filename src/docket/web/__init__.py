"""Flask application factory."""

from __future__ import annotations

import os
from datetime import timezone as _tz
from pathlib import Path

from flask import Flask, render_template
from werkzeug.middleware.proxy_fix import ProxyFix

from docket.blog.loader import load_blog_state
from docket.blog.types import Post
from docket.config import (
    ADMIN_EMAIL,
    BLOG_AUTHORS_YAML,
    BLOG_CONTENT_ROOT,
    BLOG_PREVIEW_TOKEN,
    FLASK_ENV,
    SECRET_KEY,
)
from docket.services import query as _query


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    # Railway terminates TLS at its edge proxy and forwards plain HTTP to the
    # container with X-Forwarded-Proto: https. ProxyFix promotes that header
    # into the WSGI environ so request.scheme / request.url_root render as
    # https://. Without this the Atom feed self/entry <id> + <link> tags
    # serialise as http://docket.pub/... (readers chase the redirect but the
    # canonical URLs are wrong).
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

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

    # to_utc: normalize a datetime to UTC for RSS pubDate rendering.
    # psycopg returns datetimes in the Postgres server TimeZone; locally that
    # may be America/Chicago, making the hardcoded "+0000" suffix wrong.
    # This filter normalises naive datetimes (assumed UTC) and aware datetimes
    # (astimezone conversion) so the strftime always produces correct UTC output.
    def _to_utc(dt):
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=_tz.utc)
        return dt.astimezone(_tz.utc)

    app.jinja_env.filters['to_utc'] = _to_utc

    # Source-anchor URL safety: ``is_url_safe`` resolves the domain
    # allowlist lazily through :func:`source_security.get_allowlist`
    # (TTL-cached, 10-minute refresh from ``municipalities.adapter_config``).
    # Replaces the previous eager build at app-init that required a
    # Railway redeploy whenever a new municipality was added. The admin
    # endpoint ``POST /admin/source-security/refresh`` invalidates the
    # cache for instant onboarding.
    from docket.web import source_security

    app.jinja_env.globals["is_source_url_safe"] = source_security.is_url_safe

    # ``today`` — re-evaluated per request so templates can flag meetings
    # as upcoming via ``{% if meeting.meeting_date >= today %}``. Used by
    # the meeting / item cards and the Vote Result block's no-vote branch
    # to distinguish "meeting hasn't happened yet" from "couldn't match a
    # vote." Context-processor (not jinja_env.globals) so each request
    # sees the current date — globals are bound at app-init only.
    #
    # Anchored to America/Chicago because every docket.pub city
    # (Birmingham, Mobile, Montgomery, Hoover, Homewood, Vestavia
    # Hills) is in Central Time. A naive `date.today()` would read
    # UTC on Railway, so an actively-running 7pm CT meeting (01:00
    # UTC next day) would slip from "Upcoming" to "couldn't match a
    # vote" exactly at 7pm CT — the worst possible moment.
    # If we add cities outside Central, change to a per-request
    # lookup keyed off the municipality's timezone.
    from datetime import datetime as _datetime
    from zoneinfo import ZoneInfo as _ZoneInfo

    _LOCAL_TZ = _ZoneInfo("America/Chicago")

    @app.context_processor
    def _inject_today():
        return {"today": _datetime.now(_LOCAL_TZ).date()}

    # ``is_upcoming(meeting)`` — Jinja global (not a context processor) so it
    # is bound once at app-init and available in every template.  A global is
    # the right primitive here: the function is stateless and pure (it reads
    # the clock internally when ``now`` is omitted), so there's no need for a
    # per-request injection.
    #
    # The wrapper handles BOTH shapes that templates encounter:
    #   • Meeting / RawMeeting dataclasses  → attribute access
    #   • psycopg dict rows                 → key access (what list_upcoming_meetings returns)
    # Passing ``None`` (empty rail state) returns False without raising.
    from docket.services.meeting_time import is_upcoming as _is_upcoming_impl

    def _is_upcoming_template(meeting) -> bool:
        """Jinja wrapper that accepts either a Meeting/RawMeeting object or a
        dict row (psycopg returns row mappings, models return dataclasses)."""
        if meeting is None:
            return False
        if hasattr(meeting, "meeting_date"):
            md = meeting.meeting_date
            st = getattr(meeting, "start_time", None)
        else:
            md = meeting.get("meeting_date")
            st = meeting.get("start_time")
        return _is_upcoming_impl(md, st)

    app.jinja_env.globals["is_upcoming"] = _is_upcoming_template

    # Register blueprints
    from docket.web.admin import bp as admin_bp
    from docket.web.admin_badge_review import bp as admin_badge_review_bp
    from docket.web.auth import bp as auth_bp
    from docket.web.blog import bp as blog_bp
    from docket.web.public import bp as public_bp

    app.config["BLOG_CONTENT_ROOT"] = BLOG_CONTENT_ROOT
    app.config["BLOG_PREVIEW_TOKEN"] = BLOG_PREVIEW_TOKEN
    try:
        known_city_slugs = {m["slug"] for m in _query.list_municipalities()}
    except Exception:
        # If the DB is unavailable at app-factory time (unusual: only happens
        # in tooling contexts), boot with an empty city set. The loader will
        # still raise on unknown city dirs the first time it runs.
        known_city_slugs = set()
    app.config["BLOG_STATE"] = load_blog_state(
        content_root=Path(BLOG_CONTENT_ROOT),
        authors_yaml=Path(BLOG_AUTHORS_YAML),
        known_city_slugs=known_city_slugs,
    )

    # Single source of truth for a post's canonical URL — used by templates,
    # OG tags, canonical link, Atom feed. Avoids hand-coding /al/<city>/blog
    # vs /blog/<slug> at every callsite. See spec §4 "Canonical URL helper".
    def _post_url(post: "Post") -> str:
        if post.city == "_shared":
            return f"/blog/{post.slug}"
        return f"/al/{post.city}/blog/{post.slug}"

    app.jinja_env.globals["post_url"] = _post_url
    app.register_blueprint(blog_bp)

    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(admin_badge_review_bp)

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

    # P5 task B4 — custom error templates. Both inherit base.html so the
    # masthead + footer + typography from P1 render even on error pages,
    # which is friendlier than Flask's bare default error responses.
    @app.errorhandler(404)
    def _not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def _server_error(e):
        return render_template("errors/500.html"), 500

    return app
