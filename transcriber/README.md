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

Ctrl-C finishes the current meeting and exits. Re-running is always safe: a
meeting left in `transcribed` uploads without touching the GPU; a claim older
than six hours is reclaimed.

Task Scheduler (optional): a basic task "At log on" running
`docker compose -f C:\path\to\transcriber\docker-compose.yml run --rm transcriber --max-hours 4`.

## Where things land

- `C:\docket-archive\transcripts\<meeting_id>\transcript.json` — the upload contract (kept)
- `C:\docket-archive\transcripts\<meeting_id>\words.json` — word timestamps (kept, never uploaded)
- `C:\docket-archive\work\*.wav` — audio, deleted after each meeting

## Local development (laptop, no GPU)

    pip install -r requirements-dev.txt && pytest
    TRANSCRIBER_DEVICE=cpu python -m transcriber.cli --dry-run /path/to/any-30s-clip.mp4 --model small.en

No clip is committed; supply any short meeting clip of your own at that path.
