# 0046 — Whisper's initial prompt is prose, and a prompt leak is detected against the prompt text the engine was given, not against a term list

## Decision

`build_initial_prompt()` in `transcriber/transcriber/prompt.py` renders the roster and the vocabulary as short sentences in the register of a council meeting (`Birmingham City Council. Councilors present are A, B, C. ALEA, CJI, and APC reported. ...`), never as a labelled list such as `Terms: ...` or `Councilors: ...`, and fits the 600-character budget by dropping whole sentences from the end. `is_prompt_leak()` in `transcriber/transcriber/engine.py` decides whether a chunk is the prompt read back by matching eight consecutive normalized words, on word boundaries, against the normalized prompt that `build_output()` receives as `initial_prompt`, which is the prompt the engine was actually given; no second copy of the vocabulary exists for detection.

## Rationale

Whisper conditions on the initial prompt as if it were the preceding transcript, so a labelled comma list is both unlike speech and easy to reproduce verbatim: the old `Terms:` list came back as if spoken in four of the 48 version-1 transcripts, and the fixture row that carries it (meeting 2543, seq 38) has an ordinary `avg_logprob` of -0.36, so no confidence threshold catches it and only a text match can. Prose in the meeting's own register is what the model expects to continue, and dropping whole sentences keeps every surviving sentence grammatical; with the nine-name 2026 roster the first seven of ten sentences fit, and the three trimmed carry words Whisper spells correctly unaided.

Three alternatives were rejected. Keeping the list and counting vocabulary terms in a segment needs the term list and the prompt to agree forever, two owners of one fact (`docs/PRINCIPLES.md`). Matching the whole segment as a substring of the prompt misses an echo with filler attached ("Thank you. ALEA, CJI, and APC reported...") and a repeated sentence, which is why the rule is an eight-word window. A shorter window would reach genuine phrases such as "the Birmingham City Council"; with prose sentences of three to twelve words, and a roster clause that carries middle initials in first-name order no spoken roll call reproduces, eight consecutive prompt words in genuine speech is implausible, and that residual false drop is accepted. The trap this record guards against is the agent who re-adds a crisp `Terms:` list because it reads better to a human, or who gives the detector its own term list so it can run without the prompt: the first recreates the leak and the second the drift.

## Date

2026-10-16, the plan author and the operator session in `plans/completed/transcriber-clean-speaker-segments.md` (the window rule is the operator's revision after an external review); graduated from the plan's Decision Log at its retrospective.

## Status

accepted
