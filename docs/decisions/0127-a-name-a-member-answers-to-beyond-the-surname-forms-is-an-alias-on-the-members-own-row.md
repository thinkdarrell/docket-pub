# 0127 — A name a member answers to beyond the surname forms is an alias on the member's own row

## Decision

Where a city's documents print a member under a name the variant list does not produce, the name is stored in `council_members.aliases` on that member's row and `RosterIndex` answers to it inside the member's own term, compared as any stored name is. An alias two seated members share resolves to nobody. Mobile's Scott Jones carries the alias `Scott`, and his term ends 2023-04-11.

## Rationale

Mobile's roll calls from 2021-11-02 to 2022-07-19 list `Scott` in the seventh place while votes in the same minutes list `Jones`: on 2021-11-09 the roll call reads `Penn, Carroll, Reynolds, Daves, Scott and Gregory`, 19 votes list `Scott`, 4 list `Jones`, and a waiver is "seconded by Councilmember Jones"; across the 1,275 votes of those months none lists both names. They are one member. The resolver answers to a surname or an initial with a surname, so `Scott` resolved to nobody and 472 printed positions would have stayed unresolved.

The obvious alternative was to add first names to every member's variants. That would change what Birmingham's stored names resolve to, for evidence about one member in one city; an alias is that evidence, stored where it applies and dated by the member's term.

The end of his term moved from 2023-08-08 to 2023-04-11 because the roll call of 2023-04-04 is the last that lists him and that of 2023-04-11 the first that does not; the seat was vacant until Josh Woods's term began, and under decision `0004`'s half-open window the date of the first roll call without a member is the end of his term. Two votes of 2023-04-25 print `Jones` among seven ayes while that meeting's roll call lists six; those two names stay unresolved, shown as printed, which is what an unresolved row is for.

## Date

2026-11-21, the authoring session of plan `mobile-votes-from-minutes` (Claude), from the roll calls of the city's minutes files 185, 160, 213 and 253; built by that plan's M2 (migration `050_minutes_votes`) and graduated by its M6 session on 2026-11-22 (UTC).

## Status

accepted
