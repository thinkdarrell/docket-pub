"""URL safety check for source-anchor deep links.

Combines a static allowlist of known platform domains with a dynamic
allowlist of municipality hosts loaded from ``municipalities.adapter_config``.
Blocks any URL whose host doesn't match either.

The static allowlist covers every supported CMS plus the public video
hosts citizens are realistically deep-linked into (Granicus player URLs
on a tenant subdomain, raw YouTube/Vimeo embeds). The dynamic allowlist
is read from the ``adapter_config->>'base_url'`` JSONB key — that's where
Birmingham's ``bhamal.granicus.com``, Vestavia's CivicClerk tenant, etc.
live in our schema (see migration 001 ``municipalities`` table). Together
they form a closed list: anything else (``evil.tld``, protocol-relative
``//``, ``javascript:``, ``data:``, ``file:``) gets rejected before the
partial emits an ``<a href>``.

Why not rely on the scheme guard alone?  ``http://`` and ``https://``
filter out the obvious XSS vectors but they don't stop us from rendering
a link to ``https://attacker.tld/cookie-grabber.html`` if a malformed
``source_anchor`` row ever gets stored. The closed allowlist makes it a
defense-in-depth check rather than a single-line gate.

Caching: the dynamic side is cached at module level with a 10-minute TTL
(see :func:`get_allowlist`). Onboarding a new municipality previously
required a redeploy to refresh the allowlist; now the new city is visible
within 10 minutes automatically, and the admin endpoint
``POST /admin/source-security/refresh`` (see :mod:`docket.web.admin`)
forces an immediate refresh by calling :func:`invalidate_cache`.

Usage from Jinja::

    {% if is_source_url_safe(anchor.url) %}

The Jinja global ``is_source_url_safe`` is registered in
:func:`docket.web.create_app`. It defers to the cached allowlist so the
DB query only runs on cache miss / refresh — typical request renders
stay in-memory.
"""

from __future__ import annotations

import time
from threading import Lock
from typing import Callable, ContextManager
from urllib.parse import urlparse


# Platform domains hardcoded — every supported CMS plus public video hosts.
# Add to this list when a new CMS is supported.
STATIC_ALLOWED_DOMAINS: frozenset[str] = frozenset({
    "granicus.com",     # Birmingham, etc.
    "civicclerk.com",   # Vestavia Hills, Mobile
    "civicplus.com",    # Hoover (stubbed)
    "youtube.com",
    "youtu.be",
    "vimeo.com",
})


def _normalize_host(host: str) -> str:
    """Strip port and userinfo from a netloc; lowercase the result.

    ``urlparse('https://user:pass@host:8080/p').netloc`` returns
    ``'user:pass@host:8080'`` — we only want ``host`` for allowlist
    matching. Lowercasing handles the ``HTTPS://Granicus.Com`` shape
    (DNS is case-insensitive, our allowlist is lower-case).
    """
    if "@" in host:
        host = host.split("@", 1)[1]
    if ":" in host:
        host = host.split(":", 1)[0]
    return host.lower()


def is_url_safe(
    url: object,
    allowed_domains: frozenset[str] | None = None,
) -> bool:
    """Return True iff ``url`` is http/https AND its host matches the allowlist.

    Suffix match uses a leading-dot anchor (``host.endswith('.' + domain)``)
    to prevent the classic ``granicus.com.evil.tld`` bypass — that string
    ends with ``granicus.com`` but is NOT a granicus.com subdomain. Exact
    match is also accepted (so ``granicus.com`` itself passes).

    ``allowed_domains`` defaults to the cached dynamic+static allowlist
    via :func:`get_allowlist`. Tests can pass an explicit frozenset to
    pin the allowlist independently of the cache; production calls (the
    Jinja global) leave it unset so the cache is consulted.

    Defensive against non-string input (None, int, list) and malformed
    URLs that raise inside ``urlparse``. Returns False rather than
    crashing the render.
    """
    if allowed_domains is None:
        allowed_domains = get_allowlist()
    if not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
    except (ValueError, AttributeError):
        return False
    if parsed.scheme.lower() not in ("http", "https"):
        return False
    host = _normalize_host(parsed.netloc)
    if not host:
        return False
    for domain in allowed_domains:
        if host == domain or host.endswith("." + domain):
            return True
    return False


def load_municipality_hosts(
    db_cursor_fn: Callable[[], ContextManager],
) -> frozenset[str]:
    """Read distinct municipality ``base_url`` hosts from ``adapter_config`` JSONB.

    ``db_cursor_fn`` is :func:`docket.db.db_cursor` (kept as a parameter
    so tests can inject a fake cursor without monkey-patching). Returns
    a frozenset of normalized hosts. Skips rows whose ``adapter_config``
    has no ``base_url`` or whose URL is malformed — a single bad row
    doesn't poison the whole allowlist.

    Only ``active=TRUE`` municipalities are included; deactivated cities
    shouldn't widen the allowlist.
    """
    hosts: set[str] = set()
    with db_cursor_fn() as cur:
        cur.execute(
            "SELECT adapter_config->>'base_url' AS url "
            "FROM municipalities "
            "WHERE active = TRUE "
            "  AND adapter_config ? 'base_url'"
        )
        for row in cur.fetchall():
            url = row["url"]
            if not url:
                continue
            try:
                parsed = urlparse(url.strip())
            except (ValueError, AttributeError):
                continue
            host = _normalize_host(parsed.netloc)
            if host:
                hosts.add(host)
    return frozenset(hosts)


def build_allowlist(
    db_cursor_fn: Callable[[], ContextManager],
) -> frozenset[str]:
    """Combine static + dynamic allowlist.

    Pure DB read + union — no caching here. Used by :func:`get_allowlist`
    on cache miss, and retained as a public function so existing tests
    (and any future operator script) can build the allowlist directly
    without touching the cache.
    """
    return STATIC_ALLOWED_DOMAINS | load_municipality_hosts(db_cursor_fn)


# ---------------------------------------------------------------------------
# Module-level TTL cache for the dynamic+static allowlist.
#
# Onboarding a new municipality previously required a Railway redeploy to
# rebuild ``app.config['SOURCE_DOMAIN_ALLOWLIST']`` from the
# ``municipalities`` table. That's operational debt for a non-developer
# task. We now cache the merged allowlist with a 10-minute TTL so a new
# city is visible without any redeploy, and an admin endpoint
# (``POST /admin/source-security/refresh``) calls :func:`invalidate_cache`
# for instant onboarding.
#
# Thread-safety: gunicorn forks per-worker, so each worker has its own
# ``_CACHE`` — but a single worker still serves multiple threads
# concurrently. The Lock prevents thundering-herd refresh: if N threads
# all observe an expired cache simultaneously, only one runs the DB
# query; the others block on the lock and pick up the freshly-cached
# value via the re-check inside the critical section.
# ---------------------------------------------------------------------------

_CACHE: tuple[float, frozenset[str]] | None = None  # (expiry_unix_ts, allowlist)
_CACHE_TTL_SECONDS = 600  # 10 minutes
_CACHE_LOCK = Lock()


def get_allowlist(
    db_cursor_fn: Callable[[], ContextManager] | None = None,
) -> frozenset[str]:
    """Return the cached allowlist, refreshing from DB if expired.

    ``db_cursor_fn`` defaults to :func:`docket.db.db_cursor`, but is
    parameterized so tests can inject a fake cursor without
    monkey-patching. The default lookup is deferred (lazy import) so
    importing this module never requires a DB connection.

    On a fresh cache, a single DB query runs and the result is memoized
    until ``_CACHE_TTL_SECONDS`` elapses. On DB failure, falls back to
    :data:`STATIC_ALLOWED_DOMAINS` rather than serving an empty allowlist
    that would suppress every source-anchor button — a degraded-but-
    functional render is preferable to silently dropping every link.
    The next request after the cache expires will retry the DB.
    """
    global _CACHE
    now = time.time()
    if _CACHE is not None and _CACHE[0] > now:
        return _CACHE[1]
    with _CACHE_LOCK:
        # Re-check inside the lock — another thread may have refreshed
        # while we were blocked. If so, return its value instead of
        # running a redundant DB query.
        if _CACHE is not None and _CACHE[0] > now:
            return _CACHE[1]
        if db_cursor_fn is None:
            from docket.db import db_cursor as db_cursor_fn  # noqa: F811
        try:
            allowlist = build_allowlist(db_cursor_fn)
        except Exception:
            # If the DB is unreachable we'd rather render every link via
            # the static set than render none at all. The next refresh
            # cycle (10 min) will retry; admin endpoint can also force
            # a retry via invalidate_cache().
            allowlist = STATIC_ALLOWED_DOMAINS
        _CACHE = (now + _CACHE_TTL_SECONDS, allowlist)
        return allowlist


def invalidate_cache() -> None:
    """Clear the cached allowlist.

    The next call to :func:`get_allowlist` will refresh from the DB.
    Used by the admin refresh endpoint (instant onboarding for a newly-
    added municipality) and by tests that need a clean cache state.
    """
    global _CACHE
    _CACHE = None
