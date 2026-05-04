# Repo consolidation — design

**Status:** READY FOR PLAN
**Date:** 2026-05-03
**Owner:** Darrell + Claude Code

---

## Goal

Collapse the docket.pub work — currently scattered across two GitHub repos and three feature branches — into a single repo with `main` as the source of truth.

## Current state (problem)

Two real GitHub repos exist:

| Repo | Last push | Content |
|---|---|---|
| `thinkdarrell/docket-pub` | 2026-04-26 | Abandoned skeleton: `main` (2 commits) + `gh-pages`. Just `CLAUDE.md` + planning docs. |
| `thinkdarrell/docket-pub-dw-dev` | 2026-05-02 | All real development. `main` (3 commits, mostly planning) + `feat/vote-agenda-matching` (+43 commits) + `feat/ai-summaries-scoring` (+76 commits, **deployed to Railway**). |

Locally, two clones mirror this split:
- `~/docket-pub` (the abandoned-repo clone)
- `~/docket-pub-dw-dev` (where all work happens, including newly-committed `feat/mobile-responsive`)

Result: documentation references a dev-fork workflow that never got followed; `main` on both repos is a stub; feature branches contain the real product, including the live Railway build.

## End state (success criteria)

- **One repo on GitHub:** `thinkdarrell/docket-pub` (matches the `docket.pub` domain).
- **One local clone:** `~/docket-pub`.
- **`main` contains all current product work**: vote-matching N:M (migrations 009-011), AI pipeline (migration 012), and mobile responsive layout.
- **Railway deploys from `main`**, not from a feature branch.
- **Old `thinkdarrell/docket-pub` repo archived** (read-only, retained for history).
- **Feature branches deleted** locally and on remote after their merges land.
- **`CLAUDE.md` updated** to remove the obsolete "Dev Fork Workflow" section and reflect single-repo state.

## Non-goals

- Not changing the `docket-pub-site` repo (that's a separate landing-page project; remains untouched).
- Not modifying the `al-municipal-meetings` repo (separate Birmingham pipeline project).
- Not rewriting commit history of feature branches (preserve all individual commits via `--no-ff` merges).
- Not touching the live Railway database or migrations on prod (009-012 are already applied).

---

## Approach: in-repo merges first, then GitHub rename, then local cleanup

Merging on the existing `docket-pub-dw-dev` repo first (before any rename) keeps Railway's deploy hook stable while we operate. Rename and local-clone moves come after `main` is verified equivalent to the currently-deployed `feat/ai-summaries-scoring` HEAD.

### Phase 0 — Pre-flight safety net

Tag every branch HEAD before touching anything. These tags are the rollback anchors.

```
git tag pre-consolidation/main          origin/main
git tag pre-consolidation/vote-matching origin/feat/vote-agenda-matching
git tag pre-consolidation/ai            origin/feat/ai-summaries-scoring
git tag pre-consolidation/mobile        feat/mobile-responsive
git push origin --tags
```

Also: confirm working tree is clean on every clone (`git status` returns empty), no uncommitted experiments lurking.

### Phase 1 — Merge feature branches into `main`

**Step 1.1 — PR #1: `feat/vote-agenda-matching` → `main`** (`--no-ff`)

- Created via `gh pr create --base main --head feat/vote-agenda-matching`.
- Self-review the diff (43 commits). Focus areas: migrations 009/010/011, the N:M `vote_agenda_items` join, `_upsert_link` shield, sweep_adoptions logic.
- Merge with `--no-ff` to preserve foundation history (merge commit signals "this is when N:M landed on main").
- Acceptance: `main` HEAD content equals `feat/vote-agenda-matching` HEAD content (one merge commit on top).

**Step 1.2 — PR #2: `feat/ai-summaries-scoring` → `main`** (`--no-ff`)

- Created **after** PR #1 has merged so this PR shows only the 76-commit AI delta (not 119+ commits).
- Self-review. Focus areas: `src/docket/ai/` package, prompts.py versions, migration 012, AI worker scope, `ai_runs` telemetry.
- Merge with `--no-ff`.
- Acceptance: `main` HEAD content equals `feat/ai-summaries-scoring` HEAD content (with merge commits on top).

**Step 1.3 — Re-point Railway from `feat/ai-summaries-scoring` → `main`**

- Pre-check: confirm `git diff origin/feat/ai-summaries-scoring origin/main` is empty (post-merge `main` should be functionally equivalent).
- Update Railway service source branch to `main` (Settings → Source → Branch).
- Trigger a deploy; verify health-check passes.
- DB has migrations 009-012 already in `schema_migrations`; runner skips already-applied. No DB churn expected.
- Acceptance: Railway deployment is green from `main`; site loads; `/admin/ai` panel shows expected stats.

**Step 1.4 — Rebase `feat/mobile-responsive` onto new `main`**

- Branch a safety copy first: `git branch feat/mobile-responsive-backup feat/mobile-responsive`.
- `git checkout feat/mobile-responsive && git rebase main`.
- Resolve conflicts on the 11 templates. Tactical approach (per Q3 dialog):
  - **Accept "theirs" (AI version) as the base** for each conflicting template — the AI logic must survive.
  - **Re-apply mobile UI tweaks on top** of the AI-shaped markup (small, mostly class-additions and structural reflow).
  - **Push mobile changes into `partials/council_card.html`** where the AI branch moved the per-member markup.
- New files (`mobile.css`, `sheet.js`, `bottom_tabs.html`, `source_sheet.html`) should apply cleanly — no conflicts expected there.
- Acceptance: post-rebase, `flask run` works locally; phone smoke-test (375px DevTools or actual phone over LAN) shows AI features rendering AND mobile chrome working.

**Step 1.5 — PR #3: rebased `feat/mobile-responsive` → `main`** (`--no-ff`)

- Self-review focused on three checks:
  1. AI features still render on each touched page (executive summary on meeting_detail, item summaries, AI badges).
  2. Mobile chrome still works (bottom tabs, view-source pill, source sheet, footer accordion).
  3. HTMX targets unchanged (still `#source-rail`); existing rail swaps still function.
- Merge with `--no-ff`.
- Trigger Railway deploy from `main`; verify mobile site on phone.
- Acceptance: live Railway site at `docket-web-production-6110.up.railway.app` works on desktop AND mobile.

### Phase 2 — Repo rename on GitHub

**Step 2.1 — Archive `thinkdarrell/docket-pub`** (the abandoned skeleton)

- `gh repo archive thinkdarrell/docket-pub` (or via web UI: Settings → "Archive this repository").
- Archived repos are read-only but still browsable. This frees the name.

**Step 2.2 — Rename `thinkdarrell/docket-pub-dw-dev` → `thinkdarrell/docket-pub`**

- `gh repo rename docket-pub --repo thinkdarrell/docket-pub-dw-dev` or via web UI Settings.
- GitHub keeps URL redirects automatically for the old name.

**Step 2.3 — Verify Railway integration follows the rename**

- Open Railway dashboard → service → Settings → Source.
- Confirm the source repo shows as `thinkdarrell/docket-pub`. If it still shows the old name and won't update, disconnect and reconnect via the GitHub App.
- Trigger a no-op deploy or watch for the next push to confirm the hook fires.
- Acceptance: pushing to `main` on the renamed repo triggers a Railway build.

### Phase 3 — Local clone cleanup

**Step 3.1 — Update remote URL** in `~/docket-pub-dw-dev` (cosmetic; redirect works without this, but cleaner to update):
```
cd ~/docket-pub-dw-dev
git remote set-url origin https://github.com/thinkdarrell/docket-pub.git
git fetch origin
```

**Step 3.2 — Rename the local directory**

Two-step rename to avoid collision with the abandoned `~/docket-pub`:

1. Stop any processes using `~/docket-pub-dw-dev` (Flask dev server, file watchers, IDE).
2. `mv ~/docket-pub-dw-dev ~/docket-pub-new`
3. Verify the new path works: `cd ~/docket-pub-new && git status`
4. Remove the abandoned old clone: `rm -rf ~/docket-pub`. Pre-check three things from inside that directory: `git status --short` (empty), `git stash list` (empty), and `git branch` shows only branches that exist on origin. Anything unique to the local clone must be exported first.
5. `mv ~/docket-pub-new ~/docket-pub`

**Step 3.3 — Update environment references**

- IDE workspace files (`.vscode/`, `.idea/`, etc.) pointing to old path → update.
- Shell aliases / functions referencing the old path → update.
- The `.env` file is path-internal (`DATABASE_URL` etc.) so it follows the move.
- The Python venv path is internal (`venv/bin/python`); it follows the move but may need recreation if any binaries had absolute paths embedded — usually they don't.
- Acceptance: from the new `~/docket-pub` path, `venv/bin/python -c "from docket.web import create_app; create_app()"` succeeds.

### Phase 4 — Documentation cleanup

**Step 4.1 — Update `CLAUDE.md`** on `main`

- Remove the entire "Dev Fork Workflow" section (now obsolete — there's only one repo).
- Update "Related Repositories" to reflect the single repo.
- Single direct commit to `main` with message like `Remove dev-fork workflow from CLAUDE.md after repo consolidation`.

**Step 4.2 — Update memory files**

- `~/.claude-personal/projects/-Users-darrellnance/memory/project_docket_pub.md`: drop dev-fork references; reflect single-repo state; note Railway now deploys from `main`.
- `~/.claude-personal/projects/-Users-darrellnance/memory/MEMORY.md`: remove the schema-mismatch warning I added earlier (working on `main` is no longer broken once consolidation lands).

**Step 4.3 — Optional: clean up safety branches**

After confirming everything works for ~24h, delete:
- `feat/vote-agenda-matching` and `feat/ai-summaries-scoring` (locally and on remote — they're merged into main).
- `feat/mobile-responsive` and `feat/mobile-responsive-backup`.
- `pre-consolidation/*` tags can stay indefinitely (cheap, useful as historical anchors).

---

## Rollback strategy

| Phase | If it fails | Recovery |
|---|---|---|
| Phase 1 (merges) | Bad merge lands on `main` | `git reset --hard pre-consolidation/main` on `main`, force-push (only safe pre-rename, while you're the only consumer) |
| Phase 1 (rebase) | Mobile rebase mangles | Discard the rebase; restore from `feat/mobile-responsive-backup`. Worst case: defer mobile entirely (Plan C from brainstorm). |
| Phase 2 (archive) | Wrong repo archived | Unarchive in GitHub Settings — fully reversible. |
| Phase 2 (rename) | Rename clobbers Railway hook | Reconnect Railway to `thinkdarrell/docket-pub` via GitHub App. Or rename back to `docket-pub-dw-dev` (GitHub allows un-rename within 48h). |
| Phase 3 (local) | `mv` breaks something | Re-clone from `https://github.com/thinkdarrell/docket-pub.git` into `~/docket-pub` fresh. The remote is the source of truth. |
| Phase 4 (docs) | Wrong doc edits | Plain commits; revert with `git revert`. |

## Risks & mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Mobile rebase produces unworkable conflicts | Medium | Half-day of rework | Safety branch + Plan C fallback (ship vote+AI consolidation now, defer mobile) |
| Railway deploy hook breaks during repo rename | Low | Site goes down briefly | Reconnect manually via Railway settings; archive happens AFTER merges land so production is already on `main` before any rename |
| Migration runner re-runs an already-applied migration | Very low | Could break prod | Runner sorts by version + checks `schema_migrations`; verified pattern with prior deploys |
| Local clone has uncommitted experiments we don't know about | Low | Lost work | Pre-flight `git status` and `git stash list` on every clone before destructive moves |
| Renaming repo confuses git remote URLs in third-party tools (Railway, gh CLI, IDE git plugins) | Low | Manual reconnects | GitHub URL redirects mean most tools recover automatically; manual fix where needed |

## Open questions

None — all design questions have been answered through the brainstorming dialog. Implementation plan can proceed directly from this spec.
