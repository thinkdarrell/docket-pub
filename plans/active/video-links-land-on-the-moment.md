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

M1 and M2 were executed on 2026-11-06 and their evidence is in "M1 as executed, 2026-11-06" and "M2 as executed, 2026-11-06" under Artifacts and Notes; M3 is next, and nothing from M3 on has been executed. A completed entry is written as `- [x] (YYYY-MM-DD HH:MMZ) <text>` with the time the work was observed, never an estimate, and an entry's text is never reworded once written (decision `0037`; the judge in `docs/capabilities/judge-milestone.md` identifies entries by their text).

- [x] (2026-11-06 05:01Z) M1: `transcriber/transcriber/align.py` measures where one recording sits on another's clock from two 8 kHz WAV files with numpy alone, and `transcriber/tests/test_align.py` proves it on synthetic audio: a shifted noisy copy recovers its offset and passes, unrelated audio and a recording with a cut are rejected, and the verdict rule reproduces the labelled table in Artifacts and Notes.
- [x] (2026-11-06 05:17Z) M2: migration 042 creates `meeting_video_alignments`, the `transcriber` role file grants the role SELECT on `meeting_videos` and SELECT, INSERT, UPDATE on the new table, and `transcriber/transcriber/db.py` lists the recordings that need measuring and saves a measurement, proved against the throwaway database.
- [ ] M3: an ordinary transcriber run measures up to `--measure-limit` attached YouTube recordings before the engine loads, with one stored row and one log line per recording, leaves no audio in the work folder, and carries on to transcription whatever the measuring pass meets; `transcriber/tests/test_measure.py` proves it with stubbed fetches.
- [ ] M4: `src/docket/services/video_links.py` builds a video link from a second on the Granicus clock (YouTube at the converted second when a passing recording covers it, the Granicus chapter otherwise), finds a meeting's consent block, and loads a meeting's passing recordings; `src/docket/web/video_urls.py` is gone and its tests moved.
- [ ] M5: the item page's vote link and the transcript page's item link come from the link builder, land on the item's moment under the consent rule, and name the site they open.
- [ ] M6: the minutes-versus-video block, the admin discrepancy row, and the video branch of `partials/source_anchor_button.html` come from the link builder and name the site they open; the `chapter_url` Jinja global is gone.
- [ ] M7: `_backfill_video_timestamps` writes the cue point's Granicus chapter id together with the timestamp in one statement per meeting, and `scripts/correct_agenda_chapter_ids.py` lists and corrects the meetings whose cued items still carry another id, with a dry run.
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

## Outcomes & Retrospective

This section is filled in as milestones complete. The closing retrospective is written by the retro stage after the last milestone, not by a milestone session.

M1, 2026-11-06. The matcher exists: `transcriber/transcriber/align.py`, the standard library and numpy only, written from the revised reference arithmetic, with the interface under Interfaces and Dependencies and nothing calling it yet. Its acceptance was met as stated: the ten tests of `transcriber/tests/test_align.py` failed with `ModuleNotFoundError: No module named 'transcriber.align'` before the module existed (committed in that state) and print `10 passed` after, in under 3 seconds; `./tools/verify` printed `verify: all 6 checks passed` with the transcriber suite at `105 passed` and the other tiers at their baseline. `transcriber/requirements.txt` declares numpy. One thing M1 asked for beyond its acceptance was not done: the rerun on the spike's real audio (Surprises & Discoveries, Decision Log). So the claim that the committed module reproduces the revised table on real recordings rests on its following the reference line for line and reproducing the plan's synthetic figures, not on an observation of this session. Lesson for the sessions after this one: because the plan states, case by case, what the revised rule and the authored rule each return, the session could take each revised rule out of a copy of the module and watch the test named for it fail, which is the check that stood in for the audio. M2 is next.

M2, 2026-11-06. The database has a place for measurements and the producer can reach it: migration `042_meeting_video_alignments` (one row per attached recording, two CHECK constraints, cascade from the recording), the role file's two grants (SELECT on `meeting_videos`; SELECT, INSERT, UPDATE and no DELETE on the new table), and `AlignmentCandidate`, `alignment_candidates`, `alignment_backlog`, and `save_alignment` in `transcriber/transcriber/db.py`. Nothing calls the three functions yet; M3's measuring pass will. Acceptance, clause by clause: the ten new tests failed before the code existed (committed in that state, `a5f4ab3`) and pass after; the build of the throwaway database prints `Applying migration 42: docket.migrations.042_meeting_video_alignments`; `transcriber/tests/test_db.py` prints `26 passed`; `./tools/verify` prints `verify: all 6 checks passed` with integration at `695 passed` and the transcriber suite at `110 passed`. One clause is met in a different number than written: the four-file command prints `19 passed` where the plan says `13 passed`, because the plan undercounted the tests the two older migration files already held (Surprises & Discoveries, Decision Log); the tests added are the 3, 2, and 5 the plan names. `ARCHITECTURE.md` and `docs/runbooks/transcripts.md` list the role's wider reach, and both the role file and the runbook say that the production role, created before this migration, has neither grant until the operator runs the two statements (step 2 under Validation and Acceptance). Lesson for the sessions after this one: count a file's tests by running it before the first edit, not by reading its top-level functions, and when a plan lists rules a query must keep, take each rule out of a copy in memory and watch for the test that fails; two of eight had none on the first try. M3 is next.

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
3. Same window, with `DATABASE_URL` set to the production public URL: `venv/bin/python scripts/correct_agenda_chapter_ids.py --city birmingham --dry-run`; keep the output; then the same without `--dry-run`; then the second query in Artifacts and Notes, which prints 0 items, or a residue that the script's WARNING lines explain. It requests one Granicus player page per listed meeting, a second or more apart.
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

In `src/docket/services/ingest.py` (M7): `_backfill_video_timestamps(adapter, meeting_id, raw_meeting, *, force=False, dry_run=False) -> int` and `correct_chapter_ids(slug, *, limit=50, dry_run=False) -> list[dict]`.

## Revision notes

2026-11-05, authored. The plan was written from the operator's goal of 2026-11-05 and a scope brief prepared for it; the brief's findings are folded into Purpose and Context above rather than committed as a file, and its questions were already answered by the operator (measuring rides on the existing transcriber run with no new command; until a meeting is measured its links stay on Granicus; nothing is re-transcribed; a consent item links to the start of the consent agenda and a removed item to when it is talked about). The following are deliberately left out of this plan. Making every transcript line's timestamp a video link. Transcribing or ingesting anything from the attached YouTube recordings, and re-transcribing any meeting. Cities other than Birmingham. Including `partials/source_anchor_button.html` in a page, or writing `agenda_items.source_anchor`: the branch is changed and proved by rendering the partial. Issues #62 and #63 (orphan `event-*` meeting rows, an upgrade counter in `IngestResult`). Issue #88 (wrong stored start times) and decision `0068`'s pairing: which recording is attached to which meeting is taken as it is, and a wrongly attached one is simply rejected by the matcher. `D84` and `D85` on pull request #139, `D76`, `D77`, and issue #107. Seeking the Granicus player to an arbitrary second, which it does not support. Committing the spike's audio; tests use synthetic audio. Fixing the per-run player-page fetch for meetings with an un-cued numbered item, which M8 records as debt. The operator's steps (the production GRANT, the deploy, the image rebuild, the measuring runs, the correction run, and the read-only checks) are listed under Validation and Acceptance and are no milestone's acceptance. One default of the brief was changed, with its reason in the Decision Log: a `failed` measurement is retried after 7 days instead of waiting for a method version bump.

2026-11-05, revised after an external review, before any milestone ran. The operator had a reviewer read the authored plan and brought the review to the session that had run the spike. Each point was checked there against the spike's audio and, read-only, against production, and the operator accepted the changes that held up; the reasons and the figures are in the Decision Log entries dated to the review and in "Observed at the review, 2026-11-05". What changed, and where. The matcher: one more window at the end of the overlap, an agreement tolerance of 2 seconds instead of 1, and a refusal of audio shorter than 10 seconds (M1, the reference implementation, the revised table, Interfaces). The measuring pass: failures are counted per failed fetch and not per `failed` row, any unexpected error on one recording is a `failed` row, anything that escapes ends the pass and not the run, and yt-dlp downloads get a 30-second socket timeout (M3, Interfaces). The link builder: a YouTube link is always built from the video id, and the consent block's chapter id is the run's first all-digit id (M4, Interfaces). The source button prints no time on Granicus (M6). The chapter-id rewrite gains one tested case and the old timestamp script a pointer (M7). The debt and the known limits name the end-of-recording cut, the stale offset of a re-trimmed clip, the 2-second tolerance, short recordings, and the consent vote case (Context, M8). The operator's checks gain a fifth query and a count of rejections by reason (Validation and Acceptance, Artifacts and Notes). Not taken, with reasons in the Decision Log: a shorter window for short recordings, coverage in pieces, a rollback helper for the migration tests, fewer queries per page, a different download format, ordering consent cue points by item number, and, by the operator's choice, a special rule for a consent item's later vote.

The clauses re-read against the changed rules. Every window count and coverage figure in M1's synthetic cases was computed again with the revised arithmetic, and each case that tells the revised rule from the authored one states what the authored rule returns; the cut case was rebuilt because the authored one landed on exactly 60 percent of its windows. The pass-mark table was run again on the same 72 pairs and both tables are kept. Test totals were carried forward: the transcriber suite is 105 after M1, 110 after M2, and 123 after M3 (as authored 102, 107, 118); the unit, web, and services tier is 2243 after M4, 2248 after M5, and 2251 after M6 (as authored 2241, 2246, 2249); the integration totals and the per-file counts of M2, M5, M6, and M7 are unchanged, M3's file count is 41 (was 39), and M4's is 28 (was 26). M4's link tests use a recording "covering 635.5 to 3,935.5", the authored coverage of clip 2026; it is a value handed to the link builder, not a measurement, and the moments those tests use (1,990, 2,145, and 2,256 seconds) lie inside both the authored and the revised coverage, so they stand. No Progress entry was reworded.
