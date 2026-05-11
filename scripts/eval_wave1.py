"""Pull the Wave 1 evaluation dataset for refactor planning.

Surfaces:
  - The 51 cross_stage_conflict items (Stage 1 vs Stage 2 disagreement
    + the score_overrides JSONB that records what conflicted).
  - The 97 failed_permanent items (last_error_message hints at the
    Pydantic violation pattern).
  - Badge density on the 609 completed v3 items — distribution of how
    many badges per item (the over-tagging signal).
  - Distribution of confidence levels.
  - Distribution of significance / consent_placement score floor triggers.

Run with no args: ``venv/bin/python scripts/eval_wave1.py``
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter

import psycopg2


def _resolve_db_url() -> str:
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return env_url
    out = subprocess.check_output(
        ["railway", "variables", "--service", "docket-web", "--kv"],
        text=True,
    )
    for line in out.splitlines():
        if line.startswith("DATABASE_PUBLIC_URL="):
            return line.split("=", 1)[1]
    sys.exit("DATABASE_URL not resolvable")


def main() -> int:
    cur = psycopg2.connect(_resolve_db_url()).cursor()

    # --- 1. cross_stage_conflict ---
    print("=" * 70)
    print("CROSS_STAGE_CONFLICT ITEMS")
    print("=" * 70)
    cur.execute(
        """
        SELECT ai.id, ai.title, ai.score_overrides->'conflicts' AS conflicts,
               ai.extracted_facts->>'action_type' AS action_type,
               ai.headline, ai.ai_confidence
          FROM agenda_items ai
         WHERE ai.processing_status = 'cross_stage_conflict'
           AND ai.ai_rewrite_version = 3
         ORDER BY ai.id
        """
    )
    conflicts = cur.fetchall()
    print(f"total: {len(conflicts)}\n")
    conflict_types: Counter = Counter()
    action_type_counts: Counter = Counter()
    def _kinds(conflicts_json):
        """conflicts is a list of string ids per reconcile.py."""
        if not conflicts_json:
            return []
        return list(conflicts_json)

    for c_id, title, conflicts_json, action_type, headline, confidence in conflicts[:15]:
        kinds = _kinds(conflicts_json)
        print(f"  id={c_id} action_type={action_type!r} confidence={confidence!r}")
        print(f"    title:    {(title or '')[:90]}")
        print(f"    headline: {headline!r}")
        print(f"    conflicts: {kinds}")
    # Aggregate over ALL conflicts (not just printed 15)
    for c_id, title, conflicts_json, action_type, headline, confidence in conflicts:
        for k in _kinds(conflicts_json):
            conflict_types[k] += 1
        action_type_counts[action_type or "(none)"] += 1
    print(f"\n  conflict-type distribution (all {len(conflicts)}):")
    for kind, n in conflict_types.most_common():
        print(f"    {kind:40s} {n}")
    print(f"\n  action_type distribution (all {len(conflicts)}):")
    for at, n in action_type_counts.most_common():
        print(f"    {at:40s} {n}")

    # --- 2. failed_permanent ---
    print()
    print("=" * 70)
    print("FAILED_PERMANENT ITEMS (last 20 with error messages)")
    print("=" * 70)
    cur.execute(
        """
        SELECT id, title, last_error_message
          FROM agenda_items
         WHERE processing_status = 'failed_permanent'
           AND last_error_message IS NOT NULL
         ORDER BY id DESC
         LIMIT 20
        """
    )
    failed = cur.fetchall()
    error_patterns: Counter = Counter()
    for f_id, title, err in failed:
        # Extract the Pydantic error type or first line
        first_line = (err or "").split("\n")[0][:120]
        # Pattern-match common shapes
        if "string_too_long" in (err or ""):
            error_patterns["string_too_long"] += 1
        elif "literal_error" in (err or ""):
            error_patterns["literal_error (enum mismatch)"] += 1
        elif "procedural_consistency" in (err or "") or "must have a headline" in (err or "") or "must have a non-empty" in (err or ""):
            error_patterns["procedural_consistency (Stage 2 logic)"] += 1
        elif "missing" in (err or "").lower():
            error_patterns["missing required field"] += 1
        else:
            error_patterns["other"] += 1
        print(f"  id={f_id} title={(title or '')[:60]!r}")
        print(f"    err: {first_line}")
    # Run pattern aggregation across ALL failed_permanent, not just printed 20
    cur.execute(
        "SELECT last_error_message FROM agenda_items WHERE processing_status = 'failed_permanent' AND last_error_message IS NOT NULL"
    )
    error_patterns = Counter()
    for (err,) in cur.fetchall():
        if "string_too_long" in (err or ""):
            error_patterns["string_too_long"] += 1
        elif "literal_error" in (err or ""):
            error_patterns["literal_error (enum mismatch)"] += 1
        elif "must have a headline" in (err or "") or "must have a non-empty" in (err or ""):
            error_patterns["procedural_consistency (Stage 2 logic)"] += 1
        elif "missing" in (err or "").lower():
            error_patterns["missing required field"] += 1
        else:
            error_patterns["other"] += 1
    print(f"\n  failed_permanent error-pattern distribution (all):")
    for kind, n in error_patterns.most_common():
        print(f"    {kind:40s} {n}")

    # --- 3. Badge density across completed items ---
    print()
    print("=" * 70)
    print("BADGE DENSITY (completed v3 items)")
    print("=" * 70)
    cur.execute(
        """
        SELECT badge_count, COUNT(*) AS items_with_n_badges
          FROM (
            SELECT ai.id, COUNT(b.badge_slug) AS badge_count
              FROM agenda_items ai
              LEFT JOIN agenda_item_badges b ON b.agenda_item_id = ai.id
             WHERE ai.processing_status = 'completed' AND ai.ai_rewrite_version = 3
             GROUP BY ai.id
          ) t
         GROUP BY badge_count
         ORDER BY badge_count
        """
    )
    print("  badge_count → number of items")
    for badges, items in cur.fetchall():
        bar = "█" * min(items // 5, 80)
        print(f"    {badges} badges: {items:4d} items  {bar}")

    # Top badge slugs
    cur.execute(
        """
        SELECT badge_slug, kind, COUNT(*) AS n
          FROM agenda_item_badges
         WHERE agenda_item_id IN (
            SELECT id FROM agenda_items
             WHERE processing_status = 'completed' AND ai_rewrite_version = 3
         )
         GROUP BY badge_slug, kind
         ORDER BY n DESC
        """
    )
    print("\n  top badges (across completed v3 items):")
    for slug, kind, n in cur.fetchall():
        print(f"    {slug:40s} {kind:8s} {n}")

    # --- 4. AI confidence distribution ---
    print()
    print("=" * 70)
    print("AI CONFIDENCE DISTRIBUTION (completed v3 items)")
    print("=" * 70)
    cur.execute(
        """
        SELECT ai_confidence, COUNT(*) AS n
          FROM agenda_items
         WHERE processing_status = 'completed' AND ai_rewrite_version = 3
         GROUP BY ai_confidence
         ORDER BY ai_confidence
        """
    )
    for conf, n in cur.fetchall():
        print(f"    {conf or '(none)':10s} {n}")

    # --- 5. Significance score distribution ---
    print()
    print("=" * 70)
    print("SIGNIFICANCE SCORE DISTRIBUTION (completed v3 items)")
    print("=" * 70)
    cur.execute(
        """
        SELECT
          CASE
            WHEN significance_score IS NULL THEN '(null)'
            WHEN significance_score < 2 THEN '0-1'
            WHEN significance_score < 4 THEN '2-3'
            WHEN significance_score < 6 THEN '4-5'
            WHEN significance_score < 8 THEN '6-7'
            ELSE '8-10'
          END AS bucket,
          COUNT(*) AS n
          FROM agenda_items
         WHERE processing_status = 'completed' AND ai_rewrite_version = 3
         GROUP BY bucket
         ORDER BY bucket
        """
    )
    for bucket, n in cur.fetchall():
        bar = "█" * min(n // 5, 80)
        print(f"    sig {bucket:8s} {n:4d} items  {bar}")

    # --- 6. Floor trigger frequency (Stage 2.5) ---
    print()
    print("=" * 70)
    print("STAGE 2.5 FLOOR-TRIGGER FREQUENCY")
    print("=" * 70)
    cur.execute(
        """
        SELECT t->>'trigger' AS trigger, t->>'field' AS field, COUNT(*) AS n
          FROM agenda_items ai,
               jsonb_array_elements(ai.score_overrides->'triggers') t
         WHERE ai.processing_status IN ('completed','cross_stage_conflict')
           AND ai.ai_rewrite_version = 3
         GROUP BY trigger, field
         ORDER BY n DESC
        """
    )
    for trig, field, n in cur.fetchall():
        print(f"    {trig:40s} ({field:18s}) {n}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
