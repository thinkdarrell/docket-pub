# A Granicus recording with no sound says so: the measuring pass records where a clip is silent, the meeting page leads with the council's YouTube recording, and a link into a silent stretch is labelled

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `plans/PLANS.md`.

## Purpose / Big Picture

Birmingham's council meetings are recorded twice: by the city's Granicus archive (a "clip", played on the Granicus player page) and on the council's YouTube channel. For some meetings the Granicus clip has no sound, for all of its length or for part of it. docket.pub does not know this. Its meeting page offers "Watch video" (the Granicus player) first and "Watch on YouTube" second, and a link that opens the video at a moment falls back to the Granicus player whenever the YouTube recording could not be matched to the clip, which is exactly what happens when the clip is silent, because the match is made from the sound. A reader is sent to a recording they cannot hear while an audible one is attached to the same meeting.

After this plan docket.pub measures and stores, for each Granicus clip it compares with a YouTube recording, the stretches of the clip that are silent. On the meeting page of a clip that is silent throughout, or for ten minutes or more, the YouTube link is printed first and the Granicus link says what was measured: "Granicus player · no sound", or "Granicus player · no sound for 45 of 100 minutes". A link that opens the Granicus player at a moment inside a silent stretch says "(no sound)" after its name, so the reader knows before clicking.

To see it working once the operator has taken the steps under Validation and Acceptance: open `https://docket.pub/al/birmingham/meetings/275/` (the council meeting of 2021-02-02, Granicus clip 1414, measured silent from end to end). The source links show "Watch on YouTube" first and then "Watch video" with "Granicus player · no sound" beneath it. Open `https://docket.pub/al/birmingham/meetings/3197/` (2026-11-10, clip 2034): the Granicus link reads "Granicus player · no sound for 45 of 100 minutes".

This plan does not make any link open YouTube at a moment that it opens Granicus at today, and it does not change what the transcriber transcribes. Both are deliberate and are explained in the Decision Log; the second is left to a successor plan named there.

## Progress

As authored on 2026-11-17, nothing has been executed.

- [x] (2026-11-18 04:10Z) M1: `transcriber/transcriber/sound.py` measures where 8 kHz audio is silent, in 60-second blocks against a floor of -60 dBFS, and `transcriber/tests/test_sound.py` passes with its eight tests
- [x] (2026-11-18 04:47Z) M2: migration 048 creates `granicus_clip_sound`, the `transcriber` role may select, insert, and update it, and `transcriber/transcriber/db.py` saves one row per meeting and replaces it on a second save, with the migration, role, and producer database tests passing
- [x] (2026-11-18 05:04Z) M3: the measuring pass saves and logs each Granicus clip's sound once per meeting before it measures the meeting's recordings, the producer version is 0.7.0, and `transcriber/tests/test_measure.py` passes with its three new tests
- [x] (2026-11-18 05:30Z) M4: `src/docket/services/video_links.py` loads a clip's sound, and the meeting page prints the YouTube link first and "Granicus player · no sound" or "no sound for N of M minutes" when the clip is silent throughout or for ten minutes or more, with the loader, unit, and web tests passing
- [x] (2026-11-18 05:58Z) M5: a link that opens the Granicus player inside a silent stretch, or the plain player of a clip that is silent throughout, carries "(no sound)" in its phrase and on the vote link, with the unit and web tests passing
- [ ] M6: the specs, runbook, README, architecture note, decision records, and `docs/DEBT.md` describe the sound measurement, and debt rows record the operator's post-merge steps, the clips never measured for sound, and the transcripts still made from silent audio

## Surprises & Discoveries

As authored on 2026-11-17, no milestone has run. The authoring research found the following, each observed on 2026-11-17 on the Legion (the Linux machine under WSL whose checkout is `/home/thinkdarrell/docket-pub`), with `main` at commit `d98b798` (the tip of `origin/main`, pull request #183).

- Observation: the starting state is green, and `./tools/verify` took 270 seconds against a budget of 180.
  Evidence: `verify: unit+web+services ... ok (151s)` with `3464 passed, 5 skipped, 4 xfailed, 1 warning`; `verify: integration ... ok (108s)` with `1042 passed, 1 warning`; `judge fixtures: 12 of 12 passed`; `verify: transcriber ... ok (10s)` with `134 passed`; `verify: plans ... ok (0s)`; `verify: all 6 checks passed in 270s.`

- Observation: per-file baselines, each run with `DATABASE_URL=$(tools/test-db)` and `-q -p no:cacheprovider`.
  Evidence: `tests/unit/test_video_links.py` 25 passed; `tests/integration/test_video_link_loader.py` 6; `tests/integration/test_transcriber_role.py` 5; `tests/web/test_meeting_recordings.py` 11; `tests/web/test_vote_result_block.py` 21; `tests/integration/test_046_migration.py` 4; `transcriber/tests/test_measure.py` 12; `transcriber/tests/test_db.py` 29; `transcriber/tests/test_align.py` 17. A file under `transcriber/tests/` is run in its own pytest command, never together with a file under `tests/` (a completed plan recorded that the combined command fails to collect).

- Observation: the silence rule of M1, written as a prototype and run on the whole audio of three real clips, separates silent from audible with nothing in between.
  Evidence: each clip was fetched with `ffmpeg -user_agent <the browser string in transcriber/transcriber/audio.py> -i "https://bhamal.granicus.com/DownloadFile.php?view_id=2&clip_id=<id>" -vn -ac 1 -ar 8000 -c:a pcm_s16le` and cut into 60-second blocks, a shorter last block counted when it held 10 seconds or more; a block's level is 20 times the base-10 logarithm of its root-mean-square sample value over 32768. Clip 1424 (2021-01, a meeting whose YouTube recording passed): 3,761 seconds, 63 blocks, none silent, levels from -30.2 to -17.8 dBFS. Clip 1414 (2021-02-02, meeting 275): 2,516 seconds, 42 blocks, all silent, levels from -73.8 to -70.2. Clip 2034 (2026-11-10, meeting 3197): 6,019 seconds, 101 blocks, 46 silent with levels from -70.9 to -69.7 and 55 audible with levels from -40.6 to -24.3; the silent spans were 0 to 60, 120 to 180, 240 to 720, 780 to 2,040, and 5,160 to 6,019 seconds, 2,719 seconds in all. No block of any of the three lay between -66 and -50 dBFS. The audio was deleted after measuring.

- Observation: the audible part of clip 2034 is the part its YouTube recording was matched on.
  Evidence: meeting 3197 has two recordings; `25o-l7-PP24` is `passed` with coverage 2,162 to 5,132 seconds on the Granicus clock, inside the audible run 2,040 to 5,160, and `P0vkxIkJXb4` is `rejected` with reason `score` at 5.6.

- Observation: the Granicus player plays the same file the transcriber downloads, so a clip silent in the download is silent in the player.
  Evidence: `DownloadFile.php?view_id=2&clip_id=1414` answers 302 to `https://archive-video.granicus.com/bhamal/bhamal_1b9101a9-522a-4fec-9531-e277c1b14aa3.mp4`, and the player page for clip 1414 names the stream `https://archive-stream.granicus.com/OnDemand/_definst_/mp4:archive/bhamal/bhamal_1b9101a9-522a-4fec-9531-e277c1b14aa3.mp4/playlist.m3u8`, the same file. Nobody listened to the player during authoring; the operator's look under Validation and Acceptance includes it.

- Observation: on the meetings whose Granicus clip is silent throughout, almost no link that opens the video at a moment is rendered today, so the meeting page's two untimed links are where a reader meets the silent recording.
  Evidence: production, read-only. Of the meetings holding a recording rejected with reason `score` below 7.5, 29 have no passed stretch at all: they hold 1,498 agenda items, every one with a cue point and a chapter id, 0 votes read off the video, and no transcript (transcripts exist only for meetings from 2025-10-28 on, 67 rows in all). The links that open at a moment are the vote link (needs a vote read off the video), the item link on the transcript page and the minutes-versus-video row (both need a transcript), and the source button (which no page includes), so none is rendered for those 29. Three more such meetings have a passed stretch as well (meeting 3197 among them); they hold 235 items, 234 cued, and 5 votes read off the video.

- Observation: the stored measurements on 2026-11-17, by status, reason, and method version.
  Evidence: `SELECT status, reason, method_version, count(*), count(DISTINCT meeting_video_id) FROM meeting_video_alignments GROUP BY 1,2,3` printed `passed` with no reason at version 2: 108 rows, 108 recordings; `passed` with no reason at version 3: 299 rows, 204 recordings; `rejected`, `score`, version 3: 38 and 38; `rejected`, `no_window`, version 3: 4 and 4; `failed` at version 3: 6 rows with six different error texts; and one row that is `passed` at version 2 with the reason `operator`, a state no documented statement produces (the restore clears the reason). This plan neither reads nor changes that row.

- Observation: a fully silent clip the transcriber has met is already kept off the site, and a partly silent one is not detected.
  Evidence: meeting 14 (2026-02-24, clip 1951) has a transcript row with status `low_speech`, 602 seconds of audio and "0s of speech detected"; meeting 2541 (2026-09-28, clip 2013) the same with 1,521 seconds and no YouTube recording attached. Meeting 3197 has no transcript row yet.

From M1's session of 2026-11-18 (UTC) on the Legion, in this worktree, starting at commit `665cccf`.

- Observation: the starting state in the worktree is green, and `./tools/verify` took 295 seconds.
  Evidence: run at 03:39Z before any edit, with the worktree's own `venv/` built for this session (`python3.10 -m venv venv`, `venv/bin/pip install -e ".[dev]"`): `3464 passed, 5 skipped, 4 xfailed, 2 warnings`, `1042 passed, 2 warnings`, `judge fixtures: 12 of 12 passed`, `134 passed, 1 warning`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 295s.`

- Observation: the eight tests fail before the module exists, each on the import inside its own function, and the file collects.
  Evidence: at 04:04Z, `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest transcriber/tests/test_sound.py -q -p no:cacheprovider` printed `8 failed, 1 warning in 0.13s`. The commit that holds the tests failing is the one that adds this entry.

- Observation: M1's acceptance is met. The eight tests pass against the module, the transcriber check is at 142, and `./tools/verify` is green.
  Evidence: at 04:04Z the file's command printed `8 passed, 1 warning in 0.54s`. `./tools/verify`, started at 04:05Z after the last edit and finished at 04:10Z: `3464 passed, 5 skipped, 4 xfailed, 2 warnings`, `1042 passed, 2 warnings`, `judge fixtures: 12 of 12 passed`, `142 passed, 1 warning` (134 and 8), `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 292s.`

- Observation: eleven rules were taken out of a copy of `transcriber/transcriber/sound.py` held in memory, one at a time (a pytest plugin in the session scratchpad that compiles the altered source as `transcriber.sound`; the committed file was not edited), and the eight tests run against each. Eight removals failed a test on the first run, two more after an assertion was added for each, and one cannot be told from its absence.
  Evidence: failing a test as first written: the floor at -61 (1 failed) and at -59.9 (1 failed); a short tail always joined (1); the guard that a lone short block stays a block (1); a block of zeros not silent (5); neighbouring silent blocks not joined (4); no check for empty samples (1); the comparison reversed (4). Free as first written, then pinned: `BLOCK_S` at 30 passed all eight, and `test_a_block_is_silent_below_minus_60_dbfs_and_not_at_minus_59_94` gained the assertion that thirty seconds of noise and thirty of zeros are one audible block (then 1 failed); a short tail never joined passed all eight, because 605 seconds of zeros are one span either way, and `test_a_tail_shorter_than_ten_seconds_joins_the_block_before_it` gained the assertion that five silent seconds after ten minutes of noise give no span (then 1 failed). Both assertions were added after the commit that holds the tests failing (`8def4ee`). Still free: `silent_s` without its cap of `duration_s` passes all eight. No input was found for which the sum exceeds the duration (the Decision Log entry on the review says why), so no test can show the cap; it stays as the plan states it.

From M2's session of 2026-11-18 (UTC) on the Legion, in this worktree, starting at commit `f670d28`.

- Observation: the starting state is green. Only the last 25 lines of the run were kept, so the two pytest totals of the first tiers were not read this time.
  Evidence: `./tools/verify`, started at 04:32Z before any edit: `142 passed, 1 warning` for the transcriber check, `verify: unit+web+services ... ok (165s)`, `verify: integration ... ok (112s)`, `verify: judge-fixtures ... ok (1s)`, `verify: workflows ... ok (0s)`, `verify: transcriber ... ok (11s)`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 290s.`

- Observation: migration 048 is free. `origin/main`, fetched at 04:32Z, holds `047_public_hearings.py` as its highest, and `gh pr list --state open` printed nothing on its second run (the first ended `TLS handshake timeout`).
  Evidence: `git ls-tree --name-only origin/main src/docket/migrations/` ends `047_public_hearings.py`, `__init__.py`, `runner.py`.

- Observation: the seven new tests fail before the migration, the grant, and the writer exist, and each file collects with its existing tests passing beside them.
  Evidence: at 04:38Z, each in its own command with `DATABASE_URL=$(tools/test-db)` and `-q -p no:cacheprovider`: `tests/integration/test_048_migration.py` printed `4 failed, 1 warning in 0.22s`; `tests/integration/test_transcriber_role.py` printed `1 failed, 5 passed, 1 warning in 0.35s`; `transcriber/tests/test_db.py` printed `2 failed, 29 passed, 1 warning in 0.71s`. The failures name the missing table (`relation "granicus_clip_sound" does not exist`), the migration missing from the runner's list, and the missing `save_clip_sound`. The commit that holds the tests failing is the one that adds this entry.

- Observation: M2's acceptance is met, with no carve-out. The three files pass, the status command ends with migration 48 applied, and `./tools/verify` is green with the integration tier at 1,047 and the transcriber check at 144.
  Evidence: at 04:41Z, after the last edit, each in its own command: `tests/integration/test_048_migration.py` printed `4 passed, 1 warning in 0.36s`; `tests/integration/test_transcriber_role.py` printed `6 passed, 1 warning in 0.37s`; `transcriber/tests/test_db.py` printed `31 passed, 1 warning in 0.63s`. `DATABASE_URL=$(tools/test-db) venv/bin/python -m docket.migrations.runner --status` printed as its last line `[applied] 48: docket.migrations.048_granicus_clip_sound`. `./tools/verify`, started at 04:41Z and finished at 04:46Z: `3464 passed, 5 skipped, 4 xfailed, 2 warnings`, `1047 passed, 2 warnings`, `judge fixtures: 12 of 12 passed`, `144 passed, 1 warning`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 295s.`

- Observation: twenty-seven rules were taken out, one at a time, of copies held in memory (a pytest plugin in the session scratchpad that compiles the altered `transcriber/transcriber/db.py` into `transcriber.db`, swaps the migration module's `SQL_UP` and `SQL_DOWN` after the table was dropped from the throwaway database, or swaps the role file's text the role test reads; no committed file was edited), and the file that tests each run against it. Twenty-five removals failed a test on the first run and two more after an assertion was added for each; none is left free.
  Evidence: the writer, thirteen, against `transcriber/tests/test_db.py`: no `ON CONFLICT` clause (1 failed); each of the six columns dropped from the `SET` list in turn, `measured_at` among them (1 failed each); a commit inside the save (1); the clip id taken from something other than `external_id` (2); `method_version` ignored (1); the spans dropped (1) and reversed (1); `silent_s` written from the duration (2). The migration, nine, against `tests/integration/test_048_migration.py`: no `CHECK (duration_s > 0)` (1 failed); no `silent_s >= 0` (1); no `silent_s <= duration_s` (1); no `ON DELETE CASCADE` (4 errors: the first test's teardown cannot delete its meetings and every later setup fails the same way); no primary key (1); no default on `silent_spans` (1); a down that keeps the table (2). Free as first written, then pinned: `CREATE TABLE` without `IF NOT EXISTS` and `DROP TABLE` without `IF EXISTS` each passed all four, and `test_048_up_creates_the_table_and_a_row_reads_back` gained a second run of `SQL_UP` on a database that holds the table, `test_048_down_drops_the_table_and_the_up_applies_again` a second run of `SQL_DOWN` on one that does not (then 1 failed each). Both assertions were added after the commit that holds the tests failing (`759de64`). The role file, five, against `tests/integration/test_transcriber_role.py`: no grant, a grant with `DELETE`, and a grant lacking each of `SELECT`, `INSERT`, and `UPDATE` (1 failed each).

From M3's session of 2026-11-18 (UTC) on the Legion, in this worktree, starting at commit `3006f21`.

- Observation: the starting state is green, with the totals M2 left.
  Evidence: `./tools/verify`, started at 04:52Z before any edit and finished at 04:57Z: `3464 passed, 5 skipped, 4 xfailed, 2 warnings`, `1047 passed, 2 warnings`, `judge fixtures: 12 of 12 passed`, `144 passed, 1 warning`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 292s.`

- Observation: the three new tests fail before the pass saves anything, and two existing tests fail beside them because their assertions were changed in the same commit to what M3 makes true (the Decision Log says which); the file collects and its other ten tests pass.
  Evidence: at 04:58Z, `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest transcriber/tests/test_measure.py -q -p no:cacheprovider` printed `5 failed, 10 passed, 1 warning in 0.18s`, the five being the three new tests, `test_a_measurement_with_two_stretches_is_saved_once_and_logged_once_per_stretch` (it now expects the sound's commit), and `test_main_measures_before_the_engine_loads_and_meeting_id_skips_the_measuring` (it now expects version `0.7.0`). The commit that holds the tests failing is the one that adds this entry.

- Observation: M3's acceptance is met, with no carve-out. The file passes with its fifteen tests, the version reads 0.7.0, and `./tools/verify` is green with the transcriber check at 147.
  Evidence: at 04:58Z, after the last edit, `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest transcriber/tests/test_measure.py -q -p no:cacheprovider` printed `15 passed, 1 warning in 0.08s`, and `(cd transcriber && ../venv/bin/python -c "import transcriber; print(transcriber.__version__)")` printed `0.7.0`. `./tools/verify`, started at 04:59Z and finished at 05:04Z: `3464 passed, 5 skipped, 4 xfailed, 2 warnings`, `1047 passed, 2 warnings`, `judge fixtures: 12 of 12 passed`, `147 passed, 1 warning`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 288s.`

- Observation: fifteen rules were taken out, one at a time, of a copy of `transcriber/transcriber/measure.py` held in memory (a pytest plugin in the session scratchpad that compiles the altered source over the imported `transcriber.measure`; the committed file was not edited), and the file's fifteen tests run against each. All fifteen removals failed a test on the first run, so no assertion was added after the commit that holds the tests failing (`e26d5ee`); the plugin with nothing altered printed `15 passed`. One thing no test can tell: whether a fraction of a second in the log line is rounded or cut off.
  Evidence: no save at all (4 failed); no commit after the save (3); no log line (3); the line at DEBUG (3); the save after the meeting's recordings (3); a save per recording (1); the meeting's last candidate and not its first (1); the matcher's method version in place of `SOUND_METHOD_VERSION` (1); the sound measured from a second read of the WAV (1); a database error on the save swallowed (1), and turned into `failed` rows (1); the figures not as whole seconds (3); the line logged before the row is stored (1); the spans' count replaced by another figure (3); the two figures swapped (3). The stand-in the plan fixes for `sound.measure` returns 6019.0 and 2719.0, whole numbers, so `%.0f` (which rounds) and a cut to an integer print the same line; the module rounds. The version has no removal of its own: `test_main_measures_before_the_engine_loads_and_meeting_id_skips_the_measuring` failed at `0.6.0` in the commit that holds the tests failing.

From M4's session of 2026-11-18 (UTC) on the Legion, in this worktree, starting at commit `868b201`.

- Observation: the starting state is green, with the totals M3 left.
  Evidence: `./tools/verify`, started at 05:10Z before any edit and finished at 05:15Z: `3464 passed, 5 skipped, 4 xfailed, 2 warnings`, `1047 passed, 2 warnings`, `judge fixtures: 12 of 12 passed`, `147 passed, 1 warning`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 294s.`

- Observation: nine of the ten new tests fail before the loader, the note, and the template's change exist, and each file collects with its existing tests passing beside them. The tenth, the web test of a clip silent for five minutes, passes before and after: it shows that a row with no note changes nothing, which is already true when no row is read.
  Evidence: at 05:20Z, each in its own command with `DATABASE_URL=$(tools/test-db)` and `-q -p no:cacheprovider`: `tests/unit/test_video_links.py` printed `4 failed, 25 passed, 1 warning in 0.10s`; `tests/integration/test_video_link_loader.py` printed `2 failed, 6 passed, 1 warning in 0.79s`; `tests/web/test_meeting_recordings.py` printed `3 failed, 12 passed, 1 warning in 1.87s`. The commit that holds the tests failing is the one that adds this entry.

- Observation: M4's acceptance is met, with no carve-out. The three files pass at 29, 8, and 15, and `./tools/verify` is green with the first tier at 3,472 and the integration tier at 1,049.
  Evidence: at 05:24Z, after the last edit, each in its own command with `DATABASE_URL=$(tools/test-db)` and `-q -p no:cacheprovider`: `tests/unit/test_video_links.py` printed `29 passed, 1 warning in 0.03s`; `tests/integration/test_video_link_loader.py` printed `8 passed, 1 warning in 0.85s`; `tests/web/test_meeting_recordings.py` printed `15 passed, 1 warning in 2.02s`. `./tools/verify`, started at 05:24Z and finished at 05:29Z: `3472 passed, 5 skipped, 4 xfailed, 2 warnings`, `1049 passed, 2 warnings`, `judge fixtures: 12 of 12 passed`, `147 passed, 1 warning`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 297s.`

- Observation: without a sound row the source-links section is byte for byte what it was before M4, on five kinds of meeting.
  Evidence: a script in the session scratchpad seeded five Birmingham meetings with no sound row (a Granicus player page with one YouTube recording, one with two, a meeting whose own video is on YouTube, a player page with no recording, and a meeting with no video), fetched each meeting page through the Flask test client, and wrote the five sections (`<section class="mtg-sources">` to its `</section>`) to a file. Run at `868b201` before any edit and again on the finished template, the two files are 4,982 bytes each and `cmp` reported no difference. The web test of a clip silent for five minutes holds the same for a meeting that has a row and no note: the section equals the one rendered before the row was inserted.

- Observation: twenty-five rules of M4 were taken out, one at a time, of copies held in memory (a pytest plugin in the session scratchpad that compiles the altered `src/docket/services/video_links.py` over the imported module, or hands Jinja an altered `meeting_detail.html` through `jinja2.FileSystemLoader.get_source`; no committed file was edited), and the three files' 52 tests run against each; the plugin with nothing altered printed `52 passed`. Twenty-four removals failed a test on the first run and the last after an assertion was added; none is left free.
  Evidence: the note, seven: no branch for a clip silent throughout (3 failed); the ten-minute floor excluded, `>` for `>=` (1); no floor (2); the floor at 300 (2); no cap of N at M minus 1 (1); minutes cut and not rounded (1); N and M swapped (4). The loader, twelve: no version clause (1), the version an equality (1), no clip id clause (1), `MIN_SOUND_VERSION` at 0 (1); the date UTC's and not Chicago's (3); the spans as lists (1), not as floats (1), reversed (1); `for_meetings` not setting `sound` (2), and lending one meeting's to its neighbour (1); `clip_sound_for` returning nothing (5); the duration and the silent seconds swapped (3). The template, six: no title (2 failed); a title whenever a row exists (1); no note in the meta line (3); YouTube never first (2); YouTube first whenever a recording is attached (1). Free as first written, then pinned: the test that `'MediaPlayer.php'` is in the meeting's `video_url` passed all 52 when removed, and `test_a_clip_silent_for_five_minutes_leaves_the_links_as_they_were` gained a sound row on the fixture's meeting whose own video is on YouTube and the assertion that its section does not change (then 1 failed). That assertion was added after the commit that holds the tests failing (`f449a34`). One more removal was tried on a rule that is not M4's, the existing test that a YouTube link is printed only when the row's own video is elsewhere, now inside the macro: the existing `test_yt_row_shows_one_watch_link` failed.

From M5's session of 2026-11-18 (UTC) on the Legion, in this worktree, starting at commit `8fb71ba`.

- Observation: the starting state is green, with the totals M4 left.
  Evidence: `./tools/verify`, started at 05:35Z before any edit and finished at 05:40Z: `3472 passed, 5 skipped, 4 xfailed, 2 warnings`, `1049 passed, 2 warnings`, `judge fixtures: 12 of 12 passed`, `147 passed, 1 warning`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 290s.`

- Observation: the eight new tests fail before `VideoLink` has the field and the macro prints the words, and each file collects with its existing tests passing beside them.
  Evidence: at 05:51Z, each in its own command with `DATABASE_URL=$(tools/test-db)` and `-q -p no:cacheprovider`: `tests/unit/test_video_links.py` printed `7 failed, 29 passed, 1 warning in 0.15s`; `tests/web/test_vote_result_block.py` printed `1 failed, 21 passed, 1 warning in 0.31s`. The commit that holds the tests failing is the one that adds this entry.

- Observation: M5's acceptance is met, with no carve-out. The two files pass at 36 and 22, and `./tools/verify` is green with the first tier at 3,480.
  Evidence: at 05:51Z, after the last edit, each in its own command with `DATABASE_URL=$(tools/test-db)` and `-q -p no:cacheprovider`: `tests/unit/test_video_links.py` printed `36 passed, 1 warning in 0.04s`; `tests/web/test_vote_result_block.py` printed `22 passed, 1 warning in 0.21s`. `./tools/verify`, started at 05:52Z and finished at 05:57Z: `3480 passed, 5 skipped, 4 xfailed, 2 warnings`, `1049 passed, 2 warnings`, `judge fixtures: 12 of 12 passed`, `147 passed, 1 warning`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 295s.`

- Observation: twenty-one rules of M5 were taken out, one at a time, of copies held in memory (a pytest plugin in the session scratchpad that compiles the altered `src/docket/services/video_links.py` over the imported module, or hands Jinja an altered `partials/_vote_result_block.html` through `jinja2.FileSystemLoader.get_source`; no committed file was edited), and the two files' 58 tests run against each in one command; the plugin with nothing altered printed `58 passed`. All twenty-one removals failed a test on the first run, so no assertion was added after the commit that holds the tests failing (`a0668cf`).
  Evidence: the phrase, four: the words never appended (3 failed); appended only to the chapter phrase (1); only to the plain phrase (2); appended to the YouTube phrase as well (1). The rule, eleven: no rule for a clip silent throughout (2); that rule after the test for a missing moment (1); the rule's `>=` a `>` (2); a missing moment labelled on a partly silent clip (1); a span's start excluded (1); its end included (2); no open end for a span that reaches the clip's end (1); every span open-ended (2); the open end's `>=` a `>` (1); no lower bound (1); a meeting with no sound row labelled (3). `link_for`, three: the flag never set (4); the flag set on a YouTube link (1); a moment in a silent span kept on Granicus although a stretch covers it (1). The template, three: the words never printed (1); always printed (3); printed whenever the label is Granicus (3). One thing no test can tell: whether a span's end past the clip's length (`end > duration_s`) is open-ended, because `sound.measure` never writes a span that ends past the duration; the module treats it as it treats one that ends at the duration.

From M6's session of 2026-11-18 (UTC) on the Legion, in this worktree, starting at commit `a023411`.

- Observation: the starting state is green, with the totals M5 left.
  Evidence: `./tools/verify`, run before any edit and finished at 06:08Z: `3480 passed, 5 skipped, 4 xfailed, 2 warnings`, `1049 passed, 2 warnings`, `judge fixtures: 12 of 12 passed`, `147 passed, 1 warning`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 289s.`

- Observation: the statements M6 writes into `docs/runbooks/transcripts.md` for the database owner were run by this session on a throwaway database (`tools/test-db`, migrations 1 to 48, no rows in either table), the writes inside a transaction that was rolled back. Each parsed and ran; the one that names the role could not run here.
  Evidence: the count printed `0`; the delete of the rejected rows `DELETE 0`; the read-only query of `granicus_clip_sound` its six column heads and `(0 rows)`; `DELETE FROM granicus_clip_sound WHERE meeting_id = 1;` printed `DELETE 0`; the two `UPDATE ... SET method_version` statements `UPDATE 0` each. `SELECT has_table_privilege('transcriber', 'granicus_clip_sound', 'INSERT');` printed `ERROR:  role "transcriber" does not exist`: the local server has no such role and this machine's database user cannot create one, so that line's `t` is the operator's to observe on production. None of them was run against production.

## Decision Log

- Decision: silence is stored per clip in a table of its own, `granicus_clip_sound`, keyed on the meeting, and not as a new `reason` on a `meeting_video_alignments` row.
  Rationale: silence is a property of the Granicus clip, not of one YouTube recording; a partly silent clip needs spans, which an alignment row of a rejected recording does not carry; and decision `0106` makes the transcriber's candidate query the only reader of `reason`, which a site that read it would break.
  Date/Author: 2026-11-17, the authoring session.

- Decision: a block is 60 seconds and is silent below -60 dBFS.
  Rationale: on the three clips measured whole (Surprises), silent blocks lay between -73.8 and -69.7 dBFS and audible ones between -40.6 and -17.8, with no block between -66 and -50, so -60 has about ten decibels of room on the silent side and twenty on the audible side. Sixty seconds is the size of the pieces the matcher already checks a stretch's ends in (`EDGE_S` in `transcriber/transcriber/align.py`) and keeps a three-hour clip to about 180 blocks. A block that is quiet but not silent (a recess with an open microphone) stays audible, which is the safe side for a public note that says "no sound".
  Date/Author: 2026-11-17, the authoring session.

- Decision: the clips already rejected are measured for sound because the operator deletes their rejected rows, not because the matcher's method version rises or the candidate query changes.
  Rationale: `ALIGN_METHOD_VERSION` means the matcher's arithmetic changed, and it has not. The candidate query's predicate is read by three hand statements in `docs/runbooks/transcripts.md` (the off switch, its restore, and the delete of one recording's rows), and leaving it untouched means none of them needs re-proving. Deleting a recording's rows is the documented way to have it measured again, and one statement with a `WHERE` covers the 42 recordings (decision `0026`).
  Date/Author: 2026-11-17, the authoring session.

- Decision: no link that opens the video at a moment is redirected to an untimed YouTube link when the moment is silent on Granicus; the Granicus link is kept and labelled "(no sound)".
  Rationale: a moment is stored on the Granicus clock, and the YouTube second for it is known only from an offset measured from the sound, which a silent stretch does not give. Sending a reader who clicked "Watch this vote" to the start of a three-hour recording, or to the wrong one of two parts, replaces a true link that says its limit with one that promises a moment and does not deliver it. The meeting page's untimed YouTube link is one click away and is now printed first.
  Date/Author: 2026-11-17, the authoring session.

- Decision: the meeting page notes silence only when the clip is silent throughout or for 600 seconds or more.
  Rationale: a stream that starts a few minutes before the meeting does is ordinary and not worth a note; ten minutes is the shortest gap the measured cases suggest a reader would miss (clip 2034 has 45 minutes). The figure is one constant, `NOTE_MIN_SILENT_S`.
  Date/Author: 2026-11-17, the authoring session.

- Decision: transcribing the YouTube recording when the Granicus clip is silent is not in this plan. Its successor is a plan to be authored under the slug `transcribe-youtube-when-granicus-is-silent`.
  Rationale: a transcript made from YouTube audio has its times on YouTube's clock, while every stored time of a Granicus meeting is on the Granicus clock (`docs/specs/video-links.md`, "The two clocks"); every reader of a transcript time (the item assignment by cue point, the minutes-versus-video link, the search cards) would have to learn which clock a transcript is on. That is a change of its own size. Today it would give a transcript to one meeting (meeting 14) and mend one (3197); M6 records it as debt with that count.
  Date/Author: 2026-11-17, the authoring session.

- Decision: the migration number, decision numbers, and debt ids are taken when the work is done, not here.
  Rationale: this plan names migration 048 because `origin/main` holds 047 as its highest on 2026-11-17 and no pull request is open. If `origin/main` holds a 048 when M2 starts, M2 takes the lowest free number, uses it in the file and test names, and records the change here. M6 numbers each decision record and each debt row with the lowest number above every one spent on `origin/main` and on any open pull request at that moment (`docs/DEBT.md` row `D70` states the rule); on 2026-11-17 the highest are decision `0111` and debt row `D169`.
  Date/Author: 2026-11-17, the authoring session.

- Decision: five points of the operator's review of 2026-11-17 are taken into the plan: `silent_s` is capped at `duration_s` in `sound.measure`; M1 tests a clip shorter than `MIN_TAIL_S`; the meeting page's N is never more than M minus 1; a clip silent throughout labels every Granicus link, whatever its moment, and a span that reaches the clip's end has no upper bound; and `measured_on` is the Chicago date.
  Rationale: each closes a case the first text left open. The review's rounding example (3,575 silent seconds of 3,600) cannot be written by `sound.measure`, whose audible blocks are 60 seconds or a tail of 10 or more, but 3,600 of 3,625 can, and it rounds to 60 of 60; N is capped and not turned into "no sound", because the page must not call a clip with an audible block silent. The cap on `silent_s` costs nothing; the sum can equal `duration_s` only when the spans are one span, which is exact, so no case that breaks the check was found, and the cap is there so none has to be ruled out. The review asked for UTC for the date; Chicago is used because the date is printed to readers of Birmingham's records and the site's other dates are Chicago's.
  Date/Author: 2026-11-17, the authoring session, on the operator's review.

- Decision: `meeting_detail` reads the sound through `clip_sound_for`, one query, and not from a `MeetingVideo`.
  Rationale: the review asked whether the route already loads a `MeetingVideo` it could read `sound` from. It does not: in `src/docket/web/public.py` the only call into `video_links` is `item_links` in the transcript route, and `meeting_detail` reaches `for_meetings` only inside `discrepancies.list_public_for_meeting`, behind the `MINUTES_VS_VIDEO_UI` flag, which returns rows and not the `MeetingVideo`. Calling `for_meeting` in the route would add three reads the page does not use.
  Date/Author: 2026-11-17, the authoring session, on the operator's review.

- Decision: `tests/integration/test_048_migration.py` keeps four test functions.
  Rationale: the review proposed two, to spare `./tools/verify` the rollback and re-apply of a fixture per test. Measured during authoring, the four tests of `tests/integration/test_046_migration.py`, which use the same fixtures, ran in 0.49 seconds together, against an integration tier of 108 seconds; the saving is not measurable and four functions name what failed. The budget overrun is real and is not this plan's to mend.
  Date/Author: 2026-11-17, the authoring session, on the operator's review.

- Decision: the migration is numbered 048, as the plan named it.
  Rationale: `origin/main`, fetched at the start of M2's session, holds 047 as its highest and no pull request is open (Surprises), so the fallback to another number was not needed.
  Date/Author: 2026-11-18, M2's session.

- Decision: M2's four migration tests and two writer tests assert more than the plan's sentences for them list, and the test counts are the plan's.
  Rationale: the plan names what each test shows and not every clause of the table. The removal check needs an assertion per clause, so the first migration test also shows that a meeting holds one row (a second insert raises `UniqueViolation`, which the writer's `ON CONFLICT (meeting_id)` depends on), that `silent_spans` defaults to `[]`, and that the up repeats harmlessly; the second also refuses a negative `silent_s` and a zero `duration_s` and admits a clip silent throughout (`silent_s` equal to `duration_s`, the case M4's note reads); the fourth also repeats the down. The first writer test also shows that the save does not commit (the caller's rollback takes it back), and the second changes every column between the two saves, the clip id and `measured_at` included, so no column of the `SET` list can be dropped unseen.
  Date/Author: 2026-11-18, M2's session.

- Decision: `save_clip_sound` converts the duration, the silent seconds, and each span's two numbers with `float()` before they are sent.
  Rationale: the module does not import numpy and reads the sound by attribute, so it cannot know whether a caller's figures are Python floats or numpy's; `sound.measure` returns Python floats today, and the conversion keeps the stored JSON a list of two-number lists whatever a later caller passes. The function sits at the end of the module, after `save_alignment`, which was the module's last function.
  Date/Author: 2026-11-18, M2's session.

- Decision: one sentence of the role file's existing comment is reworded: "lacks the last two GRANT statements of this file (meeting_videos and meeting_video_alignments)" now names the two statements by their tables and does not call them the last two.
  Rationale: the new grant is added after them, as the plan says, which made "the last two" false. The plan asks for the comment to be extended; leaving a sentence the same edit made untrue would send an owner with a role older than migration 042 to the wrong statements.
  Date/Author: 2026-11-18, M2's session.

- Decision: M3 changes three assertions of two existing tests in `transcriber/tests/test_measure.py`, and the version the file's `_cfg` builds, in the commit that holds the new tests failing.
  Rationale: the plan counts 12 existing tests and 3 new ones and does not say that two of the 12 pin what M3 changes. `test_a_measurement_with_two_stretches_is_saved_once_and_logged_once_per_stretch` asserted one commit for a meeting with one recording and none when the recording's save is refused; with the sound committed first those are two and one, and the second figure is the point of saving the sound first (a refused alignment save does not take it back). `test_main_measures_before_the_engine_loads_and_meeting_id_skips_the_measuring` asserts the run's version, which is `__version__`. Changing them with the tests and not with the code keeps the before state readable from git: five failed, of which three are new. The count of test functions is the plan's, 15.
  Date/Author: 2026-11-18, M3's session.

- Decision: the stand-in for `sound.measure` is set on the `transcriber.sound` module, which `measure.py` reaches as `sound.measure`, and the third new test has a second part: a database error on the sound's save ends the pass with `measure: skipped (...)`.
  Rationale: setting it on the module and not on `measure.sound` lets the file's tests run before `measure.py` imports `sound`. The plan states that a `psycopg2.Error` from the save is not caught beside the clip's fetch errors, and names no test for it; without one, a save moved inside the `try` that turns a clip's failure into `failed` rows would pass every test, so the rule is asserted inside a test the plan names.
  Date/Author: 2026-11-18, M3's session.

- Decision: the sound is saved by a helper of its own, `_save_sound` in `transcriber/transcriber/measure.py`, called in `_run` in the branch that runs when the clip's fetch succeeded, before the first check of the stop flag and the deadline for the meeting's recordings; `_granicus_features` returns a pair, the features and the `ClipSound`.
  Rationale: the plan says the save comes when the audio was fetched and before any recording is measured. Placing it before the stop check means a Ctrl-C or a passed deadline that arrives during the fetch still keeps what the fetch paid for; the row is true whether or not a recording is then measured. It sits outside the `try` whose `except Exception` turns a clip's failure into `failed` rows, so a `psycopg2.Error` from it reaches `measure_pass` and is logged as `measure: skipped (...)`, and any other error from it does the same. An error from `sound.measure` itself (no samples) is raised inside `_granicus_features` and is the clip's failure, as an unreadable WAV is. The line's two figures are printed with `%.0f`.
  Date/Author: 2026-11-18, M3's session.

- Decision: M4's ten tests assert more than the plan's sentences for them list, and the test counts are the plan's.
  Rationale: the removal check needs an assertion per clause. The second unit test also holds a clip of 5,430 seconds with 1,530 silent, which reads "26 of 91" only when a half rounds up (the plan's 45.3 and 100.3 read the same cut or rounded); the fourth also holds 600 silent seconds, which are noted, so the floor is included. The first loader test also holds a second meeting with no row, whose `sound` is `None` in the same call, and a meeting that does not exist; the second also shows that the same two rows are used once the clip id matches and the version is 2, so the version is a floor and not an equality. The first and fourth web tests hold the `title` and its Chicago date, and the first that it is on the Granicus link and not the YouTube one; the third compares the whole section with the one rendered before the row was inserted, and holds that a row on a meeting whose own video is on YouTube changes nothing.
  Date/Author: 2026-11-18, M4's session.

- Decision: in `src/docket/services/video_links.py` the statement is the constant `_SOUND_SQL` and one helper, `_clip_sounds(cur, ids)`, runs it and builds the `ClipSound` objects; `for_meetings` calls it on the cursor of its other three reads and `clip_sound_for` on a cursor of its own. `ClipSound` sits before `MeetingVideo`, and `clip_sound_for` between `for_meeting` and `item_links`. The loader converts the duration, the silent seconds, and each span's two numbers with `float()`.
  Rationale: the plan asks for the statement to be written once and used by both; a helper that also builds the objects keeps the conversion (the spans as a tuple of two-float tuples, the Chicago date) in one place too, so the two readers cannot differ. JSON whole numbers come back from psycopg2 as integers (the transcriber writes floats, a hand-written row may not), and the plan's test asks for floats.
  Date/Author: 2026-11-18, M4's session.

- Decision: the template prints each of the two links from a macro of its own, `_watch_video` and `_watch_youtube`, defined in the source-links section and called in the order `_youtube_first` decides (a note and a YouTube link to print); the `title` is the `<a>`'s second attribute, after `href`; the existing comment on the YouTube link is kept and extended to say why the links are macros.
  Rationale: the plan offers a macro per link or an if/else around the pair, and asks for each link's markup once; an if/else would print both blocks twice in the source. Each macro holds its link's own `{% if %}`, with the whitespace the blocks had, which is what keeps the section byte for byte the same without a note (Surprises). `_youtube_first` needs the YouTube link as well as the note because the plan says so, although a note with no YouTube link would print the same bytes either way.
  Date/Author: 2026-11-18, M4's session.
- Decision: M5's eight tests assert more than the plan's sentences for them list, and the test counts are the plan's.
  Rationale: the removal check needs an assertion per clause. The first unit test also holds a span's first second (780, and 0) as silent; the second, a moment between two spans, one just before a span, and a meeting with no sound row, none labelled; the third, a moment a stretch covers that lies inside a silent span, which still opens YouTube unlabelled, and a `VideoLink` built by hand as YouTube with the flag, whose phrase stays "video on YouTube"; the fourth, a second that cannot be read, which is a missing one; the fifth, a chapter with no second; the sixth, a wholly silent clip whose row holds no spans, and a negative moment, both labelled because the clip's two figures decide; the seventh, a moment on the clip's last second, and a clip whose last span stops before the clip's end, which labels neither that span's end nor a moment past the clip's end. The web test also holds a history row whose Granicus link has sound and says nothing.
  Date/Author: 2026-11-18, M5's session.

- Decision: the rule is a function of its own, `_in_silence(sound, moment)` in `src/docket/services/video_links.py`, placed before `link_for` and called once, in the `VideoLink` the Granicus branch returns; in the macro the words are printed by an `{% if %}` of their own after the label's `{% endif %}` and before the arrow.
  Rationale: the plan gives the rule's order (silent throughout, then a span, then false) and not its place; a pure function of two values keeps `link_for`'s branch one return, and the source button's call (`video` is None) gets false from the same line because it has no sound. In the macro the words follow the label, as the plan says; a link without a label (a host the builder does not know) never has the flag, since `link_for` sets it only on a Granicus link, so the two `{% if %}`s need not nest. A link with the flag reads "Watch this vote on Granicus (no sound) ↗".
  Date/Author: 2026-11-18, M5's session.

## Outcomes & Retrospective

As authored on 2026-11-17, nothing has been executed and there is no outcome to report.

## Context and Orientation

docket.pub is a Flask site over PostgreSQL that publishes Alabama council records. The site's code is under `src/docket/`; its tests are under `tests/` in tiers (`unit`, `web`, `services`, `integration`). A second program, the transcriber, lives under `transcriber/` with its own tests under `transcriber/tests/`. The transcriber runs on the operator's desktop (the Legion) inside Docker, not on the hosting service (Railway), and reaches the production database through a database role named `transcriber` that may touch only a few tables. `AGENTS.md` at the repository root is the map and names the one check command, `./tools/verify`.

A Granicus meeting is a row of `meetings` whose `external_id` is all digits (the clip id) and whose `video_url` is the player page, `https://bhamal.granicus.com/MediaPlayer.php?view_id=2&clip_id=<id>`. A YouTube recording attached to such a meeting is a row of `meeting_videos` (`provider = 'youtube'`). The two recordings of one meeting do not start at the same moment, so before the site may open YouTube at a second stored on the Granicus clock, the transcriber measures the offset between them from the sound. That is the measuring pass, `measure_pass` in `transcriber/transcriber/measure.py`, which runs at the start of an ordinary transcriber run. For each meeting that has a recording to measure it puts the Granicus clip's audio in a work folder as an 8 kHz mono 16-bit WAV file (`_granicus_features`), reads it with `align.read_wav` (which returns the samples as a numpy array of 16-bit integers), compares each of the meeting's recordings against it, and stores the result in `meeting_video_alignments`: `passed` rows, one per matching stretch, or one `rejected` or `failed` row. The recordings it measures are chosen by `alignment_candidates` in `transcriber/transcriber/db.py`; a recording `rejected` at the current method version is not chosen again until the database owner deletes its rows.

The site turns "this meeting, this second, this chapter" into a link in one module, `src/docket/services/video_links.py`. `for_meetings` loads a `MeetingVideo` per meeting (the `video_url`, the passed stretches as `Recording` objects, the consent block); `link_for` returns a `VideoLink` that opens YouTube at a converted second when a passed stretch covers the moment, and otherwise the Granicus player, at a chapter when the chapter id is all digits. `VideoLink.phrase` is the text templates print: "video on YouTube", "video chapter on Granicus", "video on Granicus", or "video". The vote link is printed by the macro `vote_source_link` in `src/docket/web/templates/partials/_vote_result_block.html` as "Watch this vote on <label>". The meeting page, `src/docket/web/templates/meeting_detail.html`, prints two untimed links in its source-links section (`<section class="mtg-sources">`): "Watch video" with the meta line "Granicus player", and, when the meeting has a YouTube recording and its own `video_url` is not on YouTube, "Watch on YouTube" with the meta line "council channel". The route is `meeting_detail` in `src/docket/web/public.py`, which passes `recordings=query.videos_for_meeting(meeting_id)` to the template.

"dBFS" is decibels relative to the loudest value a sample can hold: 0 is the loudest, and a level of -60 is a thousandth of that amplitude. "Silent" in this plan means a 60-second block of a clip's audio whose level is below -60 dBFS.

What was found, on GitHub issue #174 of `thinkdarrell/docket-pub` and in Surprises above: 42 recordings are `rejected` (38 `score`, 4 `no_window`). Every clip behind the ones tested is silent throughout or in part: the virtual meetings of February to July 2021, and single meetings in 2020, 2022, 2024, 2025, and 2026. The matcher is right to reject them and the YouTube recordings are the right ones.

Every reader and writer of what this plan adds or changes. The new table `granicus_clip_sound` has one writer, the transcriber (`save_clip_sound`, M2), and one reader, `video_links.py` (M4); it is deleted with its meeting by cascade. A row is used only when its `granicus_clip_id` equals the meeting's current `external_id`, the test `for_meetings` already applies to a measurement, so a row measured before an event id became a clip id, or against a clip the meeting no longer has, is ignored and replaced at the next measuring. No column of an existing table changes, no status gains a value, and `alignment_candidates` is not edited, so the three hand statements in `docs/runbooks/transcripts.md` that write `meeting_video_alignments` (the off switch, its restore, the delete of one recording's rows) behave as they do today. `VideoLink` gains a field with a default, so every existing construction and comparison of one keeps working; the tests that pin today's phrases keep passing because the field is false unless a clip's sound says otherwise.

The states that would make the new sentence false, and what happens in each. A meeting whose own video is on YouTube (`yt-` external id) has no sound row and its template branch is not touched. A meeting whose clip was replaced in place under the same clip id after it was measured keeps a stale row, as its measurement does today (`docs/DEBT.md` row `D99`); M6 adds this to that row. A meeting with a sound row and no YouTube recording any more (the recording was moved to another meeting row) still prints the note, which is still true of the clip, and prints no YouTube link. A clip whose every recording passed before this plan shipped is never fetched again, so it has no sound row and no note even if part of it is silent; M6 records this as debt. A clip never compared with a YouTube recording (no recording attached) is never measured; meeting 2541 is one.

## Plan of Work

### M1: the silence rule

Create `transcriber/transcriber/sound.py`. It imports numpy and nothing else of the project. It holds four constants and their meaning in comments (`SOUND_METHOD_VERSION = 1`, raised when the arithmetic or a constant changes; `BLOCK_S = 60`; `SILENCE_FLOOR_DBFS = -60.0`; `MIN_TAIL_S = 10`), the frozen dataclass `ClipSound`, and the function `measure`, all as given under Interfaces and Dependencies.

The rule `measure` applies. The samples are cut into consecutive blocks of `BLOCK_S` seconds. What is left after the last whole block is a block of its own when it holds at least `MIN_TAIL_S` seconds, and is otherwise part of the block before it; when there is no block before it, it is the only block. A block's level is 20 times the base-10 logarithm of (the root-mean-square of its samples, taken as 64-bit floats, divided by 32768); a block whose root-mean-square is zero is silent. A block is silent when its level is below `SILENCE_FLOOR_DBFS`. Neighbouring silent blocks are joined into one span from the first block's start to the last block's end, in seconds, the end never past the duration. `duration_s` is the number of samples over the rate, `silent_s` the sum of the spans' lengths and never more than `duration_s` (`min(duration_s, the sum)`, so that a rounding in the sum cannot break the table's check that `silent_s <= duration_s`), and `spans` the spans in order. No samples raises `ValueError`.

Create `transcriber/tests/test_sound.py` with eight test functions and no parametrizing, each building its samples with numpy at 8,000 samples a second. Noise for an audible block is `numpy.random.default_rng(0).normal(0, 1000, n)` cast to 16-bit integers (about -30 dBFS). The eight: six hundred seconds of zeros give `duration_s == 600.0`, `silent_s == 600.0`, and `spans == ((0.0, 600.0),)`; six hundred seconds of noise give no spans and `silent_s == 0.0`; noise for 300 seconds, zeros for 1,500, noise for 3,600, and zeros for 600 give `spans == ((300.0, 1800.0), (5400.0, 6000.0))` and `silent_s == 2100.0`; sixty seconds of the constant sample value 33 are not silent and sixty seconds of the constant value 32 are (20·log10(33/32768) is -59.94 and 20·log10(32/32768) is -60.21); 605 seconds of zeros give one span `(0.0, 605.0)` (a 5-second tail joins the block before it); 600 seconds of zeros followed by 15 seconds of noise give `spans == ((0.0, 600.0),)` and `duration_s == 615.0` (a 15-second tail is its own block); five seconds of zeros (40,000 samples), a clip shorter than `MIN_TAIL_S` with no block before it, are one block and give `duration_s == 5.0` and `spans == ((0.0, 5.0),)`; and an empty array raises `ValueError`.

### M2: the table, the grant, and the writer

Create `src/docket/migrations/048_granicus_clip_sound.py` in the shape of `src/docket/migrations/046_alignment_stretches.py` (a module docstring that says what and why, then `SQL_UP` and `SQL_DOWN` strings) and register it in the list in `src/docket/migrations/runner.py` after `docket.migrations.047_public_hearings`. The up creates the table exactly as given under Interfaces and Dependencies, with `IF NOT EXISTS`; the down drops it with `IF EXISTS`. The migration grants nothing: as its docstring must say, the `transcriber` role's grant is in `scripts/sql/create_transcriber_role.sql`, and on a database whose role already exists the owner runs the one statement by hand.

In `scripts/sql/create_transcriber_role.sql` add, after the grant on `meeting_video_alignments`, the statement `GRANT SELECT, INSERT, UPDATE ON granicus_clip_sound TO transcriber;`, and extend the comment at the top of the file: what the table holds, that the role does not delete from it (a row is replaced in place and goes with its meeting), and that a role created before migration 048 lacks this one statement, which the owner runs alone.

In `transcriber/transcriber/db.py` add `save_clip_sound` as given under Interfaces and Dependencies, beside `save_alignment`. It is one `INSERT ... ON CONFLICT (meeting_id) DO UPDATE` that sets every column, `measured_at` to `now()`; the spans go in as JSON through `psycopg2.extras.Json`, a list of two-number lists. It reads the sound by attribute so this module still does not import numpy, and it does not commit.

Tests. Create `tests/integration/test_048_migration.py` after the pattern of `tests/integration/test_046_migration.py` (the same skip mark against Railway, a prefix `m048-` for the meetings it seeds, fixtures that roll back 48 and re-apply) with four tests: after the up, a row with `duration_s = 600`, `silent_s = 120`, and spans `[[0, 120]]` inserts and reads back with those values; a row whose `silent_s` exceeds its `duration_s` raises `psycopg2.errors.CheckViolation`; deleting the meeting deletes its sound row; after the down the table does not exist (`to_regclass('granicus_clip_sound')` is NULL) and the up applies again. In `tests/integration/test_transcriber_role.py` add one test, `test_can_save_clip_sound_and_not_delete_it`: `_priv("granicus_clip_sound", p)` is true for `SELECT`, `INSERT`, and `UPDATE` and false for `DELETE`. In `transcriber/tests/test_db.py` add two tests beside `test_save_alignment_twice_leaves_one_row_holding_the_second_calls_values`, using the same fixtures that file already has for a meeting with recordings: one save stores the candidate's meeting id, its `external_id` as `granicus_clip_id`, the method version, the duration, the silent seconds, and the spans; a second save for the same meeting with other values leaves one row holding the second call's values.

### M3: the pass stores what it measured

In `transcriber/transcriber/measure.py`, `_granicus_features` reads the WAV once and returns two things, the features as today and `sound.measure(samples)` on the same samples. In `_run`, when the Granicus audio of a meeting was fetched, and before any of its recordings is measured, call `tdb.save_clip_sound(conn, group[0], clip_sound, method_version=sound.SOUND_METHOD_VERSION)`, commit, and log on the module's logger at INFO

    measure meeting <meeting id> clip <clip id>: sound duration=<seconds>s silent=<seconds>s spans=<count>

with the two figures as whole seconds. The save comes first so that a YouTube download that fails afterwards does not lose it. A `psycopg2.Error` from the save is not caught there: it ends the pass through the path that exists (`measure: skipped (...)`), which is what a missing table or a missing grant should do, exactly as migration 042's absence does today. A meeting whose Granicus fetch failed saves no sound row. Update the module docstring to say so. Set `__version__` in `transcriber/transcriber/__init__.py` to `"0.7.0"`.

In `transcriber/tests/test_measure.py` the stand-ins need to return something for the new call: read how `_wire` and `FakeDB` stub `align.read_wav`, `align.features`, and `save_alignment`, give `sound.measure` a stand-in that returns a fixed `ClipSound(duration_s=6019.0, silent_s=2719.0, spans=((0.0, 60.0), (780.0, 2040.0)))`, and have `FakeDB` record `save_clip_sound` calls. Add three tests: a meeting with two recordings saves its sound once, commits it, and logs `measure meeting <id> clip <clip>: sound duration=6019s silent=2719s spans=2`; a meeting whose Granicus fetch raises `AudioFetchError` saves no sound; a meeting whose YouTube download raises still has its sound saved before the `failed` row.

### M4: the site reads it and the meeting page says it

In `src/docket/services/video_links.py` add the constants `MIN_SOUND_VERSION = 1` (a floor, compared with `>=`, as `MIN_METHOD_VERSION` is) and `NOTE_MIN_SILENT_S = 600.0`, the frozen dataclass `ClipSound`, a field `sound: ClipSound | None = None` at the end of `MeetingVideo`, and the function `clip_sound_for`, all as given under Interfaces and Dependencies. `for_meetings` gains a fourth read and sets `sound` on each `MeetingVideo`; `clip_sound_for` runs the same statement for one meeting, and the statement is written once, as a module constant both use:

    SELECT s.meeting_id, s.duration_s, s.silent_s, s.silent_spans, s.measured_at
      FROM granicus_clip_sound s
      JOIN meetings m ON m.id = s.meeting_id
     WHERE s.meeting_id = ANY(%s)
       AND s.method_version >= %s
       AND s.granicus_clip_id = m.external_id

`ClipSound.note` is the meeting page's text: `"no sound"` when `silent_s >= duration_s`; otherwise `"no sound for N of M minutes"` when `silent_s >= NOTE_MIN_SILENT_S`, where N and M are the silent seconds and the duration in whole minutes, a half rounding up (`int(seconds / 60 + 0.5)`), and N is never more than M minus 1 (`min(N, M - 1)`): a clip with any audible block must not read as silent for all of its minutes, which rounding alone allows (3,600 silent seconds of 3,625 round to 60 of 60); otherwise `None`. `measured_on` is the date of `measured_at` in `America/Chicago` (`measured_at.astimezone(ZoneInfo("America/Chicago")).date()`), the zone the site already dates Birmingham's records in, so the date does not depend on the database session's time zone. Extend the module docstring with one paragraph on the sound row.

In `src/docket/web/public.py`, `meeting_detail` passes `clip_sound=video_links.clip_sound_for(meeting_id)` to the template. In `src/docket/web/templates/meeting_detail.html`, in the source-links section, set a variable that is the note when `clip_sound` has one and `'MediaPlayer.php'` is in `meeting.video_url`. With a note, the Granicus link's meta line reads `Granicus player · <note>` and the `<a>` carries `title="Measured by docket.pub on <measured_on in ISO form>"`; and when the page also has the YouTube link (the existing `_youtube` test), the YouTube link is printed before the Granicus link. Without a note the section is byte for byte what it is today. Print each link's markup once: move the two existing `<a>` blocks into the order the variable decides (a Jinja macro per link, or an if/else around the pair), without changing their text.

Tests. In `tests/unit/test_video_links.py` add four: `ClipSound(2516.0, 2516.0, ((0.0, 2516.0),), date(2026, 11, 17)).note == "no sound"`; `ClipSound(6019.0, 2719.0, ..., ...).note == "no sound for 45 of 100 minutes"` (2,719 / 60 is 45.3 and 6,019 / 60 is 100.3); a clip of 3,625 seconds with 3,600 silent (sixty silent blocks and a 25-second audible tail) reads `"no sound for 59 of 60 minutes"`; and a clip with `silent_s == 599.0` has no note. In `tests/integration/test_video_link_loader.py` add two, extending the `_Seed` helper with a method that inserts a sound row: a row at the current clip id and version 1, seeded with `measured_at` given explicitly as `2026-11-18 02:30:00+00`, comes back on `for_meetings(...)[id].sound` and from `clip_sound_for(id)` with its spans as a tuple of two-float tuples in order and `measured_on == date(2026, 11, 17)` (that instant is 8:30 in the evening of the 17th in Chicago); a row against another clip id, and a row at version 0, each give `None`. In `tests/web/test_meeting_recordings.py` add four, seeding sound rows for the meetings its `rows` fixture already makes: on the Granicus meeting with a YouTube recording and a wholly silent clip, the source-links section contains `Granicus player · no sound` and "Watch on YouTube" comes before "Watch video" in it; with 2,719 silent seconds of 6,019 it contains `no sound for 45 of 100 minutes`; with 300 silent seconds the section has no "no sound" and "Watch video" comes first, as today; and on the Granicus meeting without a YouTube recording a wholly silent clip prints the note and no YouTube link.

### M5: a link into silence says so

In `src/docket/services/video_links.py`, `VideoLink` gains `no_sound: bool = False` as its last field, and `phrase` appends ` (no sound)` to either Granicus phrase when it is true. In `link_for`, in the branch that returns a Granicus link, `no_sound` is decided in this order when the `MeetingVideo` has a `sound`. First, a clip silent throughout (`silent_s >= duration_s`) gives true whatever the moment is, a missing one and one at or past the clip's end included: a cue point can sit on the last second or a second past it, and no moment of such a clip has sound. Otherwise it is true when the moment is a number that lies in one of the spans, start included and end excluded, except that a span whose end reaches the clip's end (`end >= duration_s`) has no upper bound, so a moment at or after the end of a clip that ends in silence is labelled too. Otherwise it is false. Nothing else in `link_for` changes: a moment a passed stretch covers still opens YouTube, also when it lies in a silent span, and a YouTube link never carries the flag. In `src/docket/web/templates/partials/_vote_result_block.html`, the macro `vote_source_link` prints ` (no sound)` after the label when `v.video_link.no_sound`. The three templates that print `phrase` (`partials/transcript_body.html`, `partials/minutes_vs_video.html`, `admin/_discrepancy_row.html`) and the Granicus branch of `partials/source_anchor_button.html` need no edit, because the phrase carries the words. Update the docstrings of `VideoLink` and `link_for`.

Tests. In `tests/unit/test_video_links.py` add seven, each building a `MeetingVideo` for a player URL with `sound=ClipSound(6019.0, 2719.0, ((0.0, 60.0), (780.0, 2040.0), (5160.0, 6019.0)), date(2026, 11, 17))` unless said otherwise: a moment at 900 with chapter id `"77"` gives a Granicus link with `no_sound` true and the phrase `video chapter on Granicus (no sound)`; a moment at 2,040 (the end of a span, excluded) gives `no_sound` false and the phrase `video chapter on Granicus`; with a `Recording` covering 2,162 to 5,132 and a moment at 3,000 the link opens YouTube and `no_sound` is false; with no moment and a wholly silent clip the phrase is `video on Granicus (no sound)`; with no moment and the partly silent clip the phrase is `video on Granicus`; on a wholly silent clip of 2,516 seconds a moment at 2,516 with a chapter id gives `no_sound` true; and on the partly silent clip a moment at 6,025, past the clip's end, gives `no_sound` true because the last span reaches the end. In `tests/web/test_vote_result_block.py` add one beside `test_source_link_names_youtube_when_the_link_opens_youtube`: a vote whose `video_link` is a Granicus `VideoLink` with `no_sound=True` renders "Watch this vote on Granicus (no sound)".

### M6: the documents

Edit `docs/specs/video-links.md`: a new section, "A clip with no sound", after "The measuring pass", stating in the present tense the table, the rule and its constants (naming `transcriber/transcriber/sound.py` as their owner and not repeating the values that file sets, except where a sentence needs one), when the pass writes a row, which rows the site trusts, the meeting page's note and the order of its links, and the "(no sound)" label; the sentence in "What a link says" gains the two labelled phrases and the vote link's; "The measuring pass" gains the log line; "Known limits" gains the three limits named below as debt. Edit `docs/specs/meeting-types.md`, the paragraph that begins "The same page lists a row's recordings", to state the note and the order. Edit `docs/runbooks/transcripts.md`, "Measuring YouTube recordings (the backlog)": the statement that has the rejected recordings measured again (given under Validation and Acceptance), the read-only query that lists sound rows, and, under "The transcriber role", the new grant. Edit `transcriber/README.md`, "Measuring YouTube recordings": one paragraph on the sound line in the log and what it means. Edit `ARCHITECTURE.md`, the bullet that lists what the `transcriber` role can write, to add `granicus_clip_sound`. Edit `docs/specs/index.md` only if its line for `video-links.md` lists the file's sections.

Write decision records under `docs/decisions/` in the format of `docs/decisions/DECISION_FORMAT.md`, numbered by the rule in the Decision Log, for the decisions of this plan that bind later work: silence is stored per clip and trusted by clip id and version; a block is 60 seconds and silent below -60 dBFS, with the three clips' figures as the data; a link into a silent stretch is labelled and not redirected to an untimed YouTube link. Add to decision `0030`'s successors nothing: a record is written once; the new record on the table names `0030` and `0076` as the records it extends.

In `docs/DEBT.md`, add to row `D99` that a clip replaced in place also keeps a stale sound row, and add three rows numbered by the same rule. One: the operator's steps for this plan, in the order under Validation and Acceptance, with "the pull request merges" as its trigger. Two: a clip whose every recording passed before this plan shipped, and a clip with no YouTube recording attached, is never measured for sound, so a partly silent clip among them carries no note; the trigger is a reader's or the operator's report of one, or the successor plan below, whichever comes first. Three: the transcriber still transcribes the Granicus audio of a silent clip (a wholly silent one ends `low_speech` and unpublished, a partly silent one publishes with unmarked holes), with the counts from Surprises and the successor plan's slug, `transcribe-youtube-when-granicus-is-silent`, as its trigger.

This milestone does not move the plan file and does not write the closing retrospective; the lifecycle's last two steps belong to whoever closes the plan after the pull request's review.

## Concrete Steps

Every command is run from the root of the plan's worktree, `.claude/worktrees/silent-granicus-says-so` under the checkout, which needs its own `venv/` (built the way `docs/specs/operations.md`, Local environment, says). Each session starts by reading `AGENTS.md` and this file, runs `./tools/verify` before it edits, and runs it again before it records the milestone.

One file of the site's tests:

    DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_video_links.py -q -p no:cacheprovider

One file of the transcriber's tests, in a command of its own:

    DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest transcriber/tests/test_sound.py -q -p no:cacheprovider

Drop the throwaway database afterwards with `tools/test-db --drop`. Both forms were run during authoring against files that exist today and printed the counts under Surprises. Never run bare `pytest` against the database `.env` names: `tests/conftest.py` refuses it.

The migration's state:

    DATABASE_URL=$(tools/test-db) venv/bin/python -m docket.migrations.runner --status

Expected after M2, as its last line: `[applied] 48: docket.migrations.048_granicus_clip_sound`.

## Validation and Acceptance

Each milestone is accepted on the checks below, observed by the session that ran them and recorded in Progress and Surprises with the lines the commands printed. The totals are the baselines under Surprises plus the tests each milestone adds; a session that finds a different baseline at its start (because `origin/main` moved) records the baseline it found and holds the milestone to that figure plus its own additions.

M1. `transcriber/tests/test_sound.py` prints `8 passed`. The transcriber check of `./tools/verify` prints `142 passed` (134 and 8), and `./tools/verify` ends `all 6 checks passed`.

M2. `tests/integration/test_048_migration.py` prints `4 passed`; `tests/integration/test_transcriber_role.py` prints `6 passed` (5 and 1); `transcriber/tests/test_db.py` prints `31 passed` (29 and 2); the status command prints the line above; `./tools/verify` ends `all 6 checks passed` with the integration tier at `1047 passed` (1,042 and 5) and the transcriber check at `144 passed`.

M3. `transcriber/tests/test_measure.py` prints `15 passed` (12 and 3); `(cd transcriber && ../venv/bin/python -c "import transcriber; print(transcriber.__version__)")` prints `0.7.0` (it printed `0.6.0` during authoring); `./tools/verify` ends `all 6 checks passed` with the transcriber check at `147 passed`.

M4. `tests/unit/test_video_links.py` prints `29 passed` (25 and 4); `tests/integration/test_video_link_loader.py` prints `8 passed` (6 and 2); `tests/web/test_meeting_recordings.py` prints `15 passed` (11 and 4); `./tools/verify` ends `all 6 checks passed` with the first tier at `3472 passed` (3,464 and 8) and the integration tier at `1049 passed`.

M5. `tests/unit/test_video_links.py` prints `36 passed` (29 and 7); `tests/web/test_vote_result_block.py` prints `22 passed` (21 and 1); `./tools/verify` ends `all 6 checks passed` with the first tier at `3480 passed` (3,472 and 8).

M6. `grep -c "granicus_clip_sound" docs/specs/video-links.md docs/runbooks/transcripts.md ARCHITECTURE.md scripts/sql/create_transcriber_role.sql` prints a count of 1 or more for each of the four files; `grep -n "no sound" docs/specs/video-links.md docs/specs/meeting-types.md` prints lines from both; `docs/DEBT.md` holds three new rows whose ids are above every id on `origin/main`, one of which lists the six operator steps below in order; `docs/decisions/` holds the three new records; `./tools/verify` ends `all 6 checks passed`.

The operator's steps, after the pull request merges. No milestone session takes any of them, and their order matters: a rejected row deleted before the new transcriber image is running is measured by the old image, which stores no sound, and is then final again.

1. Deploy the web service and the worker from a clean `main` (`scripts/deploy.sh --service docket-web`, then `--service worker`). The web service applies migration 048 when it starts. Check with `railway ssh --service docket-web "cd /app && python -m docket.migrations.runner --status"`.
2. As the database owner, grant the role its access: `GRANT SELECT, INSERT, UPDATE ON granicus_clip_sound TO transcriber;`
3. On the Legion, rebuild the transcriber image so it runs version 0.7.0 (`docker compose build` in `transcriber/`, as `transcriber/README.md` says).
4. As the database owner, have the rejected recordings measured again. First count them: `SELECT count(*) FROM meeting_video_alignments WHERE status = 'rejected' AND reason IS DISTINCT FROM 'operator';` printed 42 on 2026-11-17. Then, in one statement: `DELETE FROM meeting_video_alignments WHERE status = 'rejected' AND reason IS DISTINCT FROM 'operator';` A row the owner switched off (`rejected` with the reason `operator`) is kept.
5. Run the backlog command of `docs/runbooks/transcripts.md` until its `measure done` line says `remaining=0`: `docker compose run --rm transcriber --limit 0 --measure-limit 400 --max-hours 8`. Each meeting logs one `sound` line.
6. Read what was stored, read-only: `SELECT s.meeting_id, m.meeting_date, s.granicus_clip_id, round(s.duration_s) AS duration_s, round(s.silent_s) AS silent_s, jsonb_array_length(s.silent_spans) AS spans FROM granicus_clip_sound s JOIN meetings m ON m.id = s.meeting_id ORDER BY m.meeting_date;` Expected from the authoring measurements: meeting 275 (clip 1414) with 2,516 and 2,516; meeting 3197 (clip 2034) with 6,019 and 2,719 in five spans. Then look at the two pages named under Purpose, at a desktop width and at a phone width, and play the Granicus player of meeting 275 for a few seconds to hear that it is silent. A clip the page calls silent that is audible in the player is an issue on `thinkdarrell/docket-pub` with the row's figures, and the note is turned off for that meeting by deleting its sound row.

## Idempotence and Recovery

Every step of every milestone can be repeated. The migration creates with `IF NOT EXISTS` and drops with `IF EXISTS`; `venv/bin/python -m docket.migrations.runner --down 48` removes the table and nothing else. `save_clip_sound` replaces a meeting's row. The measuring pass writes a sound row each time it fetches a clip, so a wrong row is corrected by deleting the meeting's alignment rows (the documented way to have a recording measured again) and running the pass.

If the site is deployed and the table is empty, every page renders as it does today, because the note and the label appear only where a row exists. If the transcriber runs version 0.7.0 before step 1 or step 2, the pass logs `measure: skipped (...)` naming the missing table or privilege and the run goes on to transcribe; nothing is lost and the next run after the grant measures. To take the note and the label off the whole site without a deploy, the database owner runs `DELETE FROM granicus_clip_sound;` (the rows return as clips are measured again), or, to keep them off, `UPDATE granicus_clip_sound SET method_version = 0;`, which puts every row below the site's floor; the restore is `UPDATE granicus_clip_sound SET method_version = 1 WHERE method_version = 0;`.

A milestone that will not fit its session is split in place in Progress (completed, remaining), the split is recorded in the Decision Log, and the session stops.

## Artifacts and Notes

The prototype of the rule, as run during authoring (Surprises), for comparison with M1's module. It is a prototype's output, not the module's:

    clip1424.wav duration=3761s blocks=63 silent_blocks=0
      spans: []
      audible blocks: min=-30.2 median=-22.8 max=-17.8 dBFS
    clip1414.wav duration=2516s blocks=42 silent_blocks=42
      spans: [(0, 2516)]
      silent blocks:  min=-73.8 max=-70.2 dBFS
    clip2034.wav duration=6019s blocks=101 silent_blocks=46
      spans: [(0, 60), (120, 180), (240, 720), (780, 2040), (5160, 6019)]
      audible blocks: min=-40.6 median=-32.5 max=-24.3 dBFS
      silent blocks:  min=-70.9 max=-69.7 dBFS

The block counts follow from the rule: 6,019 seconds is 100 whole blocks and a 19-second tail that counts on its own (101); 2,516 is 41 and a 56-second tail (42); 3,761 is 62 and a 41-second tail (63).

The findings this plan rests on are on issue #174 of `thinkdarrell/docket-pub`, in the comments of 2026-11-17.

## Interfaces and Dependencies

No new library: numpy is already a dependency of the transcriber (`transcriber/requirements.txt`) and of the site.

In `transcriber/transcriber/sound.py`, at the end of M1:

    SOUND_METHOD_VERSION = 1
    BLOCK_S = 60
    SILENCE_FLOOR_DBFS = -60.0
    MIN_TAIL_S = 10

    @dataclass(frozen=True)
    class ClipSound:
        duration_s: float
        silent_s: float
        spans: tuple[tuple[float, float], ...]

    def measure(samples: np.ndarray, rate: int = 8000) -> ClipSound: ...

The table, at the end of M2:

    CREATE TABLE IF NOT EXISTS granicus_clip_sound (
        meeting_id       INTEGER PRIMARY KEY REFERENCES meetings(id) ON DELETE CASCADE,
        granicus_clip_id TEXT NOT NULL,
        method_version   INTEGER NOT NULL,
        duration_s       DOUBLE PRECISION NOT NULL CHECK (duration_s > 0),
        silent_s         DOUBLE PRECISION NOT NULL CHECK (silent_s >= 0 AND silent_s <= duration_s),
        silent_spans     JSONB NOT NULL DEFAULT '[]'::jsonb,
        measured_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    );

`silent_spans` is a JSON array of two-number arrays, `[start_s, end_s]`, in order, on the Granicus clock.

In `transcriber/transcriber/db.py`, at the end of M2 (`cand` is the `AlignmentCandidate` that file defines; its `meeting_id` and `external_id` are the row's `meeting_id` and `granicus_clip_id`; `sound` is read by its attributes `duration_s`, `silent_s`, and `spans`):

    def save_clip_sound(conn, cand: AlignmentCandidate, sound, *, method_version: int) -> None: ...

In `src/docket/services/video_links.py`, at the end of M4:

    MIN_SOUND_VERSION = 1
    NOTE_MIN_SILENT_S = 600.0

    @dataclass(frozen=True)
    class ClipSound:
        duration_s: float
        silent_s: float
        spans: tuple[tuple[float, float], ...]
        measured_on: date

        @property
        def note(self) -> str | None: ...

    def clip_sound_for(meeting_id: int) -> ClipSound | None: ...

and `MeetingVideo` has the field `sound: ClipSound | None = None`. At the end of M5, `VideoLink` has the field `no_sound: bool = False`. The site's `ClipSound` and the transcriber's are two classes on purpose: the transcriber is a separate program that the site does not import, and the site's carries the date and the note.

Revision note, 2026-11-17: the plan as first authored.

Revision note, 2026-11-17, before any milestone ran: revised on the operator's review of the plan (seven points; five taken, two answered in the Decision Log). Changed: the M1 Progress entry and M1's rule and tests (a cap on `silent_s`; an eighth test, a five-second clip); M4's note (N capped at M minus 1, a fourth unit test) and `measured_on` (the Chicago date, an explicit `measured_at` in the loader test); M5's rule (a wholly silent clip labels every Granicus link; a span reaching the clip's end is open-ended) and its tests (seven); and every total under Validation and Acceptance that those tests move (the transcriber check 142, 144, 147; `tests/unit/test_video_links.py` 29 and 36; the first tier 3,472 and 3,480). The Validation clauses were re-read against the changed rules: 3,600 of 3,625 seconds gives N 60 capped to 59 and M 60; 2,719 of 6,019 still gives 45 of 100; a moment at 2,040 on the partly silent clip is still unlabelled, because the span ending there does not reach the clip's end.
