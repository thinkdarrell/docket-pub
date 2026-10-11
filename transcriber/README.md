# docket.pub transcript producer (Lenovo Legion)

GPU-only. Fetches Birmingham council audio from Granicus, runs faster-whisper
large-v3 and pyannote diarization, and uploads raw segments to Railway Postgres
as the narrow `transcriber` role. All thinking (names, events, comparison)
happens on the Railway worker.

## One-time setup on Windows

1. Install Docker Desktop; enable the WSL2 backend and GPU support
   (Settings → Resources → WSL integration). Install the NVIDIA Windows driver
   (Blackwell needs 570+). Nothing else is installed on Windows.
2. Copy `scripts/wslconfig.example` to `%UserProfile%\.wslconfig`, then run
   `wsl --shutdown` once. This caps WSL2 at 16 GB and reclaims memory.
3. Power plan: Settings → System → Power → "Never" sleep when plugged in;
   allow wake timers. A sleeping desktop is the most likely cause of a quiet week.
4. Create `C:\docket-archive` (the host bind mount). Audio is written and
   deleted there, so the WSL2 virtual disk never grows.
5. `copy .env.example .env` and fill in the transcriber DB URL (from the
   operator who ran `scripts/sql/create_transcriber_role.sql`) and a Hugging
   Face token that has accepted the pyannote 3.1 model terms.
6. `docker compose build` (10 minutes; downloads CUDA 12.8 torch wheels).
7. Bring-up: put a short clip at `C:\docket-archive\clips\pilot.mp4` and run
   `docker compose run --rm --entrypoint bash transcriber scripts/bringup.sh /archive/clips/pilot.mp4`
   Expect `BRING-UP OK` and a JSON file under `C:\docket-archive\transcripts\dry_run\`.
   If the CTranslate2 assertion fails, Blackwell kernels are missing from the
   wheel: set `TRANSCRIBER_DEVICE=cuda` with `--compute-type int8_float16`
   first; if that also fails, open an issue to swap `FasterWhisperEngine` for
   the WhisperX PyTorch path (one class, same `Engine` protocol).

## Running

    docker compose run --rm transcriber --since 2025-10-28 --limit 10 --max-hours 3

The run stops after 5 consecutive failures (`--max-consecutive-failures`, env `TRANSCRIBER_MAX_CONSECUTIVE_FAILURES`).
Ctrl-C finishes the current meeting and exits. Re-running is always safe: a
meeting left in `transcribed` uploads without touching the GPU; a claim older
than six hours is reclaimed. Failed meetings are not reclaimed automatically.

`--retry-failed` (env `TRANSCRIBER_RETRY_FAILED`) re-queues meetings marked failed (for example after a Granicus outage); `low_speech` meetings are terminal by design and are not retried.

An upload is public immediately: `uploaded` is one of the site's public
statuses, so the transcript page goes live at
`/al/birmingham/meetings/<id>/transcript/` as soon as a meeting finishes, with
speakers shown as "Speaker N" until the worker resolves names. There is no
review step between the producer and the site; hide a bad meeting through the
admin (`is_hidden`), which the `transcriber` role cannot do.

Operating from PowerShell on the Legion:

- Docker's progress lines arrive on stderr, so PowerShell wraps them as
  `NativeCommandError`. That is noise, not a failure; check the exit code and
  the final `done {...}` line.
- The log is full of torchaudio deprecation warnings. They are expected with the
  2.8 pin and harmless.
- Check the Hugging Face token before blaming the pipeline:
  `https://huggingface.co/api/whoami-v2` with `Authorization: Bearer <token>` must
  return 200, and the account must have accepted both pyannote model terms.
- `git push` from the Legion needs an interactive GitHub sign-in (Git Credential
  Manager); a push started in the background waits on it forever. In Git Bash
  write paths with forward slashes (`C:/docket-pub`).

Task Scheduler (optional): a basic task "At log on" running
`docker compose -f C:\path\to\transcriber\docker-compose.yml run --rm transcriber --max-hours 4`.

## Where things land

- `C:\docket-archive\transcripts\<meeting_id>\transcript.json` — the upload contract (kept)
- `C:\docket-archive\transcripts\<meeting_id>\words.json` — word timestamps (kept, never uploaded)
- `C:\docket-archive\work\*.wav` — audio, deleted after each meeting

## What to expect

- **Speed.** Roughly 15x to 20x real time including the Granicus download, so a
  three-hour meeting takes about ten minutes. A `--limit 10` batch of typical
  meetings fits well inside `--max-hours 3`.
- **Consent items are mostly silent.** The chair announces consent items by
  number only, so most agenda titles never appear in the audio. Items pulled
  from consent, roll calls, and items added at the meeting are spoken in full.
- **Stray pre-meeting clips.** Granicus sometimes lists a short test recording,
  dated the Monday before the Tuesday meeting, as a "Regular City Council
  Meeting". Silent ones end as `low_speech`. A clip of continuous mic checks can
  clear the three-minute speech floor and upload as a public transcript; hide it
  in the admin. The lasting fix is upstream, in the meeting import. Long silent
  clips may also show on the data-debt page as transcript problems.
- **Speaker clusters run high.** pyannote tends to split one person across two
  clusters, so a council meeting with public comment can show 20+ speakers.
  Merging is the worker's speaker-resolution job.
- **The roster prompt helps but doesn't guarantee spelling.** Whisper can still
  misspell a councilor's name consistently (for example "Vassa" for Vasa).
  Correction happens in speaker resolution, not here.
- **Items added at the meeting aren't in the agenda data.** `agenda_items` holds
  only the published agenda, so an item added from the floor exists only in
  the transcript.

## Local development (laptop, no GPU)

    pip install -r requirements-dev.txt && pytest
    TRANSCRIBER_DEVICE=cpu python -m transcriber.cli --dry-run /path/to/any-30s-clip.mp4 --model small.en

No clip is committed; supply any short meeting clip of your own at that path.

## Bring-up log

2026-10-10, Lenovo Legion (Windows 11, Docker Desktop 29.8.2, NVIDIA driver 610.60). Result: **pass**.

    torch 2.8.0+cu128 cuda 12.8 available True
    device NVIDIA GeForce RTX 5070 Ti capability (12, 0)
    ctranslate2 4.8.2 cuda devices 1
    /archive/transcripts/dry_run/pilot.json
    BRING-UP OK
    real 0m35.498s

Pilot clip: 2026-02-17 council meeting excerpt, 530.6 s audio (456 s speech) in 35.5 s
wall-clock (~15x real time), large-v3 float16, 10 segments, 4 diarized speakers.
Models were already cached; first run adds the large-v3 and pyannote downloads.

No CTranslate2 fallback was needed: the prebuilt 4.8.2 wheel sees the Blackwell GPU at
the default compute type. Three dependency fixes were needed first, all because
unpinned installs pulled releases newer than pyannote.audio 3.x supports:

- torch/torchaudio pinned to 2.8.0: torchaudio 2.9+ removed `AudioMetaData`
  (`AttributeError` on `import pyannote.audio`).
- huggingface_hub pinned `<1.0`: hub 1.0 removed `use_auth_token`, which pyannote 3.x
  passes to `hf_hub_download` (`TypeError`).
- `engine.py` allowlists the four globals the segmentation-3.0 checkpoint pickles
  (`TorchVersion`, `Specifications`, `Problem`, `Resolution`) for torch's
  weights-only loading, instead of disabling it (`UnpicklingError`).
