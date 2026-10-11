# 0006 — Votes link to agenda items through the vote_agenda_items join table; one consent vote fans out to many items, each link carrying association_type and match_confidence (1.0 for a named callout, 0.8 for default consent fill).

## Decision

Votes link to agenda items through the vote_agenda_items join table; one consent vote fans out to many items, each link carrying association_type and match_confidence (1.0 for a named callout, 0.8 for default consent fill).

## Rationale

Birmingham passes most of its agenda in consent blocks, where one recorded vote adopts dozens of items at once. A single agenda_item_id foreign key on the vote row could represent only one of them, so the first matcher reached about one percent coverage. The join table, introduced by migration 009 and backfilled by 010, raised vote-level coverage to about eleven percent and link count to over 33,000. The deprecated singular columns were dropped in migration 011.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes (original decision 2026-05-01)

## Status

accepted
