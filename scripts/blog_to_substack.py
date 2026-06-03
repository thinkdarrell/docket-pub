"""Cross-post helper: take a markdown post and produce a Substack-ready version.

Stripping frontmatter, rewriting relative asset paths to absolute https://docket.pub
URLs, and resolving [[item:N]] / [[meeting:N]] shortcodes to inline markdown links.

Usage:
    python -m scripts.blog_to_substack content/blog/<city>/<file>.md

Output goes to stdout, _exports/<city>-<slug>-substack.md (gitignored), AND the
macOS clipboard via pbcopy when available.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import frontmatter

ITEM_RE = re.compile(r"\[\[item:(\d+)\]\]")
MEETING_RE = re.compile(r"\[\[meeting:(\d+)\]\]")
RELATIVE_IMG_RE = re.compile(r"!\[([^\]]*)\]\(((?!https?://|/|data:)[^)]+)\)")


def build_substack_markdown(
    path: Path,
    *,
    city: str,
    slug: str,
    item_titles: dict[int, str],
    meeting_titles: dict[int, str],
) -> str:
    post = frontmatter.load(path)
    md = post.content
    md = RELATIVE_IMG_RE.sub(
        lambda m: f"![{m.group(1)}](https://docket.pub/blog/assets/{city}/{slug}/{m.group(2)})",
        md,
    )

    def _item(m):
        nid = int(m.group(1))
        title = item_titles.get(nid, f"item {nid}")
        # TODO: city slug is not available in this CLI; replace <unknown> with the real
        # city slug before publishing (e.g. https://docket.pub/al/birmingham/items/42/).
        return f"[{title}](https://docket.pub/al/<unknown>/items/{nid}/)"

    def _meeting(m):
        nid = int(m.group(1))
        title = meeting_titles.get(nid, f"meeting {nid}")
        # TODO: city slug is not available in this CLI; replace <unknown> with the real
        # city slug before publishing (e.g. https://docket.pub/al/birmingham/meetings/2232/).
        return f"[{title}](https://docket.pub/al/<unknown>/meetings/{nid}/)"

    md = ITEM_RE.sub(_item, md)
    md = MEETING_RE.sub(_meeting, md)
    return md


def _copy_to_clipboard(text: str) -> bool:
    try:
        proc = subprocess.run(
            ["pbcopy"], input=text, text=True, check=False, capture_output=True
        )
        return proc.returncode == 0
    except FileNotFoundError:
        return False


def _dump_to_exports(text: str, *, city: str, slug: str) -> Path:
    """Write the converted markdown to _exports/<city>-<slug>-substack.md.

    _exports/ is gitignored. The on-disk copy survives clipboard overwrites
    and gives the author a durable artifact to re-paste from if the Substack
    editor session is interrupted.
    """
    exports_dir = Path.cwd() / "_exports"
    exports_dir.mkdir(exist_ok=True)
    out_path = exports_dir / f"{city}-{slug}-substack.md"
    out_path.write_text(text)
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)

    rel = args.path.relative_to(Path.cwd() / "content" / "blog")
    city = rel.parts[0]
    slug = args.path.stem
    # Strip date prefix from slug
    m = re.match(r"^\d{4}-\d{2}-\d{2}-(.+)$", slug)
    if m:
        slug = m.group(1)

    # We don't run the live DB query in this script. The author should
    # have the canonical titles handy already; for one-shot use the
    # shortcodes will become "item N" / "meeting N" if not provided via
    # an optional --titles JSON file.
    out = build_substack_markdown(
        args.path, city=city, slug=slug, item_titles={}, meeting_titles={}
    )
    print(out)
    export_path = _dump_to_exports(out, city=city, slug=slug)
    print(f"\n(wrote {export_path})", file=sys.stderr)
    if _copy_to_clipboard(out):
        print("(copied to clipboard via pbcopy)", file=sys.stderr)
    print(
        "\nReminder: after publishing on Substack, set "
        "`cross_posted_to.substack` in the post's frontmatter.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
