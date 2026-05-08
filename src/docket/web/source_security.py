"""URL safety check for source-anchor deep links.

Combines a static allowlist of known platform domains with a dynamic
allowlist of municipality hosts loaded from ``municipalities.adapter_config``
at app init. Blocks any URL whose host doesn't match either.

The static allowlist covers every supported CMS plus the public video
hosts citizens are realistically deep-linked into (Granicus player URLs
on a tenant subdomain, raw YouTube/Vimeo embeds). The dynamic allowlist
is read once at :func:`docket.web.create_app` time from the
``adapter_config->>'base_url'`` JSONB key — that's where Birmingham's
``bhamal.granicus.com``, Vestavia's CivicClerk tenant, etc. live in our
schema (see migration 001 ``municipalities`` table). Together they form
a closed list: anything else (``evil.tld``, protocol-relative ``//``,
``javascript:``, ``data:``, ``file:``) gets rejected before the partial
emits an ``<a href>``.

Why not rely on the scheme guard alone?  ``http://`` and ``https://``
filter out the obvious XSS vectors but they don't stop us from rendering
a link to ``https://attacker.tld/cookie-grabber.html`` if a malformed
``source_anchor`` row ever gets stored. The closed allowlist makes it a
defense-in-depth check rather than a single-line gate.

Usage from Jinja::

    {% if is_source_url_safe(anchor.url) %}

The Jinja global ``is_source_url_safe`` is registered in
:func:`docket.web.create_app` and partially applies the resolved
allowlist so callers only pass a URL.
"""

from __future__ import annotations

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


def is_url_safe(url: object, allowed_domains: frozenset[str]) -> bool:
    """Return True iff ``url`` is http/https AND its host matches ``allowed_domains``.

    Suffix match uses a leading-dot anchor (``host.endswith('.' + domain)``)
    to prevent the classic ``granicus.com.evil.tld`` bypass — that string
    ends with ``granicus.com`` but is NOT a granicus.com subdomain. Exact
    match is also accepted (so ``granicus.com`` itself passes).

    Defensive against non-string input (None, int, list) and malformed
    URLs that raise inside ``urlparse``. Returns False rather than
    crashing the render.
    """
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
    """Combine static + dynamic allowlist. Called once at app init."""
    return STATIC_ALLOWED_DOMAINS | load_municipality_hosts(db_cursor_fn)
