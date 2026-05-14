# Refactor #2 retrospective — remediation status

**Source retro:** background-agent review of PRs #16–#21 (2026-05-12).
**Original plan:** `docs/superpowers/plans/2026-05-11-conservative-policy-badges.md`.
**Status as of:** 2026-05-14.

Refactor #2 ("conservative policy badges") shipped to prod on 2026-05-12 across PRs #16, #17, #18, #19, and #21. Because deploys outpaced reviews in the 23-second momentum-merge window, a follow-up retrospective audit was run against the merged code. Findings below.

---

## Risk register (ranked, with status)

| # | Severity | Finding | Status |
|---|---|---|---|
| 1 | **HIGH** | `list_agenda_items` leaked flagged badges + rendered withdrawn items as pending on `/al/<slug>/meetings/<id>` | **DONE — PR #23** (2026-05-12) |
| 2 | MEDIUM | Writer SSOT drift — 5 of 6 INSERT paths bypass `decide_status_and_confidence` | **OPEN** — next up |
| 3 | MEDIUM | `pipeline.finalize_from_rewrite` writes `status='flagged'` without audit row | **DONE — PR #35** (2026-05-14) |
| 4 | MEDIUM | Admin badge-review UPDATE has no concurrency guard (two admins both succeed) | **DONE — PR #36** (2026-05-14) |
| 5 | LOW | PR #20's two negative-guard tests duplicate PR #21's coverage | OPEN |
| 6 | LOW | `resolve_policy_badge_confidence` is dead code in production | OPEN |
| 7 | LOW | `list_badges_on_item` (admin manage UI) silently renders flagged/rejected | OPEN |
| 8 | LOW | PR #21 body's "no reader filters on withdrawn" claim is inaccurate | OPEN |
| 9 | LOW | Deploy-vs-review process bug — three downstream PRs merged within 23 seconds | OPEN (process note) |

---

## Confirmed clean (no action needed)

- `is_withdrawn_or_deferred()` runs before `is_procedural()` in both `wave0.py:run_wave_0` and `pipeline.py:process_item`.
- Migrations 021/022/023 are idempotent.
- Badge-reader gates correct in `query.py` for `list_items_by_badge`, `category_kpis`, `badge_volume_year`, `badge_volume_recent`, `mv_badge_volume_monthly`.
- Admin badge-review list correctly scoped to `status='flagged'`.
- PR #20 was fully reverted by PR #21 (net zero contribution to `wave0.py`).

---

## Out-of-band findings (surfaced during MEDIUM #2 verification)

### Migration 013 down-rollback is broken on `main`

`tests/integration/test_migration_013.py::test_013_up_down_up_cycle` fails because migration 026's `coverage_subject_links` FK references `priority_badge_templates` (a 013 table), but 013's `SQL_DOWN` doesn't `CASCADE` or drop the dependent constraint.

**Symptom in CI / local full-suite runs:** the test aborts mid-rollback, leaving the test DB schema half-down. Every downstream integration test then fails until the DB is reset. ~16 failures cascade from this one root cause.

**Fix:** update `src/docket/migrations/013_impact_first_refactor.py:SQL_DOWN` to either:
- (a) drop `coverage_subject_links_subject_slug_fkey` before dropping `priority_badge_templates`, or
- (b) use `DROP TABLE priority_badge_templates CASCADE`.

Worth its own small PR. Not blocking the retro remediation but explains why local full-suite runs look noisier than they should.

---

## What's still in the queue (sized rough)

| Item | Size | Risk |
|---|---|---|
| MEDIUM #1 — writer SSOT drift (5 INSERT sites) | ~45–60 min | low, mechanical |
| Migration 013 down-rollback fix | ~15–30 min | low, SQL only |
| LOWs ×5 | ~10–20 min each | very low |
| Refactor #2 followup #2 — consent text recovery | own session | needs brainstorm |
| Withdrawn-shape regex variants (a/b/c/d) | ~20 min × 4 | low |
| Issue #33 — AI cost telemetry broken | unscoped | dig first |
| Issue #34 — BHM 5/12 procedural misclass | unscoped | dig first |

**~3–4 focused hours to clear all MEDIUMs + LOWs + migration rot.** Followup #2 and the open issues need investigation before sizing.

---

## Open questions for reviewer

1. **LOW #6 — `resolve_policy_badge_confidence`**: prefer outright delete or a `warnings.warn` deprecation shim? It's tests-only today; nothing in production references it.
2. **LOW #9 — deploy-vs-review process bug**: is this worth codifying as a CI gate (e.g. block deploy from a branch whose PR has no approval), or is the new "one PR at a time, no momentum merges" understanding enough?
3. **Migration 013 rot**: should the fix include adding a `pytest` autouse fixture that resets the schema between integration files so future down-migration bugs don't cascade silently? (Slower CI, but isolates blast radius.)

---

## Shipped PRs

- **#23** (2026-05-12) — `fix(query): hide flagged badges + withdrawn items from citizen meeting-detail` → closes HIGH.
- **#35** (2026-05-14) — `fix(ai/pipeline): write audit row when policy badge lands flagged` → closes MEDIUM #2.
- **#36** (2026-05-14) — `fix(admin/badge-review): concurrency guard on approve/reject` → closes MEDIUM #3.
