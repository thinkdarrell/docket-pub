"""Render markdown blog posts to HTML."""

from __future__ import annotations

import re
from urllib.parse import urlparse

import markdown


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
