# Visual Refactor — Phase 1 (Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the foundation tokens (type scale, spacing scale) and fix a footer-grid mismatch so later phases of the visual refactor build on a clean base.

**Architecture:** Pure CSS additions to `styles.css` (new `:root` custom properties) plus one CSS grid correction in `tweaks.css`. No template changes, no JS changes — the footer accordion and bottom-tab infrastructure already exist in production. Tokens are *declared* in P1 but only become *consumed* by partials and pages built in P2+. P1 ships behind a "no visible change at desktop" verification check.

**Tech Stack:** CSS custom properties (already used throughout `styles.css`), no build step, Flask dev server for verification, pytest for regression guard.

**Spec:** `docs/superpowers/specs/2026-05-14-visual-refactor-design.md` (Phase 1 section).

**Predecessor:** Spec self-review commit `7c7e328` (2026-05-14). P1 scope was reduced after a codebase audit confirmed bottom_tabs / source_sheet / mobile-search-icon / breadcrumbs / footer accordion are all already shipped.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `src/docket/web/static/styles.css` | Modify (add to `:root`) | Type-scale + spacing-scale CSS custom properties. New tokens live in the existing `:root` block alongside the OKLCH color tokens already there. |
| `src/docket/web/static/tweaks.css` | Modify (one line, `.footnote-cols`) | Correct the 4-column grid to match the 2-column-of-content reality. Eliminates two empty grid cells visible at ≥769px. |
| `tests/test_smoke.py` (or existing equivalent) | Read only — verify no template render regressions when re-run | Existing pytest must stay green. |

No new files. No template changes. No JS changes.

---

## Task 1: Audit existing token landscape and confirm token names are not in use

**Files:**
- Read: `src/docket/web/static/styles.css`
- Read: `src/docket/web/static/layout.css`
- Read: `src/docket/web/static/councilmatic.css`
- Read: `src/docket/web/static/tweaks.css`
- Read: `src/docket/web/static/mobile.css`
- Read: `src/docket/web/static/css/smart_brevity.css`

- [ ] **Step 1: Search every CSS file for any pre-existing `--type-*` or `--space-*` custom property**

Run: `grep -rn -- "--type-\|--space-" src/docket/web/static/`
Expected: zero matches (these token names are not yet in use). If any matches surface, note them — the plan's chosen names must not collide with existing declarations.

- [ ] **Step 2: Search every CSS file for hardcoded size values that will be replaced by tokens (for visibility, not yet for change)**

Run: `grep -rEn "font-size:\s*(64|44|28|17|15|10)px" src/docket/web/static/`
Expected: many matches — these are the call sites that *could* eventually consume the new type tokens. **Do not edit them in P1**. The point is to confirm token values match what the design already uses in practice; if a number is wildly off, the token is wrong.

- [ ] **Step 3: Confirm no commits, no changes yet**

Run: `git status`
Expected: clean working tree.

---

## Task 2: Add type-scale tokens to `styles.css`

**Files:**
- Modify: `src/docket/web/static/styles.css` — add inside the existing `:root { ... }` block (lines 3-57), after the font-family declarations (around line 42).

- [ ] **Step 1: Open `styles.css` and find the existing `:root` block**

Run: `grep -n "^:root {" src/docket/web/static/styles.css`
Expected: one match, line 3.

Run: `grep -n "^}" src/docket/web/static/styles.css | head -3`
Expected: first `^}` match around line 57 (closing the `:root` block).

- [ ] **Step 2: Insert type-scale tokens at the end of `:root`**

Edit `src/docket/web/static/styles.css`. Find this line (around line 47):

```css
  --radius:   4px;
  --radius-2: 8px;
```

Immediately AFTER `--radius-2: 8px;` (and BEFORE the "Semantic aliases" comment that follows), insert:

```css

  /* type scale — declared in P1 (visual refactor), consumed by P2+ partials.
     Source: docs/superpowers/specs/2026-05-14-visual-refactor-design.md */
  --type-hero:        64px;
  --type-hero-mobile: 44px;
  --type-section:     28px;
  --type-card:        17px;
  --type-body:        15px;
  --type-eyebrow:     10px;
  --type-mono-num:    26px;
```

- [ ] **Step 3: Verify the file is still syntactically valid by re-reading the `:root` block**

Run: `sed -n '3,75p' src/docket/web/static/styles.css`
Expected: the `:root { ... }` block now contains the new `--type-*` block; no stray braces; the closing `}` and `* { box-sizing: border-box; }` line that follows are still intact.

- [ ] **Step 4: Confirm no other CSS files were touched**

Run: `git diff --stat`
Expected: exactly one file modified (`src/docket/web/static/styles.css`), with additions only.

- [ ] **Step 5: Start the local dev server (or restart if running)**

Run: `venv/bin/flask run` (from repo root, with `.env` set so `DATABASE_URL` points to local docket_db).

If the server is already running and serving static files with no-cache, no action needed. Otherwise, start it and leave it running in another shell.

- [ ] **Step 6: Visual verification — confirm tokens are present in browser**

Open `http://localhost:5000/al/birmingham/` (or any page) in a browser.

Open devtools, Elements panel, select `<html>`, look at the Styles panel. Filter for `--type-`. All 7 tokens (`--type-hero`, `--type-hero-mobile`, `--type-section`, `--type-card`, `--type-body`, `--type-eyebrow`, `--type-mono-num`) should be visible on the `:root` rule.

Expected: 7 tokens present with the values from Step 2.

- [ ] **Step 7: Visual verification — confirm NO existing page rendering has changed**

The tokens are declared but not yet consumed. Visit:
- `http://localhost:5000/` (homepage)
- `http://localhost:5000/al/birmingham/` (city overview)
- `http://localhost:5000/al/birmingham/meetings/` (meeting list)
- Pick any meeting → meeting detail
- Pick any agenda item → item detail

Each page must look identical to before this commit. (Open before/after browser tabs side-by-side if uncertain.)

Expected: zero visible difference. If anything looks different, something else got edited by mistake — `git diff` and investigate.

- [ ] **Step 8: Run pytest to catch any incidental regressions**

Run: `venv/bin/pytest -x --ignore=tests/live 2>&1 | tail -20`
Expected: all tests pass. The `--ignore=tests/live` skips the live-API gated tests that require `ANTHROPIC_API_KEY`.

If any test fails, do NOT proceed. Investigate, fix, then re-run.

- [ ] **Step 9: Commit**

```bash
git add src/docket/web/static/styles.css
git -c user.email=hello@docket.pub commit -m "$(cat <<'EOF'
style(tokens): add type-scale CSS custom properties

Declared in :root for consumption by P2+ visual-refactor partials.
No call sites consume these tokens yet — declaration-only PR.

Source: docs/superpowers/specs/2026-05-14-visual-refactor-design.md
EOF
)"
```

Expected: commit succeeds, hook (if any) passes.

---

## Task 3: Add spacing-scale tokens to `styles.css`

**Files:**
- Modify: `src/docket/web/static/styles.css` — add inside the existing `:root { ... }` block, immediately after the new `--type-mono-num` token from Task 2.

- [ ] **Step 1: Locate the insertion point**

Run: `grep -n "type-mono-num" src/docket/web/static/styles.css`
Expected: one match, on the line you added in Task 2.

- [ ] **Step 2: Insert spacing-scale tokens after `--type-mono-num: 26px;`**

Edit `src/docket/web/static/styles.css`. Immediately AFTER `--type-mono-num:    26px;`, insert:

```css

  /* spacing scale — declared in P1, consumed by P2+ partials.
     Off-scale values discouraged in new partials. */
  --space-1:  4px;
  --space-2:  8px;
  --space-3:  12px;
  --space-4:  16px;
  --space-6:  24px;
  --space-8:  32px;
  --space-12: 48px;
  --space-16: 64px;
```

Note the naming: the trailing number is the *value in 4px units divided by 4 for clarity at common sizes*. So `--space-4` = 16px (4×4), `--space-8` = 32px (4×8), etc. Adopt this naming convention for any future spacing additions.

- [ ] **Step 3: Verify the file is still syntactically valid**

Run: `sed -n '3,85p' src/docket/web/static/styles.css`
Expected: `:root` block contains both the type-scale block and the new spacing-scale block; closing `}` intact; following `* { box-sizing: border-box; }` intact.

- [ ] **Step 4: Visual verification — tokens visible in devtools, no rendering change**

Same as Task 2 Step 6: filter `:root` styles for `--space-`. Expect 8 tokens visible.

Same as Task 2 Step 7: every page renders identically.

- [ ] **Step 5: Run pytest**

Run: `venv/bin/pytest -x --ignore=tests/live 2>&1 | tail -20`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/docket/web/static/styles.css
git -c user.email=hello@docket.pub commit -m "$(cat <<'EOF'
style(tokens): add spacing-scale CSS custom properties

Declared in :root alongside the type-scale block from the previous
commit. Naming convention: trailing number is value-in-4px-units
(--space-4 = 16px, --space-8 = 32px, etc.). Off-scale values
discouraged in new partials.

Source: docs/superpowers/specs/2026-05-14-visual-refactor-design.md
EOF
)"
```

Expected: commit succeeds.

---

## Task 4: Fix the footer 4-column grid mismatch in `tweaks.css`

**Background:** `tweaks.css:5` declares `.footnote-cols { grid-template-columns: repeat(4, 1fr); }` but `partials/footer.html` only renders 2 `.footnote-col` children. At desktop widths this leaves columns 3 and 4 as empty grid cells, visible as excess whitespace on the right half of the footer. P1 corrects this to 2 columns, matching the spec ("Footer stays 2 columns + colophon").

**Files:**
- Modify: `src/docket/web/static/tweaks.css:5-10`

- [ ] **Step 1: Confirm current state**

Run: `sed -n '5,11p' src/docket/web/static/tweaks.css`
Expected output:
```css
.footnote-cols {
  display: grid; grid-template-columns: repeat(4, 1fr);
  gap: 32px;
  padding-bottom: 32px;
  border-bottom: 1px solid var(--rule);
}
```

- [ ] **Step 2: Confirm template has 2 columns, not 4**

Run: `grep -c 'class="footnote-col"' src/docket/web/templates/partials/footer.html`
Expected: `2` (two `.footnote-col` children).

If the count is 4, STOP — the footer was changed since the plan was written; re-evaluate before editing.

- [ ] **Step 3: Edit `tweaks.css` to use 2 columns**

Change line 6 from:

```css
  display: grid; grid-template-columns: repeat(4, 1fr);
```

to:

```css
  display: grid; grid-template-columns: repeat(2, 1fr);
```

Leave gap, padding-bottom, and border-bottom unchanged.

- [ ] **Step 4: Verify the edit**

Run: `sed -n '5,11p' src/docket/web/static/tweaks.css`
Expected: line 6 now reads `display: grid; grid-template-columns: repeat(2, 1fr);`. Other lines unchanged.

- [ ] **Step 5: Visual verification — desktop footer now fills full width**

In the dev-server browser tab (≥769px wide window), scroll to the bottom of any page (e.g., `http://localhost:5000/al/birmingham/`).

Before this change: the "About" and "For citizens" columns sat in the left half of the footer; the right half was empty whitespace.

After this change: the two columns now span the full width of the page container, each taking 50% with the 32px gap between them. Colophon and bottom strip render the same.

Expected: no empty whitespace to the right of the columns at desktop.

- [ ] **Step 6: Visual verification — mobile footer accordion still works**

Resize the browser window to <768px (or open devtools responsive mode at iPhone width).

The `mobile.css:313-318` rule overrides `.footnote-cols` to `display: flex; flex-direction: column;` at narrow widths, so the desktop grid-template-columns value doesn't affect mobile rendering. Accordion behavior should be unchanged: first column open, others tappable to expand.

Expected: footer accordion works as before; first column open by default; tapping a closed column header expands it.

- [ ] **Step 7: Run pytest**

Run: `venv/bin/pytest -x --ignore=tests/live 2>&1 | tail -20`
Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/docket/web/static/tweaks.css
git -c user.email=hello@docket.pub commit -m "$(cat <<'EOF'
fix(footer): correct .footnote-cols grid to match 2-column template

The .footnote-cols grid was declared as 4 columns but partials/footer.html
only renders 2 .footnote-col children, leaving two empty grid cells visible
as right-side whitespace at desktop widths.

Spec ("docs/superpowers/specs/2026-05-14-visual-refactor-design.md", P1)
confirms the footer stays 2-column + colophon. Mobile accordion behavior is
unaffected (mobile.css overrides the grid to a flex column at <768px).
EOF
)"
```

Expected: commit succeeds.

---

## Task 5: Final verification across the site

**Files:** read-only verification of all rendered pages.

- [ ] **Step 1: Re-run the full pytest suite**

Run: `venv/bin/pytest --ignore=tests/live 2>&1 | tail -10`
Expected: all tests pass.

- [ ] **Step 2: Visual sweep at desktop width (≥1024px window)**

Open each of these in the dev-server browser and confirm no unexpected layout shift vs. pre-P1:

- `http://localhost:5000/` — homepage
- `http://localhost:5000/al/birmingham/` — city overview
- `http://localhost:5000/al/birmingham/meetings/` — meeting list
- `http://localhost:5000/al/birmingham/meetings/<any-id>/` — meeting detail
- `http://localhost:5000/al/birmingham/items/<any-id>/` — item detail
- `http://localhost:5000/al/birmingham/council/` — council roster
- `http://localhost:5000/al/birmingham/budget/` (or any badge slug) — category landing
- `http://localhost:5000/search` — search results page
- `http://localhost:5000/topics/` — topics index
- `http://localhost:5000/coverage/` — coverage listing
- `http://localhost:5000/about/` — about page

Expected: every page renders identically to before P1 *except* that the footer now spans full width at desktop (the only intentional visible change).

- [ ] **Step 3: Visual sweep at mobile width (<768px responsive mode, e.g., iPhone 14 Pro)**

Same page list as Step 2.

Expected: every page renders identically to before P1 (mobile footer accordion already worked; the desktop grid change does not affect mobile because `mobile.css` overrides `.footnote-cols`).

- [ ] **Step 4: Confirm devtools shows the new tokens**

In the open browser session, devtools → Elements → select `<html>` → Styles panel → scroll the `:root` rule.

Expected:
- 7 `--type-*` tokens visible (`--type-hero`, `--type-hero-mobile`, `--type-section`, `--type-card`, `--type-body`, `--type-eyebrow`, `--type-mono-num`)
- 8 `--space-*` tokens visible (`--space-1` through `--space-16`)

- [ ] **Step 5: Confirm `git log` shows three clean commits**

Run: `git log --oneline -5`
Expected: three commits at the top (type tokens, spacing tokens, footer grid fix) authored to `hello@docket.pub`.

---

## Task 6: Deploy and post-deploy verification

**Background:** Per CLAUDE.md, deploy only happens from `main` after PR merge. P1 work has been on a feature branch; this task assumes the PR has been merged to `main` and `main` is checked out locally.

- [ ] **Step 1: Confirm on `main` with no uncommitted changes**

Run: `git status && git branch --show-current`
Expected: branch is `main`, working tree clean.

- [ ] **Step 2: Pull latest `main`**

Run: `git pull --ff-only origin main`
Expected: fast-forward to the merged PR head.

- [ ] **Step 3: Deploy to Railway**

Run: `railway up --service docket-web --detach`
Expected: build succeeds (CSS-only change, no migration). Deploy completes within ~3-5 minutes.

**Do NOT use** `railway redeploy` — per CLAUDE.md, that restarts the old build without picking up new code.

- [ ] **Step 4: Post-deploy verification on production**

Open `https://docket.pub/al/birmingham/` in a browser.

In devtools, Elements → `<html>` → Styles → `:root`:
- Confirm 7 `--type-*` tokens present
- Confirm 8 `--space-*` tokens present

Scroll to the footer at desktop width:
- Confirm 2 columns span the full container width with 32px gap (no right-side whitespace).

Resize to mobile width:
- Confirm footer accordion still works: first column open, others tappable to expand.

Expected: production matches local verification from Task 5.

- [ ] **Step 5: Skim Railway logs for any new errors after deploy**

Run: `railway logs --service docket-web 2>&1 | tail -50`
Expected: no new 500s, no template render errors, no static-asset 404s.

---

## Self-Review Checklist (run after writing the plan)

Spec coverage:
- ✓ Type scale tokens → Task 2
- ✓ Spacing scale tokens → Task 3
- ✓ Footer 4-col → 2-col correction → Task 4
- ✓ "Other corrections recorded but not implemented" (Legislation nav, breadcrumbs partial, etc.) → correctly not in the plan; spec documents them as not-in-scope

Placeholder scan:
- ✓ Every step has actual code or actual commands; no "TBD" or "fill in" placeholders
- ✓ Commit messages are full text, not summaries

Type consistency:
- ✓ Token names (`--type-hero`, etc.) used consistently across Tasks 2, 3, 5 verification, and Task 6 verification
- ✓ File paths use the full `src/docket/web/...` prefix consistently
