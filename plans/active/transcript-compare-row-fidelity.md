# Keep human-approved discrepancy rows through unchanged-minutes re-compares, remap model-assigned `vote_outcome`, and fix the vote-result vocabulary

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `plans/PLANS.md`.

## Purpose / Big Picture

docket.pub transcribes Birmingham City Council video and compares what was said against the official minutes. The comparison stage writes its findings as rows in the `minutes_discrepancies` table; an admin approves or rejects each row in a review queue, and only approved rows ever reach the public meeting page. Three defects in that stage, all found during the 2026-10-11 smoke test on Birmingham meeting 2364 and filed as GitHub issues #112, #114, and #116, make the stage either lose a human decision or mislabel a finding. This plan closes all three in one small pull request.

After the work, three things are true that are not true today. First, a re-comparison whose minutes have not changed (the kind a prompt-version bump or a manual rerun causes) leaves every row a human approved exactly as it was: still `approved`, still carrying the reviewer's name and time, still on the public page. Today the same rerun silently sets the approved row to `stale` whenever the model's second opinion differs from its first, and the row vanishes from the public page with nothing in the queue saying why. Second, a row whose category the model chose as `vote_outcome` is written as `wording`, because `vote_outcome` is reserved for the deterministic tally check that code performs with no model involved; today a model-initiated row can land in that category at `minor` severity, a shape the deterministic path never produces. Third, the vote-result vocabulary reads "carried over" and "carried forward" as no outcome instead of as a pass, and reads "motion to deny approved", "motion to deny carried", and "the council approves the denial" as a fail; today the first two read as a pass and the third reads as no outcome, which hides real outcome disagreements and manufactures false material ones.

How to see it working: `venv/bin/python -c "from docket.ai.transcripts.aligner import canonical_result as c, _results_differ as d; print(c('carried over'), c('carried forward'), c('motion to deny approved'), c('motion to deny carried'), c('the council approves the denial'), d('carried over','adopted'), d('motion to deny approved','denied'))"` prints `None None fail fail fail False False` after the work; on this checkout today it prints `pass pass pass pass None False True` (observed while authoring, 2026-10-11). The other two changes are visible through the integration tests this plan adds and through `./tools/verify`, which runs them.

## Progress

- [x] (2026-10-12 04:06Z) M1: `canonical_result` in `src/docket/ai/transcripts/aligner.py` reads continued-item words as no outcome and the deny, reject, and defeat stems as fail, and `build_rows` in `src/docket/ai/transcripts/compare.py` writes a model-assigned `vote_outcome` category as `wording`; the new cases in `tests/unit/test_aligner.py` and `tests/unit/test_compare_render.py` were observed red before each source edit and green after.
- [x] (2026-10-12 04:20Z) M2: `reconcile()` in `src/docket/ai/transcripts/compare.py` keeps approved rows through a pass whose claim does not carry `compare_skipped_reason = 'minutes_changed'`, `reset_for_versions()` in `src/docket/ai/transcripts/pipeline.py` no longer counts approved rows, `scripts/transcript_recompare.py` takes `--minutes-changed`, and the runbook and the script docstring state the policy; the new cases in `tests/integration/test_recompare.py` were observed red before the source edits and green after.
- [ ] M3: `docs/specs/transcripts.md` describes the comparison stage's reconcile policy, category remap, and vote-result vocabulary in the present tense, `docs/specs/index.md` lists it, and `docs/DEBT.md` rows `D9` and `D42` record what this plan reflected and what it deferred, and a new `DEBT` row records the deferred prompt alignment with the next `COMPARE_PROMPT_VERSION` bump as its trigger.

## Surprises & Discoveries

Nothing has been executed yet. Two things were found while authoring and shaped the plan:

- Observation: the issue #116 table says "the council approves the denial" reads `pass` today; on this checkout it reads `None`, because `_PASS_WORDS` has `approved?` and never matches "approves". The fix is the same either way (fail stems checked first).
  Evidence: `venv/bin/python -c "..."` as printed in Purpose above printed `pass pass pass pass None False True` on 2026-10-11 at commit `1a0d91d`.
- Observation: making approved rows survive an unchanged-minutes pass would, on its own, make `reset_for_versions()` re-queue the meeting on every cron tick after a `COMPARE_PROMPT_VERSION` bump, because that function counts `approved` rows whose `prompt_version` is below the current one and a surviving approved row keeps its old version forever. The existing test `test_reset_for_versions_is_idempotent_after_compare` in `tests/integration/test_transcript_pipeline.py` guards the same trap for stale and rejected rows. M2 therefore also removes `approved` from the compare-reset count (Decision Log).
  Evidence: `src/docket/ai/transcripts/pipeline.py` lines 319 to 323, read 2026-10-11: `d.review_state IN ('proposed', 'approved', 'dismissed_by_model') AND d.prompt_version < %s`.

## Decision Log

- Decision: three milestones, one pull request. M1 holds the two pure-unit fixes (#116 and #114), M2 the database-backed policy change (#112) with the runbook and script docstring, M3 the behaviour spec and the debt rows.
  Rationale: the operator asked for one small PR; each milestone is one session with its own red-then-green evidence, and each leaves the branch coherent on its own. The two unit fixes together are still smaller than M2 alone, and splitting them would cost a second 630-second verify cycle for no extra safety.
  Date/Author: 2026-10-11, plan author.
- Decision: issue #112 takes the issue's option A. `reconcile(meeting_id, rows, *, minutes_changed=False)` stales only `proposed` rows when `minutes_changed` is false and stales `approved` and `proposed` rows (today's behaviour) when it is true. `write_rows` takes and forwards the same keyword, and `run_compare_stage` derives it as `claim.get("compare_skipped_reason") == "minutes_changed"`, the same expression the stage already uses to decide whether to re-extract the minutes side.
  Rationale: the claim already carries the trigger; the weekly `sweep_minutes_changes` is the only production writer of `'minutes_changed'`, so the two production paths the issue names (`reset_for_versions` and `run_for_meeting`) carry `NULL` and get the new behaviour with no further plumbing. Option B (a `stale_reason` column plus an admin bucket) needs a migration and UI and still hides an approved row from the public page. The default `False` means a caller that forgets the keyword preserves human verdicts, the safer failure.
  Date/Author: 2026-10-11, plan author.
- Decision: the match pool in `reconcile()` includes `approved` rows unconditionally (`review_state IN ('stale', 'rejected', 'approved')`), and a new row matched to an approved row is written in place with `review_state` kept at `approved` and `reviewed_at`, `reviewed_by`, and `review_note` kept, by extending the existing `new_state` rule to `match["review_state"] if match["review_state"] in ("rejected", "approved") else "proposed"`.
  Rationale: on a `minutes_changed` pass no approved rows remain after the stale sweep, so the wider pool changes nothing there; on an unchanged pass it is what stops a re-proposed finding from being inserted as a duplicate beside the approved original. The existing UPDATE already keeps the reviewer columns whenever `new_state` is not `proposed`, so approved becomes symmetric with rejected, which the issue argues for.
  Date/Author: 2026-10-11, plan author.
- Decision: when a matched approved row's replacement carries `citation_match = 'missing'`, the stored excerpts, page, start time, and `citation_match` are kept and only the text columns, severity, confidence, and `prompt_version` are refreshed.
  Rationale: `approve()` in `src/docket/services/discrepancies.py` refuses to approve a row whose citation is missing, so an approved row with an unverified excerpt is a state the service never creates; letting reconcile create it would publish a quote the guard could not find (`docs/PRINCIPLES.md`, "Source or silence"). The pool SELECT grows by five columns to make the old values available; no schema changes.
  Date/Author: 2026-10-11, plan author.
- Decision: `reset_for_versions()` counts only `proposed` and `dismissed_by_model` rows in its compare-reset branch, not `approved`.
  Rationale: see Surprises. Alternatives considered: stamping surviving approved rows with the current `prompt_version` (rejected: the column records the version that produced the row's text, and `GOALS.md` requires every AI sentence to carry its real prompt version); a per-transcript "compared at version" column (rejected: a migration, outside a small PR). The consequence, stated in the spec: a meeting whose only live rows are approved does not re-compare after a prompt bump; `scripts/transcript_recompare.py --meeting-id N` is the manual path for it. Rejected and stale survivors already behave this way.
  Date/Author: 2026-10-11, plan author.
- Decision: `scripts/transcript_recompare.py` gains `--minutes-changed`; without it the script writes `compare_skipped_reason = NULL` instead of `'minutes_changed'`.
  Rationale: today the script always claims the minutes changed, which after this plan would stale approved rows on every manual rerun, the exact behaviour #112 removes. Without the flag the stage also skips re-extracting the minutes side (one fewer Sonnet call) because `run_compare_stage` re-extracts only when minutes events are absent or the reason is `'minutes_changed'`.
  Date/Author: 2026-10-11, plan author.
- Decision: issue #114 is fixed by one helper in `compare.py`, `model_category(category, *, meeting_id, title)`, applied on the judge path and the hunter path of `build_rows`; the prompts and the pydantic `Literal` lists keep `vote_outcome`.
  Rationale: dropping the word from the prompt text is a prompt change that rides a `COMPARE_PROMPT_VERSION` bump, and `reset_for_versions` turns a bump into a paid Opus re-compare of every compared meeting with a live row below the new version; issue #114 defers it for that reason. The remap is applied before the row's category is used for the hunter fold-in set, so a remapped hunter row folds into an aligner `wording` row on the same anchor the way any other wording row does.
  Date/Author: 2026-10-11, plan author.
- Decision: issue #116 is fixed with a `_NONE_WORDS` pattern checked first and widened fail stems, as the issue proposes; `_PASS_WORDS` is untouched, so "approves" alone still reads `None`.
  Rationale: the fail-first order already makes "approves the denial" read fail once `den(?:y|ies|ied|ial)` is a fail stem, so widening the pass words is not needed for any case in the goal. The no-outcome list is the issue's (`carried over`, `carried forward`, `tabled`, `withdrawn`, `postponed`, `continued`, `deferred`, `no action`); a result string that mixes one of those words with a decision word reads `None`, which skips the comparison rather than guessing, the same stance the function's docstring already takes.
  Date/Author: 2026-10-11, plan author.
- Decision: the #112 tests live in the integration tier (`tests/integration/test_recompare.py`), not the unit tier.
  Rationale: `reconcile()` opens `db_cursor()`; the goal's "unit test observed red first" is met by that tier, which `./tools/verify` runs. One existing test, `test_recompare_updates_matched_rows_in_place_and_leaves_others_stale`, encodes today's stale-everything policy and becomes the `minutes_changed` case by passing `reason="minutes_changed"` on its claim and monkeypatching `C.extract_minutes_side` to return `"ok"` (the stage re-extracts the minutes side on that reason, and the test's seeded minutes events must stay). The issue's suggested `tests/unit/test_pipeline_reset.py` does not exist and is not created; one assertion in the existing reset test states that the compare-reset branch leaves `compare_skipped_reason` NULL.
  Date/Author: 2026-10-11, plan author.
- Decision: `D42` (the two speaker helpers `compare.py` imports from `docket.services.transcripts`) stays deferred; `D9` is narrowed, not closed.
  Rationale: paying `D42` touches `ab.py`, `events.py`, `compare.py`, and `services/transcripts.py`, against the operator's "one small PR". Its trigger ("next change to the transcript stages") fires on this plan, so M3 records the deferral in the row and the trigger stays armed for the next one. `D9` says the first plan touching the transcripts area reflects its behaviour into `docs/specs/`; this plan reflects only the comparison-stage behaviour it changes, so the row is narrowed to exclude that part.
  Date/Author: 2026-10-11, plan author.
- Decision: the scope brief's out-of-scope items are left out of this plan: paying `D42`; dropping `vote_outcome` from the judge and hunter category lists in `prompts.py` and the `Literal` in `schemas.py`; widening `_PASS_WORDS`; option B of #112; issues #113 and #115; editing the historical design document under `docs/superpowers/specs/`; a new `tests/unit/test_pipeline_reset.py`.
  Rationale: each is either a prompt-version cost, a migration, an audit rather than a fix, or history rather than current behaviour. See the revision note at the end.
  Date/Author: 2026-10-11, plan author.
- Decision: M3 also adds a `docs/DEBT.md` row for the deferred prompt alignment (issue #114), with the next `COMPARE_PROMPT_VERSION` bump as its trigger.
  Rationale: the #114 decision above defers removing `vote_outcome` from the prompts and the `Literal` for cost reasons but recorded that deferral only in this plan; a register row with the bump as its trigger makes the deferral fire on its own when someone next edits the prompt, instead of relying on memory. Raised by an outside review of the plan; the review's other points (regex vocabulary breadth, extracting reconcile's state transitions into a pure function, logging when pass and fail words both match) were read and left out as either already handled by the fail-first order and the widened no-outcome list or out of a three-issue PR's scope.
  Date/Author: 2026-10-12, operator (Darrell Nance, with Claude).
- Decision: the second-pass judge function the Plan of Work said to copy into `test_approved_rows_survive_an_unchanged_minutes_rerun` is a module-level helper `_wording_verdicts_only(info)` in `tests/integration/test_recompare.py`; the existing minutes-changed test keeps its own inline copy untouched, and a second helper `_full_rows(mid)` reads the title, version, and citation columns `_states` does not.
  Rationale: the Plan of Work said "copy it"; a named helper is the same verdicts with one definition, and leaving the existing test's inline copy in place keeps that test's diff to the two lines change (1) asks for. No behaviour differs.
  Date/Author: 2026-10-12, M2 session.
- Decision: the script's `--help` acceptance ("a usage line containing `[--minutes-changed]`") is read as met: argparse wraps the usage over two physical lines at the default width and prints it on one line at `COLUMNS=120`; both were run and both are in Artifacts and Notes.
  Rationale: the content is what the acceptance names; the wrap is terminal width, not script behaviour, and it was recorded rather than hidden.
  Date/Author: 2026-10-12, M2 session.

## Outcomes & Retrospective

M1 closed 2026-10-12 (UTC; the session ran late on 2026-10-11 Central). Every M1 acceptance check was run and met: the probe prints `None None fail fail fail False False`; the two unit files print `43 passed`; the red outputs before each source edit are in Artifacts and Notes (six `FAILED` aligner lines, two `FAILED` render lines with `assert 'vote_outcome' == 'wording'`); `./tools/verify` passed in 141s with exit 0; and the source diff against `origin/main` lists only `aligner.py` and `compare.py`. No carve-out. Issues #116 and #114 are fixed in code; #112 (M2) and the spec and debt rows (M3) remain. One observation for the next session: the plan's Concrete Steps said verify took 180s while authoring; both runs this session took 134s and 141s. Nothing else diverged from the Plan of Work.

M2 closed 2026-10-12 04:20Z. Every M2 acceptance check was run and met: the two integration files print `22 passed`; the red outputs are in Artifacts and Notes (both new tests `FAILED` before the source edits, the second with `unexpected keyword argument 'minutes_changed'`; the existing stale-everything test `FAILED` after the source edits and before its claim was changed); the script's `--help` shows `[--minutes-changed]` and exits 0; the runbook and script greps each print lines and the `pipeline.py` grep prints `1`; `./tools/verify` passed in 145s with exit 0 (integration tier `620 passed`, up from 618 at the start). No carve-out. Two small deviations from the Plan of Work are in the Decision Log (a shared verdicts helper instead of a copied function; the wrapped usage line). Issue #112 is fixed in code; the spec and debt rows (M3) remain. `git diff --stat origin/main -- src/ scripts/` now lists `aligner.py`, `compare.py`, `pipeline.py`, and `scripts/transcript_recompare.py`.

## Context and Orientation

docket.pub is a Python 3.10 Flask application with a PostgreSQL database and an APScheduler worker. This plan touches only the transcript comparison pipeline under `src/docket/ai/transcripts/`, one operator script, the tests for them, and documentation. Every command below runs from the worktree root, `/Users/darrellnance/docket-pub/.claude/worktrees/transcript-compare-row-fidelity`, with that checkout's own `venv/`.

The transcript pipeline. A desktop machine transcribes council video and uploads segments into the `transcripts` and `transcript_segments` tables. The worker task `transcript_pipeline` (`src/docket/ai/transcripts/pipeline.py`) then advances each transcript one stage per claim: `uploaded` to `speakers_resolved` (speaker names), to `events_extracted` (a timeline of events such as motions and votes, extracted from the transcript and, when the minutes PDF is available, from the minutes), to `compared`. A claim is the dictionary `claim_next()` or `claim_meeting()` returns from the `transcripts` row: `id`, `meeting_id`, `status`, `version`, `word_count`, and `compare_skipped_reason`. `compare_skipped_reason` is a text column on `transcripts`; it is `NULL` on an ordinary pass, `'no_minutes'` or `'minutes_unavailable'` when the minutes side could not run, and `'minutes_changed'` when the weekly sweep `sweep_minutes_changes()` (same file, line 327) found the minutes PDF's hash changed and queued a re-comparison. `advance()` writes the stage outcome's `skipped_reason` back into that column, so after a successful compare it reads `NULL`.

The comparison stage is `run_compare_stage(claim, *, client)` in `src/docket/ai/transcripts/compare.py`. It loads both event timelines, calls `align()` from `src/docket/ai/transcripts/aligner.py` to pair them deterministically into candidates (a `Candidate` has a `kind`, a `category`, the two events, a note, the agenda item references, and for the tally check a `vote_row`), sends every candidate whose category is not `vote_outcome` to a language model called the judge (system prompt `JUDGE_SYSTEM` in `prompts.py`, result schema `JudgeResult` of `Verdict` objects in `schemas.py`), sends the full texts to a second model call called the hunter (`HUNTER_SYSTEM`, `HunterResult` of `HuntedDiscrepancy` objects) to find what the aligner missed, and then calls `build_rows()` to turn candidates, verdicts, and hunted findings into row dictionaries whose keys are the `_COLS` tuple (line 304). Finally `write_rows()` calls `reconcile()` to write them. The six categories a row may carry are fixed by a CHECK constraint in migration 035: `vote_outcome`, `omission`, `addition`, `wording`, `sequence`, `speaker`. The deterministic tally check (issue #114 calls it "spec decision J") is the first loop of `build_rows` (lines 205 to 227): candidates with `category == "vote_outcome"` become rows with `origin = 'aligner'`, `severity = 'material'`, and no model involved. The judge path (lines 229 to 250) writes `base(v.category or c.category, ...)`, and the hunter path (lines 258 to 295) writes `base(h.category, ...)`; both take the model's category verbatim, which is #114's defect. Line 256 builds the `taken` set the hunter path uses to fold a restated finding into the aligner's row; it keys on the row's category and anchor event.

The vote-result vocabulary is `canonical_result(s)` in `aligner.py` (line 97). It normalises a result string (`normalize` from `src/docket/ai/transcripts/guard.py` lowercases and joins hyphenated line breaks; it keeps punctuation) and returns `"fail"` when `_FAIL_WORDS` matches, else `"pass"` when `_PASS_WORDS` matches, else `None`. `_results_differ(a, b)` (line 112) reports a mismatch only when both sides are non-`None` and differ, and both `details_differ` (paired vote events) and `vote_outcome_candidates` (transcript vote against the minutes-derived `votes` row) call it. Because `_PASS_WORDS` contains the bare word `carried`, "carried over" reads `pass`; because the only deny-family fail word is `denied`, "motion to deny approved" reads `pass`. That is #116.

Rows and their review states. `minutes_discrepancies` (DDL in `src/docket/migrations/035_transcripts.py` line 131) carries `review_state` in `proposed`, `approved`, `rejected`, `dismissed_by_model`, `stale`; `previous_review_state`; `reviewed_at`, `reviewed_by`, `review_note`; `citation_match` in `exact`, `fuzzy`, `missing`; `origin` in `aligner`, `model_initiated`; and `prompt_version`. `src/docket/services/discrepancies.py` owns the state changes: `approve()` (line 54) moves a `proposed` row to `approved` and refuses a row whose `citation_match` is `missing`; `list_public_for_meeting()` (line 171) and its two siblings read `approved` rows only, so the public meeting page shows exactly the approved rows. The admin queue template `src/docket/web/templates/admin/_discrepancy_row.html` shows a "re-review (was X)" chip when `previous_review_state` is set and is not changed by this plan.

`reconcile(meeting_id, rows)` (compare.py line 336) is #112's defect. It deletes the meeting's `dismissed_by_model` rows, sets every `approved` and `proposed` row to `stale` with `previous_review_state` recording the old state, loads the meeting's `stale` and `rejected` rows as a match pool, and for each new `proposed` row either updates a matching pool row in place (`match_stale()`, line 320: same category and `transcript_event_id`, or for additions same category and agenda item with a minutes-excerpt similarity of at least 0.8) or inserts it. A matched rejected row stays `rejected` and keeps its reviewer; a matched stale row becomes `proposed` and its reviewer columns are cleared. An unmatched stale row stays stale. The design document that rule came from wrote it for one trigger, a changed minutes PDF; but reconcile runs on every compare pass, and two production paths re-compare with the minutes unchanged: `reset_for_versions()` (pipeline.py line 305), which after a `COMPARE_PROMPT_VERSION` bump moves every `compared` transcript with a live row below the new version back to `events_extracted` with `compare_skipped_reason` left as it was (its compare-reset branch, lines 319 to 323, does not touch the column, so it stays `NULL` after a successful earlier compare); and `run_for_meeting()` (line 373), which `scripts/transcript_recompare.py` drives. On those paths the only thing that makes a row vanish is the judge deciding differently, and a human-approved row then goes stale.

The operator script `scripts/transcript_recompare.py` moves one meeting's transcript back to `events_extracted` and sets `compare_skipped_reason = 'minutes_changed'` unconditionally (line 26), then either leaves it for the next cron tick or runs the stages now. Its `--help` today prints `usage: transcript_recompare.py [-h] --meeting-id MEETING_ID [--now]` (observed while authoring).

Tests and the verify command. `./tools/verify` (about 150 seconds; budget 180) builds a disposable database named `docket_test_<hash>` from the migrations, exports `DATABASE_URL` at it, runs `tests/unit`, `tests/web`, `tests/services`, then `tests/integration`, then the milestone judge's fixtures and the workflow shape check, and drops the database. Never run `pytest` against a database you care about: the unit tier deletes rows from whatever `DATABASE_URL` names. To run one file alone on a disposable database: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest <file> -q -p no:cacheprovider; tools/test-db --drop`. The hash is derived from the checkout path, so two commands that build the test database cannot run at the same time in one worktree. The transcript tests use a fixture bundle: `install_bundle(pilot_bundle(), ...)` in `tests/support/transcript_fixtures.py` inserts a Birmingham meeting with one agenda item, a short transcript, and minutes text; `_seed_events()` in `tests/integration/test_compare_stage.py` inserts hand-written timelines whose pairing yields one `sequence` and one `wording` candidate; `_client(verdicts_fn, hunted=None)` is a mocked model client; `_claim(inst, reason=None)` builds a claim; `_ids_in_prompt(user)` lists the candidate ids the judge prompt shows. `tests/integration/test_recompare.py` reuses all four and defines `_real_all(info)` (every candidate real) and `_states(mid)` (every row's id, category, states, reviewer). `tests/unit/test_compare_render.py` builds `Candidate`, `Verdict`, and `HuntedDiscrepancy` objects by hand with `SEGS`, `_ev()`, and `transcript_text()` and calls `build_rows` with no database. `tests/unit/test_aligner.py` has an `ev()` helper and the existing vocabulary test `test_vote_vocabulary_is_not_a_vote_outcome_discrepancy`.

The milestone judge. Every milestone session must commit at least once, every commit must change this plan file, exactly one Progress line changes from `- [ ]` to `- [x] (YYYY-MM-DD HH:MMZ)` with no other change to that line, and the tree must be clean at the end (`docs/capabilities/judge-milestone.md`). Git hooks are never disabled.

Documentation that owns the comparison behaviour today: `docs/runbooks/transcripts.md` (operator runbook; its "Re-comparison" section, lines 103 to 110, states the stale-everything policy), the docstring of `scripts/transcript_recompare.py` (lines 8 to 9, same policy), and the historical design document `docs/superpowers/specs/2026-10-05-meeting-transcripts-design.md`, which `AGENTS.md` classes as history, not current behaviour, and which this plan does not edit. `docs/specs/` holds present-tense behaviour specs; `docs/specs/index.md` lists them and says the areas in debt row `D9`, transcripts among them, have none yet. `docs/DEBT.md` row `D42` records that `compare.py` line 30 imports `SPEAKER_CONFIDENCE_FLOOR` and `speaker_ordinals` from `docket.services.transcripts`, an inward layer reaching outward, with the trigger "next change to the transcript stages".

Out of scope, deliberately (from the scope brief and the Decision Log): paying `D42`; removing `vote_outcome` from the prompt category lists (`prompts.py` lines 97 and 111) and the `Literal` types (`schemas.py` lines 202 and 217); widening `_PASS_WORDS`; a `stale_reason` column; issues #113 (judge stability measurement) and #115 (real-data sweep); the historical design document; `tests/unit/test_pipeline_reset.py`.

## Plan of Work

M1, `src/docket/ai/transcripts/aligner.py`, lines 93 to 109. Add, above `_FAIL_WORDS`, a third pattern:

    _NONE_WORDS = re.compile(r"\b(carried (?:over|forward)|tabled|withdrawn|postponed|continued|deferred|no action)\b")

Replace `_FAIL_WORDS` with:

    _FAIL_WORDS = re.compile(r"\b(not (?:adopted|approved|carried|granted)|fail(?:s|ed)?|den(?:y|ies|ied|ial)|defeat(?:s|ed)?|reject(?:s|ed|ion)?|lost)\b")

Leave `_PASS_WORDS` as it is. In `canonical_result`, after `if not n: return None`, add `if _NONE_WORDS.search(n): return None` before the fail check, and extend the docstring with one sentence: a result that names a continuation (carried over, tabled, withdrawn, postponed, continued, deferred, no action) is no outcome and never pairs as pass or fail, and the deny, reject, and defeat stems are fail words so "motion to deny approved" reads fail (issue #116). The prototype of exactly these three patterns, run while authoring against `normalize`, produced the table in Artifacts and Notes.

M1, `tests/unit/test_aligner.py`. Add `_results_differ` to the import from `docket.ai.transcripts.aligner` and `import pytest` at the top. Append, after the existing vocabulary test, one parametrized test:

    @pytest.mark.parametrize("text, expected", [
        ("carried over", None), ("carried forward", None), ("tabled", None), ("withdrawn", None),
        ("motion to deny approved", "fail"), ("motion to deny carried", "fail"), ("the council approves the denial", "fail"),
        ("application denied", "fail"), ("the motion to approve NOT adopted and the above resolution adopted", "fail"),
        ("approved as amended", "pass"), ("passed", "pass"), ("adopted", "pass"),
    ])
    def test_canonical_result_issue_116_table(text, expected):
        """Issue #116: continued items are no outcome; a denial the body approved is a fail."""
        assert canonical_result(text) == expected

and one plain test `test_results_differ_skips_continuations_and_reads_approved_denials_as_fail` asserting `_results_differ("carried over", "adopted") is False` (one side is no outcome, so the comparison is skipped) and `_results_differ("motion to deny approved", "denied") is False` (both read fail). Before editing `aligner.py`, run the file and record the red rows: the expectation from the authoring probe is that five parametrized cases fail (`carried over`, `carried forward`, `motion to deny approved`, `motion to deny carried`, `the council approves the denial`) and the `_results_differ` test fails on its second assertion.

M1, `src/docket/ai/transcripts/compare.py`. Add one module-level function directly above `build_rows`:

    def model_category(category: str, *, meeting_id: int, origin: str, title: str) -> str:
        """vote_outcome is reserved for the deterministic tally check in build_rows (issue #114). A judge
        verdict or a hunter finding that picks it is a model's reading of a vote, which is wording."""
        if category == "vote_outcome":
            log.info("compare: meeting %s remapped a model-assigned vote_outcome to wording (%s, %s)", meeting_id, origin, title[:60])
            return "wording"
        return category

In the judge path, replace `base(v.category or c.category, ...)` at line 239 so the first argument is `model_category(v.category or c.category, meeting_id=meeting_id, origin="aligner", title=v.title or c.note)`. In the hunter path, compute `cat = model_category(h.category, meeting_id=meeting_id, origin="model_initiated", title=h.title)` at the top of the `for h in hunted:` body and use `cat` in place of `h.category` at both line 286 (the `taken` membership tests) and line 289 (`base(...)`). The deterministic loop and the dismissed branch are untouched.

M1, `tests/unit/test_compare_render.py`. Add `import logging` and three tests after the fold-in test, reusing `SEGS`, `_ev`, `transcript_text`, `Candidate`, `Verdict`, `HuntedDiscrepancy`:

`test_judge_assigned_vote_outcome_is_written_as_wording(caplog)`: a `wording` candidate (`Candidate(1, "mismatch", "wording", t_ev, m_ev, "note", frozenset({1}))` with `t_ev = _ev(7, "transcript", 7, "motion", start_s=3400.0)` and `m_ev = _ev(17, "minutes", 17, "motion", char_offset=0)`), a `Verdict(candidate_id=1, is_real=True, category="vote_outcome", severity="minor", title="Voice vote recorded as roll call", description="d", transcript_quote="we will go into executive session", minutes_quote=None, confidence=0.7, dismiss_reason=None)`; with `caplog.set_level(logging.INFO, logger="docket.ai.transcripts.compare")`, call `build_rows(99, [cand], [verdict], [], tt=transcript_text(SEGS), minutes=None, t_events=[t_ev], m_events=[m_ev], valid_item_ids={1})`; assert exactly one row, `row["category"] == "wording"`, `row["severity"] == "minor"`, `row["title"] == "Voice vote recorded as roll call"`, `row["origin"] == "aligner"`, and `"remapped a model-assigned vote_outcome" in caplog.text`.

`test_hunter_assigned_vote_outcome_is_written_as_wording()`: no candidates or verdicts; one `HuntedDiscrepancy(category="vote_outcome", severity="minor", title="Consent agenda shown as a roll-call vote", description="d", agenda_item_refs=[1], transcript_quote="three years between the agency and Alabama power", transcript_segment_seq=1, minutes_quote=None, minutes_page=None, confidence=0.8)`; `build_rows(99, [], [], [h], tt=..., minutes=None, t_events=[t_ev], m_events=[], valid_item_ids={1})`; assert one row with `category == "wording"`, `severity == "minor"`, `origin == "model_initiated"`, title unchanged.

`test_deterministic_vote_outcome_candidate_keeps_its_category()`: `Candidate(1, "vote_outcome", "vote_outcome", t_ev, None, "transcript says failed 3-5; minutes vote row 900 says passed 8-0", frozenset({1}), vote_row={"id": 900, "result": "passed", "yeas": 8, "nays": 0, "abstentions": None, "raw_text": "the motion passed", "item_ids": [1]})` with `t_ev = _ev(7, "transcript", 7, "vote", start_s=3400.0)`; `build_rows(99, [cand], [], [], ...)`; assert one row with `category == "vote_outcome"`, `severity == "material"`, `origin == "aligner"`. This third test passes before and after the edit; it pins the deterministic path.

Run the file before editing `compare.py` and record the red output: the first two tests are expected to fail with `assert 'vote_outcome' == 'wording'`.

M2, `src/docket/ai/transcripts/compare.py`, `reconcile` and `write_rows`. Change the signatures to `reconcile(meeting_id: int, rows: list[dict], *, minutes_changed: bool = False) -> dict` and `write_rows(meeting_id: int, rows: list[dict], *, minutes_changed: bool = False) -> int`, with `write_rows` forwarding the keyword. Rewrite the docstring of `reconcile` to state the policy: a `minutes_changed` pass (the weekly sweep, or the script with `--minutes-changed`) stales `approved` and `proposed` rows first and re-proposes what comes back; any other pass (a prompt-version reset, a manual rerun) stales only `proposed` rows, because on unchanged input the only thing that can make a row vanish is the model deciding differently, and a human's approval outranks that; matched approved rows are refreshed in place and stay approved; matched rejected rows stay rejected; old model dismissals are replaced wholesale (issue #112). Then four edits inside the function. (1) The stale UPDATE's `IN ('approved', 'proposed')` becomes a parameter: `states = ("approved", "proposed") if minutes_changed else ("proposed",)` and `review_state = ANY(%s)` with `list(states)`. (2) The pool SELECT reads `review_state IN ('stale', 'rejected', 'approved')` and adds `transcript_excerpt, transcript_start_s, minutes_event_id, minutes_page, citation_match` to its column list. (3) `new_state = match["review_state"] if match["review_state"] in ("rejected", "approved") else "proposed"`. (4) Directly before the UPDATE, `if new_state == "approved" and r["citation_match"] == "missing": r = {**r, **{k: match[k] for k in ("transcript_excerpt", "transcript_start_s", "minutes_excerpt", "minutes_event_id", "minutes_page", "citation_match")}}` with a two-line comment saying why (an approved row never carries an unverified citation; `approve()` enforces it on the way in and reconcile must not undo it). The UPDATE statement itself is unchanged; its `CASE WHEN %s = 'proposed'` clauses already keep the reviewer columns for `approved`. The stale count at the end is unchanged.

M2, `src/docket/ai/transcripts/compare.py`, `run_compare_stage`. At the top of the function, after `tid, mid = ...`, add `minutes_changed = claim.get("compare_skipped_reason") == "minutes_changed"`, use it in the existing `if not m_events or ...` condition, and pass `minutes_changed=minutes_changed` to `write_rows`. The module docstring (lines 2 to 8) gains one sentence pointing at `reconcile` for the re-comparison policy.

M2, `src/docket/ai/transcripts/pipeline.py`, `reset_for_versions`. In the second UPDATE (line 319), change `d.review_state IN ('proposed', 'approved', 'dismissed_by_model')` to `d.review_state IN ('proposed', 'dismissed_by_model')`. Rewrite the docstring's second paragraph: the compare reset counts only rows the next pass will rewrite (`proposed` and `dismissed_by_model`); approved rows survive an unchanged-minutes pass at their old `prompt_version` (`compare.reconcile`), rejected and stale rows are never re-stamped, so counting any of them would re-compare the meeting on every tick after a bump; a meeting whose live rows are all approved is re-compared by hand with `scripts/transcript_recompare.py`.

M2, `scripts/transcript_recompare.py`. Add `ap.add_argument("--minutes-changed", action="store_true", help="the minutes PDF changed: re-extract the minutes side and stale approved rows that do not come back")`. Change the UPDATE to `compare_skipped_reason = %s` with the parameter `"minutes_changed" if a.minutes_changed else None` placed before `a.meeting_id`. Replace the docstring's last paragraph (lines 8 to 9) with: without `--minutes-changed` the rerun keeps every approved row (`compare.reconcile` stales only proposed rows and refreshes a matched approved row in place); with it, approved rows go stale unless the same discrepancy comes back, which is re-proposed in place for re-review. Add a third usage line showing `--minutes-changed --now`.

M2, `tests/integration/test_recompare.py`. Three changes. (1) The existing `test_recompare_updates_matched_rows_in_place_and_leaves_others_stale` gains the `monkeypatch` fixture, `monkeypatch.setattr(C, "extract_minutes_side", lambda mid, *, client: "ok")` before the second `run_compare_stage`, and `_claim(pilot, reason="minutes_changed")` on that second call; its docstring line says it is the minutes-changed case. Nothing else in it changes. (2) New `test_approved_rows_survive_an_unchanged_minutes_rerun(pilot)`: seed, first compare with `_real_all(info)`, approve both rows by SQL (`review_state='approved', reviewed_at=now(), reviewed_by='t'`) and set their `prompt_version = C.COMPARE_PROMPT_VERSION - 1` and `transcripts.status = 'compared'`; second compare with the same `verdicts` function the existing test defines (copy it; only the wording candidate is real) and `_claim(pilot)` (reason `None`); then assert: the wording row keeps its id, `review_state == "approved"`, `reviewed_by == "t"`, `reviewed_at is not None`, `previous_review_state is None`, `title == "wording title v2"`, `prompt_version == C.COMPARE_PROMPT_VERSION`; the sequence row is `approved`, `reviewed_by == "t"`, `prompt_version == C.COMPARE_PROMPT_VERSION - 1`; `from docket.services import discrepancies as D; {r["id"] for r in D.list_public_for_meeting(pilot.meeting_id)}` equals the two ids; no row is `stale`; and after `P.advance(pilot.transcript_id, P.StageOutcome("compared"))`, `P.reset_for_versions() == 0` and the transcript's status is still `compared` (the idempotence guard from Surprises). (3) New `test_reconcile_minutes_changed_flag_decides_whether_approved_rows_go_stale(pilot)`: seed events; insert one approved row by SQL directly (category `wording`, `transcript_event_id` = the seeded transcript `executive_session_motion` event, `minutes_event_id` = the seeded minutes one, `citation_match='exact'`, `transcript_excerpt=info["exec_text"]`, `reviewed_by='t'`, `reviewed_at=now()`, `prompt_version=C.COMPARE_PROMPT_VERSION`); call `C.reconcile(pilot.meeting_id, [], minutes_changed=False)` and assert the row is still `approved` with `reviewed_by == "t"`; then build one row dictionary shaped as `_COLS` that matches it (same category and `transcript_event_id`, `review_state="proposed"`, `citation_match="missing"`, `transcript_excerpt="words nobody said"`, title `"refreshed"`), call `C.reconcile(pilot.meeting_id, [row], minutes_changed=False)` and assert the row is still `approved`, `title == "refreshed"`, `citation_match == "exact"`, `transcript_excerpt == info["exec_text"]`, and the meeting still has one non-dismissed row; finally call `C.reconcile(pilot.meeting_id, [], minutes_changed=True)` and assert `review_state == "stale"`, `previous_review_state == "approved"`, `reviewed_by == "t"`. Run the file before editing `compare.py` and record the red output: test (2) is expected to fail at the wording row's `review_state` (`'proposed' != 'approved'`) and test (3) with `TypeError: reconcile() got an unexpected keyword argument 'minutes_changed'`. After the `compare.py` and `pipeline.py` edits and before change (1), the existing test is expected to fail at its `("proposed", "approved")` assertion; record that too, then make change (1).

M2, `tests/integration/test_transcript_pipeline.py`, `test_reset_for_versions_is_idempotent_after_compare`: directly after `assert P.reset_for_versions() == 1`, add `assert _row(tid)["compare_skipped_reason"] is None   # the compare reset is an unchanged-minutes pass (issue #112)`. This passes before and after; it states the fact M2 relies on.

M2, `docs/runbooks/transcripts.md`, lines 103 to 110 ("Re-comparison"). Replace the paragraph with one that says: the daily tick re-downloads each compared meeting's minutes at most weekly; a changed PDF re-extracts the minutes side and re-runs the comparison as a minutes-changed pass, on which approved rows go `stale`, a candidate that comes back is re-proposed in place (badged "re-review"), and unmatched approvals stay `stale` under the stale tab; every other re-comparison (a `COMPARE_PROMPT_VERSION` bump, `scripts/transcript_recompare.py` without `--minutes-changed`) is an unchanged-minutes pass that keeps approved rows as they are, refreshing a matched one in place, and stales only unreviewed proposals; a prompt bump re-queues only meetings with a proposed or model-dismissed row below the new version, so a meeting whose rows are all approved is re-run by hand with the script; bumping `EVENTS_PROMPT_VERSION` re-extracts the transcript side, which changes transcript event ids and strands approvals as `stale`; keep that rare. Also change the "One meeting:" line (line 72) to mention `--minutes-changed` when the PDF changed.

M3, new file `docs/specs/transcripts.md`, present tense, about thirty lines, no code fences, headed `# Transcript comparison`. It covers only the comparison stage and says so in its first paragraph, pointing at `docs/runbooks/transcripts.md` for the rest of the pipeline. Sections: "What a comparison pass writes" (candidates from the aligner, the judge and the hunter, rows in `minutes_discrepancies`, the review states and that public pages show approved rows only); "Which categories a model may assign" (the six categories; `vote_outcome` is written only by the deterministic tally check in `build_rows`, always `material`, origin `aligner`; a judge verdict or hunter finding that names `vote_outcome` is written as `wording` and logged); "How a vote result is read" (`canonical_result`: no outcome for the continuation words, fail for the negation clause and the fail stems including deny, reject, defeat, pass for the pass words; fail is checked before pass; a mismatch needs both sides to name an outcome); "Re-comparison" (the two kinds of pass keyed on `compare_skipped_reason = 'minutes_changed'`; what each does to approved, proposed, rejected, dismissed rows; matched rows refreshed in place and a matched approved row keeping its verified citation; `reset_for_versions` counting only proposed and model-dismissed rows and the consequence for approved-only meetings; the script's flag). Every claim names the file and function it comes from.

M3, `docs/specs/index.md`: add one table row after the `calibration.md` row, first cell `` `transcripts.md` ``, second cell: The transcript comparison stage: which categories a model may assign, how a vote result is read, and what a re-comparison does to reviewed rows. Change the closing paragraph so it says the areas `D9` lists have no spec yet except the transcript comparison stage, which `transcripts.md` covers.

M3, `docs/DEBT.md`: in row `D9`, change the Item cell to end "transcripts (except the comparison stage's reconcile policy, category remap, and vote-result vocabulary, in `docs/specs/transcripts.md`)". In row `D42`, append to the "Why deferred" cell: "; the plan `transcript-compare-row-fidelity` (2026-10) changed `compare.py` and deferred it again to keep that PR small". The trigger cell is unchanged. Add one new row at the end of the register, numbered one above the highest existing ID: Item "Judge and hunter prompts still list `vote_outcome` as an assignable category; `model_category` in `compare.py` remaps it to `wording` after the fact"; Where `src/docket/ai/transcripts/prompts.py` (judge and hunter category lists), `src/docket/ai/transcripts/schemas.py` (the `Literal`), `src/docket/ai/transcripts/compare.py` (`model_category`); Why deferred "Dropping the word from the prompt is a prompt change that rides a `COMPARE_PROMPT_VERSION` bump, which `reset_for_versions` turns into a paid Opus re-compare of every compared meeting (issue #114, plan `transcript-compare-row-fidelity`, 2026-10)"; Trigger "The next `COMPARE_PROMPT_VERSION` bump removes `vote_outcome` from both prompt category lists and the `Literal`, and `model_category` then becomes a guard that logs instead of a remap".

## Milestones

### Milestone 1: the vote-result vocabulary and the category remap, unit-tested red then green

Scope: `aligner.py`, `compare.py` (`model_category` and its two call sites), and the two unit test files. At the end of M1 the probe in Purpose prints `None None fail fail fail False False`, and a model that labels a finding `vote_outcome` gets a `wording` row. No database behaviour changes.

Work, in order. Run `./tools/verify` and record its final line. Add the two aligner tests; run `tests/unit/test_aligner.py` alone and record the failures. Edit `aligner.py`; run again, record the pass line. Add the three `compare_render` tests; run that file alone and record the failures. Edit `compare.py`; run again. Run the probe. Run `./tools/verify`. Commit along the way; every commit also changes this plan.

Acceptance, from the worktree root:

`venv/bin/python -c "from docket.ai.transcripts.aligner import canonical_result as c, _results_differ as d; print(c('carried over'), c('carried forward'), c('motion to deny approved'), c('motion to deny carried'), c('the council approves the denial'), d('carried over','adopted'), d('motion to deny approved','denied'))"` prints `None None fail fail fail False False`.

`DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_aligner.py tests/unit/test_compare_render.py -q -p no:cacheprovider; tools/test-db --drop` prints a line ending `43 passed in <n>s` with no `failed` (the baseline count plus the twelve parametrized rows, the `_results_differ` test, and the three remap tests).

The plan's Artifacts and Notes holds the red output of both files, observed before the matching source edit: at least five `FAILED` lines naming `test_canonical_result_issue_116_table[...]` and one naming `test_results_differ_skips_continuations_and_reads_approved_denials_as_fail`, and two `FAILED` lines naming the two remap tests with `assert 'vote_outcome' == 'wording'` in their output.

`./tools/verify; echo "exit=$?"` prints `verify: all 4 checks passed in <n>s.` and `exit=0`.

`git diff --stat origin/main -- src/ scripts/` lists only `src/docket/ai/transcripts/aligner.py` and `src/docket/ai/transcripts/compare.py`.

### Milestone 2: approved rows survive an unchanged-minutes re-compare

Scope: `reconcile`, `write_rows`, and `run_compare_stage` in `compare.py`; `reset_for_versions` in `pipeline.py`; the script; `tests/integration/test_recompare.py` and one assertion in `tests/integration/test_transcript_pipeline.py`; the runbook section and the script docstring. At the end of M2 a meeting re-compared with unchanged minutes keeps its approved rows and the public page keeps showing them; a minutes-changed pass behaves as before; a prompt bump no longer re-queues a meeting forever because of a surviving approved row.

Work, in order. Run `./tools/verify` and record its final line. Add the two new tests to `test_recompare.py`; run that file alone and record the two failures. Edit `compare.py` and `pipeline.py`; run the file again and record that the two new tests pass and the existing `test_recompare_updates_matched_rows_in_place_and_leaves_others_stale` now fails at its `("proposed", "approved")` assertion. Make change (1) to that test; run again, record the pass line. Add the pipeline-test assertion. Edit the script and run its `--help`. Edit the runbook. Run `./tools/verify`. Commit along the way with the plan.

Acceptance, from the worktree root:

`DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_recompare.py tests/integration/test_transcript_pipeline.py -q -p no:cacheprovider; tools/test-db --drop` prints a line ending `22 passed in <n>s` with no `failed` (the baseline count of the two files plus the two new tests).

The plan's Artifacts and Notes holds, observed before the source edits, a `FAILED` line for `test_approved_rows_survive_an_unchanged_minutes_rerun` and one for `test_reconcile_minutes_changed_flag_decides_whether_approved_rows_go_stale` containing `unexpected keyword argument 'minutes_changed'`; and, observed after the source edits and before the test's claim was changed, a `FAILED` line for `test_recompare_updates_matched_rows_in_place_and_leaves_others_stale`.

`venv/bin/python scripts/transcript_recompare.py --help` prints a usage line containing `[--minutes-changed]` and exits 0 (it needs no database to print help; observed today it prints `usage: transcript_recompare.py [-h] --meeting-id MEETING_ID [--now]`).

`grep -n "minutes-changed" docs/runbooks/transcripts.md scripts/transcript_recompare.py` prints at least one line from each file; `grep -c "IN ('proposed', 'dismissed_by_model')" src/docket/ai/transcripts/pipeline.py` prints `1`.

`./tools/verify; echo "exit=$?"` prints `verify: all 4 checks passed in <n>s.` and `exit=0`.

### Milestone 3: the behaviour is written down where the next reader looks

Scope: documentation only. At the end of M3 a reader of `docs/specs/` finds a present-tense description of the comparison stage's three rules, and `docs/DEBT.md` says what this plan reflected and what it deferred.

Work: write `docs/specs/transcripts.md` as the Plan of Work describes; add the index row and adjust the closing paragraph; edit rows `D9` and `D42`; run `./tools/verify`; commit with the plan; write the Outcomes & Retrospective entry.

Acceptance, from the worktree root:

`grep -n 'transcripts.md' docs/specs/index.md` prints one table row naming the file. `head -1 docs/specs/transcripts.md` prints `# Transcript comparison`. `grep -c 'minutes_changed' docs/specs/transcripts.md` prints at least `2`; `grep -c 'canonical_result' docs/specs/transcripts.md` and `grep -c 'model_category' docs/specs/transcripts.md` each print at least `1`; `grep -c 'docs/runbooks/transcripts.md' docs/specs/transcripts.md` prints at least `1`.

`grep -n 'transcript-compare-row-fidelity' docs/DEBT.md` prints the `D42` row and the new prompt-alignment row; `grep -n 'docs/specs/transcripts.md' docs/DEBT.md` prints the `D9` row; `grep -c 'COMPARE_PROMPT_VERSION. bump removes' docs/DEBT.md` prints `1`.

`./tools/verify; echo "exit=$?"` prints `verify: all 4 checks passed in <n>s.` and `exit=0`, and `git status --porcelain` prints nothing.

## Concrete Steps

All from `/Users/darrellnance/docket-pub/.claude/worktrees/transcript-compare-row-fidelity`. Outputs marked "expected" were not obtained while authoring; outputs marked "observed" were.

Start and end of every milestone session:

    ./tools/verify; echo "exit=$?"

Observed while authoring on commit `1a0d91d` (2026-10-11): `verify: test-db ... ok (1s)`, `unit+web+services ... ok (79s)`, `integration ... ok (95s)`, `judge-fixtures ... ok (4s)`, `workflows ... ok (1s)`, `verify: all 4 checks passed in 180s.`, `exit=0`. That is exactly the 180-second budget `AGENTS.md` states; a session whose verify runs longer has not broken anything, but should record the time.

M1, the aligner file alone (run before and after the `aligner.py` edit):

    DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_aligner.py -q -p no:cacheprovider; tools/test-db --drop

Expected before the edit: `FAILED tests/unit/test_aligner.py::test_canonical_result_issue_116_table[carried over-None]` and four more parametrized rows plus `test_results_differ_...`, then `6 failed, 28 passed`. Expected after: `34 passed`.

M1, the render file alone (before and after the `compare.py` edit):

    DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_compare_render.py -q -p no:cacheprovider; tools/test-db --drop

Expected before: `2 failed, 7 passed`, the two failures containing `assert 'vote_outcome' == 'wording'`. Expected after: `9 passed`.

M1, the probe: the command in Purpose. Observed today: `pass pass pass pass None False True`. Expected after: `None None fail fail fail False False`.

M2, the recompare file alone, three times (before the source edits, after them, after the existing test's claim change):

    DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_recompare.py -q -p no:cacheprovider; tools/test-db --drop

Expected first run: `2 failed, 8 passed`. Expected second run: `1 failed, 9 passed` (the existing stale-everything test). Expected third run: `10 passed`.

M2, the script banner:

    venv/bin/python scripts/transcript_recompare.py --help; echo "exit=$?"

Observed today: `usage: transcript_recompare.py [-h] --meeting-id MEETING_ID [--now]` and `exit=0`. Expected after: `usage: transcript_recompare.py [-h] --meeting-id MEETING_ID [--now] [--minutes-changed]`.

M3: the grep lines under Milestone 3 acceptance.

Commits: `git add <files> plans/active/transcript-compare-row-fidelity.md && git commit -m "<message>"`, never with `--no-verify`. Commit messages begin `plan: transcript-compare-row-fidelity M<n>, ...` and end with the attribution line the session's instructions give.

## Validation and Acceptance

Each milestone's acceptance is listed under its heading in Milestones. The plan as a whole is accepted when all three Progress lines are ticked with dates, every acceptance command under Milestones has been run and its observed output recorded in Artifacts and Notes, `./tools/verify` passes on the branch head, and the pull request that `cycle-run` opens from this branch references issues #112, #114, and #116 with `Closes` lines so merging it closes them.

## Idempotence and Recovery

Every step is a file edit or a test run and can be repeated. `tools/test-db --drop` removes the disposable database if a run was interrupted; two test-database commands must not run concurrently in one worktree. If a milestone session runs out of room, split its Progress line in place (completed: X; remaining: Y), record the split in the Decision Log, commit, and stop. Nothing in this plan touches the production database or the Anthropic API; the model client is mocked in every test named here.

## Artifacts and Notes

Authoring prototype of the three patterns from Plan of Work M1, run with `venv/bin/python` on 2026-10-11 against `normalize` from `guard.py` (observed):

    'carried over' -> None
    'carried forward' -> None
    'motion to deny approved' -> fail
    'motion to deny carried' -> fail
    'the council approves the denial' -> fail
    'application denied' -> fail
    'tabled' -> None
    'withdrawn' -> None
    'approved as amended' -> pass
    'the motion to approve NOT adopted and the above resolution adopted' -> fail
    'passed' -> pass
    'adopted' -> pass
    'That item passes.' -> pass
    'failed' -> fail
    'denied' -> fail
    'motion to approve NOT adopted; resolution adopted' -> fail
    '' -> None
    'deferred two weeks' -> None
    'not adopted' -> fail
    differ False False True

The last line is `_results_differ` on `("carried over", "adopted")`, `("motion to deny approved", "denied")`, and `("approved", "not adopted")`; every existing assertion in `test_vote_vocabulary_is_not_a_vote_outcome_discrepancy` keeps its value.

Milestone sessions append their observed red and green outputs here under a heading per milestone.

### M1 session (2026-10-11, commit `ddbe174` at start)

Starting state, observed before any edit, `./tools/verify; echo "exit=$?"`:

    verify: test-db ... ok (1s) postgresql://docket@localhost:5432/docket_test_2dae8997
    verify: unit+web+services ... ok (58s)
    verify: integration ... ok (72s)
    verify: judge-fixtures ... ok (3s)
    verify: workflows ... ok (0s)
    verify: all 4 checks passed in 134s.
    exit=0

Aligner tests added, run before the `aligner.py` edit, `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_aligner.py -q -p no:cacheprovider; tools/test-db --drop` (observed):

    FAILED tests/unit/test_aligner.py::test_canonical_result_issue_116_table[carried over-None]
    FAILED tests/unit/test_aligner.py::test_canonical_result_issue_116_table[carried forward-None]
    FAILED tests/unit/test_aligner.py::test_canonical_result_issue_116_table[motion to deny approved-fail]
    FAILED tests/unit/test_aligner.py::test_canonical_result_issue_116_table[motion to deny carried-fail]
    FAILED tests/unit/test_aligner.py::test_canonical_result_issue_116_table[the council approves the denial-fail]
    FAILED tests/unit/test_aligner.py::test_results_differ_skips_continuations_and_reads_approved_denials_as_fail
    6 failed, 28 passed in 0.60s

The `_results_differ` test failed on its second assertion (`assert True is False` where `True = _results_differ('motion to deny approved', 'denied')`), as the Plan of Work expected.

Same command after the `aligner.py` edit (observed): `34 passed in 0.47s`.

The probe from Purpose after the edit (observed): `None None fail fail fail False False`.

Render tests added, run before the `compare.py` edit, `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_compare_render.py -q -p no:cacheprovider; tools/test-db --drop` (observed):

    E       AssertionError: assert 'vote_outcome' == 'wording'
    E       AssertionError: assert 'vote_outcome' == 'wording'
    FAILED tests/unit/test_compare_render.py::test_judge_assigned_vote_outcome_is_written_as_wording
    FAILED tests/unit/test_compare_render.py::test_hunter_assigned_vote_outcome_is_written_as_wording
    2 failed, 7 passed in 0.97s

After the `compare.py` edit, both unit files together, `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_aligner.py tests/unit/test_compare_render.py -q -p no:cacheprovider; tools/test-db --drop` (observed): `43 passed in 0.98s`.

`git diff --stat origin/main -- src/ scripts/` (observed): `src/docket/ai/transcripts/aligner.py | 9 +++++++--` and `src/docket/ai/transcripts/compare.py | 19 +++++++++++++++----`, `2 files changed, 22 insertions(+), 6 deletions(-)`; no other file listed.

Closing `./tools/verify; echo "exit=$?"` on the M1 tree (observed):

    verify: test-db ... ok (0s) postgresql://docket@localhost:5432/docket_test_2dae8997
    verify: unit+web+services ... ok (59s)
    verify: integration ... ok (78s)
    verify: judge-fixtures ... ok (4s)
    verify: workflows ... ok (0s)
    verify: all 4 checks passed in 141s.
    exit=0

### M2 session (2026-10-12, commit `ad31cd1` at start)

Starting state, observed before any edit, `./tools/verify; echo "exit=$?"`:

    verify: test-db ... ok (1s) postgresql://docket@localhost:5432/docket_test_2dae8997
    verify: unit+web+services ... ok (56s)
    verify: integration ... ok (78s)
    verify: judge-fixtures ... ok (4s)
    verify: workflows ... ok (0s)
    verify: all 4 checks passed in 139s.
    exit=0

Recompare tests added, run before the `compare.py` and `pipeline.py` edits, `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_recompare.py -q -p no:cacheprovider; tools/test-db --drop` (observed):

    E       AssertionError: assert ('proposed' == 'approved'
    E       TypeError: reconcile() got an unexpected keyword argument 'minutes_changed'
    FAILED tests/integration/test_recompare.py::test_approved_rows_survive_an_unchanged_minutes_rerun
    FAILED tests/integration/test_recompare.py::test_reconcile_minutes_changed_flag_decides_whether_approved_rows_go_stale
    2 failed, 8 passed in 2.75s

The first failure is at the wording row's `review_state` assertion, the second at the first `reconcile(..., minutes_changed=False)` call, as the Plan of Work expected.

Same command after the `compare.py` and `pipeline.py` edits and before the existing test's claim was changed (observed):

    E       AssertionError: assert ('approved', None) == ('proposed', 'approved')
    FAILED tests/integration/test_recompare.py::test_recompare_updates_matched_rows_in_place_and_leaves_others_stale
    1 failed, 9 passed in 2.72s

The existing test still sent `compare_skipped_reason = None`, so its approved wording row now survives as approved, which is the new policy; it fails at its `("proposed", "approved")` assertion as the Plan of Work expected.

After change (1) to that test (monkeypatched `extract_minutes_side`, claim `reason="minutes_changed"`) and the one-line assertion in `tests/integration/test_transcript_pipeline.py`, both files together, `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/integration/test_recompare.py tests/integration/test_transcript_pipeline.py -q -p no:cacheprovider; tools/test-db --drop` (observed): `22 passed in 3.17s`.

Script banner after the `scripts/transcript_recompare.py` edit, `venv/bin/python scripts/transcript_recompare.py --help; echo "exit=$?"` (observed; argparse wrapped the usage over two physical lines at the default width):

    usage: transcript_recompare.py [-h] --meeting-id MEETING_ID [--now]
                                   [--minutes-changed]
    ...
      --minutes-changed     the minutes PDF changed: re-extract the minutes side
                            and stale approved rows that do not come back
    exit=0

The same with `COLUMNS=120` printed the usage on one line (observed): `usage: transcript_recompare.py [-h] --meeting-id MEETING_ID [--now] [--minutes-changed]`.

`grep -n "minutes-changed" docs/runbooks/transcripts.md scripts/transcript_recompare.py` (observed): three lines from the runbook (73, 108, 112) and three from the script (7, 9, 27). `grep -c "IN ('proposed', 'dismissed_by_model')" src/docket/ai/transcripts/pipeline.py` (observed): `1`.

Closing `./tools/verify; echo "exit=$?"` on the M2 tree (observed):

    verify: test-db ... ok (1s) postgresql://docket@localhost:5432/docket_test_2dae8997
    verify: unit+web+services ... ok (61s)
    verify: integration ... ok (79s)
    verify: judge-fixtures ... ok (4s)
    verify: workflows ... ok (0s)
    verify: all 4 checks passed in 145s.
    exit=0

The integration tier printed `620 passed` (618 at the session start plus the two new tests). `git diff --stat origin/main -- src/ scripts/` (observed): `scripts/transcript_recompare.py | 13`, `aligner.py | 9`, `compare.py | 63`, `pipeline.py | 9`; `4 files changed, 67 insertions(+), 27 deletions(-)`.

## Interfaces and Dependencies

No new libraries. In `src/docket/ai/transcripts/aligner.py`, at module level:

    _NONE_WORDS: re.Pattern   # continuation words; checked first in canonical_result
    _FAIL_WORDS: re.Pattern   # negation clause plus fail, deny, defeat, reject, lost stems
    _PASS_WORDS: re.Pattern   # unchanged
    def canonical_result(s) -> str | None   # None, "fail", or "pass"; unchanged signature

In `src/docket/ai/transcripts/compare.py`:

    def model_category(category: str, *, meeting_id: int, origin: str, title: str) -> str
    def reconcile(meeting_id: int, rows: list[dict], *, minutes_changed: bool = False) -> dict   # {"inserted", "updated", "stale"}
    def write_rows(meeting_id: int, rows: list[dict], *, minutes_changed: bool = False) -> int

`run_compare_stage(claim, *, client)` keeps its signature and derives `minutes_changed` from `claim["compare_skipped_reason"]`. `reset_for_versions()` in `pipeline.py` keeps its signature and return value (count of transcripts moved). `scripts/transcript_recompare.py` accepts `--meeting-id N [--now] [--minutes-changed]`. The `minutes_discrepancies` schema, `prompts.py`, and `schemas.py` are unchanged.

## Revision notes

2026-10-11, authored. The scope brief's out-of-scope items are deliberately left out: paying `D42` (four files, against the one-small-PR ask; trigger re-armed); dropping `vote_outcome` from the judge and hunter category lists and the `Literal` types (a prompt change rides a paid `COMPARE_PROMPT_VERSION` bump); widening `_PASS_WORDS` (not needed for any goal case); #112 option B (migration plus UI); issues #113 and #115 (audits, not fixes); the historical design document (history per `AGENTS.md`); `tests/unit/test_pipeline_reset.py` (does not exist; `reset_for_versions` is covered in `tests/integration/test_transcript_pipeline.py`). Added beyond the brief, for reasons the Decision Log gives: `reset_for_versions` stops counting approved rows, and a matched approved row keeps its verified citation.
