# Visual Refactor — Design Spec

**Date:** 2026-05-14
**Status:** Approved (pending user review of spec file)
**Predecessor:** Refactor #2 (PRs #16–#21) shipped 2026-05-12
**Sketch source:** `/Users/darrellnance/Downloads/docket-pub (1).zip` (Claude design canvas export)

---

## Context

The backend refactor cycle is done. This is the visual/UX refactor. The user's framing: "MOSTLY this is moving/removing where data is not creating new data points. We will be condensing the top of overview significantly and normalizing display."

The sketch zip provides JSX mockups for 6 surfaces: City Overview, Meeting Detail, Item Detail, Member Detail, Topic Detail, Source Health. Production currently has ~12 additional pages not covered by the sketches (homepage, category landing, coverage, search, topics index, meeting list, council roster, councilors index, about ×3, public data-debt, RSS feeds, 404/500). All of those are in scope for a translation pass.

---

## Locked decisions

1. **Visual direction:** the primary "Friendly" mockup is canonical. `variations.jsx` (Ledger / Terminal) is exploratory; elements adopt only if clearly better in practice.
2. **Member detail = new full page.** Roster cards link to it. **Bigger rule: the rail is overview-only.** It appears only when it shows information not already on the page. `RailMeeting` / `RailItem` / `RailMember` views (and their routes) are deleted from scope.
3. **KPI placement split:**
   - Inline strip (page body): Meetings YTD / Dollars YTD / Flagged items
   - Source rail (overview only): Meetings lifetime, Agenda items YTD, Votes YTD, Dollars pending vs settled — each with a per-KPI SQL explainer (`[n]` citation, hardcoded display string)
   - Dropped from the KPI strip: Council members, Topics tracked (they're nav, not numbers)
   - Freshness chip stays in the header
   - **"Flagged items" definition:** to a citizen, the label sitting next to "Dollars YTD" reads as *controversial legislation*, not pipeline errors. So the inline KPI is a **civic signal**, not a data-quality signal. Definition: **items with contested votes** — count of agenda_items joined to votes where `votes.nays > 0 OR votes.abstentions > 0`. Pure derivation from existing data; no new column; aligns with the "Contested votes" section already on the page. (`meetings.flag` doesn't exist in the schema — was flagged as "looks new" in the sketch synthesis; rejected.)
   - **Data-quality count is a separate metric.** If we want it visible, label it "Data issues" or "Pipeline errors" and put it in the rail or on the Source Health page — *not* in the inline strip next to dollar/meeting counts. Decided not in scope for the inline strip.
4. **Mobile = Plan A** (lightweight launcher) for v1. Plan B (peek-sheet w/ snap-points + scroll-sync) parked as a v2 tracking issue.
5. **Source Health = new page** (pipeline transparency, linked from the freshness chip). **Public data-debt stays as-is** (citizen-facing item list). Different concepts, different pages.
6. **Category landing = translation pass only.** No layout changes. Inherits new shared components; follow-up issue logged for proper UX revisit later.

---

## Rollout — 5 phases, each its own PR

Mobile (Plan A) responsive CSS ships alongside desktop CSS in each phase — not its own phase.

---

## Phase 1 — Foundation

**Scope shrunk after codebase audit (2026-05-14).** Most "foundation" infrastructure already exists in production — see "Already implemented" below. P1 lands only the genuinely-missing pieces.

### Already implemented (NOT touched in P1)
- Bottom tab bar: `partials/bottom_tabs.html` is fully wired (5 tabs: City / Meetings / Topics / Council / More; aria-current handling; More opens a `<dialog>` action sheet).
- Source sheet: `partials/source_sheet.html` exists and is included in `base.html`.
- Mobile search icon: `masthead.html:46-54` already collapses search to an icon button at mobile widths.
- Breadcrumbs: `masthead.html:57-63` already renders crumbs for city-scoped pages via a `{% block crumb %}` Jinja block (no new partial needed).
- Fonts: Source Serif 4, IBM Plex Sans, JetBrains Mono all loaded in `base.html:10`.
- OKLCH color tokens, t-display/t-eyebrow/t-mono/t-meta/t-label type classes — all defined in `styles.css`.
- `mobile.css` loads last, `@media (max-width:768px)` rules win at narrow widths.
- Per-page `<link rel="stylesheet">` order is correct.

### Genuinely missing — what P1 actually does

#### 1. Design tokens (`src/docket/web/static/styles.css`)
Add to `:root`:
- **Type-scale variables:** `--type-hero: 64px`, `--type-hero-mobile: 44px`, `--type-section: 28px`, `--type-card: 17px`, `--type-body: 15px`, `--type-eyebrow: 10px`, `--type-mono-num: 26px`. Used by P3+ when new partials and rebuilt pages reference them.
- **Spacing-scale variables:** `--space-1: 4px`, `--space-2: 8px`, `--space-3: 12px`, `--space-4: 16px`, `--space-6: 24px`, `--space-8: 32px`, `--space-12: 48px`, `--space-16: 64px`. Off-scale values discouraged in new partials.

#### 2. Footer mobile accordion (`src/docket/web/templates/partials/footer.html` + `tweaks.css`)
- Wrap each `.footnote-col` body in `<details>` / `<summary>`. First column gets `open` attribute.
- CSS in `tweaks.css`: at `min-width: 769px`, force-show content + hide disclosure arrow (`pointer-events: none` on summary, `::marker { display: none }`, `> *:not(summary) { display: block }`). At `max-width: 768px`, render as normal accordion with `+`/`−` indicator.
- Colophon and bottom strip are NOT accordioned — they stay flat.

### Spec corrections (do not implement; here for record)
- **Footer stays 2 columns + colophon** (not 4). The original "4 columns (About / Citizens / Journalists / Trust)" target was aspirational from the sketch synthesis; production has 2 columns with real copy and a colophon. Adding "Journalists" / "Trust" columns needs copy authorship — out of scope for the visual refactor.
- **Drop "Legislation" from masthead nav.** No `/legislation` route exists; the existing per-city nav (Overview / Meetings / Members) is correct.
- **No new `breadcrumbs.html` partial.** Existing `{% block crumb %}` block in `masthead.html` is the right pattern; new pages override it.

### Files touched in P1
- `src/docket/web/static/styles.css` (token additions)
- `src/docket/web/templates/partials/footer.html` (wrap cols in `<details>`)
- `src/docket/web/static/tweaks.css` (accordion CSS)

That's it. Three files. ~80 lines of changes total.

### Verification
- Tokens are visible in browser devtools `:root` inspector.
- Footer renders identically at desktop (≥769px) — 2 columns, all content visible, no disclosure arrows.
- Footer at mobile (<768px) shows first column open, others collapsed; tapping summary expands.
- No pytest regressions (existing suite must pass).

---

## Phase 2 — Component library

Extracts/restyles partials. No page templates change in P2 — they keep their current layouts but pick up restyled partials.

### New partials
- `partials/meeting_card.html` — args: `meeting`, `variant=strip|grid`. Used on overview (strip), meeting list (grid), homepage.
- `partials/num_stat.html` — args: `label`, `value`, optional `sub`, optional `accent`. Used in KPI strip, meeting/member/source-health headers.
- `partials/freshness_chip.html` — args: `state` (good/warn/bad), `last_synced`. Links to `/al/<slug>/source-health/`.
- `partials/source_rail.html` — desktop sidebar container. Overview-only. Replaces `partials/rail_default.html`.
- `partials/source_sheet.html` — mobile sheet container. Same slots as `source_rail.html`, different chrome. Driven by `sheet.js`.
- `partials/kpi_explainer.html` — args: `label`, `value`, `sub`, `sql_display`. Single KPI card with SQL toggle. Hardcoded SQL display string; *not* live-executed.
- `partials/topic_row.html` — extracted from `city.html` topic carousel. Horizontal scroll-snap pills.
- `partials/breadcrumbs.html` — args: `crumbs` list. Renders below masthead on every non-root page.

### Restyled (kept partial, new look)
- `partials/smart_brevity_card.html` — the canonical item card. Keeps its 6 state variants (smart_brevity / procedural / degraded / failed / pending / placeholder). Restyled to match the sketch's LegislationCard idiom: eyebrow + tier badge + title + mono byline + status pill + topic dot. **Decision: no parallel `LegislationCard` partial** — that would fork the state logic.
- `partials/council_card.html` — restyled to baseball-card pattern (avatar tile + name + district + attendance % + alignment %).
- `partials/badge_chip.html` — restyled.
- `partials/dollar_tier.html` — restyled.

### Deleted
- `partials/rail_meeting.html`
- `partials/rail_member.html`
- View functions and routes: `rail_meeting()` (`public.py:874`) and `rail_member()` (`public.py:892`), plus their URL bindings.

### Untouched in P2
- All page templates
- All admin templates
- All RSS templates
- `partials/volume_timeline.html` (category landing — translation pass in P5)

### Convention note
Existing project pattern is `{% include %}` with context, not `{% macro %}`. P2 keeps that — only one macro is defined site-wide today; introducing a macros file would be inconsistent.

### Verification
- Site renders identically except for the four restyled partials (item cards, council cards, badge chips, dollar tiers).
- These look new but still work on existing page layouts.
- Visual check on city, meeting_detail, council, item_detail, category_landing — no breakage.

---

## Phase 3 — City overview rebuild

The centerpiece. Replaces `src/docket/web/templates/city.html` and updates `city_overview()` in `src/docket/web/public.py:82`.

### New top of page

1. Breadcrumbs (from P1)
2. **CityLead** — one compressed block:
   - Eyebrow: `council type · county · population` (one line, 10px mono caps)
   - h1: city name only (e.g., "Birmingham, Alabama") — no narrative below
   - Freshness chip on the right, linked to `/al/<slug>/source-health/`
3. **Inline KPI strip** — 3 `num_stat` cards: Meetings YTD, Dollars YTD, Flagged items
4. Browse by Priority grid (kept, restyled with new badge chips)

Roughly 3 short rows where today there are ~6 stacked elements.

### Below the fold (kept, lightly restyled)
- Topics carousel → `partials/topic_row.html`
- This Week meetings → `partials/meeting_card.html` (strip variant)
- Upcoming meetings → `partials/meeting_card.html` (strip variant)
- Notable items → restyled `smart_brevity_card`
- Contested votes → restyled
- Council cards → restyled `council_card`, each linking to `/al/<slug>/council/<member_id>/` (route added in P4)

### Source rail (desktop, overview only)
- KPI explainers stacked: Meetings lifetime, Agenda items YTD, Votes YTD, Dollars pending vs settled
- Each renders one `kpi_explainer` with value + label + optional `sub` (grounding text) + "show SQL" toggle (hardcoded SQL display string in the partial; *not* live-executed)
- **"Lifetime" KPIs get a `sub` line** indicating the start year — e.g., "Since 2017" — derived from `MIN(meetings.date)` for the city. Prevents reader confusion as historical backfill expands. Same pattern applied to any other "lifetime" or "all-time" counter.
- Source/provenance block: adapter class, last sync time, link to source URL

### Mobile (Plan A)
- CityLead h1 drops to 44px Source Serif
- KPI strip becomes horizontal scroll-snap (3 × 130px cards)
- **"View source" entry point moves to the top of the page** — small inline link/button placed near the freshness chip in the CityLead. **No floating bottom pill** (avoids thumb-zone collision with the bottom tab bar). The two affordances are semantically distinct: freshness chip → navigates to the `/source-health/` page (pipeline view); inline "View source" link → opens the source sheet (overview's provenance + KPI rail content). Keep both visible at the top so they're equally discoverable.
- Sheet behavior: full-screen modal, simple open/close, no snap points (Plan A). **Fixed top-right "Close" (X) button**, large hit target (≥44×44px), focus-trapped, scroll-locked. Esc closes on devices with hardware keyboards.

### Data flow / new computed values

The view function builds a `city_stats` dict:

```
meetings_ytd, dollars_ytd, flagged_count          # inline strip
meetings_lifetime, agenda_items_ytd, votes_ytd,
dollars_pending, dollars_settled                  # rail
```

Each is a scoped COUNT/SUM with `municipality_id` filter and year-to-date range. **No schema changes** — these are aggregations over existing columns (`meetings.date`, `agenda_items.dollars`, `votes.id`, `agenda_items.flag IS NOT NULL`).

### Performance
- 8 small aggregations on indexed columns scoped to one city. Expected fast.
- Memory entry warns contested-votes/member-votes joins were the OOM culprits — those queries don't change here.
- If profiling shows the strip is slow, wrap `city_stats` in a 5-minute Flask cache (page updates daily via cron; TTL well under cron interval is safe).
- Per feedback memory: do an in-transaction synthetic-scale EXPLAIN on Railway before merge.

### Deleted from `city.html`
- Hero narrative block
- 4-card KPI grid (replaced by 3-card inline)
- "Council members" and "Topics tracked" KPI cards
- Badge legend paragraph (legend lives in `/about/how-we-read-minutes/`)

### Files touched
- `src/docket/web/templates/city.html` (rewrite)
- `src/docket/web/templates/partials/source_rail.html`, `source_sheet.html`, `kpi_explainer.html` (populated)
- `src/docket/web/public.py:82` — `city_overview()` builds `city_stats`
- `src/docket/web/static/js/sheet.js` — wired to the "View source" pill on city pages only

### Risks
- Aggregation queries on Railway — EXPLAIN check before merge.
- The Browse by Priority section is **not** in scope to move; it stays.

### Verification
- Top of page is ~3 rows tall on desktop.
- Inline KPI strip shows 3 numbers (Meetings YTD / Dollars YTD / Flagged items — contested votes).
- Rail (desktop) shows 4 KPI explainers + provenance. Lifetime KPI shows "Since YYYY" sub-label.
- Mobile: inline "View source" link near the freshness chip opens the full-screen sheet (same content as the desktop rail). No floating bottom pill.
- Mobile sheet has a top-right Close button (≥44×44px hit target), focus-trapped, scroll-locked, Esc closes.
- Freshness chip links to Source Health page (built in P4).

---

## Phase 4 — Detail pages

One PR (or split in two if it grows). None of these pages get a rail per the overview-only rule. All info lays out in the page body.

### 4a. Meeting Detail (`src/docket/web/templates/meeting_detail.html`)
- **Header:** back link → eyebrow (type pill · date · venue) → h1 (title) → NumStat strip (agenda items / recorded votes / dollars)
- **Body:** agenda sections grouped by type (Consent / Resolutions / Ordinances / Hearings / Communications). The split already exists; new section header partial gives each a header + count.
- Per-item vote tally stays as today, restyled with new badges/dollar tiers. Source + confidence shown inline as small mono meta.
- **Conflict callout** appears when sources disagree. **All conflict evaluation happens in `public.py:208`**, not in the template — the view function computes a `has_conflict: bool` and passes it in. Avoids Jinja anti-patterns (heavy text comparison / multi-source reconciliation logic in template = bloated render budget + harder debugging). If/when a `votes.conflict` column is added later, the view function reads it directly; until then, the view function derives the boolean from existing `minutes_text` vs `video_ocr` vote sources. Template stays a simple `{% if has_conflict %}`.
- Route + view function unchanged (`public.py:208`); view function gains a small private helper for the conflict computation.

### 4b. Item Detail (`src/docket/web/templates/item_detail.html`)
- **Header:** back link → eyebrow (item_number + meeting context) → dollar tier badge (right) → h1 (title) → mono byline (sponsor · date · section) → status pill → topic dot
- **Body:** Why it matters → vote result block (if vote exists) → extracted facts strip (existing partial) → related items (by topic or shared sponsor, query already supported) → coverage block (existing partial)
- No conflict callout here — too little space; conflicts surface at the meeting level.
- Route + view function unchanged (`public.py:245`).

### 4c. Topic Detail (`src/docket/web/templates/topic_detail.html`)
- Light page. **Header:** breadcrumbs → eyebrow (color dot · count) → h1 (topic label)
- **Body:** card grid of items in this topic (restyled `smart_brevity_card`, existing pagination)
- Route + view function unchanged (`public.py:823`).

### 4d. Member Detail — NEW ROUTE

- **Route:** `/al/<slug>/council/<member_id>/`. Consistent with existing `/al/<slug>/council/` roster pattern.
- **View function:** new `member_detail()` in `public.py`. Renders `src/docket/web/templates/member_detail.html`.
- **Header:** breadcrumbs → avatar tile + name (h1) → meta line (district · term) → NumStat strip (attendance % / alignment_with_majority % / sponsorship count)
- **Body:** voting history table with filter chips (All / Dissent only / Sponsored only) → recent sponsored items list
- **Data:** `council_members.attendance`, `.alignment_with_majority`, `.votes_total` all exist. Sponsorship count = `COUNT(agenda_items WHERE sponsor_member_id = ?)`. Voting history = JOIN through `member_votes` → `votes` → `agenda_items`.
- **Performance:** memory flags member_votes JOINs as the OOM culprit. Voting history table **must paginate** (20 rows). Filter chips re-query the server; don't filter in-page.
- **Filter chip extensibility:** the filter chip row uses the same horizontal scroll-snap container pattern as `topic_row`. v1 chips are All / Dissent / Sponsored. The row must accept additional chips without redesign — when the platform adopts strategic-priority / watchdog-theme tagging later, citizens will want to filter a member's voting history by those tags. Leave spatial + CSS room; don't hard-code three chip widths.
- **Term scoping:** memory note — "Birmingham council has had many members; term dates must cover actual vote date ranges." Voting history scoped to the member's term/vote window, not the city's full history.
- **Roster wire-up:** `partials/council_card.html` becomes a link to this route. Updates `council.html` and the council section on `city.html`.

### 4e. Source Health — NEW ROUTE

- **Route:** `/al/<slug>/source-health/`. Linked from the freshness chip in the new masthead.
- **View function:** new `source_health()` in `public.py`. Renders `src/docket/web/templates/source_health.html`.
- **Header:** breadcrumbs → h1 ("Source health · Birmingham") → freshness chip (large variant)
- **Body:** pipeline stages — Source → Adapter → Parser → Index. Each stage shows: state dot (good/warn/bad), last_checked, last_success, next_check.
- **v1 data scope (no schema additions, no new probe infrastructure):**
  - Source = `municipalities.source_url` (display only — no live reachability probe in v1; current platform has no URL-probe cron task)
  - Adapter = `municipalities.adapter_class` + last successful `ingest_all` run (derive from MAX(`meetings.created_at`) for this city or from the cron worker's Healthchecks.io last-success timestamp if exposed)
  - Parser = last successful agenda parse (most recent meeting with `agenda_count > 0`)
  - Index = most recent meeting `created_at` for this city; total meetings/items indexed
- **Not in v1:** live source-URL reachability probe, real-time pipeline-stage telemetry, per-stage failure logs. Those failure logs exist in `/admin/errors`; source health links there for admins. Sketch shows richer pipeline detail; v1 ships with what's derivable from existing data. Live probes + per-stage history are a follow-up.
- **Public, no admin info.** Operator-detail lives in `/admin/data-debt/` and `/admin/errors`.

### Files touched in P4
- `src/docket/web/templates/meeting_detail.html`, `item_detail.html`, `topic_detail.html` (restyle)
- `src/docket/web/templates/member_detail.html`, `source_health.html` (new)
- `src/docket/web/public.py` — new `member_detail()` and `source_health()` view functions + routes
- `src/docket/web/templates/council.html` and `partials/council_card.html` — wire roster links to new member route
- No migrations. No new columns. Everything derives from existing data.

### Risks
- `votes.conflict` may not exist yet → callout falls back or feature-flags off.
- Member voting history query is the highest-risk perf item. Pagination + EXPLAIN check on Railway before merge.

---

## Phase 5 — Translation pass

One PR (or two if it gets big). No new layouts, no new components — each page inherits P1 tokens + P2 partials.

| Page | Template | Treatment |
|------|----------|-----------|
| Homepage (`/`) | `index.html` | New `meeting_card` (strip), new typography. No layout change. |
| Meeting list (`/al/<slug>/meetings/`) | `meetings.html` | New `meeting_card` (grid), restyled pagination, type filter stays. |
| Council roster (`/al/<slug>/council/`) | `council.html` | Restyled `council_card`; member links wired in P4. |
| Topics index (`/topics/`) | `topics.html` | `topic_row` partial + new typography. |
| Search (`/search`) | `search.html` | Restyled `smart_brevity_card` results. |
| Coverage listing (`/coverage/`) | `coverage/listing.html` | Light restyle of existing coverage partials. FTS bar matches new tokens. |
| Coverage permalink (`/coverage/<id>`) | `coverage/permalink.html` | Restyle. Polymorphic subjects footer (item/meeting/member/badge) must render in all 4 cases — test each. |
| About × 3 | `about.html`, `about_methodology.html`, `about_corrections.html` | Typography from P1 carries most of it; sanity-check copy fits new spacing. |
| Councilors index (`/councilors/`) | `councilors.html` | City picker, new typography. |
| Public data-debt (`/al/<city>/data-debt`) | `data_debt.html` | Per Q5: functionally identical, new typography only. |
| Category landing (`/al/<slug>/<badge>/`) | `category_landing.html` | Translation: new cards via `_item_list`, new `badge_chip`, new typography. KPI strip uses new `num_stat`. Volume timeline SVG untouched. Cross-filter chips restyled. Follow-up issue logged for UX revisit. |
| RSS × 3 | `rss/*.xml.j2`, `coverage/feed.xml.j2` | Untouched — XML, no visual styling. |
| Item badges overflow | (501 stub at `/items/<id>/badges`) | Left as stub; follow-up issue logged. |
| 404 / 500 | new `errors/404.html`, `errors/500.html` | New custom templates. Masthead/footer/typography from P1. Friendly copy. |

### Files touched
- ~12 templates, light edits each. Zero view function changes. Zero migrations.

### Risks
- Category landing has the most surface area; visual-regression check that volume timeline still renders and cross-filters still resolve correctly after restyle.
- Coverage permalink polymorphic subjects — test item/meeting/member/badge subject types each.
- About pages — copy may need trimming if it overflows new spacing tokens.

---

## Cross-cutting concerns

### Out of scope
- All admin templates (`/admin/*`). Operator-only; visual changes don't help citizens.
- Public API (deferred per CLAUDE.md).
- Pairs / proposers (v1.1+ outstanding; future cycle).
- Plan B mobile (peek-sheet + snap-points + scroll-sync) — parked as v2.
- Category landing UX revisit — follow-up issue.
- Item badges overflow real implementation — follow-up issue.

### Testing approach
- Visual: manual walkthrough at desktop + mobile breakpoint for each phase before merge.
- Functional: existing pytest suite must stay green. New routes (`member_detail`, `source_health`) get smoke tests.
- DB: in-transaction EXPLAIN on Railway production for `city_stats` aggregation and `member_detail` voting history JOIN before P3 / P4 merge.
- The user is the final visual reviewer per phase; no automated visual regression in v1.

### Data integrity
- No new columns. No migrations. No backfills.
- Conflict callout in P4 is the only feature that *might* want a new column (`votes.conflict`) — explicitly feature-flagged off if absent. Logged as a follow-up data-quality task, not a blocker.

### Performance budget
- Overview page must stay within current p95 server-rendering budget (~200ms on Railway).
- Member detail voting history paginates to 20 rows.
- Source rail KPI explainer SQL is *display only* — never live-executed.
- No new heavy joins added anywhere.

### Mobile (Plan A) implementation notes
- Single codebase, responsive at 768px hard cutoff.
- Sheet uses `<dialog>` element if browser support is acceptable, otherwise hand-rolled with `aria-modal="true"` + focus trap + scroll lock + Esc-to-close. Fixed top-right Close button (≥44×44px hit target).
- `sheet.js` ~50 lines vanilla JS. No external library.
- **No floating bottom pill.** The "View source" entry point is an inline link near the freshness chip in CityLead (city overview only). Avoids thumb-zone collision with the bottom tab bar.
- Bottom tab bar appears on every page `<768px`.

---

## Follow-up issues (post-merge)

1. **Category landing UX revisit** — sketch + redesign the cross-filter UI, KPI placement, and timeline interactions in a follow-up cycle.
2. **Item badges overflow page** — replace the 501 stub with a real listing once items routinely carry >3 badges.
3. **Plan B mobile** — peek-sheet at 30%, drag-up to 92%, scroll-sync rail content. Decide after Plan A use data accrues.
4. **`votes.conflict` column** — if conflict-callout feature proves valuable, formalize as a column with explicit detection rules.
5. **Real-time source-health telemetry** — pipeline-stage per-run logs surfaced publicly; current v1 derives from existing data.

---

## Sketch reference

Source files (in `/tmp/docket-sketches/` after extraction):
- `Birmingham Overview.html` + `design-canvas.jsx` + `components-header.jsx` — city overview canon
- `meeting-detail.jsx`, `item-detail.jsx`, `topic-detail.jsx`, `member-detail.jsx`, `source-health.jsx` — detail pages
- `components-feed.jsx`, `components-rail.jsx`, `components-council.jsx` — components
- `variations.jsx` — Ledger / Terminal exploration (reference only)
- `mobile-variations.jsx` + `uploads/Mobile_Design_Plan_A_Lightweight.md` — mobile Plan A canon
- `uploads/Docket Birmingham - Detail Pages Brief.md`, `uploads/docket-pub_ui.md` — written briefs
