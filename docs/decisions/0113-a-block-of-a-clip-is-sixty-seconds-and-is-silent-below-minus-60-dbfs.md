# 0113 — A clip's sound is measured in blocks of 60 seconds, and a block is silent below -60 dBFS

## Decision

`transcriber/transcriber/sound.py` cuts a clip's 8 kHz audio into blocks of `BLOCK_S` (60 seconds), counts a remainder of `MIN_TAIL_S` (10 seconds) or more as a block of its own and joins a shorter one to the block before it, and calls a block silent when its level is below `SILENCE_FLOOR_DBFS` (-60 dBFS: 20 times the base-10 logarithm of the block's root-mean-square sample value over 32768). A change to the arithmetic or to one of those constants raises `SOUND_METHOD_VERSION`.

## Rationale

The figures come from three clips fetched whole on 2026-11-17 and measured by a prototype of the rule. Clip 1424 (a 2021 meeting whose YouTube recording passed): 3,761 seconds, 63 blocks, none silent, levels from -30.2 to -17.8 dBFS. Clip 1414 (2021-02-02, meeting 275): 2,516 seconds, 42 blocks, all silent, levels from -73.8 to -70.2. Clip 2034 (2026-11-10, meeting 3197): 6,019 seconds, 101 blocks, 46 silent with levels from -70.9 to -69.7 and 55 audible with levels from -40.6 to -24.3. No block of the three lay between -66 and -50 dBFS, so -60 has about ten decibels of room on the silent side and twenty on the audible side. On clip 2034 the audible run from 2,040 to 5,160 seconds holds the 2,162 to 5,132 seconds on which its YouTube recording passed, so the rule and the matcher agree about where the sound is.

The floor is set for what the site says with it. The meeting page prints "no sound" and a link says "(no sound)", so the error to avoid is calling an audible stretch silent. A block that is quiet and not silent, a recess with an open microphone, stays audible, at the cost of a stretch a listener would call silent going unlabelled. A floor relative to the clip's own level (so many decibels below its median block) is the obvious alternative; it has no answer for a clip that is silent throughout, as clip 1414 is, and the gap in the absolute levels leaves no need for it.

Sixty seconds is the size of the pieces the matcher already checks a stretch's ends in (`EDGE_S` in `transcriber/transcriber/align.py`), keeps a three-hour clip to about 180 blocks, and is finer than anything the site prints, which is whole minutes. A shorter block would find shorter silences, which the meeting page does not note below ten minutes, and would call a pause in speech a silence sooner.

Three clips are a small sample, and they are the data there was: the record of the rule's first production run is the place to check it (the read-only query in `docs/runbooks/transcripts.md`, "Measuring YouTube recordings (the backlog)"), and a clip the page calls silent that is audible in the player is an issue with its row's figures.

## Date

2026-11-17, the authoring session of plan `silent-granicus-says-so` (Claude), from its own measurements of clips 1424, 1414, and 2034; built by that plan's M1 and graduated by its M6 session on 2026-11-18.

## Status

accepted
