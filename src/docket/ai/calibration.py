"""Calibration report queries — daily AI scoring drift detection.

Spec: docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md §3.5.
Decision #91 cleanup runs alongside (in the worker task, not here).
"""
from __future__ import annotations


QUERY_A_DIVERGENCE = """
SELECT
  ai.id, m.municipality_id AS city_id, ai.title,
  (ai.score_overrides->>'original_ai_significance')::int AS ai_sig,
  (ai.score_overrides->>'final_significance')::int AS final_sig,
  (ai.score_overrides->>'final_significance')::int
    - (ai.score_overrides->>'original_ai_significance')::int AS sig_delta,
  ai.extracted_facts->>'action_type' AS action_type,
  ai.score_overrides->'triggers' AS triggers_fired
FROM agenda_items ai
JOIN meetings m ON m.id = ai.meeting_id
WHERE ai.score_overrides IS NOT NULL
  AND ai.updated_at > NOW() - INTERVAL '24 hours'
  AND ABS(
      COALESCE((ai.score_overrides->>'final_significance')::int, 0)
      - COALESCE((ai.score_overrides->>'original_ai_significance')::int, 0)
  ) > 3
ORDER BY sig_delta DESC;
"""

QUERY_B1_UNDERSCORING = """
WITH category_stats AS (
  SELECT
    ai.extracted_facts->>'action_type' AS action_type,
    ai.ai_rewrite_version AS prompt_version,
    COUNT(*) AS total_items,
    COUNT(*) FILTER (
      WHERE (ai.score_overrides->>'final_significance')::int
            > (ai.score_overrides->>'original_ai_significance')::int
    ) AS items_with_sig_boost,
    AVG(CASE
          WHEN (ai.score_overrides->>'final_significance')::int
               > (ai.score_overrides->>'original_ai_significance')::int
          THEN (ai.score_overrides->>'final_significance')::int
               - (ai.score_overrides->>'original_ai_significance')::int
        END) AS avg_boost_magnitude
  FROM agenda_items ai
  WHERE ai.processing_status = 'completed'
    AND ai.updated_at > NOW() - INTERVAL '7 days'
  GROUP BY action_type, prompt_version
)
SELECT *,
  ROUND(100.0 * items_with_sig_boost / NULLIF(total_items, 0), 1) AS pct_boosted
FROM category_stats
WHERE total_items >= 30
  AND items_with_sig_boost::float / total_items > 0.20
ORDER BY pct_boosted DESC;
"""

QUERY_B2_OVERSCORING = """
WITH category_stats AS (
  SELECT
    ai.extracted_facts->>'action_type' AS action_type,
    ai.ai_rewrite_version AS prompt_version,
    COUNT(*) AS total_items,
    COUNT(*) FILTER (
      WHERE (ai.score_overrides->>'final_consent')::int
            < (ai.score_overrides->>'original_ai_consent')::int
    ) AS items_with_consent_reduction,
    AVG(CASE
          WHEN (ai.score_overrides->>'final_consent')::int
               < (ai.score_overrides->>'original_ai_consent')::int
          THEN (ai.score_overrides->>'original_ai_consent')::int
               - (ai.score_overrides->>'final_consent')::int
        END) AS avg_reduction_magnitude
  FROM agenda_items ai
  WHERE ai.processing_status = 'completed'
    AND ai.updated_at > NOW() - INTERVAL '7 days'
  GROUP BY action_type, prompt_version
)
SELECT *,
  ROUND(100.0 * items_with_consent_reduction / NULLIF(total_items, 0), 1) AS pct_reduced
FROM category_stats
WHERE total_items >= 30
  AND items_with_consent_reduction::float / total_items > 0.20
ORDER BY pct_reduced DESC;
"""

QUERY_C_DRIFT = """
WITH weekly_baselines AS (
  SELECT
    ai.extracted_facts->>'action_type' AS action_type,
    DATE_TRUNC('week', ai.updated_at)::date AS week,
    AVG(ai.significance_score) AS avg_sig,
    AVG(ai.consent_placement_score) AS avg_consent,
    COUNT(*) AS n
  FROM agenda_items ai
  WHERE ai.updated_at > NOW() - INTERVAL '12 weeks'
    AND ai.processing_status = 'completed'
    AND ai.significance_score IS NOT NULL
  GROUP BY action_type, week
)
SELECT
  action_type, week, avg_sig, avg_consent, n,
  avg_sig - LAG(avg_sig) OVER (PARTITION BY action_type ORDER BY week) AS sig_delta_wow,
  n - LAG(n) OVER (PARTITION BY action_type ORDER BY week) AS volume_delta_wow
FROM weekly_baselines
WHERE n >= 10
ORDER BY action_type, week DESC;
"""


def run_calibration_queries(cur) -> dict:
    """Execute the 4 calibration queries against `cur`. Returns a dict
    summarizing the counts (NOT the full row payloads — those are too
    large for log lines and the caller should query separately if needed).

    Counts only:
      - divergence_count: rows where |delta| > 3 in last 24h
      - underscoring_categories: count of (action_type, version) categories failing the >20% sig-boost threshold
      - overscoring_categories: count of (action_type, version) categories failing the >20% consent-reduction threshold
      - drift_alerts: count of rows in Query C where sig_delta_wow < -1.0 AND volume_delta_wow's abs() < n * 0.3
    """
    counts: dict[str, int] = {}

    cur.execute(QUERY_A_DIVERGENCE)
    counts['divergence_count'] = len(cur.fetchall())

    cur.execute(QUERY_B1_UNDERSCORING)
    counts['underscoring_categories'] = len(cur.fetchall())

    cur.execute(QUERY_B2_OVERSCORING)
    counts['overscoring_categories'] = len(cur.fetchall())

    cur.execute(QUERY_C_DRIFT)
    drift_rows = cur.fetchall()
    counts['drift_alerts'] = sum(
        1 for row in drift_rows
        if (
            row.get('sig_delta_wow') is not None
            and row['sig_delta_wow'] < -1.0
            and row.get('volume_delta_wow') is not None
            and row.get('n', 0) > 0
            and abs(row['volume_delta_wow']) < row['n'] * 0.3
        )
    )

    return counts
