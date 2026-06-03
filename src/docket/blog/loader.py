"""Blog content loader: parse markdown files into Post dataclasses."""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from datetime import date
from pathlib import Path

import frontmatter

from docket.blog.types import Post

logger = logging.getLogger(__name__)

SLUG_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})-(?P<slug>[a-z0-9][a-z0-9-]*)$")

RESERVED_SHARED_SLUGS = {"tag", "assets", "feed", "feed.xml", "internal"}


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
        _author_keys=list(meta.get("authors") or []),
    )


def _apply_status_precedence(post: Post) -> Post:
    """Spec §3 'Status precedence (strict)': future date overrides any status."""
    from datetime import date as _date

    today = _date.today()
    if post.date > today and post.status != "draft":
        return replace(post, status="scheduled")
    return post


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
        post = _apply_status_precedence(post)
        if post.city == "_shared" and post.slug in RESERVED_SHARED_SLUGS:
            raise LoaderError(
                f"{post.source_path}: reserved slug {post.slug!r} for _shared posts "
                f"(would collide with /blog/{post.slug} route)"
            )
        key = (post.city, post.slug)
        if key in seen:
            raise LoaderError(
                f"{post.source_path}: duplicate slug {post.slug!r} for city {post.city!r}"
            )
        seen.add(key)
        posts.append(post)

    return posts


def load_blog_state(
    *,
    content_root: Path,
    authors_yaml: Path,
    known_city_slugs: set[str],
) -> "BlogState":
    """Top-level loader: walks content/blog/, parses, resolves authors + shortcodes,
    renders to HTML, builds reverse indexes. Called once at process start."""
    from docket.blog.authors import AuthorsRegistry, load_authors_registry
    from docket.blog.render import (
        compute_reading_time,
        count_words,
        render_post_html,
        rewrite_cover_image,
    )
    from docket.blog.shortcodes import (
        collect_shortcode_refs,
        resolve_shortcode_titles,
    )
    from docket.blog.types import BlogState

    authors_reg: AuthorsRegistry = load_authors_registry(authors_yaml)
    raw_posts = load_posts_from_disk(
        content_root=content_root, known_city_slugs=known_city_slugs
    )

    # Collect all shortcode refs across all posts and resolve in batches.
    all_item_ids: set[int] = set()
    all_meeting_ids: set[int] = set()
    for p in raw_posts:
        items, meetings = collect_shortcode_refs(p.body_markdown)
        all_item_ids |= items
        all_meeting_ids |= meetings

    item_titles, meeting_titles = resolve_shortcode_titles(
        item_ids=all_item_ids, meeting_ids=all_meeting_ids
    )

    # Warn once per missing ID.
    for nid in sorted(all_item_ids - set(item_titles)):
        logger.warning("blog: shortcode [[item:%s]] references unknown agenda_item", nid)
    for nid in sorted(all_meeting_ids - set(meeting_titles)):
        logger.warning("blog: shortcode [[meeting:%s]] references unknown meeting", nid)

    rendered: list[Post] = []
    for p in raw_posts:
        authors = authors_reg.resolve_keys(p._author_keys)

        items_in_post, meetings_in_post = collect_shortcode_refs(p.body_markdown)
        post_item_titles = {i: item_titles[i] for i in items_in_post if i in item_titles}
        post_meeting_titles = {
            i: meeting_titles[i] for i in meetings_in_post if i in meeting_titles
        }

        body_html = render_post_html(
            p.body_markdown,
            city=p.city,
            slug=p.slug,
            item_titles=post_item_titles,
            meeting_titles=post_meeting_titles,
        )
        cover_url = rewrite_cover_image(p.cover_image_url, city=p.city, slug=p.slug)
        wc = count_words(body_html)
        rt = compute_reading_time(wc)

        rendered.append(
            replace(
                p,
                body_html=body_html,
                authors=authors,
                cover_image_url=cover_url,
                word_count=wc,
                reading_time_minutes=rt,
            )
        )

    rendered.sort(key=lambda p: (p.date, p.slug), reverse=True)
    posts_by_id = {(p.city, p.slug): p for p in rendered}

    posts_by_item_id: dict[int, list[Post]] = {}
    posts_by_meeting_id: dict[int, list[Post]] = {}
    for p in rendered:
        for iid in p.related_item_ids:
            posts_by_item_id.setdefault(iid, []).append(p)
        for mid in p.related_meeting_ids:
            posts_by_meeting_id.setdefault(mid, []).append(p)

    return BlogState(
        posts=rendered,
        posts_by_id=posts_by_id,
        posts_by_item_id=posts_by_item_id,
        posts_by_meeting_id=posts_by_meeting_id,
        authors=authors_reg.by_key,
    )
