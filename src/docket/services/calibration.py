"""Calibration queries — admin observability into AI scoring drift.

Six query helpers feed the ``/admin/calibration`` dashboard. They map
1-to-1 onto the spec sections that defined them:

- :func:`query_a_per_item_divergence` — Spec §3.5 Query A: per-item
  ``ABS(final_significance - original_ai_significance) > 3`` over the
  last 24 hours. Useful for catching individual mis-scores Stage 2.5
  had to override hard.
- :func:`query_b1_under_scoring_impact` — Spec §3.5 Query B1: per
  ``(action_type, prompt_version)`` window over 7 days, surfaces
  categories where AI under-rated significance > 20% of the time
  (sample size >= 30).
- :func:`query_b2_over_scoring_consent` — Spec §3.5 Query B2:
  symmetric to B1 but for consent placement (AI rated as more
  consent-appropriate than the floors allowed).
- :func:`query_c_baseline_drift` — Spec §3.5 Query C: 12-week
  per-action_type trend in ``avg(significance_score)``,
  ``avg(consent_placement_score)`` and volume. Catches systematic
  prompt drift even when Stage 2.5 never fires.
- :func:`query_badge_volume_calibration` — Spec §5.7: per
  ``(city, badge, week)`` over 12 weeks; flags policy badges where
  deterministic-only or LLM-only signals exceed 40% (suggests
  matcher_hints / prompt mismatch).
- :func:`query_top_false_positives` — Spec §5.7 (decision #65):
  policy badges admins removed >= 5 times in the last 7 days.

All queries use ``%s`` placeholders (parameterized SQL — never string
concatenation) and return ``list[dict]``. Empty list when no rows
match the threshold — the admin template renders a per-panel empty
state in that case.

**Spec/code drift note** — the spec text says ``ai.updated_at`` for
Queries A/B1/B2/C, but the local schema doesn't have an ``updated_at``
column on ``agenda_items`` (Migration 001 did not add the
auto-update trigger to ``agenda_items``; only ``meetings`` and
``municipalities`` carry one). The closest analog with the same
freshness semantics is :py:attr:`agenda_items.ai_generated_at` —
written by the AI worker on every successful Stage 2 / 2.5 run, which
is exactly the moment ``score_overrides`` is populated. Using
``ai_generated_at`` keeps the queries' intent ("was this score
recently produced?") intact. If/when an ``updated_at`` is added in a
future migration, swap it in here.

The dashboard is admin-only, so the per-row dicts may carry internal
vocabulary (``action_type``, ``prompt_version``, ``triggers_fired``)
without translation — admin readers can read it.
"""

from __future__ import annotations

from typing import Any

from docket.db import db_cursor


# ---------------------------------------------------------------------------
# Query A — Per-item divergence (>3 points either direction, 24h window).
# ---------------------------------------------------------------------------


def query_a_per_item_divergence() -> list[dict[str, Any]]:
    """Items whose final significance diverges from the AI's by > 3 in 24h.

    Returns rows ordered by ``sig_delta DESC`` so the most-boosted items
    surface first. Empty list when no items hit the threshold.

    Columns: ``id``, ``city_id``, ``title``, ``ai_sig``, ``final_sig``,
    ``sig_delta``, ``action_type``, ``triggers_fired``.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT
              ai.id,
              m.municipality_id                              AS city_id,
              ai.title,
              (ai.score_overrides->>'original_ai_significance')::int AS ai_sig,
              (ai.score_overrides->>'final_significance')::int       AS final_sig,
              (ai.score_overrides->>'final_significance')::int
                - (ai.score_overrides->>'original_ai_significance')::int
                                                              AS sig_delta,
              ai.extracted_facts->>'action_type'              AS action_type,
              ai.score_overrides->'triggers'                  AS triggers_fired
              FROM agenda_items ai
              JOIN meetings m ON m.id = ai.meeting_id
             WHERE ai.score_overrides IS NOT NULL
               AND ai.ai_generated_at > NOW() - INTERVAL '24 hours'
               AND ABS(
                   COALESCE((ai.score_overrides->>'final_significance')::int, 0)
                   - COALESCE(
                       (ai.score_overrides->>'original_ai_significance')::int, 0
                     )
               ) > 3
             ORDER BY sig_delta DESC
            """
        )
        return [dict(row) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Query B1 — Under-scoring Impact (significance boost % > 20%).
# ---------------------------------------------------------------------------


def query_b1_under_scoring_impact() -> list[dict[str, Any]]:
    """Categories where Stage 2.5 had to boost significance > 20% of the time.

    Window: last 7 days. Min sample size: 30 items per
    ``(action_type, prompt_version)``. Surfaces (action_type,
    prompt_version) tuples where the LLM is systematically scoring
    too low for that category.

    Per spec §3.5: the denominator (``total_items``) is **all completed
    items** in the (action_type, prompt_version) group within the
    7-day window — NOT just items where Stage 2.5 fired. ``pct_boosted``
    is therefore "of all completed items, what fraction had Stage 2.5
    raise their significance score?". The 20% threshold is calibrated
    to this denominator. Items without ``score_overrides`` populated
    (e.g. AI accepted the score as-is, no overrides written) contribute
    to ``total_items`` but never to ``items_with_sig_boost`` because the
    boost check uses ``->>'final_significance'`` which is NULL on those
    rows and the comparison ``NULL > NULL`` is NULL (excluded by
    ``COUNT(*) FILTER``).

    Columns: ``action_type``, ``prompt_version``, ``total_items``,
    ``items_with_sig_boost``, ``avg_boost_magnitude``, ``pct_boosted``.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            WITH category_stats AS (
              SELECT
                ai.extracted_facts->>'action_type'  AS action_type,
                ai.ai_rewrite_version               AS prompt_version,
                COUNT(*)                            AS total_items,
                COUNT(*) FILTER (
                  WHERE (ai.score_overrides->>'final_significance')::int
                        > (ai.score_overrides->>'original_ai_significance')::int
                )                                   AS items_with_sig_boost,
                AVG(CASE
                      WHEN (ai.score_overrides->>'final_significance')::int
                           > (ai.score_overrides->>'original_ai_significance')::int
                      THEN (ai.score_overrides->>'final_significance')::int
                           - (ai.score_overrides->>'original_ai_significance')::int
                    END)                            AS avg_boost_magnitude
                FROM agenda_items ai
               WHERE ai.processing_status = 'completed'
                 AND ai.ai_generated_at > NOW() - INTERVAL '7 days'
               GROUP BY action_type, prompt_version
            )
            SELECT
              action_type,
              prompt_version,
              total_items,
              items_with_sig_boost,
              avg_boost_magnitude,
              ROUND(
                100.0 * items_with_sig_boost / NULLIF(total_items, 0), 1
              )                                     AS pct_boosted
              FROM category_stats
             WHERE total_items >= 30
               AND items_with_sig_boost::float / total_items > 0.20
             ORDER BY pct_boosted DESC
            """
        )
        return [dict(row) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Query B2 — Over-scoring Consent (consent reduction % > 20%).
# ---------------------------------------------------------------------------


def query_b2_over_scoring_consent() -> list[dict[str, Any]]:
    """Categories where Stage 2.5 had to lower consent placement > 20% of the time.

    Symmetric to :func:`query_b1_under_scoring_impact` but pivoting on
    consent_placement: the ceiling fired when AI rated something as more
    consent-appropriate than it should be. Same 7-day window, same
    sample-size floor (30).

    Per spec §3.5: the denominator (``total_items``) is **all completed
    items** in the (action_type, prompt_version) group within the
    7-day window — NOT just items where Stage 2.5 fired. Items where
    AI's consent placement was accepted as-is contribute to
    ``total_items`` but not to ``items_with_consent_reduction``, since
    the reduction predicate evaluates to NULL on rows without
    ``score_overrides`` populated.

    Columns: ``action_type``, ``prompt_version``, ``total_items``,
    ``items_with_consent_reduction``, ``avg_reduction_magnitude``,
    ``pct_reduced``.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            WITH category_stats AS (
              SELECT
                ai.extracted_facts->>'action_type'  AS action_type,
                ai.ai_rewrite_version               AS prompt_version,
                COUNT(*)                            AS total_items,
                COUNT(*) FILTER (
                  WHERE (ai.score_overrides->>'final_consent')::int
                        < (ai.score_overrides->>'original_ai_consent')::int
                )                                   AS items_with_consent_reduction,
                AVG(CASE
                      WHEN (ai.score_overrides->>'final_consent')::int
                           < (ai.score_overrides->>'original_ai_consent')::int
                      THEN (ai.score_overrides->>'original_ai_consent')::int
                           - (ai.score_overrides->>'final_consent')::int
                    END)                            AS avg_reduction_magnitude
                FROM agenda_items ai
               WHERE ai.processing_status = 'completed'
                 AND ai.ai_generated_at > NOW() - INTERVAL '7 days'
               GROUP BY action_type, prompt_version
            )
            SELECT
              action_type,
              prompt_version,
              total_items,
              items_with_consent_reduction,
              avg_reduction_magnitude,
              ROUND(
                100.0 * items_with_consent_reduction / NULLIF(total_items, 0), 1
              )                                     AS pct_reduced
              FROM category_stats
             WHERE total_items >= 30
               AND items_with_consent_reduction::float / total_items > 0.20
             ORDER BY pct_reduced DESC
            """
        )
        return [dict(row) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Query C — Baseline drift (12-week trend per action_type).
# ---------------------------------------------------------------------------


def query_c_baseline_drift() -> list[dict[str, Any]]:
    """12-week per-(action_type, week) baseline trend.

    Returns one row per ``(action_type, week)`` with the week's average
    significance + consent placement scores and the volume. Min volume
    per week is 10 (avoids low-sample noise on rare action types).
    Includes week-over-week deltas so callers can render sparklines or
    flag drift directly.

    Rows are returned ordered by ``action_type, week DESC`` so a
    callable that groups in Python sees recent weeks first within each
    series.

    **Low-volume filter is applied INSIDE the CTE** (Option A from the
    G1 review) — weeks with ``n < 10`` are dropped from the time series
    entirely BEFORE the LAG window function runs. This means
    ``sig_delta_wow`` for a given visible row compares against the
    previous *visible high-volume* row, not against an invisible
    filtered-out week. Without this discipline, a low-volume week in
    the middle of a series would silently distort the drift signal:
    the surviving rows' LAG would point to a row that's then dropped
    from output, hiding the gap. Trade-off: rendered week ranges may
    not be contiguous (a low-volume week is visibly absent in the
    series), which is the correct behavior — we'd rather show "no row
    for that week" than a misleading delta.

    Columns: ``action_type``, ``week``, ``avg_sig``, ``avg_consent``,
    ``n``, ``sig_delta_wow``, ``volume_delta_wow``.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            WITH weekly_baselines AS (
              SELECT
                ai.extracted_facts->>'action_type'    AS action_type,
                DATE_TRUNC('week', ai.ai_generated_at)::date AS week,
                AVG(ai.significance_score)            AS avg_sig,
                AVG(ai.consent_placement_score)       AS avg_consent,
                COUNT(*)                              AS n
                FROM agenda_items ai
               WHERE ai.ai_generated_at > NOW() - INTERVAL '12 weeks'
                 AND ai.processing_status = 'completed'
                 AND ai.significance_score IS NOT NULL
               GROUP BY action_type, week
              HAVING COUNT(*) >= 10
            )
            SELECT
              action_type,
              week,
              avg_sig,
              avg_consent,
              n,
              avg_sig
                - LAG(avg_sig) OVER (
                    PARTITION BY action_type ORDER BY week
                  )                                   AS sig_delta_wow,
              n
                - LAG(n) OVER (
                    PARTITION BY action_type ORDER BY week
                  )                                   AS volume_delta_wow
              FROM weekly_baselines
             ORDER BY action_type, week DESC
            """
        )
        return [dict(row) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Badge volume calibration — 12-week (city, badge, week) trend with split.
# ---------------------------------------------------------------------------


def query_badge_volume_calibration() -> list[dict[str, Any]]:
    """Per (city, policy-badge, week) volume + deterministic/llm split.

    12-week window. Returns rows for every ``(city_id, badge_slug,
    week)`` group of policy-kind badges, with the count breakdowns and
    the two ratios that admins watch for prompt/matcher mismatch:
    ``pct_deterministic_only`` and ``pct_llm_only``. The spec's >40%
    callout (Section 5.7) is rendering-time logic — this query returns
    every row so the template can highlight outliers without round-
    tripping back for "drilldown" data.

    Columns: ``city_id``, ``badge_slug``, ``week``, ``n_items``,
    ``n_high_conf``, ``n_deterministic_only``, ``n_llm_only``,
    ``pct_deterministic_only``, ``pct_llm_only``.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT
              m.municipality_id                                  AS city_id,
              aib.badge_slug,
              DATE_TRUNC('week', aib.detected_at)::date          AS week,
              COUNT(*)                                           AS n_items,
              COUNT(*) FILTER (WHERE aib.confidence >= 1.0)      AS n_high_conf,
              COUNT(*) FILTER (WHERE aib.source = 'deterministic')
                                                                 AS n_deterministic_only,
              COUNT(*) FILTER (WHERE aib.source = 'llm')         AS n_llm_only,
              ROUND(
                100.0 * COUNT(*) FILTER (WHERE aib.source = 'deterministic')
                  / NULLIF(COUNT(*), 0),
                1
              )                                                  AS pct_deterministic_only,
              ROUND(
                100.0 * COUNT(*) FILTER (WHERE aib.source = 'llm')
                  / NULLIF(COUNT(*), 0),
                1
              )                                                  AS pct_llm_only
              FROM agenda_item_badges aib
              JOIN agenda_items ai ON ai.id = aib.agenda_item_id
              JOIN meetings m ON m.id = ai.meeting_id
             WHERE aib.kind = 'policy'
               AND aib.detected_at > NOW() - INTERVAL '12 weeks'
             GROUP BY m.municipality_id, aib.badge_slug, week
             ORDER BY m.municipality_id, aib.badge_slug, week DESC
            """
        )
        return [dict(row) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Top False Positives — admin removals >= 5 in 7 days.
# ---------------------------------------------------------------------------


def query_top_false_positives() -> list[dict[str, Any]]:
    """Policy badges admins removed >= 5 times in the last 7 days.

    Reads ``agenda_item_badges_audit`` (Migration 013, decision #65).
    Filters to ``action='removed'`` and ``actor_role='admin'`` so cron
    cleanups and on-write removals don't pollute the panel. Returns
    one row per ``(city_id, badge_slug)`` pair, with the distinct
    removal reasons aggregated for fast pattern recognition.

    Columns: ``city_id``, ``badge_slug``, ``n_removals``,
    ``reasons_cited`` (text[]).
    """
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT
              m.municipality_id           AS city_id,
              aiba.badge_slug,
              COUNT(*)                    AS n_removals,
              ARRAY_AGG(DISTINCT aiba.reason)
                FILTER (WHERE aiba.reason IS NOT NULL)
                                          AS reasons_cited
              FROM agenda_item_badges_audit aiba
              JOIN agenda_items ai ON ai.id = aiba.agenda_item_id
              JOIN meetings m ON m.id = ai.meeting_id
             WHERE aiba.action = 'removed'
               AND aiba.actor_role = 'admin'
               AND aiba.occurred_at > NOW() - INTERVAL '7 days'
             GROUP BY m.municipality_id, aiba.badge_slug
            HAVING COUNT(*) >= 5
             ORDER BY n_removals DESC
            """
        )
        return [dict(row) for row in cur.fetchall()]
