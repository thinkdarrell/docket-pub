# 0047 — The producer drops hallucinations on whole Whisper chunks before the per-word speaker split, and the split keeps every one-word run

## Decision

`build_output()` in `transcriber/transcriber/engine.py` runs `clean_segments()` on the raw chunks faster-whisper emits, where `is_hallucination()` reads a chunk's `avg_logprob` and word count, and only then runs `split_by_speaker()`, which cuts each kept chunk at every word-level diarization cluster change with no smoothing of short runs; the child segments inherit the chunk's `avg_logprob` and `no_speech_prob`. "Short" is a hallucination signal at the chunk grain and a legitimate turn at the word grain, and the order is what keeps the two rules from colliding.

## Rationale

The batched pipeline merges a genuine short utterance into the surrounding chunk of roughly 28 seconds, so a standalone short low-confidence chunk is almost always Whisper filling applause or silence: of the fixture's eight rows at or below -0.8 logprob, every one is filler or nonsense and none is a genuine response. After the split, a genuine one-word "Here." has exactly the shape of that filler, so a filter run after the split would delete the roll call this change exists to recover (the clerk's names and nine answers sat inside one chunk under one cluster in 40 of 48 transcripts, and the worker's `find_roll_call_pairs()` paired nothing). Smoothing short runs during the split was rejected for the same reason: the roll call is made of one-word turns. The cluster jitter that smoothing would hide is diarization quality (pyannote over-splitting one voice, `D53` in `docs/DEBT.md`) and is fixed at the diarizer, not by merging runs. The children inherit the chunk's two confidence numbers because they are Whisper statistics of the chunk and there is no honest per-child value; word probabilities are a different quantity.

The trap this record guards against is the agent who sees filler surviving inside a long low-confidence chunk, or jittery one-word segments inside one voice, and moves the hallucination rule after the split or adds a minimum run length. Either change passes every test that does not contain a roll call and silently removes the one thing the split was built for.

## Date

2026-10-16, the plan author in `plans/completed/transcriber-clean-speaker-segments.md`; graduated from the plan's Decision Log at its retrospective.

## Status

accepted; `0052` adds a same-cluster merge after the split and records a tried and rejected fragment-absorption rule; the no-smoothing clause stands
