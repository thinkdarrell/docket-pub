# Visual Refactor — Phase 4.1 (Detail Page Restyles) Design & Implementation Plan

> **Goal:** Complete the visual overhaul of the existing detail pages (Meeting, Item, Topic) by applying the Phase 1 design tokens and Phase 2 components. This brings the detail pages into visual alignment with the new homepage and city overview.

**Dependency:** Plan 4-2 must ship first. Plan 4-2 produces three shared primitives this plan consumes: `partials/breadcrumbs.html`, `query.list_related_items_by_topic`, and `query.list_related_items_by_sponsor`.

**Worktree Strategy:** Create a new worktree off `main` (after Plan 4-2 merges) — e.g., `EnterWorktree name: "visual-refactor-p4-1"`.

## 1. Objective
Refactor `meeting_detail.html`, `item_detail.html`, and `topic_detail.html` to remove legacy layout patterns (the old 4-card KPI grid, the feed-row table on topic_detail) and replace them with the new `NumStat` strips, breadcrumbs, and restyled smart-brevity cards.

## 2. Key Files & Context
- **Templates:**
  - `src/docket/web/templates/meeting_detail.html`
  - `src/docket/web/templates/item_detail.html`
  - `src/docket/web/templates/topic_detail.html`
- **Partials (consumed):** `partials/card_smart_brevity.html`, `partials/card_v2_fallback.html`, `partials/num_stat.html`, `partials/breadcrumbs.html` (produced by 4-2).
- **View Functions:** `src/docket/web/public.py` (`meeting_detail`, `item_detail`, `topic_detail`).
- **Service helpers (consumed, produced by 4-2):** `query.list_related_items_by_topic`, `query.list_related_items_by_sponsor`.

## 3. Implementation Steps

### 3.1. Meeting Detail Restyle (`meeting_detail.html`)
- **Header Structure:**
  - Back link to city overview.
  - Eyebrow row: `meeting.meeting_type` pill · date · venue.
  - Main `h1` (title) using `var(--type-hero)`.
  - Replace `.kpi-grid` (lines 19–40) with a `NumStat` strip. **Swap "Topics count" for "Total dollars".** Backend change: pre-compute `SUM(agenda_items.dollars_amount)` in the `meeting_detail()` view function (route-side pre-compute pattern). Pass as `total_dollars`.
- **Body Restructure:**
  - Group agenda sections by **Consent vs Regular only** (matching the existing `is_consent` boolean). Do NOT invent a 5-bucket taxonomy — the data model doesn't support it.
  - Ensure per-item vote tally uses the new restyled badges and dollar tiers.
- **Conflict Callout: DROPPED.** At current scale (77 OCR votes total per CLAUDE.md), genuine conflicts are vanishingly rare. The existing OCR-source warning banner (`meeting_detail.html:71–82`) is sufficient.
- **Source Links & KPIs:**
  - "Source links at bottom" is a **no-op** here — P3 already moved them (lines 301–329).
  - The 4-card KPI explainer stack at the bottom (via `page_sources`, gated on `kpi_stats`) **must remain**. Do not remove during the restyle.

### 3.2. Item Detail Restyle (`item_detail.html`)
- **Header Structure:**
  - Back link.
  - Eyebrow (item number + meeting context).
  - Dollar tier badge aligned to the right (omit when no dollars).
  - Main `h1` (title).
  - Mono byline (sponsor · date · section).
  - Status pill and topic dot.
- **Body Components:**
  - Retain the "Why it matters" block, vote result block, and extracted facts strip.
  - **Additive Feature (Related Items):** Below the facts strip, render two related-items sections via `query.list_related_items_by_topic(item_id, limit=3)` and `query.list_related_items_by_sponsor(item_id, limit=3)`. Each section renders via `partials/card_smart_brevity.html` and is omitted if its list is empty. Topic section appears before sponsor section.
- **Source Links:** Relies on `page_sources` via `base.html`.

### 3.3. Topic Detail Restyle (`topic_detail.html`)
- **Header:** Consume `partials/breadcrumbs.html` (from 4-2) with crumbs `[Home → Topics → {topic_name}]`. Eyebrow (color dot · count), `h1` (topic label). Set `<title>` to "{Topic Label} — Topics — {City}" (city scope) or "{Topic Label} — Topics" (cross-city).
- **Body Layout Shift:** Change the row-table layout to a card grid using `partials/card_smart_brevity.html`. **Verification:** Cross-meeting feed — verify the card variant surfaces meeting context (date and meeting title). If the partial assumes single-meeting context, wrap it or pass a `show_meeting_context=True` flag.
- **Source Links:** Relies on `page_sources` via `base.html`.

## 4. Verification & Testing
- **Visual Review Gates:** Human visual review across mobile (<768px) and desktop breakpoints for all three templates. Ensure typography scale matches P1 guidelines.
- **Test Updates:** Add or update snapshot tests in `tests/web/test_partials_visual_refactor.py`. Add new route tests for the related-items section (assert it's present when seed item has topic/sponsor, absent otherwise).
- **Full pytest suite:** Must stay green (baseline ~1639 tests post-P3).
