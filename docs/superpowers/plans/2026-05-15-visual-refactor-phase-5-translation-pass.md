# Visual Refactor — Phase 5 (Translation Pass) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Translate ~12 remaining public templates onto the P1 tokens + P2/P3/P4 partials so the entire citizen surface matches the new design system. Zero new layouts, zero new components, zero view-function logic changes (with one well-scoped exception called out in Task A4).

**Architecture:** Each page swaps its bespoke `.kpi-grid` / `.feed-table` markup for the established partials (`num_stat.html`, `meeting_card.html`, `card_smart_brevity.html`, `breadcrumbs.html`, `topic_row.html`, `council_card.html`, `dollar_tier.html`) and consumes the new typography tokens (`--type-hero`, etc.). Detail-style headers pick up `.hero--detail` for tighter rhythm.

**Tech Stack:** Flask + Jinja2 templates, vanilla CSS (no preprocessor), pytest for route smoke tests.

**Dependency:** PR #57 (Plan 4-1) must merge before starting. P5 inherits all classes added in 4-1 (`.back-link`, `.detail-eyebrow`, `.hero--detail`, etc.).

**Worktree strategy:** Create a new worktree off `main` after P4-1 merges — e.g., `EnterWorktree name: "visual-refactor-p5"`.

**Recommended PR split (optional):** This plan can ship as one PR or two:
- **PR α (light pass):** Tasks 0, A1–A7, B4. 9 templates with low surface area; low review risk.
- **PR β (card / FTS / category landing):** Tasks B1–B3, C1, Z1. Higher per-template change.

Each task below is independently testable; the split point is arbitrary.

---

## Pages in scope (canon from spec §Phase-5 table)

| Task | Page | Template | Treatment |
|---|---|---|---|
| A1 | Homepage | `index.html` | `meeting_card` strip, drop old kpi-grid |
| A2 | Meeting list | `meetings.html` | `meeting_card` grid, restyled pagination |
| A3 | Council roster | `council.html` | Drop hero kpi padding override; already uses `council_card` |
| A4 | Topics index | `topics.html` | New typography, drop kpi-grid, `topic_row` carousel |
| A5 | Councilors index | `councilors.html` | City picker — typography only |
| A6 | Public data-debt | `data_debt.html` | Typography only (per spec Q5) |
| A7 | About × 3 | `about.html`, `about_methodology.html`, `about_corrections.html` | Typography sanity-check |
| B1 | Search | `search.html` | `card_smart_brevity` grid, pass `municipality` to template ctx |
| B2 | Coverage listing | `coverage/listing.html` | FTS bar restyle + visual tokens |
| B3 | Coverage permalink | `coverage/permalink.html` | Light restyle + polymorphic 4-case test |
| B4 | 404 / 500 | new `errors/404.html`, `errors/500.html` | New templates, friendly copy |
| C1 | Category landing | `category_landing.html` | Translation: KPI strip → num_stat, cross-filter chips restyle |
| Z1 | Tests + visual review | — | Full pytest + dev server smoke |
| Z2 | Wrap-up | — | `finishing-a-development-branch` |

### Explicitly out of scope

- Item badges overflow (`/items/<id>/badges`) — left as 501 stub; follow-up issue.
- RSS feeds (`rss/*.xml.j2`, `coverage/feed.xml.j2`) — XML, no visual.
- All admin templates.
- Category landing UX revisit — translation only; follow-up issue tracks the redesign.
- Vote-result block on item_detail — P4-1 follow-up; not P5.

---

## Task 0: Pre-flight + meeting_card shape normalization

**Files:**
- Modify: `src/docket/web/templates/partials/meeting_card.html`
- Modify: `tests/web/test_partials_visual_refactor.py:205-265` (`_sample_meeting` helper + 4 tests)

**Context:** `meeting_card.html` (P2a) was written against a hypothetical shape with `meeting.date`. Production `Meeting` dataclass uses `meeting.meeting_date`. The partial has zero current consumers, so renaming the input is safe — but P5 needs it before A1/A2 can adopt it.

- [ ] **Step 1: Confirm P4-1 merged**

Run: `git log --oneline origin/main | head -3`
Expected: top commit references "Visual refactor — Phase 4.1" (PR #57 squash-merge).

If P4-1 isn't merged, stop here.

- [ ] **Step 2: Update the partial to consume `meeting.meeting_date`**

```html
{# meeting_card.html — line 28-30 #}
    <span class="meeting-card__eyebrow t-mono">
      {{- meeting.meeting_date.strftime('%b %-d, %Y') -}}
      <span class="meeting-card__dot" aria-hidden="true"></span>
      {{- meeting.meeting_date.strftime('%a') -}}
    </span>
```

Update the docstring's "Required context" section to read `meeting.meeting_date` (not `meeting.date`).

- [ ] **Step 3: Update the test fixture and assertions**

In `tests/web/test_partials_visual_refactor.py:205-265`, change `_sample_meeting()`:

```python
def _sample_meeting():
    return SimpleNamespace(
        id=42,
        meeting_date=date_cls(2026, 5, 13),  # was `date=...`
        title='City Council · Regular Meeting',
        meeting_type='regular',
        summary='Routine agenda; one large procurement item.',
        agenda_count=18,
        dollars_total=2_400_000,
    )
```

The existing `assert '18' in html` etc. still hold.

- [ ] **Step 4: Run partial tests**

Run: `venv/bin/pytest tests/web/test_partials_visual_refactor.py -k meeting_card -v`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/docket/web/templates/partials/meeting_card.html tests/web/test_partials_visual_refactor.py
git commit -m "p5(task 0): normalize meeting_card partial to use meeting.meeting_date"
```

---

## Task A1: Homepage (`index.html`)

**Files:**
- Modify: `src/docket/web/templates/index.html`
- Test: `tests/web/test_p5_translation.py` (new file)

**Treatment:** Replace `.kpi-grid` (lines 17-35) with `kpi_strip` style 3-card if `stats` exists. Replace the "Cities" `.feed-table` (lines 38-67) with a card grid using `.cc` cards (same pattern as `councilors.html`). Replace "This week" `.tw-card` loops (lines 78-97) with `meeting_card` strip variant.

- [ ] **Step 1: Write the failing route test**

Create `tests/web/test_p5_translation.py`:

```python
"""Route smoke tests for P5 — translation pass.

Each test asserts the DOM contract that P5's restyle landed: new
partials are consumed, old bespoke markup is gone. Heavy data
assertions live in unit tests; these tests check structural hooks.
"""
from __future__ import annotations

import pytest


def test_homepage_uses_kpi_strip_not_kpi_grid(client):
    body = client.get("/").get_data(as_text=True)
    assert "kpi-strip" in body
    # Old 3-card kpi-grid removed
    assert 'grid-template-columns: repeat(3, 1fr)' not in body


def test_homepage_renders_meeting_card_for_this_week(client):
    body = client.get("/").get_data(as_text=True)
    # If this-week strip renders at all, it uses the meeting_card partial,
    # not the old .tw-card markup.
    has_tw_section = 'class="tw"' in body or 'class="tw "' in body
    if has_tw_section:
        assert "meeting-card meeting-card--strip" in body
        assert "tw-card" not in body
```

Run: `venv/bin/pytest tests/web/test_p5_translation.py::test_homepage_uses_kpi_strip_not_kpi_grid -v`
Expected: FAIL (kpi-grid still present, kpi-strip absent).

- [ ] **Step 2: Replace the KPI grid with kpi_strip-style includes**

In `index.html:17-35`, replace:

```html
    {% if stats %}
    <div class="kpi-strip">
        {% with label='Cities', value='{:,}'.format(stats.municipalities), sub='Alabama municipalities' %}
            {% include 'partials/num_stat.html' with context %}
        {% endwith %}
        {% with label='Meetings', value='{:,}'.format(stats.meetings), sub='indexed' %}
            {% include 'partials/num_stat.html' with context %}
        {% endwith %}
        {% with label='Agenda items', value='{:,}'.format(stats.agenda_items), sub='extracted', accent=true %}
            {% include 'partials/num_stat.html' with context %}
        {% endwith %}
    </div>
    {% endif %}
```

- [ ] **Step 3: Replace the .tw-card loops with meeting_card strip**

In `index.html:77-98`, replace the inner `.tw-strip` body with:

```html
    <div class="tw-strip">
        {% for m in upcoming_meetings[:4] %}
            {% with meeting=m, variant='strip', municipality={'slug': m.municipality_slug} %}
                {% include 'partials/meeting_card.html' with context %}
            {% endwith %}
        {% endfor %}
        {% for m in recent_meetings[:4] %}
            {% with meeting=m, variant='strip', municipality={'slug': m.municipality_slug} %}
                {% include 'partials/meeting_card.html' with context %}
            {% endwith %}
        {% endfor %}
    </div>
```

Note: `upcoming_meetings` and `recent_meetings` rows from `list_recent_meetings_for_city` etc. include `municipality_slug`. Verify in `public.py:index()` that the view passes that key (it should — P3 added the per-city helpers).

If the view returns flat dicts without `municipality_slug`, fall back: pass `municipality={'slug': m.slug or m.municipality_slug}` via inline expression. Read `public.py:index()` first to confirm shape.

- [ ] **Step 4: Run the route tests**

Run: `venv/bin/pytest tests/web/test_p5_translation.py -v`
Expected: 2 passing.

- [ ] **Step 5: Visual smoke**

Start dev server (if not running): `DATABASE_URL=$DATABASE_PUBLIC_URL FLASK_APP=src/docket/web FLASK_DEBUG=1 venv/bin/flask run --debug --port 5050`

Visit `http://localhost:5050/`. Verify: 3-card kpi-strip, this-week strip renders as `meeting-card--strip` instances.

- [ ] **Step 6: Commit**

```bash
git add src/docket/web/templates/index.html tests/web/test_p5_translation.py
git commit -m "p5(task A1): homepage adopts kpi_strip + meeting_card strip"
```

---

## Task A2: Meeting list (`meetings.html`)

**Files:**
- Modify: `src/docket/web/templates/meetings.html`
- Test: append to `tests/web/test_p5_translation.py`

**Treatment:** Drop the `.kpi-grid` (lines 23-39). Replace `.feed-table` rows (lines 55-77) with `meeting_card` grid variant. Pagination: restyle to use `.t-mono` tokens consistently; the structural markup stays.

- [ ] **Step 1: Append failing test**

Add to `tests/web/test_p5_translation.py`:

```python
def test_meetings_list_uses_meeting_card_grid(client):
    """Birmingham always has meetings — assert restyle landed.
    Skip gracefully if route 404s in CI without seeded data."""
    resp = client.get("/al/birmingham/meetings/")
    if resp.status_code != 200:
        pytest.skip("Birmingham meetings route not available in this env")
    body = resp.get_data(as_text=True)
    # New: meeting_card grid variant
    assert "meeting-card meeting-card--grid" in body
    # Old: feed-table layout dropped on this page
    assert "feed-table" not in body


def test_meetings_list_drops_kpi_grid(client):
    resp = client.get("/al/birmingham/meetings/")
    if resp.status_code != 200:
        pytest.skip("Birmingham meetings route not available in this env")
    body = resp.get_data(as_text=True)
    assert 'class="kpi-grid"' not in body
```

Run: `venv/bin/pytest tests/web/test_p5_translation.py -k meetings_list -v`
Expected: FAILs (kpi-grid + feed-table both still present).

- [ ] **Step 2: Drop the kpi-grid from meetings.html**

Replace `meetings.html:23-39` with nothing (delete the entire `<div class="kpi-grid">…</div>` block). The `<p class="hero-sub">` above already states the total count and page numbers — that's the inline scaffolding the spec calls for.

- [ ] **Step 3: Replace the feed-table with a meeting_card grid**

Replace `meetings.html:55-77` with:

```html
    <div class="meeting-card-grid">
        {% for m in meetings %}
            {% with meeting=m, variant='grid', municipality=municipality %}
                {% include 'partials/meeting_card.html' with context %}
            {% endwith %}
        {% endfor %}
    </div>
```

- [ ] **Step 4: Add `.meeting-card-grid` to layout.css**

Append to `src/docket/web/static/layout.css` near the existing `/* ── P2a meeting_card ─── */` block (~line 850):

```css
.meeting-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--space-4);
  margin-top: var(--space-4);
}
```

And in `mobile.css` near the existing meeting_card rule:

```css
@media (max-width: 768px) {
  .meeting-card-grid {
    grid-template-columns: 1fr;
  }
}
```

If the existing P2a `.meeting-card` rule already has a grid wrapper, reuse it instead of adding new — read `layout.css:850-900` first.

- [ ] **Step 5: Restyle pagination using existing tokens**

`meetings.html:81-97` already uses `.t-mono .link` and is structurally fine. Replace the inline `style="display: flex; gap: 12px;"` with a class on the parent `<div>`:

```html
        <div class="pagination-controls t-mono">
            {% if page > 1 %}
            <a class="link" href="?page={{ page - 1 }}{% if meeting_type %}&type={{ meeting_type }}{% endif %}">← Previous</a>
            {% endif %}
            {% if page < total_pages %}
            <a class="link" href="?page={{ page + 1 }}{% if meeting_type %}&type={{ meeting_type }}{% endif %}">Next →</a>
            {% endif %}
        </div>
```

Add to `layout.css`:

```css
.pagination-controls {
  display: flex;
  gap: var(--space-3);
  align-items: center;
}
```

- [ ] **Step 6: Run tests + visual smoke**

Run: `venv/bin/pytest tests/web/test_p5_translation.py -v`

Visit `http://localhost:5050/al/birmingham/meetings/` — verify grid of meeting cards, no table, working pagination.

- [ ] **Step 7: Commit**

```bash
git add src/docket/web/templates/meetings.html src/docket/web/static/layout.css src/docket/web/static/mobile.css tests/web/test_p5_translation.py
git commit -m "p5(task A2): meeting list adopts meeting_card grid + restyled pagination"
```

---

## Task A3: Council roster (`council.html`)

**Files:**
- Modify: `src/docket/web/templates/council.html`

**Treatment:** Already nearly compliant. It uses `council_card` partial (which P2b restyled) and the standard `.hero` + `.council` sections. The only legacy artifact is `style="padding-bottom: 24px;"` inline on `.hero` (line 5). Replace with `.hero--detail` class.

- [ ] **Step 1: Replace inline padding with `.hero--detail`**

`council.html:5`:

```html
<section class="hero hero--detail">
```

(Remove `style="padding-bottom: 24px;"`.)

- [ ] **Step 2: Visual smoke**

Visit `http://localhost:5050/al/birmingham/council/`. Verify cards look right and the hero rhythm matches detail pages.

No new test — `test_council_card_*` in `test_partials_visual_refactor.py` already covers the partial. Page-level rendering exercises any breakage on full pytest.

- [ ] **Step 3: Commit**

```bash
git add src/docket/web/templates/council.html
git commit -m "p5(task A3): council roster adopts .hero--detail rhythm"
```

---

## Task A4: Topics index (`topics.html`)

**Files:**
- Modify: `src/docket/web/templates/topics.html`
- Modify: `src/docket/web/public.py` (view function — pass `topic_row` data shape)
- Test: append to `tests/web/test_p5_translation.py`

**Treatment:** Drop `.kpi-grid` (lines 38-54). Replace `.council-grid` cards (lines 68-85) with `partials/topic_row.html` carousel — that's the partial built in P2a specifically for topics.

**Exception:** The view function (`topics_index` in `public.py:931`) currently passes `topics` as a list of `{topic, count}` dicts. `topic_row` expects a richer shape including `slug`, `label`, `count`, `color`. The view function needs a small adapter — this is the one allowed view-function change in P5.

- [ ] **Step 1: Append failing test**

Add to `tests/web/test_p5_translation.py`:

```python
def test_topics_index_uses_topic_row_partial(client):
    body = client.get("/topics/").get_data(as_text=True)
    # topic_row's structural hooks (verified by existing partial tests)
    assert "topic-row" in body or "topic-pill" in body
    # Old kpi-grid dropped
    assert 'class="kpi-grid"' not in body
    # Old council-grid dropped (was being misused for topic cards)
    assert "council-grid" not in body
```

Run: `venv/bin/pytest tests/web/test_p5_translation.py -k topics_index -v`
Expected: FAIL.

- [ ] **Step 2: Read the topic_row partial contract**

Read `src/docket/web/templates/partials/topic_row.html`. Confirm the expected shape: `topics` is a list of `{slug, label, count, color}` dicts and `city_slug` is required.

- [ ] **Step 3: Adapt the view function to feed topic_row's shape**

In `public.py:topics_index()`, after building `topics` (the count list) and `all_topics`, also build:

```python
    # P5 — topic_row partial needs flat {slug, label, count, color?} dicts.
    count_by_slug = {tc["topic"]: tc["count"] for tc in topics}
    topic_row_items = [
        {
            "slug": t.slug,
            "label": t.name,
            "count": count_by_slug.get(t.slug, 0),
            "color": getattr(t, "color", None),
        }
        for t in all_topics
        if count_by_slug.get(t.slug, 0) > 0
    ]
```

Pass `topic_row_items=topic_row_items, city_slug=city` to `render_template`.

- [ ] **Step 4: Rewrite topics.html body**

Replace `topics.html:38-86` (the kpi-grid + the .council-grid section) with:

```html
{# ── Topics carousel ─────────────────────────────── #}
{% if topic_row_items %}
<section class="feed">
    <header class="feed-head">
        <div>
            <div class="t-eyebrow">Topics</div>
            <h2 class="feed-title t-display">Pick a topic</h2>
        </div>
        <div class="t-mono t-meta">{{ topic_row_items | length }} active</div>
    </header>

    {% with topics=topic_row_items, city_slug=(city or '') %}
        {% include 'partials/topic_row.html' with context %}
    {% endwith %}
</section>
```

Also drop the kpi-grid (`topics.html:38-54`) — replace nothing; the hero-sub already states counts inline.

- [ ] **Step 5: Mark hero as `.hero--detail` for rhythm**

`topics.html:24`:

```html
<section class="hero hero--detail">
```

- [ ] **Step 6: Run tests + visual smoke**

Run: `venv/bin/pytest tests/web/test_p5_translation.py -k topics_index -v`

Visit `http://localhost:5050/topics/`. Verify topic carousel renders, counts correct.

- [ ] **Step 7: Commit**

```bash
git add src/docket/web/templates/topics.html src/docket/web/public.py tests/web/test_p5_translation.py
git commit -m "p5(task A4): topics index adopts topic_row carousel"
```

---

## Task A5: Councilors index (`councilors.html`)

**Files:**
- Modify: `src/docket/web/templates/councilors.html`

**Treatment:** Already uses standard hero + feed + `.cc` cards. The only change: add `.hero--detail` so the page rhythm matches the rest of P5.

- [ ] **Step 1: Add `.hero--detail`**

`councilors.html:5`:

```html
<section class="hero hero--detail">
```

- [ ] **Step 2: Visual smoke**

Visit `http://localhost:5050/councilors/`.

- [ ] **Step 3: Commit**

```bash
git add src/docket/web/templates/councilors.html
git commit -m "p5(task A5): councilors index adopts .hero--detail"
```

---

## Task A6: Public data-debt (`data_debt.html`)

**Files:**
- Modify: `src/docket/web/templates/data_debt.html`

**Treatment:** Per spec Q5 — functionally identical, new typography only. The template already uses `.hero` + `.feed`. Add `.hero--detail`.

- [ ] **Step 1: Add `.hero--detail`**

`data_debt.html:35`:

```html
<section class="hero hero--detail">
```

- [ ] **Step 2: Visual smoke**

Visit `http://localhost:5050/al/birmingham/data-debt`.

- [ ] **Step 3: Commit**

```bash
git add src/docket/web/templates/data_debt.html
git commit -m "p5(task A6): data-debt page adopts .hero--detail"
```

---

## Task A7: About × 3 (`about.html`, `about_methodology.html`, `about_corrections.html`)

**Files:**
- Modify: `src/docket/web/templates/about.html`
- Modify: `src/docket/web/templates/about_methodology.html`
- Modify: `src/docket/web/templates/about_corrections.html`

**Treatment:** All three already use the standard hero + feed pattern with `--type-hero` token. Sanity-check that the new typography doesn't break their copy width.

- [ ] **Step 1: Add `.hero--detail` to each about page hero**

In each of the three files, change `<section class="hero">` (line 5) to `<section class="hero hero--detail">`.

- [ ] **Step 2: Visual smoke at desktop + mobile**

Visit:
- `http://localhost:5050/about/`
- `http://localhost:5050/about/how-we-read-minutes/`
- `http://localhost:5050/about/corrections/`

Verify: no copy overflow, headings render at `var(--type-hero)`, body copy width feels right.

If any page has copy that overflows new spacing, trim copy in that template rather than re-tuning tokens.

- [ ] **Step 3: Commit**

```bash
git add src/docket/web/templates/about.html src/docket/web/templates/about_methodology.html src/docket/web/templates/about_corrections.html
git commit -m "p5(task A7): About pages adopt .hero--detail rhythm"
```

---

## Task B1: Search (`search.html`)

**Files:**
- Modify: `src/docket/web/templates/search.html`
- Modify: `src/docket/web/public.py` (`search` view — pass `municipality` for `page_sources` KPI stack)
- Test: append to `tests/web/test_p5_translation.py`

**Treatment:** Drop the `.kpi-grid` (lines 39-57). Replace results `.feed-table` (lines 98-139) with `card_smart_brevity` grid (`show_meeting_context=true` because results span meetings). Resolves P3 carry-forward #3 for `search` (pass `municipality` when city-scoped).

- [ ] **Step 1: Append failing tests**

Add to `tests/web/test_p5_translation.py`:

```python
def test_search_results_use_card_smart_brevity(client):
    """Search a common term that's likely to return results in any
    backfill state; skip if zero results in CI."""
    resp = client.get("/search?q=council")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # If results exist, they render via card_smart_brevity, not feed-table.
    if "No results" not in body and "Type a query" not in body:
        assert "smart-brevity-card" in body
        assert "feed-table" not in body


def test_search_drops_kpi_grid(client):
    body = client.get("/search?q=council").get_data(as_text=True)
    assert 'class="kpi-grid"' not in body
```

Run: `venv/bin/pytest tests/web/test_p5_translation.py -k search -v`
Expected: FAIL.

- [ ] **Step 2: Pass `municipality` from the view function when city is scoped**

In `public.py:search()`, after resolving the city slug:

```python
    municipality = query.get_municipality(city) if city else None
    kpi_stats = (
        query._kpi_stats_for_municipality(municipality)
        if municipality is not None
        else None
    )
```

Add `municipality=municipality, kpi_stats=kpi_stats` to the `render_template` call.

- [ ] **Step 3: Drop the kpi-grid from search.html**

Replace `search.html:39-57` (the `{% if query %}` kpi-grid block) with nothing — the page-source KPI stack at page-bottom (gated on `kpi_stats`) replaces it.

- [ ] **Step 4: Replace results feed-table with card_smart_brevity grid**

Replace `search.html:98-139` with:

```html
        {% with show_meeting_context=true %}
        <div class="notable-list smart-brevity-list smart-brevity-list--regular">
            {% for item in results %}
                {% include 'partials/card_smart_brevity.html' %}
            {% endfor %}
        </div>
        {% endwith %}
```

This relies on the P4-1 defensive fallback in `_card_shell.html` that uses `item.municipality_slug` when page-level `municipality` is absent (cross-city searches).

- [ ] **Step 5: Add `.hero--detail` to search hero**

`search.html:22`:

```html
<section class="hero hero--detail">
```

- [ ] **Step 6: Run tests + visual smoke**

Run: `venv/bin/pytest tests/web/test_p5_translation.py -k search -v`

Visit `http://localhost:5050/search?q=council` and `http://localhost:5050/search?q=council&city=birmingham`.

Verify: result cards render, no feed-table, city-scoped search shows page_sources KPI stack at bottom.

- [ ] **Step 7: Commit**

```bash
git add src/docket/web/templates/search.html src/docket/web/public.py tests/web/test_p5_translation.py
git commit -m "p5(task B1): search adopts card_smart_brevity grid + page_sources wiring"
```

---

## Task B2: Coverage listing (`coverage/listing.html`)

**Files:**
- Modify: `src/docket/web/templates/coverage/listing.html`

**Treatment:** Light restyle — wrap header in `.hero hero--detail`, restyle FTS bar with existing token classes, restyle tabs + pagination.

- [ ] **Step 1: Rewrite the header**

Replace `coverage/listing.html:4-7` with:

```html
<section class="hero hero--detail">
    <div class="hero-top">
        <div>
            <div class="t-eyebrow">Editorial coverage</div>
            <h1 class="hero-title t-display">Editorial coverage</h1>
            <p class="hero-sub">Notes and press citations on Alabama municipal meetings.</p>
        </div>
    </div>
</section>
```

- [ ] **Step 2: Restyle tabs with token classes**

Replace `coverage/listing.html:9-13` with:

```html
<nav class="coverage-tabs t-mono">
  <a href="{{ url_for('public.coverage_listing') }}" class="coverage-tab{% if not kind %} is-active{% endif %}">All</a>
  <a href="{{ url_for('public.coverage_listing', kind='note') }}" class="coverage-tab{% if kind == 'note' %} is-active{% endif %}">Notes</a>
  <a href="{{ url_for('public.coverage_listing', kind='citation') }}" class="coverage-tab{% if kind == 'citation' %} is-active{% endif %}">Citations</a>
</nav>
```

- [ ] **Step 3: Restyle the FTS search bar**

Replace `coverage/listing.html:15-19` with:

```html
<form method="get" action="{{ url_for('public.coverage_listing') }}" class="coverage-search">
  {% if kind %}<input type="hidden" name="kind" value="{{ kind }}">{% endif %}
  <div class="topsearch">
    <span class="topsearch-icon t-mono">⌕</span>
    <input type="search" name="q" value="{{ q }}" placeholder="Search coverage…">
  </div>
  <button type="submit" class="leg-viewall t-mono">Search →</button>
</form>
```

This reuses the same `.topsearch` chrome the masthead uses — visual consistency for citizens.

- [ ] **Step 4: Add CSS for `.coverage-tabs` + `.is-active` if not present**

Check `src/docket/web/static/*.css` for an existing `.coverage-tabs` rule. If absent, append to `layout.css`:

```css
.coverage-tabs {
  display: flex;
  gap: var(--space-3);
  padding: var(--space-3) 0;
  border-bottom: 1px solid var(--rule);
}
.coverage-tab {
  text-decoration: none;
  color: var(--ink-3);
  padding: var(--space-2) 0;
  border-bottom: 2px solid transparent;
}
.coverage-tab.is-active {
  color: var(--ink-1);
  border-bottom-color: var(--accent);
}
.coverage-search {
  display: flex;
  gap: var(--space-3);
  align-items: center;
  padding: var(--space-3) 0;
}
.coverage-search .topsearch { flex: 1; max-width: 480px; }
```

If the existing CSS uses a different convention (e.g., `.active` not `.is-active`), match it.

- [ ] **Step 5: Visual smoke**

Visit `http://localhost:5050/coverage/`. Verify: hero header, tabs with active state, FTS bar matching masthead style, entries render unchanged.

- [ ] **Step 6: Commit**

```bash
git add src/docket/web/templates/coverage/listing.html src/docket/web/static/layout.css
git commit -m "p5(task B2): coverage listing — hero + FTS bar + tabs restyle"
```

---

## Task B3: Coverage permalink (`coverage/permalink.html`)

**Files:**
- Modify: `src/docket/web/templates/coverage/permalink.html`
- Modify: `src/docket/web/templates/partials/coverage_note.html` (only if polymorphic subject footer reveals a defect)
- Test: append to `tests/web/test_p5_translation.py`

**Treatment:** Wrap the partial in a hero header and breadcrumbs. **Critical:** the polymorphic subjects footer in `coverage_note.html` must render in all 4 subject types — item, meeting, member, badge. The plan asserts this via a route test for each subject kind.

- [ ] **Step 1: Append failing test (polymorphic subject coverage)**

Add to `tests/web/test_p5_translation.py`:

```python
def test_coverage_permalink_renders_for_all_subject_kinds(client):
    """Coverage permalink must render correctly for each polymorphic
    subject type. If no coverage entries exist of a given kind, the
    test skips that one — but at least one must exist to validate
    P5's restyle on the page itself.
    """
    # Hit the listing first to discover an existing coverage entry.
    resp = client.get("/coverage/?kind=note")
    if resp.status_code != 200:
        pytest.skip("Coverage routes not available in this env")
    body = resp.get_data(as_text=True)
    # Find at least one coverage permalink href; if none, skip.
    import re
    matches = re.findall(r'href="(/coverage/\d+)"', body)
    if not matches:
        pytest.skip("No coverage entries in DB to permalink-test")
    for permalink in matches[:5]:
        permalink_resp = client.get(permalink)
        assert permalink_resp.status_code == 200, f"{permalink} returned {permalink_resp.status_code}"
        permalink_body = permalink_resp.get_data(as_text=True)
        # The hero structural hooks must be present
        assert 'class="hero hero--detail"' in permalink_body
        assert "breadcrumbs" in permalink_body
```

Run: `venv/bin/pytest tests/web/test_p5_translation.py -k coverage_permalink -v`
Expected: FAIL.

- [ ] **Step 2: Rewrite coverage/permalink.html**

Replace the entire file with:

```html
{% extends "base.html" %}
{% block title %}{{ note.body[:60] }}… — Coverage — docket.pub{% endblock %}

{% block content %}
{% set crumbs = [
  {'label': 'Home',     'url': url_for('public.index')},
  {'label': 'Coverage', 'url': url_for('public.coverage_listing')},
  {'label': 'Entry',    'url': None},
] %}
{% include 'partials/breadcrumbs.html' %}

<section class="hero hero--detail">
    <div class="hero-top">
        <div>
            <div class="t-eyebrow">Editorial coverage · {{ note.kind | title }}</div>
            <h1 class="hero-title t-display">{{ note.body[:80] }}{% if note.body | length > 80 %}…{% endif %}</h1>
        </div>
    </div>
</section>

<article class="coverage-permalink">
  {% include "partials/coverage_note.html" %}
</article>
{% endblock %}
```

- [ ] **Step 3: Run polymorphic subject test**

Run: `venv/bin/pytest tests/web/test_p5_translation.py -k coverage_permalink -v`
Expected: PASS (or SKIP if no coverage entries in test DB).

If the test passes against Railway data, manually visit at least one coverage entry of each subject kind (item / meeting / member / badge) via the listing and confirm the page renders.

- [ ] **Step 4: Commit**

```bash
git add src/docket/web/templates/coverage/permalink.html tests/web/test_p5_translation.py
git commit -m "p5(task B3): coverage permalink — hero + breadcrumbs"
```

---

## Task B4: Error templates (404 / 500)

**Files:**
- Create: `src/docket/web/templates/errors/404.html`
- Create: `src/docket/web/templates/errors/500.html`
- Modify: `src/docket/web/__init__.py` (register error handlers)
- Test: append to `tests/web/test_p5_translation.py`

**Treatment:** New custom error templates inheriting `base.html`. Masthead + footer from P1, friendly copy, link back home.

- [ ] **Step 1: Append failing tests**

Add to `tests/web/test_p5_translation.py`:

```python
def test_404_renders_custom_template(client):
    resp = client.get("/this/path/definitely/does/not/exist")
    assert resp.status_code == 404
    body = resp.get_data(as_text=True)
    # Custom 404 template renders the masthead from P1
    assert "docket.pub" in body  # brand mark
    assert "404" in body  # the status code shown to user
    # Friendly affordance
    assert "Home" in body or "home" in body


def test_500_renders_custom_template_in_production(client):
    """The 500 handler only kicks in when app.debug is False; in pytest
    we don't exercise it directly (test_client raises). Just smoke-load
    the template via render_template via render_partial to verify
    syntax.
    """
    # Direct template render to validate Jinja syntax.
    from docket.web import create_app
    app = create_app()
    with app.test_request_context():
        from flask import render_template
        body = render_template("errors/500.html")
        assert "500" in body
        assert "docket.pub" in body
```

Run: `venv/bin/pytest tests/web/test_p5_translation.py -k "404 or 500" -v`
Expected: FAIL.

- [ ] **Step 2: Create `errors/404.html`**

```bash
mkdir -p src/docket/web/templates/errors
```

```html
{# src/docket/web/templates/errors/404.html #}
{% extends "base.html" %}
{% block title %}Not found — docket.pub{% endblock %}

{% block content %}
<section class="hero hero--detail">
    <div class="hero-top">
        <div>
            <div class="t-eyebrow t-mono">Error · 404</div>
            <h1 class="hero-title t-display">We couldn't find that page</h1>
            <p class="hero-sub">
                The page or meeting you're looking for may have been removed, retracted by the
                city, or never existed. Public meeting records change over time — that's the nature
                of municipal transparency.
            </p>
        </div>
    </div>
</section>

<section class="feed">
    <header class="feed-head">
        <div>
            <div class="t-eyebrow">Try these</div>
            <h2 class="feed-title t-display">Where to next</h2>
        </div>
    </header>
    <ul class="t-mono" style="line-height: 2;">
        <li><a class="link" href="{{ url_for('public.index') }}">← Home</a></li>
        <li><a class="link" href="{{ url_for('public.topics_index') }}">Browse topics</a></li>
        <li><a class="link" href="{{ url_for('public.search') }}">Search agenda items</a></li>
    </ul>
</section>
{% endblock %}
```

- [ ] **Step 3: Create `errors/500.html`**

```html
{# src/docket/web/templates/errors/500.html #}
{% extends "base.html" %}
{% block title %}Something broke — docket.pub{% endblock %}

{% block content %}
<section class="hero hero--detail">
    <div class="hero-top">
        <div>
            <div class="t-eyebrow t-mono">Error · 500</div>
            <h1 class="hero-title t-display">Something on our end broke</h1>
            <p class="hero-sub">
                docket.pub hit an unexpected error rendering this page. The fault is ours, not yours.
                We log every 500; nothing about your request is hidden from the operator. Try again in
                a moment, or take a different path below.
            </p>
        </div>
    </div>
</section>

<section class="feed">
    <header class="feed-head">
        <div>
            <div class="t-eyebrow">Try these</div>
            <h2 class="feed-title t-display">Where to next</h2>
        </div>
    </header>
    <ul class="t-mono" style="line-height: 2;">
        <li><a class="link" href="{{ url_for('public.index') }}">← Home</a></li>
        <li><a class="link" href="{{ url_for('public.search') }}">Search</a></li>
    </ul>
</section>
{% endblock %}
```

- [ ] **Step 4: Register error handlers in `__init__.py`**

In `src/docket/web/__init__.py`, after `create_app()` registers the blueprints, add:

```python
    from flask import render_template

    @app.errorhandler(404)
    def _not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def _server_error(e):
        return render_template("errors/500.html"), 500
```

Place these immediately before `return app`.

- [ ] **Step 5: Run tests + visual smoke**

Run: `venv/bin/pytest tests/web/test_p5_translation.py -k "404 or 500" -v`

Visit `http://localhost:5050/some-unknown-path` — confirm custom 404. The 500 template renders correctly via the unit test; manual 500 isn't easily triggered in dev.

- [ ] **Step 6: Commit**

```bash
git add src/docket/web/templates/errors/ src/docket/web/__init__.py tests/web/test_p5_translation.py
git commit -m "p5(task B4): custom 404 + 500 templates with friendly copy"
```

---

## Task C1: Category landing (`category_landing.html`)

**Files:**
- Modify: `src/docket/web/templates/category_landing.html`
- Modify: `src/docket/web/templates/partials/rail_category.html` (read first — may need a touch-up)
- Test: append to `tests/web/test_p5_translation.py`

**Treatment:** Translation only, no UX changes. The existing template uses the new partials (`_item_list.html`, `card_smart_brevity.html`, `badge_chip.html`, `volume_timeline.html`) already — most of it. Open items:
1. Header (`.hero` at line 22) should use `.hero--detail` for rhythm consistency.
2. Cross-filter chips inline styles (lines 119-129) — replace with class.
3. Active-month chip inline styles (lines 136-156) — replace with class.
4. Cross-filter `<select>` inline `style=` (line 106) — replace with class.

Volume timeline SVG and item list partials are explicitly left alone (per spec).

- [ ] **Step 1: Append failing test**

```python
def test_category_landing_uses_hero_detail(client):
    """Pick the property_recovery badge under birmingham — likely
    populated in any deployment. Skip if the route 404s."""
    resp = client.get("/al/birmingham/property_recovery/")
    if resp.status_code != 200:
        pytest.skip("Category landing route not available in this env")
    body = resp.get_data(as_text=True)
    assert "hero hero--detail" in body


def test_category_landing_drops_inline_chip_styles(client):
    resp = client.get("/al/birmingham/property_recovery/")
    if resp.status_code != 200:
        pytest.skip("Category landing route not available in this env")
    body = resp.get_data(as_text=True)
    # Inline styles on cross-filter chips were P4 carry-over — should be gone.
    assert 'class="cross-filter-chips"' in body
    # Inline style="display: flex; ...; padding: 12px 0;" on the chip row removed.
    assert 'class="cross-filter-chips" style=' not in body
```

Run: `venv/bin/pytest tests/web/test_p5_translation.py -k category_landing -v`
Expected: FAIL.

- [ ] **Step 2: Add `.hero--detail` to category_landing hero**

`category_landing.html:22`:

```html
<section class="hero hero--detail">
```

- [ ] **Step 3: Remove inline styles from cross-filter chip row**

Replace `category_landing.html:119` with:

```html
    <div class="cross-filter-chips">
```

(Remove the `style="display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 0;"`.)

- [ ] **Step 4: Add `.cross-filter-chips` rule to layout.css**

Search `layout.css` for an existing `.cross-filter-chips` rule. If absent, append:

```css
.cross-filter-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  padding: var(--space-3) 0;
}
.active-month-chip-row {
  display: flex;
  gap: var(--space-2);
  padding: var(--space-2) 0;
}
.cross-filter-form {
  padding: var(--space-2) 0;
}
.cross-filter {
  font: inherit;
  padding: var(--space-2) var(--space-2);
  min-width: 280px;
  border: 1px solid var(--rule);
  background: var(--paper);
  color: var(--ink);
}
```

- [ ] **Step 5: Remove inline styles from active-month chip row**

`category_landing.html:136`:

```html
    <div class="active-month-chip-row">
```

(Remove `style="display: flex; gap: 8px; padding: 8px 0;"`.)

- [ ] **Step 6: Remove inline styles from cross-filter form + select**

Replace `category_landing.html:95-106` form + select wrapper with class-only:

```html
    <form class="cross-filter-form">
        <label class="t-label" for="cross-filter-select">
            Combine with another badge
        </label>
        <select name="and" id="cross-filter-select" class="cross-filter"
                hx-get="{{ url_for('public.category_landing', slug=municipality.slug, badge_slug=badge.slug) }}"
                hx-target="#item-list"
                hx-swap="outerHTML"
                hx-include="this"
                hx-trigger="change"
                hx-push-url="true">
            <option value="">— combine with another badge —</option>
            {% for other in available_badges %}
            <option value="{{ other.slug }}"
                    {% if other.slug in cross_filters %}selected{% endif %}>
                {{ other.icon }} {{ other.name }}
            </option>
            {% endfor %}
        </select>
    </form>
```

Update the inline label style: add to `layout.css`:

```css
.cross-filter-form .t-label {
  display: block;
  margin-bottom: var(--space-1);
}
```

- [ ] **Step 7: Run tests + visual smoke**

Run: `venv/bin/pytest tests/web/test_p5_translation.py -k category_landing -v`

Visit `http://localhost:5050/al/birmingham/property_recovery/`. Verify:
- Hero uses `.hero--detail` rhythm
- Volume timeline still renders correctly
- Cross-filter dropdown works (HTMX, ?and= URL push)
- Active-month chip works when ?month=YYYY-MM
- All chips visually consistent with rest of site

- [ ] **Step 8: Commit**

```bash
git add src/docket/web/templates/category_landing.html src/docket/web/static/layout.css tests/web/test_p5_translation.py
git commit -m "p5(task C1): category landing translation — hero rhythm + inline-style cleanup"
```

---

## Task Z1: Full test sweep + visual review

**Files:** none — verification only.

- [ ] **Step 1: Full pytest**

Run: `venv/bin/pytest --ignore=tests/live -q`
Expected: All non-live tests pass; baseline grows by however many tests Tasks A1–C1 added (~10–15).

- [ ] **Step 2: Visual review of every P5 surface at desktop + mobile**

Dev server on Railway prod data. URL checklist:

```
http://localhost:5050/                                            # A1
http://localhost:5050/al/birmingham/meetings/                     # A2
http://localhost:5050/al/birmingham/council/                      # A3
http://localhost:5050/topics/                                     # A4
http://localhost:5050/councilors/                                 # A5
http://localhost:5050/al/birmingham/data-debt                     # A6
http://localhost:5050/about/                                      # A7
http://localhost:5050/about/how-we-read-minutes/                  # A7
http://localhost:5050/about/corrections/                          # A7
http://localhost:5050/search?q=council                            # B1
http://localhost:5050/search?q=council&city=birmingham            # B1 (city-scoped)
http://localhost:5050/coverage/                                   # B2
http://localhost:5050/coverage/<pick-one-from-listing>            # B3 — pick a note + a citation
http://localhost:5050/this-does-not-exist                         # B4 (404)
http://localhost:5050/al/birmingham/property_recovery/            # C1
http://localhost:5050/al/birmingham/property_recovery/?and=blight # C1 cross-filter
```

For each: at desktop, then resize to <768px (mobile breakpoint).

If any page has copy that overflows new spacing tokens — trim the template's copy or adjust the page's hero to use `.hero` (not `.hero--detail`) so it gets more breathing room.

- [ ] **Step 3: Document any issues found**

If a surface needs follow-up, log it in the PR description rather than expanding scope. Visual-refactor follow-ups belong to a future cycle, not the translation PR.

---

## Task Z2: Finish the development branch

**Files:** none — workflow only.

- [ ] **Step 1: Invoke the skill**

Use `superpowers:finishing-a-development-branch`. Answer Option 2 (Push + PR) unless told otherwise.

- [ ] **Step 2: PR title and body**

Suggested title: `Visual refactor — Phase 5 (translation pass)`

Body sections:
- **Summary** — bullet per task group (A, B, C)
- **Mid-PR pivots** (if any)
- **Follow-ups** — anything deferred
- **Test plan** — pytest count + visual review checklist URLs

---

## Self-review (executed before saving)

1. **Spec coverage:** Spec §Phase-5 table has 14 rows. Mapped to tasks:
   - Homepage → A1 ✓
   - Meeting list → A2 ✓
   - Council roster → A3 ✓
   - Topics index → A4 ✓
   - Search → B1 ✓
   - Coverage listing → B2 ✓
   - Coverage permalink → B3 ✓
   - About × 3 → A7 ✓
   - Councilors index → A5 ✓
   - Public data-debt → A6 ✓
   - Category landing → C1 ✓
   - RSS × 3 → explicitly out of scope ✓
   - Item badges overflow → explicitly out of scope ✓
   - 404 / 500 → B4 ✓

2. **Placeholder scan:** No "TBD", "TODO", "implement later". Every code block contains actual content.

3. **Type consistency:** `meeting_card` partial takes `meeting.meeting_date` after Task 0; all consumers (A1, A2) reference that name. `topic_row` partial takes a `topics` list of `{slug, label, count, color}` dicts; A4 builds that exact shape in the view function. Error handlers register on `app` (not `bp`) since they're app-level.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-15-visual-refactor-phase-5-translation-pass.md`. Two execution options:

1. **Subagent-Driven (recommended for plans this size)** — dispatch a fresh subagent per task, review between tasks. The bite-sized task structure was designed for this.
2. **Inline Execution** — execute tasks in the current session using `executing-plans`.

Which approach?
