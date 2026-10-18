# 0053 — The deny list in `.claude/settings.json` guards stated norms, one rule per form an agent usually types, and is not a containment boundary

## Decision

Every rule under `permissions.deny` in `.claude/settings.json` corresponds to a rule a document in this repository already states in prose (today: hook bypass, from `AGENTS.md` Working rules, and deploying from an agent session, from `GOALS.md` Constraints and `docs/specs/operations.md` Deploying), written as the invocation an agent usually types, with each form git or the tool documents for it (`--no-verify` and its short form `-n`, `-c core.hooksPath=`). No rule is added for a norm no document states, and no rule is added to close a wrapper form (`bash scripts/deploy.sh`, `/usr/bin/git`, `sh -c '...'`). `AGENTS.md` says the file is the one place the rules live.

## Rationale

The Claude Code permission documentation, read on 2026-10-17, says a Bash deny rule matches the invocation Claude usually writes and is not a security boundary: it does not match the same program reached through another path or a shell wrapper. A list that tried to contain would therefore never be complete, and a reader who found it would trust it as containment anyway. A rule that guards a stated norm has something to cite when it fires, and its refusal sends the agent to the document that states the rule; a rule for an unstated norm (force pushes, destructive SQL, an allowlist of read-only commands) has nothing to cite and would be the first text to state the rule, in a file no reader opens.

The alternative was proposed twice and declined twice. The operator's review of the authoring plan asked for `bash scripts/deploy.sh` and `sh scripts/deploy.sh` rules; they were declined because `scripts/deploy.sh` itself refuses every branch but `main`, where a human deploys, and because closing one wrapper invites closing the next. The closing review then found `git commit -n`, git's documented short form of `--no-verify`, missing; it was added, which is not an exception to this decision but its application: the norm was already stated, and the form is one git documents. Future rules are judged the same way: name the document that states the norm, and the form the tool documents.

One consequence binds plan authors: the deny list reaches the very session that writes it, after a short delay, so a plan that adds a rule cannot have the same session demonstrate the denied command's behaviour (the plan's M2 session observed its own `scripts/deploy.sh` probe refused one Bash call after writing the file). `skills/plan-author/SKILL.md` says what the plan does instead.

## Date

2026-10-17, the plan author (Claude, in the operator's session) in `plans/active/factory-enforcement.md`; graduated from the plan's Decision Log at its retrospective on 2026-10-18.

## Status

accepted
