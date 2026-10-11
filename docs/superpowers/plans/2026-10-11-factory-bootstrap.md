# Factory Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install factory-loop's artifact layer into docket-pub so the two factory workflows have a map, goals, architecture, principles, debt register, decision records, plan convention, and skills to read.

**Architecture:** Copy factory-loop's `template/` payload and `skills/` into the repo unmodified, then fill every skeleton from the content that today lives in CLAUDE.md, the design specs, and the operator's answers recorded in this plan. CLAUDE.md shrinks to one line that imports `AGENTS.md`. Nothing in `src/` changes. Every filled artifact is verified by running the searches and reference walks factory-loop's harness-init procedure names, not by reading.

**Tech Stack:** Markdown, git, POSIX shell, Python 3.10 venv (only to run the existing test suite as the published verify command).

**Spec:** `docs/superpowers/specs/2026-10-10-factory-cycle-design.md`, step 1 of "Order of work". Read sections 1, 5, and 6 before starting. The upstream procedure this plan follows is `skills/harness-init/SKILL.md` in the factory-loop checkout; this plan is that procedure with every answer filled in.

## Global Constraints

- Work only in the worktree `/Users/darrellnance/docket-pub/.claude/worktrees/factory-cycle` on branch `docs/factory-cycle-spec`. Run every shell command from there. Never touch `/Users/darrellnance/docket-pub` itself.
- Copy factory-loop files, never retype them. The payload comes from `/Users/darrellnance/projects/factory-loop` pinned at commit `bcbd3a42026a76325ca792c8295a02e78cdb1e41`.
- Never edit a copied format document or skill: `plans/PLANS.md`, `docs/capabilities/CARD_FORMAT.md`, `docs/decisions/DECISION_FORMAT.md`, the six card files, and everything under `skills/` stay byte-identical to upstream.
- Never overwrite a file the repo already has. If a copy would collide, stop and record the collision in this plan.
- No em dashes in prose anywhere in the new artifacts; use a comma, a colon, or a new sentence. The one exception is a heading where the upstream skeleton or format document itself puts an em dash: the `# NNNN — <statement>` title `docs/decisions/DECISION_FORMAT.md` mandates, the `### Dn — title` detail headings in `docs/DEBT.md`, and the `# <name> — agent guide` title of `AGENTS.md`. Each task's em dash count below follows from this rule.
- Every `grep -c` used as a check ends with `|| true`, because a zero count exits 1 and would abort a chained line.
- Before replacing any skeleton, confirm it is still a skeleton: `grep -c '{{FILL' <file> || true` must print a number above zero. If it prints 0, stop; someone already filled it.
- If `gh` is not authenticated or the active account is not `thinkdarrell`, stop and ask the operator to run `gh auth switch -u thinkdarrell` or `gh auth login` themselves; both are interactive and cannot be run by an agent.
- Commit email is `hello@docket.pub` (already configured in this worktree). Every commit message ends with the line `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- `AGENTS.md` stays under 100 lines. Count with `wc -l AGENTS.md` before committing it.
- A command published in `AGENTS.md` must have been run in this worktree during this plan, with its observed result recorded in the task that ran it.
- Never claim a capability status above `specced` or a maturity rung above L0.
- Do not start any feature work, fix any test, or build `tools/verify`. Those belong to plan one. This plan ends with an installed harness.

## Review Focus

Inputs the spec implies but no step's checks exercise directly. Each line names the owning task, which carries the check.

1. A backticked path in a filled artifact that names a directory with a trailing slash (`docs/decisions/`) must resolve as a directory, not fail the reference walk. Task 10's walk script handles both forms.
2. A `{{FILL` marker split across lines, or `GUIDANCE` appearing in legitimate prose (for example in a principle about guidance), would make the finish searches lie in either direction. Task 10 runs both searches and a reviewer reads every hit before deciding.
3. `CLAUDE.md` reduced to `@AGENTS.md` must actually import in Claude Code. Task 9 verifies the import syntax against the Claude Code docs with the claude-code-guide agent and records the answer.
4. The `.claude/skills` symlink must point at a relative path so it survives a clone to another directory. Task 1 creates it relative and checks it resolves.
5. The worktree's `venv` must import `src/docket` from the worktree, not from the main checkout, or every verify result in this and later plans describes the wrong tree. Task 0 proves the import path before anything else runs.

---

### Task 0: Environment and the venv trap

**Files:**
- Create: `/Users/darrellnance/projects/factory-loop` (clone, outside the repo)
- Create: `venv/` in the worktree (gitignored)
- Modify: `docs/superpowers/specs/2026-10-10-factory-cycle-design.md` (section 5, one paragraph)

**Interfaces:**
- Produces: `FL=/Users/darrellnance/projects/factory-loop`, the payload source every later task copies from. `venv/bin/python` in the worktree, the interpreter every published command uses.

- [ ] **Step 1: Clone factory-loop at the pinned commit**

```bash
cd /Users/darrellnance/projects
git clone https://github.com/bholzer/factory-loop.git
cd factory-loop
git checkout bcbd3a42026a76325ca792c8295a02e78cdb1e41
git rev-parse HEAD
```

Expected: the last line prints `bcbd3a42026a76325ca792c8295a02e78cdb1e41`. If the clone already exists, `git -C /Users/darrellnance/projects/factory-loop fetch && git checkout bcbd3a4` instead.

- [ ] **Step 2: Confirm the payload directory from factory-loop's own map**

```bash
grep -n 'template/' /Users/darrellnance/projects/factory-loop/AGENTS.md | head -3
ls /Users/darrellnance/projects/factory-loop/template /Users/darrellnance/projects/factory-loop/skills
```

Expected: the map names `template/` as the payload; `template` lists `AGENTS.md ARCHITECTURE.md GOALS.md docs plans`; `skills` lists `capability-build doc-garden harness-init plan-author plan-execute retro`.

- [ ] **Step 3: Prove the venv trap**

```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/factory-cycle
../../../venv/bin/python -c "import docket; print(docket.__file__)"
```

Expected: prints `/Users/darrellnance/docket-pub/src/docket/__init__.py`. That is the main checkout, not this worktree. The editable install in the main venv pins `docket` to the main checkout's `src`, so any test run from a worktree with that venv tests the wrong code.

- [ ] **Step 4: Build the worktree's own venv**

```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/factory-cycle
python3.10 -m venv venv
venv/bin/pip install -q -e ".[dev]"
venv/bin/python -c "import docket; print(docket.__file__)"
```

`python3.10` is on PATH on this machine (3.10.21 observed 2026-10-11). If it is not, use `/opt/homebrew/bin/python3.10`, or `brew install python@3.10` first; do not substitute a different minor version, because `requirements.lock` is compiled for 3.10.

Expected: the last line prints `/Users/darrellnance/docket-pub/.claude/worktrees/factory-cycle/src/docket/__init__.py`. Takes two to four minutes. `venv/` is already in `.gitignore`; confirm with `git status --porcelain | grep venv` printing nothing.

- [ ] **Step 5: Run the verify tier once to record the baseline**

```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/factory-cycle
time venv/bin/python -m pytest tests/unit tests/web tests/services -q --no-header -p no:cacheprovider 2>&1 | tail -3
```

Expected: a summary line like `1 failed, 1554 passed, 4 xfailed in 52s`. The one failure is `tests/web/test_blog_routes.py::test_city_route_filters_to_city_and_shared`. Record the exact summary line and wall time here in this plan under the step (append a line starting `Observed:`). If the counts differ from main's, that is fine; record what you saw.

Observed (2026-10-11, worktree on origin/main 3d08e5f): `5 failed, 1726 passed, 3 skipped, 4 xfailed, 2 warnings in 71.14s`; wall 1:13.80. Failures: four in `tests/web/test_blog_routes.py` (`test_city_route_filters_to_city_and_shared`, `test_post_detail_renders`, `test_post_detail_emits_twitter_card_meta`, `test_preview_token_reveals_draft`), all HTTP 500 from `BuildError: Could not build url for endpoint 'public.city_overview' with values ['slug']`; and `tests/web/test_city_overview_render.py::test_meeting_detail_source_links_below_executive_summary` (`kpi-grid section missing`). The plan's expectation of one failure came from the feature branch; main has five. D1 in Task 7 and the AGENTS.md command line in Task 9 are widened accordingly.

- [ ] **Step 6: Record the venv finding in the spec**

In `docs/superpowers/specs/2026-10-10-factory-cycle-design.md`, section 5 ("Isolation and branching"), after the paragraph that begins "`cycle-plan` creates branch", insert this paragraph:

```
Each worktree gets its own Python environment. The main checkout's venv holds an editable install that pins the `docket` package to the main checkout's `src/`, so a test run from a worktree using that venv silently tests the wrong tree. `cycle-plan` therefore runs `python3.10 -m venv venv && venv/bin/pip install -e ".[dev]"` inside the new worktree after creating it, and every published command uses `venv/bin/python` relative to the worktree. The `isolated-env` capability card is where this becomes a mechanical check.
```

Also add to the "Known unknowns" list at the end of the spec:

```
- Whether a two-to-four-minute venv build per worktree is acceptable at the start of every `cycle-plan`, or whether a shared wheel cache (`pip install --cache-dir`) should be configured. Measured on the first real plan.
```

- [ ] **Step 7: Commit**

```bash
git add docs/superpowers/specs/2026-10-10-factory-cycle-design.md
git commit -m "docs: spec section 5, each worktree needs its own venv (editable install trap)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 1: Install the payload and the procedures, unfilled

**Files:**
- Create: `AGENTS.md`, `GOALS.md`, `ARCHITECTURE.md` (skeletons)
- Create: `docs/PRINCIPLES.md`, `docs/MATURITY.md`, `docs/DEBT.md`, `docs/decisions/DECISION_FORMAT.md`, `docs/specs/index.md`, `docs/capabilities/*.md` (7 files: `index.md`, `CARD_FORMAT.md`, and six cards)
- Create: `plans/PLANS.md`, `plans/active/.gitkeep`, `plans/completed/.gitkeep`
- Create: `skills/<six>/SKILL.md`
- Create: `.claude/skills` (symlink to `../skills`)

**Interfaces:**
- Produces: every path later tasks fill. Nothing is filled here; this task's commit is the unmodified upstream payload so the diff of every later commit shows exactly what docket-pub added.

- [ ] **Step 1: Check for collisions before copying**

```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/factory-cycle
FL=/Users/darrellnance/projects/factory-loop
(cd $FL/template && find . -type f) | while read f; do [ -e "$f" ] && echo "COLLISION: $f"; done; echo "collision check done"
[ -e skills ] && echo "COLLISION: skills/"; [ -e .claude/skills ] && echo "COLLISION: .claude/skills"; echo done
```

Expected: only the two `done` lines. `docs/` exists but none of the payload's filenames under it exist here (`docs/specs`, `docs/decisions`, `docs/capabilities`, `PRINCIPLES.md`, `MATURITY.md`, `DEBT.md` are all new). If any COLLISION line prints, stop, record it in this plan, and resolve it before copying.

- [ ] **Step 2: Copy the payload and the skills**

```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/factory-cycle
FL=/Users/darrellnance/projects/factory-loop
cp -Rn $FL/template/. .
cp -Rn $FL/skills ./skills
git status --porcelain | wc -l
```

Expected: about 24 new paths. `-n` refuses to overwrite, which is the harness-init rule.

- [ ] **Step 3: Verify byte identity of the copied set**

```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/factory-cycle
FL=/Users/darrellnance/projects/factory-loop
LC_ALL=C diff -r $FL/template . --brief 2>/dev/null | grep -v '^Only in \.' ; echo "template diff done"
diff -r $FL/skills skills --brief; echo "skills diff done"
```

Expected: only the two `done` lines (differences that begin `Only in .` are docket-pub's own files and are filtered).

- [ ] **Step 4: Make the skills reachable by Claude Code**

```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/factory-cycle
ln -s ../skills .claude/skills
ls -l .claude/skills
ls .claude/skills/plan-execute/SKILL.md
```

Expected: `.claude/skills -> ../skills` and the second `ls` prints the path. The link is relative so a clone elsewhere still resolves. Check `.gitignore` does not exclude it: `git check-ignore .claude/skills` prints nothing.

- [ ] **Step 5: Commit the unfilled installation**

```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/factory-cycle
git add AGENTS.md GOALS.md ARCHITECTURE.md docs/PRINCIPLES.md docs/MATURITY.md docs/DEBT.md docs/decisions docs/specs docs/capabilities plans skills .claude/skills
git commit -m "chore: install factory-loop payload and skills, unfilled (upstream bcbd3a4)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git show --stat HEAD | tail -3
```

Expected: roughly 24 files changed, all insertions.

---

### Task 2: Fill GOALS.md

**Files:**
- Modify: `GOALS.md` (replace the skeleton entirely)

**Interfaces:**
- Produces: the scope and non-goals every later plan is graded against. `docs/PRINCIPLES.md` (Task 3) and `docs/DEBT.md` (Task 7) refer to constraints and unknowns stated here.

The content below is the operator's interview answers, drafted on 2026-10-11 from CLAUDE.md, the design specs, and the operator's memory notes. The operator's review of this plan is the interview: any correction they make during that review is edited into this task before execution, and approval of the plan is approval of this text. Do not pause for a second confirmation during execution.

- [ ] **Step 1: Confirm GOALS.md is still a skeleton, then replace it with this content**

```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/factory-cycle
grep -c '{{FILL' GOALS.md || true
```

Expected: a number above zero. Then replace the file:

```markdown
# Goals

## Purpose

docket.pub ingests, parses, and indexes the public meeting records of Alabama municipalities and publishes them as a searchable site. A resident can find what their council voted on, who sponsored it, what it cost, and read the city's own document that says so. Every fact on the site links back to that source document. The project is in a private development phase: the site is live at https://docket.pub but has not been announced.

## Outcomes

- A resident can open any Birmingham City Council meeting back to 2005 and see its agenda items, the vote of each member, the dollar amounts involved, and a link to the official minutes or the video.
- A reader can search across cities and land on an item page whose headline and "why it matters" text trace to the source text, with the AI prompt version and generation time stored beside them.
- A journalist can subscribe to editorial coverage by RSS and cite docket.pub item and meeting pages as stable permalinks.
- New meetings, votes, summaries, and video OCR appear within a day of the city publishing them without an operator touching anything.

## Success conditions

- Every citizen-facing data point renders a source badge and a link that resolves to the city's own document.
- Facts derived from video OCR and facts from official minutes are labelled distinctly everywhere they appear, and a disagreement between them is shown as a disagreement.
- Every scheduled worker task pings its Healthchecks.io check on schedule; a missed ping pages the operator.
- The published verify command in `AGENTS.md` passes on `main`.
- Daily AI spend stays under `AI_DAILY_BUDGET_USD`; the admin dashboard at `/admin/ai` shows it.
- No AI-generated sentence is shown without its prompt version and generated-at timestamp stored on the same row.

## Scope

Alabama municipalities whose meeting platforms the adapters support: Granicus (Birmingham), CivicClerk (Vestavia Hills, Mobile), generic HTML archives (Homewood), and CivicPlus (adapter exists, no city yet produces data). Birmingham is the deep case and the only city with votes, video OCR, and transcripts. One operator runs the project.

The repository is the project's only memory. Multi-file or multi-session work runs under a plan in `plans/active/` following `plans/PLANS.md`. Design specs and plans written before this convention arrived live under `docs/superpowers/` and are history, not current behaviour.

The agent harness artifacts and the procedures under `skills/` come from the harness blueprint at https://github.com/bholzer/factory-loop, checked out at `/Users/darrellnance/projects/factory-loop`, whose `docs/guide/adopting.md` is the adopter guide.

Related repositories: `thinkdarrell/al-municipal-meetings` is the original Birmingham scraper and remains a research sandbox; `thinkdarrell/docket-pub-site` is the separate landing page; `thinkdarrell/docket-pub-archived` is a read-only pre-consolidation skeleton.

## Non-goals

- A public REST API: deferred until public launch because of the security surface it opens; the security checklist in `docs/SECURITY_CHECKLIST.md` gates launch.
- Replacing Flask and HTMX with a JavaScript frontend such as Astro: the current stack renders everything the outcomes need; re-evaluate only if a concrete rendering limit appears.
- Coverage outside Alabama: depth in one state's records is the product.
- Editorial opinion beyond what the records support: summaries describe what the body did; the editorial coverage feature cites outside journalism rather than writing it.
- Absorbing `al-municipal-meetings` into this repository: the video OCR pipeline was ported in 2026-05; the rest stays a sandbox.
- Running our own language models: summaries use the Anthropic API behind a daily budget cap.
- Autonomous choice of what to build next: the operator states goals; the factory plans and executes them.
- Deploying from inside any automated loop: a human deploys from `main` after a pull request merges.

## Constraints

- The production Postgres volume on Railway is small (1 GB). Per-row bulk updates across tens of thousands of rows overflow its write-ahead log and have crashed the database; bulk changes use one targeted SQL statement.
- The Railway worker idles near 954 MB; an OCR scan adds roughly 750 MB. Nothing may spawn a second heavy Python process on the worker.
- Daily AI spend is capped by `AI_DAILY_BUDGET_USD` and every batch respects it.
- Scraping city sites uses polite delays of at least one second between requests.
- `railway up` deploys whatever is in the local working tree, so deploys happen only from a clean `main` after merge, through `scripts/deploy.sh`.
- Local Postgres is version 16; Railway runs 18.3. Dumps and restores against Railway use the postgresql@18 binaries.
- Commits in this repository use the `hello@docket.pub` identity and the `thinkdarrell` GitHub account.
- New Anthropic API call sites mirror the tool-use pattern in `src/docket/ai/client.py` and are smoke-tested live before they ship.

## Known unknowns

- Will Hoover (CivicPlus) or Montgomery ever publish data the adapters can read?
- Can the 89 percent of minutes votes with no linked agenda item be linked without a language-model fallback, or is that the floor?
- Does a factory workflow run survive a multi-hour plan without being cut off? The first real plan measures this.
- What does public launch require beyond `docs/SECURITY_CHECKLIST.md`, and when?
- Is a two-to-four-minute venv build per worktree acceptable at the start of every plan?
```

- [ ] **Step 2: Confirm no scaffolding survived**

```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/factory-cycle
grep -c '{{FILL' GOALS.md || true; grep -c GUIDANCE GOALS.md; grep -c '—' GOALS.md || true
```

Expected: `0`, `0`, `0`.

- [ ] **Step 3: Commit**

```bash
git add GOALS.md
git commit -m "docs: fill GOALS.md from operator interview

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Fill docs/PRINCIPLES.md

**Files:**
- Modify: `docs/PRINCIPLES.md` (replace the skeleton entirely)

**Interfaces:**
- Produces: the six rules `AGENTS.md` (Task 9) tells agents to read before data-touching changes, and the rules doc-garden and retro grade against.

- [ ] **Step 1: Confirm docs/PRINCIPLES.md is still a skeleton, then replace it with this content**

```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/factory-cycle
grep -c '{{FILL' docs/PRINCIPLES.md || true
```

Expected: a number above zero. Then replace the file (text supplied by the operator on 2026-10-11 from their own draft):

```markdown
# Principles

Six rules that outrank convenience in this repository. Constraints imposed from outside live in `GOALS.md`; these are chosen.

## Source or silence

The rule: every data point shown to a reader links to the city's own document, and a value the source does not supply is shown as missing rather than filled with a plausible default.
Violated when: an LLM summary hallucinates a name, date, or dollar amount not strictly present in the source text; a template renders a fact without a corresponding source link or badge; or a SQL query maps a NULL to "0", "Unknown", or an assumed default on its way to the page.

## Keep the sources apart

The rule: a fact from video OCR and a fact from the official minutes carry their origin wherever they travel, are never merged into one column without a source flag, and a disagreement between them is displayed as a disagreement, not resolved by code.
Violated when: a migration, query, or data model uses `COALESCE()` or similar logic on a column that carries source provenance to merge OCR and minutes data into one field; or a page displays one vote count when the two underlying sources disagree.

## Framing follows the data

The rule: editorial text says what the record shows and does not manufacture balance, caveats, or a second side the record does not contain.
Violated when: an AI prompt or summary adds "on the other hand," "weighing the options," or "critics might say" without an explicit agenda item, recorded vote, or source citation supporting that opposition; or when editorializing adjectives replace raw municipal facts.

## Evidence or silence

The rule: a change is reported as working only after the command that proves it has run and its output was observed; a change to a data pipeline is compared old against new on real rows before it ships.
Violated when: an agent, plan, or PR claims a test passed or a fix worked without recording the `pytest` summary line or the script's output; a pipeline change is shipped on unit tests alone without a recorded SQL `SELECT` showing before-and-after results on real data; or a plan names the command that *would* prove the change instead of what running it actually printed.

## Production is not a sandbox

The rule: nothing runs a per-row sweep, a full re-ingest, or an unbounded batch against the Railway database or the Anthropic API; bulk changes are one targeted SQL statement with a WHERE clause, and batches are bounded by a limit and the daily budget.
Violated when: an agent writes an `UPDATE` or `DELETE` statement against `DATABASE_PUBLIC_URL` without a strict, narrow `WHERE` clause; a CLI API invocation omits the `--limit` flag; or a script loops per-row writes over thousands of production rows instead of issuing one statement, which is what overflowed the write-ahead log and crash-looped the production database on 2026-05-12.

## One owner per fact

The rule: every fact about this project lives in exactly one file, and every other file that needs it links there instead of restating it.
Violated when: an agent hardcodes prompt rules, API constraints, or badge definitions inside a service module rather than importing them from the module or table that owns them (`src/docket/ai/prompts.py`, `src/docket/ai/badges_policy.py`, `src/docket/config.py`, the `priority_badge_templates` table); or two files state the same detail (such as a cron schedule in prose vs. `scheduler.py`) and one quietly goes stale.
```

- [ ] **Step 2: Confirm no scaffolding survived**

```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/factory-cycle
grep -c '{{FILL' docs/PRINCIPLES.md || true; grep -c GUIDANCE docs/PRINCIPLES.md; grep -c '—' docs/PRINCIPLES.md || true
```

Expected: `0`, `0`, `0`.

- [ ] **Step 3: Commit**

```bash
git add docs/PRINCIPLES.md
git commit -m "docs: fill PRINCIPLES.md, six rules

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Fill ARCHITECTURE.md, verifying each rule against the code

**Files:**
- Modify: `ARCHITECTURE.md` (replace the skeleton entirely)

**Interfaces:**
- Consumes: nothing.
- Produces: the layer map `boundary-lint` would enforce and the "Known rough edges" that become debt rows D7 and D8 in Task 7. The rough-edge list must match what the greps in Step 1 actually find.

- [ ] **Step 1: Run the layer-rule greps and record what they print**

```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/factory-cycle
echo "--- web modules that execute SQL directly"
grep -rl 'cur.execute\|db_cursor\|db()' src/docket/web/*.py
echo "--- inner layers importing services or web"
grep -rn 'from docket.web\|from docket.services\|import docket.services' src/docket/adapters src/docket/analysis src/docket/enrichment src/docket/ai src/docket/models src/docket/blog 2>/dev/null
echo "--- services importing web or worker"
grep -rn 'from docket.web\|from docket.worker' src/docket/services
echo "--- models importing anything above them"
grep -rn 'from docket\.' src/docket/models | grep -v 'from docket.models'
```

Expected on 2026-10-11: six web files (`auth.py`, `admin_badge_review.py`, `admin.py`, `create_admin.py`, `source_security.py`, `public.py`); four inner-layer imports of `docket.services` (`enrichment/cli.py:14`, `ai/batch_ingest.py:252`, `ai/pipeline.py:70`, `ai/badges_policy.py:106`); nothing for the last two. Record the actual output under this step as `Observed:` lines. If the counts differ, the "Known rough edges" section below is edited to match reality before committing.

- [ ] **Step 2: Confirm ARCHITECTURE.md is still a skeleton, then replace it with this content, adjusting the rough edges to Step 1's output**

```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/factory-cycle
grep -c '{{FILL' ARCHITECTURE.md || true
```

Expected: a number above zero. Then replace the file:

```markdown
# Architecture

## Shape

docket.pub is a Python application with three runtime processes sharing one PostgreSQL database: a Flask web app that serves citizens and an authenticated admin, an APScheduler worker that ingests, analyses, and summarises on a daily schedule, and command-line entry points an operator runs by hand. A fourth process, the transcriber, runs on a separate desktop machine and writes transcripts through a database role restricted to the transcript tables. Every city's meeting platform is reached through an adapter that implements one protocol, so the rest of the system never knows which vendor a city uses. The organising idea is that the service layer owns every transaction: web routes, worker tasks, and CLIs call services, and services call adapters, analysis, enrichment, and the AI pipeline.

## Components

### Adapters

- Lives in: `src/docket/adapters/`
- Owns: fetching meetings, agenda items, and document links from one vendor platform (Granicus, CivicClerk, CivicPlus, generic HTML archive) and returning them as the raw dataclasses in `src/docket/models/protocol.py`.
- Does not: write to the database or decide what a meeting means; `services/ingest.py` does both.

### Models

- Lives in: `src/docket/models/`
- Owns: the dataclasses for meetings, agenda items, votes, member votes, and vote-to-item links, and the `MunicipalSourceAdapter` protocol.
- Does not: touch the database or import any other layer.

### Services

- Lives in: `src/docket/services/`
- Owns: every transaction. Ingest (scrape, enrich, upsert, then sweep minutes adoptions), query (all reads for the web layer), enrichment, maintenance, minutes adoption, video OCR orchestration, badges, coverage, archived-meeting backfill.
- Does not: render HTML, schedule itself, or talk to a vendor site directly.

### Analysis

- Lives in: `src/docket/analysis/`
- Owns: turning documents into facts: the Birmingham minutes PDF parser (attendance and votes), the approval-title date parser, the N:M vote-to-agenda matcher with its provisional-to-official promotion, and the video OCR subpackage (`ocr/`: classifier, header, layout, sequence, pipeline, rosters).
- Does not: decide when to run; services and the worker call it.

### Enrichment

- Lives in: `src/docket/enrichment/`
- Owns: deterministic extraction from item text: dollar amounts and tiers, sponsors, keyword topics.
- Does not: call a language model.

### AI pipeline

- Lives in: `src/docket/ai/`
- Owns: the Anthropic client with its tool-use pattern and retries, prompt versions, Wave 0 non-LLM classification, Stage 1 extraction, Stage 2 Smart Brevity rewrite, Stage 2.5 reconcile, badge policy, batch submission and ingest, cost telemetry, the operator CLI, and the daily budget gate.
- Does not: serve pages or own the cron schedule.

### Worker

- Lives in: `src/docket/worker/`
- Owns: the APScheduler process on the Railway `worker` service, the task wrappers that call services, and Healthchecks.io pings. The schedule is the code in `scheduler.py`, not any prose.
- Does not: contain business logic.

### Web

- Lives in: `src/docket/web/`
- Owns: the Flask app factory, public routes and HTMX partials, admin routes, session auth, Jinja templates and the design-system CSS.
- Does not: by rule, execute SQL; see Known rough edges.

### Blog

- Lives in: `src/docket/blog/`
- Owns: loading markdown posts with frontmatter from `content/` and rendering them under each city.
- Does not: touch meeting data.

### Migrations

- Lives in: `src/docket/migrations/`
- Owns: numbered schema migrations and the runner that applies, rolls back, and reports them.
- Does not: seed data outside a numbered migration.

### Scripts

- Lives in: `scripts/`
- Owns: one-off backfills and operator tools, including `deploy.sh`.
- Does not: get scheduled; anything recurring moves into the worker.

### Transcriber

- Lives in: `transcriber/`
- Owns: the desktop producer that transcribes council video and uploads through the `transcriber` database role, which can write only the transcript tables and its heartbeat.
- Does not: read or write any other table.

## Layer map and dependency rules

From outermost to innermost: entry points (`web/`, `worker/`, `ai/cli.py`, `enrichment/cli.py`, `migrations/runner.py`, `scripts/`), then `services/`, then the domain layers (`adapters/`, `analysis/`, `enrichment/`, `ai/`, `blog/`), then `models/`, `db.py`, and `config.py`. Dependencies point inward only.

- Nothing under `src/docket/services/` may import from `src/docket/web/` or `src/docket/worker/`.
- Nothing under `src/docket/adapters/`, `src/docket/analysis/`, `src/docket/enrichment/`, or `src/docket/blog/` may import from `src/docket/services/`, `src/docket/web/`, or `src/docket/worker/`. Exception: `enrichment/cli.py` is an entry point and may import services.
- Nothing under `src/docket/models/` may import from any other `docket` package.
- Nothing under `src/docket/web/` may call `db()` or `db_cursor()` or execute SQL; it calls services.
- `src/docket/ai/` may not import from `src/docket/services/`. This rule is currently violated; see Known rough edges.

## Cross-cutting invariants

- Services own transactions; a transaction opened anywhere else is a defect.
- Every row produced from a source document stores a link to that document and the source kind (`minutes_text`, `video_ocr`, `api`).
- Configuration reaches code only through `src/docket/config.py`, which reads environment variables; no module reads `os.environ` directly for a setting that config already exposes.
- Anything that writes a shared queue row claims it with `FOR UPDATE SKIP LOCKED` so a second worker instance is safe.
- Prompt and schema versions are compared with a floor (`>=`), never equality.

## Known rough edges

- Six web modules execute SQL directly (`auth.py`, `admin.py`, `admin_badge_review.py`, `create_admin.py`, `source_security.py`, `public.py`), contrary to the web rule above. Tracked as `D7` in `docs/DEBT.md`.
- `src/docket/ai/` imports `docket.services.badges` in three places, an inward layer reaching outward. Tracked as `D8` in `docs/DEBT.md`.
- `src/docket/rosters/` is named in older documentation but does not exist; council rosters are scraped by adapters and stored by migration. No debt row: the reference is removed in this bootstrap.
```

- [ ] **Step 3: Confirm every path named in the file exists**

```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/factory-cycle
grep -o '`[^`]*`' ARCHITECTURE.md | tr -d '`' | grep -E '^(src|scripts|transcriber|content|docs)/' | sort -u | while read p; do [ -e "$p" ] || echo "MISSING: $p"; done; echo walk done
grep -c '{{FILL' ARCHITECTURE.md || true; grep -c GUIDANCE ARCHITECTURE.md; grep -c '—' ARCHITECTURE.md || true
```

Expected: `walk done` with no MISSING lines, then `0`, `0`, `0`. `src/docket/rosters/` is deliberately not backticked in the rough-edges line because it must not resolve.

- [ ] **Step 4: Commit**

```bash
git add ARCHITECTURE.md
git commit -m "docs: fill ARCHITECTURE.md, layer map verified by grep, two rough edges

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Write the decision records

**Files:**
- Create: `docs/decisions/0001-...md` through `docs/decisions/0030-...md`

**Interfaces:**
- Consumes: `docs/decisions/DECISION_FORMAT.md` (four fields: Decision, Rationale, Date, Status). Do not edit that file.
- Produces: thirty files `AGENTS.md` maps to and that CLAUDE.md's "Key decisions to preserve" section is deleted in favour of (Task 9).

Each file follows the format exactly: title `# NNNN — <statement>` is the one place an em dash is required by the upstream format, so it is allowed in the H1 only. Date is `2026-10-11, recorded at harness bootstrap from CLAUDE.md and operator notes; original decision date where known in parentheses`. Status is `accepted` for all thirty.

- [ ] **Step 1: Create the thirty files from this table, in three batches**

For each row, create `docs/decisions/<NNNN>-<slug>.md` with the Decision text as given and a Rationale of two to five sentences expanding the rationale column. Where the rationale column names an incident date, include it.

Work in three batches so no single step generates more than ten files: 0001 to 0010, then 0011 to 0020, then 0021 to 0030. After each batch run `ls docs/decisions | grep -c '^00' || true` and expect `10`, `20`, `30` in turn, then commit the batch with the message `docs: decision records NNNN to NNNN` (plus the co-author line). Step 2 and Step 3 below run once, after the third batch, and Step 3's commit will then contain nothing new unless Step 2 found a fix to make; that is fine.

| NNNN | slug | Decision | Rationale (expand) |
| --- | --- | --- | --- |
| 0001 | postgresql-from-day-one | The database is PostgreSQL in every environment; there is no SQLite path. | Multi-city scale, full-text search, and JSONB were needed from the start; the predecessor repo's SQLite forced a rewrite. (2026-04) |
| 0002 | adapter-per-platform | Every city is reached through an adapter implementing `MunicipalSourceAdapter`; adding a city on a supported platform is a `municipalities` row plus council data, not code. | Four vendors already differ in HTML, API, and PDF shape; isolating them keeps ingest generic. |
| 0003 | postgres-fts-not-a-search-engine | Search uses PostgreSQL tsvector and tsquery with GIN indexes, not a separate engine. | One fewer service to run and back up; `websearch_to_tsquery` covers the query shapes readers use. |
| 0004 | rosters-scraped-not-seeded | Council members and term dates are scraped and stored by migration, and member votes resolve to `council_member_id` dynamically from roster plus term dates. | Hand-maintained name maps rotted at the 2025-10-28 Birmingham transition; term-dated rosters handle it. |
| 0005 | ocr-and-minutes-coexist | Video OCR votes and official-minutes votes are stored side by side with their source kind; disagreements are flagged, never merged. | The Data Honesty Protocol: readers must see which source said what. |
| 0006 | votes-link-to-items-n-to-m | Votes link to agenda items through the `vote_agenda_items` join table; one consent vote fans out to many items with `association_type` and `match_confidence` (1.0 named, 0.8 default fill). | Birmingham passes most items in consent blocks; a single foreign key on the vote row could not represent it. (Migration 009, 2026-05-01) |
| 0007 | provisional-links-promote-on-adoption | Consent links insert as provisional and flip to official when council adopts the minutes; the sweep sets `minutes_adopted_at` and calls the matcher, and the matcher calls strict re-parse for adopted meetings still holding provisional links. | Minutes are approved weeks later in batches; the dual trigger keeps links present before promotion without re-downloading PDFs daily. |
| 0008 | manual-links-are-shielded | A `vote_agenda_items` row with `is_manual=TRUE` is never changed by automation, enforced by an app-level check in `_upsert_link` and a `WHERE is_manual = FALSE` on every UPDATE. | A human correction must survive every future matcher run. |
| 0009 | strict-reparse-needs-positive-evidence | Strict re-parse deactivates a consent link only when the item is absent from the enumerated resolution list and the minutes record a separate vote on it; a mere failure to match leaves the link active, and an empty resolved set is safe. | The earlier rule hid thousands of valid consent links behind parser misses; PR #100 restored them. (2026-10-08) |
| 0010 | adoption-dates-parsed-never-guessed | Approval titles are tokenised into date lists and ranges; a title with a missing year or an unknown word is rejected and logged as `adoption_parse_skip`, with no dateutil fallback. | Guessing produced wrong adoption dates that PR #101 had to correct. (2026-10) |
| 0011 | two-phase-meeting-summary | A meeting's executive summary is written provisionally when its items are processed and overwritten once `minutes_adopted_at` is set. | Readers get a summary within a day; the adopted record corrects it later. |
| 0012 | procedural-items-not-summarised | Roll call, pledge, invocation, and minutes-not-ready items get `is_substantive=false`, null scores, and empty text; the title is the content. | A paraphrase of "Roll Call" is noise and cost; the schema treats empty output as the intended shape. (Item prompt v2, 2026-05) |
| 0013 | distinctive-versus-routine-at-six | Before the meeting summary prompt, items with significance 6 or above are rendered in full and the rest are grouped by topic with counts. | Without the split, dozens of demolitions dominated every summary. (Meeting prompt v2) |
| 0014 | version-gates-use-a-floor | Any check on a prompt, schema, or rewrite version compares with `>=`, never `==`. | An `== N` reader gate hid 906 production items when the version bumped. |
| 0015 | ai-queue-newest-first | The AI claim query orders by `meeting_date DESC` so a fresh ingest renders within one cron tick. | Readers care about this week's meeting; the backfill can wait. |
| 0016 | prompt-families-use-100-series-versions | A new prompt-version family starts at a 100-series number so downstream dispatcher thresholds treat it as current. | Introducing a parallel family at low numbers failed the dispatcher's gate. |
| 0017 | wave0-title-fallback | Wave 0 treats `title` as the body when `description` and `raw_text` are empty and the title is at least 120 characters. | Granicus puts the whole item body in the title; without this, 90 percent of Birmingham was misclassified as `no_agenda_text`. (2026-05-06) |
| 0018 | llm-only-badges-are-flagged | A policy badge is `applied` only with deterministic backing; a badge only the model suggested lands `flagged` for admin review. | Conservative display of policy labels; 65 LLM-only badges went to review on 2026-05-12. |
| 0019 | withdrawn-is-its-own-bucket | Items the council withdrew, deferred, or postponed get `processing_status='withdrawn'`, distinct from `procedural_skipped`. | The procedural queue was polluted by 332 withdrawn items. (Migration 023) |
| 0020 | ocr-lives-here-al-muni-is-a-sandbox | The video OCR pipeline is native to `src/docket/analysis/ocr/`; `al-municipal-meetings` stays a research sandbox and is not absorbed. | PR #84 ported the pipeline; the rest of the old repo has no reader. (2026-05-22) |
| 0021 | ocr-uses-the-claim-pattern | OCR work is claimed with an atomic UPDATE RETURNING fed by `FOR UPDATE SKIP LOCKED`, the attempt counter bumped at claim time, with a 3-attempt cap, 24-hour backoff, and 60-day window. | A crash mid-scan must still consume an attempt, and two workers must never scan the same meeting. |
| 0022 | deploy-only-from-main-by-a-human | Deploys run `scripts/deploy.sh` from a clean `main` after a pull request merges; never from a feature branch and never from an automated loop. | `railway up` ships the local tree regardless of branch; the wrapper records the commit SHA in the image. Branch protection is parked pending GitHub Pro (issue #37). |
| 0023 | worker-is-a-separate-railway-service | The cron worker is its own Railway service with a custom start command; the Procfile `worker:` line is informational. | Railway runs only the `web:` Procfile line. |
| 0024 | umami-through-views-only | Analytics are queried only through the `v_*` views with the `umami_reader` role, never raw Umami tables. | The view layer absorbs Umami schema changes. (PR #69, 2026-05-17) |
| 0025 | hsts-without-subdomains-until-www | HSTS is sent with a one-year max-age and without `includeSubDomains` until `www.docket.pub` is served by Railway. | `www` is a Namecheap HTTP redirect today; forcing HTTPS on it would break it. |
| 0026 | bulk-changes-are-one-targeted-statement | Bulk reclassification on production is a single SQL UPDATE scoped by WHERE, never a per-row sweep from the CLI. | A Wave 0 sweep wrote 360 MB of WAL and crash-looped the 500 MB Railway volume on 2026-05-12. |
| 0027 | anthropic-call-sites-mirror-client-py | Every new Anthropic call site uses the tool-use pattern in `src/docket/ai/client.py` and is smoke-tested live before shipping. | Hand-rolled call shapes broke on schema validation in production. |
| 0028 | pipeline-changes-are-compared-on-real-data | A non-trivial change to an extraction, matching, or summary pipeline is run old against new on real rows and the difference read before it ships. | Unit tests pass on changes that degrade real output. |
| 0029 | harness-from-factory-loop | The agent harness artifacts and skills come from bholzer/factory-loop and are not edited locally; new multi-file work uses `plans/PLANS.md`, and `docs/superpowers/` is history. | A local fork of the convention cannot take upstream fixes; one plan format keeps the judge script honest. (2026-10-11) |
| 0030 | transcriber-role-is-write-limited | The desktop transcriber connects as a role that can write only the transcript tables and its heartbeat; uploads are public on arrival. | A machine outside Railway holds credentials; limiting the role bounds the blast radius. (2026-10) |

- [ ] **Step 2: Verify the set**

```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/factory-cycle
ls docs/decisions | grep -c '^00[0-9][0-9]-'
for f in docs/decisions/00*.md; do for h in '## Decision' '## Rationale' '## Date' '## Status'; do grep -q "^$h" "$f" || echo "MISSING $h in $f"; done; done; echo format check done
grep -L '^## Status' docs/decisions/00*.md
grep -c '—' docs/decisions/00*.md | grep -v ':1$'
```

Expected: `30`, `format check done` with no MISSING lines, nothing from `grep -L`, and nothing from the last command (exactly one em dash per file, in the H1).

- [ ] **Step 3: Commit**

```bash
git add docs/decisions
git commit -m "docs: thirty decision records graduated from CLAUDE.md and operator notes

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Write docs/specs/operations.md and the specs index

**Files:**
- Create: `docs/specs/operations.md`
- Modify: `docs/specs/index.md` (fill the table; keep the reflection-rule prose)

**Interfaces:**
- Consumes: the operator content in `CLAUDE.md` sections "Key Commands", "Development Workflow > Rules", "Key decisions to preserve" (the operational bullets only: local CLI against prod, transcriber role, cron worker schedule note, Procfile gotcha, custom domain, HSTS, OCR resource ceiling, WAL warning), and "Local PostgreSQL setup".
- Produces: the one present-tense home for how the system is run, which `AGENTS.md` maps to and which `cycle-run`'s review panel may read.

- [ ] **Step 1: Write docs/specs/operations.md**

Move, do not rewrite, the content from the CLAUDE.md sections named above into this structure. Keep code blocks verbatim. Replace prose em dashes with commas or new sentences. Do not include status history, test counts, or data statistics; those are deleted in Task 9.

```markdown
# Operations

How docket.pub is run today: environments, commands, deploys, and the gotchas an operator hits. Present tense. The cron schedule itself is the code in `src/docket/worker/scheduler.py`; this file does not restate it.

## Local environment

<the venv setup, lockfile workflow, migrations runner, flask run, and "Local PostgreSQL setup" blocks from CLAUDE.md; add one sentence: each git worktree needs its own venv because the editable install pins `docket` to one checkout>

## Tests

<the three tiers as observed in this plan: unit+web+services (about 70 s, no database needed beyond what conftest sets), integration (about 50 s, needs local Postgres with docket_db migrated, no rollback, tests own their cleanup), live (opt-in with -m live, real Anthropic calls). Name the two known failures and point to D1 and D2 in docs/DEBT.md>

## Deploying

<"Deployed commit SHA" block with scripts/deploy.sh, the deploy-only-from-main rule, railway up versus railway redeploy, the Procfile and worker-service note, how to re-deploy the worker>

## Railway specifics

<railway run versus railway ssh; DATABASE_URL internal versus DATABASE_PUBLIC_URL; the postgresql@18 binaries for dumps; the AI CLI against prod command; the worker memory ceiling; the WAL warning with the 2026-05-12 incident; the Postgres-pKpA note pointing at D32>

## Domain and headers

<custom domain state, DNS records, HSTS header and why includeSubDomains is omitted, the www pickup steps>

## Transcriber

<the transcriber role paragraph; link to transcriber/README.md and docs/runbooks/transcripts.md>

## Runbooks

- `docs/runbooks/cron-worker.md`: Healthchecks setup, --run-once verification, alert response, backfill.
- `docs/runbooks/analytics.md` and `docs/analytics-queries.md`: Umami views and queries.
- `docs/runbooks/transcripts.md`: the Legion producer.
- `docs/runbooks/v3-cutover.md` and `docs/runbooks/smart-brevity-ui-flip.md`: the Impact-First cutover procedures.
- `docs/SECURITY_CHECKLIST.md`: pre-launch requirements.
```

- [ ] **Step 2: Fill docs/specs/index.md**

Replace the table and remove the GUIDANCE comment blocks. Keep the "The reflection rule" section verbatim.

```markdown
| Spec | Covers |
| --- | --- |
| `operations.md` | How the system is run: environments, tests, deploys, Railway, domain, transcriber, runbook index |
```

Add one sentence under the table: "Present-tense behaviour specs for ingest, vote matching, the AI pipeline, OCR, coverage, blog, and transcripts do not exist yet; the design documents under `docs/superpowers/specs/` describe them as of the day each shipped. Tracked as `D9` in `docs/DEBT.md`."

- [ ] **Step 3: Verify**

```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/factory-cycle
grep -c '{{FILL' docs/specs/index.md docs/specs/operations.md || true; grep -c GUIDANCE docs/specs/index.md docs/specs/operations.md; grep -c '—' docs/specs/operations.md docs/specs/index.md || true
grep -o '`docs/[^`]*`\|`scripts/[^`]*`\|`src/[^`]*`\|`transcriber/[^`]*`' docs/specs/operations.md | tr -d '`' | sort -u | while read p; do [ -e "$p" ] || echo "MISSING: $p"; done; echo walk done
```

Expected: all counts `0`, `walk done` with no MISSING lines.

- [ ] **Step 4: Commit**

```bash
git add docs/specs
git commit -m "docs: specs/operations.md moved from CLAUDE.md; specs index

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Seed docs/DEBT.md

**Files:**
- Modify: `docs/DEBT.md` (replace the skeleton entirely)
- Read: `docs/superpowers/scratch/2026-10-11-debt-candidates.md` (the verified candidate list; rows marked LIKELY-DONE are not debt)

**Interfaces:**
- Produces: stable IDs `D1` through `D32` that `ARCHITECTURE.md` (D7, D8), `docs/specs/` (D9, D32), and `AGENTS.md` refer to. IDs are never reused.

The rule from the skeleton's guidance: debt is deliberate. Bugs nobody chose stay in GitHub issues. An issue appears here only when it records a deliberate deferral, and the row cites the issue.

- [ ] **Step 1: Confirm docs/DEBT.md is still a skeleton, then replace it with this content**

```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/factory-cycle
grep -c '{{FILL' docs/DEBT.md || true
```

Expected: a number above zero. Then replace the file:

```markdown
# Debt

## Register

| ID | Item | Where | Why deferred | Trigger to pay it down |
| --- | --- | --- | --- | --- |
| D1 | Five web tests fail on `main`: four blog route tests build a URL for `public.city_overview` with a `slug` the route no longer takes (HTTP 500), and `test_meeting_detail_source_links_below_executive_summary` finds no `kpi-grid` section | `tests/web/test_blog_routes.py`, `tests/web/test_city_overview_render.py` | Route and template changed under the tests; not ship blockers | Plan one, first milestone |
| D2 | `test_033_up_refreshes_mv_with_filter` fails: the fixture does not capture and restore the materialised view | `tests/integration/test_033_migration.py` | Globally stateful; not a ship blocker | Plan one, first milestone |
| D3 | Integration tests run against the developer's `docket_db` with hand-written cleanup and no rollback | `tests/integration/conftest.py` | Faster to write; one developer | Plan one builds a disposable `docket_test` rebuilt from migrations per run, dropped `WITH (FORCE)` |
| D4 | Local Postgres 16, Railway 18.3 | local environment | Homebrew default | Plan one may point `docket_test` at the installed postgresql@18 |
| D5 | No single cheap verify command; `AGENTS.md` publishes a pytest line instead | repository root | Nothing aggregated the tiers | Plan one creates `tools/verify`; the `fast-verify` card |
| D6 | A worktree using the main checkout's venv tests the main checkout's code | `venv/` editable install | Only one checkout existed | `cycle-plan` builds a venv per worktree; the `isolated-env` card |
| D7 | Six web modules execute SQL directly | `src/docket/web/auth.py`, `admin.py`, `admin_badge_review.py`, `create_admin.py`, `source_security.py`, `public.py` | Grew with the admin surface | The next plan touching each module moves its SQL into `services/` |
| D8 | `ai/` imports `docket.services.badges` | `src/docket/ai/pipeline.py:70`, `batch_ingest.py:252`, `badges_policy.py:106` | Badge slugs live in services | Next change to badge policy moves the enabled-slug lookup into `ai/` or a shared module |
| D9 | No present-tense behaviour specs for ingest, vote matching, AI pipeline, OCR, coverage, blog, transcripts | `docs/specs/` | Design docs under `docs/superpowers/specs/` served as specs | The first plan touching each area reflects its behaviour into `docs/specs/` |
| D10 | `www.docket.pub` is a Namecheap HTTP redirect; HSTS omits `includeSubDomains` | DNS, `src/docket/web/__init__.py` | Apex first | Public launch preparation |
| D11 | Impact-First Phase 4 not built: migration 014 to drop the legacy `summary` column | `src/docket/migrations/` | Waits for every completed item to reach v3 | `SELECT count(*) FROM agenda_items WHERE processing_status='completed' AND ai_rewrite_version IS NULL` returns 0 |
| D12 | About 7,500 consent items sit in `data_quality_skipped` as `no_agenda_text`; the body is in the minutes PDF | `src/docket/ai/wave0.py`, `votes.raw_text` | Needs its own brainstorm; two recovery paths unevaluated | Before the next backfill wave |
| D13 | About 89 withdrawn-family rows use marker shapes Wave 0 does not match | `src/docket/ai/wave0.py` | Shape B landed in PR #22; the rest were listed, not fixed | Next Wave 0 change |
| D14 | No CSRF protection on admin POST routes | `src/docket/web/admin*.py` | Single trusted admin | Before any second admin user or public launch (issue #83) |
| D15 | Branch protection on `main` not enabled; deploy-from-main is discipline | GitHub settings | GitHub Pro required for private repo protection | GitHub Pro or a second committer (issue #37) |
| D16 | OCR assumes `city="birmingham"` and `scan_interval=2` | `src/docket/analysis/ocr/rosters.py`, `src/docket/services/video_ocr.py` | One OCR city | A second city with video (issue #86) |
| D17 | Admin force-rescan has no audit log | `POST /admin/meetings/<id>/rescan-ocr` | Parity with other admin actions left for later | Next admin audit pass (issue #85) |
| D18 | `video_ocr` cron has no Healthchecks ping | Railway worker env `HEALTHCHECK_VIDEO_OCR_UUID` | Ping no-ops cleanly when unset | Create the check and set the variable (issue #89) |
| D19 | Deprecated `scripts/import_video_ocr.py` still present | `scripts/` | Kept one cycle as a schema-mapping reference | Overdue: delete in the next gardening pass |
| D20 | OCR claim window hard-coded to 60 days | `src/docket/services/video_ocr.py` | Manual laptop OCR covers older meetings | Backfilling older meetings by OCR |
| D21 | Blog follow-ups: `extra_css` lint, sitemap, `city_blog_url()` helper, frontmatter type validation, authoring ergonomics | `src/docket/blog/`, `src/docket/web/` | v1 deliberately minimal | Next blog work (issue #92) |
| D22 | Search has no facets or sort | `src/docket/services/query.py` `search_agenda_items` | Separate feature | When search is revisited |
| D23 | Editorial coverage v1.1 to v1.3 surfaces (meeting, member, badge) and v2 proposers not built | templates, coverage schema | Paired chip-plus-block ships | When v1.1 starts |
| D24 | Granicus retraction (403) not detected; ghost rows deleted by hand | `src/docket/adapters/granicus.py` | Rare | Next ghost card |
| D25 | Five badge INSERT paths bypass `decide_status_and_confidence` | `src/docket/ai/badges_process.py`, `src/docket/web/admin.py`, `src/docket/worker/tasks.py` | Correct today via the DB default | Any change to the badge status contract |
| D26 | Manual vote-link correction UI not built; `is_manual` column ready | `src/docket/web/admin.py` | No miss has needed hand-fixing yet | First matcher miss that needs a human |
| D27 | No index on `agenda_items.dollars_amount` | migrations | Not yet slow | EXPLAIN shows a sequential scan at current scale |
| D28 | Source reconciliation (OCR versus minutes on the same meeting) not built | `src/docket/services/` | Few meetings have both | A meeting where both sources disagree reaches a reader |
| D29 | CivicPlus adapter is a stub; Hoover and Montgomery have no data | `src/docket/adapters/civicplus.py` | Hoover's AgendaCenter is empty | Hoover or Montgomery publishes readable data |
| D30 | Test fixture `seed_item` leaves orphan meetings in the local DB | `tests/unit/test_ai_worker_writeback.py` | Cosmetic | Next touch of that test file |
| D31 | A dozen stale `worktree-*` branches on `origin` | GitHub | Left after merges | Overdue: delete in the next gardening pass |
| D32 | A second Postgres service `Postgres-pKpA` exists in the Railway project with no known use | Railway | Unknown origin | Next Railway bill review |

## Details

### D3 — Integration tests share the developer database

Tests under `tests/integration/` connect to `DATABASE_URL`, insert rows, and delete them in `try/finally`. A test that fails before cleanup leaves rows; the migration tests apply and roll back real migrations against the same database. For the factory's `cycle-run`, a milestone that corrupts state fails the next milestone's tests for a reason the next agent cannot see. Fixed means: a `docket_test` database created by `tools/verify` from `python -m docket.migrations.runner` on each run, dropped first with `DROP DATABASE docket_test WITH (FORCE)`, and `DATABASE_URL` pointed at it for the integration tier only.

### D7 — SQL in the web layer

The rule in `ARCHITECTURE.md` says routes call services. The six modules named in the row call `db_cursor()` directly, mostly in admin forms and auth. Fixed means each query becomes a function in `src/docket/services/` with a unit test, and `grep -rl 'db_cursor\|db()' src/docket/web` prints nothing. Pay it down module by module inside plans that already touch each module; do not open a plan for it alone.

### D12 — Consent item text recovery

Birmingham's Granicus agenda lists consent items as title-only references. The body text appears in the post-meeting minutes PDF, which `analysis/minutes_parser.py` already parses for votes and stores in `votes.raw_text`. Two paths were named and neither evaluated: recover the body from the minutes text and re-run Wave 0, or have the adapter follow the item link to the full text at ingest. The brainstorm decides.

### D13 — Withdrawn marker shapes

Shapes not matched: `ITEM N. (WITHDRAWN)`, `(ph) ITEM N. REQUESTED TO BE WITHDRAWN`, `CONSENT(ph) WITHDRAWN ITEM N.`, `CONSENT(ph) ITEM N.- WITHDRAWN`. The matched shapes are in `WITHDRAWN_TITLE_PATTERNS` in `src/docket/ai/wave0.py`. Reclassify with one targeted UPDATE per decision 0026.
```

- [ ] **Step 2: Verify**

```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/factory-cycle
grep -c '{{FILL' docs/DEBT.md || true; grep -c GUIDANCE docs/DEBT.md || true
grep -c '^| D[0-9]' docs/DEBT.md
grep -c '—' docs/DEBT.md || true
```

Expected: `0`, `0`, `32`, and `4` (one em dash per Details heading, which mirrors the skeleton's `### D1 — title` form; that form is the upstream format and is allowed there only).

- [ ] **Step 3: Commit**

```bash
git add docs/DEBT.md
git commit -m "docs: seed DEBT.md with 32 rows from tests, architecture greps, issues, and operator notes

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Set the maturity rung and the capability register

**Files:**
- Modify: `docs/MATURITY.md` (fill Current rung; delete GUIDANCE blocks; keep rungs, promotion, demotion, and gating table as shipped)
- Modify: `docs/capabilities/index.md` (delete GUIDANCE blocks; keep all six rows)

**Interfaces:**
- Produces: the register the judge-milestone card (plan one) will add a row to.

- [ ] **Step 1: Fill the Current rung section of docs/MATURITY.md**

Replace the `{{FILL ...}}` under `## Current rung` with:

```markdown
L0, human-gated. Nothing is mechanically enforced: the verify command in `AGENTS.md` is a pytest line an agent runs by hand, and every card in `docs/capabilities/index.md` is a specification. The single thing that moves this project toward L1 is `tools/verify` becoming the one command every session runs, with `fast-verify` promoted to `enforced` and green for twenty landed changes.
```

Delete every `<!-- GUIDANCE ... -->` block. Change nothing else.

- [ ] **Step 2: Clean docs/capabilities/index.md**

Delete the GUIDANCE comment blocks. Keep all six rows as `specced` with `—` in the Enforced-at column (that dash is the upstream table convention and is allowed). All six cards apply here: `fast-verify` (D5), `evidence-check` (plans will exist), `doc-integrity` (the reference walk), `boundary-lint` (the layer map), `isolated-env` (D3, D6), `prose-duplication` (one owner per fact).

- [ ] **Step 3: Verify**

```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/factory-cycle
grep -c '{{FILL' docs/MATURITY.md docs/capabilities/index.md || true; grep -c GUIDANCE docs/MATURITY.md docs/capabilities/index.md || true
for c in $(grep -o '^| `[a-z-]*`' docs/capabilities/index.md | tr -d '|` '); do [ -f docs/capabilities/$c.md ] || echo "MISSING card $c"; done; echo register check done
for c in $(grep -o '^| L[0-9] | `[a-z-]*`' docs/MATURITY.md | awk -F'`' '{print $2}'); do grep -q "^| \`$c\`" docs/capabilities/index.md || echo "GATING ROW WITHOUT CARD $c"; done; echo gating check done
```

Expected: all counts `0`; both `done` lines with nothing before them.

- [ ] **Step 4: Commit**

```bash
git add docs/MATURITY.md docs/capabilities/index.md
git commit -m "docs: maturity at L0, capability register of six specced cards

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Write AGENTS.md, reduce CLAUDE.md to an import, point README at the map

**Files:**
- Modify: `AGENTS.md` (replace the skeleton entirely)
- Modify: `CLAUDE.md` (replace entirely with one line)
- Modify: `README.md` (add one line under the title block)

**Interfaces:**
- Consumes: every artifact from Tasks 2 through 8.
- Produces: the entry point every agent session and every factory subagent reads first.

- [ ] **Step 1: Confirm the import syntax with the claude-code-guide agent**

Ask the `claude-code-guide` agent: "Does a CLAUDE.md consisting only of the line `@AGENTS.md` import that file's contents into every session, and does Claude Code discover skills through a symlinked `.claude/skills` directory?" Record both answers here as `Observed:` lines. If the import syntax differs, use the documented form in Step 3. If that agent is unavailable in the executing environment, read the Claude Code documentation page on memory and CLAUDE.md imports (https://docs.anthropic.com/en/docs/claude-code/memory) directly and record what it says; if neither is reachable, write `@AGENTS.md` anyway, since it is the form factory-loop's own CLAUDE.md uses, and record `not confirmed` in the bootstrap report.

- [ ] **Step 2: Write AGENTS.md**

```markdown
# docket.pub — agent guide

docket.pub ingests, parses, and indexes Alabama municipal meeting records and publishes them at https://docket.pub with every fact linked to the city's own source document. Python 3.10, Flask and HTMX, PostgreSQL, deployed on Railway; a cron worker does the daily work. The one thing to understand before editing: the service layer owns every transaction, and nothing shown to a reader may lose its link to the source. Read `docs/PRINCIPLES.md` before touching anything that produces or renders data.

## Map

- `GOALS.md`: purpose, outcomes, scope, non-goals, constraints, known unknowns. Read first.
- `ARCHITECTURE.md`: components, layer map, dependency rules, known rough edges.
- `docs/PRINCIPLES.md`: six rules that override convenience.
- `docs/MATURITY.md`: the autonomy ladder; this project is at L0.
- `docs/DEBT.md`: deliberate deferrals with triggers, `D1` onward.
- `docs/decisions/`: one file per durable decision, `0001` onward.
- `docs/specs/`: present-tense behaviour. `operations.md` is how the system is run.
- `docs/capabilities/`: spec cards for mechanical checks, with status in `index.md`.
- `plans/PLANS.md`: the plan convention. `plans/active/` in flight, `plans/completed/` done.
- `skills/`: the six procedures (`plan-author`, `plan-execute`, `doc-garden`, `retro`, `capability-build`, `harness-init`). Also reachable as `.claude/skills/`.
- `docs/superpowers/`: design specs, plans, and reviews written before this harness. History, not current behaviour.
- `docs/runbooks/`: operator procedures, indexed from `docs/specs/operations.md`.
- GitHub issues on `thinkdarrell/docket-pub`: bugs nobody chose. Deliberate deferrals go in `docs/DEBT.md`.

## Commands

Run from the repository root (or the worktree root) with that checkout's own `venv/`.

- Verify (cheap): `venv/bin/python -m pytest tests/unit tests/web tests/services -q` (about 70 s; five known failures, `D1`). There is no aggregated verify command yet; `D5` and the `fast-verify` card track it.
- Full tests: `venv/bin/python -m pytest -q` (adds integration; needs local Postgres with `docket_db` migrated; one known failure, `D2`). Live tests: add `-m live`.
- Migrations: `venv/bin/python -m docket.migrations.runner` (`--status`, `--down 1`).
- Dev server: `venv/bin/flask run`.
- Deploy: humans only, from a clean `main`, `scripts/deploy.sh --service docket-web` or `--service worker`.

## Working rules

- Multi-file or multi-session work requires an ExecPlan per `plans/PLANS.md`.
- Execute one milestone per session. Update every living section `plans/PLANS.md` requires, with observed evidence. Stop.
- Never report a planned command as passing evidence. Run it, record what you observed.
- Decisions with lasting effect go in the plan's Decision Log; durable ones graduate to `docs/decisions/`.
- Nothing material lives outside the repo. If it was decided, it is written here.
- This file is a map, not an encyclopedia. Keep it under about 100 lines; content that wants to grow moves into `docs/` and leaves a one-line map entry.
- Before changing anything under `src/docket/adapters/`, `src/docket/analysis/`, `src/docket/services/ingest.py`, or a template that renders data, read `docs/PRINCIPLES.md`.
- Routes, worker tasks, and CLIs call `docket.services.*`; services own transactions. Known violations are `D7`.
- Never run a per-row sweep or an unbounded batch against production; see decision `0026`.
- Scrape city sites with at least one second between requests.
- Commit as `hello@docket.pub`; the GitHub account is `thinkdarrell`.
- Each worktree needs its own `venv/` (`python3.10 -m venv venv && venv/bin/pip install -e ".[dev]"`); the main checkout's venv tests the main checkout.
```

- [ ] **Step 3: Reduce CLAUDE.md**

Replace the whole file with exactly:

```
@AGENTS.md
```

Everything it held is now owned elsewhere: layout and architecture in `ARCHITECTURE.md`; commands and operations in `docs/specs/operations.md` and `AGENTS.md`; decisions in `docs/decisions/`; rules in `docs/PRINCIPLES.md` and `AGENTS.md`; the ported-components table, build phases, and data statistics are deleted as status history with no reader (git keeps them).

- [ ] **Step 4: Add one line to README.md**

Under the title block (after line 7), add:

```
**For agents and contributors:** start at [`AGENTS.md`](AGENTS.md).
```

- [ ] **Step 5: Run the published commands before committing them**

```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/factory-cycle
venv/bin/python -m docket.migrations.runner --status 2>&1 | tail -2
venv/bin/flask --help 2>&1 | head -1
scripts/deploy.sh --help 2>&1 | head -2 || sed -n 1,15p scripts/deploy.sh
wc -l AGENTS.md
grep -c '{{FILL' AGENTS.md || true; grep -c GUIDANCE AGENTS.md; grep -c '—' AGENTS.md || true
```

Expected: the status command prints the migration table tail (or a connection error if local Postgres is down, which is still a run and is recorded as observed); flask prints its usage line; deploy.sh prints usage or its header (do not run it without `--help`); `wc -l` under 100; counts `0`, `0`, `1` (the H1 em dash, which mirrors the upstream skeleton's title form).

- [ ] **Step 6: Commit**

```bash
git add AGENTS.md CLAUDE.md README.md
git commit -m "docs: AGENTS.md map; CLAUDE.md becomes @AGENTS.md; README points at the map

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: Verify by running, record the bootstrap report

**Files:**
- Modify: this plan file (append the Bootstrap report section)

**Interfaces:**
- Consumes: everything above.
- Produces: the report harness-init step 11 requires, written into this plan so the pull request can quote it.

- [ ] **Step 1: Finish searches across every filled artifact**

```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/factory-cycle
grep -rn '{{FILL' AGENTS.md GOALS.md ARCHITECTURE.md docs/PRINCIPLES.md docs/MATURITY.md docs/DEBT.md docs/specs docs/capabilities docs/decisions plans/PLANS.md; echo "fill search done"
grep -rn 'GUIDANCE' AGENTS.md GOALS.md ARCHITECTURE.md docs/PRINCIPLES.md docs/MATURITY.md docs/DEBT.md docs/specs docs/capabilities docs/decisions; echo "guidance search done"
```

Expected: only the two `done` lines. Any hit is read, then fixed in the owning file with its own commit.

- [ ] **Step 2: Reference walk**

```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/factory-cycle
for f in AGENTS.md GOALS.md ARCHITECTURE.md docs/PRINCIPLES.md docs/MATURITY.md docs/DEBT.md docs/specs/*.md docs/capabilities/index.md; do
  grep -o '`[^`]*`' "$f" | tr -d '`' | grep -E '^(src|scripts|docs|plans|skills|tests|tools|transcriber|content|\.claude)(/|$)|^(AGENTS|GOALS|ARCHITECTURE|CLAUDE|README)\.md$' | sort -u | while read p; do [ -e "$p" ] || echo "$f: unresolved $p"; done
done; echo "reference walk done"
```

Expected: `reference walk done` with no unresolved lines except those this plan reserved on purpose: `tools/verify` (plan one, named in `docs/DEBT.md` D5 and `docs/MATURITY.md`). Record each reserved path here as `Observed:` and confirm it already has its debt row. Any other unresolved path is a defect: fix the path in the owning file, one commit per fix.

- [ ] **Step 3: Card and register agreement, gating rows**

Re-run Task 8 Step 3's two loops. Expected: both `done` lines with nothing before them.

- [ ] **Step 4: Published commands run here**

Re-run Task 9 Step 5 and Task 0 Step 5. Record the observed summary lines.

- [ ] **Step 5: Upstream byte identity still holds**

```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/factory-cycle
FL=/Users/darrellnance/projects/factory-loop
diff $FL/template/plans/PLANS.md plans/PLANS.md && echo "PLANS.md identical"
diff $FL/template/docs/capabilities/CARD_FORMAT.md docs/capabilities/CARD_FORMAT.md && echo "CARD_FORMAT identical"
diff $FL/template/docs/decisions/DECISION_FORMAT.md docs/decisions/DECISION_FORMAT.md && echo "DECISION_FORMAT identical"
for c in fast-verify evidence-check doc-integrity boundary-lint isolated-env prose-duplication; do diff -q $FL/template/docs/capabilities/$c.md docs/capabilities/$c.md; done; echo "cards checked"
diff -r $FL/skills skills && echo "skills identical"
```

Expected: every `identical` line prints and `diff -q` prints nothing.

- [ ] **Step 6: Append the bootstrap report to this plan**

Add a section `## Bootstrap report` at the end of this file with these paragraphs, each filled from what the steps above printed:

- Created: the list of files, by directory, with `wc -l AGENTS.md`.
- From interview rather than tree: GOALS.md Purpose, Outcomes, Non-goals, Constraints, Known unknowns; PRINCIPLES.md; decisions 0027 to 0029. Everything else came from CLAUDE.md, the specs, or greps.
- Omitted: nothing from the payload; all six cards kept, with the one-line reason each applies.
- Debt register: 32 rows; name the three overdue ones (D19, D31, and D5 if plan one has not started).
- Reserved paths from the reference walk, each with its debt row.
- Entry points: CLAUDE.md is `@AGENTS.md` (with the claude-code-guide answer); `.claude/skills` is a committed relative symlink to `skills/`.
- Verify command observed: the pytest summary line and time.
- Next: plan one, authored by hand following `skills/plan-author/SKILL.md`, covering `tools/verify`, `tools/judge-milestone` with fixtures, D1, D2, D3, and the `judge-milestone` card. Not started here.

- [ ] **Step 7: Commit the report**

```bash
git add docs/superpowers/plans/2026-10-11-factory-bootstrap.md
git commit -m "docs: bootstrap report appended to the plan

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: Push and open the pull request

**Files:** none changed.

- [ ] **Step 1: Push**

```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/factory-cycle
git log --oneline origin/main..HEAD | wc -l
GIT_TERMINAL_PROMPT=0 git push -u origin docs/factory-cycle-spec
```

Expected: about 14 commits; push succeeds without a prompt.

- [ ] **Step 2: Open the PR**

```bash
cd /Users/darrellnance/docket-pub/.claude/worktrees/factory-cycle
gh auth status 2>&1 | grep -m1 'Logged in'
gh pr create --base main --head docs/factory-cycle-spec --title "docs: adopt the factory-loop harness and the factory cycle spec" --body-file <(sed -n '/^## Bootstrap report/,$p' docs/superpowers/plans/2026-10-11-factory-bootstrap.md; printf '\n\nSpec: docs/superpowers/specs/2026-10-10-factory-cycle-design.md\nPlan: docs/superpowers/plans/2026-10-11-factory-bootstrap.md\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)\n')
```

Expected: the first line shows the `thinkdarrell` account; the second prints the PR URL. Record the URL here. If the first line shows a different account or no login, stop before `gh pr create`, report that the branch is pushed and the PR is not opened, and ask the operator to run `gh auth switch -u thinkdarrell` (or `gh auth login`) and then re-run Step 2 themselves or in a new session.

- [ ] **Step 3: Report to the operator**

State the PR URL, the AGENTS.md line count, the verify summary observed, the reserved paths, and that plan one is the next step and has not been started.
