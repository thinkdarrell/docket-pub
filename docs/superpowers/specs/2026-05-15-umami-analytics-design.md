# Umami Analytics Design

**Date:** 2026-05-15
**Status:** Draft (brainstorm)
**Scope:** Add privacy-first product analytics to docket.pub via a self-hosted Umami instance on Railway, with the event store living in the existing Railway Postgres so Claude can query analytics directly through the same DB tooling already used for editorial data. Captures pageviews, geo, and a small set of B-priority editorial events to validate the rails / coverage / outbound-source features.

## Problem

docket.pub currently has zero analytics. Every editorial design decision — rail variants, coverage pairs, the ?month filter on category landing, the badge UI — has shipped to production without any feedback signal beyond manual page visits and qualitative judgment. We can't answer basic questions:

1. **Are the rails working?** PR D shipped a per-page rail variant on category landing. Did anyone click it? Which variant outperforms?
2. **Is the platform fulfilling its civic mission?** docket.pub exists to route readers back to primary municipal documents. We don't know whether the outbound clicks happen.
3. **What do readers want that we don't have?** Search misses are an editorial roadmap that we're currently throwing away.

The constraint that makes this non-trivial: docket.pub is a civic transparency platform. Loading Google Analytics or a cookie-based tracker would undermine the privacy posture that's already implicit in the brand. Any analytics solution must be cookieless, consent-banner-free, and aligned with the platform's mission.

## Goals

- Pageview counting with geo (country / city level) and referrer attribution.
- Custom event capture for three priority editorial signals: rail clicks, outbound source clicks, and search submissions (including zero-result misses).
- Cookieless and consent-banner-free by design.
- Analytics data lives in the existing Railway Postgres so Claude can query it via the same `DATABASE_PUBLIC_URL` pattern already used for editorial data — no MCP server, no API wrapper.
- Insulated from Umami's schema evolution via a thin read-only view layer that we own.
- Bounded resource impact on the existing `docket-web` / `worker` services.

## Non-Goals

- **Funnels, retention cohorts, session replay.** These require persistent visitor IDs, which the strict-privacy posture rules out.
- **A custom dashboard.** Umami's built-in dashboard handles A-tier traffic questions. For B-tier editorial questions, we query Postgres directly.
- **MCP server / API wrapper.** With events in our own Postgres, the existing DB-querying pattern already covers the agentic use case.
- **PgBouncer / external connection pooling.** Per-role `CONNECTION LIMIT` is sufficient at this scale.
- **The full v2 event set.** Six candidate events were discussed; v1 ships three (rail_click, outbound_source_click, search_submit). The other three (coverage_pair_click, month_filter, item_badge_click) are deferred to a follow-up once we've seen baseline data.

## Architecture

### Services

A third Railway service named `analytics`, running the official Umami Postgres image:

- **Image:** `ghcr.io/umami-software/umami:postgres-latest`
- **Public ingress:** yes, on the custom domain `stats.docket.pub`
- **Internal egress:** to the existing Railway Postgres instance
- **Start command:** the image default (Umami's Node entry point)
- **Healthcheck path:** `/api/heartbeat` (Umami built-in)

The existing `docket-web` and `worker` services are untouched at the service level. `docket-web` gets one new line in `base.html`; `worker` gets one new scheduled task for retention.

### Database

Create a separate database `umami` on the existing Railway Postgres instance (Postgres 18.3). Same server, isolated schema. Two roles:

```sql
-- Owner role used by the Umami container
CREATE ROLE umami WITH LOGIN PASSWORD '<generated>' CONNECTION LIMIT 8;
CREATE DATABASE umami OWNER umami;
GRANT ALL PRIVILEGES ON DATABASE umami TO umami;

-- Read-only role for Claude / ad-hoc analysis
CREATE ROLE umami_reader WITH LOGIN PASSWORD '<generated>';
GRANT CONNECT ON DATABASE umami TO umami_reader;
-- After view layer is applied:
GRANT USAGE ON SCHEMA public TO umami_reader;
GRANT SELECT ON v_pageviews_daily, v_event_counts_daily,
                 v_event_props_daily, v_referrers_daily, v_geo_daily
       TO umami_reader;
```

The `CONNECTION LIMIT 8` on the `umami` role is the hard backstop that protects `docket-web` and `worker` from connection-pool starvation during a traffic spike. Umami's internal Prisma client is independently capped via a `?connection_limit=5` URL parameter (see env vars below), so Prisma queues requests internally rather than crashing against the Postgres rejection wall. Five Prisma connections under an eight-role cap leaves three-connection headroom for reconnect storms.

`umami_reader` has no access to the raw Umami tables — only the views. This is the structural guarantee that Umami schema changes can't break Claude's queries.

### Custom domain

`stats.docket.pub` CNAMEs to the `analytics` service's Railway domain. Adblockers' standard lists default-block Umami/Plausible CDN endpoints; serving from a `docket.pub` subdomain captures 15–30% more real traffic and reinforces the privacy posture (network panel shows only docket.pub requests).

If aggressive CNAME-resolving blockers (uBlock Origin strict mode) become a problem in future, the next iteration is a Flask reverse proxy serving `docket.pub/s/script.js` and `docket.pub/s/api/send` from the main app, with the `analytics` service made internal-only. Documented here as a known forward path; not built in v1.

### View layer

A single SQL file `db/umami_views.sql` defines the stable read-only views. Applied once after Umami's first-boot schema is created. The Flask app does not run Umami migrations — Umami manages its own schema on startup.

```sql
-- db/umami_views.sql
-- Stable read-only views over Umami's raw schema.
-- All path normalization happens here, NOT at ingestion time.
-- When Umami upgrades and breaks a column, fix this file — never the consumers.

DROP VIEW IF EXISTS v_pageviews_daily CASCADE;
CREATE VIEW v_pageviews_daily AS
SELECT
  date_trunc('day', created_at)::date AS day,
  CASE
    WHEN url_path ~ '^/al/[^/]+/meetings/\d+' THEN
         regexp_replace(url_path, '/meetings/\d+', '/meetings/[id]')
    WHEN url_path ~ '^/al/[^/]+/items/\d+' THEN
         regexp_replace(url_path, '/items/\d+', '/items/[id]')
    WHEN url_path ~ '^/coverage/\d+' THEN '/coverage/[id]'
    WHEN url_path ~ '^/items/\d+/badges' THEN '/items/[id]/badges'
    ELSE url_path
  END AS normalized_path,
  COUNT(*) AS pageviews,
  COUNT(DISTINCT session_id) AS sessions
FROM website_event
WHERE event_type = 1  -- pageview
GROUP BY 1, 2;

DROP VIEW IF EXISTS v_event_counts_daily CASCADE;
CREATE VIEW v_event_counts_daily AS
SELECT
  date_trunc('day', created_at)::date AS day,
  event_name,
  COUNT(*) AS count,
  COUNT(DISTINCT session_id) AS sessions
FROM website_event
WHERE event_type = 2  -- custom event
GROUP BY 1, 2;

DROP VIEW IF EXISTS v_event_props_daily CASCADE;
CREATE VIEW v_event_props_daily AS
SELECT
  date_trunc('day', we.created_at)::date AS day,
  we.event_name,
  ed.data_key   AS prop_key,
  ed.string_value AS prop_value,
  COUNT(*) AS count
FROM website_event we
JOIN event_data ed ON ed.website_event_id = we.event_id
WHERE we.event_type = 2
GROUP BY 1, 2, 3, 4;

DROP VIEW IF EXISTS v_referrers_daily CASCADE;
CREATE VIEW v_referrers_daily AS
SELECT
  date_trunc('day', created_at)::date AS day,
  referrer_domain,
  COUNT(*) AS pageviews
FROM website_event
WHERE event_type = 1 AND referrer_domain IS NOT NULL
GROUP BY 1, 2;

DROP VIEW IF EXISTS v_geo_daily CASCADE;
CREATE VIEW v_geo_daily AS
SELECT
  date_trunc('day', created_at)::date AS day,
  country,
  city,
  COUNT(*) AS pageviews,
  COUNT(DISTINCT session_id) AS sessions
FROM website_event
WHERE event_type = 1
GROUP BY 1, 2, 3;
```

Column names above match Umami v2's current schema. Exact references will be verified against the running container during deployment; any mismatches get fixed in this file, not anywhere downstream.

### Path normalization

City slugs (`/al/birmingham/`) and badge slugs (`/al/birmingham/<badge>/`) are deliberately preserved — they're the dimensions we care about. Only opaque numeric IDs collapse. This keeps the D-priority civic-geo signal intact at the URL level (every BHM-vs-Mobile pageview is countable without joining to event properties).

HTMX partial endpoints (`/al/<slug>/_rail/...` and `/items/<id>/badges`) don't render `base.html` and therefore don't fire pageviews. They show up in the data only when explicitly tracked, which we don't do — the originating click is captured as a `rail_click` custom event from the source page.

### Tracking script placement

A single `<script>` tag added to `base.html`, just before `</head>`:

```html
<script defer
        src="https://stats.docket.pub/script.js"
        data-website-id="<UUID>"
        data-do-not-track="true"
        data-exclude-search="true"></script>
```

- `data-do-not-track="true"` — honor browser DNT signal.
- `data-exclude-search="true"` — strip query strings from auto-captured pageview paths. We capture meaningful query-string features (the `?month=` filter on category landing) as explicit custom events instead, decoupling analytics from routing.
- Excluded paths configured in Umami's website settings: `/admin/*`, `/healthz`, `*.rss`, `/al/*/data-debt.rss`, `/al/*/upcoming-hearings.rss`, `/coverage.rss`.

### Event helper

`src/docket/web/static/js/track.js`:

```javascript
// Single source of truth for custom event tracking.
// Wraps umami.track() with a try/catch so a blocked analytics script
// can never break a click handler.
window.docketTrack = function (name, props) {
  try {
    if (window.umami && typeof window.umami.track === 'function') {
      window.umami.track(name, props || {});
    }
  } catch (e) {
    // Analytics blocked or failed — never break the page.
  }
};
```

Loaded via one `<script src="{{ url_for('static', filename='js/track.js') }}" defer></script>` in `base.html`. Templates emit events via inline handlers or delegated listeners that call `docketTrack(name, props)`.

## v1 Event Set

Three events ship in v1. Each is wired through `docketTrack()`.

### rail_click

Fires when a visitor clicks a link inside any rail partial (default, meeting, or member rail).

Properties:
- `rail_variant` — which rail partial rendered the link. One of `default`, `meeting`, `member`, `source_rail` (the per-page variant added in the PR D visual refactor).
- `source_page_type` — which page the rail was rendered on. One of `home`, `city`, `meeting`, `item`, `category_landing`, `coverage`, `topic`, `search`, `councilor`.
- `target_type` — what the clicked link points to. One of `meeting`, `item`, `member`, `category`, `source_doc`.
- `target_id` — numeric ID where applicable, or slug.

(Note: `rail_variant` is mutually exclusive of `source_page_type` — the first describes which partial was rendered, the second describes where it appeared. Both are needed to answer "which rail variant works best on which page.")

Implementation: a delegated `click` listener on `.rail` in `base.html` reads `data-*` attributes from the clicked anchor. Rail partial templates already render most of the needed metadata; small additions to `rail_default.html`, `rail_meeting.html`, `rail_member.html` to expose `data-target-type` and `data-target-id`.

Answers: are the rails earning their visual weight in the layout? Which variant converts on which source page?

### outbound_source_click

Fires when a visitor clicks a link to a primary municipal document (Granicus video timestamp, minutes PDF, city website page, agenda PDF). This is docket.pub's North Star metric — the civic mission is to route readers back to the source.

Properties:
- `source_type` — one of `granicus_video`, `minutes_pdf`, `agenda_pdf`, `city_site`, `other`
- `target_domain` — hostname of the destination URL (e.g., `bhamal.granicus.com`)
- `item_id` or `meeting_id` — context, when available

Implementation: delegated `click` listener on `a[href]` checks for external hosts and classifies. The classifier is small and lives in `track.js`. Source badges in templates (`citation-badge`, `source-link`, etc.) already carry the `data-source-type` attribute we need.

Answers: is the platform actually fulfilling its civic-transparency mission? Which document types do readers reach for?

### search_submit

Fires on search form submission.

Properties:
- `query` — the submitted query string (lowercased, trimmed)
- `result_count` — integer, including 0
- `city` — current city scope, when scoped

Implementation: the search form posts to `/search`. The server-rendered results page emits a one-shot `docketTrack('search_submit', {...})` call in a `<script>` tag at the top of `search.html`, with values templated from the request and result count.

Zero-result searches are the high-value signal: they are literal product roadmap input from readers. The `result_count` property makes them filterable in a single SQL query.

Answers: what do readers want that we don't have? What's the gap between editorial assumption and reader intent?

## Operations

### Retention

A new `prune_analytics` task on the existing `worker` scheduler, registered alongside the current five tasks. Monthly cadence (1st of each month, 04:00 America/Chicago, before any other scheduled task). Implementation:

```python
# src/docket/worker/tasks.py — new task
def prune_analytics():
    """Delete Umami events older than 24 months. Idempotent."""
    dsn = os.environ["ANALYTICS_DATABASE_URL"]
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("""
            DELETE FROM website_event
            WHERE created_at < NOW() - INTERVAL '24 months'
        """)
        deleted = cur.rowcount
        conn.commit()
    return {"deleted": deleted}
```

Wrapped in `_safe_run` like the other tasks, with its own Healthchecks UUID. New env vars on the `worker` service:
- `ANALYTICS_DATABASE_URL` — full DSN with `?connection_limit=2` (batch-only, doesn't need more)
- `HEALTHCHECK_PRUNE_ANALYTICS_UUID` — heartbeat ID

For ~18 months we expect nothing to delete (Umami has only just started running). The task is correct by construction from day 1.

### Initial setup

Sequence is captured in a new runbook `docs/runbooks/analytics.md`:

1. **Provision DB and roles** via `psql` against the Railway public proxy: create `umami` database, `umami` and `umami_reader` roles with passwords, set `CONNECTION LIMIT 8` on `umami`.
2. **Create Railway service** `analytics`: Empty Service → set image to `ghcr.io/umami-software/umami:postgres-latest`, copy env vars (`DATABASE_URL=postgres://umami:...@<host>:<port>/umami?connection_limit=5`, `APP_SECRET=<generated>`, `HASH_SALT=<generated>`).
3. **Boot the container.** Umami auto-creates its schema on first boot. Verify tables exist via `psql`.
4. **Apply view layer**: `psql $UMAMI_DATABASE_URL -f db/umami_views.sql`.
5. **Grant `umami_reader` SELECT** on the views (final block of the view file, applied once).
6. **Custom domain**: add `stats.docket.pub` in Railway's custom-domain config for the `analytics` service. Update Namecheap DNS to CNAME `stats` to the Railway-provided target. Wait for Let's Encrypt cert provisioning.
7. **First-boot admin** at `https://stats.docket.pub` — set initial admin user/password. Register `docket.pub` as a tracked website. Copy the `data-website-id` UUID.
8. **Configure excluded paths** in the Umami website settings (`/admin/*`, `*.rss`, etc.).
9. **Plumb the script** into `base.html`. Add `track.js`. Deploy `docket-web`.
10. **Smoke test**: load the homepage, click one rail item, perform one search. Verify rows in `website_event` (1 pageview row + 1 `rail_click` row + 1 `search_submit` row), confirm they surface in the relevant views.
11. **Worker env vars**: add `ANALYTICS_DATABASE_URL` and `HEALTHCHECK_PRUNE_ANALYTICS_UUID` to the `worker` service. Deploy `worker`.

### Credentials storage

- `umami` role password → Railway env vars (`analytics` service `DATABASE_URL`, `worker` service `ANALYTICS_DATABASE_URL`).
- `umami_reader` role password → developer `.env.local` for ad-hoc Claude/CLI queries. Not committed.
- `data-website-id` UUID → committed in `base.html` (it's a public identifier, not a secret).

### Monitoring

Umami's built-in dashboard at `https://stats.docket.pub` covers A-tier traffic and D-tier geo questions. B-tier editorial questions are answered via direct Postgres queries documented in `docs/analytics-queries.md`.

The `prune_analytics` task pings Healthchecks.io monthly. The `analytics` service itself has no Healthchecks integration in v1 — Railway's container health is sufficient (failure mode is "stats site down," not "data lost," because the script gracefully no-ops on a missing tracker).

## Agentic Query Layer

No service, no MCP, no API wrapper. Three artifacts:

### `docs/analytics-queries.md`

Stable view schemas plus a cheat sheet of common questions. Lives in the repo so it's diffed when views change. Roughly:

- View reference (columns + grain for each of the five views).
- Common Q→SQL patterns: top pages last 7 days, rail variant conversion, zero-result searches, geo breakdown by city, referrer analysis.
- Connection guidance (use `umami_reader` credentials with `?dbname=umami` against `$DATABASE_PUBLIC_URL_HOST`).

### `CLAUDE.md` pointer

Three lines added to the existing `CLAUDE.md`:

> Analytics views live in the `umami` database on the Railway Postgres instance. Query via `umami_reader` credentials in `.env.local` (read-only on views, not raw tables). See `docs/analytics-queries.md` for view schemas and common patterns. Never query raw Umami tables — only the `v_*` views.

### Operating pattern

Ad-hoc analytics questions are answered by Claude running a SQL query against the `umami` database using the existing DB tooling pattern. Example session:

```
user: what searches returned zero results last week?
claude: [queries v_event_props_daily + v_event_counts_daily joined on event_name='search_submit', filters result_count='0', orders by count desc]
```

When Umami upgrades and breaks a column, the failure surfaces as a query error during such a session. The fix is one PR to `db/umami_views.sql`; consumers don't move.

## Testing

- **Unit tests:** `tests/unit/test_track_js.py` is N/A (frontend JS). Manual verification only.
- **Integration test:** new `tests/integration/test_analytics_views.py` — boots a temporary Postgres, runs Umami's schema-init SQL (or a fixture dump of an empty Umami DB), applies `db/umami_views.sql`, inserts hand-crafted rows into `website_event` and `event_data`, asserts each view returns the expected aggregation. This catches view-definition breakage on Umami version bumps before they hit production.
- **Smoke test post-deploy:** documented in the runbook (step 10 above). Manual, takes ~3 minutes.
- **Worker test:** `tests/unit/test_prune_analytics.py` — mocks the DB cursor, asserts the DELETE is issued with the right interval, asserts the row count is returned.

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Umami schema changes between releases | Medium (Umami is actively maintained) | View layer absorbs it. Integration test catches breakage. Pin the Umami image to a specific tag, not `latest`, so upgrades are explicit. |
| Connection pool starvation against the editorial app | Low | `CONNECTION LIMIT 8` on the `umami` role + `connection_limit=5` in Prisma URL. Three-connection headroom. |
| WAL bloat on the small Railway DB volume | Low (analytics writes are small per row) | The Railway volume is now 1GB (resized 2026-05-12 after the Wave 0 incident). Umami writes are ~200 bytes per row; at 10K pageviews/day this is 2MB/day of base data, well under WAL pressure. |
| Adblockers neutralize the tracker globally | Medium | `data-do-not-track="true"` honors DNT explicitly. Custom subdomain captures default-list blockers. CNAME-aware blockers escape; documented Phase 2 path is the in-app reverse proxy. |
| Sensitive data in event properties (e.g., query strings containing PII) | Low (we control what gets tracked) | Search queries are lowercased and trimmed but not redacted — readers searching for personal context (their own address, etc.) is a possible PII exposure. Mitigation: in `search_submit`, strip queries longer than 80 chars or containing digits adjacent to street suffixes. Defer the precise filter until we see real data; document the concern. |
| Umami container OOM | Low | Umami is light (~150MB RAM idle). Railway's default per-service memory is sufficient. |
| `stats.docket.pub` Let's Encrypt cert provisioning delay | Low | One-time concern at setup. Document in runbook with a 10-minute wait window. |

## Migration / Rollout

This is purely additive — no migrations to docket's existing schema, no changes to existing routes, no impact on the ingest/AI/vote-matching pipelines.

Rollout order:

1. Spec approved → write implementation plan.
2. DB roles + service provisioning (server-side, no app changes).
3. View layer + smoke verification with hand-crafted rows.
4. `track.js` + `base.html` script tag → deploy `docket-web`.
5. Three event handlers wired in templates → deploy `docket-web`.
6. `prune_analytics` task + worker env vars → deploy `worker`.
7. Two weeks of baseline observation. Then decide which of the three deferred events (coverage_pair_click, month_filter, item_badge_click) to add next.

Rollback for any individual step is single-file: removing the script tag from `base.html` and redeploying takes the entire tracker offline cleanly, leaving the data intact for forensic review.

## Open Questions

1. **Search query PII filtering** — what's the right rule? Discussed in Risks. Recommend deferring to see real data, then defining the filter precisely. Marked here so it's not forgotten.
2. **Public stats page** — Umami can expose a public read-only dashboard at `stats.docket.pub/share/<token>`. Could be a transparency artifact on-brand for civic mission ("here's what's been read on docket.pub"). Not part of v1; flagged as a low-cost enhancement.

## References

- Umami v2 docs: https://umami.is/docs
- Umami Docker image: https://github.com/umami-software/umami/pkgs/container/umami
- Existing cron worker design: `docs/superpowers/specs/2026-05-04-cron-worker-design.md`
- Existing repo CLAUDE.md (where the agentic pointer will land)
