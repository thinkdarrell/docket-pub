# 0107 — One public hearing is told from another by its date, its kind, and the opening of its subject, never by a case number

## Decision

Two agenda items set the same hearing when their readings have the same date and the same kind and their subject keys are equal, or one key opens the other, the shorter is at least 90 characters (`PREFIX_MIN` in `src/docket/enrichment/hearings.py`), and it opens exactly one hearing of that date and kind. A weed-lot hearing's key is its property count. A short key that opens two or more hearings joins none and stands as its own hearing.

## Rationale

The obvious key is the case number. It sits at the end of the resolution's sentence, and Birmingham's stored titles from before about May 2026 are cut at 255 or 256 characters, so it is missing from every cut title. What a cut title does hold is the opening of the subject, so the opening is the key: the subject after the hearing's date, with bracketed notes and the "(Submitted by" tail removed, reduced to lower-case letters and digits.

The threshold was 40 characters as first written. A written review before any milestone ran pointed out that the words every zoning hearing shares ("to consider the adoption of an Ordinance TO AMEND THE ZONING DISTRICT MAP OF THE CITY OF BIRMINGHAM") reduce to 82 characters and the vacation wording to 58, so a title cut inside that wording gave a key that opens every such hearing of its day and would have been folded into whichever came first. Ninety is past both. Ninety alone is not enough: item 2116's key is 100 characters and ends at the last digit of its case number, so a title one character shorter would open two case numbers that differ in the next digit. Hence the one-candidate rule, and the order in which groups are made (longest key first), so the answer does not depend on which item has the lower id.

The pairs the rule was built on are tests: items 62830 and 62881 carry identical text and are one hearing; item 3297 amends item 3339's hearing, its key is 101 characters, and 3339's opens with it; items 1680 and 1681 are two zoning hearings of one day that differ inside the first 100 characters; items 1152 and 1153 are two vacations of one day that differ at the square footage.

What is given up, on purpose: a cut title with fewer than 90 characters of subject becomes a second entry for a hearing already listed, and two different weed-lot resolutions that set one day and list the same number of properties are stored as one. A doubled entry can be seen and reported; a hearing folded into another cannot. `D158` in `docs/DEBT.md` holds both.

## Date

2026-11-16, the plan author (Claude) of plan `birmingham-coming-up`, corrected the same day by Claude after a second written review the operator asked to have assessed; built by the plan's M1 and M2 sessions on 2026-11-17.

## Status

accepted
