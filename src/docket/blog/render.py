"""Render markdown blog posts to HTML."""

from __future__ import annotations

import re
from urllib.parse import urlparse

import markdown

from docket.blog.shortcodes import ITEM_RE, MEETING_RE, ResolvedItem


def _mermaid_fence_format(source, language, css_class, options, md, **kwargs):
    return f'<div class="{css_class}">{source}</div>'


EXTENSIONS = [
    "tables",
    "attr_list",
    "def_list",
    "admonition",
    "toc",
    "pymdownx.superfences",
    "pymdownx.smartsymbols",
]

SUPERFENCES_CONFIG = {
    "pymdownx.superfences": {
        "custom_fences": [
            {
                "name": "mermaid",
                "class": "mermaid",
                "format": _mermaid_fence_format,
            },
        ],
    },
}


def render_markdown(md: str) -> str:
    """Run the markdown pipeline on a raw string. Pure: no I/O, no DB."""
    converter = markdown.Markdown(
        extensions=EXTENSIONS,
        extension_configs=SUPERFENCES_CONFIG,
        output_format="html5",
    )
    return converter.convert(md)


# ---------------------------------------------------------------------------
# Iframe allowlist sanitizer
# ---------------------------------------------------------------------------

IFRAME_RE = re.compile(r"<iframe\b[^>]*>.*?</iframe>", re.IGNORECASE | re.DOTALL)
SRC_RE = re.compile(r'\bsrc="([^"]+)"', re.IGNORECASE)
WIDTH_RE = re.compile(r'\bwidth="([^"]+)"', re.IGNORECASE)
HEIGHT_RE = re.compile(r'\bheight="([^"]+)"', re.IGNORECASE)

IFRAME_HOST_ALLOWLIST = {
    "datawrapper.dwcdn.net",
    "datawrapper.de",
    "flo.uri.sh",
    "flourish.studio",
    "observablehq.com",
    "www.youtube.com",
    "youtube-nocookie.com",
    "player.vimeo.com",
}


def _host_allowed(host: str) -> bool:
    host = host.lower()
    if host in IFRAME_HOST_ALLOWLIST:
        return True
    # Subdomain match (e.g. "public.flourish.studio").
    for allowed in IFRAME_HOST_ALLOWLIST:
        if host.endswith("." + allowed):
            return True
    return False


def sanitize_iframes(html: str) -> str:
    """Replace iframes: allowlisted hosts get `sandbox` + `loading=lazy` injected;
    others are removed entirely."""

    def _replace(match: re.Match) -> str:
        tag = match.group(0)
        src_match = SRC_RE.search(tag)
        if not src_match:
            return ""
        try:
            host = urlparse(src_match.group(1)).hostname or ""
        except ValueError:
            return ""
        if not _host_allowed(host):
            return ""
        src = src_match.group(1)
        width = WIDTH_RE.search(tag)
        height = HEIGHT_RE.search(tag)
        attrs = [f'src="{src}"']
        if width:
            attrs.append(f'width="{width.group(1)}"')
        if height:
            attrs.append(f'height="{height.group(1)}"')
        attrs.append('loading="lazy"')
        attrs.append('sandbox="allow-scripts allow-same-origin allow-popups"')
        attrs.append('frameborder="0"')
        return f"<iframe {' '.join(attrs)}></iframe>"

    return IFRAME_RE.sub(_replace, html)


# ---------------------------------------------------------------------------
# Asset URL rewriter
# ---------------------------------------------------------------------------

IMG_SRC_RE = re.compile(r'(<img\b[^>]*\bsrc=")([^"]+)(")', re.IGNORECASE)
A_HREF_RE = re.compile(r'(<a\b[^>]*\bhref=")([^"]+)(")', re.IGNORECASE)

SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.\-]*:", re.IGNORECASE)


def _is_external(url: str) -> bool:
    return bool(SCHEME_RE.match(url)) or url.startswith("/") or url.startswith("#")


def rewrite_asset_urls(html: str, *, city: str, slug: str) -> str:
    """Rewrite relative img/href URLs to `/blog/assets/<city>/<slug>/<path>`.
    Absolute (scheme://...), root-relative (/...), and fragment (#...) URLs pass through.
    """
    base = f"/blog/assets/{city}/{slug}/"

    def _rewrite(match: re.Match) -> str:
        prefix, url, suffix = match.group(1), match.group(2), match.group(3)
        if _is_external(url):
            return f"{prefix}{url}{suffix}"
        return f"{prefix}{base}{url}{suffix}"

    html = IMG_SRC_RE.sub(_rewrite, html)
    html = A_HREF_RE.sub(_rewrite, html)
    return html


def rewrite_cover_image(value: str | None, *, city: str, slug: str) -> str | None:
    """Same rule as `rewrite_asset_urls`, for the frontmatter `cover_image` scalar."""
    if not value:
        return None
    if _is_external(value):
        return value
    return f"/blog/assets/{city}/{slug}/{value}"


# ---------------------------------------------------------------------------
# Reading time
# ---------------------------------------------------------------------------

TAG_RE = re.compile(r"<[^>]+>")
WORDS_PER_MINUTE = 200


def count_words(html: str) -> int:
    text = TAG_RE.sub(" ", html)
    return len([w for w in text.split() if w])


def compute_reading_time(word_count: int) -> int:
    return max(1, round(word_count / WORDS_PER_MINUTE))


# ---------------------------------------------------------------------------
# Full render pipeline
# ---------------------------------------------------------------------------


def _expand_shortcodes_in_markdown(
    md: str,
    *,
    item_titles: dict[int, ResolvedItem],
    meeting_titles: dict[int, ResolvedItem],
) -> str:
    """Expand `[[item:N]]` / `[[meeting:N]]` into markdown anchors before rendering.

    Resolution failures render as `[item:N]` plain text + WARNING already logged
    at load time by the caller. We don't re-log per render.
    """

    def _item(m: re.Match) -> str:
        nid = int(m.group(1))
        resolved = item_titles.get(nid)
        if resolved is None:
            return f"[item:{nid}]"
        url = f"/al/{resolved.city_slug}/items/{nid}/"
        return f'<a href="{url}" class="docket-link" data-kind="item">{resolved.title}</a>'

    def _meeting(m: re.Match) -> str:
        nid = int(m.group(1))
        resolved = meeting_titles.get(nid)
        if resolved is None:
            return f"[meeting:{nid}]"
        url = f"/al/{resolved.city_slug}/meetings/{nid}/"
        return (
            f'<a href="{url}" class="docket-link" data-kind="meeting">{resolved.title}</a>'
        )

    md = ITEM_RE.sub(_item, md)
    md = MEETING_RE.sub(_meeting, md)
    return md


def render_post_html(
    body_markdown: str,
    *,
    city: str,
    slug: str,
    item_titles: dict[int, ResolvedItem],
    meeting_titles: dict[int, ResolvedItem],
) -> str:
    """Full pipeline: shortcodes → markdown → iframe sanitize → asset URL rewrite."""
    expanded = _expand_shortcodes_in_markdown(
        body_markdown, item_titles=item_titles, meeting_titles=meeting_titles
    )
    html = render_markdown(expanded)
    html = sanitize_iframes(html)
    html = rewrite_asset_urls(html, city=city, slug=slug)
    return html
