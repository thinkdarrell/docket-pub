# Visual Refactor — Phase 2a (Component Library, additive partials) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Each task is dispatched to a **fresh sonnet implementer subagent**, then reviewed by a **fresh sonnet spec reviewer**, then by a **fresh sonnet code-quality reviewer**, before marking the task complete. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Model floor: sonnet.** P1 (foundation) tried haiku for one implementer task and the implementer hallucinated its verification narrative (claimed curl output that couldn't have existed). Sonnet floor for *any* task whose steps include "check output X and report it back."
>
> **🛑 HUMAN VERIFICATION GATES.** P2a is **purely additive** — every new partial is a file that isn't consumed by any rendered page yet. There is **no visible change anywhere on the site** in P2a. The single human gate is at Task 8 (final verification): confirm a sweep of production pages still looks identical to pre-P2a. Programmatic verification is pytest snapshot tests against each partial + curl-for-200 across every public route.

**Goal:** Land the 6 new Jinja partials that P3+ pages will consume — `num_stat`, `freshness_chip`, `topic_row`, `kpi_explainer`, `meeting_card`, `source_rail` — each with a pytest snapshot test that renders the partial standalone, asserts key DOM structure, and proves the partial doesn't break when context is missing. **Zero impact on rendered pages in P2a** (no template, view function, or CSS-call-site changes that would alter what's currently shown).

**Architecture:**
- Strictly **additive**: P2a creates new files, never modifies a rendered template. Verification is pytest-only (no Flask serving needed; partials don't appear on any page yet).
- **Partial smoke tests** are introduced as a pattern in Task 1 — a tiny pytest helper that lets us render a single partial with a sample context and assert on the output. The pattern lives in `tests/web/conftest.py` so P3+ can reuse it.
- **P2b (the visible-change phase)** — restyling `_card_shell.html` / `council_card.html` / `badge_chip.html` / `dollar_tier.html`, making the rail conditional in `base.html`, deleting `rail_meeting.html` + `rail_member.html` + their routes, switching `base.html` to include `source_rail` instead of `rail_default` — gets its own plan written after P2a ships. Splitting at this seam keeps the visible-change PR small and reviewable, and P2a can ship in a couple of hours.

**Tech Stack:**
- Jinja2 templates (no framework changes)
- Pytest with Flask's `test_request_context` for partial rendering (provides both app + request context so partials that call `url_for` work)
- CSS custom properties from P1 (`--type-*`, `--space-*`) consumed in partial CSS
- No new Python dependencies, no migrations, no JS changes

**Spec:** `docs/superpowers/specs/2026-05-14-visual-refactor-design.md` (Phase 2 section)
**Predecessor:** P1 shipped via PR #50 (merge `59d3e4a`), type-scale + spacing-scale tokens + footer grid fix live on Railway.

**Open decision parked for P3 (NOT a P2a blocker):**
- `--type-hero` is declared at 64px in `styles.css` (per spec) but `.hero-title` in `layout.css:150` is currently 72px. P2a partials don't consume `--type-hero` (no new partial uses hero-sized text), so this can wait. Decide in the P3 plan whether to shrink the live hero to 64px or update the token to 72px before P3's CityLead partial lands.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `tests/web/conftest.py` | Modify or create | Add a pytest fixture `render_partial(name, **ctx)` that renders a single Jinja partial with the supplied context inside a Flask `test_request_context` (required for partials that call `url_for`). Used by every new test in P2a and by P3+. |
| `tests/web/test_partials_visual_refactor.py` | Create | One test function per new partial, each asserting render success + presence of key DOM elements. |
| `src/docket/web/templates/partials/num_stat.html` | Create | Reusable KPI / NumStat block — label + value + optional sub. |
| `src/docket/web/templates/partials/freshness_chip.html` | Create | Status pill — state dot + last_synced timestamp + link to `/al/<slug>/source-health/`. |
| `src/docket/web/templates/partials/topic_row.html` | Create | Horizontal scroll-snap pill row. Args: `topics` list. |
| `src/docket/web/templates/partials/kpi_explainer.html` | Create | Single KPI card with collapsible SQL display. Args: `label`, `value`, `sub`, `sql_display`. |
| `src/docket/web/templates/partials/meeting_card.html` | Create | Two-variant card (`strip` for horizontal scroll, `grid` for vertical list). Args: `meeting`, `variant`. |
| `src/docket/web/templates/partials/source_rail.html` | Create | The new desktop rail partial. Includes existing `rail_default.html`'s content (via `{% include %}`) and adds a KPI-explainer stack section. **Lives alongside `rail_default.html` in P2a — base.html is not yet pointed at source_rail; that switch happens in P2b.** |
| `src/docket/web/static/layout.css` | Modify | Add CSS for the new partials (`.num-stat`, `.freshness-chip`, `.topic-row`, `.kpi-explainer`, `.meeting-card`, `.source-rail`). All rules scoped to the new class names — no existing selectors modified. |
| `src/docket/web/static/mobile.css` | Modify | Add mobile-specific overrides for the new partials at `<768px` (KPI strip horizontal scroll, meeting-card strip width, etc.). All in a new "Phase 2 partials" section at the end of the file. |

**No file deletions in P2a.** All cleanup (deleting `rail_default.html`, `rail_meeting.html`, `rail_member.html`, removing their routes) is P2b.

---

## Task 1: Worktree setup + Jinja partial test fixture

**Why this is separate:** P2a needs a tiny pytest helper (`render_partial`) that the next 6 tasks reuse. Landing it first means every subsequent task can drop a single-line test instead of reinventing the rendering harness.

**Files:**
- Create or modify: `tests/web/conftest.py`

### Step 1: Controller — create worktree

- [ ] Run from canonical repo (`/Users/darrellnance/docket-pub`, on `main`):

```bash
git checkout main && git pull --ff-only origin main
```

Use the platform's native worktree tool (e.g., `EnterWorktree`) to create an isolated workspace. Branch name: `worktree-visual-refactor-p2a`.

After entering the worktree, symlink the canonical venv + `.env` so pytest can run:

```bash
ln -s /Users/darrellnance/docket-pub/venv venv
ln -s /Users/darrellnance/docket-pub/.env .env
```

Confirm clean baseline (deselecting the pre-existing env-blocked test from P1):

```bash
venv/bin/pytest --ignore=tests/live --deselect tests/unit/test_ai_worker_run.py::test_run_once_refuses_over_budget -q 2>&1 | tail -3
```

Expected: `1536 passed`. Same baseline as P1.

### Step 2: Dispatch implementer subagent (sonnet)

- [ ] Send this exact prompt to a fresh sonnet implementer:

> You are the implementer subagent for docket.pub visual-refactor Phase 2a Task 1. Working directory: `/Users/darrellnance/docket-pub/.claude/worktrees/worktree-visual-refactor-p2a`. Branch: `worktree-visual-refactor-p2a`. `cd` into the worktree at the start of every shell command — subagents inherit a cwd that may not be the worktree.
>
> **Context.** P2a creates 6 new Jinja partials that aren't consumed by any rendered page yet. Each partial gets a pytest "smoke render" test. This task sets up the fixture every later test will use. The pattern lives at `tests/web/conftest.py` so P3+ can reuse it.
>
> **Check first whether `tests/web/conftest.py` already exists.** Run `ls tests/web/`. If `conftest.py` exists, you'll add a fixture to it. If not, create a new file. Either way, report the starting state in your final summary.
>
> **Spec.** Add a pytest fixture named `render_partial` that:
> - Returns a function with signature `render_partial(partial_path: str, **context) -> str` where `partial_path` is relative to the templates dir (e.g., `'partials/num_stat.html'`)
> - Renders the partial inside a Flask `app_context()` using the docket Flask app's Jinja env
> - Returns the rendered HTML string
> - Works for both standalone partials and partials that `{% extends %}` another template
>
> Use the existing app factory: `from docket.web import create_app`. The fixture should be `scope='function'` and yield the helper function. Look at existing test files like `tests/web/test_public.py` (if it exists) or `tests/test_smoke.py` for the app-creation pattern already in use in this codebase — match it.
>
> **TDD step before implementing the fixture itself:** write a tiny throwaway test in `tests/web/test_partials_visual_refactor.py` that uses the fixture to render `partials/footer.html` (which already exists and renders cleanly) and asserts the rendered HTML contains the string `docket.pub`. The footer template references `municipality` conditionally and `now` for the colophon date — pass `municipality=None, now=None` as context (or whatever sample values mirror what the production view passes). Run that test BEFORE implementing the fixture to confirm it fails for the right reason (`fixture 'render_partial' not found`).
>
> Once the fixture is in place and the smoke test passes, **leave the throwaway test in `test_partials_visual_refactor.py`** — it will be the file later tasks add to.
>
> **Verification:** Run `venv/bin/pytest tests/web/test_partials_visual_refactor.py -v 2>&1 | tail -10`. Expected: one test passes.
>
> Then run the deselected full suite: `venv/bin/pytest --ignore=tests/live --deselect tests/unit/test_ai_worker_run.py::test_run_once_refuses_over_budget -q 2>&1 | tail -3`. Expected: `1537 passed` (1536 baseline + 1 new).
>
> **Commit message:**
> ```
> test(partials): add render_partial pytest fixture for P2 component library
>
> Lets each new partial in P2a-onwards ship with a snapshot test that
> renders it standalone with a sample context. Pattern reused by P3+
> for partials consumed on real pages.
>
> Smoke test against existing partials/footer.html validates the fixture
> works with templates that have conditional logic.
> ```
>
> **Output format.** Status: DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED. Include the pytest tail verbatim. List any decisions you made (e.g., "conftest.py didn't exist, created it"). Do NOT proceed past this task.

### Step 3: Controller — verify implementer's claims directly

- [ ] After the implementer returns DONE, verify before dispatching reviewers:

```bash
ls tests/web/
cat tests/web/conftest.py | head -40
venv/bin/pytest tests/web/test_partials_visual_refactor.py -v 2>&1 | tail -10
venv/bin/pytest --ignore=tests/live --deselect tests/unit/test_ai_worker_run.py::test_run_once_refuses_over_budget -q 2>&1 | tail -3
git log --oneline -2
```

Expected: `conftest.py` contains a `render_partial` fixture; new test passes; suite at 1537 passed; one commit on top of the worktree base.

If anything is off, do NOT dispatch reviewers — dispatch a fix subagent with specifics.

### Step 4: Dispatch spec compliance reviewer (sonnet)

- [ ] Send this prompt to a fresh sonnet reviewer:

> You are the spec-compliance reviewer for Task 1 of docket.pub visual-refactor P2a. Worktree at `/Users/darrellnance/docket-pub/.claude/worktrees/worktree-visual-refactor-p2a`. Single commit on top of the worktree's base.
>
> **The spec for this task was:** add a `render_partial(partial_path, **context) -> str` pytest fixture in `tests/web/conftest.py` that renders a Jinja partial inside a Flask app_context using docket's app factory. Add one throwaway test in `tests/web/test_partials_visual_refactor.py` that uses the fixture against `partials/footer.html` and asserts presence of `docket.pub` in the output.
>
> Read the commit (`git -C <worktree> show HEAD`) and answer:
> 1. Is the fixture's signature exactly `(partial_path: str, **context) -> str`? Or something subtly different?
> 2. Is it `scope='function'`? Or longer-lived (would cache state across tests)?
> 3. Does it use the existing app factory (`create_app`) or invent a new app?
> 4. Is the throwaway test in `tests/web/test_partials_visual_refactor.py` (the file later tasks will add to)?
> 5. Anything **extra** added beyond the spec? Removing extras is part of compliance.
> 6. Anything **missing** vs the spec?
>
> Report COMPLIANT / NON_COMPLIANT plus specific issues. Be honest — don't pass compliance if anything is off-spec.

If NON_COMPLIANT: re-dispatch the implementer with the reviewer's specific feedback. Re-review. Repeat until COMPLIANT.

### Step 5: Dispatch code quality reviewer (sonnet)

- [ ] After spec compliance is ✓, send this prompt to a fresh sonnet reviewer:

> You are the code-quality reviewer for Task 1 of docket.pub visual-refactor P2a. Worktree at `/Users/darrellnance/docket-pub/.claude/worktrees/worktree-visual-refactor-p2a`. Single commit `git show HEAD`.
>
> Review the fixture and test for:
> 1. **App lifecycle.** Is the Flask app created once per test (matching `scope='function'`) or imported at module load? Test-isolation considerations.
> 2. **Context safety.** If `render_partial` is called with a context that's missing keys the template references, does it raise a clear error or silently produce broken HTML?
> 3. **Reuse fit.** Will this fixture work cleanly for partials that `{% extends %}` `_card_shell.html`? (P2b will test card variants this way.) If the answer is "needs more work," call it out as a P2b prerequisite.
> 4. **Conventions.** Does the file match the existing `tests/` style (imports, naming, docstring conventions)?
> 5. **Anything else worth fixing before this lands.**
>
> Report APPROVED / NEEDS_CHANGES with specific bullets.

If NEEDS_CHANGES: implementer fixes, reviewer re-reviews, until APPROVED.

### Step 6: Controller — mark task complete

- [ ] Update TaskList: Task 1 → completed.

---

## Task 2: `partials/num_stat.html` + test

**Why num_stat first:** smallest new partial, used by every subsequent partial as a reference for the test pattern.

**Files:**
- Create: `src/docket/web/templates/partials/num_stat.html`
- Modify: `tests/web/test_partials_visual_refactor.py`

### Step 1: Dispatch implementer subagent (sonnet)

- [ ] Send this prompt:

> You are the implementer subagent for docket.pub visual-refactor P2a Task 2. Working directory: `/Users/darrellnance/docket-pub/.claude/worktrees/worktree-visual-refactor-p2a`. `cd` in at the start of every shell command.
>
> **Context.** Creating a reusable NumStat partial — the label-over-value card used in inline KPI strips (P3 city overview), in meeting/member detail page headers (P4), and in source-health stats (P4). The partial is just declared here; nothing renders it yet on any page.
>
> **TDD: write the failing test first.** Add to `tests/web/test_partials_visual_refactor.py`:
>
> ```python
> def test_num_stat_renders_label_and_value(render_partial):
>     html = render_partial(
>         'partials/num_stat.html',
>         label='Meetings YTD',
>         value='42',
>     )
>     assert 'Meetings YTD' in html
>     assert '42' in html
>     assert 'num-stat' in html  # CSS hook class
>
> def test_num_stat_renders_sub_when_provided(render_partial):
>     html = render_partial(
>         'partials/num_stat.html',
>         label='Meetings',
>         value='1,003',
>         sub='Since 2017',
>     )
>     assert 'Since 2017' in html
>
> def test_num_stat_omits_sub_when_absent(render_partial):
>     html = render_partial(
>         'partials/num_stat.html',
>         label='Votes',
>         value='12',
>     )
>     # No <div class="num-stat-sub"> when sub is not passed.
>     assert 'num-stat-sub' not in html
>
> def test_num_stat_accent_modifier_class(render_partial):
>     html = render_partial(
>         'partials/num_stat.html',
>         label='Flagged',
>         value='4',
>         accent=True,
>     )
>     assert 'is-accent' in html
> ```
>
> Run: `venv/bin/pytest tests/web/test_partials_visual_refactor.py -v -k num_stat 2>&1 | tail -10`. All four should FAIL with template-not-found.
>
> **Implement the partial.** Create `src/docket/web/templates/partials/num_stat.html`:
>
> ```jinja
> {# NumStat partial — label + value + optional sub.
>    Spec: docs/superpowers/specs/2026-05-14-visual-refactor-design.md (P2/P3).
>    Args:
>      label  (str, required)  — e.g. "Meetings YTD"
>      value  (str|int, req.)  — pre-formatted (e.g. "1,003", "$12.4M")
>      sub    (str, optional)  — grounding text (e.g. "Since 2017")
>      accent (bool, optional) — adds .is-accent for visual emphasis
> #}
> <div class="num-stat{% if accent %} is-accent{% endif %}">
>   <div class="num-stat-label t-mono">{{ label }}</div>
>   <div class="num-stat-value t-display">{{ value }}</div>
>   {% if sub %}
>     <div class="num-stat-sub t-meta">{{ sub }}</div>
>   {% endif %}
> </div>
> ```
>
> **Add CSS.** Append to `src/docket/web/static/layout.css` (at the very end of the file, under a new comment `/* ── P2a partials ───────────────────────────────────────── */`):
>
> ```css
> /* ── P2a partials ───────────────────────────────────────── */
>
> .num-stat {
>   display: flex;
>   flex-direction: column;
>   gap: var(--space-1);
>   padding: var(--space-3) var(--space-4);
>   border: 1px solid var(--rule);
>   border-radius: var(--radius);
>   background: var(--paper);
> }
> .num-stat-label {
>   font-size: var(--type-eyebrow);
>   letter-spacing: 0.12em;
>   text-transform: uppercase;
>   color: var(--ink-3);
> }
> .num-stat-value {
>   font-size: var(--type-mono-num);
>   font-family: var(--font-mono);
>   font-feature-settings: "tnum" 1, "lnum" 1;
>   color: var(--ink);
> }
> .num-stat-sub {
>   font-size: 11px;
>   color: var(--ink-3);
> }
> .num-stat.is-accent .num-stat-value {
>   color: var(--accent-ink);
> }
> ```
>
> **No mobile.css change yet.** This partial isn't on any page; mobile responsiveness is handled in P3 when it gets consumed.
>
> Run tests again: `venv/bin/pytest tests/web/test_partials_visual_refactor.py -v -k num_stat 2>&1 | tail -10`. All four should PASS.
>
> Run full suite: `venv/bin/pytest --ignore=tests/live --deselect tests/unit/test_ai_worker_run.py::test_run_once_refuses_over_budget -q 2>&1 | tail -3`. Expected: `1541 passed` (1537 baseline after Task 1 + 4 new).
>
> **Commit message:**
> ```
> feat(partials): add num_stat reusable NumStat partial
>
> Label + value + optional sub. Consumed by P3 city overview inline
> KPI strip and P4 detail-page headers (meeting/member/source-health).
> Not yet rendered on any page — declaration-only.
>
> Uses --type-eyebrow, --type-mono-num, --space-* tokens from P1.
> ```
>
> **Output format.** Status / pytest tails verbatim / decisions / halt.

### Step 2: Controller — verify directly

- [ ] After implementer returns DONE:

```bash
cat src/docket/web/templates/partials/num_stat.html
git diff src/docket/web/static/layout.css | tail -40
venv/bin/pytest tests/web/test_partials_visual_refactor.py -v -k num_stat 2>&1 | tail -10
venv/bin/pytest --ignore=tests/live --deselect tests/unit/test_ai_worker_run.py::test_run_once_refuses_over_budget -q 2>&1 | tail -3
```

Expected: partial exists, CSS appended at file end, 4 num_stat tests pass, suite at 1541 passed.

### Step 3: Spec reviewer (sonnet)

- [ ] Prompt verbatim:

> Spec compliance reviewer for P2a Task 2 (num_stat). Worktree at `/Users/darrellnance/docket-pub/.claude/worktrees/worktree-visual-refactor-p2a`. Read `git show HEAD`.
>
> Spec for this task: `partials/num_stat.html` accepts args `label`, `value`, optional `sub`, optional `accent`. Renders `.num-stat` container with `.num-stat-label` + `.num-stat-value` + optional `.num-stat-sub`. Accent flag adds `.is-accent` modifier on the container. CSS lives in `layout.css` under a new "P2a partials" section. Uses `--type-eyebrow`, `--type-mono-num`, `--space-*` tokens. Pytest tests cover: basic render, sub presence/absence, accent flag.
>
> Verify each bullet. Report COMPLIANT / NON_COMPLIANT with specifics.

### Step 4: Code quality reviewer (sonnet)

- [ ] Prompt:

> Code-quality reviewer for P2a Task 2. Worktree, `git show HEAD`. Comment on:
> 1. CSS namespacing — does `.num-stat` collide with any existing selector? (`grep -n "num-stat" src/docket/web/static/`)
> 2. Token usage — are `--type-*`, `--space-*` from P1 used consistently, or are there magic numbers slipping in?
> 3. Jinja safety — what happens if `value` is `None`? Does the test cover it? Should it?
> 4. Accessibility — is the label/value pair semantic enough? (A `<dl>` would be more semantic than two `<div>`s; weigh against existing project conventions.)
> 5. Anything else.
>
> APPROVED / NEEDS_CHANGES.

If NEEDS_CHANGES: implementer fixes, reviewer re-reviews.

### Step 5: Controller — mark complete

- [ ] Task 2 → completed.

---

## Task 3: `partials/freshness_chip.html` + test

**Files:**
- Create: `src/docket/web/templates/partials/freshness_chip.html`
- Modify: `tests/web/test_partials_visual_refactor.py`, `src/docket/web/static/layout.css`

### Step 1: Dispatch implementer (sonnet)

- [ ] Prompt:

> Implementer for P2a Task 3 — `partials/freshness_chip.html`. Worktree at `/Users/darrellnance/docket-pub/.claude/worktrees/worktree-visual-refactor-p2a`. `cd` in for every shell call.
>
> **Context.** A small status pill — dot + state label + relative timestamp — that appears in the new compressed CityLead header in P3. Links to `/al/<slug>/source-health/` (the new Source Health page built in P4). For P2a, this partial is declared but not rendered on any page.
>
> **TDD — failing tests first.** Append to `tests/web/test_partials_visual_refactor.py`:
>
> ```python
> def test_freshness_chip_renders_state_and_timestamp(render_partial):
>     html = render_partial(
>         'partials/freshness_chip.html',
>         state='good',
>         last_synced='2 hours ago',
>         source_health_url='/al/birmingham/source-health/',
>     )
>     assert 'freshness-chip' in html
>     assert 'is-good' in html
>     assert '2 hours ago' in html
>     assert 'href="/al/birmingham/source-health/"' in html
>
> def test_freshness_chip_state_classes(render_partial):
>     for state in ('good', 'warn', 'bad'):
>         html = render_partial(
>             'partials/freshness_chip.html',
>             state=state,
>             last_synced='just now',
>             source_health_url='/al/test/source-health/',
>         )
>         assert f'is-{state}' in html
>
> def test_freshness_chip_dot_aria_hidden(render_partial):
>     """The visual dot must be aria-hidden so screen readers
>     hear only the state label + timestamp."""
>     html = render_partial(
>         'partials/freshness_chip.html',
>         state='good',
>         last_synced='now',
>         source_health_url='/al/test/source-health/',
>     )
>     assert 'aria-hidden="true"' in html
> ```
>
> Run and confirm all FAIL.
>
> **Implement.** Create `src/docket/web/templates/partials/freshness_chip.html`:
>
> ```jinja
> {# Freshness chip — dot + state label + last-synced timestamp.
>    Spec: docs/superpowers/specs/2026-05-14-visual-refactor-design.md
>    Links to the city's Source Health page (P4).
>    Args:
>      state             ('good' | 'warn' | 'bad', required)
>      last_synced       (pre-formatted string, e.g., "2 hours ago", required)
>      source_health_url (str, required)
> #}
> <a class="freshness-chip is-{{ state }}" href="{{ source_health_url }}">
>   <span class="freshness-dot" aria-hidden="true"></span>
>   <span class="freshness-state-label t-mono">
>     {% if state == 'good' %}Live · feed active
>     {%- elif state == 'warn' %}Stale · check source
>     {%- else %}Broken · feed down{% endif %}
>   </span>
>   <span class="freshness-sub t-meta">updated {{ last_synced }}</span>
> </a>
> ```
>
> **Append to `layout.css`** (under the existing P2a section from Task 2):
>
> ```css
>
> .freshness-chip {
>   display: inline-flex;
>   align-items: center;
>   gap: var(--space-2);
>   padding: var(--space-1) var(--space-3);
>   border: 1px solid var(--rule);
>   border-radius: 999px;
>   background: var(--paper);
>   color: var(--ink-2);
>   text-decoration: none;
>   font-size: var(--type-eyebrow);
>   transition: border-color 0.15s, color 0.15s;
> }
> .freshness-chip:hover { border-color: var(--rule-strong); color: var(--ink); }
> .freshness-dot {
>   width: 7px;
>   height: 7px;
>   border-radius: 50%;
>   background: var(--ink-4);
> }
> .freshness-chip.is-good .freshness-dot { background: var(--good); }
> .freshness-chip.is-warn .freshness-dot { background: var(--warn); }
> .freshness-chip.is-bad  .freshness-dot { background: var(--bad); }
> .freshness-state-label { font-size: var(--type-eyebrow); letter-spacing: 0.1em; text-transform: uppercase; }
> .freshness-sub { font-size: 11px; color: var(--ink-3); }
> ```
>
> Run tests: pass. Run full suite: 1544 passed (1541 + 3 new).
>
> **Commit message:**
> ```
> feat(partials): add freshness_chip status pill for new masthead area
>
> Dot + state label + relative timestamp, links to Source Health (P4).
> Three states: good/warn/bad. Not yet rendered on any page.
> ```

### Step 2-5: Controller verify → spec reviewer → code reviewer → mark complete

Same pattern as Task 2. Controller cross-checks: partial exists, CSS appended, 3 new tests pass, suite at 1544.

Spec reviewer prompt template (substitute task-specific spec): "Spec compliance reviewer for P2a Task 3. Spec: freshness_chip with args (state, last_synced, source_health_url). States: good/warn/bad. Includes aria-hidden dot. CSS in layout.css P2a section. Tests cover render, all 3 states, aria-hidden assertion." COMPLIANT / NON_COMPLIANT.

Code reviewer prompt template: "Code-quality reviewer for P2a Task 3. Comment on: namespacing (`grep -n freshness src/docket/web/static/`), color contrast (the .is-warn / .is-bad dots against --paper bg — sketch out whether they meet WCAG 3:1 graphical-object contrast), token usage, semantic markup (link semantics — is the whole chip a link or just the state label?), edge cases (what if state is an unexpected value? falls through to .is- which is broken)." APPROVED / NEEDS_CHANGES.

---

## Task 4: `partials/topic_row.html` + test

**Files:**
- Create: `src/docket/web/templates/partials/topic_row.html`
- Modify: `tests/web/test_partials_visual_refactor.py`, `layout.css`

### Step 1: Implementer prompt (sonnet)

> Implementer for P2a Task 4 — `partials/topic_row.html`. Worktree at the standard P2a path.
>
> **Context.** Horizontal scroll-snap pill row showing top topics. Currently inlined in `city.html`; P3 will swap to using this partial. For P2a it's declared but not consumed.
>
> **Look at existing topic-pill markup in `city.html`** (`grep -A 5 "topic-pill\|topic-row" src/docket/web/templates/city.html`) — your partial should produce equivalent HTML so when P3 swaps the inline markup for the partial, the visual is identical.
>
> **Before writing the `url_for` call, verify the exact route kwarg name.** Run `grep -nE "@bp\.route.*topic|def topic_detail" src/docket/web/public.py`. You'll see the endpoint name is `public.topic_detail` and its kwarg name is whatever the function signature shows. Use that exact kwarg name in `url_for('public.topic_detail', <kwarg>=topic.slug)`. A wrong kwarg name raises `werkzeug.routing.BuildError` at test time and the agent will loop trying to debug a Jinja issue that's actually a routing-arity issue.
>
> **TDD tests first:**
>
> ```python
> def test_topic_row_renders_pills(render_partial):
>     topics = [
>         {'slug': 'budget', 'label': 'Budget', 'count': 42, 'color': '#1a73e8'},
>         {'slug': 'housing', 'label': 'Housing', 'count': 18, 'color': '#34a853'},
>     ]
>     html = render_partial('partials/topic_row.html', topics=topics, city_slug='birmingham')
>     assert 'topic-row' in html
>     assert 'Budget' in html
>     assert 'Housing' in html
>     assert '42' in html
>     # Pills link into the city-scoped topic page
>     assert '/topics/budget/' in html
>     assert 'topic-pill' in html
>
> def test_topic_row_handles_empty_list(render_partial):
>     """No topics → render empty (or with a 'no topics yet' affordance)."""
>     html = render_partial('partials/topic_row.html', topics=[], city_slug='birmingham')
>     # Render must not crash; container may or may not be present.
>     # Spec choice: render an empty container so the row's vertical space is reserved.
>     assert 'topic-row' in html or html.strip() == ''
> ```
>
> Run, confirm fail.
>
> **Implement.** Create `src/docket/web/templates/partials/topic_row.html`:
>
> ```jinja
> {# Horizontal scroll-snap pills, one per topic.
>    Args:
>      topics    list of dicts with slug / label / count / color
>      city_slug str — used to scope topic links to the city
> #}
> {% if topics %}
> <div class="topic-row">
>   {% for topic in topics %}
>     <a class="topic-pill"
>        href="{{ url_for('public.topic_detail', topic=topic.slug) }}"
>        style="--topic-color: {{ topic.color or 'var(--ink-3)' }};">
>       <span class="topic-pill-dot" aria-hidden="true"></span>
>       <span class="topic-pill-label">{{ topic.label }}</span>
>       <span class="topic-pill-count t-mono">{{ topic.count }}</span>
>     </a>
>   {% endfor %}
> </div>
> {% endif %}
> ```
>
> **CSS append to `layout.css`:**
>
> ```css
>
> .topic-row {
>   display: flex;
>   gap: var(--space-3);
>   overflow-x: auto;
>   scroll-snap-type: x mandatory;
>   padding: var(--space-2) 0;
>   -webkit-overflow-scrolling: touch;
> }
> .topic-row::-webkit-scrollbar { display: none; }
> .topic-row { scrollbar-width: none; }
> .topic-pill {
>   display: inline-flex;
>   align-items: center;
>   gap: var(--space-2);
>   padding: var(--space-2) var(--space-4);
>   border: 1px solid var(--rule);
>   border-radius: 999px;
>   background: var(--paper);
>   color: var(--ink);
>   text-decoration: none;
>   scroll-snap-align: start;
>   flex-shrink: 0;
> }
> .topic-pill:hover { border-color: var(--rule-strong); }
> .topic-pill-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--topic-color); }
> .topic-pill-label { font-size: 13px; }
> .topic-pill-count { font-size: var(--type-eyebrow); color: var(--ink-3); }
> ```
>
> Run tests: pass. Suite: 1546 passed.
>
> **Commit message:**
> ```
> feat(partials): add topic_row horizontal-scroll pill row
>
> Extracted-shape partial for the topic carousel. P3 swaps the inline
> markup in city.html for this partial; P2a only declares it.
> ```

### Step 2-5: same pattern.

Reviewer prompts substitute "topic_row" / topics. Code reviewer should also check: scrollbar hiding cross-browser, scroll-snap-type browser support, `url_for('public.topic_detail', topic=...)` matches the existing route signature, what happens with `topics=None` (not just `[]`).

---

## Task 5: `partials/kpi_explainer.html` + test

**Files:**
- Create: `src/docket/web/templates/partials/kpi_explainer.html`
- Modify: tests + `layout.css`

### Step 1: Implementer (sonnet)

> Implementer for P2a Task 5 — `partials/kpi_explainer.html`. Worktree at standard path.
>
> **Context.** The KPI explainer card that lives inside the new `source_rail` (Task 7) on overview pages. Each card shows: label, value, optional sub-label, and a collapsible block displaying the SQL that produced the value (display-only — *not* live-executed). 4 instances render in the source rail in P3 (Meetings lifetime, Agenda items YTD, Votes YTD, Dollars pending vs settled).
>
> **TDD tests first:**
>
> ```python
> def test_kpi_explainer_renders_value_and_label(render_partial):
>     html = render_partial(
>         'partials/kpi_explainer.html',
>         label='Meetings lifetime',
>         value='1,003',
>         sub='Since 2017',
>         sql_display='SELECT count(*) FROM meetings WHERE municipality_id = $1',
>     )
>     assert 'kpi-explainer' in html
>     assert 'Meetings lifetime' in html
>     assert '1,003' in html
>     assert 'Since 2017' in html
>     assert 'SELECT count(*)' in html
>     assert 'municipality_id' in html
>
> def test_kpi_explainer_sql_in_details(render_partial):
>     """SQL display lives inside <details> so it's collapsible
>     without JS. Summary is the chevron/CTA."""
>     html = render_partial(
>         'partials/kpi_explainer.html',
>         label='Votes YTD',
>         value='123',
>         sub=None,
>         sql_display='SELECT count(*) FROM votes',
>     )
>     assert '<details' in html
>     assert '<summary' in html
>
> def test_kpi_explainer_omits_sub_when_none(render_partial):
>     html = render_partial(
>         'partials/kpi_explainer.html',
>         label='Votes',
>         value='12',
>         sub=None,
>         sql_display='SELECT 1',
>     )
>     assert 'kpi-explainer-sub' not in html
> ```
>
> **Implement** `partials/kpi_explainer.html`:
>
> ```jinja
> {# KPI explainer card with collapsible SQL display.
>    Lives inside the new source_rail (Task 7), one per KPI.
>    Args:
>      label       (str, required)
>      value       (str, required) — pre-formatted
>      sub         (str | None)    — e.g., "Since 2017"
>      sql_display (str, required) — hardcoded query for transparency.
>                                    Not executed at render time.
> #}
> <article class="kpi-explainer">
>   <div class="kpi-explainer-label t-mono">{{ label }}</div>
>   <div class="kpi-explainer-value t-display">{{ value }}</div>
>   {% if sub %}
>     <div class="kpi-explainer-sub t-meta">{{ sub }}</div>
>   {% endif %}
>   <details class="kpi-explainer-sql">
>     <summary class="t-mono">show SQL</summary>
>     <pre class="kpi-explainer-sql-pre"><code>{{ sql_display }}</code></pre>
>   </details>
> </article>
> ```
>
> **CSS append:**
>
> ```css
>
> .kpi-explainer {
>   padding: var(--space-3);
>   border: 1px solid var(--rule);
>   border-radius: var(--radius);
>   background: var(--paper);
>   display: flex;
>   flex-direction: column;
>   gap: var(--space-1);
> }
> .kpi-explainer-label {
>   font-size: var(--type-eyebrow);
>   letter-spacing: 0.12em;
>   text-transform: uppercase;
>   color: var(--ink-3);
> }
> .kpi-explainer-value {
>   font-size: var(--type-mono-num);
>   font-family: var(--font-mono);
>   font-feature-settings: "tnum" 1, "lnum" 1;
>   color: var(--ink);
> }
> .kpi-explainer-sub { font-size: 11px; color: var(--ink-3); }
> .kpi-explainer-sql { margin-top: var(--space-2); }
> .kpi-explainer-sql summary {
>   cursor: pointer;
>   font-size: var(--type-eyebrow);
>   color: var(--accent);
>   list-style: none;
> }
> .kpi-explainer-sql summary::-webkit-details-marker { display: none; }
> .kpi-explainer-sql summary::marker { display: none; }
> .kpi-explainer-sql summary::after { content: " →"; }
> .kpi-explainer-sql[open] summary::after { content: " ↓"; }
> .kpi-explainer-sql-pre {
>   margin: var(--space-2) 0 0;
>   padding: var(--space-2);
>   background: var(--paper-2);
>   border: 1px solid var(--rule);
>   border-radius: var(--radius);
>   font-size: 11px;
>   color: var(--ink-2);
>   overflow-x: auto;
>   white-space: pre-wrap;
>   word-break: break-word;
> }
> ```
>
> Tests pass → suite at 1549.
>
> **Commit message:**
> ```
> feat(partials): add kpi_explainer card with collapsible SQL display
>
> One card per KPI inside the new source_rail (Task 7). SQL is display-
> only — never executed at render time. Uses native <details> for the
> toggle so no JS is required.
> ```

### Step 2-5: same pattern.

Code reviewer should specifically check: does using native `<details>` break any existing JS that wires custom collapsibles? (`grep -rn 'details' src/docket/web/static/`). What's the SQL HTML-escaping story — is `{{ sql_display }}` autoescaped (it should be — confirm). What if `sql_display` contains a `<` and breaks the `<code>` display?

---

## Task 6: `partials/meeting_card.html` + test

**Files:**
- Create: `src/docket/web/templates/partials/meeting_card.html`
- Modify: tests + `layout.css` + `mobile.css`

### Step 1: Implementer (sonnet)

> Implementer for P2a Task 6 — `partials/meeting_card.html`. Worktree at standard path.
>
> **Context.** Two-variant meeting card. `variant='strip'` for horizontal-scroll This-Week / Upcoming sections on city overview. `variant='grid'` for meeting list / homepage cards. Both variants share the same data binding (a `meeting` dict/object) but lay out differently.
>
> **Look at existing meeting-card markup in `city.html`** (the This-Week strip section) and `meetings.html` (the grid) to see what data fields meetings expose. Match those field references exactly — `meeting.date`, `meeting.title`, `meeting.summary`, `meeting.agenda_count`, `meeting.dollars_total`, `meeting.meeting_type`, `meeting.id`. Use `municipality.slug` for the link target.
>
> **Before writing the `url_for` call, verify the exact route kwarg names.** Run `grep -nE "@bp\.route.*meeting|def meeting_detail" src/docket/web/public.py`. You'll see the endpoint name is `public.meeting_detail` and its kwarg names match its function signature. Use `url_for('public.meeting_detail', <slug_kwarg>=municipality.slug, <id_kwarg>=meeting.id)` with the exact kwarg names from the signature. A wrong kwarg name raises `werkzeug.routing.BuildError` at test time.
>
> **TDD tests first:**
>
> ```python
> from types import SimpleNamespace
> from datetime import date as date_cls
>
>
> def _sample_meeting():
>     return SimpleNamespace(
>         id=42,
>         date=date_cls(2026, 5, 13),
>         title='City Council · Regular Meeting',
>         meeting_type='regular',
>         summary='Routine agenda; one large procurement item.',
>         agenda_count=18,
>         dollars_total=2_400_000,
>     )
>
>
> def test_meeting_card_strip_variant_renders(render_partial):
>     m = _sample_meeting()
>     html = render_partial(
>         'partials/meeting_card.html',
>         meeting=m,
>         variant='strip',
>         municipality=SimpleNamespace(slug='birmingham'),
>     )
>     assert 'meeting-card' in html
>     assert 'meeting-card--strip' in html
>     assert 'City Council' in html
>     # Strip variant should reference the date and item count compactly.
>     assert '18' in html
>
>
> def test_meeting_card_grid_variant_renders(render_partial):
>     m = _sample_meeting()
>     html = render_partial(
>         'partials/meeting_card.html',
>         meeting=m,
>         variant='grid',
>         municipality=SimpleNamespace(slug='birmingham'),
>     )
>     assert 'meeting-card--grid' in html
>     assert 'Routine agenda' in html  # Summary visible in grid, not strip
>
>
> def test_meeting_card_link_to_meeting_detail(render_partial):
>     m = _sample_meeting()
>     html = render_partial(
>         'partials/meeting_card.html',
>         meeting=m,
>         variant='grid',
>         municipality=SimpleNamespace(slug='birmingham'),
>     )
>     assert '/al/birmingham/meetings/42/' in html
>
>
> def test_meeting_card_handles_zero_dollars(render_partial):
>     m = _sample_meeting()
>     m.dollars_total = 0
>     html = render_partial(
>         'partials/meeting_card.html',
>         meeting=m,
>         variant='grid',
>         municipality=SimpleNamespace(slug='birmingham'),
>     )
>     # Card should still render — zero dollars is valid data, not missing.
>     assert 'meeting-card' in html
> ```
>
> **Implement** the partial. Hand-craft a layout where:
> - **Strip variant** (`variant='strip'`): fixed-width card (~220px), date + weekday + dot, h3 title (clamped to ~2 lines), agenda count chip. No summary.
> - **Grid variant** (`variant='grid'`): wider card, date + weekday + dot, h3 title, summary paragraph (clamped to ~3 lines), bottom row with agenda count + dollar tier indicator.
>
> Both link to `{{ url_for('public.meeting_detail', slug=municipality.slug, meeting_id=meeting.id) }}`.
>
> CSS in `layout.css` (P2a section) for both variants. Add `mobile.css` overrides under a new `/* ── P2a partials ─── */` section near the end: strip variant cards become 240px wide; grid variant becomes single-column at <768px.
>
> Test all four cases → suite at 1553.
>
> **Commit message:**
> ```
> feat(partials): add meeting_card with strip + grid variants
>
> One partial, two layouts: strip for horizontal-scroll lanes on city
> overview / homepage, grid for meeting list. P3 swaps the inline markup
> on city.html for this partial; P5 does the same for index.html and
> meetings.html.
> ```

### Step 2-5: same pattern. Code reviewer should check: does the partial gracefully handle `meeting.summary == None` (some meetings don't have one)? Same for `dollars_total == None`. Mobile.css addition placement.

---

## Task 7: `partials/source_rail.html` + test

**Why this is last among the new partials:** it composes other partials (`kpi_explainer` from Task 5, the existing `rail_default.html` content) and is the highest-coordination piece.

**Files:**
- Create: `src/docket/web/templates/partials/source_rail.html`
- Modify: tests + `layout.css`

### Step 1: Implementer (sonnet)

> Implementer for P2a Task 7 — `partials/source_rail.html`. Worktree at standard path.
>
> **Context.** The new desktop rail container that P3+ pages will use (city overview only — per spec, rail is overview-only). For P2a, it's declared but NOT yet wired into `base.html` (that switch is P2b). Lives alongside `rail_default.html`.
>
> **Composition.** `source_rail.html` is built from three sections in order:
> 1. **City provenance section** — re-uses `rail_default.html`'s HTML (Platform / Adapter / Records table + Source documents link block). Could either `{% include 'partials/rail_default.html' %}` directly OR copy its markup. Decision: **`{% include %}`** — keeps single-source for provenance markup; if `rail_default.html` is updated, both stay in sync until P2b retires `rail_default`.
> 2. **KPI explainer stack** — new in P2a. Renders 4 `kpi_explainer` partials with hardcoded sample SQL displays. In P3 the values will be pulled from the `city_stats` dict the view function builds; for P2a tests, accept the values as an injected context dict.
> 3. **Source/provenance footer** — already present in `rail_default.html`, so step 1's include covers this.
>
> **TDD tests first:**
>
> ```python
> from types import SimpleNamespace
>
>
> def test_source_rail_includes_provenance_and_kpis(render_partial):
>     muni = SimpleNamespace(
>         slug='birmingham',
>         name='Birmingham',
>         state='AL',
>         adapter_class='GranicusAdapter',
>     )
>     kpi_stats = [
>         {'label': 'Meetings lifetime', 'value': '1,003', 'sub': 'Since 2017',
>          'sql_display': 'SELECT count(*) FROM meetings WHERE municipality_id = $1'},
>         {'label': 'Agenda items YTD', 'value': '14,212', 'sub': None,
>          'sql_display': 'SELECT count(*) FROM agenda_items ai JOIN meetings m ...'},
>         {'label': 'Votes YTD', 'value': '892', 'sub': None,
>          'sql_display': 'SELECT count(*) FROM votes v JOIN meetings m ...'},
>         {'label': 'Dollars pending', 'value': '$48.2M', 'sub': 'vs $112M settled',
>          'sql_display': 'SELECT sum(dollars_amount) FROM agenda_items ...'},
>     ]
>     html = render_partial(
>         'partials/source_rail.html',
>         municipality=muni,
>         meeting_count=1003,
>         kpi_stats=kpi_stats,
>     )
>     # Provenance section comes through from rail_default include
>     assert 'GranicusAdapter' in html
>     assert 'Birmingham' in html
>     # All 4 KPI explainers render
>     assert 'Meetings lifetime' in html
>     assert 'Agenda items YTD' in html
>     assert 'Votes YTD' in html
>     assert 'Dollars pending' in html
>     # Sample SQL substrings show up
>     assert 'FROM agenda_items' in html
>
>
> def test_source_rail_handles_empty_kpi_stats(render_partial):
>     """Rail renders even when stats are missing (defensive)."""
>     muni = SimpleNamespace(
>         slug='birmingham', name='Birmingham', state='AL',
>         adapter_class='GranicusAdapter',
>     )
>     html = render_partial(
>         'partials/source_rail.html',
>         municipality=muni,
>         meeting_count=1003,
>         kpi_stats=[],
>     )
>     # Provenance still renders
>     assert 'GranicusAdapter' in html
>     # KPI section is absent or empty — no card chrome
>     assert 'Meetings lifetime' not in html
> ```
>
> Run, confirm fail.
>
> **Implement** `partials/source_rail.html`:
>
> ```jinja
> {# Desktop source rail — overview-only (per spec; rail = overview-only rule).
>    Lives alongside rail_default.html in P2a; base.html switch to this
>    partial happens in P2b.
>    Args:
>      municipality   (object) — required for the included rail_default section
>      meeting_count  (int)    — required for rail_default
>      kpi_stats      (list)   — list of {label, value, sub, sql_display} dicts
> #}
>
> {# 1. Provenance section — re-uses existing rail_default content. #}
> {% include 'partials/rail_default.html' %}
>
> {# 2. KPI explainer stack — new in P2a.
>    Defensive dict access: stat is a dict, and `sub` may be intentionally
>    omitted (not just None). Use Jinja's get() so a missing key resolves
>    to None instead of raising / rendering Undefined under strict_undefined. #}
> {% if kpi_stats %}
> <section class="source-rail-kpis">
>   <div class="source-rail-section-h t-eyebrow">By the numbers</div>
>   {% for stat in kpi_stats %}
>     {% with label=stat.get('label'),
>             value=stat.get('value'),
>             sub=stat.get('sub'),
>             sql_display=stat.get('sql_display') %}
>       {% include 'partials/kpi_explainer.html' %}
>     {% endwith %}
>   {% endfor %}
> </section>
> {% endif %}
> ```
>
> **CSS append to `layout.css`:**
>
> ```css
>
> .source-rail-kpis {
>   margin-top: var(--space-6);
>   padding-top: var(--space-4);
>   border-top: 1px solid var(--rule);
>   display: flex;
>   flex-direction: column;
>   gap: var(--space-3);
> }
> .source-rail-section-h {
>   color: var(--ink-3);
>   margin-bottom: var(--space-2);
> }
> ```
>
> Run tests → suite at 1555.
>
> **Commit message:**
> ```
> feat(partials): add source_rail composing rail_default + kpi_explainer stack
>
> The new overview-only rail partial. Includes rail_default.html for the
> provenance section + a configurable list of kpi_explainer cards for the
> by-the-numbers section. Not yet wired into base.html — that swap and the
> retirement of rail_default happen in P2b.
> ```

### Step 2-5: same pattern. Code reviewer focus: `{% with %}` + `{% include %}` interaction (do the with-bindings propagate correctly into the included template?), what if `kpi_stats` items are missing keys (e.g., no `sub`), include-from-include depth.

---

## Task 8: Final verification + PR + deploy + production gate

**Files:** read-only across the worktree + production curl.

### Step 1: Controller — full local verification

- [ ] Run:

```bash
echo "== Suite =="
venv/bin/pytest --ignore=tests/live --deselect tests/unit/test_ai_worker_run.py::test_run_once_refuses_over_budget -q 2>&1 | tail -3

echo "== New partial files =="
ls -la src/docket/web/templates/partials/{num_stat,freshness_chip,topic_row,kpi_explainer,meeting_card,source_rail}.html

echo "== CSS additions =="
grep -c "P2a partials" src/docket/web/static/layout.css
grep -c "P2a partials" src/docket/web/static/mobile.css

echo "== Diff stat vs origin/main =="
git diff --stat origin/main..HEAD

echo "== Commit log =="
git log --oneline origin/main..HEAD
```

Expected:
- Suite: 1555 passed
- 6 partial files exist
- "P2a partials" appears at least once in each of layout.css + mobile.css
- Diff stat: ~7 files (`tests/web/conftest.py`, `tests/web/test_partials_visual_refactor.py`, 6 partials, layout.css, mobile.css)
- 7 commits visible

### Step 2: Programmatic regression check via route-smoke

- [ ] Start Flask in the worktree on port 5001 (port 5000 is taken by macOS AirPlay):

```bash
nohup venv/bin/flask --app docket.web run --port 5001 > /tmp/flask-p2a.log 2>&1 &
sleep 3
```

Note: Flask's editable install resolves `docket.web` against the canonical repo's source folder, not the worktree's — same gotcha as P1. For P2a this is actually fine: the new partials aren't included by any existing page, so the canonical source produces the same rendering whether or not our worktree's files exist. Use the route-smoke just to confirm no template rendering errors:

```bash
for path in "/" "/al/birmingham/" "/al/birmingham/meetings/" "/al/birmingham/council/" "/search" "/topics/" "/coverage/" "/about/"; do
  code=$(curl -sS -o /dev/null -w "%{http_code}" "http://localhost:5001${path}")
  echo "${code} ${path}"
done
```

Expected: every line begins with `200`. No `5xx`.

### Step 3: 🛑 Human Verification Gate — pre-merge sanity check

- [ ] Post this message to the operator and HALT:

> "P2a worktree complete. All 6 new partials shipped with snapshot tests; suite at 1555 (1536 baseline + 19 new). Zero changes to rendered pages — the new partials aren't included by any template yet. Route-smoke confirms every public page still returns 200. No commits modify existing partials, view functions, or page templates.
>
> Before I push the branch and open the PR, please:
> - Skim the diff: `git -C /Users/darrellnance/docket-pub/.claude/worktrees/worktree-visual-refactor-p2a diff origin/main..HEAD`
> - Confirm the partial designs match the sketch idiom you have in mind. (Each partial file is short and self-contained — Task 6 meeting_card is the largest at ~50 lines.)
>
> Reply 'approved' to push + open PR + merge + deploy. If you want changes to any partial before merge, describe them and I'll dispatch a fix subagent."

### Step 4: Push branch + open PR

- [ ] After approval:

```bash
git push -u origin worktree-visual-refactor-p2a

gh pr create --base main --head worktree-visual-refactor-p2a --title "style(p2a): visual refactor component library — 6 new partials + test fixture" --body "$(cat <<'EOF'
## Summary

Phase 2a of the visual refactor: introduces 6 new Jinja partials (`num_stat`, `freshness_chip`, `topic_row`, `kpi_explainer`, `meeting_card`, `source_rail`) that P3+ city overview + detail pages will consume. **Zero impact on rendered pages** — each partial is declared but not yet included by any template.

P2b will land separately: restyling `_card_shell.html` / `council_card.html` / `badge_chip.html` / `dollar_tier.html`, switching `base.html` to use `source_rail`, retiring `rail_default.html` / `rail_meeting.html` / `rail_member.html` and their routes.

## Commits

(7 commits — fixture + 6 partials, one per file)

## Spec

`docs/superpowers/specs/2026-05-14-visual-refactor-design.md` (Phase 2)

## Test plan

- [x] `pytest --ignore=tests/live --deselect tests/unit/test_ai_worker_run.py::test_run_once_refuses_over_budget` → 1555 passed (1536 baseline + 19 new partial-snapshot tests).
- [x] Each new partial has a snapshot test covering basic render + edge cases (empty inputs, optional args, state variants).
- [x] Route-smoke at desktop: every public page returns 200 — no template render regressions.
- [ ] **Post-merge production verification:** curl `https://docket.pub/static/styles.css?v=$(date +%s)` confirms layout.css additions are live; route-smoke against docket.pub confirms zero rendering regressions. Visual sweep confirms no unintended visual changes anywhere.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

### Step 5: Merge + deploy

- [ ] On user approval:

```bash
gh pr merge <PR#> --merge --delete-branch
# (Local main update may fail because canonical repo is on main; the merge happens on remote regardless.)
git -C /Users/darrellnance/docket-pub fetch origin
git -C /Users/darrellnance/docket-pub pull --ff-only origin main
(cd /Users/darrellnance/docket-pub && railway up --service docket-web --detach)
```

### Step 6: Production verification

- [ ] Poll for deploy completion with a background process (same pattern as P1 Task 6):

```bash
deadline=$(($(date +%s) + 360))
while [ $(date +%s) -lt $deadline ]; do
  # Look for one of the new CSS class names that should now be served.
  count=$(curl -sS "https://docket.pub/static/layout.css?v=$(date +%s)" 2>/dev/null | grep -c "freshness-chip\|kpi-explainer\|meeting-card")
  ts=$(date '+%H:%M:%S')
  if [ "$count" -ge 3 ]; then
    echo "[$ts] P2a CSS live (matches=$count)"
    exit 0
  fi
  echo "[$ts] count=$count — waiting..."
  sleep 20
done
echo "TIMEOUT"
exit 1
```

Run in background; wait for completion notification.

- [ ] Verify Railway logs are clean after deploy:

```bash
(cd /Users/darrellnance/docket-pub && railway logs --service docket-web 2>&1 | tail -30)
```

Expected: gunicorn boot, migrations no-op, workers up, no errors.

### Step 7: 🛑 Human Verification Gate — production sanity

- [ ] Post this message and HALT:

> "P2a deployed. Programmatic checks confirm the new CSS class names are live in `layout.css`. **Hard-refresh** `https://docket.pub/al/birmingham/` (Cmd+Shift+R) and skim 2-3 other pages. **Expected: zero visible change anywhere** — the new partials aren't consumed by any rendered page yet. If anything looks different, that's a regression worth investigating.
>
> Reply 'approved' to close out P2a and remove the worktree."

### Step 8: Closeout

- [ ] On approval:
  - Final code-quality reviewer pass on the whole P2a branch (sonnet, ~400 word cap, same pattern as P1's final review).
  - Exit + remove worktree.
  - Update memory: `project_visual_refactor_2026_05_14.md` → P2a shipped.
  - Note P2b as next planned phase.

---

## Self-Review Checklist

Spec coverage:
- ✓ `num_stat` → Task 2
- ✓ `freshness_chip` → Task 3
- ✓ `topic_row` → Task 4
- ✓ `kpi_explainer` → Task 5
- ✓ `meeting_card` → Task 6
- ✓ `source_rail` → Task 7
- ✗ `_card_shell.html` restyle, `council_card.html` restyle, `badge_chip.html` restyle, `dollar_tier.html` restyle, rail-conditional in base.html, delete `rail_meeting.html`+`rail_member.html` + routes → **deferred to P2b** (separate plan); rationale documented in the Architecture section
- ✗ `breadcrumbs.html` partial → **spec correction in P1 commit `7c7e328`**: existing `{% block crumb %}` in masthead.html is the right pattern; no new partial needed

Placeholder scan:
- ✓ Every step has actual code blocks or actual commands. No "TBD", "implement appropriately", etc.
- ✓ Each subagent prompt is verbatim and self-contained. Subagent doesn't need to read the spec.

Type / arg consistency:
- ✓ `render_partial` fixture signature is consistent across tasks 1-7
- ✓ Token usage (`--type-*`, `--space-*`) is the same naming convention across all CSS additions
- ✓ CSS class names follow `.partial-name` + `.partial-name-element` BEM-ish pattern consistently

Agent-execution audit:
- ✓ Model floor = **sonnet** declared in the header banner; no haiku dispatches anywhere in the plan
- ✓ Every implementer step is followed by a controller-side direct verification BEFORE reviewer dispatch (P1 lesson: trust-but-verify after the haiku hallucination)
- ✓ Visual verification routed to **two** Human Verification Gates only (pre-merge sanity, post-deploy production sanity). Everything else is programmatic.
- ✓ Production verification (Step 6) uses `?v=$(date +%s)` cache-bust for every CDN-served URL

Risk / scope:
- ✓ P2a is purely additive: no template, view function, or call-site change to existing pages. The riskiest possible failure is "a new partial has a Jinja syntax error" — pytest catches that before deploy.
- ✓ P2b (the restyle pass that touches every page) gets its own plan after P2a ships. Splitting at this seam keeps each PR's visual review burden small.

Worktree pattern:
- ✓ Same worktree-off-main + symlinked-venv pattern as P1
- ✓ ExitWorktree call deferred to closeout (Task 8 Step 8) — operator decides keep vs remove after closeout
