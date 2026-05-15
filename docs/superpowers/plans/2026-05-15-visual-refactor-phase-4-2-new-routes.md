# Visual Refactor — Phase 4.2 (New Routes & Cleanup) Design & Implementation Plan

> **Goal:** Introduce Member Detail and Source Health routes, wire existing components, bundle P3 carry-forward cleanup tasks, and produce three shared primitives (breadcrumbs partial + 2 query helpers) consumed by Plan 4-1.

**Worktree Strategy:** Native worktree (e.g., `EnterWorktree name: "visual-refactor-p4-2"`). Worktrees get their own venv (not symlinked to canonical) — pattern from P2a/P2b/P3 holds.

## 1. Objective
Build `/al/<slug>/council/<member_id>/` and `/al/<slug>/source-health/` with high-performance, OOM-resistant queries. Clean up P3 technical debt. Produce shared primitives for Plan 4-1.

## 2. P3 Carry-Forwards (Bundle First — Pre-Cleanup Commit)
Execute these small cleanups in a single commit before the new routes:
- **Hoover `council_type`:** apply via migration 030 (idempotent). See §3.1.
- **Mobile `.hero-title` token rewire:** The `--type-hero-mobile: 44px` token already exists in `styles.css:53`. The `.hero-title` rule in `mobile.css:78–84` currently uses literal `44px !important`. Replace with `var(--type-hero-mobile) !important`. Cosmetic; same computed value.
- **Orphan CSS sweep — SKIPPED.** Grep against templates confirms `rail-*` classes are still consumed by `rail_category.html` (rendered by `category_landing.html`), and `source-sheet-*` classes are still consumed by `bottom_tabs.html`. P3 carry-forwards #4 and #5 are obsolete and should be dropped from the carry-forward list.

## 3. Implementation Steps

### 3.1. Migration 030 — Sponsor Trigram Index + Hoover Fix
- New file: `src/docket/migrations/030_sponsor_trgm_and_hoover.py`.
- Idempotent. `pg_trgm` extension already enabled by migration 013 — **do NOT add `CREATE EXTENSION`**.
- Up:
  ```sql
  CREATE INDEX IF NOT EXISTS idx_agenda_items_sponsor_trgm
    ON agenda_items USING gin (sponsor gin_trgm_ops);
  UPDATE municipalities
    SET metadata = jsonb_set(metadata, '{council_type}', '"Council-manager"')
    WHERE slug = 'hoover';
  ```
- Down: `DROP INDEX IF EXISTS idx_agenda_items_sponsor_trgm;` (Hoover UPDATE intentionally not reversed — no harm to leave correct value).
- Register in `runner.py:MIGRATIONS`.

### 3.2. Member Detail Route (`/al/<slug>/council/<member_id>/`)
- **Backend (`public.py` & `query.py`):**
  - Route: `GET /al/<slug>/council/<member_id>/`.
  - **Cross-city tamper guard:** 404 when `member.municipality_id != municipality.id`. Test this case explicitly.
  - SEO `<title>`: "{Member Name} — {District} — {City}".
  - Reuse `query.get_council_member`, `query.get_member_vote_summary`.
  - **Sponsorship count:** `SELECT COUNT(*) FROM agenda_items WHERE sponsor ILIKE %s` with `%{member_name}%`. Trigram index from migration 030 supports this. Document the substring-collision caveat in the helper docstring.
  - **Voting History Query:** JOIN `member_votes → votes → vote_agenda_items → agenda_items`.
    - Filter `vote_agenda_items.is_active = TRUE` to prevent pulled-from-consent leaks.
    - Select `member_votes.position` (NOT `.vote`).
    - **Cursor pagination** on `(meeting_date DESC, vote_id DESC)`, NOT `LIMIT/OFFSET`. Encode cursor as base64'd `(meeting_date_iso, vote_id)`.
  - **Caching:** Module-level dict cache `_member_cache` (TTL 10 min) mirroring the `_overview_cache` pattern in `public.py`. TTL-only invalidation — manual busts unnecessary since freshness window is short relative to cron cadence.
- **Frontend (`member_detail.html` — new file):**
  - **Header:** Breadcrumbs (`[Home → {City} → Council → {Member}]`) via `partials/breadcrumbs.html`. Avatar (same `cc-portrait` SVG pattern as `council_card.html`), name (`h1`), meta line (district · term). `NumStat` strip: Attendance % / Alignment % / Sponsorship count.
  - **Body:** Voting history table. Filter chips (All / Dissent / Sponsored) trigger server-side re-queries preserving cursor state via standard links (`?filter=dissent&cursor=...`). "Sponsored" filter shows agenda items where `sponsor ILIKE %name%` (separate query — these items have no `position` per-member).
  - **Empty States:**
    - Zero votes for member: render "No recorded roll-call votes yet." (newly elected, term not started).
    - Zero members on parent `/council/` page: existing `council.html` already handles this via its `{% if members %}` block.

### 3.3. Source Health Route (`/al/<slug>/source-health/`)
- **Backend (`public.py` & `query.py`):**
  - Route: `GET /al/<slug>/source-health/`.
  - SEO `<title>`: "Source Health — {City}".
  - Data sources (all from existing schema):
    - **Source:** `meetings.source_url` (most recent meeting's upstream URL — this is the chain-of-custody link).
    - **Adapter:** `municipalities.adapter_class`.
    - **Parser:** `SELECT MAX(m.meeting_date) FROM meetings m JOIN agenda_items a ON a.meeting_id = m.id WHERE m.municipality_id = %s` (last successful agenda parse).
    - **Index:** `query.most_recent_ingest_at(municipality_id)` (already exists at `query.py:3002`).
  - Light caching: same 10-min TTL pattern, optional (page is low-traffic).
- **Frontend (`source_health.html` — new file):**
  - **Header:** Breadcrumbs (`[Home → {City} → Source health]`) via `partials/breadcrumbs.html`. `h1` ("Source health · {City}"). Hero-style freshness chip rendered **inline** (no `size='lg'` variant on `freshness_chip.html` — render directly).
  - **Body:** Pipeline stages (Source → Adapter → Parser → Index). Each stage: state dot (good/warn/bad), last checked time, last success time. Admin-only link to `/admin/errors` if that route exists; otherwise omit (verify in `admin.py` before referencing).
  - **Rate-limit consideration:** Page is uptime-monitor-friendly. No login wall, no heavy queries — fine to leave uncached if cache adds complexity.

### 3.4. Wiring the Links
- **`partials/city_lead.html`:** Wrap the existing inline `city-lead-chip` markup (lines 27–37) in an `<a href="{{ url_for('public.source_health', slug=municipality.slug) }}">` tag. Do NOT switch to `freshness_chip.html` (different markup; would force CSS changes).
- **`partials/council_card.html`:** Convert `<button type="button">` (line 4) to `<a href="{{ url_for('public.member_detail', slug=municipality.slug, member_id=m.id) }}">`. Adjust CSS `.cc` to use link reset styles instead of button resets (remove `appearance: none`, add `text-decoration: none; color: inherit; display: block;`). Wire the "View record →" copy as the link affordance.

### 3.5. Verification & Testing
- **Synthetic-Scale EXPLAIN:** Voting-history JOIN is M:1:N:1. Verify on Railway public DB using the BEGIN/INSERT(synthetic rows to post-backfill scale)/ANALYZE/EXPLAIN/ROLLBACK pattern from memory. Confirm the trigram index is used for sponsorship-count `ILIKE` and the cursor pagination avoids full table scans.
- **Routing:** Smoke tests in `tests/web/test_new_routes_p4.py`:
  - 200 OK for valid `(slug, member_id)` pair.
  - 404 for invalid `member_id`.
  - 404 for cross-city URL tampering (member exists, but `member.municipality_id != municipality.id`).
  - 200 OK for `/al/<slug>/source-health/`.
- **Visual Review Gate:** Human visual review of both new templates across mobile (<768px) and desktop. Source Health is the most uncharted UX — gate carefully.
- **Full pytest:** Must stay green (baseline ~1639 tests post-P3).

## 4. Cleanup of CSS After Wiring
After the `<button>` → `<a>` conversion in `council_card.html`, audit:
- `.cc:focus`, `.cc:active`, `.cc:hover` rules — adjust for anchor semantics.
- Keyboard focus styles — ensure visible focus ring on the new anchor (was likely already present via button focus).

## 5. New Shared Primitives (Produced Here, Consumed by Plan 4-1)

### 5.1. `src/docket/web/templates/partials/breadcrumbs.html`

Drop-in file:

```jinja
{# Breadcrumbs — nav trail. Used on detail/leaf pages to surface hierarchy
   without consuming hero space.
   Spec: docs/superpowers/specs/2026-05-14-visual-refactor-design.md (P4)

   Args (parent scope):
     crumbs (list[dict], required) — ordered list. Each dict:
       label (str, required)
       url   (str | None, optional) — None renders as the current/leaf crumb.
                                     The final crumb is always rendered as
                                     leaf (no link), regardless of url.
#}
{%- if crumbs and crumbs | length > 0 -%}
<nav class="breadcrumbs t-mono" aria-label="Breadcrumb">
  <ol class="breadcrumbs-list">
    {%- for crumb in crumbs -%}
      <li class="breadcrumbs-item">
        {%- if crumb.url and not loop.last -%}
          <a class="breadcrumbs-link" href="{{ crumb.url }}">{{ crumb.label }}</a>
        {%- else -%}
          <span class="breadcrumbs-current" aria-current="page">{{ crumb.label }}</span>
        {%- endif -%}
        {%- if not loop.last -%}
          <span class="breadcrumbs-sep" aria-hidden="true">/</span>
        {%- endif -%}
      </li>
    {%- endfor -%}
  </ol>
</nav>
{%- endif -%}
```

Invocation pattern (parent-scope `{% set %}`):

```jinja
{% set crumbs = [
  {'label': 'Home',              'url': url_for('public.index')},
  {'label': municipality.name,   'url': url_for('public.city_overview', slug=municipality.slug)},
  {'label': 'Council',           'url': url_for('public.city_council', slug=municipality.slug)},
  {'label': member.name,         'url': None},
] %}
{% include 'partials/breadcrumbs.html' %}
```

CSS hooks to add in `layout.css`: `.breadcrumbs`, `.breadcrumbs-list`, `.breadcrumbs-item`, `.breadcrumbs-link`, `.breadcrumbs-current`, `.breadcrumbs-sep`.

### 5.2. `query.list_related_items_by_topic`

```python
def list_related_items_by_topic(
    item_id: int,
    *,
    limit: int = 3,
    same_city_only: bool = True,
) -> list[dict]:
    """Return up to `limit` agenda items sharing the seed item's topic.

    Excludes the seed item itself and any other item from the same meeting
    (to surface cross-meeting context rather than sibling agenda items).
    Filters out withdrawn items, matching `list_agenda_items` semantics.
    Returns [] when the seed has no topic or doesn't exist.

    Column shape matches `list_agenda_items_by_topic` so callers can render
    via `partials/card_smart_brevity.html` without adaptation.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT seed.topic, seed.meeting_id, mt_seed.municipality_id
            FROM agenda_items seed
            JOIN meetings mt_seed ON mt_seed.id = seed.meeting_id
            WHERE seed.id = %s
            """,
            (item_id,),
        )
        seed = cur.fetchone()
        if not seed or not seed["topic"]:
            return []

        where_city = "AND mt.municipality_id = %s" if same_city_only else ""
        params: list = [seed["topic"], item_id, seed["meeting_id"]]
        if same_city_only:
            params.append(seed["municipality_id"])
        params.append(limit)

        cur.execute(
            f"""
            SELECT ai.*,
                   mt.title AS meeting_title,
                   mt.meeting_date,
                   m.name   AS municipality_name,
                   m.slug   AS municipality_slug
            FROM agenda_items ai
            JOIN meetings mt        ON ai.meeting_id = mt.id
            JOIN municipalities m   ON mt.municipality_id = m.id
            WHERE m.active = TRUE
              AND ai.topic = %s
              AND ai.id <> %s
              AND ai.meeting_id <> %s
              AND ai.processing_status::text <> 'withdrawn'
              {where_city}
            ORDER BY mt.meeting_date DESC
            LIMIT %s
            """,
            params,
        )
        return [dict(row) for row in cur.fetchall()]
```

### 5.3. `query.list_related_items_by_sponsor`

```python
def list_related_items_by_sponsor(
    item_id: int,
    *,
    limit: int = 3,
    same_city_only: bool = True,
) -> list[dict]:
    """Return up to `limit` agenda items sharing the seed item's sponsor text.

    Uses ILIKE against `agenda_items.sponsor` (TEXT column, no FK). The
    trigram index added in migration 030 supports the %substring% pattern.
    Excludes the seed item and other items from the same meeting.
    Filters out withdrawn items. Returns [] when the seed has no sponsor.

    Caveat: ILIKE substring matching can catch unrelated names (e.g., 'Smith'
    matches 'Smithson'). Acceptable for a 3-item related list; not safe for
    counts or attribution. Column shape matches `list_agenda_items_by_topic`.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT seed.sponsor, seed.meeting_id, mt_seed.municipality_id
            FROM agenda_items seed
            JOIN meetings mt_seed ON mt_seed.id = seed.meeting_id
            WHERE seed.id = %s
            """,
            (item_id,),
        )
        seed = cur.fetchone()
        if not seed or not seed["sponsor"]:
            return []

        where_city = "AND mt.municipality_id = %s" if same_city_only else ""
        params: list = [f"%{seed['sponsor']}%", item_id, seed["meeting_id"]]
        if same_city_only:
            params.append(seed["municipality_id"])
        params.append(limit)

        cur.execute(
            f"""
            SELECT ai.*,
                   mt.title AS meeting_title,
                   mt.meeting_date,
                   m.name   AS municipality_name,
                   m.slug   AS municipality_slug
            FROM agenda_items ai
            JOIN meetings mt        ON ai.meeting_id = mt.id
            JOIN municipalities m   ON mt.municipality_id = m.id
            WHERE m.active = TRUE
              AND ai.sponsor ILIKE %s
              AND ai.id <> %s
              AND ai.meeting_id <> %s
              AND ai.processing_status::text <> 'withdrawn'
              {where_city}
            ORDER BY mt.meeting_date DESC
            LIMIT %s
            """,
            params,
        )
        return [dict(row) for row in cur.fetchall()]
```

## 6. Sequencing (within this PR)

1. **Pre-cleanup commit** (P3 carry-forwards): migration 030, mobile token rewire, orphan CSS sweep. Run pytest — should stay green.
2. **Shared primitives commit:** breadcrumbs partial + CSS hooks + 2 query helpers (with unit tests against local DB).
3. **Member detail commit:** route + template + cache + cursor pagination + tests.
4. **Source health commit:** route + template + tests.
5. **Wiring commit:** council_card → anchor, city_lead chip → anchor, CSS adjustments.
6. **Human visual review gate.** Address any pivots.
7. **Open PR.** Merge after review.

## 7. Out of Scope (deferred follow-ups)
- Live source-URL reachability probe (mentioned in master spec — defer to post-P4).
- Real-time pipeline-stage telemetry, per-stage failure logs (covered by `/admin/errors` link).
- `freshness_chip.html` refactor to support `size='lg'` variant (defer — inline rendering on source_health is fine for now).
- Migrating `city_lead.html` to consume `freshness_chip.html` partial (deferred — inline chip is fine).
- Search + topic_detail views passing `municipality` to template context for KPI explainer stack (P3 carry-forward #3, not P4 scope).
