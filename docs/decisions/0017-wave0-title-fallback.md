# 0017 — Wave 0 data-quality evaluation treats title as the item body when description and raw_text are both empty and the title is at least 120 characters.

## Decision

Wave 0 data-quality evaluation treats title as the item body when description and raw_text are both empty and the title is at least 120 characters.

## Rationale

The Granicus adapter shape for Birmingham puts the whole item text in title and leaves description NULL. Without this rule the first production Wave 0 run on 2026-05-06 classified about 90 percent of the Birmingham archive as no_agenda_text. The 120-character floor keeps genuinely title-only consent references (such as 'CONSENT ITEM 5. A Resolution') in the skipped bucket, where docs/DEBT.md D12 tracks their recovery.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes (original decision 2026-05-06)

## Status

accepted
