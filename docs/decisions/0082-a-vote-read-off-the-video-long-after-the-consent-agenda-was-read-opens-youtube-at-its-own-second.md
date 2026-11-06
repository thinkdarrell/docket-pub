# 0082 — A vote read off the video more than 120 seconds after the consent agenda was read opens YouTube at its own second

## Decision

The vote link on a consent item whose moment is the consent block's start (its cue point is inside the block or missing) opens YouTube at the vote's own second when the vote was read more than `CONSENT_GAP_S` (120 seconds) after the block's end and a recording covers that second (`video_links.vote_link`). In every other case the link is the item's, as decision `0079` has it; on Granicus, which can only open a chapter, it stays the block's chapter. This replaces the last sentence of the Decision in `0079`, which gave such a vote no special case; the rest of `0079` stands.

## Rationale

Decision `0079` named the case and left it unguarded: an item pulled off consent and voted on separately whose cue point the clerk never moved sends "Watch this vote" to the reading of the consent agenda. On 2026-11-05 the operator chose to skip a guard and keep a count, 8 of 78 votes read off the video on consent items, of which 2 were votes 1,034 and 4,090 seconds after the block. On 2026-11-06 the same query printed the same 8 of 78, the trigger of the debt row had not fired, and the operator chose to add the guard anyway, before the first recording is measured.

The guard does not tell a pulled item from the consent agenda's own vote, and it does not need to. The other 6 of the 8 are the consent agenda's own vote, read 147 to 331 seconds after the reading ended and attached to the last item of the run; `0079` called the start of the reading the right place for them. A link that says "Watch this vote" and opens at the vote is right for them too, so all 8 open at their own second. Telling the two apart was the alternative (by how many items share the vote) and would have added a read and a second threshold for no better landing; each of the 8 votes is attached to one item.

The threshold is the consent rule's own gap: a vote within 120 seconds of the run's end is treated as part of the reading, by the number that already says which cue points are. The guard is for YouTube alone because `0079`'s reason for one landing on both sites still holds where it can: Granicus opens chapters, and the only chapter such an item has is the block's. So this is the second link, after a discrepancy row, that can land in different places on the two sites. When no recording covers the vote's second the link falls back to the item's moment, which may itself open YouTube at the reading.

Nothing changes on the site until a recording is measured: with no measurement every link opens Granicus.

## Date

2026-11-06, the operator, after the plan's fifth read-only query was run again on production; built by Claude in the session that followed the closing review of plan `video-links-land-on-the-moment`.

## Status

accepted
