"""Render markdown blog posts to HTML."""

from __future__ import annotations

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
