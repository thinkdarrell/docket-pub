# 0032 — The public Minutes vs. Video block stays dark until the ship gate on the admin AI panel reads "met" and MINUTES_VS_VIDEO_UI=true is set on docket-web; until then discrepancies are reviewed only at /admin/review/discrepancies. Event extraction runs on Sonnet 5.5, not Haiku.

## Decision

The public Minutes vs. Video block stays dark until the ship gate on the admin AI panel reads "met" and MINUTES_VS_VIDEO_UI=true is set on docket-web; until then discrepancies are reviewed only at /admin/review/discrepancies. Event extraction runs on Sonnet 5.5, not Haiku.

## Rationale

A block that tells readers the official minutes disagree with the video is the strongest claim the site makes, so it ships only once the citation-miss rate and review backlog measured by the ship gate are acceptable, and only by an operator flipping a flag after reading that gate. The Haiku-versus-Sonnet A/B on extraction showed Haiku missing material events, so extraction stays on Sonnet 5.5 despite the cost. docs/runbooks/transcripts.md owns the gate's thresholds and procedure.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md as merged from PRs #105 and #106 (original decision 2026-10)

## Status

accepted
