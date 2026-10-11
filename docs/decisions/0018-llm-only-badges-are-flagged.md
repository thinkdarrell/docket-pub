# 0018 — A policy badge is applied, and so visible to readers, only when a deterministic signal (keyword, action type, or topic) backs it. A badge only the model suggested lands as flagged for admin review; rejected archives it.

## Decision

A policy badge is applied, and so visible to readers, only when a deterministic signal (keyword, action type, or topic) backs it. A badge only the model suggested lands as flagged for admin review; rejected archives it.

## Rationale

Policy labels such as property recovery or housing stability are editorial claims about an item, and a model-only suggestion is not strong enough evidence to publish. decide_status_and_confidence in src/docket/ai/badges_policy.py is the single source of truth, with confidence 1.0 for both signals, 0.8 for deterministic only, and 0.4 for model only. On 2026-05-12, 65 model-only badges went to the review queue at /admin/badge-review instead of the public site.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes (original decision 2026-05-12)

## Status

accepted
