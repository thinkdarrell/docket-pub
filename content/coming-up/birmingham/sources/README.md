# Source saved for the "What's coming up" page

The city's own file, fetched on 2026-11-17 and kept as fetched, so a reviewer can check every row of `../neighborhood-schedule.yaml` against the page it was transcribed from. It is a working copy for checking the transcription, not something the site serves: the page links the public address. `src/docket/services/neighborhood_schedule.py` refuses to load the schedule when this file's SHA-256 is not the one below, which is also recorded in the YAML's `source` block.

| File | What it is | Public address | Read | SHA-256 |
| --- | --- | --- | --- | --- |
| `2026_NA_Meeting_Schedule_rev._2-3-2026.pdf` | "City of Birmingham Community Resource Services Division Neighborhood Association Meeting Schedule", printed "Revised February 3, 2026". Three pages, one table of 99 associations: the association, its meeting date and time, the meeting type, and the meeting information. | https://s3.us-east-2.amazonaws.com/assets.birminghamal.gov/s3fs-public/2026-02/2026_NA_Meeting_Schedule_rev._2-3-2026.pdf | 2026-11-17 | `f9987d63389a280b5333fb9675d090bcf76c3069ccce7f05ea1052fabda7333e` |

When the city publishes a later revision or the next year's schedule, the new PDF is saved here, this row and the YAML are updated together, and the transcription is checked again. The procedure is owned by `docs/specs/coming-up.md`, "Saving a later revision or the next year's schedule".
