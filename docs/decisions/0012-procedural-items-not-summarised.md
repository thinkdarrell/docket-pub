# 0012 — Roll call, pledge, invocation, and minutes-not-ready notices get is_substantive = false, null scores, and empty summary text. The title is the content.

## Decision

Roll call, pledge, invocation, and minutes-not-ready notices get is_substantive = false, null scores, and empty summary text. The title is the content.

## Rationale

A paraphrase of 'Roll Call' is noise for the reader and cost for the budget. The first production batch surfaced this when Haiku returned empty rationales for procedural items and the schema validator rejected them; the fix was to make that the intended shape rather than an error. The template renders nothing extra for these items.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes (original decision 2026-05)

## Status

accepted
