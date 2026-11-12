"""Crawler policy: ``/robots.txt`` and the sitemap family.

The policy in one paragraph: search engines and readers are welcome on every
public page; nobody is sent into the admin area, the search results page, or
query-string URLs (which multiply without end); and crawlers that identify
themselves as collecting AI training data are disallowed from the whole
site. ``robots.txt`` is a request, not a wall. A crawler that ignores it has
to be handled at the server, not here.

The sitemaps exist so welcome crawlers find item pages directly instead of
discovering tens of thousands of them by following links. Layout:

    /sitemap.xml                       index of every file below
    /sitemaps/pages.xml                the site-wide pages (home, about, ...)
    /sitemaps/<city>/meetings.xml      the city's overview pages + each meeting
    /sitemaps/<city>/items-<n>.xml     the city's agenda items, 10,000 per file

Every sitemap response is rendered once a day per URL and held in a small
in-process cache, mirroring ``_rss_cached`` in :mod:`docket.web.public`.
"""

from __future__ import annotations

import threading
import time
from xml.sax.saxutils import escape

from flask import Blueprint, Response, abort, url_for

from docket.services import sitemap as sitemap_svc

bp = Blueprint("crawlers", __name__)

#: Seconds a rendered sitemap is reused. Meetings are ingested once a day,
#: so a day-old sitemap is at most one ingest behind.
SITEMAP_TTL_SECONDS = 86_400
_CACHE_CONTROL = f"public, max-age={SITEMAP_TTL_SECONDS}"

#: Crawlers that identify themselves as gathering AI training data, or as
#: fetching pages on behalf of an AI assistant. Each gets ``Disallow: /``.
#: The ``-Extended`` tokens are the training-only controls of Google and
#: Apple; their ordinary search crawlers are unaffected and stay welcome.
#: Editing this list changes the published policy; the about page describes
#: it in words.
AI_CRAWLERS = (
    "GPTBot",
    "ChatGPT-User",
    "OAI-SearchBot",
    "ClaudeBot",
    "Claude-Web",
    "Claude-SearchBot",
    "Claude-User",
    "anthropic-ai",
    "Google-Extended",
    "Applebot-Extended",
    "Bytespider",
    "TikTokSpider",
    "CCBot",
    "PerplexityBot",
    "Perplexity-User",
    "Amazonbot",
    "meta-externalagent",
    "meta-externalfetcher",
    "FacebookBot",
    "cohere-ai",
    "cohere-training-data-crawler",
    "Diffbot",
    "omgili",
    "omgilibot",
    "webzio-extended",
    "Timpibot",
    "YouBot",
    "AI2Bot",
    "Ai2Bot-Dolma",
    "PanguBot",
    "DuckAssistBot",
    "MistralAI-User",
    "Kangaroo Bot",
    "ImagesiftBot",
    "img2dataset",
    "PetalBot",
)

#: Site-wide pages listed in ``/sitemaps/pages.xml``. City pages are not
#: here; each city's own sitemap lists them.
SITE_PAGES = (
    "/",
    "/about/",
    "/about/how-we-read-minutes/",
    "/about/corrections/",
    "/coverage/",
    "/councilors/",
)

_ROBOTS_HEADER = """\
# docket.pub crawler policy
#
# docket.pub publishes Alabama municipal meeting records, with every fact
# linked to the city's own source document. Search engines and readers are
# welcome on every public page.
#
# Use of this site's content to train AI models is not permitted. The
# crawlers listed further down identify themselves as collecting training
# data or as fetching on behalf of an AI assistant; they are disallowed
# from the whole site.
#
# Questions: hello@docket.pub
"""

_ROBOTS_GENERAL = """\
User-agent: *
Allow: /
Disallow: /admin/
Disallow: /search
Disallow: /*?
"""


def robots_body(sitemap_url: str) -> str:
    """The full ``robots.txt`` text, given the absolute sitemap index URL."""
    ai_block = "".join(f"User-agent: {agent}\n" for agent in AI_CRAWLERS) + "Disallow: /\n"
    return "\n".join([_ROBOTS_HEADER, _ROBOTS_GENERAL, ai_block, f"Sitemap: {sitemap_url}\n"])


@bp.route("/robots.txt")
def robots_txt() -> Response:
    body = robots_body(url_for("crawlers.sitemap_index", _external=True))
    return Response(body, mimetype="text/plain", headers={"Cache-Control": _CACHE_CONTROL})


# --- sitemap rendering -------------------------------------------------------

_cache: dict[str, tuple[float, str]] = {}
_lock = threading.Lock()


def clear_cache() -> None:
    """Forget every rendered sitemap. Tests call this after seeding rows."""
    with _lock:
        _cache.clear()


def _cached(key: str, render_fn) -> str:
    now = time.time()
    hit = _cache.get(key)
    if hit and (now - hit[0]) < SITEMAP_TTL_SECONDS:
        return hit[1]
    with _lock:
        hit = _cache.get(key)
        if hit and (time.time() - hit[0]) < SITEMAP_TTL_SECONDS:
            return hit[1]
        rendered = render_fn()
        _cache[key] = (time.time(), rendered)
        return rendered


def _xml_response(body: str) -> Response:
    return Response(body, mimetype="application/xml", headers={"Cache-Control": _CACHE_CONTROL})


def _lastmod(value) -> str:
    return f"<lastmod>{value.date().isoformat()}</lastmod>" if value else ""


def _urlset(entries) -> str:
    """``entries`` is an iterable of ``(absolute_url, updated_at_or_None)``."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, updated in entries:
        lines.append(f"<url><loc>{escape(loc)}</loc>{_lastmod(updated)}</url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def _abs(path: str) -> str:
    return url_for("crawlers.sitemap_index", _external=True).removesuffix("/sitemap.xml") + path


@bp.route("/sitemap.xml")
def sitemap_index() -> Response:
    def render() -> str:
        lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
                 f"<sitemap><loc>{escape(_abs('/sitemaps/pages.xml'))}</loc></sitemap>"]
        for city in sitemap_svc.list_cities():
            slug = city["slug"]
            lines.append(f"<sitemap><loc>{escape(_abs(f'/sitemaps/{slug}/meetings.xml'))}</loc></sitemap>")
            for page in range(1, city["item_pages"] + 1):
                lines.append(f"<sitemap><loc>{escape(_abs(f'/sitemaps/{slug}/items-{page}.xml'))}</loc></sitemap>")
        lines.append("</sitemapindex>")
        return "\n".join(lines) + "\n"

    return _xml_response(_cached("index", render))


@bp.route("/sitemaps/pages.xml")
def sitemap_pages() -> Response:
    return _xml_response(_cached("pages", lambda: _urlset((_abs(p), None) for p in SITE_PAGES)))


@bp.route("/sitemaps/<slug>/meetings.xml")
def sitemap_city_meetings(slug: str) -> Response:
    if not sitemap_svc.city_exists(slug):
        abort(404)

    def render() -> str:
        entries = [(_abs(f"/al/{slug}/"), None),
                   (_abs(f"/al/{slug}/meetings/"), None),
                   (_abs(f"/al/{slug}/council/"), None)]
        entries += [(_abs(f"/al/{slug}/meetings/{m['id']}/"), m["updated_at"])
                    for m in sitemap_svc.list_meetings(slug)]
        return _urlset(entries)

    return _xml_response(_cached(f"meetings:{slug}", render))


@bp.route("/sitemaps/<slug>/items-<int:page>.xml")
def sitemap_city_items(slug: str, page: int) -> Response:
    if page < 1 or not sitemap_svc.city_exists(slug):
        abort(404)
    items = sitemap_svc.list_items(slug, page)
    if not items:
        abort(404)
    return _xml_response(_cached(
        f"items:{slug}:{page}",
        lambda: _urlset((_abs(f"/al/{slug}/items/{i['id']}/"), i["updated_at"]) for i in items),
    ))
