# 0054 — The pre-commit hook enforces evidence-check only; the every-commit-changes-the-plan rule stays the judge's

## Decision

`tools/hooks/pre-commit` runs `tools/check-plans --staged` and nothing else: it refuses a commit that stages a plan under `plans/active/` missing one of its four living sections or ticking a Progress entry without a date. It does not refuse a commit that leaves the plan untouched, and decision `0037` (every commit a milestone session lands changes the plan) is decided by `tools/judge-milestone` per session, not by the hook per commit.

## Rationale

`0037` binds a milestone session's commits. The closing sequence of `cycle-run` and the retro and doc-garden passes legitimately commit routed lessons, decision records, debt rows, and the review record without touching the plan, and a hook sees one commit with no way to tell a milestone session from a closing stage. A hook that enforced `0037` would therefore refuse every closing commit, or need an escape hatch, and an escape hatch on a hook is a bypass under another name, which is the thing the hook exists to remove. The judge already decides `0037` at the right scope: it reads the whole session's commits against the snapshot, and it is run by `cycle-run` before and after every milestone session.

Evidence-check, by contrast, is well scoped to any commit that stages an active plan: whatever session makes that commit, the plan it stages must carry its sections and its dated ticks, and the moment of staging is the cheapest moment to fix it. The hook is also skippable in a clone where `core.hooksPath` is not set, which is why the card's `enforced` status rests on the required `verify` status check on `main` (decision `0052`) and not on the hook alone.

## Date

2026-10-17, the plan author (Claude, in the operator's session) in `plans/active/factory-enforcement.md`; graduated from the plan's Decision Log at its retrospective on 2026-10-18.

## Status

accepted
