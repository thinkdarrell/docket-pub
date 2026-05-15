# Visual Refactor — Phase 3 (City Overview Rebuild) Design

> **Status:** Brainstormed 2026-05-15. Supersedes the Phase 3 section of `2026-05-14-visual-refactor-design.md` because P2b dropped the rail (the master spec assumed an overview-only rail; P2b shipped `page_sources.html` as a page-bottom block on every page instead).
>
> **Predecessor:** P2b shipped 2026-05-15 (PR #54, squash-merge `d6dab01`). 9 P2b follow-ups were logged; this spec resolves 3 of them: **#1** `--type-hero` 64px-vs-72px mismatch (token wins), **#4** top 4-card KPI grid replacement, **#5** `page_sources` / `footer.html` colophon Adapter overlap. The remaining 6 follow-ups (orphan rail CSS, sheet.js dead branches, lifetime-dollar UX honesty, mid-density 1280px rules, pre-existing topics 404, KPI value font) are out of scope here.
>
> **Scope band:** "P3 + obvious-overlap fixes" (option B from brainstorming). Specifically: rebuild city.html top of page, resolve `--type-hero` decision, slim footer.html colophon to remove duplicate Adapter info. **Deferred:** orphan rail CSS in layout.css + mobile.css, sheet.js dead source-rail branches, lifetime-dollar UX honesty.

---

## Architecture

Single PR rewrites the top section of `src/docket/web/templates/city.html` (replacing the hero narrative + 4-card KPI grid + 2 standalone KPI cards + badge legend paragraph with 3 compressed rows). Below-the-fold sections (Topics carousel · This Week · Upcoming · Notable items · Contested votes · Council cards) stay structurally; they already consume P2b's restyled partials.

Two structural shifts beyond the city.html rewrite:

1. **KPI section split.** The 4-card KPI explainer stack currently rendered on overview's bottom (via `page_sources.html` when `kpi_stats` is in context) moves to **interior pages only** (meetings list, council, search, topic detail, meeting detail, category landing). Overview's bottom becomes provenance-only. The intent: overview's top owns quick at-a-glance YTD stats (3 cards); interior pages get the deeper lifetime / YTD explainer stack to give city-wide context to a citizen who landed on a specific surface.

2. **`page_sources.html` ↔ `footer.html` colophon dedup.** Both currently display per-city Adapter info. Strip the Adapter tile from footer's colophon; footer becomes "about docket.pub the project" (Schema · Source · Updated + data-honesty paragraph). page_sources owns the per-city provenance.

A new `municipalities.metadata` JSONB column powers the CityLead eyebrow (council type · county · population). Adding a city now means INSERT + populate JSON; no schema or code change beyond seed data.

---

## Components

### 1. CityLead block (new partial)

Replaces the hero block + 4-card KPI grid + 2 standalone KPI cards. Renders 2 compressed rows:

```
[Council–manager · Jefferson County · 196,910 pop.]              ← eyebrow, 10px mono caps
[Birmingham, AL]                       [● Live · synced 4m ago]   ← h1 64px serif + freshness chip
```

**Breadcrumbs deliberately excluded.** The master spec listed "Breadcrumbs (from P1)" but `partials/breadcrumbs.html` was never built (P1 didn't include it; P2a's actual partial list also skipped it). Breadcrumbs are not meaningful on a city overview (it IS the root for a city). When P4 builds meeting detail / member detail / source health, those pages can introduce breadcrumbs at that time — out of scope here.

**File:** `src/docket/web/templates/partials/city_lead.html` (NEW).

**Args (via render context):**
- `municipality` (dict) — required. Must include `name`, `state`, `slug`, `adapter_class`, and `metadata` (dict, may be empty).
- `freshness` (dict, optional) — `{state: 'good'|'warn'|'bad', last_synced: datetime, label: str}`. When absent, chip renders in a neutral "unknown" state.

**Eyebrow rendering:** consumes `municipality.metadata.get('council_type')`, `.get('county')`, `.get('population')` with `population_year` optional. If all three are missing the eyebrow row collapses (renders nothing). If only some are present, render what's available joined by `· ` separators. **Graceful degradation is required** — newly-onboarded cities will lack metadata until populated.

**Population format:** `{value:,} pop.` (e.g., "196,910 pop.").

**h1:** city + state (`"{name}, {state}"`). Single line at 64px Source Serif 4 (consumes `--type-hero`).

**Freshness chip:** consumes the existing `partials/freshness_chip.html` from P2a (currently unconsumed in production — this is its first render). **In P3, the chip is static** (no link, no click). P4 wires the source-health route and makes it clickable.

### 2. 3-card YTD strip

Directly below CityLead. Three `partials/num_stat.html` partials (P2a):

| Card | label | value | source |
|---|---|---|---|
| 1 | "Meetings YTD" | int formatted with `:,` | `query.count_meetings_ytd(mid)` |
| 2 | "Dollars YTD" | "$N.NM" or "$NNN,NNN" via `format_dollars` filter | `query.sum_dollars_ytd(mid)` |
| 3 | "Flagged items" | int | `query.count_contested_votes_ytd(mid)` |

"Flagged items" maps to "contested votes" per the original spec line 200. Definition: votes recorded YTD where the council split (≥1 dissent).

Wraps in a single `.kpi-strip` flex container. On desktop, 3 cards equal width. On mobile (`<768px`), horizontal scroll-snap (3 × 130px cards).

### 3. Browse by Priority grid

**Kept structurally as-is.** Uses P2b's restyled `partials/badge_chip.html` automatically (the badge chips were restyled in P2b Task 5 + size-fix `9a41240`). P3's only work here is a CSS audit to confirm the tile rendering still feels right with the new chips.

### 4. Below the fold (unchanged structure, restyled partials inherited)

- **Topics carousel** → already uses P2a's `topic_row.html` (or migrates to it if not yet)
- **This Week meetings** → uses `meeting_card.html` strip variant
- **Upcoming meetings** → `meeting_card.html` strip variant
- **Notable items** → `card_smart_brevity.html` (restyled in P2b Task 6)
- **Contested votes** → restyled in P2b
- **Council cards** → restyled `council_card.html` (P2b Task 7); links to `/al/<slug>/council/<member_id>/` are **NOT** wired in P3 — that's P4 (member detail page). For P3 the cards remain `<button type="button">` no-ops as they are today.

### 5. Deleted from city.html

- Hero narrative block (was lines for the descriptive paragraph)
- 4-card KPI grid (replaced by the new 3-card YTD strip)
- "Council members" and "Topics tracked" KPI cards (counts available via other surfaces)
- Badge legend paragraph (legend lives in `/about/how-we-read-minutes/`)

### 6. `page_sources.html` change

No template restructure. The only change: it's now rendered with `kpi_stats` ONLY by interior view functions, not by `city_overview()`. The `{% if kpi_stats %}` gate already exists from P2b; the change is what views opt in.

### 7. `footer.html` colophon slim

Drop the `<div class="footnote-grid t-mono">` block's Adapter tile. Keep Schema · Source · Updated + the data-honesty paragraph.

---

## Data flow

### Migration (next sequence number — `029_municipalities_metadata.py` likely)

```sql
ALTER TABLE municipalities ADD COLUMN metadata JSONB NOT NULL DEFAULT '{}'::jsonb;
```

Seed UPDATE for the 6 existing cities (Birmingham, Mobile, Montgomery, Hoover, Homewood, Vestavia Hills) with `council_type`, `county`, `population`, `population_year` fields. Future cities INSERT with their metadata payload at onboarding time; no migration needed per-city.

Example seed:
```sql
UPDATE municipalities SET metadata = '{
  "council_type": "Council-manager",
  "county": "Jefferson County",
  "population": 196910,
  "population_year": 2020
}'::jsonb WHERE slug = 'birmingham';
```

### New query helpers in `src/docket/services/query.py`

```python
def count_meetings_ytd(municipality_id: int) -> int
def sum_dollars_ytd(municipality_id: int) -> Decimal
def count_contested_votes_ytd(municipality_id: int) -> int
def most_recent_ingest_at(municipality_id: int) -> datetime | None
def _kpi_stats_for_municipality(municipality: dict) -> list[dict]
def _freshness_state(last_ingest: datetime | None) -> dict  # → {state, label, last_synced}
```

**`_kpi_stats_for_municipality`** consolidates the 4 P2b helpers (`count_meetings_lifetime`, `count_agenda_items_ytd`, `count_votes_ytd`, `dollars_pending_vs_settled`) into a single list-of-dicts call. Returns the same `kpi_stats` shape `page_sources.html` already consumes from P2b. Single source of truth for the interior-page explainer stack.

### View function changes in `src/docket/web/public.py`

- `city_overview()` — builds `city_stats` dict (3 YTD values for the top strip); DROPS the `kpi_stats` build that P2b added. `city_stats` is keyed `meetings_ytd`, `dollars_ytd`, `flagged_count`.
- `city_meetings()`, `city_council()`, `search()`, `topic_detail()`, `meeting_detail()`, `category_landing()` — each adds `kpi_stats=query._kpi_stats_for_municipality(municipality)` to its `render_template` call. Six view functions touched.

---

## Mobile reflow

At `<768px`:
- Eyebrow stays inline (wraps to 2 lines if necessary)
- h1 drops to 44px Source Serif (existing `.hero-title { font-size: 56px }` rule in mobile.css adjusts to 44px to match the new CityLead intent — verify against the post-P2b layout)
- Freshness chip flows below h1
- 3-card YTD strip becomes horizontal scroll-snap (3 × 130px cards) — new `.kpi-strip` mobile rule
- `bottom_tabs.html` unchanged (site-wide nav from P2b)
- No bottom sheet, no floating pill

---

## `--type-hero` token migration

P2a follow-up #1 resolved here. The token at `styles.css:52` says `--type-hero: 64px`. The live `.hero-title` rule at `layout.css:146` ignored the token and used `72px` literal.

P3 changes:
- `.hero-title { font-size: 72px }` rewritten to `font-size: var(--type-hero);` — token wins, value is 64px
- CityLead's h1 also uses `var(--type-hero)` directly

Visual delta on the live site: city overview hero shrinks from 72px to 64px. The 64px feels "compressed" which matches the spec's framing. Brainstorming-time visual review confirmed the delta is subtle and the smaller size is acceptable.

---

## Performance

- 3 new YTD aggregations on city overview (count_meetings, sum_dollars, count_contested_votes) — all scoped to municipality + indexed columns. Expected <50ms each at current scale.
- 4 explainer stack queries × 6 interior view functions = added load on interior page renders. Each query is scoped + indexed + small; aggregate <200ms expected per render.
- Existing 5-min `_overview_cache` for city overview is preserved.
- Interior pages don't have a comparable cache today; if profiling shows per-render slowdown, add a similar TTL cache to the high-traffic ones (meetings list, council roster).
- Per memory `feedback_explain_at_scale.md`: run in-transaction synthetic-scale EXPLAIN on Railway public DB for each new query before merge.

---

## Files touched

| File | Action |
|---|---|
| `src/docket/migrations/029_municipalities_metadata.py` | NEW migration (column add + 6-city seed) |
| `src/docket/migrations/runner.py` | Register migration 029 |
| `src/docket/services/query.py` | +3 YTD helpers + `most_recent_ingest_at` + `_freshness_state` + `_kpi_stats_for_municipality` |
| `src/docket/web/public.py` | Update city_overview + 5-6 interior view functions |
| `src/docket/web/templates/city.html` | Rewrite top section; insert `city_lead` + `kpi_strip` partials; delete hero narrative + 4-card KPI grid + 2 standalone KPI cards + badge legend |
| `src/docket/web/templates/partials/city_lead.html` | NEW partial |
| `src/docket/web/templates/partials/kpi_strip.html` | NEW partial (3-card wrapper around 3 `num_stat` partials) |
| `src/docket/web/templates/partials/footer.html` | Remove Adapter tile from colophon |
| `src/docket/web/static/styles.css` | New `.city-lead*` rules; `.hero-title` rewritten to consume `--type-hero` |
| `src/docket/web/static/layout.css` | New `.kpi-strip` rules |
| `src/docket/web/static/mobile.css` | Mobile reflow for `.city-lead*` and `.kpi-strip` |
| `tests/web/test_partials_visual_refactor.py` | Snapshot tests for city_lead + kpi_strip |
| `tests/web/test_city_overview_render.py` | NEW or extended — render tests for the new top section + KPI split |
| `tests/migrations/test_029_municipalities_metadata.py` | NEW — apply + rollback test for the migration |

---

## Risks

- **Migration ordering on Railway.** Apply locally first, verify Railway after deploy via `python -m docket.migrations.runner --status`. Migration is idempotent (`IF NOT EXISTS` not strictly needed for a simple column add, but write it defensively).
- **Interior page render cost.** 4 added queries per interior render — verify EXPLAIN timings. If meetings list / council roster slow noticeably, add per-route TTL cache as follow-up.
- **Freshness chip data source — confirmed.** No `last_sync_at` column exists on `municipalities`. P3 derives freshness from `MAX(meetings.created_at)` scoped to the city — the most recent ingest timestamp. New helper `query.most_recent_ingest_at(municipality_id) -> datetime | None`. State thresholds in a helper: `good < 24h since most recent ingest`, `warn < 7d`, `bad >= 7d`. Returns `None` for newly-onboarded cities with zero meetings (chip renders in neutral "unknown" state).
- **Browse by Priority visual regression.** The grid wasn't touched in P2b but its tiles consume the restyled `badge_chip`. Visual sweep before merge.
- **Eyebrow + h1 overflow on long city names.** Birmingham fits comfortably. Vestavia Hills + state may push tighter. Test rendering with the longest expected city name.

---

## Verification

- Top of page on city overview is ~3 short rows (eyebrow + h1+chip + KPI strip) vs. today's 6 stacked elements.
- 3-card YTD strip shows 3 numbers; values match a manual SQL query against the database.
- Interior pages (meetings list, council, search, topic detail, meeting detail, category landing) render the 4-card KPI explainer stack in `page_sources.html` at the page bottom.
- City overview's `page_sources.html` renders provenance only — NO KPI explainer stack.
- Footer colophon shows Schema · Source · Updated tiles (3 tiles, not 4) — no Adapter tile.
- Freshness chip renders with status dot + adapter name + relative timestamp; **not clickable in P3** (P4 wires).
- Migration applies cleanly; rollback works.
- All 6 existing cities show their eyebrow line; a hypothetical city with empty metadata renders an empty eyebrow row (no broken text).
- Mobile (<768px): CityLead reflows cleanly; KPI strip becomes horizontal scroll; eyebrow may wrap.
- Pytest count: ~1605 (1595 baseline + ~10 new tests).
- EXPLAIN on Railway public DB confirms each new query under 50ms at current scale.

---

## Out of scope (deferred for later phases)

- Orphan rail CSS (~110 lines) in `layout.css` + `mobile.css` — P3 cleanup pass or P4.
- `sheet.js` dead source-rail/source-sheet branches — same.
- Lifetime dollar sum UX honesty (`$5.3B pending / $766M settled` double-counts line items) — P3 follow-up or new spec.
- Source Health page (P4) — the freshness chip's eventual click target.
- Member detail page (P4) — the council card's eventual click target.
- Top 4-card KPI grid's "Council members" and "Topics tracked" cards — explicitly deleted, not replaced.
