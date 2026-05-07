# Docket.pub Impact-First Refactor — Design Doc

**Date:** 2026-05-05
**Status:** In progress (brainstorming session, working draft)
**Repo:** thinkdarrell/docket-pub
**Builds on:** existing AI pipeline live since 2026-05-02 (`src/docket/ai/`)

> Working draft. Final canonical version will land at `docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md` once approved. This file is updated in place as we work — no version suffixes.

---

## Locked decisions

| # | Decision | Resolution |
|---|---|---|
| 1 | Build order | **C → A → B** — structured extraction first, then Smart Brevity, then strategic badges |
| 2 | Badge taxonomy | **Hybrid** — process layer (city-agnostic) + policy layer (per-city, editorial) |
| 3 | Stage 1 extraction fields (v1) | **6 fields**: funding source, counterparty, procurement method, location, action type (with appointment sub-types), next steps |
| 4 | Pipeline architecture | **Layer in**, don't replace. ~1-2 LLM calls per item, not 3. |
| 5 | Smart Brevity output shape | Replace `summary` with `headline` (≤60 chars) + `why_it_matters` (≤200 chars) |
| 6 | Banned-words list | Hard ban: Whereas, Heretofore/Hereinafter/Hereby/Hereto/Hereof, Notwithstanding, Aforesaid/Aforementioned, Pursuant to, Be it resolved, In the matter of, For and on behalf of. Soft replace: Appropriation→"set aside", Resolution→"decision/vote", Ordinance→"law/rule", Procurement→"buy", Allocation→"set aside", Encumber→"commit funds", Authorize→"approve" |
| 7 | Process badges (v1, all deterministic) | **7 badges**: 💰 Hidden on consent (consent_placement_score ≤ 3) · 🤝 Sole-source/no-bid · ⚖️ Legal settlement · 🪧 Split vote · 🔥 Contested · ↩️ Amends prior contract · 🚨 Emergency action. *(Updated by decisions #52 split-vote → two badges and #58 rename amends_prior_contract.)* |
| 8 | Policy badges (Birmingham 2026) | 4 badges: 🏚️ Blight Accountability · 🏠 Housing Stability · 🏗️ Property Recovery · 🛡️ Public-Safety Tech & Privacy |
| 9 | Policy-badge matching | Hybrid: Stage 2 LLM `suggested_badge_slugs` + per-city deterministic rules. Confidence: both/one/neither. |
| 10 | UI scope (v1) | Smart Brevity Card + per-badge category landing pages + "Browse by Priority" homepage section |
| 11 | Multi-city scope | All 4 cities Stage 1+2 + process badges. Birmingham only for policy badges in v1. |
| 12 | Backfill scope | Checkpointed waves 2026 → 2021 → 2017 via Anthropic Batches API. **~$119 with Batches API** (~$287 if forced to sync API). Cost reduced further by Wave 0 procedural skip (decision #78) — actuals depend on Wave 0's pending-item count. |
| 13 | Relevance pre-filter (Stage 0b) | Deterministic regex + Stage 2 procedural-skip fallback. ~10-15% items skip both LLM calls. |
| 14 | Score-floor table (LOCKED) | Tier-aligned table in Section 1. All overrides logged in `score_overrides JSONB`. |
| 15 | Historical data strategy | Re-process all into new schema. No legacy view. |
| 16 | Source-document anchoring | `source_anchor JSONB`. Page-level v1 floor. bbox opportunistic. Degradation chain in Section 1. |
| 17 | Engagement hooks (next_steps) | 6th Stage 1 field. Best-effort, all sub-fields nullable. |
| 18 | Idempotent pipeline | Local response cache + atomic per-item commit + `ai_processed_at_version INT` progress tracking. |
| 19 | Degraded mode | Pre-Stage-0a quality gate. `data_quality` enum with priority-tagged admin queue. |
| 20 | Threshold consistency | All score-floor triggers derive from existing dollar-tier color system. |
| 21 | Appointment sub-classification | `appointment_executive` / `appointment_board` / `appointment_advisory` with per-sub-type score floors. |
| 22 | Backfill transition strategy | Progressive switchover. v3 UI ships immediately; per-item fallback chain. |
| 23 | Source-anchor degradation chain | bbox → page → doc URL → "OCR needed" badge. UI adapts View Source button per available level. |
| 24 | Next-steps best-effort | Stage 1 only populates explicit fields, never infers. UI engagement strip auto-hides when fully null (with master-calendar fallback link — see #29). |
| 25 | Dead-letter handling | `processing_attempts INT` + retry ceiling at 3 attempts + `failed_permanent` status. |
| 26 | Regex improvement via telemetry (Stage 0b) | No separate LLM-light classifier. Daily report logs items where Stage 2 returned `is_substantive=false` but Stage 0b regex didn't match. Self-improving filter. Revisit if >5% of skips still happen at Stage 2 after 30 days live. |
| 27 | Threshold-divergence calibration alerts | Daily admin job queries `score_overrides` for `\|boosted_score - original_ai_score\| > 3`. `score_overrides` JSONB records `original_ai_score` + `final_score`. |
| 28 | Badge Template Library | New table `priority_badge_templates` (catalog). `priority_badges_config` references templates with optional per-city overrides. Birmingham's 4 v1 badges seed the catalog. |
| 29 | Master-calendar fallback | New `municipalities.master_calendar_url`. Engagement strip falls back to "Check city's master calendar" when next_steps is fully null. |
| 30 | Failed-permanent rendering | `processing_status='failed_permanent'` items render Title + 🚧 "Processing Error — [report]" badge. Searchable, citizen-visible. |
| 31 | Priority-tagged OCR queue | Stage 0a sets `data_debt_priority enum('low', 'normal', 'high')` for `data_quality != 'ok'` items based on cheap title heuristics. |
| 32 | "Notify Me When Ready" — deferred | Requires citizen accounts. v1: public `/al/<city>/data-debt` page. Phase 4 adds opt-in email. |
| 33 | Task-level concurrency lock | `pg_try_advisory_lock(hash('docket.<task_name>'))` wraps each worker task. If lock unavailable: no-op + Healthchecks `not-running` ping. |
| 34 | Migration phasing for null-safety | Migration 013 strictly additive. Migration 014 drops legacy `summary` only after backfill confirms v3 outputs landed. No frontend dark period. |
| 35 | Three-layer financial guardrails | (a) `AI_DAILY_BUDGET_USD` soft cap + Healthchecks `budget_exceeded` ping. (b) `AI_PER_RUN_BUDGET_USD` ($5) hard cap halts mid-run. (c) `AI_PER_ITEM_INPUT_TOKEN_CAP` (50K) → item to `failed_retry`. |
| 36 | Funding-source enum expansion | Added `tif` (Tax Increment Financing) and `capital_improvement` (CIP-funded). |
| 37 | Location detail — parcel_id | `LocationDetail.parcel_id: str \| None` — county tax-assessor PIN, enables direct linking to assessor records. |
| 38 | Next-steps — public_hearing_time | `NextSteps.public_hearing_time: str \| None` — accessibility lens (business hours vs evening). |
| 39 | Action-type expansion | Added: `annexation`, `liquor_license`, `right_of_way`, `bid_rejection`. Split `abatement` → `weed_abatement` (low sig) + `tax_abatement` (high sig). |
| 40 | Procedural regex (Alabama-context) | Added 5 patterns: vouchers/bills/payroll, claims, recognition of visitors, awards/presentations, reading of communications/petitions. |
| 41 | Priority-keyword tunes | High: + `annexation`, `rezoning`, `variance`, `easement`. Low: + `travel authorization`, `membership dues`, `notary bond`. |
| 42 | Cache key includes exact model ID | Cache key uses model ID returned in Anthropic response (e.g., `claude-haiku-4-5-20251001`), not the alias. |
| 43 | Body-equals-title heuristic for `no_text_layer` | Replaced ALL-CAPS check with `body.lower() == title.lower() AND len(body) < 200`. |
| 44 | Tax-abatement score floor | `action_type='tax_abatement'` AND `dollars_amount >= $250K` → min `significance_score = 7`. Tax abatements often look small in the resolution body but represent millions in foregone revenue. |
| 45 | Cross-stage reconciliation in service layer | New `docket/ai/reconcile.py` runs after both stages, before commit. If Stage 1 extracted counterparty / funding / dollars but Stage 2 says `is_substantive=False` → conflict. Default action: auto-retry Stage 2 once with override prompt; if still conflicting, set `processing_status='cross_stage_conflict'` and escalate to admin queue. Pydantic per-stage models stay focused on structural validity. |
| 46 | Subject-matter floors (surveillance / police oversight / eminent domain) | New `SUBJECT_MATTER_FLOORS` table independent of `action_type`. Detection by keyword regex on title+description OR `suggested_badge_slugs` membership. Boost `significance_score` to ≥ 7; lower `consent_placement_score` to ≤ 2. Surveillance kept at sig=7 (not 8) — sig=8 reserved for orange-tier settlements; policy-badge handles category-level surfacing. v1 reuses `consent_placement_score` as controversy proxy; if conflation proves lossy, add dedicated `controversy_score` in v2. |
| 47 | Resident-first prompt framing | Update item prompt v3 system prompt to be prescriptive about resident impact: explicitly enumerate consequence categories (taxes, commute, property rights, utility costs, neighborhood safety) and contrast city-first vs resident-first framing with examples. |
| 48 | Per-city score-floor overrides | New table `city_score_floor_overrides (city_id, trigger_name, override_threshold_amount, override_min_score)`. Empty in v1 — all 4 AL cities share Alabama-scale defaults. Lookup function hot-paths overrides. Trigger predicates stay code-defined; only thresholds and bounds are per-city tunable. Admin UI deferred to Phase 4. |
| 49 | Directional bias + drift tracking | Calibration rollup splits into two named alerts: **Under-scoring Impact** (% of items needing sig boost > 20% per action_type/7-day window) and **Over-scoring Consent** (% needing consent reduction > 20%). Percentage-based threshold avoids high-volume false alarms. Separate "AI baseline drift" query tracks `AVG(significance_score)` per action_type week-over-week — catches systematic under-scoring even when no override fires. |
| 50 | Section-3 polish pass | Pydantic validators reject empty/whitespace strings (`headline and len(headline.strip()) > 0`). Reconciliation triggers extended to include `liquor_license`, `right_of_way`, and subject-matter regex matches (surveillance / police-oversight / eminent-domain). Subject-matter floors raised: eminent domain → sig=8, police oversight → sig=8, surveillance stays sig=7. Item prompt v3 adds explicit negative instruction against city-first/procedural cliché ledes. |
| 51 | Cost-increase amendment v1 simplification | Fire on ANY `action_type='contract_amendment'` with prior `contract_award` from same counterparty (trigram similarity ≥ 0.6, same city). Drop strict $ comparison — `dollars_amount` is the regex-extracted largest dollar, not always the new total, so amendments that only state the delta would silently miss. Confidence drops to **0.6**. Description updated to "modifies a prior contract with this vendor; may or may not increase total cost." Phase 4 adds precision via Stage 1 `dollars_breakdown` (delta vs total) + entity normalization. |
| 52 | Split-vote → two badges | 🪧 **Split vote** (1+ no/abstain) and 🔥 **Contested** (2+ no/abstain). `contested` is strict subset of `split_vote` (both fire when 2+ dissent). UI collapses: shows "🔥 Contested" with vote count when both fire, "🪧 Split" when only split fires. |
| 53 | Hidden-on-consent confidence guard | Predicate tightens: `consent_placement_score <= 3 AND (ai_confidence IN ('high','medium') OR Stage 2.5 deterministic floor fired)`. Defends against AI miscalibration on low-confidence outputs while still firing on Red-tier $ / sole-source / settlement / exec-appointment items where the deterministic floor overrides AI confidence anyway. |
| 54 | Emergency action title regex | SQL adds `OR title ~* '\b(emergency\|exigent\|expedited)\b'` to the existing action_type / procurement_method clauses. Catches Alabama-common phrasing like "Ratifying an emergency repair…" without overfiring on generic "ratifying" titles. |
| 55 | Process-badge latency accepted as design | Split-vote and cost-increase badges depend on data (member_votes, cross-item lookups) that lands later anyway — up to 24h after item creation. No special "pending" UI state in v1; documented in cron-worker runbook. |
| 56 | Contested = ≥2 AND >20% of votes cast | Hybrid threshold: `n_dissent >= 2 AND (n_dissent::float / n_voting) > 0.20`. Avoids over-firing on large councils (Homewood's 11 members → needs 3 dissents instead of 2). Documented as Alabama-default; per-city overrides via existing `city_score_floor_overrides` pattern. |
| 57 | Manual badge preservation in cleanup | Nightly process-badge cleanup excludes `source='manual'` rows so admin overrides aren't silently overwritten. SQL: `DELETE … WHERE kind='process' AND source != 'manual'`. |
| 58 | `amends_prior_contract` slug + drop $-filter | Rename `cost_increase_amendment` → `amends_prior_contract`. Drop `dollars_amount > 0` requirement so time-only and scope-only amendments fire too. Phase 4 reintroduces strict `cost_increase_amendment` slug once delta-vs-total distinction is reliable. |
| 59 | Trigram threshold = **0.6** (v1 default, tightened from 0.5) | Counterparty fuzzy match uses `similarity(a, b) >= 0.6` — reduces false positives on generic vendor names while still capturing legitimate punctuation/suffix variants ("Acme Inc" / "Acme Industries Inc"). Per-city override available via `city_score_floor_overrides`. Loosen to 0.5 if 30-day false-negative rate is too high. |
| 60 | Regex flag in matcher_hints | Keyword entries can be plain strings (escaped) OR `{"pattern": "...", "is_regex": true}` for sophisticated patterns. Invalid regex → log warning + skip (never crash matcher). Strings remain `re.escape`-d with word boundaries. |
| 61 | Significance gating for policy badges (REVISED) | **Render-time** gate at `significance_score >= 3`. Matcher always writes the badge row to `agenda_item_badges`; the gate lives in the **service layer** (`list_items_by_badge` query in `services/query.py`, plus the equivalent in search and admin views) so all read paths share it. Per-badge threshold from `priority_badges_config.matcher_hints_override.min_significance` overrides the global default. More flexible than matcher-time gating — admin UI can later tune the threshold per-city without re-running matchers. |
| 62 | `matching_metadata JSONB` on agenda_item_badges | Records the exact trigger that fired: `{"matched_keyword": "BPRA"}`, `{"matched_action_type": "demolition"}`, `{"matched_topic": "housing"}`, or combinations. Enables fast admin debugging of over-firing patterns. |
| 63 | `excluded_action_types` in matcher_hints | Hard guard before inclusion checks. Defaults seeded per badge (every policy badge excludes `liquor_license`, `proclamation`, `appointment_advisory`; some add more). Prevents category contamination. |
| 64 | UI badge ordering — process before policy | Process badges always occupy first visible slots, sorted by alarm level (hidden_on_consent → legal_settlement → contested → sole_source → emergency_action → split_vote → amends_prior_contract). Policy badges second, by confidence then alphabetical. Section 6 specs full rendering. |
| 65 | `agenda_item_badges_audit` log + false-positive tracking | New table logs admin add/remove/modify events with actor, role, reason, timestamp. Calibration `policy_badge_calibration` task adds "Top False Positives" query: badges admins removed >5 times in 7 days. Also formalizes manual-badge preservation (decision #57) audit trail. |
| 66 | Mobile Brevity-First layout (<768px) | Badge chips collapse to horizontal scroll-snap row ABOVE the headline. Headline + why_it_matters become first content in viewport. Desktop unchanged. CSS-only via `@media (max-width: 768px)`. |
| 67 | Verification Spark for high-confidence badges | ✨ icon appended to 1.0-confidence badge chips. 0.6-confidence chips bare. Replaces outlined-vs-solid as the primary confidence signal (additive marking reads faster than subtractive). |
| 68 | Consent Baseline overlay on volume timeline | SVG renders a second data series — overlay line or split bar showing % of items in each bucket that landed on consent. Surfaces the "stated priority vs actually-deliberated" gap. |
| 69 | bbox highlight in PDF deferred to Phase 4 | Browser-native PDF viewers don't support programmatic bbox highlight via URL fragments — only `#page=N`. v1 ships page-jump only (already in source-anchor degradation chain #16/23). Phase 4 embeds PDF.js with annotation overlay alongside bbox capture work. |
| 70 | Context-aware engagement strip for `public_hearing_set` | When `action_type='public_hearing_set'` AND `public_hearing_date IS NULL`, render "Awaiting hearing date — [📅 Subscribe to upcoming hearings RSS →]" linking to new feed at `/al/<city>/upcoming-hearings.rss`. RSS-based; no notification subsystem required. |
| 71 | Dollar-tier accessibility symbols | Display becomes `$87,500 ($$)` / `$1.8M ($$$$)`. Green=`$`, Yellow=`$$`, Orange=`$$$`, Red=`$$$$`. WCAG 2.1 — color no longer load-bearing for tier perception. |
| 72 | `cross_stage_conflict` UI variant | 6th Smart Brevity Card variant. Renders v3 outputs (headline + why_it_matters + facts) WITH ⚠️ "Verification in progress" pill at top. Honest about the state without hiding partial information. Once admin resolves and `processing_status` flips to `completed`, pill disappears. |
| 73 | Mobile carousel respects strict priority sort | The mobile horizontal scroll-snap row uses the same process-first ordering as decision #64 — oversight badges (Hidden on consent → Settlement → Contested → Sole-source → Emergency → Split → Amends-prior) always occupy the first scroll positions; policy badges follow. Citizens swipe through in order; first-visible signals are always the most time-sensitive. |
| 74 | Badge legend + first-visit popover | City page header gains a one-liner legend: *"Badges show oversight (process) and priorities (policy). ✨ = AI-verified by multiple sources."* Plus a 24h-cookie-gated dismissible first-visit popover on the first city page a citizen visits. Educates users about the spark and the kinds of badges without requiring per-chip hover (which doesn't work on mobile). |
| 75 | ARIA labels for dollar tiers | Each dollar amount renders both visual symbols ($/$$/$$$/$$$$) AND a visually-hidden screen-reader label: `$1.8M ($$$$)<span class="sr-only">, Red tier</span>`. Plus `aria-label="$1.8M, Red tier (over $1 million)"` on the parent for assistive tech that doesn't traverse children. WCAG 2.1 AA compliant. |
| 76 | ~~Actionable modals for "Verification in progress" / "Processing Error"~~ — **RETIRED**. Replaced by lightweight tooltips. Modals were over-engineering for explainers; tooltips do 80% of the work at 10% of the surface area and don't break reading flow. |
| 77 | ~~`data_issue_reports` table + crowdsourced reporting endpoint~~ — **RETIRED for v1**. Replaced by `mailto:` link to admin email. We're a transparency platform, not a CRM — no staffing for triage in v1. The DB schema + admin queue earned their keep only with active moderation. Phase 4 can revisit when citizen accounts exist. |
| 78 | Wave 0 (non-LLM pre-pass) | Combined Stage 0a (data quality) + Stage 0b (procedural regex) across the full ~75K archive BEFORE any paid API calls. Output: every item lands in `procedural_skipped`, `data_quality_skipped`, or `pending`. Wave 0 produces the actual LLM workload count (likely 20-30% smaller than the original 75K estimate) — Wave 1 cost projections recalculated against `pending` items only. Costs $0, takes hours not days. |
| 79 | Significance-sorted dead-letter queue | Admin `/admin/errors` queue sorts by `data_debt_priority DESC, meeting_date DESC`. Same title-driven priority logic as the OCR queue (decision #31). High-impact items (>$1M, settlement, surveillance) jump ahead of routine procedurals regardless of failure date. |
| 80 | Backfill-active banner ~~+ chip tooltip~~ — **BANNER RETIRED**, chip tooltip retained. Card-level "summary updating" chip carries the state info adequately; the global banner was editorial redundancy. Chip tooltip explanation kept (decision #80, second clause): *"This summary is being refreshed as part of an ongoing pipeline update. The underlying data is unchanged."* `BACKFILL_ACTIVE` env var no longer needed. |
| 81 | Adaptive concurrency for 429 resilience | New `docket/ai/concurrency.py` `AdaptiveWorkerPool` — scales worker count down by 1 when ≥5 rate-limit hits in 5 minutes; cool-down period of 10 min before scaling back up. Applied to both backfill driver and live `ai_items` task so backfill never monopolizes rate-limit budget at the cost of new-meeting ingestion. |
| 82 | `backfill_session_id` for atomic rollback | New nullable UUID column on `agenda_items`. Each wave run writes a session UUID to all items it processes. Rollback = single `UPDATE … WHERE backfill_session_id = :uuid` statement. Denormalized (also recoverable via `ai_batch_items` join) but worth the extra column for 2am-incident ergonomics. |
| 83 | Unified search vector for transition consistency | New `agenda_items.search_vector tsvector` column with trigger that coalesces `title + description + headline + why_it_matters + summary`. Search remains reliable for both pre-backfill (v2-only) and post-backfill (v3) items throughout the transition. Trigger function gets a one-line edit to drop the `summary` term at Migration 014. GIN index for sub-50ms FTS queries. |
| 86 | **Big Fish Override** | Stage 0a override: if title contains a HIGH_KEYWORD (`settlement`, `sole source`, `no-bid`, `emergency`, `flock`, `surveillance`, `litigation`, `department head`, `police chief`, `city attorney`, `annexation`, `rezoning`, `variance`, `easement`), force `data_quality='ok'` AND `data_debt_priority='high'` regardless of body length / OCR readiness. Catches "$50M settlement with bad OCR" cases that would otherwise route to the data-debt queue and miss the LLM pipeline. Reuses the existing HIGH_KEYWORDS list from decision #41 (NOT broadened to include "Contract" — too generic). |
| 87 | **Headline density validation** | Pydantic `procedural_consistency` validator tightens substantive-item check: `len(headline.strip()) >= 10` (was `> 0`). Catches "lazy" 1-3 character headlines that pass schema but carry no information. Items failing this go to `failed_retry`; after 3 attempts → `failed_permanent`. |
| 88 | **Wave 0.5 — Live Calibration burst** | Between Wave 0 (non-LLM pre-pass) and Wave 1 (Batches API archive), a small synchronous burst processes items in the **current calendar month** (predicate: `meeting_date >= DATE_TRUNC('month', CURRENT_DATE)`) via the standard Anthropic API. Trades higher per-item cost for ~4-hour turnaround instead of 1-2 days for Batches API. **Stays sync** even under rate-limit pressure — uses linear-backoff retry through `AdaptiveWorkerPool` (decision #81) rather than falling back to Batches API, because instant feedback is required for prompt calibration. Cost: ~$8 for the current month. Citizens see v3 cards on the most-watched recent meetings within hours of deploy. |
| 89 | **Amendment Noise Filter** | The `amends_prior_contract` badge SQL adds a negative title/description regex to suppress firing on recurring/routine renewals: `NOT (title \|\| description) ~* '\b(recurring\|monthly invoice\|annual renewal\|routine renewal\|periodic billing)\b'`. Catches false positives where a vendor has a prior contract but the current item is a non-substantive recurring billing. Confidence stays at 0.6. |
| 90 | **RSS feed caching** | Public RSS endpoints (`/al/<city>/data-debt.rss`, `/al/<city>/upcoming-hearings.rss`) get a **60-minute XML-specific cache** layered above the Flask handler. Aggressive RSS-reader polling (some clients refresh every 1-5 minutes) would otherwise hammer the DB. Cache invalidates on the 60-minute boundary; manual flush available via admin endpoint when urgent updates land. Implementation: Flask `@cache.cached(timeout=3600, query_string=True)` decorator on the RSS routes. |
| 84 | OCR queue priority-sort UI ships in Phase 2 | The `/admin/data-debt` route MUST sort by `data_debt_priority DESC, meeting_date DESC` from initial Phase 2 deploy — not added later. Otherwise admins start working the queue without the priority signal even though the underlying data is already populated by Wave 0. Reinforces decisions #31 + #79. |
| 85 | ~~Render-time legalese softener~~ — **RETIRED**. Dead code after a 14-day transition window isn't worth shipping. The transition is bounded; the chip + natural backfill progression mitigate the inconsistency adequately. Removing avoids regex-on-prose grammatical risk and dead-code maintenance. |

---

## Open questions

**Zero open questions.** All decisions resolved.

---

## Architectural context (current state, May 2026)

- Existing AI pipeline: 1 Haiku 4.5 call per substantive item (summary + 2 scores + procedural skip), 1 Sonnet 4.6 call per meeting (executive summary, distinctive-vs-routine split)
- Live on Railway since 2026-05-02. Cron worker live since 2026-05-04.
- Two-phase lifecycle keyed off `meetings.minutes_adopted_at`
- Existing dollar tiers: **Green <$50K · Yellow $50-250K · Orange $250K-1M · Red >$1M**
- 240+ tests; daily budget gate via `AI_DAILY_BUDGET_USD`
- Cost: ~$0.0026/item, ~$0.0085/meeting

---

## Section 1 — Architecture overview

### Pipeline shape

```
Per item:

  Stage 0a [NEW]      — Data-quality gate. Title + description length, OCR
                         readability, agenda body presence.
                         Sets data_quality enum + data_debt_priority.
                         If not 'ok' → skip Stages 1+2, render degraded card.

  Stage 0b [NEW]      — Relevance pre-filter (deterministic title regex).
                         If matched → set processing_status='procedural_skipped',
                         skip Stages 1+2.
                         Telemetry loop expands regex over time.

  Stage 1 [NEW]       — Haiku 4.5 + cache_control. Extracts 6 structured fields.
                         Captures source_anchor (bbox/page/doc/OCR-needed).
                         Local response cache keyed by sha256(model_id + version + input).

  Stage 2 [EVOLVED]   — Haiku 4.5. Item prompt v2 → v3.
                         Consumes Stage 1 JSON + raw text.
                         Produces: headline (≤60 chars), why_it_matters
                         (≤200 chars), significance_score, consent_placement_score,
                         suggested_badge_slugs[], confidence.
                         Banned-words list applied in prompt.
                         Replaces existing `summary` field.

  Stage 2.5 [NEW]     — Score-floor post-pass. Deterministic.
                         Boosts significance_score, lowers consent_placement_score
                         per the tier-aligned table. Logs all overrides with
                         original_ai_score + final_score for divergence queries.

  Process badges [NEW]   — Deterministic SQL post-pass. No LLM. 7 badges.

  Policy badges [NEW]    — Hybrid: Stage 2's suggested_badges + per-city
                            deterministic rules. Confidence: both/one/neither.

  Atomic commit       — All stages written in one DB transaction. All-or-none.
                         pg_try_advisory_lock at task level prevents overlap.

Per meeting:
  Sonnet 4.6 [UNCHANGED] — Existing executive summary continues unchanged in v1.
```

### Score-floor table (LOCKED, tier-aligned)

**Boost `significance_score` (never reduce):**

| Trigger | Min `significance_score` |
|---|---|
| Red+ tier (`dollars_amount >= $10M`) | 9 |
| Red tier (`dollars_amount >= $1M`) | 7 |
| Orange tier (`>= $250K`) AND `procurement_method='sole_source'` | 7 |
| Orange tier (`>= $250K`) AND `action_type='settlement'` | 8 |
| Yellow tier (`>= $50K`) AND `procurement_method='sole_source'` | 6 |
| Yellow tier (`>= $50K`) AND `action_type='settlement'` | 6 |
| `action_type='settlement'` (any $) | 6 |
| `action_type='zoning'` AND (parcels >= 5 OR acres >= 10) | 7 |
| `action_type='emergency_procurement'` | 7 |
| `action_type='appointment_executive'` | 7 |
| `action_type='appointment_board'` | 5 |
| `action_type='appointment_advisory'` | (no floor) |
| `action_type='tax_abatement'` AND `>= $250K` | 7 |

**Lower `consent_placement_score`:**

| Trigger | Max `consent_placement_score` |
|---|---|
| Red tier AND `is_consent=TRUE` | 2 |
| `procurement_method='sole_source'` AND `is_consent=TRUE` | 2 |
| `action_type='settlement'` AND `is_consent=TRUE` | 1 |
| `action_type='appointment_executive'` AND `is_consent=TRUE` | 2 |

### Source-anchor graceful degradation

```
PDF:    {type, url, page, bbox}  →  {type, url, page}  →  {type, url}  →  data_quality='no_text_layer'
HTML:   {type, url, anchor}      →  {type, url}
Video:  {type, url, timestamp_seconds}
```

### Backfill transition (progressive switchover)

| Item state | UI rendering |
|---|---|
| v3 outputs present | Smart Brevity Card (full) |
| v2 outputs present, v3 not yet | Smart Brevity Card with v2 `summary` as `why_it_matters`, no `headline`, "summary updating" chip |
| `data_quality != 'ok'` | Degraded card: "Source needs OCR — [Report] [View original]" with `data_debt_priority` shown to admins |
| `processing_status='procedural_skipped'` | Title-only render |
| `processing_status='failed_permanent'` | Title-only render + 🚧 "Processing Error — [report]" badge |

### Engagement strip rendering logic

```
IF next_steps has any populated field:
   render populated fields
   AND append master calendar link as tail option
ELSE IF municipalities.master_calendar_url IS NOT NULL:
   render only "📅 Check Birmingham's master calendar →"
ELSE:
   strip is hidden
```

### Operational guardrails

**Concurrency model:**

```
Per task:
  acquire pg_try_advisory_lock(hash('docket.' + task_name))
  IF lock acquired:
    run task body (per-item SELECT FOR UPDATE SKIP LOCKED applies)
    release lock (auto on session end)
  ELSE:
    log "task already running"
    Healthchecks ping with body 'not-running'
    return (no-op)
```

Applies to all 7 worker tasks.

**Migration phasing:**

| Migration | Contents | When |
|---|---|---|
| 013 | All new columns and tables (additive only) | Before backfill begins |
| 014 | DROP `agenda_items.summary` | After backfill query confirms v3 outputs landed for all items |

**Financial guardrails:**

| Guardrail | Default | Override | Behavior on breach |
|---|---|---|---|
| `AI_DAILY_BUDGET_USD` | $10 ($30 backfill) | `--force-budget` | Refuse new batches + Healthchecks `budget_exceeded` ping |
| `AI_PER_RUN_BUDGET_USD` | $5 | `--force-run-cap` | Halt current task mid-run |
| `AI_PER_ITEM_INPUT_TOKEN_CAP` | 50K | `--force-token-cap` | Item → `failed_retry` with `input_too_large` error |

### Cost & cadence

- ~$0.005/item raw (sync API); with Stage 0 procedural skip (~10-15%) effective ~$0.0042-0.0045/item
- Backfill: ~75K items × 4 cities, after Wave 0 procedural skip ≈ ~50K LLM-processed items ≈ **~$119 via Anthropic Batches API** (50% discount). Sync-API alternative would be ~$287. See Section 7.1 for the full wave-by-wave breakdown.
- Worker tasks evolve:
  - `ai_items` does Stages 0→2.5 in sequence per item (atomic commit)
  - New `process_badges` task (cheap SQL pass)
  - Policy badges generated within Stage 2 (no separate task)
  - New daily `calibration_report` task (divergence + Stage 0b regex misses)

### Schema changes (full inventory)

**New columns on `agenda_items`:**

| Column | Type | Purpose |
|---|---|---|
| `extracted_facts` | JSONB | Stage 1 output: 6 structured fields |
| `headline` | TEXT (≤60 chars) | Smart Brevity headline |
| `why_it_matters` | TEXT (≤200 chars) | Resident-impact lede |
| `source_anchor` | JSONB | bbox/page/anchor/timestamp deep-link metadata |
| `data_quality` | ENUM | ok / no_text_layer / no_agenda_text / empty / foreign_language |
| `data_debt_priority` | ENUM | low / normal / high |
| `processing_status` | ENUM | pending / procedural_skipped / data_quality_skipped / extracted / rewritten / badged / completed / failed_retry / failed_permanent |
| `processing_attempts` | INT DEFAULT 0 | Retry counter |
| `last_error_at` | TIMESTAMP | Last failure time |
| `last_error_message` | TEXT | Last failure detail |
| `score_overrides` | JSONB | Audit log; includes `original_ai_score` + `final_score` |
| `ai_extraction_version` | INT | Stage 1 prompt version |
| `ai_rewrite_version` | INT | Stage 2 prompt version |

**New column on `municipalities`:**

| Column | Type | Purpose |
|---|---|---|
| `master_calendar_url` | TEXT NULLABLE | City's published calendar URL |

**New tables:**

| Table | Purpose |
|---|---|
| `agenda_item_badges` | `(agenda_item_id, badge_slug, kind, confidence, source)` |
| `priority_badge_templates` | `(slug, name, description, icon, default_matcher_hints)` |
| `priority_badges_config` | `(city_id, template_slug, name_override?, description_override?, matcher_hints_override?, enabled)` |

**Deprecated, dropped after backfill:** `agenda_items.summary`.

---

## Section 2 — Stage 0 + Stage 1 detail

### 2.1 Stage 0a — Data-quality gate

```python
def evaluate_data_quality(item: AgendaItem) -> tuple[DataQuality, DataDebtPriority]:
    # Big Fish Override (decision #86): high-impact title keywords force
    # data_quality='ok' regardless of body length / OCR readiness.
    # Prevents big-money or transparency-critical items from getting routed
    # to the data-debt queue and missing the LLM pipeline.
    if _is_big_fish(item.title):
        return ('ok', 'high')

    if not item.title or len(item.title.strip()) < 5:
        return ('empty', _priority_from_title(item.title))

    body = item.description or item.raw_text or ''
    body_clean = body.strip()

    if not body_clean:
        return ('no_agenda_text', _priority_from_title(item.title))

    if len(body_clean) < 50 and item.source_type == 'pdf':
        return ('no_text_layer', _priority_from_title(item.title))

    # body equals title (PDF parser fell back to title-only)
    if (body_clean.lower().strip() == (item.title or '').lower().strip()
            and len(body_clean) < 200):
        return ('no_text_layer', _priority_from_title(item.title))

    if _is_likely_foreign_language(body_clean):
        return ('foreign_language', _priority_from_title(item.title))

    return ('ok', 'normal')


def _is_big_fish(title: str | None) -> bool:
    """Big Fish Override (decision #86) — uses HIGH_KEYWORDS from
    _priority_from_title plus dollar regex matching Red tier."""
    if not title:
        return False
    t = title.lower()
    if any(kw in t for kw in _HIGH_KEYWORDS):
        return True
    if _extract_dollars_regex(title) >= 1_000_000:
        return True
    return False


def _priority_from_title(title: str) -> DataDebtPriority:
    if not title:
        return 'normal'
    t = title.lower()

    HIGH_KEYWORDS = (
        'settlement', 'sole source', 'sole-source', 'no-bid', 'no bid',
        'emergency', 'flock', 'surveillance', 'litigation',
        'department head', 'police chief', 'city attorney',
        'annexation', 'rezoning', 'variance', 'easement',
    )
    LOW_KEYWORDS = (
        'fleet', 'fuel', 'tires', 'maintenance', 'office supplies',
        'mileage', 'travel reimbursement', 'minutes',
        'travel authorization', 'membership dues', 'notary bond',
    )

    if _extract_dollars_regex(title) >= 1_000_000:
        return 'high'
    if any(kw in t for kw in HIGH_KEYWORDS):
        return 'high'
    if any(kw in t for kw in LOW_KEYWORDS):
        return 'low'
    return 'normal'
```

#### Big Fish Override examples

| Title | Body state | Big Fish? | Final state |
|---|---|---|---|
| "Settlement of Smith vs. City for $250,000" | empty | ✓ ("settlement") | `data_quality='ok'`, priority='high' — proceeds to LLM |
| "Sole-source extension: Flock cameras 5yr $1.8M" | empty | ✓ ("sole source", "flock", >$1M) | `data_quality='ok'`, priority='high' — proceeds to LLM |
| "Ratifying emergency repair of water main #4" | image-only PDF | ✓ ("emergency") | `data_quality='ok'`, priority='high' — proceeds to LLM |
| "Eminent domain proceeding for Highway 280 expansion" | body=title | ✓ (matches HIGH_KEYWORDS) | `data_quality='ok'`, priority='high' — proceeds to LLM |
| "Approval of fleet fuel purchase" | empty | ✗ | `data_quality='no_agenda_text'`, priority='low' — degraded card |
| "Authorizing professional services agreement" | image-only PDF | ✗ | `data_quality='no_text_layer'`, priority='normal' — degraded card |
| "Routine maintenance contract amendment" | body too short | ✗ | `data_quality='no_text_layer'`, priority='low' — degraded card |

The override is intentionally **conservative**: it only fires for items
whose TITLE alone signals high impact. Items with potentially-significant
body content but unremarkable titles still route through the data-debt
queue where they're sorted by `data_debt_priority` for admin OCR
follow-up.

### 2.2 Stage 0b — Relevance pre-filter (regex)

```python
PROCEDURAL_TITLE_PATTERNS = (
    r'^\s*roll\s+call',
    r'^\s*(call to|opening of)\s+(public\s+)?comments?',
    r'^\s*pledge\s+of\s+allegiance',
    r'^\s*invocation',
    r'^\s*moment\s+of\s+silence',
    r'^\s*motion\s+to\s+adjourn',
    r'^\s*adjournment',
    r'^\s*recess',
    r'^\s*approval\s+of\s+(prior|previous|the)?\s*minutes',
    r'minutes\s+(not\s+)?(yet\s+)?(ready|available|received)',
    r'^\s*reading\s+of\s+(the\s+)?minutes',
    r'^\s*proclamations?\s*$',
    r'^\s*public\s+comment\s+period',
    r'^\s*executive\s+session',
    # Alabama council common patterns:
    r'^\s*(vouchers?|bills?|payroll)\s+for\s+payment',
    r'^\s*approval\s+of\s+claims',
    r'^\s*recognition\s+of\s+(visitors?|guests?)',
    r'^\s*awards?\s+and\s+presentations?',
    r'^\s*reading\s+of\s+(communications?|petitions?)',
)
```

Daily `calibration_report` task:

```sql
SELECT title, COUNT(*)
FROM agenda_items
WHERE ai_rewrite_version = (SELECT current_rewrite_version)
  AND extracted_facts->>'is_substantive' = 'false'
  AND processing_status != 'procedural_skipped'
GROUP BY title
ORDER BY 2 DESC
LIMIT 50;
```

Surfaces titles where Stage 2 declared procedural but regex missed. Admin reviews monthly, expands `PROCEDURAL_TITLE_PATTERNS` via PR.

### 2.3 Stage 1 — Structured fact extraction

**Model:** Haiku 4.5. **Cache control:** system prompt + JSON schema example get `cache_control: ephemeral`.

```python
class StructuredFacts(BaseModel):
    funding_source: Literal[
        'general_fund', 'arpa', 'esser', 'cares', 'state_grant',
        'federal_grant', 'bond', 'special_tax', 'private', 'sponsorship',
        'tif', 'capital_improvement',
        'mixed', 'unknown'
    ]
    counterparty: str | None
    procurement_method: Literal[
        'competitive', 'sole_source', 'no_bid', 'rfp',
        'emergency', 'unknown', 'not_applicable'
    ]
    location: LocationDetail | None
    action_type: Literal[
        'contract_award', 'contract_amendment', 'ordinance', 'resolution',
        'appointment_executive', 'appointment_board', 'appointment_advisory',
        'zoning', 'demolition',
        'weed_abatement', 'tax_abatement',
        'settlement', 'emergency_procurement',
        'appropriation', 'budget_amendment',
        'proclamation', 'public_hearing_set',
        'annexation', 'liquor_license', 'right_of_way', 'bid_rejection',
        'other'
    ]
    next_steps: NextSteps
    parcels_affected: int | None
    acres_affected: float | None


class LocationDetail(BaseModel):
    ward_or_district: str | None
    neighborhood: str | None
    address: str | None
    parcel_id: str | None


class NextSteps(BaseModel):
    committee_referral: str | None
    public_hearing_date: date | None
    public_hearing_time: str | None
    comment_period_end: date | None
    implementation_date: date | None
```

System prompt sketch:

```
You extract structured facts from a single municipal-government agenda item.
You output JSON matching the schema below — no prose, no markdown, no commentary.

Do not invent facts. If a field cannot be determined from the input, return null.

For action_type='appointment*', also classify the appointment as one of:
  - appointment_executive: Mayor's cabinet, Department Head, Police Chief,
    City Attorney, City Clerk, Finance Director, Fire Chief, Library Director
  - appointment_board: Board of Education, Board of Adjustment, Planning
    Commission, Housing Authority, Library Board, BJCTA, IDB
  - appointment_advisory: citizen advisory committees, task forces,
    ad-hoc bodies, ceremonial proclamation honorees

For procurement_method, choose the most specific applicable value:
  - competitive, sole_source, no_bid, rfp, emergency, unknown, not_applicable

For next_steps, extract ONLY explicitly-stated future actions.
Do not infer. If the resolution doesn't say "set for public hearing on June 5,"
do not populate public_hearing_date.

Return ALL the schema's keys; use null when unknown.
```

Pydantic validation runs on every Haiku response. Validation failure → `processing_status='failed_retry'`. After 3 attempts → `failed_permanent`.

#### Example extracted_facts outputs

**Example 1 — Sole-source tech contract (good extraction):**

Input title: *"Resolution authorizing sole-source extension of Flock Safety license agreement for $1,800,000 over five years, funded by general fund."*

```json
{
  "funding_source": "general_fund",
  "counterparty": "Flock Safety Inc.",
  "procurement_method": "sole_source",
  "location": {
    "ward_or_district": null,
    "neighborhood": null,
    "address": null,
    "parcel_id": null
  },
  "action_type": "contract_amendment",
  "next_steps": {
    "committee_referral": null,
    "public_hearing_date": null,
    "public_hearing_time": null,
    "comment_period_end": null,
    "implementation_date": null
  },
  "parcels_affected": null,
  "acres_affected": null
}
```

**Example 2 — Tax abatement (good extraction):**

Input title: *"Ordinance granting tax abatement to ABC Manufacturing for $4.2M facility investment in District 7, with public hearing set for July 15, 2026 at 6:00 PM."*

```json
{
  "funding_source": "tif",
  "counterparty": "ABC Manufacturing",
  "procurement_method": "not_applicable",
  "location": {
    "ward_or_district": "District 7",
    "neighborhood": null,
    "address": null,
    "parcel_id": null
  },
  "action_type": "tax_abatement",
  "next_steps": {
    "committee_referral": null,
    "public_hearing_date": "2026-07-15",
    "public_hearing_time": "6:00 PM",
    "comment_period_end": null,
    "implementation_date": null
  },
  "parcels_affected": null,
  "acres_affected": null
}
```

**Example 3 — Procedural item (correctly returns minimal extraction):**

Input title: *"Approval of minutes from May 1, 2026."*

Stage 0b matches the procedural regex first; Stage 1 is **never invoked**. Item gets `processing_status='procedural_skipped'`.

If somehow Stage 1 IS invoked (Stage 0b regex misses), Stage 1 returns:

```json
{
  "funding_source": "unknown",
  "counterparty": null,
  "procurement_method": "not_applicable",
  "location": null,
  "action_type": "other",
  "next_steps": {
    "committee_referral": null,
    "public_hearing_date": null,
    "public_hearing_time": null,
    "comment_period_end": null,
    "implementation_date": null
  },
  "parcels_affected": null,
  "acres_affected": null
}
```

Stage 2 then catches it via its own procedural-skip logic (item prompt v3) and outputs `is_substantive=false`. The telemetry loop (decision #26) flags the title for inclusion in `PROCEDURAL_TITLE_PATTERNS` next iteration.

**Example 4 — Bad extraction (would fail Pydantic):**

```json
{
  "funding_source": "FederalGrantPlusBond",   // ← not in enum
  "counterparty": "ABC Co.",
  "procurement_method": "competitive_bid",     // ← should be "competitive"
  "action_type": "kontract_award",             // ← typo, not in enum
  "parcels_affected": "five"                   // ← string, should be int
}
```

All three field violations trigger `ValidationError` → `processing_status='failed_retry'`.

### 2.4 Source anchor capture

```python
def build_source_anchor(item: AgendaItem) -> dict | None:
    if item.video_url and item.video_timestamp_seconds:
        return {'type': 'video', 'url': item.video_url,
                'timestamp_seconds': item.video_timestamp_seconds}

    if item.source_pdf_path:
        if item.pdf_position and item.pdf_position.get('bbox'):
            return {'type': 'pdf', 'url': item.source_url,
                    'page': item.pdf_position['page'],
                    'bbox': item.pdf_position['bbox']}
        if item.pdf_position and item.pdf_position.get('page'):
            return {'type': 'pdf', 'url': item.source_url,
                    'page': item.pdf_position['page']}
        return {'type': 'pdf', 'url': item.source_url}

    if item.source_html_anchor:
        return {'type': 'html', 'url': item.source_url, 'anchor': item.source_html_anchor}

    if item.source_url:
        return {'type': 'html', 'url': item.source_url}

    return None
```

v1 ships with **page-level only** for PDFs; bbox capture is a follow-up enhancement requiring minutes-parser changes.

### 2.5 Response cache mechanics

```python
def cache_key(api_response, prompt_version: int, canonical_input: str) -> str:
    # api_response.model is the EXACT model ID returned by Anthropic
    # (e.g., 'claude-haiku-4-5-20251001'), NOT the alias 'haiku-4.5'.
    return hashlib.sha256(
        f"{api_response.model}|v{prompt_version}|{canonical_input}".encode()
    ).hexdigest()
```

```
Path: data/ai_cache/<sha256>.json
Format: { "response": <api_response>, "cached_at": <iso_timestamp> }
```

Cache hit on retry → no Anthropic API call, no cost. Cache survives crashes. Mirrors existing `data/minutes_cache/` pattern. Disk estimate: 75K items × ~3KB × 2 stages = ~450MB max. Cleanup of entries older than 90 days where current prompt version doesn't match.

---

## Section 3 — Stage 2 + Stage 2.5 detail

### 3.1 Item prompt v3 — system prompt

```
You are rewriting a single agenda item for citizens reading docket.pub.

You receive:
  (a) the raw item title + description, and
  (b) structured facts extracted in Stage 1: funding source, counterparty,
      procurement method, location (ward/district, neighborhood, address,
      parcel_id), action type, next steps (committee, hearing date/time,
      comment-period end, implementation date).

FIRST decide: is this a substantive item or a procedural item?

PROCEDURAL items are routine meeting mechanics whose title already
conveys everything: roll call, pledge of allegiance, invocation,
motion to adjourn, approval of prior minutes, opening of public comment,
"minutes not ready" notices, recognition of visitors, awards/presentations,
reading of communications, vouchers/bills/payroll for payment, claims,
recess, executive session close-out. For these:
  - Set is_substantive = false
  - Set headline = null, why_it_matters = null
  - Set both numeric values to null
  - Set rationales = "" (empty)
  - Set suggested_badge_slugs = []
  - Set confidence based on how clearly procedural the item is

SUBSTANTIVE items are decisions, debates, contracts, ordinances,
appointments, zoning cases, settlements, abatements (tax or weed),
liquor licenses, annexations — anything whose outcome matters. For these:

(1) Write a HEADLINE (≤60 chars) — result-oriented, active voice.
    Must be ≥10 characters with substantive content (decision #87).

    Good headlines:
      "Council awards $4.2M HVAC contract to Acme Industries"
      "Settlement: City pays $250K for 2024 use-of-force claim"
      "Sole-source: Flock licenses extended 5 years for $1.8M"
      "BPRA: 14 blighted properties move toward demolition"
      "Land Bank acquires 6 tax-delinquent parcels in District 4"
      "Body-cam footage release rules tighten to 30 days"
      "Annexation: Hidden Lake parcel joins city limits"

    Bad headlines (would fail validation or quality bar):
      "Approval"                    ← too short (<10 chars)
      "Item passed"                 ← lazy, no info
      "Resolution No. 2026-0142"    ← procedural identifier, not content
      "Authorizes Mayor"            ← city-first framing
      "Whereas the Council..."      ← banned legalese
      "$1.8M contract"              ← missing what/who
      "Important decision today"    ← vague, no actor or consequence

(2) Write WHY IT MATTERS (≤200 chars; one sentence preferred, two short
    sentences allowed for items with multiple impact vectors).

    Identify the DIRECT CONSEQUENCE for residents. Ask: will this change
    their taxes, their commute, their property rights, their utility costs,
    or their neighborhood's safety? If no direct consequence exists,
    describe the specific change to public services or city operations.

    Use RESIDENT-first framing, not CITY-first framing.

    Good (resident-first): "Higher water rates for homes in Wards 4 and 7
      starting August. Affects ~3,400 households."
    Good (resident-first): "Smoother commute on Highway 280; project
      finishes summer 2027."
    Good (resident-first): "Body-cam footage rules tighten — police must
      release video within 30 days of force incidents."
    Good (resident-first): "Land Bank takes over abandoned house at 123
      Main; clears tax debt to make it sale-ready."
    Bad (city-first):      "Authorizes the Mayor to enter into an agreement
      to fund operations of the Birmingham Water Works."
    Bad (procedure-first): "Approves contract amendment #4 with vendor X."
    Bad (vague):           "Important policy change affecting residents."
    Bad (jargon-laden):    "Whereas, pursuant to Section 2.31, hereby
      authorizing said procurement of aforesaid services."

(3) Score significance_score 0-10 (0 = trivial, 10 = major impact).
    Write the rationale BEFORE the numeric value.

(4) Score consent_placement_score 0-10 (0 = should never be on consent /
    high public interest; 10 = perfect consent candidate / routine).
    Write the rationale BEFORE the numeric value.

(5) Suggest BADGE SLUGS from the per-city policy badge list provided
    in the user message. Include only badges you are reasonably confident
    apply. Empty list is acceptable.

BANNED WORDS — HARD (avoid entirely):
  Whereas, Heretofore, Hereinafter, Hereby, Hereto, Hereof, Notwithstanding,
  Aforesaid, Aforementioned, Pursuant to, Be it resolved, In the matter of,
  For and on behalf of.

BANNED WORDS — SOFT (replace with natural English):
  Appropriation → "set aside" / "spend"
  Resolution → "decision" / "vote" (or drop entirely)
  Ordinance → "law" / "rule"
  Procurement → "buy" / "purchase"
  Allocation → "set aside"
  Encumber / Encumbrance → "commit funds"
  Authorize (passive) → "approve" / "let"

Write in active voice. Lead with the RESULT, not the PROCESS.

NEGATIVE INSTRUCTIONS — do NOT lead with phrases like:
  "The City Council approved..."
  "This resolution authorizes..."
  "The Mayor is hereby authorized to..."
  "By a vote of X-Y, the Council..."
Start the headline and why_it_matters DIRECTLY with the consequence.

Confidence: "high" if the item's text is unambiguous AND Stage 1 facts
are populated; "medium" if title is clear but details are sparse;
"low" if you had to guess at intent or Stage 1 returned mostly nulls.
```

### 3.2 Item prompt v3 — user message template

```
City: {city_name}
Available policy badge slugs: {policy_badge_slugs_csv}

Title: {title}
Description: {description}
Sponsor: {sponsor}
Dollar amount: {dollars_amount}
Topic (legacy): {topic}
Is on consent agenda: {is_consent}

Stage 1 structured facts:
{extracted_facts_json}
```

The Stage 1 JSON gets injected directly so Sonnet/Haiku can leverage the
pre-extracted facts rather than re-deriving them.

### 3.3 Item prompt v3 — Pydantic output

```python
class ItemRewrite(BaseModel):
    is_substantive: bool
    headline: str | None = Field(None, max_length=60)
    why_it_matters: str | None = Field(None, max_length=200)
    significance_rationale: str = Field("", max_length=1500)
    significance_score: int | None = Field(None, ge=0, le=10)
    consent_placement_rationale: str = Field("", max_length=1500)
    consent_placement_score: int | None = Field(None, ge=0, le=10)
    suggested_badge_slugs: list[str] = []
    confidence: Literal['high', 'medium', 'low']

    @model_validator(mode='after')
    def procedural_consistency(self):
        if not self.is_substantive:
            assert self.headline is None
            assert self.why_it_matters is None
            assert self.significance_score is None
            assert self.consent_placement_score is None
            assert self.suggested_badge_slugs == []
        else:
            # Density validation (decision #87): headline must be ≥10 chars
            # to catch "lazy" outputs that pass schema but carry no info.
            assert self.headline and len(self.headline.strip()) >= 10, \
                "substantive items must have a headline ≥10 characters"
            assert self.why_it_matters and len(self.why_it_matters.strip()) > 0, \
                "substantive items must have a non-empty why_it_matters"
            assert self.significance_score is not None
            assert self.consent_placement_score is not None
        return self
```

Server-side hard truncation also enforced before DB write — defense in
depth against the LLM occasionally exceeding caps.

### 3.4 Stage 2.5 — Score-floor post-pass

```python
@dataclass
class FloorTrigger:
    name: str  # human-readable identifier, e.g. "red_tier_dollars"
    predicate: Callable[[AgendaItem, StructuredFacts], bool]
    score_field: Literal['significance', 'consent_placement']
    bound: int  # MIN for significance, MAX for consent_placement


SIGNIFICANCE_FLOORS: list[FloorTrigger] = [
    # Dollar tiers
    FloorTrigger("red_plus_10m", lambda i, f: (i.dollars_amount or 0) >= 10_000_000,
                 'significance', 9),
    FloorTrigger("red_1m", lambda i, f: (i.dollars_amount or 0) >= 1_000_000,
                 'significance', 7),
    # Orange tier × triggers
    FloorTrigger("orange_sole_source",
                 lambda i, f: (i.dollars_amount or 0) >= 250_000
                              and f.procurement_method == 'sole_source',
                 'significance', 7),
    FloorTrigger("orange_settlement",
                 lambda i, f: (i.dollars_amount or 0) >= 250_000
                              and f.action_type == 'settlement',
                 'significance', 8),
    # Yellow tier × triggers
    FloorTrigger("yellow_sole_source",
                 lambda i, f: (i.dollars_amount or 0) >= 50_000
                              and f.procurement_method == 'sole_source',
                 'significance', 6),
    FloorTrigger("yellow_settlement",
                 lambda i, f: (i.dollars_amount or 0) >= 50_000
                              and f.action_type == 'settlement',
                 'significance', 6),
    # Action-type-only triggers
    FloorTrigger("any_settlement", lambda i, f: f.action_type == 'settlement',
                 'significance', 6),
    FloorTrigger("zoning_large",
                 lambda i, f: f.action_type == 'zoning'
                              and ((f.parcels_affected or 0) >= 5
                                   or (f.acres_affected or 0) >= 10),
                 'significance', 7),
    FloorTrigger("emergency_proc",
                 lambda i, f: f.action_type == 'emergency_procurement',
                 'significance', 7),
    FloorTrigger("appt_executive",
                 lambda i, f: f.action_type == 'appointment_executive',
                 'significance', 7),
    FloorTrigger("appt_board",
                 lambda i, f: f.action_type == 'appointment_board',
                 'significance', 5),
    FloorTrigger("tax_abatement_orange",
                 lambda i, f: f.action_type == 'tax_abatement'
                              and (i.dollars_amount or 0) >= 250_000,
                 'significance', 7),
]


# Subject-matter floors — independent of action_type.
# Detected by keyword regex on title+description OR suggested_badge_slugs
# membership. Each fires BOTH a significance boost AND a consent_placement
# ceiling.
SUBJECT_MATTER_PATTERNS = {
    'surveillance_alpr': re.compile(
        r'\b(flock|alpr|license\s+plate\s+reader|predictive\s+policing|'
        r'facial\s+recognit|surveillance\s+camera|gunshot\s+detect|'
        r'shotspotter|audit\s+log)\b',
        re.IGNORECASE,
    ),
    'police_oversight': re.compile(
        r'\b(citizen\s+review\s+board|use\s+of\s+force|police\s+misconduct|'
        r'complaint\s+review|police\s+(accountab|oversight)|internal\s+affairs)\b',
        re.IGNORECASE,
    ),
    'eminent_domain': re.compile(
        r'\b(eminent\s+domain|condemnation\s+for\s+public\s+use|'
        r'compulsory\s+acquisition|taking\s+by\s+the\s+city)\b',
        re.IGNORECASE,
    ),
}

SUBJECT_MATTER_FLOORS: list[FloorTrigger] = [
    # Surveillance / ALPR — keyword OR public_safety_tech_privacy badge
    FloorTrigger("surveillance_alpr_significance",
                 lambda i, f: (
                     SUBJECT_MATTER_PATTERNS['surveillance_alpr'].search(
                         f"{i.title or ''} {i.description or ''}"
                     ) is not None
                     or 'public_safety_tech_privacy' in (f.suggested_badge_slugs or [])
                 ),
                 'significance', 7),
    FloorTrigger("surveillance_alpr_consent",
                 lambda i, f: i.is_consent and (
                     SUBJECT_MATTER_PATTERNS['surveillance_alpr'].search(
                         f"{i.title or ''} {i.description or ''}"
                     ) is not None
                     or 'public_safety_tech_privacy' in (f.suggested_badge_slugs or [])
                 ),
                 'consent_placement', 2),

    # Police oversight — sig=8 (peak resident-government friction; regex narrow enough to avoid noise)
    FloorTrigger("police_oversight_significance",
                 lambda i, f: SUBJECT_MATTER_PATTERNS['police_oversight'].search(
                     f"{i.title or ''} {i.description or ''}"
                 ) is not None,
                 'significance', 8),
    FloorTrigger("police_oversight_consent",
                 lambda i, f: i.is_consent and SUBJECT_MATTER_PATTERNS['police_oversight'].search(
                     f"{i.title or ''} {i.description or ''}"
                 ) is not None,
                 'consent_placement', 2),

    # Eminent domain — sig=8 (constitutional clash; always make-the-news tier)
    FloorTrigger("eminent_domain_significance",
                 lambda i, f: SUBJECT_MATTER_PATTERNS['eminent_domain'].search(
                     f"{i.title or ''} {i.description or ''}"
                 ) is not None,
                 'significance', 8),
    FloorTrigger("eminent_domain_consent",
                 lambda i, f: i.is_consent and SUBJECT_MATTER_PATTERNS['eminent_domain'].search(
                     f"{i.title or ''} {i.description or ''}"
                 ) is not None,
                 'consent_placement', 2),
]


def _resolve_threshold(city_id: int, trigger_name: str,
                        default_threshold: int | None,
                        default_bound: int) -> tuple[int | None, int]:
    """Per-city override lookup. Empty table in v1 returns defaults."""
    row = db_lookup_override(city_id, trigger_name)
    if row is None:
        return default_threshold, default_bound
    return (
        row.override_threshold_amount or default_threshold,
        row.override_min_score or default_bound,
    )


CONSENT_PLACEMENT_CEILINGS: list[FloorTrigger] = [
    FloorTrigger("red_consent",
                 lambda i, f: (i.dollars_amount or 0) >= 1_000_000 and i.is_consent,
                 'consent_placement', 2),
    FloorTrigger("sole_source_consent",
                 lambda i, f: f.procurement_method == 'sole_source' and i.is_consent,
                 'consent_placement', 2),
    FloorTrigger("settlement_consent",
                 lambda i, f: f.action_type == 'settlement' and i.is_consent,
                 'consent_placement', 1),
    FloorTrigger("appt_executive_consent",
                 lambda i, f: f.action_type == 'appointment_executive' and i.is_consent,
                 'consent_placement', 2),
]


def apply_score_floors(item: AgendaItem,
                        facts: StructuredFacts,
                        ai: ItemRewrite,
                        city_id: int) -> ScoreOverrides:
    """Boost significance, lower consent_placement. Never the reverse.
    Returns audit record for score_overrides JSONB.
    Per-city overrides resolved via _resolve_threshold()."""
    fired: list[dict] = []

    # Significance: action-type, dollar-tier, AND subject-matter floors
    final_sig = ai.significance_score
    for trig in SIGNIFICANCE_FLOORS + SUBJECT_MATTER_FLOORS:
        if trig.score_field != 'significance':
            continue
        if trig.predicate(item, facts):
            _, effective_bound = _resolve_threshold(
                city_id, trig.name, None, trig.bound
            )
            if final_sig is None or effective_bound > final_sig:
                fired.append({
                    'trigger': trig.name,
                    'field': 'significance',
                    'pre': final_sig,
                    'post': effective_bound,
                })
                final_sig = effective_bound

    # Consent placement: existing ceilings AND subject-matter floors
    final_consent = ai.consent_placement_score
    for trig in CONSENT_PLACEMENT_CEILINGS + SUBJECT_MATTER_FLOORS:
        if trig.score_field != 'consent_placement':
            continue
        if trig.predicate(item, facts):
            _, effective_bound = _resolve_threshold(
                city_id, trig.name, None, trig.bound
            )
            if final_consent is None or effective_bound < final_consent:
                fired.append({
                    'trigger': trig.name,
                    'field': 'consent_placement',
                    'pre': final_consent,
                    'post': effective_bound,
                })
                final_consent = effective_bound

    return ScoreOverrides(
        original_ai_significance=ai.significance_score,
        final_significance=final_sig,
        original_ai_consent=ai.consent_placement_score,
        final_consent=final_consent,
        triggers=fired,
    )
```

The result lands in `agenda_items.score_overrides JSONB` with this shape:

```json
{
  "original_ai_significance": 4,
  "final_significance": 8,
  "original_ai_consent": 7,
  "final_consent": 1,
  "triggers": [
    {"trigger": "orange_settlement", "field": "significance", "pre": 4, "post": 8},
    {"trigger": "settlement_consent", "field": "consent_placement", "pre": 7, "post": 1}
  ]
}
```

The DB-stored `agenda_items.significance_score` and
`agenda_items.consent_placement_score` use the post-floor values
(`final_significance`, `final_consent`). The originals live only in
`score_overrides` for audit and calibration.

### 3.5 Calibration alert query

Daily worker task `calibration_report` runs:

```sql
-- Items processed in the last 24h where AI judgment vs floor diverged > 3 points
SELECT
  ai.id,
  m.city_id,
  ai.title,
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
```

Aggregated rollup query (also nightly) groups by `action_type` to spot
systematic AI miscalibration patterns:

```sql
SELECT
  ai.extracted_facts->>'action_type' AS action_type,
  COUNT(*) AS items_diverging,
  AVG(
    (ai.score_overrides->>'final_significance')::int
    - (ai.score_overrides->>'original_ai_significance')::int
  ) AS avg_delta,
  ai.ai_rewrite_version AS prompt_version
FROM agenda_items ai
WHERE ai.score_overrides IS NOT NULL
  AND ai.updated_at > NOW() - INTERVAL '7 days'
  AND ABS(
      COALESCE((ai.score_overrides->>'final_significance')::int, 0)
      - COALESCE((ai.score_overrides->>'original_ai_significance')::int, 0)
  ) > 3
GROUP BY ai.extracted_facts->>'action_type', ai.ai_rewrite_version
ORDER BY items_diverging DESC;
```

If any `(action_type, version)` row shows `items_diverging > 20`
and `avg_delta > 3`, that's the trigger to bump
`ITEM_PROMPT_VERSION` and refine the system-prompt language for that
action type. The result feeds an admin "calibration" dashboard panel
plus a Healthchecks ping with the rollup body when the threshold trips.

### 3.6 Procedural items in v3

Procedural items continue rendering with title-only, exactly as in v2 —
the only change is that the v3 prompt now also handles the additional
Alabama-context procedurals (vouchers, claims, awards/presentations,
visitor recognition, communications/petitions). The Pydantic
`procedural_consistency` validator above ensures these are correctly
null'd out at the schema layer.

### 3.7 Cross-stage reconciliation (service layer)

Pydantic per-stage models stay focused on per-stage structural validity.
Cross-stage business logic lives in `docket/ai/reconcile.py`, called from
the worker right before the atomic commit.

```python
# docket/ai/reconcile.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal


@dataclass
class ReconciliationResult:
    action: Literal['accept', 'retry_stage2_with_override', 'mark_cross_stage_conflict']
    conflicts: list[str]
    override_instruction: str | None = None  # injected into Stage 2 retry prompt


def reconcile_stages(facts: StructuredFacts,
                      rewrite: ItemRewrite,
                      item: AgendaItem,
                      already_retried: bool = False) -> ReconciliationResult:
    """Catch high-confidence Stage 1 extractions being silently dropped by
    Stage 2 procedural verdicts. Default: auto-retry once, then escalate."""
    conflicts: list[str] = []

    # Stage 2 says procedural BUT Stage 1 found substance
    if not rewrite.is_substantive:
        if facts.counterparty:
            conflicts.append('stage1_has_counterparty_but_stage2_procedural')
        if facts.funding_source not in ('unknown', None):
            conflicts.append('stage1_has_funding_source_but_stage2_procedural')
        if (item.dollars_amount or 0) >= 50_000:  # Yellow tier or above
            conflicts.append('yellow_tier_dollars_but_stage2_procedural')
        if facts.action_type in ('settlement', 'tax_abatement', 'annexation',
                                   'emergency_procurement', 'liquor_license',
                                   'right_of_way', 'zoning',
                                   'appointment_executive', 'appointment_board'):
            conflicts.append(f'high_attention_action_type_but_stage2_procedural:{facts.action_type}')

        # Subject-matter regex check — surveillance/police/eminent-domain titles
        # should never silently fall through to procedural even when action_type
        # is generic (contract_award, ordinance, etc.)
        haystack = f"{item.title or ''} {item.description or ''}"
        for matter, pattern in SUBJECT_MATTER_PATTERNS.items():
            if pattern.search(haystack):
                conflicts.append(f'subject_matter_match_but_stage2_procedural:{matter}')
                break

    if not conflicts:
        return ReconciliationResult(action='accept', conflicts=[])

    if already_retried:
        # Second attempt also failed — escalate
        return ReconciliationResult(
            action='mark_cross_stage_conflict',
            conflicts=conflicts,
        )

    # First retry: re-prompt Stage 2 with explicit override instruction
    override = (
        "PREVIOUS ATTEMPT INCORRECTLY classified this as procedural despite "
        "Stage 1 extracting these substantive facts: "
        f"counterparty={facts.counterparty!r}, funding={facts.funding_source!r}, "
        f"action_type={facts.action_type!r}, dollars=${item.dollars_amount or 0:,}. "
        "If those facts are accurate, this item IS substantive. Re-classify "
        "and write a headline + why-it-matters."
    )
    return ReconciliationResult(
        action='retry_stage2_with_override',
        conflicts=conflicts,
        override_instruction=override,
    )
```

Worker integration:

```python
# In worker.py, per-item processing loop
result = reconcile_stages(facts, rewrite, item, already_retried=False)

if result.action == 'retry_stage2_with_override':
    rewrite = call_stage2(item, facts,
                          extra_instruction=result.override_instruction)
    result = reconcile_stages(facts, rewrite, item, already_retried=True)

if result.action == 'mark_cross_stage_conflict':
    item.processing_status = 'cross_stage_conflict'  # surfaces in admin queue
    log_conflict(item.id, result.conflicts)
    # Still commit Stage 1 facts and Stage 2 output as-is — don't lose data
elif result.action == 'accept':
    item.processing_status = 'completed'

# Atomic commit follows
```

Adds a new `processing_status` enum value: `cross_stage_conflict`.

### 3.8 Per-city score-floor overrides

Trigger predicates stay code-defined (Python lambdas can't serialize cleanly
to a DB row). Only thresholds and bounds are tunable per-city. Empty table
in v1 — all 4 AL cities use shared defaults.

```sql
CREATE TABLE city_score_floor_overrides (
  city_id INT NOT NULL REFERENCES municipalities(id),
  trigger_name TEXT NOT NULL,
  -- Override either or both. NULL falls back to code default.
  override_threshold_amount NUMERIC NULL,  -- replaces dollar threshold (e.g. $1M → $500K for smaller cities)
  override_min_score INT NULL,             -- replaces sig=7 → sig=8 for stricter cities
  reason TEXT,                             -- audit: why was this override added?
  added_by TEXT,                           -- admin who added it
  added_at TIMESTAMP DEFAULT NOW(),
  PRIMARY KEY (city_id, trigger_name)
);
```

Lookup function (`_resolve_threshold` defined alongside the floor tables)
hot-paths to defaults in v1. Phase 4 adds an admin UI for editing rows.

### 3.5 Calibration alert query (revised — directional bias + drift)

Daily worker task `calibration_report` runs three queries:

**Query A — Per-item divergence (>3 points either direction):**

```sql
SELECT
  ai.id,
  m.city_id,
  ai.title,
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
```

**Query B — Two named alerts (percentage-based, separate panels):**

*Alert B1: "Under-scoring Impact"* — flags categories where AI consistently
fails to recognize significance. Triggers when >20% of items in a
(action_type, prompt_version) needed a sig boost over 7 days.

```sql
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
WHERE total_items >= 30                              -- min sample size
  AND items_with_sig_boost::float / total_items > 0.20  -- >20% needed a boost
ORDER BY pct_boosted DESC;
```

*Alert B2: "Over-scoring Consent"* — flags categories where AI consistently
rates items as more consent-appropriate than they should be.

```sql
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
```

Each renders as its own panel in the admin calibration dashboard. Different
(action_type, version) rows can appear in only one or both — surfacing
which axis the prompt is failing on.

**Query C — Baseline drift (catches systematic AI under-scoring even when no override fires):**

```sql
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
  action_type,
  week,
  avg_sig,
  avg_consent,
  n,
  avg_sig - LAG(avg_sig) OVER (PARTITION BY action_type ORDER BY week) AS sig_delta_wow,
  n - LAG(n) OVER (PARTITION BY action_type ORDER BY week) AS volume_delta_wow
FROM weekly_baselines
WHERE n >= 10  -- avoid noise on low-volume action types
ORDER BY action_type, week DESC;
```

Drift alert: if `sig_delta_wow < -1.0` AND `ABS(volume_delta_wow) < n*0.3`
(volume similar but average dropped >1 point), surface in admin calibration
panel. Catches "AI started under-scoring this category" even when no
override fires.

If any (action_type, version) row in Query B shows
`n_overrides > 20 AND avg_positive_sig_delta > 1.5`, OR Query C surfaces
sustained drift, that's the trigger to bump `ITEM_PROMPT_VERSION` and
refine the system-prompt language for that action type.

---

## Section 4 — Process badges

Process badges are city-agnostic, deterministic, and require no LLM calls.
They're derived from already-extracted fields (Stage 1, Stage 2, Stage 2.5)
plus existing vote/member-vote data.

### 4.1 Storage schema

```sql
-- Created in Migration 013 alongside extracted_facts and friends
CREATE TABLE agenda_item_badges (
  id              SERIAL PRIMARY KEY,
  agenda_item_id  INT NOT NULL REFERENCES agenda_items(id) ON DELETE CASCADE,
  badge_slug      TEXT NOT NULL,
  kind            TEXT NOT NULL CHECK (kind IN ('process', 'policy')),
  confidence      NUMERIC(3, 2),    -- NULL or 1.0 for process; 0.0-1.0 for policy
  source          TEXT NOT NULL CHECK (source IN ('deterministic', 'llm', 'both', 'manual')),
  detected_at     TIMESTAMP NOT NULL DEFAULT NOW(),

  UNIQUE (agenda_item_id, badge_slug)
);

CREATE INDEX idx_agenda_item_badges_slug ON agenda_item_badges (badge_slug, kind);
CREATE INDEX idx_agenda_item_badges_item ON agenda_item_badges (agenda_item_id);
```

A `matching_metadata` JSONB column captures *which* trigger fired (decision #62)
— added in the same migration:

```sql
ALTER TABLE agenda_item_badges
  ADD COLUMN matching_metadata JSONB NOT NULL DEFAULT '{}'::jsonb;
```

Examples of stored payloads:
- `{"matched_keyword": "BPRA"}` — keyword regex hit
- `{"matched_keywords": ["blight", "demolition order"]}` — multiple hits
- `{"matched_action_type": "demolition"}` — action_type matched
- `{"matched_topic": "housing"}` — legacy topic matched
- `{"llm_only": true}` — LLM suggested, no deterministic match
- `{"both": true, "matched_keyword": "Flock"}` — both sources fired

The `priority_badge_templates` catalog (decision #28) carries the human-facing
metadata — name, description, icon, default matcher hints. Process badges
are seeded into the catalog as `kind='process'` rows with no per-city
overrides expected.

### 4.2 Process badge catalog (seed data for Migration 013)

```sql
INSERT INTO priority_badge_templates (slug, name, description, icon, kind) VALUES
  ('hidden_on_consent', 'Hidden on consent',
   'Item the AI judged should NOT be on consent (high public interest), but is on consent anyway.',
   '💰', 'process'),
  ('sole_source', 'Sole-source / no-bid',
   'Procurement that bypassed competitive bidding.',
   '🤝', 'process'),
  ('legal_settlement', 'Legal settlement',
   'Item resolves a legal claim — often closed-session-resolved.',
   '⚖️', 'process'),
  ('split_vote', 'Split vote',
   'Council was not unanimous — at least one no or abstain.',
   '🪧', 'process'),
  ('contested', 'Contested',
   'Genuinely divided — 2+ dissenters and >20% of votes cast.',
   '🔥', 'process'),
  ('amends_prior_contract', 'Amends prior contract',
   'Modifies a prior contract with this vendor; may or may not increase total cost.',
   '↩️', 'process'),
  ('emergency_action', 'Emergency action',
   'Declared emergency or emergency procurement; usually skips standard procurement rules.',
   '🚨', 'process');
```

### 4.3 Computation cadence

| Badge | Computation timing | Why |
|---|---|---|
| `hidden_on_consent` | On-write (in Stage 2.5 atomic commit) | Depends only on existing-row data |
| `sole_source` | On-write | Depends only on Stage 1 extraction |
| `legal_settlement` | On-write | Depends only on Stage 1 extraction |
| `emergency_action` | On-write | Depends only on Stage 1 extraction |
| `split_vote` | Nightly batch | Depends on member_votes, often attached AFTER item creation when minutes are parsed |
| `amends_prior_contract` | Nightly batch | Cross-item join (counterparty × meeting_date) |

The 4 on-write badges run as a single transaction step inside the
per-item atomic commit — no risk of stale state for items the user just
viewed in real-time. The 2 batch-computed badges land within 24h.

A new worker task `process_badges` runs nightly at 09:30 (after
`vote_matching` at 09:00) and processes any items modified in the
last 36 hours.

### 4.4 SQL — the 6 process badges

Each query is idempotent (`ON CONFLICT DO NOTHING`) and scoped by the
nightly task to items modified in the last 36 hours via a temp table or CTE.
The patterns below are simplified to show the core predicates.

#### 1. 💰 Hidden on consent

```sql
INSERT INTO agenda_item_badges (agenda_item_id, badge_slug, kind, confidence, source)
SELECT ai.id, 'hidden_on_consent', 'process', 1.0, 'deterministic'
FROM agenda_items ai
WHERE ai.is_consent = TRUE
  AND ai.consent_placement_score IS NOT NULL
  AND ai.consent_placement_score <= 3
  AND ai.processing_status = 'completed'
  AND (
    -- Deterministic floor fired (Red-tier $, sole-source, settlement,
    -- exec-appointment): trust it regardless of AI confidence
    EXISTS (
      SELECT 1
      FROM jsonb_array_elements(ai.score_overrides->'triggers') AS trig
      WHERE trig->>'field' = 'consent_placement'
    )
    -- Otherwise: require AI to be at least medium-confident before flagging
    OR ai.ai_confidence IN ('high', 'medium')
  )
ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING;
```

Uses the *post-floor* `consent_placement_score` (Stage 2.5 may have
lowered the AI's value via the deterministic ceilings). So a $5M no-bid
contract on consent fires the badge even if Haiku originally rated it
consent_placement=8 — Stage 2.5 pushed it to 2 first, AND the trigger
log shows the deterministic floor fired (which bypasses the
ai_confidence requirement). Defends against AI miscalibration on
low-confidence outputs while still firing on the high-stakes
deterministic-floor cases.

**Examples:**

| Item | is_consent | consent_placement | ai_confidence | Floor fired? | Badge fires? |
|---|---|---|---|---|---|
| $5M Flock contract on consent | TRUE | 2 (post-floor) | medium | yes (sole_source_consent) | ✓ |
| $50K legal settlement on consent | TRUE | 1 (post-floor) | low | yes (settlement_consent) | ✓ (floor bypasses confidence) |
| $30K office supplies on consent | TRUE | 9 (legitimately routine) | high | no | ✗ (score too high) |
| $80K fleet fuel on consent | TRUE | 8 | high | no | ✗ (score too high) |
| $1M road work, NOT on consent | FALSE | n/a | high | no | ✗ (not on consent) |
| $200K item on consent, AI sig=2 but confidence=low | TRUE | 2 | low | no | ✗ (confidence guard rejects) |

#### 2. 🤝 Sole-source / no-bid

```sql
INSERT INTO agenda_item_badges (agenda_item_id, badge_slug, kind, confidence, source)
SELECT ai.id, 'sole_source', 'process', 1.0, 'deterministic'
FROM agenda_items ai
WHERE ai.extracted_facts->>'procurement_method' IN ('sole_source', 'no_bid')
  AND ai.processing_status = 'completed'
ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING;
```

**Examples:**

| Item | procurement_method | Badge fires? |
|---|---|---|
| "Sole-source: Flock 5-year extension" | `sole_source` | ✓ |
| "Award of bid #2026-14 for HVAC, lowest of 4 bids" | `competitive` | ✗ |
| "Emergency procurement of generators after storm" | `emergency` | ✗ (separate badge) |
| "Single-source authorization: proprietary software" | `sole_source` | ✓ |
| "RFP #2026-22 issued; awards pending" | `rfp` | ✗ |
| Item with no extracted procurement_method | `unknown` | ✗ |

#### 3. ⚖️ Legal settlement

```sql
INSERT INTO agenda_item_badges (agenda_item_id, badge_slug, kind, confidence, source)
SELECT ai.id, 'legal_settlement', 'process', 1.0, 'deterministic'
FROM agenda_items ai
WHERE ai.extracted_facts->>'action_type' = 'settlement'
  AND ai.processing_status = 'completed'
ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING;
```

**Examples:**

| Item | action_type | Badge fires? |
|---|---|---|
| "Settlement of Smith v. City for $250K (use of force)" | `settlement` | ✓ |
| "Approval of settlement agreement, Jones v. Birmingham" | `settlement` | ✓ |
| "Settlement of accounts: monthly procurement reconciliation" | `appropriation` (not settlement) | ✗ (Stage 1 should classify by intent, not by word presence) |
| "Authorize attorney to defend lawsuit" | `resolution` | ✗ (defense, not settlement) |

#### 4. 🪧 Split vote — and 🔥 Contested

Two badges, computed from one CTE that counts dissenters per
agenda item:

```sql
WITH dissent_counts AS (
  SELECT
    vai.agenda_item_id,
    COUNT(*) FILTER (WHERE mv.vote_value IN ('no', 'abstain')) AS n_dissent,
    COUNT(*) FILTER (WHERE mv.vote_value IN ('yes', 'no', 'abstain')) AS n_voting
  FROM vote_agenda_items vai
  JOIN votes v ON v.id = vai.vote_id
  JOIN member_votes mv ON mv.vote_id = v.id
  WHERE vai.is_active = TRUE
  GROUP BY vai.agenda_item_id
)
-- Split vote: 1+ dissenter
INSERT INTO agenda_item_badges (agenda_item_id, badge_slug, kind, confidence, source)
SELECT agenda_item_id, 'split_vote', 'process', 1.0, 'deterministic'
FROM dissent_counts
WHERE n_dissent >= 1
ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING;

-- Contested: 2+ dissenters AND >20% of votes cast (Alabama-default;
-- per-city tuning via city_score_floor_overrides, decision #48)
INSERT INTO agenda_item_badges (agenda_item_id, badge_slug, kind, confidence, source)
SELECT agenda_item_id, 'contested', 'process', 1.0, 'deterministic'
FROM dissent_counts
WHERE n_dissent >= 2
  AND n_voting > 0
  AND (n_dissent::float / n_voting) > 0.20
ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING;
```

Notes:
- "absent" deliberately excluded — that's an attendance issue, not contention
- Both `'no'` and `'abstain'` count as contention
- `contested` is a near-subset of `split_vote` — when 2+ dissent AND >20%, both fire; when 2+ dissent but ≤20% (large councils), only `split_vote` fires
- UI display rule: render "🔥 Contested (vote: 6-3)" when both badges present;
  render "🪧 Split (6-1)" when only `split_vote` fires. Vote count comes
  from a separate `votes` query — badges themselves stay free of payload.
- Provisional votes (per the existing two-phase lifecycle) are included; the
  badge appears as soon as votes are matched, not only after minutes adoption
- Non-roll-call voice votes have no member_vote rows — badges silently
  don't fire for those (we can't surface what we don't have)

**Examples:**

| Vote outcome | n_voting | n_dissent | % dissent | split_vote | contested |
|---|---|---|---|---|---|
| 9-0 unanimous (Birmingham) | 9 | 0 | 0% | ✗ | ✗ |
| 8-1 (Birmingham) | 9 | 1 | 11% | ✓ | ✗ (only 1 dissenter) |
| 7-2 (Birmingham) | 9 | 2 | 22% | ✓ | ✓ (≥2 AND >20%) |
| 6-3 (Birmingham) | 9 | 3 | 33% | ✓ | ✓ |
| 4-3 (Vestavia) | 7 | 3 | 43% | ✓ | ✓ |
| 9-2 (Homewood, 11 members) | 11 | 2 | 18% | ✓ | ✗ (>2 dissent but ≤20%) |
| 8-3 (Homewood) | 11 | 3 | 27% | ✓ | ✓ |
| 5 yes, 2 abstain, 2 absent | 7 | 2 | 28% | ✓ | ✓ (abstain counts; absent doesn't) |
| Voice vote, no roll call recorded | 0 | 0 | n/a | ✗ | ✗ (no data) |

#### 5. ↩️ Amends prior contract (v1 simplification)

Migration 013 enables the `pg_trgm` extension for trigram similarity
matching on counterparty strings:

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX idx_agenda_items_counterparty_trgm
  ON agenda_items USING gin ((extracted_facts->>'counterparty') gin_trgm_ops);
```

Then:

```sql
WITH prior_contracts AS (
  SELECT
    ai.id AS prior_id,
    ai.meeting_id AS prior_meeting_id,
    ai.extracted_facts->>'counterparty' AS prior_counterparty,
    ai.dollars_amount AS prior_dollars,
    m.meeting_date AS prior_date,
    m.city_id AS prior_city
  FROM agenda_items ai
  JOIN meetings m ON m.id = ai.meeting_id
  WHERE ai.extracted_facts->>'action_type' = 'contract_award'
    AND ai.dollars_amount > 0
    AND TRIM(COALESCE(ai.extracted_facts->>'counterparty', '')) <> ''
)
INSERT INTO agenda_item_badges (agenda_item_id, badge_slug, kind, confidence, source)
SELECT DISTINCT ai.id, 'amends_prior_contract', 'process', 0.6, 'deterministic'
FROM agenda_items ai
JOIN meetings m ON m.id = ai.meeting_id
JOIN prior_contracts pc
  ON similarity(
       LOWER(TRIM(pc.prior_counterparty)),
       LOWER(TRIM(ai.extracted_facts->>'counterparty'))
     ) >= 0.6                                -- trigram fuzzy match (decision #59)
  AND pc.prior_city = m.city_id              -- same city only
  AND pc.prior_date < m.meeting_date         -- prior in time
WHERE ai.extracted_facts->>'action_type' = 'contract_amendment'
  AND ai.processing_status = 'completed'
  AND TRIM(COALESCE(ai.extracted_facts->>'counterparty', '')) <> ''
  -- NOTE: dollars_amount > 0 deliberately omitted (decision #58) —
  -- time-only / scope-only amendments are still substantive and
  -- should fire the badge.
  -- Amendment noise filter (decision #89): suppress on recurring/routine renewals
  AND NOT (
    COALESCE(ai.title, '') || ' ' || COALESCE(ai.description, '')
  ) ~* '\b(recurring|monthly invoice|annual renewal|routine renewal|periodic billing)\b'
ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING;
```

**v1 simplification (decision #51):** drop the strict
`new_dollars > prior_dollars` comparison. `dollars_amount` is the
regex-extracted *largest* dollar in the text (per `enrichment/dollars.py`),
not always the new total — amendments that only state the delta would
silently fail strict comparison. Instead, fire the badge for ANY
amendment with a counterparty match (trigram ≥ 0.6) where prior award
exists same-city.

Confidence **0.6** acknowledges:
- Counterparty match is fuzzy v1 (no entity normalization yet)
- We're not verifying the amendment actually increases cost; just that it
  modifies a prior contract with this vendor

Phase 4 promotes this to confidence 1.0 by:
- Adding Stage 1 `dollars_breakdown` field (`kind: 'total' | 'delta' | 'unknown'`,
  `delta_amount: Decimal | None`, `new_total: Decimal | None`)
- Replacing trigram with canonical `counterparty_entity_id` FK
- Strict comparison once delta vs total is reliably distinguishable

Edge: if the original contract isn't in our database (pre-2017 or
adapter gap), we miss the signal. Acceptable in v1 — we surface what
we can verify.

**Examples:**

| New item | Prior contract in DB? | Trigram match? | Badge fires? |
|---|---|---|---|
| "Amend Acme Industries HVAC contract — add $50K" | ✓ "Acme Industries HVAC, $1M" 2024 | sim ≈ 0.85 | ✓ confidence 0.6 |
| "Amend Brasfield & Gorrie GMP, scope change" | ✓ "Brasfield Gorrie construction" 2025 | sim ≈ 0.78 | ✓ confidence 0.6 |
| "Time-only extension: ABC Co. agreement" | ✓ "ABC Co., $250K" 2023 | sim ≈ 0.95 | ✓ (no $ change required, decision #58) |
| "First award to NewVendor Inc., $100K" | ✗ no prior NewVendor | n/a | ✗ |
| "Amend HVAC contract with Acme" (typo: counterparty extracted as "Acme HVAC LLC") | ✓ "Acme Industries" prior | sim ≈ 0.40 | ✗ (too different, below 0.5 threshold) |
| "Amendment to Mobile city contract" (cross-city) | ✓ "Acme Industries" but different city | n/a | ✗ (same-city scope) |

#### 6. 🚨 Emergency action

```sql
INSERT INTO agenda_item_badges (agenda_item_id, badge_slug, kind, confidence, source)
SELECT ai.id, 'emergency_action', 'process', 1.0, 'deterministic'
FROM agenda_items ai
WHERE (
    ai.extracted_facts->>'action_type' = 'emergency_procurement'
    OR ai.extracted_facts->>'procurement_method' = 'emergency'
    OR ai.title ~* '\b(emergency|exigent|expedited)\b'
  )
  AND ai.processing_status = 'completed'
ON CONFLICT (agenda_item_id, badge_slug) DO NOTHING;
```

Three signals catch the badge:
1. Stage 1 classified `action_type='emergency_procurement'` (cleanest path)
2. Stage 1 classified `procurement_method='emergency'` while action_type is
   generic (`contract_award`)
3. Title contains "emergency", "exigent", or "expedited" (catches Alabama
   common phrasing like *"Ratifying an emergency repair…"* even when
   Stage 1 didn't classify it). Word-boundary `\b` prevents false-positive
   matches on substrings; "ratifying" alone is *not* in the regex —
   "Ratifying personnel decisions" doesn't fire because no emergency
   keyword is present.

**Examples:**

| Item | action_type | procurement_method | Title regex | Badge fires? |
|---|---|---|---|---|
| "Emergency procurement of generators" | `emergency_procurement` | n/a | matches "emergency" | ✓ |
| "Ratifying an emergency water main repair" | `contract_award` | `emergency` | matches "emergency" | ✓ |
| "Emergency declaration: severe weather response" | `resolution` | n/a | matches "emergency" | ✓ |
| "Expedited contract award for storm cleanup" | `contract_award` | `competitive` | matches "expedited" | ✓ |
| "Ratifying personnel decisions made between meetings" | `resolution` | n/a | no match | ✗ |
| "Emergency contact list update" | `resolution` | n/a | matches "emergency" | ✓ (over-fire — admin can manually remove badge; surfaces in calibration if pattern repeats) |
| "Routine contract award" | `contract_award` | `competitive` | no match | ✗ |

### 4.5 Recompute / cleanup logic

The nightly `process_badges` task processes a 36-hour window:

```python
def run_process_badges_task():
    """Recompute process badges for items modified in the last 36 hours.
    Idempotent — safe to run multiple times. Pure deterministic SQL."""

    with db_cursor() as cur:
        # Lock the task so a manual --run-once doesn't collide with the schedule
        cur.execute("SELECT pg_try_advisory_lock(%s)",
                    [task_lock_id('process_badges')])
        if not cur.fetchone()[0]:
            log.warning("process_badges already running, skipping")
            health_ping('process_badges', body='not-running')
            return

        try:
            # Identify the working set
            cur.execute("""
                CREATE TEMP TABLE recent_items ON COMMIT DROP AS
                SELECT id FROM agenda_items
                WHERE updated_at > NOW() - INTERVAL '36 hours'
                  AND processing_status = 'completed';
            """)

            # Drop existing process-kind badges for those items so we get a
            # clean slate. Manual badges (source='manual') are preserved
            # — admin overrides survive nightly recompute. (decision #57)
            cur.execute("""
                DELETE FROM agenda_item_badges
                WHERE kind = 'process'
                  AND source != 'manual'
                  AND agenda_item_id IN (SELECT id FROM recent_items);
            """)

            # Run the 6 INSERT queries scoped to recent_items
            for query in PROCESS_BADGE_QUERIES:
                cur.execute(query)  # each query joins recent_items via WHERE clause

            cur.execute("SELECT pg_advisory_unlock(%s)",
                        [task_lock_id('process_badges')])
        except Exception:
            log.exception("process_badges task failed")
            health_ping('process_badges', body='failure')
            raise

        health_ping('process_badges', body='success')
```

The on-write path (for the 4 fast badges) runs in `worker.py`'s per-item
processing loop, after `apply_score_floors()`, inside the same atomic
transaction as the rest of the per-item commit:

```python
def compute_on_write_process_badges(item, facts, scores, ai_confidence):
    """Returns list of (badge_slug, confidence) tuples for the 4 on-write badges.
    Mirrors the deterministic SQL exactly — both paths must agree."""
    out = []

    # Hidden on consent — requires AI confidence guard OR Stage 2.5 floor fired
    if (item.is_consent
            and scores.final_consent is not None
            and scores.final_consent <= 3):
        any_consent_floor_fired = any(
            t['field'] == 'consent_placement' for t in scores.triggers
        )
        if ai_confidence in ('high', 'medium') or any_consent_floor_fired:
            out.append(('hidden_on_consent', 1.0))

    if facts.procurement_method in ('sole_source', 'no_bid'):
        out.append(('sole_source', 1.0))
    if facts.action_type == 'settlement':
        out.append(('legal_settlement', 1.0))

    if (facts.action_type == 'emergency_procurement'
            or facts.procurement_method == 'emergency'
            or re.search(r'\b(emergency|exigent|expedited)\b',
                         item.title or '', re.IGNORECASE)):
        out.append(('emergency_action', 1.0))

    return out
```

The nightly batch then redundantly reasserts these (clean-slate DELETE +
INSERT) — slightly wasteful but ensures the on-write path can never drift
out of sync with the deterministic SQL. Both paths reach the same result.

### 4.6 Multi-city behavior

Process badges work for **all 4 cities** automatically — every query
operates on `agenda_items` regardless of `meeting.city_id`. No per-city
config needed. New cities added later (Mobile expansion, Hoover, etc.)
inherit the full process-badge set on day 1.

The `priority_badge_templates` catalog stays as a single shared catalog
across cities for process badges (no opt-in per city — process badges
always apply where the criteria match).

---

## Section 5 — Policy badges

Policy badges are city-specific, editorial, and reflect the administration's
*stated* priorities. Volume tracking per badge over time becomes a separate
accountability lens: "the mayor said blight is the top priority — how many
blight items actually hit the docket this fiscal year?"

### 5.1 Storage schema (templates + per-city config)

Two tables introduced in Migration 013, layered:

```sql
-- The shared catalog. Process badges and policy badges both seed here;
-- the kind column distinguishes.
CREATE TABLE priority_badge_templates (
  slug                    TEXT PRIMARY KEY,
  name                    TEXT NOT NULL,
  description             TEXT NOT NULL,
  icon                    TEXT NOT NULL,
  kind                    TEXT NOT NULL CHECK (kind IN ('process', 'policy')),
  default_matcher_hints   JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at              TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Per-city opt-in to a template, with optional per-city overrides.
-- Process badges do not appear here (they're always-on, citywide).
CREATE TABLE priority_badges_config (
  id                          SERIAL PRIMARY KEY,
  city_id                     INT NOT NULL REFERENCES municipalities(id) ON DELETE CASCADE,
  template_slug               TEXT NOT NULL REFERENCES priority_badge_templates(slug) ON DELETE CASCADE,
  -- Per-city overrides (NULL = inherit from template)
  name_override               TEXT NULL,
  description_override        TEXT NULL,
  matcher_hints_override      JSONB NULL,
  enabled                     BOOLEAN NOT NULL DEFAULT TRUE,
  -- Metadata
  added_at                    TIMESTAMP NOT NULL DEFAULT NOW(),
  added_by                    TEXT,
  notes                       TEXT,

  UNIQUE (city_id, template_slug)
);

CREATE INDEX idx_priority_badges_config_city ON priority_badges_config (city_id) WHERE enabled = TRUE;
```

Resolution at read-time:

```python
def resolve_policy_badge(city_id: int, slug: str) -> ResolvedBadge | None:
    """Returns the effective per-city badge config, or None if not enabled."""
    row = db_lookup_config(city_id, slug)
    if row is None or not row.enabled:
        return None
    template = db_lookup_template(slug)
    return ResolvedBadge(
        slug=slug,
        name=row.name_override or template.name,
        description=row.description_override or template.description,
        icon=template.icon,
        matcher_hints=row.matcher_hints_override or template.default_matcher_hints,
    )
```

### 5.2 Birmingham 2026 seed data

Migration 013 seeds the 4 BHM v1 badges into `priority_badge_templates` and
opts BHM into all 4 via `priority_badges_config`. Other cities get the
process badges (always-on) but no policy-badges enabled in v1.

```sql
-- 1. Seed the catalog (templates)
INSERT INTO priority_badge_templates
  (slug, name, description, icon, kind, default_matcher_hints) VALUES
  (
    'blight_accountability',
    'Blight Accountability',
    'Blighted property registration, demolition orders, tax penalties on neglected property, BPRA enforcement.',
    '🏚️',
    'policy',
    '{
      "keywords": ["blight", "blighted", "blighted property", "BPRA", "Blighted Property Registration",
                   "condemnation order", "unsafe structure", "nuisance abatement", "demolition order",
                   "tax penalty for neglect", "code enforcement"],
      "action_types": ["demolition", "weed_abatement"],
      "topics": ["blight"],
      "excluded_action_types": ["liquor_license", "proclamation", "appointment_advisory", "right_of_way"],
      "min_significance": 3
    }'::jsonb
  ),
  (
    'housing_stability',
    'Housing Stability',
    'Housing Trust Fund allocations, affordable-housing initiatives, eviction protections, tenant rights.',
    '🏠',
    'policy',
    '{
      "keywords": ["housing trust", "affordable housing", "eviction protection", "tenant rights",
                   "down payment assistance", "rental assistance", "low income housing",
                   "fair housing", "homestead exemption"],
      "action_types": ["appropriation", "ordinance"],
      "topics": ["housing"],
      "excluded_action_types": ["liquor_license", "proclamation", "appointment_advisory"],
      "min_significance": 3
    }'::jsonb
  ),
  (
    'property_recovery',
    'Property Recovery',
    'Land Bank Act acquisitions, tax-delinquency reclamation, derelict-parcel return to productive use.',
    '🏗️',
    'policy',
    '{
      "keywords": ["Land Bank", "Jefferson County Land Bank", "tax delinquent", "tax sale",
                   "redevelopment authority", "quiet title", "derelict parcel", "tax foreclosure"],
      "action_types": ["resolution", "ordinance"],
      "topics": ["land", "property"],
      "excluded_action_types": ["liquor_license", "proclamation", "appointment_advisory"],
      "min_significance": 3
    }'::jsonb
  ),
  (
    'public_safety_tech_privacy',
    'Public-Safety Tech & Privacy',
    'Surveillance deployments, police technology, body cameras, predictive policing, facial recognition, ALPRs.',
    '🛡️',
    'policy',
    '{
      "keywords": ["Flock", "ALPR", "license plate reader", "body cam", "body-worn camera",
                   "predictive policing", "facial recognition", "surveillance camera",
                   "audit log", "gunshot detection", "ShotSpotter", "Axon"],
      "action_types": ["contract_award", "contract_amendment", "ordinance", "appropriation"],
      "topics": ["public_safety"],
      "excluded_action_types": ["liquor_license", "proclamation", "appointment_advisory"],
      "min_significance": 3
    }'::jsonb
  );

-- 2. Opt Birmingham into all 4 (no overrides — defaults inherited)
INSERT INTO priority_badges_config (city_id, template_slug, enabled, added_by, notes)
SELECT m.id, t.slug, TRUE, 'migration_013', 'BHM 2026 v1 priority list'
FROM municipalities m
CROSS JOIN priority_badge_templates t
WHERE m.slug = 'birmingham'
  AND t.slug IN ('blight_accountability', 'housing_stability',
                  'property_recovery', 'public_safety_tech_privacy');
```

The 4 process badges (Section 4.2) plus this seed gives BHM a full set of
10 badges (6 process + 4 policy). Mobile/Vestavia/Homewood get 6 process
badges plus zero policy badges in v1; per-city policy lists land in
Phase 4 once their stated priorities are gathered.

#### Birmingham policy-badge fires/doesn't-fire examples

**🏚️ Blight Accountability:**

| Item | Sig | Action type | Match? |
|---|---|---|---|
| "BPRA enforcement on 14 properties in District 4" | 7 | `demolition` | ✓ keyword + action_type |
| "Demolition order for 123 Main St (unsafe structure)" | 6 | `demolition` | ✓ keyword + action_type |
| "Annual code-enforcement training for staff" | 2 | `appropriation` | ✗ keyword match but sig <3 (render-gated) |
| "Liquor license renewal for 234 Elm St (formerly blighted)" | 5 | `liquor_license` | ✗ excluded_action_types |
| "Routine fleet purchase for code enforcement vehicles" | 3 | `contract_award` | ✗ no keyword match, no action_type match |

**🏠 Housing Stability:**

| Item | Sig | Action type | Match? |
|---|---|---|---|
| "Housing Trust Fund: $500K allocation for affordable rentals" | 7 | `appropriation` | ✓ keyword + action_type |
| "Eviction protection ordinance for tenants in Wards 5-6" | 8 | `ordinance` | ✓ keyword + action_type |
| "Down payment assistance program: $1.2M federal grant" | 7 | `appropriation` | ✓ keyword + action_type |
| "Travel reimbursement for Housing Department staff" | 1 | `appropriation` | ✗ sig <3 (render-gated) |
| "Liquor license: housing development project ground floor" | 4 | `liquor_license` | ✗ excluded_action_types |
| "Routine pothole repair on Housing Authority property" | 3 | `contract_award` | ✗ no keyword match |

**🏗️ Property Recovery:**

| Item | Sig | Action type | Match? |
|---|---|---|---|
| "Land Bank acquires 6 tax-delinquent parcels" | 7 | `resolution` | ✓ keyword + action_type |
| "Quiet title action on tax-foreclosed property at 456 Oak" | 6 | `resolution` | ✓ keyword |
| "Jefferson County Land Bank Authority: appoint new director" | 5 | `appointment_board` | ✓ keyword (but appointment_board not in excluded list) |
| "Routine property maintenance contract award" | 2 | `contract_award` | ✗ sig <3 (render-gated) |
| "Liquor license at recovered Land Bank property" | 4 | `liquor_license` | ✗ excluded_action_types |

**🛡️ Public-Safety Tech & Privacy:**

| Item | Sig | Action type | Match? |
|---|---|---|---|
| "Flock Safety 5-year extension: $1.8M sole-source" | 7 (boosted to 7 by SUBJECT_MATTER_FLOORS) | `contract_amendment` | ✓ keyword + action_type |
| "Body-worn camera footage retention ordinance" | 8 | `ordinance` | ✓ keyword + action_type |
| "Predictive policing pilot evaluation report" | 6 | `resolution` | ✓ keyword |
| "ALPR audit log review: Q1 2026 results" | 7 (boosted by surveillance match) | `resolution` | ✓ keyword |
| "Routine patrol car fuel budget" | 2 | `contract_award` | ✗ no keyword match, no topic match |
| "Liquor license at Police Athletic League facility" | 3 | `liquor_license` | ✗ excluded_action_types |
| "Annual report on police department staffing" | 4 | `resolution` | ✗ no keyword match (despite "police") |

### 5.3 Hybrid matching contract

Per decision #9: Stage 2 LLM emits `suggested_badge_slugs` AND deterministic
per-badge rules layer on top. Confidence is a function of how many sources
agree.

#### LLM side (Stage 2 prompt)

The system prompt (Section 3.1) already directs Stage 2 to populate
`suggested_badge_slugs`. The user message template includes the per-city
enabled badges:

```
City: {city_name}
Available policy badge slugs: {comma-separated enabled slugs for city}
```

Stage 2 picks 0-N badges from that list it's reasonably confident apply.
Empty list is acceptable. **Important constraint:** the LLM must NOT
suggest badges not in the city's enabled list — those are silently dropped
during reconciliation.

#### Deterministic side (per-badge matchers)

Each badge's `default_matcher_hints` JSONB drives the deterministic match.
The matcher fires if ANY of:
- A keyword regex from `keywords` matches the title or description
- The item's `action_type` is in `action_types`
- The item's legacy `topic` (existing 11-category classification) is in `topics`

```python
def deterministic_policy_match(item: AgendaItem,
                                facts: StructuredFacts,
                                rewrite: ItemRewrite,
                                hints: dict) -> tuple[bool, dict]:
    """Returns (matched, metadata) — metadata records WHICH trigger fired.
    Returns (False, {}) when no match. Metadata is stored in
    agenda_item_badges.matching_metadata for admin debugging.

    Note: significance gating is RENDER-time, not matcher-time (revised
    decision #61). The matcher always writes the badge row when the
    item matches. The gate lives in the SERVICE LAYER — specifically
    `services/query.py:list_items_by_badge` (Section 6.5), plus the
    search index reader and admin views — so every read path shares
    the same filter. The per-badge `min_significance` value comes from
    `priority_badges_config.matcher_hints_override.min_significance`
    (default 3 if not set). Decoupling matcher from gate lets admins
    lower the threshold later without re-running the matcher."""

    # Hard guard — categorical exclusions (decision #63)
    if facts.action_type in hints.get('excluded_action_types', []):
        return (False, {})

    text = f"{item.title or ''} {item.description or ''}".lower()

    # Keyword match — supports plain strings (escaped) and {pattern, is_regex}
    matched_keywords: list[str] = []
    for entry in hints.get('keywords', []):
        if isinstance(entry, dict) and entry.get('is_regex'):
            pattern = entry['pattern']                       # raw regex (decision #60)
            display = entry.get('label', pattern)
        else:
            kw = entry if isinstance(entry, str) else entry.get('pattern', '')
            pattern = r'\b' + re.escape(kw.lower()) + r'\b'
            display = kw

        try:
            if re.search(pattern, text):
                matched_keywords.append(display)
        except re.error as e:
            log.warning("invalid regex in matcher_hints: %r (%s)", pattern, e)
            continue

    if matched_keywords:
        return (True, {'matched_keywords': matched_keywords})

    # Action-type match
    if facts.action_type in hints.get('action_types', []):
        return (True, {'matched_action_type': facts.action_type})

    # Legacy topic match
    if item.topic and item.topic in hints.get('topics', []):
        return (True, {'matched_topic': item.topic})

    return (False, {})
```

#### Confidence model

```python
def resolve_policy_badge_confidence(slug: str,
                                      llm_suggested: bool,
                                      deterministic_match: bool) -> float | None:
    """Returns confidence value, or None if neither source fired."""
    if llm_suggested and deterministic_match:
        return 1.0       # both sources agree → high confidence
    if llm_suggested or deterministic_match:
        return 0.6       # one source only → medium confidence
    return None          # neither fired → no badge
```

Source field per row in `agenda_item_badges`:

```python
def resolve_source(llm: bool, det: bool) -> str:
    if llm and det:
        return 'both'
    if llm:
        return 'llm'
    if det:
        return 'deterministic'
    raise ValueError("called for non-firing badge")
```

#### When matching runs

Policy-badge matching runs **on-write** for every substantive item, in the
same atomic commit as Stage 2 / 2.5 / process badges. Unlike the
expensive cross-item process badges (split-vote, amends-prior-contract),
policy matching is cheap and per-item.

```python
def compute_policy_badges(item, facts, rewrite, city_id):
    """Returns list of (slug, confidence, source, matching_metadata) tuples."""
    enabled = list_enabled_policy_badges(city_id)        # cached per-city
    out = []

    suggested = set(rewrite.suggested_badge_slugs or [])
    # Filter to enabled only — drop any LLM hallucinations of disabled badges
    suggested &= {b.slug for b in enabled}

    for badge in enabled:
        llm = badge.slug in suggested
        det, det_metadata = deterministic_policy_match(
            item, facts, rewrite, badge.matcher_hints
        )
        conf = resolve_policy_badge_confidence(badge.slug, llm, det)
        if conf is None:
            continue

        # Build matching_metadata for audit/debugging
        if llm and det:
            metadata = {'both': True, **det_metadata}
        elif llm:
            metadata = {'llm_only': True}
        else:
            metadata = det_metadata

        out.append((badge.slug, conf, resolve_source(llm, det), metadata))

    return out
```

### 5.4 UI display rules (forward-pointer to Section 6)

The UI shows policy badges that fire at the item card level (Section 6
covers full Smart Brevity Card design). Display rules:

| Confidence | Visual treatment |
|---|---|
| 1.0 (both) | Solid badge chip with full color |
| 0.6 (one) | Outlined badge chip, slightly muted |

**Ordering rule (decision #64):** Process badges always render BEFORE
policy badges. Within process, sorted by alarm level:

1. 💰 hidden_on_consent
2. ⚖️ legal_settlement
3. 🔥 contested
4. 🤝 sole_source
5. 🚨 emergency_action
6. 🪧 split_vote
7. ↩️ amends_prior_contract

Within policy: highest confidence first, then alphabetical by slug.

When >3 badges fire, the first 3 by this ordering render; remainder
collapse to "+N more" expandable. Process-first ordering ensures the
most time-sensitive oversight signals (Hidden on Consent, Settlement,
Contested) are never buried.

Category landing pages (Section 6.4) only show items with confidence ≥ 0.6
by default; admins can toggle "include low-confidence" for review.

### 5.5 Per-city expansion plan

Adding a new city's policy badges (Phase 4 or sooner):

1. **Identify stated priorities** — read the mayor's State-of-the-City
   address, fiscal-year priorities document, council strategic plan, etc.
   This is editorial work, not engineering.
2. **Pick from existing templates first** — most policy areas (blight,
   housing, public safety) already have templates from BHM. Reuse with
   per-city overrides on `name_override` and `matcher_hints_override`
   for local nuance.
3. **Add new templates only when genuinely novel** — e.g., Mobile has a
   distinct port/maritime concern that BHM doesn't. New template:
   `port_maritime`.
4. **INSERT into `priority_badges_config`** with the city's template
   selections and any overrides. Backfill script kicks off to rematch
   historical items against the newly-enabled badges (cheap deterministic
   pass; no LLM re-runs needed).

For v1 launch, no other city is opted in — keeps editorial scope tight.
Mobile is the most likely Phase 4 first follower based on current data
volume.

### 5.6 Edge cases & matcher tuning

#### Negation patterns

The deterministic keyword match doesn't handle negation ("this is NOT a
blight item"). v1 accepts the false-positive rate this introduces.
Mitigation: the LLM side rarely fires on negated items (it has full
context), so the `confidence=0.6 (deterministic-only)` items get the
visual outline that signals "lower confidence" and admin reviewers know
to check those more carefully.

If specific patterns over-fire (caught via the calibration dashboard
volume report — Section 5.7), per-city `matcher_hints_override` can
add `excluded_phrases` to the JSONB. v1 honors it if present:

```python
# In deterministic_policy_match, before keyword loop:
for excl in hints.get('excluded_phrases', []):
    if excl.lower() in text.lower():
        return False        # explicit exclusion overrides everything
```

This was deliberately not added to v1 default hints (no city has shown
this need yet) but the matcher loop honors it.

#### Multi-badge items

A single item can hit multiple policy badges — a Flock contract using
ARPA money in a blighted neighborhood could fire `public_safety_tech_privacy`
+ `blight_accountability`. All matching badges land as separate rows in
`agenda_item_badges`. UI displays up to 3 policy badges per card; >3 collapses
into "+N more" with hover/click to expand.

#### What if no policy badges fire?

That's the common case for routine items. The card shows process badges
only (or none). No empty "no policy badges" placeholder.

### 5.7 Calibration & evolution

Daily admin task `policy_badge_calibration` (extends the existing
`calibration_report` task) surfaces:

```sql
-- Volume per (city, badge, week) — flag spikes/troughs
SELECT
  m.city_id,
  aib.badge_slug,
  DATE_TRUNC('week', ai.updated_at)::date AS week,
  COUNT(*) AS n_items,
  COUNT(*) FILTER (WHERE aib.confidence >= 1.0) AS n_high_conf,
  COUNT(*) FILTER (WHERE aib.source = 'deterministic') AS n_deterministic_only,
  COUNT(*) FILTER (WHERE aib.source = 'llm') AS n_llm_only
FROM agenda_item_badges aib
JOIN agenda_items ai ON ai.id = aib.agenda_item_id
JOIN meetings m ON m.id = ai.meeting_id
WHERE aib.kind = 'policy'
  AND ai.updated_at > NOW() - INTERVAL '12 weeks'
GROUP BY m.city_id, aib.badge_slug, week
ORDER BY m.city_id, aib.badge_slug, week DESC;
```

Two signals to watch:
- **High `n_deterministic_only` ratio** — keyword match firing without LLM
  agreement. Either LLM is missing it (prompt needs tuning) or keyword is
  over-matching (add excluded_phrases). Threshold: if >40% of badge fires
  in a week are deterministic-only, flag for review.
- **High `n_llm_only` ratio** — LLM picking up the badge but keyword/topic
  rules aren't catching it. Suggests adding new keyword patterns to
  `default_matcher_hints` or `matcher_hints_override`. Threshold: same
  >40%.

#### Top False Positives (decision #65)

Admin add/remove events on `agenda_item_badges` are logged to a separate
audit table:

```sql
CREATE TABLE agenda_item_badges_audit (
  id              SERIAL PRIMARY KEY,
  agenda_item_id  INT NOT NULL REFERENCES agenda_items(id),
  badge_slug      TEXT NOT NULL,
  action          TEXT NOT NULL CHECK (action IN ('added', 'removed', 'modified')),
  actor           TEXT,                                  -- admin username or 'system'
  actor_role      TEXT NOT NULL CHECK (
                    actor_role IN ('admin', 'cron', 'on_write')
                  ),
  reason          TEXT,
  occurred_at     TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_badge_audit_recent
  ON agenda_item_badges_audit (occurred_at DESC, badge_slug, action)
  WHERE actor_role = 'admin';
```

The calibration task adds a "Top False Positives" query:

```sql
-- Policy badges admins removed >5 times in 7 days
SELECT
  m.city_id,
  aiba.badge_slug,
  COUNT(*) AS n_removals,
  ARRAY_AGG(DISTINCT aiba.reason) FILTER (WHERE aiba.reason IS NOT NULL)
    AS reasons_cited
FROM agenda_item_badges_audit aiba
JOIN agenda_items ai ON ai.id = aiba.agenda_item_id
JOIN meetings m ON m.id = ai.meeting_id
WHERE aiba.action = 'removed'
  AND aiba.actor_role = 'admin'
  AND aiba.occurred_at > NOW() - INTERVAL '7 days'
GROUP BY m.city_id, aiba.badge_slug
HAVING COUNT(*) >= 5
ORDER BY n_removals DESC;
```

If a badge surfaces here, admin reviewers know exactly which one is
over-firing AND can read the captured `reason` strings for the pattern.
Triggers a prompt-version bump or matcher_hints update.

The audit log also formalizes manual-badge preservation (decision #57)
— when an admin manually adds a badge with `source='manual'`, the audit
log captures who and why.

Per badge, the dashboard shows weekly volume trend. The "did the
administration do what they said" lens (decision-conversation insight)
naturally falls out of this view: if blight badge volume drops by 50%
quarter-over-quarter, that's the headline.

---

## Section 6 — UI changes

The existing app uses Flask + Jinja2 + HTMX with an editorial design system
(Source Serif + IBM Plex). Section 6 changes layer onto that — no SPA
rebuild, no new JS libraries. Charts render as server-side SVG. Filters
use HTMX for partial updates.

### 6.1 Smart Brevity Card — variants & state machine

The card replaces the existing item rendering on `meeting_detail.html`,
city overview, search results, and the new category landing pages. Six
variants drive off `processing_status` and `data_quality`:

```
                          ┌─────────────────────┐
                          │ AgendaItem          │
                          └──────────┬──────────┘
                                     │
            ┌────────────────────────┼────────────────────────┐
            │                        │                        │
            ▼                        ▼                        ▼
   data_quality != 'ok'     processing_status =      ai_rewrite_version
                            'procedural_skipped'      = 3 (current v3)
            │                        │                        │
            ▼                        ▼                        ▼
   ┌─────────────────┐    ┌─────────────────┐      ┌─────────────────┐
   │ degraded variant│    │ procedural      │      │ Smart Brevity   │
   │ "Source needs   │    │ variant         │      │ FULL variant    │
   │  OCR — [Report] │    │ (title-only)    │      │ headline + why_ │
   │  [View orig]"   │    │                 │      │ it_matters +    │
   └─────────────────┘    └─────────────────┘      │ facts + badges  │
                                                    └─────────────────┘

   processing_status =
   'failed_permanent'                              ai_rewrite_version
            │                                       = 2 (legacy v2)
            ▼                                                │
   ┌─────────────────┐                                       ▼
   │ failed variant  │                          ┌─────────────────────┐
   │ title + 🚧     │                          │ FALLBACK variant    │
   │ "Processing    │                          │ summary as why_it_  │
   │  Error" badge   │                          │ matters, no head-   │
   │ + [Report]      │                          │ line, "summary      │
   └─────────────────┘                          │ updating" chip      │
                                                 └─────────────────────┘
```

Single template (`partials/smart_brevity_card.html`) with branching;
the meeting page passes the item dict and the template selects the
variant based on the state machine.

```jinja
{# partials/smart_brevity_card.html — abbreviated #}
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

#### Full Smart Brevity variant

```
┌─────────────────────────────────────────────────────────────┐
│ 💰 Hidden on consent  🤝 Sole-source  🛡️ Public Safety Tech │  ← badges (process-first)
│                                                             │
│ Sole-source: Flock licenses extended 5 years for $1.8M     │  ← headline (≤60c)
│                                                             │
│ Higher per-camera rates affect surveillance budget          │  ← why_it_matters (≤200c)
│ in Wards 4-7; council-approved without competitive bid.    │
│                                                             │
│ ───────────────────────────────────────────────────────    │
│ 🏢 Counterparty: Flock Safety Inc.                         │  ← facts strip
│ 💵 Cost: $1,800,000 (Red tier)                             │
│ 🏛️ Funding: General fund                                   │
│ 📍 Location: Citywide                                      │
│ 📋 Action: Contract amendment (sole-source)                │
│                                                             │
│ ───────────────────────────────────────────────────────    │
│ 📅 Public hearing June 5 at 6:00 PM • 🏛️ Public Safety    │  ← engagement strip
│ Committee  •  📅 Check Birmingham's master calendar →      │
│                                                             │
│ [View Source: Page 4 of minutes_2026_05_03.pdf →]         │  ← source anchor
└─────────────────────────────────────────────────────────────┘
```

Facts strip pulls from `extracted_facts` JSONB. Empty fields are omitted
(no "Counterparty: not specified" placeholders).

**Dollar-tier accessibility (decisions #71 + #75):** facts strip renders
dollar amounts with both color tier AND symbolic suffix AND a
visually-hidden screen-reader label:

```jinja
{# partials/dollar_tier.html #}
<span class="dollars dollars--{{ tier }}"
      aria-label="{{ amount | format_dollars }}, {{ tier|title }} tier ({{ tier_description }})">
  {{ amount | format_dollars }}
  ({{ tier_symbol }})<span class="sr-only">, {{ tier|title }} tier</span>
</span>
```

Where:
- Green (<$50K) → `$87,500 ($)` + sr-only ", Green tier"
- Yellow ($50K-$250K) → `$120,000 ($$)` + sr-only ", Yellow tier"
- Orange ($250K-$1M) → `$640,000 ($$$)` + sr-only ", Orange tier"
- Red (>$1M) → `$1,800,000 ($$$$)` + sr-only ", Red tier"

`tier_description` for the parent `aria-label` adds the threshold
context (e.g., "over $1 million"). Triple-redundant signal: color +
symbol + screen-reader text. WCAG 2.1 AA compliant; tier perception
works without color, without sight, and on monochrome printouts.

**Mobile Brevity-First layout (decision #66):** below 768px viewport,
badge chips collapse to a horizontal scroll-snap row ABOVE the headline.
Headline + why_it_matters become the first content visible. CSS-only:

```css
@media (max-width: 768px) {
  .smart-brevity-card .badge-row {
    order: -1;                          /* move badges to top */
    overflow-x: auto;
    scroll-snap-type: x mandatory;
    display: flex;
    gap: 0.5rem;
    padding-bottom: 0.5rem;
  }
  .smart-brevity-card .badge-row .badge-chip {
    flex-shrink: 0;
    scroll-snap-align: start;
  }
  .smart-brevity-card .badge-more {
    /* "+N more" hidden on mobile — full row scrolls */
    display: none;
  }
}
```

On mobile, the "+N more" collapse drops in favor of native scroll —
citizens swipe through the full badge set.

#### Procedural variant

```
┌─────────────────────────────────────────────────────────────┐
│ Approval of minutes from May 1, 2026                       │
└─────────────────────────────────────────────────────────────┘
```

Title-only. No badges, no facts, no engagement strip. Compact list
density when many appear sequentially.

#### Degraded variant

```
┌─────────────────────────────────────────────────────────────┐
│ Resolution authorizing payment to ABC Construction Inc.    │
│                                                             │
│ ⚠️ Source document needs OCR — text not yet extractable    │
│                                                             │
│ [Report this issue]  [View original PDF]                   │
└─────────────────────────────────────────────────────────────┘
```

When `data_debt_priority='high'`, append a small admin-only chip
(visible to logged-in admins) showing priority and link to admin queue.

#### Failed-permanent variant

```
┌─────────────────────────────────────────────────────────────┐
│ 🚧 Processing Error                                        │
│                                                             │
│ Resolution amending agreement #2024-12-345                 │
│                                                             │
│ Our automated systems couldn't process this item after     │
│ 3 attempts. The original document is available below.      │
│                                                             │
│ [Report this]  [View original]                             │
└─────────────────────────────────────────────────────────────┘
```

Searchable (FTS still indexes title) but visually flagged so citizens
know it's not silently missing.

#### Cross-stage-conflict variant

```
┌─────────────────────────────────────────────────────────────┐
│ ⚠️ Verification in progress                                │  ← top pill
│ 💰 Hidden on consent ✨  🤝 Sole-source ✨                  │  ← badges still render below
│                                                             │
│ Sole-source: Flock licenses extended 5 years for $1.8M     │  ← v3 outputs shown
│                                                             │
│ Higher per-camera rates affect surveillance budget...       │
│ ─── facts strip ───                                         │
│                                                             │
│ Note: Our automated reading of this item is being           │
│ double-checked. The summary above is best-effort while     │
│ verification is pending.                                    │
└─────────────────────────────────────────────────────────────┘
```

Triggered by `processing_status='cross_stage_conflict'` (decision #45 +
#72). Auto-retry resolves most cases before they reach this state; the
admin queue lists outstanding ones. Once resolved, status flips to
`completed` and pill disappears.

**Tooltip-only explainer (decision #76 retired in favor of tooltips):**
the pill carries a `title` attribute and an `aria-label` so hover (desktop)
and screen readers convey the explanation without breaking reading flow.
No modal, no HTMX endpoint — citizens get the meaning passively.

```jinja
{# partials/card_verification_pending.html — pill markup #}
<span class="verification-pill"
      title="Our automated systems read this item in two passes (facts and summary). When those disagree we hold the result for manual review. Most resolve within a day; the summary above is best-effort."
      aria-label="Verification in progress: dual-pass review pending; summary is best-effort">
  ⚠️ Verification in progress
</span>
```

Same pattern for the `🚧 Processing Error` pill: tooltip explains the
3-attempt retry + manual resolution path. Modal-based UX was retired —
tooltips are cheaper, mobile-friendly via long-press, and don't break
reading flow.

#### v2-fallback variant (transition window)

```
┌─────────────────────────────────────────────────────────────┐
│ ⏳ summary updating                                         │
│                                                             │
│ Resolution authorizing payment to ABC Construction Inc.    │
│ for landscape maintenance services in 2026 budget cycle.   │
│ The contract amount is $87,500 and runs through Dec 2026.  │
│                                                             │
│ [View original]                                             │
└─────────────────────────────────────────────────────────────┘
```

Renders the v2 `summary` directly; no `headline` available. The
"summary updating" chip is a small grey pill, honest about state. This
variant disappears once Migration 014 drops the `summary` column.

### 6.2 Badge chip rendering

Single template `partials/badge_chip.html`:

```jinja
{# partials/badge_chip.html #}
<span class="badge-chip
             badge-{{ badge.kind }}
             badge-conf-{{ 'high' if badge.confidence >= 1.0 else 'medium' }}
             badge-slug-{{ badge.slug }}"
      title="{{ badge.description }}{% if badge.confidence >= 1.0 %} · AI-verified{% endif %}">
  {{ badge.icon }} {{ badge.name }}
  {% if badge.slug == 'split_vote' or badge.slug == 'contested' %}
    {% if vote_count %}
      <span class="badge-meta">{{ vote_count.yes }}-{{ vote_count.no }}</span>
    {% endif %}
  {% endif %}
  {# Verification Spark — decision #67 #}
  {% if badge.confidence >= 1.0 %}<span class="badge-spark" aria-label="AI-verified">✨</span>{% endif %}
</span>
```

Visual treatment:

| Selector | Treatment |
|---|---|
| `.badge-conf-high` | Solid background + ✨ Verification Spark suffix (decision #67) |
| `.badge-conf-medium` | Solid background, no spark |
| `.badge-process` | Red/orange/yellow palette per alarm level |
| `.badge-policy` | Cool palette (blue/green/purple per badge) |

**Verification Spark (decision #67):** the ✨ icon is the primary
high-confidence signal — additive marking that reads faster than the
older outlined-vs-solid treatment. Outlined chips reserved for
disabled/inactive states only. The `aria-label="AI-verified"` ensures
screen readers convey the same meaning.

**Badge legend (decision #74):** desktop hover-tooltip via the existing
`title` attribute is fine but doesn't reach mobile users. Each city
page header carries a one-line legend just below the city name:

```jinja
{# In templates/city.html, immediately after the city headline #}
<p class="badge-legend" id="badge-legend">
  Badges show oversight
  (<span class="badge-process-sample">process</span>)
  and priorities
  (<span class="badge-policy-sample">policy</span>).
  <span class="badge-spark">✨</span> = AI-verified by multiple sources.
  <a href="{{ url_for('public.about_badges') }}">Learn more →</a>
</p>
```

A 24h-cookie-gated first-visit popover appears on the first city page
a citizen visits — same legend content, dismissible, written once
to localStorage so it doesn't reappear. Implementation uses a tiny
HTMX-friendly Alpine.js sliver (already in the existing app) or pure
CSS + checkbox state.

**Strict priority sort across viewports (decision #73):** the mobile
horizontal carousel uses the same `order_badges` Python helper as
desktop. There is no "show top 3 on desktop, scroll-all on mobile"
asymmetry — both viewports see badges in the same priority order. On
mobile the user swipes; on desktop the user clicks "+N more" to expand.
The first three positions in BOTH layouts are always process badges if
any are present.

Badge ordering (decision #64) applied at render time:

```python
def order_badges(badges: list[BadgeChip]) -> list[BadgeChip]:
    process_alarm_order = [
        'hidden_on_consent', 'legal_settlement', 'contested',
        'sole_source', 'emergency_action', 'split_vote',
        'amends_prior_contract',
    ]
    process = sorted(
        [b for b in badges if b.kind == 'process'],
        key=lambda b: process_alarm_order.index(b.slug)
                       if b.slug in process_alarm_order else 999,
    )
    policy = sorted(
        [b for b in badges if b.kind == 'policy'],
        key=lambda b: (-b.confidence, b.slug),
    )
    return process + policy
```

Collapse rule (>3 badges):

```jinja
{% set ordered = badges | order_badges %}
{% for chip in ordered[:3] %}
  {% include 'partials/badge_chip.html' %}
{% endfor %}
{% if ordered|length > 3 %}
  <button class="badge-more"
          hx-get="/items/{{ item.id }}/badges"
          hx-target="this"
          hx-swap="outerHTML">
    +{{ ordered|length - 3 }} more
  </button>
{% endif %}
```

HTMX expands inline on click; no full page reload.

### 6.3 Engagement strip

```jinja
{# partials/engagement_strip.html #}
{% set ns = item.next_steps or {} %}
{% set has_any = ns.committee_referral or ns.public_hearing_date
                  or ns.comment_period_end or ns.implementation_date %}

{% if has_any %}
  <div class="engagement-strip">
    {% if ns.public_hearing_date %}
      📅 Public hearing
      {{ ns.public_hearing_date | format_date }}
      {% if ns.public_hearing_time %} at {{ ns.public_hearing_time }}{% endif %}
    {% endif %}

    {% if ns.committee_referral %}
      • 🏛️ {{ ns.committee_referral }}
    {% endif %}

    {% if ns.comment_period_end %}
      • 📝 Comment by {{ ns.comment_period_end | format_date }}
    {% endif %}

    {% if ns.implementation_date %}
      • ▶️ Effective {{ ns.implementation_date | format_date }}
    {% endif %}

    {% if city.master_calendar_url %}
      • <a href="{{ city.master_calendar_url }}" rel="noopener">
        📅 City master calendar →
      </a>
    {% endif %}
  </div>

{# Context-aware: action_type hints at upcoming hearing but date is null (decision #70) #}
{% elif facts.action_type == 'public_hearing_set' and not ns.public_hearing_date %}
  <div class="engagement-strip engagement-strip--awaiting">
    Awaiting hearing date —
    <a href="{{ url_for('public.upcoming_hearings_rss', city=city.slug) }}"
       rel="noopener">
      📅 Subscribe to upcoming hearings RSS →
    </a>
    <span class="report-issue-link">
      <a href="mailto:{{ config.ADMIN_EMAIL }}?subject=Missing hearing date for item {{ item.id }}&body=Item URL: {{ url_for('public.item_detail', city=city.slug, item_id=item.id, _external=True) }}%0D%0A%0D%0AThis item has action_type=public_hearing_set but no hearing date is shown.">
        Report missing date
      </a>
    </span>
  </div>

{% elif city.master_calendar_url %}
  <div class="engagement-strip engagement-strip--fallback">
    <a href="{{ city.master_calendar_url }}" rel="noopener">
      📅 Check {{ city.name }}'s master calendar →
    </a>
  </div>
{% endif %}
```

Auto-hides when nothing to show (no `else` branch with placeholder text).
The action-type-aware variant signals to citizens that the data is
*expected* not just *missing* — and the RSS link is the path forward
until citizen-account notifications land in Phase 4.

### 6.4 Source-anchor deep links

`partials/source_anchor_button.html` adapts to the captured anchor level:

```jinja
{% set anchor = item.source_anchor or {} %}

{% if anchor.type == 'pdf' %}
  {% if anchor.bbox %}
    <a href="{{ anchor.url }}#page={{ anchor.page }}" class="view-source">
      View Source: PDF page {{ anchor.page }} (region) →
    </a>
  {% elif anchor.page %}
    <a href="{{ anchor.url }}#page={{ anchor.page }}" class="view-source">
      View Source: PDF page {{ anchor.page }} →
    </a>
  {% else %}
    <a href="{{ anchor.url }}" class="view-source">
      View Source: PDF →
    </a>
  {% endif %}

{% elif anchor.type == 'html' and anchor.anchor %}
  <a href="{{ anchor.url }}{{ anchor.anchor }}" class="view-source">
    View Source: agenda item →
  </a>

{% elif anchor.type == 'video' and anchor.timestamp_seconds %}
  <a href="{{ anchor.url }}?t={{ anchor.timestamp_seconds }}" class="view-source">
    View Source: video at {{ anchor.timestamp_seconds | format_timestamp }} →
  </a>

{% elif anchor.url %}
  <a href="{{ anchor.url }}" class="view-source">
    View Source →
  </a>

{% elif item.data_quality == 'no_text_layer' %}
  <span class="view-source view-source--unavailable">
    Source needs OCR
    {% if g.user.is_admin %}
      <a href="{{ url_for('admin.data_debt', highlight=item.id) }}">
        [admin queue]
      </a>
    {% endif %}
  </span>
{% endif %}
```

Browser handles `#page=` and `?t=` natively for PDF and YouTube/Granicus
video viewers. No client-side JS required.

### 6.5 Category landing pages

New route `/al/<city>/<badge_slug>` rendered by `web/public.py`. Each
landing page has 5 sections:

```
┌─────────────────────────────────────────────────────────────┐
│ 🏚️ Blight Accountability                                    │  ← header (badge name + icon + city)
│ Tracking Birmingham's blight enforcement, 2017-2026         │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│ This year: 23 items · $4.2M total spent                    │  ← KPI strip
│ Mayor Woodfin's stated 2026 priority                       │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  ▁▂▄▃▅▇█▆▅▃▂▁  ▁▂▄▃▅▇█▆▅▃▂▁                                │  ← volume timeline (SVG)
│  2024  2025  2026                                           │
│  [Woodfin term overlay]                                     │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│ Filter: [All confidence ▼] [Cross-filter ▼]               │  ← filter controls (HTMX)
│                                                             │
├─────────────────────────────────────────────────────────────┤
│ ┌─ item card ──────────────────────────────────────┐       │  ← item list
│ │ Smart Brevity Card                                │       │
│ └───────────────────────────────────────────────────┘       │
│ ┌─ item card ──────────────────────────────────────┐       │
│ │ Smart Brevity Card                                │       │
│ └───────────────────────────────────────────────────┘       │
│ [load more]                                                 │
└─────────────────────────────────────────────────────────────┘
```

Service-layer query (`docket/services/query.py`):

```python
def list_items_by_badge(city_id: int, badge_slug: str,
                        min_confidence: float = 0.6,
                        cross_filter_slugs: list[str] = (),
                        limit: int = 25,
                        offset: int = 0,
                        include_low_significance: bool = False) -> list[AgendaItem]:
    """Items with badge_slug, optionally also having cross-filter badges.
    Default min_confidence=0.6 hides single-source matches; admins toggle off.

    Render-time significance gate (decision #61): for policy badges, items
    are filtered by significance_score >= per-badge min_significance
    (default 3 from `priority_badges_config.matcher_hints_override`).
    Admins can pass include_low_significance=True to see everything.
    Process badges have no significance gate — they're always-on."""

    # Resolve the per-badge significance threshold (policy only)
    badge_template = lookup_badge_template(badge_slug)
    apply_sig_gate = (
        badge_template.kind == 'policy'
        and not include_low_significance
    )
    min_sig = (
        resolve_policy_badge(city_id, badge_slug).matcher_hints
            .get('min_significance', 3)
        if apply_sig_gate else None
    )

    sql = """
        SELECT ai.*
        FROM agenda_items ai
        JOIN agenda_item_badges aib ON aib.agenda_item_id = ai.id
        JOIN meetings m ON m.id = ai.meeting_id
        WHERE m.city_id = %s
          AND aib.badge_slug = %s
          AND aib.confidence >= %s
          AND ai.processing_status = 'completed'
    """
    params = [city_id, badge_slug, min_confidence]

    if min_sig is not None:
        sql += " AND ai.significance_score >= %s"
        params.append(min_sig)

    for cross_slug in cross_filter_slugs:
        sql += """
          AND EXISTS (
            SELECT 1 FROM agenda_item_badges x
            WHERE x.agenda_item_id = ai.id AND x.badge_slug = %s
          )
        """
        params.append(cross_slug)

    sql += " ORDER BY m.meeting_date DESC, ai.dollars_amount DESC NULLS LAST"
    sql += " LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    return execute(sql, params)
```

The same render-time gate applies in two other read paths:
- **Search results** (when narrowing by badge slug) — filtered by `significance_score >= 3` for policy badges
- **Smart Brevity Card badge chips** — when rendering the chip list per item, policy chips with significance below threshold are filtered out (process chips always render)

These three call sites share a small helper `apply_policy_significance_gate(items, badge_slug, city_id)` so the threshold logic stays in one place.

KPI strip:

```python
def category_kpis(city_id: int, badge_slug: str,
                   year: int) -> dict:
    return {
        'item_count': count_items(city_id, badge_slug, year),
        'total_dollars': sum_dollars(city_id, badge_slug, year),
        'mayor_priority_quote': lookup_priority_quote(city_id, badge_slug, year),
    }
```

`mayor_priority_quote` is editorial — populated in `priority_badges_config.notes`
or a separate `priority_quotes` table. Phase 4 work; v1 omits or hardcodes.

### 6.6 Volume timeline (SVG)

Server-rendered, no client-side JS. Data shape:

```python
def badge_volume_series(city_id: int, badge_slug: str,
                          start_date: date, end_date: date,
                          bucket: Literal['week', 'month'] = 'month') -> list[dict]:
    """Returns [{period, n_items, total_dollars}, ...] for charting."""
```

Render as a `<partials/volume_timeline.html>` partial:

```jinja
{# partials/volume_timeline.html — server-rendered SVG bars #}
<svg viewBox="0 0 800 200" class="volume-timeline" role="img"
     aria-label="{{ badge.name }} volume by {{ bucket }}">

  {# Mayoral term overlay bands (background) #}
  {% for term in mayoral_terms %}
    <rect x="{{ term.x_start }}" y="0"
          width="{{ term.width }}" height="200"
          class="term-overlay term-overlay--{{ term.party }}"
          opacity="0.08"/>
    <text x="{{ term.x_label }}" y="14"
          class="term-label">{{ term.mayor }}</text>
  {% endfor %}

  {# Volume bars #}
  {% for point in series %}
    <rect x="{{ point.x }}" y="{{ point.y }}"
          width="{{ point.width }}" height="{{ point.height }}"
          class="volume-bar"
          data-period="{{ point.period }}"
          data-count="{{ point.n_items }}">
      <title>{{ point.period }}: {{ point.n_items }} items, ${{ point.total_dollars | format_dollars }}</title>
    </rect>
  {% endfor %}

  {# X-axis labels (year ticks) #}
  {% for year in year_ticks %}
    <text x="{{ year.x }}" y="195"
          class="axis-label" text-anchor="middle">{{ year.year }}</text>
  {% endfor %}
</svg>
```

CSS handles theming (Source Serif font, dark/light mode). Hover tooltip is
SVG `<title>` (browser-native).

The mayoral-term overlay turns the chart into the accountability-lens
view: a citizen sees which mayor presided over each volume change.
Birmingham's `mayoral_terms` table seeded in Migration 013 (or in the
existing seed migrations if BHM data already exists).

**Consent baseline overlay (decision #68):** each volume bar is split
into two segments — the lower portion (saturated color) is items NOT on
consent, the upper portion (lighter shade) is items ON consent. The
ratio surfaces the "stated priority vs actually-deliberated" gap at a
glance. If "Blight" is a stated priority but 90% of blight items are
on consent without discussion, the bar is mostly the lighter shade.

```jinja
{# inside the volume bars loop — modified to show consent split #}
{% for point in series %}
  {# Lower segment: items NOT on consent (substantive deliberation) #}
  <rect x="{{ point.x }}" y="{{ point.y_substantive }}"
        width="{{ point.width }}" height="{{ point.height_substantive }}"
        class="volume-bar volume-bar--substantive"/>
  {# Upper segment: items ON consent (rubber-stamped) #}
  <rect x="{{ point.x }}" y="{{ point.y_consent }}"
        width="{{ point.width }}" height="{{ point.height_consent }}"
        class="volume-bar volume-bar--consent">
    <title>{{ point.period }}: {{ point.n_items }} total
({{ point.n_consent }} on consent, {{ point.n_substantive }} substantive),
${{ point.total_dollars | format_dollars }}</title>
  </rect>
{% endfor %}
```

Service-layer query gains a `n_consent` field per bucket:

```sql
SELECT
  DATE_TRUNC(:bucket, m.meeting_date)::date AS period,
  COUNT(*) AS n_items,
  COUNT(*) FILTER (WHERE ai.is_consent = TRUE) AS n_consent,
  COUNT(*) FILTER (WHERE ai.is_consent = FALSE) AS n_substantive,
  COALESCE(SUM(ai.dollars_amount), 0) AS total_dollars
FROM agenda_items ai
JOIN meetings m ON m.id = ai.meeting_id
JOIN agenda_item_badges aib ON aib.agenda_item_id = ai.id
WHERE m.city_id = :city AND aib.badge_slug = :slug
  AND aib.confidence >= 0.6
  AND m.meeting_date BETWEEN :start AND :end
GROUP BY period
ORDER BY period;
```

The materialized view `mv_badge_volume_monthly` (Section 6.11) gets
extended with the `n_consent` column to keep the timeline render fast.

### 6.7 Homepage "Browse by Priority"

Adds a section to existing `templates/city.html`:

```jinja
{# city.html — new section #}
<section class="browse-by-priority">
  <h2>Browse by priority</h2>

  <div class="priority-grid">
    {% for badge in city_policy_badges %}
      <a href="{{ url_for('public.category_landing',
                           city=city.slug, badge_slug=badge.slug) }}"
         class="priority-tile">
        <div class="priority-tile__icon">{{ badge.icon }}</div>
        <div class="priority-tile__name">{{ badge.name }}</div>
        <div class="priority-tile__count">
          {{ badge_volume_year(city.id, badge.slug) }} this year
        </div>
      </a>
    {% endfor %}
  </div>

  <h3>Process transparency</h3>
  <div class="priority-grid priority-grid--process">
    {% for badge in process_badges %}
      <a href="{{ url_for('public.category_landing',
                           city=city.slug, badge_slug=badge.slug) }}"
         class="priority-tile priority-tile--process">
        <div class="priority-tile__icon">{{ badge.icon }}</div>
        <div class="priority-tile__name">{{ badge.name }}</div>
        <div class="priority-tile__count">
          {{ badge_volume_recent(city.id, badge.slug, days=30) }} last 30 days
        </div>
      </a>
    {% endfor %}
  </div>
</section>
```

Two grids: policy (4 tiles for BHM) and process (7 tiles always).

### 6.8 Cross-filters

Category landing pages support combining badges via URL query params:
`/al/birmingham/blight?and=hidden_on_consent`. The route reads the `and`
param (comma-separated for multiple), validates against enabled badges,
and passes to `list_items_by_badge`.

UI control is an HTMX-driven dropdown:

```jinja
<select name="and" class="cross-filter"
        hx-get="{{ url_for('public.category_landing',
                            city=city.slug, badge_slug=badge.slug) }}"
        hx-target="#item-list"
        hx-include="[name='and']"
        hx-trigger="change"
        hx-push-url="true">
  <option value="">— combine with another badge —</option>
  {% for other in available_badges if other.slug != badge.slug %}
    <option value="{{ other.slug }}"
            {% if other.slug in active_cross_filters %}selected{% endif %}>
      {{ other.icon }} {{ other.name }}
    </option>
  {% endfor %}
</select>
```

Pushes URL state via `hx-push-url` so citizens can bookmark / share
filtered views.

### 6.9 Public data-debt page

New route `/al/<city>/data-debt`. Lists items where
`data_quality != 'ok'` OR `processing_status='failed_permanent'`,
sorted by `data_debt_priority DESC, meeting_date DESC`.

```
┌─────────────────────────────────────────────────────────────┐
│ Data debt — items not yet machine-readable                  │
│                                                             │
│ These items exist on the city's public record, but our      │
│ automated systems can't extract them. Most need OCR.        │
│                                                             │
│ Subscribe to RSS: [link]                                    │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│ ⚠️ HIGH                                                     │
│ • Resolution authorizing $1.4M emergency repair             │
│   Birmingham, Jan 14, 2026 — needs OCR                      │
│ • Settlement of [redacted] claim                            │
│   Birmingham, Mar 22, 2026 — needs OCR                      │
│                                                             │
│ NORMAL (124 items)                                          │
│ • [load more]                                                │
└─────────────────────────────────────────────────────────────┘
```

RSS feed at `/al/<city>/data-debt.rss` (decision #32 — citizens
bookmark/RSS until citizen-account notification feature in Phase 4).

### 6.10 Admin views

Four new admin routes (require `login_required`):

| Route | Purpose |
|---|---|
| `/admin/calibration` | Score-divergence dashboard, regex-miss telemetry, top false-positives |
| `/admin/data-debt` | Same content as public page + edit controls + priority sort |
| `/admin/errors` | Items with `processing_status='failed_permanent'`, retry/escalate buttons |
| `/admin/badges/audit` | `agenda_item_badges_audit` log viewer, filterable by badge/actor/date |

Manual badge add/remove uses HTMX endpoints that write to
`agenda_item_badges` AND `agenda_item_badges_audit` in one transaction.

**Note:** decision #77 (`data_issue_reports` schema + admin queue) was
retired in favor of `mailto:` links pointing at `municipalities.admin_email`.
v1 ships with **4 admin routes**, not 5. Citizen issue reports flow via
email and are triaged out-of-app. Phase 4 can revisit when citizen
accounts and notification subsystem exist.

### 6.11 Performance & caching

Category landing pages potentially aggregate heavy queries (volume timelines
across years). Per project memory ("Railway landing page queries must be
lightweight — caused OOM/timeout on the small Railway instance"):

- **Materialized view** `mv_badge_volume_monthly` refreshed nightly:
  ```sql
  CREATE MATERIALIZED VIEW mv_badge_volume_monthly AS
  SELECT
    m.city_id,
    aib.badge_slug,
    DATE_TRUNC('month', m.meeting_date)::date AS month,
    COUNT(*) AS n_items,
    COALESCE(SUM(ai.dollars_amount), 0) AS total_dollars
  FROM agenda_item_badges aib
  JOIN agenda_items ai ON ai.id = aib.agenda_item_id
  JOIN meetings m ON m.id = ai.meeting_id
  WHERE aib.confidence >= 0.6
  GROUP BY m.city_id, aib.badge_slug, month;

  CREATE UNIQUE INDEX ON mv_badge_volume_monthly (city_id, badge_slug, month);
  ```
- Refreshed by `process_badges` task (after badges land): `REFRESH
  MATERIALIZED VIEW CONCURRENTLY mv_badge_volume_monthly`.
- Volume timeline reads from the MV — sub-100ms even for 10-year ranges.

- **Item-list pagination** uses standard LIMIT/OFFSET with index on
  `(meeting.city_id, meeting_date DESC, agenda_items.dollars_amount DESC)`.
  Default page size 25.

- **Smart Brevity Card render** is template-only — no per-card DB
  calls. The list view fetches items + badges + meeting in 2 queries
  (items joined to meetings; badges in a single `WHERE agenda_item_id IN (...)`).

---

## Section 7 — Backfill plan

The new pipeline (Stage 0 → Stage 2.5 + badges) needs to process every
substantive agenda item across 4 cities × ~8.5 years (2017-2026). This
section spells out execution: how the work is paced, how the budget is
managed, how prompt iterations interleave with batch runs, and what
happens when items fail mid-stream.

### 7.1 Scope & cost projection

**Working set:** ~75K agenda items across BHM/Mobile/Vestavia/Homewood
based on existing data volumes.

The plan is staged across **five waves**: Wave 0 is a non-LLM
pre-pass that runs Stage 0a (data quality) and Stage 0b (procedural
regex) across the full archive. Wave 0.5 is a small synchronous
burst on the current calendar month — pays standard API rates instead
of Batches API for ~4-hour turnaround instead of 1-2 days, so
citizens see v3 cards on the most-watched recent meetings within
hours of deploy. Waves 1-3 then process the remaining `pending`
items via Batches API in checkpointed date-range blocks.

| Wave | What | Est. items | Cost | Time |
|---|---|---|---|---|
| Wave 0 | Stage 0a + 0b across full archive (no LLM, decision #78) | ~75,000 | **$0** | hours |
| Wave 0.5 | **Live calibration burst** — items where `meeting_date >= DATE_TRUNC('month', CURRENT_DATE)` via standard sync API (decision #88) | ~500-1,000 | ~$8 | hours |
| Wave 1 | Stage 1+2 on remaining 2026 `pending` items via Batches API | ~5,500 | ~$12 | 1-2 days |
| Wave 2 | Stage 1+2 on 2021-2025 `pending` items via Batches API | ~28,000 | ~$63 | 4-7 days |
| Wave 3 | Stage 1+2 on 2017-2020 `pending` items via Batches API | ~16,000 | ~$36 | 2-4 days |
| **Total** | **Wave 0 + 0.5 + Waves 1-3** | **~50,000 LLM-processed** | **~$119** | **7-14 days** |

(Original pre-Wave-0 estimate was ~64K LLM-processed at ~$144. Wave 0
quantifies the actual procedural-skip + data-quality-skip rate from
real data; revised projections will replace the estimates above. Most
likely the actual number lands lower because Alabama councils are
procedural-heavy, especially in older archives.)

Per-item cost assumption: ~$0.0045 effective (Haiku 4.5 with
cache_control on system prompt). Batches API discount: 50%.

**Daily budget gate:** `AI_DAILY_BUDGET_USD` raised to **$30** during
backfill weeks. Below that cap the worker self-paces; above it, queues
the rest for the next day. The whole backfill completes in 7-14
calendar days at $30/day depending on Batches API latency.

### Wave 0 mechanics

Wave 0 is a single non-LLM pass that hits every agenda item in the
archive in priority order (newest first):

```python
# scripts/backfill_wave_0.py
def run_wave_0(city_ids: list[int]) -> Wave0Report:
    """Runs Stage 0a + 0b across the entire archive. No LLM calls.
    Sets data_quality, data_debt_priority, processing_status for
    every item. Idempotent — safe to re-run."""

    cur.execute("""
        SELECT ai.id, ai.title, ai.description, ai.raw_text,
               ai.source_type, m.id AS meeting_id
        FROM agenda_items ai
        JOIN meetings m ON m.id = ai.meeting_id
        WHERE m.city_id = ANY(%s)
          AND ai.ai_extraction_version IS NULL
          AND ai.processing_status IN ('pending', NULL)
        ORDER BY m.meeting_date DESC
    """, [city_ids])

    counts = Counter()
    for row in cur:
        item = AgendaItem(**row)

        # Stage 0a — data quality gate (Section 2.1)
        quality, priority = evaluate_data_quality(item)

        if quality != 'ok':
            update_item(item.id,
                       data_quality=quality,
                       data_debt_priority=priority,
                       processing_status='data_quality_skipped')
            counts['data_quality_skipped'] += 1
            continue

        # Stage 0b — procedural regex (Section 2.2)
        if any(re.match(p, item.title or '', re.IGNORECASE)
               for p in PROCEDURAL_TITLE_PATTERNS):
            update_item(item.id,
                       data_quality='ok',
                       processing_status='procedural_skipped')
            counts['procedural_skipped'] += 1
            continue

        # Survives both gates — eligible for Wave 1+
        update_item(item.id,
                   data_quality='ok',
                   data_debt_priority='normal',
                   processing_status='pending')
        counts['pending'] += 1

    return Wave0Report(counts=counts, ...)
```

After Wave 0 completes, the LLM workload is exactly `counts['pending']`.
Wave 1's batch driver scopes its first SQL to `WHERE processing_status = 'pending' AND meeting_date >= '2026-01-01'`.

Re-cost projection: re-run Wave 0's count query and update the
`AI_DAILY_BUDGET_USD` ceiling if needed.

**Idempotent:** Wave 0 is safe to re-run if Stage 0a/0b regex patterns
get refined later. Items already classified just get re-evaluated; no
data loss.

### 7.2 Wave ordering — why 2026 → 2021 → 2017

The order is deliberate. Each wave is a **prompt-validation
checkpoint** before committing to the next:

```
Wave 1 (2026 — recent)
   │
   ▼  Process ~7,500 items
   │  Spot-check headlines, why_it_matters, badge accuracy
   │  Run calibration_report task on the new data
   │  IF metrics good: proceed
   │  IF prompt issues: bump ITEM_PROMPT_VERSION, re-process Wave 1
   │
   ▼  Wave 2 (2021-2025 — mid-range)
   │  Process ~36,000 items
   │  Same checkpoint — most likely to surface drift
   │
   ▼  Wave 3 (2017-2020 — oldest)
      Process ~21,000 items
      Older data has more variance (different OCR quality, scrapers,
      meeting formats) — handle last when prompt is most stable
```

Recent items are checkpointed first because:
- They're the highest-traffic content (citizens look at recent meetings most)
- We have the most context on accuracy (we can spot-check against current
  reality)
- Ships UI value to users sooner — the homepage and category landing
  pages render meaningfully after Wave 1
- Cheapest to re-process if prompt iteration is needed

If Wave 1's `calibration_report` task surfaces persistent under-scoring
or category miscalibration (per Section 3.5 alerts), we bump
`ITEM_PROMPT_VERSION` and re-process Wave 1 only — Wave 2 hasn't started.
Costs us another ~$16 to redo Wave 1; saves us from baking the same
mistake into 36K Wave 2 items.

### 7.3 Anthropic Batches API integration

```python
# docket/ai/batches.py — new module
import anthropic

def submit_batch(items: list[AgendaItem], stage: Literal['stage1', 'stage2']) -> str:
    """Submits a batch to Anthropic. Returns batch ID for polling."""
    client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])

    requests = []
    for item in items:
        if stage == 'stage1':
            req = build_stage1_request(item)
        else:
            req = build_stage2_request(item, get_stage1_facts(item))
        requests.append({
            'custom_id': f'item-{item.id}-{stage}',
            'params': req,
        })

    batch = client.messages.batches.create(requests=requests)
    record_batch(batch.id, stage, [i.id for i in items])
    return batch.id


def poll_batch(batch_id: str) -> BatchStatus:
    """Polls the batch. Returns status; pulls and persists results when 'ended'."""
    client = anthropic.Anthropic()
    batch = client.messages.batches.retrieve(batch_id)

    if batch.processing_status == 'ended':
        for result in client.messages.batches.results(batch_id):
            persist_batch_result(result, batch_id)

    return BatchStatus(
        id=batch.id,
        status=batch.processing_status,
        request_counts=batch.request_counts,
    )
```

**New table** `ai_batches` records each batch:

```sql
CREATE TABLE ai_batches (
  id                    SERIAL PRIMARY KEY,
  anthropic_batch_id    TEXT NOT NULL UNIQUE,
  stage                 TEXT NOT NULL CHECK (stage IN ('stage1', 'stage2')),
  wave                  TEXT NOT NULL,           -- '2026' / '2021-2025' / '2017-2020'
  item_count            INT NOT NULL,
  submitted_at          TIMESTAMP NOT NULL DEFAULT NOW(),
  completed_at          TIMESTAMP NULL,
  cost_usd              NUMERIC(10, 4) NULL,
  status                TEXT NOT NULL CHECK (
                          status IN ('submitted', 'in_progress',
                                     'ended', 'failed', 'expired')
                        )
);

CREATE TABLE ai_batch_items (
  batch_id          INT NOT NULL REFERENCES ai_batches(id) ON DELETE CASCADE,
  agenda_item_id    INT NOT NULL REFERENCES agenda_items(id) ON DELETE CASCADE,
  custom_id         TEXT NOT NULL,
  result_status     TEXT NULL CHECK (
                      result_status IN ('succeeded', 'errored', 'expired')
                    ),
  PRIMARY KEY (batch_id, agenda_item_id)
);
```

Backfill driver runs as a worker task `backfill_batch_driver`:
- Selects next ~10K items needing processing in the current wave
- Submits two batches (Stage 1 and Stage 2) — they're sequential per
  item (Stage 2 needs Stage 1 output), but Stage 2 can batch the
  results of completed Stage 1 items
- Polls every 30 minutes; persists results when batches end
- Anthropic Batches API has 24h SLA; typical latency is 1-4 hours

### 7.4 Local response cache + idempotent resume

Per decision #18, every Stage 1/2 response also lands in the local
file cache (`data/ai_cache/<sha256>.json`). Backfill flow:

```
For each item in current wave:
  1. Check local cache → if hit, skip the API entirely
  2. Else submit to Batches API
  3. On result, write to DB AND to cache
  4. Update agenda_items.processing_status, ai_extraction_version,
     ai_rewrite_version, processing_attempts
```

If the worker crashes mid-wave or Railway restarts:
- `processing_status` and `ai_*_version` columns tell us exactly which
  items are done
- The next worker invocation queries `WHERE ai_rewrite_version <
  CURRENT_VERSION AND processing_status NOT IN ('completed', 'failed_permanent')`
  and resumes
- Cache files survive Railway restarts (they're in the persistent
  volume); cache hits are free

This makes backfill resumable at item granularity — you can ctrl-C the
driver, restart it tomorrow, and it picks up where it left off.

### 7.5 Dead-letter handling during backfill

Per decisions #25, #45, #65, the per-item retry ceiling is 3 attempts.
During backfill specifically:

| Failure mode | Handling |
|---|---|
| Pydantic validation failed (Stage 1 or 2) | Retry once with same prompt; if still fails, mark `failed_retry` and continue. After 3 total attempts → `failed_permanent`. |
| Cross-stage conflict (#45) | Auto-retry Stage 2 once with override prompt. If still conflicts → `cross_stage_conflict` status; backfill continues. |
| Token ceiling exceeded (#35) | Mark `failed_retry` with `last_error_message='input_too_large'`. Surface in admin queue for manual chunking review. Don't retry. |
| Anthropic API error (rate limit, server) | Retry with exponential backoff (1s/4s/16s). After 3 attempts → mark `failed_retry` with API error in `last_error_message`. |
| Daily budget exceeded | Mid-batch: complete in-flight requests, halt new submissions. Resume next day when budget resets. |

After each wave completes, run:

```sql
SELECT processing_status, COUNT(*) AS n
FROM agenda_items
WHERE meeting_id IN (
  SELECT id FROM meetings WHERE meeting_date BETWEEN :wave_start AND :wave_end
)
GROUP BY processing_status
ORDER BY processing_status;
```

Expected distribution after a healthy wave: ~85-90% `completed`,
~10-15% `procedural_skipped`/`data_quality_skipped`, <2% `failed_*` or
`cross_stage_conflict`. If the failure rate exceeds 5%, halt the next
wave and investigate.

**Significance-sorted error queue (decision #79):** the
`/admin/errors` admin view sorts `failed_permanent` items by
`data_debt_priority DESC, meeting_date DESC` — the high-priority
heuristic from Stage 0a (HIGH_KEYWORDS like "settlement", "Flock",
"emergency", or Red-tier dollar amounts in the title). A failed
$50M bond from 2019 jumps ahead of a failed 2017 proclamation.
Same priority logic applies to `data_quality_skipped` (OCR queue)
items, so admins always work the highest-civic-impact data debt
first regardless of failure mode or chronological order.

### 7.6 Frontend transition during backfill

Per decision #22 (progressive switchover), the v3 UI ships **before**
backfill completes. The card variant state machine handles partial
states:

| Day | What citizens see |
|---|---|
| Day 0 (Migration 013 lands + Wave 0 runs) | All items still rendering v2 fallback (no v3 fields populated) — chip says "summary updating" with explanatory tooltip. (Backfill banner retired — decision #80.) |
| Day 1-3 (Wave 1 in progress) | Recent items (2026) start rendering full Smart Brevity Card. Older items still v2-fallback. |
| Day 3-10 (Wave 2 in progress) | 2021-2025 items transition to Smart Brevity Card. Pre-2021 items still v2-fallback. |
| Day 10-14 (Wave 3 in progress) | Pre-2021 items transition. By end, 100% v3. |
| Day 14+ (Wave 3 complete) | All cards on v3; v2-fallback no longer rendered for any item. |
| Day 15+ (Migration 014 ready) | DROP `agenda_items.summary` column. v2-fallback variant template retired. |

No UI dark period at any point.

**Backfill banner retired (decision #80, banner clause).** The card-level
"summary updating" chip carries the transition state adequately; a
global banner was redundant editorial polish. `BACKFILL_ACTIVE` env var
no longer needed.

**Chip tooltip retained (decision #80, tooltip clause):** the existing
"summary updating" chip on v2-fallback cards carries a longer tooltip /
aria-label:

```html
<span class="chip-summary-updating"
      title="This summary is being refreshed as part of an ongoing pipeline update. The underlying data is unchanged."
      aria-label="Summary updating: refresh in progress, underlying data unchanged">
  ⏳ summary updating
</span>
```

Keeps the citizen-friendly framing ("updating", not "legacy") while
making the system context explicit for anyone who hovers/queries.

### 7.7 Operator runbook

`docs/runbooks/backfill.md` (new):

```markdown
## Daily ops during backfill

Morning check (admin dashboard):
- ai_batches table: any batches stuck >24h?
- calibration_report: any new alerts?
- /admin/errors: any failed_permanent items above 5% of wave?

Daily commands:
  # Status
  railway run venv/bin/python -m docket.ai.cli --status

  # Submit next 10K Wave N items (Stage 1 batch)
  railway run venv/bin/python -m docket.ai.cli --wave 2026 --stage 1 --batch-size 10000

  # Poll all open batches (also runs as scheduled task every 30 min)
  railway run venv/bin/python -m docket.ai.cli --poll-batches

  # Re-process Wave 1 after prompt-version bump
  railway run venv/bin/python -m docket.ai.cli --wave 2026 --reprocess
```

Healthchecks integration: new UUIDs `HEALTHCHECK_BACKFILL_DRIVER_UUID`
and `HEALTHCHECK_BATCH_POLLER_UUID`. Driver pings on each batch
submission; poller pings on each polling cycle.

### 7.8 Special cases

#### Re-runs after prompt-version bump

When `ITEM_PROMPT_VERSION` increments (driven by calibration alerts):

1. The version bump invalidates the local cache (cache key includes
   prompt_version, decision #42)
2. Backfill driver detects items with `ai_rewrite_version < current_version`
   and re-queues them
3. Cost duplication is acceptable — prompt iteration is the whole point

A prompt bump that affects 10K already-processed items costs ~$22
(Batches API) to re-process. Trivial relative to the value of getting
the prompt right.

#### Cross-stage conflicts during backfill

`cross_stage_conflict` items don't block the wave. They land in the
admin queue for manual resolution post-wave. If the rate exceeds 1%
of any wave, that's a Stage 2 prompt issue and warrants a version bump.

#### Items added during backfill

The cron-worker `ai_items` task continues running its normal nightly
schedule throughout backfill. New items from daily ingestion are
processed within 24h regardless of which wave the historical backfill
is in. The two paths (backfill driver + nightly task) coordinate via
`pg_try_advisory_lock` per task — they don't collide.

### Adaptive concurrency (decision #81)

Both the backfill driver and the live `ai_items` task share an adaptive
worker pool that scales based on rate-limit pressure:

```python
# docket/ai/concurrency.py
from collections import deque
import time

class AdaptiveWorkerPool:
    """Adjusts worker count based on observed 429 frequency.
    Shared between backfill driver and live ai_items task so backfill
    never monopolizes Anthropic rate-limit budget at the cost of
    new-meeting ingestion."""

    def __init__(self, max_workers: int = 5, min_workers: int = 1):
        self.max_workers = max_workers
        self.min_workers = min_workers
        self.current_workers = max_workers
        self._429_timestamps: deque[float] = deque(maxlen=20)
        self._last_scale_down: float | None = None

    def record_429(self) -> None:
        """Called after each rate-limit error. May scale workers down."""
        self._429_timestamps.append(time.time())
        if self._count_in_window(seconds=300) >= 5:
            new_count = max(self.min_workers, self.current_workers - 1)
            if new_count != self.current_workers:
                log.warning("scaling workers down: %d → %d (429 storm)",
                           self.current_workers, new_count)
                self.current_workers = new_count
                self._last_scale_down = time.time()

    def consider_scale_up(self) -> None:
        """Called periodically by the worker pool. Only scales up after
        a 10-minute cool-down with zero 429s."""
        if (self._last_scale_down
                and time.time() - self._last_scale_down < 600):
            return
        if self._count_in_window(seconds=600) == 0:
            new_count = min(self.max_workers, self.current_workers + 1)
            if new_count != self.current_workers:
                log.info("scaling workers up: %d → %d (cool-down clear)",
                        self.current_workers, new_count)
                self.current_workers = new_count

    def _count_in_window(self, seconds: int) -> int:
        cutoff = time.time() - seconds
        return sum(1 for t in self._429_timestamps if t > cutoff)
```

Shared instance lives in module scope; both backfill and live tasks
import and call `record_429()` on rate-limit errors and
`consider_scale_up()` once per polling cycle. Net effect: backfill
auto-yields capacity to live ingestion when Anthropic is busy, then
reclaims it.

### Atomic wave checkpoints (decision #82)

Each wave run generates a `backfill_session_id UUID` and writes it to
every item it processes:

```sql
ALTER TABLE agenda_items
  ADD COLUMN backfill_session_id UUID NULL;

CREATE INDEX idx_agenda_items_backfill_session
  ON agenda_items (backfill_session_id)
  WHERE backfill_session_id IS NOT NULL;
```

Backfill driver pseudocode:

```python
def run_wave(wave_name: str, date_range: tuple[date, date]):
    session_id = uuid.uuid4()
    log.info("starting wave %s with session_id=%s", wave_name, session_id)
    record_session(session_id, wave_name, date_range)

    for batch in iterate_pending_items(date_range, batch_size=10000):
        result = submit_and_poll(batch)
        for item, output in result:
            write_outputs(item.id, output, backfill_session_id=session_id)
```

Rollback (single statement, indexed):

```sql
-- Whoops — Wave 2 was run with a buggy ITEM_PROMPT_VERSION; roll it back
UPDATE agenda_items
SET ai_rewrite_version = NULL,
    ai_extraction_version = NULL,
    headline = NULL,
    why_it_matters = NULL,
    extracted_facts = NULL,
    score_overrides = NULL,
    processing_status = 'pending',
    backfill_session_id = NULL
WHERE backfill_session_id = '01918f2c-aa11-7c8e-...';
```

Then re-queue the wave with the corrected prompt version. The local
response cache (Section 7.4) is keyed by prompt version, so the
re-run gets fresh API responses for every item; no stale cache hits.

---

## Section 8 — Schema migrations + phasing + test strategy

This section sequences the build, the deploy, and the verification.
Two migrations bookend the work (013 strictly additive, 014 drops the
legacy column). Four phases between them ship code in dependency
order. The test pyramid extends the existing unit/integration/live
structure with new coverage for every locked decision.

### 8.1 Migration 013 — additive (everything new lands here)

Single migration that creates all new schema. Runs as part of normal
deploy via `python -m docket.migrations.runner`. **Strictly additive**
— no destructive changes — so v2 frontend and backfill can coexist
during the transition window.

```python
# src/docket/migrations/013_impact_first_refactor.py
def up(cur):
    # 1. Required extensions
    cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

    # 2. Enums
    cur.execute("""
        CREATE TYPE data_quality_enum AS ENUM (
            'ok', 'no_text_layer', 'no_agenda_text', 'empty', 'foreign_language'
        );
        CREATE TYPE data_debt_priority_enum AS ENUM ('low', 'normal', 'high');
        CREATE TYPE processing_status_enum AS ENUM (
            'pending', 'procedural_skipped', 'data_quality_skipped',
            'extracted', 'rewritten', 'badged', 'completed',
            'failed_retry', 'failed_permanent', 'cross_stage_conflict'
        );
    """)

    # 3. New columns on agenda_items
    cur.execute("""
        ALTER TABLE agenda_items
          ADD COLUMN extracted_facts        JSONB                       DEFAULT NULL,
          ADD COLUMN headline               TEXT                        DEFAULT NULL,
          ADD COLUMN why_it_matters         TEXT                        DEFAULT NULL,
          ADD COLUMN source_anchor          JSONB                       DEFAULT NULL,
          ADD COLUMN data_quality           data_quality_enum           DEFAULT NULL,
          ADD COLUMN data_debt_priority     data_debt_priority_enum     DEFAULT NULL,
          ADD COLUMN processing_status      processing_status_enum      DEFAULT 'pending',
          ADD COLUMN processing_attempts    INT                         DEFAULT 0,
          ADD COLUMN last_error_at          TIMESTAMP                   DEFAULT NULL,
          ADD COLUMN last_error_message     TEXT                        DEFAULT NULL,
          ADD COLUMN score_overrides        JSONB                       DEFAULT NULL,
          ADD COLUMN ai_extraction_version  INT                         DEFAULT NULL,
          ADD COLUMN ai_rewrite_version     INT                         DEFAULT NULL,
          ADD COLUMN ai_confidence          TEXT                        DEFAULT NULL
                     CHECK (ai_confidence IS NULL OR
                            ai_confidence IN ('high', 'medium', 'low')),
          ADD COLUMN backfill_session_id    UUID                        DEFAULT NULL;

        ADD CONSTRAINT chk_headline_length CHECK (
            headline IS NULL OR length(headline) <= 60
        );
        ADD CONSTRAINT chk_why_it_matters_length CHECK (
            why_it_matters IS NULL OR length(why_it_matters) <= 200
        );
    """)

    # 4. New column on municipalities
    cur.execute("""
        ALTER TABLE municipalities
          ADD COLUMN master_calendar_url TEXT DEFAULT NULL;
    """)

    # 4a. Unified search vector — covers BOTH v2 (summary) and v3
    # (headline + why_it_matters) content fields so search remains
    # reliable across the transition (decision #83).
    cur.execute("""
        ALTER TABLE agenda_items
          ADD COLUMN search_vector tsvector;

        CREATE INDEX idx_agenda_items_fts
          ON agenda_items USING GIN (search_vector);

        CREATE FUNCTION agenda_items_search_vector_update() RETURNS trigger AS $$
        BEGIN
          NEW.search_vector := to_tsvector('english',
            COALESCE(NEW.title, '')          || ' ' ||
            COALESCE(NEW.description, '')    || ' ' ||
            COALESCE(NEW.headline, '')       || ' ' ||
            COALESCE(NEW.why_it_matters, '') || ' ' ||
            COALESCE(NEW.summary, '')
          );
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_agenda_items_search_vector
          BEFORE INSERT OR UPDATE ON agenda_items
          FOR EACH ROW EXECUTE FUNCTION agenda_items_search_vector_update();

        -- Backfill the column for existing rows (one-time)
        UPDATE agenda_items SET search_vector = to_tsvector('english',
          COALESCE(title, '') || ' ' ||
          COALESCE(description, '') || ' ' ||
          COALESCE(summary, '')
        );
    """)

    # 5. New tables (defined in detail across Sections 4-7; condensed here)
    cur.execute("""
        CREATE TABLE agenda_item_badges (
            id                SERIAL PRIMARY KEY,
            agenda_item_id    INT NOT NULL REFERENCES agenda_items(id) ON DELETE CASCADE,
            badge_slug        TEXT NOT NULL,
            kind              TEXT NOT NULL CHECK (kind IN ('process', 'policy')),
            confidence        NUMERIC(3, 2),
            source            TEXT NOT NULL CHECK (source IN ('deterministic', 'llm', 'both', 'manual')),
            matching_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            detected_at       TIMESTAMP NOT NULL DEFAULT NOW(),
            UNIQUE (agenda_item_id, badge_slug)
        );

        CREATE TABLE priority_badge_templates (
            slug                  TEXT PRIMARY KEY,
            name                  TEXT NOT NULL,
            description           TEXT NOT NULL,
            icon                  TEXT NOT NULL,
            kind                  TEXT NOT NULL CHECK (kind IN ('process', 'policy')),
            default_matcher_hints JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at            TIMESTAMP NOT NULL DEFAULT NOW()
        );

        CREATE TABLE priority_badges_config (
            id                     SERIAL PRIMARY KEY,
            city_id                INT NOT NULL REFERENCES municipalities(id) ON DELETE CASCADE,
            template_slug          TEXT NOT NULL REFERENCES priority_badge_templates(slug) ON DELETE CASCADE,
            name_override          TEXT,
            description_override   TEXT,
            matcher_hints_override JSONB,
            enabled                BOOLEAN NOT NULL DEFAULT TRUE,
            added_at               TIMESTAMP NOT NULL DEFAULT NOW(),
            added_by               TEXT,
            notes                  TEXT,
            UNIQUE (city_id, template_slug)
        );

        CREATE TABLE agenda_item_badges_audit (
            id              SERIAL PRIMARY KEY,
            agenda_item_id  INT NOT NULL REFERENCES agenda_items(id),
            badge_slug      TEXT NOT NULL,
            action          TEXT NOT NULL CHECK (action IN ('added', 'removed', 'modified')),
            actor           TEXT,
            actor_role      TEXT NOT NULL CHECK (actor_role IN ('admin', 'cron', 'on_write')),
            reason          TEXT,
            occurred_at     TIMESTAMP NOT NULL DEFAULT NOW()
        );

        CREATE TABLE city_score_floor_overrides (
            city_id                   INT NOT NULL REFERENCES municipalities(id),
            trigger_name              TEXT NOT NULL,
            override_threshold_amount NUMERIC,
            override_min_score        INT,
            reason                    TEXT,
            added_by                  TEXT,
            added_at                  TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (city_id, trigger_name)
        );

        CREATE TABLE ai_batches (
            id                 SERIAL PRIMARY KEY,
            anthropic_batch_id TEXT NOT NULL UNIQUE,
            stage              TEXT NOT NULL CHECK (stage IN ('stage1', 'stage2')),
            wave               TEXT NOT NULL,
            item_count         INT NOT NULL,
            submitted_at       TIMESTAMP NOT NULL DEFAULT NOW(),
            completed_at       TIMESTAMP,
            cost_usd           NUMERIC(10, 4),
            status             TEXT NOT NULL CHECK (
                                 status IN ('submitted', 'in_progress', 'ended', 'failed', 'expired')
                               )
        );

        CREATE TABLE ai_batch_items (
            batch_id        INT NOT NULL REFERENCES ai_batches(id) ON DELETE CASCADE,
            agenda_item_id  INT NOT NULL REFERENCES agenda_items(id) ON DELETE CASCADE,
            custom_id       TEXT NOT NULL,
            result_status   TEXT CHECK (result_status IN ('succeeded', 'errored', 'expired')),
            PRIMARY KEY (batch_id, agenda_item_id)
        );

        -- data_issue_reports table retired (decision #77); v1 uses mailto: links
        -- to admin email instead of an in-app reporting schema.

        CREATE TABLE mayoral_terms (
            id           SERIAL PRIMARY KEY,
            city_id      INT NOT NULL REFERENCES municipalities(id),
            mayor_name   TEXT NOT NULL,
            party        TEXT,
            term_start   DATE NOT NULL,
            term_end     DATE
        );
    """)

    # 6. Indexes
    cur.execute("""
        CREATE INDEX idx_agenda_items_processing_status
            ON agenda_items (processing_status)
            WHERE processing_status NOT IN ('completed', 'failed_permanent');
        CREATE INDEX idx_agenda_items_extraction_version
            ON agenda_items (ai_extraction_version);
        CREATE INDEX idx_agenda_items_rewrite_version
            ON agenda_items (ai_rewrite_version);
        CREATE INDEX idx_agenda_items_backfill_session
            ON agenda_items (backfill_session_id)
            WHERE backfill_session_id IS NOT NULL;
        CREATE INDEX idx_agenda_items_data_debt
            ON agenda_items (data_debt_priority, meeting_id)
            WHERE data_quality IS NOT NULL AND data_quality != 'ok';
        CREATE INDEX idx_agenda_items_counterparty_trgm
            ON agenda_items USING gin ((extracted_facts->>'counterparty') gin_trgm_ops);

        CREATE INDEX idx_agenda_item_badges_slug
            ON agenda_item_badges (badge_slug, kind);
        CREATE INDEX idx_agenda_item_badges_item
            ON agenda_item_badges (agenda_item_id);

        CREATE INDEX idx_priority_badges_config_city
            ON priority_badges_config (city_id) WHERE enabled = TRUE;

        CREATE INDEX idx_badge_audit_recent
            ON agenda_item_badges_audit (occurred_at DESC, badge_slug, action)
            WHERE actor_role = 'admin';

        -- (data_issue_reports index retired with the table — decision #77)

        CREATE INDEX idx_ai_batches_status
            ON ai_batches (status, submitted_at DESC)
            WHERE status IN ('submitted', 'in_progress');

        CREATE INDEX idx_mayoral_terms_city
            ON mayoral_terms (city_id, term_start DESC);
    """)

    # 7. Materialized view for category-page volume timelines
    cur.execute("""
        CREATE MATERIALIZED VIEW mv_badge_volume_monthly AS
        SELECT
            m.city_id,
            aib.badge_slug,
            DATE_TRUNC('month', m.meeting_date)::date AS month,
            COUNT(*)                                          AS n_items,
            COUNT(*) FILTER (WHERE ai.is_consent = TRUE)     AS n_consent,
            COUNT(*) FILTER (WHERE ai.is_consent = FALSE)    AS n_substantive,
            COALESCE(SUM(ai.dollars_amount), 0)              AS total_dollars
        FROM agenda_item_badges aib
        JOIN agenda_items ai ON ai.id = aib.agenda_item_id
        JOIN meetings m ON m.id = ai.meeting_id
        WHERE aib.confidence >= 0.6
        GROUP BY m.city_id, aib.badge_slug, month;

        CREATE UNIQUE INDEX ON mv_badge_volume_monthly (city_id, badge_slug, month);
    """)

    # 8. Seed data — process badge templates (Section 4.2)
    cur.execute("INSERT INTO priority_badge_templates ... ;")
    # 9. Seed data — Birmingham 2026 policy badge templates + config rows (Section 5.2)
    cur.execute("INSERT INTO priority_badge_templates ... ;")
    cur.execute("INSERT INTO priority_badges_config ... ;")
    # 10. Seed data — BHM mayoral terms (for SVG overlay)
    cur.execute("INSERT INTO mayoral_terms ... ;")


def down(cur):
    """Rollback. Reverses everything in up()."""
    cur.execute("DROP MATERIALIZED VIEW IF EXISTS mv_badge_volume_monthly;")
    cur.execute("DROP TABLE IF EXISTS mayoral_terms;")
    cur.execute("DROP TABLE IF EXISTS ai_batch_items;")
    cur.execute("DROP TABLE IF EXISTS ai_batches;")
    cur.execute("DROP TABLE IF EXISTS city_score_floor_overrides;")
    cur.execute("DROP TABLE IF EXISTS agenda_item_badges_audit;")
    cur.execute("DROP TABLE IF EXISTS priority_badges_config;")
    cur.execute("DROP TABLE IF EXISTS priority_badge_templates;")
    cur.execute("DROP TABLE IF EXISTS agenda_item_badges;")
    cur.execute("ALTER TABLE municipalities DROP COLUMN master_calendar_url;")
    cur.execute("""
        ALTER TABLE agenda_items
          DROP COLUMN backfill_session_id,
          DROP COLUMN ai_confidence,
          DROP COLUMN ai_rewrite_version,
          DROP COLUMN ai_extraction_version,
          DROP COLUMN score_overrides,
          DROP COLUMN last_error_message,
          DROP COLUMN last_error_at,
          DROP COLUMN processing_attempts,
          DROP COLUMN processing_status,
          DROP COLUMN data_debt_priority,
          DROP COLUMN data_quality,
          DROP COLUMN source_anchor,
          DROP COLUMN why_it_matters,
          DROP COLUMN headline,
          DROP COLUMN extracted_facts;
    """)
    cur.execute("DROP TYPE IF EXISTS processing_status_enum;")
    cur.execute("DROP TYPE IF EXISTS data_debt_priority_enum;")
    cur.execute("DROP TYPE IF EXISTS data_quality_enum;")
    # pg_trgm extension left in place (other queries may use it)
```

Migration 013 is idempotent over re-runs via `IF NOT EXISTS` clauses
(easy to add to the schema-migrations runner pattern). Pre-deploy
verification: dry-run on local Postgres 18 + Railway preview branch.

### 8.2 Migration 014 — drop legacy `summary` column

Runs ONLY after backfill confirms v3 outputs landed for all items.
**Manually triggered**, not auto-applied.

```python
# src/docket/migrations/014_drop_legacy_summary.py
def up(cur):
    # Verification gate: every completed substantive item has v3 outputs
    cur.execute("""
        SELECT COUNT(*) FROM agenda_items
        WHERE processing_status = 'completed'
          AND ai_rewrite_version != 3;
    """)
    legacy_count = cur.fetchone()[0]
    if legacy_count > 0:
        raise MigrationError(
            f"Refusing to drop summary column — {legacy_count} completed "
            f"items still on ai_rewrite_version != 3. Re-run backfill."
        )

    # Update the search-vector trigger to drop the summary term BEFORE
    # dropping the column itself (otherwise the trigger fires on the
    # implicit row update and references the missing column).
    cur.execute("""
        CREATE OR REPLACE FUNCTION agenda_items_search_vector_update()
        RETURNS trigger AS $$
        BEGIN
          NEW.search_vector := to_tsvector('english',
            COALESCE(NEW.title, '')          || ' ' ||
            COALESCE(NEW.description, '')    || ' ' ||
            COALESCE(NEW.headline, '')       || ' ' ||
            COALESCE(NEW.why_it_matters, '')
          );
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    cur.execute("ALTER TABLE agenda_items DROP COLUMN summary;")


def down(cur):
    """Re-adds the column as nullable. Data is unrecoverable —
    backfill from v3 outputs (`headline` + `why_it_matters`) is the
    only path to repopulate."""
    cur.execute("ALTER TABLE agenda_items ADD COLUMN summary TEXT;")
```

### 8.3 Phasing — what ships when

The C → A → B build order (decision #1) is conceptual priority, not
a strict deploy sequence. In practice the pipeline ships as a
coherent whole gated by a feature flag, then backfills incrementally.
Four phases:

```
                      MIGRATION 013                MIGRATION 014
                            │                            │
   ┌────────────────────────┼────────────────────────────┼───────────┐
   │ Phase 1   │  Phase 2   │     Phase 3 (Backfill)     │  Phase 4  │
   │ Schema    │ Pipeline + │  Wave 1 → Wave 2 → Wave 3  │  Cleanup  │
   │  + Wave 0 │   Frontend │   (LLM, paid API calls)    │           │
   │   (~2 hr) │   (~1 day) │       (~7-14 days)         │  (~1 day) │
   └───────────┴────────────┴────────────────────────────┴───────────┘
```

**Phase 1 — Schema + Wave 0 (~2 hours)**

| Step | Action | Verification |
|---|---|---|
| 1 | Land Migration 013 in production via `railway up` + `python -m docket.migrations.runner` | Run `--status` to confirm 013 applied; smoke-test reads against new columns return null |
| 2 | Run Wave 0: `python -m docket.ai.cli --wave 0` | Counts of items in each `processing_status` align with expectations; no v2 outputs disturbed |

Wave 0 is non-LLM, costs $0, and surfaces the actual LLM-eligible item
count which informs Wave 1+ budgets.

Phase 1.5 — Wave 0.5 Live Calibration Burst (decision #88) runs after
Phase 2 deploys the pipeline code and before Wave 1 submits to
Batches API. See Phase 2 / Phase 3 sequencing below.

**Phase 2 — Pipeline + Frontend (~1 day)**

| Step | Action | Verification |
|---|---|---|
| 1 | Deploy all new pipeline code (Stages 0-2.5, reconcile, badges) behind `IMPACT_FIRST_ENABLED=false` env flag | Existing v2 pipeline still runs; new code paths dormant |
| 2 | Deploy v3 frontend behind `SMART_BREVITY_UI=false` env flag | Existing v2 UI renders unchanged; new partials registered but unreachable |
| 3 | Flip `IMPACT_FIRST_ENABLED=true` for the worker only | Live `ai_items` task starts using Stages 0-2.5 for incoming new items; existing items still on v2 |
| 4 | Run unit + integration tests against the live worker | Sample new items get full v3 outputs; check calibration dashboard for early signals |
| 5 | Confirm `/admin/data-debt` queue sorts by `data_debt_priority DESC, meeting_date DESC` from launch (decision #84) | Admins working OCR queue see high-priority items at top from Day 1, not after a later UI patch |
| 6 | Confirm search returns results for both v2 (summary-only) and v3 (headline + why_it_matters) items via the unified `search_vector` column | Sample queries against fixture items in both states return results regardless of version |

Frontend stays on v2 UI throughout Phase 2 — citizens don't see the new
cards until Wave 1 is well-populated. Search, however, is fully
multi-version aware from the moment Migration 013 lands (decision #83).

**Phase 3 — Backfill (~7-14 days)**

| Step | Action | Verification |
|---|---|---|
| 1 | Submit Wave 0.5 (live calibration burst, current month, sync API) | ~500-1,000 items processed within hours; spot-check outputs immediately for prompt quality |
| 2 | Submit Wave 1 (remaining 2026 items via Batches API) | Daily check `ai_batches` for status; calibration_report task surfaces early prompt drift |
| 3 | Spot-check Wave 0.5 + Wave 1 outputs across 20-30 random items | Headlines read clean; badges fire correctly; cross-stage conflicts <1% |
| 4 | If issues: bump `ITEM_PROMPT_VERSION` and re-run Wave 0.5 + Wave 1 (cost: ~$20) | Recalibrate, re-spot-check |
| 5 | Flip `SMART_BREVITY_UI=true` once Wave 0.5 + Wave 1 are satisfactory | Citizens start seeing v3 cards on 2026 meetings; older meetings still v2-fallback chip |
| 6 | Submit Wave 2 (2021-2025) | Daily monitoring; per-wave failure-rate threshold = 5% |
| 7 | Submit Wave 3 (2017-2020) | Same monitoring; older data more likely to need data_quality_skipped |
| 8 | Wave 3 completes | All `processing_status=completed` items now on v3; v2-fallback variant ready to retire |

Adaptive worker pool (decision #81) keeps live ingestion of new
meetings flowing throughout backfill.

**Phase 4 — Cleanup (~1 day)**

| Step | Action | Verification |
|---|---|---|
| 1 | Run Migration 014: `python -m docket.migrations.runner --apply 014` | Verification gate confirms all `processing_status=completed` items have `ai_rewrite_version=3`; trigger function updated to drop `summary` term; column dropped |
| 2 | Remove v2-fallback variant template + dead code | Card variant state machine simplifies to 5 variants |
| 3 | Tag the release: `git tag refactor-impact-first-v1` | Anchor for future rollback |

### 8.4 Test strategy

Existing layout (per CLAUDE.md): `tests/unit/` (~270), `tests/integration/`, `tests/live/` (gated on `ANTHROPIC_API_KEY`). New coverage extends this without restructuring.

**Unit tests (~200 new)**

| File | Coverage |
|---|---|
| `tests/unit/test_stage_0a_data_quality.py` | Every branch of `evaluate_data_quality()`: empty title, missing body, body=title, body too short, foreign-language detection, ALL CAPS rejection. ~25 tests. |
| `tests/unit/test_stage_0a_priority.py` | `_priority_from_title()` against HIGH_KEYWORDS, LOW_KEYWORDS, dollar-regex matches, default normal. ~15 tests. |
| `tests/unit/test_stage_0b_regex.py` | Each procedural pattern matches expected examples and rejects substantive lookalikes. ~25 tests. |
| `tests/unit/test_stage_1_extraction_schema.py` | Pydantic validation: each field's enum coverage, nested LocationDetail and NextSteps, boundary cases. ~20 tests. |
| `tests/unit/test_stage_2_smart_brevity_schema.py` | `procedural_consistency` validator: substantive requires populated fields, procedural rejects populated fields, empty-string rejection. ~15 tests. |
| `tests/unit/test_stage_2_5_floors.py` | Each `SIGNIFICANCE_FLOORS` and `CONSENT_PLACEMENT_CEILINGS` predicate fires correctly. SUBJECT_MATTER_FLOORS keyword + badge-slug paths. Score-overrides JSONB shape. ~30 tests. |
| `tests/unit/test_stage_2_5_overrides.py` | Per-city threshold overrides applied correctly via `_resolve_threshold`. Empty table returns defaults. ~10 tests. |
| `tests/unit/test_reconcile.py` | Each conflict path: counterparty + procedural, funding + procedural, dollars + procedural, action_type + procedural, subject-matter + procedural. Auto-retry vs. escalate. ~15 tests. |
| `tests/unit/test_process_badges.py` | Each badge's deterministic SQL (run against in-memory test DB): hidden_on_consent confidence guard, sole_source, settlement, split_vote vs. contested thresholds, amends_prior_contract trigram fuzzy match, emergency_action title regex. ~30 tests. |
| `tests/unit/test_policy_badge_matcher.py` | `deterministic_policy_match`: significance gate, excluded_action_types guard, keyword regex, action_type match, topic match, regex flag escaping, invalid-regex skip. ~20 tests. |
| `tests/unit/test_policy_badge_compute.py` | `compute_policy_badges`: LLM hallucination filtering, both/llm/deterministic confidence resolution, matching_metadata payload. ~10 tests. |
| `tests/unit/test_concurrency.py` | `AdaptiveWorkerPool` scale-down on 429 storm, scale-up after cool-down, min/max bounds. ~10 tests. |
| `tests/unit/test_response_cache.py` | Cache hit/miss, key derivation includes prompt version + model ID, version bump invalidates. ~10 tests. |

**Integration tests (~30 new)**

| File | Coverage |
|---|---|
| `tests/integration/test_full_pipeline_substantive.py` | Mocked Haiku — process a substantive item end-to-end through Stages 0a → 2.5 → badges → atomic commit. Verifies all columns populated, audit log entries written. |
| `tests/integration/test_full_pipeline_procedural.py` | Mocked — procedural item gets caught by Stage 0b, no LLM calls made, downstream stages no-op. |
| `tests/integration/test_full_pipeline_degraded.py` | Mocked — bad-quality item flagged at Stage 0a, no Stage 1+2, render-side falls to degraded card. |
| `tests/integration/test_cross_stage_retry.py` | Mocked Stage 1 returns substantive facts, Stage 2 returns procedural verdict; reconcile triggers retry-with-override; second Stage 2 returns substantive; commit succeeds. |
| `tests/integration/test_cross_stage_escalate.py` | Same setup, both Stage 2 attempts return procedural; processing_status='cross_stage_conflict'; admin queue surfaces it. |
| `tests/integration/test_backfill_resume.py` | Run partial backfill, kill mid-wave, resume — completed items skipped, in-flight items reprocessed. |
| `tests/integration/test_backfill_session_rollback.py` | Run wave with one session_id, manually `UPDATE … WHERE backfill_session_id=` rollback; columns null and processing_status reverted. |
| `tests/integration/test_migration_013_idempotent.py` | Run 013 up, then up again (no changes); down, then up; verify final state matches single-up state. |
| `tests/integration/test_migration_014_gate.py` | Try to apply 014 before backfill complete — raises MigrationError; complete backfill, retry — succeeds. |
| `tests/integration/test_calibration_queries.py` | Seed `score_overrides` JSONB across known-bad items; run calibration queries; expect alerts on under-scoring action_type pattern. |
| `tests/integration/test_materialized_view_refresh.py` | Refresh `mv_badge_volume_monthly` after badge updates; volume timeline reads return correct counts including consent split. |

**Live tests (gated on `ANTHROPIC_API_KEY` — ~10 new)**

| File | Coverage |
|---|---|
| `tests/live/test_stage_1_real_haiku.py` | Real Haiku 4.5 call against 3 sample items (one substantive, one procedural, one ambiguous). Verifies Pydantic validation passes against real model output. |
| `tests/live/test_stage_2_real_haiku.py` | Same for Stage 2 — real Haiku, real Pydantic validation, real banned-words enforcement check. |
| `tests/live/test_full_pipeline_real_api.py` | End-to-end on 5 real items through actual Anthropic API. Cost: ~$0.025/run; gated to manual invocation. |
| `tests/live/test_batches_api_smoke.py` | Submit a 3-item Batches API batch, poll until ended, verify result persistence. Cost: ~$0.015. |

**Frontend snapshot tests (~15 new)**

| File | Coverage |
|---|---|
| `tests/frontend/test_card_variants.py` | Render each of the 6 Smart Brevity Card variants (full / procedural / degraded / failed-permanent / v2-fallback / cross-stage-conflict) with fixture data; snapshot HTML. |
| `tests/frontend/test_engagement_strip.py` | Render engagement strip in 4 states: full next_steps / partial / awaiting (action_type=public_hearing_set with null date) / fallback (master calendar). |
| `tests/frontend/test_volume_timeline.py` | Render SVG volume timeline with mayoral-term overlay and consent baseline split; snapshot. |
| `tests/frontend/test_badge_chip_ordering.py` | Order_badges() with mixed process+policy, confidence levels; verify process-first ordering and "+N more" collapse. |

Snapshot tests use Jinja2's render_template() against fixture data and
hash the output; regression detection without a real browser.

### 8.5 Rollback plans by failure mode

| Failure mode | Detected via | Rollback action | Time to recover |
|---|---|---|---|
| Frontend regression after `SMART_BREVITY_UI=true` flip | Sentry/error logs, citizen reports | Set `SMART_BREVITY_UI=false`; redeploy. v2 cards return immediately. | < 5 min |
| Backfill batch produced bad outputs (prompt regression) | Calibration alerts, spot-checks | Single `UPDATE … WHERE backfill_session_id=…` to clear. Bump prompt version. Re-run wave. | < 10 min reset, hours-to-day to re-run wave |
| Stage 2 prompt persistently miscalibrating | Calibration alerts >5 days | Bump `ITEM_PROMPT_VERSION`; re-cascade affected items only. | Hours |
| Migration 013 issue post-deploy | Smoke tests fail; column reads return errors | `python -m docket.migrations.runner --down 013`. v2 pipeline resumes from where it left off. | < 5 min |
| Anthropic API rate-limit storm | AdaptiveWorkerPool scaling down to min | Self-correcting via decision #81; if persistent, halt backfill driver, leave live ai_items running | Auto-recovers; manual halt if needed |
| Cost overrun mid-wave | Daily budget gate breach | Soft cap pauses new submissions automatically; resume next day. Override with `--force-budget` if urgent. | Self-correcting |
| Catastrophic state corruption | Multiple of the above; manual investigation | `git revert` the deploy; run Migration 014 down (re-adds summary column null); accept data loss; restart backfill from scratch | Hours |

### 8.6 Success metrics

Measured during and after the refactor:

| Metric | Threshold | Measurement |
|---|---|---|
| Backfill completion rate | ≥ 95% items reach `processing_status='completed'` | After Wave 3 |
| Failed-permanent rate | < 2% per wave | After each wave |
| Cross-stage conflict rate | < 1% per wave | After each wave |
| Calibration alert rate | No (action_type, version) row exceeds 20% sig boost rate | Daily during backfill, weekly thereafter |
| Cost vs. budget | Total < $144 (Batches API estimate) | Sum of `ai_batches.cost_usd` |
| Citizen engagement | Click-through rate on category landing pages > existing topic browse | First 30 days post-launch |
| Performance | Category landing page p95 latency < 500ms | Continuous via existing perf monitoring |
| Search consistency | < 5% of searches return mixed v3/v2 results post-Wave 3 | Once-off audit at Wave 3 completion |

Failure of any threshold doesn't trigger automatic rollback — it
triggers admin investigation per the rollback table above.

### 8.7 Documentation deliverables

Alongside the code changes, this refactor adds three runbook docs:

| Doc | Purpose |
|---|---|
| `docs/runbooks/backfill.md` | Daily ops during backfill (per Section 7.7) |
| `docs/runbooks/calibration.md` | How to read the admin calibration dashboard, when to bump prompts |
| `docs/runbooks/badges.md` | How to add new policy badges per city, how to review false positives |

The CLAUDE.md root file gets a new Phase entry:

> **Phase 19** — Impact-first refactor (Sections 1-8 in this design doc)

Plus the existing decisions list in CLAUDE.md gets new entries for
each major architectural change (Wave 0, hybrid badge taxonomy, etc.)
so future contributors can find them without reading the spec doc.

### 8.8 Effort estimate

Coarse breakdown for sequencing implementation:

| Phase | Engineering days | Notes |
|---|---|---|
| Migration 013 + Wave 0 driver + tests | 3 | Schema is mechanical; Wave 0 reuses existing Stage 0 logic |
| Stage 1 prompt + extraction worker + tests | 4 | Prompt iteration, Pydantic schema validation, cache integration |
| Stage 2 v3 prompt + integration + tests | 3 | Evolving v2 prompt, banned words, suggested badges, reconcile.py |
| Stage 2.5 floors + overrides + tests | 3 | Scaffolding the floor table, per-city overrides, calibration queries |
| Process badges (7) + tests | 2 | Mostly SQL; pg_trgm setup |
| Policy badges (matcher + 4 BHM templates) + tests | 3 | Matcher logic, hybrid confidence model, audit log |
| Frontend: Smart Brevity Card variants + chips + engagement strip | 4 | 6 variants, mobile carousel, Jinja partials |
| Frontend: Category landing pages + SVG timelines | 3 | Mayoral overlay, consent baseline split, MV-backed query |
| Frontend: Admin views + data-issue endpoint | 2 | 5 admin routes plus citizen-facing report endpoint |
| Backfill driver + Batches API integration + tests | 3 | submit/poll/resume/session_id |
| Adaptive concurrency + integration | 1 | Module + worker integration |
| Operator runbooks | 1 | Three docs |
| Migration 014 + cleanup | 0.5 | Verification gate + drop |
| Buffer / integration / live testing / spot-checks | 3 | Reality check budget |
| **Total** | **~35 engineer-days** | Sequential single-engineer estimate; ~2.5x throughput with two engineers working parallelizable phases |

Calendar time including waves: **6-8 weeks** for a single engineer to
ship and complete backfill; **3-4 weeks** with two engineers
parallelizing Phase 2 frontend + Phase 2 pipeline.
