# 0067 — A YouTube recording's cleaned title is a rung of the meeting-type ladder, and the YouTube pass never writes a classification itself

## Decision

For a row whose own title is generic and which no admin has locked, the first of its YouTube recordings' cleaned titles (`meeting_videos.clean_title`, primary first) that `classify_title` reads as something other than the generic council meeting decides its type, sitting, and body, with `type_source = 'video'`; the rung sits below the admin lock and the specific title and above the city calendar and the schedule rule (`resolve` in `src/docket/services/meeting_types.py`, `docs/specs/meeting-types.md`). `services/youtube_meetings.sync_city` attaches and creates recordings and then calls `meeting_types.resolve_and_store` over the rows it touched; it never writes `meeting_type`, `session_kind`, `body_name`, or `type_source` on an existing row.

## Rationale

The obvious alternative was for the YouTube pass to write the body name it read ("Budget and Finance Committee") straight onto the Granicus row it attached to. That write would last one night: `ingest_municipality` calls `resolve_and_store` over every listed Granicus row every morning, and a schedule-rule resolution carries `body_name = None`, so the next ingest would undo it and the two passes would flip the row daily. Entering the ladder as its own rung makes the YouTube evidence survive every re-resolution, gives the meeting page an honest provenance line ("The council's YouTube recording names it." with a link to the recording), and keeps the admin lock above it.

The rung outranks the calendar and the rule because the stream's title is the council's own name for that recording, written on the day, while the calendar lists only upcoming events and the rule names no body at all. It sits below a specific title because a Granicus clip already named by the clerk ("Budget Hearing") is the city's own record and is final.

## Date

2026-10-24, Claude, after the design review, in `plans/active/youtube-council-channel.md` (built in its M3 and M4; the file moves to `plans/completed/` when the plan closes).

## Status

accepted
