# Video links land on the moment: on YouTube when the recording has been measured against the Granicus clip and covers that second, and on the Granicus chapter otherwise

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `plans/PLANS.md`.

## Purpose / Big Picture

docket.pub shows Birmingham City Council meetings with links into the meeting video: "Watch this vote" on an agenda item's page, "video chapter" beside an item on the transcript page and in the minutes-versus-video comparison, and a "View Source: video at" button. Today every one of those links opens the city's Granicus player (the video site at bhamal.granicus.com), and many of them open it at the very start of a two-hour recording, because the Granicus player can only jump to a numbered chapter and about half of the 2026 meetings store agenda items under an id that is not a chapter number. The council streams the same meetings to YouTube, whose player can open at any second, and 329 of Birmingham's 1,048 Granicus meetings already have their YouTube recording attached in the database. But the two recordings of one meeting do not start at the same moment: in eight sampled pairs the YouTube recording began between 101 and 3,232 seconds after the Granicus clip did, so a time stored for Granicus cannot simply be handed to YouTube.

After this plan, four things are true that are not true today.

First, the transcriber (the desktop program on the operator's Legion computer that already downloads meeting audio to make transcripts) measures, at the start of an ordinary run and without the graphics card, where each attached YouTube recording sits on its Granicus clip's clock. It does this by comparing the sound of the two recordings. For each recording it stores one row: the offset in seconds (Granicus seconds minus YouTube seconds), the stretch of the Granicus clock the recording covers, the match score, the version of the method, when it was measured, and whether the match passed. It keeps none of the audio. Each recording is measured on its own, so a meeting streamed in two numbered parts, or uploaded twice, has one row per recording.

Second, every timed video link the site renders opens YouTube at the converted second, `https://www.youtube.com/watch?v=<id>&t=<N>s`, when a recording whose match passed covers that moment, and opens the Granicus player otherwise: when the recording has not been measured yet, when its match was rejected, or when the moment falls outside the stretch it covers. Times stay stored on the Granicus clock and are converted only when the link is built. Each link names the site it opens ("Watch this vote on YouTube", "video chapter on Granicus").

Third, a consent item links to the start of the consent agenda. The consent agenda is the block of routine items the council passes with one vote; the clerk reads them out in a quick run, so their individual Granicus cue points land seconds apart inside that reading and mean nothing on their own. A consent item whose cue point sits inside that run, or that has no cue point at all, links to the run's first cue point. An item whose cue point is outside the run, including one pulled off consent and discussed separately, links to its own moment.

Fourth, the Granicus fallback lands on the chapter. Agenda items that were ingested from the agenda PDF before the recording existed keep ids such as `event-2715-1`; the code that later fills in their video timestamps now also writes the real Granicus chapter id, and an operator script corrects the rows already stored.

How to see it working once the plan has shipped and the operator has run the steps under Validation and Acceptance. On meeting 3184 (2026-10-27, Granicus clip 2026, YouTube video `FR84h22hQvA`, measured offset 635.48 seconds), a link for non-consent item 64 (cue point 2,256 s) opens `https://www.youtube.com/watch?v=FR84h22hQvA&t=1620s`; a link for any consent item among items 1 to 63 whose cue point lies in the 1,990 to 2,085 second run, and for consent items 7 to 9, which have no cue point, opens the start of the consent agenda at `t=1354s`; and a link for non-consent item 3 (2,145 s) opens its own moment at `t=1509s`. On the 2026-10-13 meeting (clip 2017), whose YouTube recording is a 30-minute piece of an 85-minute meeting, a moment in the first 53 minutes opens the Granicus chapter instead. The meeting page still shows its plain "Watch video" (Granicus player) link beside "Watch on YouTube". In the repository, `./tools/verify` passes with new tests that fail before each milestone's code exists.

## Progress

M1, M2, M3, M4, M5, M6, and M7 were executed on 2026-11-06 and their evidence is in "M1 as executed, 2026-11-06", "M2 as executed, 2026-11-06", "M3 as executed, 2026-11-06", "M4 as executed, 2026-11-06", "M5 as executed, 2026-11-06", "M6 as executed, 2026-11-06", and "M7 as executed, 2026-11-06" under Artifacts and Notes; M8 is next, and nothing of M8 has been executed. A completed entry is written as `- [x] (YYYY-MM-DD HH:MMZ) <text>` with the time the work was observed, never an estimate, and an entry's text is never reworded once written (decision `0037`; the judge in `docs/capabilities/judge-milestone.md` identifies entries by their text).

- [x] (2026-11-06 05:01Z) M1: `transcriber/transcriber/align.py` measures where one recording sits on another's clock from two 8 kHz WAV files with numpy alone, and `transcriber/tests/test_align.py` proves it on synthetic audio: a shifted noisy copy recovers its offset and passes, unrelated audio and a recording with a cut are rejected, and the verdict rule reproduces the labelled table in Artifacts and Notes.
- [x] (2026-11-06 05:17Z) M2: migration 042 creates `meeting_video_alignments`, the `transcriber` role file grants the role SELECT on `meeting_videos` and SELECT, INSERT, UPDATE on the new table, and `transcriber/transcriber/db.py` lists the recordings that need measuring and saves a measurement, proved against the throwaway database.
- [x] (2026-11-06 05:35Z) M3: an ordinary transcriber run measures up to `--measure-limit` attached YouTube recordings before the engine loads, with one stored row and one log line per recording, leaves no audio in the work folder, and carries on to transcription whatever the measuring pass meets; `transcriber/tests/test_measure.py` proves it with stubbed fetches.
- [x] (2026-11-06 05:49Z) M4: `src/docket/services/video_links.py` builds a video link from a second on the Granicus clock (YouTube at the converted second when a passing recording covers it, the Granicus chapter otherwise), finds a meeting's consent block, and loads a meeting's passing recordings; `src/docket/web/video_urls.py` is gone and its tests moved.
- [x] (2026-11-06 06:04Z) M5: the item page's vote link and the transcript page's item link come from the link builder, land on the item's moment under the consent rule, and name the site they open.
- [x] (2026-11-06 06:26Z) M6: the minutes-versus-video block, the admin discrepancy row, and the video branch of `partials/source_anchor_button.html` come from the link builder and name the site they open; the `chapter_url` Jinja global is gone.
- [x] (2026-11-06 06:46Z) M7: `_backfill_video_timestamps` writes the cue point's Granicus chapter id together with the timestamp in one statement per meeting, and `scripts/correct_agenda_chapter_ids.py` lists and corrects the meetings whose cued items still carry another id, with a dry run.
- [ ] M8: the close: `docs/specs/video-links.md` and the edited specs read in the present tense, the durable decisions are in `docs/decisions/` from `0076`, `docs/DEBT.md` carries the operator's after-merge steps and the follow-ups, and `D9` names what is now specified.

## Surprises & Discoveries

At authoring no session had run, so there was no surprise to record. What the author observed while writing the plan (the baseline test totals, the three role tests that fail under the default database role, the 72-pair measurement the pass mark was chosen from) is in Context and Orientation and in Artifacts and Notes, each marked as observed on 2026-11-05.

As revised on 2026-11-05, still before any milestone ran: an external review of the plan was checked against the spike's audio and against production, read-only, in the operator's session. What that found (clock drift of up to 113 parts per million between the two recordings of one meeting, a cut near the end of a recording that neither the authored nor the revised matcher detects, nine attached recordings longer than four hours, and eight OCR votes on consent items that fall after the consent block) is recorded in "Observed at the review, 2026-11-05" under Context and Orientation and in Artifacts and Notes, and the changes it led to are in the Decision Log and the revision note at the bottom.

From the M1 session, 2026-11-06. Nothing in M1 contradicted the plan; these are the observations a later session can use.

- Observation: the module written from the reference arithmetic reproduces every synthetic figure the plan states, to within 0.1 of a score, on a signal this session drew itself (the plan gives the seeds but not the order of the draws, so the samples are not the author's).
  Evidence: the seven lines under "M1 as executed, 2026-11-06" in Artifacts and Notes, beside the plan's own: 40.9 for the plan's 40.8, 5.4 for 5.5, 44.8 for 44.7, 49.5 and 13.3 for 49.5 and 13.4, 39.4 for 39.4, 27.0 for 26.9, and the same window counts, coverage, and reasons in every case.

- Observation: each test that the plan calls "the test of" a revised rule does fail when that rule is taken out, checked by running the ten tests against altered copies of the module built in memory (the committed file was not edited).
  Evidence: with `AGREE_S` at 1.0 only the offset-step test fails; with the end window anchored to the end of the recording only the runs-past-the-clip test fails; with no end window five fail (shifted copy, starts before the clip, cut, runs past the clip, offset step); under the whole authored rule the same five fail. The cut test fails without the end window because it asserts 4 of 6 windows; the verdict there is `conflict` either way.

- Observation: in the 1.5-second step case the whole-recording offset is not a coin flip between the two true offsets, although the second piece is the longer by 3.5 seconds. A session that redraws the signal can expect 400.0 again.
  Evidence: the best score within half a second of 400.0 was 27.03 and within half a second of 401.5 was 24.87.

- Observation: the spike's folder still exists, and this session did not read its audio. Before weighing its own instructions the session listed the folder once (`ls`, which printed `data`, `fetch.log`, and several `.sql` files) and then stopped: the workflow that started the session confines it to this worktree and says nothing outside the repository is available to it. The rerun of the nine matched pairs that M1 asks for "if the spike's audio is still readable" was therefore not made. M1 calls it evidence, not acceptance.
  Evidence: no line of the form `passed offset=635.48s ...` from real audio exists from this session; the Decision Log entry of 2026-11-06 says who can produce them and how.

- Observation: the session's permission system refused `cat .env` (the refusal named credentials), so the Concrete Steps check "`cat .env` prints one line" was replaced by a test that the file exists.
  Evidence: `test -f .env` printed `.env exists`, and the baseline `./tools/verify` built `postgresql://thinkdarrell@/docket_test_7c0790d1` and passed the three role tests that fail under the default role.

From the M2 session, 2026-11-06. One clause of M2's acceptance states a count the repository cannot print; the rest held.

- Observation: M2's first acceptance command prints `19 passed`, not the `13 passed` the plan states. The plan's sum takes "the 3 and 2 that existed" from the functions at the top level of `tests/integration/test_038_migration.py` and `test_040_migration.py`; each file also holds tests in a class (two in `TestCalendarEventForeignKey`, four in `TestMeetingVideos`), so they held 5 and 6 before this milestone, and with the role file's 3 the three files printed `14 passed` before any edit.
  Evidence: the per-file counts under "M2 as executed, 2026-11-06" in Artifacts and Notes, taken before the first edit; 14 plus the 3 and 2 this milestone adds is 19. The totals `./tools/verify` prints are as the plan states (integration `695 passed`, transcriber `110 passed`), because those were summed from the tier totals and not from these files.

- Observation: the first draft of the five producer tests, the one committed failing, left two of the candidate rules unpinned. The session ran the five tests against copies of the two SQL strings altered in memory, one rule removed at a time (the committed file was not edited): with the version compared by equality instead of as a floor, and with a `rejected` row retried like a `failed` one, all five still passed.
  Evidence: `version compared by equality: 0 failed` and `rejected rows retried like failures: 0 failed` on the first run. After a row at a later method version was added to the third test and the second test's rejected row was made 30 days old, the same run printed one failing test for each of eight removals: the never-measured-first ordering, the primary-first ordering, the hidden filter, the all-digit filter, the clip-id comparison, the version floor, the retry of failures (two tests), and the finality of a rejected row. Both additions sit inside functions the plan names, so the count stays at five.

- Observation: the role file's grants are enough for the three functions as written; nothing else (a sequence, another table) is needed. Checked once on the throwaway database from a scratch script, not a committed test: the role was created from the file, a session did `SET ROLE transcriber`, and the functions were called as the producer will call them.
  Evidence: the script printed `current_user: transcriber`, one candidate, `backlog: 1`, two saves of the same recording, `backlog now: 0`, and then `InsufficientPrivilege: permission denied for table meeting_video_alignments` for a DELETE and `InsufficientPrivilege: permission denied for table meeting_videos` for an UPDATE. The committed role tests read `has_table_privilege` only, as the three that existed do.

- Observation: `git grep -n "rollback_migration" -- tests` confirms the plan's three places: `test_040_migration.py` twice and `test_038_migration.py` once roll 040 back. `tests/integration/test_migration_013.py` also rolls migrations back, a fixed list from 28 down to 21 and then 13, none of which drops `meeting_videos`, so it needed no change.
  Evidence: the full `./tools/verify` run with migration 042 applied printed `695 passed` for integration.

- Observation: one command of this session was mistyped and ran no test. A redirect to a path under an unset `$TMPDIR` failed inside `export DATABASE_URL=$(tools/test-db 2>...)`, so the variable was exported empty for the two pytest commands that followed in that shell. Neither printed a `passed` or `failed` line. Read from the code afterwards, not observed as output: `tests/conftest.py` refuses a database not named `docket_test_*` before collection, and `transcriber/tests/test_db.py` skips when its URL is empty. The command was run again correctly and that run is the evidence recorded.
  Evidence: the correct run printed `Applying migration 42: docket.migrations.042_meeting_video_alignments`, `19 passed`, and `26 passed`.

From the M3 session, 2026-11-06. Every figure in M3's acceptance was observed as written; these are the observations a later session can use.

- Observation: the thirteen new tests passed on the first run of the code, so the session checked that they can fail: the eleven tests of `test_measure.py` were run against copies of `transcriber/transcriber/measure.py` altered in memory, one rule taken out at a time (the committed file was not edited). Each of 27 removals fails at least one test.
  Evidence: the list under "M3 as executed, 2026-11-06" in Artifacts and Notes. The revised rules each have their own test: with a Granicus failure counted once per row only the three-recordings test fails; with the handler on one recording narrowed to named exception types the `RuntimeError` test fails (and two others); with the count not set back after a measured recording, and with the pass never stopping, only the three-in-a-row test fails.

- Observation: the stubbed tests cannot show that what ffmpeg writes at `-ar 8000` is what `align.read_wav` accepts, nor that an offset survives a lossy codec, so the session ran the pass once from a scratch script with real ffmpeg (8.0.1 on this machine), the real matcher, and the real `transcriber.db` functions on the throwaway database. Only the two network fetches were stood in for. It measured correctly through each format.
  Evidence: the M1 synthetic pair (seconds 400 to 1,305 of the seed-1 signal, with noise) stored as Opus in WebM at 24 kbit/s against the clip stored as 16 kHz FLAC in the archive printed `passed offset=400.00s covers=400.0-1305.0s score=40.8 runner_up=3.6 windows=4/4`, and against the clip stored as AAC in MP4 printed the same with `score=41.1`; M1 printed 40.9 for the raw samples. The transcript is under "M3 as executed".

- Observation: read from `transcriber/transcriber/cli.py` as this milestone leaves it, not observed in Docker: the speech model is loaded whenever the measuring pass returns, also when there is nothing to transcribe. The backlog command (`--limit 0 --measure-limit 400`) therefore loads the model onto the graphics card and then exits with nothing claimed, and so does a run stopped with Ctrl-C during the measuring. M3 orders the calls this way ("only then does it construct `FasterWhisperEngine`; then it calls `run_loop`"), so it was built as written and `transcriber/README.md` says so. A candidate for the debt rows M8 writes.
  Evidence: `test_main_measures_before_the_engine_loads_and_meeting_id_skips_the_measuring` records `["connect", "measure", "engine", "loop"]`; nothing between `measure_pass` and `load_engine()` in `main()` reads the limit or the stop flag.

- Observation: also read from the code: the measuring pass writes no row to `producer_heartbeats`. `run_loop` writes `started` when it begins, which is now after the pass and after the model has loaded, so during a long backlog run the heartbeat table shows nothing for the host. The plan asks for no heartbeat from the pass and none was added. A second candidate for M8.
  Evidence: `transcriber/transcriber/measure.py` calls three functions of `db.py` (`alignment_candidates`, `alignment_backlog`, `save_alignment`) and no other.

- Observation: `cli.main()` calls `load_dotenv()`, which finds this worktree's `.env` from the package folder and puts its `DATABASE_URL` into the process for good. A test that calls `main()` would hand that variable to every test that runs after it in the same process, so the one test that does replaces `cli.load_dotenv` with a function that does nothing.
  Evidence: from `transcriber/`, with the variable removed from the environment, a one-off command printed `before main: DATABASE_URL set: False` and, after `cli.main(['--help'])`, `after main: DATABASE_URL set: True` (the value was not printed).

- Observation: one scratch command of this session failed before it ran anything. The end-to-end script was first started by its path from `transcriber/`, where Python puts the script's own folder on the import path and not the current one; it stopped at `ModuleNotFoundError: No module named 'transcriber'` before it connected. It was started again with `PYTHONPATH` set to `transcriber/`, and that run is the evidence recorded.
  Evidence: the first run printed the traceback and `drop exit 0`; no row was written by it.

From the M4 session, 2026-11-06. Every figure in M4's acceptance was observed as written; these are the observations a later session can use.

- Observation: the twenty new tests passed on the first run of the module, so the session checked that they can fail: both files were run against copies of `src/docket/services/video_links.py` altered in memory, one rule taken out at a time (the committed file was not edited). Of 42 removals, 38 failed at least one test on the first try, and one more after an assertion was added.
  Evidence: the list under "M4 as executed, 2026-11-06" in Artifacts and Notes. The one with no failing test on the first try was a consent block that leaves out its own first cue point: the first item's own id was also the block's chapter id, so both rules returned the same pair. `test_item_moment_follows_the_consent_rule` now also uses a block whose chapter id is its second item's, and that removal fails it.

- Observation: three clauses of the module cannot be told apart from their absence by any test, and are kept. `AND mv.provider = 'youtube'` in the recordings read: the table's CHECK admits no other provider (migration 040), so no row can show the difference. `AND video_timestamp_seconds IS NOT NULL` in the consent read: `consent_block` drops a cue point with no second itself. The early return of `item_links` for a meeting with no `video_url`: without it the same empty result comes back one query later, because `link_for` builds no link.
  Evidence: `provider not compared`, `cue-less consent rows read`, and `item links not short-cut for a meeting without video` each printed `0 failed` and `28 passed`.

- Observation: `git mv` was used as M4 says, but git does not record the move as a rename, because the file grew from 56 lines to more than 330 in the same commit. `git log --follow tests/unit/test_video_links.py` will stop at this session's first commit; the eight tests' earlier history is under the old path.
  Evidence: `git status --short` before that commit printed `A  tests/unit/test_video_links.py` and `D  tests/unit/test_video_urls.py`, not an `R` line.

- Observation: the deleted module's compiled file is still on disk, untracked and ignored, and cannot be imported. This is the stale `.pyc` the acceptance uses `git grep` to avoid.
  Evidence: `find src tests -name "video_urls*"` printed `src/docket/web/__pycache__/video_urls.cpython-310.pyc` and nothing else; `venv/bin/python -c "import docket.web.video_urls"` printed `ModuleNotFoundError: No module named 'docket.web.video_urls'`.

- Observation: `ARCHITECTURE.md`'s Services entry lists what the layer owns by name (ingest, query, badges, the briefing, and so on) and does not name timed video links. M4 names no edit to that file and none was made. A candidate for M8, which writes the standing documents.
  Evidence: read from the Services section of `ARCHITECTURE.md` (line 21 on); `git grep -n "video_links" -- ARCHITECTURE.md docs/specs` prints nothing.

From the M5 session, 2026-11-06. Every figure in M5's acceptance was observed as written; these are the observations a later session can use.

- Observation: the links were seen on the item page through the real route, which no test of this milestone does (the vote block's tests render the partial with stand-in votes, and the query's tests stop at the `VideoLink`). A scratch script seeded meeting 3184's shape on the throwaway database (three consent items cued at 1,990, 2,037, and 2,085 seconds, a consent item with no cue point, non-consent item 64 at 2,256 seconds, one OCR vote on each of three of them) and requested `/al/birmingham/items/<id>/` with Flask's test client, before and after a passing measurement (offset 635.48) was inserted.
  Evidence: with no measurement the three pages printed `Watch this vote on Granicus ↗` to `...clip_id=99062026&amp;meta_id=371164` (item 64) and `&amp;meta_id=371101` (the consent item in the run and the one with no cue point: the first chapter of the run). With the measurement they printed `Watch this vote on YouTube ↗` to `watch?v=FR84h22hQvA&amp;t=1620s`, `&amp;t=1354s`, and `&amp;t=1354s`, the three figures in Purpose. The transcript is under "M5 as executed".

- Observation: the seven new tests and the rewritten one passed on the first run of the code but for one that the session's own draft broke (next entry), so the session checked that they can fail: the three files were run with one rule taken out in memory at a time, by a scratch pytest plugin that recompiles `_attach_video_links` from altered source or alters a template's source as Jinja loads it (no committed file was edited). Of 22 removals, 21 fail at least one test.
  Evidence: the list under "M5 as executed, 2026-11-06" in Artifacts and Notes. The one with no failing test is `video_url` not being required of a vote before a link is built: `link_for` returns no link for a meeting with no `video_url`, so the same `None` comes back two queries later. The clause is kept; it spares those two reads.

- Observation: one test of the session's first draft was wrong, and the mistake was not visible in the before state. Two OCR votes of one meeting were inserted at the same second, which `idx_votes_ocr_unique` (`meeting_id, video_timestamp, source`, migration 034) refuses. Before the code existed that test failed earlier, at its first assertion, with the `AttributeError` the before state records; with the code it reached the second insert.
  Evidence: the first run after the code printed `psycopg2.errors.UniqueViolation: duplicate key value violates unique constraint "idx_votes_ocr_unique"` with `Key (meeting_id, video_timestamp, source)=(16, 2400, video_ocr) already exists.` and `1 failed, 54 passed`. The second vote was moved to 2,401 seconds (its expected link from `t=1764s` to `t=1765s`) and the next run printed `55 passed`. The test file therefore differs by that one line pair between the commit that holds the failing tests and the commit that holds the code.

- Observation: three links change beyond naming their site, each following from a rule already in this plan; a reader comparing pages before and after will see them. An OCR vote on a meeting other than the item's own no longer carries the item's chapter id (the old template appended the item's `meta_id` to the other meeting's player URL, a chapter of a different clip). On the transcript page an item whose id is not a chapter id reads "video on Granicus ↗" where it read "video chapter ↗" on the same plain URL, and an item with no `external_id` at all now has that link where it had none. And on a meeting whose own video is on YouTube the transcript's item link reads "video on YouTube ↗" and opens at the item's cue point when it has one.
  Evidence: the first two are asserted (`later_link` in `test_ocr_vote_without_a_measurement_gets_the_granicus_chapter_link`; `plain` in `test_item_link_opens_the_granicus_chapter_when_nothing_is_measured`). The third is read from `link_for` and M4's unit tests of it; no test or scratch run of this session rendered a transcript page for a `yt-` meeting.

- Observation: `git grep -n "chapter_url(" -- src/docket/web` now prints two lines, `admin/_discrepancy_row.html` and `partials/minutes_vs_video.html`, where it printed four after M4. Those are M6's two templates; the `chapter_url` Jinja global is still registered for them.
  Evidence: the command's output, run at 06:05Z.

- Observation: no standing document states the wording or the rule of either link, so nothing outside the code and this plan went stale in this milestone.
  Evidence: `git grep -n "Watch this vote\|video chapter\|vote_source_link" -- docs/specs docs/runbooks README.md ARCHITECTURE.md` prints nothing. M8 writes `docs/specs/video-links.md`.

From the M6 session, 2026-11-06. Every figure in M6's acceptance was observed as written; these are the observations a later session can use.

- Observation: the five new tests passed on the first run of the code, so the session checked that they can fail: the four files were run with one rule taken out in memory at a time, by a scratch pytest plugin that recompiles `discrepancies._attach_video_links` from altered source, wraps a function, or alters a template's source as Jinja loads it (no committed file was edited). Of 37 removals, 35 fail at least one test.
  Evidence: the list under "M6 as executed, 2026-11-06" in Artifacts and Notes. The two with no failing test cannot be told apart from the code as committed. A row with no item that still asks `item_moment`: the item's columns come through a LEFT JOIN and are all NULL for such a row, so `item_moment` returns no chapter by itself; the test on `agenda_item_id` is kept because it says what M6 says. The admin row's link printed when the row has a `video_url` instead of a `video_link`: inside the template's test for a second, a row has one exactly when it has the other, since `link_for` builds a link whenever there is a base URL.

- Observation: the plan's first source-button test could not render at all in the test's own app as it stood: that app's allowlist of hosts (`_TEST_ALLOWLIST` in `tests/unit/test_source_anchor.py`) did not hold `youtube.com`, so the partial's safety check refused a YouTube anchor before the video branch was reached. `youtube.com` was added to the test's list; production's own list already holds it.
  Evidence: `STATIC_ALLOWED_DOMAINS` in `src/docket/web/source_security.py` lists `youtube.com` and `youtu.be`; with the host added, the before state shows the old branch rendering that anchor as `watch?v=abc&amp;t=65` under "View Source: video at 1:05".

- Observation: three assertions were added to the new tests after the commit that holds them failing, so the test files differ between that commit and the one that holds the code. Each came from the removal check or from a state this plan names.
  Evidence: two were added while the list of removals was being written, before its first run, because no assertion then standing could have failed under them: in `tests/integration/test_minutes_vs_video_public.py`, that `create_app` registers `video_link` as `video_links.link_for` and no `chapter_url` (no page includes the source button, so nothing else can show what the application registers); and in `tests/unit/test_source_anchor.py`, a fragment on the Granicus anchor's URL in the two cases with no chapter id. The third was added after the first run, which printed `89 passed` for "admin row's link printed on video_url, not video_link": in `tests/integration/test_admin_discrepancies.py`, the meeting with no `video_url` at the end of the new function. It does not pin that removal (nothing can) but it does pin the state, and the removal "a meeting with no video still gets a link" was added with it and fails.

- Observation: one removal of the session's first removal run was itself malformed and is not in the recorded list: it was meant to restore the old markup for every host and instead printed the word `OLD` in place of a link. It failed seven tests and showed nothing the two "branch gone" removals do not; it was deleted from the scratch plugin before the run that is recorded.
  Evidence: the first run's line read `button: old markup for every host  7 failed, 82 passed`; the recorded run has 37 removals and no such line.

- Observation: four links change beyond naming their site, each following from a rule already in this plan; a reader comparing pages before and after will see them. A discrepancy row whose item's id is not a chapter id reads "video on Granicus ↗" where it read "video chapter ↗" on the same plain URL. A discrepancy row on a consent item inside the consent block carries the block's chapter where it carried the item's own id. A discrepancy row on a meeting whose own video is on YouTube reads "video on YouTube ↗" and opens at the row's own second, where it read "video chapter ↗" on the plain watch URL. And the source button on a Granicus player anchor no longer appends `&t=<N>` (which the player ignores) and prints no time.
  Evidence: the first two and the last are asserted (`plain` in both integration tests; `chapter(371101)` in the public block's test; the second source-button test). The third is read from `link_for` and M4's unit tests of it; no test or scratch run of this session rendered a discrepancy for a `yt-` meeting.

- Observation: read from `link_for`, not a fault found by a test: when the source button is given a `video`, the link is built from `video.video_url`, and the anchor's own URL is used only for the partial's safety check. `video.video_url` is not itself put through `is_source_url_safe`. No page passes `video` today, so nothing renders this; the partial's header comment says the variable must be the `MeetingVideo` of the meeting the anchor's video belongs to. A candidate for the known limits M8 writes.
  Evidence: `base = video.video_url if video is not None else url` in `src/docket/services/video_links.py`; the third source-button test passes the same player URL in both places.

- Observation: the source button still treats an anchor at second 0 as having no timestamp, although `link_for` would open YouTube at `&t=0s`. The branch's guard is the truthy test it had, which `test_video_timestamp_zero_renders_as_start_of_meeting` pins as a strict expected failure; M6 names no change to it.
  Evidence: `tests/unit/test_source_anchor.py` printed `4 xfailed` before and after this milestone.

- Observation: each of the four list functions now makes three more reads (those of `video_links.for_meetings`) when at least one of its rows has a second, and none when no row has one. Read from the code, not timed.
  Evidence: `_attach_video_links` calls `for_meetings` once with the distinct meetings of the rows that have a second, and `for_meetings` returns `{}` for no ids without a query (Interfaces, "As built in M4").

- Observation: no standing document states the wording or the rule of any of the three surfaces, so nothing outside the code and this plan went stale in this milestone. One docstring names the old wording and is still true: `src/docket/web/filters.py` gives "View Source: video at 1:23:45" as an example of `format_timestamp`, which is what the button still prints for a host that is neither YouTube nor a Granicus player page.
  Evidence: `git grep -n "video chapter\|View Source: video\|video_link(" -- docs/specs docs/runbooks README.md ARCHITECTURE.md` prints nothing; `git grep -c "chapter_url" -- . ':!plans' ':!docs/superpowers'` prints three files: the module that defines it (6 lines), its unit tests (9), and the public block's test (2: the assertion that the global is gone and its comment).

From the M7 session, 2026-11-06. Every figure in M7's acceptance was observed as written. The first observation below is a risk in what the correction script selects, read from the code, which the operator should weigh before step 3 under Validation and Acceptance; the rest are for the sessions after this one.

- Observation: read from the code, not observed on any real row: the correction script can pair an item with the wrong index point on a meeting whose items were first ingested from the player page and not from the agenda PDF. For such a meeting `agenda_items.item_number` is the point's position in the player's list (`item_number=str(i + 1)` in `GranicusAdapter.fetch_agenda_items`), not the agenda number, while the rewrite matches a point to an item by the "ITEM N" in the point's title. The ordinary ingest pass never reaches such a meeting (all its items have timestamps, so the precheck returns), and the script lists it only when one of its cued, numbered items carries an id that is not all digits, which for a player-page item means the adapter's fallback id `<clip>-<position>`, given when the point had no `data-id`. On such an item the rewrite is still refused when another row of the meeting holds the chapter id, as a row does when that point was itself ingested as an item with its `data-id`. What is left is a meeting whose items carry fallback ids while today's page carries `data-id`s that no row holds: there the item at position N would be given the chapter id of the point titled "ITEM N", a different item whenever the list has an entry before item 1. Whether production holds any such row is not known from this worktree (the developer database holds no cued item, as "Observed at authoring" says).
  Evidence: the selection in `correct_chapter_ids` asks only for "a numbered item with a timestamp and an id that is not all digits", as M7 specifies; The id `1950-15` in the tests has the fallback's shape, but it is written by hand in `tests/support/transcript_fixtures.py` and shows the shape only, not that production holds it; the one set of agenda rows in the repository that was exported from production, `tests/fixtures/transcript_2543/agenda_items.json`, holds only `event-2712-...` ids. The sixth query under "The operator's read-only queries" counts the cued, numbered items whose id is neither a chapter id nor an agenda-PDF id; it was parsed on the throwaway database at 06:46Z and printed `0|0|0` there. If it prints 0 on production the case does not arise; if not, the dry run's lines for those meetings are read before the write, and a narrower selection (ids beginning `event-`) is a decision for the operator, not one this session made.

- Observation: the five new tests passed on the first run of the code, so the session checked that they can fail: the file was run with one rule taken out in memory at a time, by a scratch pytest plugin that re-executes `docket.services.ingest` or `scripts.correct_agenda_chapter_ids` from altered source before collection (no committed file was edited). Of 42 removals, 41 fail at least one test.
  Evidence: the list under "M7 as executed, 2026-11-06" in Artifacts and Notes. The one with no failing test is the returned count being the computed one instead of the statement's own (`cur.rowcount`): in one process the two are the same number, since the rows are read and written in one transaction. The statement's count is kept because it is what makes "one statement per meeting" testable: with `page_size` left at psycopg2's 100 the 120-item test reads 20.

- Observation: the correction test of the first draft, the one committed failing, left four clauses free, found while the list of removals was being written and before its first run: a stored chapter id that differs from its point's (kept), a cued item with no id at all (rewritten and selected), "newest first" where the newest meeting is not the lowest row id, and everything the script prints. The test was extended inside the same function, so the file differs between the commit that holds the failing tests and the one that holds the code.
  Evidence: the first run of the code against the committed tests printed `12 passed, 1 warning in 1.41s` at 06:39Z; after the additions it printed `12 passed, 1 warning in 1.55s`; the removals named "a stored chapter id is rewritten too", "correct: an item with no id does not count", "correct: oldest row first", and the seven beginning "script:" each fail the extended test.

- Observation: the mocked tests hand `_backfill_video_timestamps` ready-made index points, so they cannot show that what the real adapter reads off a player page is what the rewrite accepts. The session ran the script once from a scratch file through the real `GranicusAdapter`, with only `requests.get` stood in for by a made-up page, on a meeting of meeting 3184's shape (64 numbered items on `event-2715-N` ids, all cued but consent items 7 to 9). It rewrote 61 ids in one run and the links changed as Purpose says they should.
  Evidence: the transcript under "M7 as executed": `61 rows would change`, then `61 rows changed`, then `0 meetings, 0 rows`; item 64's link went from "video on Granicus" on the plain player to "video chapter on Granicus" at `&meta_id=371164`, and consent items 8 (no cue point) and 20 to the consent block's first chapter, `&meta_id=371101`. The page was written by the session from the plan's description of one (`<div class="index-point" time="..." data-id="...">ITEM N - ...</div>`); no real player page was fetched, and none is in `tests/fixtures`.

- Observation: the repository holds one meeting's real agenda rows in exactly the state this milestone is for, and the session ran the script on them. `tests/fixtures/transcript_2543/agenda_items.json` was exported read-only from production on 2026-10-10 (its README says so): meeting 2543, clip 2016, 2026-10-06, 66 rows, of which 65 are numbered, all 65 cued, all on ids `event-2712-N`, no number repeated, and one un-numbered `event-2712-minutes-approval`. Every numbered item has its timestamp, so the ingest precheck returns for this meeting and only the script reaches it. With those rows inserted on the throwaway database and a player page made up from them, the script rewrote all 65 and left the timestamps as they were.
  Evidence: the second transcript under "M7 as executed": `fixture rows: 66 numbered: 65 distinct numbers: 65 repeated numbers: []`, `65 rows would change`, `65 rows changed`, `timestamps unchanged by the write: True`, then `0 meetings, 0 rows`. The rows are real and the page is not: its points sit at each item's own stored second, titled `ITEM <item number>`, with invented `data-id`s. That the real page's titles name "ITEM N" is implied by the rows themselves, whose timestamps only this function's title match could have filled; what a real `data-id` looks like is the plan's statement, not something this session saw.

- Observation: read from the code: a meeting with a numbered item that never gets a cue point (meeting 3184's consent items 7 to 9) passes the precheck on every ingest run, as Context already says, and so any id the rewrite leaves alone in such a meeting is logged at WARNING on every run, once per row. A candidate for the debt row M8 writes about that per-run fetch.
  Evidence: the two `logger.warning` calls in `_backfill_video_timestamps` sit inside the loop over the meeting's items and run whether or not anything is written; the forced second call in `test_duplicated_number_and_taken_chapter_id_are_left_alone` logs the same four warnings again and changes nothing.

- Observation: read from the code: a meeting the script lists but cannot fully correct is listed again on every run and costs one player-page request each time, and the list is cut at `--limit` newest first. If 50 or more such meetings stood ahead of a correctable one, the default run would never reach it; a larger `--limit` does.
  Evidence: the selection has no memory of an earlier run; `LIMIT %s` follows `ORDER BY m.meeting_date DESC NULLS LAST, m.id DESC`. The operator's second query, after the write, prints the residue.

- Observation: read from the code: `_ingest_agenda_items` returns the pass's count, which `ingest_municipality` adds into the figure it logs as "Agenda items: %d inserted" and returns as `IngestResult.agenda_items_inserted`. That was already true of filled timestamps; it now also counts a row whose id alone was rewritten.
  Evidence: `return _backfill_video_timestamps(adapter, meeting_id, raw_meeting)` in `_ingest_agenda_items`, unchanged by this milestone, and `total_items += count` in `ingest_municipality`.

- Observation: no standing document names the backfill, either script, or the chapter id, so nothing outside the code and this plan went stale in this milestone.
  Evidence: `git grep -n "_backfill_video_timestamps\|backfill_agenda_timestamps\|correct_agenda_chapter_ids\|correct_chapter_ids" -- docs/specs docs/runbooks README.md ARCHITECTURE.md docs/DEBT.md GOALS.md` prints nothing. M8 writes the spec and the operator's order.

## Decision Log

- Decision: measurements live in a new narrow table, `meeting_video_alignments`, whose primary key is `meeting_video_id`, not in new columns on `meeting_videos`.
  Rationale: the transcriber connects with a database role that may write only its own tables (decision `0030`). A separate table lets that role gain write access to exactly one new table and read access to `meeting_videos`, instead of UPDATE on a table the worker's YouTube sync owns. One row per recording is the goal's own shape ("stores per recording"), so the recording's id is the key and no sequence needs a grant.
  Date/Author: 2026-11-05, plan author (Claude), from the scope brief's default.

- Decision: a measurement records the Granicus clip id it was measured against (`granicus_clip_id`), and both the link builder and the measuring pass treat a row whose clip id differs from the meeting's current `external_id` as no measurement.
  Rationale: `youtube_meetings.sync_city` can move a recording from one meeting row to another (absorption, `UPDATE meeting_videos SET meeting_id`), and a meeting's `external_id` changes when an upcoming event becomes a clip. An offset is only true against the clip it was measured on; a stale one would send a reader to the wrong second with nothing on the page to show it.
  Date/Author: 2026-11-05, plan author.

- Decision: the matcher is the spike's method (cross-correlation of smoothed log band-energy envelopes at 8 kHz, 4 bands, 25 frames a second, 0.4 s smoothing, 8 s moving mean removed) made sturdier by a three-part pass mark and a conflict rule: a recording passes only when the whole-recording score is at least 9.0, the score exceeds the best score at any other offset by at least 4.0, at least 60 percent of its 5-minute windows that lie inside the clip find their best nearby match within 1 second of the whole-recording offset, and no window matches strongly (score 8.0 or more) at a different offset.
  Rationale: chosen from data, as the goal asks. On 2026-11-05 the author ran this exact rule over the spike's audio: 9 matched pairs (8 clips, one with two uploads) and all 63 mismatched pairings of the same recordings. All 9 matched pairs pass; their lowest score is 12.3 (clip 2017), lowest margin 7.0, lowest window share 13 of 18. All 63 mismatched pairs are rejected on score alone; their highest score is 7.3, largest margin 1.83, largest window share 3 of 6. The score alone separates the sample, but only by 7.3 against 12.3, so the margin and the window share are required as independent confirmation: a wrong offset cannot satisfy windows that each search their own neighbourhood. The conflict rule rejects a recording that was cut or edited (two true offsets) instead of linking half of it wrongly. The table is in Artifacts and Notes.
  Date/Author: 2026-11-05, plan author.
  Superseded in part on 2026-11-05 by the review decisions at the end of this log: the agreement tolerance is 2 seconds, not 1, and one more window is measured at the end of the overlap. The scores, the three-part pass mark, and the conflict score stand.

- Decision: the stored coverage is the span from the first confirmed window's start to the last confirmed window's end, mapped onto the Granicus clock and clipped to the clip, not the whole overlap of the two recordings.
  Rationale: "on YouTube when it can be trusted". Outside the confirmed span nothing has checked that the two recordings still run together; a moment there falls back to Granicus. The cost is that up to 5 minutes at the end of a recording (the part past the last whole window) and any unconfirmed windows at either edge link to Granicus.
  Date/Author: 2026-11-05, plan author.
  Superseded in part on 2026-11-05 by the end-window decision at the end of this log: the part past the last whole window is now measured by a window of its own, so only unconfirmed windows at either edge link to Granicus. Coverage is still the span from the first confirmed window to the last.

- Decision: a `rejected` row (audio fetched, match below the pass mark) is final until the method version rises; a `failed` row (audio could not be fetched from either side) is tried again once it is 7 days old; three `failed` results in a row stop the measuring pass for that run.
  Rationale: the scope brief's default re-measured failures only on a version bump. A failure is usually the network or YouTube refusing the Legion for a day (debt `D85` on pull request #139 names one way that can happen), and a version bump re-measures every recording, about a minute each for 329 of them. Retrying after a week is cheap; stopping after three consecutive failures keeps a blocked day from spending the run on downloads that cannot succeed.
  Date/Author: 2026-11-05, plan author, departing from the brief's default for the reason given.
  Superseded in part on 2026-11-05 by the failure-counting decision at the end of this log: the three that stop the pass are three failed fetches in a row, not three `failed` rows, and any unexpected error on one recording is a `failed` row. The 7-day retry stands.

- Decision: measuring rides on the ordinary transcriber run, before the speech engine is constructed, bounded by `--measure-limit` (environment `TRANSCRIBER_MEASURE_LIMIT`, default 20 recordings, 0 turns it off), newest meeting first; it does not run under `--meeting-id`, `--dry-run`, `--cache-audio`, `--capture-inputs`, or `--replay`; `--max-hours` and Ctrl-C bound the measuring pass and the transcription loop as one run; and no error inside the pass stops transcription.
  Rationale: the operator's answer of 2026-11-05 is that measuring rides on the existing run with no new command. `FasterWhisperEngine.__init__` loads the speech model onto the graphics card, so "without the GPU" means before that constructor. Unbounded, 329 recordings at about a minute each would hold the first run for hours; 20 a run is about 20 minutes, and `--limit 0 --measure-limit 400` drains the backlog on purpose. The single-meeting and no-database modes each promise one thing and exit.
  Date/Author: 2026-11-05, plan author, from the operator's answers.

- Decision: the Granicus side is read from the archive's `audio.flac` when the meeting has one and downloaded otherwise; both sides are converted to 8 kHz mono WAV in the work folder and deleted when the recording has been measured; the YouTube side asks yt-dlp for the smallest audio format; measuring never writes to the archive.
  Rationale: the goal says the audio is discarded. Reading the archived FLAC spares Granicus a request (decision `0065` keeps that file for exactly this reuse). The spike matched on yt-dlp's `worstaudio` downloads, and the envelopes use nothing above 3.6 kHz.
  Date/Author: 2026-11-05, plan author.

- Decision: a link that stands for an agenda item (the vote link on the item's page, the item link on the transcript page) uses the item's moment under the consent rule on both sites. A discrepancy row, which carries its own second (`transcript_start_s`), opens YouTube at that second and Granicus at the item's chapter. A vote on a different meeting from the item, or an item with no moment, uses the vote's own second.
  Rationale: the scope brief's default, kept: Granicus can only open a chapter, so an item link that used the vote's own second on YouTube and the item's chapter on Granicus would land in two different places for the same click. A discrepancy quotes specific words, and its second is the only honest moment for them where the site can seek.
  Date/Author: 2026-11-05, plan author, from the scope brief.

- Decision: the consent block of a meeting is the largest run of consent items' cue points in which neighbours are at most 120 seconds apart, and it exists only when that run has at least 3 cue points; a tie goes to the earlier run. A non-consent item always links to its own moment.
  Rationale: the block has to be found from the data, and the minimum and maximum of all consent cue points would swallow an item that was pulled off consent and discussed twenty minutes later (its `is_consent` flag comes from the printed agenda and stays true). On meeting 3184 the consent cue points span 95 seconds for about 59 items. A lone consent cue point, or two, is more likely a pulled item than the reading of the agenda, so fewer than 3 make no block and such a meeting's un-cued consent items keep a plain Granicus link. The production shape of other meetings is not known from this worktree; the read-only query that checks it is in Artifacts and Notes and the operator runs it before merge.
  Date/Author: 2026-11-05, plan author.

- Decision: one module, `src/docket/services/video_links.py`, owns link building (the URL rules, the consent rule, the coverage test, and the database reads). `src/docket/web/video_urls.py` is deleted and its `chapter_url` moves there. Services hand templates a finished link object; only the source-anchor partial calls a Jinja global, `video_link`.
  Rationale: "One owner per fact" in `docs/PRINCIPLES.md`, and the layer rule in `ARCHITECTURE.md` that `web/` executes no SQL and `services/` imports nothing from `web/`. The builder needs the Granicus chapter rule, so that rule cannot stay in `web/`. Handing templates finished links keeps `src/docket/web/admin_transcripts.py` unedited, so debt `D7` is not tripped.
  Date/Author: 2026-11-05, plan author.

- Decision: link wording. The vote link reads "Watch this vote on YouTube ↗" or "Watch this vote on Granicus ↗". The transcript, minutes-versus-video, and admin links read "video on YouTube ↗", "video chapter on Granicus ↗" when the Granicus link carries a chapter, and "video on Granicus ↗" when it opens the plain player. The source button reads "View Source: video on YouTube at <time> →" with YouTube's own time, or "View Source: video on Granicus at <time> →" when it lands on a chapter.
  Rationale: the goal says each link names the site it opens. "Chapter" is printed only when the link carries one, so the text never promises a jump the link does not make. Copy is the operator's to change.
  Date/Author: 2026-11-05, plan author.
  Superseded in part on 2026-11-05 by the source-button decision at the end of this log: on Granicus the source button prints no time. The other wordings stand.

- Decision: the converted second is the floor of (Granicus seconds minus offset); coverage is half-open, start included and end excluded; a converted second below zero falls back to Granicus.
  Rationale: a link may land half a second early and never late. The worked figures in Purpose (1620, 1354, 1509) are floors of 1620.52, 1354.52, and 1509.52.
  Date/Author: 2026-11-05, plan author.

- Decision: `_backfill_video_timestamps` keeps its existing precheck (it fetches the player page only when a numbered item lacks a timestamp) and writes the chapter id in the same statement as the timestamp; rows that already have a timestamp but not a chapter id are corrected by an operator script, not by widening the precheck.
  Rationale: widening the precheck to "has a non-chapter id" would make every ingest run re-fetch the player page of any meeting whose ids can never be rewritten, forever, and `test_idempotent_second_call_no_op` in `tests/integration/test_ingest_backfill_timestamps.py` pins that a second call makes no request. The existing rows are a known, small set (items ingested from agenda PDFs since 2026-05-17), so one supervised run with a dry run first is the house pattern for a production correction (decision `0026`).
  Date/Author: 2026-11-05, plan author.

- Decision: the production GRANT for the `transcriber` role is an operator step, not part of migration 042.
  Rationale: `ARCHITECTURE.md` says `scripts/sql/create_transcriber_role.sql` holds the role's grants. A conditional GRANT inside a migration would be a second owner of that fact, and the migration runs as the app role on every deploy whether or not the role exists. Until the GRANT is run the measuring pass logs one warning and the run transcribes as before.
  Date/Author: 2026-11-05, plan author, from the scope brief.

- Decision: this plan uses migration number 042, decision numbers from `0076`, and debt ids from `D94`.
  Rationale: the worktree is cut from `origin/main`, which lacks two open pull requests. Read on 2026-11-05 with `git ls-tree` and `git show`: branch `plan/search-finds-what-was-said` (pull request #140) holds `041_search_cards.py`, decisions `0071` to `0075`, and debt rows up to `D93`; branch `docs/youtube-rollout-followups` (pull request #139) holds `D84` and `D85`; migration 039 is left to `plans/active/meeting-types-name-the-body.md`. Debt `D70` records that these numbers have no uniqueness check.
  Date/Author: 2026-11-05, plan author.

- Decision: the work is cut into eight milestones in this order: the matcher, the table and grants, the measuring pass, the link builder, the two item links, the two discrepancy links and the source button, the chapter-id repair, the close. No milestone is a prototype.
  Rationale: feasibility was the open question, and it was measured while authoring on the spike's real audio (72 pairs, Artifacts and Notes) rather than left to a first milestone, because that audio sits in a temporary folder that may be gone when a milestone session starts. Each milestone leaves the repository coherent: the matcher is a pure module, the table exists before anything reads it, the link builder returns Granicus links until measurements exist, and the templates move in two sessions that each end with every page rendering.
  Date/Author: 2026-11-05, plan author.

The entries below were added on 2026-11-05, before any milestone ran, after the operator had an external reviewer read the plan. Each of the review's points was checked in the operator's session against the spike's audio and, read-only, against production; the figures are in "Observed at the review, 2026-11-05" under Context and Orientation and in Artifacts and Notes. The operator accepted the changes and said to revise the plan; Claude checked the points and drafted the entries.

- Decision: the matcher measures one more window, the end window, which ends where the overlap of the two recordings ends (at the end of the YouTube recording, or at the end of the Granicus clip when the recording runs past it), unless a whole 5-minute window of the grid already ends there.
  Rationale: the authored loop counted whole windows only, so the stretch after the last whole window, up to 5 minutes of every recording, could never be covered, and a quiet last window widened it: on clip 2024 coverage stopped 598 seconds before the recording ended, on clip 2026 143 seconds. With the end window those are 0, and eight of the nine matched pairs are covered to the end of the overlap; clip 2004's end window does not confirm, so its last 75 seconds stay on Granicus. All 9 matched pairs still pass and all 63 mismatched pairs are still rejected on score. Anchoring the window to the end of the overlap rather than to the end of the recording is this session's addition to the review's proposal: three of the nine recordings run past the end of their clip (clips 942, 1530, and 2004), and a window anchored to the recording's end falls outside the clip and is not counted.
  Date/Author: 2026-11-05, the operator, from the external review; checked and drafted by Claude.

- Decision: the agreement tolerance `AGREE_S` is 2.0 seconds, not 1.0. A window confirms the whole-recording offset when its best nearby match is within 2 seconds of it, and a strong window counts as a conflict only when it is more than 2 seconds away.
  Rationale: the two recordings of one meeting do not run at exactly the same speed. Measured on the nine matched pairs, the offset moved by up to 0.56 seconds over 4,949 seconds (113 parts per million, clip 1831), and production holds 9 attached recordings longer than four hours (the longest 16,901 seconds). At 113 parts per million a recording of that length drifts 1.9 seconds end to end, about 0.95 either side of the whole-recording offset, which is the authored limit; past it the edge windows would stop confirming and, being strong, would each count as a conflict and reject the whole recording. At 2.0 seconds nothing changes on the 72 pairs. The price is stated, not hidden: a link may land up to 2 seconds from the moment, and a recording with a step of up to 2 seconds in it (a brief stream dropout) passes with the later part that far off; a step of 3 seconds is still rejected (both observed on synthetic audio, Artifacts and Notes). Clerk cue points are coarser than that.
  Date/Author: 2026-11-05, the operator, from the external review; checked and drafted by Claude.

- Decision: the measuring pass counts failed fetches, not `failed` rows. A Granicus-side failure counts once for its meeting however many recordings it had, a YouTube-side failure counts once, any `passed` or `rejected` result sets the count back to zero, and three in a row end the pass. Any exception other than a database error raised while one recording is fetched, converted, read, or measured saves a `failed` row and the pass goes on; an exception that escapes the per-recording handling ends the pass with one warning and the run goes on to transcription. `features` refuses audio shorter than 10 seconds with a `ValueError`.
  Rationale: production holds 27 meetings with more than one attached recording, 2 of them with 3 or 4, so one broken Granicus clip could save three `failed` rows and end the pass by itself. The pass healed on the next run (a fresh `failed` row is not a candidate for 7 days), so this is a small fix, not a rescue. The authored text promised that no error inside the pass stops transcription but named three exception types; a download that yields a few bytes, or an error type nobody listed, would have ended the run before the engine loaded.
  Date/Author: 2026-11-05, the operator, from the external review; checked and drafted by Claude.

- Decision: a YouTube link is always built from the video id as `https://www.youtube.com/watch?v=<id>` with `&t=<n>s` when there is a second, never by appending to the stored URL. A URL on a YouTube host from which no video id can be read is treated as any other host.
  Rationale: the authored wording ("returns that video at `&t=<floor>s`") could be read as appending, which turns `https://youtu.be/<id>` into a broken URL and doubles a `t=` the stored URL already carries. Production holds no such URL today (every `meeting_videos.url` and every YouTube `meetings.video_url` begins `https://www.youtube.com/watch?v=`), so this is a statement of the rule, with one test.
  Date/Author: 2026-11-05, the operator, from the external review; checked and drafted by Claude.

- Decision: on Granicus the source button reads "View Source: video chapter on Granicus →" when the link carries a chapter and "View Source: video on Granicus →" when it opens the plain player, with no time printed. On YouTube it still prints YouTube's own time.
  Rationale: the Granicus player opens the chapter's start, not the anchor's second, so "at 1:05" promised a jump the link does not make, which the wording decision above says the text must never do. No page renders this branch today (production holds no agenda item with a video source anchor).
  Date/Author: 2026-11-05, the operator, from the external review; checked and drafted by Claude.

- Decision: the consent block's chapter id is the id of the first cue point in the run whose id is all digits, and the first cue point's id when none is. The cue points stay ordered by cue second and then row id.
  Rationale: if the run's first item is one whose id the M7 rewrite had to leave alone, every consent item of the meeting would lose its Granicus chapter although the next item in the run has a usable one seconds later. The review also proposed ordering ties by `item_number`; that column is text (migration 001), so "10" would sort before "2", and row id follows the order the agenda was inserted in.
  Date/Author: 2026-11-05, the operator, from the external review; checked and drafted by Claude.

- Decision: the vote link is not given a special rule for a consent item whose OCR vote falls after the consent block while the item's cue point is inside the block or missing. The fifth operator query in Artifacts and Notes counts such votes and is run before merge.
  Rationale: the review rated this case high: an item pulled off consent and voted on separately, whose cue point the clerk never moved, would send "Watch this vote" to the reading of the consent agenda. The operator chose on 2026-11-05 to skip the guard and add a check, on a first count in the session that found no such vote. That count used a looser block (the 90th percentile of the consent cue points) and a ten-minute threshold. The plan's own block rule, in the fifth query, then printed 8 of the 78 OCR votes on consent items. In all 8 the item is the last item of the block, which is how a vote read off the video is attached: to the item whose cue point precedes it. In 6 of them the vote is 147 to 331 seconds after the block's last cue point and before the next cue point, which is the consent agenda's own vote, and the start of the consent agenda is where the operator's rule sends it. In 2 (meeting 8 of 2026-03-31 and meeting 2367 of 2026-07-28) the vote is 1,034 and 4,090 seconds after the block; there the link lands on the consent reading and the vote shown on the page happened later. The operator has been told of the corrected count in the same session; the decision stands as made until the operator changes it, and a guard, if wanted, is a change to `get_vote_for_item` in M5 that uses the vote's own second on YouTube when it lies more than `CONSENT_GAP_S` after the block.
  Date/Author: 2026-11-05, the operator (the skip and the check); the corrected count by Claude in the same session.

- Decision: `ytdlp_options` sets `socket_timeout` to 30 seconds; `scripts/backfill_agenda_timestamps.py` gains a sentence pointing at the correction script; a Granicus clip trimmed in place after it was measured is named as an undetected state and recorded as debt with the removed YouTube video.
  Rationale: three small points of the review, each a line or a sentence. The timeout bounds a stalled in-process download, which no `subprocess.TimeoutExpired` can catch. The old script fills timestamps without chapter ids, after which the ingest precheck never fetches that meeting's player page again, so its reader is sent to the script that repairs it. Nothing has shown the clerk trims published clips, so the plan names the state and builds no detector.
  Date/Author: 2026-11-05, the operator, from the external review; checked and drafted by Claude.

- Decision: five points of the review are not taken. A shorter window for recordings under 5 minutes; coverage in pieces around a mid-stream glitch; a shared helper for the migration tests' rollbacks; fewer queries per page; and a different yt-dlp format.
  Rationale: none of the 359 attached recordings is shorter than 300 seconds (3 are under 600), and a second window size would be arithmetic the pass mark was not chosen on. None of the nine matched pairs has a conflict window; a rejected recording falls back to Granicus, the 2-second tolerance already absorbs a small step, and `ALIGN_METHOD_VERSION` lets a later method re-measure, so the operator counts `rejected` rows with reason `conflict` after the first full run (Validation and Acceptance) and coverage in pieces is built only if they appear. Pull request #140 does not touch `tests/integration/test_038_migration.py` or `test_040_migration.py`, and both already name migration numbers the way M2 adds one. The item page would run six small indexed queries where three would do, on a site with little traffic. The fall-through of `worstaudio/bestaudio/worst` to a small video file is deliberate: ffmpeg keeps only the audio.
  Date/Author: 2026-11-05, the operator, from the external review; checked and drafted by Claude.

The entries below were made by the M1 session on 2026-11-06.

- Decision: `transcriber/tests/test_align.py` imports `transcriber.align` inside each test function, not at the top of the file, and states the 8 kHz sample rate as its own constant.
  Rationale: `skills/plan-execute/SKILL.md` asks that a test of a symbol that does not exist yet import it inside the test, so the file collects and the before state reads as each test failing on its own. M1's acceptance names the error (`ModuleNotFoundError: No module named 'transcriber.align'`), not its shape; with the import at the top the same error would have been one collection error, and with it inside the functions it is `10 failed`. The alternative of one module-scoped fixture that imports the module was not taken because a fixture error reads as `10 errors` at setup, which is the collection-error shape again.
  Date/Author: 2026-11-06, M1 session (Claude).

- Decision: `describe()` prints `covers=none` when no window was confirmed, and `rejected (<reason>)` in place of `passed` for a rejected measurement; run as a module with anything but two arguments, `align` prints a usage line on stderr and exits 2.
  Rationale: the plan gives `describe()`'s text for a passing measurement only, and M3's log line reuses it with `rejected (<reason>)`, so the module produces that form itself and M3 logs `describe()`'s text unchanged. A rejected measurement can have no confirmed window, and then `granicus_start_s` and `granicus_end_s` are None; printing `covers=none` keeps the line's fields in one order, where leaving the field out would make the line harder to read by eye and by `grep`.
  Date/Author: 2026-11-06, M1 session (Claude).

- Decision: the synthetic signal is drawn as one `default_rng(seed)` giving first the envelope levels (five a second, squared uniforms, linearly interpolated) and then float32 white noise, multiplied, scaled by 6,000, clipped, and stored as 16-bit; `test_read_wav_refuses_anything_but_8khz_mono_16_bit` also checks a stereo file, an 8-bit file, and that a good file reads back sample for sample; `test_measure_files_matches_measure` also checks `describe()`'s opening. The count stays at ten functions.
  Rationale: the plan fixes the seeds and the shape of the signal but not the scale or the order of the draws, and says the scores need only land on the same side of the pass mark; 6,000 keeps the loudest samples inside 16 bits. The plan names the 16 kHz case for `read_wav`; the function's name promises mono and 16-bit as well, and each is one line in the same test. No test was added beyond the ten named, so the totals in every milestone's acceptance stand.
  Date/Author: 2026-11-06, M1 session (Claude).

- Decision: the rerun of the nine matched pairs on the spike's audio was not made in the M1 session and is left to the operator, or to a later session whose instructions allow reading that folder.
  Rationale: the workflow that started the session confines it to this worktree; the plan makes the rerun evidence and not acceptance, so the two instructions do not conflict over whether M1 is complete, and the narrower one was followed. What is lost is a direct check that the committed module prints the revised table's nine lines on real audio; what stands in for it is that the module follows the reference line for line, reproduces the plan's synthetic figures, and that operator step 5 under Validation and Acceptance compares the first real measurements with the same table (clip 2017's coverage, clip 1831's offset). To make the rerun, from the worktree root, for each row of the revised table: `cd transcriber && ../venv/bin/python -m transcriber.align <spike>/data/g_<clip>/audio.wav <spike>/data/y_<video>/audio.wav`, where `<spike>` is the folder named in "Observed at authoring"; each printed line should agree with its row to 0.1 second and in its verdict.
  Date/Author: 2026-11-06, M1 session (Claude).

The entries below were made by the M2 session on 2026-11-06.

- Decision: M2's acceptance clause `13 passed` is read as the plan's miscount and is met as `19 passed`; no test was removed or added to reach either number, and the acceptance paragraph carries a dated note rather than a rewritten figure.
  Rationale: the clause gives its own sum ("the 3 and 2 that existed, the new file's 3, and the role file's 5"), and the first two terms are wrong against the files as they stood before any edit (5 and 6, counted in this session). The other terms, and every total the later milestones build on (integration 695, transcriber 110), are as stated and were observed. Stopping to have the plan re-authored for an addition error would have cost a session and changed no code; passing over it silently would have left a completion claim that does not match what the command prints.
  Date/Author: 2026-11-06, M2 session (Claude).

- Decision: in the candidate order, "never-measured before stale failures" puts a row below the method version asked for, and a row measured against another clip id, with the recordings that have no row; only a `failed` row at the current version and clip, old enough to retry, sorts after them.
  Rationale: the plan names two classes and four ways to be a candidate. The Decision Log already says a row against another clip id is treated "as no measurement", and a row below the version floor is one the site ignores too, so both are recordings without a usable measurement and belong with the first class whatever their stored status. A failure being retried is the only candidate that has already cost a download and may fail again, which is why it goes last.
  Date/Author: 2026-11-06, M2 session (Claude).

- Decision: `save_alignment` takes the measurement by attribute and does not import `transcriber.align`; it writes all twelve columns and `measured_at` on every call, so a call with no measurement sets the offset, span, score, runner-up, and window counts to NULL; it keeps at most 4,000 characters of `reason`.
  Rationale: `db.py` is imported by every producer command and `align` imports numpy, which the claim and upload paths do not need. "Setting every column" is the plan's wording, and the alternative of keeping old figures under a new `failed` status would leave a row whose offset no measurement stands behind. The length bound is what `mark_status` in the same file does to `last_error`, for the same reason: a yt-dlp error can carry a page of text.
  Date/Author: 2026-11-06, M2 session (Claude).

- Decision: the two new GRANT statements are the last two statements of `scripts/sql/create_transcriber_role.sql`, and the file's comment and the runbook paragraph both say that a role created before migration 042 needs those two run alone by the owner.
  Rationale: the plan asks for them "after the existing grants" and has the operator run exactly those two on production, where the role has existed since 2026-10-10 and `CREATE ROLE` at the top of the file would fail. Listing the new tables in the runbook without that sentence would have read as a statement that production already has the grants, which is false until the operator's step 2.
  Date/Author: 2026-11-06, M2 session (Claude).

- Decision: the new tests assert a little more than the plan lists, inside the functions it names and without changing any count: the migration test also refuses a `passed` row with half a span or an empty one and accepts a `failed` row with neither; the role test also checks that `meeting_videos` cannot be deleted from; the producer tests also exclude an `event-` placeholder row, hold a 30-day-old `rejected` row and a row at a later method version out of the candidates, and save a third, `rejected`, measurement.
  Rationale: each is one line beside the case the plan names and pins a clause of the table's CHECK or of the candidate rule that the named cases alone left free (two of them found by the removal check in Surprises & Discoveries). The alternative of new test functions would have moved every total the later milestones state.
  Date/Author: 2026-11-06, M2 session (Claude).

The entries below were made by the M3 session on 2026-11-06.

- Decision: `transcriber/tests/test_measure.py` imports `transcriber.measure` inside each test function, and the before state of M3's acceptance is recorded as `13 failed, 28 passed`.
  Rationale: `skills/plan-execute/SKILL.md` asks for it, as in M1. M3's acceptance says the command "fails before `measure.py` exists" and names no shape; with the import at the top the file would not have collected and the eleven would have read as one error.
  Date/Author: 2026-11-06, M3 session (Claude).

- Decision: the pass groups its candidates by meeting in the order each meeting first appears, so a meeting's recordings are measured together even when they are not adjacent in the candidate order.
  Rationale: M2's order puts a failure being retried after every never-measured recording, so one meeting's two recordings can arrive apart. M3 says "walk them meeting by meeting" and that the Granicus audio is fetched once for a meeting; grouping only adjacent rows would ask Granicus twice for the same clip. The cost is that a retried recording is measured earlier than its place in the order, which harms nothing.
  Date/Author: 2026-11-06, M3 session (Claude).

- Decision: the 3-second pause is slept after every request to Granicus, whether or not it succeeded, and not at all when the archive's `audio.flac` was read. The two local reads (the FLAC, and the yt-dlp download) call `fetch_audio` with `attempts=1`; the Granicus download keeps `fetch_audio`'s three attempts.
  Rationale: M3 says "after a download from Granicus" and is silent on a failed one. The pause is owed for the request (`GOALS.md`, polite scraping), and a failing clip is exactly when the next request should not follow at once. `fetch_audio`'s retries, five seconds apart, exist for the network; a local file that ffmpeg cannot read will not read on the second try.
  Date/Author: 2026-11-06, M3 session (Claude).

- Decision: the stop flag and the deadline are checked before a meeting's Granicus audio is fetched and again before each of its recordings; the deadline has passed when the clock reads more than it, not when it equals it. A pass that stops this way logs `measure: stop requested; stopping` or `measure: max-hours reached; stopping` at INFO and still logs `measure done`.
  Rationale: M3 says "before each recording". The check before the meeting spares Granicus a request the pass would not use, and the check after it catches a Ctrl-C pressed during that download. The strict comparison is `run_loop`'s own, so one `--max-hours` means one thing in both.
  Date/Author: 2026-11-06, M3 session (Claude).

- Decision: log levels and texts the plan left open. A `passed` or `rejected` line is INFO and a `failed` line is WARNING. The error inside `failed (...)` and inside `measure: skipped (...)` is put on one line and cut at 300 characters in the log; the stored `reason` keeps the whole text (up to `save_alignment`'s 4,000). In `measure: skipped (...)` a database error prints its own message, which is how the plan's `permission denied ...` example reads, and any other exception prints its class name, a colon, and its message. Three failed fetches log `measure: 3 fetches failed in a row; stopping` at WARNING. `measure done` is logged whenever the pass reaches its end, early or not, and is not logged after `measure: skipped`. The rollback in the top handler is itself guarded, so a dead connection cannot raise out of the pass.
  Rationale: the plan fixes the texts of the per-recording lines and of the last line and says the pass "ends with a warning"; the rest had to be chosen. A yt-dlp error can carry a page of text, which belongs in the row and not on a log line the operator reads by eye. Leaving `measure done` out after a `skipped` keeps that line meaning that the backlog was read.
  Date/Author: 2026-11-06, M3 session (Claude).

- Decision: `cli.py` imports `measure_pass` at the top of the module, and `main()` builds the engine through a small inner function, `load_engine()`, called in three places: before `dry_run`, before the `--capture-inputs` connection, and, in the ordinary run, after the connection and the measuring pass. With `--meeting-id` the call is `run_loop(conn, engine, cfg)` exactly as before.
  Rationale: M3's test replaces `measure_pass` on `cli`, which needs the name there; the price is that every producer command, `--replay` included, now imports numpy, which the image carries and `requirements.txt` has declared since M1. The engine could not stay where it was built (above `--dry-run` and `--capture-inputs`, which need it) and also come after the measuring, so its construction became a function; the two single-purpose modes keep their old order of engine first, connection second.
  Date/Author: 2026-11-06, M3 session (Claude).

- Decision: the new tests assert more than the plan lists, inside the functions it names and without changing a count. The first also makes its second recording `rejected` (the saved status and reason, and the `rejected (windows)` log line), and checks the `measure done` line, the 8 kHz rate and file name of every conversion, the yt-dlp format, a commit per row, and that the candidate read's transaction is ended before any download. The two-recordings test also runs three candidates in which one meeting's two are not adjacent. The three-in-a-row test also runs fail, fail, measured, fail, fail and expects all five tried. The stop test also covers a flag set before the pass starts and a deadline exactly reached. The privilege test also covers a database error on a later save and a `RuntimeError` from the backlog read. The FLAC test also checks that no pause is slept and that the archive is unchanged. The `main()` test also checks `--measure-limit`, `TRANSCRIBER_MEASURE_LIMIT`, that the pass and the loop get one stop flag and one start time, and the deadline under `--max-hours`. The Granicus-failure test also checks that no YouTube audio is downloaded for the broken clip and that the pause is still slept. The second `test_audio.py` function also checks the default format and that `source_for` hands the format on.
  Rationale: each is a line or two beside the case the plan names and pins a clause of M3's prose that the named cases alone left free; the removal check in Surprises & Discoveries is what showed they are pinned. New functions would have moved the `41 passed` and `123 passed` the acceptance states.
  Date/Author: 2026-11-06, M3 session (Claude).

- Decision: in `transcriber/README.md` the log lines are given as forms with one passing line as an example, the minute-a-recording figure is called an estimate, and one line was added to "Where things land" for the `align-*.wav` files.
  Rationale: no real run of the pass has been observed by any session, so the README does not print a made-up log. The list under "Where things land" names every file the producer leaves in the work folder, and would have been incomplete without the new one.
  Date/Author: 2026-11-06, M3 session (Claude).

The entries below were made by the M4 session on 2026-11-06.

- Decision: the twenty new tests import `docket.services.video_links` inside each test function, and the before state of M4's acceptance is recorded as `20 failed, 8 passed`. In the commit that holds the failing tests, the moved file's first line still imports `chapter_url` from `docket.web.video_urls`; the commit that adds the module changes that line.
  Rationale: `skills/plan-execute/SKILL.md` asks for it, as in M1 and M3. M4's acceptance states the after state only (`28 passed`). With the new import at the top of the moved file before the module existed, the file would not have collected and the eight moved tests would have read as one error instead of eight passes.
  Date/Author: 2026-11-06, M4 session (Claude).

- Decision: `item_moment` returns `(None, None)` only for a consent item with no cue point in a meeting with no block. Every other item that falls to "its own" gets `(cue_s, external_id)` as they are, so a non-consent item with no cue point returns `(None, external_id)`. `item_links` returns a link for every agenda item of a meeting that has a `video_url`; an item with no moment gets the plain link, whose `timed` is false.
  Rationale: M4 says "the item's own cue point and id ... for any non-consent item" and "nothing" for the one case, and this is the literal reading. It keeps what the transcript page does today for an item that has a chapter id and no cue point (a Granicus chapter link), and it is what the consent decision above means by "such a meeting's un-cued consent items keep a plain Granicus link". The alternative, leaving un-timed items out of `item_links`, would have made M5's template drop a link the page prints today. The cost falls on M5: an item whose `external_id` is NULL prints no link today and will print "video on Granicus ↗" to the plain player, because the link no longer depends on the item having an id.
  Date/Author: 2026-11-06, M4 session (Claude).

- Decision: what `link_for` does with the inputs the plan left open. A second that is `None`, a boolean, not readable as a number, or not finite is absent. On a meeting whose own video is on YouTube, a negative second is absent too (the plain watch URL). When `video` is given, the base URL is `video.video_url` whether or not `url` is also given, and a `video` with no `video_url` gives no link. `timed` on Granicus is computed with the same test `chapter_url` makes (`str(meta_id).isdigit()`), through one private helper, `_is_chapter_id`, which `consent_block` also uses for "all digits". `VideoLink.seconds` is `None` on every link that is not YouTube. A link at YouTube second 0 is a timed link (`&t=0s`, `seconds` 0), so a template must test `seconds is not none`, not its truth.
  Rationale: each follows a sentence of Interfaces and Dependencies ("treated as absent", "or from `url` when `video` is None", "`timed` true exactly when the chapter id was applied"); the helper keeps the three places that ask "is this a chapter id" from drifting apart, while `chapter_url` itself moved byte for byte, as M4 requires. Comparing the returned URL with the base to decide `timed` was rejected: `chapter_url` also drops a fragment and can meet a URL that already carries the same `meta_id`.
  Date/Author: 2026-11-06, M4 session (Claude).

- Decision: `youtube_id` reads an id only from an `http` or `https` address whose host is `youtube.com`, `www.youtube.com`, `m.youtube.com`, or `music.youtube.com` with the path `/watch` and a `v` parameter, or whose host is `youtu.be` or `www.youtu.be` with the id as the path, and only when the id is made of letters, digits, `_`, and `-`. It does not require eleven characters. `/live/<id>`, `/embed/<id>`, and `/shorts/<id>` addresses are not read and fall under "any other host".
  Rationale: the plan names the two forms and nothing else, and production holds only the first. The character test keeps anything read from a stored URL from being pasted into a link the site builds; a length test would have refused the plan's own M6 example (`watch?v=abc`) and the ids M2's tests insert.
  Date/Author: 2026-11-06, M4 session (Claude).

- Decision: `for_meetings` returns an entry for every meeting that exists, also one with no `video_url`; it reads `id` and `video_url` in its first query and leaves the clip-id comparison to the join in the second (`a.granicus_clip_id = m.external_id`), so `external_id` is never brought into Python; it compares `mv.provider = 'youtube'`; and it runs its three queries on one connection. `consent_block` sorts the cue points it is given by second, keeping the given order among equal seconds, so the row-id tie-break is the loader's `ORDER BY video_timestamp_seconds, id` and the function is correct on unsorted input.
  Rationale: Interfaces says the first query reads "the meetings' `video_url` and `external_id`"; the comparison it is read for is done in SQL, where a NULL `external_id` compares as unknown and the row is left out without a default. The provider test is not in the plan's list: the links built from these rows are YouTube links, so a row of any later provider must not reach them, and the clause costs nothing today (Surprises says why no test can pin it).
  Date/Author: 2026-11-06, M4 session (Claude).

- Decision: the new tests assert more than the plan lists, inside the functions it names and without changing a count. Among them: a gap of exactly 120 seconds joins a run and 120.5 does not; unsorted cue points; a cue point with no second; both ends of the block and of a recording's coverage; a second handed over as text; the source button's call (`video` None, `url` given); a second covered by two recordings of which the first would go negative; a stored YouTube URL that already carries `t=`; a look-alike host; and, in the loader, a `failed` and an unmeasured recording beside the `rejected` one, a measurement at a later method version, a non-consent cue point 90 seconds after the run, two consent cue points that share a second, an item past the recording's coverage, the same items with the measurement deleted, and a meeting with no video. Three assertions were added after the commit that holds the failing tests: the negative second on a YouTube meeting, the shared second, and the block whose chapter id is not its first item's.
  Rationale: each is a line or two beside the case the plan names and pins a clause that the named cases alone left free; the removal check is what showed which. New functions would have moved the `28 passed`, `2243 passed`, and `700 passed` the acceptance states.
  Date/Author: 2026-11-06, M4 session (Claude).

The entries below were made by the M5 session on 2026-11-06.

- Decision: the before state of M5's acceptance is recorded as `8 failed, 47 passed`: the seven tests this milestone adds and the one it rewrites, committed failing before any file under `src/` was edited. The new tests import `VideoLink` inside the test function in `tests/web/test_vote_result_block.py`, and nothing in the three files needed an import that could fail collection.
  Rationale: M5's acceptance states the after state only (`55 passed`). Every symbol the new tests name existed after M4 except the attribute `VoteEntry.video_link`, which fails as an `AttributeError` inside each test, so the shape `skills/plan-execute/SKILL.md` asks for (each new test failing beside the old ones passing) came without a workaround.
  Date/Author: 2026-11-06, M5 session (Claude).

- Decision: when the item has no second of its own, the vote link opens at the vote's own second and keeps the chapter id `item_moment` returned. That is no chapter for a consent item with no cue point in a meeting with no block, as M5 says, and the item's own id for a non-consent item with no cue point.
  Rationale: M5 says "falling back to the vote's own `video_timestamp` with no chapter when the item has no moment". When that sentence was written `item_moment` returned nothing in exactly one case, the consent item with no cue point and no block, and there the two readings agree. M4 then built `item_moment` to return `(None, external_id)` for a non-consent item with no cue point (its Decision Log entry), a case the sentence does not name. Read onto that case literally, it would take the chapter away from an item that has a chapter id and no cue point, whose link today is `chapter_url(v.video_url, item.external_id)`: the Granicus link would get worse in a milestone meant to make it better. Keeping the id costs one thing, stated here: for such an item YouTube opens at the vote's own second and Granicus at the item's chapter, two places for one link, which is what the discrepancy rows already do by the decision of 2026-11-05. No row of this shape is known: a chapter id comes from a cue point, which carries its second.
  Date/Author: 2026-11-06, M5 session (Claude).

- Decision: a vote "has" a `video_timestamp` when the column is not NULL, so a vote read at second 0 gets a link; it "has" a `video_url` when the meeting's is not NULL or empty. When no vote of the item has both, `get_vote_for_item` reads nothing more (not the item's row, not the recordings).
  Rationale: the old template tested both by truth, so a vote stored at exactly 0.0 seconds printed the minutes link. M5 says "the entries that have both", and zero is a second like any other, which M4 already decided for `link_for` (`&t=0s` is a timed link). Only a vote read off the video carries a timestamp (Context and Orientation), so an item whose votes all come from the minutes has none to link; the early return keeps this milestone from adding four reads (the item's row and `for_meetings`' three) to that item's page.
  Date/Author: 2026-11-06, M5 session (Claude).

- Decision: the work on the entries is one private function of `src/docket/services/query.py`, `_attach_video_links(item_id, entries)`, which sets the attribute on the entries it is given; `query.py` imports `docket.services.video_links` at the top of the module; `VoteEntry.video_link` is the last field and the only one with a default.
  Rationale: `get_vote_for_item` stays the one SQL statement and the one list it was, and the rule has a name and a docstring of its own. `video_links` imports `docket.db` and the standard library only (Interfaces, "As built in M4"), so the import cannot become a cycle. The default keeps every existing construction of a `VoteEntry` valid, which M5 asks for by writing the field as `video_link: object | None = None`.
  Date/Author: 2026-11-06, M5 session (Claude).

- Decision: in `partials/transcript_body.html` both lines of the old link went, the `chapter_url` line and the condition above it (`items_by_id.get(item_id) and items_by_id[item_id].external_id`); the link is printed when `item_video_links.get(item_id)` is set and for no other reason. The partial's header comment gained a sentence saying where the link comes from.
  Rationale: M5 says "replace the `chapter_url` line with: when `item_video_links.get(item_id)` is set, a link", and M4 recorded what follows for this milestone: the link no longer depends on the item having an id. Keeping the old condition would have hidden the link of an item whose moment is known and whose id is missing, which on YouTube is a real jump.
  Date/Author: 2026-11-06, M5 session (Claude).

- Decision: the new tests assert more than the plan lists, inside the functions it names and without changing a count. In `tests/web/test_vote_result_block.py`: the rewritten test's link carries a chapter other than the fake item's `external_id`, so a template that still built its own URL fails it, and it also renders a link with no label ("Watch this vote ↗" and no "on"); the YouTube test also puts a Granicus link in the vote history, one site named per row. In `tests/unit/test_query_get_vote_for_item.py`: the Granicus test also covers an unmeasured and a rejected recording, an item with an agenda-PDF id (the plain player, not timed), an item with a chapter id and no cue point, and a vote on another meeting (that meeting's player, no chapter); the YouTube test also covers a vote whose own second differs from the item's moment, the consent rule (inside the run, no cue point, outside the run), an item whose moment is past coverage while the vote's second is inside it, an item with no cue point (the vote's own second), a vote on another meeting with its own recording, and a consent item with no moment; the no-timestamp test also covers a vote at second 0 and a vote with a timestamp on a meeting with no video. In `tests/integration/test_transcript_routes.py`: both tests compare the whole `<a>` tag and that it is printed once, on the full page and on the HTMX partial; the first also moves the item past coverage; the second also adds an item with no `external_id`.
  Rationale: each is a few lines beside the case the plan names and pins a clause of M5's prose or of the decisions above that the named cases alone left free; the removal check in Surprises & Discoveries is what shows they are pinned. New functions would have moved the `55 passed`, `2248 passed`, and `702 passed` the acceptance states.
  Date/Author: 2026-11-06, M5 session (Claude).

The entries below were made by the M6 session on 2026-11-06.

- Decision: the before state of M6's acceptance is recorded as `5 failed, 84 passed, 4 xfailed`: the five tests this milestone adds, committed failing before any file under `src/` was edited. No import in the three files could fail collection; the one test that needs `MeetingVideo` and `Recording` imports them inside the function.
  Rationale: M6's acceptance states the after state only (`89 passed, 4 xfailed`). `skills/plan-execute/SKILL.md` asks that the before state be readable from git, and every symbol the new tests name existed after M4, so each new test fails on an assertion about a link beside the old ones passing.
  Date/Author: 2026-11-06, M6 session (Claude).

- Decision: the private function is `_attach_video_links(rows)` in `src/docket/services/discrepancies.py`. It sets the key `video_link` on every row it is given, `None` included, and returns the same list; each of the four list functions calls it after its own `db_cursor` block has closed; the module imports `docket.services.video_links` at the top. Of what `item_moment` returns, only the chapter id is used: the second is always the row's own `transcript_start_s`.
  Rationale: M6 names the function's work and leaves its shape. Setting the key on every row lets a caller read `row["video_link"]` without asking whether the row had a second. `for_meetings` opens a connection of its own, so calling it inside the list function's `with` block would hold two at once for nothing. The decision of 2026-11-05 on discrepancy rows says the row "opens YouTube at that second and Granicus at the item's chapter", which is why the item's moment is asked for its chapter and not its second. `video_links` imports `docket.db` and the standard library only, so the import cannot become a cycle.
  Date/Author: 2026-11-06, M6 session (Claude).

- Decision: a row's chapter is taken from whatever agenda item the row names, under the consent block of the row's own meeting, with no check that the item belongs to that meeting.
  Rationale: `_SELECT` gains the two columns M6 names and no third, and the old templates did the same with `item_external_id`. The only writer of `minutes_discrepancies.agenda_item_id` is `src/docket/ai/transcripts/compare.py`, which takes it from the agenda item references of the events it compares for that meeting (read at its line 209; where those references come from was not traced further). No row naming another meeting's item is known, the table has no constraint against one, and a guard would need a column M6 does not add. If one ever appears, its Granicus link would carry a chapter id of another clip; what the player does with such an id was not observed.
  Date/Author: 2026-11-06, M6 session (Claude).

- Decision: what the source button does in the cases M6 left open. On YouTube the time is printed only when the link carries a second (`_vl.seconds is not none`); a link with none reads "View Source: video on YouTube →". When `video_link` returns nothing, or a link whose site is neither YouTube nor Granicus, the old markup is rendered from the anchor's own URL. The branch is still entered only for a truthy `timestamp_seconds`.
  Rationale: `link_for` drops a second it cannot use (a negative one on a YouTube video, text that is no number) and returns the plain watch URL; printing " at " and an empty time there would promise a jump the link does not make, which the wording decision of 2026-11-05 forbids, and M4 recorded that a template must test `seconds is not none`. `link_for` returns nothing only for a `video` with no `video_url`, which no page passes; falling back to the anchor's URL keeps the button there. The truthy guard is pinned by a strict expected failure in the same test file (Surprises & Discoveries), and M6 says "the existing markup is kept exactly" for other hosts, which that test renders.
  Date/Author: 2026-11-06, M6 session (Claude).

- Decision: the comment beside `"meta_id=" not in html` in `tests/integration/test_admin_discrepancies.py` now says that the link is built by `docket.services.video_links` and carries a chapter only for an all-digit item id; the assertion is unchanged. The helpers the two integration files share (`_measured_recording`, `_video_link_tags`) live in that file and are imported by `tests/integration/test_minutes_vs_video_public.py`, as `_disc` already is.
  Rationale: M6 says to correct the comment and that the assertion still holds. The comment's fact (a chapter needs a numeric id) was still true; what had gone stale was the implication that the template decides it. One helper file follows the import the public test already makes.
  Date/Author: 2026-11-06, M6 session (Claude).

- Decision: the new tests assert more than the plan lists, inside the functions it names and without changing a count. In `tests/integration/test_admin_discrepancies.py`: the whole `<a>` tag of each row; with nothing measured, "video on Granicus ↗" on the plain player for a row with an item, a row with no item, and a row past the recording's coverage, and no link for a row with no second; `video_link` is `None` on that row and absent from `get`'s; with the item's id made all digits, "video chapter on Granicus ↗" for the rows with an item and still the plain link for the row without; with the measurement, YouTube at each covered row's own second (3,300 and 1,100, not the item's 3,209) and the chapter for the row past coverage; and no link at all once the meeting has no `video_url`. In `tests/integration/test_minutes_vs_video_public.py`: the meeting page, the item page, and the index; a second meeting with no recording, whose row on the index stays on Granicus beside the measured meeting's YouTube link; the consent rule for the chapter (a lone consent item keeps its own id, and inside a run of three takes the run's first); and the application's two globals. In `tests/unit/test_source_anchor.py`: a stored YouTube URL that already carries `t=` and a fragment; a negative second (no time printed); an item id that is not a chapter id and no id at all, each with a fragment on the anchor's URL; and, with a `video`, a second the recording does not cover.
  Rationale: each is a few lines beside the case the plan names and pins a clause of M6's prose or of the decisions above that the named cases alone left free; the removal check in Surprises & Discoveries is what shows they are pinned. New functions would have moved the `89 passed`, `2251 passed`, and `704 passed` the acceptance states.
  Date/Author: 2026-11-06, M6 session (Claude).

The entries below were made by the M7 session on 2026-11-06.

- Decision: the before state of M7's acceptance is recorded as `5 failed, 7 passed`: the five tests this milestone adds, committed failing before `src/docket/services/ingest.py` was edited or the script existed. `correct_chapter_ids` and the script's `main` are imported inside the one test that calls them, after that test has inserted its rows. The third test ("a point whose id is not all digits") also makes a dry run and holds one point with a chapter id.
  Rationale: M7's acceptance states the after state only (`12 passed`). `skills/plan-execute/SKILL.md` asks that the before state be readable from git and that a symbol which does not exist yet be imported inside the test. The third test as the plan words it describes what the old code already did (it filled the timestamp and never touched an id), so alone it would have passed before and after; the dry run and the mixed point make it a test of this milestone. Importing after the inserts is M5's lesson: the statements ran against the real tables in the before state.
  Date/Author: 2026-11-06, M7 session (Claude).

- Decision: "all digits" in `ingest.py` is one constant, `_CHAPTER_ID_PATTERN = "^[0-9]+$"`, read by Python (`_is_chapter_id`, a full match) and handed to PostgreSQL as a parameter of the selection in `correct_chapter_ids`. `ingest.py` does not import the link builder's test.
  Rationale: the rewrite and the query that looks for rows still to rewrite must agree, or a row could be listed forever or never; one string in both places cannot drift, and it is the pattern the operator's second query uses. `video_links._is_chapter_id` is private (Interfaces, "As built in M4") and is `str.isdigit()`, which also accepts digits outside ASCII; every id this pattern accepts that test accepts too, so an id written here is always one the link builder will use. A point id of other digits would be left unwritten, which is the safe side; Granicus has not been seen to produce one.
  Date/Author: 2026-11-06, M7 session (Claude).

- Decision: a stored id that is NULL counts as "not all digits": the pass rewrites it under the same guards, and `correct_chapter_ids` selects on `a.external_id IS NULL OR a.external_id !~ '^[0-9]+$'`.
  Rationale: M7 says "when the stored id is not all digits" and "an id that is not all digits", and is silent on an item with no id; M5 and M6 both render such an item. It is the item that most lacks a chapter, and treating it alike in the rewrite and in the selection keeps the two from disagreeing. The cost is stated: the operator's second query uses `!~` alone, which leaves a NULL out, so its count can be lower than the script's list by such items. No insert path in `src/` writes a NULL id, and none is known on production.
  Date/Author: 2026-11-06, M7 session (Claude).

- Decision: the pass reads every row of the meeting, un-numbered ones too, in the transaction that writes, and takes no row lock. The ids "held" are those of all rows; the items matched are the numbered ones.
  Rationale: M7 says "read the meeting's numbered items" and also "no other row of the meeting holds ... that id". `UNIQUE(meeting_id, external_id)` covers every row, so an un-numbered row holding a chapter id would raise the unique violation M7's fourth test forbids; that test holds its taken id on an un-numbered row. One transaction makes the read and the write see the same rows. A lock was not taken: M7 asks for none, and two passes over one meeting at once (the worker's ingest and the operator's script) would compute the same values from the same page.
  Date/Author: 2026-11-06, M7 session (Claude).

- Decision: order and precedence inside the pass. The first index point on the page that names a number gives both the timestamp and the chapter id for that number, as the timestamp alone was taken before. Numbers are taken in the order their first point appears on the page, and within a number the rows in id order; so when two points carry one chapter id under two item numbers, "the first of those items" is the item whose point comes first on the page. A stored timestamp is never replaced, also when the point's differs. Every row of a duplicated number still gets its timestamp, as before; only the id is withheld.
  Rationale: M7 says "the first point's timestamp and its `external_id`" and "fill the timestamp when it is NULL"; the page's order is the source's own, and the old code already let the first point win. The fourth test puts the point for item 5 before the point for item 4 so that page order and row order differ. Leaving a moved cue point's stored second alone is the old behaviour, and M7 says to fill a timestamp only when it is NULL.
  Date/Author: 2026-11-06, M7 session (Claude).

- Decision: the statement is sent through `execute_values` with `page_size=len(changes)` and the template `(%s::integer, %s::real, %s::text)`; the function returns the statement's own row count on a write and the computed count under `dry_run`.
  Rationale: `execute_values` splits its rows into pages of 100 by default, which would be two statements for a meeting of 120 items; M7 says one. The casts state each column's type instead of leaving it to what PostgreSQL infers from the literals of a `VALUES` list; the session did not try the statement without them. `video_timestamp_seconds` is `REAL` (migration 008), and every test that keeps a stored timestamp reads it back unchanged.
  Date/Author: 2026-11-06, M7 session (Claude).

- Decision: log texts the plan left open. INFO, once per meeting when anything changes or would: `meeting <clip id>: <n> video timestamps filled, <m> chapter ids rewritten`, with ` (dry run, nothing written)` appended under `dry_run`; it replaces the old `backfilled video timestamps for n/m items on meeting <clip id>`. WARNING, once per row: `chapter id <id> not written to agenda item <row id> of meeting <clip id>: item number <N> is on <k> rows`, or `...: another row of the meeting holds it or was given it`. Both are logged under `dry_run` too. An id left alone because its point has no chapter id is not logged.
  Rationale: M7 names the two warnings and the two counts and no wording. The dry run is where the operator first reads the residue, so it logs what the write would. A point with no chapter id is the ordinary state of every test that existed before this milestone, not a conflict.
  Date/Author: 2026-11-06, M7 session (Claude).

- Decision: `correct_chapter_ids` raises `ValueError` for a slug that names no city; catches whatever one meeting raises, logs it at ERROR, and goes on to the next; and returns five keys per meeting, the four M7 names and `error` (`None`, or `<Class>: <message>`, with `changed` 0). Its order is `meeting_date DESC NULLS LAST, id DESC`. The `RawMeeting` is built from the row's stored columns as they are, with no default for a NULL. The lines that load the city and its adapter are written again in the function, not factored out of `ingest_municipality`.
  Rationale: M7 is silent on a city that does not exist and on a page that cannot be read. An empty list for a mistyped city would print `0 meetings, 0 rows`, which reads as "nothing left to correct". Letting one failed request end the pass would put every older meeting behind a clip whose page is gone, since the list is newest first; `ingest_municipality` catches per meeting for the same reason. The fifth key is an addition to the interface M7 states, made so the caller can tell "nothing to change" from "not looked at". `ingest_municipality` was left unedited because changing it is not this milestone's work.
  Date/Author: 2026-11-06, M7 session (Claude).

- Decision: `scripts/correct_agenda_chapter_ids.py` has `main(argv=None) -> int` and exits with its result: 0, or 1 when the city is unknown (the message on stderr, nothing on stdout) or any meeting failed. A failed meeting prints `meeting <id> clip <external id> <date>: failed (<error>)`. `--limit` below 1 is refused by the argument parser (exit 2). The dry run's line reads `<n> rows would change`. Logging is set to WARNING on stderr, so the ids left alone show and the per-meeting INFO line does not.
  Rationale: M7 gives the two line forms and the totals line; the rest follows `scripts/backfill_youtube_meetings.py`, the form Concrete Steps names. A function that returns its exit code is what lets the fifth test compare the script's printed lines. Operator step 3 says the residue is explained by "the script's WARNING lines", so they must reach the terminal.
  Date/Author: 2026-11-06, M7 session (Claude).

- Decision: two docstrings beyond the one M7 names were brought up to date: one clause of `_ingest_agenda_items` ("fills timestamps and chapter ids in place") and a paragraph of the test module's.
  Rationale: both described the pass as writing timestamps only and would have been false after this milestone. No other text in `src/` says so (Surprises & Discoveries).
  Date/Author: 2026-11-06, M7 session (Claude).

- Decision: the new tests assert more than the plan lists, inside the functions it names and without changing a count. The first runs a meeting of 120 items (one statement, its row count), a later point that names item 1 again, the INFO line, an untouched title, and the second call. The second also keeps a stored timestamp that differs from the point's and rewrites an item with no id. The third also makes the dry run (count, nothing written, the INFO line's suffix) and a mixed page, and checks that no warning is logged. The fourth holds the taken id on an un-numbered row, puts the shared chapter id's points out of row order, counts the four warnings and what each names, and runs the pass again with `force=True`. The fifth also covers the unforced call (no request), a stored chapter id that is kept, an item with no id, a meeting with only an un-numbered cued item or only an un-cued numbered one, an upcoming meeting, another city's meeting, the adapter's construction and the `RawMeeting` it is handed, the limit, a failing page, an unknown city, and the script's printed lines and exit codes in each of those states.
  Rationale: each pins a clause of M7's prose or of the decisions above that the named cases alone left free; the removal check in Surprises & Discoveries is what shows they are pinned. New functions would have moved the `12 passed` and `709 passed` the acceptance states.
  Date/Author: 2026-11-06, M7 session (Claude).

## Outcomes & Retrospective

This section is filled in as milestones complete. The closing retrospective is written by the retro stage after the last milestone, not by a milestone session.

M1, 2026-11-06. The matcher exists: `transcriber/transcriber/align.py`, the standard library and numpy only, written from the revised reference arithmetic, with the interface under Interfaces and Dependencies and nothing calling it yet. Its acceptance was met as stated: the ten tests of `transcriber/tests/test_align.py` failed with `ModuleNotFoundError: No module named 'transcriber.align'` before the module existed (committed in that state) and print `10 passed` after, in under 3 seconds; `./tools/verify` printed `verify: all 6 checks passed` with the transcriber suite at `105 passed` and the other tiers at their baseline. `transcriber/requirements.txt` declares numpy. One thing M1 asked for beyond its acceptance was not done: the rerun on the spike's real audio (Surprises & Discoveries, Decision Log). So the claim that the committed module reproduces the revised table on real recordings rests on its following the reference line for line and reproducing the plan's synthetic figures, not on an observation of this session. Lesson for the sessions after this one: because the plan states, case by case, what the revised rule and the authored rule each return, the session could take each revised rule out of a copy of the module and watch the test named for it fail, which is the check that stood in for the audio. M2 is next.

M2, 2026-11-06. The database has a place for measurements and the producer can reach it: migration `042_meeting_video_alignments` (one row per attached recording, two CHECK constraints, cascade from the recording), the role file's two grants (SELECT on `meeting_videos`; SELECT, INSERT, UPDATE and no DELETE on the new table), and `AlignmentCandidate`, `alignment_candidates`, `alignment_backlog`, and `save_alignment` in `transcriber/transcriber/db.py`. Nothing calls the three functions yet; M3's measuring pass will. Acceptance, clause by clause: the ten new tests failed before the code existed (committed in that state, `a5f4ab3`) and pass after; the build of the throwaway database prints `Applying migration 42: docket.migrations.042_meeting_video_alignments`; `transcriber/tests/test_db.py` prints `26 passed`; `./tools/verify` prints `verify: all 6 checks passed` with integration at `695 passed` and the transcriber suite at `110 passed`. One clause is met in a different number than written: the four-file command prints `19 passed` where the plan says `13 passed`, because the plan undercounted the tests the two older migration files already held (Surprises & Discoveries, Decision Log); the tests added are the 3, 2, and 5 the plan names. `ARCHITECTURE.md` and `docs/runbooks/transcripts.md` list the role's wider reach, and both the role file and the runbook say that the production role, created before this migration, has neither grant until the operator runs the two statements (step 2 under Validation and Acceptance). Lesson for the sessions after this one: count a file's tests by running it before the first edit, not by reading its top-level functions, and when a plan lists rules a query must keep, take each rule out of a copy in memory and watch for the test that fails; two of eight had none on the first try. M3 is next.

M3, 2026-11-06. An ordinary producer run now measures before it transcribes: `transcriber/transcriber/measure.py` holds `measure_pass`, `audio.py` takes a sample rate and a yt-dlp format and gives every download a 30-second socket timeout, and `cli.py` has `--measure-limit`, connects first, runs the pass, and only then loads the speech model, with one stop flag and one `--max-hours` allowance for the pass and the loop. The package is `0.5.0`. Acceptance, clause by clause, all as written: the three-file command printed `13 failed, 28 passed` before the code existed (committed in that state, `505214c`) and `41 passed` after; `./tools/verify` printed `verify: all 6 checks passed` with the transcriber suite at `123 passed` and the other tiers where M2 left them; `--help` lists `--measure-limit`. There is no carve-out against the acceptance. What the milestone did not and could not observe is the pass on the Legion: yt-dlp, a Granicus download, Docker, and the production role's grants are the operator's steps 1, 2, and 4 under Validation and Acceptance. What stands between the stubbed tests and that run is one scratch run with real ffmpeg, the real matcher, and the real database functions, which measured the M1 synthetic pair correctly through FLAC, AAC, and Opus and left the work folder empty (Artifacts and Notes). `transcriber/README.md` has the operator's section, `docs/runbooks/transcripts.md` points to it, and `docs/specs/transcripts.md` names `0.5.0`. Two things read from the code are left for M8's debt list: the model loads even when the run will transcribe nothing (the backlog command, or a Ctrl-C during measuring), and the pass writes no heartbeat. Lesson for the sessions after this one: when new tests pass on the first run of the code, that is not yet evidence they test it; taking each rule out of a copy in memory took a minute and is what the session can stand behind, and the one joint no stub covers (here, ffmpeg's output into the matcher's reader) is worth one real run from a scratch script. M4 is next.

M4, 2026-11-06. The link builder exists and nothing renders from it yet: `src/docket/services/video_links.py` holds the four dataclasses, `chapter_url` (moved byte for byte), `youtube_id`, `consent_block`, `item_moment`, `link_for`, and the three reads `for_meetings`, `for_meeting`, and `item_links`. `src/docket/web/video_urls.py` is gone, `src/docket/web/__init__.py` serves the `chapter_url` Jinja global from the new module, and the four templates are unedited, so every page renders as before. Acceptance, clause by clause, all as written: the two-file command printed `20 failed, 8 passed` before the module existed (committed in that state, `7655bbb`) and `28 passed` after; `git grep -n "video_urls" -- src tests` prints nothing; `./tools/verify` printed `verify: all 6 checks passed` with the unit, web, and services tier at `2243 passed` and integration at `700 passed`, the transcriber suite unchanged at 123. There is no carve-out against the acceptance. What this milestone cannot show is a link on a page: no template calls `link_for` or reads a `VideoLink` until M5 and M6, and no measurement exists outside a test until the operator's steps after merge. Two things are left for later sessions and written where they will be read: M5 inherits that `item_links` gives every item of a meeting with video a link (Decision Log; "As built in M4" under Interfaces and Dependencies), and M8 may want `ARCHITECTURE.md`'s Services entry to name the module (Surprises & Discoveries). Lesson for the sessions after this one: the removal check again earned its minute, this time by finding a rule whose test could not fail because the fixture's two candidate answers were the same value; when a test compares a rule's output with a fallback, make the two differ. M5 is next.

M5, 2026-11-06. The two links that stand for an agenda item are built by the link builder and say which site they open. `get_vote_for_item` in `src/docket/services/query.py` sets `VoteEntry.video_link` on every vote that has a video timestamp and a video URL: the item's moment under the consent rule for a vote on the item's own meeting, the vote's own second for a vote on another meeting or for an item with no second. `partials/_vote_result_block.html` prints that link as "Watch this vote on YouTube ↗" or "Watch this vote on Granicus ↗" and builds no URL; its macro's `meta_id` parameter is gone. `meeting_transcript` in `src/docket/web/public.py` hands `item_video_links` to `partials/transcript_body.html`, which prints each item's link with its phrase ("video on YouTube ↗", "video chapter on Granicus ↗", "video on Granicus ↗"). Acceptance, clause by clause, all as written: the three-file command printed `8 failed, 47 passed` before any source file was edited (committed in that state, `c388b8a`) and `55 passed` after, the files alone printing 21, 14, and 20; `./tools/verify` printed `verify: all 6 checks passed` with the unit, web, and services tier at `2248 passed` and integration at `702 passed`, the transcriber suite unchanged at 123. There is no carve-out against the acceptance. One sentence of M5 was read more narrowly than its words allow, and the reading is in the Decision Log: an item that has a chapter id and no cue point keeps its chapter when the link falls back to the vote's own second. Beyond the acceptance, the item page was requested through the real route on seeded rows and printed the three figures in Purpose (`t=1620s`, `t=1354s`, `t=1354s`). What this milestone cannot show is a link built from a real measurement on a real page: none exists until the operator's steps after merge, and until then every one of these links reads "on Granicus". Not built, by the operator's decision of 2026-11-05: the guard for a consent item whose vote was read long after the consent block. Left for the sessions after this one: M6 moves the last two templates off `chapter_url` (`git grep` still prints them) and can copy the seeding statements named under "As built in M5"; M8's spec is the first standing document to state either link's wording. Lesson for the sessions after this one: a test that inserts several rows of one kind should be run against the real tables once before it is committed as "failing for the right reason"; this session's draft tripped a unique index that the before state could not show, because the test failed earlier for the expected reason. M6 is next.

M6, 2026-11-06. Every timed video link the site renders is now built by the link builder, and no template calls `chapter_url`. `_attach_video_links` in `src/docket/services/discrepancies.py` sets `video_link` on each row that `list_queue`, `list_public_for_meeting`, `list_public_for_item`, and `list_public_recent` return: YouTube at the row's own second when a passing recording of its meeting covers it, and otherwise the Granicus player at the item's chapter under the consent rule. `partials/minutes_vs_video.html` and `admin/_discrepancy_row.html` print that link with its phrase and build no URL; `src/docket/web/admin_transcripts.py` is unedited. `src/docket/web/__init__.py` registers the Jinja global `video_link` (`video_links.link_for`) in place of `chapter_url`, and the video branch of `partials/source_anchor_button.html` calls it: "View Source: video on YouTube at <YouTube's time> →", "View Source: video chapter on Granicus →", or "View Source: video on Granicus →", with the old markup kept for any other host. Acceptance, clause by clause, all as written: the four-file command printed `5 failed, 84 passed, 4 xfailed` before any source file was edited (committed in that state, `6e49243`) and `89 passed, 4 xfailed` after, the files alone printing 15, 6, 57 with 4 xfailed, and 11; `git grep -n "chapter_url(" -- src/docket/web` prints nothing; `./tools/verify` printed `verify: all 6 checks passed` with the unit, web, and services tier at `2251 passed` and integration at `704 passed`, the transcriber suite unchanged at 123. There is no carve-out against the acceptance. What this milestone cannot show is the same as M5's: a link built from a real measurement on a real page, which waits on the operator's steps after merge; until then every one of these links reads "on Granicus". The source button is still included by no page, so its branch is proved by rendering the partial, as the plan's revision note says. Left for the sessions after this one: M7 is the chapter-id repair in `src/docket/services/ingest.py` and touches none of this milestone's files; M8's spec is the first standing document to state these wordings, and may want two things recorded as known limits (Surprises & Discoveries): the source button builds from `video.video_url` when a page hands it a `video`, and an anchor at second 0 is still not treated as timed. Lesson for the sessions after this one: when a plan's test needs a host, a flag, or a fixture value the test file's own setup does not have, the before-state run is where that shows; here the YouTube anchor rendered only once the test app's allowlist held the host, and without that the test would have failed before and after for a reason that had nothing to do with the code. M7 is next.

M7, 2026-11-06. An item whose timestamp is filled from the player page now gets that cue point's Granicus chapter id in the same write, and the operator has a script for the rows already stored. `_backfill_video_timestamps` in `src/docket/services/ingest.py` keeps its precheck and its fetch, then reads the meeting's rows and sends every change of the meeting in one `UPDATE ... FROM (VALUES ...)`: a NULL timestamp is filled, and an id that is not a chapter id is replaced by the point's when exactly one item carries that number and no other row holds or is being given the id; an id left alone for either reason is a WARNING. It takes `force` and `dry_run`. `correct_chapter_ids(slug, *, limit=50, dry_run=False)` runs it, forced, over a city's clip meetings that have a cued, numbered item without a chapter id, newest first, and `scripts/correct_agenda_chapter_ids.py` prints its result. `scripts/backfill_agenda_timestamps.py` carries the sentence that points to the new script. Acceptance, clause by clause, all as written: the test file printed `5 failed, 7 passed` before any source file was edited (committed in that state, `95411e8`) and `12 passed` after; the script's dry run on the fresh database printed `0 meetings, 0 rows`, and a second run with every outgoing request made to raise printed the same and recorded no attempt; `grep -c "correct_agenda_chapter_ids" scripts/backfill_agenda_timestamps.py` prints 1 (0 before the edit); `./tools/verify` printed `verify: all 6 checks passed` with integration at `709 passed`, the unit, web, and services tier unchanged at `2251 passed`, and the transcriber suite unchanged at 123. There is no carve-out against the acceptance. Two things go beyond what M7 states and are in the Decision Log: the function's dictionaries carry a fifth key, `error`, and an item with no id at all is treated as one whose id is not a chapter id. Beyond the acceptance, the script was run through the real adapter on a made-up player page twice: for a meeting of meeting 3184's shape, where it rewrote 61 of 64 ids and the link builder's links for those items then carried `&meta_id=`, and for the 66 real agenda rows of meeting 2543 that the repository holds as a fixture, where it rewrote all 65 numbered ids and changed no timestamp. What this milestone cannot show is the rewrite on a real player page or a production row: that is the operator's step 3, with its dry run first. One risk was read from the code and is the first M7 entry of Surprises & Discoveries: on a meeting first ingested from the player page whose items carry the adapter's fallback ids, the script would match items to points by a number that means position in one and agenda number in the other. A sixth read-only query counts such items, and step 3 now says to run it before the write. Left for M8: the spec's account of where a chapter id comes from, the operator's order for the script, and three candidates for the debt list from this session (that risk, the warning repeated on every ingest run for a meeting with an un-cued item, and the residue that is fetched again on every script run). Lesson for the sessions after this one: when a plan names a test whose words describe what the old code already does, the before-state run is where that shows, and the fix is to put the new rule into the same function, not to accept a test that passes before and after; and when a new function selects rows by a shape ("an id that is not all digits"), ask what else has that shape besides the rows it was written for. M8 is next.

## Context and Orientation

This section describes the repository as it stood on 2026-11-05 on branch `plan/video-links-land-on-the-moment`, cut from `origin/main` at commit `ca289dd`. Read `AGENTS.md` first, and `docs/PRINCIPLES.md` before touching a template or `src/docket/services/ingest.py`.

### The terms this plan uses

Granicus is the vendor whose site, https://bhamal.granicus.com, holds Birmingham's meeting videos. A clip is one Granicus recording; its number is the clip id, and a meeting row whose `meetings.external_id` is all digits is such a clip. The Granicus player page is `MediaPlayer.php?view_id=2&clip_id=<id>`, stored as `meetings.video_url`. A cue point (Granicus calls it an index point) is a marker the clerk places in a recording where an agenda item begins; the player page lists them as `<div class="index-point" time="<seconds>" data-id="<number>">`. The number in `data-id` is the chapter id: appending `&meta_id=<number>` to the player URL makes the player jump to that marker. The player ignores every other way of naming a time (`#t=`, `&t=`), so on Granicus a link can land only on a chapter. The Granicus clock is seconds from the start of the clip; `agenda_items.video_timestamp_seconds` (an item's cue point), `votes.video_timestamp` (when the vote board was read off the video), and `transcript_segments.start_s` and `minutes_discrepancies.transcript_start_s` for a clip meeting are all on it.

A YouTube recording is a video on the council's channel that the worker task `youtube_ingest` attached to a meeting; each is a row of `meeting_videos` (migration 040: `id`, `meeting_id`, `provider` always `youtube`, `video_id`, `url`, `title`, `clean_title`, `duration_s`, `started_at`, `is_primary`). A meeting can have several: numbered parts of one stream, or the same video uploaded twice (meeting 72 of 2025-01-28, clip 1831, videos `96jZkW4zv7U` and `E0cpl0Snx20`). A `yt-` row is a meeting that exists only on YouTube: its `external_id` is `yt-<video id>` and its own `video_url` is the YouTube watch URL, so its times are already on YouTube's clock and need no conversion.

The offset of a recording is Granicus seconds minus YouTube seconds for the same instant: a moment at Granicus second g is at YouTube second g minus the offset. Coverage is the stretch of the Granicus clock a recording has been confirmed to cover. A measurement is one row saying where one recording sits against one clip. The method version is an integer the matcher carries so that a changed method can re-measure old rows. The pass mark is the rule that decides `passed` or `rejected`.

A consent item is an agenda item with `agenda_items.is_consent` true (the column is `BOOLEAN NOT NULL DEFAULT FALSE`, migration 001). The consent block is this plan's name for the run of consent cue points described in Purpose.

The transcriber is the package under `transcriber/`, run on the operator's Legion desktop in Docker; `ARCHITECTURE.md` calls it the fourth process. It connects to the production database as the PostgreSQL role `transcriber`. Its work folder (`TRANSCRIBER_WORK_DIR`, `/archive/work` in the container) holds temporary audio; its archive (`TRANSCRIBER_ARCHIVE_DIR`, `/archive/transcripts/<meeting id>/`) keeps each transcribed meeting's `audio.flac` (decision `0065`). The engine is `FasterWhisperEngine` in `transcriber/transcriber/engine.py`, whose constructor loads the speech model onto the graphics card. numpy is the numerical array library; it is installed in the repository's `venv/` (1.26.4, from `requirements.lock`) and comes into the transcriber image with torch. scipy is in neither. The Python module `yt_dlp` (the YouTube downloader) is in the transcriber image and is not importable in the repository's `venv/`, so every test stubs the download.

### What renders a timed video link today

`src/docket/web/video_urls.py` defines `chapter_url(video_url, meta_id)`: it returns the player URL with `meta_id` set when the URL contains `MediaPlayer.php` and `meta_id` is all digits, and the URL unchanged otherwise. `src/docket/web/__init__.py` registers it as the Jinja global `chapter_url` (line 101). Four templates call it and a fifth builds its own URL.

`src/docket/web/templates/partials/_vote_result_block.html` has the macro `vote_source_link(v, meta_id)`. When a vote has `video_timestamp` and `video_url` it prints "Watch this vote ↗" linking to `chapter_url(v.video_url, meta_id)`, where `meta_id` is the page's item's `external_id`; otherwise it links the minutes or the meeting page. The votes come from `query.get_vote_for_item(item_id)` in `src/docket/services/query.py` (line 4019), which returns `ItemVoteData` holding `VoteEntry` dataclasses; `item_detail` in `src/docket/web/public.py` calls it. Only votes read off the video by OCR carry `video_timestamp`.

`src/docket/web/templates/partials/transcript_body.html` (line 40) prints "video chapter ↗" on the first turn of each agenda item when the item has an `external_id`, linking to `chapter_url(meeting.video_url, items_by_id[item_id].external_id)`. The route is `meeting_transcript` in `public.py`; `items_by_id` are `AgendaItem` models from `query.list_agenda_items`, and that model has no `video_timestamp_seconds` field.

`src/docket/web/templates/partials/minutes_vs_video.html` (line 24) and `src/docket/web/templates/admin/_discrepancy_row.html` (line 19) print "video chapter ↗" for a discrepancy row that has `transcript_start_s`, linking to `chapter_url(row.video_url, row.item_external_id)`. The rows are dictionaries from `src/docket/services/discrepancies.py`, all built on one `_SELECT` that joins the meeting and the item: `list_queue` (the admin queue, rendered by `review_discrepancies` in `src/docket/web/admin_transcripts.py`), and `list_public_for_meeting`, `list_public_for_item`, and `list_public_recent` (the public block on the meeting page, the item page, and `/minutes-vs-video/`).

`src/docket/web/templates/partials/source_anchor_button.html` has a video branch: for `item.source_anchor` of type `video` with `timestamp_seconds` it appends `?t=N` or `&t=N` to the anchor's URL and prints "View Source: video at <time> →". No shipped template includes this partial and nothing in `src/` or `scripts/` writes `agenda_items.source_anchor`, so the branch is reachable only from `tests/unit/test_source_anchor.py`, which renders the partial in a small Flask app that registers the filters and the `is_source_url_safe` global and nothing else.

The meeting page, `src/docket/web/templates/meeting_detail.html` (lines 426 to 438), already prints "Watch video" with the meta line "Granicus player" and, when the row has a YouTube recording and its own video is not on YouTube, "Watch on YouTube" with "council channel". `test_granicus_row_with_a_youtube_recording_shows_both_links` in `tests/web/test_meeting_recordings.py` pins both. This plan does not edit that template; the test stays as the standing check of the goal's sixth point.

### Why the Granicus link is bare today

`src/docket/adapters/granicus.py` `fetch_agenda_items` reads a clip's player page and returns one `RawAgendaItem` per index point with `external_id` set to the point's `data-id` (falling back to `<clip>-<position>`), `video_timestamp_seconds` its time, and `item_number` its position in the list. For an upcoming meeting (external id `event-<n>`) there is no player page, so `_fetch_agenda_items_from_pdf` parses the agenda PDF and returns items with `external_id` `event-<n>-<item number>` and no timestamp; that path was added on 2026-05-17 (commit `a1e24fa`). When the meeting is later recorded, `_try_upgrade_event_row` in `src/docket/services/ingest.py` changes the meeting's `external_id` to the clip id, and on the next ingest `_ingest_agenda_items` calls `_backfill_video_timestamps(adapter, meeting_id, raw_meeting)` (line 320). That function counts the meeting's numbered items with no timestamp, returns 0 without a request when there are none, otherwise fetches the index points, reads "ITEM N" out of each point's title with `_AGENDA_ITEM_NUMBER_RE`, and runs one `UPDATE agenda_items SET video_timestamp_seconds` per item number. It never touches `external_id`, so those items keep `event-2715-1` and `chapter_url` returns the bare player URL for them. The goal's figure from production on 2026-11-05: in 2026, 24 of 48 Granicus meetings with cue points (1,434 items) carry event-style item ids.

Read from the code, not observed on production: because consent items 7 to 9 of meeting 3184 have no cue point, that meeting has numbered items with no timestamp, so the existing precheck passes and its player page is fetched on every ingest run. Such meetings will have their ids rewritten by the first ingest after this plan deploys with no operator action; meetings whose numbered items all have timestamps are reached only by the M7 script.

Every reader of `agenda_items.external_id`, since M7 changes the values it holds: the three `chapter_url` templates above (the purpose of the change); `ai.external_id AS item_external_id` in `discrepancies._SELECT` (feeds those templates); six SELECT lists in `query.py` that fill `AgendaItem.external_id` (read only by the templates above); `load_agenda` in `src/docket/ai/transcripts/events.py` (selects it; `render_agenda` does not print it); `scripts/export_transcript_fixture.py` (copies it into a fixture file); `scripts/backfill_agenda_timestamps.py` (an old one-off that matches by `external_id = <data-id> OR item_number = <position>`; left alone, it never writes the column; revised 2026-11-05: its code is still left alone, but M7 adds a sentence to its module docstring pointing at the correction script, because a run of it fills timestamps without chapter ids and the ingest precheck then never fetches that meeting's player page again). The two writers are the first-scrape INSERT in `_ingest_agenda_items`, which runs only while `processing_status.agenda_items_scraped` is false, and `backfill_missing_minutes_approval` in `src/docket/services/maintenance.py`, which inserts `<meeting external id>-minutes-approval` with a NULL item number; both use `ON CONFLICT (meeting_id, external_id) DO NOTHING`, and neither re-inserts items for a meeting that has them, so a rewritten id cannot produce a duplicate. `agenda_items` has `UNIQUE(meeting_id, external_id)`, which is why M7 guards each rewrite.

### The transcriber as it stands

`transcriber/transcriber/cli.py` `main()` parses the arguments, builds a `Config`, handles `--replay` and `--cache-audio` without a model, then constructs `FasterWhisperEngine`, then handles `--dry-run` and `--capture-inputs`, then connects and calls `run_loop(conn, engine, cfg)`, which claims meetings one at a time and honours `--limit`, `--max-hours`, and a `_Stop` object set by Ctrl-C. `transcriber/transcriber/audio.py` has `fetch_audio(source, out_wav, ...)`, which runs ffmpeg to write 16 kHz mono WAV; `source_for(external_id, work_dir)`, which returns the Granicus download URL for a clip id and, for a `yt-<video id>`, downloads the video's audio with yt-dlp into `work_dir/yt-<video id>.<ext>` and returns that path; `ytdlp_options`, which sets the format `bestaudio/best` and the optional cookie file; and `remove_downloads(external_id, work_dir)`. `transcriber/transcriber/inputs.py` has `audio_path(archive_dir, meeting_id)`, the archived `audio.flac`. `transcriber/transcriber/db.py` holds every SQL statement the producer runs. `scripts/sql/create_transcriber_role.sql` creates the role: SELECT on `meetings`, `municipalities`, `council_members`, `agenda_items`; SELECT, INSERT, UPDATE, DELETE on `transcripts`, `transcript_segments`, `transcript_speakers`, `producer_heartbeats`. `tests/integration/test_transcriber_role.py` creates the role from that file on the throwaway database and checks the privileges. The package version is `__version__ = "0.4.0"` in `transcriber/transcriber/__init__.py`. The Docker image copies the package (`transcriber/Dockerfile`), so any change to it needs `docker compose build` on the Legion.

Decision `0070` says that only the transcriber downloads YouTube audio "and only for `yt-` rows"; this plan widens that to attached recordings, for measuring. Decision `0030` says the role writes four tables; this plan adds a fifth and a read. Both get a new record at the close, and each old record's Status line gains a note naming the new one, in the form `docs/decisions/0047-chunks-are-filtered-whole-then-split-without-smoothing.md` already carries ("accepted; `0064` adds ...; the no-smoothing clause stands"), the one precedent in `docs/decisions/` for a partial amendment.

### The prose that states the rules this plan changes

Found on 2026-11-05 by searching for the words each rule is stated with. The role's table list: `ARCHITECTURE.md` lines 78 and 79 (edited in M2), `docs/runbooks/transcripts.md` "The transcriber role" (edited in M2), the comment at the top of `scripts/sql/create_transcriber_role.sql` (edited in M2), `docs/decisions/0030-transcriber-role-is-write-limited.md` (a dated record; only its Status line changes, in M8), and `README.md` line 289, which lists migration 035's tables and is left alone. YouTube audio only for `yt-` rows: `docs/decisions/0070-...md` (Status line in M8), `docs/runbooks/transcripts.md` line 16 and `transcriber/README.md` "YouTube recordings" (each gains the measuring pass in M3), `docs/specs/operations.md` line 106 (M8). Chapter links by `meta_id`: the docstring of `src/docket/web/video_urls.py` (moves in M4), the header comment of `_vote_result_block.html` (rewritten in M5), and the comment on line 78 of `tests/integration/test_admin_discrepancies.py` (M6). "Only the `video_timestamp_seconds` column is touched": the docstring of `_backfill_video_timestamps` (rewritten in M7). The producer version sentence in `docs/specs/transcripts.md` line 21 (extended in M3). No file under `docs/specs/` or `docs/runbooks/` contains "video chapter", "Watch this vote", `chapter_url`, or `meta_id`.

### States that could make a link's words false

The link text asserts a site and, by its target, a moment. A recording that is unmeasured, `rejected`, `failed`, measured below the trusted method version, or measured against another clip is not used, and the link says Granicus. A moment outside coverage says Granicus. A meeting with no `video_url` (an upcoming or cancelled meeting) has no link. A `yt-` row links to its own video at the stored second. A hidden meeting's pages are 404 before any link renders. The minutes-versus-video block renders in three contexts (the meeting page, the item page, and the index of all meetings); each row carries its own meeting's recordings, so the index is correct across meetings. One state is not detected: a video removed from YouTube after it was measured still receives links, because nothing in the database records the removal; M8 records it as debt. Three more were named at the revision of 2026-11-05, and M8 records each as debt and as a known limit in the spec. A Granicus clip trimmed in place after it was measured keeps its clip id, so its stored offset would be stale and nothing detects it; nothing has shown the clerk does this. A recording cut within about its last 150 seconds passes, and a moment after the cut (at most about 150 seconds of the meeting) opens YouTube at the wrong second; the observation is in Artifacts and Notes. And a link on YouTube may land up to 2 seconds from its moment, the agreement tolerance.

### Work in flight and open pull requests

`plans/active/meeting-types-name-the-body.md` is paused before its M5 and M6 (a production reclassification and migration 039); it touches none of this plan's files except `src/docket/migrations/runner.py`'s list. Pull request #140 (`plan/search-finds-what-was-said`) also changes `src/docket/services/query.py`, `src/docket/web/public.py`, `src/docket/migrations/runner.py`, `docs/DEBT.md`, `docs/runbooks/transcripts.md`, and three specs, in different functions and sections; whichever merges second resolves the textual overlaps. Pull request #139 changes `docs/DEBT.md` and `docs/specs/meeting-types.md`.

Debt this plan accounts for. `D9` (no present-tense spec for ingest): M8 writes the timestamp and chapter-id backfill into the new spec and edits the row. `D7` (SQL in six web modules, `admin_transcripts.py` among them): not tripped, because no milestone edits that file. `D92` on pull request #140 (domain layers opening transactions): not tripped, since the matcher is under `transcriber/` and the link code under `services/`. `D57` (the worktree's database role on this machine): see the next subsection. `D85` on pull request #139 (no JavaScript runtime for yt-dlp in the image): this plan fetches far more YouTube audio than before, so its failure may surface; fixing the image is the operator's rebuild and is not part of this plan.

### Observed at authoring, 2026-11-05

The worktree has no `.env`. With `DATABASE_URL=postgresql://thinkdarrell@/docket_db` in the environment, `./tools/verify` printed `2228 passed, 5 skipped, 4 xfailed` for the unit, web, and services tier, `690 passed` for integration, `judge fixtures: 12 of 12 passed`, `95 passed` for the transcriber suite, and `verify: all 6 checks passed in 108s`. With no override, `tools/test-db` built its database as `postgresql://docket:docket_dev@localhost:5432/docket_test_7c0790d1` and `./tools/verify` printed `688 passed, 2 warnings, 3 errors` for integration and `verify: 1 of 6 checks failed in 154s`; the three errors are the three tests of `tests/integration/test_transcriber_role.py`, whose fixture creates a role and so needs a superuser. A milestone session therefore needs the gitignored file `.env` in this worktree containing the line `DATABASE_URL=postgresql://thinkdarrell@/docket_db` (debt `D57`); the author did not create it.

Per-file baselines with that URL: `tests/unit/test_video_urls.py` 8 passed; `tests/web/test_vote_result_block.py` 19; `tests/unit/test_source_anchor.py` 54 passed and 4 xfailed; `tests/unit/test_query_get_vote_for_item.py` 11; `tests/integration/test_ingest_backfill_timestamps.py` 7; `tests/integration/test_transcriber_role.py` 3; `tests/integration/test_admin_discrepancies.py` 14; `tests/integration/test_minutes_vs_video_public.py` 5; `tests/integration/test_transcript_routes.py` 18; `tests/web/test_meeting_recordings.py` 11; `transcriber/tests/test_audio.py` 11; `transcriber/tests/test_cli_loop.py` 17; `transcriber/tests/test_db.py` 21.

The developer database `docket_db` on this machine holds no agenda item with a cue point and has no `meeting_videos` table, so no figure about production rows could be re-measured here; every production figure in this plan is the goal's, from the operator's session of 2026-11-05, and is marked so.

The spike's files were readable on 2026-11-05 under `/tmp/claude-1000/-home-thinkdarrell-docket-pub--claude-worktrees-search-finds-what-was-said/4d7fa690-b939-4083-8703-11cdd8fe0d39/scratchpad/`: `spike/align.py`, `spike/fetch.sh`, `results.txt`, and `data/g_<clip>/audio.wav` and `data/y_<video>/audio.wav` (8 kHz mono, 8 clips and 9 videos, about 1.4 GB). They are reference only, are not in the repository, and may be gone; everything a session needs from them is written into this plan.

### Observed at the review, 2026-11-05

Read in the operator's session, read-only (`BEGIN READ ONLY`), from the production database, and from the spike's audio in the folder named above. These are the figures the revision of 2026-11-05 rests on; unlike the goal's figures they were read after the plan was authored.

The recordings the measuring pass will meet: 359 YouTube recordings are attached to 329 Birmingham meetings that are not hidden, have an all-digit `external_id`, and a `MediaPlayer.php` `video_url`. 302 of those meetings have one recording, 25 have two, one has three, and one has four. No recording is shorter than 300 seconds and 3 are shorter than 600; 9 are longer than four hours and none longer than five (the longest is 16,901 seconds). The authored text speaks of "about 329 recordings"; 329 is the meeting count.

The URLs the link builder will meet: every `meeting_videos.url` and every YouTube `meetings.video_url` begins `https://www.youtube.com/watch?v=`; none uses `youtu.be`. No `agenda_items.source_anchor` has type `video`.

The votes the vote link will meet: 78 active vote links join a vote that has its own `video_timestamp` to a consent item of the same meeting, all with `association_type = 'explicit'`, one item per vote. Under the plan's block rule 53 of them fall more than 120 seconds after the block's last cue point; in 45 of those the item's own cue point is outside the block, so the authored rule already sends the link to the item's own moment. The other 8 are described in the Decision Log (6 are the consent agenda's own vote, 2 are votes 1,034 and 4,090 seconds after the block).

The ids M7 will rewrite: 24 meetings have a cued item with an event-style id, and among those items no item number repeats within a meeting.

Drift between the two recordings of one meeting, from the per-window offsets of the nine matched pairs (first confirmed window to last): clip 1831 +0.56 seconds over 4,949 seconds (113 parts per million); clips 1530 and 2024 about 0.2 and 0.3 seconds the other way (51 and 53 parts per million); clip 942 none over 6,900 seconds. The largest distance of any confirmed window from its whole-recording offset was 0.64 seconds (clip 2004).

Two facts about the code the review's points turned on: `agenda_items.item_number` is `TEXT` (migration 001), and `git diff --stat origin/main...HEAD`, run in the worktree of branch `plan/search-finds-what-was-said` (pull request #140) for the three paths `tests/integration/test_038_migration.py`, `tests/integration/test_040_migration.py`, and `src/docket/migrations/runner.py`, lists only `runner.py`, by one line.

## Plan of Work

Build the measuring half first and the reading half second, so that each half is whole before the other depends on it.

M1 writes the matcher as a pure module, `transcriber/transcriber/align.py`, from the reference in Artifacts and Notes, with its tests. M2 adds migration `src/docket/migrations/042_meeting_video_alignments.py`, the role's two new grants, and three functions in `transcriber/transcriber/db.py`. M3 adds `transcriber/transcriber/measure.py` (the pass), two keyword arguments in `audio.py`, the wiring in `cli.py`, and the operator's notes. M4 writes `src/docket/services/video_links.py` and removes `src/docket/web/video_urls.py`. M5 moves the vote link and the transcript link onto it. M6 moves the two discrepancy links and the source button onto it and drops the old Jinja global. M7 changes `_backfill_video_timestamps` and adds the correction function and its script. M8 writes the spec, graduates the decisions, and records the debt.

## Milestones

### M1: the matcher

At the end of this milestone the repository can say, from two WAV files and nothing else, where one recording sits on the other's clock and whether to trust the answer. Nothing calls it yet.

Create `transcriber/transcriber/align.py` with the constants, the `Measurement` dataclass, and the functions named in Interfaces and Dependencies, following the reference implementation in Artifacts and Notes line for line in its arithmetic: the pass mark was chosen on that arithmetic, so a different window size, band edge, or normalisation changes the scores the mark was chosen from. The module imports only the standard library and numpy; add the line `numpy>=1.26  # the audio matcher (align.py); already present through torch` to `transcriber/requirements.txt` so the import is declared. Run as a module from the `transcriber/` folder, `cd transcriber && ../venv/bin/python -m transcriber.align <granicus.wav> <youtube.wav>`, it prints one line, `describe()`'s text, which the measuring pass will log.

Create `transcriber/tests/test_align.py` with ten plain test functions (no parametrisation, so the count below holds; seven were named at authoring and three were added by the revision of 2026-11-05). Synthetic audio is made in the test with a seeded `numpy.random.default_rng`: white noise multiplied by a loudness envelope that takes a new random level five times a second (squared uniform values, linearly interpolated between), scaled to 16-bit samples at 8 kHz; the "Granicus" side is 2,000 seconds of it. A signal's frame count falls just short of its length (2,000 seconds is 49,999 frames, 0.04 seconds short; a 900.0-second piece is 22,499 frames, one short of three windows of 7,500), so a piece that is a whole number of windows long loses its last grid window and gets it back as the end window. The pieces below are a few seconds longer than a whole number of windows so that each case states plainly which windows are grid windows and which is the end window.

The synthetic cases were run at the revision of 2026-11-05 with the revised reference arithmetic in Artifacts and Notes (the Granicus signal from seed 1, the added noise from seed 2, the unrelated signals from seeds 3, 99, and 4; 3.3 seconds for all of them and their authored-rule counterparts), and printed what follows. Where the revised rule and the authored rule (agreement within 1 second, no end window) give different answers, both are stated, so each case shows which rule it tests; the scores a session sees depend on how it draws the signal and need only land on the same side of the pass mark.

`test_shifted_noisy_copy_recovers_its_offset_and_passes`: the "YouTube" side is seconds 400 to 1,305 of the same signal at half the gain plus independent white noise of the copy's own standard deviation; the measurement passes, `offset_s` is within 0.1 of 400.0, 4 of 4 windows are confirmed (three grid windows and the end window, which starts about 605 seconds into the recording), and coverage is 400.0 to 1,305.0 within 0.1 (observed: score 40.8, runner-up 3.7). The authored rule gave 3 of 3 windows and coverage 400.0 to 1,300.0, so the assertion on 1,305.0 is the test of the end window.

`test_unrelated_audio_is_rejected_on_score`: 905 seconds from a different seed is `rejected` with reason `score` (observed: score 5.5).

`test_recording_that_starts_before_the_clip_counts_only_windows_inside_it`: the YouTube side is 200 seconds of unrelated signal followed by seconds 0 to 905 of the Granicus signal, so the offset is within 0.1 of -200; the first grid window maps before second 0 and is not counted, so `windows` is 3 (the grid windows at 300 and 600 seconds and the end window), all confirmed, and coverage is 100.0 to 905.0 within 0.1 (observed: score 44.7, passed; the authored rule gave 2 windows and coverage 100.0 to 700.0). No start window mirrors the end window: the first 100 seconds of the clip, which the recording does hold, stay uncovered, and the test asserts the 100.0.

`test_cut_recording_is_rejected`: the YouTube side is seconds 300 to 1,500 followed directly by seconds 1,690 to 2,000 (two true offsets, 300 and 490); four of its six windows confirm the offset of 300, and the fifth grid window and the end window both match strongly at 490, so the status is `rejected` with reason `conflict` (observed: score 49.5, runner-up 13.4, windows 4 of 6, two conflicts). The authored case was seconds 300 to 1,200 followed by 1,500 to 1,810; under the revised rule it printed 3 of 5 windows with two conflicts, and 3 of 5 is exactly the 60 percent share, so the first piece was lengthened to keep the case clear of that line.

`test_recording_that_runs_past_the_clip_is_covered_to_the_clips_end` (added): the YouTube side is seconds 1,250 to 2,000 followed by 200 seconds of unrelated signal, so the recording runs past the end of the clip; the measurement passes, the offset is within 0.1 of 1,250, `windows` is 3, all confirmed (the grid windows at 0 and 300 seconds; the grid window at 600 seconds maps past the clip's end and is not counted; the end window ends at the clip's last frame), and coverage is 1,250.0 to 2,000.0 within 0.1 (observed: score 39.4, runner-up 3.7). The authored rule gave 2 windows and coverage 1,250.0 to 1,850.0; a window anchored to the end of the recording instead of the end of the overlap would also give 1,850.0, so the assertion on 2,000.0 is the test of where the end window is anchored.

`test_offset_step_inside_the_agreement_tolerance_passes_and_a_larger_one_is_rejected` (added): the YouTube side is seconds 400 to 1,000 followed directly by seconds 1,001.5 to 1,605, a recording with 1.5 seconds missing; it passes with the offset within 0.1 of 400.0 and 5 of 5 windows confirmed (observed: score 26.9, coverage 400.0 to 1,603.4). The authored rule rejected it (reason `windows`, 2 of 4 confirmed, two conflicts), so this half is the test of the 2-second tolerance. With 3 seconds missing (seconds 400 to 1,000 followed by 1,003 to 1,605) it is `rejected` (observed: reason `windows`, 2 of 5 confirmed, three conflicts); assert the status and that the reason is `windows` or `conflict`.

`test_features_refuses_audio_shorter_than_ten_seconds` (added): `features` on 9 seconds of samples raises `ValueError`.

`test_verdict_reproduces_the_labelled_table`: `verdict()` returns `passed` for each of the nine rows of the revised matched table in Artifacts and Notes and, in this order of checks, `no_window` for zero windows, `score` for (7.3, 5.8, 17 windows, 3 confirmed, 0 conflicts) and for (5.4, 4.7, 7, 3, 0), `margin` for (12.0, 9.0, 10, 10, 0), `windows` for (12.0, 5.0, 10, 5, 0), and `conflict` for (30.0, 5.0, 10, 10, 1). `test_read_wav_refuses_anything_but_8khz_mono_16_bit`: a 16 kHz file raises `ValueError`. `test_measure_files_matches_measure`: two WAV files written to `tmp_path` give the same `Measurement` as the arrays. Keep the synthetic signals short enough that the file runs in under 20 seconds; record its wall time.

If the spike's audio is still readable at the path given in Context, run the module, as above, on the nine matched pairs (`data/g_<clip>/audio.wav` against `data/y_<video>/audio.wav`, reading only) and record the printed lines in Artifacts and Notes beside the revised table; they should agree to 0.1 second and in every verdict. This is evidence, not acceptance: if the folder is gone, record that it is gone.

Acceptance, run in this worktree. `venv/bin/python -m pytest transcriber/tests/test_align.py -q -p no:cacheprovider` fails before the module exists with `ModuleNotFoundError: No module named 'transcriber.align'` and afterwards prints `10 passed`. `./tools/verify` prints `verify: all 6 checks passed`, with the transcriber suite at `105 passed` (95 plus the 10 added) and the other tiers at their baseline. (As authored the counts were 7 and 102; the revision of 2026-11-05 added three functions.)

### M2: the table, the grants, and the producer's reads and writes

At the end of this milestone the database has a place for measurements, the role file lets the transcriber reach it, and the producer's database layer can ask what needs measuring and save an answer.

Add `src/docket/migrations/042_meeting_video_alignments.py` with the SQL in Artifacts and Notes, and its line at the end of `MIGRATIONS` in `src/docket/migrations/runner.py`. Its docstring says that 039 is left to `plans/active/meeting-types-name-the-body.md` and 041 to pull request #140. Because the new table references `meeting_videos`, migration 040's down (`DROP TABLE IF EXISTS meeting_videos`) now fails while 042 is applied. Three places roll 040 back, and each gains `runner.rollback_migration(conn, 42)` on the line before: the `fresh_040` fixture and the body of `test_040_down_removes_all` in `tests/integration/test_040_migration.py` (lines 25 and 92 at authoring), and the `fresh_038` fixture in `tests/integration/test_038_migration.py` (line 30). Each fixture's teardown already re-applies everything. Do not edit migration 040.

In `scripts/sql/create_transcriber_role.sql` add, after the existing grants, `GRANT SELECT ON meeting_videos TO transcriber;` and `GRANT SELECT, INSERT, UPDATE ON meeting_video_alignments TO transcriber;`, and correct the comment at the top to say the role also reads `meeting_videos` and writes `meeting_video_alignments`. No DELETE is granted: a re-measure overwrites the row. Edit the two sentences of the Transcriber component in `ARCHITECTURE.md` and the paragraph under "The transcriber role" in `docs/runbooks/transcripts.md` to list the same.

In `transcriber/transcriber/db.py` add `AlignmentCandidate`, `alignment_candidates`, `alignment_backlog`, and `save_alignment` as given in Interfaces and Dependencies.

Tests. `tests/integration/test_042_migration.py`, on the pattern of `test_040_migration.py`, with three functions: the up creates the table and its CHECK constraints refuse a status outside the three and a `passed` row with no offset; a second row for one recording raises a unique violation and deleting the meeting removes the measurement; the down drops the table and the up restores it. `tests/integration/test_transcriber_role.py` gains two functions: the role can SELECT `meeting_videos` and cannot INSERT or UPDATE it; the role can SELECT, INSERT, and UPDATE `meeting_video_alignments` and cannot DELETE from it. `transcriber/tests/test_db.py` gains five functions on rows it inserts and removes itself (a Birmingham meeting with a numeric `external_id` and a `MediaPlayer.php` `video_url`, with `meeting_videos` rows): candidates come newest meeting first, the primary recording first within a meeting, and respect the limit; a measured recording, a `rejected` one, a hidden meeting's, and a `yt-` row's own recording are not candidates; a row at a lower method version, a row whose `granicus_clip_id` differs from the meeting's `external_id`, and a `failed` row older than 7 days are candidates again while a fresh `failed` row is not; `save_alignment` called twice for one recording leaves one row holding the second call's values; `alignment_backlog` returns the count of candidates without a limit.

Acceptance. `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_038_migration.py tests/integration/test_040_migration.py tests/integration/test_042_migration.py tests/integration/test_transcriber_role.py -q -p no:cacheprovider` prints `13 passed` (the 3 and 2 that existed, the new file's 3, and the role file's 5), and `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest transcriber/tests/test_db.py -q -p no:cacheprovider` prints `26 passed`; then `tools/test-db --drop`. The build output of `tools/test-db` (on stderr) includes `Applying migration 42: docket.migrations.042_meeting_video_alignments`. `./tools/verify` prints `verify: all 6 checks passed` with integration at `695 passed` (690 plus 5) and the transcriber suite at `110 passed` (105 plus 5; as authored, 107, before M1 gained three functions). (Noted by the M2 session, 2026-11-06: the first command prints `19 passed`, not 13. The two older migration files held 5 and 6 tests, not 3 and 2, before M2 touched them; the sum is 5, 6, the new file's 3, and the role file's 5. Every other figure in this paragraph was observed as written.)

### M3: the measuring pass

At the end of this milestone an ordinary producer run measures before it transcribes. The code is complete and tested with stubbed downloads; the first real measurements are the operator's step after merge, listed under Validation and Acceptance, and are not part of this milestone.

In `transcriber/transcriber/audio.py`, `fetch_audio` gains the keyword `rate: int = 16000`, used for ffmpeg's `-ar`; `ytdlp_options` and `source_for` gain the keyword `audio_format: str = "bestaudio/best"`. Existing callers are unchanged. Added at the revision of 2026-11-05: `ytdlp_options` also returns `"socket_timeout": YTDLP_SOCKET_TIMEOUT_S`, a new module constant of 30, for every download (the transcription download included), so a stalled in-process download gives up instead of holding the run; `transcriber/tests/test_audio.py` asserts only the `format` key of those options today (line 119), so no existing test changes.

Create `transcriber/transcriber/measure.py` with `measure_pass` as given in Interfaces and Dependencies. In prose: do nothing when the limit is 0 or less; read the candidates and end the transaction; walk them meeting by meeting. For each meeting, put the Granicus audio at `<work_dir>/align-<meeting id>.wav` at 8 kHz, from `inputs.audio_path(cfg.archive_dir, meeting_id)` when that file exists and from `download_url_for(external_id)` otherwise, sleeping `MEASURE_PAUSE_S` (3 seconds) after a download from Granicus; compute its features once; then for each of the meeting's candidate recordings call `source_for("yt-" + video_id, cfg.work_dir, audio_format=MEASURE_YTDLP_FORMAT)`, convert the download to `<work_dir>/align-yt-<video id>.wav` at 8 kHz, measure, delete that WAV and call `remove_downloads("yt-" + video_id, cfg.work_dir)` in a `finally`, save the row, commit, and log one line. Delete the Granicus WAV in a `finally` when the meeting's recordings are done. Failures, as revised on 2026-11-05 (the authored text named `AudioFetchError`, `subprocess.TimeoutExpired`, and `ValueError` only, and counted `failed` rows). Any exception that is not a `psycopg2.Error`, raised while a recording's audio is fetched, converted, read, or measured, saves a `failed` row whose reason is the exception's class name, a colon, and its message (`AudioFetchError: yt-dlp could not download ...`), and the pass goes on; a failure on the Granicus side saves one such row for each of that meeting's candidates. The pass counts failed fetches, not rows: a Granicus-side failure adds one for its meeting however many recordings it had, a failure on one YouTube recording adds one, and any `passed` or `rejected` result sets the count back to zero; when it reaches `MEASURE_MAX_CONSECUTIVE_FAILURES` (3) the pass ends with a warning. Before each recording, stop if the stop flag is set or the deadline has passed. Any `psycopg2.Error` (the table is missing because the migration has not run, or the role lacks the grant) is caught at the top of the pass: roll back, log `measure: skipped (<error>)` at WARNING, and return. Any other exception that reaches the top of the pass is handled the same way (roll back, the same WARNING line, return the counts so far), so that nothing the pass meets keeps the run from transcribing; `KeyboardInterrupt` is not an `Exception` and still ends the run. The log lines are `measure meeting <id> clip <clip> video <video id>: passed offset=<x.xx>s covers=<a.a>-<b.b>s score=<s.s> runner_up=<r.r> windows=<c>/<n>`, the same with `rejected (<reason>)` in place of `passed`, or `failed (<error>)`; and at the end `measure done {'passed': p, 'rejected': r, 'failed': f} remaining=<backlog>`.

In `transcriber/transcriber/cli.py`: add `--measure-limit` (type int, default from `TRANSCRIBER_MEASURE_LIMIT`, else 20) and a `Config` field `measure_limit: int = 20` (a default keeps the existing test constructions valid). In `main()`, the ordinary run (none of `--replay`, `--cache-audio`, `--dry-run`, `--capture-inputs`) connects first; when `--meeting-id` is not given it records `started = time.monotonic()`, creates one `_Stop()`, and calls `measure_pass` with the deadline `started + max_hours * 3600` (none when `--max-hours` is absent); only then does it construct `FasterWhisperEngine`; then it calls `run_loop(conn, engine, cfg, stop_flag=stop, started=started)`. `run_loop` gains the keyword `started: float | None = None` and uses it in place of its own start time when given. With `--meeting-id` the pass is skipped and `run_loop` is called as it is today. The connection is closed in the existing `finally`. Bump `__version__` to `0.5.0`.

Add a section "Measuring YouTube recordings" to `transcriber/README.md` after "YouTube recordings": what the pass does, the three log lines, `--measure-limit` and `TRANSCRIBER_MEASURE_LIMIT`, the backlog command `docker compose run --rm transcriber --limit 0 --measure-limit 400 --max-hours 8`, that the image must be rebuilt, and that a `measure: skipped (permission denied ...)` line means the production GRANT has not been run. Add one sentence to the Producer bullet of `docs/runbooks/transcripts.md` "Shape" pointing there, and extend the version sentence of `docs/specs/transcripts.md` with "`0.5.0` adds the measuring pass before the loop, which does not change the output".

Tests. `transcriber/tests/test_measure.py`, eleven plain functions (nine named at authoring, listed first, and two added by the revision of 2026-11-05, listed after them), with a fake database object in the style of `FakeDB` in `test_cli_loop.py`, `measure.source_for` and `measure.fetch_audio` replaced by stubs that write a few bytes, and `measure.align` functions replaced by stubs returning a fixed `Measurement` (the matcher itself is M1's): each candidate is measured once, saved once, and the work folder is empty afterwards; two recordings of one meeting fetch the Granicus audio once and get a row each; a YouTube fetch that raises `AudioFetchError` saves `failed` with a reason that begins `AudioFetchError: ` and holds the message, leaves the folder empty, and the next recording is still measured; three YouTube fetch failures in a row, on three meetings, stop the pass before the fourth meeting; a limit of 0 reads nothing; a set stop flag, and a passed deadline, each stop the pass before the next recording; a `psycopg2.errors.InsufficientPrivilege` from the candidate read is swallowed after a rollback and the function returns zero counts; an existing `audio.flac` is the Granicus source and no Granicus URL is fetched; and `cli.main([])`, with `tdb.connect`, `measure_pass`, `transcriber.engine.FasterWhisperEngine`, and `run_loop` replaced by recorders (the `run_loop` one returning `{"uploaded": 0, "failed": 0, "low_speech": 0}`, which `exit_code` reads), `TRANSCRIBER_DATABASE_URL` set to a string containing `sslmode=require`, and `TRANSCRIBER_WORK_DIR` and `TRANSCRIBER_ARCHIVE_DIR` set to folders under `tmp_path` (the defaults are under `/archive`, which `main()` cannot create outside Docker), calls them in the order measure, engine, loop, while `cli.main(["--meeting-id", "5"])` does not call `measure_pass`. The two added functions: a Granicus fetch that raises `AudioFetchError` on a meeting with three candidate recordings saves three `failed` rows, and the next meeting's recording is still measured (under the authored count of rows those three would have ended the pass, so the second half is the test of counting fetches); and a YouTube fetch that raises `RuntimeError("boom")` saves `failed` with the reason `RuntimeError: boom`, leaves the folder empty, and the next recording is still measured (the authored handler named three exception types and would have let this one end the run). `transcriber/tests/test_audio.py` gains two functions: `fetch_audio(..., rate=8000)` puts `-ar 8000` in the ffmpeg command; `ytdlp_options(..., audio_format="worstaudio/bestaudio/worst")` returns that format and a `socket_timeout` of 30.

Acceptance. `venv/bin/python -m pytest transcriber/tests/test_measure.py transcriber/tests/test_audio.py transcriber/tests/test_cli_loop.py -q -p no:cacheprovider` fails before `measure.py` exists and afterwards prints `41 passed` (11 new, 13 in `test_audio.py`, 17 in `test_cli_loop.py` unchanged). `./tools/verify` prints `verify: all 6 checks passed` with the transcriber suite at `123 passed` (110 plus 13; as authored, 39 and 118, before the revision of 2026-11-05 added two functions here and three in M1). `cd transcriber && ../venv/bin/python -m transcriber.cli --help` lists `--measure-limit`.

### M4: the link builder

At the end of this milestone one module can turn "this meeting, this second, this chapter id" into the link a reader should get, and can find a meeting's consent block and passing recordings. The four templates still call `chapter_url`, now served from the new module, so every page renders exactly as before.

Create `src/docket/services/video_links.py` with the dataclasses and functions in Interfaces and Dependencies. `chapter_url` moves there unchanged. Delete `src/docket/web/video_urls.py`; in `src/docket/web/__init__.py` import `video_links` from `docket.services` and point the `chapter_url` global at `video_links.chapter_url`. Move the test file with `git mv tests/unit/test_video_urls.py tests/unit/test_video_links.py` and change its import; its 8 tests stay.

Add fifteen plain functions to `tests/unit/test_video_links.py`, none touching the database (thirteen named at authoring; the two added by the revision of 2026-11-05 are the last two in this list): the consent block on meeting 3184's shape (59 consent cue points with all-digit ids spread evenly from 1,990 to 2,085 seconds gives a block from 1,990 to 2,085 whose chapter id is the first item's); a consent cue point at 3,000 seconds beside that run is outside the block; two consent cue points make no block; of two runs the larger is the block and of two equal runs the earlier; `item_moment` returns the block's start and chapter for a consent item inside the block and for a consent item with no cue point, the item's own cue point and id for a consent item outside it and for any non-consent item, and nothing for a consent item with no cue point in a meeting with no block; `link_for` with one recording (`FR84h22hQvA`, offset 635.48, covering 635.5 to 3,935.5) returns `https://www.youtube.com/watch?v=FR84h22hQvA&t=1620s` for 2,256 seconds, `t=1354s` for 1,990, and `t=1509s` for 2,145; a moment outside coverage returns the Granicus player URL with `meta_id`; no recordings returns Granicus, and a chapter id that is not all digits returns the plain player URL with `timed` false; of two recordings the one whose coverage holds the moment is chosen, and of two that both hold it the first; a meeting whose own `video_url` is a YouTube watch URL returns that video at `&t=<floor of the second>s` with no conversion, and the plain watch URL when no second is given; an unknown host returns the URL unchanged with site `other`, and no URL returns nothing; a covered moment whose converted second would be negative returns Granicus; and `phrase` reads "video on YouTube", "video chapter on Granicus", "video on Granicus", and "video" for the four cases. The two added: a run of consent cue points whose first carries the id `event-2715-1` and whose second carries `371121` gives a block whose chapter id is `371121` (the authored rule returned the first item's `event-2715-1`, which `chapter_url` cannot use), and a run in which no id is all digits keeps the first id; and a meeting whose `video_url` is `https://youtu.be/FR84h22hQvA?t=10` returns `https://www.youtube.com/watch?v=FR84h22hQvA&t=65s` for 65 seconds (appending to the stored string would give `https://youtu.be/FR84h22hQvA?t=10&t=65s`) and `https://www.youtube.com/watch?v=FR84h22hQvA` with no second, while `https://www.youtube.com/@citycouncilbham`, a YouTube address with no video id, is returned unchanged with site `other`.

Create `tests/integration/test_video_link_loader.py` with five functions on rows it inserts under a Birmingham meeting and removes: `for_meetings` returns only `passed` recordings, primary first; a row with `method_version` 0 is ignored; a row whose `granicus_clip_id` differs from the meeting's `external_id` is ignored; the consent block is computed from the meeting's consent cue points; `item_links(meeting_id)` on a seeded copy of meeting 3184's shape (consent items in a run from 1,990 seconds, one consent item with no cue point, non-consent items at 2,145 and 2,256, one passing recording with offset 635.48) returns `t=1354s` for a consent item in the run and for the un-cued one, `t=1509s`, and `t=1620s`.

Acceptance. `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_video_links.py tests/integration/test_video_link_loader.py -q -p no:cacheprovider` prints `28 passed` (8 moved, 15 and 5 new; as authored, 26 with 13), then `tools/test-db --drop`. `git grep -n "video_urls" -- src tests` prints nothing (at authoring it printed three lines: the import and the global in `src/docket/web/__init__.py` and the import in the test file; `git grep` is used so a stale `.pyc` cannot answer). `./tools/verify` prints `verify: all 6 checks passed` with the unit, web, and services tier at `2243 passed` (2228 plus 15; as authored, 2241) and integration at `700 passed` (695 plus 5).

### M5: the vote link and the transcript link

At the end of this milestone the two links that stand for an agenda item are built by the link builder, land on the item's moment under the consent rule, and say which site they open.

In `src/docket/services/query.py`, `VoteEntry` gains the field `video_link: object | None = None` (a `video_links.VideoLink`). `get_vote_for_item`, after building its entries, reads the item's `meeting_id`, `is_consent`, `video_timestamp_seconds`, and `external_id`, loads `video_links.for_meetings` for the meetings of the entries that have both `video_timestamp` and `video_url`, and sets each such entry's `video_link`: for a vote on the item's own meeting, the item's moment from `video_links.item_moment`, falling back to the vote's own `video_timestamp` with no chapter when the item has no moment; for a vote on another meeting, the vote's own `video_timestamp` with no chapter. Entries without both fields keep `None`. In `partials/_vote_result_block.html` the macro's first branch becomes `{%- if v.video_link -%}` with `href="{{ v.video_link.url }}"` and the text `Watch this vote{% if v.video_link.label %} on {{ v.video_link.label }}{% endif %} ↗`; the macro's `meta_id` parameter and both call sites' `meta_id=item.external_id` go, and the header comment is rewritten to say the link comes from `docket.services.video_links`.

In `src/docket/web/public.py` `meeting_transcript`, add `item_video_links=video_links.item_links(meeting_id)` to the context. In `partials/transcript_body.html` replace the `chapter_url` line with: when `item_video_links.get(item_id)` is set, a link to its `url` with the text `{{ link.phrase }} ↗`.

Not built, by the operator's decision of 2026-11-05 (Decision Log): a special rule for a consent item whose vote was read off the video after the consent block while the item's cue point is inside the block or missing. Such a vote link lands on the start of the consent agenda. The fifth operator query in Artifacts and Notes counts those votes; it printed 8 of 78 on 2026-11-05.

Tests. In `tests/web/test_vote_result_block.py`, `_FakeVote` gains `video_link`; `test_source_link_prefers_video_timestamp` is rewritten to pass a Granicus `VideoLink` and assert "Watch this vote on Granicus", the `meta_id` URL, and no "Read minutes"; two functions are added: a YouTube `VideoLink` renders "Watch this vote on YouTube" with the `&amp;t=1620s` URL, and a vote with a timestamp but no `video_link` falls through to the minutes link. `tests/unit/test_query_get_vote_for_item.py` gains three: an OCR vote on the item's meeting with a numeric item id and no measurement gets a Granicus link carrying `meta_id`; the same with a passing measurement covering the item's cue point gets the YouTube URL at the converted second; a vote with no `video_timestamp` has `video_link` None. `tests/integration/test_transcript_routes.py` gains two: with the fixture's item given a cue point and the meeting a passing measurement that covers it, the transcript page contains "video on YouTube" and the converted `t=`; with no measurement it contains "video chapter on Granicus" and `meta_id=77001`.

Acceptance. `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/web/test_vote_result_block.py tests/unit/test_query_get_vote_for_item.py tests/integration/test_transcript_routes.py -q -p no:cacheprovider` prints `55 passed` (21, 14, and 20), then `tools/test-db --drop`. `./tools/verify` prints `verify: all 6 checks passed` with the unit, web, and services tier at `2248 passed` (2243 plus 5; as authored, 2246) and integration at `702 passed` (700 plus 2).

### M6: the discrepancy links and the source button

At the end of this milestone no template calls `chapter_url`, and the remaining three surfaces name their site.

In `src/docket/services/discrepancies.py`, `_SELECT` gains `ai.is_consent AS item_is_consent, ai.video_timestamp_seconds AS item_cue_s`, and a private function attaches `row["video_link"]` to each row: None when `transcript_start_s` is None; otherwise `video_links.link_for(video, seconds=row["transcript_start_s"], chapter_id=<the item's chapter under item_moment, or None when the row has no item>)`, with the recordings loaded once for the distinct meetings of the page through `video_links.for_meetings`. `list_queue`, `list_public_for_meeting`, `list_public_for_item`, and `list_public_recent` return rows passed through it; `get` is unchanged. `src/docket/web/admin_transcripts.py` is not edited. In `partials/minutes_vs_video.html` and `admin/_discrepancy_row.html` the `chapter_url` expression becomes: when the row has a `video_link`, ` · <a ... href="{{ row.video_link.url }}" ...>{{ row.video_link.phrase }} ↗</a>` (the public template's variable is `d`).

In `src/docket/web/__init__.py` remove the `chapter_url` global and register `video_link` as `video_links.link_for`. In `partials/source_anchor_button.html` the video branch first sets `_vl = video_link(video|default(none), seconds=anchor.timestamp_seconds, chapter_id=item.external_id|default(none), url=_url_clean)`; when `_vl.site` is `youtube` it prints a link to `_vl.url` reading `View Source: video on YouTube at {{ _vl.seconds | format_timestamp }} →`; when it is `granicus`, a link to `_vl.url` reading `View Source: {{ _vl.phrase }} →`, which prints "View Source: video chapter on Granicus →" when the link carries a chapter and "View Source: video on Granicus →" when it opens the plain player, with no time in either (revised 2026-11-05: as authored this branch printed ` at <time>` after "video on Granicus" when `_vl.timed`, but the Granicus player opens the chapter's start, not the anchor's second); for any other host the existing markup is kept exactly, so the existing tests on `video.example.com`, `granicus.example.com/player`, and `example.com` keep passing. `video` is an optional template variable holding a `MeetingVideo`; no page passes it today. Update the partial's header comment (branch 5) to say so. In `tests/unit/test_source_anchor.py` the `app` fixture registers the `video_link` global the same way.

Tests. `tests/integration/test_admin_discrepancies.py`: correct the comment on line 78 (the assertion `"meta_id=" not in html` still holds, since the pilot item's id is `1950-15`), and add one function: with a `meeting_videos` row and a passing measurement for the pilot meeting (offset 100, covering 0 to 5,000, `granicus_clip_id` the installed meeting's `external_id`), the queue shows "video on YouTube" and `t=3300s` for the row at 56:40. `tests/integration/test_minutes_vs_video_public.py` gains one: with the flag on and the same seeding, the meeting page's block shows "video on YouTube", and without the measurement "video on Granicus". `tests/unit/test_source_anchor.py` gains three: a `https://www.youtube.com/watch?v=abc` anchor at 65 seconds renders `watch?v=abc&amp;t=65s` and "video on YouTube at 1:05"; a `MediaPlayer.php` anchor at 65 seconds on an item whose `external_id` is `371120` renders `meta_id=371120`, no `t=`, "View Source: video chapter on Granicus", and no "1:05" (as authored the assertion was "video on Granicus at 1:05"); the same anchor rendered with a `video` variable whose recording covers the second renders the YouTube URL at the converted second.

Acceptance. `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_admin_discrepancies.py tests/integration/test_minutes_vs_video_public.py tests/unit/test_source_anchor.py tests/web/test_meeting_recordings.py -q -p no:cacheprovider` prints `89 passed, 4 xfailed` (15, 6, 57, and the unchanged 11), then `tools/test-db --drop`. `git grep -n "chapter_url(" -- src/docket/web` prints nothing (at authoring it printed five lines: the four templates and the definition in `video_urls.py`). `./tools/verify` prints `verify: all 6 checks passed` with the unit, web, and services tier at `2251 passed` (2248 plus 3; as authored, 2249) and integration at `704 passed` (702 plus 2).

### M7: the Granicus chapter id

At the end of this milestone an item whose timestamp is filled from the player page gets that cue point's chapter id in the same write, and the operator has a script for the rows already stored.

In `src/docket/services/ingest.py`, rewrite the body of `_backfill_video_timestamps` after its unchanged precheck and fetch. From the fetched index points build, per "ITEM N" number, the first point's timestamp and its `external_id` when that is all digits. Read the meeting's numbered items (`id`, `item_number`, `external_id`, `video_timestamp_seconds`). For each item whose number has a point: fill the timestamp when it is NULL; rewrite `external_id` to the point's chapter id when the stored id is not all digits, the point has a chapter id, exactly one item in the meeting has that item number, and no other row of the meeting holds or is being given that id. Apply every change of the meeting in one `UPDATE agenda_items AS a SET video_timestamp_seconds = v.ts, external_id = v.ext FROM (VALUES %s) AS v(id, ts, ext) WHERE a.id = v.id` through `psycopg2.extras.execute_values`, each tuple carrying the row's final values. Log at INFO how many timestamps were filled and ids rewritten, and at WARNING each id left alone for a duplicated number or a taken id. The function gains keywords `force: bool = False` (skip the precheck) and `dry_run: bool = False` (compute and return, write nothing), and still returns the number of rows changed. Rewrite its docstring: it no longer touches only one column.

Add the public function `correct_chapter_ids(slug, *, limit=50, dry_run=False) -> list[dict]` to the same file: load the city and its adapter as `ingest_municipality` does; select the city's meetings whose `external_id` is all digits and that have a numbered item with a timestamp and an id that is not all digits, newest first, at most `limit`; for each, build a `RawMeeting` from the row and call `_backfill_video_timestamps(..., force=True, dry_run=dry_run)`; return one dictionary per meeting (`meeting_id`, `external_id`, `meeting_date`, `changed`). The adapter already sleeps its polite delay after each player-page request. Add `scripts/correct_agenda_chapter_ids.py` with `--city` (required), `--limit` (default 50), and `--dry-run`; it prints one line per meeting, `meeting <id> clip <external id> <date>: <n> rows changed` (or `would change`), and a last line `<m> meetings, <n> rows`.

Added at the revision of 2026-11-05: append one sentence to the module docstring of `scripts/backfill_agenda_timestamps.py`, and change nothing else in that file: "This script fills timestamps only and never writes a Granicus chapter id; after running it, run scripts/correct_agenda_chapter_ids.py, which fills both."

Tests, five functions added to `tests/integration/test_ingest_backfill_timestamps.py` (its seven existing tests keep their mock ids such as `clip1981-1`, which are not all digits, so their items' ids stay and their assertions stand): index points with numeric ids fill the timestamp and the id together, and a second call makes no request; an item that already has its timestamp gets its id when the pass runs because another numbered item lacks a timestamp; a point whose id is not all digits fills the timestamp and leaves the stored id; two items sharing a number, and a chapter id another row already holds, are left alone with no unique-violation error, and (added at the revision of 2026-11-05, in the same function) two index points that carry one chapter id under two different item numbers give it to the first of those items only, the second keeping its stored id, again with no unique-violation error; `correct_chapter_ids`, with `get_adapter` replaced by a mock, visits only a meeting that has a cued item with a non-chapter id, writes nothing under `dry_run`, rewrites on the real run, and lists no meeting on a second run.

Acceptance. `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_ingest_backfill_timestamps.py -q -p no:cacheprovider` prints `12 passed`; `DATABASE_URL=$(tools/test-db) venv/bin/python scripts/correct_agenda_chapter_ids.py --city birmingham --dry-run` prints `0 meetings, 0 rows` on the fresh database and makes no network request; then `tools/test-db --drop`. `grep -c "correct_agenda_chapter_ids" scripts/backfill_agenda_timestamps.py` prints 1 (it printed 0 on 2026-11-05). `./tools/verify` prints `verify: all 6 checks passed` with integration at `709 passed` (704 plus 5).

### M8: the close

At the end of this milestone the repository's standing documents describe what was built, and the steps only the operator can take are listed where the operator will find them. This milestone does not move the plan file and does not write the closing retrospective; the retro stage does both.

Write `docs/specs/video-links.md`, present tense, covering: which links are timed video links and what each one's moment is; the consent rule with its two numbers; how a link chooses YouTube or Granicus (passing measurement, trusted method version, matching clip id, half-open coverage, floor); the link wording; the `meeting_video_alignments` table and its three statuses; the measuring pass (when it runs, its bound, the retry rule, its log lines, that it keeps no audio) with a pointer to `transcriber/transcriber/align.py` as the owner of the method's constants; where an item's cue point and chapter id come from (the player page, `_backfill_video_timestamps`, the correction script); and the known limits. Add its row to `docs/specs/index.md`, and adjust the index's closing sentence about `D9`. In `docs/specs/meeting-types.md` add one sentence to the recordings paragraph saying each attached recording may carry a measurement and pointing to the new spec. In `docs/specs/transcripts.md` add one sentence that the producer run begins with the measuring pass, pointing to the new spec. In `docs/specs/operations.md`: the Transcriber section gains the role's two new grants as an operator step that points at the two statements in `scripts/sql/create_transcriber_role.sql`, and the image rebuild; the paragraph on Birmingham's YouTube recordings gains one sentence that the transcriber also downloads attached recordings' audio to measure them; and the correction script's order (dry run, write, the count query) is stated once.

Graduate the durable decisions to `docs/decisions/` in the four-field format of `DECISION_FORMAT.md`, numbers from `0076`: the role's wider grants (Rationale names `0030`); the transcriber measuring attached YouTube recordings by audio and keeping none of it (Rationale names `0070` and `0065`); a timed link being built at render time from Granicus-clock seconds, YouTube only under a passing measurement that covers the moment, with the pass mark and the data it was chosen from; the consent rule; and chapter ids being written with timestamps. Edit only the Status line of `0030` and of `0070` to `accepted; \`<new number>\` <what it widens>; the rest stands`.

In `docs/DEBT.md`: add row `D94` listing the operator's after-merge steps in the order given under Validation and Acceptance, with "the pull request merges" as its trigger; add rows from `D95` for the follow-ups this plan leaves (unconfirmed windows at either edge of a recording link to Granicus, and the first minutes of a recording that starts before its clip are not covered; a recording cut within about its last 150 seconds passes and moments after the cut open YouTube at the wrong second; a recording shorter than five minutes is rejected as `no_window`; a recording with a mid-stream step of more than 2 seconds is rejected whole, with coverage in pieces as the remedy if the operator's count of `conflict` rejections shows it matters; a Granicus clip trimmed in place after measurement keeps a stale offset; a consent item whose vote was read off the video long after the consent block, with its cue point inside the block, links to the consent reading, with the fifth operator query as its count; a video removed from YouTube after measurement still receives links; a meeting with a numbered item that has no cue point has its player page fetched on every ingest run, read from `_backfill_video_timestamps`' precheck while authoring; and anything a session's Surprises added); and edit `D9` so its exception list names timed video links and the timestamp and chapter-id backfill as specified in `docs/specs/video-links.md`. Write an Outcomes entry in this plan saying what was built and what waits on the operator.

Acceptance. `ls docs/specs/video-links.md` prints the path and `grep -c "video-links.md" docs/specs/index.md` prints at least 1; `ls docs/decisions | grep -cE "^(007[6-9]|008)"` prints the number of records written (at least 3; it printed 0 at authoring), and `grep -n "^accepted; " docs/decisions/0030-transcriber-role-is-write-limited.md docs/decisions/0070-*.md` prints one line from each file; `grep -c "^| D94 " docs/DEBT.md` prints 1; `./tools/verify` prints `verify: all 6 checks passed` with the test totals M7 left.

## Concrete Steps

Every command runs from the worktree root, `/home/thinkdarrell/docket-pub/.claude/worktrees/video-links-land-on-the-moment`, with that checkout's own `venv/`. Never run bare `pytest` against a database you care about; `tests/conftest.py` refuses any database not named `docket_test_*`, and `tools/test-db` prints the URL of the throwaway one.

Before the first milestone, make sure the worktree's database role can create a role, or `./tools/verify` fails in `tests/integration/test_transcriber_role.py`:

    cat .env

Expected on this machine: one line, `DATABASE_URL=postgresql://thinkdarrell@/docket_db`. If the file is missing, `./tools/verify` prints `688 passed, 2 warnings, 3 errors` for integration (observed 2026-11-05); the operator writes that line into `.env` (the file is gitignored) and the run starts again.

Each milestone session starts with the baseline and ends with the same command:

    ./tools/verify

Expected last line: `verify: all 6 checks passed in <n>s.` Record the tier lines (`N passed`) each time; the expected totals are in each milestone's acceptance and are the authoring baseline plus the test functions that milestone names. A session that adds a test beyond those named records its own total and says so.

A single file runs against the throwaway database like this, and the database is dropped afterwards:

    DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_video_links.py -q -p no:cacheprovider
    tools/test-db --drop

The transcriber's tests that need no database run without the variable, from the worktree root:

    venv/bin/python -m pytest transcriber/tests/test_align.py -q -p no:cacheprovider

Both forms were run on 2026-11-05 against existing files (`tests/unit/test_video_urls.py` printed `8 passed`; `transcriber/tests/test_audio.py` printed `11 passed`). The transcriber's command line was run as far as it goes outside Docker: `cd transcriber && ../venv/bin/python -m transcriber.cli --help` prints the usage, and any real run stops at `PermissionError: [Errno 13] Permission denied: '/archive'`, so no milestone runs the producer for real; `scripts/backfill_youtube_meetings.py --help` printed its usage, which is the form `scripts/correct_agenda_chapter_ids.py` follows.

For each milestone: write the tests named in its section, run them and record the failure (the missing module, table, attribute, or text), write the code, run them again and record the pass, run `./tools/verify`, update Progress, Surprises & Discoveries, Decision Log, and Outcomes & Retrospective with what was observed, and commit. Every commit of a milestone session changes this plan file (decision `0037`). Commits use the repository's configured identity (`git config user.email` prints `hello@docket.pub`). Git hooks are never bypassed.

## Validation and Acceptance

The plan's code is done when all eight Progress entries are ticked and `./tools/verify` passes. The behaviour is done when the operator has taken the steps below and seen what each says. None of them is part of any milestone's acceptance, because no factory session can reach production, the Legion's Docker, or YouTube; M8 writes them into `docs/DEBT.md` as row `D94`.

Operator, before the pull request merges, in the WSL window on the Legion from `/home/thinkdarrell/docket-pub` with `DATABASE_URL` set to the production public URL as `docs/specs/operations.md` "Railway specifics" shows: run the first three read-only queries in Artifacts and Notes, and the fifth, and paste their output into the pull request. The design assumes that in most meetings one run holds nearly all consent cue points (`block_holds_80pct` close to `with_block`), that the non-chapter-id count is nonzero (the goal gives 1,434 items on 24 meetings for 2026), that `duplicated_numbers` is 0 or small, and that the fifth query's `pulled_without_own_cue` stays near the 8 of 78 it printed on 2026-11-05; the operator reads that number and decides whether the guard described in the Decision Log is wanted before merge. A result that breaks an assumption is a Surprises entry and a decision before merge, not a silent change.

Operator, after the merge, in order.

1. WSL window, `/home/thinkdarrell/docket-pub`, on a clean `main`: `scripts/deploy.sh --service docket-web`, then `scripts/deploy.sh --service worker`. The web process applies migration 042 as it starts. Every video link still opens Granicus at this point, because nothing has been measured.
2. Same window, `psql` against the production public URL as the database owner: run the two `GRANT` statements that name `meeting_videos` and `meeting_video_alignments` in `scripts/sql/create_transcriber_role.sql`. Check with `SELECT has_table_privilege('transcriber', 'meeting_video_alignments', 'INSERT');`, which prints `t`.
3. Same window, with `DATABASE_URL` set to the production public URL: `venv/bin/python scripts/correct_agenda_chapter_ids.py --city birmingham --dry-run`; keep the output; then the same without `--dry-run`; then the second query in Artifacts and Notes, which prints 0 items, or a residue that the script's WARNING lines explain. It requests one Granicus player page per listed meeting, a second or more apart. Added by the M7 session, 2026-11-06: before the dry run, run the sixth query in Artifacts and Notes. It should print 0 items; if it does not, the dry run will list meetings that are not the agenda-PDF shape this script was written for, and the first M7 entry of Surprises & Discoveries says what to check before the write. The script exits 1 and prints a `failed (...)` line for a meeting whose player page could not be read; run it again for those.
4. Windows window on the Legion, PowerShell in `C:\docket-pub\transcriber`: `git pull`, then `docker compose build`, then an ordinary run, `docker compose run --rm transcriber --since 2025-10-28 --limit 10 --max-hours 3`. The log shows up to 20 `measure meeting ...` lines and a `measure done` line before the first transcription. To work through the backlog on purpose (359 recordings on 329 meetings when counted on 2026-11-05): `docker compose run --rm transcriber --limit 0 --measure-limit 400 --max-hours 8`. A run of `failed` lines naming yt-dlp is debt `D85`'s trigger.
5. WSL window, read-only against production: the fourth query in Artifacts and Notes. Read every `rejected` row and the lowest-scoring `passed` rows; the 30-minute recording of clip 2017 should be `passed` with coverage of about 3,232 to 5,033 seconds, and the two uploads of clip 1831 should each have a row with offset about 101.28. Count the `rejected` rows by `reason`: more than a handful with reason `conflict` or `no_window` is the trigger of the debt rows M8 writes for coverage in pieces and for short recordings.
6. A browser: open https://docket.pub/al/birmingham/meetings/3184/transcript/ if meeting 3184 has a transcript (otherwise the transcript of any 2026 council meeting whose recording step 5 shows as `passed`), find the marker of item 64, and follow "video on YouTube"; for meeting 3184 it opens `FR84h22hQvA` at 27:00 (`t=1620s`). Follow the link on a consent item; it opens at 22:34 (`t=1354s`). Open the meeting page and see "Watch video" and "Watch on YouTube" side by side.
7. Record what each step printed in `docs/runbooks/transcripts.md` or the pull request, and delete row `D94`.

## Idempotence and Recovery

Migration 042 uses `CREATE TABLE IF NOT EXISTS` and has a full down (`DROP TABLE IF EXISTS meeting_video_alignments`); rolling it back loses only measurements, which the next transcriber runs make again. `tools/test-db` rebuilds the throwaway database at any time and `tools/test-db --drop` removes it.

The measuring pass can be run any number of times: a recording with a current row is not a candidate, a save is an upsert on the recording's id, each recording is committed on its own, and the work files are deleted in `finally` blocks, so a run killed mid-download leaves at most the files of one recording under names beginning `align-` or `yt-`, which the next pass overwrites and deletes. To measure everything again, raise `ALIGN_METHOD_VERSION`; to measure one recording again, delete its row (`DELETE FROM meeting_video_alignments WHERE meeting_video_id = <id>`, as the database owner). To turn YouTube links off everywhere without a deploy, the owner can run one statement, `UPDATE meeting_video_alignments SET status = 'rejected', reason = 'operator' WHERE status = 'passed'`, which sends every link back to Granicus and is not re-measured (the rows are current); `UPDATE meeting_video_alignments SET status = 'passed', reason = NULL WHERE reason = 'operator'` restores them, since the offsets and coverage were left in place.

The link builder writes nothing. A wrong link is corrected by fixing or deleting the measurement behind it.

The chapter-id rewrite is one statement per meeting and is repeatable: a rewritten item no longer matches the "not all digits" test, so a second run changes nothing. It is not reversible from the database alone (the old `event-` id is not kept), and it does not need to be: no reader depends on the old value (Context lists them). The script is always run with `--dry-run` first.

A milestone that will not fit is split in place in Progress (completed: X; remaining: Y) with a Decision Log entry, and the session stops.

## Artifacts and Notes

### The 72 labelled pairs the pass mark was chosen from

Observed by the author on 2026-11-05, read-only, on the spike's 8 kHz audio, with the reference implementation below. Lengths and offsets in seconds; "windows" is confirmed over counted; coverage is on the Granicus clock.

    clip  meeting     video         clip len  yt len   offset    score  runner  windows  conflicts  coverage
    2026  2026-10-27  FR84h22hQvA   4112.0    3443.2   +635.48    23.6    6.0     9/11      0       635.5-3935.5
    2024  2026-10-20  uvqFjIfPLLU   7490.9    6298.2  +1008.32    27.1    5.5    15/20      0      1008.3-6708.3
    2017  2026-10-13  ara-4Ve6XCU   5116.0    1801.0  +3232.20    12.3    5.3     6/6       0      3232.2-5032.2
    2016  2026-10-06  5i-rbOW2ngw   6259.9    5362.4   +890.44    25.7    5.1    15/17      0       890.4-5990.4
    2004  2026-08-11  vj6zL48MllY   5876.1    5661.1   +401.48    18.5    5.6    13/18      0       401.5-5801.5
    1831  2025-01-28  96jZkW4zv7U   5370.4    5249.2   +101.28   108.6    3.4    17/17      0       101.3-5201.3
    1831  2025-01-28  E0cpl0Snx20   5370.4    5249.2   +101.28   108.5    3.4    17/17      0       101.3-5201.3
    1530  2022-03-01  m1dWfXzbpdI   5859.0    4449.7  +1512.72    93.3    4.0    14/14      0      1512.7-5712.7
    942   2016-02-09  kxKL-StwTPg   8076.4    7486.6   +618.48   130.4    5.0    24/24      0       618.5-7818.5

All nine print `passed`. The other 63 pairings of these 8 clips and 9 videos are mismatched on purpose (a recording of one meeting against the clip of another) and all print `rejected` with reason `score`: the highest score among them is 7.3 (clip 2016 against `vj6zL48MllY`, runner-up 5.8), the largest margin over the runner-up is 1.83, the largest window share is 3 of 6 (clip 1530 against `ara-4Ve6XCU`, score 5.4), none reaches 60 percent of its windows, and three of them have one conflict window each. Computing the features of all 17 recordings took 14.9 seconds in total and each pair took under a second to measure, on this machine. The goal's figure for fetching is about a minute a pair.

On clip 2026 the window marks read, in order, `CCCCCC..CCC` (C confirmed): two quiet windows inside the recording do not confirm, which is why the mark is a share and why coverage runs from the first confirmed window to the last. One limit seen on synthetic audio: a recording that is cut less than one whole window before its end is not rejected, because the stretch after the cut never fills a window that could conflict; its coverage still ends at the last confirmed window, so no link is built past the cut. The worked links in Purpose follow from this row: 2,256 minus 635.48 is 1,620.52, 1,990 gives 1,354.52, and 2,145 gives 1,509.52, all inside 635.5 to 3,935.5.

Everything above this line in this subsection is the authored record, produced with the authored arithmetic (agreement within 1 second, whole grid windows only). The revision of 2026-11-05 changed two things in the arithmetic, the end window and the 2-second agreement tolerance, and the same 72 pairs were run again that day, read-only, on the same audio, with the revised reference implementation below:

    clip  meeting     video         clip len  yt len   offset    score  runner  windows  conflicts  coverage
    2026  2026-10-27  FR84h22hQvA   4112.0    3443.3   +635.48    23.6    6.0    10/12      0       635.5-4078.7
    2024  2026-10-20  uvqFjIfPLLU   7491.0    6298.3  +1008.32    27.1    5.5    16/21      0      1008.3-7306.5
    2017  2026-10-13  ara-4Ve6XCU   5116.1    1801.0  +3232.20    12.3    5.3     7/7       0      3232.2-5033.2
    2016  2026-10-06  5i-rbOW2ngw   6259.9    5362.5   +890.44    25.7    5.1    16/18      0       890.4-6252.8
    2004  2026-08-11  vj6zL48MllY   5876.2    5661.2   +401.48    18.5    5.6    13/19      0       401.5-5801.5
    1831  2025-01-28  96jZkW4zv7U   5370.5    5249.3   +101.28   108.6    3.4    18/18      0       101.3-5350.5
    1831  2025-01-28  E0cpl0Snx20   5370.5    5249.3   +101.28   108.5    3.4    18/18      0       101.3-5350.5
    1530  2022-03-01  m1dWfXzbpdI   5859.0    4449.7  +1512.72    93.3    4.0    15/15      0      1512.7-5859.0
    942   2016-02-09  kxKL-StwTPg   8076.5    7486.7   +618.48   130.4    5.0    25/25      0       618.5-8076.4

All nine print `passed`, with the same offsets and scores as the authored table: the end window adds one counted window to each row and changes nothing else in the whole-recording match. The lowest score is still 12.3 and the lowest margin 7.0 (clip 2017); the lowest window share is now 13 of 19 (clip 2004, 68 percent, where the authored table had 13 of 18). Eight of the nine are now covered to the end of the overlap of the two recordings (the end of the YouTube recording for clips 2026, 2024, 2017, 2016, and 1831; the end of the clip for clips 1530 and 942, whose recordings run past it); clip 2004's end window does not confirm, so its last 75 seconds stay on Granicus. Under the authored arithmetic the uncovered stretch at the end was 598 seconds on clip 2024, 262 on clip 2016, 258 on clip 942, 143 to 149 on clips 2026, 1530, and 1831, 75 on clip 2004, and 1 on clip 2017. (Lengths in this table are printed from the sample count and in the authored table from the frame count, which is why some differ by 0.1.) The 63 mismatched pairings all print `rejected` with reason `score` again: the highest score is 7.3 (clip 2016 against `vj6zL48MllY`, runner-up 5.8, 3 of 17 windows), the largest margin 1.83, the largest window share 3 of 7 (clip 1530 against `ara-4Ve6XCU`, score 5.4), and three of them have a conflict window. Computing the features of the 17 recordings took 15.1 seconds. In the same session the two changes were also tried one at a time (with the end window anchored to the end of the recording rather than of the overlap), and no verdict among the 72 moved.

A correction to the limit stated above, from synthetic audio at the revision (a 2,000-second signal; the recording is seconds 300 to 1,400 followed directly by L seconds from second 1,700, so it is cut L seconds before its end). Under the revised arithmetic the recording passes for L of 60, 100, and 140, with coverage running over the cut to the end of the recording, and is `rejected` with reason `conflict` for L of 160, 200, 250, and 290. Under the authored arithmetic it passed for every one of those seven, and for L of 140 and more its coverage also ran 100 seconds past the cut, because the last whole grid window straddled it; the authored sentence that no link is built past the cut held only when the cut fell in the leftover after the last whole window. So the revised rule catches a cut 160 seconds or more before the end, which the authored rule did not, and neither catches a cut within about the last 150 seconds: there, a moment after the cut (at most about 150 seconds of the meeting) opens YouTube at the wrong second. Context names this state and M8 records it as debt. No real pair has shown a cut.

### The reference implementation

This is the arithmetic the revised table was produced with (the spike's `align.py` plus the window rule, as revised on 2026-11-05). M1 writes `transcriber/transcriber/align.py` from it, adding types, docstrings, the dataclass, and `read_wav`. It differs from the authored reference, which produced the authored table, in exactly four places, each marked `revised` below: `AGREE_S` was 1.0; there was no `MIN_AUDIO_S` and no length check in `features`; the window loop was `for s in range(0, len(y) - wl + 1, wl)` with no end window and the in-clip test was `offset + ys + WINDOW_S > gdur` with no tolerance; and coverage took `confirmed[0]` and `confirmed[-1]`, which the end window (not always the last by start) makes `min` and `max`.

    SR, HOP, WIN = 8000, 320, 640
    FPS = SR / HOP                                   # 25 frames a second
    BANDS = (300, 700, 1300, 2200, 3600)             # four bands, Hz
    SMOOTH_S, HIGHPASS_S, WINDOW_S = 0.4, 8.0, 300
    LOCAL_SEARCH_S, AGREE_S, RUNNER_EXCLUDE_S = 40.0, 2.0, 5.0      # revised: AGREE_S was 1.0
    PASS_SCORE, PASS_MARGIN, PASS_WINDOW_SHARE, CONFLICT_SCORE = 9.0, 4.0, 0.6, 8.0
    MIN_AUDIO_S = 10                                 # revised: added

    def _moving_mean(a, seconds):
        k = max(1, int(seconds * FPS))
        c = np.cumsum(np.vstack([np.zeros((1, a.shape[1])), a]), axis=0, dtype=np.float64)
        r = (c[k:] - c[:-k]) / k
        pad = a.shape[0] - r.shape[0]
        return np.vstack([np.repeat(r[:1], pad // 2, axis=0), r,
                          np.repeat(r[-1:], pad - pad // 2, axis=0)]).astype(np.float32)

    def features(x):                                 # x: int16 samples at 8 kHz
        if len(x) < MIN_AUDIO_S * SR:                # revised: added
            raise ValueError(f"audio is {len(x) / SR:.1f}s, shorter than {MIN_AUDIO_S}s")
        n = (len(x) - WIN) // HOP + 1
        window = np.hanning(WIN).astype(np.float32)
        freqs = np.fft.rfftfreq(WIN, 1 / SR)
        masks = [(freqs >= lo) & (freqs < hi) for lo, hi in zip(BANDS[:-1], BANDS[1:])]
        out = np.empty((n, len(masks)), dtype=np.float32)
        for s in range(0, n, 20000):                 # in chunks, to bound memory
            e = min(n, s + 20000)
            idx = (np.arange(s, e)[:, None] * HOP) + np.arange(WIN)[None, :]
            spec = np.abs(np.fft.rfft(x[idx].astype(np.float32) * window, axis=1)) ** 2
            for b, m in enumerate(masks):
                out[s:e, b] = np.log(spec[:, m].sum(axis=1) + 1e3)
        out = _moving_mean(out, SMOOTH_S)
        out = out - _moving_mean(out, HIGHPASS_S)
        out -= out.mean(axis=0)
        out /= out.std(axis=0) + 1e-9
        return out

    def xcorr_z(a, b):                               # z-scored correlation and each entry's offset
        n = len(a) + len(b) - 1
        size = 1 << (n - 1).bit_length()
        total = np.zeros(n)
        for band in range(a.shape[1]):
            total += np.fft.irfft(np.fft.rfft(a[:, band], size) * np.fft.rfft(b[::-1, band], size), size)[:n]
        z = (total - total.mean()) / (total.std() + 1e-9)
        return z, (np.arange(n) - (len(b) - 1)) / FPS

    def measure(g, y):                               # g, y: feature arrays (Granicus, YouTube)
        gdur = len(g) / FPS
        z, lags = xcorr_z(g, y)
        k = int(np.argmax(z)); offset = float(lags[k]); score = float(z[k])
        rest = z.copy(); rest[np.abs(lags - offset) <= RUNNER_EXCLUDE_S] = -np.inf
        runner_up = float(rest.max())
        wl = int(WINDOW_S * FPS); counted = conflicts = 0; confirmed = []
        starts = list(range(0, len(y) - wl + 1, wl))                   # the grid: whole windows from the start
        last = min(len(y), int(round((gdur - offset) * FPS))) - wl     # revised: the end window, which ends
        if last > 0 and last not in starts:                            # where the overlap of the two ends
            starts.append(last)
        for s in starts:
            ys = s / FPS
            if offset + ys < 0 or offset + ys + WINDOW_S > gdur + 1e-6:    # revised: the tolerance
                continue                             # the window falls outside the clip
            counted += 1
            wz, wlags = xcorr_z(g, y[s:s + wl]); wlags = wlags - ys
            kb = int(np.argmax(wz))
            near = np.abs(wlags - offset) <= LOCAL_SEARCH_S
            kn = int(np.argmax(np.where(near, wz, -np.inf)))
            if abs(wlags[kn] - offset) <= AGREE_S:
                confirmed.append(ys)
            if wz[kb] >= CONFLICT_SCORE and abs(wlags[kb] - offset) > AGREE_S:
                conflicts += 1
        start = max(0.0, offset + min(confirmed)) if confirmed else None               # revised: min and max
        end = min(gdur, offset + max(confirmed) + WINDOW_S) if confirmed else None
        status, reason = verdict(score, runner_up, counted, len(confirmed), conflicts)
        ...

    def verdict(score, runner_up, windows, confirmed, conflicts):
        if windows < 1:                              return "rejected", "no_window"
        if score < PASS_SCORE:                       return "rejected", "score"
        if score - runner_up < PASS_MARGIN:          return "rejected", "margin"
        if confirmed / windows < PASS_WINDOW_SHARE:  return "rejected", "windows"
        if conflicts:                                return "rejected", "conflict"
        return "passed", None

### Migration 042

    CREATE TABLE IF NOT EXISTS meeting_video_alignments (
        meeting_video_id  INTEGER PRIMARY KEY REFERENCES meeting_videos(id) ON DELETE CASCADE,
        granicus_clip_id  TEXT NOT NULL,
        method_version    INTEGER NOT NULL,
        status            TEXT NOT NULL CHECK (status IN ('passed', 'rejected', 'failed')),
        reason            TEXT NULL,
        offset_s          DOUBLE PRECISION NULL,
        granicus_start_s  DOUBLE PRECISION NULL,
        granicus_end_s    DOUBLE PRECISION NULL,
        score             DOUBLE PRECISION NULL,
        runner_up         DOUBLE PRECISION NULL,
        windows           INTEGER NULL,
        windows_confirmed INTEGER NULL,
        measured_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT meeting_video_alignments_passed_has_span CHECK (
            status <> 'passed'
            OR (offset_s IS NOT NULL AND granicus_start_s IS NOT NULL
                AND granicus_end_s IS NOT NULL AND granicus_end_s > granicus_start_s))
    );

`offset_s` is Granicus seconds minus YouTube seconds. `reason` holds the verdict's reason for a `rejected` row and the error text for a `failed` one. The down is `DROP TABLE IF EXISTS meeting_video_alignments;`. The only readers of `status` are `video_links.for_meetings` (which takes `passed` rows alone) and `db.alignment_candidates`.

### The operator's read-only queries

Each was parsed on the throwaway database on 2026-11-05 (every count printed 0 there). Run them inside `BEGIN READ ONLY; ... ROLLBACK;`.

First, the shape of consent cue points since 2021:

    WITH c AS (
      SELECT a.meeting_id, a.video_timestamp_seconds AS t
        FROM agenda_items a
        JOIN meetings m ON m.id = a.meeting_id
        JOIN municipalities mu ON mu.id = m.municipality_id
       WHERE mu.slug = 'birmingham' AND m.external_id ~ '^[0-9]+$' AND m.meeting_date >= '2021-01-01'
         AND a.is_consent AND a.video_timestamp_seconds IS NOT NULL),
    g AS (SELECT meeting_id, t,
                 CASE WHEN t - lag(t) OVER (PARTITION BY meeting_id ORDER BY t) <= 120 THEN 0 ELSE 1 END AS brk
            FROM c),
    r AS (SELECT meeting_id, sum(brk) OVER (PARTITION BY meeting_id ORDER BY t) AS run FROM g),
    s AS (SELECT meeting_id, run, count(*) AS n FROM r GROUP BY 1, 2),
    p AS (SELECT meeting_id, sum(n) AS cues, max(n) AS largest, count(*) AS runs FROM s GROUP BY 1)
    SELECT count(*) AS meetings,
           count(*) FILTER (WHERE largest >= 3) AS with_block,
           count(*) FILTER (WHERE runs = 1) AS one_run,
           count(*) FILTER (WHERE largest >= 0.8 * cues) AS block_holds_80pct,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY cues - largest) AS median_outside,
           max(cues - largest) AS max_outside
      FROM p;

Second, cued items whose id is not a chapter id (nonzero before the correction run, 0 or an explained residue after):

    SELECT count(*) AS items, count(DISTINCT a.meeting_id) AS meetings
      FROM agenda_items a
      JOIN meetings m ON m.id = a.meeting_id
      JOIN municipalities mu ON mu.id = m.municipality_id
     WHERE mu.slug = 'birmingham' AND m.external_id ~ '^[0-9]+$'
       AND a.item_number IS NOT NULL AND a.video_timestamp_seconds IS NOT NULL
       AND a.external_id !~ '^[0-9]+$';

Third, item numbers that repeat inside a meeting that has event-style ids (each is an id the rewrite leaves alone):

    SELECT count(*) AS duplicated_numbers
      FROM (SELECT a.meeting_id, a.item_number
              FROM agenda_items a
              JOIN meetings m ON m.id = a.meeting_id
              JOIN municipalities mu ON mu.id = m.municipality_id
             WHERE mu.slug = 'birmingham' AND m.external_id ~ '^[0-9]+$' AND a.item_number IS NOT NULL
               AND EXISTS (SELECT 1 FROM agenda_items e
                            WHERE e.meeting_id = a.meeting_id AND e.external_id LIKE 'event-%')
             GROUP BY 1, 2 HAVING count(*) > 1) d;

Fourth, after the first measuring runs (this one could not be parsed at authoring, since the table does not exist yet):

    SELECT status, count(*), round(min(score)::numeric, 1) AS lowest, round(max(score)::numeric, 1) AS highest
      FROM meeting_video_alignments GROUP BY 1 ORDER BY 1;
    SELECT m.id, m.meeting_date, m.external_id, v.video_id, a.status, a.reason, a.offset_s,
           a.granicus_start_s, a.granicus_end_s, a.score, a.runner_up, a.windows_confirmed, a.windows
      FROM meeting_video_alignments a
      JOIN meeting_videos v ON v.id = a.meeting_video_id
      JOIN meetings m ON m.id = v.meeting_id
     WHERE a.status <> 'passed' OR a.score < 20
     ORDER BY m.meeting_date DESC;
    SELECT status, reason, count(*) FROM meeting_video_alignments GROUP BY 1, 2 ORDER BY 1, 2;

Fifth, added at the revision of 2026-11-05: votes read off the video on consent items, against the consent block as `video_links.consent_block` defines it (the largest run of consent cue points at most 120 seconds apart, at least 3, the earlier run on a tie). It was run on production, read-only, on 2026-11-05 and printed `78 | 0 | 53 | 8`. `pulled_without_own_cue` counts the votes that fall more than 120 seconds after the block while the item's cue point is inside the block or missing: the votes whose link lands on the start of the consent agenda although the vote came later. The Decision Log says what the 8 were.

    WITH c AS (
      SELECT a.meeting_id, a.video_timestamp_seconds AS t
        FROM agenda_items a
        JOIN meetings m ON m.id = a.meeting_id
        JOIN municipalities mu ON mu.id = m.municipality_id
       WHERE mu.slug = 'birmingham' AND a.is_consent AND a.video_timestamp_seconds IS NOT NULL),
    g AS (SELECT meeting_id, t,
                 CASE WHEN t - lag(t) OVER (PARTITION BY meeting_id ORDER BY t) <= 120 THEN 0 ELSE 1 END AS brk
            FROM c),
    r AS (SELECT meeting_id, t, sum(brk) OVER (PARTITION BY meeting_id ORDER BY t) AS run FROM g),
    s AS (SELECT meeting_id, run, count(*) AS n, min(t) AS start_s, max(t) AS end_s FROM r GROUP BY 1, 2),
    b AS (SELECT DISTINCT ON (meeting_id) meeting_id, start_s, end_s
            FROM s WHERE n >= 3 ORDER BY meeting_id, n DESC, start_s),
    x AS (SELECT v.video_timestamp AS vote_s, a.video_timestamp_seconds AS cue_s, b.start_s, b.end_s
            FROM vote_agenda_items vai
            JOIN votes v ON v.id = vai.vote_id
            JOIN agenda_items a ON a.id = vai.agenda_item_id
            JOIN meetings m ON m.id = a.meeting_id
            JOIN municipalities mu ON mu.id = m.municipality_id
            LEFT JOIN b ON b.meeting_id = a.meeting_id
           WHERE mu.slug = 'birmingham' AND vai.is_active AND v.video_timestamp IS NOT NULL
             AND a.is_consent AND v.meeting_id = a.meeting_id)
    SELECT count(*) AS votes_on_consent_items,
           count(*) FILTER (WHERE end_s IS NULL) AS meeting_has_no_block,
           count(*) FILTER (WHERE vote_s > end_s + 120) AS voted_after_the_block,
           count(*) FILTER (WHERE vote_s > end_s + 120
                              AND (cue_s IS NULL OR cue_s BETWEEN start_s AND end_s)) AS pulled_without_own_cue
      FROM x;

Sixth, added by the M7 session on 2026-11-06: cued, numbered items whose id is neither a chapter id nor an agenda-PDF id (`event-...`), and how many of them have no id at all. It was parsed on the throwaway database, where it printed `0|0|0`; it has not been run on production. The correction script lists the meetings of these items too, and they are not the shape it was written for (the first M7 entry of Surprises & Discoveries). Run it before the script's dry run; 0 items means every meeting the script lists is one whose ids came from an agenda PDF.

    SELECT count(*) AS items, count(DISTINCT a.meeting_id) AS meetings,
           count(*) FILTER (WHERE a.external_id IS NULL) AS no_id
      FROM agenda_items a
      JOIN meetings m ON m.id = a.meeting_id
      JOIN municipalities mu ON mu.id = m.municipality_id
     WHERE mu.slug = 'birmingham' AND m.external_id ~ '^[0-9]+$'
       AND a.item_number IS NOT NULL AND a.video_timestamp_seconds IS NOT NULL
       AND (a.external_id IS NULL
            OR (a.external_id !~ '^[0-9]+$' AND a.external_id NOT LIKE 'event-%'));

### M1 as executed, 2026-11-06

Everything in this subsection was observed in the M1 session, in this worktree, on 2026-11-06 (UTC).

The starting state, before any edit. `.env` exists in the worktree (its contents were not read: the session's permission system refused `cat .env`, so the session checked only that the file is there, and the database the baseline built confirms the role). `./tools/verify`, started at 04:51Z and run a second time to keep its output, printed `2228 passed, 5 skipped, 4 xfailed, 2 warnings` for the unit, web, and services tier, `690 passed, 2 warnings` for integration, `judge fixtures: 12 of 12 passed`, `95 passed, 1 warning` for the transcriber suite, and `verify: all 6 checks passed in 109s.` (the first run: `in 112s.`); the throwaway database was `postgresql://thinkdarrell@/docket_test_7c0790d1`. These are the authoring baseline's totals.

The before state of the new tests, with `transcriber/tests/test_align.py` written and `transcriber/transcriber/align.py` not yet existing:

    $ venv/bin/python -m pytest transcriber/tests/test_align.py -q -p no:cacheprovider
    E       ModuleNotFoundError: No module named 'transcriber.align'      (ten times, once per test)
    10 failed, 1 warning in 0.10s

The test file is committed in this state, before the module, so the before state is readable from git (commit `78b19e8`).

The after state, with `transcriber/transcriber/align.py` written and the numpy line added to `transcriber/requirements.txt`:

    $ venv/bin/python -m pytest transcriber/tests/test_align.py -q -p no:cacheprovider
    10 passed, 1 warning in 2.75s

The file's wall time is under 3 seconds against the plan's bound of 20 (a run with `--durations` printed 2.71s in all and 0.90s for the slowest test, the shifted noisy copy). The warning is the `anyio` plugin's deprecation notice that every tier prints.

`./tools/verify`, started at 04:59Z with those two changes in the working tree and before the plan's tick was written, printed `2228 passed, 5 skipped, 4 xfailed, 2 warnings` for the unit, web, and services tier, `690 passed, 2 warnings` for integration, `judge fixtures: 12 of 12 passed`, `105 passed, 1 warning in 3.93s` for the transcriber suite (95 plus the 10 added), and `verify: all 6 checks passed in 110s.` After the tick was written into Progress, `tools/check-plans` (the sixth check, and the only one that reads this file) was run alone and printed `plans: 2 of 2 ok`; the full command was not run a third time.

What `describe()` printed for each synthetic case, on the signal the tests draw (Granicus from seed 1, the added noise from seed 2, the unrelated signals from seeds 3, 99, and 4), first from the module as committed and then from a copy altered in memory to the authored rule (`AGREE_S` 1.0, no end window):

    shifted noisy copy    passed offset=400.00s covers=400.0-1305.0s score=40.9 runner_up=3.7 windows=4/4
    unrelated             rejected (score) offset=-84.04s covers=216.0-516.0s score=5.4 runner_up=4.3 windows=1/3
    starts before clip    passed offset=-200.00s covers=100.0-905.0s score=44.8 runner_up=3.7 windows=3/3
    cut                   rejected (conflict) offset=300.00s covers=300.0-1500.0s score=49.5 runner_up=13.3 windows=4/6
    runs past clip        passed offset=1250.00s covers=1250.0-2000.0s score=39.4 runner_up=3.8 windows=3/3
    step of 1.5 s         passed offset=400.00s covers=400.0-1603.4s score=27.0 runner_up=4.1 windows=5/5
    step of 3 s           rejected (windows) offset=400.00s covers=400.0-1000.0s score=26.0 runner_up=4.2 windows=2/5

    under the authored rule:
    shifted noisy copy    passed offset=400.00s covers=400.0-1300.0s score=40.9 runner_up=3.7 windows=3/3
    unrelated             rejected (score) offset=-84.04s covers=216.0-516.0s score=5.4 runner_up=4.3 windows=1/2
    starts before clip    passed offset=-200.00s covers=100.0-700.0s score=44.8 runner_up=3.7 windows=2/2
    cut                   rejected (conflict) offset=300.00s covers=300.0-1500.0s score=49.5 runner_up=13.3 windows=4/5
    runs past clip        passed offset=1250.00s covers=1250.0-1850.0s score=39.4 runner_up=3.8 windows=2/2
    step of 1.5 s         rejected (windows) offset=400.00s covers=400.0-1000.0s score=27.0 runner_up=4.1 windows=2/4
    step of 3 s           rejected (windows) offset=400.00s covers=400.0-1000.0s score=26.0 runner_up=4.2 windows=2/4

The module run as a module, on WAV files of the first two cases written to the session's scratch folder and deleted afterwards:

    $ cd transcriber && ../venv/bin/python -m transcriber.align <scratch>/g.wav <scratch>/y.wav
    passed offset=400.00s covers=400.0-1305.0s score=40.9 runner_up=3.7 windows=4/4
    $ cd transcriber && ../venv/bin/python -m transcriber.align <scratch>/g.wav <scratch>/u.wav
    rejected (score) offset=-84.04s covers=216.0-516.0s score=5.4 runner_up=4.3 windows=1/3
    $ cd transcriber && ../venv/bin/python -m transcriber.align <scratch>/g.wav
    usage: python -m transcriber.align <granicus.wav> <youtube.wav>          (exit 2)

No line from real audio is recorded here: the spike's nine pairs were not rerun (Surprises & Discoveries and the Decision Log say why).

### M2 as executed, 2026-11-06

Everything in this subsection was observed in the M2 session, in this worktree, on 2026-11-06 (UTC).

The starting state, before any edit. `test -f .env` printed `.env exists` (the file was not read). `./tools/verify`, started at 05:05Z and run a second time at 05:08Z to keep its output, printed `2228 passed, 5 skipped, 4 xfailed, 2 warnings` for the unit, web, and services tier, `690 passed, 2 warnings` for integration, `judge fixtures: 12 of 12 passed`, `105 passed, 1 warning` for the transcriber suite, and `verify: all 6 checks passed in 110s.` both times; the throwaway database was `postgresql://thinkdarrell@/docket_test_7c0790d1`. These are the totals M1 left.

The files M2's acceptance names, counted before any edit, against the throwaway database:

    $ DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_038_migration.py tests/integration/test_040_migration.py tests/integration/test_transcriber_role.py -q -p no:cacheprovider
    14 passed, 1 warning in 0.45s          (alone: test_038_migration.py 5 passed, test_040_migration.py 6 passed)
    $ DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest transcriber/tests/test_db.py -q -p no:cacheprovider
    21 passed, 1 warning in 0.27s

So the three existing files hold 14 tests, not the 5 that M2's `13 passed` assumes: its "3 and 2 that existed" count the functions at the top level of `test_038_migration.py` and `test_040_migration.py` and miss the two and four tests each file holds in a class. With the 3 and 2 this milestone adds, the first acceptance command can only print `19 passed`. The Decision Log entry of this session says how that was resolved.

The before state of the new tests: `tests/integration/test_042_migration.py` written (three functions), two functions added to `tests/integration/test_transcriber_role.py`, five to `transcriber/tests/test_db.py`, and `runner.rollback_migration(conn, 42)` added before each of the three rollbacks of 040; no migration 042, no change to the role file, and nothing new in `transcriber/transcriber/db.py`.

    $ DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_038_migration.py tests/integration/test_040_migration.py tests/integration/test_042_migration.py tests/integration/test_transcriber_role.py -q -p no:cacheprovider
    FAILED tests/integration/test_042_migration.py::test_042_up_creates_the_table_and_its_checks_refuse_bad_rows
    FAILED tests/integration/test_042_migration.py::test_042_one_row_per_recording_and_the_meeting_takes_it_along
    FAILED tests/integration/test_042_migration.py::test_042_down_drops_the_table_and_up_restores_it
    FAILED tests/integration/test_transcriber_role.py::test_can_read_meeting_videos_and_not_write_them
    FAILED tests/integration/test_transcriber_role.py::test_can_save_measurements_and_not_delete_them
    5 failed, 14 passed, 1 warning in 0.59s

The three migration tests fail on `assert _table_exists()` after the up and on `psycopg2.errors.UndefinedTable: relation "meeting_video_alignments" does not exist`; the two role tests fail on `_priv('meeting_videos', 'SELECT')` being false and on the same missing relation. The 14 that existed still pass with the added rollback of 042 in their fixtures, because rolling back a migration that is not applied prints `Migration 42 is not applied.` and returns.

    $ DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest transcriber/tests/test_db.py -q -p no:cacheprovider
    FAILED transcriber/tests/test_db.py::test_alignment_candidates_newest_meeting_first_primary_first_within_the_limit
    FAILED transcriber/tests/test_db.py::test_measured_rejected_hidden_and_yt_row_recordings_are_not_alignment_candidates
    FAILED transcriber/tests/test_db.py::test_lower_version_other_clip_and_old_failure_are_alignment_candidates_again
    FAILED transcriber/tests/test_db.py::test_save_alignment_twice_leaves_one_row_holding_the_second_calls_values
    FAILED transcriber/tests/test_db.py::test_alignment_backlog_counts_the_candidates_without_a_limit
    5 failed, 21 passed, 1 warning in 0.46s

Those five fail on `AttributeError: module 'transcriber.db' has no attribute 'alignment_candidates'` (or `'alignment_backlog'`) and, where a test first stores a measurement, on the missing relation. The tests are committed in this state, before the migration, the grants, and the functions, so the before state is readable from git (commit `a5f4ab3`).

The after state, with `src/docket/migrations/042_meeting_video_alignments.py` written and listed in `runner.py`, the two grants added to `scripts/sql/create_transcriber_role.sql`, and the dataclass and three functions added to `transcriber/transcriber/db.py`. The acceptance commands, started at 05:15Z, with the build output of `tools/test-db` kept from stderr:

    $ DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_038_migration.py tests/integration/test_040_migration.py tests/integration/test_042_migration.py tests/integration/test_transcriber_role.py -q -p no:cacheprovider
    Applying migration 42: docket.migrations.042_meeting_video_alignments          (from the build, on stderr)
      Applied migration 42
    19 passed, 1 warning in 0.63s
    $ DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest transcriber/tests/test_db.py -q -p no:cacheprovider
    26 passed, 1 warning in 0.38s
    $ tools/test-db --drop                                                          (printed nothing, exit 0)

`./tools/verify`, started at 05:15Z after those, with every change of the milestone in the working tree and before the plan's tick was written, printed `2228 passed, 5 skipped, 4 xfailed, 2 warnings` for the unit, web, and services tier, `695 passed, 2 warnings` for integration (690 plus 5), `judge fixtures: 12 of 12 passed`, `110 passed, 1 warning in 4.09s` for the transcriber suite (105 plus 5), and `verify: all 6 checks passed in 110s.` After the tick and the living sections were written, `tools/check-plans` (the sixth check, and the only one that reads this file) was run alone and printed `plans: 2 of 2 ok`; the full command was not run again, since nothing but this file changed after it.

The removal check on the candidate query (Surprises & Discoveries), as it printed after the two additions to the tests (the failing tests' names are shortened here and set in parentheses); each line is the five alignment tests run against the two SQL strings of `transcriber.db` with one rule taken out in memory:

    as committed: 0 failed
    no never-measured-first ordering: 1 failed    (test_lower_version_other_clip_and_old_failure_are_alignment_candidates_again)
    no primary-first ordering: 1 failed           (test_alignment_candidates_newest_meeting_first_primary_first_within_the_limit)
    hidden meetings admitted: 1 failed            (test_measured_rejected_hidden_and_yt_row_recordings_are_not_alignment_candidates)
    yt- and event- rows admitted: 1 failed        (the same)
    clip id not compared: 1 failed                (test_lower_version_...)
    version compared by equality: 1 failed        (test_lower_version_...)
    failures never retried: 2 failed              (test_lower_version_... and test_alignment_backlog_counts_the_candidates_without_a_limit)
    rejected rows retried like failures: 1 failed (test_measured_rejected_...)

The functions under the role's grants, on the throwaway database, from a scratch script that created the role from the file, did `SET ROLE transcriber`, and removed the role and its rows afterwards:

    current_user: transcriber
    candidates: [('roleProbe01', '999930')]
    backlog: 1
    saved twice; backlog now: 0
    InsufficientPrivilege: permission denied for table meeting_video_alignments      (DELETE FROM meeting_video_alignments)
    InsufficientPrivilege: permission denied for table meeting_videos                (UPDATE meeting_videos SET is_primary = FALSE)
    rows left: 0

Not observed in this session, because no factory session can reach them: the migration on production, the two GRANT statements on the production role, and any real measurement. They are the operator's steps 1, 2, and 4 under Validation and Acceptance.

### M3 as executed, 2026-11-06

Everything in this subsection was observed in the M3 session, in this worktree, on 2026-11-06 (UTC).

The starting state, before any edit. `test -f .env` printed `.env exists` (the file was not read). `./tools/verify`, started at 05:21Z and run a second time at 05:23Z to keep its output, printed `2228 passed, 5 skipped, 4 xfailed, 2 warnings` for the unit, web, and services tier, `695 passed, 2 warnings` for integration, `judge fixtures: 12 of 12 passed`, `110 passed, 1 warning in 4.01s` for the transcriber suite, and `verify: all 6 checks passed in 111s.` (the first run: `in 110s.`); the throwaway database was `postgresql://thinkdarrell@/docket_test_7c0790d1`. These are the totals M2 left.

The before state of the new tests, started at 05:29Z: `transcriber/tests/test_measure.py` written (eleven functions) and two functions added to `transcriber/tests/test_audio.py`; no `transcriber/transcriber/measure.py`, and no change to `audio.py`, `cli.py`, or `__init__.py`.

    $ venv/bin/python -m pytest transcriber/tests/test_measure.py transcriber/tests/test_audio.py transcriber/tests/test_cli_loop.py -q -p no:cacheprovider
    E       ImportError: cannot import name 'measure' from 'transcriber' (.../transcriber/transcriber/__init__.py)      (ten times, once per test of the pass)
    E       AttributeError: <module 'transcriber.cli' ...> has no attribute 'measure_pass'                               (the test of main())
    E       TypeError: fetch_audio() got an unexpected keyword argument 'rate'
    E       TypeError: ytdlp_options() got an unexpected keyword argument 'audio_format'
    13 failed, 28 passed, 1 warning in 0.39s

The 13 that fail are the 13 this milestone adds (all eleven of `test_measure.py`, and `test_fetch_audio_rate_is_ffmpegs_ar` and `test_ytdlp_options_takes_the_audio_format_and_sets_a_socket_timeout` in `test_audio.py`); the 28 that pass are the 11 `test_audio.py` held and the 17 of `test_cli_loop.py`. The tests are committed in this state, before the module and the keywords exist, so the before state is readable from git (commit `505214c`).

The after state, with `transcriber/transcriber/measure.py` written, the keywords added in `audio.py`, the wiring in `cli.py`, and `__version__` at `0.5.0`. The acceptance commands, started at 05:33Z:

    $ venv/bin/python -m pytest transcriber/tests/test_measure.py transcriber/tests/test_audio.py transcriber/tests/test_cli_loop.py -q -p no:cacheprovider
    41 passed, 1 warning in 0.31s
    $ cd transcriber && ../venv/bin/python -m transcriber.cli --help
                  [--measure-limit MEASURE_LIMIT]
      --measure-limit MEASURE_LIMIT
                            attached YouTube recordings to measure against their
                            Granicus clips before transcribing (no GPU); 0 turns
                            the measuring off

(Two assertions were added to `test_measure.py` after the commit above and before this run, both inside functions that already existed: the rollback count in the first test and the three-candidate case in the second. The count stayed at eleven.)

`./tools/verify`, started at 05:33Z with every change of the milestone in the working tree and before the plan's tick was written, printed `2228 passed, 5 skipped, 4 xfailed, 2 warnings` for the unit, web, and services tier, `695 passed, 2 warnings` for integration, `judge fixtures: 12 of 12 passed`, `123 passed, 1 warning in 3.98s` for the transcriber suite (110 plus 13), and `verify: all 6 checks passed in 111s.` After the tick and the living sections were written, `tools/check-plans` (the sixth check, and the only one that reads this file) was run alone and printed `plans: 2 of 2 ok`, and the pre-commit hook printed `plans: 1 of 1 ok` on the commit that carries the code (`bfcccd4`); the full command was not run again, since nothing but this file changed after it.

The removal check (Surprises & Discoveries): the eleven tests of `test_measure.py` run against `transcriber.measure` with one rule taken out in memory by a scratch pytest plugin. Each line is the rule removed, how many of the eleven failed, and which (names shortened):

    as committed                                     0 failed
    Granicus failure counted once per row            1   (granicus_fetch_error_on_a_meeting_with_three_recordings)
    count not set back after a measured recording    1   (three_youtube_fetch_failures_in_a_row)
    never stops on failures                          1   (three_youtube_fetch_failures_in_a_row)
    YouTube download not removed                     9
    YouTube WAV not removed                          8
    Granicus WAV not removed                         9
    archived FLAC ignored                            1   (an_archived_audio_flac_is_the_granicus_source)
    no pause after a failed Granicus request         1   (granicus_fetch_error_on_a_meeting_with_three_recordings)
    no pause at all                                  3
    only named exception types on a recording        3   (youtube_fetch_error, three_youtube_fetch_failures, an_unexpected_error_on_one_recording)
    only named exception types on the clip           1   (granicus_fetch_error_on_a_meeting_with_three_recordings)
    no stop check before a recording                 1   (a_set_stop_flag_and_a_passed_deadline)
    no stop check before a meeting                   1   (the same)
    stop flag ignored                                1   (the same)
    deadline ignored                                 1   (the same)
    deadline passed when merely reached              1   (the same)
    top handler gone                                 1   (insufficient_privilege_on_the_candidate_read)
    top handler catches database errors only         1   (the same)
    no rollback in the top handler                   1   (the same)
    no rollback after the candidate read             2
    no commit after a measured row                   1   (each_candidate_is_measured_once)
    a limit of zero still reads                      1   (a_limit_of_zero_reads_nothing)
    conversion at the default rate                   1   (each_candidate_is_measured_once)
    yt-dlp's default format                          3
    reason without the class name                    4
    Granicus audio fetched per recording             3
    failed row saved with no reason                  3

This run was made before the three-candidate case was added to the second test; that case was then seen to pass with the committed module (the `41 passed` above) and was not run against a copy that groups only adjacent rows.

The pass from end to end, started at 05:32Z from a scratch script (not committed) run in `transcriber/` against the throwaway database `postgresql://thinkdarrell@/docket_test_7c0790d1`, which was dropped afterwards. Real: ffmpeg 8.0.1, `align`, and the three `db.py` functions. Stood in for: yt-dlp (`measure.source_for` copied a local file into the work folder, or raised) and the Granicus download URL (`measure.download_url_for` returned a local file). The audio is M1's synthetic signal: the clip is 2,000 seconds from seed 1, a "shifted" recording is seconds 400 to 1,305 of it with noise, and an "unrelated" one is 905 seconds from seed 3. The script inserted three Birmingham meetings and four recordings. Clip 999941 had an archived 16 kHz `audio.flac` and two recordings (the shifted one and the unrelated one, each as Opus in WebM at 24 kbit/s and 48 kHz); clip 999942 had no FLAC, so its audio came from the stand-in download (AAC in MP4 at 44.1 kHz), and one shifted recording; clip 999943's recording raised `AudioFetchError` after leaving a `.part` file. It printed:

    INFO transcriber.measure: measure meeting 1 clip 999941 video m3shifted01: passed offset=400.00s covers=400.0-1305.0s score=40.8 runner_up=3.6 windows=4/4
    INFO transcriber.measure: measure meeting 1 clip 999941 video m3unrelat01: rejected (score) offset=-84.04s covers=216.0-516.0s score=5.4 runner_up=4.3 windows=1/3
    INFO transcriber.measure: measure meeting 2 clip 999942 video m3shifted02: passed offset=400.00s covers=400.0-1305.0s score=41.1 runner_up=3.6 windows=4/4
    WARNING transcriber.measure: measure meeting 3 clip 999943 video m3refused01: failed (AudioFetchError: yt-dlp could not download https://www.youtube.com/watch?v=m3refused01: Sign in to confirm you're not a bot)
    INFO transcriber.measure: measure done {'passed': 2, 'rejected': 1, 'failed': 1} remaining=0
    returned: {'passed': 2, 'rejected': 1, 'failed': 1}
    granicus downloads asked for: ['999942', '999943'] pauses: [3.0, 3.0]
    work folder: []
    archive: ['<meeting 999941>', '<meeting 999941>/audio.flac'] flac untouched: True
    row: ('m3refused01', '999943', 1, 'failed', 'AudioFetchError: yt-dlp could not download https://www.youtu', None, None, None, None, None, None)
    row: ('m3shifted01', '999941', 1, 'passed', None, Decimal('400.00'), Decimal('400.0'), Decimal('1305.0'), Decimal('40.8'), 4, 4)
    row: ('m3shifted02', '999942', 1, 'passed', None, Decimal('400.00'), Decimal('400.0'), Decimal('1305.0'), Decimal('41.1'), 4, 4)
    row: ('m3unrelat01', '999941', 1, 'rejected', 'score', Decimal('-84.04'), Decimal('216.0'), Decimal('516.0'), Decimal('5.4'), 1, 3)
    INFO transcriber.measure: measure done {'passed': 0, 'rejected': 0, 'failed': 0} remaining=0
    second pass: {'passed': 0, 'rejected': 0, 'failed': 0} downloads asked for now: ['999942', '999943']
    rows left: 0

The row columns are the video id, `granicus_clip_id`, `method_version`, `status`, the first 60 characters of `reason`, `offset_s`, `granicus_start_s`, `granicus_end_s`, `score`, `windows_confirmed`, and `windows`. The pauses were recorded, not slept. The second pass found no candidate: the fresh `failed` row is not one for seven days. The same pair measured from raw samples in M1 printed `score=40.9`.

Not observed in this session, because no factory session can reach them: yt-dlp downloading a recording, ffmpeg reading a Granicus URL, the pass inside the Docker image, and the production role. They are the operator's step 4 under Validation and Acceptance, after steps 1 and 2.

### M4 as executed, 2026-11-06

Everything in this subsection was observed in the M4 session, in this worktree, on 2026-11-06 (UTC).

The starting state, before any edit. `test -f .env` printed `.env exists` (the file was not read). `./tools/verify`, started at 05:41Z, printed `2228 passed, 5 skipped, 4 xfailed, 2 warnings in 55.35s` for the unit, web, and services tier, `695 passed, 2 warnings in 48.28s` for integration, `judge fixtures: 12 of 12 passed`, `123 passed, 1 warning in 4.12s` for the transcriber suite, and `verify: all 6 checks passed in 110s.`; the throwaway database was `postgresql://thinkdarrell@/docket_test_7c0790d1`. These are the totals M3 left.

The before state of the new tests, started at 05:44Z: `tests/unit/test_video_urls.py` moved with `git mv` to `tests/unit/test_video_links.py`, its import line still naming `docket.web.video_urls` (which still exists), and fifteen functions added below its eight; `tests/integration/test_video_link_loader.py` written (five functions); no `src/docket/services/video_links.py`.

    $ DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_video_links.py tests/integration/test_video_link_loader.py -q -p no:cacheprovider
    E       ImportError: cannot import name 'video_links' from 'docket.services' (.../src/docket/services/__init__.py)      (twenty times, once per new test)
    20 failed, 8 passed, 1 warning in 0.20s
    $ tools/test-db --drop      (exit 0)

The 20 that fail are the 20 this milestone adds; the 8 that pass are the moved tests of `chapter_url`. The tests are committed in this state, before the module exists, so the before state is readable from git (commit `7655bbb`).

The after state, with `src/docket/services/video_links.py` written, `src/docket/web/video_urls.py` deleted with `git rm`, the `chapter_url` global in `src/docket/web/__init__.py` pointed at `video_links.chapter_url`, and the moved test file's import changed. The first run of the two files, started at 05:46Z, printed `28 passed, 1 warning in 0.33s`. Three assertions were then added inside functions that already existed (Decision Log), and the acceptance commands were run in their final form at 05:49Z:

    $ DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_video_links.py tests/integration/test_video_link_loader.py -q -p no:cacheprovider
    28 passed, 1 warning in 0.31s
    $ tools/test-db --drop      (exit 0)
    $ git grep -n "video_urls" -- src tests
    $                           (nothing printed; exit 1)

`./tools/verify`, started at 05:47Z with every change of the milestone in the working tree and before the plan's tick was written, printed `2243 passed, 5 skipped, 4 xfailed, 2 warnings in 55.47s` for the unit, web, and services tier (2228 plus 15), `700 passed, 2 warnings in 48.26s` for integration (695 plus 5), `judge fixtures: 12 of 12 passed`, `workflows: 2 of 2 ok`, `123 passed, 1 warning in 4.03s` for the transcriber suite, `plans: 2 of 2 ok`, and `verify: all 6 checks passed in 110s.` No file was edited while it ran. After the tick and the living sections were written, `tools/check-plans` (the sixth check, and the only one that reads this file) was run alone at 05:52Z and printed `plans: 2 of 2 ok`; the full command was not run again, since nothing but this file changed after it.

That the pages still get their links from the same function, checked three ways. The function moved without a change: a `diff` of `chapter_url` as `git show HEAD:src/docket/web/video_urls.py` prints it against the function in the new module printed nothing. The application registers it: a one-off command that built the app with `create_app()` and read `app.jinja_env.globals['chapter_url']` printed `docket.services.video_links True https://bhamal.granicus.com/MediaPlayer.php?view_id=2&clip_id=1986&meta_id=371120` (the module the global comes from, whether it is `video_links.chapter_url`, and its result for chapter 371120). And the four templates are untouched: `git grep -n "chapter_url(" -- src/docket/web` still prints four lines, the four templates, where it printed five at authoring (the fifth was the definition); the web tier that renders them is inside the `2243 passed`.

The removal check (Surprises & Discoveries): the 23 tests of `tests/unit/test_video_links.py` and the 5 of `tests/integration/test_video_link_loader.py`, run against `docket.services.video_links` with one rule taken out in memory by a scratch pytest plugin, on the throwaway database, which was dropped afterwards. Each line is the rule removed, how many of the 28 failed, and which (names shortened):

    as committed                                          0 failed
    version compared by equality                          1   (a_measurement_below_the_trusted_method_version)
    no version floor                                      1   (the same)
    no clip-id comparison                                 1   (a_measurement_against_another_clip)
    any status                                            1   (for_meetings_returns_only_passed_recordings)
    recordings not primary first                          1   (the same)
    recordings newest first after the primary             1   (the same)
    non-consent cue points read too                       1   (the_consent_block_is_computed_from_the_meetings_consent_cue_points)
    tied cue points in reverse row order                  1   (the same)
    a gap of exactly 120 s splits a run                   2
    two cue points make a block                           2
    of two equal runs the later                           1   (of_two_runs_the_larger_is_the_block)
    block chapter always the first id                     1   (the_consent_blocks_chapter_is_the_first_all_digit_id)
    cue points not sorted                                 2
    block's last cue point outside it                     2
    block's first cue point outside it                    0, and 1 after the added assertion (item_moment_follows_the_consent_rule)
    un-cued consent item has no moment                    2
    consent rule applied to every item                    1   (item_moment_follows_the_consent_rule)
    consent rule applied to none                          2
    coverage includes its end                             1   (a_moment_outside_coverage_opens_the_granicus_chapter)
    coverage excludes its start                           1   (the same)
    coverage not tested                                   3
    negative converted second allowed                     1   (a_covered_moment_whose_converted_second_would_be_negative)
    first covering recording only                         1   (the same)
    converted second rounded, not floored                 3
    offset added, not subtracted                          5
    timed whenever a chapter id is given                  1   (no_recordings_opens_granicus_and_a_non_chapter_id_the_plain_player)
    own YouTube link appended to the stored URL           1   (a_youtube_link_is_built_from_the_video_id)
    own YouTube second rounded                            1   (a_youtube_meeting_links_to_its_own_video)
    own YouTube negative second kept                      1   (the same)
    any host with watch?v= is YouTube                     1   (a_youtube_link_is_built_from_the_video_id)
    youtu.be not read                                     1   (the same)
    an empty video id accepted                            1   (the same)
    an unreadable second raises                           1   (a_youtube_meeting_links_to_its_own_video)
    any address with 'granicus' takes a chapter           1   (an_unknown_host_is_returned_unchanged)
    url argument ignored                                  2
    item links ignore the consent rule                    1   (item_links_on_meeting_3184s_shape)
    phrase always says chapter                            2
    phrase never names YouTube                            4
    no entry for a meeting without video                  1   (for_meetings_returns_only_passed_recordings)
    provider not compared                                 0   (cannot be pinned: the table's CHECK admits one provider)
    cue-less consent rows read                            0   (consent_block drops them itself)
    item links not short-cut for a meeting without video  0   (the same result, one query later)

The full list was run after the first two added assertions and before the third; the third was then run against the committed module and against the one removal it was written for (`0 failed` and `1 failed`), not against the other 41.

Not observed in this session, because nothing renders from the module yet and no factory session can reach production: a `VideoLink` on a page (M5 and M6), and a link built from a real measurement (the operator's steps 4 to 6 under Validation and Acceptance).

### M5 as executed, 2026-11-06

Everything in this subsection was observed in the M5 session, in this worktree, on 2026-11-06 (UTC).

The starting state, before any edit. `test -f .env` printed `.env exists` (the file was not read). `./tools/verify`, started at 05:54Z, printed `2243 passed, 5 skipped, 4 xfailed, 2 warnings in 55.35s` for the unit, web, and services tier, `700 passed, 2 warnings in 49.00s` for integration, `judge fixtures: 12 of 12 passed`, `workflows: 2 of 2 ok`, `123 passed, 1 warning in 3.93s` for the transcriber suite, `plans: 2 of 2 ok`, and `verify: all 6 checks passed in 111s.`; the throwaway database was `postgresql://thinkdarrell@/docket_test_7c0790d1`. These are the totals M4 left. The three files of M5's acceptance, each run alone on a throwaway database before the first edit, printed `19 passed` (`tests/web/test_vote_result_block.py`), `11 passed` (`tests/unit/test_query_get_vote_for_item.py`), and `18 passed` (`tests/integration/test_transcript_routes.py`), the counts the plan's sum starts from.

The before state of the new tests, run at 05:58Z with no file under `src/` edited: in `tests/web/test_vote_result_block.py`, `_FakeVote` given the field `video_link`, `test_source_link_prefers_video_timestamp` rewritten, and two functions added; three functions added to `tests/unit/test_query_get_vote_for_item.py`; two added to `tests/integration/test_transcript_routes.py`.

    $ DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/web/test_vote_result_block.py tests/unit/test_query_get_vote_for_item.py tests/integration/test_transcript_routes.py -q -p no:cacheprovider
    E       assert 'Watch this vote on Granicus ↗' in '...Watch this vote ↗...'                  (the rewritten test)
    E       assert 'Watch this vote on YouTube ↗' in '...Watch this vote ↗...'
    E       assert 'Watch this vote' not in '...Watch this vote ↗...'                         (a vote with a timestamp and no video_link)
    E       AttributeError: 'VoteEntry' object has no attribute 'video_link'                  (three times)
    E       ... '...meta_id=77001" target="_blank" rel="noreferrer">video chapter ↗</a>' != ...   (twice: the page still prints "video chapter ↗")
    8 failed, 47 passed, 1 warning in 2.54s
    $ tools/test-db --drop      (exit 0)

The 8 that fail are the rewritten test and the seven this milestone adds; the 47 that pass are the other 18, 11, and 18 that existed. The tests are committed in this state, before `query.py`, `public.py`, or either template is edited, so the before state is readable from git (commit `c388b8a`).

The after state, with `_attach_video_links` and the `video_link` field in `src/docket/services/query.py`, `item_video_links` in `meeting_transcript` (`src/docket/web/public.py`), and the two templates edited. The first run of the three files, at 05:59Z, printed `1 failed, 54 passed`: the failure was the session's own test inserting two OCR votes at one second (Surprises & Discoveries). With that vote moved to 2,401 seconds the run at 06:00Z printed `55 passed, 1 warning in 2.95s`. The acceptance commands in their final form, at 06:04Z:

    $ DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/web/test_vote_result_block.py tests/unit/test_query_get_vote_for_item.py tests/integration/test_transcript_routes.py -q -p no:cacheprovider
    55 passed, 1 warning in 2.91s
    $ (each file alone, same database)
    21 passed, 1 warning in 0.68s        tests/web/test_vote_result_block.py
    14 passed, 1 warning in 0.81s        tests/unit/test_query_get_vote_for_item.py
    20 passed, 1 warning in 2.09s        tests/integration/test_transcript_routes.py
    $ tools/test-db --drop      (exit 0)

`./tools/verify`, started at 06:02Z with every change of the milestone in the working tree and before the plan's tick was written, printed `2248 passed, 5 skipped, 4 xfailed, 2 warnings in 56.27s` for the unit, web, and services tier (2243 plus 5), `702 passed, 2 warnings in 48.72s` for integration (700 plus 2), `judge fixtures: 12 of 12 passed`, `workflows: 2 of 2 ok`, `123 passed, 1 warning in 3.95s` for the transcriber suite, `plans: 2 of 2 ok`, and `verify: all 6 checks passed in 112s.` No file was edited while it ran. After the tick and the living sections were written, `tools/check-plans` (the sixth check, and the only one that reads this file) was run alone at 06:06Z and printed `plans: 2 of 2 ok`; the full command was not run again, since nothing but this file changed after it.

The item page through the real route, at 06:02Z before the full run: a scratch script on the throwaway database (which it printed as `docket_test_7c0790d1`) inserted one Birmingham meeting with clip id 99062026, five agenda items, and three OCR votes, requested each item's page with Flask's test client, inserted a recording `FR84h22hQvA` with a passing measurement (offset 635.48, covering 635.5 to 4,078.7), requested the pages again, and deleted the meeting. Each line is the state, the item, the HTTP status, the link's text, and its `href` as it stands in the HTML:

    no measurement: item 64: HTTP 200: Watch this vote on Granicus ↗ -> https://bhamal.granicus.com/MediaPlayer.php?view_id=2&amp;clip_id=99062026&amp;meta_id=371164
    no measurement: item 2: HTTP 200: Watch this vote on Granicus ↗ -> https://bhamal.granicus.com/MediaPlayer.php?view_id=2&amp;clip_id=99062026&amp;meta_id=371101
    no measurement: item 7: HTTP 200: Watch this vote on Granicus ↗ -> https://bhamal.granicus.com/MediaPlayer.php?view_id=2&amp;clip_id=99062026&amp;meta_id=371101
    passing measurement: item 64: HTTP 200: Watch this vote on YouTube ↗ -> https://www.youtube.com/watch?v=FR84h22hQvA&amp;t=1620s
    passing measurement: item 2: HTTP 200: Watch this vote on YouTube ↗ -> https://www.youtube.com/watch?v=FR84h22hQvA&amp;t=1354s
    passing measurement: item 7: HTTP 200: Watch this vote on YouTube ↗ -> https://www.youtube.com/watch?v=FR84h22hQvA&amp;t=1354s
    removed meeting rows: 1

Item 64 is not a consent item and has its cue point at 2,256 seconds; item 2 is a consent item cued at 2,037 seconds inside the run that starts at 1,990 (chapter 371101); item 7 is a consent item with no cue point and the id `event-2715-7`. The votes' own seconds were 2,400, 2,300, and 2,301, none of which appears in a link.

The removal check (Surprises & Discoveries), at 06:00Z: the 55 tests of the three files, run with one rule taken out in memory, on the throwaway database, which was dropped afterwards. Each line is the rule removed, how many of the 55 failed, and which (names shortened). The first twelve alter `query._attach_video_links`, the next eight a template, the last two what the transcript route hands over:

    as committed                                          0 failed
    timestamp tested by truth, not presence               1   (vote_without_a_video_timestamp_has_no_video_link)
    video_url not required                                0   (cannot be pinned: link_for builds no link without a URL)
    every entry gets a link                               1   (vote_without_a_video_timestamp)
    the vote's own second always                          2   (with_a_passing_measurement, vote_without_a_video_timestamp)
    the item's moment on another meeting too              2   (without_a_measurement, with_a_passing_measurement)
    no fall back to the vote's own second                 1   (with_a_passing_measurement)
    chapter dropped when the vote's second is used        1   (without_a_measurement)
    consent rule not applied                              1   (with_a_passing_measurement)
    no chapter id handed to the builder                   2   (without_a_measurement, with_a_passing_measurement)
    the item's own cue point and id, no item_moment       1   (with_a_passing_measurement)
    recordings not handed to the builder                  2   (with_a_passing_measurement, vote_without_a_video_timestamp)
    consent block not handed to item_moment               1   (with_a_passing_measurement)
    vote link never names its site                        2   (source_link_prefers_video_timestamp, source_link_names_youtube)
    vote link names a site without testing the label      1   (source_link_prefers_video_timestamp)
    vote link always says Granicus                        2   (the same two)
    vote link printed on a timestamp and a video_url      1   (source_link_without_a_video_link_falls_through_to_minutes)
    vote link's address built in the template             2   (source_link_prefers_video_timestamp, source_link_names_youtube)
    transcript link always says video chapter             2   (both transcript tests)
    transcript link only for an item with an external_id  1   (item_link_opens_the_granicus_chapter_when_nothing_is_measured)
    transcript link's address built in the template       1   (item_link_opens_youtube_at_the_converted_second)
    transcript route hands over no links                  2   (both transcript tests)
    transcript route hands over another meeting's links   2   (both transcript tests)

"Chapter dropped when the vote's second is used" is the literal reading of M5's fallback sentence that the Decision Log entry of 2026-11-06 sets aside; the test that fails under it is the item with a chapter id and no cue point.

Not observed in this session, because no factory session can reach production: either link built from a real measurement (the operator's steps 4 to 6 under Validation and Acceptance), and the count of consent votes that fall after their block (the fifth operator query). Not observed either, and read from `link_for` only: the transcript page of a meeting whose own video is on YouTube.

### M6 as executed, 2026-11-06

Everything in this subsection was observed in the M6 session, in this worktree, on 2026-11-06 (UTC).

The starting state, before any edit. `test -f .env` printed `.env exists` (the file was not read). `./tools/verify`, started at 06:09Z, printed `2248 passed, 5 skipped, 4 xfailed, 2 warnings in 55.78s` for the unit, web, and services tier, `702 passed, 2 warnings in 48.70s` for integration, `judge fixtures: 12 of 12 passed`, `workflows: 2 of 2 ok`, `123 passed, 1 warning in 3.95s` for the transcriber suite, `plans: 2 of 2 ok`, and `verify: all 6 checks passed in 111s.`; the throwaway database was `postgresql://thinkdarrell@/docket_test_7c0790d1`. These are the totals M5 left. The four files of M6's acceptance, each run alone on a throwaway database before the first edit, printed `14 passed` (`tests/integration/test_admin_discrepancies.py`), `5 passed` (`tests/integration/test_minutes_vs_video_public.py`), `54 passed, 4 xfailed` (`tests/unit/test_source_anchor.py`), and `11 passed` (`tests/web/test_meeting_recordings.py`), the counts the plan's sum starts from. `git grep -n "chapter_url(" -- src/docket/web` printed two lines, `admin/_discrepancy_row.html:19` and `partials/minutes_vs_video.html:24`.

The before state of the new tests, run at 06:15Z with no file under `src/` edited: one function added to `tests/integration/test_admin_discrepancies.py` with the helpers `_measured_recording`, `_video_link_tags`, and `_queue_row`, and its line-78 comment corrected; one function added to `tests/integration/test_minutes_vs_video_public.py` with the helper `_block_row`; three functions added to `TestVideoBranches` in `tests/unit/test_source_anchor.py`, whose `app` fixture now registers the `video_link` global, whose `_render` takes an optional `video`, and whose test allowlist gains `youtube.com`.

    $ DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_admin_discrepancies.py tests/integration/test_minutes_vs_video_public.py tests/unit/test_source_anchor.py tests/web/test_meeting_recordings.py -q -p no:cacheprovider
    E   '<a href="...MediaPlayer.php?view_id=2&amp;clip_id=1950" target="_blank" rel="noreferrer">video chapter ↗</a>' != '<a href="...clip_id=1950" target="_blank" rel="noreferrer">video on Granicus ↗</a>'      (the admin queue)
    E   '<a class="link" href="...MediaPlayer.php?view_id=2&amp;clip_id=1950" ...>video chapter ↗</a>' != '<a class="link" href="https://www.youtube.com/watch?v=disc-recording&amp;t=3300s" ...>video on YouTube ↗</a>'      (the public block)
    E   assert 'href="https://www.youtube.com/watch?v=abc&amp;t=65s"' in '<a href="https://www.youtube.com/watch?v=abc&amp;t=65" ...View Source: video at 1:05 →'
    E   assert 'href="...MediaPlayer.php?view_id=2&amp;clip_id=2026&amp;meta_id=371120"' in '<a href="...clip_id=2026&amp;t=65" ...View Source: video at ...'
    E   assert 'href="https://www.youtube.com/watch?v=FR84h22hQvA&amp;t=1620s"' in '<a href="...clip_id=2026&amp;t=2256" ...View Source: video at 37:36 →'
    5 failed, 84 passed, 4 xfailed, 1 warning in 3.81s
    $ tools/test-db --drop      (exit 0)

The 5 that fail are the five this milestone adds; the 84 that pass are the 14, 5, 54, and 11 that existed. The tests are committed in this state, before `discrepancies.py`, `src/docket/web/__init__.py`, or any of the three templates is edited, so the before state is readable from git. Each of the two integration tests stopped at its first assertion about a link; the public one had by then installed a second meeting and inserted a recording with its measurement, so those statements ran against the real tables, and the admin one's later statements (an `UPDATE` of the item's id, the same recording helper) had not yet run. The commit is `6e49243`.

The after state, with `_attach_video_links` and the two new columns of `_SELECT` in `src/docket/services/discrepancies.py`, the `video_link` global in place of `chapter_url` in `src/docket/web/__init__.py`, and the three templates edited. The first run of the four files, at 06:16Z, printed `89 passed, 4 xfailed, 1 warning in 4.12s`. Three assertions were then added to the new tests (Surprises & Discoveries). The acceptance commands in their final form, at 06:24Z:

    $ DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_admin_discrepancies.py tests/integration/test_minutes_vs_video_public.py tests/unit/test_source_anchor.py tests/web/test_meeting_recordings.py -q -p no:cacheprovider
    89 passed, 4 xfailed, 1 warning in 4.19s
    $ (each file alone, same database)
    15 passed, 1 warning in 2.03s                tests/integration/test_admin_discrepancies.py
    6 passed, 1 warning in 1.97s                 tests/integration/test_minutes_vs_video_public.py
    57 passed, 4 xfailed, 1 warning in 1.04s     tests/unit/test_source_anchor.py
    11 passed, 1 warning in 1.23s                tests/web/test_meeting_recordings.py
    $ tools/test-db --drop      (exit 0)
    $ git grep -n "chapter_url(" -- src/docket/web
    (no output, exit 1)

`./tools/verify`, started at 06:24Z with every change of the milestone in the working tree and before the plan's tick was written, printed `2251 passed, 5 skipped, 4 xfailed, 2 warnings in 56.34s` for the unit, web, and services tier (2248 plus 3), `704 passed, 2 warnings in 49.82s` for integration (702 plus 2), `judge fixtures: 12 of 12 passed`, `workflows: 2 of 2 ok`, `123 passed, 1 warning in 3.97s` for the transcriber suite, `plans: 2 of 2 ok`, and `verify: all 6 checks passed in 112s.` No file was edited while it ran. After the tick and the living sections were written, `tools/check-plans` (the sixth check, and the only one that reads this file) was run alone at 06:28Z and printed `plans: 2 of 2 ok`; the full command was not run again, since nothing but this file changed after it.

The pages through the real routes. Unlike M5's vote block, both integration tests of this milestone request the pages with Flask's test client from an application built by `create_app`, so no separate scratch run was made: the admin queue (`/admin/review/discrepancies`), the meeting page, the item page, and `/minutes-vs-video/`. The links they compare, as they stand in the HTML, on the pilot meeting (clip URL `clip_id=1950`, installed with `external_id` 999015) and a row at 3,400 seconds:

    nothing measured, item id '1950-15':   <a class="link" href="https://bhamal.granicus.com/MediaPlayer.php?view_id=2&amp;clip_id=1950" target="_blank" rel="noreferrer">video on Granicus ↗</a>
    nothing measured, item id '371115':    <a href="https://bhamal.granicus.com/MediaPlayer.php?view_id=2&amp;clip_id=1950&amp;meta_id=371115" target="_blank" rel="noreferrer">video chapter on Granicus ↗</a>
    passing measurement, offset 100 s:     <a class="link" href="https://www.youtube.com/watch?v=disc-recording&amp;t=3300s" target="_blank" rel="noreferrer">video on YouTube ↗</a>

The public block's links carry `class="link"` and the admin row's do not, as before this milestone.

The removal check (Surprises & Discoveries), at 06:23Z: the 89 tests of the four files, run with one rule taken out in memory, on the throwaway database, which was dropped afterwards. Each line is the rule removed, how many of the 89 failed, and which (QUEUE is the admin queue's new test, BLOCK the public block's, YT, GR, and MEAS the three source-button tests in the order M6 lists them). The first twelve alter `discrepancies._attach_video_links`, the next five which function passes its rows through it, the next six the two discrepancy templates, the next twelve the source button, and the last two what `create_app` registers:

    as committed                                                       0 failed
    every row gets a link, second or not                               1   (QUEUE)
    the item's cue point, not the row's own second                     2   (QUEUE, BLOCK)
    no chapter id handed to the builder                                2   (QUEUE, BLOCK)
    the item's own id, no item_moment                                  1   (BLOCK)
    consent flag not handed to item_moment                             1   (BLOCK)
    cue point not handed to item_moment                                1   (BLOCK)
    consent block not handed to item_moment                            1   (BLOCK)
    recordings not handed to the builder                               2   (QUEUE, BLOCK)
    one meeting's recordings for every row                             1   (BLOCK)
    a row with no item still asks item_moment                          0   (cannot be pinned: the item's columns are NULL for such a row)
    a meeting with no video still gets a link                          1   (QUEUE)
    video_link not set on a row with no second                         1   (QUEUE)
    list_queue not passed through                                      1   (QUEUE)
    list_public_for_meeting not passed through                         1   (BLOCK)
    list_public_for_item not passed through                            1   (BLOCK)
    list_public_recent not passed through                              1   (BLOCK)
    get passed through too                                             1   (QUEUE)
    public block always says video chapter                             1   (BLOCK)
    public block's address is the meeting's video_url                  1   (BLOCK)
    public block's address built in the template (item id as chapter)  1   (BLOCK)
    admin row always says video chapter                                1   (QUEUE)
    admin row's address is the meeting's video_url                     1   (QUEUE)
    admin row's link printed on video_url, not video_link              0   (cannot be pinned: a row with a second has one exactly when it has the other)
    button: YouTube always prints a time                               1   (YT)
    button: YouTube prints the anchor's time                           1   (MEAS)
    button: YouTube prints no time                                     2   (YT, MEAS)
    button: Granicus prints the anchor's time                          2   (GR, MEAS)
    button: Granicus never says chapter                                2   (GR, MEAS)
    button: no chapter id handed over                                  2   (GR, MEAS)
    button: video variable not handed over                             1   (MEAS)
    button: the anchor's URL with its fragment                         1   (GR)
    button: YouTube branch gone (old markup)                           2   (YT, MEAS)
    button: Granicus branch gone (old markup)                          2   (GR, MEAS)
    button: other hosts get the builder's plain link                   5   (the four older tests on video.example.com and granicus.example.com, and test_partial_accepts_static_platform_granicus)
    button: second not handed over                                     2   (YT, MEAS)
    video_link global not registered by create_app                     1   (BLOCK)
    chapter_url global still registered                                1   (BLOCK)

"Button: other hosts get the builder's plain link" is the clause "for any other host the existing markup is kept exactly": the five tests that fail under it are ones that existed before this milestone.

Not observed in this session, because no factory session can reach production: any of the three links built from a real measurement (the operator's steps 4 to 6 under Validation and Acceptance). Not observed either, and read from `link_for` only: a discrepancy row of a meeting whose own video is on YouTube. The source button was rendered as a partial only; no page includes it.

### M7 as executed, 2026-11-06

Everything in this subsection was observed in the M7 session, in this worktree, on 2026-11-06 (UTC).

The starting state, before any edit. `test -f .env` printed `.env exists` (the file was not read). `./tools/verify`, started at 06:31Z, printed `2251 passed, 5 skipped, 4 xfailed, 2 warnings in 56.21s` for the unit, web, and services tier, `704 passed, 2 warnings in 49.44s` for integration, `judge fixtures: 12 of 12 passed`, `123 passed, 1 warning in 4.00s` for the transcriber suite, `plans: 2 of 2 ok`, and `verify: all 6 checks passed in 112s.`; the throwaway database was `postgresql://thinkdarrell@/docket_test_7c0790d1`. These are the totals M6 left. `tests/integration/test_ingest_backfill_timestamps.py`, run alone on a throwaway database before the first edit, printed `7 passed, 1 warning in 0.52s`, the count the plan's sum starts from. On that database `select slug, adapter_class from municipalities` printed five rows, `birmingham|GranicusAdapter` among them (and `test_backfill_ts`, which the file's own fixture leaves behind).

The before state of the new tests, run at 06:38Z with no file under `src/` or `scripts/` edited: five functions added to `tests/integration/test_ingest_backfill_timestamps.py`, four in a new class `TestBackfillWritesChapterIds` and one in `TestCorrectChapterIds`, with the helpers `_point`, `_add_item`, `_add_meeting`, `_set`, `_rows`, and `_messages`.

    $ DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_ingest_backfill_timestamps.py -q -p no:cacheprovider
    E   At index 0 diff: ('1', 'event-2692-1', 10.0) != ('1', '371101', 10.0)      (numeric ids: timestamp and id together)
    E   assert 1 == 3      (an item that has its timestamp: the old pass changed one row, the item that lacked a timestamp)
    E   TypeError: _backfill_video_timestamps() got an unexpected keyword argument 'dry_run'
    E   At index 0 diff: ('1', 'event-2692-1', 10.0) != ('1', '371101', 10.0)      (duplicated number, taken id)
    E   ImportError: cannot import name 'correct_chapter_ids' from 'docket.services.ingest'
    5 failed, 7 passed, 1 warning in 1.39s

The 5 that fail are the five this milestone adds; the 7 that pass are the seven that existed. The tests are committed in this state, before `src/docket/services/ingest.py` is edited or the script exists, so the before state is readable from git. `correct_chapter_ids` is imported inside its test, after the test has inserted its five meetings (one of them under the seeded city `homewood`) and made one call of the existing function, so those statements ran against the real tables in the before state; afterwards `homewood` and `test_backfill_ts` held no meeting.

The after state, with `_backfill_video_timestamps` rewritten and `correct_chapter_ids` added in `src/docket/services/ingest.py`, `scripts/correct_agenda_chapter_ids.py` written, and the sentence added to `scripts/backfill_agenda_timestamps.py`. The first run of the file against the tests as committed, at 06:39Z, printed `12 passed, 1 warning in 1.41s`. The fifth test was then extended (Surprises & Discoveries). The acceptance commands in their final form, at 06:43Z:

    $ DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_ingest_backfill_timestamps.py -q -p no:cacheprovider
    12 passed, 1 warning in 1.49s
    $ tools/test-db --drop
    $ DATABASE_URL=$(tools/test-db) venv/bin/python scripts/correct_agenda_chapter_ids.py --city birmingham --dry-run
    0 meetings, 0 rows      (exit 0)
    $ grep -c "correct_agenda_chapter_ids" scripts/backfill_agenda_timestamps.py
    1      (it printed 0 before the edit, at 06:43Z)

"Makes no network request" was observed, not inferred: the same command was run from a scratch wrapper that makes `requests.Session.request` and every socket connection other than a Unix socket raise and records each attempt (the database on this machine is reached through a Unix socket). It printed `0 meetings, 0 rows`, `exit 0`, and `requests or non-local connects attempted: []`. On the same fresh database the script without `--dry-run` printed `0 meetings, 0 rows` (exit 0), `--city no_such_city` printed `Municipality 'no_such_city' not found` (exit 1), `--limit 0` was refused with `error: --limit must be at least 1` (exit 2), and `--help` printed the usage with `--city`, `--limit`, and `--dry-run`. Then `tools/test-db --drop` (exit 0).

`./tools/verify`, started at 06:43Z with every change of the milestone in the working tree and before the plan's tick was written, printed `2251 passed, 5 skipped, 4 xfailed, 2 warnings in 56.23s` for the unit, web, and services tier (unchanged), `709 passed, 2 warnings in 51.06s` for integration (704 plus 5), `judge fixtures: 12 of 12 passed`, `workflows: 2 of 2 ok`, `123 passed, 1 warning in 4.00s` for the transcriber suite, `plans: 2 of 2 ok`, and `verify: all 6 checks passed in 114s.` No file was edited while it ran: its output was last written at 06:45:41Z, and the four code files of the milestone were last written between 06:39:44Z and 06:43:02Z, before it started. After the tick and the living sections were written, `tools/check-plans` (the sixth check, and the only one that reads this file) was run alone at 06:50Z and printed `plans: 2 of 2 ok`, and the pre-commit hook printed `plans: 1 of 1 ok` on the commit that holds the code, `e71ab0a`; the full command was not run again, since nothing but this file changed after it. No throwaway database was left behind: `select datname from pg_database where datname like 'docket_test_%'` printed nothing at 06:51Z.

The script through the real adapter, at 06:43Z, from a scratch file on the throwaway database (dropped afterwards). One meeting was inserted under `birmingham` with clip id 99062026: 64 numbered items on ids `event-2715-1` to `event-2715-64`, items 1 to 63 consent except item 3, cue points at 1,990 seconds and every 1.5 seconds after for the consent run, 2,145 for item 3, 2,256 for item 64, and none for items 7 to 9. `requests.get` in `docket.adapters.granicus` was replaced by a function that records the URL and returns a page the session wrote: one `Roll Call` point with a `data-id` and no item number, and one `<div class="index-point" time="<seconds>" data-id="<371100 + N>">ITEM N - A resolution</div>` per cued item. Everything else ran as shipped: `main()` of the script, `correct_chapter_ids`, `GranicusAdapter.fetch_agenda_items` (its one-second delay included), the UPDATE, and `video_links.item_links` for the links.

    before: chapter ids 0, other ids 64, un-cued 3
        item  3  event-2715-3   2145.0  ->  video on Granicus: ...MediaPlayer.php?view_id=2&clip_id=99062026
        item  8  event-2715-8   None    ->  video on Granicus: ...clip_id=99062026
        item 20  event-2715-20  2018.5  ->  video on Granicus: ...clip_id=99062026
        item 64  event-2715-64  2256.0  ->  video on Granicus: ...clip_id=99062026
    $ --dry-run
    meeting 1 clip 99062026 2026-10-27: 61 rows would change
    1 meetings, 61 rows
    exit 0 requests ['https://bhamal.granicus.com/MediaPlayer.php?view_id=2&clip_id=99062026']
    after the dry run: chapter ids 0, other ids 64, un-cued 3      (the four items as before)
    $ (the write)
    meeting 1 clip 99062026 2026-10-27: 61 rows changed
    1 meetings, 61 rows
    exit 0 requests 2
    after the write: chapter ids 61, other ids 3, un-cued 3
        item  3  371103         2145.0  ->  video chapter on Granicus: ...clip_id=99062026&meta_id=371103
        item  8  event-2715-8   None    ->  video chapter on Granicus: ...clip_id=99062026&meta_id=371101
        item 20  371120         2018.5  ->  video chapter on Granicus: ...clip_id=99062026&meta_id=371101
        item 64  371164         2256.0  ->  video chapter on Granicus: ...clip_id=99062026&meta_id=371164
    $ (again)
    0 meetings, 0 rows
    exit 0 requests 2

The three ids left are items 7 to 9, which have no point on the page; the meeting is not listed again because those items have no timestamp. Items 8 and 20 are consent items and take the consent block's chapter, which exists only once the block's first item holds a chapter id.

The script on real rows, at 06:50Z, from a second scratch file on the throwaway database (dropped afterwards). The 66 agenda rows of `tests/fixtures/transcript_2543/agenda_items.json` (exported from production on 2026-10-10) were inserted under `birmingham` as clip 2016 with their own ids, numbers, titles, consent flags, and timestamps. The page handed to the real adapter was made from the rows: one point per cued item, in order of its stored second, at that second, titled `ITEM <item number> - <the title's first 30 characters>`, with `data-id` 380000 and up.

    fixture rows: 66 numbered: 65 distinct numbers: 65 repeated numbers: []
    before: {'chapter_ids': 0, 'other_ids': 66, 'uncued_numbered': 0, 'distinct_ids': 66, 'n': 66}
    $ --dry-run
    meeting 1 clip 2016 2026-10-06: 65 rows would change
    1 meetings, 65 rows
    exit 0
    after the dry run: {'chapter_ids': 0, 'other_ids': 66, 'uncued_numbered': 0, 'distinct_ids': 66, 'n': 66}
    $ (the write)
    meeting 1 clip 2016 2026-10-06: 65 rows changed
    1 meetings, 65 rows
    exit 0
    after the write: {'chapter_ids': 65, 'other_ids': 1, 'uncued_numbered': 0, 'distinct_ids': 66, 'n': 66}
        still not a chapter id: {'item_number': None, 'external_id': 'event-2712-minutes-approval', 'video_timestamp_seconds': None}
    timestamps unchanged by the write: True
    $ (again)
    0 meetings, 0 rows
    exit 0

This is the nearest thing to "old against new on real rows" (`docs/PRINCIPLES.md`, Evidence or silence) that a session confined to the worktree can run; the comparison on production itself is the dry run of operator step 3.

The removal check (Surprises & Discoveries), at 06:42Z: the 12 tests of the file, run with one rule taken out in memory, on the throwaway database. Each line is the rule removed, how many of the 12 failed, and which (NUM is the first new test, HAS the second, NOT the third, DUP the fourth, COR the fifth, in the order M7 lists them; "older" names tests that existed before this milestone). The first twenty-two alter `_backfill_video_timestamps`, the next thirteen `correct_chapter_ids`, and the last seven the script:

    as committed                                                       0 failed
    a point's id taken as a chapter id whatever it is                  1   (NOT)
    the last point that names a number speaks for it                   1   (NUM)
    a stored timestamp is replaced                                     1   (HAS)
    no timestamp filled                                                9   (NUM, HAS, NOT, DUP, and five older)
    a stored chapter id is rewritten too                               2   (DUP, COR)
    a missing stored id is left alone                                  2   (HAS, COR)
    no chapter id written at all                                       5   (NUM, HAS, NOT, DUP, COR)
    duplicated item number not guarded                                 1   (DUP)
    an id another row holds not guarded                                1   (DUP)
    an id given in this pass not remembered                            1   (DUP)
    held ids read from numbered rows only                              1   (DUP)
    items taken in item-number order, not point order                  1   (DUP)
    ids left alone logged below WARNING                                1   (DUP)
    unchanged rows written too                                         2   (DUP, COR)
    force ignored (precheck always made)                               2   (DUP, COR)
    precheck never made                                                4   (NUM, COR, and two older)
    precheck counts un-numbered items                                  1   (one older: test_unnumbered_item_does_not_force_a_refetch)
    dry run writes                                                     2   (NOT, COR)
    execute_values left to its page of 100                             1   (NUM)
    the count is the computed one, not the statement's                 0   (cannot be pinned in one process: the two are the same number)
    no INFO line                                                       4   (NUM, HAS, NOT, DUP)
    INFO line does not say dry run                                     1   (NOT)
    correct: any meeting id shape                                      1   (COR)
    correct: any city                                                  1   (COR)
    correct: un-numbered items count                                   1   (COR)
    correct: un-cued items count                                       1   (COR)
    correct: items with a chapter id count                             1   (COR)
    correct: an item with no id does not count                         1   (COR)
    correct: oldest row first                                          1   (COR)
    correct: limit not applied                                         1   (COR)
    correct: precheck not skipped                                      1   (COR)
    correct: dry run not handed on                                     1   (COR)
    correct: one meeting's error ends the pass                         1   (COR)
    correct: an unknown city is an empty list                          1   (COR)
    correct: the meeting's stored video_url not handed to the adapter  1   (COR)
    script: --limit not handed on                                      1   (COR)
    script: --dry-run not handed on                                    1   (COR)
    script: always says changed                                        1   (COR)
    script: a failed meeting printed as 0 rows                         1   (COR)
    script: exit 0 whatever failed                                     1   (COR)
    script: no totals line                                             1   (COR)
    script: an unknown city exits 0                                    1   (COR)

One removal's first run printed no result and is recorded as run again: "ids left alone logged below WARNING" alters two calls, and the scratch plugin's own check that a removal's text occurs once stopped it before any test ran; with the check widened for that removal it printed `1 failed, 11 passed` at 06:42Z.

Not observed in this session, because no factory session can reach production or Granicus: the rewrite against a real player page, and the script against production rows (the operator's step 3). The sixth operator query was parsed on the throwaway database and has not been run where it would count anything.

## Interfaces and Dependencies

No new dependency is installed. The matcher uses numpy, already in `requirements.lock` and in the transcriber image; add the line `numpy>=1.26  # the audio matcher (align.py); already present through torch` to `transcriber/requirements.txt` in M1 so the import is declared. Downloads use ffmpeg and the `yt_dlp` module exactly as `transcriber/transcriber/audio.py` does today.

In `transcriber/transcriber/align.py` (M1):

    ALIGN_METHOD_VERSION = 1

    @dataclass(frozen=True)
    class Measurement:
        status: str                      # 'passed' or 'rejected'
        reason: str | None               # None when passed
        offset_s: float                  # Granicus seconds minus YouTube seconds
        granicus_start_s: float | None   # None when no window was confirmed
        granicus_end_s: float | None
        score: float
        runner_up: float
        windows: int
        windows_confirmed: int

    def read_wav(path) -> np.ndarray                      # ValueError unless 8 kHz, mono, 16-bit
    def features(samples: np.ndarray) -> np.ndarray       # (frames, 4) float32; ValueError under 10 seconds of samples
    def verdict(score, runner_up, windows, confirmed, conflicts) -> tuple[str, str | None]
    def measure(granicus: np.ndarray, youtube: np.ndarray) -> Measurement    # feature arrays
    def measure_files(granicus_wav, youtube_wav) -> Measurement
    def describe(m: Measurement) -> str                   # 'passed offset=635.48s covers=635.5-4078.7s score=23.6 runner_up=6.0 windows=10/12'

(The example line is clip 2026's row of the revised table; as authored it read `covers=635.5-3935.5s` and `windows=9/11`.)

As built in M1, for the sessions that call it. The method's constants are module-level names of `align` (`SR`, `HOP`, `WIN`, `FPS`, `BANDS`, `SMOOTH_S`, `HIGHPASS_S`, `WINDOW_S`, `LOCAL_SEARCH_S`, `AGREE_S`, `RUNNER_EXCLUDE_S`, `PASS_SCORE`, `PASS_MARGIN`, `PASS_WINDOW_SHARE`, `CONFLICT_SCORE`, `MIN_AUDIO_S`, and `ALIGN_METHOD_VERSION`), and `xcorr_z(a, b)` is public beside the functions above. `describe()` prints `rejected (<reason>) offset=...` for a rejected measurement and `covers=none` when no window was confirmed, so M3's log line is `measure meeting <id> clip <clip> video <video id>: ` followed by `describe()`'s text unchanged. `Measurement.offset_s`, `score`, and `runner_up` are always numbers, on a rejected measurement too; `granicus_start_s` and `granicus_end_s` are None exactly when `windows_confirmed` is 0. `Measurement` has no field for the number of conflict windows; a conflict shows only as the reason `conflict`. `read_wav` returns a read-only array of 16-bit samples, which `features` accepts as it is.

In `transcriber/transcriber/db.py` (M2):

    @dataclass(frozen=True)
    class AlignmentCandidate:
        meeting_video_id: int
        video_id: str
        meeting_id: int
        external_id: str          # the Granicus clip id
        meeting_date: date

    def alignment_candidates(conn, *, method_version: int, limit: int, retry_failed_days: int = 7) -> list[AlignmentCandidate]
    def alignment_backlog(conn, *, method_version: int, retry_failed_days: int = 7) -> int
    def save_alignment(conn, cand: AlignmentCandidate, *, method_version: int, status: str,
                       reason: str | None = None, measurement=None) -> None

A candidate is a `meeting_videos` row with `provider = 'youtube'` on a Birmingham meeting that is not hidden, whose `external_id` matches `^[0-9]+$` and whose `video_url` contains `MediaPlayer.php`, and that has no `meeting_video_alignments` row, or a row with `method_version` below the one asked for (a floor, as `ARCHITECTURE.md` requires of version comparisons), or a row whose `granicus_clip_id` differs from the meeting's `external_id`, or a `failed` row measured more than `retry_failed_days` ago. Order: never-measured before stale failures, then `meeting_date DESC`, `meetings.id DESC`, `is_primary DESC`, `meeting_videos.id`. `save_alignment` is `INSERT ... ON CONFLICT (meeting_video_id) DO UPDATE` setting every column and `measured_at = now()`; it does not commit.

As built in M2, for the session that calls them. `alignment_candidates` and `alignment_backlog` only read; like every function in `db.py` they leave the transaction open, so the caller ends it (M3: "read the candidates and end the transaction"). The MediaPlayer test is `strpos(m.video_url, 'MediaPlayer.php') > 0`, which is false for a NULL `video_url`. In the order, a row below the method version asked for and a row against another clip id sort with the recordings that have no row; only a retried failure sorts after them (Decision Log, 2026-11-06). `save_alignment` writes `granicus_clip_id` from `cand.external_id`, takes `status` and `reason` from its arguments and never from the measurement, reads `offset_s`, `granicus_start_s`, `granicus_end_s`, `score`, `runner_up`, `windows`, and `windows_confirmed` from `measurement` by attribute (so M3 passes an `align.Measurement` as it is, with `status=m.status, reason=m.reason`), writes NULL for all seven when `measurement` is None (a `failed` row), and keeps at most 4,000 characters of `reason`. A `passed` status with no measurement, or with a measurement that has no span, is refused by the table's CHECK as `psycopg2.errors.CheckViolation`, which is a `psycopg2.Error` and so falls under M3's database-error handling; `align.verdict` cannot return `passed` with no confirmed window, since zero confirmed windows fail the window share. The role may not DELETE from `meeting_video_alignments`, so nothing in the producer may rely on removing a row.

In `transcriber/transcriber/measure.py` (M3):

    MEASURE_PAUSE_S = 3.0
    MEASURE_MAX_CONSECUTIVE_FAILURES = 3
    MEASURE_YTDLP_FORMAT = "worstaudio/bestaudio/worst"
    MEASURE_RATE = 8000

    def measure_pass(conn, cfg, *, limit: int, stop=None, deadline: float | None = None,
                     clock=time.monotonic, sleep=time.sleep) -> dict    # {'passed': n, 'rejected': n, 'failed': n}

`MEASURE_MAX_CONSECUTIVE_FAILURES` counts failed fetches in a row (one per meeting for the Granicus side, one per recording for the YouTube side), not `failed` rows; M3 says how. In `transcriber/transcriber/audio.py` (M3), added at the revision of 2026-11-05:

    YTDLP_SOCKET_TIMEOUT_S = 30      # ytdlp_options returns it as "socket_timeout" for every download

As built in M3, for the session that writes the spec (M8) and for anyone who reads the log. `measure_pass` reads only `cfg.work_dir` and `cfg.archive_dir`; it raises nothing but `KeyboardInterrupt` and its kind, and returns the counts so far whatever it met. Its work files are `<work_dir>/align-<meeting id>.wav` (the clip), `<work_dir>/align-yt-<video id>.wav` (a recording), and yt-dlp's `<work_dir>/yt-<video id>.<ext>`; none outlives its recording, or its meeting for the first. The logger is `transcriber.measure`. Its lines, exactly: `measure meeting <id> clip <clip id> video <video id>: ` followed by `align.describe()`'s text (INFO), or by `failed (<Class>: <message>)` (WARNING; one line, at most 300 characters of the error); `measure: 3 fetches failed in a row; stopping` (WARNING); `measure: stop requested; stopping` and `measure: max-hours reached; stopping` (INFO); `measure: skipped (<error>)` (WARNING; the database's own message for a `psycopg2.Error`, `<Class>: <message>` otherwise); and `measure done {'passed': p, 'rejected': r, 'failed': f} remaining=<n>` (INFO; whenever the pass reaches its end, not after a `skipped`). A `failed` row's `reason` is `<Class>: <message>` in full. In `audio.py`: `fetch_audio(source, out_wav, *, attempts=3, delay_s=5.0, timeout_s=3600, rate=16000, runner=subprocess.run)`, `ytdlp_options(external_id, work_dir, *, audio_format="bestaudio/best")`, and `source_for(external_id, work_dir, *, audio_format="bestaudio/best")`. In `cli.py`: `Config.measure_limit: int = 20`, the flag `--measure-limit` with its default from `TRANSCRIBER_MEASURE_LIMIT`, and `run_loop(conn, engine, cfg, *, clock=time.monotonic, stop_flag=None, started=None)`. `transcriber.__version__` is `"0.5.0"`.

In `src/docket/services/video_links.py` (M4):

    MIN_METHOD_VERSION = 1        # the lowest method version the site trusts
    CONSENT_GAP_S = 120.0
    CONSENT_MIN_ITEMS = 3

    @dataclass(frozen=True)
    class Recording:      video_id: str; offset_s: float; start_s: float; end_s: float
    @dataclass(frozen=True)
    class ConsentBlock:   start_s: float; end_s: float; chapter_id: str | None
    @dataclass(frozen=True)
    class MeetingVideo:   video_url: str | None; recordings: tuple[Recording, ...] = (); consent: ConsentBlock | None = None
    @dataclass(frozen=True)
    class VideoLink:
        url: str
        site: str                 # 'youtube', 'granicus', or 'other'
        label: str | None         # 'YouTube', 'Granicus', or None
        seconds: int | None       # the second the link opens at on YouTube; None otherwise
        timed: bool               # True when the link lands on a second or a chapter
        @property
        def phrase(self) -> str   # 'video on YouTube', 'video chapter on Granicus', 'video on Granicus', 'video'

    def chapter_url(video_url: str | None, meta_id: object) -> str | None       # moved unchanged
    def youtube_id(url: str | None) -> str | None                               # from watch?v=<id> or youtu.be/<id>
    def consent_block(cues: Iterable[tuple[float, str | None]]) -> ConsentBlock | None   # (cue seconds, external_id) of consent items
    def item_moment(video: MeetingVideo | None, *, is_consent, cue_s, external_id) -> tuple[float | None, str | None]
    def link_for(video: MeetingVideo | None, *, seconds=None, chapter_id=None, url: str | None = None) -> VideoLink | None
    def for_meetings(meeting_ids: Iterable[int]) -> dict[int, MeetingVideo]
    def for_meeting(meeting_id: int) -> MeetingVideo | None
    def item_links(meeting_id: int) -> dict[int, VideoLink]                     # agenda item id -> its link

`link_for` takes its base URL from `video.video_url`, or from `url` when `video` is None (the source button). A value of `seconds` that cannot be read as a number is treated as absent. With no base URL it returns None. When `youtube_id(base)` reads a video id it returns `https://www.youtube.com/watch?v=<id>&t=<floor>s`, or `https://www.youtube.com/watch?v=<id>` when there is no second, built from the id and never by appending to the stored URL (revised 2026-11-05; the authored sentence said "returns that video at `&t=<floor>s`", which left open appending to a `youtu.be` URL or to one that already carries `t=`); a URL on a YouTube host with no readable video id falls under "any other host" below. When the base contains `MediaPlayer.php`: if there is a second and a recording with `start_s <= seconds < end_s` whose converted second is not negative, the first such recording in order gives `https://www.youtube.com/watch?v=<id>&t=<n>s`; otherwise the result is `chapter_url(base, chapter_id)` with `timed` true exactly when the chapter id was applied. Any other host returns the URL unchanged with site `other`, no label, and `timed` false. `for_meetings` runs three queries through `docket.db.db_cursor`: the meetings' `video_url` and `external_id`; the recordings joined to `meeting_video_alignments` where `status = 'passed'`, `method_version >= MIN_METHOD_VERSION`, and `granicus_clip_id = meetings.external_id`, ordered `is_primary DESC, meeting_videos.id`; and the consent items' cue points (`is_consent AND video_timestamp_seconds IS NOT NULL`, ordered by cue point then id; not by `item_number`, which is text). No query replaces a NULL with a default (`docs/PRINCIPLES.md`, Source or silence). `consent_block` sets `ConsentBlock.chapter_id` to the `external_id` of the first cue point in the winning run whose id is all digits, and to the run's first cue point's id when none is (revised 2026-11-05; as authored it was always the first cue point's id).

As built in M4, for the sessions that call it (M5 and M6). The module imports `docket.db` and the standard library only, and writes nothing. `VideoLink.seconds` is an `int` on a YouTube link that opens at a second, 0 included, and `None` on every other link, so a template tests `link.seconds is not none`; `label` is `None` only when `site` is `other`; `url` is always a string, since `link_for` returns `None` instead of a link when there is no base URL. `link_for(None)` with no `url` is `None`. When `video` is given its `video_url` is the base and the `url` argument is not read. A second that is `None`, a boolean, unreadable, or not finite is absent, and a second handed over as text (`"2256"`) is read. On a meeting whose own video is on YouTube the recordings, the chapter id, and a negative second are all ignored. `item_moment(video, is_consent=..., cue_s=..., external_id=...)` accepts `video=None` (no block) and returns `(None, None)` only for a consent item with no cue point where there is no block; a non-consent item with no cue point returns `(None, external_id)`, which `link_for` turns into the Granicus chapter link when the id is all digits and the plain player link otherwise. The block's bounds are both inside it (`start_s <= cue_s <= end_s`). `for_meetings(ids)` takes any iterable of meeting ids, returns `{}` for none without a query, and has an entry for every id that names a meeting, also a meeting with no `video_url`; an id that names no meeting has no entry, so `for_meeting` returns `None` for it. `Recording.offset_s`, `start_s`, and `end_s` are the stored `offset_s`, `granicus_start_s`, and `granicus_end_s`, which the table's CHECK keeps non-null on a `passed` row. `item_links(meeting_id)` returns a link for every agenda item of a meeting that has a `video_url`, timed or not, and `{}` for a meeting with no `video_url` or no such meeting; M5's template therefore prints "video on Granicus ↗" for an item with no usable chapter id, where the page today prints "video chapter ↗" on the same plain URL, and prints a link for an item whose `external_id` is NULL, where today it prints none. `youtube_id` reads `watch?v=<id>` on `youtube.com`, `www.`, `m.`, and `music.youtube.com` and `<id>` on `youtu.be`, over `http` or `https`, for ids of letters, digits, `_`, and `-`. The private names `_is_chapter_id`, `_watch_url`, and `_number` are not part of the interface. In tests, a `MeetingVideo` is built directly (`MeetingVideo(video_url=..., recordings=(Recording(...),), consent=ConsentBlock(...))`), and `tests/integration/test_video_link_loader.py` has a `_Seed` helper that inserts a meeting, a recording, a measurement, and an item, which M5's and M6's integration tests can copy the statements of.

As built in M5, for the session that moves the remaining templates (M6) and the one that writes the spec (M8). `query.VoteEntry.video_link` is a `video_links.VideoLink` or `None`, the dataclass's last field and its only default; `query._attach_video_links(item_id, entries)` sets it and is called only by `get_vote_for_item`. It is set exactly on a vote whose `video_timestamp` is not NULL (0 included) and whose meeting has a `video_url`; such a vote always gets a link, since `link_for` returns one whenever there is a base URL. The rule, in order: a vote on the item's own meeting takes `item_moment`'s second and chapter id; when that second is `None` it takes the vote's own `video_timestamp` and keeps the chapter id `item_moment` returned; a vote on another meeting takes its own `video_timestamp`, no chapter, and that meeting's recordings. `partials/_vote_result_block.html`'s macro is `vote_source_link(v)`; it prints the video link when `v.video_link` is set, with `v.video_link.url` and, when `v.video_link.label` is set, " on <label>", and it no longer reads `v.video_timestamp`, `v.video_url`, or `item.external_id`. The transcript's template variable is `item_video_links`, the dictionary `video_links.item_links(meeting_id)` returns (agenda item id to `VideoLink`), passed by `meeting_transcript` to both the full page and the HTMX partial; `partials/transcript_body.html` calls `.get` on it for every turn that starts an item, so (read from the template, not observed) a new caller of that partial must pass it. The `chapter_url` Jinja global is still registered and is called by `admin/_discrepancy_row.html` and `partials/minutes_vs_video.html` only. For M6's tests: `tests/unit/test_query_get_vote_for_item.py` has `_insert_clip_meeting`, `_insert_cued_item`, `_insert_ocr_vote`, and `_insert_recording` (a `meeting_videos` row with its measurement), and `tests/integration/test_transcript_routes.py` inserts a recording and a passing measurement for its fixture meeting in two statements; two OCR votes of one meeting cannot share a `video_timestamp` (`idx_votes_ocr_unique`).

As built in M6, for the session that writes the spec (M8). Every row returned by `discrepancies.list_queue`, `list_public_for_meeting`, `list_public_for_item`, and `list_public_recent` has the key `video_link`: a `video_links.VideoLink`, or `None` when the row has no `transcript_start_s` or its meeting has no `video_url`. `discrepancies.get` returns no such key; its row does carry the two columns `_SELECT` gained, `item_is_consent` and `item_cue_s`, which are NULL for a row with no item. `discrepancies._attach_video_links(rows)` builds each link from the row's own `transcript_start_s`, the recordings of the row's own meeting (`video_links.for_meetings` over the distinct meetings of the rows that have a second), and the chapter id `video_links.item_moment` returns for the row's item, or no chapter for a row with no item. The two templates print ` · <a href="{{ row.video_link.url }}" ...>{{ row.video_link.phrase }} ↗</a>` when the link is set (the public template's variable is `d`) and no longer read `video_url` or `item_external_id`. The Jinja globals: `chapter_url` is gone, and `video_link` is `video_links.link_for` itself, called by `partials/source_anchor_button.html` and by no other template; `video_links.chapter_url` is still a function of the module, called by `link_for`. A test application that renders the source button's video branch must register `video_link`, as the `app` fixture of `tests/unit/test_source_anchor.py` does; an application without it renders every other branch as before, since Jinja looks the name up only when the branch runs. The source button's video branch, for a safe anchor of type `video` with a truthy `timestamp_seconds`: it calls `video_link(video|default(none), seconds=anchor.timestamp_seconds, chapter_id=item.external_id|default(none), url=<the anchor's URL without its fragment>)`; site `youtube` prints "View Source: video on YouTube at <format_timestamp of the link's own second> →", or with no " at ..." when the link carries no second; site `granicus` prints "View Source: video chapter on Granicus →" or "View Source: video on Granicus →" with no time and no `t=`; anything else, and no link at all, prints the old `?t=<N>` link and "View Source: video at <time> →". `video` is an optional template variable holding a `video_links.MeetingVideo`; when it is given, the link is built from its `video_url` and not from the anchor's. For M7's and later tests: `tests/integration/test_admin_discrepancies.py` has `_measured_recording(meeting_id, clip_id, *, video_id, offset_s, start_s, end_s)` (a `meeting_videos` row with a passing measurement) and `_video_link_tags(html)`.

In `src/docket/services/ingest.py` (M7): `_backfill_video_timestamps(adapter, meeting_id, raw_meeting, *, force=False, dry_run=False) -> int` and `correct_chapter_ids(slug, *, limit=50, dry_run=False) -> list[dict]`.

As built in M7, for the session that writes the spec (M8) and for the operator. `_backfill_video_timestamps` makes its precheck unless `force` is true (a count of the meeting's numbered items with no timestamp; zero returns 0 with no request), calls `adapter.fetch_agenda_items(raw_meeting)` once, and returns 0 when no point's title names an "ITEM N". Otherwise, in one transaction, it reads every row of the meeting and builds one tuple `(id, timestamp, external_id)` for each numbered row that changes: the timestamp is the stored one, or the point's when the stored one is NULL; the id is the stored one, or the point's when the stored one is NULL or not all digits (`_CHAPTER_ID_PATTERN`, `^[0-9]+$`), the point's is all digits, one row carries that item number, and no row of the meeting holds that id or was given it earlier in the pass. It writes them in one `UPDATE agenda_items AS a SET video_timestamp_seconds = v.ts, external_id = v.ext FROM (VALUES ...) AS v(id, ts, ext) WHERE a.id = v.id` and returns that statement's row count; under `dry_run` it writes nothing and returns the number of tuples. The logger is `docket.services.ingest`; the INFO and WARNING texts are in the Decision Log. `correct_chapter_ids` raises `ValueError` for an unknown slug, builds the city's adapter with `get_adapter` (which a test replaces on `docket.services.ingest`), and returns a list, newest meeting first, of `{"meeting_id", "external_id", "meeting_date", "changed", "error"}`; `error` is `None` or `<Class>: <message>` for a meeting whose pass raised, and that meeting's `changed` is 0. It visits a meeting when the meeting's `external_id` is all digits and it has an item with `item_number IS NOT NULL`, `video_timestamp_seconds IS NOT NULL`, and an `external_id` that is NULL or not all digits. `scripts/correct_agenda_chapter_ids.py` has `main(argv=None) -> int`; it prints `meeting <id> clip <external id> <date>: <n> rows changed`, or `<n> rows would change` under `--dry-run`, or `failed (<error>)`, one line per meeting, and then `<m> meetings, <n> rows`; it exits 1 for an unknown city or any failed meeting and 2 for `--limit` below 1. For M8's tests, if it needs any: `tests/integration/test_ingest_backfill_timestamps.py` has `_point(item_num, timestamp, external_id)`, `_add_meeting(muni_id, external_id, meeting_date, items)`, `_add_item`, `_set`, and `_rows(meeting_id)`.

## Revision notes

2026-11-05, authored. The plan was written from the operator's goal of 2026-11-05 and a scope brief prepared for it; the brief's findings are folded into Purpose and Context above rather than committed as a file, and its questions were already answered by the operator (measuring rides on the existing transcriber run with no new command; until a meeting is measured its links stay on Granicus; nothing is re-transcribed; a consent item links to the start of the consent agenda and a removed item to when it is talked about). The following are deliberately left out of this plan. Making every transcript line's timestamp a video link. Transcribing or ingesting anything from the attached YouTube recordings, and re-transcribing any meeting. Cities other than Birmingham. Including `partials/source_anchor_button.html` in a page, or writing `agenda_items.source_anchor`: the branch is changed and proved by rendering the partial. Issues #62 and #63 (orphan `event-*` meeting rows, an upgrade counter in `IngestResult`). Issue #88 (wrong stored start times) and decision `0068`'s pairing: which recording is attached to which meeting is taken as it is, and a wrongly attached one is simply rejected by the matcher. `D84` and `D85` on pull request #139, `D76`, `D77`, and issue #107. Seeking the Granicus player to an arbitrary second, which it does not support. Committing the spike's audio; tests use synthetic audio. Fixing the per-run player-page fetch for meetings with an un-cued numbered item, which M8 records as debt. The operator's steps (the production GRANT, the deploy, the image rebuild, the measuring runs, the correction run, and the read-only checks) are listed under Validation and Acceptance and are no milestone's acceptance. One default of the brief was changed, with its reason in the Decision Log: a `failed` measurement is retried after 7 days instead of waiting for a method version bump.

2026-11-05, revised after an external review, before any milestone ran. The operator had a reviewer read the authored plan and brought the review to the session that had run the spike. Each point was checked there against the spike's audio and, read-only, against production, and the operator accepted the changes that held up; the reasons and the figures are in the Decision Log entries dated to the review and in "Observed at the review, 2026-11-05". What changed, and where. The matcher: one more window at the end of the overlap, an agreement tolerance of 2 seconds instead of 1, and a refusal of audio shorter than 10 seconds (M1, the reference implementation, the revised table, Interfaces). The measuring pass: failures are counted per failed fetch and not per `failed` row, any unexpected error on one recording is a `failed` row, anything that escapes ends the pass and not the run, and yt-dlp downloads get a 30-second socket timeout (M3, Interfaces). The link builder: a YouTube link is always built from the video id, and the consent block's chapter id is the run's first all-digit id (M4, Interfaces). The source button prints no time on Granicus (M6). The chapter-id rewrite gains one tested case and the old timestamp script a pointer (M7). The debt and the known limits name the end-of-recording cut, the stale offset of a re-trimmed clip, the 2-second tolerance, short recordings, and the consent vote case (Context, M8). The operator's checks gain a fifth query and a count of rejections by reason (Validation and Acceptance, Artifacts and Notes). Not taken, with reasons in the Decision Log: a shorter window for short recordings, coverage in pieces, a rollback helper for the migration tests, fewer queries per page, a different download format, ordering consent cue points by item number, and, by the operator's choice, a special rule for a consent item's later vote.

The clauses re-read against the changed rules. Every window count and coverage figure in M1's synthetic cases was computed again with the revised arithmetic, and each case that tells the revised rule from the authored one states what the authored rule returns; the cut case was rebuilt because the authored one landed on exactly 60 percent of its windows. The pass-mark table was run again on the same 72 pairs and both tables are kept. Test totals were carried forward: the transcriber suite is 105 after M1, 110 after M2, and 123 after M3 (as authored 102, 107, 118); the unit, web, and services tier is 2243 after M4, 2248 after M5, and 2251 after M6 (as authored 2241, 2246, 2249); the integration totals and the per-file counts of M2, M5, M6, and M7 are unchanged, M3's file count is 41 (was 39), and M4's is 28 (was 26). M4's link tests use a recording "covering 635.5 to 3,935.5", the authored coverage of clip 2026; it is a value handed to the link builder, not a measurement, and the moments those tests use (1,990, 2,145, and 2,256 seconds) lie inside both the authored and the revised coverage, so they stand. No Progress entry was reworded.

2026-11-06, a change to the operator's steps made by the M7 session. Operator step 3 under Validation and Acceptance gained three sentences and "The operator's read-only queries" a sixth query, because the session read from the code that the correction script also lists meetings whose non-chapter ids did not come from an agenda PDF, a shape the plan had not considered (the first M7 entry of Surprises & Discoveries). No milestone's acceptance, no Progress entry, and no rule of the code was changed by it; M8, which writes row `D94` from those steps, should carry the added check into it.
