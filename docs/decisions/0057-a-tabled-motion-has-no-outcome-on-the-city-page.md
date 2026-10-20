# 0057 — A tabled motion has no outcome: the stored result is the verb the page prints, and "voted against the outcome" is a no on a motion that passed or a yes on one that failed

## Decision

The city page writes a split vote with its stored `votes.result` as the verb (`briefing._result_verb` returns `passed`, `failed`, or `tabled` unchanged and substitutes no other word), and "voted against the outcome" has one definition, `query.AGAINST_OUTCOME_PREDICATE`: a `nay` or `no` on a motion that passed, or a `yea` or `yes` on one that failed. An abstention, and any position on a tabled motion, is a roll call attended and nothing more. The council card's number and the member page's dated Dissent view (`since` given) both use the predicate.

## Rationale

`votes.result` has no CHECK constraint, and its three writers (the minutes parser, the OCR header parser, and `video_ocr`) write `tabled` for a motion set aside, including a tied tally with abstentions. The page's first version read `"passed" if result == "passed" else "failed"` and counted "against" as every present position not aligned with the result, so a motion the council postponed was reported as defeated and every member who voted on it gained one "against"; two closing reviews found the two halves, the count first and the verb a round later. An outside review proposed a `concluded` fallback for a result the code did not anticipate; declined, because a word no row holds is a default (`docs/PRINCIPLES.md`, Source or silence), and the three writers produce only the three words. The undated Dissent view keeps its older, broader filter (`D58`) because the design excludes the member page beyond `since`, and the dated view exists so the card's number and the door it opens agree.

## Date

2026-10-19, the plan author (Claude) revising `plans/completed/birmingham-city-briefing.md` after its first and second closing reviews, applied in M7 and M9; graduated at the plan's retrospective on 2026-10-20.

## Status

accepted
