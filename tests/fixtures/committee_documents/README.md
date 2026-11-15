# Committee document fixtures

Public records of the Birmingham City Council's committees, downloaded unchanged on 2026-11-13 from the addresses the committee pages under `https://www.birminghamal.gov/government/city-council/council/council-committees-2025-2027/` list. They are the test inputs for plan `committee-documents`. Each was chosen for one property the reader must handle.

| File | Listed on page | Listed under heading | Listed name | Why it is here |
| --- | --- | --- | --- | --- |
| `bf_minutes_2026-10-12.pdf` | budget-finance-committee | OCTOBER 12, 2026 | BUDGET AND FINANCE COMMITTEE MEETING MINUTES, October 12, 2026.pdf | Ordinary minutes, items numbered `1)`; a committee consent block; six pages with a repeated page header. |
| `ti_minutes_2026-05-11.pdf` | transportation-infrastructure-committee | MAY 11, 2026 | TRANSPORTATION & INFRASTRUCTURE COMMITTEE MEETING MINUTES, May 11, 2026.pdf | Roman numerals; item VI is "Parking Reform Update"; an information-only item. The file's own name does not say "minutes". |
| `ps_minutes_2026-09-22.pdf` | public-safety-committee | SEPTEMBER 22, 2026 | PUBLIC SAFETY COMMITTEE MEETING MINUTES, September 22, 2026_0.pdf | Letters `A.`; licence applications with no number of their own; no quorum; an outcome sentence that wraps onto a second line; one free-text action. |
| `pz_minutes_2026-09-08.pdf` | planning-zoning-committee | SEPTEMBER 8, 2026 | PLANNING AND ZONING COMMITTEE MEETING MINUTES, September 8, 2026.pdf | The printed date is misspelled ("SEPTEBMBER 8, 2026"); sub-items `a.` and `b.`. |
| `ps_cow_joint_minutes_2025-11-25.pdf` | public-safety-committee | NOVEMBER 25, 2025 | PUBLIC SAFETY COMMITTEE MEETING MINUTES, November 25, 2025.pdf | A joint meeting of two committees. |
| `cd_minutes_2026-05-04_posted_under_bf.pdf` | budget-finance-committee | JUNE 22, 2026 | BUDGET AND FINANCE COMMITTEE MEETING MINUTES, June 22, 2026.pdf | The Community Development minutes of 2026-05-04, posted on another committee's page under another date. |
| `ed_agenda_june_2_no_year.pdf` | economic-workforce-development-tourism-committee | JUNE 2, 2026 | ECONOMIC AND WORKFORCE DEVELOPMENT/TOURISM COMMITTEE MEETING AGENDA, June 2, 2026 | An agenda whose printed date has no year ("Tuesday, June 2"). |
| `pz_agenda_2026-01-27_with_minutes_appended.pdf` | planning-zoning-committee | JANUARY 27, 2026 | PLANNING AND ZONING COMMITTEE MEETING AGENDA, January 27, 2026.pdf | An agenda with an earlier meeting's minutes appended; it must read as an agenda. |
| `ps_agenda_2026-09-22_scanned.pdf` | public-safety-committee | SEPTEMBER 22, 2026 | PUBLIC SAFETY COMMITTEE MEETING AGENDA, September 22, 2026.pdf | A scanned image with no text layer. |
| `page_planning_zoning.html` | | | | The Planning and Zoning committee page as served: 27 documents under 15 date headings, inside the page's `__NEXT_DATA__` script. |

The public address of each PDF is `https://s3.us-east-2.amazonaws.com/assets.birminghamal.gov/s3fs-public/<yyyy-mm>/<file name, percent-encoded>`; the committee page fixture holds the exact addresses for the Planning and Zoning files.
