# 0016 — A new prompt-version family (for example the upcoming-meeting forward voice) starts its numbering at 100 so downstream threshold gates treat its output as current.

## Decision

A new prompt-version family (for example the upcoming-meeting forward voice) starts its numbering at 100 so downstream threshold gates treat its output as current.

## Rationale

The forward-voice prompts were introduced at version 1 and their output failed the dispatcher's ai_rewrite_version >= 3 gate, so upcoming meetings rendered the fallback. Hot-fix PR #77 moved the family to 100-series numbers. Two sequences now coexist by design: 4, 5, 6 and onward for completed-meeting voice, 100, 101, 102 and onward for upcoming voice.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes (original decision 2026-05-18)

## Status

accepted
