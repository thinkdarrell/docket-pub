"""Blog blueprint: hub, per-city listing, post detail, asset serving, RSS."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from flask import Blueprint, Response, abort, current_app, make_response, render_template, request, send_from_directory

bp = Blueprint("blog", __name__)


@bp.route("/blog/assets/<city>/<slug>/<path:filename>")
def asset(city: str, slug: str, filename: str):
    """Serve post assets from `content/blog/<city>/<slug>/`.
    Bypasses Flask's default static handler so post assets stay co-located
    with their markdown in the repo. send_from_directory blocks traversal."""
    content_root = Path(current_app.config["BLOG_CONTENT_ROOT"]).resolve()
    asset_dir = (content_root / city / slug).resolve()
    # Defense in depth: refuse anything that walks out of content_root.
    try:
        asset_dir.relative_to(content_root)
    except ValueError:
        abort(404)
    return send_from_directory(asset_dir, filename)


def _published_posts(state, today: date):
    return [p for p in state.posts if p.is_published_as_of(today)]


@bp.route("/blog")
def hub():
    state = current_app.config["BLOG_STATE"]
    today = date.today()
    posts = _published_posts(state, today)[:20]
    return render_template("blog/hub.html", posts=posts, today=today)


@bp.route("/al/<city>/blog")
def city(city: str):
    state = current_app.config["BLOG_STATE"]
    today = date.today()
    posts = [
        p for p in _published_posts(state, today)
        if p.city == city or p.city == "_shared"
    ][:20]
    return render_template("blog/city.html", city=city, posts=posts, today=today)


@bp.route("/al/<city>/blog/<slug>")
def post(city: str, slug: str):
    state = current_app.config["BLOG_STATE"]
    today = date.today()
    p = state.posts_by_id.get((city, slug))
    if p is None:
        abort(404)

    if not p.is_published_as_of(today):
        # Drafts/scheduled may be unlocked by an explicit preview token. The
        # token must be configured (non-empty) and match exactly.
        configured = current_app.config.get("BLOG_PREVIEW_TOKEN") or ""
        supplied = request.args.get("preview") or ""
        if not configured or supplied != configured:
            abort(404)
        resp = make_response(render_template("blog/post.html", post=p))
        resp.headers["X-Robots-Tag"] = "noindex"
        return resp

    return render_template("blog/post.html", post=p)


@bp.route("/blog/tag/<tag>")
def tag(tag: str):
    state = current_app.config["BLOG_STATE"]
    today = date.today()
    posts = [p for p in _published_posts(state, today) if tag in p.tags][:20]
    return render_template("blog/hub.html", posts=posts, today=today, tag=tag)


def _atom_response(template_kwargs):
    body = render_template("blog/feed.atom.xml", **template_kwargs)
    return Response(body, mimetype="application/atom+xml; charset=utf-8")


@bp.route("/blog/feed.xml")
def hub_feed():
    state = current_app.config["BLOG_STATE"]
    today = date.today()
    posts = _published_posts(state, today)[:50]
    return _atom_response({
        "posts": posts,
        "feed_title": "docket.pub blog",
        "feed_url": "/blog/feed.xml",
        "feed_html_url": "/blog",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })


@bp.route("/al/<city>/blog/feed.xml")
def city_feed(city: str):
    state = current_app.config["BLOG_STATE"]
    today = date.today()
    posts = [
        p for p in _published_posts(state, today) if p.city == city or p.city == "_shared"
    ][:50]
    return _atom_response({
        "posts": posts,
        "feed_title": f"docket.pub {city} blog",
        "feed_url": f"/al/{city}/blog/feed.xml",
        "feed_html_url": f"/al/{city}/blog",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })


@bp.route("/blog/<slug>")
def shared_post(slug: str):
    state = current_app.config["BLOG_STATE"]
    today = date.today()
    p = state.posts_by_id.get(("_shared", slug))
    if p is None:
        abort(404)
    if not p.is_published_as_of(today):
        configured = current_app.config.get("BLOG_PREVIEW_TOKEN") or ""
        supplied = request.args.get("preview") or ""
        if not configured or supplied != configured:
            abort(404)
        resp = make_response(render_template("blog/post.html", post=p))
        resp.headers["X-Robots-Tag"] = "noindex"
        return resp
    return render_template("blog/post.html", post=p)
