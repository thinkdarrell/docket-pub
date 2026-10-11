# 0005 — Votes derived from video OCR and votes parsed from official minutes are stored side by side, each row carrying its source kind, and a disagreement between them is flagged for the reader rather than merged by code.

## Decision

Votes derived from video OCR and votes parsed from official minutes are stored side by side, each row carrying its source kind, and a disagreement between them is flagged for the reader rather than merged by code.

## Rationale

The Data Honesty Protocol requires that a reader can see which source said what. OCR is machine reading of a vote board on video and can misread a name; minutes are the official record but arrive weeks later and sometimes omit roll calls. Merging them would hide both failure modes. Keeping them distinct also lets the later source-reconciliation work (docs/DEBT.md D28) compare them honestly.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes

## Status

accepted
