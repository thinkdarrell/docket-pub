# Visual Refactor — Phase 1 (Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **🛑 HUMAN VERIFICATION GATES.** Every task that produces a visible CSS change ends with a **Human Verification Gate** that the agent MUST NOT pass on its own. Agents have no browser, no DevTools, no eyes. At each gate the agent must:
> 1. Post a clear message to the operator describing what to check (URL, expected outcome, mobile vs desktop).
> 2. **HALT and wait** for an explicit "approved" / "go" from the operator.
> 3. Only after operator approval, proceed to the commit step.
>
> Agents that "confirm visual verification passed" without operator input are violating this plan. Programmatic verification (curl/grep/pytest/awk) is allowed and expected at every step; visual verification is operator-only.

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

Run: `grep -rEn "font-size:\s*(64|44|28|26|17|15|10)px" src/docket/web/static/`
Expected: many matches — these are the call sites that *could* eventually consume the new type tokens (including the 26px mono-numeric value used for KPI/NumStat). **Do not edit them in P1**. The point is to confirm token values match what the design already uses in practice; if a number is wildly off, the token is wrong.

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

- [ ] **Step 3: Verify the `:root` block is still syntactically intact by dynamically extracting it**

Run: `awk '/^:root {/{flag=1} flag; /^}/{flag=0; print ""; exit}' src/docket/web/static/styles.css`
Expected: the full `:root { ... }` block prints to stdout. It must contain the new `--type-*` block. The output must end with `}` followed by a blank line (the awk extractor exits at the first `^}` it finds, which is the close of `:root`).

If the awk output is truncated or missing a closing `}`, the file is broken — STOP and inspect with the Read tool.

- [ ] **Step 4: Confirm no other CSS files were touched**

Run: `git diff --stat`
Expected: exactly one file modified (`src/docket/web/static/styles.css`), with additions only (the diff line count should show all `+`, no `-`).

- [ ] **Step 5: Verify the tokens are served correctly by Flask via curl**

Start the dev server in the background if not already running. From repo root:

Run: `DATABASE_URL=postgresql://docket@localhost:5432/docket_db venv/bin/flask --app docket.web run --port 5000 &`

Wait ~2 seconds for boot, then:

Run: `curl -sS http://localhost:5000/static/styles.css | grep -E -- "--type-(hero|hero-mobile|section|card|body|eyebrow|mono-num):"`

Expected output: 7 lines, one per token, each matching the values inserted in Step 2.

If fewer than 7 lines, the file was not served correctly OR the edit was incomplete — investigate.

- [ ] **Step 6: Run pytest to catch any template-rendering regressions**

Run: `venv/bin/pytest -x --ignore=tests/live 2>&1 | tail -20`
Expected: all tests pass. The `--ignore=tests/live` skips the live-API gated tests that require `ANTHROPIC_API_KEY`.

If any test fails, do NOT proceed. Investigate, fix, then re-run.

- [ ] **Step 7: 🛑 HUMAN VERIFICATION GATE — visual sweep of the local site**

Post this exact message to the operator and HALT:

> "Type-scale tokens added to `styles.css`. The dev server is running at `http://localhost:5000`. Please visually verify the following pages look **identical to before** (tokens are declared but not yet consumed, so there should be zero visible difference):
> - `/` (homepage)
> - `/al/birmingham/` (city overview)
> - `/al/birmingham/meetings/` (meeting list)
> - Any meeting detail
> - Any item detail
>
> Reply 'approved' to proceed to commit, or describe what looks off."

**Do not run the next step until the operator replies with explicit approval.**

- [ ] **Step 8: Commit**

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

- [ ] **Step 3: Verify the `:root` block is still syntactically intact**

Run: `awk '/^:root {/{flag=1} flag; /^}/{flag=0; print ""; exit}' src/docket/web/static/styles.css`
Expected: full `:root { ... }` block prints, containing BOTH the `--type-*` block from Task 2 AND the new `--space-*` block from this task. Block ends with `}` followed by blank line.

- [ ] **Step 4: Verify the spacing tokens are served via curl**

The dev server should still be running from Task 2 Step 5. If not, restart it (see Task 2 Step 5 command).

Run: `curl -sS http://localhost:5000/static/styles.css | grep -E -- "--space-(1|2|3|4|6|8|12|16):"`

Expected: 8 lines, one per spacing token, matching the values from Step 2.

- [ ] **Step 5: Run pytest**

Run: `venv/bin/pytest -x --ignore=tests/live 2>&1 | tail -20`
Expected: all tests pass.

- [ ] **Step 6: 🛑 HUMAN VERIFICATION GATE — visual sweep**

Post this message to the operator and HALT:

> "Spacing-scale tokens added to `styles.css`. The dev server is running at `http://localhost:5000`. Please visually verify the pages from Task 2 Step 7 still look **identical** (spacing tokens are declared but not consumed yet — zero visible difference expected). Reply 'approved' to proceed to commit."

**Do not run the next step until the operator replies with explicit approval.**

- [ ] **Step 7: Commit**

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

- [ ] **Step 5: Verify the new grid value is served by Flask**

Run: `curl -sS http://localhost:5000/static/tweaks.css | grep -A 1 "footnote-cols"`
Expected output includes the line `display: grid; grid-template-columns: repeat(2, 1fr);`. If it still says `repeat(4, 1fr)`, the file wasn't saved or Flask is serving a cached version.

- [ ] **Step 6: Confirm mobile override is unchanged (defensive check)**

Run: `grep -A 5 "13\. Footer accordion" src/docket/web/static/mobile.css | head -8`
Expected: the mobile `@media` override still sets `.footnote-cols` to `display: flex; flex-direction: column;`. That rule must NOT have been touched in this task — mobile accordion behavior depends on it.

- [ ] **Step 7: Run pytest**

Run: `venv/bin/pytest -x --ignore=tests/live 2>&1 | tail -20`
Expected: all tests pass.

- [ ] **Step 8: 🛑 HUMAN VERIFICATION GATE — desktop AND mobile footer**

Post this exact message to the operator and HALT (this gate has a real visual change, unlike Tasks 2/3):

> "Footer grid corrected from 4 cols → 2 cols. The dev server is running at `http://localhost:5000`. Two things to verify:
>
> **At desktop width (≥769px window):** Scroll to the bottom of `http://localhost:5000/al/birmingham/`. The 'About' and 'For citizens' columns should now span the full width of the page container (each ~50% with 32px gap), instead of sitting in the left half with empty whitespace on the right.
>
> **At mobile width (<768px, e.g. devtools responsive mode at iPhone 14):** Scroll to the bottom of the same page. The footer accordion should behave EXACTLY as before — first column open by default, tapping a closed column header expands it. **No change at mobile is expected.**
>
> Reply 'approved' to proceed to commit, or describe what looks off."

**Do not run the next step until the operator replies with explicit approval.**

- [ ] **Step 9: Commit**

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

**Background:** This task splits into two phases — programmatic route-smoke (agent runs) and visual sweep (operator runs). The agent must complete the programmatic phase, then HALT at the human gate before declaring P1 done.

**Files:** read-only verification of all rendered pages.

- [ ] **Step 1: Re-run the full pytest suite**

Run: `venv/bin/pytest --ignore=tests/live 2>&1 | tail -10`
Expected: all tests pass.

- [ ] **Step 2: Programmatic route-smoke — confirm every page in scope returns HTTP 200**

The dev server should be running on port 5000 from Task 2. For each URL, curl with `-o /dev/null -w '%{http_code}\n'` to capture only the status code:

Run:
```bash
for path in \
  "/" \
  "/al/birmingham/" \
  "/al/birmingham/meetings/" \
  "/al/birmingham/council/" \
  "/search" \
  "/topics/" \
  "/coverage/" \
  "/about/" \
  "/about/how-we-read-minutes/" \
  "/about/corrections/" \
  "/councilors/"; do
  code=$(curl -sS -o /dev/null -w "%{http_code}" "http://localhost:5000${path}")
  echo "${code} ${path}"
done
```

Expected: every line begins with `200`. Any `5xx` is a regression — STOP and investigate.

For meeting-detail and item-detail (parameterized routes), pick one meeting_id and one item_id from the local DB:

Run: `psql -d docket_db -c "SELECT id FROM meetings WHERE municipality_id = (SELECT id FROM municipalities WHERE slug='birmingham') ORDER BY date DESC LIMIT 1;"`

Use that ID:
```bash
mid=$(psql -d docket_db -tA -c "SELECT id FROM meetings WHERE municipality_id = (SELECT id FROM municipalities WHERE slug='birmingham') ORDER BY date DESC LIMIT 1;")
iid=$(psql -d docket_db -tA -c "SELECT id FROM agenda_items WHERE meeting_id = ${mid} LIMIT 1;")
curl -sS -o /dev/null -w "%{http_code} /al/birmingham/meetings/${mid}/\n" "http://localhost:5000/al/birmingham/meetings/${mid}/"
curl -sS -o /dev/null -w "%{http_code} /al/birmingham/items/${iid}/\n" "http://localhost:5000/al/birmingham/items/${iid}/"
```

Expected: both `200`.

- [ ] **Step 3: Programmatic token sweep — confirm tokens are served on every page response**

Tokens are in `styles.css`, included via `<link>` from `base.html`. If `base.html` renders, every page references the file. Confirm one fetch of the file shows all 15 tokens (7 type + 8 space):

Run: `curl -sS http://localhost:5000/static/styles.css | grep -cE -- "--(type|space)-"`
Expected: `15` or higher (the count of matching lines — 7 type + 8 space = 15 lines, possibly more if any other `--type-*` or `--space-*` rules exist in the file).

- [ ] **Step 4: Confirm `git log` shows three clean commits**

Run: `git log --oneline -5`
Expected: three commits at the top (type tokens, spacing tokens, footer grid fix) authored to `hello@docket.pub`. Earlier commits are pre-P1.

- [ ] **Step 5: 🛑 HUMAN VERIFICATION GATE — full visual sweep**

Post this exact message to the operator and HALT:

> "P1 programmatic verification complete: all routes return 200, all 15 tokens served, pytest green, three clean commits in the log. Before P1 can be considered done, please run a visual sweep:
>
> **At desktop width (≥1024px window):**
> - `/` — homepage
> - `/al/birmingham/` — city overview
> - `/al/birmingham/meetings/` — meeting list
> - One meeting detail
> - One item detail
> - `/al/birmingham/council/` — council roster
> - `/al/birmingham/<any-badge>/` — category landing (e.g., `/budget/`)
> - `/search`, `/topics/`, `/coverage/`, `/about/`
>
> **Expected difference:** the **footer** now spans full width at desktop (no right-side whitespace). Every other element should look unchanged.
>
> **At mobile width (<768px, devtools responsive mode):**
> - Same page list
> - Footer accordion still works (first column open, tap to expand others)
> - **Expected difference: none.**
>
> Reply 'approved' if everything looks right, or describe regressions. Once approved, P1 local work is done and ready for PR + merge + deploy (Task 6)."

**Do not declare P1 complete until the operator replies with explicit approval.**

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

- [ ] **Step 4: Programmatic production verification — confirm tokens are live on docket.pub**

CDN/browser caches will mask a successful deploy if you check via a normal browser request without a cache-bust. The agent should use a cache-busting query param so curl gets fresh bytes:

Run: `curl -sS "https://docket.pub/static/styles.css?v=$(date +%s)" | grep -cE -- "--(type|space)-"`
Expected: `15` or higher (same count as the local check in Task 5 Step 3). If `0`, the deploy didn't pick up the change OR a CDN layer is serving an older asset — investigate before proceeding.

Confirm a specific token sample:

Run: `curl -sS "https://docket.pub/static/styles.css?v=$(date +%s)" | grep -- "--type-hero:"`
Expected: a line matching `--type-hero:        64px;` (or with similar whitespace).

Confirm the footer grid fix is live:

Run: `curl -sS "https://docket.pub/static/tweaks.css?v=$(date +%s)" | grep -A 1 "footnote-cols"`
Expected output includes `grid-template-columns: repeat(2, 1fr);`.

- [ ] **Step 5: Skim Railway logs for any new errors after deploy**

Run: `railway logs --service docket-web 2>&1 | tail -50`
Expected: no new 500s, no template render errors, no static-asset 404s.

- [ ] **Step 6: 🛑 HUMAN VERIFICATION GATE — production visual confirmation**

Post this exact message to the operator and HALT:

> "P1 deployed to Railway. Programmatic checks confirm the new tokens + footer grid fix are live in the served CSS. **Browser/CDN caches will lie to you on the first visit** — please do a hard refresh (Cmd+Shift+R on Mac, Ctrl+Shift+R elsewhere) on `https://docket.pub/al/birmingham/` before checking, or append `?v=$(date +%s)` to the URL to bypass cache. Then:
>
> 1. Confirm the desktop footer spans full width (no right-side whitespace).
> 2. Confirm the mobile footer accordion still works.
> 3. Confirm no other visible regression on the page.
>
> If anything looks wrong on first hard-refresh, try a private/incognito window — that bypasses local cache definitively. If still wrong, the deploy may need a Railway redeploy or there's a CDN issue worth flagging.
>
> Reply 'approved' once production looks correct."

**Do not declare P1 fully shipped until the operator replies with explicit approval.**

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

Agent-execution audit (added after first review pass):
- ✓ No "open browser" / "open devtools" / "resize window" instructions for the agent — all visual verification routed to **Human Verification Gates** that explicitly HALT and request operator approval
- ✓ Programmatic verification uses `curl`, `grep`, `awk`, `pytest`, `psql`, and Railway CLI — all CLI-native, agent-executable
- ✓ Syntax-check uses the dynamic `awk '/^:root {/{flag=1} flag; /^}/{flag=0; print ""; exit}'` extractor instead of hardcoded `sed -n 'M,Np'` line bounds that would silently break if upstream changes alter line numbers
- ✓ Type-scale audit regex in Task 1 Step 2 includes `26` (the mono-numeric value) — was missing in the first pass
- ✓ Production verification (Task 6 Step 4) appends `?v=$(date +%s)` cache-bust to every CDN-served URL and explicitly tells the operator to hard-refresh before visual confirmation
