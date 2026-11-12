# Publish a crawler policy at /robots.txt and a sitemap family so search engines index docket.pub and AI training crawlers are told to stay out

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `plans/PLANS.md`.

## Purpose / Big Picture

Before this plan, `https://docket.pub/robots.txt` returned the site's 404 page and there was no sitemap. A crawler visiting docket.pub had no policy to follow and no map of the public pages; it either discovered tens of thousands of agenda item pages by following links or did not find them at all. The site's analytics for the month before this plan (read on 2026-11-11 from the Umami views) showed roughly 30,000 one-page visits from Singapore, Santa Clara and China, crawler traffic that the site had no stated position on, next to a few hundred human visits from Alabama.

After this plan, `https://docket.pub/robots.txt` returns a plain-text policy: every public page is open to search engines and readers, the admin area, the search results page and query-string URLs are off limits to all crawlers, and the crawlers that identify themselves as collecting AI training data (GPTBot, ClaudeBot, Google-Extended, Bytespider, CCBot and the rest) are disallowed from the whole site. The file ends with a `Sitemap:` line pointing at `https://docket.pub/sitemap.xml`, a sitemap index that names one file of site-wide pages, and per city one file of meetings and one or more files of agenda items, 10,000 per file. Hidden meetings and their items never appear. The about page's privacy section says in one sentence what the policy is and links to the file. `robots.txt` is a request, not a wall; this plan does not rate-limit anything, and says so.

## Progress

- [x] (2026-11-11 22:40Z) M1: `src/docket/web/crawlers.py` serves `/robots.txt`, `/sitemap.xml`, `/sitemaps/pages.xml`, `/sitemaps/<slug>/meetings.xml` and `/sitemaps/<slug>/items-<n>.xml`; `src/docket/services/sitemap.py` holds the four reads behind them; the blueprint is registered in `create_app`; the about page's privacy section states the policy; `docs/specs/crawlers.md` describes the behaviour and `docs/specs/index.md` lists it; `tests/web/test_crawlers.py` (20 tests) passes against a disposable database.
- [x] (2026-11-11 22:55Z) M1 closing: `./tools/verify` printed `verify: unit+web+services ... ok (71s)` (`1895 passed, 5 skipped, 4 xfailed`), `verify: integration ... ok (95s)` (`621 passed`), `verify: judge-fixtures ... ok (4s)`, `verify: workflows ... ok (0s)`, `verify: all 4 checks passed in 171s.`; plan moved to `plans/completed/`; pull request opened from `feat/crawler-policy`.

## Surprises & Discoveries

- Observation (authoring, 2026-11-11): the site is served straight from Railway, not through Cloudflare's proxy, so there is no firewall or bot-management layer to enforce the policy; `robots.txt` is the whole of what can be done without new infrastructure.
  Evidence: `dig +short docket.pub A` printed `153.52.255.92`; `curl -sI https://docket.pub/` printed `server: railway-hikari` and `x-railway-edge: atl1` and no `cf-ray` header.
- Observation (authoring, 2026-11-11): `agenda_items` has `created_at` but no `updated_at`, so item `lastmod` values come from the parent meeting's `updated_at`.
  Evidence: `src/docket/migrations/001_initial.py` lines 79 to 95 define `agenda_items` with `created_at TIMESTAMPTZ` and no `updated_at`; `meetings` (lines 44 to 59) has both.
- Observation (M1, 2026-11-11): Flask's default string converter would let `/sitemap-<slug>.xml` also match `/sitemap-birmingham-items-1.xml`, so the item and meeting files were given distinct path shapes under `/sitemaps/<slug>/` instead of one flat `sitemap-*.xml` namespace.
  Evidence: design choice made before any route was written; no ambiguous-match failure was observed because the ambiguous shape was never built.
- Observation (M1, 2026-11-11): the new test file passed on its first run against a disposable database.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/web/test_crawlers.py -q -p no:cacheprovider` printed `20 passed in 1.33s`; `tools/test-db --drop` ran afterwards.

- Observation (merge to main, 2026-11-11): main had moved from `e794566` to `a07aca7` while the branch was open, and migration 039 (merged in that window) added a CHECK on `meetings.meeting_type` allowing only `council`, `committee`, `planning`, `board` or `other`. The seeding fixture in `tests/web/test_crawlers.py` used `regular` and failed on the merged tree; it now uses `council`. `docs/specs/index.md` also conflicted (main had added four spec rows) and was resolved by keeping main's rows and inserting the `crawlers.md` row above `transcripts.md`.
  Evidence: first `./tools/verify` on the merged tree printed five `psycopg2.errors.CheckViolation: new row for relation "meetings" violates check constraint "meetings_meeting_type_check"` errors and `verify: 1 of 6 checks failed in 223s.`; after the one-word fixture change it printed `verify: all 6 checks passed in 193s.` (`unit+web+services ... ok (84s)`, `integration ... ok (95s)`, `transcriber ... ok (9s)`, `plans ... ok (0s)`).

## Decision Log

- Decision: keep AI training crawlers out of the whole site rather than let them read.
  Rationale: the operator chose this on 2026-11-11 when asked directly. The site's editorial work should not become training data for free; the reach argument (council votes showing up in AI answers) lost.
  Date/Author: 2026-11-11, operator with Claude.
- Decision: the disallow list also includes the on-demand fetchers (`ChatGPT-User`, `Claude-User`, `Perplexity-User`, `MistralAI-User`), not only the training crawlers.
  Rationale: the approved design named `ChatGPT-User` explicitly. Allowing assistant fetches while blocking training is a one-line edit to `AI_CRAWLERS` if the operator later wants it.
  Date/Author: 2026-11-11, Claude, recorded as the implementer's call.
- Decision: disallow every query-string URL (`Disallow: /*?`) for all crawlers.
  Rationale: pagination and filter parameters produce near-duplicate pages without end; the sitemaps hand crawlers every meeting and item directly, so nothing public is lost.
  Date/Author: 2026-11-11, Claude, in the approved design.
- Decision: sitemaps render on demand with a one-day in-process cache, not from a stored file or a worker task.
  Rationale: mirrors the existing `_rss_cached` pattern in `src/docket/web/public.py`; the daily ingest reaches the sitemaps within a day with no invalidation step and no new worker task.
  Date/Author: 2026-11-11, Claude, in the approved design.
- Decision: 10,000 item URLs per items file.
  Rationale: the sitemap protocol caps a file at 50,000 URLs; 10,000 keeps each render small and leaves room for the largest city (Birmingham, roughly 45,000 items) to grow.
  Date/Author: 2026-11-11, Claude.
- Decision: no rate limiting in this plan.
  Rationale: the crawler that prompted the work runs a headless browser and may ignore `robots.txt`, but its user agent has not been read yet (the Railway CLI login had expired). Deciding an enforcement layer belongs after that evidence, as a separate plan.
  Date/Author: 2026-11-11, operator with Claude.

## Outcomes & Retrospective

Delivered in one session: the policy file, the sitemap family, the about-page sentence, the spec, and 20 route tests, with the full verify suite green. Not delivered, by decision: any enforcement against crawlers that ignore `robots.txt`. The next step there is reading the Singapore crawler's user agent from Railway's HTTP logs once the CLI is logged in again, then deciding whether an application-level rate limit is worth a plan of its own. The behavioural outcome is reflected in `docs/specs/crawlers.md`.

## Context and Orientation

docket.pub is a Flask application whose public routes live in `src/docket/web/public.py` and whose application factory, `create_app`, is in `src/docket/web/__init__.py`. Routes call functions in `src/docket/services/`, which own every database read and write (the rule is stated in `AGENTS.md`). A "blueprint" is Flask's name for a group of routes registered on the application as a unit; `create_app` registers each one with `app.register_blueprint`.

A `robots.txt` file is a plain-text file at the root of a site that tells automated visitors (crawlers) which paths they may fetch. Each group starts with one or more `User-agent:` lines naming the crawler and is followed by `Allow:` and `Disallow:` path rules; `*` names every crawler. It is honoured voluntarily. A sitemap is an XML file listing a site's URLs for crawlers; a sitemap index is an XML file listing other sitemap files.

Meetings carry an `is_hidden` flag (migration 033) that keeps non-meetings out of the public site; anything the sitemaps list must respect it. Cities are rows of `municipalities` with an `active` flag.

## Plan of Work

Create `src/docket/services/sitemap.py` with `list_cities()` (active cities with visible item counts and the number of 10,000-item pages each needs), `city_exists(slug)`, `list_meetings(slug)` (visible meetings with `updated_at`) and `list_items(slug, page)` (one page of visible items with the parent meeting's `updated_at`).

Create `src/docket/web/crawlers.py` with a blueprint named `crawlers` serving `/robots.txt` (text built from a header comment, the general group, one group of `AI_CRAWLERS` with `Disallow: /`, and a `Sitemap:` line built with `url_for(..., _external=True)` so it is absolute and, behind Railway's proxy, `https`), `/sitemap.xml` (the index), `/sitemaps/pages.xml`, `/sitemaps/<slug>/meetings.xml` and `/sitemaps/<slug>/items-<int:page>.xml`. Sitemap bodies go through a one-day cache keyed by URL with a lock, copied in shape from `_rss_cached`; `clear_cache()` exists for tests.

Register the blueprint in `create_app` next to `public_bp`. Add one paragraph to the privacy section of `src/docket/web/templates/about.html`. Write `docs/specs/crawlers.md` and add its row to `docs/specs/index.md`. Write `tests/web/test_crawlers.py` using the `client` fixture from `tests/web/conftest.py` and a seeding fixture modelled on `tests/web/test_p4_1_restyles.py`.

## Concrete Steps

From the repository root, on branch `feat/crawler-policy`, with the checkout's own `venv/`:

    DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/web/test_crawlers.py -q -p no:cacheprovider
    tools/test-db --drop

expect `20 passed`. Then

    ./tools/verify

expect every check `ok` and a final `verify: all N checks passed`. Then move this file to `plans/completed/crawler-policy.md`, commit, push, and open a pull request against `main`.

## Validation and Acceptance

With the dev server running (`venv/bin/flask run`), `curl -s http://localhost:5000/robots.txt` prints a file beginning `# docket.pub crawler policy`, containing a `User-agent: *` group with `Allow: /` and `Disallow: /admin/`, a group that names `GPTBot` and `ClaudeBot` and ends `Disallow: /`, and a final `Sitemap: http://localhost:5000/sitemap.xml` line. `curl -s http://localhost:5000/sitemap.xml` prints a `<sitemapindex>` naming `/sitemaps/pages.xml` and, per active city, a `meetings.xml` and zero or more `items-<n>.xml`. For a city with a hidden meeting, that meeting's URL and its items' URLs are absent from the city's files. `tests/web/test_crawlers.py` asserts each of these.

## Idempotence and Recovery

Every step is additive and can be re-run. The seeding fixture cleans up after itself by title prefix `CRAWL_TEST_` and slug `crawltest_city`. Nothing touches production data; the policy takes effect on the next deploy of `docket-web` from `main`.

## Artifacts and Notes

The analytics reading that prompted the plan (from the Umami `v_geo_daily` view on 2026-11-11, last 30 days): Singapore 25,775 pageviews over 23,977 sessions (1.07 pages per session), Santa Clara CA 3,921 over 3,798, China 1,021 over 990, Alabama 351 over 161 (2.18 pages per session).

## Interfaces and Dependencies

No new dependencies. `docket.services.sitemap` exposes `ITEMS_PER_SITEMAP: int`, `list_cities() -> list[dict]`, `city_exists(slug: str) -> bool`, `list_meetings(slug: str) -> list[dict]`, `list_items(slug: str, page: int) -> list[dict]`. `docket.web.crawlers` exposes `bp`, `AI_CRAWLERS`, `SITE_PAGES`, `SITEMAP_TTL_SECONDS`, `robots_body(sitemap_url: str) -> str` and `clear_cache() -> None`.
