# Modularity Cleanup — Vertical Slice Architecture for docket.pub

**Date:** 2026-05-13
**Status:** Design (spec). Implementation queued behind two pre-flight items (see "Interaction with in-flight work").
**Pattern:** Vertical Slice Architecture (VSA)
**Scope:** Structural refactor of `src/docket/web/`, `src/docket/services/`, and templates. Backfill-safe boundary on `src/docket/ai/` and the pipeline layer.

---

## Motivation

docket.pub's lower stack (adapters, enrichment, models, migrations, ai pipeline stages) is already feature-modular and works well. The upper stack — citizen-facing pages and admin tooling — is organized by Flask convention (routes in one file, services in one file) and has grown into a layout where modifying a single page requires editing 4-5 directories.

Concrete smells in the current code:

- `src/docket/services/query.py` is **2,322 lines** with 45 top-level definitions spanning meetings, votes, agenda items, council members, search, topics, badges, and category-landing visualizations.
- `src/docket/web/public.py` is **828 lines** containing 22 routes for 12 distinct citizen-facing surfaces.
- `src/docket/web/admin.py` is **1,098 lines** containing 24 routes across 8 distinct admin surfaces.
- `src/docket/services/conflict_resolution.py` imports from `src/docket/ai/` — a layering inversion, since `ai/` already (correctly) imports from `services/`.
- `src/docket/web/filters.py` is **613 lines** of mixed Jinja filters with no topical grouping.

This design adopts **Vertical Slice Architecture (VSA)**: organize by business function (page/feature), not technical role (route, service, template). Each citizen-facing page becomes a self-contained folder owning its route, local query, template, and tests. Shared rendering lives in a named `components/` layer. Shared data lives in a slimmed `services/` layer split by domain noun.

### Guiding principle — locality of reasoning

A developer (or AI agent) should be able to understand, modify, and test one feature without traversing the entire repo. To change how the meeting detail page works, the answer to "where do I go?" should be **one folder**. If changing a page forces edits to two feature folders, the contract is broken — extract the shared piece up.

### The three architectural rules

1. **Pages own composition.** A feature folder owns its route, its template, its page-specific query functions, and its tests. To swap a page, you edit one folder.
2. **Components own rendering.** Anything that renders the same kind of data on more than one surface lives in `components/`. To change a card style or rail body everywhere, you edit one file.
3. **Services own data.** Canonical "what data exists" is `services/query/<topic>.py`, plus write/orchestration services (`ingest`, `enrichment`, `badges_writer`, etc.). Features import from services; services never import from features.

### Secondary benefit — AI-collaboration friendliness

VSA folders are excellent for AI-assisted development. Pointing Claude Code at `features/public/meeting_detail/` provides everything-in-one-folder context (route + query + template + tests) without scattering attention. This is a real ergonomic win given how heavily this project uses Claude for implementation.

---

## Target structure

```
src/docket/
  features/                            ← NEW. One folder per page/feature.
    public/                            ←   Citizen-facing (12 features, 22 routes)
      home/
      city_overview/
      meetings_list/
      meeting_detail/
      item_detail/
      category_landing/
      topics/
      search/
      council/
      data_debt/
      rss/
    admin/                             ←   Admin-facing (8 features, 24 routes)
      members/
      data_debt/
      errors_queue/
      source_security/
      calibration/
      ai_dashboard/
      badges/
      review_conflicts/

  components/                          ← NEW. Shared rendering (replaces templates/partials/).
    layouts/
      base.html
      admin_base.html
      rss_base.xml.j2
    cards/
      smart_brevity.html               ← 6 variants via macro parameters
      council.html
      item.html
      meeting.html
    badges/
      chip.html
      list.html
    votes/
      vote_block.html
      consent_block.html
      member_vote_row.html
    source/
      badge.html
      discrepancy.html
    rail/
      member_body.html
      meeting_body.html
      default_body.html
    masthead.html
    footer.html
    dollar_tier.html

  services/                            ← SLIMMED.
    query/                             ←   Was services/query.py (2,322 lines).
      __init__.py
      cities.py
      meetings.py
      agenda_items.py
      votes.py
      council.py
      badges.py
      search.py
      topics.py
      stats.py
      data_quality.py
    ingest.py                          ←   Unchanged
    enrichment.py                      ←   Unchanged
    minutes_adoption.py                ←   Unchanged
    maintenance.py                     ←   Unchanged
    badges_writer.py                   ←   Renamed from services/badges.py
    calibration.py                     ←   Unchanged
    # conflict_resolution.py removed   ←   Moved to ai/conflict_resolution.py

  web/                                 ← KEPT. Glue + cross-cutting.
    __init__.py                        ←   App factory; registers feature blueprints
    auth.py                            ←   /admin/login, /admin/logout, login_required
    filters/                           ←   Was web/filters.py (613 lines).
      __init__.py
      dates.py
      money.py
      badges.py
      sources.py
      text.py
    create_admin.py
    static/                            ←   CSS / fonts / JS unchanged

  # Untouched — backfill-safe boundary:
  ai/                                  ← (Gains ai/conflict_resolution.py from above)
  adapters/
  models/
  migrations/
  worker/
  analysis/
  enrichment/
  rosters/
```

---

## Feature inventory

### Public features (12 features, 22 routes)

| Feature folder | Routes |
|---|---|
| `home/` | `/`, `/about/`, `/about/how-we-read-minutes/`, `/about/corrections/` |
| `city_overview/` | `/al/<slug>/`, `/al/<slug>/_rail/default` |
| `meetings_list/` | `/al/<slug>/meetings/` |
| `meeting_detail/` | `/al/<slug>/meetings/<id>/`, `/al/<slug>/_rail/meeting/<id>` |
| `item_detail/` | `/al/<slug>/items/<id>/`, `/items/<id>/badges` |
| `category_landing/` | `/al/<slug>/<badge_slug>/` |
| `topics/` | `/topics/`, `/topics/<topic>/` |
| `search/` | `/search` |
| `council/` | `/al/<slug>/council/`, `/councilors/`, `/al/<slug>/_rail/member/<id>` |
| `data_debt/` (public) | `/al/<city>/data-debt`, `/al/<city>/data-debt.rss` |
| `rss/` | `/al/<city>/upcoming-hearings.rss` |

### Admin features (8 features, 24 routes)

| Feature folder | Routes |
|---|---|
| `members/` | `/admin/members/`, `/admin/members/add`, `/admin/members/<id>/edit`, `/admin/members/<id>/deactivate` |
| `data_debt/` (admin) | `/admin/data-debt/` |
| `errors_queue/` | `/admin/errors`, `/admin/errors/<id>/retry`, `/admin/errors/<id>/escalate` |
| `source_security/` | `/admin/source-security/refresh` |
| `calibration/` | `/admin/calibration` |
| `ai_dashboard/` | `/admin/ai` |
| `badges/` | `/admin/badges/audit`, `/admin/badges/items/<id>`, `/admin/badges/<id>/add/<slug>`, `/admin/badges/<id>/add`, `/admin/badges/<id>/remove/<slug>` |
| `review_conflicts/` | `/admin/review/conflicts` + 6 HTMX form/POST pairs |

### Three rules embedded in the mapping

1. **HTMX partial endpoints live with their owner feature.** `_rail/meeting/<id>` belongs to `meeting_detail/`, not a separate `rail/` feature.
2. **Same domain across personas = sibling folders.** `features/public/data_debt/` and `features/admin/data_debt/` are siblings — they share a service module but each owns its own route + template.
3. **Multi-route features stay together.** `review_conflicts/` is 7 routes that form one cohesive workflow.

---

## Feature contract

### What's IN a feature folder

```
features/public/meeting_detail/
  __init__.py              ← exports the blueprint
  route.py                 ← Flask blueprint + route handlers (thin)
  query.py                 ← optional: read functions used only by this feature
  templates/
    meeting_detail.html
    _rail.html             ← optional: HTMX partial template
  tests/
    test_route.py
    test_query.py
```

**Required:** `__init__.py`, `route.py`, `templates/<feature>.html`, `tests/test_route.py`.
**Optional:** `query.py`, `forms.py`, additional template partials, helper modules.

### What's NOT in a feature folder

| Lives elsewhere | Where |
|---|---|
| Schema / migrations | `migrations/` |
| Pipeline logic (AI, OCR, vote matching) | `ai/`, `analysis/`, `worker/`, `adapters/` |
| Data writes for cross-feature state | `services/ingest.py`, `services/enrichment.py`, etc. |
| Query functions used by 2+ features | `services/query/<topic>.py` |
| Shared rendering (cards, badges, rail bodies) | `components/` |
| Shared base layouts | `components/layouts/` |
| Auth | `web/auth.py` |
| Jinja filters | `web/filters/` |
| CSS / JS / fonts | `web/static/` |

### Import rules (one-way dependency graph)

```
features  →  services      (allowed)
features  →  ai            (allowed; e.g. admin/review_conflicts → ai/conflict_resolution)
features  →  components    (template imports only)
features  →  web/filters, web/auth   (allowed)
services  →  models, db, adapters, enrichment, analysis    (allowed)
services  ↛  features      (forbidden)
services  ↛  ai            (forbidden; current violation in conflict_resolution.py is fixed by moving that file to ai/)
ai        →  services      (allowed)
adapters  →  models        (allowed)
models    →  (nothing)
```

**Hard rules:**
1. A feature never imports another feature. If sharing is needed, the shared piece moves to `services/` or `components/`.
2. `services/` never imports from `features/`.
3. Components never import Python — they only consume data passed in.

### Database transactions

**Services own commits; features own composition.** A feature's route handler calls one service function per logical action. The service function manages its own database transaction internally via `docket.db.db_cursor()` (commits on context exit; rolls back on exception). The feature does not see or manage connections, cursors, or commits.

For multi-step write workflows (admin actions that must be atomic across multiple tables — accept stage 1 of a conflict resolution, add a badge plus write its audit log, deactivate a member plus close their open vote ranges), the workflow is implemented as **one orchestrator service function** that wraps all steps in a single transaction. The route handler calls that one function.

```python
# features/admin/badges/route.py
@bp.route("/badges/<int:item_id>/add/<slug>", methods=["POST"])
def add_badge(item_id, slug):
    badges_writer.add_with_audit(item_id, slug, user_id=current_user.id)
    return redirect(...)

# services/badges_writer.py
def add_with_audit(item_id, slug, user_id):
    with db_cursor() as cur:                          # single transaction
        cur.execute("INSERT INTO agenda_item_badges ...", ...)
        cur.execute("INSERT INTO agenda_item_badges_audit ...", ...)
    # commits on context exit; rolls back atomically on any exception
```

The anti-pattern this avoids: a feature calling two separate service functions in sequence (e.g., `badges_writer.add(...)` then `badges_writer.write_audit(...)`), each opening its own connection and committing independently — a failure on the second call would leave the database half-updated.

**Single-step writes** (one INSERT or one UPDATE) need no orchestrator — the existing single service function is already a complete transaction.

This pattern is already in use across `services/ingest.py`, `services/conflict_resolution.py` (moving to `ai/`), `services/badges_writer.py`, and `services/minutes_adoption.py`. The modularity refactor preserves it without modification.

### Sharing policy — hybrid (extract on first for domain nouns, on second for page shapes)

Two pure policies both fail:

- **Extract on first use everywhere** → `services/` regrows into a god module of one-call-site functions (this is how `services/query.py` got to 2,322 lines).
- **Extract on second use everywhere** → duplication risk; new features don't know what primitives already exist.

The hybrid splits along the right axis:

| Type of query | Where it goes |
|---|---|
| **Domain noun** — fetch a meeting, fetch votes for a meeting, fetch agenda items, fetch council members, search items, list topics | `services/query/<topic>.py` from day one |
| **Page-shaped** — "notable items in last 180 days for landing," "badge volume timeline for category landing," "data debt quality breakdown" — exists because a specific page needed it | `features/<feature>/query.py` until proven shared by a second feature |

**The test:** would the query make sense to someone who's never seen the feature? If yes → services. If you'd have to explain the page first → feature.

Same hybrid for components:

- Cards/atoms that render data uniformly (Smart Brevity Card, council card, badge chip, dollar tier) → `components/` from day one.
- Page-specific layout chunks → stay in feature templates until reused.

### Flask blueprint registration

Each feature exports a blueprint:

```python
# features/public/meeting_detail/__init__.py
from flask import Blueprint
bp = Blueprint("meeting_detail", __name__, template_folder="templates")
from . import route  # noqa: F401
```

`web/__init__.py` registers them under explicit URL prefixes:

```python
# web/__init__.py (excerpt)
from docket.features.public import (
    home, city_overview, meetings_list, meeting_detail, item_detail,
    category_landing, topics, search, council, data_debt as public_data_debt,
    rss,
)
from docket.features.admin import (
    members, data_debt as admin_data_debt, errors_queue, source_security,
    calibration, ai_dashboard, badges, review_conflicts,
)

for feature in (home, city_overview, meetings_list, meeting_detail,
                item_detail, category_landing, topics, search, council,
                public_data_debt, rss):
    app.register_blueprint(feature.bp)

for feature in (members, admin_data_debt, errors_queue, source_security,
                calibration, ai_dashboard, badges, review_conflicts):
    app.register_blueprint(feature.bp, url_prefix="/admin")
```

**Critical: existing URLs do not change.** All 46 routes resolve at byte-identical paths after the refactor. No broken bookmarks, no broken RSS subscribers, no SEO regression.

### Template resolution

Three search locations, in order:
1. The feature's own `templates/` folder (declared per blueprint).
2. `components/` for macros (`{% import "components/cards/smart_brevity.html" as cards %}`).
3. `components/layouts/` for base templates (`{% extends "layouts/base.html" %}`).

The Flask app registers a top-level `template_folder=COMPONENTS_DIR`; each blueprint adds its own `template_folder` relative to itself. Jinja resolves child-first then global.

### Tests

- **Per-feature tests** live in `features/<persona>/<feature>/tests/`. These exercise one feature in isolation: its route, its query, its template, its HTMX partials.
- **Cross-feature integration tests** stay at `tests/integration/`. **The rule:** any test that exercises two or more features (e.g., "admin user adds a badge, then public category landing renders the badge") is cross-feature and belongs at `tests/integration/`. A test confined to one feature folder lives with that feature.
- **Unit tests for `services/`, `ai/`, `adapters/`, etc.** stay at `tests/unit/`. These tests don't touch the web layer.

**Three concrete examples of the boundary:**

| Test asserts… | Lives at |
|---|---|
| `meeting_detail` renders consent-block collapse correctly given a fixture vote | `features/public/meeting_detail/tests/test_route.py` |
| Admin POST `/admin/badges/<id>/add/<slug>` causes the badge to render on `/al/<slug>/<badge_slug>/` | `tests/integration/test_admin_badge_to_category_landing.py` (touches admin/badges + public/category_landing) |
| Full pipeline e2e — ingest, AI process, vote match, public render | `tests/integration/test_pipeline_e2e.py` (existing; unchanged) |

This is additive — existing tests don't move except where their subject moves (route tests for an extracted feature relocate alongside the feature).

---

## Components and the rendering layer

### Layer 1 — Layouts (page shells)

```
components/layouts/
  base.html              ← citizen app shell (rail, masthead, footer, fonts, HTMX)
  admin_base.html        ← admin app shell (no rail, simpler nav)
  rss_base.xml.j2        ← RSS feed wrapper
```

Every feature template extends exactly one layout. Layouts own cross-cutting chrome.

### Layer 2 — Macros (rendering atoms)

Macros are typed functions: data parameters in, HTML out. The variant policy is critical for preventing drift:

1. **One macro per atom; variants are parameters.** Don't create `smart_brevity_full.html` and `smart_brevity_compact.html`; create one `smart_brevity.html` with a `variant` parameter.
2. **Variants are validated programmatically, not just commented.** Comments drift; enforcement doesn't. Each macro calls a registered Jinja global `validate_variant` that raises immediately on unknown values, catching drift at template render time (and therefore in route smoke tests during CI).

   ```jinja
   {# components/cards/smart_brevity.html #}
   {% macro render(item, variant="full") %}
   {{ validate_variant(
        "smart_brevity_card",
        variant,
        ["full", "compact", "meeting", "topic", "member", "search"]
   ) }}
   <article class="sb-card sb-card--{{ variant }}">...</article>
   {% endmacro %}
   ```

   The validator (registered once in `web/__init__.py` or `web/filters/__init__.py`):

   ```python
   def validate_variant(macro_name, value, allowed):
       if value not in allowed:
           raise ValueError(
               f"Unknown variant {value!r} for macro {macro_name}. "
               f"Allowed: {sorted(allowed)}"
           )
       return ""  # rendered as empty string

   app.jinja_env.globals["validate_variant"] = validate_variant
   ```

   The closed set in the `validate_variant` call is the source of truth. A typo or stale caller fails loudly at render time, never silently in production. Deprecating a variant means removing it from the allow-list and following the resulting test failures to every caller.

### Layer 3 — Jinja filters (cross-cutting formatting)

The split: **macros render markup; filters transform values.** `dollar_tier_class(amount)` returns `"tier-orange"`; `dollar_tier.html` macro wraps a value in `<span class="dollar tier-orange">$X</span>`.

`web/filters.py` (613 lines today) splits into `web/filters/<topic>.py`: `dates`, `money`, `badges`, `sources`, `text`. The `__init__.py` registers all filters with the app.

### What does NOT go in `components/`

- Page-specific layout chunks (stay in feature template).
- Logic that fetches data (macros only consume).
- Anything used by only one feature (hybrid rule: extract on second use for non-obvious atoms).

### Translation table — current → new

| Existing | New location |
|---|---|
| `templates/base.html` | `components/layouts/base.html` |
| `templates/partials/masthead.html` | `components/masthead.html` |
| `templates/partials/footer.html` | `components/footer.html` |
| `templates/partials/council_card.html` | `components/cards/council.html` |
| `templates/partials/rail_default.html` | `components/rail/default_body.html` |
| `templates/partials/rail_meeting.html` | `components/rail/meeting_body.html` |
| `templates/partials/rail_member.html` | `components/rail/member_body.html` |
| Smart Brevity Card variant templates | `components/cards/smart_brevity.html` (one macro, variants in) |

---

## Slimming services/

### Decomposition of `services/query.py`

45 top-level defs in 2,322 lines split into 11 topical files:

```
services/query/
  __init__.py
  cities.py                  ← list_municipalities, get_municipality
  meetings.py                ← list_meetings, get_meeting, recent, upcoming, hearings
  agenda_items.py            ← list_agenda_items, by_topic, high_dollar
  votes.py                   ← list_votes (3-query N:M), recent, contested, helpers
  council.py                 ← list/get_member, member_vote_summary, _normalize_party
  badges.py                  ← 11 domain-noun fns: resolve_badges, list_items_by_badge,
                             ←   list_city_policy_badges, list_enabled_badges,
                             ←   list_process_badges, list_badges_on_item, etc.
  search.py                  ← search_meetings, search_agenda_items
  topics.py                  ← topic_counts
  stats.py                   ← dashboard_stats
  data_quality.py            ← list_data_debt_items, list_failed_permanent_items_all_cities,
                             ←   list_cross_stage_conflicts
```

### Page-shaped queries that move *out* of `services/`

These 5 functions + 2 private helpers (~500 lines) exist only because the category landing page wanted them. Per the hybrid rule, they belong with the feature:

| Function | From | To |
|---|---|---|
| `category_kpis` | `services/query.py:1063` | `features/public/category_landing/query.py` |
| `badge_volume_series` | `services/query.py:1236` | `features/public/category_landing/query.py` |
| `badge_volume_year` | `services/query.py:1539` | `features/public/category_landing/query.py` |
| `badge_volume_recent` | `services/query.py:1599` | `features/public/category_landing/query.py` |
| `mayoral_term_overlay` | `services/query.py:1415` | `features/public/category_landing/query.py` |
| `_months_in_range`, `year_ticks` | helpers | same destination (private) |

### Other services/ files

| File | Action |
|---|---|
| `services/ingest.py` | Untouched |
| `services/enrichment.py` | Untouched |
| `services/minutes_adoption.py` | Untouched |
| `services/maintenance.py` | Untouched |
| `services/badges.py` | **Renamed** to `services/badges_writer.py` (disambiguates from `services/query/badges.py`) |
| `services/calibration.py` | Untouched |
| `services/conflict_resolution.py` | **Moved** to `ai/conflict_resolution.py` — see below |

### Fixing the `services → ai` inversion

The inversion has one source: `services/conflict_resolution.py` (4 import sites against `ai/`). `conflict_resolution` is logically AI workflow — it re-prompts Stage 1/Stage 2 of the AI pipeline based on admin decisions and operates on AI-generated structured data.

**Move:** `services/conflict_resolution.py` → `ai/conflict_resolution.py`. The admin feature `features/admin/review_conflicts/route.py` then imports from `ai/`.

This is a pure file move with no logic change. The integration test `tests/integration/test_conflict_resolution.py` stays in place; only the SUT path updates. The `# noqa: F401 (test-compat re-export)` smell disappears — tests can import from `ai/` directly.

### Import update pattern

```python
# Before
from docket.services.query import list_meetings, list_votes, badge_volume_series

# After
from docket.services.query.meetings import list_meetings
from docket.services.query.votes import list_votes
from docket.features.public.category_landing.query import badge_volume_series
```

Pure mechanical relocation. No call sites change *what* they call.

---

## Sequencing

### Pre-flight (must complete before refactor starts)

1. **Refactor #2 follow-up #2 — consent-text recovery.** Touches `services/` and `ai/wave0.py`. Ship first to avoid `services/query.py` merge conflicts. (Refactor #2 follow-up #1 — marker-first WITHDRAWN regex — already shipped 2026-05-12 as PR #22.)
2. **Editorial coverage spec.** Per separate brainstorm (queued; will be `docs/superpowers/specs/2026-05-13-editorial-coverage-design.md` or similar). Editorial implementation follows; modularity refactor starts after editorial ships, so feature folders are extracted into a known-stable structure.
3. **Refactor #2 retro outstanding findings.** 3 MEDIUM + 5 LOW findings from PRs #16-#21 retro. Resolve or defer explicitly before modularity starts so they don't interleave with file moves.

### 23 PRs in 5 phases

Each PR is independently shippable, reversible (`git revert`-clean because URLs don't change), and small (target <800 lines, mostly file moves).

**Phase 0 — Scaffolding (5 PRs):**

| PR | Description |
|---|---|
| 0.1 | Create folder skeleton; move `templates/partials/` → `components/`; move base layouts to `components/layouts/` |
| 0.2 | Split `services/query.py` → `services/query/<topic>.py` (11 files); update all import sites |
| 0.3 | Move `services/conflict_resolution.py` → `ai/conflict_resolution.py` |
| 0.4 | Rename `services/badges.py` → `services/badges_writer.py` |
| 0.5 | Split `web/filters.py` → `web/filters/<topic>.py` |

After Phase 0: no features have moved, but landing pads exist, `services/` is slim, layering inversion is gone, every URL is byte-identical, every existing test passes.

**Phase 1 — Easy citizen pages (3 PRs, validates the pattern):**

| PR | Feature |
|---|---|
| 1.1 | `features/public/search/` (1 route) |
| 1.2 | `features/public/topics/` (2 routes) |
| 1.3 | `features/public/home/` (4 routes incl. `/about/*`) |

**Phase 2 — Medium citizen pages (3 PRs):**

| PR | Feature |
|---|---|
| 2.1 | `features/public/meetings_list/` |
| 2.2 | `features/public/data_debt/` + `features/public/rss/` (bundled — share RSS shape) |
| 2.3 | `features/public/item_detail/` |

**Phase 3 — Complex citizen pages (3 PRs):**

| PR | Feature |
|---|---|
| 3.1 | `features/public/city_overview/` + `_rail/default` |
| 3.2 | `features/public/council/` + `_rail/member` |
| 3.3 | `features/public/meeting_detail/` + `_rail/meeting` |

**Phase 4 — The big one (1 PR):**

| PR | Feature |
|---|---|
| 4.1 | `features/public/category_landing/` (includes the ~500-line SVG timeline code moving out of `services/`) |

**Phase 5 — Admin features (8 PRs; can interleave with Phase 1-4 or follow):**

| PR | Feature |
|---|---|
| 5.1 | `features/admin/source_security/` |
| 5.2 | `features/admin/calibration/` |
| 5.3 | `features/admin/ai_dashboard/` |
| 5.4 | `features/admin/data_debt/` |
| 5.5 | `features/admin/errors_queue/` |
| 5.6 | `features/admin/members/` |
| 5.7 | `features/admin/badges/` |
| 5.8 | `features/admin/review_conflicts/` (imports from `ai/conflict_resolution`) |

### Per-feature PR shape

A typical "extract one feature" PR contains:
- New `features/<persona>/<feature>/` folder with `__init__.py`, `route.py`, optional `query.py`, `templates/`, `tests/`.
- Routes deleted from `web/public.py` or `web/admin.py`.
- Templates moved from `templates/` into the feature folder.
- Tests covering this feature moved from `tests/integration/`/`tests/unit/` into `features/<persona>/<feature>/tests/`.
- `web/__init__.py` updated to register the new blueprint.
- Import updates at any caller site.

Diff target: **<800 lines, mostly file moves.** `git diff -M` should report most changes as renames.

### Rollback strategy

- Every PR is `git revert`-clean because URLs and behavior don't change.
- Verification per PR: `pytest` + `flask routes` snapshot diff against pre-PR baseline (should be empty).
- No feature flags needed — no runtime behavior changes.

---

## Scope boundaries

### In scope

- Folder reorganization for `src/docket/web/`, `src/docket/services/`, and `src/docket/templates/`.
- Import updates at all call sites.
- Template moves into feature folders.
- Per-feature test relocation.
- One file move (`conflict_resolution.py` → `ai/`).
- One file rename (`services/badges.py` → `services/badges_writer.py`).
- One file split (`web/filters.py` → `web/filters/`).
- `services/query.py` decomposition into topical subpackage.

### Explicitly NOT in scope

| Area | Reason |
|---|---|
| `ai/*` content | Backfill safety; no prompt versions, no AI logic changes. (One file *added* to `ai/` — `conflict_resolution.py` — but no existing `ai/` code is touched.) |
| `worker/*` | No code change beyond import updates if a worker task imports from `services/query`. |
| `adapters/*` | Already well-modularized via `MunicipalSourceAdapter` protocol. |
| `models/*` | Clean leaf; nothing to do. |
| `migrations/*` | No schema changes. |
| `analysis/*`, `enrichment/*` | Already topical; not in scope. |
| CSS, fonts, JS, design tokens | Visual unchanged. |
| Template markup content | Templates *move*, but HTML they emit is byte-identical. |
| URLs | All 46 routes byte-identical. |
| Database schema | No migrations. |
| Adding new features, pages, or components | Restructure-only. |
| Type hints, docstrings, dead-code removal, formatting | Would inflate diffs and bury the structural change. |
| Astro / Eleventy / Tailwind migration | Future decision; this refactor *prepares* for but does not commit to any. |

---

## Definition of done

- [ ] `src/docket/features/public/` contains 12 feature folders.
- [ ] `src/docket/features/admin/` contains 8 feature folders.
- [ ] `src/docket/web/public.py` no longer exists.
- [ ] `src/docket/web/admin.py` no longer exists.
- [ ] `src/docket/services/query.py` no longer exists.
- [ ] `src/docket/services/conflict_resolution.py` no longer exists (moved to `ai/`).
- [ ] `src/docket/services/badges.py` no longer exists (renamed to `badges_writer.py`).
- [ ] `src/docket/templates/partials/` no longer exists (moved to `components/`).
- [ ] All 46 routes resolve at byte-identical URLs (verified via `flask routes` snapshot diff).
- [ ] Full test suite passes (`pytest`).
- [ ] `services/` no longer imports from `ai/` (verified via grep).
- [ ] `CLAUDE.md` and `README.md` architecture sections updated.

---

## Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Template path resolution breaks (Jinja can't find a moved template) | Medium | Each blueprint declares its `template_folder`; smoke test that loads each URL; `flask routes` snapshot diff per PR. |
| Import circularity introduced (feature imports feature) | Low | Hard rule in design doc; grep audit per PR. |
| God-module regrowth in `services/query/<topic>.py` | Low-Medium | Hybrid policy enforced via reviewer discipline; documented in design doc. |
| Backfill regression from `conflict_resolution.py` move | Very low | Pure file move; logic byte-identical; `tests/integration/test_conflict_resolution.py` catches semantic breakage. |
| URL drift during a PR | Low | `flask routes` snapshot diff in every feature PR. |
| Merge conflict storm from in-flight work landing during the refactor | Medium | Pre-flight gating: ship refactor #2 follow-up #2 and editorial first. Feature-folder PRs each touch a narrow area, so post-pre-flight conflicts are unlikely. |

---

## Future capability slots

The VSA structure is intrinsically extensible — new capabilities are additive, not refactor-triggering. The following are documented here so the spec is forward-looking; **no empty placeholder folders are created**, since orphan folders rot and confuse readers.

### Editorial / coverage / media (separate spec queued)

- **Admin feature:** `features/admin/editorial/`
- **Read service:** `services/query/coverage.py`
- **Write service:** `services/editorial_writer.py`
- **Components:** `components/coverage/` (inline editorial render, coverage card, media embed)
- **Surfaces that will integrate coverage** (template-level additions, not structural):
  - `features/public/item_detail/templates/item_detail.html` — inline coverage block
  - `features/public/meeting_detail/templates/meeting_detail.html` — coverage indicator on item cards
  - `features/public/council/templates/council_detail.html` — editorials about a member
  - `features/public/category_landing/templates/category_landing.html` — featured editorial
  - `features/public/home/templates/home.html` — editor's picks
  - `components/rail/coverage_body.html` — coverage in per-page rail variant
- **Data model:** TBD in the editorial spec.
- **When editorial lands:** new admin feature folder + new service modules + new components + template edits to surface features. Zero folder moves, zero refactor of existing structure.

### Public API

- **Persona:** `features/api/v1/` (third sibling alongside `public/` and `admin/`)
- **Reuses** `services/query/` as read layer.
- **No schema changes** in this slot; just exposing existing queries as JSON.

### Freshness checks

- **Service-only:** `services/freshness.py`
- **Surfaces** via existing admin features (`errors_queue/`, `data_debt/`).
- **External:** Healthchecks.io or similar for alerting.

### Source reconciliation

- **Read service:** `services/query/sources.py`
- **Component:** `components/sources/discrepancy.html`
- **Surfaces** in `meeting_detail/` and `item_detail/`.

### Astro / Eleventy migration path

Each `features/public/<feature>/` is 1-to-1 mappable to a static-site-generator page:

- `features/public/meeting_detail/` → `src/pages/meetings/[id].astro`
- `features/public/city_overview/` → `src/pages/[city]/index.astro`
- `features/public/topic_landing/` → `src/pages/topics/[slug].astro`

Jinja macros in `components/` translate to Astro components; macro parameters become Astro props. The clean feature boundary makes a future migration tractable; this refactor does not commit to one.

---

## Interaction with in-flight work

(State as of 2026-05-13.)

| Item | Interaction |
|---|---|
| Phase 3 backfill (Anthropic Batches API, ~37K items, ~$100 budget) | UNAFFECTED. No prompt versions, no AI logic touched. The single file added to `ai/` (`conflict_resolution.py`) has no batch interaction. |
| Refactor #2 follow-up #1 — marker-first WITHDRAWN regex | Shipped 2026-05-12 as PR #22. ✓ |
| Refactor #2 follow-up #2 — consent-text recovery | Pre-flight requirement. Must ship before modularity starts. |
| Refactor #2 retro outstanding findings (3 MEDIUM, 5 LOW) | Resolve or explicitly defer before modularity. |
| Category landing 4-PR series (A, B, C, D) | All shipped 2026-05-12 → 2026-05-13. ✓ Feature is stable for extraction. |
| Per-page rail variants (proven on category landing during PR D) | Aligns with `components/rail/` per-page slots. No conflict. |
| AI Stage 2 item 361 (Issue #26) | Resolved via PR #32. ✓ |
| Rail empty-state copy + ingest-debt snapshot (PR #30) | Shipped. ✓ |
| Editorial coverage spec | Pre-flight requirement. Must ship before modularity starts. |
| `www.docket.pub` Railway move | Independent infrastructure task; no interaction. |
| Astro frontend evaluation | Deferred; this refactor prepares for it. |

---

## References

- **Pattern:** Vertical Slice Architecture (VSA). Industry-standard term for organizing by business function rather than technical role. Originally articulated for .NET; the principle ports cleanly to Python/Flask.
- **Guiding principle:** Locality of reasoning — one folder per feature; understand, modify, and test in isolation.
- **Related specs:**
  - `docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md` — v3 AI pipeline (the `ai/` layer this refactor leaves untouched).
  - `docs/superpowers/specs/2026-05-04-cron-worker-design.md` — `worker/` layer (also untouched).
  - `docs/superpowers/plans/2026-05-11-conservative-policy-badges.md` — Refactor #2, includes `badges_writer` logic.
  - (Pending) `docs/superpowers/specs/2026-05-13-editorial-coverage-design.md` — pre-flight requirement.

---

## Open items deferred to implementation plan

The implementation plan (separate `docs/superpowers/plans/<date>-modularity-cleanup.md`, produced via `superpowers:writing-plans` after pre-flight clears) will detail:

- Exact `pytest` command per PR for verification.
- The `flask routes` snapshot baseline file and diff invocation.
- Per-PR diff size expectations and any expected exceptions.
- The exact set of test file moves per feature extraction (which `tests/unit/test_*.py` and `tests/integration/test_*.py` migrate where).
- How `web/__init__.py` evolves PR-by-PR as features register.
- Coordination details with editorial spec implementation (which PR series interleaves how).
