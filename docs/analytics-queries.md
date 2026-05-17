# Analytics Query Cheat Sheet

Reference for querying the Umami analytics database. **Never query raw Umami tables (`website_event`, `event_data`, `session`) — only the views below.** The view layer absorbs Umami's schema evolution; raw tables can break between Umami releases. (Umami v3 already moved `country`/`region`/`city` from `website_event` to `session` — `v_geo_daily` JOINs to absorb the change; consumers don't need to know.)

## Connecting

Read-only credentials live in `~/.docket-pub.env.local`:

```bash
source ~/.docket-pub.env.local
/opt/homebrew/opt/postgresql@18/bin/psql "$UMAMI_READER_URL"
```

The `umami_reader` role has `SELECT` only on the five `v_*` views below — no raw-table access.

## Views

| View | Grain (one row per...) | Columns |
|---|---|---|
| `v_pageviews_daily` | `(day, normalized_path)` | `day date`, `normalized_path text`, `pageviews int`, `sessions int` |
| `v_event_counts_daily` | `(day, event_name)` | `day date`, `event_name text`, `event_count int`, `sessions int` |
| `v_event_props_daily` | `(day, event_name, prop_key, prop_value)` | `day date`, `event_name text`, `prop_key text`, `prop_value text`, `event_count int` |
| `v_referrers_daily` | `(day, referrer_domain)` | `day date`, `referrer_domain text`, `pageviews int` |
| `v_geo_daily` | `(day, country, region, city)` | `day date`, `country char(2)`, `region text`, `city text`, `pageviews int`, `sessions int` |

## Path normalization

Numeric IDs collapse (`/al/birmingham/meetings/123` → `/al/birmingham/meetings/[id]`). City slugs and badge slugs are preserved because they ARE the dimensions we care about. Full normalization rules are in `db/umami_views.sql`. Post-PR #64 (item-centric refactor), traffic that used to flow through `/al/<slug>/meetings/<id>#item-N` now lands on `/al/<slug>/items/<id>/` — both are already normalized, so the shift is invisible at the view layer.

## Common patterns

### Top pages last 7 days

```sql
SELECT normalized_path, SUM(pageviews) AS views, SUM(sessions) AS sessions
FROM v_pageviews_daily
WHERE day >= current_date - 7
GROUP BY 1
ORDER BY 2 DESC
LIMIT 20;
```

### Zero-result searches (editorial roadmap)

These are literal product roadmap input from readers — what they want that we don't have.

```sql
SELECT q.prop_value AS query, COUNT(*) AS attempts
FROM v_event_props_daily q
JOIN v_event_props_daily r USING (day, event_name)
WHERE q.event_name = 'search_submit'
  AND q.prop_key = 'query'
  AND r.prop_key = 'result_count'
  AND r.prop_value = '0'
  AND q.day >= current_date - 30
GROUP BY 1
ORDER BY 2 DESC
LIMIT 30;
```

**Notes:**
- Queries longer than 40 characters are *dropped* at the client before sending (PII guardrail in `track.js`). `result_count` is still recorded for dropped queries, so the zero-result *rate* across all searches is queryable even when individual query text is suppressed.
- `result_count` reports the size of the *first page* of results (≤ 20), not the total across all pages — the search route uses a row-count heuristic, not a separate `COUNT(*)`. So `result_count='0'` is unambiguous (truly zero results), but non-zero values should be read as "this many on the first page; could be more."
- The event only fires on `page == 1` (pagination clicks don't re-fire), so each search-submit row is one user-initiated search.

### Outbound source clicks (civic-mission signal)

The North Star metric for docket.pub: are we routing readers back to primary municipal documents?

```sql
SELECT prop_value AS source_type, COUNT(*) AS clicks
FROM v_event_props_daily
WHERE event_name = 'outbound_source_click'
  AND prop_key = 'source_type'
  AND day >= current_date - 30
GROUP BY 1
ORDER BY 2 DESC;
```

Expected `source_type` values: `granicus_video`, `minutes_pdf`, `agenda_pdf`, `city_site`, `other`.

For per-item drill-down (which items drove the most outbound clicks?):

```sql
SELECT prop_value AS item_id, COUNT(*) AS clicks
FROM v_event_props_daily
WHERE event_name = 'outbound_source_click'
  AND prop_key = 'item_id'
  AND day >= current_date - 30
GROUP BY 1
ORDER BY 2 DESC
LIMIT 20;
```

### Civic geo signal (which cities are reading)

Real test of "is docket.pub reaching residents in the cities we cover, not just nerds elsewhere":

```sql
SELECT region AS state, city, SUM(pageviews) AS views, SUM(sessions) AS sessions
FROM v_geo_daily
WHERE country = 'US'
  AND day >= current_date - 30
GROUP BY 1, 2
ORDER BY 3 DESC
LIMIT 25;
```

Filter to Alabama specifically:

```sql
SELECT city, SUM(pageviews) AS views, SUM(sessions) AS sessions
FROM v_geo_daily
WHERE country = 'US'
  AND region = 'AL'
  AND day >= current_date - 30
GROUP BY 1
ORDER BY 2 DESC;
```

### Referrer breakdown

```sql
SELECT referrer_domain, SUM(pageviews) AS views
FROM v_referrers_daily
WHERE day >= current_date - 14
GROUP BY 1
ORDER BY 2 DESC
LIMIT 20;
```

### Are the new item_detail Vote Result banners earning clicks?

The `vote_source_link` macro on item_detail (PR #64) fires `outbound_source_click` with `data-item-id` context. Cross-reference items with the most vote-banner-driven outbound clicks:

```sql
WITH banner_clicks AS (
  SELECT prop_value AS item_id, COUNT(*) AS clicks
  FROM v_event_props_daily
  WHERE event_name = 'outbound_source_click'
    AND prop_key = 'item_id'
    AND day >= current_date - 14
  GROUP BY 1
)
SELECT item_id, clicks
FROM banner_clicks
ORDER BY clicks DESC
LIMIT 20;
```

(Cross-reference with the editorial DB by joining `item_id` against `agenda_items.id` for title context. The two DBs live on the same Postgres instance but in different databases — query both via separate sessions.)

## Versioning

- View definitions live in `db/umami_views.sql` (single source of truth).
- Umami version is currently v3.x (deployed via the Railway Umami template). Tag pinning is at the template level; not currently locked to a specific version.
- Schema fixture lives at `tests/fixtures/umami_schema_v3.sql` — regenerate via `pg_dump --schema-only` only when deliberately bumping Umami (procedure in `docs/runbooks/analytics.md`).
- When Umami releases a breaking schema change, the integration test (`tests/integration/test_analytics_views.py`) catches it. Fix is one PR to `db/umami_views.sql`; consumers don't move.
