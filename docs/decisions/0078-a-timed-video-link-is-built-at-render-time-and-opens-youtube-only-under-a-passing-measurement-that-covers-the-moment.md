# 0078 — A timed video link is built when the page renders, from seconds stored on the Granicus clock, and opens YouTube only when a recording whose measurement passed covers that second; otherwise it opens the Granicus chapter

## Decision

Times stay stored on the Granicus clock and are converted only when a link is built, by one module, `src/docket/services/video_links.py`, which hands templates a finished link that names its site. A link opens YouTube at the floor of (Granicus seconds minus the offset) only when an attached recording has a measurement that passed, at a method version the site trusts (a floor), made against the clip id the meeting has now, whose coverage (start included, end excluded) holds the second; in every other case it opens the Granicus player at the item's chapter. A measurement passes only when the whole-recording score is at least 9.0, exceeds the best score at any other offset by at least 4.0, at least 60 percent of the counted five-minute windows confirm the offset within 2 seconds, and no window matches strongly (8.0 or more) at a different offset; coverage is the span from the first confirmed window to the last. Those numbers are owned by `transcriber/transcriber/align.py`, and changing any of them raises `ALIGN_METHOD_VERSION`.

## Rationale

The two recordings of one meeting do not start together, so a Granicus second cannot be handed to YouTube, and the Granicus player can only jump to a chapter. Storing converted times was the alternative to converting at render time: it would have put a second clock in the tables, and every stored second would have gone stale when a recording was re-measured, rejected, or moved to another meeting row. Converting at render time means a wrong link is corrected by fixing or deleting one measurement, and a link falls back to Granicus the moment its measurement stops being trusted. The stored clip id is part of that: the worker can move a recording between meeting rows and an upcoming event's id becomes a clip id, and an offset is only true against the clip it was measured on.

The pass mark was chosen from data. On 2026-11-05 the rule was run over the audio of 8 Granicus clips and 9 YouTube recordings: the 9 matched pairs and all 63 mismatched pairings. Every matched pair passed, with a lowest score of 12.3, a lowest margin of 7.0, and a lowest confirmed share of 13 of 19 windows. Every mismatched pair was rejected on score alone, with a highest score of 7.3, a largest margin of 1.83, and a largest share of 3 of 7. The score separates that sample, but only by 7.3 against 12.3, which is why the margin and the window share are also required: a wrong offset cannot satisfy windows that each search their own neighbourhood. The conflict rule rejects a recording that was cut or edited, which has two true offsets, instead of linking half of it wrongly. The full table is in the plan's Artifacts and Notes.

Two parts of the rule came from an external review of the plan, checked on the same audio. The agreement tolerance is 2 seconds and not 1 because the two recordings do not run at exactly the same speed: the offset moved by up to 0.56 seconds over 4,949 seconds (113 parts per million), and at that rate the longest recording production held (16,901 seconds; nine ran longer than four hours) drifts about 0.95 seconds either side of its offset, which is the 1-second limit itself. Past it the edge windows stop confirming and, being strong matches, count as conflicts and reject the whole recording. One window is anchored to the end of the overlap because whole windows counted from the start left up to five minutes at the end of every recording uncovered. Neither change moved a verdict among the 72 pairs. The price of the tolerance is that a link may land up to 2 seconds from its moment.

Coverage is the confirmed span and not the whole overlap because outside it nothing has checked that the recordings still run together. The converted second is a floor and coverage is half-open so that a link may land a fraction of a second early and never late. A YouTube URL is always built from the video id, never by appending to a stored URL, which would break a `youtu.be` address and double a `t=` the stored URL already carries.

One module owns all of this because the layer rule in `ARCHITECTURE.md` keeps SQL out of `web/` and `web/` out of `services/`, and the builder needs the Granicus chapter rule, which lived in `web/` before.

## Date

2026-11-05, the plan author (Claude) from the operator's goal (until a meeting is measured its links stay on Granicus), with the end window and the 2-second tolerance decided by the operator the same day from an external review, in `plans/completed/video-links-land-on-the-moment.md` (built in its M1 and M4 to M6; the file is under `plans/active/` until the plan closes); graduated from the plan's Decision Log by its M8 session on 2026-11-06.

## Status

accepted
