"""Blog blueprint: hub, per-city listing, post detail, asset serving, RSS.

The posts are read when the process starts (``init_blog_state``, called by
``create_app``). When that read fails, most likely because the database did
not answer within the web process's limits, the process starts with an empty
blog, says so in the log at error level, and a later request to a blog
address reads them again (``_load_posts_if_pending``): at most once per
``BLOG_RETRY_SECONDS`` counted from the end of the last attempt, in one
thread at a time, until a read succeeds. Every line begins ``blog:`` and is
at warning level or above, because nothing configures logging for the web
process and Python's last-resort handler prints nothing below a warning.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path

from flask import Blueprint, Response, abort, current_app, make_response, render_template, request, send_from_directory

from docket.blog.loader import load_blog_state
from docket.blog.types import BlogState
from docket.services import query as _query

logger = logging.getLogger(__name__)

bp = Blueprint("blog", __name__)

# How long after a failed read of the posts ended the next one may start.
BLOG_RETRY_SECONDS = 30


class _PendingBlogState:
    """What a process whose posts did not load keeps until they do.

    Stored under ``app.config["BLOG_STATE_PENDING"]`` by a failed
    ``init_blog_state`` and removed by the read that succeeds.
    """

    def __init__(self, load, error_type: type[BaseException]) -> None:
        # The read to repeat: no argument, returns a BlogState or raises.
        self.load = load
        # Held by the one thread that is repeating the read.
        self.lock = threading.Lock()
        # The type of the exception the last attempt raised.
        self.error_type = error_type
        # A time.monotonic() value; no attempt is made before it.
        self.next_try = time.monotonic() + BLOG_RETRY_SECONDS


def _error_words(exc: BaseException) -> str:
    """The exception's type and text on one line (the driver's text ends in a line break)."""
    return f"{type(exc).__name__}: {' '.join(str(exc).split())}"


def init_blog_state(app, *, content_root: Path, authors_yaml: Path) -> None:
    """Read the posts into ``app.config["BLOG_STATE"]`` as the process starts.

    A read that raises anything (the database not answering, a malformed
    post or authors file) leaves an empty ``BlogState``, is logged at error
    level with its traceback, and leaves ``app.config["BLOG_STATE_PENDING"]``
    set so that a later request to a blog address repeats it. After a read
    that succeeds the key is absent.
    """

    def load() -> BlogState:
        known_city_slugs = {m["slug"] for m in _query.list_municipalities()}
        return load_blog_state(
            content_root=content_root,
            authors_yaml=authors_yaml,
            known_city_slugs=known_city_slugs,
        )

    try:
        state = load()
    except Exception as exc:
        app.config["BLOG_STATE"] = BlogState(
            posts=[], posts_by_id={}, posts_by_item_id={},
            posts_by_meeting_id={}, authors={},
        )
        app.config["BLOG_STATE_PENDING"] = _PendingBlogState(load, type(exc))
        logger.error(
            "blog: posts not loaded when the process started (%s); the blog is "
            "empty until a later request loads them; next try in %d s",
            _error_words(exc), BLOG_RETRY_SECONDS,
            exc_info=True,
        )
        return
    app.config["BLOG_STATE"] = state
    app.config.pop("BLOG_STATE_PENDING", None)


@bp.before_request
def _load_posts_if_pending() -> None:
    """Read the posts again when the read at start failed and a retry is due.

    Returns nothing on every path, so the request goes on to its route and
    reads whatever state the process then has: the request that repeats the
    read waits for it and, when it succeeds, is answered with the posts; a
    request that finds another thread reading does not wait.
    """
    # The asset route reads no post and must not wait for a read it does not use.
    if request.endpoint == "blog.asset":
        return None
    config = current_app.config
    pending = config.get("BLOG_STATE_PENDING")
    if pending is None or time.monotonic() < pending.next_try:
        return None
    if not pending.lock.acquire(blocking=False):
        return None
    try:
        # A thread that read the key just before another finished loading
        # holds an object that is no longer pending; its next_try alone
        # would have the posts read, and the recovery logged, a second time.
        if config.get("BLOG_STATE_PENDING") is not pending:
            return None
        if time.monotonic() < pending.next_try:
            return None
        try:
            state = pending.load()
        except Exception as exc:
            # Counted from the end of the attempt, which can last as long
            # as the connection limit.
            pending.next_try = time.monotonic() + BLOG_RETRY_SECONDS
            # A database that stays down prints one line a try; an error of
            # a new kind is printed in full once.
            new_kind = type(exc) is not pending.error_type
            pending.error_type = type(exc)
            logger.error(
                "blog: posts not loaded on a later request (%s); next try in %d s",
                _error_words(exc), BLOG_RETRY_SECONDS,
                exc_info=new_kind,
            )
            return None
        config["BLOG_STATE"] = state
        config.pop("BLOG_STATE_PENDING", None)
        logger.warning(
            "blog: posts loaded on a later request (%d posts)", len(state.posts)
        )
    finally:
        pending.lock.release()
    return None


@bp.after_request
def _noindex(resp: Response) -> Response:
    """Keep every blog response out of search indexes.

    The site no longer links to the blog; this asks search engines that
    already know its URLs to drop them. A header rather than a ``<meta>``
    tag so the feeds and assets are covered as well as the pages.
    """
    resp.headers["X-Robots-Tag"] = "noindex"
    return resp


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
    municipality = _query.get_municipality(city)
    return render_template(
        "blog/city.html", city=city, municipality=municipality, posts=posts, today=today
    )


@bp.route("/al/<city>/blog/<slug>")
def post(city: str, slug: str):
    state = current_app.config["BLOG_STATE"]
    today = date.today()
    p = state.posts_by_id.get((city, slug))
    if p is None:
        abort(404)

    municipality = _query.get_municipality(city)

    if not p.is_published_as_of(today):
        # Drafts/scheduled may be unlocked by an explicit preview token. The
        # token must be configured (non-empty) and match exactly.
        configured = current_app.config.get("BLOG_PREVIEW_TOKEN") or ""
        supplied = request.args.get("preview") or ""
        if not configured or supplied != configured:
            abort(404)
        resp = make_response(
            render_template("blog/post.html", post=p, municipality=municipality)
        )
        resp.headers["X-Robots-Tag"] = "noindex"
        return resp

    return render_template("blog/post.html", post=p, municipality=municipality)


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
