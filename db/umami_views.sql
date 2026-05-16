-- Stable read-only views over Umami's raw schema.
-- All path normalization happens here, NOT at ingestion time.
-- When Umami upgrades and breaks a column, fix THIS file — never the consumers.
--
-- Apply with:
--   psql "postgres://umami:...@.../umami" -f db/umami_views.sql
--
-- The `umami_reader` role's GRANT lines at the bottom let read-only consumers
-- (Claude, ad-hoc analysis) hit the views without touching raw tables.

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
    WHEN url_path ~ '^/items/\d+/badges$' THEN '/items/[id]/badges'
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
  COUNT(*) AS event_count,
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
  COUNT(*) AS event_count
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

-- Grants for the read-only role. umami_reader gets NO access to raw tables.
GRANT USAGE ON SCHEMA public TO umami_reader;
GRANT SELECT ON
  v_pageviews_daily,
  v_event_counts_daily,
  v_event_props_daily,
  v_referrers_daily,
  v_geo_daily
TO umami_reader;
