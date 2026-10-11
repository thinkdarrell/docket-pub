# src/docket/ai/transcripts/ab.py
"""Haiku 4.5 vs Sonnet 5.5 event extraction A/B (spec Section 3, 'Haiku experiment').

Not a code path the pipeline uses. Runs the transcript-side extraction on
both models for N compared meetings, records each call in ai_runs (stage
transcript_ab), scores Haiku against Sonnet as the reference and both against
the labeled material set (approved omission discrepancies), and renders a
markdown report. If Haiku passes the decision rule, the operator sets
AI_TRANSCRIPT_EVENTS_MODEL; nothing flips automatically.
"""
from __future__ import annotations

import time
from collections import Counter
from datetime import date

from docket.ai.pricing import Usage, calculate_cost_usd, usage_capture
from docket.ai.transcripts.events import load_agenda, load_segments_with_speakers, render_agenda, render_transcript
from docket.ai.transcripts.prompts import EVENTS_TRANSCRIPT_SYSTEM
from docket.ai.transcripts.schemas import EVENTS_SCHEMA, EventList, ExtractedEvent
from docket.config import AI_TRANSCRIPT_AB_MODEL, AI_TRANSCRIPT_EVENTS_MODEL
from docket.db import db, db_cursor
from docket.services.transcripts import speaker_ordinals

HAIKU_WINDOW_TOKENS = 180_000      # Haiku 4.5 has a 200K window; leave room for output
ACTION_TYPES = ("motion", "vote", "executive_session_motion", "amendment", "item_deferred", "recusal")


def event_keys(events: list[ExtractedEvent]) -> Counter:
    return Counter((e.event_type, frozenset(e.agenda_item_refs)) for e in events)


def compare_event_lists(reference: list[ExtractedEvent], candidate: list[ExtractedEvent]) -> dict:
    ref, cand = event_keys(reference), event_keys(candidate)
    hit = sum((ref & cand).values())
    per_type: dict[str, float] = {}
    for et in {k[0] for k in ref}:
        r = Counter({k: v for k, v in ref.items() if k[0] == et})
        c = Counter({k: v for k, v in cand.items() if k[0] == et})
        per_type[et] = round(sum((r & c).values()) / sum(r.values()), 3)
    return {"precision": round(hit / sum(cand.values()), 3) if cand else 0.0,
            "recall": round(hit / sum(ref.values()), 3) if ref else 0.0,
            "per_type_recall": per_type, "n_ref": sum(ref.values()), "n_cand": sum(cand.values())}


def material_labels(meeting_id: int) -> set[tuple[str, frozenset[int]]]:
    with db_cursor() as cur:
        cur.execute("""SELECT e.event_type, e.agenda_item_refs FROM minutes_discrepancies d
                         JOIN meeting_events e ON e.id = d.transcript_event_id
                        WHERE d.meeting_id = %s AND d.review_state = 'approved' AND d.category = 'omission'""", [meeting_id])
        return {(r["event_type"], frozenset(r["agenda_item_refs"])) for r in cur.fetchall()}


def _one(client, model: str, user: str, effort: str | None, notes: str) -> tuple[list[ExtractedEvent], dict]:
    from docket.ai.worker import RunSummary, _close_run, _open_run
    with db() as conn:
        run_id = _open_run(conn, "transcript_ab", model, notes)
    summary = RunSummary(stage="transcript_ab")
    t0 = time.monotonic()
    try:
        with usage_capture() as emissions:
            res = client.call(model=model, system=EVENTS_TRANSCRIPT_SYSTEM, user=user, schema=EVENTS_SCHEMA, max_tokens=32000, effort=effort)
        events = EventList.model_validate(res.data).events
        summary.rows_processed = 1
    except Exception:
        summary.rows_failed = 1
        raise
    finally:
        for m, u in emissions:
            summary.cost_usd += calculate_cost_usd(m, u)
            summary.usage = Usage(summary.usage.input_tokens + u.input_tokens, summary.usage.cache_creation_input_tokens + u.cache_creation_input_tokens,
                                  summary.usage.cache_read_input_tokens + u.cache_read_input_tokens, summary.usage.output_tokens + u.output_tokens)
        with db() as conn:
            _close_run(conn, run_id, summary)
    return events, {"cost_usd": round(summary.cost_usd, 4), "latency_s": round(time.monotonic() - t0, 1), "tokens": summary.usage.input_tokens}


def run_ab(meeting_ids: list[int], *, client, notes_prefix: str = "ab") -> list[dict]:
    results = []
    for mid in meeting_ids:
        with db_cursor() as cur:
            cur.execute("SELECT t.id FROM transcripts t WHERE t.meeting_id = %s", [mid])
            tid = cur.fetchone()["id"]
            cur.execute("SELECT title, meeting_date::text FROM meetings WHERE id = %s", [mid])
            meeting = dict(cur.fetchone())
        agenda = load_agenda(mid)
        user = (f"Meeting: {meeting['title']} on {meeting['meeting_date']}\n\n{render_agenda(agenda)}\n\n"
                f"Transcript:\n{render_transcript(load_segments_with_speakers(tid), agenda, speaker_ordinals(tid))}")
        row = {"meeting_id": mid, "skipped": None}
        if client.count_tokens(model=AI_TRANSCRIPT_AB_MODEL, system=EVENTS_TRANSCRIPT_SYSTEM, user=user) > HAIKU_WINDOW_TOKENS:
            row["skipped"] = "transcript exceeds Haiku's window"
            results.append(row)
            continue
        sonnet_events, sonnet_meta = _one(client, AI_TRANSCRIPT_EVENTS_MODEL, user, "medium", f"{notes_prefix}_sonnet")
        haiku_events, haiku_meta = _one(client, AI_TRANSCRIPT_AB_MODEL, user, None, f"{notes_prefix}_haiku")
        labels = material_labels(mid)
        def mat(evs):
            return round(len(labels & set(event_keys(evs))) / len(labels), 3) if labels else None
        row.update(sonnet=sonnet_meta, haiku={**compare_event_lists(sonnet_events, haiku_events), **haiku_meta},
                   material_recall={"sonnet": mat(sonnet_events), "haiku": mat(haiku_events)}, labels=len(labels))
        results.append(row)
    return results


def render_report(results: list[dict]) -> str:
    scored = [r for r in results if not r.get("skipped")]
    lines = [f"# Haiku 4.5 vs Sonnet 5.5 extraction A/B ({date.today().isoformat()})", "",
             f"Meetings scored: {len(scored)}; skipped: {len(results) - len(scored)}. Reference = Sonnet 5.5 output; "
             "keys = (event_type, agenda item ids) multisets. Material recall = share of approved omission events each model found.", "",
             "## Decision rule", "",
             "Haiku takes the extraction stage only if, across the scored meetings, its recall against Sonnet is at least 0.90 on "
             "motion, vote, executive_session_motion, amendment, item_deferred, and recusal events, at least 0.80 on statement events, "
             "its material recall is not below Sonnet's, and its cost is at most half of Sonnet's. Otherwise Sonnet stays.", "",
             "| meeting | Haiku recall | Haiku precision | action-type recall (min) | statement recall | material recall H/S | cost H/S | latency H/S |",
             "|---|---|---|---|---|---|---|---|"]
    agg_action, agg_stmt, h_cost, s_cost = [], [], 0.0, 0.0
    for r in scored:
        h = r["haiku"]
        action = [h["per_type_recall"][t] for t in ACTION_TYPES if t in h["per_type_recall"]]
        stmt = h["per_type_recall"].get("statement")
        agg_action += action
        if stmt is not None:
            agg_stmt.append(stmt)
        h_cost += h["cost_usd"]; s_cost += r["sonnet"]["cost_usd"]
        mr = r["material_recall"]
        lines.append(f"| meeting {r['meeting_id']} | {h['recall']} | {h['precision']} | {min(action) if action else 'n/a'} | {stmt if stmt is not None else 'n/a'} | "
                     f"{mr['haiku']}/{mr['sonnet']} | ${h['cost_usd']}/${r['sonnet']['cost_usd']} | {h['latency_s']}s/{r['sonnet']['latency_s']}s |")
    for r in results:
        if r.get("skipped"):
            lines.append(f"| meeting {r['meeting_id']} | skipped: {r['skipped']} | | | | | | |")
    min_action = min(agg_action) if agg_action else 0.0
    min_stmt = min(agg_stmt) if agg_stmt else 0.0
    passes = bool(scored) and min_action >= 0.90 and min_stmt >= 0.80 and h_cost <= 0.5 * s_cost
    lines += ["", "## Verdict", "",
              f"Action-type recall floor {min_action}, statement recall floor {min_stmt}, cost ${h_cost:.2f} vs ${s_cost:.2f}. "
              + ("Haiku passes the rule: set `AI_TRANSCRIPT_EVENTS_MODEL=claude-haiku-4-5-20251001` on the worker and re-run the pilot live test."
                 if passes else "Haiku does not pass the rule: Sonnet 5.5 stays the extraction model.")]
    return "\n".join(lines)
