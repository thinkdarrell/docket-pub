# A8 Parallel Review Packet

**For:** lead-engineer review running concurrently with the Opus + Sonnet 4.6 model reviews.
**Branch:** `feat/impact-first-phase-2-track-3` @ `0cd1e02` (15 commits ahead of `b4b9a88`)
**Model reviews:** dispatched in background; results land in chat when complete.

## TL;DR

A8 is the cross-track data-layer task that unblocks v3 card rendering. Two commits:

```
0cd1e02 fix(query): A8 follow-up — expose next_steps at top level for engagement_strip
ab48fa2 feat(query): A8 — expose v3 columns on AgendaItem + list_agenda_items
```

**Test counts:** 775 passed + 4 xfailed (vs 753 + 4 baseline → +22 new tests).
**EXPLAIN ANALYZE:** 0.18ms with index path on a 100-item meeting (target: <50ms).
**xfail-strict tests:** all 4 stayed xfail. None flipped to XPASS.

## What this unlocks

Before A8, `AgendaItem.from_row()` didn't map v3 columns. Jinja's `Undefined` made every dispatcher gate condition falsy → all items routed to `card_v2_fallback` or `card_pending`. **A8 makes v3 cards reachable in the dispatcher for the first time.** The cards still need `SMART_BREVITY_UI=true` (E6) to actually flip on for citizens, but the data path is now open.

## Three brief corrections (implementer caught my bugs)

I made three errors in the A8 brief; the implementer caught all three by reading migration 013:

1. **`ai_confidence`** is a top-level TEXT column with `CHECK ('high'|'medium'|'low')`, not a float extracted from `ai_metadata->>'confidence'`. Corrected to `str | None` from the column directly.
2. **`data_debt_priority`** enum values are `'low'|'normal'|'high'`, not `'low'|'medium'|'high'`. Tests use the correct enum.
3. **`ai_extraction_version`** sibling field added (I listed only `ai_rewrite_version`). Both stages need version tracking — Stage 1 extraction and Stage 2 rewrite versions are independent.

All three corrections are objectively right per migration 013. No judgment call needed.

## One fix-up commit (`0cd1e02`)

The implementer surfaced a real bug: `next_steps` lives inside `extracted_facts.next_steps` (sub-key), but `partials/engagement_strip.html` reads `item.next_steps` (top-level). Without the fix-up, v3 cards would render WITHOUT engagement strips when E6 flips — half of E3's value silently lost.

Fix: added top-level `next_steps: dict | None` field on `AgendaItem`, populated in `from_row()` from `extracted_facts.get("next_steps")` (with `isinstance(extracted_facts, dict)` guard). Mirrors the `headline`/`why_it_matters` top-level pattern. Engagement strip continues to read `item.next_steps` unchanged. Integration test `test_engagement_strip_renders_with_next_steps_populated` locks the bug fix.

## Files to review (priority order)

If reviewing top-down:

1. **`src/docket/models/agenda.py`** — extended dataclass. Look at the new fields, `from_row()` lifting logic, and the `next_steps` defensive guard.
2. **`src/docket/services/query.py`** — find `list_agenda_items()`. Look at the SELECT shape, the lean `extracted_facts` projection, and the badges JOIN.
3. **`src/docket/migrations/013_impact_first_refactor.py`** — source of truth for column names + types.
4. **`tests/unit/test_list_agenda_items.py`** — 22 tests. Look at distribution: NULL handling, Wave 0 routing, v2 fallback, lean shape, `next_steps` lift, defensive matrix.
5. **`src/docket/web/templates/partials/smart_brevity_card.html`** — the dispatcher. Verify all gate fields are now exposed.
6. **`src/docket/web/templates/partials/engagement_strip.html`** — verify it reads `item.next_steps` (top-level) and the fix-up makes it work.
7. **The diffs:** `git show ab48fa2` and `git show 0cd1e02`.

## Verification checklist (same questions the AI reviewers will answer)

### Spec-compliance

- [ ] **All 11 v3 columns from migration 013 exposed.** Cross-check against the migration's `ALTER TABLE ADD COLUMN` statements. Any missed?
- [ ] **Lean `extracted_facts` shape matches what cards render.** Read `_facts_strip.html`; verify the SELECT pulls every key the partial accesses.
- [ ] **`next_steps` lift handles edge cases.** `extracted_facts=None`, `extracted_facts={}` (no `next_steps` key), `extracted_facts="malformed string"` (non-dict from JSONB) → all should produce `next_steps=None` without crashing.
- [ ] **NULL items don't crash the render path.** Item with all v3 fields None → dispatcher falls through to `card_v2_fallback` or `card_pending`.
- [ ] **v2 callsites unaffected.** `search.html`, `topic_detail.html`, `city.html`, `card_v2_fallback.html` only access v2 fields. They keep working.
- [ ] **Dispatcher gate conditions all backed by dataclass fields.** `processing_status`, `data_quality`, `ai_rewrite_version`, `summary` — all present. Anything missing breaks the gate.

### Code quality

- [ ] **`jsonb_extract_path` vs `->`/`->>` operator choice** is consistent and correct (TEXT vs JSONB return types).
- [ ] **NULL JSONB inputs don't blow up `jsonb_build_object`.** `NULL->'key'` returns NULL safely.
- [ ] **Index usage.** EXPLAIN ANALYZE used `idx_agenda_items_meeting`. No function calls on `meeting_id` that would block index use.
- [ ] **Per-row payload bytes.** Lean shape vs full JSONB — verify the worst-case at Railway scale (100+ items × 6-10 lean fields × ~200 bytes each = ~150 KB) is acceptable.
- [ ] **`from_row()` defensive contract preserved.** All new fields use `row.get(...)`, no `row[...]` (KeyError risk).
- [ ] **Test isolation.** Each test sets up its own data; no shared state leak.

### Architecture (the things models catch less reliably)

- [ ] **Lean shape is lean enough.** Does `extracted_facts` lean dict include everything the partials need without dragging in the full blob? Future-proof against partial changes that need new keys?
- [ ] **`next_steps` as top-level field is consistent.** Other v3 sub-keys (e.g. `cost`, `dates`, `locations`) inside `extracted_facts` are still accessed nested. Why is `next_steps` special? The answer is "the partial reads it that way" — but is that the right long-term shape, or should ALL the v3 sub-keys be lifted to top-level for consistency?
- [ ] **`AgendaItem` dataclass is getting long.** Currently 17 v2 + 11 v3 = 28 fields. At what point do we split into `AgendaItemList` / `AgendaItemDetail` shapes? Worth flagging now vs. waiting for the detail-page query?
- [ ] **Naming consistency.** `ai_rewrite_version` vs `ai_extraction_version` vs `ai_prompt_version` — three version fields tracking different stages. Are the names distinct enough to not confuse future implementers?
- [ ] **Migration trail.** Migration 013 added these columns. A8 exposes them. The dataclass docs / `from_row()` comments should reference migration 013 so future readers can trace the schema source.

### Production-path verification (only humans catch these well)

- [ ] **What does a Birmingham agenda item look like when rendered through the new dispatcher?** Mentally trace one of the Wave 0 `procedural_skipped` items (3,909 such items in production). Should route to `card_procedural`. Was that even reachable before A8? Will it render correctly now?
- [ ] **What about a `data_quality_skipped` item?** (16,169 in production.) Should route to `card_degraded`. Verify the card has fields it needs.
- [ ] **What about the 37,475 LLM-eligible items?** None have `ai_rewrite_version=3` yet (Phase 3 backfill hasn't run). They'll route to `card_v2_fallback` if `summary` is set, else `card_pending`. Either path needs to be intact.
- [ ] **EXPLAIN ANALYZE was on local PG (108 rows total).** Default planner picked seq scan because the table is small; index-forced path was 0.18ms. At Railway scale (~57K items), the planner SHOULD pick the index path automatically — but worth verifying with a Railway-side EXPLAIN before merging if you want certainty.

## Things you might push back on

A few decisions worth surfacing for discussion:

1. **The decision to split A8 from the v2-other-pages refactor.** A8 only updates `list_agenda_items()`. Search, topic detail, city overview pages keep rendering v2 cards forever (until separate F-track tasks). Is that the right boundary? Or should A8 land all listing queries together?
2. **The lean-list approach vs. the full-JSONB approach.** We chose lean. The team validated this. But lean means the detail page needs a separate query, and partials need to be careful about which they assume. Is the indirection worth the byte savings, or is "always full JSONB" simpler?
3. **`next_steps` top-level vs. nested.** The fix-up lifted it for partial compatibility. But arguably the "right" answer is to also lift `cost`, `dates`, `locations`, `names` so all v3 sub-keys are top-level fields. That would be a 4-line dataclass change + 4 SELECT projections. Worth doing now while we're touching the dataclass, or wait?

## How to compare your verdict with the model reviews

When the parallel reviews finish (Spec-compliance + Code-quality, both Opus, both running in background), I'll surface their findings. Your verdict and theirs should:
- **Agree on REQUIRED items** if any. Disagreement here means one party missed something — investigate before proceeding.
- **Disagree somewhat on SUGGESTED items.** Models tend to be more cautious; humans tend to weigh future-rot vs. present-cost differently. Check if your SUGGESTED list overlaps theirs.
- **Disagree most on architectural feel** (lean shape adequacy, dataclass length, naming consistency). Models are weaker here. Trust your judgment.

After both reviews land, the Sonnet 4.6 second-look gets dispatched with both prior reviews + adversarial framing. That's where bugs the Opus reviews missed surface (E5 caught the ARIA `<span>` issue this way; A8 may surface dispatcher edge cases the Opus reviewers don't think to check).

## Sign-off ask after reviews

Same shape as E5:

1. **Approve A8 + fix-up to merge** (or pick fix-up scope from review findings).
2. **Acknowledge the lean shape decision is locked in.** Detail-page query in a future task gets the full JSONB; A8 stays lean.

When you're ready, drop a verdict and I'll either dispatch the Sonnet second-look (if reviews show clean ship) or run a fix-up loop (if anything REQUIRED surfaces).

## Quick references

- **Track 3 progress overview:** 5 of 15 E-tasks done + A8 (cross-track). E6 next, then F1-F5, G1-G4.
- **A8 unblocks:** v3 dispatcher routing in code. Doesn't unblock production rendering — that needs E6's `SMART_BREVITY_UI=true` flag flip.
- **What A8 doesn't do:** detail-page query, F-track listing query updates, Stage 0c content-hash dedup, deferred E4/E5 forcing-test cleanups.
- **EXPLAIN ANALYZE re-verify at Railway scale:** recommended before merging if certainty matters; the local result is a good signal but not a guarantee.
