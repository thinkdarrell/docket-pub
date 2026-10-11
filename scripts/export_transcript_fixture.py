#!/usr/bin/env python
# scripts/export_transcript_fixture.py
"""Export one meeting's transcript rows as a test fixture bundle (read-only).

    DATABASE_URL=$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-) \
      venv/bin/python scripts/export_transcript_fixture.py --meeting-id 2543 --out tests/fixtures/transcript_2543

Embeddings are dropped (they are phase 2 input and large). Minutes text is
included only when the minutes PDF downloads; the pipeline's own extractor
(docket.ai.transcripts.minutes) does the page-aware extraction so the fixture
matches production byte-for-byte.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from docket.db import db_cursor


def _rows(cur, sql, params):
    cur.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def export(meeting_id: int, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with db_cursor() as cur:
        meeting = _rows(cur, """SELECT id, external_id, title, meeting_date::text, meeting_type, video_url,
                                        minutes_url, agenda_url FROM meetings WHERE id=%s""", [meeting_id])[0]
        items = _rows(cur, """SELECT id, external_id, item_number, title, is_consent, video_timestamp_seconds
                                FROM agenda_items WHERE meeting_id=%s ORDER BY video_timestamp_seconds NULLS LAST, id""",
                      [meeting_id])
        roster = _rows(cur, """SELECT cm.id, cm.name FROM council_members cm JOIN meetings m ON m.municipality_id = cm.municipality_id
                                WHERE m.id=%s AND m.meeting_date >= cm.term_start
                                  AND m.meeting_date < COALESCE(cm.term_end, m.meeting_date + INTERVAL '1 day')
                                ORDER BY cm.name""", [meeting_id])
        segs = _rows(cur, """SELECT s.seq, s.start_s, s.end_s, s.text, s.cluster_label, s.is_silence,
                                    s.avg_logprob, s.no_speech_prob
                               FROM transcript_segments s JOIN transcripts t ON t.id = s.transcript_id
                              WHERE t.meeting_id=%s ORDER BY s.seq""", [meeting_id])
        speakers = _rows(cur, """SELECT cluster_label, council_member_id, display_name, role, confidence, method, is_manual
                                   FROM transcript_speakers WHERE meeting_id=%s ORDER BY cluster_label""", [meeting_id])
        tr = _rows(cur, """SELECT version, engine, asr_model, diarization_model, audio_duration_s, speech_ratio, word_count
                             FROM transcripts WHERE meeting_id=%s""", [meeting_id])[0]
        votes = _rows(cur, """SELECT v.id, v.external_id, v.result, v.yeas, v.nays, v.abstentions, v.source, v.raw_text,
                                     COALESCE(json_agg(json_build_object('agenda_item_id', vai.agenda_item_id,
                                              'association_type', vai.association_type)) FILTER (WHERE vai.id IS NOT NULL), '[]') AS links
                                FROM votes v LEFT JOIN vote_agenda_items vai ON vai.vote_id = v.id AND vai.is_active
                               WHERE v.meeting_id=%s GROUP BY v.id ORDER BY v.id""", [meeting_id])
    meeting["transcript"] = tr
    (out / "meeting.json").write_text(json.dumps(meeting, indent=1, default=str))
    (out / "agenda_items.json").write_text(json.dumps(items, indent=1, default=str))
    (out / "roster.json").write_text(json.dumps(roster, indent=1))
    (out / "segments.json").write_text(json.dumps(segs, indent=1, default=str))
    (out / "speakers.json").write_text(json.dumps(speakers, indent=1, default=str))
    (out / "votes.json").write_text(json.dumps(votes, indent=1, default=str))
    if meeting.get("minutes_url"):
        try:
            from docket.ai.transcripts.minutes import download_minutes, extract_pages
        except ImportError:
            print("minutes skipped: module not yet available")
        else:
            pdf = download_minutes(meeting["minutes_url"])
            if pdf:
                text, offsets = extract_pages(pdf)
                (out / "minutes.txt").write_text(text)
                (out / "minutes_pages.json").write_text(json.dumps(offsets))
    print(f"exported meeting {meeting_id}: {len(segs)} segments, {len(speakers)} clusters, {len(items)} items -> {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--meeting-id", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    export(a.meeting_id, a.out)
