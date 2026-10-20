# Transcriber version 3: drop caption-phrase hallucinations and join back-to-back same-speaker rows

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `plans/PLANS.md`.

## Purpose / Big Picture

The first version-2 re-run of meeting 2543 (the 2026-10-06 Birmingham City Council meeting, re-run 2026-10-17 with `--meeting-id 2543`) left visible defects that the operator listed in a review note: a segment reading "Thank you for watching." at 91:47 that nobody said, back-to-back rows from the same speaker that read as one sentence cut in two, a roll call that reads `SPEAKER_08: Good` / `SPEAKER_07: morning. Council Member Williams...`, and some misheard place names. After this change a reader of a re-transcribed meeting sees no caption-data filler and no sentence cut into two rows on the same speaker. Two further items were built and then withdrawn on real-audio evidence (see Surprises and the Decision Log): absorbing the one-word "Good" into its neighbour, and adding Linn Park and Boutwell Auditorium to the prompt. Uploads carry `transcripts.version = 3` so the operator can tell version-2 rows from version-3 rows before re-running the backlog. The work was one milestone, done by hand on branch `feat/transcriber-v3-quick-wins`, because it is two small rules in one module with their tests and documents.

A further item from the same review, Mr. Jenkins' three-minute public comment at 90:49–93:39 that both versions present as silence, was investigated here (Surprises) and deliberately left out (Decision Log).

## Progress

- [x] (2026-10-17 20:40Z) Signature-phrase rule, `absorb_fragments()`, `merge_same_speaker()`, vocabulary additions, `TRANSCRIPT_VERSION = 3`, `__version__ = 0.3.0` in `transcriber/transcriber/`.
- [x] (2026-10-17 20:55Z) Tests added, and the three that encoded version 2 or unpunctuated one-word runs updated; decision `0052`; `0047` status amended; spec and runbook updated.
- [x] (2026-10-17 20:58Z) First full-audio run of 2543 (no upload) with the rules as first built: the vocabulary sentence leaked four times, and the fragment absorption moved member labels onto the clerk (Surprises).
- [x] (2026-10-17 21:05Z) Withdrawn: `absorb_fragments()` and its tests, and the vocabulary edit to `prompt.py` (now back to `main`); decision `0052` rewritten to cover the merge and the rejected absorption; spec, runbook, and `0047` status adjusted.
- [x] (2026-10-17 21:10Z) Second full-audio run of 2543 with the final code: the checks in Validation pass (Artifacts).
- [ ] Pull request (needs the operator's interactive `git push`).

## Surprises & Discoveries

- Observation: Mr. Jenkins speaks about 15 dB below the chair, and faster-whisper's batched VAD (Silero, default threshold 0.5 with `min_silence_duration_ms=160` in faster-whisper 1.2.1's batched pipeline) marks most of his comment as non-speech. Lowering the threshold recovers it step by step but starts producing caption hallucinations inside it. Normalizing loudness first recovers it at the current threshold with clean text.
  Evidence: 5-minute clip 89:00–94:00 of meeting 2543 (`C:\docket-archive\work\vad_ab.out`, `vad_norm.out`). RMS per 30 s: about -23 dBFS for the chair, -39 to -41 dBFS for 91:00–93:29. VAD speech inside 90:50–93:38 (168 s): threshold 0.5 gives 60 s, 0.35 gives 89 s, 0.25 gives 106 s, and 0.15 gives 136 s plus a "Thank you for watching." at 93:09 (lp -0.70). With ffmpeg `dynaudnorm=f=500:g=31:m=20` applied first: threshold 0.5 gives 138 s, 0.35 gives 149 s, with no caption phrases, and the 89:47 "Thank you for watching." becomes the real sentence about the Winona Road neighbourhood. Decoding the clip with no VAD recovers all of it.
- Observation: the vocabulary sentence "Linn Park and Boutwell Auditorium were booked." came back as fake speech four times on the full audio, mostly in quiet stretches, and once dragged "Flock Safety license plate readers were debated." along with it. The leak detector misses these because each is shorter than `PROMPT_LEAK_MIN_WORDS` (8).
  Evidence: first version-3 run of 2543: rows at 24:42, 87:35 (in place of "Thank you very much."), 89:46, and 91:51–92:58 (67 s, inside the Jenkins gap). A scan of all archived transcripts for a row that is mostly a vocabulary sentence (`leakscan.py`) printed `hits 0`, so the pattern started with that sentence.
- Observation: in the "Good" | "morning." fragments, the one-word row is the member's correct label, and the member's second word is given to the clerk; the diarizer gives most of the members' answers to the clerk.
  Evidence: offline re-assembly from the saved inputs (`variants.py` over `2543_v3_inputs.pkl`), rows 18:42–19:03. Without absorption: `S07 Good morning, sir. Council Member O'Quinn. Good morning. Council Member Smith is absent...`, `S08 Good`, `S07 morning. Council Member Williams...`, `S20 Good`, `S07 morning.`. With absorption and merge, everything from 18:42 to 19:03 becomes one `SPEAKER_07` row.
- Observation: the final run's log said `dropped {'hallucination': 3, 'prompt_leak': 0}`, while `clean_segments()` on the pickled inputs of the same run returns 2 (80:13 "There's two ways to...", -0.94; 89:46 "Thank you for watching.", -0.97). Not explained; both listed drops are correct.
- Correction (2026-10-18, appended): the count of 3 was right. The pickle check ran as `python -c` with the source mounted on `PYTHONPATH`, and `-c` puts the working directory `/app` first on `sys.path`, so it imported the image's version-2 `engine.py`, which lacks the signature rule. The third drop is 91:47 "Thank you for watching." at -0.78, the one this plan added the rule for.
  Evidence: `raw.json` of meeting 2543 captured 2026-10-18 by `--capture-inputs`, filtered with the version-3 `is_hallucination()`: 4813 s "There's two ways to..." -0.94; 5387 s "Thank you for watching." -0.97; 5507 s "Thank you for watching." -0.78.

## Decision Log

- Decision: (superseded below) amend `0047` so that a one-word, unpunctuated run followed by a lowercase continuation is absorbed into the next run.
  Rationale: punctuation and case seemed to separate jitter from roll-call answers, and the synthetic roll-call test still paired nine.
  Date/Author: 2026-10-17, by hand.
- Decision: withdraw the absorption; `0047`'s no-smoothing clause stands, and `0052` records the merge and the rejected rule.
  Rationale: on 2543's real audio the one-word run was the correctly labelled member, and the absorption moved it to the clerk (Surprises).
  Date/Author: 2026-10-17, by hand.
- Decision: same-cluster segments are joined only when at most 1 s apart and the joined row is at most 30 s.
  Rationale: without a cap a long speech collapses into multi-minute rows; 30 s is the batched pipeline's chunk length.
  Date/Author: 2026-10-17, by hand.
- Decision: (superseded below) add Linn Park and Boutwell Auditorium to the vocabulary, first as a new sentence, then folded into two existing ones (575 characters) so that the Flock Safety sentence stays in the budget.
  Date/Author: 2026-10-17, by hand.
- Decision: withdraw the vocabulary change; `prompt.py` is as on `main`.
  Rationale: the new sentence leaked four times on the full audio. The folded variant was not run, and a rule that catches short leaks is a separate change.
  Date/Author: 2026-10-17, by hand.
- Decision: loudness normalization before VAD is not part of this change.
  Rationale: it changes every chunk boundary of every meeting and has a plausible failure (amplified noise on the silent cancelled-meeting streams crossing the 180-second low-speech floor) that needs checking on those streams first; it is the operator's call as a separate change.
  Date/Author: 2026-10-17, by hand.
- Decision: "Vassa" for Josh Vasa gets no change; the name is already in the prompt through the roster.
  Date/Author: 2026-10-17, by hand.

## Outcomes & Retrospective

2026-10-17: version 3 is the signature-phrase rule and the same-speaker merge. On the full audio of 2543, compared with the version-2 archive: speech rows 331 → 306, median 12.4 s → 14.3 s, rows of two words or fewer 28 → 21, back-to-back same-speaker pairs 24 → 0, `thank(s| you) for watching` 1 → 0, roll-call pairs 0 → 0, and no vocabulary-sentence rows. Not achieved: "Good morning." still splits at the roll call, because the diarizer gives most of the members' answers to the clerk (`D53` in `docs/DEBT.md`); the Jenkins comment is still silence, though now a clean gap rather than a hallucination. Lesson: both withdrawn rules passed their synthetic tests and failed on the first real audio, as `D56` predicted. The pickled inputs (`C:\docket-archive\work\2543_v3_inputs.pkl`: raw chunks with words, diarization turns, embeddings, and prompt) let later post-processing changes be replayed on real data without the GPU.

Reflection, appended 2026-10-19 by the doc-garden pass after plan `birmingham-city-briefing` (nothing above is reworded): this section did not say where the outcome is reflected. It is: `docs/specs/transcripts.md` describes version 3 (the signature-phrase rule and the same-speaker merge) under `TRANSCRIPT_VERSION` in present tense, and decision `0052` records why same-speaker segments are merged and split fragments are not absorbed.

## Context and Orientation

The producer in `transcriber/` runs on the operator's Windows GPU machine (the Legion) under Docker. `transcriber/transcriber/engine.py` holds the post-processing. `clean_segments()` drops hallucinated and prompt-leaked chunks, where a chunk is one roughly 28-second piece of faster-whisper output. `split_by_speaker()` cuts each kept chunk at every change of diarization cluster, where a cluster is one voice as pyannote labels it, such as `SPEAKER_07`. `build_output()` assembles the upload. `docs/specs/transcripts.md` "What the producer uploads" states these rules; decisions `0046`, `0047`, and `0052` record why.

## Plan of Work

In `engine.py`: add `SIGNATURE_LOGPROB` (-0.5) and `SIGNATURE_PHRASES`, move "thanks for watching" into the latter, add `has_signature_phrase()`, and in `is_hallucination()` drop a phrase-only chunk that contains a signature phrase at or below -0.5. Add `merge_same_speaker()` and call it in `build_output()` between the split and the silence markers. Set `TRANSCRIPT_VERSION = 3`. Tests go in `transcriber/tests/test_engine_postprocess.py` and `test_cli_loop.py`.

## Concrete Steps

From `C:/docket-pub/transcriber` in Git Bash, the suite runs in the producer image with the main package on the path, so the two roll-call tests are not skipped:

    MSYS_NO_PATHCONV=1 docker run --rm -v "C:/docket-pub:/repo" -w /repo/transcriber -e PYTHONPATH=/repo/src \
      --entrypoint bash transcriber-transcriber:latest -c "pip -q install pytest -r /repo/requirements.txt; python -m pytest -q"

## Validation and Acceptance

The suite passes with the roll-call tests running. On the full audio of meeting 2543, the version-3 output has 0 segments matching `thank(s| you) for watching`, no consecutive same-speaker rows within 1 s and 30 s, no row that is mostly a vocabulary sentence, and a roll-call pair count no lower than version 2's.

## Idempotence and Recovery

Nothing here writes to Postgres. The full-audio check writes only `C:\docket-archive\work\2543_v3.json` and a pickle of its inputs.

## Artifacts and Notes

`C:\docket-archive\work\` holds the VAD clips and outputs (`vad_ab.*`, `vad_norm.*`), the version-3 run (`v3_2543.py`, `2543_v3.json`, `2543_v3_inputs.pkl`), and the check scripts (`check.py`, `variants.py`, `leakscan.py`).

Observed 2026-10-17, suite in the producer image with `src/` on the path: `56 passed, 18 skipped` (the 18 are the Postgres-backed `test_db.py` tests; both roll-call tests ran). Final full-audio check (`check.py`, then `leakscan.py`):

    ### /archive/transcripts/2543/transcript.json  version=2
    segs=331 median=12.4s  <=2 words=28  mergeable same-speaker pairs=24  speakers=27
    for watching: 1
    roll-call pairs: 0
    ### /archive/work/2543_v3.json  version=3
    segs=306 median=14.3s  <=2 words=21  mergeable same-speaker pairs=0  speakers=26
    for watching: 0
    roll-call pairs: 0
    hits 0

## Interfaces and Dependencies

In `transcriber/transcriber/engine.py`: `merge_same_speaker(segs: list[Segment]) -> list[Segment]`, `has_signature_phrase(norm: str) -> bool`, and the constants `SIGNATURE_LOGPROB`, `SIGNATURE_PHRASES`, `MERGE_MAX_GAP_S`, `MERGE_MAX_S`. No new dependencies.

## Revision notes

- 2026-10-20, doc-garden pass after plan `member-votes-name-their-member`: the record this plan wrote as decision `0052` is `docs/decisions/0064-same-speaker-segments-are-merged-and-split-fragments-are-not-absorbed.md`. The number 0052 had already been spent by `docs/decisions/0052-main-requires-the-verify-check-to-merge.md` (pull request #124, merged the day before #125), so two records shared it on `main`; the transcriber record was renumbered and the entries above are unchanged.
