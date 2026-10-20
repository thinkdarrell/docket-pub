# 0060 — An amount reaches the city page's prose only when the item's own text backs it

## Decision

The opener, "Where the money went", the transcript door, and the `order=amount` search page write an item's amount only when `briefing.passes_dollar_check` holds: the title and description together hold exactly one dollar amount and it equals the stored `dollars_amount`, or the headline holds a figure `h` within `min(p / 2, h / 10)` of the stored amount, `p` the largest power of ten dividing `h`. An item that fails is passed over for the next largest and keeps its stored amount on the meeting and item pages. The amount written is always the stored one, and the `order=amount` page applies the same check so the first row a reader meets after "More →" is the door's first line.

## Rationale

`dollars_amount` is extracted at scrape time and can be the wrong figure from a text that names several: the KultureCity item stores $39.5 million, the campus total, where the city's contribution is $7 million. `docs/PRINCIPLES.md` Source or silence forbids quoting a number the source does not plainly state. The equality in the first condition guards a stale stored amount against a text with one figure. The cap in the second exists because "$10 million" has `p = 10,000,000`, and without the cap it would accept any stored amount from 5 to 15 million; an external review of the plan found this before any milestone ran, and with the cap 9,600,000 passes and 14,000,000 fails. Relaxing the first condition for a text with several figures and no headline figure was proposed and declined: keeping such an item out of the prose is the intended silence, and the item is still on its own pages.

## Date

2026-10-19, the plan author (Claude, cycle-plan) and the operator from an external review, in `plans/completed/birmingham-city-briefing.md`, applied in M1 to M3; graduated at the plan's retrospective on 2026-10-20.

## Status

accepted
