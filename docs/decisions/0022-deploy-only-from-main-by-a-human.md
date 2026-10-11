# 0022 — Deploys run scripts/deploy.sh from a clean main checkout after a pull request has merged, never from a feature branch and never from inside an automated loop.

## Decision

Deploys run scripts/deploy.sh from a clean main checkout after a pull request has merged, never from a feature branch and never from inside an automated loop.

## Rationale

railway up ships whatever is in the local working tree regardless of branch, so a deploy from a feature branch puts unreviewed code live. The wrapper also records the commit SHA into the image so a later audit can say which commit is running, which the 2026-05-22 parity audit had to reconstruct from file hashes. Branch protection would enforce this on GitHub but needs GitHub Pro for a private repository (issue #37, docs/DEBT.md D15), so the rule is discipline until then. railway redeploy is never used because it restarts the old build.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes

## Status

accepted
