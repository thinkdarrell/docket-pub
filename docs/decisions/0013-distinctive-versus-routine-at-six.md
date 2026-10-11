# 0013 — Before the meeting summary prompt runs, items with significance_score of 6 or above are rendered in full and the rest are grouped by topic with counts, such as '33 demolitions, 18 public safety items'.

## Decision

Before the meeting summary prompt runs, items with significance_score of 6 or above are rendered in full and the rest are grouped by topic with counts, such as '33 demolitions, 18 public safety items'.

## Rationale

Without the split, recurring demolitions and abatements dominated every Birmingham summary and the one distinctive contract or ordinance was buried. Six was chosen because Haiku scores routine abatements at 4 or 5 and reserves 6 and above for distinct dollar amounts, named contracts, or citywide effect. Sonnet is told to treat the routine cluster as at most one closing sentence.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes (original decision 2026-05)

## Status

accepted
