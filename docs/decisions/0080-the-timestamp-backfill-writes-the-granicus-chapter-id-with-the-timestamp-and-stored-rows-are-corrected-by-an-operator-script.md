# 0080 — The timestamp backfill writes an item's Granicus chapter id in the same statement as its timestamp, and items that already had a timestamp are corrected by an operator script, not by widening the ingest precheck

## Decision

`_backfill_video_timestamps` in `src/docket/services/ingest.py` keeps its precheck (it fetches a meeting's player page only when a numbered item lacks a timestamp) and, for each item it matches to a cue point, writes the cue point's chapter id to `agenda_items.external_id` together with the timestamp, in one statement per meeting. It rewrites an id only when the stored id is not a chapter id, exactly one item of the meeting carries that item number, and no other row of the meeting holds or is being given the id. Items that were given a timestamp before this rule are corrected by `scripts/correct_agenda_chapter_ids.py`, which the operator runs with a dry run first.

## Rationale

The Granicus player can jump only to a chapter, `&meta_id=<id>`. Items ingested from the agenda PDF before the recording existed carry ids such as `event-2715-1`, and the pass that later filled their timestamps never touched the id, so their links opened the player at the start of the recording; in 2026 that was 24 of 48 Granicus meetings with cue points. The id and the timestamp come from the same cue point on the same page, so writing them together costs no request.

Widening the precheck to "has an id that is not a chapter id" was the obvious way to reach the rows already stored. It would make every ingest run fetch again the player page of any meeting whose ids can never be rewritten (a duplicated item number, a taken id), forever, and `GOALS.md` binds the project to polite scraping; the existing test that a second call makes no request pins the precheck as it is. The rows already stored are a known, bounded set, and one supervised run with a dry run first is the house pattern for a production correction (decision `0026`).

The guards exist because `agenda_items` has `UNIQUE(meeting_id, external_id)`: a rewrite that collided would fail the whole statement, so an id that cannot be given safely is left alone and logged. The rewrite is not reversible from the database alone, since the old id is not kept, and it does not need to be: no reader depends on the old value.

## Date

2026-11-05, the plan author (Claude) from the operator's goal, in `plans/completed/video-links-land-on-the-moment.md` (built in its M7; the file is under `plans/active/` until the plan closes); graduated from the plan's Decision Log by its M8 session on 2026-11-06.

## Status

accepted
