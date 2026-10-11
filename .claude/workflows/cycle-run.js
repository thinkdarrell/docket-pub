export const meta = {
  name: 'cycle-run',
  description: 'Execute an ExecPlan milestone by milestone with a fresh agent per milestone, judged from git, then close it to a pull request',
  whenToUse: 'From a Claude Code session started in the plan worktree: /cycle-run plans/active/<slug>.md, optionally with a limit on milestones for this run',
  phases: [{ title: 'Preflight' }, { title: 'Milestones' }, { title: 'Closing' }],
}

// cycle-run: the factory's milestone loop. The contract is
// plans/active/factory-workflows.md (Plan of Work, M1 and M2); the judge it
// relies on is tools/judge-milestone, whose card is
// docs/capabilities/judge-milestone.md. The script has no clock, shell, or
// filesystem: every fact comes back from an agent, and every agent is told to
// report only what it observed.

// ---------------------------------------------------------------------------
// Arguments. `args` may be the plan path as a string, an array whose first
// element is the plan path (second, optionally, the limit), or an object with
// `plan` and optional `limit`.
// ---------------------------------------------------------------------------

let rawPlan
let rawLimit
if (typeof args === 'string') {
  rawPlan = args
} else if (Array.isArray(args)) {
  rawPlan = args[0]
  rawLimit = args[1]
} else if (args && typeof args === 'object') {
  rawPlan = args.plan
  rawLimit = args.limit
}

const plan = typeof rawPlan === 'string' ? rawPlan.trim().replace(/^\.\//, '') : ''
const parsedLimit = typeof rawLimit === 'string' ? Number(rawLimit.trim()) : rawLimit
const limit = Number.isInteger(parsedLimit) && parsedLimit > 0 ? parsedLimit : Infinity

if (!plan) {
  log('cycle-run: refused: no plan path given; run /cycle-run plans/active/<slug>.md')
  return { status: 'refused', plan, reason: 'no plan path given' }
}
if (!/^plans\/active\/[^/]+\.md$/.test(plan)) {
  log(`cycle-run: refused: ${plan} is not a plan under plans/active/`)
  return { status: 'refused', plan, reason: `${plan} is not a plan under plans/active/` }
}

const slug = plan.slice('plans/active/'.length, -'.md'.length)
const branch = `plan/${slug}`
const HARD_CAP = 20

// ---------------------------------------------------------------------------
// Helpers.
// ---------------------------------------------------------------------------

// The two lines every agent prompt begins with, once the worktree is known.
function common(worktree) {
  return (
    `Work only in the git worktree at ${worktree}. Every shell command you run starts with \`cd ${worktree} &&\`; you may not touch any other directory.\n` +
    'Report only what you observed. Never state a result for a command you did not run.\n'
  )
}

// Seconds since the Unix epoch, as observed by an agent, rendered as
// YYYY-MM-DDTHH:MM:SSZ with integer arithmetic (the runtime has no clock, and
// the only clock this script trusts is one an agent read with `date`).
function isoFromEpoch(epoch) {
  const secs = Number(epoch)
  if (!Number.isFinite(secs)) return ''
  let days = Math.floor(secs / 86400)
  let rem = secs - days * 86400
  const hh = Math.floor(rem / 3600)
  rem -= hh * 3600
  const mm = Math.floor(rem / 60)
  const ss = rem - mm * 60
  // Civil-from-days (Howard Hinnant's algorithm), proleptic Gregorian.
  days += 719468
  const era = Math.floor(days / 146097)
  const doe = days - era * 146097
  const yoe = Math.floor((doe - Math.floor(doe / 1460) + Math.floor(doe / 36524) - Math.floor(doe / 146096)) / 365)
  const y = yoe + era * 400
  const doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100))
  const mp = Math.floor((5 * doy + 2) / 153)
  const d = doy - Math.floor((153 * mp + 2) / 5) + 1
  const m = mp < 10 ? mp + 3 : mp - 9
  const year = m <= 2 ? y + 1 : y
  const pad = (n) => String(n).padStart(2, '0')
  return `${year}-${pad(m)}-${pad(d)}T${pad(hh)}:${pad(mm)}:${pad(ss)}Z`
}

// The run's record of landed milestones: { entry, start, end, seconds, verify_last_line }.
const milestones = []

// A halt is a returned object, never a thrown error, so the run's result is
// readable. The caller writes `return halt(...)` at the top level.
function halt(rule, where, milestone) {
  log(`cycle-run: halt ${plan}`)
  log(`cycle-run: milestone ${milestone}`)
  log(`cycle-run: ${rule}`)
  log('cycle-run: fix the cause in the worktree, commit, and re-run /cycle-run with the same arguments')
  return { status: 'halt', plan, milestone, rule, where, milestones }
}

// ---------------------------------------------------------------------------
// Preflight. One cheap agent runs ten checks from the current directory and
// returns every result, passing or not. The worktree path it observes is the
// value every later prompt substitutes.
// ---------------------------------------------------------------------------

phase('Preflight')

const PREFLIGHT_SCHEMA = {
  type: 'object',
  required: ['worktree', 'started_at', 'checks'],
  properties: {
    worktree: { type: 'string' },
    started_at: { type: 'string' },
    checks: {
      type: 'array',
      items: {
        type: 'object',
        required: ['name', 'ok', 'detail'],
        properties: { name: { type: 'string' }, ok: { type: 'boolean' }, detail: { type: 'string' } },
      },
    },
  },
}

const preflightPrompt =
  'Work only in the git worktree that is your current working directory; print it with `pwd -P` first and use that path as <worktree> below. Every shell command you run starts with `cd <worktree> &&`; you may not touch any other directory.\n' +
  'Report only what you observed. Never state a result for a command you did not run.\n' +
  '\n' +
  `You are the preflight check for a factory run of the plan ${plan} (branch ${branch}). Run the ten checks below, in order, each from the worktree. Run every check even after one fails; do not fix anything. Return one record per check with the names given here, \`ok\` true only when the check's condition holds exactly, and \`detail\` holding what the command printed (trimmed, first line or the line named).\n` +
  '\n' +
  '1. `worktree`: `pwd -P` prints a path containing `/.claude/worktrees/`, and `git rev-parse --git-common-dir` prints an absolute path (a linked worktree; in a main checkout it prints `.git`, which fails this check). Detail: both outputs.\n' +
  `2. \`branch\`: \`git rev-parse --abbrev-ref HEAD\` prints exactly \`${branch}\`.\n` +
  `3. \`plan-file\`: \`test -f ${plan}; echo "exit=$?"\` prints \`exit=0\`.\n` +
  '4. `clean-tree`: `git status --porcelain` prints nothing.\n' +
  '5. `origin`: `git remote get-url origin` prints a URL ending in `thinkdarrell/docket-pub.git` or `thinkdarrell/docket-pub`.\n' +
  '6. `ls-remote`: `GIT_TERMINAL_PROMPT=0 git ls-remote origin HEAD; echo "exit=$?"` prints `exit=0`.\n' +
  '7. `gh-user`: `gh api user --jq .login` prints `thinkdarrell`.\n' +
  "8. `venv-import`: `venv/bin/python -c 'import docket; print(docket.__file__)'` prints a path beginning with the worktree path from check 1.\n" +
  '9. `verify`: `t0=$(date +%s); ./tools/verify > "${TMPDIR:-/tmp}/cycle-run-preflight-verify.log" 2>&1; echo "exit=$?"; t1=$(date +%s); echo "seconds=$((t1-t0))"; tail -1 "${TMPDIR:-/tmp}/cycle-run-preflight-verify.log"` prints `exit=0`. Give this one Bash call a timeout of at least 300000 milliseconds; it takes about 150 seconds. Detail: the last line of the log followed by `; <seconds>s`. If it fails, also include the `verify: ... FAILED` summary lines from the log.\n' +
  `10. \`snapshot\`: \`tools/judge-milestone snapshot ${plan}; echo "exit=$?"\` prints \`exit=0\`. Detail: \`open=<count of lines beginning OPEN> done=<count of lines beginning DONE>\`, then any \`judge: defect\` line.\n` +
  '\n' +
  'Also run `date -u +%Y-%m-%dT%H:%M:%SZ` once at the start and return it as `started_at`. Return `worktree` as the exact `pwd -P` output.\n'

const pre = await agent(preflightPrompt, { effort: 'low', label: 'preflight', schema: PREFLIGHT_SCHEMA })
if (!pre) return halt('agent preflight returned no result', 'preflight', 'none')

const failing = pre.checks.find((c) => !c.ok)
if (failing) {
  return halt(`preflight check ${failing.name} failed: ${failing.detail}`, 'preflight', 'none')
}
const worktree = pre.worktree
const startedAt = pre.started_at
const verifyCheck = pre.checks.find((c) => c.name === 'verify')
log(`cycle-run: preflight ok, verify ${verifyCheck ? verifyCheck.detail : '(no verify record)'}`)

// ---------------------------------------------------------------------------
// The milestone loop. Each iteration: snapshot the plan (step 1), run one
// fresh milestone session (step 2), judge it from git and verify (step 3).
// ---------------------------------------------------------------------------

phase('Milestones')

const SNAPSHOT_SCHEMA = {
  type: 'object',
  required: ['clean', 'head', 'epoch', 'snapshot_exit', 'snapshot_path', 'open_entries', 'done_count', 'defect'],
  properties: {
    clean: { type: 'boolean' },
    head: { type: 'string' },
    epoch: { type: 'integer' },
    snapshot_exit: { type: 'integer' },
    snapshot_path: { type: 'string' },
    open_entries: { type: 'array', items: { type: 'string' } },
    done_count: { type: 'integer' },
    defect: { type: 'string' },
  },
}

const REPORT_SCHEMA = { type: 'object', required: ['report'], properties: { report: { type: 'string' } } }

const JUDGE_SCHEMA = {
  type: 'object',
  required: ['judge_exit', 'judge_output', 'verify_exit', 'verify_last_line', 'verify_seconds', 'head', 'epoch'],
  properties: {
    judge_exit: { type: 'integer' },
    judge_output: { type: 'string' },
    verify_exit: { type: 'integer' },
    verify_last_line: { type: 'string' },
    verify_seconds: { type: 'integer' },
    head: { type: 'string' },
    epoch: { type: 'integer' },
  },
}

function snapshotPrompt() {
  return (
    common(worktree) +
    '\n' +
    `You take the judge's snapshot of the plan ${plan} before a milestone session starts. Run, in this order, and report exactly what each printed:\n` +
    '\n' +
    '1. `git status --porcelain` — `clean` is true only if it prints nothing.\n' +
    '2. `git rev-parse HEAD` — return as `head`.\n' +
    '3. `date +%s` — return as `epoch` (an integer).\n' +
    `4. \`head=$(git rev-parse HEAD); f="\${TMPDIR:-/tmp}/cycle-run-${slug}-$head.snapshot"; tools/judge-milestone snapshot ${plan} > "$f"; echo "exit=$?"; echo "path=$f"; cat "$f"\` — return the exit status as \`snapshot_exit\`, the printed path (TMPDIR expanded, as echoed) as \`snapshot_path\`, and from the file's contents: \`open_entries\`, the third tab-separated field (the shortened text) of every line beginning \`OPEN\`, in file order; \`done_count\`, the number of lines beginning \`DONE\`. If the exit status is 2, \`defect\` is the \`judge: defect ...\` line it printed on stderr; otherwise \`defect\` is an empty string.\n` +
    '\n' +
    'Do not edit anything. Do not run the judge itself.\n'
  )
}

function milestonePrompt(range) {
  return (
    common(worktree) +
    '\n' +
    'You are working in a git repository whose agent harness is already\n' +
    `installed, and which has a plan in flight at ${plan}. Nothing outside\n` +
    'this repository is available to you, and you must not go looking for it.\n' +
    '\n' +
    'Task: execute the first unfinished milestone of that plan, following the\n' +
    "repository's own execution procedure, and then stop.\n" +
    '\n' +
    'The procedure is skills/plan-execute/SKILL.md; read it first, then AGENTS.md, then plans/PLANS.md, then the plan.\n' +
    `The worktree is ${worktree}. The plan is ${plan}. The previous milestone landed in commits ${range}.\n` +
    'Every commit you make changes the plan file by more than whitespace (AGENTS.md Working rules, decision 0037). Tick a Progress line by changing `- [ ]` to `- [x] (YYYY-MM-DD HH:MMZ)` and change nothing else on that line; evidence goes in the other living sections. Never disable or bypass git hooks.\n' +
    'When you are done, return a short report: the milestone executed, what you observed, any carve-out against its acceptance, and which milestone is next.\n'
  )
}

function judgePrompt(snap) {
  return (
    common(worktree) +
    '\n' +
    `You judge the milestone session that just ran on the plan ${plan}. Run, in this order, recording each command's exit status and output exactly:\n` +
    '\n' +
    `1. \`tools/judge-milestone judge ${plan} ${snap.snapshot_path} ${snap.head} 2>&1; echo "exit=$?"\` — return the exit status as \`judge_exit\` and everything it printed (stdout and stderr, all lines) as \`judge_output\`.\n` +
    '2. `t0=$(date +%s); ./tools/verify > "${TMPDIR:-/tmp}/cycle-run-judge-verify.log" 2>&1; echo "exit=$?"; t1=$(date +%s); echo "seconds=$((t1-t0))"; tail -1 "${TMPDIR:-/tmp}/cycle-run-judge-verify.log"` — give this one Bash call a timeout of at least 300000 milliseconds; it takes about 150 seconds. Return the exit status as `verify_exit`, the last line of the log as `verify_last_line`, and the seconds as `verify_seconds`. If it fails, append the `verify: ... FAILED` summary lines from the log to `verify_last_line` after a semicolon.\n' +
    '3. `git rev-parse HEAD` — return as `head`.\n' +
    '4. `date +%s` — return as `epoch` (an integer).\n' +
    '\n' +
    'Do not edit anything, do not commit, and do not try to fix a failure; report it.\n'
  )
}

let previousRange = 'none; this is the first milestone of this run'
let lastEpoch = null
let iteration = 0
let allDone = false

while (milestones.length < limit && iteration < HARD_CAP) {
  iteration += 1

  // Step 1: snapshot.
  const snap = await agent(snapshotPrompt(), { effort: 'low', label: `snapshot ${iteration}`, schema: SNAPSHOT_SCHEMA })
  if (!snap) return halt(`agent snapshot ${iteration} returned no result`, `snapshot ${iteration}, step 1 snapshot`, 'none')
  lastEpoch = snap.epoch
  const firstOpen = snap.open_entries.length ? snap.open_entries[0] : 'none'
  if (!snap.clean) {
    return halt('worktree has uncommitted changes from a previous session', `snapshot ${iteration}, step 1 snapshot`, firstOpen)
  }
  if (snap.snapshot_exit === 2) {
    return halt(snap.defect || 'tools/judge-milestone snapshot exited 2 without a defect line', `snapshot ${iteration}, step 1 snapshot`, firstOpen)
  }
  if (snap.snapshot_exit !== 0) {
    return halt(`tools/judge-milestone snapshot exited ${snap.snapshot_exit}`, `snapshot ${iteration}, step 1 snapshot`, firstOpen)
  }
  if (snap.open_entries.length === 0) {
    allDone = true
    log(`cycle-run: no open milestones in ${plan} (${snap.done_count} done)`)
    break
  }
  const entry = snap.open_entries[0]
  log(`cycle-run: milestone ${iteration}: "${entry}" from ${snap.head.slice(0, 7)} (${snap.open_entries.length} open, ${snap.done_count} done)`)

  // Step 2: the milestone session.
  const session = await agent(milestonePrompt(previousRange), {
    label: `milestone: ${entry.slice(0, 60)}`,
    stallMs: 1800000,
    schema: REPORT_SCHEMA,
  })
  if (!session) return halt(`agent milestone returned no result`, `milestone ${iteration}, step 2 milestone session`, entry)
  log(`cycle-run: session report: ${session.report.split('\n')[0].slice(0, 200)}`)

  // Step 3: judge, then verify.
  const judged = await agent(judgePrompt(snap), { effort: 'low', label: `judge ${iteration}`, schema: JUDGE_SCHEMA })
  if (!judged) return halt(`agent judge ${iteration} returned no result`, `judge ${iteration}, step 3 judge`, entry)
  lastEpoch = judged.epoch
  if (judged.judge_exit !== 0) {
    return halt(judged.judge_output.trim(), `judge ${iteration}, step 3 judge`, entry)
  }
  if (judged.verify_exit !== 0) {
    return halt(`./tools/verify failed at ${judged.head}: ${judged.verify_last_line}`, `judge ${iteration}, step 3 verify`, entry)
  }

  const seconds = judged.epoch - snap.epoch
  milestones.push({ entry, start: snap.head, end: judged.head, seconds, verify_last_line: judged.verify_last_line })
  log(`cycle-run: advanced "${entry}" in ${seconds}s, verify ${judged.verify_last_line}`)
  previousRange = `${snap.head}..${judged.head}`
}

if (!allDone && iteration >= HARD_CAP && milestones.length < limit) {
  log(`cycle-run: stopped at the hard cap of ${HARD_CAP} milestones in one run; re-run /cycle-run to continue`)
}

const finishedAt = isoFromEpoch(lastEpoch)

if (!allDone) {
  log(`cycle-run: advanced ${milestones.length} milestone(s) of ${plan}; the plan still has open milestones`)
  return { status: 'advanced', plan, milestones, started_at: startedAt, finished_at: finishedAt }
}

// ---------------------------------------------------------------------------
// Closing. The plan has no open milestones. Seven stages, each one agent (the
// review panel is three agents at once): measure the range against
// origin/main, review it through three lenses, write the findings into the
// plan, run the retro and the gardening pass, verify once more, push, and
// open the pull request. Contract: plans/active/factory-workflows.md, Plan of
// Work, M2. Every stage logs one line; a null result from any agent halts.
// ---------------------------------------------------------------------------

phase('Closing')

// A closing agent that returned nothing (died or was stopped) halts with the
// same rule the milestone loop uses; `milestone` is 'none' because none is open.
function closingNull(label, stage) {
  return halt(`agent ${label} returned no result`, `${label}, closing stage ${stage}`, 'none')
}

// The last milestone this run landed, or null when every milestone was already
// done before this run started (the record agent then reads it from the plan).
const lastLanded = milestones.length ? milestones[milestones.length - 1].entry : null

// Stage 1: diffstat. The review range is merge-base(origin/main, HEAD)..HEAD.
const DIFFSTAT_SCHEMA = {
  type: 'object',
  required: ['fetch_exit', 'base', 'head', 'diffstat', 'commits'],
  properties: {
    fetch_exit: { type: 'integer' },
    base: { type: 'string' },
    head: { type: 'string' },
    diffstat: { type: 'string' },
    commits: { type: 'array', items: { type: 'string' } },
  },
}

const diffstatPrompt =
  common(worktree) +
  '\n' +
  `The plan ${plan} has no open milestones. You measure the range the review panel will read. Run, in this order, and report exactly what each printed:\n` +
  '\n' +
  '1. `GIT_TERMINAL_PROMPT=0 git fetch -q origin 2>&1; echo "exit=$?"` — return the exit status as `fetch_exit`. Run the rest even if it is not 0.\n' +
  '2. `base=$(git merge-base origin/main HEAD); echo "$base"` — return the printed sha as `base`.\n' +
  '3. `git rev-parse HEAD` — return as `head`.\n' +
  '4. `git diff --stat "$base..HEAD" | tail -1` — return the line, trimmed, as `diffstat`.\n' +
  '5. `git log --reverse --format=%h "$base..HEAD"` — return the lines, in order, as `commits`.\n' +
  '\n' +
  'Do not edit anything, do not commit.\n'

const diff = await agent(diffstatPrompt, { effort: 'low', label: 'diffstat', schema: DIFFSTAT_SCHEMA })
if (!diff) return closingNull('diffstat', '1 diffstat')
if (diff.fetch_exit !== 0) {
  return halt(`git fetch origin exited ${diff.fetch_exit}; the review range cannot be measured against a current origin/main`, 'diffstat, closing stage 1 diffstat', 'none')
}
const range = `${diff.base}..${diff.head}`
log(`cycle-run: review range ${range}, ${diff.diffstat} (${diff.commits.length} commits)`)

// Stage 2: three reviewers at once. A barrier is right here: the record agent
// deduplicates across all three reports, so nothing downstream can start on one.
const REVIEW_SCHEMA = {
  type: 'object',
  required: ['lens', 'findings', 'declined'],
  properties: {
    lens: { type: 'string' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['severity', 'title', 'location', 'claim', 'evidence', 'refutation'],
        properties: {
          severity: { type: 'string', enum: ['severe', 'important', 'minor'] },
          title: { type: 'string' },
          location: { type: 'string' },
          claim: { type: 'string' },
          evidence: { type: 'string' },
          refutation: { type: 'string' },
        },
      },
    },
    declined: { type: 'array', items: { type: 'string' } },
  },
}

const LENSES = [
  {
    name: 'correctness',
    paragraph:
      'Your lens is correctness: does the code do what its surrounding code and tests assume; off-by-one, wrong exit status, unhandled failure, a test that cannot fail, a shell quoting or locale trap.',
  },
  {
    name: 'scope',
    paragraph:
      "Your lens is scope: compare the diff with the plan's milestone acceptance (Validation and Acceptance) and Decision Log; name work the plan did not ask for, acceptance the plan asked for and the diff does not meet, and evidence in the plan that the commits do not support.",
  },
  {
    name: 'data-honesty',
    paragraph:
      'Your lens is data honesty: every new data point a reader could see links back to a source; OCR-derived and minutes-derived facts stay distinguished; no code path silently drops rows or swallows an exception without logging it; nothing is hidden from a reader. Where the diff touches no reader-facing data, say so and check the same properties of whatever the diff does produce (run output, log lines, halt messages, records written into documents).',
  },
]

function reviewPrompt(lens) {
  return (
    common(worktree) +
    '\n' +
    `You are one of three independent reviewers of the plan ${plan}, whose milestones are all done. The other two read the same range through other lenses; you do not see their reports. You are read-only: do not edit, create, or commit anything, and do not spawn subagents (no Agent tool, no tool that starts another agent).\n` +
    '\n' +
    `${lens.paragraph}\n` +
    '\n' +
    `The range is ${range} (${diff.commits.length} commits: ${diff.commits.join(', ')}). Read the plan first: its Progress, Decision Log, Validation and Acceptance, and Artifacts and Notes. Then list the changed files with \`git diff --stat ${range}\` and the commits with \`git log --reverse --format='%h %s' ${range}\`, and read the diff one file at a time with \`git diff ${range} -- <file>\` and, for one commit, \`git show <sha> -- <file>\`. Never run \`git diff ${range}\` without a path: the whole diff at once would fill your context.\n` +
    '\n' +
    'Before keeping any candidate finding, try to refute it: re-read the surrounding code, run the command or test that would show it wrong, check whether the plan already records it as a decision. If the refutation succeeds, put the candidate in `declined` as one sentence with the reason. If it fails, keep the finding, with `refutation` saying what you tried and why it did not hold. `evidence` is a command you ran and what it printed. `location` is a repository-relative path with a line number, or a commit sha.\n' +
    '\n' +
    'Severity: `severe` means a reader of the site, the operator, or the next session is misled or blocked if this ships; `important` means wrong but contained; `minor` is everything else. A finding with no evidence you observed is not a finding.\n' +
    '\n' +
    `Return \`lens\` as \`${lens.name}\`, \`findings\` (possibly empty), and \`declined\` (possibly empty).\n`
  )
}

const reviews = await parallel(
  LENSES.map((lens) => () => agent(reviewPrompt(lens), { label: `review: ${lens.name}`, phase: 'Closing', schema: REVIEW_SCHEMA })),
)
for (let i = 0; i < LENSES.length; i += 1) {
  if (!reviews[i]) return closingNull(`review: ${LENSES[i].name}`, '2 review panel')
}
const rawCount = (severity) => reviews.reduce((n, r) => n + r.findings.filter((f) => f.severity === severity).length, 0)
log(`cycle-run: review panel reported ${rawCount('severe')} severe, ${rawCount('important')} important, ${rawCount('minor')} minor before deduplication`)

// Stage 3: the record. One agent reads all three reports, removes duplicates,
// appends the record to the plan's Decision Log, and commits that edit alone.
const RECORD_SCHEMA = {
  type: 'object',
  required: ['severe', 'important', 'minor', 'commit'],
  properties: {
    severe: { type: 'integer' },
    important: { type: 'integer' },
    minor: { type: 'integer' },
    commit: { type: 'string' },
  },
}

function recordPrompt() {
  const afterClause = lastLanded
    ? `After ${lastLanded}`
    : 'After <the text of the last `- [x]` line in the plan\'s Progress section, without its checkbox and date>'
  return (
    common(worktree) +
    '\n' +
    `You write the review record into the plan ${plan}. Three reviewers (lenses: correctness, scope, data honesty) have read the range ${range}; their reports follow as JSON. Do not re-review the code and do not judge the findings; your job is to record them faithfully.\n` +
    '\n' +
    'First remove duplicates: two findings with the same `location` and the same `claim` (the same defect, even if worded differently) are one finding; keep the higher severity and the fuller evidence, and name both lenses in its title. Count the findings that remain by severity.\n' +
    '\n' +
    `Then append one entry to the end of the plan's \`## Decision Log\` section (after its last entry, before the next \`## \` heading), in the shape the section's existing entries use: a line beginning \`- Decision: \`, continuation lines indented two spaces, then \`  Rationale: \` and \`  Date/Author: \` lines. The entry's text is:\n` +
    '\n' +
    `    - Decision: review record. ${afterClause}, three fresh reviewers (correctness, scope against the plan, data honesty) read the range ${range}, each told to refute. Counts: <n> severe, <n> important, <n> minor.\n` +
    '      <severity>: <title> (<location>): <claim>; evidence: <evidence>.\n' +
    '      (one such line per finding that remains, severe first; if none remain, one line `  No findings kept.`)\n' +
    '      Declined: <each declined item from every report, separated by `; `> (or `Declined: none.`)\n' +
    "      Rationale: the design's closing sequence writes the panel's findings into the plan so they are read with it, and halts before the pull request when a finding is severe.\n" +
    '      Date/Author: <today as YYYY-MM-DD from `date -u +%Y-%m-%d`>, review panel (cycle-run), from the three panel reports.\n' +
    '\n' +
    'Keep every finding on one line; replace line breaks inside a field with spaces. Change nothing else in the plan or in any other file.\n' +
    '\n' +
    `Commit that edit alone: \`git add ${plan} && git commit -m "plan: ${slug}, review record"\`. Then \`git status --porcelain\` must print nothing and \`git rev-parse HEAD\` is the \`commit\` you return. Return \`severe\`, \`important\`, \`minor\` as the counts after deduplication.\n` +
    '\n' +
    'The three reports:\n' +
    '\n' +
    JSON.stringify(reviews, null, 2) +
    '\n'
  )
}

const record = await agent(recordPrompt(), { label: 'review record', schema: RECORD_SCHEMA })
if (!record) return closingNull('review record', '3 review record')
log(`cycle-run: review record committed as ${record.commit.slice(0, 7)}: ${record.severe} severe, ${record.important} important, ${record.minor} minor`)
if (record.severe > 0) {
  return halt(`review found ${record.severe} severe finding(s); see the review record in ${plan}`, 'review record, closing stage 3 review record', 'none')
}
const review = { severe: record.severe, important: record.important, minor: record.minor }

// Stage 4: the retro. It follows skills/retro/SKILL.md and the lifecycle in
// plans/PLANS.md, so the plan moves to plans/completed/ here.
const RETRO_SCHEMA = {
  type: 'object',
  required: ['report', 'plan_path_now'],
  properties: { report: { type: 'string' }, plan_path_now: { type: 'string' } },
}

const retroPrompt =
  common(worktree) +
  '\n' +
  `The plan ${plan} has every milestone done and its review record committed (${record.commit}). Follow skills/retro/SKILL.md on that plan: read that file first, then do what it says, including the lifecycle steps plans/PLANS.md names at completion (the closing Outcomes & Retrospective entry, reflecting durable behaviour into docs/specs/, graduating durable decisions to docs/decisions/, and moving the file to plans/completed/${slug}.md with \`git mv\`).\n` +
  '\n' +
  "Commit as that skill says: each routed edit in its own commit, so a reviewer can accept or reject one lesson without the rest; the plan's closing section and the move in commits of their own. Never rewrite the plan's history or its evidence. Leave the tree clean: `git status --porcelain` must print nothing when you stop.\n" +
  '\n' +
  "Return `report`: the report the skill's stop condition asks for (differences found, lessons routed with owners, lessons discarded with reasons, anything undecided), concise; and `plan_path_now`: the plan's path relative to the worktree after the move, exactly as `git ls-files plans/` prints it.\n"

const retro = await agent(retroPrompt, { label: 'retro', stallMs: 1800000, schema: RETRO_SCHEMA })
if (!retro) return closingNull('retro', '4 retro')
const planNow = retro.plan_path_now
log(`cycle-run: retro done, plan now at ${planNow}: ${retro.report.split('\n')[0].slice(0, 200)}`)

// Stage 5: doc-garden.
const GARDEN_SCHEMA = { type: 'object', required: ['report'], properties: { report: { type: 'string' } } }

const gardenPrompt =
  common(worktree) +
  '\n' +
  `The plan now at ${planNow} has just finished: its retro has run and it has been moved to plans/completed/. Follow skills/doc-garden/SKILL.md: read that file first, then run every sweep it names and give every finding one of its four dispositions. Land each fix as its own commit, as its Disposition section requires. Never rewrite a plan's history. Leave the tree clean: \`git status --porcelain\` must print nothing when you stop.\n` +
  '\n' +
  "Return `report`: what was swept, what each sweep found, which fixes landed, what was deferred or handed off, and which questions were left to a reader.\n"

const garden = await agent(gardenPrompt, { label: 'doc-garden', stallMs: 1800000, schema: GARDEN_SCHEMA })
if (!garden) return closingNull('doc-garden', '5 doc-garden')
log(`cycle-run: doc-garden done: ${garden.report.split('\n')[0].slice(0, 200)}`)

// Stage 6: final verify.
const FINAL_SCHEMA = {
  type: 'object',
  required: ['verify_exit', 'verify_last_line', 'verify_seconds', 'clean', 'status', 'head', 'finished_at'],
  properties: {
    verify_exit: { type: 'integer' },
    verify_last_line: { type: 'string' },
    verify_seconds: { type: 'integer' },
    clean: { type: 'boolean' },
    status: { type: 'string' },
    head: { type: 'string' },
    finished_at: { type: 'string' },
  },
}

const finalPrompt =
  common(worktree) +
  '\n' +
  `You run the final verification before the plan ${planNow} is pushed. Run, in this order, recording each command's exit status and output exactly:\n` +
  '\n' +
  '1. `t0=$(date +%s); ./tools/verify > "${TMPDIR:-/tmp}/cycle-run-final-verify.log" 2>&1; echo "exit=$?"; t1=$(date +%s); echo "seconds=$((t1-t0))"; tail -1 "${TMPDIR:-/tmp}/cycle-run-final-verify.log"` — give this one Bash call a timeout of at least 300000 milliseconds; it takes about 150 seconds. Return the exit status as `verify_exit`, the last line of the log as `verify_last_line`, and the seconds as `verify_seconds`. If it fails, append the `verify: ... FAILED` summary lines from the log to `verify_last_line` after a semicolon.\n' +
  '2. `git status --porcelain` — `clean` is true only if it prints nothing; return what it printed (possibly empty) as `status`.\n' +
  '3. `git rev-parse HEAD` — return as `head`.\n' +
  '4. `date -u +%Y-%m-%dT%H:%M:%SZ` — return as `finished_at`.\n' +
  '\n' +
  'Do not edit anything, do not commit, and do not try to fix a failure; report it.\n'

const fin = await agent(finalPrompt, { effort: 'low', label: 'final verify', schema: FINAL_SCHEMA })
if (!fin) return closingNull('final verify', '6 final verify')
if (fin.verify_exit !== 0) {
  return halt(`./tools/verify failed at ${fin.head}: ${fin.verify_last_line}`, 'final verify, closing stage 6 final verify', 'none')
}
if (!fin.clean) {
  return halt(`worktree has uncommitted changes after the retro and doc-garden passes: ${fin.status.trim().split('\n').join('; ')}`, 'final verify, closing stage 6 final verify', 'none')
}
log(`cycle-run: final verify ok at ${fin.head.slice(0, 7)}, ${fin.verify_last_line} (${fin.verify_seconds}s)`)

// Stage 7: publish. Push the branch and open the pull request; the body is the
// plan's Outcomes & Retrospective section followed by the review record.
const PUBLISH_SCHEMA = {
  type: 'object',
  required: ['pushed', 'pr_url', 'detail', 'finished_at'],
  properties: {
    pushed: { type: 'boolean' },
    pr_url: { type: 'string' },
    detail: { type: 'string' },
    finished_at: { type: 'string' },
  },
}

const publishPrompt =
  common(worktree) +
  '\n' +
  `You publish the finished plan ${planNow}: push the branch ${branch} and open its pull request against main. Do not edit or commit anything in the repository. Run, in this order:\n` +
  '\n' +
  `1. \`GIT_TERMINAL_PROMPT=0 git push -u origin ${branch} 2>&1; echo "exit=$?"\` — \`pushed\` is true only if it prints \`exit=0\`. A credential prompt fails instead of hanging; that is intended. If the push failed, stop here: return \`pushed\` false, \`pr_url\` as an empty string, and \`detail\` holding everything the push printed.\n` +
  `2. The title: the first line of ${planNow} that begins \`# \`, without the \`# \`, cut to its first 70 characters.\n` +
  `3. The body, written to \`body="\${TMPDIR:-/tmp}/cycle-run-${slug}-pr-body.md"\` with sed or awk, never retyped: the plan's \`## Outcomes & Retrospective\` section (from that heading line up to, not including, the next line beginning \`## \`), then a blank line, then the review record (the Decision Log entry beginning \`- Decision: review record.\` through its \`Date/Author:\` line, inclusive), then a blank line, then exactly this line: \`🤖 Generated with [Claude Code](https://claude.com/claude-code)\`. Check the file with \`head -3\` and \`tail -3\` before using it.\n` +
  `4. \`gh pr create --base main --head ${branch} --title "<title>" --body-file "$body" 2>&1; echo "exit=$?"\` — on \`exit=0\` return the URL it printed as \`pr_url\`. If it printed that a pull request for ${branch} already exists, run \`gh pr view ${branch} --json url --jq .url\` and return that URL as \`pr_url\`, saying so in \`detail\`. On any other failure return \`pr_url\` as an empty string. \`detail\` always holds what the commands printed, trimmed.\n` +
  '5. `date -u +%Y-%m-%dT%H:%M:%SZ` — return as `finished_at`.\n'

const pub = await agent(publishPrompt, { effort: 'low', label: 'publish', schema: PUBLISH_SCHEMA })
if (!pub) return closingNull('publish', '7 publish')
if (!pub.pushed) {
  return halt(`git push -u origin ${branch} failed: ${pub.detail.trim().split('\n').join('; ')}`, 'publish, closing stage 7 publish', 'none')
}
if (!pub.pr_url) {
  return halt(`gh pr create failed after the push: ${pub.detail.trim().split('\n').join('; ')}`, 'publish, closing stage 7 publish', 'none')
}
log(`cycle-run: complete; ${plan} closed to ${pub.pr_url}`)

return {
  status: 'complete',
  plan,
  plan_path_now: planNow,
  milestones,
  review,
  pr_url: pub.pr_url,
  started_at: startedAt,
  finished_at: pub.finished_at || fin.finished_at,
}
