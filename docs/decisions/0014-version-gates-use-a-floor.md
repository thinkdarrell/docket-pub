# 0014 — Any check on a prompt, schema, or rewrite version compares with a floor (>=), never equality (==).

## Decision

Any check on a prompt, schema, or rewrite version compares with a floor (>=), never equality (==).

## Rationale

A reader gate written as ai_rewrite_version == 3 hid 906 production items the day the version bumped to 4, because every freshly rewritten item failed the equality. A floor expresses what the gate means, that the item was produced by a format at least this new, and survives every later bump. The template dispatcher in smart_brevity_card.html uses >= 3 for this reason.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes

## Status

accepted
