# 0116 — No afternoon or evening `transcript_pipeline` tick

## Decision

The worker task `transcript_pipeline` runs once a day. No afternoon or evening run of it is scheduled beside the afternoon pass (decision `0115`). A transcript the Legion's evening run uploads is public on arrival and shows "Speaker N" labels until the worker's next daily tick resolves its speakers.

## Rationale

The decision is the operator's, one of the four answers the operator gave on 2026-11-19 before plan `recordings-seen-the-day-posted` was written. The reasons below are the plan author's reading of the code and were not stated by the operator.

The obvious alternative is an evening tick after the Legion's scheduled run, so that a same-day transcript has its speakers' names the same evening. When the decision was made the Legion's scheduled run had not fired once, so its finishing time was unknown and bounded only by its three-hour cap; there was no time at which an evening tick was known to follow the upload. A tick advances each transcript by one stage, so an evening tick would buy speaker names a few hours early and nothing else. It would also spend from the daily AI budget in a second window, and it would add a second window in which `docs/runbooks/transcripts.md`, "Re-transcribing one meeting", forbids starting a re-transcription.

A session that sees "Speaker N" on a same-day transcript and reaches for a second tick should first read how long the Legion's run takes (`transcriber/README.md`, "The scheduled run", where the operator records it) and ask the operator.

## Date

2026-11-19, the operator's answer; recorded by the authoring session of plan `recordings-seen-the-day-posted` (Claude) and graduated by that plan's M4 session the same day.

## Status

accepted
