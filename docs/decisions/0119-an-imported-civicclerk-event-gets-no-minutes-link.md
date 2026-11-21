# 0119 — An imported CivicClerk event gets no minutes link

## Decision

A CivicClerk meeting's minutes link is the city's own Minutes file, and only for an event whose `createdOn` date (in `America/Chicago`) is on or before its `eventDate` date. An event created after its own date, or with no readable `createdOn`, is an import and gets no minutes link, until something reads the date printed in the file itself. The agenda link is the city's Agenda file where the event has one, and the portal page only as the fallback.

## Rationale

The obvious rule is to link whatever file the city labels `Minutes` on the event. Mobile loaded its meetings before 2024-06-25 into the system on 2024-07-25, after they were held, and attached files to them in bulk. Of eleven such Minutes files read on 2026-11-20, ten were the minutes of another meeting: the event of 2023-03-21 carries the minutes of August 30, 2022, the event of 2024-01-30 those of August 8, 2023. A link labelled "minutes" that opens another meeting's minutes is worse than no link (`docs/PRINCIPLES.md`, Source or silence), and nothing in the event row tells a right file from a wrong one. What does tell an import from a meeting entered in the ordinary way is that the event was created after its own date.

`createdOn` is a true UTC time and `eventDate` is the city's wall clock with a false `Z`, so the comparison is made on the Central date: without that, a meeting entered after 18:00 Central on its own day would be taken for an import and lose its minutes link for good.

The file address, `Meetings/GetMeetingFileStream(fileId=N,plainText=false)`, was observed to answer with the PDF. The portal page is built by a script in the browser and no session could check it, so it is kept only where there is no Agenda file. The cost of the rule is that 135 Mobile meetings have no minutes link though the city holds their minutes somewhere; the work that reads Mobile's minutes can pair each file to its meeting by the date on its first page (`D180` in `docs/DEBT.md`).

## Date

2026-11-20, the authoring session of plan `mobile-agendas-flow-again` (Claude), amended the same day by the operator's review revision; built by that plan's M1 and graduated by its M6 session the same day.

## Status

accepted
