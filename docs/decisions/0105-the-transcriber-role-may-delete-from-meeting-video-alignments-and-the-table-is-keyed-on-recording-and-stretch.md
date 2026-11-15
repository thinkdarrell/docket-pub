# 0105 — The transcriber role may delete from `meeting_video_alignments`, and the table is keyed on recording and stretch

## Decision

`meeting_video_alignments` is keyed on `(meeting_video_id, stretch)` (migration 046), and the `transcriber` database role holds DELETE on it beside SELECT, INSERT, and UPDATE, so a re-measure replaces a recording's stretch rows: the recording's rows are deleted and the new ones inserted in one transaction. The grant is written in `scripts/sql/create_transcriber_role.sql`, and on a database where the role already exists the owner runs `GRANT DELETE ON meeting_video_alignments TO transcriber;` by hand.

## Rationale

Decision `0076` gave the role SELECT, INSERT, and UPDATE on this table and withheld DELETE, because a recording then had one row and a re-measure was an upsert on `meeting_video_id`. Decision `0104` stores one row per confirmed stretch, and an upsert cannot remove a stretch the new measurement does not have: a recording measured as two stretches and then as one, or as rejected, would keep a stale second row, and the site would go on linking into it.

The rule of decision `0030` is that the role writes only its own tables, not that it never deletes; it already deletes from its transcript tables, and this table is its own. Nothing else of `0076` changes: the table is still separate from `meeting_videos`, the role still only reads `meeting_videos`, and still no migration grants anything to the role.

The schemas that avoid the grant were rejected. A parent row per recording holding the verdict and a stretch count, with the stretch rows beneath it, lets the writer leave stale rows above the count; rows marked superseded do the same with a flag. Each adds a second fact that every reader, the site's link builder and the transcriber's candidate query, must agree on, and a reader that forgets it links into a stretch that no longer exists. A delete leaves one fact, the rows.

The key is the pair, with no sequence and no surrogate id, so the role needs no sequence grant and every insert that names no `stretch` still lands as stretch 1 through the column default. No CHECK ties `stretch = 1` to a row that is not `passed`: the owner's off switch sets every passed row, later stretches included, to `rejected` and back (`docs/specs/video-links.md`, The measurement table).

## Date

2026-11-12, the plan author (Claude) from the operator's scope brief, in plan `youtube-links-cover-matching-stretches` (built in its M2 on 2026-11-15); graduated from the plan's Decision Log by its M4 session on 2026-11-15.

## Status

accepted
