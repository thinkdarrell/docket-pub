"""Fixture bundles for the transcript stages: the real meeting 2543 export and the meeting 15 pilot."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from docket.db import db_cursor

FIXTURES = Path("tests/fixtures")
PILOT = FIXTURES / "transcript_pilot"
PILOT_CLIP_OFFSET_S = 3290.0   # expected.json: the clip starts about 3290 s into the full video

_SRT_TIME = re.compile(r"(\d+):(\d+):(\d+),(\d+) --> (\d+):(\d+):(\d+),(\d+)")


def _t(h, m, s, ms) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_srt(path: Path, *, offset_s: float = 0.0, cluster_label: str | None = None) -> list[dict]:
    out, seq = [], 0
    blocks = path.read_text().strip().split("\n\n")
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        m = _SRT_TIME.match(lines[1])
        if not m:
            continue
        g = m.groups()
        text = " ".join(l.strip() for l in lines[2:]).strip()
        out.append({"seq": seq, "start_s": round(_t(*g[:4]) + offset_s, 3), "end_s": round(_t(*g[4:]) + offset_s, 3),
                    "text": text, "cluster_label": cluster_label, "is_silence": False,
                    "avg_logprob": None, "no_speech_prob": None})
        seq += 1
    return out


@dataclass
class Bundle:
    meeting: dict
    agenda_items: list[dict]
    roster: list[dict]
    segments: list[dict]
    speakers: list[dict] = field(default_factory=list)
    votes: list[dict] = field(default_factory=list)
    minutes_text: str | None = None
    minutes_pages: list[int] | None = None


def load_bundle(name: str) -> Bundle:
    d = FIXTURES / name
    j = lambda f: json.loads((d / f).read_text())
    minutes = (d / "minutes.txt").read_text() if (d / "minutes.txt").exists() else None
    pages = j("minutes_pages.json") if (d / "minutes_pages.json").exists() else None
    return Bundle(meeting=j("meeting.json"), agenda_items=j("agenda_items.json"), roster=j("roster.json"),
                  segments=j("segments.json"), speakers=j("speakers.json"),
                  votes=j("votes.json") if (d / "votes.json").exists() else [],
                  minutes_text=minutes, minutes_pages=pages)


PILOT_ROSTER_2026 = ["Darrell O'Quinn", "Wardine Alexander", "LaTonya Tate", "Clinton Woods", "J.T. Moore",
                     "Carol Clarke", "Crystal Smitherman", "Hunter Williams", "Valerie Abbott"]


def pilot_bundle() -> Bundle:
    raw = (PILOT / "2026-02-17_clip1950_minutes.txt").read_text()
    pages_text = raw.split("\f")
    offsets, pos = [], 0
    for p in pages_text:
        offsets.append(pos)
        pos += len(p) + 1
    text = "\n".join(pages_text)
    return Bundle(
        meeting={"id": 15, "external_id": "1950", "title": "City Council Meeting", "meeting_date": "2026-02-17",
                 "meeting_type": "council",
                 "video_url": "https://bhamal.granicus.com/MediaPlayer.php?view_id=2&clip_id=1950",
                 "minutes_url": "https://bhamal.granicus.com/MinutesViewer.php?view_id=2&clip_id=1950",
                 "transcript": {"version": 1, "engine": "whisper.cpp", "asr_model": "ggml-small.en",
                                "diarization_model": None, "audio_duration_s": 530.6, "speech_ratio": 0.9,
                                "word_count": 650}},
        agenda_items=[{"id": 1501, "external_id": "1950-15", "item_number": "15",
                       "title": "Ordinance: CJI access security agreement with ALEA and Alabama Power",
                       "is_consent": False, "video_timestamp_seconds": 3309.0}],
        roster=[{"id": 9000 + i, "name": n} for i, n in enumerate(PILOT_ROSTER_2026)],
        segments=parse_srt(PILOT / "2026-02-17_clip1950_item15_small-en.srt", offset_s=PILOT_CLIP_OFFSET_S,
                           cluster_label="S0"),
        speakers=[{"cluster_label": "S0", "council_member_id": None, "display_name": None, "role": None,
                   "confidence": None, "method": None, "is_manual": False}],
        votes=[],
        minutes_text=text, minutes_pages=offsets,
    )


@dataclass
class Installed:
    meeting_id: int
    transcript_id: int
    item_ids: dict[int, int]
    member_ids: dict[int, int]
    _inserted_members: list[int]

    def cleanup(self) -> None:
        with db_cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE id=%s", [self.meeting_id])   # cascades to every transcript table
            if self._inserted_members:
                cur.execute("DELETE FROM council_members WHERE id = ANY(%s)", [self._inserted_members])


def install_bundle(b: Bundle, *, status: str = "uploaded", external_id: str = "999543") -> Installed:
    tr = b.meeting["transcript"]
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug='birmingham'")
        muni = cur.fetchone()["id"]
        member_ids, inserted = {}, []
        for m in b.roster:
            cur.execute("SELECT id FROM council_members WHERE municipality_id=%s AND name=%s ORDER BY id LIMIT 1",
                        [muni, m["name"]])
            row = cur.fetchone()
            if row:
                member_ids[m["id"]] = row["id"]
            else:
                cur.execute("""INSERT INTO council_members (municipality_id, name, term_start, active)
                               VALUES (%s, %s, '2025-10-28', TRUE) RETURNING id""", [muni, m["name"]])
                member_ids[m["id"]] = cur.fetchone()["id"]; inserted.append(member_ids[m["id"]])
        cur.execute("""INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type, external_id, video_url, minutes_url)
                       VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                    [muni, b.meeting["title"], b.meeting["meeting_date"], b.meeting.get("meeting_type") or "council",
                     external_id, b.meeting.get("video_url"), b.meeting.get("minutes_url")])
        mid = cur.fetchone()["id"]
        cur.execute("INSERT INTO processing_status (meeting_id) VALUES (%s)", [mid])
        item_ids = {}
        for it in b.agenda_items:
            cur.execute("""INSERT INTO agenda_items (meeting_id, external_id, item_number, title, is_consent, video_timestamp_seconds)
                           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
                        [mid, it.get("external_id"), it.get("item_number"), it["title"], bool(it.get("is_consent")),
                         it.get("video_timestamp_seconds")])
            item_ids[it["id"]] = cur.fetchone()["id"]
        cur.execute("""INSERT INTO transcripts (meeting_id, status, version, engine, asr_model, diarization_model,
                                                audio_duration_s, speech_ratio, word_count, uploaded_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now()) RETURNING id""",
                    [mid, status, tr["version"], tr.get("engine"), tr.get("asr_model"), tr.get("diarization_model"),
                     tr.get("audio_duration_s"), tr.get("speech_ratio"), tr.get("word_count")])
        tid = cur.fetchone()["id"]
        sp_ids = {}
        for sp in b.speakers:
            cur.execute("""INSERT INTO transcript_speakers (meeting_id, cluster_label, council_member_id, display_name, role,
                                                            confidence, method, is_manual)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                        [mid, sp["cluster_label"], member_ids.get(sp.get("council_member_id")), sp.get("display_name"),
                         sp.get("role"), sp.get("confidence"), sp.get("method"), bool(sp.get("is_manual"))])
            sp_ids[sp["cluster_label"]] = cur.fetchone()["id"]
        for s in b.segments:
            cur.execute("""INSERT INTO transcript_segments (transcript_id, seq, start_s, end_s, text, cluster_label, speaker_id,
                                                            is_silence, avg_logprob, no_speech_prob)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        [tid, s["seq"], s["start_s"], s["end_s"], s["text"], s.get("cluster_label"),
                         sp_ids.get(s.get("cluster_label")), bool(s.get("is_silence")), s.get("avg_logprob"),
                         s.get("no_speech_prob")])
        for v in b.votes:
            cur.execute("""INSERT INTO votes (meeting_id, external_id, result, yeas, nays, abstentions, source, raw_text)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                        [mid, v.get("external_id"), v["result"], v.get("yeas"), v.get("nays"), v.get("abstentions"),
                         v.get("source") or "minutes_text", v.get("raw_text")])
            vid = cur.fetchone()["id"]
            for link in v.get("links") or []:
                if link["agenda_item_id"] in item_ids:
                    cur.execute("""INSERT INTO vote_agenda_items (vote_id, agenda_item_id, association_type, match_confidence)
                                   VALUES (%s, %s, %s, 1.0)""", [vid, item_ids[link["agenda_item_id"]], link["association_type"]])
        if b.minutes_text is not None:
            cur.execute("""INSERT INTO minutes_texts (meeting_id, source_url, pdf_sha256, text, page_offsets)
                           VALUES (%s, %s, 'fixture', %s, %s::jsonb)""",
                        [mid, b.meeting.get("minutes_url"), b.minutes_text, json.dumps(b.minutes_pages or [0])])
    return Installed(mid, tid, item_ids, member_ids, inserted)
