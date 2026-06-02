# Blog — Design Spec

**Date:** 2026-06-02
**Status:** Draft, pending review
**Goal:** Add a per-municipality blog to docket.pub at `/<city>/blog` (and a site-wide hub at `/blog`) using markdown files in the repo. No new infrastructure, no database tables, no external CMS dependency. Charts/infographics handled via embeds rather than custom-built components.

---

## 1. Goals & non-goals

**Goals**

- Author posts as markdown files in the repo; push to deploy.
- Per-municipality URL structure (`/birmingham/blog`, `/homewood/blog`, …) plus a cross-city hub.
- Posts can be a mix of editorial coverage, site announcements, civic explainers — whatever's relevant to a city's coverage.
- Posts can deep-link to specific meetings / agenda items / votes, and (reciprocally) those pages surface relevant posts.
- Embed charts, graphs, and infographics from third-party tools (Datawrapper, Flourish, Observable) and inline images without building viz components from scratch.
- Optional cross-posting to Substack via a copy/paste helper; not required day one.
- Inherit the existing visual system (Phase-5 refactor) so the blog feels native to docket.pub.

**Non-goals (v1)**

- In-browser editing / admin UI.
- Comments. Newsletter signup. Social share buttons beyond OG/Twitter cards.
- Full-text search of blog posts (the existing site search can index posts in a later pass).
- Automated bidirectional Substack publishing (one-way paste only).
- Image processing / responsive image generation.
- Multi-author drafts/review workflow.

---

## 2. Architecture overview

Self-contained subsystem inside the existing Flask app:

- **Content directory**: `content/blog/` at the repo root.
- **Loader** (`src/docket/blog/loader.py`): walks `content/blog/`, parses frontmatter + body, returns a list of `Post` dataclasses. In-memory cache, refreshed on mtime change in dev (`FLASK_ENV=development`), frozen at process start in prod.
- **Renderer** (`src/docket/blog/render.py`): markdown → HTML via `python-markdown` with a curated extension set. Iframe embeds from an allowlist pass through; other raw HTML is sanitized.
- **Blueprint** (`src/docket/web/blog.py`): Flask blueprint owning blog routes.
- **Templates** (`src/docket/web/templates/blog/`): `hub.html`, `city.html`, `post.html`, plus partials.
- **Cross-post helper** (`scripts/blog_to_substack.py`): one-shot script that emits a Substack-ready version of a post to stdout / clipboard.
- **Tests** (`tests/blog/`): loader, renderer, route, and integration tests.

**New runtime deps**: `markdown`, `python-frontmatter`, `pymdown-extensions`. All small, well-maintained, no transitive bloat.

**Not added**: new database tables, new env vars (except `BLOG_PREVIEW_TOKEN`, optional), new worker tasks, new Railway services.

---

## 3. Content structure

### Filesystem layout

```
content/blog/
  birmingham/
    2026-06-02-budget-explainer.md
    2026-06-02-budget-explainer/         # optional, only if post has local assets
      cover.jpg
      revenue-chart.png
      custom.css                         # optional, see §5 "look customization"
  homewood/
    2026-05-30-zoning-101.md
  _shared/                               # cross-city / site-wide posts
    2026-05-15-methodology-update.md
  _drafts/                               # not published; ignored by loader
    work-in-progress.md
```

City sub-directories must match a known city slug (validated against the city list used by the existing public routes). `_shared/` is reserved for posts that aren't tied to one city (methodology, site updates, statewide analysis).

### Frontmatter schema

```yaml
---
title: "Where Birmingham's 2027 Budget Actually Goes"
slug: budget-explainer              # optional; defaults to filename stem
date: 2026-06-02                    # publish date; future = scheduled
updated: 2026-06-04                 # optional
city: birmingham                    # required; or "_shared"
authors: [darrell]                  # list; resolved via config/blog_authors.yaml
summary: "One-sentence dek shown on cards and in RSS."
tags: [budget, council, explainer]  # free-form
cover_image: cover.jpg              # relative to the post's asset folder
cross_posted_to:                    # optional; renders as banner link
  substack: https://docketpub.substack.com/p/birmingham-budget
related_items: [3421, 3422]         # optional; powers reciprocal rails
related_meetings: [2232]
status: published                   # published | draft | scheduled
extra_css: [custom.css]             # optional; loaded from asset folder
---
```

**Loader rules** (errors surface at app startup, not at request time):

| Condition | Behavior |
|---|---|
| `title`, `date`, or `summary` missing | Hard error; app refuses to boot |
| `city` not in known city list (and not `_shared`) | Hard error |
| `date` in the future | Marked `scheduled`; hidden from listings until date passes |
| `status: draft` or file under `_drafts/` | Hidden everywhere in prod; visible at `/<city>/blog/<slug>?preview=<token>` if `BLOG_PREVIEW_TOKEN` matches |
| Unknown frontmatter keys | Logged warning, not fatal (forward-compat) |
| Duplicate slug within same city | Hard error |
| `related_items` / `related_meetings` reference non-existent IDs | Logged warning; rail omits the dead link |

**Status precedence (strict):**

`date` is authoritative for visibility. If `date` is in the future, the post is `scheduled` and hidden from all listings until that date passes — **regardless of whether `status: published` is set in frontmatter**. This is intentional: it prevents accidental early publishing from a typo or a forgotten `status` override. The `status` field only matters when `date` is in the past or today:

- `date` in past + `status: published` (or unset) → live.
- `date` in past + `status: draft` → hidden; preview-token-gated.
- `date` in future + any `status` → `scheduled`; hidden.
- `_drafts/` path → always hidden; preview-token-gated; `date` and `status` ignored for visibility.

### Author config

`config/blog_authors.yaml` (new):

```yaml
darrell:
  display_name: "Darrell Nance"
  bio: "Founder of docket.pub. Civic data nerd."
  avatar: darrell.jpg                # in src/docket/web/static/blog/authors/
  links:
    bluesky: https://bsky.app/profile/...
```

Posts reference authors by key. Unknown keys → hard error.

---

## 4. Routes

All routes live in a new `blog` blueprint, mounted at `/`.

| Route | Purpose | Template |
|---|---|---|
| `/blog` | Cross-city hub; most recent published posts across all cities + `_shared` | `blog/hub.html` |
| `/blog/feed.xml` | Atom feed for the hub | (XML template) |
| `/blog/tag/<tag>` | Posts with that tag, across cities | `blog/hub.html` (filtered) |
| `/<city>/blog` | Posts for that city + any `_shared` posts tagged for it | `blog/city.html` |
| `/<city>/blog/feed.xml` | Atom feed for that city | (XML template) |
| `/<city>/blog/<slug>` | Post detail | `blog/post.html` |

**Existing-route coordination**: docket.pub already has city routes (e.g. `/<city>` for council/items). The blog blueprint registers `/<city>/blog/...` with a route order that ensures it doesn't shadow existing handlers. If any city slug ever collides with a static blog prefix, the loader's startup validation catches it.

**Listing pagination**: 20 posts per page; `?page=N` query param. v1 ships without pagination if total post count is < 20; we add it when needed.

**Preview tokens (drafts)**: `?preview=<token>` checked against `BLOG_PREVIEW_TOKEN` env var. Only works for `status: draft`. Always denied in prod if env var is unset. Preview pages set `X-Robots-Tag: noindex`.

---

## 5. Rendering

### When rendering happens

**Markdown → HTML runs once, at loader time** (process start in prod, mtime-triggered in dev). The rendered HTML string is cached on the `Post` dataclass. Request handlers serve the cached HTML — no markdown parsing, no shortcode expansion, no DB hits at request time.

This makes the shortcode mechanism (§"Inline shortcodes" below) safe to use freely in long posts: a budget explainer with 50 `[[item:N]]` references resolves all titles in a single batched query during the loader's startup phase, not 50 queries per page view.

Loader sequence:

1. Walk `content/blog/`, parse frontmatter + body for each post.
2. Collect every `[[item:N]]` and `[[meeting:N]]` referenced across all posts plus every `related_items` / `related_meetings` ID. Resolve canonical titles in two batched queries (`SELECT id, title FROM agenda_items WHERE id = ANY(%s)` etc.). Build an in-memory `{id → title}` map.
3. Render each post's markdown to HTML using that map.
4. Rewrite relative asset URLs (see §"Asset URL rewriting" below).
5. Store the rendered HTML, reading time, and resolved metadata on the `Post` object.

If an ID is missing from the resolution map (deleted item, typo), the shortcode renders as plain text plus a warning logged once at load.

### Markdown pipeline

`python-markdown` with this extension set:

- `fenced_code` — triple-backtick code blocks
- `tables` — GFM-style tables
- `attr_list` — `{.class #id}` syntax on any block/inline for per-post styling
- `def_list` — definition lists
- `admonition` — `!!! note`, `!!! warning`, `!!! quote`, `!!! key-takeaway` (custom)
- `toc` — auto-generated table of contents; rendered if `toc: true` frontmatter set
- `pymdownx.superfences` with custom fences for `mermaid` and `dataviz` (see below)
- `pymdownx.smartsymbols` — typographic niceties
- Custom inline shortcode: `[[item:3421]]` / `[[meeting:2232]]` expands to a link with the canonical title pulled from the DB at render time

### Asset URL rewriting

Authors write portable, relative paths in markdown:

```markdown
![Revenue breakdown](revenue-chart.png)
```

And in frontmatter:

```yaml
cover_image: cover.jpg
```

The loader rewrites these (at load time) to absolute paths under the blog asset route:

```
/blog/assets/<city>/<slug>/<filename>
```

Served by a custom blueprint route — `@bp.route('/blog/assets/<city>/<slug>/<path:filename>')` calling `send_from_directory(CONTENT_ROOT / "blog" / city / slug, filename)`. This bypasses Flask's default static handler (which is bound to `src/docket/web/static/`) so post assets stay co-located with their markdown in `content/blog/...` — no build step, no copying, no symlinks.

For Open Graph `og:image` (which requires an absolute URL), the rewriter prepends `https://docket.pub` to the asset path.

Rewriting only applies to URLs that don't have a scheme (`http://`, `https://`, `data:`) and don't start with `/`. Absolute external URLs pass through untouched.

### Iframe embed allowlist

Raw `<iframe>` tags in markdown are sanitized except for these `src` host allowlist:

- `datawrapper.dwcdn.net` / `*.datawrapper.de`
- `flo.uri.sh` / `*.flourish.studio`
- `observablehq.com`
- `www.youtube.com` / `youtube-nocookie.com`
- `player.vimeo.com`

All iframes get `loading="lazy"`, `sandbox="allow-scripts allow-same-origin allow-popups"`, and width/height preserved from the source snippet.

### Code-block-driven diagrams

- ` ```mermaid ` → rendered client-side via the Mermaid JS lib (loaded only on post pages, async).
- ` ```dataviz ` → reserved for v1.1; would render a small Vega-Lite spec server-side to inline SVG. Not implemented in v1.

### "Look customization"

Three escape hatches for per-post visual tweaks without building a theme system:

1. **`attr_list` classes** — add `{.callout-large}` or `{.tier-green}` to any element. The blog stylesheet ships a small set of named classes (`.callout`, `.callout-large`, `.figure-wide`, `.pull-quote`, `.stat-block`).
2. **Admonition styles** — `!!! note`, `!!! warning`, `!!! quote`, `!!! key-takeaway`. Each has a default look; can be themed per-city later.
3. **Per-post CSS** — frontmatter `extra_css: [custom.css]` injects `<link rel="stylesheet" href="/static/blog/<city>/<slug>/custom.css">` on that post's page only. Authors are expected to scope selectors under `article[data-post="<slug>"]` (the wrapper element gets that attribute set) to avoid leakage. Lint warning logged if a stylesheet declares an unscoped global selector.

Raw HTML in markdown is allowed for inline overrides but sanitized to a safe-but-extensible tag list (`div`, `span`, `figure`, `figcaption`, `details`, `summary`, common semantic elements, plus the iframe allowlist above).

### Inline shortcodes

`[[item:N]]` and `[[meeting:N]]` are custom inline shortcodes resolved against the in-memory ID→title map built at loader startup. They expand to:

```html
<a href="/item/3421" class="docket-link" data-kind="item">Resolution to fund summer youth program</a>
```

Anchor text comes from the canonical title in the DB. If `N` is missing from the resolution map, the shortcode renders as `[item:N]` plain text plus a warning logged once at load.

Resolution is batched at startup, not at render time — see §"When rendering happens" above.

### Reading time + word count

Computed once at load time from the rendered text. Displayed in the post header ("6 min read").

---

## 6. Integration with the existing site

### Reciprocal links into docket.pub data

`related_items` and `related_meetings` are the bridge between editorial content and primary records:

- On a post page, render a "Mentioned in docket" rail listing the linked items / meetings (with their existing meeting card / item card partials).
- On an `item_detail.html` or `meeting_detail.html` page, look up posts whose `related_items` / `related_meetings` reference that ID. If any, render an "Editorial coverage" rail near the top, linking to those posts.

Lookup is in-memory (Posts are pre-indexed by referenced ID at load time); zero DB cost per page.

### City landing page hookup

`city.html` (the existing per-city landing page) gets a "From the blog" rail showing the 3 most recent posts for that city. If there are none, the rail is hidden — no empty state.

### Sitemap & SEO

- `sitemap.xml` (existing if present, new otherwise) includes all published blog post URLs with `lastmod` set to `updated` or `date`.
- Each post page renders Open Graph + Twitter card meta tags: `og:title`, `og:description` (from `summary`), `og:image` (cover image, absolute URL), `og:type=article`, `article:published_time`, `article:author`.
- Canonical link tag points to docket.pub. If `cross_posted_to.substack` is set, the post page renders an unobtrusive "Also on Substack →" banner.

---

## 7. Authoring workflow

### Writing a post

1. `mkdir -p content/blog/<city>/`
2. Create `YYYY-MM-DD-<slug>.md` with frontmatter + markdown body.
3. Optional: create matching asset folder, drop images / `custom.css` into it.
4. Embed charts by pasting the iframe snippet from Datawrapper/Flourish/Observable directly into the markdown.
5. Run `make blog-preview SLUG=<slug>` (or `python -m docket.blog.preview --slug <slug>`) to open the post in a local Flask instance with auto-reload.
6. Commit + push. Railway redeploys; post is live.

### Cross-posting to Substack

Manual, on-demand:

```bash
python -m docket.blog.crosspost <city>/<slug>
```

This:
1. Loads the markdown body (frontmatter stripped).
2. Rewrites relative asset paths to absolute `https://docket.pub/...` URLs.
3. Resolves `[[item:N]]` shortcodes to plain markdown links.
4. Copies the result to the clipboard (macOS `pbcopy`) and prints to stdout.
5. Reminds you to set `cross_posted_to.substack` in frontmatter after publishing.

Chart iframes paste through to Substack because Substack supports the same allowlisted hosts (Datawrapper, Flourish, YouTube).

---

## 8. Testing

Unit tests under `tests/blog/`:

**Loader (`test_loader.py`)**

- Valid post parses; all fields populated.
- Missing `title` / `date` / `summary` → raises with a useful message.
- Unknown city → raises.
- Future `date` → marked `scheduled`, excluded from `published_posts()`.
- `_drafts/` files → never appear in `published_posts()`.
- Unknown frontmatter key → logs warning, doesn't crash.
- Duplicate slug in same city → raises.
- `related_items` with non-existent ID → logs warning, omits the link.

**Renderer (`test_render.py`)**

- Plain markdown → HTML.
- Iframe from allowlisted host passes through with `sandbox` and `loading="lazy"` injected.
- Iframe from disallowed host is stripped.
- `[[item:3421]]` shortcode resolves to a link with the agenda item title.
- `[[item:99999999]]` (non-existent) renders as plain text + warning.
- Mermaid fence emits the expected `<div class="mermaid">` block.
- `attr_list` classes survive rendering.

**Routes (`test_routes.py`)**

- `/blog` lists all published posts, newest first.
- `/birmingham/blog` filters to Birmingham + `_shared`.
- `/birmingham/blog/<slug>` renders the post.
- `/birmingham/blog/<wrong-slug>` returns 404.
- Draft post returns 404 without preview token.
- Draft post returns 200 with valid `?preview=` token.
- RSS feeds validate against Atom 1.0 schema.

**Integration (`test_integration.py`)**

- A post with `related_meetings: [2232]` causes meeting 2232's detail page to render an "Editorial coverage" rail linking back.
- City landing page renders "From the blog" rail when posts exist; hides it when empty.

Existing test suite must still pass. No migrations means no DB-state risk.

---

## 9. Visual treatment

Inherits `base.html`, header, footer, color tokens, type scale from the Phase-5 visual refactor. The blog adds:

- A `.prose` reading layout (~70ch max-width, larger body type, more line-height) — applied only inside `<article>` on `post.html`.
- A post card style for listings (cover image left, title + dek + author + date right) — defined as a new partial `partials/_blog_post_card.html`.
- A small set of named utility classes (`.callout`, `.pull-quote`, `.stat-block`, `.figure-wide`) defined in `blog.css` and available via `attr_list`.

No new CSS framework, no new build step.

---

## 10. Operational considerations

- **No migrations.** No database changes anywhere.
- **No new Railway services.** Same web service serves the blog.
- **Caching.** Posts (markdown source, rendered HTML, resolved shortcode titles) are loaded once at process start in prod. Cheap enough that any reasonable post count (hundreds → low thousands) fits in memory. Request handlers serve cached HTML directly — no markdown parsing, no DB hits per request.
- **Image hosting.** Static assets ship in the repo at `content/blog/<city>/<slug>/`. Served by a custom blueprint route `/blog/assets/<city>/<slug>/<filename>` using `send_from_directory` — see §5 "Asset URL rewriting". Large posts with lots of images may want a CDN later; out of scope for v1.
- **Backups.** Posts are git-tracked, so backups come for free.
- **Performance budget.** Each post page should add < 50ms render time over the existing `base.html` shell at p50. (Achievable because HTML is precomputed; the request path is template inheritance + dict lookup.)
- **Redeploy-to-publish friction.** Every change — including a one-character typo fix — requires git push → Railway build → container restart, because posts are loaded into memory at process start. This is the v1 trade for zero DB overhead and a static site's reliability. If the latency becomes annoying in practice, v2 can add a `/admin/blog/reload` webhook route that re-walks `content/blog/` and rebuilds the in-memory cache without a container restart. Not in scope for v1.

---

## 11. Open questions / decisions deferred

- **Tag pages**: `/blog/tag/<tag>` is in the route list but ships in v1 as a simple filtered hub view (no dedicated template). Promote to its own template if usage grows.
- **Full-text search**: Hooking blog posts into existing site search is deferred. Posts are discoverable via the city landing, hub, and tag pages.
- **Comments**: Deferred indefinitely. If we add them, it'll be a separate spec; likely Disqus-replacement avoided in favor of a federated approach (Bluesky thread embed?).
- **Newsletter**: If/when desired, Substack handles the newsletter side; docket.pub stays the canonical home.
- **Dataviz fences**: `pymdownx.superfences` reserves the `dataviz` fence for a future Vega-Lite renderer. v1 does not implement.

---

## 12. Out-of-scope follow-ups (post-v1)

- Per-author pages (`/blog/by/<author>`).
- Series support (`series: bham-budget-2027` frontmatter).
- Programmatic Substack publishing.
- Per-post analytics in the docket.pub admin (Umami already covers this site-wide).
