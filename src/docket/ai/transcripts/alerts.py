"""Outbound alerts (spec Section 3, "Alerting"): the first active alert in the codebase.

One env-gated webhook URL. Slack reads `text`, Discord reads `content`; both
are sent. Fired on a transcript entering failed or needs_review (pipeline),
on a tripped candidate cap (TranscriptHeld), and once a day when the desktop
looks stalled.
"""
from __future__ import annotations

import logging

import requests

from docket.config import ALERT_WEBHOOK_URL, TRANSCRIPT_BACKFILL_SINCE
from docket.db import db_cursor

log = logging.getLogger(__name__)
STALL_DAYS = 7


def post_alert(kind: str, text: str, **fields) -> bool:
    if not ALERT_WEBHOOK_URL:
        return False
    payload = {"text": text, "content": text, "kind": kind, "source": "docket.pub worker", **fields}
    try:
        resp = requests.post(ALERT_WEBHOOK_URL, json=payload, timeout=10)
        if not resp.ok:
            log.warning("alert webhook returned %s", resp.status_code)
            return False
        return True
    except requests.RequestException as e:
        log.warning("alert webhook failed: %s", e)
        return False


def producer_stalled() -> dict | None:
    with db_cursor() as cur:
        cur.execute(
            """SELECT m.id AS meeting_id, m.meeting_date
                 FROM meetings m JOIN municipalities mu ON mu.id = m.municipality_id
                 LEFT JOIN transcripts t ON t.meeting_id = m.id
                WHERE mu.slug = 'birmingham' AND m.external_id ~ '^[0-9]+$' AND m.is_hidden = FALSE
                  AND m.video_url IS NOT NULL AND t.id IS NULL
                  AND m.meeting_date >= %s::date AND m.meeting_date < CURRENT_DATE - %s
                ORDER BY m.meeting_date DESC LIMIT 1""",
            [TRANSCRIPT_BACKFILL_SINCE, STALL_DAYS],
        )
        meeting = cur.fetchone()
        if not meeting:
            return None
        cur.execute(
            "SELECT max(last_seen_at) AS hb, bool_or(last_seen_at > now() - make_interval(days => %s)) AS fresh "
            "FROM producer_heartbeats",
            [STALL_DAYS],
        )
        row = cur.fetchone()
        if row["fresh"]:
            return None
        hb = row["hb"]
    return {"meeting_id": meeting["meeting_id"], "meeting_date": str(meeting["meeting_date"]),
            "last_heartbeat": str(hb) if hb else None}


def alert_if_producer_stalled() -> bool:
    s = producer_stalled()
    if s is None:
        return False
    return post_alert("producer_stalled",
                      f"Legion looks stalled: meeting {s['meeting_id']} ({s['meeting_date']}) has video and no transcript; "
                      f"last producer heartbeat {s['last_heartbeat'] or 'never'}.", **s)
