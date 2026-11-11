# 0088 — A committee recording is named by elimination only when one event is left, it runs ten minutes, and nothing competes

## Decision

On a day whose calendar lists several committee events, the calendar rung of `services/meeting_types.resolve` names a generic-titled recording after the one event the day's already-named rows do not account for, and only when exactly one event is left, the recording runs at least `ELIMINATION_MIN_S` (600 seconds), and no other unnamed recording of the day runs that long or has no stored length; otherwise the day stays "Council committee meeting". On a day with one committee event a recording under 600 seconds does not take the name when a longer unnamed recording of that day could. A cancelled calendar event names nothing and accounts for nothing. Who names and who competes is decided from each row's own facts, never from what the calendar rung stored for another row, and the meeting page says when a name was reached this way.

## Rationale

The rule this extends (`0085`) matched a row without documents to the day's committee event only when the day had exactly one, so every two-committee day stayed generic even when the council's YouTube channel had named one of the two recordings and the other could only be the second committee. The operator asked for the forced answer and for nothing more: an undecidable day stays generic rather than guessed. Hence "exactly one left" and "nothing competes"; with two events and no named row, or two full-length unnamed recordings, the rule declines, and a tiebreak (clip order against the calendar's start times, say) would be a guess resting on `start_time`, which is wrong by construction (issue #88).

The 600-second floor is there because the clerk's equipment leaves stream tests of a few minutes in the archive beside real recordings. Without it a four-minute test left beside a named recording would take the name of a committee whose meeting the archive never recorded, and on a one-committee day the test and the real recording were both named, which then defeated the attach by name in the YouTube pass (two rows of the name, and a third created for the recording). A short clip does not block a longer recording's elimination, for the same reason; a clip of unknown length does, since nothing shows it is short. The floor is the same number as the hiding rule's `SHORT_CLIP_S` (`0089`) and a separate rule.

The first draft let a sibling's stored `calendar_event_id` claim an event and resolved each day twice. On a day with one committee event and two generic clips the first pass gave both clips the event and the second took it from both, so the result depended on the pass count. Deciding from facts the rung does not itself write (title, lock, minutes, items, attached recordings, length) cannot oscillate, and lets each row be resolved once, in any order. It is also why `resolve_and_store` resolves every visible row of each date it is given a row of: one row's new recording can now name another.

A cancelled event is dropped by its stored status (anything neither NULL nor `active`, since `active` is the only value observed and a guessed spelling of cancelled would miss the real one) or by its title, so a cancelled committee meeting neither names an equipment test nor blocks elimination for the committee that did meet.

The provenance sentence differs for an eliminated name because the calendar did not say which recording is which; the page states the inference instead of presenting it as the city's own naming (`docs/PRINCIPLES.md`, "Source or silence").

## Date

2026-11-11, the operator (an undecidable day stays generic) and Claude as the author of plan `committee-clips-named-or-hidden` (the floor, the competitors, the row-facts rule after an outside review); built by the plan's M2 session and graduated by its M5 session the same day.

## Status

accepted
