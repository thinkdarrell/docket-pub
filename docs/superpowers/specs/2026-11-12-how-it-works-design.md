# How it works: the path of an item through the Birmingham City Council

Date: 2026-11-12. Status: initial plan, awaiting the operator's approval. This is a design and phased plan, not an ExecPlan; each phase below becomes its own ExecPlan under `plans/active/` when it is started.

## 1. Intent

docket.pub tells a reader what the council voted on. It does not tell them how a thing got to that vote, or what happens next. A reader who sees "failed 3–6" on an ordinance has no way to know that the ordinance passed 8–0 a week later, and that the first vote was not a rejection at all.

This work adds a Birmingham-only section that shows how an item moves: who can submit it, how it reaches a committee and how it gets out, what first and second reading mean, when a public hearing is required, how the consent agenda works, what the vote needs, and what the Mayor does afterwards. The section is built around one visual path. A reader picks a real item and watches it travel along that path, jumping to the video moment, the transcript, or the city's document at each stop. The same path appears in miniature on every item, as a progress strip that links back to the explainer.

The reader is someone curious about what is happening and how the machinery works. It is not a glossary.

## 2. Goals, non-goals, anti-goals

Goals:

- One page that explains the whole path, each claim quoting the rule that governs it and linking to that rule.
- Real items walked through the path, with a link at each stop to the recording, transcript, minutes, or agenda for that day.
- A progress strip on item cards and item pages that says where the item is on the path and links back to the explainer with that item selected.

Non-goals:

- Other cities. Birmingham only.
- General civics. Nothing goes on the page because "that is how councils work"; only what Birmingham's own sources say.
- Predicting outcomes or saying what "should" happen next beyond what a rule states.

Anti-goals (the work has failed if any of these is true, even if everything renders):

- A stop on the path is shown as having happened when the records do not show it. The rules say every item goes to a committee; the records often do not show that it did. The strip must say "not in the record", not draw a tick.
- A rule is paraphrased without its source, or a rule from general Alabama law is presented as Birmingham's where the two differ.
- The strip makes a held-over ordinance look defeated, or a consent item look individually debated.

The repository's principles apply as written, in particular "Source or silence" and "Framing follows the data" in `docs/PRINCIPLES.md`.

## 3. What the rules say

Every statement in the explainer must trace to one of the sources below. Section numbers are given so the builder can quote them exactly. Text copies of every source, with public addresses and the date each was read (2026-11-12), are in `content/how-it-works/birmingham/sources/` (see its `README.md`). The General Code chapter there was saved from Municode by the operator in a browser, because Municode refuses automated readers. The page links the public address and quotes from these copies.

Sources:

- **General Code of the City of Birmingham, Title 2, Chapter 2, Article A**, "Meetings, Rules, Procedures and Enactment of Legislation" (§§2-2-1 to 2-2-18). This is the council's rulebook; there is no separate Rules of Procedure document. The council's own Resolution 1958-25 (2025-11-04) appoints committees "in accordance with §2-2-14 of the Birmingham City Code".
- **Mayor-Council Act**, as codified at Ala. Code §45-37A-52 and following (the copy on the city's website is stale and must not be quoted for §§3.06, 3.07, 3.10).
- **Alabama Code**, general law: §11-45-2, §11-45-8, §11-52-77, §23-4-2, §§11-67-60 to -64, §11-53B-4, §28-1-6.
- **Birmingham Zoning Ordinance**, July 2026 edition, Title 1, Chapter 9, Article II.
- **The "Statement of Conduct of Business"** printed on every council agenda.
- **The Citizen's Handbook 2024**, a council publication (useful for plain statements; it is out of date in places, for example it says eleven committees).
- **Council minutes and committee minutes**, as evidence of practice.

What they establish:

| Step | Rule | Source |
| --- | --- | --- |
| Who can submit | "a councilmember, the mayor or city attorney". Nothing is considered unless a councilmember sponsors it by moving its adoption. | Code §2-2-15(c) |
| Drafting | Ordinances and resolutions are prepared by the City Attorney on the council president's written request, or reviewed by the City Attorney for form and legality. | Code §2-2-15(a) |
| Agenda deadline | To the City Clerk by 5:00 p.m. Wednesday. A late item needs unanimous consent, or an addendum approved by the council president at least 24 hours before the meeting. | Code §2-2-3 |
| Mayor's recommendation | Everything is "submitted to the mayor for his or her administrative recommendation" on introduction. | Code §2-2-15(b) |
| Into committee | "Unless waived by unanimous consent, every ordinance or resolution requiring council approval shall be submitted to a committee of the council prior to submission of the item to the council." | Code §2-2-15(c)(2) |
| Out of committee | The committee reports at the next regular council meeting after it meets, unless the council grants more time; the council may take the item as reported, with the committee's amendments or substitutions. | Code §2-2-15(c)(2) |
| Referral by vote | A motion to refer must set a time of no more than 21 calendar days, or the next council meeting after the committee meets, whichever is less. | Code §2-2-15(c)(5) |
| Discharge | A majority of members voting, never fewer than four, can discharge a committee; the item returns for final action at the next regular meeting. | Code §2-2-15(c)(5) |
| Committees decide nothing | "No action of any committee including the committee of the city council as a whole shall be considered final without a formal vote of the full council at a regular council meeting." | Code §2-2-14(b) |
| Committee membership | Appointed by the council president, subject to council approval. Quorum of two. Public participation is at the chair's "complete discretion". | Code §2-2-14(a) |
| What a committee does in practice | Recommends to the council agenda, recommends to the consent agenda, forwards "with NO Recommendation", or takes "No Action – Information Only". The Handbook: committees "don't have the power to 'kill a bill.'" | Committee minutes Sept–Oct 2026; Handbook p. 9 |
| Order of business | Roll call; minutes; communications from the Mayor; boards and agencies; consent agenda; final passage; introduction and first reading; old and new business; requests from the public; presentations; adjournment. | Code §2-2-7 |
| Consent agenda | Routine items approved by one motion. A councilmember or the Mayor can remove any item; a citizen can ask that a `(ph)` item be removed so its hearing is held. A removed item returns to its normal place. | Statement of Conduct of Business |
| First reading | No ordinance "of permanent operation" passes at the meeting where it is introduced "except by unanimous consent of all members of the council present". A unanimous vote to pass counts as the consent. | Ala. Code §45-37A-52.64 |
| Postponed items | A postponed item returns on the date it was postponed to, without being resubmitted. An item that fails must start over unless reconsidered. | Code §2-2-15(c)(6), (7) |
| Quorum and votes | Quorum is five. "All measures shall be adopted by the vote of at least four councilmembers." | Code §2-2-4; Ala. Code §45-37A-52.64 |
| Five-vote cases | Budget amendments and additional appropriations need five votes and the Mayor's written recommendation or approval. | Ala. Code §§45-37A-52.128, 52.134 |
| Public hearings | Held "where required by law, or by unanimous consent". Written requests to speak are heard first. Three minutes each unless extended. | Code §2-2-11(b), (d) |
| Speaking on a non-hearing agenda item | Three minutes, following council presentations. | Code §2-2-7(9)a |
| General public comment | Sign the list before the meeting; three minutes; thirty minutes in total; not at two consecutive meetings. | Code §2-2-11(a), §2-2-7(9)b |
| Speaking in committee | A resident may ask to address a committee on a matter referred to it; the request goes through the City Clerk to the chair. | Code §2-2-11(c) |
| After the vote | The Clerk transmits to the Mayor within 48 hours. The Mayor has 10 days from passage to veto in writing; no action counts as approval. Override takes two-thirds of the members elected (six of nine). No veto over council appointments or investigations. | Ala. Code §45-37A-52.64 |
| Taking effect | Ordinances of a general or permanent nature take effect on publication. Rezonings take effect on the newspaper announcement. Franchises wait 30 days. | Ala. Code §11-45-8(b); Zoning Ord. Art. II §6; §45-37A-52.65 |
| Rezoning's own route | Zoning Advisory Committee or Planning Commission, then the council's Planning and Zoning Committee, then a council hearing on at least 22 days' published notice. Deemed denied if the council takes no final action within 180 days of filing, or 90 days after the committee receives it. | Zoning Ord. Art. II §§3–4 |
| Hearing notice by type | Right-of-way vacation: four weekly notices, 30 days' mail. Weed abatement: certified mail 21 days ahead, two weeks of newspaper notice, signs seven days ahead. Budget: at least seven days after publication. | Ala. Code §23-4-2, §§11-67-61 to -63, §45-37A-52.128 |

Open questions the explainer must state as open, not resolve by assumption:

1. **Rule against practice on committees.** The code says every item goes to a committee unless waived by unanimous consent. Many agenda items show only "(Recommended by the Director of …)" and no committee. Whether those were waived, or whether the Committee of the Whole reference in §2-2-15(c)(4) covers them, is not shown in any record read so far. The page says what the rule is and what the agenda shows, side by side.
2. **Four votes or five for a permanent ordinance.** Both Birmingham-specific sources say four. General law §11-45-2(b) says a majority of members elected. The page quotes the Birmingham rule and notes the general-law wording; it does not rule on the conflict.
3. **The `**` marker** on agenda items is not defined anywhere read. Do not explain it.
4. **Who designates consent items.** Budget and Finance minutes show the committee recommending consent placement; no rule read assigns the choice.
5. **The legal basis for liquor-licence and inoperable-vehicle hearings.** They are marked `(ph)` on every agenda; the code sections that require them sit in other titles of the General Code that have not been read.
6. **Current committee list.** Resolution 1958-25 (2025-11-04) names six committees and the Committee of the Whole. The city's website now lists eight. The date and instrument of the change have not been found.
7. **§2-2-19.** An ordinance on the 2026-06-16 agenda proposed adding electronic attendance at §2-2-19; the saved copy of the code shows it as reserved.

Items 5 to 7 need a person with a browser or a call to the City Clerk (205-254-2294). None blocks Phase 1.

## 4. What docket.pub holds today

Measured on production, read-only, 2026-11-12. Counts are pattern matches on stored item text and are lower bounds, because older items often store only a short title.

- 58,437 Birmingham agenda items, 2008-02-26 to 2026-11-11; 38,331 are consent items.
- The city's agenda writes the process onto each item: `CONSENT`, `(ph)` for a public hearing, `P` for permanent operation, `[First Reading]` and `[Second Reading]`, "(Submitted by …)", "(Recommended by …)" naming committees, the Mayor and department heads, "(NOT Recommended by …)", "NO Recommendation", and "(Did Not Receive Unanimous Consent, Held Over from M/D/YYYY to M/D/YYYY)".
- How often each appears in stored text: `(ph)` 9,944; "recommended by" 6,484; `P` 1,524; first reading 635; second reading 48; no or not recommended 42; held over or deferred from 66.
- **The `P`, `(ph)` and section-heading markers are stored on the wrong row.** The city prints them before the item number (`P ITEM 16.`, `(ph) ITEM 9.`), and the item-marker pattern in `src/docket/analysis/agenda_parser.py` accepts only a `CONSENT(...)` prefix. So a `P` or a bare `(ph)` lands at the end of the previous item's text, a section heading lands at the end of the last item of the section before it, and a `CONSENT(ph)` prefix is consumed and kept nowhere. Production shows it: item 58893 (agenda item 16) ends "… Committee) ** P", which is item 17's marker, and item 59026 ends "… INTRODUCTION AND FIRST READING OF ORDINANCES AND RESOLUTIONS P". The `P` and `(ph)` counts above therefore count the right number of markers on the wrong items. The bracketed markers inside the item's own text (`[First Reading]`, `[Second Reading]`, "Recommended by", "Held Over from") are on the right row. This describes rows made from the agenda PDF; rows made from Granicus index points are a second text shape the Phase 3 builder inspects before parsing them.
- Full item text with the recommendation line is mostly a 2026 phenomenon: 1,695 of 2,926 items in 2026 carry it, against 369 of 3,270 in 2025.
- What is stored as structure today: `is_consent`, and `sponsor` from "Submitted by" (11,960 items). "Recommended by" is parsed in `src/docket/enrichment/sponsors.py` and discarded. `(ph)` is recognised by the item-marker pattern in `src/docket/analysis/agenda_parser.py` and not stored. `agenda_items.section` is NULL on every row. The AI-extracted `next_steps.committee_referral` is filled on 14 rows.
- Nothing links one item's appearances across meetings.
- Committee meetings exist as meetings (named by body, with YouTube recordings) but carry almost no agenda items: 55 items under committee meetings against 58,306 under council meetings. Committee agendas and minutes are published on birminghamal.gov and are not ingested.
- **A finding that Phase 3 must fix.** When an ordinance fails to get unanimous consent at first reading, the minutes record a roll call, and the site stores it as an ordinary vote with result `failed`. Vote 12206 (meeting 2237) reads "failed, 3–6" on an ordinance that was adopted 8–0 the following week. Today that is shown to readers as a defeat.

## 5. The path

The stops, in order, with the side routes. Names are the reader-facing words; the builder may adjust wording but not meaning.

1. **Submitted**: by a councilmember, the Mayor, or the City Attorney, to the Clerk by Wednesday 5 p.m.
2. **Committee**: reviews and recommends, or forwards without a recommendation. Cannot decide.
3. **On the agenda**: under consent, final passage, or first reading.
   - Side route, **Consent**: one motion for the group; any councilmember or the Mayor can pull an item.
   - Side route, **Public hearing**: for items marked `(ph)`; held when the item is called.
4. **First reading**: an item of permanent operation is introduced. With unanimous consent it can pass the same day.
   - Side route, **Held over**: one objection sends it to the next meeting as a second reading.
5. **Final vote**: quorum five, at least four votes.
6. **Mayor**: ten days to sign or veto; silence is approval.
7. **In effect**: on publication, where publication is required.

An item's position is only ever what its own records show. A stop with no record is drawn as "not in the record".

## 6. The sample journey: the parking-fines ordinance

This is the first journey the explainer ships with, and the test case for every phase. Every fact below was read from production on 2026-11-12; ids are `agenda_items.id`, `meetings.id`, and `votes.id`.

The item: "An Ordinance to amend Title 8, Chapter 3, Section 10, 'Summary Disposition of Minor Traffic and Other Minor Offenses by Fine Schedule' to revise the fines for the summary disposition of municipal parking offenses, to add certain offenses previously omitted from the summary disposition schedule, and to provide for an administrative fee to cover certain expenses for tickets referred for collection." Submitted by the City Attorney. Recommended by the Transportation and Infrastructure Committee. Marked `P`.

It travelled with a sibling ordinance amending Title 8, Chapter 3, Section 8 (items 58894 and 59025), which followed the same route. The journey shows the Section 10 ordinance and mentions the sibling.

| Stop | Date | What the record shows | Record |
| --- | --- | --- | --- |
| Submitted | not in the record | Submitted by the City Attorney. The submission date is not published. | item text |
| Committee | 2026-05-11 | Transportation and Infrastructure Committee, item VI, "Parking Reform Update", presented by Christine Argo, Deputy Director of the Department of Transportation: raise parking fines by $10 across the board (unchanged since 2009) and add a $3 administrative fee for citations unpaid after 30 days. Councilors present: O'Quinn, Smith. "Councilor O'Quinn Motioned to Approve, including the amendment increasing the fine under Section 10-9-16(A) to $60 for commercial vehicles. Councilor Smith Seconded the Motion. Item Recommended to the City Council Agenda." The item is not on that meeting's posted agenda. The recording is YouTube `MiL1mYay0eQ`; the moment in it has not been located and there is no transcript. | meeting 3142; committee minutes, `content/how-it-works/birmingham/sources/committee-transportation-minutes-2026-05-11.txt` |
| First reading, listed and withdrawn | 2026-05-19 | Item 16 under "Introduction and First Reading", marked `P` and `[First Reading]`. When it was called, the Clerk said the item "has been requested to be withdrawn by the mayor's office"; the President: "Item 16 and 17 are withdrawn." No roll call. This is the machine transcript at 2,486 to 2,507 seconds; the builder checks it against the recording and the adopted minutes before quoting it. | item 58893, meeting 2232, transcript segments at 2486–2507 s |
| First reading, voted | 2026-05-26 | Item 11, again `[First Reading]`. Councilmember Williams moved adoption, seconded by Councilmember Smith. Ayes: Gunn, Vasa, Woods. Nays: O'Quinn, Smith, Smitherman, Williams, Tate, Alexander. The Presiding Officer "declared the ordinance not adopted due to the item being an item of permanent operation and therefore needing unanimous consent to be adopted at it's first reading. The item was held over to the meeting of June 2, 2026 for a second reading." Later in the same meeting Councilmember Woods moved, seconded by Councilmember Smith, that it "be adopted on its first reading"; the minutes record the roll "for unanimous consent" with the same three ayes and six nays, and it was again "declared … not adopted and held over". So the minutes hold two roll calls on this ordinance that day, both stored with result `failed`. | item 58990, meeting 2237; vote 12206 (linked to item 58990) and vote 12219 (the second motion, linked to no item) |
| Held over | 2026-05-26 to 2026-06-02 | The next agenda carries the note "(Did Not Receive Unanimous Consent, Held Over from 5/26/2026 to 6/2/2026)". | item 59026 text |
| Final vote | 2026-06-02 | Item 11, `[Second Reading]`. Adopted **as amended** as Ordinance No. 26-61; the amended title adds "to increase fines for certain on-street parking offenses". Ayes: Gunn, O'Quinn, Smitherman, Vasa, Williams, Woods, Tate, Alexander. Nays: none. The item is at 5,313 seconds in the recording. | item 59026, meeting 2238, vote 12271 |
| Mayor | not in the record | The ten-day window ran to 2026-06-12. The site holds no record of signature or veto. | none |
| In effect | not in the record | Effective on publication; the site holds no publication record. | none |

Why this journey: it shows a committee recommendation, a withdrawal at the Mayor's request, a first reading, the unanimous-consent rule biting, a week's delay, an amendment on the floor, and a final vote that differs from the first, all from the city's own minutes. It also shows three honest gaps. And it is the case the site currently gets wrong: vote 12206 is displayed as a failed vote.

Transcripts exist for meetings 2232 and 2238 (status `compared`) and 2237 (`needs_review`); the committee meetings have recordings and no transcript.

Three further journeys, traced on production and in the committees' minutes on 2026-11-12. Meeting ids are `meetings.id`; every council meeting below has a Granicus recording, and every committee meeting a YouTube recording and no transcript.

**A rezoning with a split recommendation and a hearing: case ZAC2026-08007.** An ordinance to rezone 1259 Huffman Road from D-3 Single-Family Residential to C-1 Neighborhood Commercial, for a new Boys & Girls Club of Central Alabama.

| Stop | Date | What the record shows | Record |
| --- | --- | --- | --- |
| Zoning Advisory Committee | not in the record | The council agenda says "(NOT Recommended by the ZAC)". The site holds no ZAC record. | item 62781 text |
| Committee | 2026-09-08 | Planning and Zoning Committee, under "Zoning Cases": "Councilor O'Quinn Motioned to Approve. Councilor Tate Seconded the Motion. Item Recommended to the City Council Agenda." | meeting 3172; committee minutes, https://s3.us-east-2.amazonaws.com/assets.birminghamal.gov/s3fs-public/2026-09/PLANNING%20AND%20ZONING%20COMMITTEE%20MEETING%2C%20September%208%2C%202026.pdf |
| Hearing set, first reading | 2026-09-15 | Item 98, marked `[First Reading]` (read from production 2026-11-13): "A Resolution setting a public hearing October 13, 2026, to consider the adoption of an Ordinance" for this case. Cue at 3,320 seconds. Two video-OCR votes are linked to this item (12340 and 12341); the journey quotes no tally here until the minutes settle which roll call is its own. | item 61883, meeting 2487 |
| Public hearing and final vote | 2026-10-13 | Item 1, marked `[Second Reading]`, "and the hearing of all interested parties", "(Recommended by the Planning and Zoning Committee) (NOT Recommended by the ZAC)". Passed 8 to 0, read from the video; the official minutes are not yet published, so the tally is labelled "from the video". Cue at 2,662 seconds. | item 62781, meeting 2609, vote 12385 (source `video_ocr`) |
| Mayor, in effect | not in the record | A rezoning takes effect on the newspaper announcement (Zoning Ord. Art. II §6); the site holds no record of it. | none |

The same agenda item also exists as item 62832 under meeting 2613 (2026-10-26, external id `event-2713`, typed `committee`, no body named). That row is a second copy of a council agenda under a mislabelled meeting, not a second appearance of the ordinance, and no journey cites it.

**A liquor licence with a hearing and no committee recommendation: Legion Field.** "A Resolution relative to the application of Greenawalt Hospitality, LLC, for a Special Retail Liquor License 160 to be used at Legion Field, 400 Graymont Avenue West … and the hearing of all interested parties."

| Stop | Date | What the record shows | Record |
| --- | --- | --- | --- |
| Committee | 2026-09-22 | Public Safety Committee: no incidents reported, zoning requirements met, no tax delinquencies. "Item Recommended to the City Council Agenda By The Committee Chair – Lack of Quorum." | meeting 3179; committee minutes, https://s3.us-east-2.amazonaws.com/assets.birminghamal.gov/s3fs-public/2026-10/PUBLIC%20SAFETY%20COMMITTEE%20MEETING%20MINUTES%2C%20September%2022%2C%202026_0.pdf |
| Public hearing and vote | 2026-09-29 | Item 7, "(Submitted by Councilor Tate, Chairman, Public Safety Committee) (No Recommendation by the Public Safety Committee)". Passed 8 to 0, read from the video; minutes not yet published. Cue at 872 seconds. | item 62035, meeting 2536, vote 12344 (source `video_ocr`) |
| Mayor | not in the record | | none |

This journey shows what "no recommendation" can mean: the committee had no quorum, and the chair forwarded the item (General Code §2-2-14(a) sets a committee quorum at two).

**A routine contract on consent: Friends of Avondale Park.** A resolution for an agreement of up to $4,000 for free events in Avondale Park.

| Stop | Date | What the record shows | Record |
| --- | --- | --- | --- |
| Committee | 2026-10-12 | Budget and Finance Committee, item 6, inside the committee's own consent block ("Items #4,6,7,8,9,10,11,12"): "Councilor Alexander Motioned to Approve. Councilor Woods Seconded the Motion. Items Recommended to the City Council Consent Agenda." | meeting 3183; committee minutes, https://s3.us-east-2.amazonaws.com/assets.birminghamal.gov/s3fs-public/2026-11/BUDGET%20AND%20FINANCE%20COMMITTEE%20MEETING%20MINUTES%2C%20October%2012%2C%202026.pdf |
| Consent agenda | 2026-10-20 | Consent item 18. Consent items pass on one motion for the group. No vote is linked to this item yet; the minutes are not published. Cue at 1,714 seconds. | item 62911, meeting 2624 |
| Mayor | not in the record | | none |

The video-sourced tallies above must be checked again when the minutes are published, and the journeys updated to cite the minutes.

## 7. Phase 1: the explainer page

What a reader gets: a page at `/al/birmingham/how-it-works/` (address is this plan's call) with the path drawn across the top, a row of real items to pick from, the selected item's journey laid onto the path with dated stops and source links, and below it one short section per stop quoting the rule. Selecting a different item redraws the journey without leaving the page. A link to the page from the Birmingham city page and the meeting page.

How it is built (this plan's calls unless marked):

- Journeys are hand-traced and checked in as data, one file per journey, each stop naming the record it rests on (item id, meeting id, vote id, video second, or "not in the record" with the reason). Nothing about a journey is inferred at render time in this phase.
- The builder traces the further journeys, the same way the parking-fines one was traced: read-only queries against production (the local database holds no Birmingham agenda items). The route is in `docs/specs/operations.md`: take `DATABASE_PUBLIC_URL` from `railway variables --service docket-web --kv` and run `psql` with `PGOPTIONS='-c default_transaction_read_only=on'`. No writes. Where a stop cannot be established from the records (a committee meeting with a recording and no transcript, for example), the journey says so; nobody is asked to supply it from memory.
- The page renders live links from those ids through the existing services, so a video link uses the same timed-link logic as the item page (`docs/birmingham/05-video-transcripts-search.md`), and a stop whose record has been hidden or removed degrades to text.
- The rules table in section 3 is the page's content. Each rule shows its citation and a link to the public source. Rule text is quoted, not paraphrased, wherever a quotation is given above.
- The seven open questions in section 3 appear on the page as open, in plain words.
- No language model writes any sentence on this page.
- Flask and HTMX, a template beside `about_methodology.html`, routes calling `docket.services.*`. No new JavaScript framework. The mockup the operator approved is at `.superpowers/brainstorm/4672-1794533138/content/path-and-progress.html` (layout only).
- The page must work at phone width; the path may scroll sideways or stack.

Done when:

- The parking-fines journey renders with every link resolving to the city's document, the recording at the right second, or the transcript.
- Every stop without a record says so.
- Every rule on the page carries a citation, and a reviewer can find the quoted words in the source.
- At least three further journeys are traced, verified against the records, and selectable.
- `./tools/verify` passes.

Left to the builder: the journey file format and where it lives; the visual design (the operator's approved direction is the mockup's structure, not its styling); how the path collapses on a phone; test design.

## 8. Phase 2: committee agendas and minutes

Pulled forward by the operator on 2026-11-12, because the committee stop is the weakest part of every journey and nothing else can fill it.

What is in today, and what is not. Committee **meetings** are in: 94 Birmingham committee meetings in 2026, named by body, 93 with a recording (most from the council's YouTube channel), 12 with a transcript. Committee **documents** are not: only 3 of those meetings have any agenda items, and no committee agenda or minutes is read. So the site can say a committee met and show the video, and cannot say what it took up or what it did with it.

The source. The city publishes each committee's agendas and minutes as PDFs on that committee's page under `https://www.birminghamal.gov/government/city-council/council/council-committees-2025-2027/`, grouped by month. All eight pages were read on 2026-11-12. Between them they list 106 agendas and 90 minutes, from December 2025 to November 2026:

| Committee | Agendas | Minutes |
| --- | --- | --- |
| Arts and Parks | 9 | 5 |
| Budget and Finance | 22 | 19 |
| Committee of the Whole / Administration and Governmental Affairs | 7 | 6 |
| Community Development | 9 | 7 |
| Economic and Workforce Development / Tourism | 15 | 13 |
| Planning and Zoning | 14 | 13 |
| Public Safety | 21 | 19 |
| Transportation and Infrastructure | 9 | 8 |

Most minutes files do not have the word "minutes" in their name: "TRANSPORTATION & INFRASTRUCTURE COMMITTEE MEETING, May 11, 2026.pdf" is the minutes and "… MEETING AGENDA, May 11, 2026.pdf" is the agenda. Only Public Safety names its minutes as minutes. The kind of a document is settled by its first page (it prints "MINUTES" or "AGENDA"), not by its file name. This is the same website the city-calendar reader (`src/docket/adapters/city_calendar.py`) already reads, and the same polite-delay rule applies.

The minutes are the record, not the agenda. The Transportation and Infrastructure agenda for 2026-05-11 does not list the parking ordinance; the minutes for that meeting record it as item VI, "Parking Reform Update". An item can be taken up without having been on the posted agenda, so items come from the minutes where minutes exist and from the agenda only until they do.

Where else committee documents are, and what this phase does about them:

- **Before December 2025.** The council's former website, birminghamalcitycouncil.org, published committee agendas and minutes for at least 2024 and 2025 (search results list dozens, for example "JOINT PUBLIC SAFETY AND SPECIAL CALLED COMMITTEE OF THE WHOLE MEETING AGENDA March 26 2024.pdf"), and had per-committee agenda and minutes archive pages. That site now redirects to birminghamal.gov and its PDFs return 404. The Wayback Machine holds some of those PDFs. Counted on 2026-11-12 from its index of `birminghamalcitycouncil.org/wp-content/uploads/<year>/` (PDFs captured with status 200, one per address, with "committee" in the file name, by the year of the upload folder): 198 for 2022 (98 agendas, 100 minutes or other), 138 for 2023 (86 and 52), 98 for 2024 (61 and 37), 10 for 2025 (9 and 1), none for 2021. For scale, the city's current pages hold 196 for the twelve months to November 2026, so 2022 looks close to whole, 2023 and 2024 are partial, and 2025 is almost entirely missing. birminghamal.gov's "previous council committees" page carries no documents.
- **Granicus** carries only the council's own view; no committee documents.
- **BirminghamWatch**, a news organisation, hosts copies of some 2025 committee agendas. A third party's copy is not the city's document and is not a source.
- This phase reads the city's current pages only. Recovering 2024 and 2025 from the Wayback Machine is a possible later backfill, in the manner of the 2023 archive manifest (decision `0033`), and is the operator's decision. The 2025 gap cannot be filled from the archive; the remaining routes are a records request to the City Clerk or the Council Administrator, and the council's own YouTube recordings of those meetings.

What the minutes hold, from Budget and Finance, 2026-10-12 (`content/how-it-works/birmingham/sources/committee-bf_min.txt`): the members present; then numbered items, each with a short name, the resolution or ordinance text, "Submitted by", "Department", "Recommended Funding Source", "Amount", and "Action Taken", which records who moved and seconded and ends in one of a small set of outcomes:

- "Item Recommended to the City Council Agenda"
- "Item(s) Recommended to the City Council Consent Agenda" (Budget and Finance also passes its own consent block: "Items #4,6,7,8,9,10,11,12")
- "Item Recommended to the City Council Agenda with NO Recommendation"
- "No Action – Information Only" (Committee of the Whole)

The builder surveys all eight committees' minutes for further wordings before fixing the list; an outcome that matches none is stored as its raw text and shown as such, not forced into a category.

What a reader gets: a committee meeting page that lists what the committee took up and what it did with each item, linked to the city's agenda and minutes PDFs and, where the meeting has one, its recording. The explainer's committee stop can then show a real committee meeting with a real outcome.

How it is built (this plan's calls):

- Documents attach to the committee meeting rows that already exist, matched by committee and date. A document for a date with no meeting row creates one through the same ingest path as everything else; a meeting is never listed twice.
- The meeting's date comes from the page's own date heading, not the file name. File names are unreliable: the minutes for 2026-09-28 are posted as "September 28, 2025.pdf".
- An item's outcome is stored as a committee action in the minutes' own words plus a category. It is not a vote: committee minutes record a motion and a second, not a roll call, and the site must not show a tally the record does not contain.
- An item from an agenda with no minutes yet is shown as on the agenda, with no outcome.
- Committee items do not go through the AI summary stages at first, so the daily AI budget is untouched; the item shows the city's own text. Whether to summarise them is a later decision for the operator.
- The existing rows are checked first: 55 items sit under committee meetings today, and the eight most recent (2026-10-26, no committee named) read like council business, so that meeting may be mislabelled.

Done when:

- The Budget and Finance meeting of 2026-10-12 shows its items with their outcomes, and the page's words can be found in the minutes PDF it links.
- The Transportation and Infrastructure meeting of 2026-05-11 shows item VI, "Parking Reform Update", with its action, and the parking-fines journey's committee stop links to it.
- A recorded count shows, per committee, how many 2026 meetings have an agenda, minutes, and items, and how many dates have a document and no recording or a recording and no document.
- A daily worker task keeps it current, pinging its health check like the other tasks.
- `./tools/verify` passes.

Left to the builder: whether this is a new adapter or an extension of the calendar reader; how a joint meeting of two committees is stored; the storage of the committee action; how the minutes' item numbering maps onto `item_number`.

## 9. Phase 3: reading the markers into data

What a reader gets: every Birmingham item whose text carries the markers shows a simple progress strip naming its own stage (for example "Committee recommended · First reading · today"), with "How this works" linking to the explainer. The strip does not yet jump between meetings. The "failed" first-reading vote stops reading as a defeat.

What is read from each item's text, deterministically, by pattern and never by a language model:

- reading stage: first reading, second reading, or none stated;
- `P` (permanent operation) and `(ph)` (public hearing);
- the recommendation list: each recommender, and its kind (recommended, not recommended, no recommendation, conditional), keeping committees distinct from the Mayor and department heads;
- "Held Over from … to …" and "Deferred from …", with their dates;
- the agenda section the item sits under (final passage or first reading), which `agenda_items.section` was made for and does not hold.

Where the markers come from (this plan's call). Because `P`, `(ph)` and the section heading sit on the wrong row or nowhere (section 4), they cannot be read from a row's own stored text. The parser is fixed so that new agendas store them on the right item. Existing rows are backfilled by fetching and re-parsing the agenda PDFs of council meetings from 2026-01-01 onward, about one fetch per meeting, from a laptop with the polite delay, as the repository's other backfills run (`docs/specs/operations.md`). Earlier years are left as they are; their text is mostly title-only and the strip is absent there. The bracketed markers and the recommendation lines are read from the stored text, which has them on the right row.

And for votes: a roll call that fails only because unanimous consent was not given is shown as "held over: unanimous consent not given", with the tally, and never as "failed".

- The evidence is the minutes' own words and nothing else: the Presiding Officer's declaration ("not adopted due to the item being an item of permanent operation and therefore needing unanimous consent", "held over to the regular meeting on …") or the motion's ("for unanimous consent"). Both are inside the stored `raw_text` of votes 12206 and 12219. A vote is never reclassified by inference from the item being `P` and at first reading, and a video-OCR vote, which has no such text, is never reclassified.
- The rule runs in both directions. A first-reading roll call with a majority in favour and one objection is stored today as `passed` although the ordinance was held over; the same wording identifies it.
- Storage (this plan's call, to be confirmed in the Phase 3 ExecPlan because it amends decision `0057`): a new stored result word for "held over", treated everywhere as no outcome, the way a tabled motion already is. That way every page that prints the result is corrected at once, and a held-over roll call counts for and against nobody in "against the outcome".

Constraints:

- A parser version is stored beside the parsed facts, as the AI stages already do, so a rule change can be re-run.
- The backfill is bounded and respects "Production is not a sandbox": one targeted statement or a limited batch, compared old against new on real rows before it ships. The production volume is 1 GB.
- Counts shown anywhere distinguish "no marker in the text" from "no text stored". Pre-2026 items mostly lack the text; the strip is absent there, not empty.
- The existing `sponsor` behaviour does not change.

Done when:

- On the parking-fines items (58893, 58990, 59026) the strip reads first reading, first reading, second reading held over from 5/26, with the Transportation and Infrastructure Committee's recommendation.
- Items 58893 and 58894 carry `P` themselves, and no item carries its neighbour's marker, on a recorded sample of re-parsed 2026 agendas.
- Votes 12206 and 12219 no longer render as a failed ordinance on the item page, the meeting page, the member pages, or the city page's "Where they disagreed". The effect on the "against the outcome" counts (decision `0057`) is measured and recorded before shipping.
- A recorded before-and-after on production rows shows how many items gained each fact.
- `./tools/verify` passes.

Open for the builder to settle with the operator at plan time: whether the parsed facts live in new columns or one JSON column; whether the upcoming-hearings feed switches from title search to the `(ph)` flag in this phase.

## 10. Phase 4: one item across meetings

What a reader gets: the strip's stops become links. From the June 2 vote a reader jumps back to the May 26 objection and the May 19 introduction, and forward from an introduction to the vote. The explainer's item picker can then offer any linked item, not only the hand-traced ones.

How appearances are tied together, strongest evidence first:

1. the city's own pointer: "Held Over from 5/26/2026 to 6/2/2026" names the earlier meeting;
2. a shared case or instrument number in the text (ZAC2026-08007, SUB2026-08019, an ordinance or resolution number);
3. the same title after normalising, within a bounded window of meetings.

Each link stores which of these made it. A link made only by title similarity is labelled as such where it is shown, and anything below a confidence the builder sets is not shown at all. Links are never made by a language model.

The committee stop: once Phase 2 has put committee items and their outcomes in the database, a council item is tied to the committee item it came from by the same three kinds of evidence, within the weeks before its first council appearance, and the strip's committee stop links to that committee meeting's item, its recording, and the committee's minutes. Where no committee item matches, the stop falls back to what the council agenda says ("Recommended by the … Committee") with no meeting named.

Done when:

- The parking-fines strip links 58893, 58990 and 59026 in order, and the sibling ordinance likewise, with no false link between the two siblings.
- The rezoning ZAC2026-08007 links its two appearances.
- A sample of links by each method has been checked by hand and the error rate recorded.
- `./tools/verify` passes.

## 11. Risks

- **The rule and the practice differ.** The committee rule is the plain case. The page states both and does not explain the difference away.
- **Thin history.** The markers are rich in 2026 and sparse before. The feature will look like a 2026 feature; the page should say that item text before 2026 is often title-only.
- **Sibling items.** Near-identical ordinances travel together; title matching will confuse them. The parking-fines pair is the standing test.
- **Vote reclassification touches published counts.** Treating unanimous-consent roll calls as their own kind changes member dissent counts. Measure first.
- **Sources move.** Municode is not machine-readable and the city's copy of the Mayor-Council Act is stale. Quotations are pinned to the dated copies named in section 3, and the page shows the date each source was read.

## 12. Decisions

Made by the operator: Birmingham only; a visual path with real items selectable on it; a progress strip on each item linking to recordings and transcripts at each stage; the order of the phases, with committee agendas and minutes pulled forward to second (2026-11-12); gaps shown as gaps.

Made in this plan, open to correction: the page address; the names of the stops; hand-traced journeys as checked-in data for Phase 1, traced by the builder with read-only production access; deterministic parsing only; backfilling the misplaced markers by re-parsing 2026 agenda PDFs and leaving earlier years alone; identifying a held-over roll call only from the minutes' own words; storing it as a new result word with no outcome; the three linking methods and their order; committee items carrying no AI summary at first; recording a committee's action as the minutes word it and never as a vote.
