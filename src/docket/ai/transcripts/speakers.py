"""Speaker resolution: deterministic signals + Sonnet 5.5 judgment, written to transcript_speakers.

Diarization over-clusters (24 clusters on a 104-minute meeting), so this stage
expects many clusters per person and resolves each cluster independently; two
clusters resolved to the same member is the merge. Signals (spec Section 3):
roll-call pairs, chair addresses, self-identification, sampled utterances.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from pydantic import ValidationError

from docket.ai.exceptions import TranscriptHeld
from docket.ai.transcripts.guard import normalize
from docket.ai.transcripts.prompts import SPEAKER_SYSTEM
from docket.ai.transcripts.schemas import SPEAKER_SCHEMA, SpeakerAssignment, SpeakerResolution
from docket.config import AI_TRANSCRIPT_SPEAKER_MODEL, TRANSCRIPT_TOKEN_CEILING
from docket.db import db_cursor

log = logging.getLogger(__name__)

RESPONSE_WORDS = {"here", "present", "yes", "no", "aye", "nay", "yeah"}
_TITLE_RE = re.compile(r"\b(council\s*(?:or|member|man|woman)|councilmember|councilor|president|pro\s*tem|"
                       r"madam|mister|mr|ms|mrs|dr)\b", re.I)
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
# A title+name inside a back-reference ("as Councilor Tate said earlier") is a mention, not an address.
_REFERENCE_WORDS = {"said", "says", "mentioned", "stated", "noted", "earlier", "previously"}


@dataclass(frozen=True)
class RosterMember:
    id: int
    name: str
    surname: str


def surname(name: str) -> str:
    toks = [t for t in re.split(r"[\s,]+", name.strip()) if t]
    while toks and re.sub(r"\W", "", toks[-1]).lower() in _SUFFIXES:
        toks.pop()
    return re.sub(r"[^a-z]", "", toks[-1].lower()) if toks else ""


def roster_for_meeting(meeting_id: int) -> list[RosterMember]:
    with db_cursor() as cur:
        cur.execute(
            """SELECT cm.id, cm.name
                 FROM council_members cm
                 JOIN meetings m ON m.municipality_id = cm.municipality_id
                WHERE m.id = %s
                  AND m.meeting_date >= cm.term_start
                  AND m.meeting_date < COALESCE(cm.term_end, m.meeting_date + INTERVAL '1 day')
                ORDER BY cm.name, cm.id""",
            [meeting_id],
        )
        return [RosterMember(r["id"], r["name"], surname(r["name"])) for r in cur.fetchall()]


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z]+", normalize(text))


def mentioned_members(text: str, roster: list[RosterMember]) -> list[RosterMember]:
    """Surname hits in the text, tolerant of ASR spelling ("O Quinn", "Smithermann")."""
    toks = _tokens(text)
    joined = {toks[i] + toks[i + 1] for i in range(len(toks) - 1)} | set(toks)   # "o quinn" -> "oquinn"
    hits: list[RosterMember] = []
    for m in roster:
        if m.surname in joined:
            hits.append(m)
            continue
        if len(m.surname) >= 5 and any(len(t) >= 5 and SequenceMatcher(None, t, m.surname).ratio() >= 0.85
                                        for t in joined):
            hits.append(m)
    return hits


def is_short_response(text: str) -> bool:
    toks = _tokens(text)
    return 0 < len(toks) <= 3 and any(t in RESPONSE_WORDS for t in toks)


def is_substantive(text: str) -> bool:
    return len(_tokens(text)) >= 8


def _speech(segments: list[dict]) -> list[dict]:
    return [s for s in segments if not s.get("is_silence") and (s.get("text") or "").strip()]


@dataclass
class RollCallPair:
    name_seq: int
    name_text: str
    member: RosterMember
    response_seq: int
    response_cluster: str | None
    response_text: str


def find_roll_call_pairs(segments: list[dict], roster: list[RosterMember], max_gap_s: float = 8.0) -> list[RollCallPair]:
    segs = _speech(segments)
    out: list[RollCallPair] = []
    for i, s in enumerate(segs):
        hits = mentioned_members(s["text"], roster)
        if len(hits) != 1 or len(_tokens(s["text"])) > 6:
            continue   # a roll call reads one short name at a time
        for nxt in segs[i + 1:i + 4]:
            if nxt["start_s"] - s["end_s"] > max_gap_s:
                break
            if nxt.get("cluster_label") == s.get("cluster_label"):
                if mentioned_members(nxt["text"], roster):
                    break          # the reader moved on to the next name: this member did not answer
                continue
            # The first utterance from another cluster is the only candidate response.
            if is_short_response(nxt["text"]):
                out.append(RollCallPair(s["seq"], s["text"], hits[0], nxt["seq"], nxt.get("cluster_label"), nxt["text"]))
            break
    return out


@dataclass
class ChairAddress:
    address_seq: int
    address_text: str
    member: RosterMember
    next_seq: int
    next_cluster: str | None
    next_text: str


def find_chair_addresses(segments: list[dict], roster: list[RosterMember], max_gap_s: float = 20.0) -> list[ChairAddress]:
    """A member named with a title (or a question), then the next SUBSTANTIVE utterance from another cluster.

    Interjections of three words or fewer (a cough, "thank you", a mic bump)
    are skipped and the following cluster is considered instead.
    """
    segs = _speech(segments)
    out: list[ChairAddress] = []
    for i, s in enumerate(segs):
        hits = mentioned_members(s["text"], roster)
        if len(hits) != 1 or not (_TITLE_RE.search(s["text"]) or "?" in s["text"]):
            continue
        if _REFERENCE_WORDS & set(_tokens(s["text"])):
            continue
        for nxt in segs[i + 1:i + 5]:
            if nxt["start_s"] - s["end_s"] > max_gap_s:
                break
            if nxt.get("cluster_label") == s.get("cluster_label"):
                continue
            if len(_tokens(nxt["text"])) <= 3:
                continue          # interjection; keep looking
            if is_substantive(nxt["text"]):
                out.append(ChairAddress(s["seq"], s["text"], hits[0], nxt["seq"], nxt.get("cluster_label"), nxt["text"]))
            break                 # a non-substantive, non-interjection reply ends the search either way
    return out


@dataclass(frozen=True)
class ClusterStats:
    label: str
    speaking_s: float
    utterances: int
    first_s: float
    words: int


def cluster_stats(segments: list[dict]) -> dict[str, ClusterStats]:
    acc: dict[str, list] = {}
    for s in _speech(segments):
        cl = s.get("cluster_label")
        if cl is None:
            continue
        a = acc.setdefault(cl, [0.0, 0, s["start_s"], 0])
        a[0] += s["end_s"] - s["start_s"]
        a[1] += 1
        a[3] += len(s["text"].split())
    return {cl: ClusterStats(cl, round(a[0], 1), a[1], a[2], a[3]) for cl, a in acc.items()}


def sample_utterances(segments: list[dict], per_cluster: int = 6, min_words: int = 6,
                      max_words: int = 60) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = {}
    for s in _speech(segments):
        if s.get("cluster_label") is None or len(s["text"].split()) < min_words:
            continue
        by.setdefault(s["cluster_label"], []).append(s)
    out: dict[str, list[dict]] = {}
    for cl, utts in by.items():
        n = len(utts)
        if n <= per_cluster:
            idxs = list(range(n))
        else:
            idxs = sorted({round(i * (n - 1) / (per_cluster - 1)) for i in range(per_cluster)}) if per_cluster > 1 else [0]
        out[cl] = [{"seq": utts[i]["seq"], "start_s": utts[i]["start_s"],
                    "text": " ".join(utts[i]["text"].split()[:max_words])} for i in idxs]
    return out


@dataclass
class SpeakerPacket:
    roster: list[RosterMember]
    roll_calls: list[RollCallPair]
    addresses: list[ChairAddress]
    stats: dict[str, ClusterStats]
    samples: dict[str, list[dict]] = field(default_factory=dict)


def build_packet(segments: list[dict], roster: list[RosterMember]) -> SpeakerPacket:
    return SpeakerPacket(roster, find_roll_call_pairs(segments, roster), find_chair_addresses(segments, roster),
                         cluster_stats(segments), sample_utterances(segments))


def hms(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def render_speaker_user(packet: SpeakerPacket, meeting: dict) -> str:
    lines = [f"Meeting: {meeting.get('title')} on {meeting.get('meeting_date')} (meeting id {meeting.get('id')})", "",
             "Roster seated on this date (council_member_id: name):"]
    lines += [f"  {m.id}: {m.name}" for m in packet.roster]
    lines += ["", "Roll-call candidate pairs (a name read, then a short response from another cluster):"]
    lines += [f'  [seq={p.name_seq}] "{p.name_text}" -> [seq={p.response_seq} cluster {p.response_cluster}] "{p.response_text}"'
              for p in packet.roll_calls] or ["  (none found)"]
    lines += ["", "Chair addresses (a member named with a title, then a substantive utterance from another cluster):"]
    lines += [f'  [seq={a.address_seq}] "{a.address_text}" -> [seq={a.next_seq} cluster {a.next_cluster}] "{a.next_text}"'
              for a in packet.addresses] or ["  (none found)"]
    lines += ["", "Clusters, in order of first appearance, with sampled utterances:"]
    for cl, st in packet.stats.items():
        lines.append(f"\n{cl}: {st.speaking_s:.0f} s speaking, {st.utterances} utterances, {st.words} words, first heard {hms(st.first_s)}")
        for u in packet.samples.get(cl, []):
            lines.append(f'  [seq={u["seq"]} t={hms(u["start_s"])}] "{u["text"]}"')
        if not packet.samples.get(cl):
            lines.append("  (no utterance of six words or more)")
    lines += ["", f"Return exactly {len(packet.stats)} assignments, one per cluster label above, in this order: "
              + ", ".join(packet.stats)]
    return "\n".join(lines)


# --- stage ------------------------------------------------------------------
CONFIDENCE_CAPS = {"two_signals": 0.95, "one_signal": 0.75, "sample_inference": 0.55}
_DB_METHOD = {"roll_call": "roll_call", "addressed_by_chair": "addressed_by_chair",
              "self_identification": "llm_inference", "sample_inference": "llm_inference"}


def load_speech_segments(transcript_id: int) -> list[dict]:
    with db_cursor() as cur:
        cur.execute("""SELECT seq, start_s, end_s, text, cluster_label, is_silence
                         FROM transcript_segments
                        WHERE transcript_id = %s AND is_silence = FALSE AND text <> ''
                        ORDER BY seq""", [transcript_id])
        return [dict(r) for r in cur.fetchall()]


def _meeting(meeting_id: int) -> dict:
    with db_cursor() as cur:
        cur.execute("SELECT id, title, meeting_date::text FROM meetings WHERE id = %s", [meeting_id])
        return dict(cur.fetchone())


def apply_confidence_rules(a: SpeakerAssignment, cluster_texts: dict[str, str],
                           roster_ids: set[int]) -> tuple[float, str, bool]:
    """Spec: two independent signals -> high; one -> medium cap; content-only -> below display floor.

    The model's quotes are verified against the cluster's own text. An
    unverified primary quote drops the assignment to sample_inference.
    """
    text = normalize(cluster_texts.get(a.cluster_label, ""))
    q1 = bool(a.evidence_quote.strip()) and normalize(a.evidence_quote) in text
    q2 = bool(a.evidence_quote_2 and a.evidence_quote_2.strip()) and normalize(a.evidence_quote_2 or "") in text \
        and normalize(a.evidence_quote_2 or "") != normalize(a.evidence_quote)
    method = a.method
    if method != "sample_inference" and not q1:
        method = "sample_inference"
    if method == "sample_inference":
        cap = CONFIDENCE_CAPS["sample_inference"]
    elif q1 and q2:
        cap = CONFIDENCE_CAPS["two_signals"]
    else:
        cap = CONFIDENCE_CAPS["one_signal"]
    conf = min(a.confidence, cap)
    return round(conf, 3), _DB_METHOD[method], q1


def write_assignments(meeting_id: int, transcript_id: int, resolved: list[tuple[SpeakerAssignment, float, str]],
                      roster: list[RosterMember]) -> int:
    names = {m.id: m.name for m in roster}
    updated = 0
    with db_cursor() as cur:
        for a, conf, method in resolved:
            member_id = a.council_member_id if a.council_member_id in names else None
            display = names.get(member_id) if member_id else (a.display_name or None)
            role = a.role if (member_id or a.role != "council") else "unknown"
            cur.execute(
                """UPDATE transcript_speakers
                      SET council_member_id = %s, display_name = %s, role = %s, confidence = %s, method = %s,
                          needs_review = %s
                    WHERE meeting_id = %s AND cluster_label = %s AND is_manual = FALSE""",
                [member_id, display, role, conf, method, conf < 0.6, meeting_id, a.cluster_label],
            )
            updated += cur.rowcount
        # Segments uploaded before a speaker row existed, or re-uploaded, get linked here.
        cur.execute("""UPDATE transcript_segments s SET speaker_id = sp.id
                         FROM transcript_speakers sp
                        WHERE s.transcript_id = %s AND sp.meeting_id = %s
                          AND sp.cluster_label = s.cluster_label AND s.speaker_id IS DISTINCT FROM sp.id""",
                    [transcript_id, meeting_id])
    return updated


def run_speaker_stage(claim: dict, *, client) -> "StageOutcome":  # noqa: F821
    from docket.ai.transcripts.pipeline import StageOutcome

    tid, mid = claim["id"], claim["meeting_id"]
    segments = load_speech_segments(tid)
    roster = roster_for_meeting(mid)
    packet = build_packet(segments, roster)
    if not packet.stats:
        return StageOutcome("speakers_resolved", detail="no speech clusters")
    user = render_speaker_user(packet, _meeting(mid))
    model = AI_TRANSCRIPT_SPEAKER_MODEL
    tokens = client.count_tokens(model=model, system=SPEAKER_SYSTEM, user=user)
    if tokens > TRANSCRIPT_TOKEN_CEILING:
        raise TranscriptHeld("token_ceiling", f"{tokens} tokens > ceiling {TRANSCRIPT_TOKEN_CEILING}")
    res = client.call(model=model, system=SPEAKER_SYSTEM, user=user, schema=SPEAKER_SCHEMA,
                      max_tokens=16000, effort="medium")
    try:
        parsed = SpeakerResolution.model_validate(res.data)
    except ValidationError as e:
        raise TranscriptHeld("schema_invalid", f"speaker response failed validation: {e}") from e
    labels = set(packet.stats)
    got = {a.cluster_label for a in parsed.assignments}
    if not labels <= got:
        raise TranscriptHeld("schema_invalid", f"missing assignments for clusters {sorted(labels - got)[:5]}")
    cluster_texts: dict[str, str] = {}
    for s in segments:
        if s.get("cluster_label"):
            cluster_texts[s["cluster_label"]] = cluster_texts.get(s["cluster_label"], "") + " " + s["text"]
    roster_ids = {m.id for m in roster}
    resolved = []
    for a in parsed.assignments:
        if a.cluster_label not in labels:
            continue
        conf, method, _ = apply_confidence_rules(a, cluster_texts, roster_ids)
        resolved.append((a, conf, method))
    n = write_assignments(mid, tid, resolved, roster)
    log.info("speakers: meeting %s clusters=%d updated=%d roll_calls=%d addresses=%d tokens=%d",
             mid, len(labels), n, len(packet.roll_calls), len(packet.addresses), tokens)
    return StageOutcome("speakers_resolved", detail=f"{n} clusters")
