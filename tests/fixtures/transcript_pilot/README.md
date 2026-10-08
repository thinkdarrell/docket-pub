# Transcript pilot fixture — Birmingham City Council, 2026-02-17, Item 15

Source clip: user's Premiere export of the Item 15 window (530.6 s) from
Granicus clip 1950 (docket meeting id 15). Transcribed 2026-10-04 with
whisper.cpp `ggml-small.en` on an M1 Pro (27 s wall-clock). The minutes
text is `pdftotext` of the Granicus MinutesViewer PDF for the same clip.

Provenance details: source clip file
`~/Documents/Adobe/Premiere Pro/26.0/2026-02-17_clip1950_council-meeting.mp4`
(530.6 s, user-clipped Item 15 window); model whisper.cpp ggml-small.en,
M1 Pro, 27 s wall-clock. Granicus index points: item open 3309 s,
motion 3393 s, vote 3847 s.

`expected.json` records the two hand-verified discrepancies the pipeline
must reproduce (spec, "Pilot evidence"). The transcript file still
contains the small model's errors ("aliyah" for ALEA, "Vassa" for Vasa);
that is intentional, it is what name resolution has to fix.

Note the "36-25A-7(a)(4)" string in `expected.json` is the normalized
form; the small model rendered it as "36, 25, a seven a four". The
citation guard's normalizer (Plan 2) is what makes these match.
