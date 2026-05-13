# Track 3 — Comprehensive Status (2026-05-08)

**Branch:** `feat/impact-first-phase-2-track-3` @ `63c49b1` (17 commits ahead of `b4b9a88`, local-only)
**Worktree:** `~/docket-pub-pf2-track-3`
**Tests:** 781 passed + 5 xfailed across the full unit suite
**Track 3 progress:** 5 of 15 E/F/G tasks done + A8 (cross-track) + cleanup. 9 remaining.

---

## 1. At a glance

Track 3 of the Phase 2 Impact-First Refactor builds the v3 Smart Brevity Card UI. It ships behind a feature flag (`SMART_BREVITY_UI`) and renders v3 cards only when the AgendaItem dataclass exposes v3 columns (the A8 task). All five UI tasks complete (E1–E5), plus the cross-track data-layer task (A8) and a follow-on cleanup commit. Every task went through a 3-pass review pipeline: parallel Opus (spec-compliance + code-quality, read-only) → Sonnet 4.6 second-look (adversarial) → user review (lead engineer). Five `xfail-strict` forcing-function tests gate the deferred cleanup items so they can't silently rot.

**Three things still gate citizens seeing v3:**

1. **E6** — feature-flag gate (next task, ~30 min). Lands the gate; doesn't flip it.
2. **Phase 3 backfill** — ~$100 / 7–14 days for ~37K LLM-eligible items via Anthropic Batches API. Not built yet.
3. **Railway EXPLAIN ANALYZE** at production scale (~57K rows) — hard prerequisite for the `SMART_BREVITY_UI=true` flip to verify the planner picks `idx_agenda_items_meeting`.

---

## 2. Recent — EXHAUSTIVE (E5, A8, cleanup)

### 2.1 E5 — Dollar Tier with WCAG Markup

**Plan:** §E5 lines 1788–1804. **Spec:** §6.1, decisions #71 (color symbols) + #75 (ARIA labels).

**Two commits:**
- `10f52c9` — `feat(web): WCAG-2.1-compliant dollar tier with symbols + sr-only labels`
- `57ad1c5` — `fix(web): E5 review fix-up — role="img" for ARIA validity, .sr-only CSS, README + caching`

**Functional outcome.** Every `dollars_amount` rendered via the v3 facts strip carries triple-redundant tier signal:

- **Color** — CSS class `dollars--green | --yellow | --orange | --red`
- **Symbol** — visible text `$ | $$ | $$$ | $$$$` (decision #71)
- **Screen-reader label** — both `<span class="sr-only">, Red tier</span>` AND `aria-label="$1.8M, Red tier (over $1 million)"` on a `role="img"` parent (decision #75 + ARIA 1.2 compliance)

Tier perception works without color, without sight, and on monochrome printouts.

**Files changed:**

| Path | Change |
|---|---|
| `src/docket/web/templates/partials/dollar_tier.html` | NEW — 49-line partial, 35-line docstring documenting the triple-redundancy contract. `role="img"` on outer `<span>`. `format_dollars` cached via `{% set %}`. |
| `src/docket/web/filters.py` | Added `format_dollars` and `dollar_tier` filters. `dollar_tier` returns `DollarTier(color, symbol, description)` NamedTuple with `__str__` returning the color (v2 backcompat). Cross-link comment to `enrichment/dollars.py` thresholds. |
| `src/docket/web/public.py` | Removed legacy `@bp.app_template_filter("dollar_tier")` (would have clobbered the new global filter). |
| `src/docket/web/templates/partials/_facts_strip.html` | Replaced E5 TODO marker with the dollar_tier include. Outer `{% if dollars_amount %}` guard preserved. |
| `src/docket/web/static/styles.css` | NEW `.sr-only` utility class (4 lines). Pre-fix-up, no stylesheet defined it — without the rule, the SR label would render visibly the moment v3 cards became reachable. |
| `tests/unit/test_dollar_tier.py` | NEW — 71 tests across 5 classes (filter behavior, format dollars, partial per-tier, partial no-render, WCAG contract, facts-strip integration, role="img" check, sr-only CSS regression guard, silent-False forcing test). |
| `tests/unit/test_engagement_strip.py`, `tests/unit/test_smart_brevity_card_dispatcher.py` | Fixture switch to real `register_filters` (the inline string-shape override broke under the new NamedTuple shape). Two assertions strengthened to pin all three WCAG channels. |
| `docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md` | §6.1 canonical Jinja edited to match `dollar_tier.html` byte-for-byte (NamedTuple shape, `role="img"`). Prose example bumped from `$1,800,000` to `$1.8M ($$$$)` to align with decision #71. New paragraph explaining ARIA `role="img"` rationale. |
| `README.md` | Updated `dollar_tier` docstring for the NamedTuple return shape. |

**Notable decisions:**

1. **NamedTuple `__str__` shim for v2 backwards-compat.** Plan §E5 said `dollar_tier(amount)` returns a 3-tuple. But four pre-existing v2 templates (`search.html`, `topic_detail.html`, `card_v2_fallback.html`, `city.html`) interpolate the filter result directly: `class="tier-{{ amt | dollar_tier }}"` — they expected a string. Solved by `NamedTuple(color, symbol, description)` with custom `__str__` returning `self.color`. v3 partials get `.color`/`.symbol`/`.description` named access; v2 templates get the legacy `tier-green` output via Jinja's `str(value)` autoescape; tests can unpack as a 3-tuple. Zero v2 churn. The silent-False trap (`dollar_tier(amt) == 'green'` is False even though `str(...)` is `'green'`) is locked in by `test_eq_returns_false_when_compared_to_color_string`.

2. **ARIA 1.2 compliance — `role="img"` on the outer span.** Sonnet 4.6 second-look caught: `aria-label` on a plain `<span>` is invalid per ARIA 1.2 §6.2.1 (`<span>`'s implicit `generic` role is on the "prohibited naming" list). NVDA + Chrome and VoiceOver + Safari may silently ignore the attribute. Adding `role="img"` advertises the element as a self-contained graphic-like unit for which `aria-label` IS the accessible name. Spec §6.1 edited in lockstep with the partial. Both Opus reviewers verified the partial matched the spec — but the spec itself had the bug.

3. **`.sr-only` CSS dependency made explicit.** Pre-fix-up, no stylesheet defined `.sr-only`. Today the v3 path is unreachable so citizens don't see the issue, but at A8 launch the `<span class="sr-only">, Red tier</span>` would render as ordinary visible inline text. `styles.css` now ships the standard 4-line utility. `test_sr_only_class_is_visually_hidden_in_styles_css` asserts the rule exists with `position: absolute` + `clip: rect(0, 0, 0, 0)`, guarding against future CSS refactors silently breaking accessibility.

4. **Spec edited in lockstep with implementation.** Three places in spec §6.1 changed: canonical Jinja matches partial byte-for-byte; prose example bumped to `$1.8M ($$$$)`; new paragraph explains ARIA validity rationale. Same E3 lesson — when implementation deviates from spec text in a way the reviewer signs off on, edit the spec in lockstep so future readers don't see drift.

**Test impact:** 215 passed + 4 xfailed (pre-E5: 130) → 215 + 4 (E5 implementation, 71 new) → 215 + 4 (fix-up). Forcing tests stayed at 4 (E4's three plus E5 fix-up did NOT add a new forcing test — the bbox-viewrect xfail was added during E4 fix-up, not E5).

**E5 deferred items.** No new forcing tests from E5; the partial render is fully reachable once A8 lands.

---

### 2.2 A8 — AgendaItem + list_agenda_items extension

**Plan:** Cross-track task; tracked in coordination plan and project memory. **Spec:** §6.1–6.5 reference v3 columns; migration 013 defines them.

**Three commits:**
- `ab48fa2` — `feat(query): A8 — expose v3 columns on AgendaItem + list_agenda_items`
- `0cd1e02` — `fix(query): A8 follow-up — expose next_steps at top level for engagement_strip`
- `ff6cabb` — `fix(query): A8 review fix-up — lift v3 sub-keys + version docstrings + badges stub`

**What A8 does.** Pure data-layer task. Migration 013 added 14 v3 columns to `agenda_items` (Phase 1). Before A8, `AgendaItem.from_row()` didn't map them. The dispatcher (`smart_brevity_card.html`) reads `processing_status`, `data_quality`, `ai_rewrite_version` — Jinja's default `Undefined` made every gate condition falsy, so all items routed to `card_v2_fallback` or `card_pending`. **A8 makes v3 cards reachable in the dispatcher for the first time.**

A8 is **list-page only** — `services/query.py:list_agenda_items()`. Other listing queries (search, topic_detail, city) stay v2 by explicit scope decision. The detail page query is also out of scope; F-track tasks will handle it.

**Three design decisions (signed off before dispatch):**

1. **Lean list query** (not lazy-load). Lazy-load creates N+1 queries when partials render in a loop. Lean SELECT pulls small fields directly + `jsonb_extract_path` / `jsonb_build_object` for the heaviest blob (`extracted_facts`). Worst case at 100 items: ~150 KB instead of ~500 KB.
2. **Single `AgendaItem` dataclass** with v3 fields as `Optional`. Existing `from_row()` already uses `row.get(...)`. Extending in same pattern. Splitting into `AgendaItemList`/`AgendaItemDetail` deferred until the detail-page query task lands.
3. **Scope: `list_agenda_items()` only.** Search, topic_detail, city pages stay v2. Avoids 2-3x larger task; doesn't unblock E6.

**v3 columns exposed (8 of 14, others deferred):**

| Field | Type | Source | Use |
|---|---|---|---|
| `data_quality` | TEXT | column | Dispatcher gate (`!= 'ok'` → degraded) |
| `data_debt_priority` | TEXT (`'low'\|'normal'\|'high'`) | column | Admin view gating |
| `processing_status` | TEXT | column | Dispatcher gate (failed/procedural/conflict) |
| `ai_extraction_version` | INT | column | Stage 1 (LLM extraction) version tracking |
| `ai_rewrite_version` | INT | column | Stage 2 (Smart Brevity rewrite) — gate for `card_smart_brevity` |
| `ai_confidence` | TEXT (`'low'\|'medium'\|'high'`) | column | Confidence display |
| `headline` | TEXT | column | v3 card headline |
| `why_it_matters` | TEXT | column | v3 card why-it-matters prose |
| `source_anchor` | JSONB (small) | column | Source-anchor button (E4) |
| `extracted_facts` | JSONB (lean) | `jsonb_build_object` of 6 keys | Facts strip + engagement strip |
| `next_steps` | dict | lifted from `extracted_facts.next_steps` | Engagement strip top-level |
| `counterparty` | str | lifted from `extracted_facts.counterparty` | Facts strip top-level |
| `funding_source` | str | lifted from `extracted_facts.funding_source` | Facts strip top-level |
| `procurement_method` | str | lifted from `extracted_facts.procurement_method` | Facts strip top-level |
| `action_type` | str | lifted from `extracted_facts.action_type` | Engagement strip top-level |
| `location` | dict | lifted from `extracted_facts.location` | Facts strip top-level |

**v3 columns NOT exposed (5 — admin/operator only, detail-page work):**
`processing_attempts`, `last_error_at`, `last_error_message`, `score_overrides`, `backfill_session_id`. All have zero references in any partial (verified by grep).

**EXPLAIN ANALYZE on local PG (108 agenda_items total):**
- Default planner choice (small table): seq scan → 0.55 ms.
- `enable_seqscan=off` to verify the indexed path: `Index Scan using idx_agenda_items_meeting` for outer scan, `Index Only Scan` on `agenda_item_badges_agenda_item_id_badge_slug_key` for badges subquery, `Index Only Scan` on `priority_badge_templates_pkey` for templates JOIN → **0.18 ms**. No N+1, no seq scans on badge tables, well under the 50 ms target.
- **Hard prereq for E6 production flip:** re-run EXPLAIN ANALYZE on Railway production replica (~57K items) before flipping `SMART_BREVITY_UI=true`. Local result is a good signal but not a guarantee.

**Implementer-caught corrections to my brief:**

1. `ai_confidence` is TEXT with CHECK constraint `'high'|'medium'|'low'`, not float extracted from `ai_metadata->>'confidence'`. Used the column directly.
2. `data_debt_priority` enum is `'low'|'normal'|'high'`, not `'low'|'medium'|'high'`. Tests use the correct values.
3. Added `ai_extraction_version` (sibling of `ai_rewrite_version`). I missed it in the brief.
4. `next_steps` is a sub-key of `extracted_facts`, not a top-level column. Initial fix in `0cd1e02`: lift `next_steps` only. After user review, `ff6cabb` lifted all 5 remaining v3 sub-keys for consistency.

**Three-pass review findings:**

| Reviewer | Verdict | Findings |
|---|---|---|
| Code-quality (Opus) | ship | 2 SUGGESTED — badges Decimal/float docstring note; lean-keys `<=` → `==` assertion |
| Spec-compliance (Opus) | ship | 2 SUGGESTED — defensive test for malformed-string `extracted_facts`; badges JOIN missing `city_id` filter (defense-in-depth, deferred) |
| Sonnet 4.6 second-look | ship | 1 NEW — `_badge_row.html` HTMX `+N more` button targets `/items/<id>/badges` which has no route; would 404 the moment any item has >3 badges post-Phase 3 |
| User (lead) | ship | 2 NEW — lift inconsistency anti-pattern (lift only `next_steps` while leaving other sub-keys nested); version-field naming docstrings |

All findings folded into `ff6cabb`:
- **Lifted 5 remaining v3 sub-keys** (counterparty, funding_source, procurement_method, action_type, location) to top-level fields with `from_row()` lift logic. Defensive `isinstance(extracted_facts, dict)` guard handles malformed JSONB.
- **Phase 1 / Phase 2 docstrings** mapping the three version fields (`ai_extraction_version` → Stage 1, `ai_rewrite_version` → Stage 2, `ai_prompt_version` → legacy v2).
- **Decimal/float docstring note** on `query.py` badges JOIN section.
- **Defensive tests** for `extracted_facts="malformed string"` and `extracted_facts=[1,2,3]` → all lifted sub-keys correctly None.
- **Lean-shape equality assertion** with fully-populated fixture so `==` is meaningful.
- **`/items/<id>/badges` 501 stub** in `public.py` (matches E4/E5 stub-route convention) plus `xfail-strict` forcing test that flips when the real endpoint ships.

**Files changed across all three A8 commits:**

| Path | Change |
|---|---|
| `src/docket/models/agenda.py` | +12 fields on `AgendaItem` (5 v3 status/version, headline, why_it_matters, source_anchor, extracted_facts, plus 6 lifted sub-keys after `ff6cabb`). `from_row()` extended with defensive lift logic. Phase 1/Phase 2 docstrings on version fields. |
| `src/docket/services/query.py` | `list_agenda_items()` SELECT extended with v3 columns + `jsonb_build_object(jsonb_strip_nulls(...))` for lean `extracted_facts` + Decimal/float docstring note on badges JOIN. |
| `src/docket/web/public.py` | Stub `/items/<id>/badges` route returning 501 with TODO marker. |
| `src/docket/web/templates/partials/_badge_row.html` | Retired stale "click 404s" comment now that the stub returns 501. |
| `src/docket/web/templates/partials/_facts_strip.html` | Lifted sub-key access from `facts.X` to `item.X` (cleanup commit `63c49b1` simplified further). |
| `src/docket/web/templates/partials/engagement_strip.html` | Same lift for `action_type`. |
| `tests/unit/test_list_agenda_items.py` | NEW + extended — 22 tests post-fix-up: NULL handling, Wave 0 routing, all dispatcher gates, lean shape, defensive matrix, top-level lift verification, engagement strip integration. |
| `tests/unit/test_source_anchor.py` | +2 tests for badges 501 stub + xfail-strict 200 forcing test. |

**Test impact:** 215 + 4 (post-E5) → 753 + 4 (A8 implementation, +538 from broader test discovery as A8 landed) → 775 + 4 (A8 follow-up, +22 new) → 781 + 5 (A8 fix-up, +6 + 1 new xfail).

---

### 2.3 Cleanup commit `63c49b1`

**Goal.** A8 fix-up `ff6cabb` lifted 5 v3 sub-keys to top-level but kept defensive `or facts.X` fallbacks in the partials so existing engagement_strip test fixtures (bare dicts, not `AgendaItem` instances) wouldn't break. The cleanup converts those fixtures to use `AgendaItem` and drops the fallbacks for full lift consistency.

**Pure refactor — no behavior change.** Test counts unchanged: 781 + 5 xfailed before, 781 + 5 xfailed after.

**Hidden bug caught.** `test_list_agenda_items.py:test_ai_rewrite_version_3_routes_to_smart_brevity` was passing `extracted_facts={"counterparty": ...}` to its `_make_item` helper. The `AgendaItem` constructor doesn't auto-lift sub-keys (only `from_row()` does). The test was rendering with `extracted_facts` populated but `counterparty` (top-level) None — and the partial's fallback was hiding the inconsistency. Removing the fallback exposed the bug. Fix: promote sub-keys to top-level kwargs in the test fixture, matching the shape `from_row()` produces in production.

This is the kind of bug that surfaces ONLY when defensive fallbacks are stripped out. The cleanup paid for itself on the first pass — the test now asserts the same shape production data has, instead of masked coverage.

**Changes:**

| Path | Change |
|---|---|
| `src/docket/web/templates/partials/engagement_strip.html` | Removed `{% set facts = item.extracted_facts or {} %}` and `{% set action_type = item.action_type or facts.action_type %}`. Reads `item.action_type` directly. |
| `src/docket/web/templates/partials/_facts_strip.html` | Removed all 5 `{% set X = item.X or facts.X %}` lines + `facts = item.extracted_facts or {}`. Markup references `item.counterparty`, `item.funding_source`, `item.procurement_method`, `item.action_type`, `item.location` inline. |
| `tests/unit/conftest.py` | NEW — exports `make_agenda_item(**overrides) -> AgendaItem` helper with sensible defaults. |
| `tests/unit/test_engagement_strip.py` | All 16 fixtures converted to `make_agenda_item(...)`. Sub-keys lifted to top-level kwargs. |
| `tests/unit/test_smart_brevity_card_dispatcher.py` | All 21 fixtures converted across 4 test classes. |
| `tests/unit/test_dollar_tier.py` | 2 fixtures in `TestFactsStripDollarTierSwap` converted (out of strict scope but consistency). |
| `tests/unit/test_list_agenda_items.py` | Hidden-bug fix in `test_ai_rewrite_version_3_routes_to_smart_brevity`. |

---

## 3. Past — SOME detail (E1–E4)

### 3.1 E1 — Smart Brevity Card 6-variant dispatcher

**Commits:** `1e4e211` (implementation), `ce273e2` (review fixes), `2bef322` (protocol-relative URL rejection follow-up).

**Built:** `smart_brevity_card.html` dispatcher Jinja + 7 variant partials (`card_smart_brevity`, `card_verification_pending`, `card_degraded`, `card_failed`, `card_procedural`, `card_v2_fallback`, `card_pending`). Order matters: terminal states (`failed_permanent`, `data_quality_skipped`) checked first. v2 fallback at the bottom for items without v3 columns.

**Key decisions:** dispatcher gates on `processing_status` + `data_quality` + `ai_rewrite_version` (set by Wave 0 + Stage 1/2). v2-fallback hardened during review fixes. `_source_link_stub.html` introduced as a temporary stub for view-source links (E4 partially superseded, A8 finalized via the v2-side cleanup pattern).

**23 tests.** No active forcing tests from E1.

### 3.2 E2 — Badge Chip with Verification Spark

**Commits:** `575d898` (implementation), `198f6fb` (review fixes).

**Built:** `badge_chip.html` partial + `_badge_row.html` shared row + `order_badges` Jinja filter (process-first ordering by alarm rank, then policy by descending confidence then slug). Mobile carousel respects same priority sort. AI-verified spark (✨) shown when `confidence >= 1.0` per decision #67.

**Key decisions:** process badges grouped before policy badges. Process-alarm rank as O(1) dict lookup (built once at import). Defensive against malformed badge rows. `--accent` CSS token introduced for spark color.

**14 tests.** No active forcing tests.

### 3.3 E3 — Engagement Strip with Mailto Fallback

**Commits:** `c94410e` (implementation), `8ce83b2` (review fixes), `f9c4c3b` (Sonnet 4.6 second-look fixes).

**Built:** `engagement_strip.html` rendering 4 states: scheduled hearing date, comment period open, implementation date upcoming, and a "report data issue" mailto fallback when key fields are missing. `format_date` Jinja filter (Python 3.10 ISO-parse compat). `ADMIN_EMAIL` env config propagated to `app.config`.

**Key decisions:** RFC 6068 mailto urlencoded subject. `target="_blank"` + `rel="noopener noreferrer"` on every external link (project convention). Stubbed `public.item_detail` and `public.upcoming_hearings_rss` routes returning 404 — `url_for(...)` would have raised `BuildError` at first render without the stubs.

**Lesson learned (recorded in feedback memory):** Both Opus reviewers deferred three real production crashes as "downstream task territory" — the `municipality` vs `city` variable mismatch and missing `public.item_detail` / `public.upcoming_hearings_rss` routes. A fresh Sonnet 4.6 second-look correctly identified them as production crashes that should ship now. **Pattern:** when a reviewer says "not this task's bug," verify the production render path actually works without that fix. A shim that's two lines and unblocks downstream is cheaper than a "track for later" note. This is why the Track 3 protocol now mandates a Sonnet 4.6 second-look for any UI-bound task.

**22 tests.** No active forcing tests.

### 3.4 E4 — Source-Anchor Adaptive Button

**Commits:** `e233b2c` (implementation), `d0d0ee9` (xfail-strict forcing tests), `5f65bc6` (review fix-up).

**Built:** `source_anchor_button.html` with 8 branches: PDF + bbox + page → page link with region marker, PDF + page → `#page=N`, PDF bare → bare URL, HTML + anchor, video + timestamp → `?t=NNN`, bare URL, `data_quality == 'no_text_layer'` → "Source needs OCR" + admin-only data-debt link, else nothing. `format_timestamp` Jinja filter for video timestamps. `admin.data_debt` route stub (501 after fix-up). Domain allowlist module (`src/docket/web/source_security.py`) — global allowlist of platform domains (Granicus, CivicClerk, CivicPlus, YouTube, Vimeo) + dynamic municipality hosts loaded from `municipalities.adapter_config->>'base_url'` at app init.

**Review fix-up `5f65bc6`:** URL fragment canonicalization (strip pre-existing `#`), query-string canonicalization (use `&` if URL already has `?`), `format_timestamp` `OverflowError` catch, case + whitespace scheme normalization, 404 → 501 stub, **dropped "(region)" label** since the URL only delivers `#page=N` not bbox precision. Spec §6.4 edited in lockstep.

**4 xfail-strict forcing tests landed across E4:**
1. `test_data_debt_returns_200_when_queue_page_lands` — fires when admin queue is built (F-track work)
2. `test_source_link_stub_is_retired` — fires when `_source_link_stub.html` is deleted and 4 v2 cards swap to `source_anchor_button`
3. `test_video_timestamp_zero_renders_as_start_of_meeting` — fires if Stage 1 emits 0 as legitimate sentinel and partial flips truthy check to `is not none`
4. `test_pdf_bbox_emits_viewrect_deep_link` — fires when Stage 1 commits to PDF user-space coordinates and partial emits `#page=N&viewrect=L,T,W,H`

**130 cumulative tests post-E4.**

---

## 4. Future — VERY high level

### 4.1 Remaining Track 3 (E6, F-track, G-track)

| Task | Scope | Sequence |
|---|---|---|
| **E6** | `SMART_BREVITY_UI` env-flag gate. ~30 min. Lands gate, doesn't flip. | Next |
| **F1** | `list_items_by_badge` service for category landing pages. | After E6 |
| **F2** | Volume timeline (server-rendered SVG bars + mayoral term overlay). | After F1 |
| **F3** | Category landing pages render. | After F1+F2 |
| **F4** | KPI strip (year-to-date counts, total dollars). | After F3 |
| **F5** | Upcoming hearings RSS feed (replaces 404 stub from E3). | Independent |
| **G1–G4** | Admin views: data debt queue (replaces 501 stub from E4), badge backfill, AI cost dashboard, item detail. | After F-track |

### 4.2 Cross-track + Phase 2 close

- **B5** — atomic `process_item()` convergence: wires Stage 0a/0b/0c → Stage 1 extraction → Stage 2 rewrite → Stage 2.5 score floors → reconcile → process_badges → policy_badges → audit_log → persist. Single transaction. Lands after Track 3.

### 4.3 Phase 3 — LLM backfill

- **Pre-Phase-3:** Stage 0c content-hash dedup task. Adds `content_hash` and `ai_content_hash` columns; AI worker skips items where content + prompt version unchanged. Surfaced during E5 user review; ~$15 saved on Birmingham re-publish pattern, more material at full backfill scale.
- **Backfill execution:** ~$100 over 7–14 days for ~37K LLM-eligible items via Anthropic Batches API. Plan exists at `docs/superpowers/plans/2026-05-06-impact-first-refactor-phase-3.md`; not built yet.

### 4.4 Production rollout

In sequence, no shortcuts:

1. Track 3 finishes (E6 + F + G).
2. B5 atomic `process_item()` lands.
3. Stage 0c content-hash dedup lands.
4. `IMPACT_FIRST_ENABLED=true` — worker flips to v3 pipeline.
5. Phase 3 backfill runs (~$100, 7–14 days).
6. **Railway EXPLAIN ANALYZE verification** at ~57K rows confirms planner picks `idx_agenda_items_meeting`.
7. `SMART_BREVITY_UI=true` — citizens see v3 cards.
8. Phase 4 / Migration 014 — drops legacy `summary` column.

### 4.5 Phase 4 — cleanup

- Migration 014 drops legacy `summary` column once all completed items are at v3.
- Forcing tests fire as their respective cleanup tasks land:
  - `_source_link_stub.html` deleted, 4 v2 cards swapped (E4 forcing test #2).
  - `admin.data_debt` real queue page built (E4 forcing test #1).
  - `/items/<id>/badges` overflow endpoint built (A8 forcing test).
  - `timestamp_seconds=0` decision flipped (E4 forcing test #3) if Stage 1 emits 0.
  - `viewrect` deep link enabled (E4 forcing test #4) if Stage 1 commits to PDF user-space coords.

---

## 5. Outstanding items

### 5.1 Forcing tests (xfail-strict — 5 active)

| Test | Source | Fires when… |
|---|---|---|
| `test_data_debt_returns_200_when_queue_page_lands` | E4 | F-track / G-track real queue page implementation |
| `test_source_link_stub_is_retired` | E4 | `_source_link_stub.html` deleted + 4 v2 cards swap to `source_anchor_button` |
| `test_video_timestamp_zero_renders_as_start_of_meeting` | E4 | Partial Jinja flips truthy check to `is not none` (only if Stage 1 emits 0 as sentinel) |
| `test_pdf_bbox_emits_viewrect_deep_link` | E4 | Partial bbox branch updated to emit `#page=N&viewrect=...` (gated on Stage 1 coord guarantee) |
| `test_item_badges_overflow_returns_200_when_endpoint_lands` | A8 fix-up | F-track endpoint replaces 501 stub |

When any of these tests start passing, `strict=True` flips them into real test failures, forcing whoever lands the cleanup to remove the xfail mark. Five rot-prevention guards.

### 5.2 Architectural follow-ups

- **`AgendaItemList` / `AgendaItemDetail` split** — currently 33 fields on `AgendaItem` (28 + 5 lifted). Defer to detail-page query task.
- **`ORDER BY ai.item_number` is TEXT sort** — pre-existing bug noted by spec-compliance reviewer ("10" sorts before "2"). Separate ticket; not A8 scope.
- **Domain allowlist refresh on municipality changes** — `app.config['SOURCE_DOMAIN_ALLOWLIST']` built once at app startup. New cities require redeploy.
- **bbox `viewrect` upgrade** — requires Stage 1 coord-system commitment first.
- **i18n** — frontend has zero infrastructure. Project-wide architectural decision; not v3-task scope.
- **Stage 0c content-hash dedup** — between A8 and Phase 3 backfill. Required before backfill runs at full scale.

### 5.3 v2 surfaces deferred from Track 3

`search.html`, `topic_detail.html`, `city.html` still render legacy v2 cards. F-track tasks will explicitly extend to v3 when each flow is designed for it. This was an explicit scope-narrowing decision (3-decision sign-off during A8 design call) to keep A8 risk low and unblock E6.

---

## 6. Review pipeline pattern (validated through A8)

**Per-task pipeline:**

1. **Implementer** — fresh Agent (foreground, sequential). Brief includes plan section, spec section, worktree path, test command. Does NOT pre-classify anything as "out of scope."
2. **Two parallel Opus reviews** (background, read-only):
   - Spec-compliance — verifies partial/output matches canonical spec.
   - Code-quality — verifies defensiveness, security, test rigor, style.
3. **Sonnet 4.6 second-look** (foreground, mandatory for production-shipping tasks). Brief attaches both prior reviews and explicitly directs adversarial verification of every "OK to ship — unreachable today" claim. For each "deferred" finding, must answer: "does production render correctly TODAY without this fix? If no, it's not deferrable."
4. **User review** — parallel review packet (markdown, written to disk). User surfaces concerns the models miss (architectural feel, naming, future-readability).
5. **Fix-up loop** — single follow-up commit consolidating SUGGESTED + new findings.
6. **Memory update** — bump pickup file with new SHA, test count, new design constraints / forcing tests.

**When second-look is mandatory:**
- Any UI-bound task touching production render path.
- Any new route or schema migration.
- Any commit where Opus reviewers used phrases like "out of scope," "downstream task," "spec gap not implementation gap."

**When second-look is skippable:**
- Tests-only commits (no production code touched).
- Pure refactors with full test coverage and no behavior change (e.g., the cleanup commit `63c49b1`).
- Doc-only commits.

**Why parallel reviewers use the default Opus model and second-look uses Sonnet 4.6:** different priors, different mistake patterns. Cross-model framing + adversarial prompt is what catches deferrals (E3 lesson, E5 ARIA bug, A8 badges-HTMX 404 — all caught by the second-look pattern, not the parallel Opus reviews).

---

## 7. Files / locations reference

**Worktree:** `~/docket-pub-pf2-track-3` (sibling to `~/docket-pub`).

**Branch:** `feat/impact-first-phase-2-track-3` (local-only; not pushed).

**Plan:** `docs/superpowers/plans/2026-05-06-impact-first-refactor-phase-2.md` §E1-E6 + cross-track A-tasks tracked in `docs/superpowers/plans/2026-05-06-impact-first-phase-2-coordination.md`.

**Spec:** `docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md` §6.x + decisions log lines 86-90.

**Memory pickup:** `~/.claude-personal/projects/-Users-darrellnance/memory/project_pickup_2026_05_08_track3_a8_done.md`.

**Review docs (all under `~/docket-pub-pf2-track-3/docs/superpowers/reviews/`, all untracked):**
- `2026-05-07-e4-source-anchor-button-review.md` — E4 deep-dive technical review (448 lines)
- `2026-05-07-e5-dollar-tier-review.md` — E5 deep-dive technical review (448 lines)
- `2026-05-08-e5-pr-summary.md` — E5 PR-style team summary (post-fix-up, 13 KB)
- `2026-05-08-a8-parallel-review-packet.md` — A8 parallel-review packet (245 lines)
- `2026-05-08-track3-comprehensive-status.md` — this document

**Test command:**
```bash
cd ~/docket-pub-pf2-track-3
PYTHONPATH=$(pwd)/src ~/docket-pub/venv/bin/pytest tests/unit/ -v
```

---

## 8. Technical deep dives

Appendix-style detail for engineers who need to read the actual shapes, SQL, and defensive guards rather than narrative summaries.

### 8.1 The full `AgendaItem` dataclass (post-A8 + fix-up + cleanup)

`src/docket/models/agenda.py`. Frozen dataclass, 33 fields. Order matters — required fields first, optional defaults after, grouped by phase. Annotated below:

```python
@dataclass(frozen=True)
class AgendaItem:
    """A persisted agenda item row."""

    # --- v1 / required fields ----------------------------------------------
    id: int
    meeting_id: int
    external_id: str | None
    item_number: str | None
    title: str
    description: str | None
    section: str | None
    is_consent: bool
    sponsor: str | None
    dollars_amount: Decimal | None
    topic: str | None
    significance_score: float | None  # 0-10
    consent_placement_score: float | None  # 0-10

    # --- v2 AI columns (Haiku item summary, legacy) -------------------------
    summary: str | None = None
    ai_metadata: dict | None = None

    # --- AI version tracking (3 independent stages) -------------------------
    # Each version is bumped via constants in src/docket/ai/prompts.py;
    # bumping cascades re-processing for items at that stage AND downstream:
    #   - ai_prompt_version      → Legacy v2 (Haiku item summary → `summary`)
    #   - ai_extraction_version  → Phase 2 / Stage 1 (LLM extraction →
    #                              `extracted_facts` JSONB)
    #   - ai_rewrite_version     → Phase 2 / Stage 2 (Smart Brevity rewrite →
    #                              `headline` + `why_it_matters`)
    # All three coexist on every item so partials can gate cleanly on a
    # single stage's version while the others stay independent.
    ai_prompt_version: int | None = None
    ai_generated_at: datetime | None = None

    # --- v3 columns from migration 013 (Phase 1 + Phase 2) ------------------
    data_quality: str | None = None              # TEXT enum (no_text_layer, no_agenda_text, ok, ...)
    data_debt_priority: str | None = None        # TEXT enum: 'low' | 'normal' | 'high'
    processing_status: str | None = None         # TEXT enum (8 values; see migration 013)
    ai_extraction_version: int | None = None     # Stage 1
    ai_rewrite_version: int | None = None        # Stage 2 — gate for card_smart_brevity
    ai_confidence: str | None = None             # TEXT enum: 'high' | 'medium' | 'low'
    headline: str | None = None
    why_it_matters: str | None = None
    source_anchor: dict | None = None
    extracted_facts: dict | None = None          # LEAN: 6 keys only (see §8.2)

    # --- Lifted v3 sub-keys (top-level aliases for extracted_facts.*) -------
    # The lift is ADDITIVE: extracted_facts still carries each value;
    # the top-level field is a typed alias for partial readability.
    next_steps: dict | None = None
    counterparty: str | None = None
    funding_source: str | None = None
    procurement_method: str | None = None
    action_type: str | None = None
    location: dict | None = None

    # --- Aggregated badges (from agenda_item_badges JOIN) -------------------
    # Empty list when no badges; field(default_factory=list) avoids the
    # mutable-default-arg trap.
    badges: list[dict] = field(default_factory=list)
```

**Why `frozen=True`:** prevents in-process mutation. A partial that does `{% set facts = item.extracted_facts %}` followed by anything that tries to write back would raise; we want strict read-only semantics for cache safety.

**Why no `field(default_factory=dict)` for the JSONB fields:** the dataclass invariant is "missing/null → None," not "missing/null → empty dict." Partials use `or {}` guards in Jinja for the empty-dict case. Using `default_factory=dict` would make `item.extracted_facts is None` always False, which would break `from_row()` consumers that distinguish "not set" from "empty."

### 8.2 The `list_agenda_items()` SELECT (annotated SQL)

`src/docket/services/query.py:100-209`:

```sql
SELECT
    -- v1 / v2 columns (preserved from pre-A8)
    ai.id,
    ai.meeting_id,
    ai.external_id,
    ai.item_number,
    ai.title,
    ai.description,
    ai.section,
    ai.is_consent,
    ai.sponsor,
    ai.dollars_amount,
    ai.topic,
    ai.significance_score,
    ai.consent_placement_score,
    ai.summary,
    ai.ai_metadata,
    ai.ai_prompt_version,
    ai.ai_generated_at,

    -- v3 flat columns. ::text casts on enum-typed columns produce TEXT
    -- so psycopg returns a Python str, not the enum object. Saves a
    -- round-trip through the enum decoder for hot-path queries.
    ai.data_quality::text       AS data_quality,
    ai.data_debt_priority::text AS data_debt_priority,
    ai.processing_status::text  AS processing_status,
    ai.ai_extraction_version,
    ai.ai_rewrite_version,
    ai.ai_confidence,
    ai.headline,
    ai.why_it_matters,

    -- source_anchor: small enough to inline as full JSONB (~200 bytes
    -- per row; type/url/page/anchor/timestamp_seconds/bbox).
    ai.source_anchor,

    -- LEAN extracted_facts: build a dict containing only the keys the
    -- v3 cards render. NULL the whole field when extracted_facts is NULL
    -- so the partial's `or {}` guard fires correctly. jsonb_strip_nulls
    -- removes absent sub-keys so an item with only `counterparty` set
    -- doesn't carry the other 5 keys as JSON nulls. Each individual key
    -- is pulled with the right operator:
    --   - ->>  for TEXT keys (counterparty, funding_source, procurement_method, action_type)
    --   - ->   for JSONB sub-objects (location, next_steps)
    CASE
        WHEN ai.extracted_facts IS NULL THEN NULL
        ELSE jsonb_strip_nulls(jsonb_build_object(
            'counterparty',       ai.extracted_facts->>'counterparty',
            'funding_source',     ai.extracted_facts->>'funding_source',
            'procurement_method', ai.extracted_facts->>'procurement_method',
            'action_type',        ai.extracted_facts->>'action_type',
            'location',           ai.extracted_facts->'location',
            'next_steps',         ai.extracted_facts->'next_steps'
        ))
    END AS extracted_facts,

    -- Badges: aggregate matching templates into a BadgeChip-shaped jsonb
    -- array. COALESCE to '[]' so AgendaItem.from_row() always sees a list
    -- (never None). The subquery uses idx_agenda_item_badges_item from
    -- migration 013 (line 245). ORDER BY detected_at DESC so the most
    -- recently-detected badge is first (relevant for the "+N more" UI
    -- if a citizen wants the latest badges first).
    --
    -- NOTE: badge confidence values arrive as Decimal through the JSONB-agg
    -- round-trip (NUMERIC(3,2) column → jsonb_build_object → jsonb_agg →
    -- psycopg → Python). Consumers comparing to a float should explicitly
    -- cast (e.g., `float(chip["confidence"]) >= 1.0`) — direct comparison
    -- works in Python but is non-obvious.
    COALESCE(
        (
            SELECT jsonb_agg(jsonb_build_object(
                       'kind',        b.kind,
                       'slug',        b.badge_slug,
                       'confidence',  b.confidence,
                       'name',        t.name,
                       'icon',        t.icon,
                       'description', t.description
                   ) ORDER BY b.detected_at DESC)
            FROM agenda_item_badges b
            JOIN priority_badge_templates t ON t.slug = b.badge_slug
            WHERE b.agenda_item_id = ai.id
        ),
        '[]'::jsonb
    ) AS badges
FROM agenda_items ai
WHERE ai.meeting_id = %s
ORDER BY ai.item_number  -- pre-existing TEXT sort: "10" < "2"; separate ticket
```

### 8.3 `from_row()` defensive lift logic

`src/docket/models/agenda.py:87-140`. Every v3 sub-key has a per-key `isinstance` guard so a malformed `extracted_facts` (string, list, or with a sub-key of the wrong type) collapses to None instead of raising:

```python
@classmethod
def from_row(cls, row: dict) -> AgendaItem:
    extracted_facts = row.get("extracted_facts")
    # Defense: if extracted_facts itself isn't a dict (e.g. came back as
    # JSONB null, a stray string, a list), every lift returns None. Per-
    # key isinstance guards isolate damage so one bad value (e.g.,
    # counterparty: 42) doesn't poison the rest of the dict.
    ef = extracted_facts if isinstance(extracted_facts, dict) else {}
    next_steps          = ef.get("next_steps")          if isinstance(ef.get("next_steps"), dict)         else None
    counterparty        = ef.get("counterparty")        if isinstance(ef.get("counterparty"), str)        else None
    funding_source      = ef.get("funding_source")      if isinstance(ef.get("funding_source"), str)      else None
    procurement_method  = ef.get("procurement_method")  if isinstance(ef.get("procurement_method"), str)  else None
    action_type         = ef.get("action_type")         if isinstance(ef.get("action_type"), str)         else None
    location            = ef.get("location")            if isinstance(ef.get("location"), dict)           else None
    return cls(
        # ... all v1/v2 fields via row.get(...) ...
        extracted_facts=extracted_facts,  # raw lean dict still passed through
        next_steps=next_steps,
        counterparty=counterparty,
        funding_source=funding_source,
        procurement_method=procurement_method,
        action_type=action_type,
        location=location,
        badges=row.get("badges") or [],
    )
```

**Why type-guard each key independently rather than once at the dict level:** if `ef` is a dict but some keys are wrongly typed (e.g., LLM returned a number where it should have returned a string), the per-key guard isolates damage. Without it, the whole dataclass instance would carry a poisoned field that would later break `f"{item.counterparty}".upper()` or similar string ops in templates.

**Why `extracted_facts=extracted_facts` (raw passthrough) AND the lifts:** the lift is ADDITIVE. The lean dict still carries each value (in case a partial wants to read all sub-keys via `item.extracted_facts.<key>` for symmetry). The top-level field is a convenience alias.

### 8.4 Dispatcher routing under Wave 0 — full behavior matrix

`src/docket/web/templates/partials/smart_brevity_card.html`:

```jinja
{% if item.processing_status == 'failed_permanent' %}
  {% include 'partials/card_failed.html' %}
{% elif item.data_quality and item.data_quality != 'ok' %}
  {% include 'partials/card_degraded.html' %}
{% elif item.processing_status == 'procedural_skipped' %}
  {% include 'partials/card_procedural.html' %}
{% elif item.processing_status == 'cross_stage_conflict' %}
  {% include 'partials/card_verification_pending.html' %}
{% elif item.ai_rewrite_version == 3 %}
  {% include 'partials/card_smart_brevity.html' %}
{% elif item.summary %}
  {% include 'partials/card_v2_fallback.html' %}
{% else %}
  {% include 'partials/card_pending.html' %}
{% endif %}
```

**Behavior matrix for Wave 0 production data shapes:**

| `processing_status` | `data_quality` | `ai_rewrite_version` | `summary` | Routes to | Wave 0 count |
|---|---|---|---|---|---|
| `'failed_permanent'` | * | * | * | `card_failed` | 0 today |
| `'data_quality_skipped'` | (NULL or any) | * | * | `card_degraded` (via `data_quality != 'ok'` gate) | included in 16,169 |
| any | `'no_text_layer'` | * | * | `card_degraded` | included in 16,169 |
| any | `'no_agenda_text'` | * | * | `card_degraded` | included in 16,169 |
| `'procedural_skipped'` | (NULL) | * | * | `card_procedural` | 3,909 |
| `'cross_stage_conflict'` | * | * | * | `card_verification_pending` | 0 today (Stage 3 not run) |
| `'pending'` | (NULL or 'ok') | (NULL) | (set) | `card_v2_fallback` | many of 37,475 |
| `'pending'` | (NULL or 'ok') | (NULL) | (NULL) | `card_pending` | many of 37,475 |
| `'completed'` | (NULL or 'ok') | `3` | * | `card_smart_brevity` | 0 today (Phase 3 not run) |

**Order matters.** `failed_permanent` and `data_quality_skipped` are terminal states; they take priority over Stage 1/2 gates because there's no point routing a permanently-failed item to the v3 card path. `cross_stage_conflict` checked before `ai_rewrite_version == 3` so an item that completed Stage 2 but failed reconcile doesn't accidentally render as a clean v3 card.

**Crucial: the `cross_stage_conflict` state is written only by `reconcile.py:mark_cross_stage_conflict`, which fires only during Stage 3 reconciliation (Phase 3). Today this branch is structurally unreachable but correctly ready.**

### 8.5 Migration 013 column reference (cross-reference table)

Migration adds these columns to `agenda_items`:

| Column | Type | A8 exposed? | Indexed? | Use |
|---|---|---|---|---|
| `data_quality` | TEXT enum | ✓ | yes (partial: `data_debt`) | Wave 0 classification |
| `data_debt_priority` | TEXT enum (`low\|normal\|high`) | ✓ | yes (`idx_agenda_items_data_debt`) | admin queue prioritization |
| `processing_status` | TEXT enum (8 values) | ✓ | yes (partial: `idx_agenda_items_processing_status`) | dispatcher gate |
| `ai_extraction_version` | INT | ✓ | yes (`idx_agenda_items_extraction_version`) | Stage 1 cascade |
| `ai_rewrite_version` | INT | ✓ | yes (`idx_agenda_items_rewrite_version`) | Stage 2 cascade + dispatcher gate |
| `ai_confidence` | TEXT enum (`high\|medium\|low`) | ✓ | no | confidence display |
| `headline` | TEXT | ✓ | no | v3 card headline |
| `why_it_matters` | TEXT | ✓ | no | v3 card prose |
| `source_anchor` | JSONB | ✓ | no | source-anchor button |
| `extracted_facts` | JSONB | ✓ (lean) | yes (`idx_agenda_items_counterparty_trgm` GIN) | facts strip + engagement strip |
| `processing_attempts` | INT | ✗ deferred | no | retry telemetry (admin-only) |
| `last_error_at` | TIMESTAMPTZ | ✗ deferred | no | retry telemetry |
| `last_error_message` | TEXT | ✗ deferred | no | retry telemetry |
| `score_overrides` | JSONB | ✗ deferred | no | manual score floor overrides |
| `backfill_session_id` | TEXT | ✗ deferred | yes (partial: `idx_agenda_items_backfill_session`) | Phase 3 session tracking |

**5 of 14 columns deferred** to detail-page query. All 5 have zero references in any partial under `web/templates/`. Verified by grep during spec-compliance review.

**Indexes that matter for `list_agenda_items()`:**
- `idx_agenda_items_meeting` (pre-existing) — outer scan path. The query `WHERE meeting_id = %s` uses this.
- `idx_agenda_item_badges_item` (line 245) — badges subquery path.
- `priority_badge_templates_pkey` — JOIN on template slug.

`idx_agenda_items_processing_status` is a **partial index** (only items NOT in `('completed', 'failed_permanent')`). Used by background workers polling for items needing processing, NOT by the list query. List query reads all statuses.

### 8.6 EXPLAIN ANALYZE annotated output (local PG, 108 rows)

Default planner choice (`enable_seqscan=on`, small table):

```
Sort  (cost=8.42..8.46 rows=15 width=...)  (actual time=0.55..0.55 rows=15 loops=1)
  Sort Key: ai.item_number
  ->  Seq Scan on agenda_items ai  (cost=0..7.92 rows=15 width=...)  (actual time=0.04..0.41 rows=15 loops=1)
        Filter: (meeting_id = 142)
  SubPlan 1
    ->  ... badges aggregation ...
Planning Time: 0.5 ms
Execution Time: 0.55 ms
```

With `SET enable_seqscan = OFF` to force the indexed plan:

```
Sort  (cost=...)  (actual time=0.18..0.18 rows=15 loops=1)
  Sort Key: ai.item_number
  ->  Index Scan using idx_agenda_items_meeting on agenda_items ai
        (actual time=0.05..0.12 rows=15 loops=1)
        Index Cond: (meeting_id = 142)
  SubPlan 1
    ->  Index Only Scan using agenda_item_badges_agenda_item_id_badge_slug_key
          on agenda_item_badges b
          Heap Fetches: 0
    ->  Index Only Scan using priority_badge_templates_pkey
          on priority_badge_templates t
          Heap Fetches: 0
Planning Time: 0.4 ms
Execution Time: 0.18 ms
```

**At 108 rows the planner's seq-scan choice is correct** (smaller cost than the index lookup). At 57K rows on Railway, it MUST flip to the index path; if it doesn't, the badge subquery fan-out goes O(n²) and the query becomes a serious problem. The hard prereq before E6 production flip is verifying the Railway planner picks `idx_agenda_items_meeting` automatically.

**What to watch for at scale:**
1. Does `meeting_id = X` use `idx_agenda_items_meeting`? (Should always; no function call wraps the predicate.)
2. Is the badges subquery executed once per agenda_item row or hoisted to a single GROUP BY? (Subquery — that's fine for ≤150 items per meeting.)
3. Is `jsonb_strip_nulls + jsonb_build_object` evaluated row-by-row? (Yes — no way around it; ~6 keypath lookups + 1 strip per row. Negligible at any realistic row count.)

### 8.7 NamedTuple `__str__` mechanics (E5)

`src/docket/web/filters.py`:

```python
class DollarTier(NamedTuple):
    color: str
    symbol: str
    description: str

    def __str__(self) -> str:
        return self.color
```

**Three contracts simultaneously:**

1. **v3 partial uses named access:**
   ```jinja
   {%- set tier_data = amount | dollar_tier -%}
   <span class="dollars dollars--{{ tier_data.color }}"
         role="img"
         aria-label="{{ amount | format_dollars }}, {{ tier_data.color|title }} tier ({{ tier_data.description }})">
     {{ amount | format_dollars }}
     ({{ tier_data.symbol }})<span class="sr-only">, {{ tier_data.color|title }} tier</span>
   </span>
   ```

2. **v2 templates use string interpolation:**
   ```jinja
   <span class="tier tier-{{ amt | dollar_tier }}">  {# renders "tier-green" via __str__ #}
   ```
   Jinja's autoescape calls `str(value)` on filter results when interpolated into attributes. Custom `__str__` returns `self.color`. Output: `tier-green`. Identical to the legacy filter.

3. **Tests use 3-tuple unpacking:**
   ```python
   color, symbol, description = amount | dollar_tier  # NamedTuple unpacks as tuple
   ```

**The silent-False trap:**
```python
amount = Decimal('100')
tier = dollar_tier(amount)
str(tier) == 'green'        # True  (uses __str__)
tier == 'green'             # False (NamedTuple __eq__ compares as tuple)
'green' in tier             # True  (tuple membership; tier.color is 'green')
```

If a future template writes `{% if amount | dollar_tier == 'green' %}`, the comparison is silently False even though the filter returned the green tier. `test_eq_returns_false_when_compared_to_color_string` locks this contract — if anyone removes `__str__` from `DollarTier`, the test fails AND a future `==` comparison would silently break. Both ends pinned.

**Why not just return a dict instead of a NamedTuple:**
- Dicts don't have `__str__` returning a single field; would need a wrapper class anyway.
- Dicts unpack via `.values()`, less ergonomic than tuple unpacking.
- NamedTuples are immutable (matches the dataclass `frozen=True` discipline).
- Type-annotated NamedTuple gives mypy + IDE completion on `.color`/`.symbol`/`.description`.

### 8.8 `xfail-strict` forcing test mechanics

`pytest.mark.xfail(strict=True, reason=...)` semantics:

| Test runs | `strict=False` (default) | `strict=True` |
|---|---|---|
| Test FAILS (assertion fails / error raised) | reported as `XFAIL` (expected failure) — pipeline green | reported as `XFAIL` — pipeline green |
| Test PASSES (assertion holds) | reported as `XPASS` — pipeline green (warning) | reported as `XPASSED` (failure) — pipeline RED |

The `strict=True` is the rot-prevention key. When a future PR makes the test start passing (because the underlying cleanup landed), strict mode flips it from `XFAIL` to `XPASSED` which is a HARD test failure. The engineer must either:
1. Verify the cleanup actually shipped, then remove the `xfail` mark (the desired state — test goes green permanently).
2. Realize they accidentally made a test pass that was meant to lock in a deferred behavior, and revert.

**Active forcing tests in Track 3:**

```python
# E4 — d0d0ee9
@pytest.mark.xfail(strict=True, reason="data_debt route is currently a 501 stub")
def test_data_debt_returns_200_when_queue_page_lands(client):
    response = client.get("/admin/data-debt/?highlight=42")
    # Note: passes admin session in fixture
    assert response.status_code == 200

@pytest.mark.xfail(strict=True, reason="_source_link_stub.html still in use by 4 v2 cards")
def test_source_link_stub_is_retired():
    stub_path = Path("src/docket/web/templates/partials/_source_link_stub.html")
    assert not stub_path.exists()
    for tpl in Path("src/docket/web/templates/partials/").glob("card_*.html"):
        assert "_source_link_stub" not in tpl.read_text()

@pytest.mark.xfail(strict=True, reason="spec §6.4 uses truthy `if anchor.timestamp_seconds`")
def test_video_timestamp_zero_renders_as_start_of_meeting():
    rendered = _render(anchor={"type": "video", "url": "...", "timestamp_seconds": 0})
    assert "0:00" in rendered

# E4 fix-up — 5f65bc6
@pytest.mark.xfail(strict=True, reason="bbox branch produces output identical to page-only branch")
def test_pdf_bbox_emits_viewrect_deep_link():
    rendered = _render(anchor={"type": "pdf", "url": "...", "page": 7, "bbox": [10,20,100,200]})
    assert "viewrect=" in rendered

# A8 fix-up — ff6cabb
@pytest.mark.xfail(strict=True, reason="HTMX overflow-badges endpoint is a 501 stub")
def test_item_badges_overflow_returns_200_when_endpoint_lands(client):
    response = client.get("/items/42/badges")
    assert response.status_code == 200
```

When any of these FIRES (passes), it's a signal to investigate the corresponding cleanup. The pattern explicitly named on a class wrapper:

```python
class TestForcingFunctionsForE4Cleanups:
    """Forcing functions: each test asserts a future state and is marked
    xfail-strict. When the corresponding cleanup ships, the test passes,
    `strict=True` turns the XPASS into a real failure, and the engineer
    is forced to remove the xfail mark — confirming the cleanup actually
    happened. If the test passes WITHOUT removing the mark, that's an
    alarm that someone partially completed a deferred task without
    closing the loop."""
```

### 8.9 The cleanup commit's hidden-bug discovery

Walkthrough of `63c49b1`'s `test_ai_rewrite_version_3_routes_to_smart_brevity` fix:

**Before cleanup, the test:**
```python
def test_ai_rewrite_version_3_routes_to_smart_brevity(client):
    item = _make_item(
        ai_rewrite_version=3,
        headline="Approve $1.8M demolition contract",
        why_it_matters="Largest demolition contract this year.",
        extracted_facts={
            "counterparty": "Flock Safety Inc.",
            "funding_source": "general_fund",
            "action_type": "contract_award",
            "next_steps": {"public_hearing_date": "2026-06-15"},
        },
        # ... other fields ...
    )
    html = render_card(item)
    assert "Flock Safety Inc." in html
```

**`_make_item()` builds an `AgendaItem` directly via the constructor** — it does NOT go through `from_row()`. The `from_row()` lift logic (which auto-promotes `extracted_facts.counterparty` to top-level `counterparty`) is bypassed. Result: the constructed item has `extracted_facts={"counterparty": "Flock Safety Inc.", ...}` BUT `counterparty=None` (top-level).

**Pre-cleanup, the partial had a fallback:**
```jinja
{% set counterparty = item.counterparty or facts.counterparty %}
```

The fallback hid the bug. Test rendered, "Flock Safety Inc." appeared in HTML (via the fallback path), test passed.

**Post-cleanup, the partial reads only `item.counterparty`:**
```jinja
{% if item.counterparty %}
  <p>Counterparty: {{ item.counterparty }}</p>
{% endif %}
```

The fallback is gone. `item.counterparty` is None. The conditional doesn't fire. "Flock Safety Inc." doesn't appear. Test fails.

**Fix:** lift the sub-keys to top-level kwargs in the test fixture, matching the shape `from_row()` produces in production:

```python
item = _make_item(
    ai_rewrite_version=3,
    headline="...",
    why_it_matters="...",
    counterparty="Flock Safety Inc.",      # top-level
    funding_source="general_fund",         # top-level
    action_type="contract_award",          # top-level
    next_steps={"public_hearing_date": "2026-06-15"},  # top-level
    extracted_facts={                      # raw lean dict (still passed for symmetry)
        "counterparty": "Flock Safety Inc.",
        "funding_source": "general_fund",
        "action_type": "contract_award",
        "next_steps": {"public_hearing_date": "2026-06-15"},
    },
    # ... other fields ...
)
```

**Lesson generalizes:** when a refactor strips out defensive fallbacks, hidden bugs that were masked by the fallback become test failures. This is a feature, not a regression — the test was previously asserting a meaningless thing (rendering with a fallback that wouldn't fire in production). Post-cleanup, the test asserts the actual production rendering path.

### 8.10 Per-task test breakdown

| Test file | Tests | Coverage focus |
|---|---|---|
| `test_smart_brevity_card_dispatcher.py` | 22 | Each dispatcher gate + fallthrough; v2 fallback fields; source link scheme validation; verification pending content |
| `test_badge_chip_ordering.py` | 14 | Process-first ordering; alarm-rank lookup; Verification Spark threshold; defensive against missing fields |
| `test_engagement_strip.py` | 22 | 4 states (hearing scheduled, comment open, implementation upcoming, mailto fallback); date formatting; mailto encoding |
| `test_source_anchor.py` | 51 + 4 xfailed | 8 dispatcher branches; format_timestamp filter; admin.data_debt 501 stub; scheme rejection; badges 501 stub + xfail forcing tests |
| `test_source_security.py` | 34 | Static allowlist + dynamic municipality hosts; scheme normalization; subdomain handling |
| `test_dollar_tier.py` | 71 + 1 xfailed | Filter behavior; format_dollars; per-tier rendering; WCAG triple-redundancy + Path A/B; sr-only CSS regression guard; silent-False trap |
| `test_list_agenda_items.py` | 22 | NULL handling for v3 fields; Wave 0 routing; lean shape lock-in; defensive `extracted_facts` matrix; engagement strip integration |
| Total | **~256** plus full v2 + AI tests = **781 + 5** |

### 8.11 JSONB extraction operator cheatsheet (for future tasks)

PostgreSQL JSONB operators used in A8:

| Operator | Returns | Example | Use in A8 |
|---|---|---|---|
| `->>` | TEXT | `extracted_facts->>'counterparty'` | scalar TEXT keys |
| `->` | JSONB | `extracted_facts->'location'` | nested objects (`{address, ward, ...}`) |
| `jsonb_build_object` | JSONB | `jsonb_build_object('k1', v1, 'k2', v2)` | construct lean dict |
| `jsonb_strip_nulls` | JSONB | `jsonb_strip_nulls(jsonb_build_object(...))` | remove keys where source returned NULL |
| `jsonb_agg` | JSONB array | `(SELECT jsonb_agg(...) FROM ...)` | aggregate multiple rows into array |
| `IS NULL` (JSONB) | bool | `extracted_facts IS NULL` | NULL ≠ JSONB null literal `'null'::jsonb` |
| `?` | bool | `adapter_config ? 'base_url'` | key existence test (used in `source_security.py`) |

**Common pitfalls avoided in A8:**
- Using `->` where `->>` was needed (returns JSONB null instead of NULL TEXT).
- Forgetting `jsonb_strip_nulls` (lean dict carries 5 explicit `null` values for missing keys, breaking the partial's `or {}` semantic).
- Confusing SQL NULL with JSONB null literal (`'null'::jsonb`). The CASE guard `WHEN extracted_facts IS NULL THEN NULL` returns SQL NULL; nesting `jsonb_build_object` over a NULL would return `{...all nulls...}` not NULL.

---

## 9. Quick links

**Full git log (Track 3 only, base `b4b9a88` excluded):**
```
63c49b1 refactor(web): drop or-facts fallback in v3 partials, convert fixtures to AgendaItem
ff6cabb fix(query): A8 review fix-up — lift v3 sub-keys + version docstrings + badges stub
0cd1e02 fix(query): A8 follow-up — expose next_steps at top level for engagement_strip
ab48fa2 feat(query): A8 — expose v3 columns on AgendaItem + list_agenda_items
57ad1c5 fix(web): E5 review fix-up — role="img" for ARIA validity, .sr-only CSS, README + caching
10f52c9 feat(web): WCAG-2.1-compliant dollar tier with symbols + sr-only labels
5f65bc6 fix(web): E4 review fix-up — URL canonicalization, domain allowlist, 501 stub, drop bbox label
d0d0ee9 test(web): xfail-strict forcing tests for E4 TODO cleanups
e233b2c feat(web): adaptive source-anchor button (bbox → page → doc → OCR-needed)
f9c4c3b fix(web): E3 second-look — alias city in cards, stub item_detail+RSS routes
8ce83b2 fix(web): E3 review fixes — RFC 6068 mailto, target=_blank, format_date 3.10 compat
c94410e feat(web): engagement strip with 4 states + mailto fallback for missing data
198f6fb fix(web): E2 review fixes — link CSS, accent token, defensive confidence, _badge_row shared partial
575d898 feat(web): badge chip with Verification Spark + process-first ordering + mobile carousel
2bef322 fix(web): reject protocol-relative URLs in source-link stub
ce273e2 fix(web): E1 review fixes — v2 fallback fields, verification facts/source, scheme validation
1e4e211 feat(web): Smart Brevity Card 6-variant dispatcher + partials
```
