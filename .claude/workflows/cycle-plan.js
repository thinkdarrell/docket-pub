export const meta = {
  name: 'cycle-plan',
  description: 'Turn a stated goal into a committed ExecPlan on its own branch, worktree, and venv, or stop with the questions only the operator can answer',
  whenToUse: 'From any checkout of docket-pub: /cycle-plan <goal in a sentence or two>',
  phases: [{ title: 'Scope' }, { title: 'Setup' }, { title: 'Author' }],
}

// cycle-plan: the factory's planning command. The contract is
// plans/active/factory-workflows.md (Plan of Work, M3). Five agents run in
// sequence: guard (is this a docket-pub checkout with a reachable origin),
// scope (a read-only brief for the goal, or the operator's questions), setup
// (branch, worktree, venv), plan-author (skills/plan-author/SKILL.md writes and
// commits plans/active/<slug>.md), check (the judge's snapshot accepts the new
// plan, the tree is clean, one commit over origin/main). The script has no
// clock, shell, or filesystem: every fact comes back from an agent, and every
// agent is told to report only what it observed.

// ---------------------------------------------------------------------------
// Arguments. `args` may be the goal as a string, an array whose first element
// is the goal (second, optionally, the operator's answers), or an object with
// `goal` and optional `answers` (a string the operator appends after a
// `questions` stop).
// ---------------------------------------------------------------------------

let rawGoal
let rawAnswers
if (typeof args === 'string') {
  rawGoal = args
} else if (Array.isArray(args)) {
  rawGoal = args[0]
  rawAnswers = args[1]
} else if (args && typeof args === 'object') {
  rawGoal = args.goal
  rawAnswers = args.answers
}

const goal = typeof rawGoal === 'string' ? rawGoal.trim() : ''
const answers = typeof rawAnswers === 'string' ? rawAnswers.trim() : ''

if (!goal) {
  log('cycle-plan: refused: no goal given; run /cycle-plan <goal in a sentence or two>')
  return { status: 'refused', reason: 'no goal given', where: 'arguments' }
}

// The goal as every agent reads it: the operator's sentence, plus their
// answers when this is the rerun after a `questions` stop.
const goalText = answers
  ? `${goal}\n\nThe operator's answers to the questions a previous run of /cycle-plan asked:\n${answers}`
  : goal

// ---------------------------------------------------------------------------
// Helpers.
// ---------------------------------------------------------------------------

// The two lines every agent prompt begins with, once the directory is known.
// `kind` is `checkout` for the directory the operator launched from (which may
// be a main checkout or a linked worktree) and `worktree` for the one this run
// creates; the rule is the same.
function confine(kind, dir) {
  return (
    `Work only in the git ${kind} at ${dir}. Every shell command you run starts with \`cd ${dir} &&\`; you may not touch any other directory.\n` +
    'Report only what you observed. Never state a result for a command you did not run.\n'
  )
}

// A refusal is a returned object, never a thrown error, so the run's result is
// readable. The caller writes `return refuse(...)` at the top level. `extra`
// carries whatever the operator needs to clean up or resume.
function refuse(reason, where, extra) {
  log(`cycle-plan: refused: ${reason}`)
  return { status: 'refused', reason, where, ...(extra || {}) }
}

// `agent()` resolves to null when the agent was stopped or died after retries.
function noResult(label, where, extra) {
  return refuse(`agent ${label} returned no result`, where, extra)
}

// ---------------------------------------------------------------------------
// Stage 1: guard. One cheap agent confirms this is a docket-pub checkout with
// the right remote and GitHub account, fetches origin, and reports the main
// checkout's path (the parent of the common git directory) and origin/main.
// ---------------------------------------------------------------------------

phase('Scope')

const GUARD_SCHEMA = {
  type: 'object',
  required: ['checkout', 'main', 'ok', 'detail', 'origin_main'],
  properties: {
    checkout: { type: 'string' },
    main: { type: 'string' },
    ok: { type: 'boolean' },
    detail: { type: 'string' },
    origin_main: { type: 'string' },
  },
}

const guardPrompt =
  'Work only in the git checkout that is your current working directory; print it with `pwd -P` first and use that path as <checkout> below. Every shell command you run starts with `cd <checkout> &&`; you may not touch any other directory.\n' +
  'Report only what you observed. Never state a result for a command you did not run.\n' +
  '\n' +
  'You are the guard for a run of /cycle-plan, which will author a new ExecPlan for docket-pub on a new branch and worktree. Run the seven checks below, in order, each from <checkout>. Run every check even after one misses; fix nothing. `ok` is true only when every condition holds exactly. `detail` holds one line per check, `<name>: <what it printed>`, with any miss listed first and marked `MISS`.\n' +
  '\n' +
  '1. `checkout`: `pwd -P`, then `git rev-parse --show-toplevel`. The top level is the repository root; if `pwd -P` is a subdirectory of it, use the top level as <checkout> from here on. Return the top-level path, resolved with `cd <toplevel> && pwd -P`, as `checkout`.\n' +
  '2. `main`: `main=$(cd "$(git rev-parse --git-common-dir)/.." && pwd -P); echo "$main"` prints an absolute path. This is the main checkout: the same as `checkout` when the current directory is the main checkout (`git rev-parse --git-common-dir` prints `.git` there), and the parent repository when the current directory is a linked worktree (it prints an absolute `.../.git` there). Return it as `main`.\n' +
  '3. `origin`: `git remote get-url origin` prints a URL ending in `thinkdarrell/docket-pub.git` or `thinkdarrell/docket-pub`.\n' +
  '4. `gh-user`: `gh api user --jq .login` prints `thinkdarrell`.\n' +
  '5. `fetch`: `GIT_TERMINAL_PROMPT=0 git fetch -q origin; echo "exit=$?"` prints `exit=0`.\n' +
  '6. `origin-main`: `git rev-parse origin/main` prints a 40-character commit sha. Return it as `origin_main`.\n' +
  '7. `tools`: `test -x tools/judge-milestone && test -x tools/verify; echo "exit=$?"` prints `exit=0` (the plan this run writes will be executed and judged with them).\n' +
  '\n' +
  'Do not edit anything, create nothing, and do not check out any branch.\n'

const guard = await agent(guardPrompt, { effort: 'low', label: 'guard', schema: GUARD_SCHEMA })
if (!guard) return noResult('guard', 'guard, stage 1')
if (!guard.ok) return refuse(`guard check failed: ${guard.detail}`, 'guard, stage 1')
const checkout = guard.checkout
const main = guard.main
log(`cycle-plan: guard ok, checkout ${checkout}, main ${main}, origin/main ${guard.origin_main.slice(0, 7)}`)

// ---------------------------------------------------------------------------
// Stage 2: scope. A read-only agent studies the repository for the goal and
// returns the brief, or the questions only the operator can answer.
// ---------------------------------------------------------------------------

const SCOPE_SCHEMA = {
  type: 'object',
  required: ['outcome', 'slug', 'files', 'debt_paid', 'debt_tripped', 'specs_altered', 'out_of_scope', 'questions'],
  properties: {
    outcome: { type: 'string' },
    slug: { type: 'string' },
    files: { type: 'array', items: { type: 'string' } },
    debt_paid: { type: 'array', items: { type: 'string' } },
    debt_tripped: { type: 'array', items: { type: 'string' } },
    specs_altered: { type: 'array', items: { type: 'string' } },
    out_of_scope: { type: 'array', items: { type: 'string' } },
    questions: { type: 'array', items: { type: 'string' } },
  },
}

const scopePrompt =
  confine('checkout', checkout) +
  '\n' +
  'You scope a goal for a new ExecPlan of docket-pub, before the plan is authored. You are read-only: edit nothing, create nothing, commit nothing, create no branch or worktree, and start no subagents.\n' +
  '\n' +
  'The goal, as the operator stated it:\n' +
  '\n' +
  `${goalText}\n` +
  '\n' +
  'Read, in this order: `AGENTS.md`; `GOALS.md` (purpose, scope, non-goals, constraints); `docs/DEBT.md` (deferred items with stable ids `Dn` and the triggers that reopen them); `docs/capabilities/index.md` (which checks are enforced mechanically); the open GitHub issues (`gh issue list --state open --limit 50`, then `gh issue view <n>` for any issue the goal names or that plainly concerns it); then the code and documents the goal touches, found with grep from the repository root and read in full where they are small. `ARCHITECTURE.md` says which layer owns what when the goal names code.\n' +
  '\n' +
  'Return the brief with these fields:\n' +
  '- `outcome`: the goal restated as something an outside reader can observe after the work (a command and what it prints, a page and what it shows, a check that fails today and passes afterwards), not as code changes.\n' +
  "- `slug`: a short name for the plan: lowercase letters, digits, and hyphens only, at most 40 characters, naming the outcome rather than the mechanism. It must not already be a branch: `git branch -a --list 'plan/<slug>'` must print nothing; if it prints anything, choose another slug and check again, and say so in `out_of_scope`.\n" +
  '- `files`: repository-relative paths the work will change or must read closely, each confirmed to exist with `ls`.\n' +
  '- `debt_paid`: ids from `docs/DEBT.md` (for example `D12`) that this work would close, each with a few words; empty if none.\n' +
  '- `debt_tripped`: ids from `docs/DEBT.md` whose trigger this work would set off, each with a few words; empty if none.\n' +
  '- `specs_altered`: files under `docs/specs/` whose present-tense description of behaviour this work would change; empty if none.\n' +
  '- `out_of_scope`: adjacent work you noticed and deliberately exclude, each with a few words of why.\n' +
  '- `questions`: only questions the operator alone can answer: a choice between outcomes the goal leaves open, a constraint only they know, a scope the goal might or might not include. Write each as the question followed by why the plan cannot proceed on an assumption. A question whose answer is in the repository, or that a reasonable default settles, does not belong here: settle it and record the choice in `outcome` or `out_of_scope`. Leave `questions` empty when the plan can proceed.\n'

const brief = await agent(scopePrompt, { label: 'scope', schema: SCOPE_SCHEMA })
if (!brief) return noResult('scope', 'scope, stage 2')

if (brief.questions.length > 0) {
  log(`cycle-plan: questions: the scope agent asks ${brief.questions.length} question(s) only the operator can answer; rerun /cycle-plan with the answers appended to the goal`)
  brief.questions.forEach((q, i) => log(`cycle-plan: question ${i + 1}: ${q}`))
  return { status: 'questions', questions: brief.questions, brief }
}

const slug = brief.slug.trim()
if (!/^[a-z0-9-]{1,40}$/.test(slug)) {
  return refuse(`scope agent returned slug "${slug}", which is not lowercase letters, digits, and hyphens of at most 40 characters`, 'scope, stage 2', { brief })
}
const branch = `plan/${slug}`
const planPath = `plans/active/${slug}.md`
log(`cycle-plan: scope ok, slug ${slug}: ${brief.files.length} file(s), ${brief.debt_paid.length} debt paid, ${brief.debt_tripped.length} debt tripped, ${brief.specs_altered.length} spec(s) altered, ${brief.out_of_scope.length} out of scope`)

// ---------------------------------------------------------------------------
// Stage 3: setup. From the main checkout, cut the branch and worktree from
// origin/main and build the worktree's own venv.
// ---------------------------------------------------------------------------

phase('Setup')

const SETUP_SCHEMA = {
  type: 'object',
  required: ['worktree', 'branch', 'venv_seconds', 'import_path', 'ok', 'detail'],
  properties: {
    worktree: { type: 'string' },
    branch: { type: 'string' },
    venv_seconds: { type: 'integer' },
    import_path: { type: 'string' },
    ok: { type: 'boolean' },
    detail: { type: 'string' },
  },
}

const expectedWorktree = `${main}/.claude/worktrees/${slug}`

const setupPrompt =
  `Work only in the git checkout at ${main} and in the worktree you create beneath it at ${expectedWorktree}. Every shell command you run starts with \`cd ${main} &&\` or, once it exists, \`cd ${expectedWorktree} &&\`; you may not touch any other directory.\n` +
  'Report only what you observed. Never state a result for a command you did not run.\n' +
  '\n' +
  `You set up the branch, worktree, and Python environment for a new plan named ${slug}. Run the four steps below in order and stop at the first failure: report it, do not clean up, do not retry, do not try another name.\n` +
  '\n' +
  `1. From ${main}: \`git worktree add -b ${branch} .claude/worktrees/${slug} origin/main; echo "exit=$?"\` must print \`exit=0\`. (\`.claude/worktrees/\` is gitignored and \`.claude/skills\` is a committed symlink, so nothing else needs creating.)\n` +
  `2. \`cd ${expectedWorktree} && pwd -P\` prints the worktree's resolved path; return it as \`worktree\`. In the worktree, \`git rev-parse --abbrev-ref HEAD\` must print \`${branch}\`; return it as \`branch\`.\n` +
  '3. In the worktree: `t0=$(date +%s); python3.10 -m venv venv && venv/bin/pip install -q -e ".[dev]"; echo "exit=$?"; t1=$(date +%s); echo "seconds=$((t1-t0))"` must print `exit=0`. Give this one Bash call a timeout of at least 600000 milliseconds: it took 18 seconds with a warm pip cache and may take several minutes cold. Return the seconds as `venv_seconds` (an integer).\n' +
  "4. In the worktree: `venv/bin/python -c 'import docket; print(docket.__file__)'` must print a path beginning with the `worktree` path from step 2 (the editable install pins `docket` to the checkout it was installed from; a path elsewhere means the wrong venv). Return the printed path as `import_path`.\n" +
  '\n' +
  `\`ok\` is true only when all four steps held. \`detail\` holds one line per step with what it printed; on a failure its first line names the step that failed and what now exists on disk (the branch \`${branch}\`, the directory \`.claude/worktrees/${slug}\`, its \`venv/\`), so the operator can remove them.\n`

const setup = await agent(setupPrompt, { effort: 'low', label: 'setup', schema: SETUP_SCHEMA })
const cleanup = `from ${main}: git worktree remove --force .claude/worktrees/${slug}; git branch -D ${branch}`
if (!setup) return noResult('setup', 'setup, stage 3', { branch, worktree: expectedWorktree, cleanup })
if (!setup.ok) {
  return refuse(`setup failed: ${setup.detail}`, 'setup, stage 3', { branch, worktree: setup.worktree || expectedWorktree, cleanup })
}
const worktree = setup.worktree
log(`cycle-plan: setup ok, worktree ${worktree} on ${setup.branch}, venv built in ${setup.venv_seconds}s`)

// ---------------------------------------------------------------------------
// Stage 4: plan-author. A fresh agent in the new worktree follows
// skills/plan-author/SKILL.md and commits the plan alone.
// ---------------------------------------------------------------------------

phase('Author')

const AUTHOR_SCHEMA = {
  type: 'object',
  required: ['plan_path', 'milestone_count', 'first_milestone', 'first_acceptance', 'left_out'],
  properties: {
    plan_path: { type: 'string' },
    milestone_count: { type: 'integer' },
    first_milestone: { type: 'string' },
    first_acceptance: { type: 'string' },
    left_out: { type: 'string' },
  },
}

const authorPrompt =
  confine('worktree', worktree) +
  '\n' +
  `You author a new ExecPlan for the docket-pub repository on the branch ${branch} in this worktree, which was just cut from origin/main and has its own venv. The procedure is skills/plan-author/SKILL.md; read it first and follow it, including everything it tells you to read (plans/PLANS.md in full, GOALS.md, ARCHITECTURE.md, docs/PRINCIPLES.md, docs/capabilities/index.md, docs/DEBT.md, the files under docs/specs/ the work touches, plans/active/ for work in flight) and every file the brief below names.\n` +
  '\n' +
  'The goal, as the operator stated it:\n' +
  '\n' +
  `${goalText}\n` +
  '\n' +
  'The scope brief, written by a read-only agent that studied this repository for the goal (JSON):\n' +
  '\n' +
  `${JSON.stringify(brief, null, 2)}\n` +
  '\n' +
  "Fold the brief into the plan's Purpose / Big Picture and Context and Orientation sections as prose; the brief is not committed as its own file. Treat its `questions` as settled (it is empty, or the operator's answers are in the goal text above). Its `out_of_scope` items are what the plan deliberately leaves out; say so in the plan's revision note. Its `debt_paid`, `debt_tripped`, and `specs_altered` items name the rows of docs/DEBT.md and the files under docs/specs/ the plan must account for.\n" +
  '\n' +
  'Rules the mechanical judge enforces on the file (tools/judge-milestone, contract docs/capabilities/judge-milestone.md), beyond what plans/PLANS.md asks: the plan has a `## Progress` section whose milestone lines each begin `- [ ] ` and none is ticked here; the sections `## Surprises & Discoveries`, `## Decision Log`, and `## Outcomes & Retrospective` each exist with at least one sentence under them (the authoring decisions belong in the Decision Log now; the other two can say that nothing has been executed yet), because a missing or empty one fails the snapshot the next stage takes. A milestone session later ticks a Progress line by changing `- [ ]` to `- [x] (YYYY-MM-DD HH:MMZ)` and changing nothing else on that line, so write each line as text that can stand unchanged for the life of the plan. Every milestone session starts and ends with `./tools/verify` (about 150 seconds), so state each milestone\'s acceptance as commands run in this worktree and what they print.\n' +
  '\n' +
  `Write the plan to ${planPath}. Commit it alone, with no other file in the commit, with the exact message \`plan: ${slug}, authored\`. Never disable or bypass git hooks. Leave the tree clean. Do not start any of the work the plan describes.\n` +
  '\n' +
  `Return \`plan_path\` (\`${planPath}\`), \`milestone_count\`, \`first_milestone\` (the text of the first Progress line), \`first_acceptance\` (that milestone's acceptance in one or two sentences), and \`left_out\` (what you deliberately left out of the plan, in one paragraph).\n`

const authored = await agent(authorPrompt, { label: 'plan-author', stallMs: 1800000, schema: AUTHOR_SCHEMA })
if (!authored) return noResult('plan-author', 'plan-author, stage 4', { branch, worktree, cleanup })
log(`cycle-plan: plan authored at ${authored.plan_path}, ${authored.milestone_count} milestone(s); first: ${authored.first_milestone.slice(0, 120)}`)

// ---------------------------------------------------------------------------
// Stage 5: check. From the launching checkout, the judge's snapshot accepts
// the new plan, the worktree is clean, and the branch is one commit over
// origin/main.
// ---------------------------------------------------------------------------

const CHECK_SCHEMA = {
  type: 'object',
  required: ['ok', 'detail', 'open_count'],
  properties: {
    ok: { type: 'boolean' },
    detail: { type: 'string' },
    open_count: { type: 'integer' },
  },
}

const checkPrompt =
  confine('checkout', checkout) +
  '\n' +
  `You check the plan a plan-author agent just committed in the worktree ${worktree} (branch ${branch}), working from this checkout. Run the three commands below in order and report exactly what each printed; edit nothing, commit nothing.\n` +
  '\n' +
  `1. \`tools/judge-milestone snapshot ${worktree}/${planPath}; echo "exit=$?"\` must print \`exit=0\`, at least one line beginning \`OPEN\`, and no line beginning \`DONE\`, \`NOSTAMP\`, \`MISSING\`, or \`EMPTY\`. Return the number of lines beginning \`OPEN\` as \`open_count\` (0 when the command failed).\n` +
  `2. \`git -C ${worktree} status --porcelain\` must print nothing.\n` +
  `3. \`git -C ${worktree} log --oneline origin/main..HEAD\` must print exactly one line.\n` +
  '\n' +
  "`ok` is true only when all three held. `detail` holds one line per command with what it printed (for the snapshot: its exit status, the counts of each record kind, and any `judge: defect` line; for the status: `clean` or the lines; for the log: the line or the count of lines), with any miss listed first and marked `MISS`.\n"

const checked = await agent(checkPrompt, { effort: 'low', label: 'check', schema: CHECK_SCHEMA })
if (!checked) return noResult('check', 'check, stage 5', { branch, worktree, plan_path: authored.plan_path, cleanup })
if (!checked.ok) {
  log(`cycle-plan: the plan is committed in ${worktree} but failed the check; fix it there, commit, and read it before running /cycle-run`)
  return refuse(`check failed: ${checked.detail}`, 'check, stage 5', { branch, worktree, plan_path: authored.plan_path, cleanup })
}
log(`cycle-plan: check ok, ${checked.open_count} open milestone(s), clean tree, one commit over origin/main`)

const next = `Read the plan. Record any change you want as a dated Decision Log entry naming yourself as author, commit it in the worktree, then start a new Claude Code session in ${worktree} and run /cycle-run ${planPath}`
log(`cycle-plan: planned; ${planPath} on ${branch} in ${worktree}`)
return {
  status: 'planned',
  branch,
  worktree,
  plan_path: authored.plan_path,
  milestone_count: authored.milestone_count,
  first_milestone: authored.first_milestone,
  first_acceptance: authored.first_acceptance,
  left_out: authored.left_out,
  venv_seconds: setup.venv_seconds,
  next,
}
