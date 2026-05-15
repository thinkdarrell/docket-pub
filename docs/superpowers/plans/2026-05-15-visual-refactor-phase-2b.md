# Visual Refactor — Phase 2b (Restyles + rail rewire + retire morphing-rail) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Each task is dispatched to a **fresh sonnet implementer subagent**, then reviewed by a **fresh sonnet spec reviewer**, then by a **fresh sonnet code-quality reviewer**, before marking the task complete. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Model floor: sonnet.** Same rule as P2a — any verification step that says "check output X and report it back" must run on sonnet+, not haiku.
>
> **🛑 HUMAN VERIFICATION GATES.** P2b is the first phase of the visual refactor with **user-visible changes**. Each restyle task has a per-task visual review gate (Flask dev server + browser sweep). The final task does a full-site visual sweep before opening the PR.

**Goal:** Land the four partial restyles consumed by current pages (`smart_brevity_card`, `council_card`, `badge_chip`, `dollar_tier`), switch `base.html`'s rail include from `rail_default` → `source_rail` and make it overview-only, and retire the morphing-rail pattern by deleting `rail_meeting.html` / `rail_member.html` and their routes. Resolves P2a follow-ups #2 (CSS bloat: `.stat-card-base` extraction + `t-tnum` reuse + letter-spacing normalization) and #4 (`dollar_tier` explicit `amount` arg). Leaves `--type-hero` mismatch (P2a follow-up #1) for the P3 plan to address.

**Architecture:**
- **Visible restyles** are isolated to four partials; page templates are not restructured (P3+'s job). Each restyle keeps the partial's existing args + DOM contract so callers don't break.
- **Rail goes from morphing → static**. `base.html` switches to `source_rail` (which includes `rail_default`'s body) wrapped in a `{% if show_rail %}` block. Only `city_overview()` passes `show_rail=True` (with its `kpi_stats` data). Non-overview pages render no rail at all, so the layout reclaims that column (P3 will use it).
- **Morphing routes go away.** `rail_meeting()` / `rail_member()` view functions + URL bindings + their partials are deleted, along with the `hx-get` attributes in the six template call sites that still target them. Cards in those templates retain their existing `<a href>` navigation to detail pages (verified per template — see Task 9).
- **`rail_default.html` stays alive** as the "rail body" content (provenance + meeting count). Both `source_rail.html` and `source_sheet.html` already `{% include %}` it; that pattern persists. Only the `rail_default()` *view function* (HTMX endpoint) is deleted — its sole purpose was to swap the rail back to default after a morphing change, which is no longer needed.
- **Mobile source sheet** (`source_sheet.html`) is gated to overview-only in `base.html`, matching the same overview-only rule. **`bottom_tabs.html` stays site-wide** — it's the primary mobile nav (City / Meetings / Topics / Council / More); gating it would trap mobile users on every sub-page with no way out.

**Tech Stack:**
- Jinja2 templates, Flask, HTMX (callers only — no HTMX changes)
- Pytest with the `render_partial` fixture from P2a (`tests/web/conftest.py`)
- CSS custom properties from P1 (`--type-*`, `--space-*`), `t-tnum` utility, `.sr-only` from `styles.css`
- No new Python dependencies, no migrations, no JS changes

**Spec:** `docs/superpowers/specs/2026-05-14-visual-refactor-design.md` — Phase 2 section (lines 87-124) for restyles; "Source rail (desktop, overview only)" (lines 152-156) for the rail rule.
**Predecessor:** P2a shipped via PR #53 (merge `ffa91e3`, 2026-05-15). 6 new partials + 23 snapshot tests live on `main`, unconsumed in production.
**Memory:** `project_visual_refactor_2026_05_14.md` records the seven follow-ups carried forward from P2a. P2b resolves #2 and #4 inline. Follow-up #1 (`--type-hero` 64px-vs-72px) is **not** in P2b scope — leave for the P3 plan. Follow-ups #3/#5/#6/#7 stay parked for P3.

**Open decisions to flag in PR review:**
- P3 follow-up #1 (`--type-hero` mismatch) is parked — P2b does not consume `--type-hero`.
- After the rail goes overview-only, non-overview pages have an empty right column. P3 will reclaim it; in the meantime the `app-rail` grid track simply renders empty space. We do **not** change `app.css` / `layout.css` to collapse the grid in P2b (that's a layout-shape change that would belong with P3's overview rebuild).

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `src/docket/web/templates/partials/dollar_tier.html` | Modify | Change implicit-`{% set %}`-context contract to an explicit `amount` arg. Restyle to the new look (new class names, P1 tokens). |
| `src/docket/web/templates/partials/meeting_card.html` | Modify | Replace the `{% set amount = … %}{% include 'dollar_tier.html' with context %}` pattern with `{% with amount=meeting.dollars_total %}{% include 'dollar_tier.html' %}{% endwith %}` (or equivalent explicit-arg pass). |
| `src/docket/web/templates/partials/badge_chip.html` | Modify | Restyle pill; class-name namespace stays under `badge-chip-*`. |
| `src/docket/web/templates/partials/smart_brevity_card.html` | Untouched | This is the dispatcher; restyle happens on the variant files it delegates to. |
| `src/docket/web/templates/partials/card_smart_brevity.html` | Modify | Apply LegislationCard idiom (eyebrow + tier badge + title + mono byline + status pill + topic dot). |
| `src/docket/web/templates/partials/card_v2_fallback.html` | Modify | Same restyle to match (used for items still on v2 summaries, same visual contract). |
| `src/docket/web/templates/partials/council_card.html` | Modify | Baseball-card pattern: avatar tile + name + district + attendance % + alignment %. Removes the `hx-get`/`hx-target` attrs in Task 9; this task only restyles the body. |
| `src/docket/web/templates/base.html` | Modify | Wrap the rail aside + mobile sheet + bottom tabs in a `{% if show_rail %}` (or `{% block rail %}` override) gate. Switch include from `rail_default` → `source_rail`. |
| `src/docket/web/public.py` | Modify | (Task 8) `city_overview()` passes `show_rail=True` + `kpi_stats=[…]` to the template. (Task 10) Delete `rail_default()`, `rail_meeting()`, `rail_member()` view functions and their routes. |
| `src/docket/web/templates/city.html` | Modify | Override `{% block rail %}` to include `source_rail`. Remove `hx-get`/`hx-target` attrs from card markup in 6 spots (Task 9). |
| `src/docket/web/templates/meetings.html` | Modify | Remove `hx-get="…rail_meeting"` / `hx-target="#source-rail"` from card markup (Task 9). |
| `src/docket/web/templates/search.html` | Modify | Same removal (Task 9). |
| `src/docket/web/templates/topic_detail.html` | Modify | Same removal (Task 9). |
| `src/docket/web/templates/meeting_detail.html` | Modify | Remove `{% include "partials/rail_meeting.html" %}` at line 5 (Task 9). |
| `src/docket/web/templates/partials/rail_meeting.html` | Delete | Morphing rail retired (Task 10). |
| `src/docket/web/templates/partials/rail_member.html` | Delete | Morphing rail retired (Task 10). |
| `src/docket/web/static/layout.css` | Modify | Extract `.stat-card-base` shared class (resolves P2a follow-up #2), apply new partials' selectors, drop the redundant `font-feature-settings` rules in `.num-stat-label`/`-value` + `.kpi-explainer-label`/`-value` (use `t-tnum` instead). Normalize letter-spacing across `freshness-chip-state-label` (0.1em) / `num-stat-label` / `kpi-explainer-label` (0.12em) — pick 0.1em. New rules for restyled partials. |
| `src/docket/web/static/mobile.css` | Modify | Mobile overrides for the restyled cards if needed. |
| `src/docket/web/static/styles.css` | Untouched if possible | Only touch if a token needs adjusting (and even then, prefer adding a new token over editing existing ones). |
| `tests/web/test_partials_visual_refactor.py` | Modify | Update snapshot tests for `num_stat` / `kpi_explainer` to drop the redundant `font-feature-settings` assertion (now covered by `t-tnum`); update letter-spacing assertions. |
| `tests/unit/test_dollar_tier.py` | Modify | Update `render_template("partials/dollar_tier.html", amount=…)` call sites stay identical; add a regression test that the partial no longer relies on caller's `{% set amount %}` context. |
| `tests/web/test_routes_smoke.py` (or equivalent) | Modify | Drop rail-route entries from any route smoke list; add an assertion that GET `/al/birmingham/_rail/meeting/123` returns 404 after Task 10. |

---

## Task 1: Worktree setup + own venv + baseline pytest pass

**Why this is separate:** P2a learned (the hard way — see `feedback_haiku_verification_hallucination.md`) that symlinking the canonical venv into a worktree can corrupt the canonical environment. Each worktree gets its own venv. This task lands clean baseline before any code changes.

**Files:**
- None modified — environment setup only.

### Step 1: Controller — create worktree

- [ ] Run from canonical repo (`/Users/darrellnance/docket-pub`, on `main`):

```bash
git checkout main && git pull --ff-only origin main
```

Use the platform's native worktree tool (e.g., `EnterWorktree`) to create an isolated workspace. Branch name: `worktree-visual-refactor-p2b`.

### Step 2: Implementer — set up worktree's own venv

- [ ] From inside the worktree (NOT a symlink — own venv per memory `feedback_haiku_verification_hallucination.md` and `project_visual_refactor_2026_05_14.md`):

```bash
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
# Mirror canonical's frozen versions so worktree pip-state can't drift mid-PR
pip install -r <(/Users/darrellnance/docket-pub/venv/bin/pip freeze)
```

Symlink the .env (no secrets duplication):

```bash
ln -s /Users/darrellnance/docket-pub/.env .env
```

### Step 3: Baseline pytest

- [ ] Run:

```bash
venv/bin/pytest --ignore=tests/live -q 2>&1 | tail -3
```

Expected: `1540 passed` (or higher — `pytest` count drifts with new tests landed on `main` after P2a; whatever the current `main` baseline shows is the target).

If the baseline doesn't match `main`'s number, stop and report — the worktree may not be at the latest commit. Verify with `git log -1 --oneline` against canonical's `git log -1 --oneline origin/main`.

### Step 4: Confirm a Flask dev server boots locally

- [ ] Run (using port 5001 — port 5000 is AirPlay on this Mac, per P2a):

```bash
PORT=5001 venv/bin/flask --app docket.web run --port 5001 &
sleep 2
curl -sf http://localhost:5001/ -o /dev/null && echo "200 OK"
kill %1
```

Expected: `200 OK`.

### Step 5: Commit baseline state (no code changes)

- [ ] Not applicable — Task 1 has no code changes. Move to Task 2.

---

## Task 2: CSS bloat cleanup — extract `.stat-card-base`, drop redundant `font-feature-settings`, normalize letter-spacing

**Why this is separate:** Resolves P2a follow-up #2. Lands a small, reviewable cleanup before any visible-change task. Has no visible impact on the rendered site (the new partials it touches are still unconsumed). Verifies the CSS change is byte-equivalent in computed style for the consumers added in P2a.

**Files:**
- Modify: `src/docket/web/static/layout.css` — extract `.stat-card-base`; remove `font-feature-settings: "tnum" 1, "lnum" 1` from `.num-stat-label`/`-value` and `.kpi-explainer-label`/`-value` selectors that already get tnum from a `t-tnum` class on the element; normalize `.freshness-chip-state-label` letter-spacing from `0.1em` to `0.12em` (matches `.num-stat-label` and `.kpi-explainer-label`).
- Modify: `src/docket/web/templates/partials/num_stat.html` — add `t-tnum` class to the value span if not already there.
- Modify: `src/docket/web/templates/partials/kpi_explainer.html` — same.
- Modify: `tests/web/test_partials_visual_refactor.py` — update the `font-feature-settings` and letter-spacing assertions to match the new state.

### Step 1: Write a failing test for the consolidated base class

- [ ] Add to `tests/web/test_partials_visual_refactor.py`:

```python
def test_stat_card_base_class_exists_in_layout_css():
    """`.stat-card-base` is the shared base for num_stat and kpi_explainer cards.
    Both partials' root element should carry this class so common rules
    (padding, border, background) live in one selector."""
    css = (PROJECT_ROOT / "src/docket/web/static/layout.css").read_text()
    assert ".stat-card-base" in css, ".stat-card-base shared rule missing"


def test_num_stat_renders_t_tnum_on_value(render_partial):
    """num_stat's value span uses the .t-tnum utility instead of redeclaring
    font-feature-settings inline."""
    html = render_partial("num_stat", label="Meetings YTD", value="42")
    assert 'class="num-stat-value t-tnum"' in html or 'class="t-tnum num-stat-value"' in html
```

### Step 2: Run tests; verify the new tests fail

- [ ] Run:

```bash
venv/bin/pytest tests/web/test_partials_visual_refactor.py -k "stat_card_base or t_tnum" -v
```

Expected: 2 FAIL (one missing class in CSS, one missing class on the value span).

### Step 3: Implement — extract `.stat-card-base` + add `t-tnum` to values

- [ ] Open `src/docket/web/static/layout.css`, find the existing `.num-stat`, `.num-stat-label`, `.num-stat-value` block and the parallel `.kpi-explainer-*` block (introduced in P2a). Refactor:

```css
/* Shared base — Phase 2b extraction (P2a follow-up #2) */
.stat-card-base {
    padding: var(--space-md);
    border: 1px solid var(--color-rule);
    background: var(--color-surface);
    border-radius: 4px;
}

.num-stat,
.kpi-explainer {
    /* inherits from .stat-card-base via the class on the partial */
}

.num-stat-label,
.kpi-explainer-label {
    font: 500 11px/1.3 var(--font-mono);
    letter-spacing: 0.12em;  /* normalized */
    text-transform: uppercase;
    color: var(--color-meta);
}

.num-stat-value,
.kpi-explainer-value {
    font: 600 var(--type-stat) var(--font-sans);
    color: var(--color-ink);
    /* font-feature-settings removed — now via .t-tnum on the element */
}

.freshness-chip-state-label {
    /* … existing rules … */
    letter-spacing: 0.12em;  /* was 0.1em — normalized */
}
```

(Exact selector bodies depend on what's currently in `layout.css`. The implementer must preserve all existing rules — only the four enumerated changes apply: extract `.stat-card-base`, drop `font-feature-settings` from the four selectors, normalize letter-spacing on `.freshness-chip-state-label`.)

- [ ] Open `src/docket/web/templates/partials/num_stat.html`. Add `stat-card-base` to the root class list and `t-tnum` to the value span:

```jinja
{# Existing structure preserved; only class lists updated. #}
<div class="num-stat stat-card-base">
  <div class="num-stat-label">{{ label }}</div>
  <div class="num-stat-value t-tnum">{{ value }}</div>
  {% if sub %}<div class="num-stat-sub">{{ sub }}</div>{% endif %}
</div>
```

- [ ] Same change to `src/docket/web/templates/partials/kpi_explainer.html` — add `stat-card-base` to the root, `t-tnum` to the value span.

### Step 4: Update existing snapshot assertions

- [ ] In `tests/web/test_partials_visual_refactor.py`, find any test asserting `font-feature-settings` is in the rendered partial output and replace with assertions on the `t-tnum` class. Find any test asserting `letter-spacing: 0.1em` on `.freshness-chip-state-label` and update to `0.12em`.

### Step 5: Run full pytest

- [ ] Run:

```bash
venv/bin/pytest tests/web/ -q
```

Expected: all green (baseline count from Task 1, no drop, no skip).

### Step 6: Visual smoke (no visible change expected, but verify)

- [ ] Boot Flask, hit `/`, screenshot the masthead-area (where `num_stat` would render if it were consumed). Expected: identical to pre-task screenshot. Since `num_stat` isn't yet consumed on any page, this is mostly a regression check that nothing accidentally broke.

```bash
PORT=5001 venv/bin/flask --app docket.web run --port 5001 &
sleep 2
curl -sf http://localhost:5001/al/birmingham/ -o /tmp/p2b-task2-overview.html
grep -c "num-stat\|kpi-explainer" /tmp/p2b-task2-overview.html
kill %1
```

Expected `0` matches (neither partial is consumed yet — Task 8 wires them in via source_rail).

### Step 7: Commit

- [ ] Stage and commit:

```bash
git add src/docket/web/static/layout.css \
        src/docket/web/templates/partials/num_stat.html \
        src/docket/web/templates/partials/kpi_explainer.html \
        tests/web/test_partials_visual_refactor.py
git commit -m "style: extract .stat-card-base + use t-tnum + normalize letter-spacing"
```

---

## Task 3: `dollar_tier` — explicit `amount` arg (P2a follow-up #4)

**Why this is separate:** Today the partial reads `amount` from caller context via `{% set %}` + `with context`. That implicit contract was logged as a P2a follow-up because a refactor to dollar_tier wouldn't fail loudly at the meeting_card call site. Switch to an explicit `{% with amount=… %}` pattern so the call site is statically visible. No visible change.

**Files:**
- Modify: `src/docket/web/templates/partials/dollar_tier.html` — drop the "implicit context" comment, keep arg name `amount` (only the contract changes, not the var name).
- Modify: `src/docket/web/templates/partials/meeting_card.html` — change `{% set amount = meeting.dollars_total %} … {% include 'partials/dollar_tier.html' with context %}` to `{% with amount=meeting.dollars_total %}{% include 'partials/dollar_tier.html' %}{% endwith %}`.
- Modify: `tests/unit/test_dollar_tier.py` — add a regression test that the partial doesn't read `amount` from outer Jinja scope when invoked without `with context`.

### Step 1: Write a failing test for strict-isolation contract

**Jinja scope note:** `{% include %}` inherits parent context **by default**. To get a strict explicit-arg contract, the caller MUST use `{% include 'partials/dollar_tier.html' without context %}` — otherwise an outer-scope `amount` will leak in even if `{% with amount=… %}` isn't used. The test below confirms the new posture.

- [ ] Add to `tests/unit/test_dollar_tier.py`:

```python
def test_dollar_tier_does_not_inherit_amount_from_outer_scope(app):
    """Regression: dollar_tier callers must pass amount via {% with %}
    AND {% include … without context %} so an outer-scope `amount`
    cannot leak in. Test renders with a MISLEADING outer-scope amount
    and the partial included WITHOUT context and WITHOUT a {% with %};
    the partial must see no amount → render nothing."""
    with app.test_request_context():
        from flask import render_template_string
        rendered = render_template_string(
            "{% set amount = 1234567 %}"
            "{% include 'partials/dollar_tier.html' without context %}"
        )
    assert rendered.strip() == "", (
        f"dollar_tier inherited amount from outer scope; got: {rendered!r}"
    )


def test_dollar_tier_with_explicit_amount_via_with_without_context(app):
    """Positive case: the canonical call pattern must work."""
    with app.test_request_context():
        from flask import render_template_string
        rendered = render_template_string(
            "{% with amount=250000 %}"
            "{% include 'partials/dollar_tier.html' without context %}"
            "{% endwith %}"
        )
    assert 'dollars--orange' in rendered  # $250K is the orange tier
    assert '$250,000' in rendered or '$250K' in rendered
```

### Step 2: Run the tests; verify the first one fails initially

- [ ] Run:

```bash
venv/bin/pytest tests/unit/test_dollar_tier.py -k "outer_scope or explicit_amount_via_with" -v
```

Expected: the first test PASSES already if Jinja's `without context` semantics are working correctly (the partial sees no `amount` because `without context` strips outer scope, and the partial's `|default(None)` resolves to None → no render). The second test FAILS because `meeting_card.html` hasn't been updated yet to use the new `without context` posture, BUT this test renders the partial directly via `render_template_string`, so it's actually testing Jinja semantics, not the call site.

**Implementer:** if the first test FAILS (partial inherited the outer `amount`), that means `dollar_tier.html` currently has its own `{% set %}` or a missing default. Confirm by reading the partial source before "fixing" anything — the goal is for `without context` semantics to be the enforcement; the partial just needs `|default(None)` as a safety belt.

### Step 3: Implement the explicit-arg posture

- [ ] In `src/docket/web/templates/partials/dollar_tier.html`, replace the docstring's "implicit context — parent passes `amount`" wording with an explicit-arg note:

```jinja
{# Dollar Tier with WCAG Markup — spec §6.1, decisions #71 + #75.

   Args (pass via {% with amount=… %} or as a kwarg to render_template):
     - ``amount``  — Decimal | None. When None or invalid, renders nothing.

   …rest of docstring preserved verbatim…
#}
{%- set amount = amount|default(None) -%}
{%- set tier_data = amount | dollar_tier -%}
{%- if tier_data -%}
…existing body unchanged…
{%- endif -%}
```

The `|default(None)` is the explicit guard against undefined.

- [ ] In `src/docket/web/templates/partials/meeting_card.html`, change line 45-47 from:

```jinja
{%- set amount = meeting.dollars_total -%}
{% if amount %}
  {% include 'partials/dollar_tier.html' with context %}
{% endif %}
```

to:

```jinja
{% if meeting.dollars_total %}
  {% with amount=meeting.dollars_total %}
    {% include 'partials/dollar_tier.html' without context %}
  {% endwith %}
{% endif %}
```

**Jinja note (corrected during Task 3 execution):** my original wording said "use `without context`" — that's broken. Jinja's `without context` strips ALL parent scope, **including `{% with %}`-bound vars**. So `{% with amount=X %}{% include … without context %}{% endwith %}` passes nothing to the partial — the partial would render empty.

The correct working idiom is `{% with amount=X %}{% include … with context %}{% endwith %}`. The `{% with %}` block creates a new scope that SHADOWS any outer `amount`; `with context` (the default) propagates that shadowed scope into the partial. Outer-scope leakage is prevented by the `{% with %}` shadow, not by `without context`.

The negative isolation test (`test_dollar_tier_does_not_inherit_amount_from_outer_scope`) still uses `without context` correctly — it asserts what happens when an explicit-arg pattern is NOT used. Real call sites use `with context`. Both meeting_card.html (Task 3) and card_smart_brevity.html (Task 6) follow this pattern.

### Step 4: Run all relevant tests

- [ ] Run:

```bash
venv/bin/pytest tests/unit/test_dollar_tier.py tests/web/test_partials_visual_refactor.py -q
```

Expected: all green.

### Step 5: Commit

- [ ] Stage and commit:

```bash
git add src/docket/web/templates/partials/dollar_tier.html \
        src/docket/web/templates/partials/meeting_card.html \
        tests/unit/test_dollar_tier.py
git commit -m "refactor(dollar_tier): take amount as explicit arg (no caller context)"
```

---

## Task 4: Restyle `dollar_tier.html`

**Why this is separate:** First restyle, smallest blast radius (partial is currently only consumed by `meeting_card.html`, which is itself unconsumed in production). Establishes the restyle pattern for Tasks 5–7. Visual review can happen against `tests/web/test_partials_visual_refactor.py`'s snapshot output, plus a manual render via the partial test fixture, plus a Flask render once meeting_card is consumed (P3).

**Spec reference:** Phase 2 restyle list (spec line 105: "restyled"). No detailed visual brief in the spec for dollar_tier specifically — the implementer should follow the design tokens from P1 (`--color-dollar-green` / `-yellow` / `-orange` / `-red`, type `--type-meta`, spacing `--space-xs`) and the sketch's visual idiom.

**Files:**
- Modify: `src/docket/web/templates/partials/dollar_tier.html` — restyle markup. New class names go under `dollars-` namespace (existing pattern). The accessibility approach (visible amount + symbol + `.sr-only` tier description) MUST be preserved (it's WCAG-tested in `tests/unit/test_dollar_tier.py`).
- Modify: `src/docket/web/static/layout.css` — new `.dollars` / `.dollars--<tier>` rules using P1 tokens.
- Modify: `tests/unit/test_dollar_tier.py` — snapshot rules updated where they assert on specific CSS classes that have changed.

### Step 1: Update existing tests to assert NEW DOM shape

- [ ] In `tests/unit/test_dollar_tier.py`, locate the "per-tier rendering" test block (line 424). Update each test's DOM assertions to match the new structure decided by the implementer (e.g., if the new markup is `<span class="dollars dollars--red"><span class="dollars-amount">$1.8M</span><span class="dollars-symbol">$$$$</span><span class="sr-only">…</span></span>`, update assertions accordingly).

**Important contract preservation:**
- The visible amount text still uses the `format_dollars` filter.
- The visible tier symbol (`$`, `$$`, `$$$`, `$$$$`) still appears.
- The `.sr-only` span still contains "tier (description)" prose.
- The `.dollars` root class still exists (other CSS may target it).
- The `.dollars--green/yellow/orange/red` modifier classes still exist (E2 may target them).

If any of those break, the test suite will alert. Implementer: do NOT change the contract; restyle within it.

### Step 2: Run updated tests; verify some fail

- [ ] Run:

```bash
venv/bin/pytest tests/unit/test_dollar_tier.py -q
```

Expected: some tests FAIL because the DOM hasn't been updated yet to match the new assertions. (If you've kept the contract identical and only added new structural elements, most tests still pass; only the new-structure assertions fail.)

### Step 3: Implement the restyle

- [ ] Edit `src/docket/web/templates/partials/dollar_tier.html` — restyle the inner markup (keeping the `{%- if tier_data -%}` guard + `.sr-only` span + the four modifier classes). Apply P1 tokens: monospace for amount (`--font-mono` or use `.t-tnum`), `--type-meta` size, P1 `--space-xs` for any internal gaps. Concrete shape (one reasonable cut — implementer may adjust if a better composition emerges):

```jinja
{%- set amount = amount|default(None) -%}
{%- set tier_data = amount | dollar_tier -%}
{%- if tier_data -%}
{%- set formatted = amount | format_dollars -%}
<span class="dollars dollars--{{ tier_data.color }}">
  <span class="dollars-amount t-tnum">{{ formatted }}</span>
  <span class="dollars-symbol" aria-hidden="true">{{ tier_data.symbol }}</span>
  <span class="sr-only">, {{ tier_data.color|title }} tier ({{ tier_data.description }})</span>
</span>
{%- endif -%}
```

- [ ] Edit `src/docket/web/static/layout.css` — add (or update existing) rules for `.dollars`, `.dollars-amount`, `.dollars-symbol`, and the four `.dollars--*` color modifiers. Use the four P1 tokens for dollar tiers (`--color-dollar-green` / `-yellow` / `-orange` / `-red` — verify these tokens exist in `styles.css` after P1; if they don't, define them now). Concrete rules — implementer's call on exact pixel values but use tokens not magic numbers:

```css
.dollars {
    display: inline-flex;
    align-items: baseline;
    gap: var(--space-xs);
    font: 500 var(--type-meta) var(--font-mono);
}
.dollars-amount { font-weight: 600; }
.dollars-symbol { opacity: 0.7; letter-spacing: 0.04em; }
.dollars--green  { color: var(--color-dollar-green); }
.dollars--yellow { color: var(--color-dollar-yellow); }
.dollars--orange { color: var(--color-dollar-orange); }
.dollars--red    { color: var(--color-dollar-red); }
```

### Step 4: Run tests; verify all green

- [ ] Run:

```bash
venv/bin/pytest tests/unit/test_dollar_tier.py tests/web/test_partials_visual_refactor.py -q
```

Expected: all green.

### Step 5: 🛑 HUMAN VISUAL REVIEW

- [ ] Render dollar_tier via the test fixture to a temp HTML file for manual inspection:

```bash
venv/bin/python -c "
from docket.web import create_app
app = create_app()
with app.test_request_context():
    from flask import render_template
    out = []
    for amt in [25000, 100000, 500000, 2500000]:
        out.append(f'<div style=padding:20px>{amt}: ' +
                   render_template('partials/dollar_tier.html', amount=amt) + '</div>')
    open('/tmp/p2b-task4-dollar-tier.html', 'w').write(
        '<link rel=stylesheet href=\"http://localhost:5001/static/styles.css\">' +
        '<link rel=stylesheet href=\"http://localhost:5001/static/layout.css\">' +
        ''.join(out)
    )
print('Wrote /tmp/p2b-task4-dollar-tier.html')
"
PORT=5001 venv/bin/flask --app docket.web run --port 5001 &
sleep 2
open /tmp/p2b-task4-dollar-tier.html
```

User reviews in browser. Confirms tier colors are distinguishable, symbols visible, amount-then-symbol composition reads well. User says GO or REVISE. If REVISE, iterate. If GO, kill server and proceed.

```bash
kill %1
```

### Step 6: Commit

- [ ] Stage and commit:

```bash
git add src/docket/web/templates/partials/dollar_tier.html \
        src/docket/web/static/layout.css \
        tests/unit/test_dollar_tier.py
git commit -m "style(dollar_tier): restyle to P1 tokens + monospace amount"
```

---

## Task 5: Restyle `badge_chip.html`

**Why this is separate:** Same pattern as Task 4 — small, contained restyle. Currently consumed by `card_smart_brevity.html` and `card_v2_fallback.html`, so the restyle becomes visible on every item card site-wide as soon as this task lands.

**Spec reference:** Spec line 104 ("restyled"); no detailed brief — implementer uses P1 tokens and sketch idiom.

**Files:**
- Modify: `src/docket/web/templates/partials/badge_chip.html` — restyle outer pill + verification spark placement.
- Modify: `src/docket/web/static/layout.css` — `.badge-chip` and its modifiers (`.badge-process`, `.badge-policy`, `.badge-conf-high`, `.badge-conf-medium`, `.badge-slug-<slug>`, `.badge-spark`, `.badge-meta`).
- Modify: existing snapshot tests in `tests/web/test_partials_visual_refactor.py` or `tests/unit/test_card_smart_brevity_renders.py` or similar — update DOM assertions for the new structure.

### Step 1: Locate existing tests + identify failing-then-passing assertion path

- [ ] Run:

```bash
grep -rn "badge_chip\|badge-chip\|badge-conf" tests/ | head -20
```

Implementer reads each test that asserts on badge_chip output and identifies which assertions need updating for the restyle. Bake a TODO list inline before changing markup.

### Step 2: Write a new test asserting the restyled structure

- [ ] Add a new test to `tests/web/test_partials_visual_refactor.py`:

```python
def test_badge_chip_restyle_uses_p1_tokens(render_partial):
    """The restyled chip must render the chip in its new structure
    (icon-leading, name, optional vote-count, verification spark).
    Asserts the post-restyle DOM tree shape."""
    chip = {
        'kind': 'process',
        'slug': 'split_vote',
        'confidence': 1.0,
        'description': 'Council split on this item',
        'icon': '⚡',
        'name': 'Split vote',
        'vote_count': {'yes': 5, 'no': 4},
    }
    html = render_partial("badge_chip", chip=chip)
    assert 'class="badge-chip' in html
    assert 'badge-process' in html
    assert 'badge-conf-high' in html
    assert 'badge-slug-split_vote' in html
    assert '⚡' in html
    assert 'Split vote' in html
    assert '5-4' in html
    assert '✨' in html  # verification spark
    assert 'aria-label="AI-verified"' in html
```

### Step 3: Run and verify pass (existing markup already supports most of this)

- [ ] Run:

```bash
venv/bin/pytest tests/web/test_partials_visual_refactor.py -k "badge_chip_restyle" -v
```

Expected: PASS already (current markup at `badge_chip.html` lines 22-34 supports all those assertions). This test is a regression anchor — if the implementer accidentally drops the icon, name, vote-count, or spark during restyle, this test alerts.

### Step 4: Implement the visual restyle

- [ ] Modify `src/docket/web/static/layout.css` to add or update `.badge-chip` rules. Use P1 tokens (`--type-meta`, `--space-xs`, `--color-meta`). The implementer follows the sketch and produces:
  - Pill shape with subtle border (using `--color-rule`)
  - Icon-leading layout, gap of `--space-xs`
  - Verification spark (`✨`) styled with slight scale + warm tint
  - High-confidence variants visually distinct from medium
  - `badge-meta` (vote count like "5-4") in `--font-mono` at smaller size

- [ ] Optionally restructure `badge_chip.html` for better semantics (e.g., wrap the visible content in nested spans for finer style control). MUST preserve the data contract (chip dict shape).

### Step 5: Run tests

- [ ] Run:

```bash
venv/bin/pytest tests/ -q
```

Expected: all green.

### Step 6: 🛑 HUMAN VISUAL REVIEW

- [ ] Render every item card variant to inspect the restyle in real context (since badge_chip is consumed by item cards):

```bash
PORT=5001 venv/bin/flask --app docket.web run --port 5001 &
sleep 2
open "http://localhost:5001/al/birmingham/"
# inspect Notable items + Contested votes sections
```

User reviews. Confirms chips read well, spark visible for high-confidence, vote-count meta legible. GO or REVISE. Kill server when done.

```bash
kill %1
```

### Step 7: Commit

- [ ] Stage and commit:

```bash
git add src/docket/web/templates/partials/badge_chip.html \
        src/docket/web/static/layout.css \
        tests/web/test_partials_visual_refactor.py
git commit -m "style(badge_chip): restyle pill + spark to P1 tokens"
```

---

## Task 6: Restyle `card_smart_brevity.html` + `card_v2_fallback.html` to LegislationCard idiom

**Why this is separate:** Highest-impact restyle in P2b. Touches the canonical item card seen on city.html, meetings.html, search.html, topic_detail.html, item_detail.html, and category_landing.html. Restyle target: spec line 102's LegislationCard idiom — "eyebrow + tier badge + title + mono byline + status pill + topic dot." Both variants get the same visual treatment because they're functionally equivalent (one renders v3 Smart Brevity content, one renders legacy v2 summaries; they appear interchangeably in lists and must look uniform).

**Spec reference:** Spec line 102; sketch references in `/Users/darrellnance/Downloads/docket-pub (1).zip` (LegislationCard mockup).

**Files:**
- Modify: `src/docket/web/templates/partials/card_smart_brevity.html` — restructure markup to LegislationCard idiom.
- Modify: `src/docket/web/templates/partials/card_v2_fallback.html` — same restructure for visual parity.
- Modify: `src/docket/web/templates/partials/_card_shell.html` — if it's the underlying shell consumed by both variants, restyle here so both inherit. (Read the file first to determine if it's an actual shared shell or just one variant's body.)
- Modify: `src/docket/web/static/css/smart_brevity.css` (or `layout.css` if cleaner) — new card layout rules.
- Modify: existing tests that snapshot card rendering — update DOM assertions to match new structure.

### Step 1: Read the existing card structure end-to-end

- [ ] Implementer reads (in order):
  - `src/docket/web/templates/partials/smart_brevity_card.html` (dispatcher, 19 lines)
  - `src/docket/web/templates/partials/card_smart_brevity.html`
  - `src/docket/web/templates/partials/card_v2_fallback.html`
  - `src/docket/web/templates/partials/_card_shell.html` (81 lines — the underlying shell)
  - `src/docket/web/static/css/smart_brevity.css` (existing styles)
  - All current snapshot tests targeting these partials (`grep -rn "card_smart_brevity\|smart_brevity_card" tests/`).

Implementer writes a 1-paragraph summary of the current structure inline in the task notes (where the data fields are, how the shell wraps the variant, what classes drive layout) before making changes. Commit this comprehension before changing code? No — keep it in working memory; jump to step 2.

### Step 2: Write tests asserting the NEW LegislationCard structure

- [ ] Add to the appropriate snapshot test file (`tests/web/test_partials_visual_refactor.py` or wherever item-card snapshots live):

```python
def test_card_smart_brevity_legislation_idiom(app, render_partial):
    """Restyled card uses LegislationCard idiom:
    - eyebrow (mono caps, item number + section)
    - tier badge (top-right)
    - h3 title
    - mono byline (sponsor · date)
    - status pill (footer)
    - topic dot (color hint)
    """
    # Construct a fully-populated v3 item mock
    item = {
        # … exact mock structure depends on what card_smart_brevity reads;
        # implementer fills this from the comprehension done in Step 1.
    }
    html = render_partial("card_smart_brevity", item=item)
    assert 'class="ls-card' in html or 'class="legislation-card' in html
    assert 'ls-card-eyebrow' in html
    assert 'ls-card-title' in html
    assert 'ls-card-byline' in html
    assert 'ls-card-status' in html
    assert 'ls-card-topic-dot' in html
```

(Class name choice — `.ls-card-*` for "legislation card" — is the implementer's call. Whatever naming is chosen, BOTH `card_smart_brevity.html` and `card_v2_fallback.html` must adopt it. Decide once, apply twice.)

### Step 3: Run; verify failure

- [ ] Run:

```bash
venv/bin/pytest tests/web/test_partials_visual_refactor.py -k "legislation_idiom" -v
```

Expected: FAIL (new structure not yet implemented).

### Step 4: Implement restyle on `card_smart_brevity.html`

- [ ] Restructure the markup to:

```jinja
<article class="ls-card" data-status="{{ item.processing_status }}">
  <div class="ls-card-head">
    <div class="ls-card-eyebrow t-mono">
      {{ item.item_number }} · {{ item.section_name|default('Item') }}
    </div>
    {% if item.dollars_total %}
      {% with amount=item.dollars_total %}
        {% include 'partials/dollar_tier.html' with context %}
      {% endwith %}
    {% endif %}
  </div>

  <h3 class="ls-card-title">{{ item.headline or item.title }}</h3>

  {% if item.why_it_matters %}
    <p class="ls-card-body">{{ item.why_it_matters }}</p>
  {% endif %}

  <div class="ls-card-byline t-mono">
    {% if item.sponsor %}{{ item.sponsor }} · {% endif %}{{ item.meeting_date|format_date }}
  </div>

  <footer class="ls-card-foot">
    <span class="ls-card-status">{{ item.processing_status|title }}</span>
    {% if item.topic %}
      <span class="ls-card-topic-dot" style="background: var(--topic-{{ item.topic }}, var(--color-rule))"
            aria-label="Topic: {{ item.topic }}"></span>
    {% endif %}
    {% include 'partials/_badge_row.html' %}
  </footer>
</article>
```

**Critical:** Preserve every existing data binding. The implementer must cross-reference the current `card_smart_brevity.html` to find any fields used in conditionals or rendered, and ensure each one survives the rewrite. If a field is dropped, P3+'s downstream pages will silently lose data.

### Step 5: Apply identical restyle to `card_v2_fallback.html`

- [ ] Same structure, but `item.summary` instead of `item.headline` / `item.why_it_matters`. Both variants land in the same `.ls-card` shell so list views render uniformly.

### Step 6: Update CSS

- [ ] In `src/docket/web/static/css/smart_brevity.css` (preferred, since it's already loaded after `layout.css`), add:

```css
.ls-card {
    display: grid;
    grid-template-areas: "head" "title" "body" "byline" "foot";
    gap: var(--space-xs);
    padding: var(--space-md);
    border: 1px solid var(--color-rule);
    background: var(--color-surface);
    border-radius: 6px;
}
.ls-card-head { display: flex; justify-content: space-between; align-items: flex-start; }
.ls-card-eyebrow {
    font: 500 11px/1.3 var(--font-mono);
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--color-meta);
}
.ls-card-title  { font: 600 var(--type-card-title) var(--font-serif); margin: 0; }
.ls-card-body   { font: 400 var(--type-body) var(--font-sans); color: var(--color-ink-soft); }
.ls-card-byline {
    font: 400 var(--type-meta) var(--font-mono);
    color: var(--color-meta);
}
.ls-card-foot {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    border-top: 1px solid var(--color-rule);
    padding-top: var(--space-xs);
}
.ls-card-status {
    font: 500 11px/1.2 var(--font-mono);
    text-transform: uppercase;
    letter-spacing: 0.1em;
}
.ls-card-topic-dot {
    width: 8px; height: 8px; border-radius: 50%;
    display: inline-block;
}
```

If any required token doesn't exist yet, add it to `styles.css` `:root` block (`--type-card-title`, `--type-body`, `--type-meta` etc. — most should already exist from P1).

### Step 7: Run full test suite

- [ ] Run:

```bash
venv/bin/pytest tests/ -q
```

Expected: all green.

### Step 8: 🛑 HUMAN VISUAL REVIEW — multi-page sweep

- [ ] Boot Flask. Walk through every page that consumes these cards:

```bash
PORT=5001 venv/bin/flask --app docket.web run --port 5001 &
sleep 2
open "http://localhost:5001/al/birmingham/"
open "http://localhost:5001/al/birmingham/meetings/"
open "http://localhost:5001/al/birmingham/topics/"
open "http://localhost:5001/al/birmingham/topics/public_safety"
open "http://localhost:5001/search?q=demolition"
open "http://localhost:5001/al/birmingham/property_recovery"
```

User reviews each page. Confirms cards render consistently across all surfaces, dollar tier (Task 4) and badges (Task 5) compose correctly inside the card foot, no broken images / overflowing text / missing fields. GO or REVISE.

```bash
kill %1
```

### Step 9: Commit

- [ ] Stage and commit:

```bash
git add src/docket/web/templates/partials/card_smart_brevity.html \
        src/docket/web/templates/partials/card_v2_fallback.html \
        src/docket/web/static/css/smart_brevity.css \
        src/docket/web/static/styles.css \
        tests/web/test_partials_visual_refactor.py
git commit -m "style(item-card): LegislationCard idiom on Smart Brevity + v2 variants"
```

---

## Task 7: Restyle `council_card.html` to baseball-card pattern (keep hx-get for now)

**Why this is separate:** Independent of item cards; consumed by `city.html` and `council.html`. Spec calls for "baseball-card pattern (avatar tile + name + district + attendance % + alignment %)." Attendance/alignment data isn't currently rendered — it has to be computed by the consumer (city.html / council.html) and passed in. **For P2b, render the attendance/alignment ONLY if the consumer passes them**; don't change the consumer to compute them yet. (P3/P4 will wire the data.)

**Important:** Task 7 leaves the `hx-get`/`hx-target` attrs on `<button class="cc">` in place. Removal happens in Task 9 (together with the other hx-get cleanup).

**Files:**
- Modify: `src/docket/web/templates/partials/council_card.html` — restyle to baseball-card. Optional fields `attendance_pct` and `alignment_pct` on the `m` dict.
- Modify: `src/docket/web/static/layout.css` — new `.cc-*` rules.
- Modify: tests covering council_card snapshot.

### Step 1: Write a failing test asserting the new optional-fields contract

- [ ] Add:

```python
def test_council_card_renders_attendance_alignment_when_provided(render_partial):
    m = {
        'id': 7, 'name': 'Jane Doe', 'district_name': 'District 3',
        'attendance_pct': 92, 'alignment_pct': 78, 'photo_url': None,
    }
    municipality = {'slug': 'birmingham'}
    html = render_partial("council_card", m=m, municipality=municipality)
    assert '92%' in html
    assert '78%' in html
    assert 'cc-attendance' in html
    assert 'cc-alignment' in html


def test_council_card_omits_attendance_alignment_when_missing(render_partial):
    m = {'id': 7, 'name': 'Jane Doe', 'district_name': 'District 3', 'photo_url': None}
    municipality = {'slug': 'birmingham'}
    html = render_partial("council_card", m=m, municipality=municipality)
    assert 'cc-attendance' not in html
    assert 'cc-alignment' not in html
```

### Step 2: Run; verify failure

- [ ] Run:

```bash
venv/bin/pytest tests/web/test_partials_visual_refactor.py -k "council_card" -v
```

Expected: FAIL — new fields not yet rendered.

### Step 3: Implement the restyle

- [ ] Update `src/docket/web/templates/partials/council_card.html`:

```jinja
{# Council member card — baseball-card pattern (spec §Phase 2 restyles).
   Expects: m (council member dict), municipality (with .slug).
   Optional on m: attendance_pct, alignment_pct (rendered if present). #}
{% set hue = (m.id * 137) % 360 %}
<button class="cc"
        type="button"
        hx-get="{{ url_for('public.rail_member', slug=municipality.slug, member_id=m.id) }}"
        hx-target="#source-rail"
        hx-swap="innerHTML">
    <div class="cc-portrait" style="background: oklch(0.45 0.12 {{ hue }})">
        {# existing SVG pattern + initials preserved verbatim — restyle is on the body, not the portrait #}
        <svg viewBox="0 0 100 100" class="cc-portrait-bg" aria-hidden="true">…</svg>
        <div class="cc-initials t-display">{{ m.name.split()[0][0] }}{{ m.name.split()[-1][0] }}</div>
        {% if not m.photo_url %}
        <div class="cc-portrait-tag t-mono">photo · placeholder</div>
        {% endif %}
    </div>
    <div class="cc-body">
        <div class="cc-name">{{ m.name }}</div>
        <div class="cc-district t-mono">{{ m.district_name or 'At-Large' }}</div>

        {% if m.attendance_pct is defined and m.attendance_pct is not none %}
          <div class="cc-stats">
            <span class="cc-attendance">
              <span class="cc-stat-label t-mono">Attend.</span>
              <span class="cc-stat-value t-tnum">{{ m.attendance_pct }}%</span>
            </span>
            <span class="cc-alignment">
              <span class="cc-stat-label t-mono">Align.</span>
              <span class="cc-stat-value t-tnum">{{ m.alignment_pct or '—' }}%</span>
            </span>
          </div>
        {% endif %}

        <div class="cc-foot t-mono">
            <span>View record →</span>
        </div>
    </div>
</button>
```

(Restyle preserves the hx-get / hx-target / hx-swap attrs. Task 9 removes them.)

### Step 4: Update CSS in `src/docket/web/static/layout.css`

- [ ] Add baseball-card layout rules to `.cc`, `.cc-body`, `.cc-stats`, `.cc-stat-label`, `.cc-stat-value`. Implementer composes the visual using P1 tokens.

### Step 5: Run all tests

- [ ] Run:

```bash
venv/bin/pytest tests/ -q
```

Expected: all green.

### Step 6: 🛑 HUMAN VISUAL REVIEW

- [ ] Boot Flask. Inspect council strips on the overview and the council roster page (attendance/alignment will NOT render yet — they're only rendered if data is passed; consumers don't pass them in P2b):

```bash
PORT=5001 venv/bin/flask --app docket.web run --port 5001 &
sleep 2
open "http://localhost:5001/al/birmingham/"
open "http://localhost:5001/al/birmingham/council/"
```

User confirms restyled card renders without attendance/alignment cleanly. GO or REVISE.

```bash
kill %1
```

### Step 7: Commit

- [ ] Stage and commit:

```bash
git add src/docket/web/templates/partials/council_card.html \
        src/docket/web/static/layout.css \
        tests/web/test_partials_visual_refactor.py
git commit -m "style(council_card): baseball-card pattern + optional attendance/alignment"
```

---

## Task 8: Make rail conditional in `base.html` + wire `city_overview` to provide `source_rail`

**Why this is separate:** This is the **structural rail switch**. After this task, the right-rail aside renders only on the overview page (`city.html`); every other page renders no rail. Mobile source sheet is also gated to overview-only. **`bottom_tabs.html` stays site-wide as an unconditional include** — it's the primary mobile nav (City / Meetings / Topics / Council / More); gating it would trap mobile users on every sub-page.

**Critical:** `rail_meeting()` / `rail_member()` routes still exist and the hx-get calls in card templates still fire — Task 9 removes those. In the intermediate state between Task 8 and Task 9, clicking a card on a non-overview page issues an hx-get to a still-valid route, but there's no `#source-rail` element in the DOM, so HTMX silently fails. This is acceptable as an intermediate state within the same PR.

**Files:**
- Modify: `src/docket/web/templates/base.html` — wrap rail aside + mobile source sheet in `{% block rail %}` / `{% block mobile_chrome %}` blocks (overridden only by `city.html`). **`bottom_tabs.html` stays as an unconditional include** — it's site-wide primary mobile nav.
- Modify: `src/docket/web/templates/city.html` — override the rail block to include `source_rail` with `kpi_stats`.
- Modify: `src/docket/web/public.py` — `city_overview()` builds `kpi_stats` and passes `show_rail=True` to the template.

### Step 1: Decide the conditional pattern

Two reasonable approaches:

**A. Context-flag pattern:** view function passes `show_rail=True/False`; base.html does `{% if show_rail %}…{% endif %}`. Pro: explicit. Con: every view that wants no rail does nothing; every view that wants a rail explicitly passes the flag, which means `city_overview` is the only one that opts in.

**B. Jinja block override pattern:** base.html declares `{% block rail %}{% endblock %}` empty; city.html overrides it to include `source_rail`. Pro: idiomatic Jinja; no view-function changes. Con: mobile sheet + bottom tabs need a separate block, OR the same block wraps all three.

**Decision: B (block override).** It keeps view functions clean and matches the existing `{% block content %}` pattern. The mobile source sheet goes in a second block `{% block mobile_chrome %}` overridden by city.html only. **`bottom_tabs.html` stays as an unconditional include outside both blocks** — site-wide primary mobile nav.

### Step 2: Write a failing test

- [ ] Add to `tests/web/test_base_rail_conditional.py` (create if missing):

```python
def test_overview_renders_source_rail(client):
    """City overview page renders the source rail aside."""
    resp = client.get("/al/birmingham/")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert 'id="source-rail"' in html
    assert 'source-rail-kpis' in html  # the kpi_explainer stack rendered


def test_non_overview_page_has_no_rail(client):
    """Meetings list, search, council roster, topic detail, meeting detail
    must NOT render the rail aside (overview-only rule)."""
    for path in [
        "/al/birmingham/meetings/",
        "/al/birmingham/council/",
        "/al/birmingham/topics/",
        "/search?q=demolition",
    ]:
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} returned {resp.status_code}"
        html = resp.data.decode()
        assert 'id="source-rail"' not in html, f"{path} still rendered the rail"


def test_non_overview_page_has_no_mobile_sheet(client):
    """Source sheet is gated to overview-only; bottom_tabs is NOT gated
    (site-wide primary mobile nav — gating would trap mobile users)."""
    resp = client.get("/al/birmingham/meetings/")
    html = resp.data.decode()
    assert 'class="source-sheet' not in html, "source_sheet should be overview-only"
    assert 'class="bottom-tabs' in html, "bottom_tabs must stay site-wide"
```

### Step 3: Run; verify failures

- [ ] Run:

```bash
venv/bin/pytest tests/web/test_base_rail_conditional.py -v
```

Expected: 3 FAILs (current `base.html` renders rail + sheet + tabs unconditionally).

### Step 4: Implement `base.html` block structure

- [ ] Update `src/docket/web/templates/base.html`:

```html
<body>
    {% block body %}
    <div class="app">
        <main class="app-main">
            {% include "partials/masthead.html" %}
            {% block content %}{% endblock %}
            {% include "partials/footer.html" %}
        </main>
        {# Rail = overview-only (P2b). Pages that want a rail override `block rail`. #}
        {% block rail %}{% endblock %}
    </div>

    {# Mobile source sheet — overview-only (paired with desktop rail). #}
    {% block mobile_chrome %}{% endblock %}

    {# Bottom tabs — site-wide primary mobile nav. NOT gated. #}
    {% include "partials/bottom_tabs.html" %}
    {% endblock %}

    <script src="{{ url_for('static', filename='sheet.js') }}" defer></script>
</body>
```

Note: the `<div class="app-rail"><aside …>…</aside></div>` block, plus the `source_sheet` + `bottom_tabs` includes, are moved OUT of the default and INTO `city.html`'s overrides.

### Step 5: Add the overview's rail block to `city.html`

- [ ] In `src/docket/web/templates/city.html`, add (right after the existing `extends "base.html"` and before `{% block content %}`):

```jinja
{% block rail %}
<div class="app-rail">
    <aside class="rail" aria-label="Source of truth" id="source-rail">
        {% include "partials/source_rail.html" %}
    </aside>
</div>
{% endblock %}

{% block mobile_chrome %}
{# bottom_tabs.html is NOT included here — it stays in base.html as a site-wide include. #}
{% include "partials/source_sheet.html" %}
{% endblock %}
```

### Step 6: Wire `city_overview()` to pass `kpi_stats`

- [ ] In `src/docket/web/public.py`, find `city_overview()` (line 82 per CLAUDE.md). At the end of the function (after all existing data prep), build `kpi_stats`. **Use the four KPIs from spec line 153**. The `sql_display` strings are rendered as-is to citizens in the KPI explainer card (no parameter binding happens client-side), so they must be **human-readable with the actual filter value interpolated** — not the `%s` driver placeholder, which would render as literal text to the user.

```python
mid = municipality.id
kpi_stats = [
    {
        'label': 'Meetings (lifetime)',
        'value': query.count_meetings_total(mid),
        'sub': f"Since {query.min_meeting_year(mid)}",
        'sql_display': f"SELECT count(*) FROM meetings WHERE municipality_id = {mid}",
    },
    {
        'label': 'Agenda items YTD',
        'value': query.count_agenda_items_ytd(mid),
        'sub': None,
        'sql_display': (
            f"SELECT count(*) FROM agenda_items ai "
            f"JOIN meetings m ON m.id = ai.meeting_id "
            f"WHERE m.municipality_id = {mid} "
            f"AND m.date >= date_trunc('year', now())"
        ),
    },
    {
        'label': 'Votes YTD',
        'value': query.count_votes_ytd(mid),
        'sub': None,
        'sql_display': (
            f"SELECT count(*) FROM votes v "
            f"JOIN meetings m ON m.id = v.meeting_id "
            f"WHERE m.municipality_id = {mid} "
            f"AND m.date >= date_trunc('year', now())"
        ),
    },
    {
        'label': 'Dollars (pending / settled)',
        'value': query.format_pending_vs_settled_dollars(mid),
        'sub': None,
        'sql_display': (
            f"SELECT sum(dollars_total) FROM agenda_items ai "
            f"JOIN meetings m ON m.id = ai.meeting_id "
            f"WHERE m.municipality_id = {mid}"
        ),
    },
]
```

**Safety note:** `municipality.id` is an integer pulled from the database (not user-controlled input). f-string interpolation here is for display only — these strings are never executed as SQL. The actual queries use parameterized helpers (`query.count_*`), which is the safe path. Still, the implementer should add a one-line comment in `public.py` noting that `sql_display` strings are display-only to prevent future "helpful" refactors that try to execute them.

The `count_*` and `format_*` query helpers may not exist yet. If a helper is missing, **inline the SQL** in `public.py` for P2b (the spec is fine with hardcoded SQL display strings; the actual queries should still be real). Pass `kpi_stats=kpi_stats` and `meeting_count=…` to `render_template`.

**Per-feedback memory `feedback_explain_at_scale.md`:** before merge, run an in-transaction EXPLAIN on Railway against synthetic-scale data for each new aggregation. P3 will use these queries on the city overview; verify they're fast before P3 builds on them.

### Step 7: Run tests; iterate

- [ ] Run:

```bash
venv/bin/pytest tests/ -q
```

Some tests may fail because `city_overview()` now requires the `kpi_stats` data. Update test fixtures if needed (the test client already exercises the route, so the route must succeed end-to-end).

Expected after fixing: all green, including the new `tests/web/test_base_rail_conditional.py`.

### Step 8: 🛑 HUMAN VISUAL REVIEW

- [ ] Boot Flask. Confirm rail only renders on city overview:

```bash
PORT=5001 venv/bin/flask --app docket.web run --port 5001 &
sleep 2
open "http://localhost:5001/al/birmingham/"        # rail visible, 4 KPI explainers
open "http://localhost:5001/al/birmingham/meetings/"   # NO rail; layout reflows or has empty column
open "http://localhost:5001/al/birmingham/council/"    # NO rail
open "http://localhost:5001/search?q=demolition"        # NO rail
```

User confirms:
- Overview: rail renders with provenance section + KPI explainer stack, no double-scroll (P2a follow-up #3).
- Non-overview: no rail, layout doesn't break (the `app-rail` track may render empty space — that's expected; P3 collapses it).
- Mobile: source_sheet only on overview; **bottom_tabs visible on every page** — tap each tab from a sub-page (e.g., `/meetings/`) and confirm navigation works.

GO or REVISE.

```bash
kill %1
```

### Step 9: Commit

- [ ] Stage and commit:

```bash
git add src/docket/web/templates/base.html \
        src/docket/web/templates/city.html \
        src/docket/web/public.py \
        tests/web/test_base_rail_conditional.py
git commit -m "feat: rail = overview-only; wire city_overview to source_rail kpi_stats"
```

---

## Task 9: Remove dead `hx-get` rail calls from page templates

**Why this is separate:** The hx-get/hx-target attrs in six template call sites now point at routes whose response can't land (no `#source-rail` element on non-overview pages). Removing them tidies the markup and decouples the templates from the routes being deleted in Task 10. Cards retain navigation via their existing `<a href>` wrappers — verify per template.

**Files:**
- Modify: `src/docket/web/templates/city.html` (6 spots) — lines 157, 170, 202, 248, 310, 390 per the audit above. **City.html does still render the rail (Task 8), but the rail is now STATIC** — meeting/member-row clicks no longer morph the rail. So even on the overview page, these hx-gets are dead.
- Modify: `src/docket/web/templates/meetings.html` — line 62 area.
- Modify: `src/docket/web/templates/search.html` — line 110 area.
- Modify: `src/docket/web/templates/topic_detail.html` — line 73 area.
- Modify: `src/docket/web/templates/partials/council_card.html` — drop hx-get from `<button class="cc">`. Keep it as a `<button class="cc" type="button">` (no-op until P4). **Do NOT convert to `<a href="#">`** — that causes a jump-to-top viewport snap on click. **Decision:** in P2b, where should clicking a council card go? Memory says "Member detail = NEW full page (`/al/<slug>/council/<member_id>/`)" — that route doesn't exist until P4. Picked option:
  - **`<button class="cc" type="button">` (no-op).** Retains visual styling (selector unchanged), no nav, no jump-to-top, no form-submit. P4 swaps `<button>` → `<a href="{{ url_for('public.member_detail', ...) }}">` when the route lands.
  - Rejected: `<a href="#" class="cc">` because the empty fragment scroll-snaps to top — jarring UX.
  - Rejected: `<a href="/al/<slug>/council/">` (back to roster) because clicking a roster card to re-load the roster is meaningless feedback.
- Modify: `src/docket/web/templates/meeting_detail.html` — remove `{% include "partials/rail_meeting.html" %}` at line 5. (This is the in-page rail include for the meeting page; with Task 8 the page has no rail at all, so the include is dead.)

### Step 1: Inventory each call site + verify card has alternative navigation

- [ ] For each template + line, the implementer reads ~20 lines of context. Goal: confirm the card already has an `<a href>` wrapping it (or inside it) that handles navigation when the hx-get is removed. If a template's card has **no** href and relies entirely on hx-get for navigation, the implementer adds an `<a href>` wrapping the relevant content (target: the appropriate meeting detail URL via `url_for('public.meeting_detail', …)`).

  Compile findings inline:

  | File | Line | Existing `<a href>`? | If not, what to add |
  |------|------|---------------------|---------------------|
  | city.html | 157 | (audit) | (audit) |
  | city.html | 170 | (audit) | (audit) |
  | city.html | 202 | (audit) | (audit) |
  | city.html | 248 | (audit) | (audit) |
  | city.html | 310 | (audit) | (audit) |
  | city.html | 390 | (audit) | (audit) |
  | meetings.html | 62 | (audit) | (audit) |
  | search.html | 110 | (audit) | (audit) |
  | topic_detail.html | 73 | (audit) | (audit) |
  | council_card.html | 5 | n/a — see decision above | Keep `<button class="cc" type="button">` (no-op) |
  | meeting_detail.html | 5 | n/a — drop include | — |

### Step 2: Write a regression test asserting cards are clickable

- [ ] Add to `tests/web/test_card_navigation.py` (create if missing):

```python
def test_overview_meeting_cards_have_href(client):
    """Each meeting card on the city overview must be wrapped in or contain
    an <a href> after the hx-get removal — otherwise the card becomes
    a dead element."""
    resp = client.get("/al/birmingham/")
    html = resp.data.decode()
    # Heuristic: count meeting card containers and confirm each one nests an <a href>
    # Implementer adjusts the selector based on actual card class:
    import re
    cards = re.findall(r'<article[^>]*class="[^"]*meeting[_-]card[^"]*"[^>]*>.*?</article>',
                       html, flags=re.S)
    assert cards, "no meeting cards found on overview"
    for c in cards:
        assert 'href=' in c, f"card has no href: {c[:100]}"


def test_no_dead_hx_get_to_rail_meeting(client):
    """No template should still hx-get to rail_meeting / rail_member after Task 9."""
    for path in [
        "/al/birmingham/", "/al/birmingham/meetings/",
        "/al/birmingham/council/", "/search?q=demolition",
        "/al/birmingham/topics/public_safety",
    ]:
        resp = client.get(path)
        html = resp.data.decode()
        assert "rail_meeting" not in html, f"{path} still has rail_meeting hx-get"
        assert "rail_member" not in html, f"{path} still has rail_member hx-get"
```

### Step 3: Run; verify failure

- [ ] Run:

```bash
venv/bin/pytest tests/web/test_card_navigation.py -v
```

Expected: at least `test_no_dead_hx_get_to_rail_meeting` FAILs.

### Step 4: Remove hx-get attrs, add missing hrefs

- [ ] Per the inventory in Step 1, edit each call site. Use targeted `Edit` calls (not `replace_all`) to keep diffs reviewable. For each: remove the `hx-get="…"`, `hx-target="#source-rail"`, `hx-swap="innerHTML"` attrs from the element. If the element was a `<button class="…">` and now has no other purpose, convert to `<a class="…" href="…">` — for cards, the href points at the meeting detail page (`url_for('public.meeting_detail', meeting_id=…)`).
- [ ] In `meeting_detail.html`, delete line 5: `{% include "partials/rail_meeting.html" %}`.
- [ ] In `council_card.html`, strip the three `hx-*` attrs from `<button class="cc">` and add `type="button"` to prevent any default form-submit. Keep the element as `<button class="cc" type="button">` — click is a silent no-op until P4 swaps it to `<a href="…/council/<member_id>/">`.

### Step 5: Run tests

- [ ] Run:

```bash
venv/bin/pytest tests/ -q
```

Expected: all green.

### Step 6: 🛑 HUMAN VISUAL REVIEW — interaction sweep

- [ ] Boot Flask. Click around each page and confirm:
  - Meeting cards navigate to the meeting detail page (not just trigger an hx-get).
  - Council cards on overview and roster page are visually unchanged. Click does **nothing** (no jump-to-top, no navigation) — silent no-op until P4 wires the member-detail route.
  - No browser console errors about 404s on `/_rail/meeting/N` or `/_rail/member/N`.

```bash
PORT=5001 venv/bin/flask --app docket.web run --port 5001 &
sleep 2
open "http://localhost:5001/al/birmingham/"
# In each page: click a meeting card → should navigate to /al/birmingham/meetings/<id>/
# Open browser DevTools → Console → confirm no 404s
```

GO or REVISE.

```bash
kill %1
```

### Step 7: Commit

- [ ] Stage and commit:

```bash
git add src/docket/web/templates/city.html \
        src/docket/web/templates/meetings.html \
        src/docket/web/templates/search.html \
        src/docket/web/templates/topic_detail.html \
        src/docket/web/templates/meeting_detail.html \
        src/docket/web/templates/partials/council_card.html \
        tests/web/test_card_navigation.py
git commit -m "refactor: drop dead hx-get rail calls; cards navigate via href"
```

---

## Task 10: Delete `rail_meeting.html`, `rail_member.html`, and `rail_default()` / `rail_meeting()` / `rail_member()` view functions

**Why this is separate:** Pure deletion. Final cleanup. After Tasks 8+9 there are zero callers of these partials and zero hx-get targets for these routes; this task removes the now-dead code.

**Files:**
- Delete: `src/docket/web/templates/partials/rail_meeting.html`
- Delete: `src/docket/web/templates/partials/rail_member.html`
- **Keep:** `src/docket/web/templates/partials/rail_default.html` (still included by `source_rail.html` and `source_sheet.html`).
- Modify: `src/docket/web/public.py` — delete `rail_default()` (lines 860-871), `rail_meeting()` (lines 874-889), `rail_member()` (lines 892-903). Their route decorators go with them.
- Modify: tests that exercise those routes — drop entries.

### Step 1: Confirm zero remaining callers

- [ ] Run:

```bash
grep -rn "rail_meeting\|rail_member\|public\.rail_default" src/docket/ tests/ --include="*.py" --include="*.html"
```

Expected: only the definitions in `public.py` (which we're about to delete) and `rail_meeting.html`/`rail_member.html` themselves (also about to be deleted) match. If there are other matches, fix them before proceeding.

### Step 2: Write a test asserting routes return 404 after deletion

- [ ] Add to `tests/web/test_base_rail_conditional.py`:

```python
def test_rail_routes_404_after_p2b(client):
    """rail_default / rail_meeting / rail_member endpoints removed in P2b."""
    # Use a known-valid municipality slug + ids
    assert client.get("/al/birmingham/_rail/default").status_code == 404
    assert client.get("/al/birmingham/_rail/meeting/1").status_code == 404
    assert client.get("/al/birmingham/_rail/member/1").status_code == 404
```

### Step 3: Run; verify failure

- [ ] Run:

```bash
venv/bin/pytest tests/web/test_base_rail_conditional.py -k "404_after_p2b" -v
```

Expected: FAIL — routes still return 200 (or 404 only if the slug/id is invalid; we need them to 404 unconditionally because the route doesn't exist).

### Step 4: Delete the view functions

- [ ] Open `src/docket/web/public.py`. Delete lines 857-903 (the entire `--- HTMX rail partials ---` section). Also delete any preceding comment header.

### Step 5: Delete the partials

- [ ] Run:

```bash
rm src/docket/web/templates/partials/rail_meeting.html
rm src/docket/web/templates/partials/rail_member.html
```

### Step 6: Run full pytest

- [ ] Run:

```bash
venv/bin/pytest tests/ -q
```

Expected: all green, including the new 404 test.

### Step 7: Visual smoke

- [ ] Boot Flask. Click through the same pages as Task 9's review. Confirm no regressions.

```bash
PORT=5001 venv/bin/flask --app docket.web run --port 5001 &
sleep 2
curl -sf -o /dev/null -w "%{http_code}\n" http://localhost:5001/al/birmingham/_rail/default
# expect 404
curl -sf -o /dev/null -w "%{http_code}\n" http://localhost:5001/al/birmingham/_rail/meeting/1
# expect 404
curl -sf -o /dev/null -w "%{http_code}\n" http://localhost:5001/al/birmingham/_rail/member/1
# expect 404
kill %1
```

### Step 8: Commit

- [ ] Stage and commit:

```bash
git add -A   # captures the deletes
git commit -m "chore: retire rail_meeting/rail_member partials + rail_*() view functions"
```

(The `-A` is safe here because there are no untracked files we'd accidentally stage; verify with `git status` first.)

---

## Task 11: Final verification + visual sweep + open PR

**Why this is separate:** Lands the PR with a clear summary of every visible change + every cleanup. Final visual sweep across every restyled surface to catch any cross-task interaction issues.

**Files:**
- None modified — verification + PR-open only.

### Step 1: Run the full suite from a cold start

- [ ] Run:

```bash
venv/bin/pytest --ignore=tests/live -q 2>&1 | tail -3
```

Expected: all green. Note the final test count (P2b adds ~10-15 new tests across the 10 tasks).

### Step 2: Full-site visual sweep

- [ ] Boot Flask. Walk every public surface and screenshot:

```bash
PORT=5001 venv/bin/flask --app docket.web run --port 5001 &
sleep 2
open "http://localhost:5001/"
open "http://localhost:5001/al/birmingham/"
open "http://localhost:5001/al/birmingham/meetings/"
open "http://localhost:5001/al/birmingham/council/"
open "http://localhost:5001/al/birmingham/topics/"
open "http://localhost:5001/al/birmingham/topics/public_safety"
open "http://localhost:5001/al/birmingham/property_recovery"
open "http://localhost:5001/search?q=demolition"
open "http://localhost:5001/coverage/"
open "http://localhost:5001/about/how-we-read-minutes/"
```

User reviews each page for:
- Item cards in LegislationCard idiom (Task 6)
- Council cards in baseball-card pattern (Task 7)
- Restyled badge chips inside cards (Task 5)
- Restyled dollar tier inside cards once `meeting_card` is consumed (Task 4 — not yet visible in P2b since meeting_card isn't on any page; placeholder verification)
- Rail visible only on the overview page (Task 8)
- No broken hx-gets in browser console (Task 9 + Task 10)

Plus mobile width:

```bash
# In Chrome / Safari DevTools, set viewport to 375px wide and re-walk the same pages.
```

User confirms layouts adapt cleanly. GO or REVISE.

```bash
kill %1
```

### Step 3: Run an in-transaction EXPLAIN on Railway for the new kpi_stats aggregations

- [ ] Per `feedback_explain_at_scale.md`, run:

```bash
PGURL=$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-) \
  /opt/homebrew/opt/postgresql@18/bin/psql "$PGURL" -c "
  BEGIN;
  EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM meetings WHERE municipality_id = 1;
  EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM agenda_items
    WHERE municipality_id = 1 AND created_at >= date_trunc('year', now());
  -- repeat for the other two queries from Task 8
  ROLLBACK;
"
```

Expected: each query completes under 50ms with index usage. If not, add a covering index in a small migration before merge.

### Step 4: Push the branch and open the PR

- [ ] From the worktree (NOT canonical):

```bash
git push -u origin worktree-visual-refactor-p2b
gh pr create --title "Visual refactor — Phase 2b (restyles + rail rewire)" --body "$(cat <<'EOF'
## Summary
- Restyles 4 partials consumed by current pages: `card_smart_brevity` / `card_v2_fallback` (LegislationCard idiom), `council_card` (baseball-card), `badge_chip` (P1 tokens), `dollar_tier` (P1 tokens + monospace amount + explicit `amount` arg).
- Rail switches to overview-only via `{% block rail %}` override pattern in `base.html`. City overview renders `source_rail` (provenance + 4 KPI explainers stacked); every other page renders no rail. Mobile sheet + bottom tabs also gated to overview.
- Retires the morphing-rail pattern: deletes `rail_meeting.html`, `rail_member.html`, plus `rail_default()` / `rail_meeting()` / `rail_member()` view functions and their routes. Strips dead `hx-get`/`hx-target` attrs from 6 template call sites; cards now navigate via `<a href>`.

## Follow-ups resolved (from P2a)
- #2: extracted `.stat-card-base`, replaced redundant `font-feature-settings` with `t-tnum`, normalized letter-spacing.
- #3: verified no double-scroll in `source_rail` (rail_default content nests cleanly).
- #4: `dollar_tier` now takes explicit `amount` arg instead of caller's implicit `{% set %}` context.

## Follow-ups parked
- #1 `--type-hero` 64px-vs-72px — for P3 plan (no P2b partial consumes `--type-hero`).
- #5/#6/#7 — for P3.

## Test plan
- [ ] Full pytest green (final count posted in CI).
- [ ] In-transaction EXPLAIN on Railway shows each new aggregation under 50ms.
- [ ] Visual sweep across overview / meetings / council / search / topics / category landing / coverage on desktop + mobile.
- [ ] After merge: deploy via `railway up --service docket-web --detach`, then verify on production at https://docket.pub/al/birmingham/.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

### Step 5: Update memory

- [ ] After PR opens, update `project_visual_refactor_2026_05_14.md` to mark P2b as "PR open" (and on merge → "shipped"). Note in memory:
  - PR number and merge SHA (post-merge)
  - Which P2a follow-ups #2, #3, #4 are resolved
  - Which follow-ups (#1, #5, #6, #7) remain for P3
  - Confirm `--type-hero` decision is now a P3 blocker

---

## Self-review checklist (run before handing this plan to a controller)

**1. Spec coverage:**
- ✅ Phase 2 restyles: all four partials covered (Tasks 4-7).
- ✅ Phase 2 deletes: rail_meeting, rail_member, view functions (Task 10).
- ✅ source_rail base.html wire-in (Task 8).
- ✅ rail = overview-only rule (Task 8 + 9).
- ✅ source_sheet + bottom_tabs gated to overview (Task 8).
- ⚠️ `--type-hero` mismatch — intentionally parked for P3, called out in plan header.

**2. P2a follow-ups:**
- ✅ #2 (CSS bloat) — Task 2.
- ✅ #3 (source_rail double-scroll) — verified in Task 8 visual review.
- ✅ #4 (dollar_tier implicit context) — Task 3.
- ⚠️ #1, #5, #6, #7 — parked for P3.

**3. Placeholder scan:**
- ✅ No "TBD" / "fill in details" — every step has concrete content.
- ⚠️ Task 9 Step 1 inventory table marked "(audit)" — implementer fills in during execution (it's not a placeholder for a *decision*, it's data the implementer gathers).
- ⚠️ Task 6 Step 4 has an implementer judgment call about exact class names (`.ls-card-*` vs alternative); the visual review gate covers it.

**4. Type consistency:**
- ✅ `kpi_stats` shape (`{label, value, sub, sql_display}`) matches what `source_rail.html` already expects from P2a.
- ✅ `amount` arg on `dollar_tier` matches `meeting_card.html` and `tests/unit/test_dollar_tier.py`.
- ✅ Council card optional fields `attendance_pct` / `alignment_pct` — rendered only if provided; consumers don't provide in P2b.

**5. Ordering safety:**
- ✅ Each task leaves the site in a working state.
- ✅ Restyles (Tasks 4-7) come before rail rewire (Task 8) so visual review can catch restyle issues independently of layout issues.
- ✅ Route deletions (Task 10) come last, after hx-get callers are gone (Task 9).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-15-visual-refactor-phase-2b.md`. Two execution options:

**1. Subagent-Driven (recommended)** — Controller dispatches a fresh sonnet subagent per task with the per-task review gates baked in. P2b has 10 substantive tasks + 1 PR-open task; expect ~3-4 hours of wall time with the human visual reviews.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`. Batch execution with checkpoint pauses at each human-review gate. Faster for the no-review tasks (1, 2, 3, 10, 11) but the same total time for the visual-review tasks (4-9).

Which approach?
