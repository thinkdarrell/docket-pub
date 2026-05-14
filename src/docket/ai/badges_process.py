"""Process badges — deterministic SQL queries that classify items by procedural shape.

Spec: docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md §4.4, §4.5.

Six SQL constants cover 7 distinct badges:
  1. hidden_on_consent     — consent item with low placement score + guard
  2. sole_source           — procurement_method = sole_source | no_bid
  3. legal_settlement      — action_type = settlement
  4+5. split_vote /        — 1+ or 2+ dissenters on a roll-call vote
       contested
  6. amends_prior_contract — contract_amendment that trigram-matches a prior award
  7. emergency_action      — emergency procurement / method / title keyword

Every INSERT is idempotent via ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING.
Every INSERT includes city_id = m.municipality_id (decision #92).
Every INSERT sets status='applied' explicitly (refactor #2 retro [MEDIUM #1]):
process badges are deterministic with no LLM-only path, so they always
land citizen-visible. The decision lane for the policy-badge path lives
in ``docket.ai.badges_policy.decide_status_and_confidence``.

Note on member_votes.position: the DB schema uses column `position` with values
'yea' | 'nay' | 'abstain' | 'absent'. The spec pseudocode used 'yes'/'no' names;
these queries use the real DB values.
"""
from __future__ import annotations
import re

# ---------------------------------------------------------------------------
# Badge 1: Hidden on consent
# ---------------------------------------------------------------------------

HIDDEN_ON_CONSENT_SQL = """
INSERT INTO agenda_item_badges
    (agenda_item_id, city_id, badge_slug, kind, confidence, source, status)
SELECT ai.id, m.municipality_id, 'hidden_on_consent', 'process', 1.0, 'deterministic', 'applied'
FROM agenda_items ai
JOIN meetings m ON m.id = ai.meeting_id
WHERE ai.is_consent = TRUE
  AND ai.consent_placement_score IS NOT NULL
  AND ai.consent_placement_score <= 3
  AND ai.processing_status = 'completed'
  AND (
    EXISTS (
      SELECT 1 FROM jsonb_array_elements(ai.score_overrides->'triggers') AS trig
      WHERE trig->>'field' = 'consent_placement'
    )
    OR ai.ai_confidence IN ('high', 'medium')
  )
ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING;
"""

# ---------------------------------------------------------------------------
# Badge 2: Sole-source / no-bid
# ---------------------------------------------------------------------------

SOLE_SOURCE_SQL = """
INSERT INTO agenda_item_badges
    (agenda_item_id, city_id, badge_slug, kind, confidence, source, status)
SELECT ai.id, m.municipality_id, 'sole_source', 'process', 1.0, 'deterministic', 'applied'
FROM agenda_items ai
JOIN meetings m ON m.id = ai.meeting_id
WHERE ai.extracted_facts->>'procurement_method' IN ('sole_source', 'no_bid')
  AND ai.processing_status = 'completed'
ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING;
"""

# ---------------------------------------------------------------------------
# Badge 3: Legal settlement
# ---------------------------------------------------------------------------

LEGAL_SETTLEMENT_SQL = """
INSERT INTO agenda_item_badges
    (agenda_item_id, city_id, badge_slug, kind, confidence, source, status)
SELECT ai.id, m.municipality_id, 'legal_settlement', 'process', 1.0, 'deterministic', 'applied'
FROM agenda_items ai
JOIN meetings m ON m.id = ai.meeting_id
WHERE ai.extracted_facts->>'action_type' = 'settlement'
  AND ai.processing_status = 'completed'
ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING;
"""

# ---------------------------------------------------------------------------
# Badges 4 + 5: Split vote and Contested (one CTE, two INSERTs)
#
# The CTE is redeclared for each INSERT because PostgreSQL scopes CTEs
# per-statement. Both INSERTs are executed together in one cur.execute() call.
#
# Note: member_votes.position uses 'yea'/'nay'/'abstain'/'absent'.
# Dissent = 'nay' or 'abstain'. Voting (counted) = 'yea', 'nay', 'abstain'.
# 'absent' is excluded — attendance issue, not contention.
# ---------------------------------------------------------------------------

SPLIT_VOTE_AND_CONTESTED_SQL = """
WITH dissent_counts AS (
  SELECT
    vai.agenda_item_id,
    ai.meeting_id,
    m.municipality_id AS city_id,
    COUNT(*) FILTER (WHERE mv.position IN ('nay', 'abstain')) AS n_dissent,
    COUNT(*) FILTER (WHERE mv.position IN ('yea', 'nay', 'abstain')) AS n_voting
  FROM vote_agenda_items vai
  JOIN votes v ON v.id = vai.vote_id
  JOIN member_votes mv ON mv.vote_id = v.id
  JOIN agenda_items ai ON ai.id = vai.agenda_item_id
  JOIN meetings m ON m.id = ai.meeting_id
  WHERE vai.is_active = TRUE
  GROUP BY vai.agenda_item_id, ai.meeting_id, m.municipality_id
)
INSERT INTO agenda_item_badges
    (agenda_item_id, city_id, badge_slug, kind, confidence, source, status)
SELECT agenda_item_id, city_id, 'split_vote', 'process', 1.0, 'deterministic', 'applied'
FROM dissent_counts
WHERE n_dissent >= 1
ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING;

WITH dissent_counts AS (
  SELECT
    vai.agenda_item_id,
    m.municipality_id AS city_id,
    COUNT(*) FILTER (WHERE mv.position IN ('nay', 'abstain')) AS n_dissent,
    COUNT(*) FILTER (WHERE mv.position IN ('yea', 'nay', 'abstain')) AS n_voting
  FROM vote_agenda_items vai
  JOIN votes v ON v.id = vai.vote_id
  JOIN member_votes mv ON mv.vote_id = v.id
  JOIN agenda_items ai ON ai.id = vai.agenda_item_id
  JOIN meetings m ON m.id = ai.meeting_id
  WHERE vai.is_active = TRUE
  GROUP BY vai.agenda_item_id, m.municipality_id
)
INSERT INTO agenda_item_badges
    (agenda_item_id, city_id, badge_slug, kind, confidence, source, status)
SELECT agenda_item_id, city_id, 'contested', 'process', 1.0, 'deterministic', 'applied'
FROM dissent_counts
WHERE n_dissent >= 2
  AND n_voting > 0
  AND (n_dissent::float / n_voting) > 0.20
ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING;
"""

# ---------------------------------------------------------------------------
# Badge 6: Amends prior contract (confidence 0.6 — trigram similarity, decision #89)
# ---------------------------------------------------------------------------

AMENDS_PRIOR_CONTRACT_SQL = """
WITH prior_contracts AS (
  SELECT
    ai.id AS prior_id,
    ai.meeting_id AS prior_meeting_id,
    ai.extracted_facts->>'counterparty' AS prior_counterparty,
    ai.dollars_amount AS prior_dollars,
    m.meeting_date AS prior_date,
    m.municipality_id AS prior_city
  FROM agenda_items ai
  JOIN meetings m ON m.id = ai.meeting_id
  WHERE ai.extracted_facts->>'action_type' = 'contract_award'
    AND ai.dollars_amount > 0
    AND TRIM(COALESCE(ai.extracted_facts->>'counterparty', '')) <> ''
)
INSERT INTO agenda_item_badges
    (agenda_item_id, city_id, badge_slug, kind, confidence, source, status)
SELECT DISTINCT ai.id, m.municipality_id, 'amends_prior_contract', 'process', 0.6, 'deterministic', 'applied'
FROM agenda_items ai
JOIN meetings m ON m.id = ai.meeting_id
JOIN prior_contracts pc
  ON similarity(
       LOWER(TRIM(pc.prior_counterparty)),
       LOWER(TRIM(ai.extracted_facts->>'counterparty'))
     ) >= 0.6
  AND pc.prior_city = m.municipality_id
  AND pc.prior_date < m.meeting_date
WHERE ai.extracted_facts->>'action_type' = 'contract_amendment'
  AND ai.processing_status = 'completed'
  AND TRIM(COALESCE(ai.extracted_facts->>'counterparty', '')) <> ''
  AND NOT (
    COALESCE(ai.title, '') || ' ' || COALESCE(ai.description, '')
  ) ~* '(recurring|monthly invoice|annual renewal|routine renewal|periodic billing)'
ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING;
"""

# ---------------------------------------------------------------------------
# Badge 7: Emergency action
# ---------------------------------------------------------------------------

EMERGENCY_ACTION_SQL = r"""
INSERT INTO agenda_item_badges
    (agenda_item_id, city_id, badge_slug, kind, confidence, source, status)
SELECT ai.id, m.municipality_id, 'emergency_action', 'process', 1.0, 'deterministic', 'applied'
FROM agenda_items ai
JOIN meetings m ON m.id = ai.meeting_id
WHERE (
    ai.extracted_facts->>'action_type' = 'emergency_procurement'
    OR ai.extracted_facts->>'procurement_method' = 'emergency'
    OR ai.title ~* '\m(emergency|exigent|expedited)'
  )
  AND ai.processing_status = 'completed'
ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING;
"""

# ---------------------------------------------------------------------------
# Ordered list for the batch runner (C2 cron task)
# ---------------------------------------------------------------------------

PROCESS_BADGE_QUERIES: list[str] = [
    HIDDEN_ON_CONSENT_SQL,
    SOLE_SOURCE_SQL,
    LEGAL_SETTLEMENT_SQL,
    SPLIT_VOTE_AND_CONTESTED_SQL,
    AMENDS_PRIOR_CONTRACT_SQL,
    EMERGENCY_ACTION_SQL,
]


# ---------------------------------------------------------------------------
# On-write helper — mirrors the SQL above for the 4 fast non-vote badges
# (decision #57: both paths must agree)
# ---------------------------------------------------------------------------

def compute_on_write_process_badges(
    item,
    facts,
    scores,
    ai_confidence,
) -> list[tuple[str, float]]:
    """Return list of (badge_slug, confidence) for the 4 fast on-write badges.

    Covers: hidden_on_consent, sole_source, legal_settlement, emergency_action.
    Does NOT cover split_vote / contested / amends_prior_contract — those require
    DB lookups (vote rows, prior contract history) and run only in the nightly
    batch via SPLIT_VOTE_AND_CONTESTED_SQL / AMENDS_PRIOR_CONTRACT_SQL.

    Mirrors the SQL exactly — both paths must agree (decision #57).

    Args:
        item: duck-typed object with .is_consent (bool) and .title (str | None)
        facts: StructuredFacts — .procurement_method, .action_type
        scores: ScoreOverrides — .final_consent (int|None), .triggers (list[dict])
        ai_confidence: 'high' | 'medium' | 'low' | None — Stage 2 confidence field
    """
    out: list[tuple[str, float]] = []

    # --- Hidden on consent ---------------------------------------------------
    # Fires when item is on consent, floor-adjusted consent score <= 3, AND
    # either (a) a consent_placement floor fired, OR (b) AI confidence is high/medium.
    if (
        item.is_consent
        and scores.final_consent is not None
        and scores.final_consent <= 3
    ):
        any_consent_floor_fired = any(
            t.get('field') == 'consent_placement' for t in scores.triggers
        )
        if ai_confidence in ('high', 'medium') or any_consent_floor_fired:
            out.append(('hidden_on_consent', 1.0))

    # --- Sole-source / no-bid -----------------------------------------------
    if facts.procurement_method in ('sole_source', 'no_bid'):
        out.append(('sole_source', 1.0))

    # --- Legal settlement ----------------------------------------------------
    if facts.action_type == 'settlement':
        out.append(('legal_settlement', 1.0))

    # --- Emergency action ----------------------------------------------------
    if (
        facts.action_type == 'emergency_procurement'
        or facts.procurement_method == 'emergency'
        or re.search(
            r'\b(emergency|exigent|expedited)\b',
            item.title or '',
            re.IGNORECASE,
        )
    ):
        out.append(('emergency_action', 1.0))

    return out
