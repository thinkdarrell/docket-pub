# 0059 — The opener is counted per request; only the heavy vote facts are precomputed, by one upsert per city after vote matching

## Decision

`briefing.opener_facts` counts the last and next meeting's facts at request time from single-meeting queries, behind the page's five-minute cache, and only the split votes of the last 180 days, the unanimity fallback, and the per-member twelve-month counts come from `city_briefing_facts (municipality_id, fact_set, payload, computed_at)`, rebuilt for every flagged city by the `briefing_facts` task at 09:45 America/Chicago with one `INSERT ... ON CONFLICT DO UPDATE` carrying both rows per city. A stale row is reported on source health, not on the page.

## Rationale

The next-meeting clause depends on the clock (a meeting stops being upcoming three hours after it starts), so a once-a-day row would name a meeting that already happened for most of a day, and the last-meeting clause touches one meeting's indexed rows. The member aggregate over a year of votes and the split-vote scan are the queries the old route had switched off for cold-load cost, and the design forbids a cold load slower than the old page's. 09:45 is after the daily ingest (06:00), `vote_matching` (09:00, which decides what a split vote names), and `process_badges` (09:30); earlier, the row would be computed from yesterday's links. One statement per city is `docs/PRINCIPLES.md` Production is not a sandbox. The two alternatives were the old route's TODO (everything per request, which it had abandoned) and everything precomputed, which would have put a stale "next meeting" on the first screen.

## Date

2026-10-19, the plan author (Claude, cycle-plan) in `plans/active/birmingham-city-briefing.md`, applied in M1 and M2; graduated at the plan's retrospective on 2026-10-20.

## Status

accepted
