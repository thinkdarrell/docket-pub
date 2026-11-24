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

Caching: the merged list is kept at module level and read again from
the database ten minutes after a read that succeeded (see
:func:`get_allowlist`), so a new city is visible within ten minutes
with no redeploy, and the admin endpoint
``POST /admin/source-security/refresh`` (see :mod:`docket.web.admin`)
forces the next call to read by calling :func:`invalidate_cache`.

When the read fails or times out, the error is logged in a line that
begins ``source allowlist:``, the last list the database gave goes on
being served (never a wider one), and the read is tried again 30
seconds after the failed attempt ended. The fixed domains stand alone
only when no list has loaded in the process, which is logged as an
error. The line ``source allowlist: the database answered again``
records the recovery.

Usage from Jinja::

    {% if is_source_url_safe(anchor.url) %}

The Jinja global ``is_source_url_safe`` is registered in
:func:`docket.web.create_app`. It defers to the cached allowlist so the
DB query only runs on cache miss / refresh — typical request renders
stay in-memory.
"""

from __future__ import annotations

import logging
import time
from threading import Lock
from typing import Callable, Iterable
from urllib.parse import urlparse, urlsplit

logger = logging.getLogger(__name__)


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


def is_viewer_url(
    url: object,
    allowed_domains: frozenset[str] | None = None,
) -> bool:
    """True iff ``url`` is an address the minutes page viewer may fetch.

    Stricter than :func:`is_url_safe`, because a yes here lets the web
    process make a request to the address and not only print a link to it:

    * a string with no backslash, no white space and no control character
      anywhere in it (the characters on which URL readers disagree: the
      allowlist reads ``https://evil.example\\@city.civicclerk.com/x`` as
      the city's host, the library that makes the fetch as ``evil.example``);
    * ``https`` (the fetch refuses anything else);
    * no user name or password, and no port but 443;
    * and :func:`is_url_safe` says yes.

    Never raises. Registered in :func:`docket.web.create_app` as the Jinja
    global ``is_minutes_viewer_url``. Plan `minutes-open-at-the-vote-page`,
    M3.
    """
    if not isinstance(url, str):
        return False
    if any(ch == "\\" or ord(ch) < 33 or ord(ch) == 127 for ch in url):
        return False
    if not url.lower().startswith("https://"):
        return False
    try:
        parts = urlsplit(url)
        if parts.username is not None or parts.password is not None:
            return False
        if parts.port not in (None, 443):
            return False
    except ValueError:  # a port that cannot be read, a malformed host
        return False
    return is_url_safe(url, allowed_domains)


def load_municipality_hosts(
    urls_fn: Callable[[], Iterable[str | None]],
) -> frozenset[str]:
    """Return the distinct hosts of the municipalities' stored ``base_url`` values.

    ``urls_fn`` takes nothing and returns those stored values; in
    production it is :func:`docket.services.query.list_active_base_urls`,
    which owns the one SQL statement (active municipalities whose
    ``adapter_config`` has a ``base_url``; deactivated cities shouldn't
    widen the allowlist). This module executes no SQL. It is kept as a
    parameter so tests can inject a plain function without
    monkey-patching. Returns a frozenset of normalized hosts. Skips a
    value that is empty or whose URL is malformed — a single bad row
    doesn't poison the whole allowlist.
    """
    hosts: set[str] = set()
    for url in urls_fn():
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
    urls_fn: Callable[[], Iterable[str | None]],
) -> frozenset[str]:
    """Combine static + dynamic allowlist.

    One call of ``urls_fn`` (see :func:`load_municipality_hosts`) and a
    union — no caching here. Used by :func:`get_allowlist` on cache miss,
    and retained as a public function so existing tests (and any future
    operator script) can build the allowlist directly without touching
    the cache.
    """
    return STATIC_ALLOWED_DOMAINS | load_municipality_hosts(urls_fn)


# ---------------------------------------------------------------------------
# Module-level state for the merged (fixed + city hosts) allowlist.
#
# ``_CACHE`` is the list being served and when it is due to be read
# again: ten minutes (``_CACHE_TTL_SECONDS``) after a read that succeeded,
# so a new city is visible without a redeploy, and 30 seconds
# (``_RETRY_SECONDS``) after a read that failed. Both are counted on
# ``time.monotonic()``, which a stepped wall clock cannot lengthen or cut
# short, and from the end of the attempt: an attempt can last as long as
# the web process's statement limit (30 seconds), and an expiry counted
# from before it would already be past.
#
# ``_LAST_LOADED`` is the last list a read that succeeded gave (``None``
# until one succeeds in this process). It is what a failed read serves,
# so a city host the database allowed a moment ago is still allowed, and
# it is exactly a list the database gave, never a wider one: the minutes
# page viewer fetches from hosts on this list.
#
# ``_LAST_ATTEMPT_FAILED`` is true from a failed attempt until the next
# one that succeeds, which logs the recovery.
#
# Thread-safety: the web process is one gunicorn worker with four
# threads. Only the thread holding ``_CACHE_LOCK`` asks the database. A
# thread that finds the list due while another is asking serves the list
# it has and does not wait; only a thread with nothing to serve (no list
# has loaded or been stored in the process) waits for the lock, and picks
# up what the other stored via the re-check inside the critical section.
# ---------------------------------------------------------------------------

_CACHE: tuple[float, frozenset[str]] | None = None  # (expiry by time.monotonic(), the list served)
_LAST_LOADED: frozenset[str] | None = None  # the last list a successful read gave
_LAST_ATTEMPT_FAILED: bool = False  # true from a failed attempt to the next that succeeds
_CACHE_TTL_SECONDS = 600  # 10 minutes, after a read that succeeded
_RETRY_SECONDS = 30  # after a read that failed
_CACHE_LOCK = Lock()


def get_allowlist(
    urls_fn: Callable[[], Iterable[str | None]] | None = None,
) -> frozenset[str]:
    """Return the allowlist, reading it from the database when it is due.

    ``urls_fn`` defaults to
    :func:`docket.services.query.list_active_base_urls`, but is
    parameterized so tests can inject a plain function without
    monkey-patching. The default lookup is deferred (lazy import) so
    importing this module never requires a DB connection.

    A list that is not yet due is returned without the lock. A read that
    succeeds is served for ``_CACHE_TTL_SECONDS`` and remembered as the
    last list that loaded. A read that raises anything (the database
    down, a connection or statement ended by the web process's limits)
    is logged with the error's type and text, and what is served in its
    place, for ``_RETRY_SECONDS``, is the last list that loaded (a
    warning) or, when none has loaded in this process,
    :data:`STATIC_ALLOWED_DOMAINS` alone (an error). The first read that
    succeeds after a failure logs ``the database answered again``; a
    read that follows no failure logs nothing.

    A caller that has a list to serve (the one that is due, or after
    :func:`invalidate_cache` the last one that loaded) never waits for
    another thread's read: it returns that list. Never raises on a
    failed read.
    """
    global _CACHE, _LAST_LOADED, _LAST_ATTEMPT_FAILED
    cached = _CACHE
    if cached is not None and cached[0] > time.monotonic():
        return cached[1]
    in_hand = cached[1] if cached is not None else _LAST_LOADED
    if in_hand is None:
        # Nothing to serve: wait for whoever is asking.
        _CACHE_LOCK.acquire()
    elif not _CACHE_LOCK.acquire(blocking=False):
        # Another thread is asking the database; its answer is not
        # needed to serve this caller.
        return in_hand
    try:
        # Re-check inside the lock, on a clock read again — another
        # thread may have just stored a list, and a caller that waited
        # may have waited as long as a connection attempt lasts.
        cached = _CACHE
        if cached is not None and cached[0] > time.monotonic():
            return cached[1]
        if urls_fn is None:
            from docket.services.query import list_active_base_urls as urls_fn  # noqa: F811
        try:
            allowlist = build_allowlist(urls_fn)
        except Exception as exc:
            error = f"{type(exc).__name__}: {' '.join(str(exc).split())}"
            if _LAST_LOADED is not None:
                served = _LAST_LOADED
                logger.warning(
                    "source allowlist: query failed (%s); serving the last "
                    "list that loaded (%d hosts); next try in %d s",
                    error, len(served), _RETRY_SECONDS,
                )
            else:
                served = STATIC_ALLOWED_DOMAINS
                logger.error(
                    "source allowlist: query failed (%s); no list has loaded "
                    "in this process, so only the fixed domains are allowed; "
                    "next try in %d s",
                    error, _RETRY_SECONDS,
                )
            _LAST_ATTEMPT_FAILED = True
            _CACHE = (time.monotonic() + _RETRY_SECONDS, served)
            return served
        _LAST_LOADED = allowlist
        _CACHE = (time.monotonic() + _CACHE_TTL_SECONDS, allowlist)
        if _LAST_ATTEMPT_FAILED:
            _LAST_ATTEMPT_FAILED = False
            logger.warning(
                "source allowlist: the database answered again (%d hosts)",
                len(allowlist),
            )
        return allowlist
    finally:
        _CACHE_LOCK.release()


def invalidate_cache() -> None:
    """Make the next call of :func:`get_allowlist` ask the database.

    Used by the admin refresh endpoint (instant onboarding for a newly-
    added municipality). It clears the list being served and keeps the
    last list that loaded and the record of a failed attempt: if the
    re-read then fails, that last list is served and the failure logged,
    so pressing refresh while the database is failing neither withholds
    a city's links nor hides the recovery line.
    """
    global _CACHE
    _CACHE = None


def forget_allowlist() -> None:
    """Forget everything the module holds: the list being served, the
    last list that loaded, and whether the last attempt failed.

    For tests only, which need a clean state between cases. Nothing in
    the application calls it; the operator's refresh is
    :func:`invalidate_cache`.
    """
    global _CACHE, _LAST_LOADED, _LAST_ATTEMPT_FAILED
    _CACHE = None
    _LAST_LOADED = None
    _LAST_ATTEMPT_FAILED = False
