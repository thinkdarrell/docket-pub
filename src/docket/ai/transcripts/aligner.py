# src/docket/ai/transcripts/aligner.py
"""Pair the two event timelines before any model judges (spec Section 4, "Alignment").

1. Group by agenda item references, not by time (a reopened item is one group).
2. Effective consent blocks per side: published consent minus pulled plus added.
3. Within a group, pair by type and order; leftovers are omission/addition
   candidates (only for event types the minutes normally record).
4. LCS over paired events across the meeting; out-of-order pairs are sequence candidates.
5. Actors compare as council_member_ids only. No phonetic matching.
6. Vote tallies compare against existing `votes` rows (minutes-derived baseline).
"""
from __future__ import annotations

import re
from bisect import bisect_left
from dataclasses import dataclass, field

from docket.ai.transcripts.guard import canonical_statute, normalize

MINUTED_TYPES = frozenset({"motion", "amendment", "vote", "executive_session_motion", "recusal", "procedural_ruling",
                           "item_deferred", "consent_amendment", "statement", "recess", "reconvene", "adjourn"})
_ACTOR_TYPES = {"motion", "amendment", "executive_session_motion", "recusal", "item_deferred"}


@dataclass(frozen=True)
class Event:
    id: int
    source: str
    seq: int
    event_type: str
    scope: str
    item_refs: frozenset[int]
    actor_member_id: int | None
    actor_text: str | None
    summary: str
    detail: dict
    start_s: float | None
    page: int | None
    char_offset: int | None


def event_from_row(row: dict) -> Event:
    return Event(row["id"], row["source"], row["seq"], row["event_type"], row["scope"],
                 frozenset(row.get("agenda_item_refs") or []), row.get("actor_member_id"), row.get("actor_text"),
                 row["summary"], dict(row.get("detail") or {}), row.get("start_s"), row.get("page"), row.get("char_offset"))


@dataclass
class Candidate:
    candidate_id: int
    kind: str
    category: str
    transcript_event: Event | None
    minutes_event: Event | None
    note: str
    item_refs: frozenset[int] = field(default_factory=frozenset)
    vote_row: dict | None = None


def effective_consent_block(published: set[int], events: list[Event]) -> set[int]:
    """Events must be in timeline order (load_events orders by seq); a pull then an add re-admits the item."""
    block = set(published)
    for ev in sorted(events, key=lambda e: e.seq):
        if ev.event_type != "consent_amendment":
            continue
        items = set(ev.detail.get("items") or []) or set(ev.item_refs)
        if ev.detail.get("action") == "pulled":
            block -= items
        elif ev.detail.get("action") == "added":
            block |= items
    return block


def group_key(ev: Event, consent_block: set[int]) -> tuple:
    if not ev.item_refs and ev.detail.get("unlisted_item"):
        return ("unlisted", normalize(ev.detail["unlisted_item"])[:60])   # floor-added item, no agenda row
    if ev.scope == "meeting" or not ev.item_refs:
        return ("meeting",)
    if ev.scope == "consent_block" or (len(ev.item_refs) > 1 and ev.item_refs <= consent_block):
        return ("consent",)
    return ("item", tuple(sorted(ev.item_refs)))


def _tokens(s: str | None) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", normalize(s or "")))


def _jaccard(a: str | None, b: str | None) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / len(ta | tb) if (ta or tb) else 1.0


def details_differ(t: Event, m: Event) -> str | None:
    td, md = t.detail, m.detail
    if t.event_type == "vote":
        if td.get("result") and md.get("result") and normalize(td["result"]) != normalize(md["result"]):
            return "vote_outcome"
        for k in ("yeas", "nays", "abstentions"):
            if td.get(k) is not None and md.get(k) is not None and td[k] != md[k]:
                return "vote_outcome"
        return None
    if t.event_type in _ACTOR_TYPES and t.actor_member_id and m.actor_member_id and t.actor_member_id != m.actor_member_id:
        return "speaker"
    if t.event_type == "executive_session_motion":
        tc, mc = td.get("statute_cite"), md.get("statute_cite")
        if tc and mc and canonical_statute(tc) != canonical_statute(mc):
            return "wording"
        if _jaccard(td.get("stated_reason"), md.get("stated_reason")) < 0.5:
            return "wording"
        return None
    if t.event_type in ("item_deferred", "motion", "consent_amendment", "procedural_ruling"):
        for k in ("action", "to_date", "kind"):
            if td.get(k) and md.get(k) and normalize(td[k]) != normalize(md[k]):
                return "wording"
    if t.event_type in ("amendment", "statement", "procedural_ruling", "motion"):
        key = "what_changed" if t.event_type == "amendment" else ("ruling" if t.event_type == "procedural_ruling" else "as_stated")
        if td.get(key) and md.get(key) and _jaccard(td[key], md[key]) < 0.4:
            return "wording"
    return None


def pair_group(t_evs: list[Event], m_evs: list[Event]):
    pairs, t_only, m_only = [], [], []
    types = {e.event_type for e in t_evs} | {e.event_type for e in m_evs}
    for et in sorted(types):
        ts = [e for e in t_evs if e.event_type == et]
        ms = [e for e in m_evs if e.event_type == et]
        for a, b in zip(ts, ms):
            pairs.append((a, b))
        t_only += ts[len(ms):]
        m_only += ms[len(ts):]
    return pairs, t_only, m_only


def sequence_candidates(pairs: list[tuple[Event, Event]]) -> list[tuple[Event, Event]]:
    """Pairs not on the longest increasing subsequence of minutes order (sorted by transcript order)."""
    ordered = sorted(pairs, key=lambda p: p[0].seq)
    seqs = [p[1].seq for p in ordered]
    tails, prev, idx_at = [], [-1] * len(seqs), []
    for i, v in enumerate(seqs):
        k = bisect_left(tails, v)
        if k == len(tails):
            tails.append(v); idx_at.append(i)
        else:
            tails[k] = v; idx_at[k] = i
        prev[i] = idx_at[k - 1] if k else -1
    keep, i = set(), idx_at[-1] if idx_at else -1
    while i != -1:
        keep.add(i); i = prev[i]
    return [p for i, p in enumerate(ordered) if i not in keep]


def vote_outcome_candidates(t_events: list[Event], votes: list[dict]) -> list[Candidate]:
    out = []
    for ev in t_events:
        if ev.event_type != "vote" or not ev.item_refs:
            continue
        for v in votes:
            if not (set(v.get("item_ids") or []) & ev.item_refs):
                continue
            td = ev.detail
            differs = (td.get("result") and v.get("result") and normalize(td["result"]) != normalize(v["result"])) or any(
                td.get(k) is not None and v.get(k) is not None and td[k] != v[k] for k in ("yeas", "nays", "abstentions"))
            if differs:
                out.append(Candidate(0, "vote_outcome", "vote_outcome", ev, None,
                                     f"transcript says {td.get('result')} {td.get('yeas')}-{td.get('nays')}; "
                                     f"minutes vote row {v['id']} says {v.get('result')} {v.get('yeas')}-{v.get('nays')}",
                                     ev.item_refs, vote_row=v))
    return out


def align(t_events: list[Event], m_events: list[Event], *, consent_items: set[int], votes: list[dict]) -> list[Candidate]:
    t_block = effective_consent_block(consent_items, t_events)
    m_block = effective_consent_block(consent_items, m_events)
    cands: list[Candidate] = []
    for item in sorted(m_block - t_block):   # in the minutes' consent block, handled separately on video
        ref = next((e for e in m_events if item in e.item_refs and e.event_type == "vote"), None) or \
              next((e for e in m_events if item in e.item_refs), None)
        tref = next((e for e in t_events if item in e.item_refs), None)
        cands.append(Candidate(0, "consent_block", "addition", tref, ref,
                               "pulled from consent on video; still inside the consent block in the minutes", frozenset({item})))
    for item in sorted(t_block - m_block):
        ref = next((e for e in t_events if item in e.item_refs), None)
        mref = next((e for e in m_events if item in e.item_refs), None)
        cands.append(Candidate(0, "consent_block", "omission", ref, mref,
                               "inside the consent block on video; handled separately in the minutes", frozenset({item})))
    settled = (m_block - t_block) | (t_block - m_block)

    groups: dict[tuple, tuple[list[Event], list[Event]]] = {}
    for ev in t_events:
        if ev.event_type == "consent_amendment" and (set(ev.detail.get("items") or []) | set(ev.item_refs)) & settled:
            continue
        groups.setdefault(group_key(ev, t_block), ([], []))[0].append(ev)
    for ev in m_events:
        if ev.event_type == "consent_amendment" and (set(ev.detail.get("items") or []) | set(ev.item_refs)) & settled:
            continue
        groups.setdefault(group_key(ev, m_block), ([], []))[1].append(ev)

    all_pairs, mism, omis, adds = [], [], [], []
    for key, (ts, ms) in groups.items():
        if key[0] == "item" and settled & set(key[1]):
            continue   # the pulled item's own group is covered by the consent_block candidate
        pairs, t_only, m_only = pair_group(ts, ms)
        all_pairs += pairs
        for a, b in pairs:
            cat = details_differ(a, b)
            if cat:
                mism.append(Candidate(0, "mismatch", cat, a, b, f"{a.event_type}: {cat} differs", a.item_refs | b.item_refs))
        omis += [Candidate(0, "omission", "omission", e, None, f"{e.event_type} on video, not in minutes", e.item_refs)
                 for e in t_only if e.event_type in MINUTED_TYPES]
        adds += [Candidate(0, "addition", "addition", None, e, f"{e.event_type} in minutes, not on video", e.item_refs)
                 for e in m_only if e.event_type in MINUTED_TYPES]
    seqs = [Candidate(0, "sequence", "sequence", a, b, "paired events occur in a different order", a.item_refs | b.item_refs)
            for a, b in sequence_candidates(all_pairs)]
    ordered = cands + mism + omis + adds + seqs + vote_outcome_candidates(t_events, votes)
    for i, c in enumerate(ordered, start=1):
        c.candidate_id = i
    return ordered
