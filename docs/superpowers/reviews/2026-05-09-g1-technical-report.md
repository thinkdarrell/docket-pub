# G1 — Calibration Dashboard: Comprehensive Technical Report

**Status:** Implementation landed; both parallel Opus reviews complete; awaiting Sonnet 4.6 second-look + final-auditor + consultant review against this document.

**Commit under review:** `0549963` on `feat/impact-first-phase-2-track-3`
**Worktree:** `~/docket-pub-pf2-track-3`
**HEAD before commit:** `d7661c0`
**Spec:** §3.5 revised (line 1272+) and §5.7 (line 2335+) of `docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md`
**Plan:** §G1 (line 2004+) of `docs/superpowers/plans/2026-05-06-impact-first-refactor-phase-2.md`

This report is intended to be **self-contained**: a downstream auditor or consultant agent should be able to form an independent opinion from this document alone, then verify specific concerns against source. All file paths are relative to the worktree root unless otherwise noted.

---

## 1. Executive Summary

G1 ships the `/admin/calibration` dashboard — six SQL queries surfacing AI prompt-tuning signal as panels:

| Panel | Query | Window | Purpose |
|---|---|---|---|
| A | Per-item divergence | 24h | Items where Stage 2.5 floors moved significance > 3 points |
| B1 | Under-scoring Impact | 7d | (action_type, prompt_version) categories where AI under-rated significance > 20% of the time |
| B2 | Over-scoring Consent | 7d | Symmetric to B1 — AI over-rated consent placement > 20% of the time |
| C | Baseline drift | 12 weeks | Per-action_type week-over-week mean significance + consent + volume |
| Badge volume | Calibration | 12 weeks | Per-(city, badge, week) deterministic-only / LLM-only ratios for policy badges |
| Top False Positives | Audit-log | 7d | Policy badges admins removed ≥ 5 times |

**Preliminary verdict (subject to Sonnet + auditor + consultant review):** Implementation is structurally sound — queries are parameterized, auth is correctly wired through the existing blueprint hook, tests exercise meaningful boundaries — but **3 REQUIRED findings** block a clean ship:

| # | Source | Finding | Severity |
|---|---|---|---|
| **R-Q1** | Opus #1 | B1 + B2 added an undocumented `score_overrides IS NOT NULL` predicate to the inner CTE that changes denominator semantics from spec | Real correctness gap; affects pct_boosted / pct_reduced math |
| **R-T1** | Opus #2 | `class="cal-panel"` referenced 6× in template, defined in zero stylesheets — panels stack with no visual separation | Visual regression on the populated state; empty-state fallback looks fine |
| **R-T2** | Opus #2 | Panel A's `triggers_fired` cell renders Python `repr()` of a JSONB list — `{{ row.triggers_fired }}` calls `__str__` on a Python list-of-dicts, not JSON | Admin sees `[{'kind': 'yellow_settlement', ...}]` Python repr in the cell, not JSON |

Plus **9 SUGGESTED** + **11 NICE-TO-HAVE** items across the two Opus rounds. Full inventory in §6 below.

This is the **12th protocol run** of Track 3.

---

## 2. Implementation Surface

Single commit, 4 files, +1397/-0:

| File | Change | Lines |
|---|---|---|
| `src/docket/services/calibration.py` | NEW | 369 |
| `src/docket/web/admin.py` | Modified — added route at `:218` | +37 |
| `src/docket/web/templates/admin/calibration.html` | NEW | 314 |
| `tests/integration/test_calibration.py` | NEW — 23 tests | 677 |

Test deltas:
- Unit: 838 → 838 (no new unit tests; G1 tests live in integration because they seed cross-table data)
- Integration: 190 → 213 (+23)
- Full suite green at `pytest tests/unit tests/integration`

### 2.1 The route (`admin.py:218–249`)

```python
@bp.route("/calibration")
def calibration():
    """Calibration dashboard — six panels surfacing AI prompt-tuning signal.

    Six panels, one per query in :mod:`docket.services.calibration`:
    1. Per-item divergence (24h, ABS sig delta > 3)
    2. Under-scoring Impact (7d, > 20% boosted)
    3. Over-scoring Consent (7d, > 20% reduced)
    4. Baseline drift (12-week per-action_type trend)
    5. Badge volume calibration (12-week per-policy-badge with
       deterministic_only / llm_only ratios)
    6. Top False Positives (admin removals >= 5 in 7d)

    No caching for v1 — admin traffic is low + login_required keeps
    random hits out + monitoring surfaces don't tolerate 5-min staleness.
    If perf becomes a concern, mirror the F5 _rss_cached lock pattern.
    """
    from docket.services import calibration as calibration_service

    return render_template(
        "admin/calibration.html",
        per_item_divergence=calibration_service.query_a_per_item_divergence(),
        under_scoring_impact=calibration_service.query_b1_under_scoring_impact(),
        over_scoring_consent=calibration_service.query_b2_over_scoring_consent(),
        baseline_drift=calibration_service.query_c_baseline_drift(),
        badge_volume=calibration_service.query_badge_volume_calibration(),
        top_false_positives=calibration_service.query_top_false_positives(),
    )
```

Auth: covered by the blueprint-level `before_request` hook at `admin.py:13–21` (per Opus #2 verification). The `auth.py:23–32` `@login_required` decorator exists but is NOT used here — the hook supersedes it. Same pattern as all other admin routes.

### 2.2 The template (`admin/calibration.html`)

Six `<section class="cal-panel" data-panel="...">` blocks. Each panel:
- `<h2>` heading + 1-line description
- Empty-state shared macro `{{ empty_state() }}` for "no rows" path
- Otherwise a `<table>` with `<thead>`/`<tbody>`, columns matching the query's return shape

Heading hierarchy: page `<h1>` ("Calibration dashboard") → 6× `<h2>` panel headings. Semantic for screen readers.

### 2.3 Test inventory (`test_calibration.py`)

23 integration tests:
- **Boundary tests** that meaningfully exercise SQL: `test_query_a_excludes_below_threshold` (delta=3 not surfaced; delta=4 surfaced), `test_query_b1_min_sample_size` (29 vs. 30), `test_query_b1_pct_threshold` (20% vs. 21%), `test_query_top_false_positives_threshold` (4 vs. 5)
- **Auth tests:** anonymous → 302 redirect with `next=` param; logged-in admin → 200
- **Render tests:** all 6 panels present in HTML; empty-state path on each
- **Symmetry tests:** B2 symmetric shape with B1 against opposite override

Per Opus #1: tests are NOT substring-thin — they actually exercise the SQL boundaries.

---

## 3. The Six Queries — Source Snippets

### 3.1 Query A — Per-item divergence

`calibration.py:62–98`. Returns rows where `ABS(final_significance - original_ai_significance) > 3` over the last 24 hours.

```sql
SELECT
  ai.id,
  m.municipality_id                              AS city_id,    -- aliased
  ai.title,
  (ai.score_overrides->>'original_ai_significance')::int AS ai_sig,
  (ai.score_overrides->>'final_significance')::int       AS final_sig,
  (ai.score_overrides->>'final_significance')::int
    - (ai.score_overrides->>'original_ai_significance')::int
                                                 AS sig_delta,
  ai.extracted_facts->>'action_type'             AS action_type,
  ai.score_overrides->'triggers'                 AS triggers_fired
FROM agenda_items ai
JOIN meetings m ON m.id = ai.meeting_id
WHERE ai.score_overrides IS NOT NULL
  AND ai.ai_generated_at > NOW() - INTERVAL '24 hours'   -- spec: ai.updated_at
  AND ABS(
      COALESCE((ai.score_overrides->>'final_significance')::int, 0)
      - COALESCE((ai.score_overrides->>'original_ai_significance')::int, 0)
  ) > 3
ORDER BY sig_delta DESC
```

Note `triggers_fired` returns `score_overrides->'triggers'` — a JSONB value. Critical for **R-T2** (see §6).

### 3.2 Query B1 — Under-scoring Impact

`calibration.py:106–156`. CTE-based:

```sql
WITH category_stats AS (
  SELECT
    ai.extracted_facts->>'action_type'  AS action_type,
    ai.ai_rewrite_version               AS prompt_version,
    COUNT(*)                            AS total_items,
    COUNT(*) FILTER (...)               AS items_with_sig_boost,
    AVG(CASE ...)                       AS avg_boost_magnitude
  FROM agenda_items ai
  WHERE ai.processing_status = 'completed'
    AND ai.ai_generated_at > NOW() - INTERVAL '7 days'
    AND ai.score_overrides IS NOT NULL    -- ⚠️ NOT IN SPEC; see R-Q1 below
  GROUP BY action_type, prompt_version
)
SELECT
  action_type, prompt_version, total_items, items_with_sig_boost,
  avg_boost_magnitude,
  ROUND(100.0 * items_with_sig_boost / NULLIF(total_items, 0), 1)
                                        AS pct_boosted
FROM category_stats
WHERE total_items >= 30
  AND items_with_sig_boost::float / total_items > 0.20
ORDER BY pct_boosted DESC
```

Spec equivalent (§3.5 line 1306+) does NOT have the `score_overrides IS NOT NULL` predicate inside the CTE. Implementer added it. **R-Q1** below explains why this changes denominator semantics.

### 3.3 Query B2 — Over-scoring Consent

`calibration.py:164–215`. Symmetric to B1 — same CTE shape, swap sig fields for consent fields, swap `>` for `<`. Same `score_overrides IS NOT NULL` predicate added (same R-Q1 issue applies).

### 3.4 Query C — Baseline drift

`calibration.py:223–274`. Note the LAG window function for week-over-week deltas:

```sql
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
)
SELECT
  action_type, week, avg_sig, avg_consent, n,
  avg_sig - LAG(avg_sig) OVER (PARTITION BY action_type ORDER BY week)
                                        AS sig_delta_wow,
  n - LAG(n) OVER (PARTITION BY action_type ORDER BY week)
                                        AS volume_delta_wow
FROM weekly_baselines
WHERE n >= 10                            -- ⚠️ filter applied AFTER LAG (see S-Q1)
ORDER BY action_type, week DESC
```

Per Opus #1: the `WHERE n >= 10` clause applies AFTER the LAG window function. So if week-3 has n=8 (filtered out), week-2's LAG points to week-3 conceptually (a week excluded from the output) — but since week-3 isn't in the output, the LAG value is computed against a row that's then dropped. **Window function semantics:** PostgreSQL evaluates LAG before WHERE. Result: a sig_delta_wow that compares to a hidden excluded week, then itself gets compared to the next visible week — produces hidden week-over-week gaps.

### 3.5 Badge volume calibration

`calibration.py:282–328`. Per-(city, badge_slug, week) over 12 weeks:

```sql
SELECT
  m.municipality_id                                  AS city_id,
  aib.badge_slug,
  DATE_TRUNC('week', aib.detected_at)::date          AS week,
  COUNT(*)                                           AS n_items,
  COUNT(*) FILTER (WHERE aib.confidence >= 1.0)      AS n_high_conf,
  COUNT(*) FILTER (WHERE aib.source = 'deterministic') AS n_deterministic_only,
  COUNT(*) FILTER (WHERE aib.source = 'llm')         AS n_llm_only,
  ROUND(100.0 * COUNT(*) FILTER (WHERE aib.source = 'deterministic')
        / NULLIF(COUNT(*), 0), 1)                    AS pct_deterministic_only,
  ROUND(100.0 * COUNT(*) FILTER (WHERE aib.source = 'llm')
        / NULLIF(COUNT(*), 0), 1)                    AS pct_llm_only
FROM agenda_item_badges aib
JOIN agenda_items ai ON ai.id = aib.agenda_item_id
JOIN meetings m ON m.id = ai.meeting_id
WHERE aib.kind = 'policy'
  AND aib.detected_at > NOW() - INTERVAL '12 weeks'
GROUP BY m.municipality_id, aib.badge_slug, week
ORDER BY m.municipality_id, aib.badge_slug, week DESC
```

Per Opus #1: `agenda_item_badges` has its own `city_id` column (Migration 013) — the JOIN to meetings is unnecessary for `city_id`. Perf nit, not correctness.

The spec's >40% threshold (§5.7) is rendering-time logic in the template — query returns every row.

### 3.6 Top False Positives

`calibration.py:336–369`. Joins `agenda_item_badges_audit` (Migration 013, decision #65):

```sql
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
```

Note: spec §5.7 line 80 says ">5" but the spec SQL says `>= 5`. Implementation matches the spec SQL (`>= 5`). Tests assert `>= 5` boundary at 4 vs. 5. Spec text/SQL contradiction documented; implementation follows the SQL.

---

## 4. Spec/Code Drift Inventory

The implementer made two adaptations from spec to actual schema. Both are documented in the calibration.py module docstring (lines 33–47).

### 4.1 `ai.updated_at` → `ai.ai_generated_at`

**Spec text:** §3.5 lines 1292, 1324, 1377 use `ai.updated_at` for the freshness window in Queries A, B1/B2, and C.

**Actual schema:** `agenda_items` does not have an `updated_at` column. Migration 001 added an `updated_at` trigger only to `meetings` and `municipalities`.

**Implementer's substitution:** `ai.ai_generated_at` — set by the AI worker on every successful Stage 2 / 2.5 run. Same moment `score_overrides` is written.

**Both Opus reviews accept this adaptation:**
- Opus #1: "defensible — same freshness semantics"
- Opus #2: out of scope, deferred to reviewer #1

**One subtlety auditor/consultant should weigh:** does `ai_generated_at` get re-set on prompt re-cascade? Per project memory ("bump ITEM_PROMPT_VERSION → re-process"), yes — the AI worker re-runs Stage 2 / 2.5 and updates `ai_generated_at`. Implication: the 24h window in Query A will catch re-cascaded items even if their `score_overrides` were originally written days ago. This is **probably correct** — the re-cascade re-evaluates the override — but worth confirming during the auditor stage.

### 4.2 `m.city_id` → `m.municipality_id` aliased as `city_id`

**Spec text:** §3.5 / §5.7 use `m.city_id` throughout.

**Actual schema:** `meetings.municipality_id` (per Migration 001).

**Implementer's substitution:** `m.municipality_id AS city_id` in every SELECT — preserves the spec's column name in the result rows so downstream consumers (templates, tests) read `row.city_id` per spec.

Opus #1: defensible. Opus #2: out of scope.

### 4.3 (Not strictly drift, but related) Query A `triggers` JSONB output

**Spec line 1288:** `ai.score_overrides->'triggers' AS triggers_fired`

The arrow operator `->` (not `->>`) returns a JSONB value, not a string. The implementation matches the spec exactly. The downstream rendering choice is what creates **R-T2**: the template directly interpolates this JSONB value, which Python sees as a `list` (or `dict`) and `__str__`s it.

Spec is silent on the rendering shape. Implementer chose raw `{{ row.triggers_fired }}`. Opus #2 caught the resulting Python repr.

---

## 5. F5-Pattern Compliance Check

Per `f5_done` memory, F5 established 5 forward-applicable patterns. G1's compliance:

| Pattern | G1 Status | Notes |
|---|---|---|
| Cache helpers must use `threading.Lock` + double-checked locking | **N/A** | G1 added no cache helpers. Implementer chose option (a): no caching for v1. Documented in route docstring. Defensible per Opus #2 — admin traffic is low. |
| UI copy at model layer via `enum.Enum` `.label` property | **N/A** | G1 is admin-only. No citizen-facing copy translation needed. Internal vocabulary (`action_type`, `prompt_version`, `triggers_fired`) is acceptable for admin readers. |
| City-fanout tests parametrize across all 4 deployed cities | **N/A** | G1 is admin-only. No city fanout. The dashboard aggregates across cities for B1/B2/C (per `(action_type, prompt_version)` not per-city) and emits city_id rows in A/Badge volume/Top FP. Multi-city assertions could be added if the auditor or consultant feels the surface needs it. |
| Defensive XML escaping (`cdata_safe`) | **N/A** | No XML output in G1. |
| xfail-strict tests are forcing functions, not bugs | **PRESERVED** | G1 left all 5 xfails alone — none target this surface. The `test_data_debt_returns_200_when_queue_page_lands` xfail will trip when **G2** lands (admin OCR queue at `/admin/data-debt/`), not G1. |

**Compliance summary:** All 5 F5 patterns are either correctly applied or correctly identified as not-applicable for an admin-only, no-XML, no-cache surface.

---

## 6. Findings Inventory

### 6.1 REQUIRED (3)

#### R-Q1 — Undocumented `score_overrides IS NOT NULL` in B1/B2 CTE
**Source:** Opus #1
**File:** `src/docket/services/calibration.py:138` (B1) and `:197` (B2)
**Spec reference:** §3.5 lines 1322–1325 (B1) and 1354–1357 (B2)

**Evidence:** Spec's B1/B2 CTE filters by `processing_status='completed'` and the time window only. The implementer added `AND ai.score_overrides IS NOT NULL` to the CTE WHERE clause. This means:

- **Spec semantics:** denominator (`total_items`) = all completed items in window. `pct_boosted` = (items where final > original AI score) / (all completed items in window). If 1000 items were processed and 50 had their significance boosted, `pct_boosted = 5%`.
- **Implementation semantics:** denominator = items where score_overrides is non-NULL. If only 100 of those 1000 items had score_overrides (the others had AI scores accepted as-is), `pct_boosted = 50/100 = 50%`.

The implementation's semantics may be **more useful operationally** (it answers "of items where Stage 2.5 fired, how often did we boost?"), but it's NOT what the spec specifies. The 20% threshold needs to be calibrated to whichever denominator the team picks; if the spec's threshold was tuned to "20% of all completed items," the implementation will surface alerts at much lower true volumes than intended.

**Fix options:**
1. **Remove the predicate** to match spec semantics — denominator becomes all completed items in window
2. **Keep the predicate, document the deviation** — denominator becomes "items where Stage 2.5 fired" — and note that the 20% threshold is recalibrated

Reviewer's recommendation (per Opus #1): pick one explicitly and document the choice in the docstring + spec patch.

#### R-T1 — `cal-panel` class has zero CSS rules
**Source:** Opus #2
**File:** `src/docket/web/templates/admin/calibration.html` lines 39, 82, 127, 173, 225, 272

**Evidence:** Grep across all 6 stylesheet files in `src/docket/web/static/` returns zero matches for `cal-panel`. The 6 panels render with no spacing, no borders, no background — they stack as plain `<section>` elements with default browser margin only.

This is the **direct parallel** of F5's R4 (data-debt BEM classes had zero CSS). Same pattern, same fix shape: add rules to `tweaks.css` + `mobile.css`. The empty-state path looks fine because the macro renders a centered styled message; the populated path looks broken.

**Fix:** Add CSS rules for `.cal-panel` (padding, border, spacing between panels). Likely 8–15 lines. Match the design tokens used by F2/F3/F4/F5 (`--accent-ink`, `--paper`, etc.).

#### R-T2 — `triggers_fired` renders as Python `repr()`, not JSON
**Source:** Opus #2
**File:** `src/docket/web/templates/admin/calibration.html:68`

**Evidence:** `score_overrides->'triggers'` (the JSONB `->` operator) returns a JSONB value. psycopg2's default JSONB adapter deserializes this to a Python `list` (or `dict`) — NOT a string.

`{{ row.triggers_fired }}` in Jinja calls `str(row.triggers_fired)`, which on a list invokes Python's `__repr__`. Result: cells render as:

```
[{'kind': 'yellow_settlement', 'magnitude': 2, 'reason': 'tier-floor'}]
```

(Single quotes, Python dict syntax) instead of valid JSON or human text.

This is worse than the implementer's "raw JSON" expectation. Three possible fixes:

1. **Render as JSON via a Jinja filter:** add `tojson` or a custom `|json` filter so the cell shows valid JSON
2. **Humanize via `floors.py:FloorTrigger.name` map:** translate trigger kinds to human strings — was the implementer's flagged follow-up
3. **Combine:** humanize the kind + show magnitudes — best admin readability

For v1, option 1 is cheapest and produces correct (if dense) output. Option 2 requires additional code. The choice here is a design call for the auditor / consultant.

### 6.2 SUGGESTED (9)

#### From Opus #1 (queries + service):
- **S-Q1: Query C LAG over filtered window.** The `WHERE n >= 10` filter applies AFTER the LAG window function. If a low-sample week is dropped, the surviving weeks' LAG points to the dropped week, hiding the gap. Fix: move `n >= 10` filter into the CTE before the window function runs.
- **S-Q2: Spec text/SQL contradiction on Top FP threshold.** §5.7 line 80 says ">5" but spec SQL says `>= 5`. Implementation matches SQL; tests match impl. Either patch the spec text to `>= 5`, or add a comment that the SQL is authoritative.
- **S-Q3: `agenda_item_badges` direct `city_id` column unused.** Badge volume query JOINs meetings to get city_id, but `aib.city_id` exists directly. Drop the JOIN for ~5% query speedup (perf nit, not correctness).

#### From Opus #2 (admin route + template + auth):
- **S-T1: 6 separate DB connections per page GET.** Each query opens its own `db_cursor()`. Acceptable for v1 admin traffic but worth noting. Could be batched into one connection with reused cursor.
- **S-T2: `data-panel` test hooks unstyled.** Used as test selectors only. Acceptable, but if a design pass adds CSS later, repurposing `data-panel` to `class` would be cleaner. (Implementer flagged.)
- **S-T3: No "last updated" timestamp on the dashboard.** With no caching, every page render is fresh — but the admin doesn't see when each query ran. Add a `<small>Generated at {{ now }}</small>` per panel for confidence.
- **S-T4: Empty-state copy may be too generic.** Shared macro outputs same text for every panel. Per-panel context (e.g., "No items in last 24h with score divergence > 3" for Panel A) would be more diagnostic.
- **S-T5: Tables don't right-align numeric columns.** Some columns use `t-tnum` class for tabular numerals but right-alignment isn't consistently applied; admin scanning is harder.
- **S-T6: No alert visual treatment on panels with results.** A populated `Top False Positives` panel looks identical to an empty one (style-wise). If a panel has rows, that's the alert signal — visually distinguish.

### 6.3 NICE-TO-HAVE (11)

Mostly polish — collapse helpers in calibration.py, module-level constants for thresholds (currently inline in SQL), more humanized panel descriptions, link from row to source agenda item, etc. Listed in the individual review files; deferred indefinitely unless auditor/consultant elevate.

---

## 7. Implementer's Open Questions and Reviewer Responses

### Q1 (Implementer to Reviewer #1): `ai_generated_at` vs `ai.updated_at`?

**Opus #1 response:** Defensible. Same freshness semantics. The 24h window catches recently-rerun Stage 2 / 2.5 items, including re-cascades. Spec `updated_at` was probably a placeholder for whatever timestamp marks the override write; `ai_generated_at` is exactly that.

### Q2 (Implementer to Reviewer #1): `m.city_id` aliasing?

**Opus #1 response:** Aliasing is correct. The downstream consumers read `row.city_id`; the alias preserves spec's interface. JOIN conditions still work because `JOIN meetings m ON m.id = ai.meeting_id` is unchanged.

### Q3 (Implementer to Reviewer #1): Query C flat vs grouped output?

**Opus #1 response:** Flat is correct for the spec; the template renders as a single table. If admin really wants per-action-type sparklines, the template can group in Jinja using `{% groupby %}`, or the service can return `dict[action_type, list[row]]`. Not blocker. (Note: this was the implementer's question; the LAG-after-filter issue is S-Q1, a separate concern.)

### Q4 (Implementer to Reviewer #2): Raw-JSON `triggers_fired` rendering?

**Opus #2 response:** Worse than raw JSON — it's Python `repr()`. See R-T2. Fix in v1.

### Q5 (Implementer to Reviewer #2): `data-panel` test hooks vs class?

**Opus #2 response:** S-T2 above — acceptable for v1; convert to class when a design pass lands.

### Q6 (Implementer to Reviewer #2): No caching for v1?

**Opus #2 response:** Acceptable. Documented choice. Mirror F5 `_rss_cached` pattern only when perf becomes a real concern.

---

## 8. Test Coverage Status

| Category | Tests | Notes |
|---|---|---|
| Auth gating | 2 | anonymous → 302 redirect with `next=` param; logged-in admin → 200 |
| Rendering | 3 | All 6 panels present; empty-state on each panel; heading hierarchy |
| Query A boundary | 2 | delta=3 not surfaced; delta=4 surfaced |
| Query B1 boundaries | 2 | sample size 29 vs 30; pct 20% vs 21% |
| Query B2 symmetry | 2 | mirror of B1 against opposite override |
| Query C 12-week window | 2 | weeks within window included; week 13 excluded |
| Top FP boundaries | 2 | 4 removals not surfaced; 5 surfaced; admin actor_role required |
| Empty data path | 6 | each query returns `[]` cleanly with no data; template renders empty state |
| Cross-table seeding | 2 | exercises `agenda_item_badges_audit` real path |
| **Total** | **23** | All passing. Per Opus #1 audit: **NOT** substring-thin — boundaries genuinely exercised. |

Test gap noted by Opus #1: no test exercises Query C's LAG-over-filtered-window behavior (S-Q1). If that's fixed, add a test covering the gap-week scenario.

---

## 9. Risk Assessment for Auditor / Consultant Review

**Production risk if shipped as-is:**

| Risk | Severity | Mitigation in fix-up |
|---|---|---|
| R-Q1 — B1/B2 thresholds may not align with spec intent; teams could chase false alerts or miss real ones | Medium-High | Document the chosen denominator semantics + verify the 20% threshold is calibrated to it |
| R-T1 — Visual regression; populated dashboard reads as broken | Low (admin only; no public exposure) | Add 8–15 lines of CSS |
| R-T2 — Admin sees Python repr of internal data structures | Low (admin readers can read it) but unprofessional | One filter swap (`tojson` or custom) |
| S-Q1 — Hidden week-over-week gaps in Query C | Medium (drift detection accuracy) | Move filter into CTE; add test |
| 6 separate DB connections per GET (S-T1) | Very Low (admin traffic) | Track for future optimization |
| No "last updated" timestamps (S-T3) | Very Low | Add per-panel timestamp |

**Architectural risk:**
None identified. G1 introduces no new caching, no model layer changes, no enum proliferation, no XML surfaces. The surface is small and bounded.

---

## 10. Cross-Review Correlation

Unlike F3 (where Opus #1 + Opus #2 converged on the same hit-area defect from different angles) or F4 (where the chain layered scope corrections), G1's two reviews found mostly independent issues with one notable convergence:

| Issue | Opus #1 | Opus #2 |
|---|---|---|
| Spec/code drift (`updated_at` → `ai_generated_at`) | Verified, defensible | Out of scope, deferred |
| `m.city_id` alias | Verified | Out of scope |
| `cal-panel` zero-CSS | Out of scope | **R-T1 caught** |
| `triggers_fired` Python repr | Out of scope | **R-T2 caught** |
| B1/B2 denominator drift | **R-Q1 caught** | Out of scope |
| Query C LAG-after-filter | **S-Q1 caught** | Out of scope |
| Auth gating mechanism (blueprint hook) | Out of scope | Verified |
| 6 panels + empty state | Out of scope | Verified |
| Tests boundary rigor | Verified for SQL boundaries | Verified for auth/render path |

Each angle caught what the other angle wasn't looking at. **No convergent finds** this round — meaning no single defect was independently detected from two angles. This is a coverage signal: each reviewer was deep in their lane.

---

## 11. Preliminary Fix-Up Scope (Subject to Sonnet + Auditor + Consultant)

Pending downstream review, the fix-up scope appears to be:

**REQUIRED (3):**
1. R-Q1 — Resolve B1/B2 denominator semantics: pick spec or current; document choice; recalibrate threshold if needed
2. R-T1 — Add CSS for `.cal-panel` (padding, separation, border) in `tweaks.css` + mobile rule
3. R-T2 — Render `triggers_fired` as JSON via `tojson` filter, OR humanize via `FloorTrigger.name` map

**SUGGESTED-accept (3):**
- S-Q1 — Move `n >= 10` filter into CTE, before LAG; add test
- S-T3 — Add per-panel "Generated at" timestamp
- S-T4 — Per-panel empty-state copy

**SUGGESTED-defer (6):**
- S-Q2 (spec text/SQL contradiction; document)
- S-Q3 (drop redundant meetings JOIN — perf only)
- S-T1 (6 DB connections per page — perf)
- S-T2 (`data-panel` → class — design pass)
- S-T5 (right-align numeric columns — polish)
- S-T6 (alert visual treatment — design pass)

**NICE-TO-HAVE (11):** declined unless elevated.

---

## 12. Appendix — File References

All source paths relative to `~/docket-pub-pf2-track-3`:

**Implementation:**
- `src/docket/services/calibration.py` — 369 lines, 6 query functions
- `src/docket/web/admin.py` — modified, route at line 218–249
- `src/docket/web/templates/admin/calibration.html` — 314 lines, 6 panels
- `tests/integration/test_calibration.py` — 677 lines, 23 tests

**Spec / Plan:**
- `docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md` §3.5 (line 1272+) and §5.7 (line 2335+)
- `docs/superpowers/plans/2026-05-06-impact-first-refactor-phase-2.md` §G1 (line 2004+)

**Reviews (untracked, F2/F3/F4/F5 convention):**
- `docs/superpowers/reviews/2026-05-09-g1-opus-review-1-queries-service.md`
- `docs/superpowers/reviews/2026-05-09-g1-opus-review-2-admin-template-auth.md`

**Memory:**
- `~/.claude-personal/projects/-Users-darrellnance/memory/project_pickup_2026_05_09_f5_done.md` (current session pickup)

**Existing patterns referenced:**
- F5 `_rss_cached` lock pattern at `src/docket/web/public.py:443`
- F5 `DataQuality` enum at `src/docket/models/data_quality.py`
- Existing admin auth hook at `src/docket/web/admin.py:13–21`
- `floors.py:FloorTrigger.name` map for triggers_fired humanization (R-T2 option 2)

---

## End of report

This report is intended for downstream Sonnet 4.6 second-look, final-auditor Opus 4.7, and any consultant agent the user dispatches. Each finding includes file paths, line numbers, and reasoning so the next stage can verify against source efficiently. **No fix-up has been performed yet.**
