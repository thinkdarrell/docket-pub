# 0056 — The city page counts one vote source per meeting, minutes first, through a fragment its caller scopes

## Decision

Every count on the city page (the opener's vote sentence, "Where they disagreed", the council cards' twelve-month numbers, the meetings list's split count, and the member page under `since`) takes one source per meeting through `briefing.chosen_source_cte(scope)`: `minutes_text` when the meeting has any vote from the minutes with `needs_review` false, otherwise `manual`, then `api`, then `video_ocr`; votes flagged `needs_review` are excluded everywhere, and a clause counted from video votes says "from the video". The fragment takes the caller's condition on `v.meeting_id` and is never written unscoped.

## Rationale

Decision `0005` keeps OCR and minutes votes side by side and forbids merging them. A page that counted both sources for one meeting would count each roll call twice, and one that chose per vote would mix the two inside one number. Choosing per meeting, minutes first, is the smallest rule that yields one number without adjudicating: a human-written record outranks a machine reading of the vote board, and where both exist the meeting page and the minutes-versus-video page still show the disagreement. The first draft's order, `min(v.source)`, gave the same answer for the values migration 001 allows but said nothing; the explicit order says why.

The scope argument exists because an unscoped `GROUP BY v.meeting_id` over all of `votes` is computed in full whenever the planner cannot push the outer meeting filter into the aggregate, so the opener's single-meeting query would have paid for every vote in every city on each cold load; an external review of the plan found this before any milestone ran. Scoped, every caller stays on `idx_votes_meeting`. The undated member page predates the rule and keeps its own filter (`D58` in `docs/DEBT.md`).

## Date

2026-10-19, the plan author (Claude, cycle-plan) and the operator from an external review, in `plans/active/birmingham-city-briefing.md`; graduated from the plan's Decision Log at its retrospective on 2026-10-20.

## Status

accepted
