# 0110 — A neighborhood meeting's date is computed from the rule the city's schedule prints, and from nothing else

## Decision

A neighborhood association is given dates only by the monthly rule printed in the city's published schedule PDF, which is the one source of the schedule and is saved in the repository beside its hand transcription. A row whose rule does not state a recurring day is given no dates and is named on the page with the schedule's own words: for the 2026 schedule, Glen Iris ("First Monday of this month @ 6:30 pm") and Bridlewood ("No Meetings"). No date is moved or annotated for a holiday, and no date is produced for a year other than the schedule's.

## Rationale

`docs/PRINCIPLES.md`, "Source or silence". "Fourth Monday @ 6:00 p.m." (East Birmingham) is read as every month, as every other row of a monthly schedule is, and Overton is given the six months its row names. "Of this month" names one month of a document revised on February 3 and does not say which rule holds after it, and "No Meetings" beside a printed rule is the city saying the association is not meeting; a date for either would be docket.pub's guess. Naming the two on the page tells a member of either why the association is absent.

A holiday note was proposed in review. It would be a claim by docket.pub and needs a city document to link; a search on 2026-11-16 found no holiday list published by the City of Birmingham for 2026. The page says instead that a meeting moved for a holiday is not reflected (`D156`).

The city's spreadsheet of the schedule was considered as a way to spare the transcription. The one found on 2026-11-16 covers 2023 to 2025 and is a year older than the PDF, so a draft made from it would carry rules the city has since changed into a file whose every row is then checked against the newer PDF by eye: more places to go wrong, not fewer. The PDF is transcribed by hand, the loader refuses the file when the saved PDF's digest is not the one recorded, a test compares every row with the PDF's own table on every run, and a person reads a generated sheet against the PDF.

Stopping at the schedule's year is the same rule. The 2026 schedule says nothing about 2027, and a rule carried forward would print dates under a link to a document that does not cover them. The cost is that the neighborhood section is empty from January 1 until the next schedule is saved (`D161`).

## Date

2026-11-16, the plan author (Claude) of plan `birmingham-coming-up`; the holiday note declined by Darrell Nance (operator) on Claude's recommendation, and the spreadsheet declined by Claude and reported to the operator, the same day. Built by the plan's M4 and M5 sessions on 2026-11-17.

## Status

accepted
