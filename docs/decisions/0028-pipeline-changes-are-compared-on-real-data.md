# 0028 — A non-trivial change to an extraction, matching, or summary pipeline is run old against new on real rows, and the difference is read, before it ships.

## Decision

A non-trivial change to an extraction, matching, or summary pipeline is run old against new on real rows, and the difference is read, before it ships.

## Rationale

Unit tests pass on changes that degrade real output: a prompt tweak that reads well on fixtures can flatten every real headline, and a matcher change can drop thousands of links while its tests stay green. The vote-matcher v2 and the Smart Brevity prompt versions were each tuned this way, and the cases where the step was skipped are the ones that needed hot-fixes.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes

## Status

accepted
