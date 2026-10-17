# Move the factory's rules into the most deterministic place that can hold them: an active-plan check, a refusing test suite, deny rules, a refusing deploy wrapper, continuous integration, and a protected `main`

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `plans/PLANS.md`.

## Purpose / Big Picture

Today every rule that governs a change to this repository lives in one of two places: prose an agent reads before it acts (`AGENTS.md`, `plans/PLANS.md`, the six skills, the prompts inside the two saved workflows) or a check an agent chooses to run afterwards (`./tools/verify`, `tools/judge-milestone`). Nothing refuses a bad commit at the moment it is made, nothing stops a red branch from merging, and `docs/MATURITY.md` says so in one sentence: nothing is `enforced` yet. A review of the factory on 2026-10-17 sorted its rules into four cells (deterministic or judgment, before the agent acts or after) and found the deterministic-before cell empty and the deterministic-after cell unwired.

After this plan, an outside reader sees four things they cannot see now. A pull request against `main` carries a status check named `verify` that GitHub requires to be green before the merge button works, administrators included; the repository is public, so GitHub provides this for free, and the GitHub Pro blocker recorded in `docs/DEBT.md` `D15` no longer applies. A commit that stages an active plan missing one of its four living sections, or ticking a Progress entry without a date, is refused by a pre-commit hook with the remediation text in front of the agent, and the same check runs as verify's sixth check over every plan in `plans/active/`. A `pytest` run pointed at any database not named `docket_test_*` stops before it collects a test, so the row-deleting unit fixture that `D37` describes can no longer reach a developer's `docket_db`. And `scripts/deploy.sh` exits nonzero on a branch other than `main` or a dirty tree instead of printing a warning and sleeping three seconds, while a committed `.claude/settings.json` denies the agent the commands that bypass hooks or deploy. Two capability cards move to `enforced`, and `docs/MATURITY.md` says what is enforced and since when.

## Progress

- [x] (2026-10-17 23:58Z) M1: `tools/check-plans` decides evidence-check for every active plan, runs as verify's sixth check and as the pre-commit hook in `tools/hooks/`, and the card is `built`.
- [ ] M2: the test suite refuses a database not named `docket_test_*` outside the live tier, the project `.claude/settings.json` denies the hook-bypass and deploy commands, and `scripts/deploy.sh` refuses a non-main branch or a dirty tree.
- [ ] M3: `.github/workflows/verify.yml` runs `./tools/verify` on every push and on pull requests to main, and one run on this branch has completed green.
- [ ] M4: `main` requires the `verify` check to merge, `fast-verify` and `evidence-check` are `enforced`, decision 0052 is written, D15 is paid, and MATURITY.md says what is enforced.

## Surprises & Discoveries

- Observation (authoring, 2026-10-17): nothing has been executed yet. The authoring research found one surprise worth recording before any milestone runs: `gh run list --workflow verify.yml` fails with `HTTP 404: workflow verify.yml not found on the default branch` until the workflow file is on `main`, so M3 lists runs by branch, never by workflow name.
  Evidence: the command printed exactly that line in the main checkout on 2026-10-17 with no `.github/` directory in the repository.
- Observation (M1, 2026-10-17): the authoring estimate of verify's wall time (85 s) was low for this worktree; the starting run took 96 s (fast tiers 45 s, integration 49 s), still inside the 180 s budget `AGENTS.md` states.
  Evidence: `verify: all 5 checks passed in 96s.` in Artifacts and Notes.
- Observation (M1, 2026-10-17): the judge's `snapshot` mode prints the plan's parsed records to stdout on every exit, so `tools/check-plans` must discard stdout and read only stderr, or the hook would print one record line per Progress entry on every commit.
  Evidence: `tools/judge-milestone` lines 187 to 188 (`read_plan <"$plan" >"$TMP/records"; cat "$TMP/records"`); with stdout discarded the hook's passing path printed only the `plans:` lines recorded in Artifacts and Notes.
- Observation (M1, 2026-10-17): the restore step the plan wrote for clause (e), `git checkout -- <plan>`, does not undo the probe, because the probe stages the broken plan before the refused commit and `git checkout -- <path>` copies the index to the working tree; the file stayed broken and staged, and the verify run that followed failed its sixth check. `git checkout HEAD -- <plan>` is the restore that works. Validation and Acceptance clause (e) and Idempotence and Recovery are corrected below to say so.
  Evidence: after the plan's command, `git status --porcelain` printed `M  plans/active/factory-enforcement.md` and `./tools/verify` printed `verify: plans ... FAILED (0s)` and `verify: 1 of 6 checks failed in 97s.`; after `git checkout HEAD -- plans/active/factory-enforcement.md` it printed nothing and verify printed `verify: all 6 checks passed in 96s.` (both transcripts in Artifacts and Notes).

## Decision Log

- Decision: the plan is cut into four milestones along the cells of the review's matrix, not along files. M1 is the one new mechanical check and its two enforcement points; M2 is the three deterministic-before guards that need no GitHub; M3 is the CI job observed green once; M4 is the GitHub setting and the status changes it justifies.
  Rationale: each milestone leaves the repository coherent and verifiable alone (M1 and M2 are proven by `./tools/verify` and local refusals; M3 by a run on GitHub; M4 by the protection API), and M4 depends on M3's job name, so M3 cannot be folded into M4 without a session that both writes YAML and waits on GitHub. The alternative, one milestone per file, would leave `docs/capabilities/index.md` edited four times.
  Date/Author: 2026-10-17, plan author (Claude, by hand in the operator's session).
- Decision: the pre-commit hook enforces evidence-check (sections present, ticked entries dated) on staged active plans, and does not enforce decision 0037 (every milestone commit changes the plan).
  Rationale: 0037 binds only a milestone session's commits; the closing sequence legitimately commits routed lessons, doc-garden fixes, and the review record without touching the plan, and a hook cannot tell a milestone session from a closing stage. The judge already decides 0037 at the right scope. Evidence-check is well scoped to any commit that stages a file under `plans/active/`, which is exactly the enforcement point its card names.
  Date/Author: 2026-10-17, plan author.
- Decision: `core.hooksPath` is set once per clone by the operator (`git config core.hooksPath tools/hooks` in the main checkout) and documented in `docs/specs/operations.md` Local environment; this plan does not edit `cycle-plan.js` to set it.
  Rationale: repository configuration is shared by every linked worktree, so one setting covers every factory worktree on the machine (verified on 2026-10-17 in a throwaway repository: a relative `core.hooksPath` set in the main repository fired inside a linked worktree with the worktree root as its working directory). Editing a saved workflow trips `D45`, which asks the next workflow edit to commit a stub runtime and its scenarios, and that is a plan of its own.
  Date/Author: 2026-10-17, plan author.
- Decision: the deny list in `.claude/settings.json` covers `--no-verify`, `-c core.hooksPath=`, `railway up`, `railway redeploy`, and `scripts/deploy.sh`, and nothing else.
  Rationale: each of those is a rule the repository already states in prose (`AGENTS.md` Working rules; `GOALS.md` Constraints; `docs/specs/operations.md` Deploying) and the review found written where an agent must read it rather than where the tool refuses it. Force pushes, destructive SQL, and an allowlist of read-only commands were considered and left out: none is a stated rule of this repository, and the Claude Code documentation says a Bash deny rule matches the invocation Claude usually writes and is not a security boundary, so each rule should guard a stated norm, not attempt containment.
  Date/Author: 2026-10-17, plan author.
- Decision: the continuous-integration job runs on every push to any branch and on pull requests to `main`, and is named `verify`.
  Rationale: a milestone can observe a run only if pushing the branch triggers one, and `gh run list --workflow` cannot find a workflow that is not yet on `main`. A pull-request branch will run twice per push, once for each event, which costs Actions minutes the public repository gets free. The job name is the status-check context M4 requires; keeping it identical to the command's name keeps the fast-verify card's identity property (the documented command is the one CI runs) legible.
  Date/Author: 2026-10-17, plan author.
- Decision: branch protection on `main` requires the `verify` check with `strict` false, applies to administrators, requires no reviewer, and forbids force pushes and deletion.
  Rationale: one person commits here, so a required reviewer would block every merge; `strict` would demand a rebase of every plan branch after any merge to `main`, which the factory does not do; administrators included is the point, since the operator is the administrator and the rule exists to stop the operator's own habit. The alternative, a ruleset, offers nothing extra for one branch and one committer.
  Date/Author: 2026-10-17, plan author.
- Decision: `fast-verify` and `evidence-check` are promoted to `enforced` in M4, after the required check exists; `judge-milestone` stays `built`.
  Rationale: `docs/capabilities/CARD_FORMAT.md` defines `enforced` as running where it cannot be skipped, which the required status check is and the pre-commit hook alone is not (a clone without `core.hooksPath` set skips it). The judge's fixture self-test becomes enforced through verify, but the judge itself runs only inside `cycle-run`, which a session can decline to use, so its card's status is unchanged. `docs/MATURITY.md` L0 says a human approves every capability status change; the operator's review of this plan's pull request is that approval, and the plan does not claim L1.
  Date/Author: 2026-10-17, plan author.
- Decision: decision 0052 is written by M4 directly rather than graduated by the retro, and decision 0022 is left as it stands.
  Rationale: `docs/specs/operations.md` Deploying has to cite the record that explains the protection the moment the protection exists, and a spec does not cite a plan. 0022's statement (deploys run from a clean `main` by a human) still binds; only its rationale's sentence about GitHub Pro is dated, and `docs/decisions/DECISION_FORMAT.md` says a record's rationale is never rewritten. Number 0052 is the next free number on 2026-10-17 (0051 exists); if another plan has taken it by M4, M4 uses the next free number and records the substitution here.
  Date/Author: 2026-10-17, plan author.
- Decision (revision of 2026-10-17, after the operator's review of the authored plan): six review points are adopted and written into Plan of Work, Concrete Steps, and Validation and Acceptance: `core.hooksPath` is set before M1's first commit; `tools/check-plans` guards the empty-directory glob and uses `|` as its `sed` delimiter; the guard in `tests/conftest.py` reads the environment first and imports `docket.config` only when the variable is unset; `scripts/deploy.sh` tests the dirty tree before the branch, and acceptance clause (e2) exercises that path with a `COMMIT_SHA` probe; the `-m live` exemption's exactness is stated in the spec; and the two check runs a pull request will show are stated in M4. Two review points were checked and found not to apply, with the evidence added to Context: nothing asserts verify's check count, and the editable install reads the pinned lock. One point is declined: deny rules for `bash scripts/deploy.sh` and `sh scripts/deploy.sh`.
  Rationale: each adopted point either removed an ordering trap (the hook demonstration against an uncommitted plan) or a known POSIX or `sed` pitfall, or made an untested code path observable; the two non-applying points are recorded so the next reader does not re-check them. The declined rules would add to a list whose Decision above limits each rule to a stated norm; the Claude Code documentation says these rules are not a containment boundary, and `scripts/deploy.sh` itself refuses every branch but `main`, which is where a human, not an agent, deploys.
  Date/Author: 2026-10-17, plan author, from the operator's pasted review.
- Decision: the database-name guard lives in `tests/conftest.py`, keys on the pytest marker expression, and has no environment-variable escape hatch.
  Rationale: the root conftest is the one file every tier under `tests/` loads, so the guard runs before any fixture of any tier. The live tier legitimately reads a real database, and `pyproject.toml` already makes `-m live` the one way to select it, so the exact expression `live` is the exemption; an environment variable would re-introduce the judgment the guard exists to remove. The producer suite under `transcriber/tests` deletes only rows it inserted, by id, so it is left alone.
  Date/Author: 2026-10-17, plan author.
- Decision (M1): `tools/check-plans` treats any judge exit other than 0 as a failure of that file, and prints the judge's own defect line for exit 2 whatever the defect (the three structural defects the judge names, and a file that does not exist); the `no date` branch selects the dated-tick guidance and every other exit-2 line gets the `plans/PLANS.md requires` guidance, so the judge's `carries the required section ... with nothing under it` (an empty section) and `does not exist` fall under the section guidance.
  Rationale: the Plan of Work names only the two guidance lines and says "otherwise" for the second, so inventing a third line for the empty-section or missing-file cases would be scope the plan did not state; the judge's defect line already says exactly what is wrong, and the guidance line's last clause ("an empty section is also a failure") covers the empty case.
  Date/Author: 2026-10-17, M1 session.
- Decision (M1): `core.hooksPath` was set by running `git config core.hooksPath tools/hooks` from inside the worktree, not from the main checkout.
  Rationale: a linked worktree's `git config` (without `--worktree`) writes the shared repository configuration, and `git config --show-origin` confirmed the value landed in `/home/thinkdarrell/docket-pub/.git/config`, which is exactly what the Decision above says the operator's command in the main checkout would do; the session may not touch any other directory, and the effect is identical.
  Date/Author: 2026-10-17, M1 session.
- Decision (M1): the `docs/specs/operations.md` Tests paragraph's closing-line quote was not changed, because it already reads `verify: all M checks passed in Ss.` with `M` as a placeholder rather than `all 5 checks`; the fifth-check clause gained the sixth and the judge paragraph gained a description of `tools/check-plans` and the hook instead.
  Rationale: the Plan of Work said to change the count "where that paragraph quotes verify's closing line"; it quotes it with a placeholder, so there was no count to change, and recording that here saves the next reader a search.
  Date/Author: 2026-10-17, M1 session.

## Outcomes & Retrospective

M1 (2026-10-17): complete, acceptance (a) through (f) met as observed in Artifacts and Notes; the one carve-out is procedural, not against acceptance: the restore command clause (e) prescribed did not restore (it left the broken plan staged), so the session restored from `HEAD` instead and corrected the clause, and one `./tools/verify` run in between failed its sixth check on the still-broken plan, which is recorded as the check doing its job rather than as a regression. Remaining: M2 through M4. The authoring session cut the branch `plan/factory-enforcement` and the worktree `.claude/worktrees/factory-enforcement` from `origin/main` at 79084a2, built its venv in 21 seconds, and wrote the worktree's gitignored `.env` with `DATABASE_URL=postgresql://thinkdarrell@/docket_db` because `D57` applies on this machine. This section is written at completion.

## Context and Orientation

The repository is docket.pub, a Python 3.10 Flask application with a PostgreSQL database; `AGENTS.md` is the map. The "factory" is the pair of saved Claude Code workflows under `.claude/workflows/` (`cycle-plan.js`, `cycle-run.js`) that plan and execute work in fresh agent sessions, plus the tools they call: `./tools/verify` (the one check command), `tools/test-db` (the disposable database it builds), `tools/judge-milestone` (decides from git and the plan file whether a session advanced exactly one milestone), and `tools/check-workflows`. This plan changes none of the workflow scripts.

A capability card under `docs/capabilities/` is a specification of one mechanical check; `docs/capabilities/index.md` records each card's status as `specced` (nothing runs), `built` (runs on demand, and has been seen to fail on a real violation), or `enforced` (runs where it cannot be skipped). `fast-verify` is `./tools/verify`; `evidence-check` is the check that every plan under `plans/active/` carries the four living sections (Progress, Surprises & Discoveries, Decision Log, Outcomes & Retrospective) non-empty and that every ticked Progress entry carries a date; both facts are already decided for one plan by `tools/judge-milestone snapshot <plan>`, which exits 0 when the record holds and 2 with one `judge: defect <plan> ...` line on stderr when it does not. The card asks for the aggregation over every active plan, which is what M1 builds.

The verify command as it stands runs five checks and prints one summary line per check, then `verify: all 5 checks passed in Ss.` or `verify: N of 5 checks failed in Ss.`; it adds a check with one `check <name> <command>` line. On the authoring machine (Linux under WSL) it passed on 2026-10-17 in 85 seconds with `DATABASE_URL=postgresql://thinkdarrell@/docket_db` exported: fast tiers `1875 passed, 5 skipped, 4 xfailed` in 40 s, integration `624 passed` in 43 s, judge fixtures `12 of 12 passed`, workflows ok, transcriber `70 passed`. Without that variable it fails at the database build with `permission denied to create database`, because the local `docket` role lacks CREATEDB (`D57`); every worktree on this machine therefore needs a gitignored `.env` naming that URL, and this plan's worktree has one. The `DATABASE_URL` that verify exports to every tier names a database `docket_test_<hash>`.

Git hooks are not versioned, but `core.hooksPath` may point at a directory inside the worktree. On 2026-10-17 a throwaway repository with `git config core.hooksPath tools/hooks` set in the main repository ran `tools/hooks/pre-commit` from a linked worktree, with the worktree root as the working directory, and the commit exited 1 when the hook did; `git commit --no-verify` and `git -c core.hooksPath=/dev/null commit` both bypassed it, which is why M2's deny rules name those two forms. The repository has no hooks today (`git config core.hooksPath` prints nothing; `.git/hooks` holds only samples), so the `AGENTS.md` rule "git hooks are never disabled or bypassed" currently guards nothing.

Claude Code reads a committed, shared `.claude/settings.json` from the project (`.gitignore` already says it stays trackable; only `settings.local.json` is ignored). Its permission rules are evaluated deny first, then ask, then allow, and a deny rule applies when any subcommand of a compound command matches it, including inside `$(...)`. A Bash rule is the command text with `*` standing for any text, spaces included; a trailing ` *` also matches the bare command only when it is the rule's only wildcard; the rule matches past a leading environment-variable assignment and the wrappers `timeout`, `time`, `nice`, `nohup`, `stdbuf`; it does not match the same program invoked as `/usr/bin/git` or through `sh -c`, so the documentation calls it a guard on the invocation Claude usually writes, not a security boundary. These facts are quoted from `https://code.claude.com/docs/en/permissions` as read on 2026-10-17.

The unit-tier fixture `fresh_db` in `tests/unit/test_ai_worker_claim.py` lines 13 to 28 runs `DELETE FROM` on seven tables against whatever `DATABASE_URL` names (`D37`); `tests/conftest.py` is the root conftest every tier loads and today only sets `ANTHROPIC_API_KEY`, `PGTZ`, and `TZ`. `pyproject.toml` sets `addopts = "-m 'not live'"`, so inside pytest `session.config.option.markexpr` is the string `not live` by default and exactly `live` when the live tier is selected (probed on 2026-10-17 with a plugin that printed the value and exited). `docket.config.DATABASE_URL` resolves the environment, then `.env`, then the built-in default, and `urllib.parse.urlsplit(url).path` is `/docket_db` for the WSL URL, so the database name is that path with its leading slash removed. Importing `docket.config` early is harmless: `src/docket/__init__.py` is empty, the module's only side effect is `load_dotenv()`, five integration test modules already import `DATABASE_URL` from it at collection time, and no test under `tests/` (the live tier aside) sets or reloads `DATABASE_URL`.

`scripts/deploy.sh` wraps `railway up --detach`; it prints a WARNING and sleeps three seconds on a branch other than `main` and does not look at the working tree. `GOALS.md` Constraints says deploys happen only from a clean `main` after merge, decision `0022` records why, and `docs/specs/operations.md` Deploying says a dead wrapper leaves `COMMIT_SHA` behind and `git status` shows it. `railway` is on PATH on this machine at `/home/linuxbrew/.linuxbrew/bin/railway`; the refusal in M2 runs before anything invokes it.

GitHub: the repository `thinkdarrell/docket-pub` is public (`gh repo view --json visibility` printed `PUBLIC` on 2026-10-17), Actions are enabled (`gh api repos/thinkdarrell/docket-pub/actions/permissions --jq .enabled` printed `true`), no workflow exists (`actions/workflows` total_count 0), `main` is not protected (`branches/main/protection` returned `Branch not protected`, HTTP 404) and no rulesets exist, and the operator's `gh` token has the `repo` scope, which suffices for branch protection on a repository the account owns. `D15` in `docs/DEBT.md` and decision `0022` both say protection needs GitHub Pro for a private repository; the repository stopped being private and the row's trigger has fired. The `ubuntu-latest` runner image (`Ubuntu2404-Readme.md`, read 2026-10-17) ships Node.js 22.23.3, PostgreSQL 16.15 with the server disabled by default (its `psql` client on PATH), Python 3.10.22 as a cached tool, and Perl 5.38.2 (which provides `shasum`, which `tools/test-db` uses to name the database). `pyproject.toml` declares `dependencies` dynamic and reads them from `requirements.lock` (`[tool.setuptools.dynamic]`), so `pip install -e ".[dev]"` installs the pinned tree and nothing resolves loosely on a fresh runner; the producer suite under `transcriber/tests` passed its 70 tests in this worktree's venv with none of `faster-whisper`, `pyannote.audio`, or `torch` installed (`pip list` shows none of them), so CI needs nothing from `transcriber/requirements.txt`; `tools/fixtures/judge/run` never invokes `./tools/verify` and nothing under `tools/`, `tests/`, or `transcriber/tests` asserts verify's check count, so M1's change from five checks to six breaks no check; `requirements.lock` pins `psycopg2-binary`, so no `libpq-dev` is needed; the tests that mention `ffmpeg`, `ffprobe`, or `tesseract` mock `subprocess.run` or skip, so no apt packages are needed; `tests/integration/test_analytics_views.py` finds `psql` by trying the Homebrew path and then `psql` on PATH, and creates a database per run, which the `docket` user in the `postgres:16` image may do because it is that image's superuser.

Prose that states the rules this plan changes, each listed as an edit or a leave-alone: `docs/MATURITY.md` Current rung, the sentences "Nothing is `enforced` yet: verify runs when a session chooses to run it, not where it cannot be skipped." (M4 edits) and "`evidence-check` stays `specced`: ... that aggregation is a separate small build." (M1 edits); `docs/DEBT.md` row `D15` (M4 deletes) and row `D37` (M2 edits its trigger); `AGENTS.md` line 16 (the `tools/` map entry; M1 adds `check-plans` and `hooks/pre-commit`), line 27 (the Verify entry; M1 names the sixth check, M2 adds the refusal sentence), and line 39 (the hooks sentence; M1 adds where the hooks live); `docs/specs/operations.md` Local environment (M1 adds the `core.hooksPath` step), Tests (M1 the sixth check, M2 the refusal, M3 the CI paragraph), Deploying (M2 the refusals, M4 the protection); `docs/specs/index.md` line 23 (M1 and M3 extend the `operations.md` row); `docs/capabilities/index.md` (M1, M3, M4); `docs/capabilities/evidence-check.md` Enforcement point and Remediation message (M1 records the as-built shapes); decision `0022` (leave alone; its Decision still binds, and `DECISION_FORMAT.md` forbids rewriting a rationale); `plans/completed/*.md` mentions of absent hooks (leave alone; history); `skills/harness-init/SKILL.md` line 117 and `skills/capability-build/SKILL.md` line 11 (leave alone; generic wording).

## Plan of Work

### M1: the active-plan check, verify's sixth check, and the pre-commit hook

Create `tools/check-plans`, a POSIX shell script in the style of `tools/check-workflows` (header comment stating the contract, `set -u`, `cd "$(dirname "$0")/.."`, a `fail` helper, one line per item, a final count line, exit 0 only when every item passed). Its contract: with no arguments it checks every `plans/active/*.md`; with `--staged` it checks the index version of every staged, added-or-modified file matching `plans/active/*.md` (listed by `git diff --cached --name-only --diff-filter=AM -- 'plans/active/*.md'` and read with `git show ":$path"` into a temporary file, so the hook judges what will be committed, not the working tree); with one or more file paths it checks those files (this is how the failing case is demonstrated on a copy, without touching the real plan). The no-argument loop guards against POSIX globbing (`for f in plans/active/*.md` yields the literal pattern when the directory holds no `.md` file) with `[ -e "$f" ] || continue` before counting, as `tools/check-workflows` does. For each file it runs `tools/judge-milestone snapshot <file>` with stdout discarded and stderr captured; the judge reads the file's contents only (`read_plan <"$plan"`) and echoes the path it was given, so a temporary copy judges identically and the path substitution below is purely cosmetic. Exit 0 prints `plans: <path> ... ok (Progress, Surprises & Discoveries, Decision Log, Outcomes & Retrospective)`. Exit 2 prints `plans: <path> ... FAILED`, then the judge's `judge: defect ...` line indented two spaces with any temporary path replaced by the real path (a `sed` with `|` as its delimiter, since both paths contain `/`), then the card's guidance indented two spaces: when the defect line contains `no date`, the line `Completed entries record when the work was observed: - [x] (YYYY-MM-DD HH:MMZ) <entry>. Use the time you observed, not an estimate.`; otherwise the line `plans/PLANS.md requires Progress, Surprises & Discoveries, Decision Log, and Outcomes & Retrospective in every plan. Add the heading and the entries the work produced; an empty section is also a failure.` Any other exit prints `plans: <path> ... FAILED` and `  tools/judge-milestone snapshot exited <n>`. The last line is `plans: N of N ok` (exit 0) or `plans: K of N failed` (exit 1); with nothing to check it prints `plans: no active plans` (no-argument mode) or `plans: no staged plans` (`--staged`) and exits 0, because an empty `plans/active/` is a passing state by the card.

Create `tools/hooks/pre-commit`, executable, three lines of substance: a header comment naming its purpose and the one-time install command, then `cd "$(git rev-parse --show-toplevel)" && exec tools/check-plans --staged`. Git runs a pre-commit hook with the worktree root as its working directory, so the `cd` is a guard, not a requirement.

Add the sixth check to `tools/verify` after the transcriber line, so the existing ordinals in the documents stay true:

    check "plans"             tools/check-plans

Update the header comment of `tools/verify` to list it. Edit `AGENTS.md` line 16 to add `check-plans` (every active plan carries its living sections and dated ticks) and `hooks/pre-commit` (the same check on a staged plan; installed with `git config core.hooksPath tools/hooks`) to the `tools/` entry; line 27 to name the active-plan check as the sixth thing verify runs; line 39 to say the hooks live in `tools/hooks/`. Keep `AGENTS.md` under about 100 lines (it is 48). Edit `docs/specs/operations.md` Local environment to add, after the `node` sentence, one sentence and the command `git config core.hooksPath tools/hooks`, saying it is run once in the main checkout and applies to every linked worktree because worktrees share the repository's configuration; edit its Tests section to name the sixth check (`tools/check-plans`, what it prints, that an empty `plans/active/` passes) and to change `all 5 checks` to the new count where that paragraph quotes verify's closing line; edit `docs/specs/index.md` line 23 to add `the active-plan check as its sixth` and `the hooks path`. In `docs/capabilities/evidence-check.md`, rewrite the Enforcement point section to the as-built facts (verify's sixth check; `tools/hooks/pre-commit` on any commit that stages an active plan, where `core.hooksPath` is set) and replace the Remediation message section's two examples with the as-built output shapes above. In `docs/capabilities/index.md` set `evidence-check` to `built` with Enforced at `./tools/verify` (sixth check); `tools/hooks/pre-commit` where `core.hooksPath` is set. In `docs/MATURITY.md` Current rung, replace the sentence beginning "`evidence-check` stays `specced`" with one saying it is `built` as `tools/check-plans`, verify's sixth check, seen to fail on both halves of its failing case on the date observed.

Promote to `built` only after both halves of the card's failing case have been observed, as Validation and Acceptance below states, and record the observed output in Artifacts and Notes.

### M2: the test suite refuses the wrong database, the settings file denies, the deploy wrapper refuses

In `tests/conftest.py`, add a `pytest_sessionstart(session)` hook after the existing environment lines. It reads `session.config.option.markexpr` (default `None` or the string pytest received); when the stripped value is exactly `live` it returns. Otherwise it takes the URL from `os.environ.get("DATABASE_URL")` and, only when that is unset, from `docket.config.DATABASE_URL` (which also reads `.env`), so a verify run, which exports the variable, imports no application code before collection; it takes `urllib.parse.urlsplit(url).path.lstrip("/")` as the database name, and when that name does not start with `docket_test_` calls `pytest.exit(message, returncode=2)` with the message: `tests: refusing to run against database '<name>': the unit tier deletes rows from whatever DATABASE_URL names (docs/DEBT.md D37). Run ./tools/verify, or one tier with DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest <tier> -q -p no:cacheprovider; tools/test-db --drop (docs/specs/operations.md Tests). The live tier (-m live) is exempt.` Add a module docstring paragraph saying why. No test is added for the guard; its acceptance is the observed refusal below.

Create `.claude/settings.json` with exactly this content (two-space indentation, trailing newline):

    {
      "permissions": {
        "deny": [
          "Bash(git * --no-verify)",
          "Bash(git * --no-verify *)",
          "Bash(git -c core.hooksPath=*)",
          "Bash(git * -c core.hooksPath=*)",
          "Bash(railway up *)",
          "Bash(railway redeploy *)",
          "Bash(scripts/deploy.sh *)",
          "Bash(./scripts/deploy.sh *)"
        ]
      }
    }

In `scripts/deploy.sh`, replace the `if [ "$branch" != "main" ]` block (the WARNING, the "continuing in 3s" line, and the `sleep 3`) with two refusals, dirty tree first so that both code paths can be observed from the plan branch: when `git status --porcelain` prints anything, print `deploy: refusing to deploy with uncommitted changes (git status --porcelain is not empty): railway up ships the working tree as it is. Commit, stash, or remove them (a COMMIT_SHA left by a dead run counts) and re-run.` to stderr and exit 3; then, when the branch is not `main`, print `deploy: refusing to deploy from branch '<branch>': deploys run from a clean main after the pull request has merged (GOALS.md Constraints, decision 0022).` to stderr and exit 3. Both run before `COMMIT_SHA` is written and before `railway` is invoked. Keep each test to one line of the form `if [ -n "$(git status --porcelain)" ]; then`, since the dirty-tree path is exercised from this branch only by the acceptance probe below and otherwise first runs for real on `main`. Update the script's header comment to state both refusals and the exit code.

Documents: in `docs/DEBT.md` row `D37`, append to the Why deferred cell that since this plan `tests/conftest.py` refuses any database not named `docket_test_*` outside the live tier, so the deletes cannot reach `docket_db`, and leave the trigger's second clause (scope the deletes or move the tests) as the remaining work. In `AGENTS.md` line 27, after the `D37` clause, add that `tests/conftest.py` refuses any other database outside the live tier. In `docs/specs/operations.md` Tests, add one sentence after the live-tests paragraph stating the refusal, its exit status 2, and that the exemption is the exact marker expression `live`, so a single live test is run as `venv/bin/python -m pytest -m live tests/live/<file>` and any other expression is refused; in Deploying, replace the sentence about a dead wrapper leaving `COMMIT_SHA` with one that also says the wrapper refuses, with exit 3, a branch other than `main` or a working tree with uncommitted changes, so a leftover `COMMIT_SHA` blocks the next deploy until it is removed. Add one sentence to `AGENTS.md` Working rules, or extend line 39, saying the committed `.claude/settings.json` denies the hook-bypass and deploy commands and that the rules are listed there and nowhere else.

### M3: continuous integration runs verify

Create `.github/workflows/verify.yml`:

    name: verify
    on:
      push:
      pull_request:
        branches: [main]
    jobs:
      verify:
        name: verify
        runs-on: ubuntu-latest
        timeout-minutes: 20
        services:
          postgres:
            image: postgres:16
            env:
              POSTGRES_USER: docket
              POSTGRES_PASSWORD: docket_dev
              POSTGRES_DB: docket_db
            ports: ['5432:5432']
            options: >-
              --health-cmd "pg_isready -U docket"
              --health-interval 5s
              --health-timeout 5s
              --health-retries 10
        env:
          DATABASE_URL: postgresql://docket:docket_dev@localhost:5432/docket_db
        steps:
          - uses: actions/checkout@v4
          - uses: actions/setup-python@v5
            with:
              python-version: '3.10'
              cache: pip
              cache-dependency-path: requirements.lock
          - run: python -m venv venv && venv/bin/pip install -e ".[dev]"
          - run: ./tools/verify

The job invokes the documented command by name and nothing else, which is the identity property the fast-verify card asks for. `./tools/verify` and `tools/test-db` hard-code `venv/bin/python`, so the venv is created at the repository root under that name. Node and `psql` come from the runner image; if the first run fails with `psql not found` or `node is not on PATH`, add a step `sudo apt-get install -y postgresql-client` or `actions/setup-node@v4` respectively, record the failure in Surprises & Discoveries, and run again. Commit the workflow together with this plan's Progress and evidence edits, push the branch with `git push -u origin plan/factory-enforcement`, and watch the run to completion as Validation and Acceptance states. Record the run's URL, wall time, and verify's closing line in Artifacts and Notes.

Documents: in `docs/specs/operations.md` Tests, add a paragraph `Continuous integration` saying `.github/workflows/verify.yml` runs `./tools/verify` on every push to any branch and on pull requests to `main`, in a job named `verify`, on `ubuntu-latest` with Python 3.10, a `postgres:16` service as user `docket`, and the runner's own Node and `psql`; that a pull-request branch therefore runs twice per push; and the observed wall time of the first run. In `docs/specs/index.md` line 23 add `continuous integration` to the tests clause. In `docs/capabilities/index.md`, extend the `fast-verify` row's Enforced at cell with `.github/workflows/verify.yml` (the `verify` job), leaving the status `built` until M4.

### M4: main is protected, two cards are enforced, the record is updated

From the worktree, set the protection:

    gh api --method PUT repos/thinkdarrell/docket-pub/branches/main/protection --input - <<'EOF'
    {"required_status_checks":{"strict":false,"contexts":["verify"]},"enforce_admins":true,"required_pull_request_reviews":null,"restrictions":null,"allow_force_pushes":false,"allow_deletions":false}
    EOF

and read it back with `gh api repos/thinkdarrell/docket-pub/branches/main/protection --jq '.required_status_checks.contexts, .enforce_admins.enabled'`. Then: in `docs/capabilities/index.md` set `fast-verify` and `evidence-check` to `enforced`, each Enforced at cell naming `./tools/verify`, the `verify` job in `.github/workflows/verify.yml` as the required status check on `main` (decision 0052), and, for evidence-check, `tools/hooks/pre-commit`; leave `judge-milestone` at `built`. Write `docs/decisions/0052-main-requires-the-verify-check-to-merge.md` in the four-field format of `DECISION_FORMAT.md`: the Decision that a change reaches `main` only by pull request with the `verify` status check green, administrators included, with no required reviewer and no force pushes; the Rationale naming decision `0022` and `D15` (the rule was discipline because protection needed GitHub Pro for a private repository; the repository is public, so GitHub provides it free), why `strict` is false (one committer; the factory never rebases a plan branch), why administrators are included (the operator is the administrator), why no reviewer is required (one committer), and the exact `gh api` command above as the way to recreate it; the Date as the day observed with `M4 session of plans/active/factory-enforcement.md, on the operator's instruction in that plan`; Status `accepted`. Delete row `D15` from `docs/DEBT.md` (closed rows are deleted; the number is never reused). In `docs/MATURITY.md` Current rung, replace the sentence "Nothing is `enforced` yet: verify runs when a session chooses to run it, not where it cannot be skipped." with one stating that since the observed date `./tools/verify` is the required `verify` status check on `main` (`.github/workflows/verify.yml`, decision `0052`), so `fast-verify` and `evidence-check` are `enforced`, that `tools/hooks/pre-commit` additionally runs evidence-check on staged plans where `core.hooksPath` is set, and that the judge itself still runs only inside `cycle-run`; keep the twenty-consecutive-changes sentence unchanged. In `docs/specs/operations.md` Deploying, add that GitHub refuses a direct push to `main` and a merge whose `verify` check is not green, citing `0052`, and that the protection is recreated with the command the decision records. `AGENTS.md` needs no edit in M4 unless the Map's `docs/decisions/` line counts files, which it does not.

The pull request that closes this plan is itself the first merge the protection governs. Because the workflow runs on both events, the pull request shows two check runs named `verify`, one from the push and one from the pull-request event; the required context accepts either, and GitHub waits for the newest check suite to finish before the merge button enables. The `docs/specs/operations.md` sentence M4 adds says so.

## Concrete Steps

Every milestone session works in `/home/thinkdarrell/docket-pub/.claude/worktrees/factory-enforcement` on branch `plan/factory-enforcement`, with that worktree's own `venv/` and its gitignored `.env` (`DATABASE_URL=postgresql://thinkdarrell@/docket_db`, needed on this machine per `D57`). Each session begins and ends with `./tools/verify` (about 85 seconds here; budget 180 s) and records both closing lines. Commands below are expected transcripts labelled as such; the executing session replaces them with what it observed.

M1, in order (executed 2026-10-17; the observed transcripts are in Artifacts and Notes): run `./tools/verify` (expect `verify: all 5 checks passed in Ss.`; observed `verify: all 5 checks passed in 96s.`); write `tools/check-plans` and `tools/hooks/pre-commit`, `chmod +x` both; run `tools/check-plans` (expect one `ok` line for `plans/active/factory-enforcement.md` and `plans: 1 of 1 ok`); demonstrate both failing halves on copies (commands under Validation and Acceptance); set `git config core.hooksPath tools/hooks` now, before the first commit, so every commit this milestone makes exercises the hook's passing path; add the verify line; edit the documents; commit the work so far together with the plan's evidence so far (several commits per milestone are normal; each must change the plan, decision 0037, and the hook will check the plan each time); demonstrate the hook's refusal (clause (e) under Validation and Acceptance, which breaks the committed plan, sees the commit refused, and restores it from `HEAD`); run `./tools/verify` (expect `verify: plans ... ok (0s)` and `verify: all 6 checks passed in Ss.`); write the remaining evidence, tick M1, and commit.

M2, in order: verify; add the guard to `tests/conftest.py`; run the refusal command (expect exit 2 and the message, no tests collected); run the live-collection command (expect a collection count, not a refusal); write `.claude/settings.json`; validate it with `venv/bin/python -m json.tool .claude/settings.json > /dev/null; echo "exit=$?"` (expect `exit=0`); attempt `git -c core.hooksPath=/dev/null status` from the session's own Bash tool and record whether the tool refused it (a session started before the file existed may not see the new rule; say so if the call ran, and the operator confirms the denial in a fresh session before merge); edit `scripts/deploy.sh`; with a clean tree run `scripts/deploy.sh --service docket-web; echo "exit=$?"` (expect the branch refusal and `exit=3`; the worktree is on `plan/factory-enforcement`, so `railway` is never reached), then `touch COMMIT_SHA; scripts/deploy.sh --service docket-web; echo "exit=$?"; rm COMMIT_SHA` (expect the dirty-tree refusal and `exit=3`); edit the documents; verify (expect 6 checks passed; the exported `docket_test_` URL passes the guard); write the evidence and tick M2.

M3, in order: verify; write `.github/workflows/verify.yml`; commit it with the plan's edits; `git push -u origin plan/factory-enforcement`; `gh run list --branch plan/factory-enforcement --limit 1 --json databaseId,name,status,conclusion,url,createdAt,updatedAt` (expect one row named `verify`); `gh run watch <databaseId> --exit-status; echo "exit=$?"` (expect `exit=0`; give the Bash call a timeout of at least 900000 milliseconds); `gh run view <databaseId> --json conclusion,jobs --jq '.conclusion, (.jobs[] | .name + " " + .conclusion)'` (expect `success` and `verify success`); edit the documents with the observed wall time; verify locally; commit, push again (this triggers a second run; it need not be awaited, but its result is recorded if seen); write the evidence and tick M3.

M4, in order: verify; run the `gh api --method PUT` command (expect a JSON body naming the `verify` context); read it back (expect `["verify"]` and `true`); write decision 0052; edit `docs/capabilities/index.md`, `docs/DEBT.md`, `docs/MATURITY.md`, `docs/specs/operations.md`; run the acceptance greps; verify; write the evidence and tick M4.

## Validation and Acceptance

M1 is accepted when: (a) `./tools/verify` prints a line `verify: plans ... ok (Ns)` and the closing line `verify: all 6 checks passed in Ss.`, exit 0; (b) `tools/check-plans` with no argument prints `plans: plans/active/factory-enforcement.md ... ok (Progress, Surprises & Discoveries, Decision Log, Outcomes & Retrospective)` and `plans: 1 of 1 ok`, exit 0; (c) on a copy with the Decision Log heading removed, made with `T=$(mktemp -d); cp plans/active/factory-enforcement.md "$T/a.md"; sed -i '/^## Decision Log$/d' "$T/a.md"; tools/check-plans "$T/a.md"; echo "exit=$?"`, the output names `$T/a.md`, contains `missing the required section` and the `plans/PLANS.md requires` guidance line, and ends `plans: 1 of 1 failed` and `exit=1`; (d) on a copy where the first `- [ ] ` in Progress is changed to `- [x] ` with no date (`sed -i '0,/^- \[ \] /s//- [x] /' "$T/b.md"` after copying), the output contains `no date` and the `Completed entries record when the work was observed` guidance line, exit 1; (e) with everything committed and `git config core.hooksPath tools/hooks` set, breaking the real plan the same way as (c), staging it, and running `git commit -m probe; echo "exit=$?"` prints `plans: plans/active/factory-enforcement.md ... FAILED` and `exit=1`, after which `git checkout HEAD -- plans/active/factory-enforcement.md` (corrected by the M1 session from `git checkout -- ...`, which restores from the index where the broken plan is staged; see Surprises & Discoveries) restores it and `git status --porcelain` prints nothing; (f) `docs/capabilities/index.md` shows `evidence-check` as `built`. The session records (c), (d), and (e) verbatim in Artifacts and Notes: they are the card's promotion evidence.

M2 is accepted when: (a) `DATABASE_URL=postgresql://thinkdarrell@/docket_db venv/bin/python -m pytest tests/unit -q -p no:cacheprovider; echo "exit=$?"` prints the `tests: refusing to run against database 'docket_db'` message, collects no tests, and prints `exit=2`; (b) `venv/bin/python -m pytest -m live --collect-only -q tests/live 2>&1 | tail -1` prints a line ending `tests collected` (or `test collected`) rather than the refusal (collection needs no API key; `tests/conftest.py` sets a dummy); (c) `./tools/verify` prints `verify: all 6 checks passed in Ss.`; (d) `venv/bin/python -m json.tool .claude/settings.json > /dev/null; echo "exit=$?"` prints `exit=0` and `grep -c '"Bash(' .claude/settings.json` prints `8`; (e) with a clean tree, `scripts/deploy.sh --service docket-web; echo "exit=$?"` on this branch prints the branch refusal to stderr and `exit=3`, and `ls COMMIT_SHA` prints `No such file or directory`; (e2) after `touch COMMIT_SHA`, the same command prints the dirty-tree refusal and `exit=3`, and `rm COMMIT_SHA` leaves `git status --porcelain` empty; (f) the session's own attempt to run `git -c core.hooksPath=/dev/null status` through its Bash tool is recorded as refused, or recorded as not refused with the note that the operator confirms it in a fresh session before merge.

M3 is accepted when: (a) `gh run list --branch plan/factory-enforcement --limit 1 --json name,status,conclusion` prints a row with `"name":"verify"`, `"status":"completed"`, `"conclusion":"success"`; (b) `gh run view <id> --json jobs --jq '.jobs[].name'` prints `verify`; (c) the run's log, fetched with `gh run view <id> --log | grep 'verify: all'`, contains `verify: all 6 checks passed`; (d) `./tools/verify` passes locally; (e) `docs/specs/operations.md` Tests states the observed CI wall time.

M4 is accepted when: (a) `gh api repos/thinkdarrell/docket-pub/branches/main/protection --jq '.required_status_checks.contexts, .enforce_admins.enabled'` prints `["verify"]` on one line and `true` on the next; (b) `grep -c '^| D15 ' docs/DEBT.md` prints `0`; (c) `grep -cE '^\| .(fast-verify|evidence-check). \| enforced ' docs/capabilities/index.md` prints `2`; (d) `ls docs/decisions/0052-*.md` prints one path; (e) `grep -c 'enforced. yet' docs/MATURITY.md` prints `0`; (f) `./tools/verify` passes. Clause (b) counts lines beginning with the row's cell, so a mention of `D15` in decision 0052's rationale, which is expected, does not fail it.

## Idempotence and Recovery

`tools/check-plans` reads files and writes nothing but its temporary directory, which it removes on exit. The hook refuses or allows and changes nothing; `git checkout HEAD -- <plan>` undoes the probe edit in M1 (e) (the staged copy as well as the working tree; `git checkout -- <plan>` alone would leave the staged, broken copy in place), which is run only after the real plan is committed. Setting `core.hooksPath` is one `git config` line and is undone with `git config --unset core.hooksPath`; it lives in the repository's configuration, so it applies to the main checkout and every worktree on this machine at once. The database guard changes no state; the refusal command in M2 (a) runs against `docket_db` deliberately and is safe because it exits before collection. `scripts/deploy.sh` under M2 refuses before writing `COMMIT_SHA` or invoking `railway`, so running it from the plan branch deploys nothing. The CI workflow is idempotent: every push runs it again. Branch protection is one PUT; a wrong body is corrected by another PUT, and `gh api --method DELETE repos/thinkdarrell/docket-pub/branches/main/protection` removes it entirely. A milestone halted by the judge or by verify is resumed as `docs/specs/operations.md` Running the factory says: fix the cause in the worktree, commit, re-run `/cycle-run` with the same arguments.

## Artifacts and Notes

Authoring (2026-10-17): `./tools/verify` in the main checkout with `DATABASE_URL=postgresql://thinkdarrell@/docket_db`:

    verify: test-db ... ok (0s) postgresql://thinkdarrell@/docket_test_fc2d98b9
    verify: unit+web+services ... ok (40s)
    verify: integration ... ok (43s)
    verify: judge-fixtures ... ok (1s)
    verify: workflows ... ok (0s)
    verify: transcriber ... ok (1s)
    verify: all 5 checks passed in 85s.

Without the variable the same command printed `ERROR:  permission denied to create database` and `verify: 5 of 5 checks failed in 0s.` (`D57`). The hooks-path experiment printed `config seen in worktree: tools/hooks`, `hook ran in <worktree path>`, `commit exit=1`, then `exit=0` for both `--no-verify` and `-c core.hooksPath=/dev/null`. The pytest probe printed `markexpr= 'not live'`. `gh run list --workflow verify.yml --limit 1` printed `HTTP 404: workflow verify.yml not found on the default branch`. Milestone sessions append their transcripts below this paragraph.

M1 (2026-10-17, observed): starting state, `./tools/verify` in the worktree on a clean tree at 5935f0b, before any edit:

    verify: test-db ... ok (0s) postgresql://thinkdarrell@/docket_test_a485ea18
    verify: unit+web+services ... ok (45s)
    verify: integration ... ok (49s)
    verify: judge-fixtures ... ok (1s)
    verify: workflows ... ok (0s)
    verify: transcriber ... ok (1s)
    verify: all 5 checks passed in 96s.

`git config core.hooksPath` printed nothing (exit 1) and `tools/hooks` did not exist. After writing `tools/check-plans` and `tools/hooks/pre-commit`, clause (b), `tools/check-plans` with no argument:

    plans: plans/active/factory-enforcement.md ... ok (Progress, Surprises & Discoveries, Decision Log, Outcomes & Retrospective)
    plans: 1 of 1 ok
    exit=0

Clause (c), `T=$(mktemp -d); cp plans/active/factory-enforcement.md "$T/a.md"; sed -i '/^## Decision Log$/d' "$T/a.md"; tools/check-plans "$T/a.md"; echo "exit=$?"`:

    plans: /tmp/tmp.2s6px3T0Hc/a.md ... FAILED
      judge: defect /tmp/tmp.2s6px3T0Hc/a.md is missing the required section `## Decision Log`
      plans/PLANS.md requires Progress, Surprises & Discoveries, Decision Log, and Outcomes & Retrospective in every plan. Add the heading and the entries the work produced; an empty section is also a failure.
    plans: 1 of 1 failed
    exit=1

Clause (d), `cp plans/active/factory-enforcement.md "$T/b.md"; sed -i '0,/^- \[ \] /s//- [x] /' "$T/b.md"; tools/check-plans "$T/b.md"; echo "exit=$?"`:

    plans: /tmp/tmp.2s6px3T0Hc/b.md ... FAILED
      judge: defect /tmp/tmp.2s6px3T0Hc/b.md has a completed Progress entry with no date at line 15 ("M1: `tools/check-plans` decides evidence-check for every active plan, ru...")
      Completed entries record when the work was observed: - [x] (YYYY-MM-DD HH:MMZ) <entry>. Use the time you observed, not an estimate.
    plans: 1 of 1 failed
    exit=1

Also observed in the same run: `tools/check-plans --staged` with nothing staged printed `plans: no staged plans` and `exit=0`; a path that does not exist printed `plans: <path> ... FAILED`, the judge's `judge: defect <path> does not exist`, the `plans/PLANS.md requires` guidance, `plans: 1 of 1 failed`, `exit=1`. `git config core.hooksPath tools/hooks` run from the worktree wrote `tools/hooks` to `file:/home/thinkdarrell/docket-pub/.git/config` (`git config --show-origin --get core.hooksPath`), the repository configuration shared with the main checkout.

The first commit of the milestone (b67201d) ran the hook on its passing path and printed, before the commit was accepted:

    plans: plans/active/factory-enforcement.md ... ok (Progress, Surprises & Discoveries, Decision Log, Outcomes & Retrospective)
    plans: 1 of 1 ok

Clause (e), with everything committed at b67201d and `core.hooksPath` set: `sed -i '/^## Decision Log$/d' plans/active/factory-enforcement.md && git add plans/active/factory-enforcement.md && git commit -m probe; echo "exit=$?"`:

    plans: plans/active/factory-enforcement.md ... FAILED
      judge: defect plans/active/factory-enforcement.md is missing the required section `## Decision Log`
      plans/PLANS.md requires Progress, Surprises & Discoveries, Decision Log, and Outcomes & Retrospective in every plan. Add the heading and the entries the work produced; an empty section is also a failure.
    plans: 1 of 1 failed
    exit=1

`git log --oneline -1` still printed b67201d, so no commit was made. The clause's restore step, `git checkout -- plans/active/factory-enforcement.md`, exited 0 but `git status --porcelain` then printed `M  plans/active/factory-enforcement.md` (staged, not clean): that command restores the working tree from the index, and the index held the broken plan. The `./tools/verify` run started in the same command therefore saw the broken plan and printed:

    verify: test-db ... ok (0s) postgresql://thinkdarrell@/docket_test_a485ea18
    verify: unit+web+services ... ok (46s)
    verify: integration ... ok (49s)
    verify: judge-fixtures ... ok (1s)
    verify: workflows ... ok (0s)
    verify: transcriber ... ok (1s)
    verify: plans ... FAILED (0s)
    verify: 1 of 6 checks failed in 97s. Each failing check's output is above its summary line; re-run one with:
        DATABASE_URL=$(tools/test-db) tools/check-plans; tools/test-db --drop

which is the sixth check failing for real inside verify, an observation the plan did not ask for but which the card's enforcement point is about. `git checkout HEAD -- plans/active/factory-enforcement.md` then exited 0, `git status --porcelain` printed nothing, `grep -c '^## Decision Log$'` printed `1`, and `tools/check-plans` printed the clause (b) output again with `exit=0`. Clause (a), `./tools/verify` on the restored tree:

    verify: test-db ... ok (0s) postgresql://thinkdarrell@/docket_test_a485ea18
    verify: unit+web+services ... ok (46s)
    verify: integration ... ok (49s)
    verify: judge-fixtures ... ok (1s)
    verify: workflows ... ok (0s)
    verify: transcriber ... ok (0s)
    verify: plans ... ok (0s)
    verify: all 6 checks passed in 96s.

exit 0, at 2026-10-17 23:56Z.

## Interfaces and Dependencies

`tools/check-plans [--staged | <file>...]`: POSIX sh; depends on `tools/judge-milestone` (its `snapshot` mode and exit codes 0 and 2), `git` (for `--staged` only), `mktemp`, `sed`, `grep`. Output lines begin `plans: `. Exit 0 when every checked file holds or nothing was checked, 1 when any file failed. It is verify's sixth check and the body of `tools/hooks/pre-commit`.

`tools/hooks/pre-commit`: POSIX sh, executable; `exec tools/check-plans --staged` from the worktree root. Activated per clone by `git config core.hooksPath tools/hooks`.

`tests/conftest.py` `pytest_sessionstart`: exempts the exact marker expression `live`; otherwise requires the database name in `docket.config.DATABASE_URL` to start with `docket_test_`; refuses with `pytest.exit(..., returncode=2)`.

`.claude/settings.json`: the eight deny rules listed in M2, under `permissions.deny`, and nothing else. It is the one place these rules live; prose elsewhere points here.

`scripts/deploy.sh`: exit 2 on bad usage (unchanged), exit 3 on a branch other than `main` or a non-empty `git status --porcelain`, before `COMMIT_SHA` is written or `railway` is invoked.

`.github/workflows/verify.yml`: workflow `verify`, job id and name `verify`, triggers `push` (all branches) and `pull_request` (base `main`); runs `./tools/verify` with `DATABASE_URL=postgresql://docket:docket_dev@localhost:5432/docket_db` against a `postgres:16` service. The status-check context is `verify`.

Branch protection on `main`: `required_status_checks.contexts == ["verify"]`, `strict` false, `enforce_admins` true, no required reviews, no restrictions, force pushes and deletion disallowed. Recorded in decision `0052`.

Identifiers spent by this plan: decision number `0052`; verify check name `plans`; no new `docs/DEBT.md` rows (`D15` is deleted, `D37` edited; the next free row number is `D59`, which this plan does not use).

## Revision notes

- 2026-10-17, M1 session: Validation and Acceptance clause (e) and Idempotence and Recovery now say `git checkout HEAD -- <plan>` where they said `git checkout -- <plan>`, because the latter was run as written and left the staged, broken plan in place (Surprises & Discoveries); the Concrete Steps M1 line notes it was executed and points to the transcripts. No Progress line text, acceptance number, or identifier changed.

- 2026-10-17, after the operator reviewed the authored plan and pasted a ten-point review: Plan of Work M1 gained the empty-glob guard and the `sed` delimiter note; M2 gained the environment-first guard, the dirty-tree-first order in `scripts/deploy.sh`, and the exact-expression sentence for the spec; M4 gained the two-check-runs sentence; Concrete Steps M1 now sets `core.hooksPath` before the first commit and says several commits per milestone are expected; Concrete Steps and Validation M2 gained the `COMMIT_SHA` probe (clause (e2)); Context gained the facts that refute the review's two showstoppers (the judge fixtures and verify's count; the lock as the editable install's source; the producer tests' independence from the heavy packages) and the import-safety facts for `docket.config`. The Decision Log entry dated the same day records what was adopted, what did not apply, and what was declined. No Progress line, acceptance number, or identifier changed; Validation clauses (a) through (f) of each milestone were re-read against the revised rules and hold as written, with M2 (e) now explicitly a clean-tree clause beside the new (e2).
