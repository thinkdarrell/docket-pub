# SMART_BREVITY_UI Feature-Flag Flip Runbook

The `SMART_BREVITY_UI` env var on the `docket-web` Railway service gates v3
Smart Brevity Card rendering in `meeting_detail.html`. When unset or `false`,
citizens see the legacy v2 `notable-row` markup verbatim. When `true`, every
agenda item is dispatched through `partials/smart_brevity_card.html` and routed
to one of the seven v3 variants (`failed`, `degraded`, `procedural`,
`verification_pending`, `smart_brevity`, `v2_fallback`, `pending`) based on
Wave 0 / Phase 2 columns on `AgendaItem`.

This is a rendering-only flag — no migrations, no data writes. Flipping it
takes ~30 seconds (one Railway container restart). Rolling back is the same
operation in reverse.

> **Status: HISTORICAL — flag flipped in production on 2026-05-12.**
> `SMART_BREVITY_UI=true` is the live state on `docket-web`. This runbook
> is preserved as the audit record of the pre-flip checklist and as the
> rollback procedure if v3 rendering ever needs to be disabled. The
> pre-flip checklist (sections below) is no longer actionable — see the
> Rollback section for the operationally-relevant procedure.

## Pre-flip checklist

Run through this list before setting `SMART_BREVITY_UI=true` in Railway. Each
item exists because flipping the flag exposes a different surface — better to
verify than to discover post-flip.

1. **A8 deployed.** `AgendaItem.from_row()` must lift v3 columns
   (`processing_status`, `data_quality`, `ai_rewrite_version`,
   `headline`, `why_it_matters`, `extracted_facts`, plus the v3 sub-key
   lifts) so the dispatcher can read `item.<field>` directly.
   ```bash
   git log --oneline | grep "A8"
   ```
   Expect `ab48fa2` (A8 — expose v3 columns), `0cd1e02` (A8 follow-up —
   `next_steps` at top level), and `ff6cabb` (A8 review fix-up — lift v3
   sub-keys + version docstrings + badges stub).

2. **Wave 0 has run.** Without Wave 0, every item shows up as `pending`
   (no `processing_status`, no `data_quality`), which collapses the new
   UI to a single uninteresting variant.
   ```bash
   railway run --service docket-web psql "$DATABASE_URL" -c \
     "SELECT COUNT(*) FROM agenda_items WHERE processing_status IS NOT NULL"
   ```
   Expect ~57K. Live distribution as of 2026-05-07: 37,475 pending (65%),
   16,169 `data_quality_skipped` (28%), 3,909 `procedural_skipped` (7%).

3. **EXPLAIN ANALYZE verified at scale.** The Phase 2 query layer
   (`list_agenda_items()` in `services/query.py`) was tuned in commit
   `904c4a0` to keep the planner on `idx_agenda_items_meeting` and
   `idx_agenda_item_badges_item` even at 172K rows. Re-verify on a
   production replica before flipping (synth-scale procedure documented
   in `docs/superpowers/feedback/feedback_explain_at_scale.md`).
   - **DONE for current production scale** (post-Wave 0, ~57K rows).
   - **DONE for 172K-row simulation** (Phase 3 backfill projection).

4. **(Optional but recommended) Phase 3 backfill has reached meaningful
   coverage.** Without Phase 3, items with v2 `summary` set will fall to
   `card_v2_fallback` (visible-but-transitional), and items with no
   summary fall to `card_pending`. Citizens see real v3 cards
   (`card_smart_brevity`) only for items where `ai_rewrite_version=3`.
   Phase 3 plan: `docs/superpowers/plans/2026-05-06-impact-first-refactor-phase-3.md`.

## Flip procedure

1. Open the [Railway dashboard](https://railway.app) → `docket-web`
   service → **Variables** tab.
2. Add a new variable: `SMART_BREVITY_UI=true`.
3. Click **Save**. Railway restarts the container (~30 seconds).
4. **Verify:** visit any meeting detail page on `docket.pub`. The five
   Wave 0 categories should now be visually distinct:
   - Items with `data_quality != 'ok'` → `card_degraded` ("Source needs OCR" or similar).
   - Items with `processing_status='procedural_skipped'` → `card_procedural` (terse, no body).
   - Items with `processing_status='failed_permanent'` → `card_failed`.
   - Items with `processing_status='cross_stage_conflict'` → `card_verification_pending`.
   - Items with v2 `summary` set (no v3 yet) → `card_v2_fallback`
     (with the "⏳ summary updating" chip — see the next section).
   - Items with no v3 fields and no v2 summary → `card_pending`.
   - Once Phase 3 runs: items with `ai_rewrite_version=3` → `card_smart_brevity` (full v3 experience).

## Expected visual changes for v2-only items

Items that have a v2 `summary` set but have not yet been processed by
Phase 3 (so `ai_rewrite_version != 3`) render through `card_v2_fallback`
instead of the inline `notable-row` markup. They:

- Get wrapped in `<article class="smart-brevity-card smart-brevity-card--v2-fallback">`.
- Display a "⏳ summary updating" chip indicating Phase 3 hasn't completed for this item.
- Are intentional design — flagged in `partials/card_v2_fallback.html`'s
  header comment as a "transitional state, disappears once Migration 014
  drops the `summary` column."

**Operators flipping the flag should know this WILL change the visual
appearance of v2-only items**, even though the underlying data is
unchanged. If you flip the flag the day before Phase 3 reaches meaningful
coverage, expect MOST items to render as `card_v2_fallback`. That's
correct, not a bug — but it's a discontinuity worth communicating to
anyone watching the site.

## Rollback procedure

1. Railway dashboard → `docket-web` → **Variables**.
2. Either delete `SMART_BREVITY_UI` or set it to `false`.
3. Click **Save**. Railway restarts the container; v2 rendering returns
   immediately.
4. No data migration needed; the flag is rendering-only.

## What if it goes wrong

- **Pages timeout.** Check that `idx_agenda_items_meeting` and
  `idx_agenda_item_badges_item` are still in use on production. Re-run
  `EXPLAIN ANALYZE` on the same query the dashboard fired:
  ```sql
  EXPLAIN ANALYZE
  SELECT * FROM agenda_items WHERE meeting_id = $1 ORDER BY ... LIMIT 100;
  ```
  If the planner switched to `Seq Scan`, roll back the flag and
  investigate (Phase 3 row-count change can shift planner choice).

- **Pages crash with a `TemplateNotFound` or similar.** Probably a route
  stub firing in `engagement_strip.html` or `_facts_strip.html` for a
  URL that's not yet wired (E4 deferred). Roll back the flag immediately,
  then patch the partial.

- **Visual layout broken.** Probably a CSS class hook missing a rule.
  The `.sr-only` class is in `static/styles.css` (added in the E5 fix-up,
  commit `57ad1c5`). The `.dollars--*` and `.smart-brevity-card--*`
  classes are emitted by the partials but are deliberately unstyled —
  the design pass for v3 cards is deferred. The cards will look
  visible-but-default until that ships. That's expected, not broken.

- **One specific item renders as the wrong variant.** Check its row:
  ```sql
  SELECT id, processing_status, data_quality, ai_rewrite_version,
         headline, summary
    FROM agenda_items WHERE id = <id>;
  ```
  Compare against the dispatcher in `partials/smart_brevity_card.html`
  (the `{% if %}` chain). If the row's data implies a different variant
  than what's rendering, the bug is in the dispatcher; if the data is
  wrong for the variant it's routing to, the bug is upstream in Wave 0
  / Phase 2 / Phase 3.

## Related

- E6 commit (gate): `1f695b8`
- E6 review fix-up (this commit): tests + runbook + drift detection
- A8 commits (data layer): `ab48fa2`, `0cd1e02`, `ff6cabb`
- Wave 0: Phase 1, see `docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md` §0
- Phase 2 coordination: `docs/superpowers/plans/2026-05-06-impact-first-phase-2-coordination.md`
- Phase 3 plan: `docs/superpowers/plans/2026-05-06-impact-first-refactor-phase-3.md`
- Forcing tests: five `xfail-strict` tests in the suite will fire when
  their respective cleanups ship (data-debt queue, source-link stub
  deletion, etc.) — not blocking for the flag flip itself.
