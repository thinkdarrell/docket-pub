# 0017 — Wave 0 data-quality evaluation treats title as the item body when description and raw_text are both empty and the title is at least 60 characters.

## Decision

Wave 0 data-quality evaluation treats title as the item body when description and raw_text are both empty and the title is at least 60 characters.

## Rationale

The Granicus adapter shape for Birmingham puts the whole item text in title and leaves description NULL. Without this rule the first production Wave 0 run on 2026-05-06 classified about 90 percent of the Birmingham archive as no_agenda_text. The floor began at 120 characters; issue #34 lowered it to 60 once procedural detection ran before the fallback, because the higher floor had been doing double duty as a procedural filter and was dropping short real items. The code and its comment in src/docket/ai/wave0.py are the owner of the current number; this record explains why a floor exists at all.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md, operator notes, and src/docket/ai/wave0.py (original decision 2026-05-06, threshold revised under issue #34)

## Status

accepted
