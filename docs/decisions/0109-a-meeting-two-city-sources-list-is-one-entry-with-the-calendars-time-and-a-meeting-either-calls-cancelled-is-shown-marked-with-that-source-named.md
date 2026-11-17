# 0109 — A meeting two city sources list is one entry with the calendar's time, and a meeting either source calls cancelled is shown, marked, with that source named

## Decision

On the coming-up page and in its feed, a row of the council's video site and an event of the city calendar are one meeting when the row's `calendar_event_id` names the event, or when they are the only unpaired council row and council event of one Chicago day. A merged meeting prints the calendar event's day and time; a meeting the video site alone lists prints its stored `start_time`. A meeting either source calls cancelled is kept, marked cancelled, with a sentence naming each source that says so and, for a pair where only one does, a second sentence saying the other still lists it. The calendar event of a cancelled meeting carries "Cancelled: " in its `SUMMARY` and no `STATUS` line.

## Rationale

The time. The stored `start_time` of an upcoming Granicus row was two hours late on 2026-11-16 (GitHub issue #88: meeting 3207 stored 11:00 for a 9:30 meeting; the fix was pull request #181, then open), and the city's calendar gave 9:30 for the same meeting. Whatever becomes of that defect, the calendar event is the city's own page for the meeting and carries an end as well as a start, so where there is one it is the source of the day and the time, both from the one source so an entry cannot sit under one date and print another's time.

The pairing. The meeting-type resolver already writes `calendar_event_id` when it matches a row to an event, so that is the first rule. The day rule exists for a row the resolver has not reached. It is confined to council meetings and to a day with exactly one of each, because two committee meetings on one day are common and a wrong merge would hide a meeting.

Cancellation. The plan first left a cancelled meeting out, on the ground that the page is a list of things to attend. The operator reversed that before any milestone ran: a reader who had the meeting in mind, or in a subscribed calendar, is better served by seeing that it is off than by finding it gone. When the two sources disagree, docket.pub shows both things the city published and rules on neither, which is "Source or silence" applied to a disagreement; a separate "Conflicting Status" label was considered, and the two sentences say the same with the sources named. A stored status that is neither `active` nor a spelling of cancelled is quoted as stored (`The city calendar marks this "postponed".`), because docket.pub does not know what the word means.

No `STATUS:CANCELLED`. A second review said that Google Calendar and Apple Calendar remove an event so marked from a subscribed calendar. A search on 2026-11-16 neither confirmed nor refuted it, and production held no cancelled event to try. The marking exists so that a subscriber sees the meeting is off; a line that may make a program hide the event works against that, and words in the title are shown by every program. `D163` in `docs/DEBT.md` is the row for adding the line back once it has been seen in real programs.

## Date

2026-11-16. The time and the pairing: the plan author (Claude) of plan `birmingham-coming-up`. Showing a cancelled meeting, and the feed without a `STATUS` line: Darrell Nance (operator), after two written reviews of the plan. The cases the plan left open (two rows naming one event, a quoted status in a pair) were settled by the plan's M6 session on 2026-11-17 and are in `docs/specs/coming-up.md`.

## Status

accepted
