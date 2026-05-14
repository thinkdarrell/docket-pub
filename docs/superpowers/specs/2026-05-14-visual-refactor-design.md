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
   - **"Flagged items" definition (TBD before P3):** the sketch field is ambiguous against the current schema. Options: (a) count of items with `agenda_item_badges.status = 'flagged'` (admin queue items — risk: skews to LLM-only badge suggestions, citizen interpretation unclear); (b) count of items with `data_debt_priority = 'high'` (data quality issues — clearest "needs attention" signal); (c) count of meetings with `meetings.flag IS NOT NULL` (consent-placement / sources-disagree at meeting level). Lean = **(b)** — most aligned with citizen-facing "what needs attention" framing. Confirm in P3 implementation.
4. **Mobile = Plan A** (lightweight launcher) for v1. Plan B (peek-sheet w/ snap-points + scroll-sync) parked as a v2 tracking issue.
5. **Source Health = new page** (pipeline transparency, linked from the freshness chip). **Public data-debt stays as-is** (citizen-facing item list). Different concepts, different pages.
6. **Category landing = translation pass only.** No layout changes. Inherits new shared components; follow-up issue logged for proper UX revisit later.

---

## Rollout — 5 phases, each its own PR

Mobile (Plan A) responsive CSS ships alongside desktop CSS in each phase — not its own phase.

---

## Phase 1 — Foundation

Touches every page lightly. Lands as one PR.

### Design tokens (`src/docket/web/static/css/styles.css`)
- **Type scale:** hero 64px, section 28px, card 17px, body 15px, eyebrow 10px (mono caps), mono numeric 26px (KPI/NumStat values). Mobile hero drops to 44px.
- **Fonts:** Source Serif 4 (display + body), IBM Plex Sans (UI/labels), JetBrains Mono (code/numeric). All already loaded.
- **Spacing scale:** 4 / 8 / 12 / 16 / 24 / 32 / 48 / 64. No off-scale magic numbers.
- **Colors:** existing OKLCH tokens kept. Tier colors (green/yellow/orange/red) unchanged.

### Masthead (`src/docket/web/templates/partials/masthead.html`)
- One row: brand + city switcher + nav (Overview / Meetings / Legislation / Members) + search.
- The "What is this?" narrative slot is **deleted** — it lives at `/about/`.
- Breadcrumb trail renders below masthead.

### Footer (`src/docket/web/templates/partials/footer.html`)
- Desktop: 4 columns (About / Citizens / Journalists / Trust).
- Mobile: collapses to accordion; first section open by default.

### Mobile chrome
- Bottom tab bar appears `<768px`: 5 fixed tabs — City, Meetings, Topics, Council, More. Glass/blur background. Above sheet, below modal.
- Search collapses to icon (routes to `/search`, no inline input).
- Breakpoint = 768px hard cutoff. No tablet intermediate; tablets get desktop, landscape phones get mobile.

### Files touched
- `src/docket/web/templates/base.html`
- `src/docket/web/templates/partials/masthead.html`, `partials/footer.html`
- `src/docket/web/static/css/styles.css` (tokens)
- `src/docket/web/static/css/layout.css` (masthead, footer, breadcrumb)
- `src/docket/web/static/css/mobile.css` (tab bar, sheet z-indexing, breakpoint)
- New: `src/docket/web/static/js/tabs.js` (active tab state from URL)

### Deleted
- Hero narrative block in `base.html`
- Large city-name banner on city pages (relocates to compressed `CityLead` in P3)

### Verification
- Every page renders with new fonts/spacing.
- No layout breakage on existing templates.
- Mobile tab bar visible at `<768px`, hidden at `≥768px`.

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
- Each renders one `kpi_explainer` with value + label + "show SQL" toggle (hardcoded SQL display string in the partial; *not* live-executed)
- Source/provenance block: adapter class, last sync time, link to source URL

### Mobile (Plan A)
- CityLead h1 drops to 44px Source Serif
- KPI strip becomes horizontal scroll-snap (3 × 130px cards)
- "View source" pill — sticky bottom-right above tab bar (z-index 30) — opens `source_sheet` full-screen with the same content as the desktop rail
- Sheet behavior: full-screen modal, simple open/close, no snap points (Plan A)

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
- Inline KPI strip shows 3 numbers.
- Rail (desktop) shows 4 KPI explainers + provenance.
- Mobile: "View source" pill opens full-screen sheet with same content.
- Freshness chip links to Source Health page (built in P4).

---

## Phase 4 — Detail pages

One PR (or split in two if it grows). None of these pages get a rail per the overview-only rule. All info lays out in the page body.

### 4a. Meeting Detail (`src/docket/web/templates/meeting_detail.html`)
- **Header:** back link → eyebrow (type pill · date · venue) → h1 (title) → NumStat strip (agenda items / recorded votes / dollars)
- **Body:** agenda sections grouped by type (Consent / Resolutions / Ordinances / Hearings / Communications). The split already exists; new section header partial gives each a header + count.
- Per-item vote tally stays as today, restyled with new badges/dollar tiers. Source + confidence shown inline as small mono meta.
- **Conflict callout** appears when `votes.conflict` flag is set OR sources disagree. If the column doesn't exist yet, fall back to comparing minutes_text vs video_ocr counts in-template. Feature-flag off until/unless that data exists.
- Route + view function unchanged (`public.py:208`).

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
- Sheet uses `<dialog>` element if browser support is acceptable, otherwise hand-rolled with `aria-modal="true"` + focus trap + scroll lock.
- `sheet.js` ~50 lines vanilla JS. No external library.
- "View source" pill appears on city overview only (per rail-overview-only rule).
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
