# 0079 — A consent item links to the start of the consent agenda, which is found as the largest run of consent cue points at most 120 seconds apart, when that run holds at least three

## Decision

A link that stands for an agenda item uses the item's moment under one rule on both sites (`video_links.consent_block` and `video_links.item_moment`). The consent block of a meeting is the largest run of its consent items' cue points in which neighbours are at most 120 seconds apart, it exists only when that run has at least 3 cue points, and a tie goes to the earlier run. A consent item whose cue point is inside the block, or that has no cue point, links to the block's first cue point; a consent item whose cue point is outside it, and every non-consent item, links to its own. The block's chapter id is the first all-digit id in the run. A vote link on a consent item follows the same rule, with no special case for a vote read off the video after the block.

## Rationale

The clerk reads the consent items out in one quick run, so their individual cue points land seconds apart inside that reading and mean nothing singly; on the meeting of 2026-10-27 about 59 of them span 95 seconds. The operator's rule is that a consent item links to the start of the consent agenda and an item removed from it links to when it is talked about.

The block has to be found from the data. The minimum and maximum of all consent cue points was the obvious way and would have swallowed an item pulled off consent and discussed twenty minutes later, whose `is_consent` flag comes from the printed agenda and stays true. A run with a gap limit leaves that item outside. Fewer than three cue points make no block because a lone consent cue point, or two, is more likely a pulled item than the reading of the agenda. The cue points are ordered by second and then row id, not by `item_number`, which is text and would put "10" before "2". The chapter id is the first all-digit id, not the first item's, so that one item whose id could not be rewritten to a chapter id (decision `0080`) does not cost every consent item of the meeting its Granicus chapter.

An item link uses the item's moment on both sites, instead of the vote's own second on YouTube and the item's chapter on Granicus, because Granicus can only open a chapter and one click should not land in two different places. A discrepancy row is the exception: it quotes specific words, so on YouTube it opens at its own second.

The case not guarded: an item pulled off consent and voted on separately whose cue point the clerk never moved sends "Watch this vote" to the reading of the consent agenda. Counted on production on 2026-11-05 under this rule, 8 of the 78 votes read off the video on consent items fall more than 120 seconds after the block while the item's cue point is inside it or missing; 6 of those are the consent agenda's own vote, where the start of the consent agenda is the right place, and 2 are votes 1,034 and 4,090 seconds later. The operator chose to skip a guard and keep the count as a check (`docs/DEBT.md`).

## Date

2026-11-05, the operator (the rule, and the choice to skip the guard) and the plan author (Claude; the run, its two numbers, and the chapter id), in `plans/completed/video-links-land-on-the-moment.md` (built in its M4 and M5; the file is under `plans/active/` until the plan closes); graduated from the plan's Decision Log by its M8 session on 2026-11-06.

## Status

accepted
