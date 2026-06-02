"""Blog content loader: parse markdown files into Post dataclasses."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import frontmatter

from docket.blog.types import Post

SLUG_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})-(?P<slug>[a-z0-9][a-z0-9-]*)$")


class LoaderError(Exception):
    """Raised when a blog post file is malformed or violates a loader rule."""


def parse_post_file(path: Path, *, content_root: Path) -> Post:
    """Parse a single markdown file into a Post.

    Validates required frontmatter fields. Does NOT resolve authors, shortcodes,
    asset URLs, or render markdown — those are downstream stages.
    """
    post = frontmatter.load(path)
    meta = post.metadata
    body_markdown = post.content

    rel = path.relative_to(content_root)
    source_path = rel.as_posix()

    title = meta.get("title")
    if not title:
        raise LoaderError(f"{source_path}: missing required frontmatter `title`")

    summary = meta.get("summary")
    if not summary:
        raise LoaderError(f"{source_path}: missing required frontmatter `summary`")

    raw_date = meta.get("date")
    if not raw_date:
        raise LoaderError(f"{source_path}: missing required frontmatter `date`")
    if not isinstance(raw_date, date):
        raise LoaderError(
            f"{source_path}: `date` must be a YAML date (YYYY-MM-DD), got {raw_date!r}"
        )

    # City is derived from the parent dir, but frontmatter `city` overrides
    # (e.g. _shared posts can declare a tag-target city).
    parent_dir = rel.parts[0] if rel.parts else ""
    city = meta.get("city") or parent_dir
    if not city:
        raise LoaderError(f"{source_path}: cannot determine `city`")

    # Slug: frontmatter override > filename stem (post YYYY-MM-DD- prefix stripped)
    slug = meta.get("slug")
    if not slug:
        stem = path.stem
        match = SLUG_RE.match(stem)
        slug = match.group("slug") if match else stem

    status = meta.get("status") or "published"
    if status not in ("published", "draft", "scheduled"):
        raise LoaderError(
            f"{source_path}: invalid `status` {status!r} "
            "(must be published, draft, or scheduled)"
        )

    return Post(
        title=str(title),
        slug=slug,
        date=raw_date,
        city=city,
        summary=str(summary),
        body_markdown=body_markdown,
        body_html="",  # filled by render stage
        authors=[],  # filled by authors stage
        tags=list(meta.get("tags") or []),
        cover_image_url=meta.get("cover_image"),  # rewritten by asset stage
        cross_posted_to=dict(meta.get("cross_posted_to") or {}),
        related_item_ids=list(meta.get("related_items") or []),
        related_meeting_ids=list(meta.get("related_meetings") or []),
        status=status,
        extra_css=list(meta.get("extra_css") or []),
        updated=meta.get("updated") if isinstance(meta.get("updated"), date) else None,
        reading_time_minutes=0,  # computed by render stage
        word_count=0,  # computed by render stage
        source_path=source_path,
    )


def load_posts_from_disk(
    *,
    content_root: Path,
    known_city_slugs: set[str],
) -> list[Post]:
    """Walk `content_root` for .md files, parse each, validate, return Posts.

    Skips:
      - any file under a path component starting with "_drafts"
      - hidden files (leading dot)
      - non-.md files

    Raises LoaderError on:
      - unknown city directory (not in known_city_slugs and not "_shared")
      - duplicate (city, slug) pair
      - any per-file LoaderError surfaced by parse_post_file
    """
    if not content_root.exists():
        return []

    posts: list[Post] = []
    seen: set[tuple[str, str]] = set()  # (city, slug)
    allowed_cities = known_city_slugs | {"_shared"}

    for md_path in sorted(content_root.rglob("*.md")):
        rel_parts = md_path.relative_to(content_root).parts
        if any(part.startswith("_drafts") for part in rel_parts[:-1]):
            continue
        if md_path.name.startswith("."):
            continue

        top = rel_parts[0]
        if top not in allowed_cities:
            raise LoaderError(
                f"{md_path.relative_to(content_root).as_posix()}: "
                f"unknown city directory {top!r} "
                f"(allowed: {sorted(allowed_cities)})"
            )

        post = parse_post_file(md_path, content_root=content_root)
        key = (post.city, post.slug)
        if key in seen:
            raise LoaderError(
                f"{post.source_path}: duplicate slug {post.slug!r} for city {post.city!r}"
            )
        seen.add(key)
        posts.append(post)

    return posts
