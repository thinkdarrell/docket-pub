# Crawler policy

docket.pub publishes a crawler policy at `/robots.txt` and a sitemap family rooted at `/sitemap.xml`. Both are served by the Flask blueprint in `src/docket/web/crawlers.py`; the database reads behind the sitemaps live in `src/docket/services/sitemap.py`.

## What `/robots.txt` says

The general rule (`User-agent: *`) allows every public page and disallows three things: the admin area (`/admin/`), the search results page (`/search`), and any URL carrying a query string (`/*?`), because filter and pagination parameters produce near-duplicate pages without end. Search engines are not named; they fall under the general rule and are welcome.

A second group names the crawlers that identify themselves as collecting AI training data or as fetching pages for an AI assistant (GPTBot, ClaudeBot, Google-Extended, Applebot-Extended, Bytespider, CCBot, PerplexityBot, Amazonbot, meta-externalagent, and the rest of the `AI_CRAWLERS` tuple in `crawlers.py`) and disallows them from the whole site. `Google-Extended` and `Applebot-Extended` are the training-only controls of Google and Apple; ordinary Google and Apple search indexing is unaffected. The file opens with a plain-language statement that use of the site's content to train AI models is not permitted, and the about page says the same in its privacy section.

`robots.txt` is advisory. A crawler that ignores it, as headless-browser scrapers usually do, is not stopped by anything in this spec. Since 2026-11-11 the site is behind Cloudflare's proxy, and one WAF rule challenges unverified traffic from two cloud networks; `docs/specs/operations.md` (Domain and headers) describes that layer. There is still no application-level rate limit.

## The sitemap family

`/sitemap.xml` is a sitemap index listing every file below. `/sitemaps/pages.xml` lists the site-wide pages (home, about pages, coverage, councilors); the blog is not listed. Every response from the blog's routes (pages, feeds, assets) carries the header `X-Robots-Tag: noindex`, and `robots.txt` does not disallow them, so a crawler can fetch a blog URL and read that it must not index it. For each active city, `/sitemaps/<slug>/meetings.xml` lists the city overview, meetings list and council pages, then every meeting that is not hidden, with `lastmod` from `meetings.updated_at`. `/sitemaps/<slug>/items-<n>.xml` lists that city's agenda items 10,000 per file, in id order, skipping items whose meeting is hidden; `n` counts from 1, and a page past the end, a page below 1, or an unknown or inactive city returns 404.

Every sitemap response is rendered at most once a day per URL, held in an in-process cache, and served with `Cache-Control: public, max-age=86400`. The daily ingest therefore reaches the sitemaps within a day without any invalidation step. Changing a hidden flag on a meeting takes effect in the sitemaps on the same schedule.

## How to check it

With the dev server running, `curl -s http://localhost:5000/robots.txt` prints the policy ending in a `Sitemap:` line with an absolute URL, and `curl -s http://localhost:5000/sitemap.xml` prints a `<sitemapindex>` naming `/sitemaps/pages.xml` plus one meetings file and zero or more items files per city. `tests/web/test_crawlers.py` seeds a city with one visible and one hidden meeting and asserts the hidden one, and its item, never appear.
