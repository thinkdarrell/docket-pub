# Keep each meeting's audio and GPU-stage outputs in the archive, and replay post-processing on the CPU

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `plans/PLANS.md`.

## Purpose / Big Picture

The version-3 backlog re-run (2026-10-18, 47 meetings, about 4½ hours) downloaded every recording again and re-ran speech recognition and diarization, though version 3 changed only post-processing. After this change the producer keeps `audio.flac`, `raw.json`, and `diarization.json` in each meeting's archive folder. A re-run then skips the download, and a post-processing change can be checked on every archived meeting in seconds with `--replay`, with no GPU or database. Two passes, `--cache-audio` and `--capture-inputs`, fill the archive for meetings transcribed before the change without claiming or uploading anything. Done by hand in one milestone on branch `feat/transcriber-input-cache`.

## Progress

- [x] (2026-10-18 21:20Z) `transcriber/transcriber/inputs.py` (paths, `get_audio`, `store_flac`, raw/diarization read and write, `replay`); `meeting_source()` in `db.py`; `process_claim()` uses the cache and writes both files; `--cache-audio`, `--capture-inputs`, `--replay` in `cli.py`; `__version__` 0.4.0.
- [x] (2026-10-18 21:22Z) `transcriber/tests/test_inputs.py`, 10 tests; the suite prints `66 passed, 18 skipped`.
- [x] (2026-10-18 21:29Z) On the Legion, image `transcriber-cache:test`: `--cache-audio 2543`, `--capture-inputs 2543`, `--replay 2543` (Artifacts).
- [x] (2026-10-18 21:40Z) Spec, runbook, README, decision `0053`; correction appended to `plans/completed/transcriber-v3-quick-wins.md`.
- [ ] Pull request; after merge, `--cache-audio` then `--capture-inputs` for the 47 version-3 meetings (2543 is done).

## Surprises & Discoveries

- Observation: the replay of freshly captured inputs matched the uploaded transcript exactly, so on this meeting the GPU stages are deterministic run to run.
  Evidence: `live 306 replay 306 identical rows 306`, `word-level similarity 1.0 11380 11380`, `same speaker labels 26 26`.
- Observation: `python -c` inside the producer image imports the image's own `/app/transcriber`, not a mounted source on `PYTHONPATH`, because `-c` puts the working directory first on `sys.path`. That is what made the previous plan's hallucination count read 2 instead of 3 (correction appended there). Run checks as script files, or mount the source over `/app/transcriber`.

## Decision Log

- Decision: FLAC, not the WAV. Rationale: lossless at about 55 percent of the WAV size (110 MB against 200 MB for 2543's 104 minutes), and the decoded WAV hashes the same. Date/Author: 2026-10-18, by hand.
- Decision: the cache never fails a meeting; a write failure is logged, an undecodable file is deleted and fetched again. Rationale: it is a convenience, and a broken copy that a later run trusted would be worse than none. Date/Author: 2026-10-18, by hand.
- Decision: the passes take several meeting ids. Rationale: the models load once per pass rather than once per meeting (about 30 to 60 seconds each). Date/Author: 2026-10-18, by hand.
- Decision: `TRANSCRIPT_VERSION` stays 3. Rationale: the output is unchanged; only `__version__` moves. Date/Author: 2026-10-18, by hand.

## Outcomes & Retrospective

On meeting 2543: `--cache-audio` fetched 110 MB of FLAC whose decoded WAV has the download's SHA-256; `--capture-inputs` took about 4 minutes with no download; `--replay` rebuilt the uploaded transcript row for row in under a second. What remains is the archive fill for the other 47 version-3 meetings after the merge.

## Context and Orientation

The producer in `transcriber/` runs under Docker on the operator's GPU machine. `cli.py` `process_claim()` fetches a meeting's audio, runs `engine.transcribe()` (Whisper) and `engine.diarize()` (pyannote), and passes their outputs to `build_output()` in `engine.py`, which applies the post-processing. The archive is `/archive/transcripts/<id>/` in the container, the host folder `C:\docket-archive\transcripts\<id>\`.

## Plan of Work

As in Progress. `inputs.get_audio(source, wav, flac, fetch=...)` decodes the FLAC when present and otherwise fetches and keeps one. `process_claim()` writes `raw.json` right after transcription and `diarization.json` right after diarization. The three modes are mutually exclusive argparse options in `main()`: replay runs before any database URL check or model load, cache-audio opens the database but loads no model, and capture-inputs loads the models and only reads the database.

## Concrete Steps

From `C:/docket-pub/transcriber` on the Legion after the merge (`git pull`, `docker compose build`):

    docker compose run --rm transcriber --cache-audio <ids>
    docker compose run --rm transcriber --capture-inputs <ids>
    docker compose run --rm transcriber --replay <ids>

## Validation and Acceptance

The suite passes (`66 passed, 18 skipped`, the skips being Postgres-backed `test_db.py`). On 2543 the decoded FLAC hashes to the transcript's `audio_sha256`, and `--replay` reproduces the uploaded transcript.

## Idempotence and Recovery

All three passes are safe to repeat: `--cache-audio` skips a meeting whose `audio.flac` exists, `--capture-inputs` overwrites its two files, `--replay` overwrites only `replay.json`. None writes to Postgres.

## Artifacts and Notes

    INFO transcriber: cache-audio done {2543: 'fetched'}
    ad43315f67158a689508369707ee8310b1242915af639c79f2c771b16b5f226b  /tmp/x.wav   (transcript's audio_sha256)
    INFO transcriber: capture-inputs done {2543: 'captured'} oom_fallbacks=0
    INFO transcriber: meeting 2543: replayed 306 segments, 26 speakers -> /archive/transcripts/2543/replay.json
    live 306 replay 306 identical rows 306

## Interfaces and Dependencies

`transcriber/transcriber/inputs.py`: `audio_path`, `raw_path`, `diarization_path`, `get_audio`, `store_flac`, `write_raw`, `read_raw`, `write_diarization`, `read_diarization`, `replay`. `transcriber/transcriber/db.py`: `meeting_source(conn, meeting_id) -> str | None`. `transcriber/transcriber/cli.py`: `cache_audio`, `capture_inputs`, `replay_meeting`. ffmpeg's built-in FLAC encoder; no new Python dependency.

## Revision notes

- 2026-10-20, doc-garden pass after plan `member-votes-name-their-member`: the record this plan wrote as decision `0053` is `docs/decisions/0065-the-archive-keeps-each-meetings-audio-and-gpu-stage-outputs.md`. The number 0053 had already been spent by `docs/decisions/0053-the-deny-list-guards-stated-norms-and-is-not-a-containment-boundary.md` (pull request #124, merged before #126), so two records shared it on `main`; the transcriber record was renumbered and the entries above are unchanged.
