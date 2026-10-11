# transcript_2543 fixture

Real transcript rows for Birmingham City Council, Regular City Council Meeting,
2026-10-06 (docket.pub meeting id 2543, Granicus clip id 2016; see `meeting.json`).

- Transcribed on the Legion on 2026-10-10 with faster-whisper large-v3 and pyannote 3.1 diarization.
- Exported on 2026-10-10 with `scripts/export_transcript_fixture.py --meeting-id 2543` (read-only, production).
- Speaker embeddings are dropped.
- `minutes.txt` and `minutes_pages.json` are absent because the minutes were not yet adopted
  (`minutes_url` is null at export time).
- Load with `tests.support.transcript_fixtures.load_bundle("transcript_2543")`.
