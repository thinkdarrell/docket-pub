# 0077 — The transcriber measures each YouTube recording attached to a Granicus meeting by comparing its audio with the clip's, at the start of an ordinary run and before the speech model loads, and keeps none of the audio

## Decision

An ordinary transcriber run begins with a measuring pass (`transcriber/transcriber/measure.py`): for up to `--measure-limit` attached YouTube recordings, newest meeting first, it downloads the recording's smallest audio track with yt-dlp, takes the Granicus side from the archive's `audio.flac` when the meeting has one and from Granicus otherwise, compares the two at 8 kHz with `transcriber/transcriber/align.py`, stores one row, and deletes both working files. It never writes to the archive and has no command of its own. A `rejected` measurement is final until the method version rises; a `failed` one is tried again once it is 7 days old; three failed fetches in a row end the pass for that run; and no error inside the pass keeps the run from transcribing.

## Rationale

Decision `0070` says only the transcriber downloads YouTube audio, and only for `yt-` rows. The offset between a meeting's two recordings can be found only from their sound (in eight sampled pairs the YouTube recording began between 101 and 3,232 seconds after the Granicus clip), the YouTube Data API serves no audio, and the worker's datacenter address is the one YouTube challenges, so the reasons that put yt-dlp on the operator's home machine in `0070` put this download there too. This record widens `0070`'s "only for `yt-` rows" to recordings attached to a Granicus meeting, for measuring and nothing else: nothing from an attached recording is transcribed or ingested.

The operator's answer was that measuring rides on the existing run, with no new command to remember. It runs before `FasterWhisperEngine` is constructed because that constructor is what loads the model onto the graphics card. Unbounded, the 359 recordings waiting when this was decided would have held the first run for hours at about a minute each, so a run measures 20 by default and `--limit 0 --measure-limit 400` works through the backlog on purpose.

The audio is discarded because nothing needs it again: the stored row is the whole result, and a changed method re-measures from fresh downloads. Reading the archived FLAC spares Granicus a request, which is the reuse decision `0065` keeps that file for. The smallest format is enough because the method uses nothing above 3.6 kHz.

Re-measuring failures only on a method version bump was the first default. A failure is usually the network or YouTube refusing the machine for a day, and a version bump re-measures every recording; retrying after a week is cheap, and stopping after three failed fetches keeps a blocked day from spending the run on downloads that cannot succeed. The three are counted per fetch and not per stored row, because one broken Granicus clip on a meeting with three recordings would otherwise end the pass alone.

## Date

2026-11-05, the operator (measuring rides on the ordinary run; the audio is not kept) and the plan author (Claude), revised the same day after an external review the operator commissioned (failures counted per fetch, any unexpected error is a `failed` row), in `plans/completed/video-links-land-on-the-moment.md` (built in its M1 to M3; the file is under `plans/active/` until the plan closes); graduated from the plan's Decision Log by its M8 session on 2026-11-06.

## Status

accepted
