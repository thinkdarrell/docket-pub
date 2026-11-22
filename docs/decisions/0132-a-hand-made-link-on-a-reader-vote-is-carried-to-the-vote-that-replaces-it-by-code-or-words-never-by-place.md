# 0132 — A hand-made link on a reader vote is carried to the vote that replaces it, found by its code or its words and never by its place

## Decision

When a meeting's reader votes are replaced, every `vote_agenda_items` row of an old vote that is `is_manual` or not `is_active` is inserted again, unchanged, on the new vote that is the same vote: the one new vote with the old vote's code where one old and one new vote carry that code, otherwise the one new vote with the same `raw_text` where one old and one new vote carry it. A link whose vote is not found that way is dropped and logged. A link the code join made is not carried.

## Rationale

`_replace_votes` deletes and inserts, so every vote gets a new id and its links go by cascade; `link_votes_by_code` then saw a coded vote with no link and attached it again, putting back a link an admin had removed (`D194`, the third important finding of the closing review of plan `mobile-votes-from-minutes`). It is reachable at `READER_VERSION` 1, when a file on a meeting's own event takes the meeting from a file on another event.

The debt row named two mends, both by `external_id`: keep the vote's row, or carry the link. A reader vote's `external_id` is its place in the file (`<meeting>-mv-<n>`). The reason to raise `READER_VERSION` is that the reader now reads a file differently, and one vote found or lost early in a file moves the place of every vote after it; a link carried by place would then sit, at full confidence and marked as set by hand, on a vote nobody linked. The code is what the city printed for the vote and does not move, and the vote's own words are the next best thing. Where neither tells the vote apart the link is dropped: no link is the honest state (`docs/PRINCIPLES.md`, Source or silence), and the log line says a hand-made link was lost. The cost is that a removed link on a coded vote whose code the new reading no longer gives to exactly one vote is not kept, and the join may attach that vote again.

Updating rows in place instead of replacing them would keep ids and every link, but needs the same matching to decide which row is which, and leaves three statements (update, insert, delete) where the plan measured two inserts per file.

## Date

2026-11-22, the operator's session that mended the closing review's findings before pull request #193 merged (Claude, at the operator's request).

## Status

accepted
