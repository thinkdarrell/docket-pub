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

// Closing (phase `Closing`) is added by M2 of plans/active/factory-workflows.md.
log(`cycle-run: ${plan} has no open milestones; closing sequence not yet implemented (M2)`)
return { status: 'complete', plan, milestones, started_at: startedAt, finished_at: finishedAt }
