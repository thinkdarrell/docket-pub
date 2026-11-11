# 0089 — A short or speechless clip on a day with no calendar event is hidden automatically, with its reason, two brakes, and a permanent exemption

## Decision

The daily worker task `non_meetings` hides a generic-titled Granicus clip that has no agenda link, minutes link, agenda item, or YouTube recording, whose date the stored calendar shows no council or committee event on, and which either runs under `SHORT_CLIP_S` (600 seconds) or has a `low_speech` transcript, once its date is at least four days past and not before the city's `calendar_complete_from`. It writes `meetings.hidden_reason = 'not_a_meeting'`; every writer of `is_hidden = TRUE` writes its reason. It hides nothing while the city's calendar has not been read for 36 hours, never hides a clip that has a public transcript with speech (it lists it for the operator instead), and never hides a row whose `keep_visible_at` is set, which an admin's unhide sets for good.

## Rationale

Before this, only an admin hid a meeting (and the YouTube pass, a row it absorbed). The clerk's streaming equipment leaves recordings of one to eight minutes in the archive on days nothing was scheduled; on 2026-11-11 five of the ten generic committee cards on Birmingham's meetings page were such clips, and on 2026-10-11 the operator had hidden nineteen by hand. The operator's instruction was to hide the short clips on days with no calendar event, and those with a low-speech result even when longer.

Length alone was the obvious rule and is wrong: real committee meetings of six and eleven minutes exist (2026-10-05, 2026-11-02). It is the empty calendar day that marks a test, which is why the rule could not exist before the calendar held past days (`0087`) and is bounded below by `calendar_complete_from`: before that date an empty day means the city had already removed its events. For the same reason any event on the day keeps a clip, a cancelled one included, the opposite of the resolver's reading (`0088`) and the direction in which a mistake leaves a clip visible.

The brakes each answer one way of hiding a real meeting. During a calendar outage every day looks empty, so the rule stops when the newest `fetched_at` is more than 36 hours old, measured by the database's clock. The YouTube pass creates a row for an unmatched recording once it is three days old, so at four days it has either attached a recording to the clip, which keeps it, or has none. A clip with a transcript that has speech is held back for the operator; a transcript is not required before hiding, because a hidden or untranscribed clip never gets one (the producer claims only visible rows, and runs when the operator starts it). Every doubt makes the rule do less: a NULL length is not short, a row with no `external_id` is left.

The reason is a column because the operator must be able to list what was hidden automatically and undo all of it with one statement, and the admin page prints it. The exemption is its own column, not the type lock (`type_locked_at`), because the lock says who classified a row, not whether it may be hidden; without the exemption a row brought back by hand would vanish again the next morning. The write is one statement per city scoped to rows still visible and not exempt (`0026`), so a row an admin changed between the read and the write is left as the admin put it.

No new value of `is_hidden` and no new reader: twenty-seven files already exclude a hidden row from pages, search, the YouTube pass, and the producer's claims, and an automatically hidden row behaves in each exactly as one an admin hid.

## Date

2026-11-11, the operator (hide the short clips on empty days and the low-speech ones; the transcript brake) and Claude as the author of plan `committee-clips-named-or-hidden` (ten minutes as "short", the two columns, the four days and the 36 hours after an outside review); built by the plan's M4 session and graduated by its M5 session the same day.

## Status

accepted
