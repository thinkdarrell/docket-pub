# src/docket/ai/transcripts/minutes.py
"""Minutes PDF -> text with page offsets, stored once per meeting in minutes_texts.

The existing minutes_parser.extract_text_from_pdf joins pages and drops the
page boundaries; the comparison needs `page` on every minutes event and
discrepancy, so this extractor keeps offsets. Layout mode is deliberately off
(single-column minutes; layout mode is what introduces column breaks).
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
from bisect import bisect_right
from dataclasses import dataclass

import pdfplumber
import requests

from docket.analysis.ocr.frame_io import BROWSER_USER_AGENT
from docket.db import db_cursor

log = logging.getLogger(__name__)


MAX_MINUTES_PDF_BYTES = 40 * 1024 * 1024   # the largest Birmingham minutes seen are under 5 MB; this is a crash guard


def download_minutes(url: str, timeout: int = 30, max_bytes: int = MAX_MINUTES_PDF_BYTES) -> bytes | None:
    """Stream the PDF and give up past `max_bytes`, before pdfplumber ever sees it. Oversize is reported
    like any other unavailable download: the caller records minutes_unavailable and tries again tomorrow."""
    try:
        resp = requests.get(url, timeout=timeout, allow_redirects=True, stream=True,
                            headers={"User-Agent": BROWSER_USER_AGENT})
        try:
            resp.raise_for_status()
            declared = resp.headers.get("Content-Length") or ""
            if declared.isdigit() and int(declared) > max_bytes:
                log.warning("minutes PDF declares %s bytes, over the %d cap: %s", declared, max_bytes, url)
                return None
            chunks: list[bytes] = []
            size = 0
            for chunk in resp.iter_content(chunk_size=256 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    log.warning("minutes PDF exceeded the %d byte cap while streaming: %s", max_bytes, url)
                    return None
                chunks.append(chunk)
        finally:
            resp.close()
    except requests.RequestException as e:
        log.warning("minutes download failed %s: %s", url, e)
        return None
    content = b"".join(chunks)
    if content[:5] != b"%PDF-":
        log.warning("minutes URL did not return a PDF: %s", url)
        return None
    return content


def extract_pages(pdf_bytes: bytes) -> tuple[str, list[int]]:
    pages: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            pages.append((page.extract_text() or "").replace("\f", ""))
    offsets, pos = [], 0
    for p in pages:
        offsets.append(pos)
        pos += len(p) + 1          # the "\n" joiner
    return "\n".join(pages), offsets


def page_for_offset(page_offsets: list[int], offset: int) -> int:
    return max(1, bisect_right(page_offsets, offset))


@dataclass
class MinutesCapture:
    minutes_text_id: int
    text: str
    page_offsets: list[int]
    sha256: str
    changed: bool
    is_new: bool


def load_minutes(meeting_id: int) -> MinutesCapture | None:
    with db_cursor() as cur:
        cur.execute("SELECT id, text, page_offsets, pdf_sha256 FROM minutes_texts WHERE meeting_id = %s", [meeting_id])
        row = cur.fetchone()
    if not row:
        return None
    return MinutesCapture(row["id"], row["text"], list(row["page_offsets"]), row["pdf_sha256"], False, False)


def capture_minutes(meeting_id: int, minutes_url: str) -> MinutesCapture | None:
    pdf = download_minutes(minutes_url)
    if pdf is None:
        return None
    sha = hashlib.sha256(pdf).hexdigest()
    with db_cursor() as cur:
        cur.execute("SELECT id, pdf_sha256, source_url, text, page_offsets FROM minutes_texts WHERE meeting_id = %s", [meeting_id])
        existing = cur.fetchone()
        if existing and existing["pdf_sha256"] == sha and existing["source_url"] == minutes_url:
            return MinutesCapture(existing["id"], existing["text"], list(existing["page_offsets"]), sha, False, False)
        text, offsets = extract_pages(pdf)
        cur.execute(
            """INSERT INTO minutes_texts (meeting_id, source_url, pdf_sha256, text, page_offsets, extracted_at)
               VALUES (%s, %s, %s, %s, %s::jsonb, now())
               ON CONFLICT (meeting_id) DO UPDATE
                 SET source_url = EXCLUDED.source_url, pdf_sha256 = EXCLUDED.pdf_sha256, text = EXCLUDED.text,
                     page_offsets = EXCLUDED.page_offsets, extracted_at = now()
               RETURNING id""",
            [meeting_id, minutes_url, sha, text, json.dumps(offsets)],
        )
        mt_id = cur.fetchone()["id"]
    return MinutesCapture(mt_id, text, offsets, sha, changed=existing is not None, is_new=existing is None)


def recheck_minutes(meeting_id: int) -> bool | None:
    with db_cursor() as cur:
        cur.execute("SELECT minutes_url FROM meetings WHERE id = %s", [meeting_id])
        row = cur.fetchone()
    if not row or not row["minutes_url"]:
        return None
    cap = capture_minutes(meeting_id, row["minutes_url"])
    return None if cap is None else cap.changed
