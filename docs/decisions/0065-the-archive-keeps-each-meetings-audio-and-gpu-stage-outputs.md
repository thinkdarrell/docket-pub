# 0065 — The archive keeps each meeting's audio as FLAC and the two GPU stages' outputs, so re-runs skip the download and post-processing changes replay on the CPU

## Decision

Beside `transcript.json` and `words.json`, each meeting's archive folder keeps `audio.flac` (the 16 kHz mono audio, lossless), `raw.json` (Whisper's chunks before cleaning, with the prompt, duration, SHA-256, and model names), and `diarization.json` (pyannote's turns and embeddings), written by `transcriber/transcriber/inputs.py`. A run decodes `audio.flac` when it exists instead of downloading from Granicus. `--replay` rebuilds an output from the two JSON files with no audio, model, or database; `--cache-audio` and `--capture-inputs` fill the archive for meetings transcribed before this change without claiming or uploading. None of the three files is uploaded.

## Rationale

The version-3 backlog re-run of 47 meetings (2026-10-18) downloaded every recording again because the producer deleted its WAV after each meeting, and it re-ran both GPU stages even though version 3 changed only post-processing. Download and model load were roughly a third of each meeting's wall time; the GPU stages were the rest. Two of the version-3 rules were built and withdrawn only after a full GPU run on meeting 2543 showed them failing (`plans/completed/transcriber-v3-quick-wins.md`); with the inputs archived that check is a CPU replay over every meeting in seconds. On 2543 the decoded FLAC has the same SHA-256 as the original download, and the replay of freshly captured inputs reproduced the uploaded version-3 transcript row for row.

The original design deleted audio so that nothing large lands inside the WSL2 virtual disk (`docs/superpowers/specs/2026-10-05-meeting-transcripts-design.md`); the archive is the NTFS bind mount, so that reason still holds. The recordings are public Granicus video. The cost is about 63 MB per hour of meeting, about 5 GB for the 2026 archive. A FLAC that cannot be written is logged and the meeting continues, and one that does not decode is deleted and fetched again, so the cache can never fail a meeting.

## Date

2026-10-18, by hand on branch `feat/transcriber-input-cache` (plan `plans/completed/transcriber-input-cache.md`).

## Status

accepted
