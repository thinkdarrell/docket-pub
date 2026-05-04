# Repo Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate two GitHub repos into one (`thinkdarrell/docket-pub`) and merge three feature branches into `main`, ending with a single repo + single local clone where `main` is the live source of truth and Railway deploys from `main`.

**Architecture:** In-repo merges first (preserves Railway deploy stability), then GitHub repo rename (only after `main` carries production-equivalent code), then local clone cleanup, then docs/memory updates. Rollback anchors via `pre-consolidation/*` tags pushed to remote before any destructive work.

**Tech Stack:** Git, GitHub CLI (`gh`), Railway dashboard, macOS shell.

**Spec:** `docs/superpowers/specs/2026-05-03-repo-consolidation-design.md`

**Working directory throughout Phase 0–2:** `/Users/darrellnance/docket-pub-dw-dev`
**Working directory after Phase 3:** `/Users/darrellnance/docket-pub`

---

## Phase 0 — Pre-flight safety net

### Task 0.1: Verify working tree state on the active clone

**Files:** none (read-only inspection)

- [ ] **Step 1: Confirm CWD and branch**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && pwd && git branch --show-current
```

Expected output:
```
/Users/darrellnance/docket-pub-dw-dev
main
```

- [ ] **Step 2: Confirm working tree is clean (ignoring untracked junk we know about)**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git status --short
```

Expected output (only `data/` and `.DS_Store` artifacts; no `M` or `A` lines):
```
?? data/
?? docs/superpowers/.DS_Store
```

- [ ] **Step 3: Confirm no stashes or unmerged work hiding**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git stash list && echo "---branches---" && git branch
```

Expected: empty stash list. Local branches should be `main`, `feat/ai-summaries-scoring`, `feat/vote-agenda-matching`, `feat/mobile-responsive`.

If anything else appears, STOP and investigate before proceeding.

### Task 0.2: Push local commits that the merges will need

**Files:** push only — no edits.

- [ ] **Step 1: Push the spec commit on `main`**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git push origin main
```

Expected output: a `main` push with one new commit (`3a47135 Add repo consolidation design spec`).

- [ ] **Step 2: Push the mobile-responsive branch (so PR #3 has a remote head)**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git push --set-upstream origin feat/mobile-responsive
```

Expected output: new remote branch created from `8fe21c0 Add mobile responsive layout (Plan A — lightweight launcher)`.

- [ ] **Step 3: Verify both branches are on origin**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git ls-remote --heads origin | grep -E "(main|mobile-responsive)"
```

Expected output: two lines, one for each branch ref.

### Task 0.3: Create safety tags on every branch HEAD

**Files:** none (tag operations).

- [ ] **Step 1: Fetch latest refs**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git fetch origin
```

- [ ] **Step 2: Create the four safety tags**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && \
  git tag pre-consolidation/main          origin/main && \
  git tag pre-consolidation/vote-matching origin/feat/vote-agenda-matching && \
  git tag pre-consolidation/ai            origin/feat/ai-summaries-scoring && \
  git tag pre-consolidation/mobile        origin/feat/mobile-responsive
```

Expected: no errors.

- [ ] **Step 3: Push tags to remote**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git push origin --tags
```

Expected output:
```
 * [new tag]         pre-consolidation/main          -> pre-consolidation/main
 * [new tag]         pre-consolidation/vote-matching -> pre-consolidation/vote-matching
 * [new tag]         pre-consolidation/ai            -> pre-consolidation/ai
 * [new tag]         pre-consolidation/mobile        -> pre-consolidation/mobile
```

- [ ] **Step 4: Verify tags exist on remote**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git ls-remote --tags origin | grep pre-consolidation
```

Expected: 4 lines.

---

## Phase 1 — Merge feature branches into `main`

### Task 1.1: Open PR #1 — vote-agenda-matching → main

**Files:** none (GitHub PR creation).

- [ ] **Step 1: Confirm PR #1 head and base**

Head: `feat/vote-agenda-matching` (43 commits ahead of `main`). Base: `main`.

- [ ] **Step 2: Open the PR**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && \
gh pr create --base main --head feat/vote-agenda-matching \
  --title "Merge vote-agenda-matching: N:M vote↔item matcher + migrations 009-011" \
  --body "$(cat <<'EOF'
Brings the N:M vote-to-agenda-item matcher work into main.

## What lands

- `vote_agenda_items` join table replaces the singular `votes.agenda_item_id` FK
- Substantive (1:1) and consent-block (1:N) matchers via `_classify_vote` dispatch
- `_upsert_link()` enforces the `is_manual` shield at app + DB level
- `strict_reparse_meeting` promotes provisional consent links to official after council adoption
- `services/minutes_adoption.py:sweep_adoptions` resolves "Approval of Minutes from <date>"
- Migrations 009 (schema), 010 (backfill 187 prior matches), 011 (drop deprecated singular columns) — already applied to Railway prod

## Migration safety

All three migrations are already in `schema_migrations` on Railway prod. Runner will skip them on next deploy.

## Self-review checklist

- [ ] Diff makes sense at a glance (43 commits)
- [ ] Migration files (009, 010, 011) present and runnable
- [ ] No CLAUDE.md changes that conflict with what's on main

Spec: `docs/superpowers/specs/2026-05-01-vote-agenda-matching-design.md`
Plan: `docs/superpowers/plans/2026-05-01-vote-agenda-matching-plan.md`
EOF
)"
```

Expected output: a PR URL like `https://github.com/thinkdarrell/docket-pub-dw-dev/pull/1`.

- [ ] **Step 3: Capture the PR URL** for the merge step.

### Task 1.2: Self-review and merge PR #1

**Files:** none (GitHub UI action).

- [ ] **Step 1: Open the PR in browser**

```bash
gh pr view --web --repo thinkdarrell/docket-pub-dw-dev <PR_NUMBER_FROM_1.1>
```

Or open the URL captured in Task 1.1.

- [ ] **Step 2: Skim the "Files changed" tab**

Focus areas (per spec):
- `src/docket/migrations/009_*.py`, `010_*.py`, `011_*.py` — should be three new migration files
- `src/docket/analysis/vote_matcher.py` — N:M dispatch, `_upsert_link`
- `src/docket/services/minutes_adoption.py` — `sweep_adoptions`
- `src/docket/services/query.py` — `list_votes` 3-query reader
- `src/docket/web/templates/meeting_detail.html` — substantive vs consent-block branching

- [ ] **Step 3: Click "Merge pull request" → "Create a merge commit"**

This is GitHub's `--no-ff` equivalent. Confirm with the default merge commit message.

- [ ] **Step 4: Pull merged main locally and verify**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git checkout main && git pull origin main
git log --oneline -5
```

Expected: a merge commit at the top, followed by 43 vote-matching commits in the history.

- [ ] **Step 5: Verify migration files exist on main**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && ls src/docket/migrations/ | grep -E "^(009|010|011)"
```

Expected: three files (`009_vote_agenda_items.py`, `010_backfill_vote_agenda_items.py`, `011_drop_deprecated_vote_columns.py`).

### Task 1.3: Open PR #2 — ai-summaries-scoring → main

**Files:** none (GitHub PR creation).

- [ ] **Step 1: Confirm PR #2 will show only the AI delta**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git rev-list --count main..origin/feat/ai-summaries-scoring
```

Expected: a number in the high 70s (76 minus any commits already merged via PR #1's vote-matching foundation; should be ~33 unique AI commits since vote-matching brought 43 along).

If the number is near 119, PR #1 didn't actually merge — STOP and re-verify Task 1.2.

- [ ] **Step 2: Open the PR**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && \
gh pr create --base main --head feat/ai-summaries-scoring \
  --title "Merge ai-summaries-scoring: AI pipeline + migration 012 (LIVE on Railway)" \
  --body "$(cat <<'EOF'
Brings the AI summarization pipeline into main. Already deployed to Railway from this branch since 2026-05-02.

## What lands

- `src/docket/ai/` package: exceptions, pricing, results (Pydantic), contexts, prompts, client, worker, cli (8 modules)
- Migration 012: adds `summary, ai_metadata, ai_prompt_version, ai_generated_at` to `agenda_items` and `meetings`; new `ai_runs` cost-telemetry table
- Item prompt v2 (procedural-skip) and meeting prompt v2 (distinctive-vs-routine split at sig=6)
- Daily budget gate via `AI_DAILY_BUDGET_USD`
- Admin dashboard at `/admin/ai`
- Worker uses `SELECT FOR UPDATE SKIP LOCKED` for concurrency safety

## Migration safety

Migration 012 is already in `schema_migrations` on Railway prod (applied 2026-05-02). Runner will skip on next deploy from main.

## Self-review checklist

- [ ] PR shows ~33 commits (just the AI delta, not 119)
- [ ] Migration 012 present
- [ ] No conflicts with vote-matching work

Spec: `docs/superpowers/specs/2026-05-01-summaries-and-scoring-design.md`
Plan: `docs/superpowers/plans/2026-05-01-summaries-and-scoring-plan.md`
EOF
)"
```

Expected output: a new PR URL.

### Task 1.4: Self-review and merge PR #2

**Files:** none (GitHub UI action).

- [ ] **Step 1: Open PR in browser** (same `gh pr view --web`).

- [ ] **Step 2: Skim "Files changed"**

Focus areas:
- `src/docket/ai/` directory — 8 new modules
- `src/docket/migrations/012_*.py` — migration file
- `src/docket/web/templates/admin/ai*.html` — admin panel templates
- `src/docket/web/templates/meeting_detail.html` — executive summary rendering
- `src/docket/web/templates/partials/council_card.html` — new shared partial (matters for mobile rebase)

- [ ] **Step 3: Merge via "Create a merge commit"**.

- [ ] **Step 4: Pull and verify**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git checkout main && git pull origin main && git log --oneline -10
```

Expected: a second merge commit at the top.

- [ ] **Step 5: Verify AI package + migration 012 exist on main**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && ls src/docket/ai/ && ls src/docket/migrations/ | grep "^012"
```

Expected: 8 files in `src/docket/ai/` (exceptions.py, pricing.py, results.py, contexts.py, prompts.py, client.py, worker.py, cli.py + `__init__.py`); one file matching `012_*.py`.

- [ ] **Step 6: Verify main HEAD content equals what was on feat/ai-summaries-scoring HEAD**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git diff main..pre-consolidation/ai -- src/docket/
```

Expected: empty diff (the merge brought in everything; only the safety tag's earlier HEAD differs by missing the merge commits themselves).

### Task 1.5: Re-point Railway from feat/ai-summaries-scoring → main

**Files:** none (Railway dashboard action).

- [ ] **Step 1: Open Railway dashboard for the docket-web service**

URL: `https://railway.app/project/<your-project>/service/docket-web/settings`

- [ ] **Step 2: Update the source branch**

In Settings → Source → Branch, change from `feat/ai-summaries-scoring` to `main`. Save.

- [ ] **Step 3: Trigger a deploy**

Either click "Deploy" or push a no-op commit to main. The platform will pull from `main` and build.

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git checkout main && git commit --allow-empty -m "Trigger Railway redeploy from main after consolidation" && git push origin main
```

- [ ] **Step 4: Watch the deploy**

In Railway dashboard, "Deployments" tab. Wait for the build to succeed and the new release to be promoted.

- [ ] **Step 5: Verify production health**

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://docket-web-production-6110.up.railway.app/
```

Expected: `200`.

- [ ] **Step 6: Spot-check the AI features**

Open `https://docket-web-production-6110.up.railway.app/admin/ai` (you'll need to log in). Confirm:
- Queue depth shows expected counts
- 7-day cost is non-zero (AI has been running)
- Recent runs list is populated

If 500 or wrong content, STOP. Roll back via Railway dashboard "Redeploy" on the previous successful deployment.

### Task 1.6: Create safety branch for mobile, then rebase onto new main

**Files:** none (branch operations).

- [ ] **Step 1: Confirm we're on main and up to date**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git checkout main && git pull origin main
```

- [ ] **Step 2: Create safety backup of mobile-responsive**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git branch feat/mobile-responsive-backup feat/mobile-responsive
```

- [ ] **Step 3: Switch to mobile-responsive and rebase onto main**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git checkout feat/mobile-responsive && git rebase main
```

Expected: rebase will likely report conflicts on the 11 templates listed below. The rebase pauses with `CONFLICT` messages.

If rebase succeeds with NO conflicts (unlikely): skip to Task 1.8.

### Task 1.7: Resolve template conflicts (mobile rebase)

**Files (the 11 conflicting templates):**
- Modify: `src/docket/web/templates/base.html`
- Modify: `src/docket/web/templates/city.html`
- Modify: `src/docket/web/templates/council.html`
- Modify: `src/docket/web/templates/index.html`
- Modify: `src/docket/web/templates/meetings.html`
- Modify: `src/docket/web/templates/search.html`
- Modify: `src/docket/web/templates/topic_detail.html`
- Modify: `src/docket/web/templates/topics.html`
- Modify: `src/docket/web/templates/partials/masthead.html`
- Modify: `src/docket/web/templates/partials/rail_default.html`
- Modify: `src/docket/web/static/tweaks.css`
- (Likely also: `src/docket/web/templates/partials/council_card.html` if AI branch added it)

**New files (should apply cleanly with NO conflicts):**
- `src/docket/web/static/mobile.css`
- `src/docket/web/static/sheet.js`
- `src/docket/web/templates/partials/bottom_tabs.html`
- `src/docket/web/templates/partials/source_sheet.html`

**Tactical approach (per spec Q3):** for each conflicting file, accept the AI version as the base, then layer mobile UI tweaks back in.

- [ ] **Step 1: Identify all conflicting files at this rebase pause**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git status --short | grep "^UU"
```

Expected: list of conflicting files, all under `src/docket/web/templates/` and possibly `static/tweaks.css`.

- [ ] **Step 2: For `base.html` — resolve conflict**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git checkout --theirs src/docket/web/templates/base.html
```

This takes the main-branch version (the AI-aware one). Now layer in the mobile additions:

Edit `src/docket/web/templates/base.html` to:
- Add `<link rel="stylesheet" href="{{ url_for('static', filename='mobile.css') }}">` AFTER the existing CSS links and BEFORE `</head>` (mobile.css must load LAST so its `@media` rules win)
- Update the viewport meta to: `<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">`
- Add `<meta name="theme-color" content="#fafaf7">`
- Inside `<body>`, AFTER the `<div class="app">` block but inside `{% block body %}`, add:
  ```html
  {% include "partials/source_sheet.html" %}
  {% include "partials/bottom_tabs.html" %}
  ```
- BEFORE `</body>`, add: `<script src="{{ url_for('static', filename='sheet.js') }}" defer></script>`

Then:

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git add src/docket/web/templates/base.html
```

- [ ] **Step 3: For `tweaks.css` — resolve conflict**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git checkout --theirs src/docket/web/static/tweaks.css
```

Then append the search form rules from the mobile commit. Open `tweaks.css` and add BEFORE the `.rail-empty-cta` block:

```css
/* search form (used on /search) */
.search-form {
  display: flex; flex-direction: column; gap: 12px;
  margin-top: 16px;
  max-width: 720px;
}
.search-form-row {
  display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
}
.search-select {
  height: 36px;
  padding: 0 10px;
  border: 1px solid var(--rule-strong);
  border-radius: 4px;
  background: var(--paper);
  font: inherit;
  font-size: 13px;
  color: var(--ink);
  cursor: pointer;
  flex: 1 1 200px;
  min-width: 0;
}
.search-select:focus { outline: 2px solid var(--accent); outline-offset: 2px; }
```

Then:

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git add src/docket/web/static/tweaks.css
```

- [ ] **Step 4: For `partials/masthead.html` — resolve conflict**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git checkout --theirs src/docket/web/templates/partials/masthead.html
```

Inside the `<div class="masthead-row">`, AFTER the `<div class="topsearch">` block (which is the desktop search input), add a mobile-only search button:

```html
{# Mobile-only: compact search icon button. Hidden on desktop via mobile.css. #}
<button class="mobile-search-btn"
        type="button"
        aria-label="Search"
        data-href="{{ url_for('public.search', city=municipality.slug) if (municipality is defined and municipality) else url_for('public.search') }}">
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>
    </svg>
</button>
```

Then:

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git add src/docket/web/templates/partials/masthead.html
```

- [ ] **Step 5: For `partials/rail_default.html` — resolve conflict**

The mobile branch's update to `rail_default.html` improves the default copy and adds source-document links. Take the mobile branch's version (this content is BETTER than main's old wording even on desktop):

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git checkout --ours src/docket/web/templates/partials/rail_default.html
```

(`--ours` here means the rebased branch's version — i.e., the mobile branch's edit.)

Then verify it doesn't reference any data the AI-branch query.py doesn't supply (the mobile version uses `municipality.adapter_class`, `meeting_count`, etc. — all standard fields):

```bash
cd /Users/darrellnance/docket-pub-dw-dev && grep -E "(municipality\.|meeting_count|members)" src/docket/web/templates/partials/rail_default.html
```

If any unsupported variable is referenced, edit accordingly. Otherwise:

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git add src/docket/web/templates/partials/rail_default.html
```

- [ ] **Step 6: For `index.html`, `meetings.html`, `search.html`, `topic_detail.html`, `topics.html` — resolve conflicts**

These pages on `main` (post-AI) may be either bare (raw HTML) or already polished. Check each:

```bash
cd /Users/darrellnance/docket-pub-dw-dev && for f in index meetings search topic_detail topics; do
  echo "=== $f.html (main version) ==="
  git show main:src/docket/web/templates/$f.html | head -10
done
```

For each file:

**If the main version is bare (raw `<h1>`, `<div>`):** take the mobile branch's editorial version (mobile branch did the polish):
```bash
git checkout --ours src/docket/web/templates/<file>.html && git add src/docket/web/templates/<file>.html
```

**If the main version is already polished (has `.hero`, `.feed`, etc.):** take the main version as base, then layer in any mobile-specific additions:
```bash
git checkout --theirs src/docket/web/templates/<file>.html
```
Then manually inspect the mobile branch's version (`git show feat/mobile-responsive-backup:src/docket/web/templates/<file>.html`) for any mobile-specific changes (e.g., `class="mobile-search-btn"`, doc-availability sub-lines on `.feed-meeting-sub`) and re-apply.

```bash
git add src/docket/web/templates/<file>.html
```

- [ ] **Step 7: For `city.html` — resolve conflict (the most complex)**

The mobile branch made these changes to `city.html`:
1. Reordered sections: "Recent meetings" feed appears BEFORE "Council members" (was after)
2. Added doc-availability sub-line under each meeting title (`agenda · video` etc.)
3. Added a doc-count cell (`{{count}} doc{{s}}`)
4. Added "All meetings →" link in the feed header

Take main's version as base (it has the AI summary integrations etc.):

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git checkout --theirs src/docket/web/templates/city.html
```

Then re-apply the four mobile changes by looking at:

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git show feat/mobile-responsive-backup:src/docket/web/templates/city.html > /tmp/mobile-city.html
diff src/docket/web/templates/city.html /tmp/mobile-city.html | head -80
```

Apply the four edits manually, then:

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git add src/docket/web/templates/city.html
```

- [ ] **Step 8: For `council.html` — resolve conflict (special: AI branch added council_card.html partial)**

If `partials/council_card.html` exists on main (the AI branch's shared partial):

```bash
cd /Users/darrellnance/docket-pub-dw-dev && ls src/docket/web/templates/partials/council_card.html
```

If it exists, the mobile rules in `mobile.css` for the 3x3 grid (`.cc`, `.cc-portrait`, etc.) work via class selectors so they apply to the partial without modification. Just take main's `council.html` and the partial as-is:

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git checkout --theirs src/docket/web/templates/council.html
git add src/docket/web/templates/council.html
```

If `council_card.html` does NOT exist (mobile branch's version has the markup inline), take the mobile branch's version:
```bash
git checkout --ours src/docket/web/templates/council.html && git add src/docket/web/templates/council.html
```

- [ ] **Step 9: Verify all conflicts resolved**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git status --short
```

Expected: no `UU` lines. All previously conflicting files show `M` (modified) or `A` (added).

- [ ] **Step 10: Continue the rebase**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git rebase --continue
```

Expected: rebase completes successfully. If it pauses again on a different commit, the same conflict-resolution pattern applies.

### Task 1.8: Smoke-test the rebased mobile branch locally

**Files:** none (server check).

- [ ] **Step 1: Confirm branch state**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git branch --show-current && git log --oneline -3
```

Expected: branch = `feat/mobile-responsive`; HEAD = the (rebased) mobile commit; second commit = the most recent main HEAD.

- [ ] **Step 2: Start the dev server**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && venv/bin/flask --app 'docket.web:create_app()' run --host 0.0.0.0 --port 5050 &
```

- [ ] **Step 3: Verify desktop pages load**

```bash
sleep 2 && for url in / /al/birmingham/ /al/birmingham/meetings/ /al/birmingham/council/ /search /topics/; do
  echo "$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5050${url})  ${url}"
done
```

Expected: every line starts with `200`.

- [ ] **Step 4: Verify mobile chrome is in the rendered HTML**

```bash
curl -s http://localhost:5050/al/birmingham/ | grep -c "bottom-tabs\|view-source-pill\|mobile-search-btn\|source-sheet"
```

Expected: 4+ (one match per partial/element).

- [ ] **Step 5: Verify AI executive summary still renders**

```bash
curl -s http://localhost:5050/al/birmingham/ | grep -c "executive_summary\|ai_metadata\|t-eyebrow.*[Ss]ummary"
```

If main's `meeting_detail.html` renders an executive summary, this should match. If output is 0, that's only OK if the local DB has no AI data — verify by browsing Railway prod instead.

- [ ] **Step 6: Stop the dev server**

```bash
kill $(lsof -ti :5050)
```

If smoke tests fail: STOP. Inspect the rebase output, restore from `feat/mobile-responsive-backup`, retry the conflict resolution.

### Task 1.9: Push rebased mobile branch and open PR #3

**Files:** none.

- [ ] **Step 1: Force-push the rebased branch**

The original `feat/mobile-responsive` was based on the old `main`. Rebasing changed its history. Force-push to update the remote.

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git push --force-with-lease origin feat/mobile-responsive
```

`--force-with-lease` is safer than `--force`: it refuses if anyone else pushed to the branch since you fetched.

- [ ] **Step 2: Open PR #3**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && \
gh pr create --base main --head feat/mobile-responsive \
  --title "Merge mobile-responsive: mobile layout (Plan A) on top of AI-aware templates" \
  --body "$(cat <<'EOF'
Adds mobile responsive layout. Rebased onto current main (post vote-matching + AI merges) so the 11 templates carry both AI logic AND mobile chrome.

## What lands

- Single `@media (max-width: 768px)` block in new `static/mobile.css`
- ~150 lines vanilla JS in new `static/sheet.js`
- New partials: `bottom_tabs.html` (5-tab nav), `source_sheet.html` (native `<dialog>` bottom sheet + persistent "View source" pill)
- Mobile-only: 3-column council grid, horizontal scroll-snap KPI/this-week strips, footer accordion
- City overview: meetings before council, doc-availability sub-line on each meeting row
- Editorial polish on previously-bare templates (search, topics, topic_detail, meetings, index, council)

## Self-review checklist

- [ ] AI features still render (executive summary, item summaries, AI badges)
- [ ] Mobile chrome works (bottom tabs visible at <=768px, View Source pill, source sheet)
- [ ] HTMX targets unchanged (still `#source-rail`)

Spec: `Downloads/2026-05-03-mobile-responsive-design.md` (external; not in repo)
EOF
)"
```

Expected: a PR URL.

### Task 1.10: Self-review and merge PR #3

**Files:** none (GitHub UI action).

- [ ] **Step 1: Open in browser** and review the diff. Focus on the 11 conflict-resolved templates — verify both AI shapes AND mobile classes are present.

- [ ] **Step 2: Merge via "Create a merge commit"**.

- [ ] **Step 3: Pull and verify locally**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && git checkout main && git pull origin main && git log --oneline -10
```

Expected: third merge commit at the top.

- [ ] **Step 4: Trigger Railway deploy + verify**

Railway should auto-deploy from the push to main. Watch the dashboard.

```bash
sleep 60 && curl -s -o /dev/null -w "%{http_code}\n" https://docket-web-production-6110.up.railway.app/
```

Expected: `200`.

- [ ] **Step 5: Phone smoke test**

Visit `https://docket-web-production-6110.up.railway.app/al/birmingham/` on your phone. Expected:
- Bottom tab bar appears
- View source pill bottom-right
- Tapping things navigates / opens sheet appropriately
- AI executive summary visible on meeting detail (if data exists)

If anything breaks: STOP. Roll back via Railway "Redeploy" on the previous successful deployment, investigate, fix, redeploy.

---

## Phase 2 — Repo rename on GitHub

### Task 2.1: Archive the empty `thinkdarrell/docket-pub` repo

**Files:** none (GitHub action).

- [ ] **Step 1: Confirm `thinkdarrell/docket-pub` is the empty/abandoned one**

```bash
gh repo view thinkdarrell/docket-pub --json name,description,pushedAt
```

Expected output should show `pushedAt` from April 26 (old) and a "Municipal meeting intelligence platform" description.

- [ ] **Step 2: Archive it**

```bash
gh repo archive thinkdarrell/docket-pub --yes
```

Expected output: `✓ Archived repository thinkdarrell/docket-pub`.

- [ ] **Step 3: Verify archived**

```bash
gh repo view thinkdarrell/docket-pub --json isArchived
```

Expected output: `{"isArchived": true}`.

### Task 2.2: Rename `docket-pub-dw-dev` → `docket-pub`

**Files:** none (GitHub action).

- [ ] **Step 1: Rename via gh CLI**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && gh repo rename docket-pub --repo thinkdarrell/docket-pub-dw-dev --yes
```

Expected output: `✓ Renamed repository thinkdarrell/docket-pub`.

If gh CLI fails with permissions, do it via web UI: navigate to `https://github.com/thinkdarrell/docket-pub-dw-dev/settings`, scroll to "Repository name", change to `docket-pub`, click Rename.

- [ ] **Step 2: Verify the new name**

```bash
gh repo view thinkdarrell/docket-pub --json name,pushedAt
```

Expected: `{"name": "docket-pub", "pushedAt": "..."}` showing today's date.

- [ ] **Step 3: Verify the old URL still redirects**

```bash
curl -s -o /dev/null -w "%{http_code}\n" -L https://github.com/thinkdarrell/docket-pub-dw-dev
```

Expected: `200` (GitHub follows the rename redirect to the new URL).

### Task 2.3: Verify Railway integration follows the rename

**Files:** none (Railway dashboard action).

- [ ] **Step 1: Open Railway service → Settings → Source**

URL: `https://railway.app/project/<your-project>/service/docket-web/settings`

- [ ] **Step 2: Confirm the linked repo shows the new name**

If the dashboard shows `thinkdarrell/docket-pub`, you're good. If it still shows the old name AND won't update on click, click "Disconnect" then "Connect" → reauthorize the GitHub App → select `thinkdarrell/docket-pub` and branch `main`.

- [ ] **Step 3: Trigger a no-op deploy to confirm the hook works**

```bash
cd /Users/darrellnance/docket-pub-dw-dev && \
git remote set-url origin https://github.com/thinkdarrell/docket-pub.git && \
git commit --allow-empty -m "Trigger Railway deploy after repo rename" && \
git push origin main
```

- [ ] **Step 4: Watch Railway deploy** in the dashboard. Expected: build kicks off automatically.

If it doesn't kick off: re-link via Disconnect → Reconnect (Step 2 fallback).

---

## Phase 3 — Local clone cleanup

### Task 3.1: Stop all running processes using the active clone

**Files:** none.

- [ ] **Step 1: Confirm no Flask dev server, file watchers, etc. are running**

```bash
lsof -ti :5050 :5000 :8000 2>/dev/null | xargs -r kill 2>/dev/null
ps aux | grep -E "(flask|python.*docket)" | grep -v grep
```

Expected: no remaining docket-related processes.

- [ ] **Step 2: Close any IDE windows or editor tabs** with files in `~/docket-pub-dw-dev` open. (Manual check.)

### Task 3.2: Verify the abandoned `~/docket-pub` clone has no unique work

**Files:** none (read-only inspection).

- [ ] **Step 1: Check uncommitted changes**

```bash
cd /Users/darrellnance/docket-pub && git status --short
```

Expected: empty.

- [ ] **Step 2: Check stashes**

```bash
cd /Users/darrellnance/docket-pub && git stash list
```

Expected: empty.

- [ ] **Step 3: Check for local-only branches**

```bash
cd /Users/darrellnance/docket-pub && git branch
```

Expected: only `main` (and `gh-pages` if you ever touched it). Both should track `origin/...`.

- [ ] **Step 4: Compare local main to origin main**

```bash
cd /Users/darrellnance/docket-pub && git fetch origin && git log origin/main..main --oneline
```

Expected: empty (no local commits ahead of origin).

If anything is non-empty: STOP. Export the unique work first (e.g., `git stash show -p > /tmp/saved-stash.patch`).

### Task 3.3: Two-step rename of the local directory

**Files:** none (filesystem moves).

- [ ] **Step 1: Move the active clone to a temp name**

```bash
mv /Users/darrellnance/docket-pub-dw-dev /Users/darrellnance/docket-pub-new
```

- [ ] **Step 2: Verify the temp path works**

```bash
cd /Users/darrellnance/docket-pub-new && git status --short && git remote -v
```

Expected: clean status; remote points to `https://github.com/thinkdarrell/docket-pub.git` (was set in Task 2.3).

- [ ] **Step 3: Remove the abandoned old clone**

```bash
rm -rf /Users/darrellnance/docket-pub
```

- [ ] **Step 4: Move the temp name to the canonical name**

```bash
mv /Users/darrellnance/docket-pub-new /Users/darrellnance/docket-pub
```

- [ ] **Step 5: Verify final state**

```bash
ls -la /Users/darrellnance | grep docket
cd /Users/darrellnance/docket-pub && git status --short && git branch && pwd
```

Expected: only `docket-pub` (not `docket-pub-dw-dev` or `docket-pub-new`); branches include `main` plus the feature branches we'll clean up later.

### Task 3.4: Verify the relocated clone still works end-to-end

**Files:** none (functional check).

- [ ] **Step 1: Start dev server from new path**

```bash
cd /Users/darrellnance/docket-pub && venv/bin/flask --app 'docket.web:create_app()' run --port 5050 &
sleep 2 && curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5050/
```

Expected: `200`.

If venv binaries fail with hardcoded path errors (rare): recreate the venv:
```bash
cd /Users/darrellnance/docket-pub && rm -rf venv && python3 -m venv venv && venv/bin/pip install -e ".[dev]"
```

- [ ] **Step 2: Stop the dev server**

```bash
kill $(lsof -ti :5050)
```

---

## Phase 4 — Documentation cleanup

### Task 4.1: Update CLAUDE.md to remove dev-fork references

**Files:** Modify: `/Users/darrellnance/docket-pub/CLAUDE.md`

- [ ] **Step 1: Read current dev-fork section**

```bash
cd /Users/darrellnance/docket-pub && grep -n "Dev Fork Workflow\|docket-pub-dev\|docket-pub-dw-dev" CLAUDE.md
```

This shows you exactly which lines reference the dev fork.

- [ ] **Step 2: Remove the entire "Dev Fork Workflow" section**

Open `CLAUDE.md` and delete:
- The `## Dev Fork Workflow` heading
- All content under it through to (but not including) the next top-level section
- Any inline references to `docket-pub-dev` or `docket-pub-dw-dev` elsewhere

- [ ] **Step 3: Update "Related Repositories" section** (search for it; it lists repos):

Remove the line referring to `thinkdarrell/docket-pub-dev` or similar dev-fork URL. The remaining line should be the canonical repo name.

- [ ] **Step 4: Verify no leftover references**

```bash
cd /Users/darrellnance/docket-pub && grep -n "Dev Fork\|docket-pub-dev\|docket-pub-dw-dev" CLAUDE.md
```

Expected: no output.

- [ ] **Step 5: Commit and push**

```bash
cd /Users/darrellnance/docket-pub && git add CLAUDE.md && git commit -m "Remove dev-fork workflow from CLAUDE.md after repo consolidation

Single repo now: thinkdarrell/docket-pub. Railway deploys from main."
git push origin main
```

### Task 4.2: Update memory files

**Files:**
- Modify: `/Users/darrellnance/.claude-personal/projects/-Users-darrellnance/memory/MEMORY.md`
- Modify: `/Users/darrellnance/.claude-personal/projects/-Users-darrellnance/memory/project_docket_pub.md`

- [ ] **Step 1: Remove the schema-mismatch warning from MEMORY.md** (added during this session; obsolete after consolidation)

Open `MEMORY.md` and delete the bullet that begins:
> `- **Working on `main` locally is broken right now**: local DB has migrations 009/010/011/012 applied...`

- [ ] **Step 2: Update `feat/ai-summaries-scoring` bullet in MEMORY.md** to reflect merged state:

Change:
```
- **`feat/ai-summaries-scoring` branch**: fully pushed to origin and DEPLOYED to Railway...
```

To:
```
- **AI pipeline (formerly `feat/ai-summaries-scoring`)**: merged into main on 2026-05-03 during repo consolidation. Live on Railway from main.
```

- [ ] **Step 3: Update `project_docket_pub.md` to reflect single-repo state**

Open `project_docket_pub.md` and find the "**Repos:**" section. Replace it with:
```markdown
**Repo:**
- `thinkdarrell/docket-pub` (private) — single canonical repo. Railway deploys from `main`.
- `thinkdarrell/docket-pub-dw-dev` was renamed to `thinkdarrell/docket-pub` on 2026-05-03 during consolidation. The original empty `docket-pub` was archived.
- `thinkdarrell/al-municipal-meetings` — original Birmingham pipeline, separate project.
- Local clone at `/Users/darrellnance/docket-pub` (was `~/docket-pub-dw-dev` before consolidation).
```

- [ ] **Step 4: Memory files don't need a git commit** (they're outside the repo).

### Task 4.3: Optional — clean up merged feature branches

**Files:** none (branch deletes).

Run these only if you've verified Railway has been stable on `main` for at least an hour, and you're confident you don't need to revisit the feature branches.

- [ ] **Step 1: Delete remote feature branches**

```bash
cd /Users/darrellnance/docket-pub && \
  git push origin --delete feat/vote-agenda-matching && \
  git push origin --delete feat/ai-summaries-scoring && \
  git push origin --delete feat/mobile-responsive
```

- [ ] **Step 2: Delete local feature branches**

```bash
cd /Users/darrellnance/docket-pub && \
  git branch -D feat/vote-agenda-matching feat/ai-summaries-scoring feat/mobile-responsive feat/mobile-responsive-backup
```

- [ ] **Step 3: Keep the `pre-consolidation/*` tags forever** (they're cheap and useful as historical anchors). Don't delete them.

- [ ] **Step 4: Verify final branch state**

```bash
cd /Users/darrellnance/docket-pub && git branch -a
```

Expected output: just `main` locally and `remotes/origin/main` (plus tags).

---

## Self-review summary

**Spec coverage check:**
- ✅ Phase 0 (safety tags) covered by Task 0.3
- ✅ Phase 1 (PR #1, PR #2, Railway repoint, mobile rebase, PR #3) covered by Tasks 1.1–1.10
- ✅ Phase 2 (archive + rename) covered by Tasks 2.1–2.3
- ✅ Phase 3 (local cleanup) covered by Tasks 3.1–3.4
- ✅ Phase 4 (docs + memory + optional cleanup) covered by Tasks 4.1–4.3
- ✅ Rollback strategy covered inline in spec; safety tags created in Task 0.3 enable it

**Total tasks:** 17 (4 in Phase 0, 10 in Phase 1, 3 in Phase 2, 4 in Phase 3, 3 in Phase 4 — Phase 4.3 optional).

**Estimated total time:**
- Phases 0 + 1.1–1.5 (mechanical): ~30 minutes
- Phase 1.6–1.8 (rebase + conflict resolution): **30–60 minutes** (bulk of the work)
- Phases 1.9–4 (mechanical): ~30 minutes

**Critical-path notes:**
- Task 1.5 (Railway repoint) MUST succeed before Task 1.6 (mobile rebase). If Railway breaks on `main`, fix that first.
- Task 1.7 (rebase conflicts) is the hardest part. Plan for it; don't rush.
- Task 2.1 (archive) MUST happen before Task 2.2 (rename) — GitHub won't let you take the `docket-pub` name while the abandoned repo holds it.
- Task 3.3 destructive ops (`rm -rf`) — Task 3.2 pre-checks are non-skippable.
