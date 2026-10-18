# 0052 — main requires the verify status check to merge, administrators included

## Decision

A change reaches `main` only when the status check named `verify` (the `verify` job of `.github/workflows/verify.yml`, which runs `./tools/verify`) is green on the commit it brings: a pull request cannot merge until its head's check is green, and a direct push is accepted only for a commit whose check has already passed. The rule applies to administrators, requires neither a reviewer nor a pull request, and forbids force pushes to and deletion of `main`.

## Rationale

Decision `0022` made deploy-from-a-clean-`main` a matter of discipline because branch protection needed GitHub Pro for a private repository (`docs/DEBT.md` `D15`, issue #37). The repository is public now, so GitHub provides the protection free, and the discipline becomes a setting: a red branch cannot merge, and a red push to `main` is refused by the server rather than by the habit of one person. The pull-request route itself stays a working rule (`AGENTS.md`), not a setting: the protection body sets `required_pull_request_reviews` to null, so a commit whose `verify` check already passed can be pushed to `main` directly; a pull-request requirement with zero approvals would close that and was left out because every factory merge already arrives by pull request. The alternative, keeping the rule in prose, is what the factory review of 2026-10-17 found wanting: nothing refused a red merge at the moment it was made.

`strict` is false (the branch need not be up to date with `main` before merging) because one person commits here and the factory never rebases a plan branch after a merge to `main`; `strict` would demand that rebase on every plan branch after any merge. Administrators are included because the operator is the administrator, and the rule exists to stop the operator's own habit. No reviewer is required because there is one committer, and a required reviewer would block every merge. A ruleset was considered and offers nothing extra for one branch and one committer.

The protection is recreated, from any checkout with a `gh` token that has the `repo` scope, with:

    gh api --method PUT repos/thinkdarrell/docket-pub/branches/main/protection --input - <<'EOF'
    {"required_status_checks":{"strict":false,"contexts":["verify"]},"enforce_admins":true,"required_pull_request_reviews":null,"restrictions":null,"allow_force_pushes":false,"allow_deletions":false}
    EOF

and read back with `gh api repos/thinkdarrell/docket-pub/branches/main/protection --jq '.required_status_checks.contexts, .enforce_admins.enabled'`, which prints `["verify"]` and `true`. The operator set it and read it back on 2026-10-18 (plans/completed/factory-enforcement.md, Artifacts and Notes). Because the workflow runs on both the `push` and the `pull_request` event, a pull request shows two check runs named `verify`; a successful run of either name satisfies the required context.

## Date

2026-10-18, M4 session of plans/completed/factory-enforcement.md, on the operator's instruction in that plan; the protection was set and read back by the operator the same day (UTC)

## Status

accepted
