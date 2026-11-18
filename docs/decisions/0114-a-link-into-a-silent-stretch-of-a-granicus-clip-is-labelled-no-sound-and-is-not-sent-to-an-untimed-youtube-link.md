# 0114 — A link that opens the Granicus player where the clip is silent is labelled "(no sound)" and is not redirected to an untimed YouTube link

## Decision

A link that opens a meeting's video at a moment keeps opening the Granicus player when no passed stretch of a YouTube recording covers the moment, also when the clip was measured silent there. Such a link says "(no sound)" after the site's name (`VideoLink.no_sound`, set in `link_for` in `src/docket/services/video_links.py`). The label changes what a link says and never where it goes. The meeting page, whose two video links are untimed, prints the YouTube link first and says "no sound" on the Granicus link when the clip is silent throughout or for ten minutes or more (`NOTE_MIN_SILENT_S`).

## Rationale

The obvious remedy for "this moment is silent on Granicus and the meeting has a YouTube recording" is to open YouTube. It cannot be done at the moment: every stored time of a Granicus meeting is on the Granicus clock, and the YouTube second for it is known only from an offset the transcriber measures from the sound, which a silent stretch does not give. What is left is the untimed link, the start of a recording that runs for hours, or of the wrong one of two parts. A reader who clicked "Watch this vote" would be given a link that promises a moment and does not deliver it, in place of a true link that states its limit. The label keeps the promise the link can keep (the chapter, on the city's own player) and says what the reader will find there; the audible recording is one click away on the meeting page, where it is now printed first.

The rule does not narrow where YouTube is used: a moment a passed stretch covers opens YouTube whether or not it lies in a silent span, and a YouTube link never carries the label, because the label is about the Granicus player.

A clip silent throughout labels every Granicus link, a link with no moment and one past the clip's end included, and a silent span that reaches the clip's end has no upper bound, because a cue point can sit on the last second or past it and no such moment has sound.

The meeting page's floor of ten minutes is one constant. A stream that starts a few minutes before the meeting does is ordinary and not worth a note; the measured partly silent clip has 45 silent minutes of 100. The label on a timed link has no floor, because it speaks of one moment and not of the clip.

Transcribing the YouTube recording when the Granicus clip is silent would give these moments sound of their own. It is not built: a transcript made from YouTube audio has its times on YouTube's clock, and every reader of a transcript time would have to learn which clock a transcript is on (`docs/DEBT.md`, `D172`).

## Date

2026-11-17, the authoring session of plan `silent-granicus-says-so` (Claude); the rule for a clip silent throughout and for a span that reaches the clip's end was added on the operator's review of the plan the same day; built by that plan's M4 and M5 and graduated by its M6 session on 2026-11-18.

## Status

accepted
