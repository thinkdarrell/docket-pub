# E5 — Dollar Tier with WCAG Markup (Track 3 of 5/15) — Ready for Team Review

**Status:** Shipped on `feat/impact-first-phase-2-track-3` (local), ready to merge after team sign-off.
**Branch:** `feat/impact-first-phase-2-track-3` @ `57ad1c5` (13 commits ahead of `b4b9a88`)
**Plan:** §E5 of `docs/superpowers/plans/2026-05-06-impact-first-refactor-phase-2.md`
**Spec:** §6.1 of `docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md` (decisions #71, #75)

## Verdict at a glance

| Reviewer | Outcome |
|---|---|
| Spec-compliance (Opus, parallel) | ship — no findings |
| Code-quality (Opus, parallel) | ship — 6 SUGGESTED items, no REQUIRED |
| Sonnet 4.6 second-look | ship — 1 new finding (N1 — ARIA 1.2 validity) |
| User review | all SUGGESTED items + N1 folded into fix-up; 1 new backlog item surfaced (content-hash dedup) |
| **Combined verdict** | **SHIP** |

All review findings are now closed. 6 SUGGESTED items + N1 + 1 optional forcing test landed in `57ad1c5`. The pre-fix-up technical review report is in `docs/superpowers/reviews/2026-05-07-e5-dollar-tier-review.md` (also on Drive) for engineers who want the full audit trail.

## What shipped

Two commits — implementation + review fix-up:

```
57ad1c5 fix(web): E5 review fix-up — role="img" for ARIA validity, .sr-only CSS, README + caching
10f52c9 feat(web): WCAG-2.1-compliant dollar tier with symbols + sr-only labels
```

### Functional outcome

Every `dollars_amount` rendered via the v3 facts strip now has **WCAG 2.1 AA triple-redundant tier signal**:

- **Color** — CSS class `dollars--green | --yellow | --orange | --red`
- **Symbol** — visible text `$ | $$ | $$$ | $$$$` (decision #71 — color is no longer load-bearing)
- **Screen-reader label** — both `<span class="sr-only">, Red tier</span>` AND `aria-label="$1.8M, Red tier (over $1 million)"` on a `role="img"` parent (decision #75)

Tier perception works without color, without sight, and on monochrome printouts.

### Files touched (commit-spanning)

| Path | Change |
|---|---|
| `src/docket/web/templates/partials/dollar_tier.html` | NEW — 49 lines (35-line docstring + 14-line Jinja). `role="img"` for ARIA validity. `format_dollars` cached via `{% set %}`. |
| `src/docket/web/filters.py` | Added `format_dollars` and `dollar_tier` filters. `dollar_tier` returns `DollarTier(color, symbol, description)` NamedTuple with `__str__` returning the color (v2-template backcompat). Threshold prose has cross-link comment to `enrichment/dollars.py`. |
| `src/docket/web/public.py` | Removed legacy `@bp.app_template_filter("dollar_tier")` (replaced by global filter in `filters.py`). |
| `src/docket/web/templates/partials/_facts_strip.html` | Replaced E5 TODO marker with the new partial include. Outer `{% if dollars_amount %}` guard preserved. |
| `src/docket/web/static/styles.css` | NEW `.sr-only` utility class (4 lines). Dollar-tier partial depends on it; previously absent in any loaded stylesheet. |
| `tests/unit/test_dollar_tier.py` | NEW — 71 unit tests across 5 classes (filter behavior, format dollars, partial per-tier, partial no-render, WCAG contract, facts-strip integration, plus N1 role validity, sr-only CSS regression guard, and silent-False forcing test). |
| `tests/unit/test_engagement_strip.py` | Fixture switched to real `register_filters` (the inline string-shape override broke against the new NamedTuple shape). |
| `tests/unit/test_smart_brevity_card_dispatcher.py` | Same fixture switch. Two assertions strengthened — now pin all three WCAG channels (`"$1.8M"`, `"dollars--red"`, `"($$$$)"`) instead of legacy single-color string. |
| `docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md` | §6.1 canonical Jinja edited to match the partial byte-for-byte (NamedTuple shape, `role="img"`). Prose example bumped from `$1,800,000` to `$1.8M ($$$$)` to align with decision #71. |
| `README.md` | Updated `dollar_tier` docstring to describe the NamedTuple return shape. |

## Test results

```
tests/unit/test_dollar_tier.py                        71 passed
tests/unit/test_badge_chip_ordering.py                14 passed
tests/unit/test_engagement_strip.py                   23 passed
tests/unit/test_source_anchor.py                      51 passed + 4 xfailed
tests/unit/test_source_security.py                    34 passed
tests/unit/test_smart_brevity_card_dispatcher.py      22 passed
                                                      ───────────────
Track 3 v3-partial suite total:                      215 passed + 4 xfailed
```

The 4 xfails are intentional `xfail-strict` forcing-function tests on E4 deferred items — they're SUPPOSED to fail today and will fire as real test failures the moment downstream cleanup tasks land. See `docs/superpowers/reviews/2026-05-07-e4-source-anchor-button-review.md` §9 for the forcing-function pattern.

Run command:
```bash
cd ~/docket-pub-pf2-track-3
PYTHONPATH=$(pwd)/src ~/docket-pub/venv/bin/pytest tests/unit/test_dollar_tier.py -v
```

## Notable decisions

### 1. NamedTuple `__str__` shim for v2 backwards-compat

Plan §E5 says `dollar_tier(amount)` returns `('green'|...|'red', '$'|...|'$$$$', 'over $X')`. But four pre-existing v2 templates (`search.html`, `topic_detail.html`, `card_v2_fallback.html`, `city.html`) interpolate the filter result directly: `class="tier-{{ amt | dollar_tier }}"`. They expect a string, not a tuple.

Solved by returning a `NamedTuple(color, symbol, description)` with custom `__str__` returning `self.color`. v3 partial gets `.color`/`.symbol`/`.description` named access; v2 templates get the legacy `tier-green` output via Jinja's `str(value)` autoescape; tests can unpack as a 3-tuple. Zero v2 template churn.

The silent-False trap (`dollar_tier(amt) == 'green'` is False even though `str(...)` is `'green'`) is locked in by `test_eq_returns_false_when_compared_to_color_string`. `grep -rE 'dollar_tier\s*(==|!=|in)'` returned zero hits in the codebase — no caller relies on the broken comparison pattern.

### 2. ARIA 1.2 compliance — `role="img"` on the outer span

Sonnet 4.6 second-look caught: `aria-label` on a plain `<span>` is invalid per ARIA 1.2 §6.2.1. The `<span>` element has implicit role `generic`, which is on the "prohibited naming" list — `aria-label` is not allowed there. NVDA + Chrome and VoiceOver + Safari may silently ignore the attribute.

Fix: add `role="img"` to the outer span. The element advertises itself as a self-contained graphic-like unit for which `aria-label` is the accessible name. Spec §6.1 was edited in the same commit to match. Test `test_outer_span_has_role_img_for_aria_label_validity` locks the regression.

### 3. `.sr-only` CSS dependency made explicit

The partial emits `<span class="sr-only">, Red tier</span>` expecting the standard "visually hidden but screen-reader readable" semantic. Pre-fix-up, no stylesheet defined `.sr-only` — without the rule, the screen-reader label would render as ordinary visible inline text the moment v3 cards become reachable.

`styles.css` now ships the standard 4-line utility. `test_sr_only_class_is_visually_hidden_in_styles_css` asserts the rule exists with `position: absolute` + `clip: rect(0, 0, 0, 0)`, guarding against future CSS refactors silently breaking accessibility.

### 4. Spec edited in lockstep with implementation

Three places in spec §6.1 changed in `10f52c9` and `57ad1c5`:
- Canonical Jinja now matches the partial byte-for-byte (NamedTuple shape, `role="img"`).
- Prose example: `$1,800,000` → `$1.8M ($$$$)` (aligns with decision #71).
- Added paragraph explaining why `role="img"` is required for ARIA validity.

This follows the E3 lesson: when implementation deviates from spec text in a way the reviewer is signing off on, edit the spec in lockstep so future readers don't see drift.

## What's NOT in this PR (deferred + forcing-tested)

These are A8-gated. The A8 task (extending `AgendaItem` dataclass + `services/query.py:list_agenda_items()` SELECT to expose v3 columns) hasn't started. Until then, the dispatcher routes every item to `card_v2_fallback` or `card_pending` — none of the v3 partials (engagement_strip, source_anchor_button, dollar_tier) actually render in production today. Listed here so the A8 implementer doesn't miss them:

- **`_source_link_stub.html` deletion + 4 v2 cards swap to `source_anchor_button`** — gated on A8. Forcing test `test_source_link_stub_is_retired` (xfail-strict).
- **`admin.data_debt` queue page** — currently a 501 stub. Real implementation likely F-track. Forcing test `test_data_debt_returns_200_when_queue_page_lands`.
- **`timestamp_seconds=0` rendering** — falls through to bare URL today. If Stage 1 emits 0 as a legitimate sentinel, flip to `is not none`. Forcing test `test_video_timestamp_zero_renders_as_start_of_meeting`.
- **PDF bbox `viewrect` deep link** — bbox+page branch produces output identical to page-only. When Stage 1 commits to PDF user-space coordinates, switch to `#page=N&viewrect=L,T,W,H`. Forcing test `test_pdf_bbox_emits_viewrect_deep_link`.

All four xfail-strict tests will fire as **real test failures** the moment the corresponding cleanup ships, forcing the implementer to remove the xfail mark — preventing silent rot.

## A8 design constraints surfaced during E4 + E5 reviews (heads-up for downstream work)

The team should know these before A8 lands:

1. **SQL/memory bloat risk.** A meeting can have 100+ items. Adding 7-10 JSONB columns (`source_anchor`, `extracted_facts`, `ai_metadata`, `next_steps`, `badges`, etc.) to `list_agenda_items()` SELECT could push 50-200 KB extra per page-render. **Recommended:** separate list query (lean) from detail query (full v3 set), OR lazy-load JSONB blobs via `load_extracted_facts(item_id)` etc. Verify with EXPLAIN ANALYZE on a 100-item meeting before merging.

2. **Domain allowlist refresh on municipality changes.** `app.config['SOURCE_DOMAIN_ALLOWLIST']` is built once at app startup. Adding a city without a redeploy → links to that city silently dropped. Document in runbook OR rebuild on `municipalities` table change.

3. **bbox `viewrect` coord-system commitment.** Don't ship `viewrect=` URLs without verifying Stage 1's coord guarantee — wrong-region links are worse than missing-region links.

## NEW backlog item — Stage 0c content-hash dedup

Surfaced during E5 user review. The ingest layer keys upserts by `(meeting_id, external_id)` — re-published minutes update in place — but there's no content-hash dedup before AI processing. Birmingham's "minutes amendment" pattern (~20% of meetings re-publish within 1-2 weeks) means the AI worker may re-run on functionally-identical content, OR fail to re-run when content changed but `ai_prompt_version` didn't.

**Proposed (not yet built):** add `content_hash` and `ai_content_hash` TEXT columns to `agenda_items`. Hash on `(title || description || raw_text)` (SHA-256). AI worker compares: skip if `content_hash == ai_content_hash` AND `ai_prompt_version` matches. Re-run on either differing.

**Schedule:** between A8 and Phase 3 backfill. Blocks: nothing in Track 3. Blocks: Phase 3 (don't run the big backfill without dedup). Cost-benefit: ~$15 saved on Birmingham at Sonnet $0.0085/meeting + 5% dedup, more material at Phase 3 scale, plus stale-summary correctness.

Full design notes in the project memory pickup file.

## Sign-off ask

Two things from the team:

1. **Approve E5 + fix-up to merge.** Branch is local; ready to push after sign-off. (Per Track 3 plan, the branch may stay local until full Track 3 finishes — happy to push the PR now or hold per team preference.)

2. **Acknowledge A8 design constraints.** Whoever picks up A8 needs to know about the SQL/memory bloat risk and decide between the lean-list-query approach vs. lazy-loading JSONB blobs. Worth a 15-minute design conversation before the A8 implementer starts.

## Where to go deeper (optional)

- **Pre-fix-up technical review:** `docs/superpowers/reviews/2026-05-07-e5-dollar-tier-review.md` (also on Drive). 448 lines, full audit trail of all three review passes + deep dives on N1, `.sr-only`, NamedTuple shim, and the A8 wall.
- **E4 review (last task before this one):** `docs/superpowers/reviews/2026-05-07-e4-source-anchor-button-review.md`. Same shape; useful context if the team wants to understand how the review pipeline catches issues at every layer.
- **Spec §6.1 (dollar-tier accessibility):** lines 2519-2541 of `docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md`.
- **Decisions log #71 + #75:** lines 86-90 of the spec.

---

## Track 3 progress overview

| Task | Status | Commit |
|---|---|---|
| E1 — Dispatcher + 7 variant partials | shipped | `1e4e211` + fix-ups |
| E2 — Badge chip with Verification Spark | shipped | `575d898` + fix-ups |
| E3 — Engagement strip with mailto fallback | shipped | `c94410e` + fix-ups |
| E4 — Source-anchor adaptive button | shipped | `e233b2c` + fix-ups |
| **E5 — Dollar tier with WCAG markup** | **shipped — UNDER REVIEW** | **`10f52c9` + `57ad1c5`** |
| E6 — Feature flag the v3 UI | next | (depends on A8 for citizen-visible effect) |
| F1-F5 — Category landing pages, RSS, etc. | pending | — |
| G1-G4 — Admin views | pending | — |
| **A8 — Cross-track: extend AgendaItem + query** | **must precede E6** | — |

5 of 15 tasks complete. Track 3 finishes when all E/F/G tasks ship + A8.
