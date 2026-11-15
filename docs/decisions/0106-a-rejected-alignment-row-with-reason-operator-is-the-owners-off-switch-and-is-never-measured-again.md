# 0106 — A `rejected` row of `meeting_video_alignments` with reason `operator` is the owner's off switch, and it is never measured again

## Decision

The owner sends every YouTube link back to Granicus by setting the `passed` rows of `meeting_video_alignments` to `rejected` with the reason `operator`, and that reason on a `rejected` row is reserved for it. Such a row is never a candidate for the measuring pass, by its version or by its clip id (`_ALIGNMENT_UNMEASURED` in `transcriber/transcriber/db.py`), migration 046 does not delete it, and the restore sets it back to `passed` and clears the reason. Both statements are in `docs/runbooks/transcripts.md`, "Measuring YouTube recordings (the backlog)".

## Rationale

The site reads `passed` rows alone, so the switch has always been an UPDATE of the status, and nothing marks a switched-off row except its reason. Decision `0104` gave a row that is not `passed` the method version (3) as its floor, and every passed row on production sat at version 2, so a switched-off row was a candidate under the rule as that plan's M2 wrote it: ordinary transcriber runs would have downloaded those recordings again and written fresh `passed` rows, 20 recordings a run, and the links would have come back on. Migration 046's DELETE of the rows rejected at version 2, as first written, would have removed the same rows outright had the switch been on when it ran. Neither happened: the rule and the statement existed only on the plan's branch, the closing review showed the fault with the candidate query on a throwaway database, and the switch has never been run on production. The candidate query is therefore the one reader of `reason`, and the migration's DELETE names it too.

The alternative was to have the switch also set `method_version = 3`. It is one clause shorter. It leaves migration 046 deleting switched-off rows when the switch is on at the deploy, it writes a method version onto rows that method never produced, and it holds only as long as the operator remembers the clause.

The exemption covers the clip clause as well as the version clause, because a switch that a re-uploaded clip can undo is not a switch; once restored, a row is `passed` and every ordinary rule applies to it again. It is for `rejected` rows only: a `passed` row with the reason `operator` is a row passed by hand (row 832) and answers to the ordinary rules. The restore clears the reason because a restored row that kept `operator` would read as passed by hand, which is true of row 832 alone; the cost is that a round trip of the switch clears row 832's reason too, and its record is then the runbook's History entry of 2026-11-12. The comparison is `IS DISTINCT FROM`, never `<>`: `reason` is NULL on an ordinary `passed` row and may be NULL on a rejection, and `NULL <> 'operator'` is not true, which would drop those rows from the candidates and keep them through the migration.

The switch covers the rows that exist when it is run. A recording measured afterwards gets `passed` rows of its own; holding the switch as a state needs a setting the writer reads, which is deferred (`D153`).

## Date

2026-11-15, the operator's answer to the closing review of plan `youtube-links-cover-matching-stretches`, which found that the switch no longer held after that plan's M2; written into the plan's Decision Log by the revising session (Claude), built and graduated by the plan's M5 session on 2026-11-15.

## Status

accepted
