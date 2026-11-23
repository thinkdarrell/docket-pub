"""One bounded fetch of a city's own PDF, for a reader who asked to see it.

A city-neutral, read-only client outside the adapter protocol: no database
and no import from ``docket.services`` or ``docket.web``. The caller decides
which address may be fetched (the web layer's allowlist) and how often (the
minutes viewer service keeps a second between requests to one host); this
module makes the one request and bounds it.

One attempt. ``https`` only. No redirect is followed, so the request stays
on the address the caller's allowlist passed. The body is streamed and
refused once it is over ``MAX_BYTES``; the fetch is given up once
``DEADLINE_S`` has passed. The body is read with ``response.raw.read1``,
which returns whatever has arrived (at most ``CHUNK_BYTES``) after one read
of the socket, and the deadline is looked at after each such read, so the
fetch ends within ``DEADLINE_S`` plus one read of up to ``READ_TIMEOUT_S``,
however slowly the body trickles in. (``iter_content`` is not used: for a
body with a ``Content-Length`` it hands nothing back until a whole chunk has
arrived, so a slow sender that never fell silent went unchecked; debt row
``D204``, paid here.) A body that does not carry a PDF header in its first
1,024 bytes is refused.

The constants are read when ``fetch_pdf`` is called, so a test can change
them.

Plan `minutes-open-at-the-vote-page`, M1; M2b added ``Accept-Encoding``;
the read by ``read1`` came after the plan closed, before its merge.
"""

from __future__ import annotations

import time

import requests
import urllib3

CONNECT_TIMEOUT_S = 3.0
READ_TIMEOUT_S = 4.0
DEADLINE_S = 8.0
MAX_BYTES = 25 * 1024 * 1024
CHUNK_BYTES = 16 * 1024
USER_AGENT = "docket.pub minutes viewer (+https://docket.pub)"

_PDF_MARK = b"%PDF-"
_PDF_MARK_WITHIN = 1024

_now = time.monotonic  # replaced in tests


class SourceFileError(Exception):
    """The file could not be fetched within the bounds, or is not a PDF.

    ``host_down`` is True when the host did not answer (a connection error,
    a timeout, a status of 500 or above, the deadline), and False when the
    failure is about the one file (a status below 500, too big, not a PDF,
    an address that is not ``https``).
    """

    def __init__(self, reason: str, *, host_down: bool = False):
        super().__init__(reason)
        self.reason = reason
        self.host_down = host_down


def fetch_pdf(url: str) -> bytes:
    """One GET of a city's PDF, one attempt. SourceFileError unless the address is https,
    the answer is a 200, the body is at most MAX_BYTES, arrives within DEADLINE_S, and
    has b'%PDF-' in its first 1,024 bytes. Follows no redirect."""
    if not isinstance(url, str) or not url.lower().startswith("https://"):
        raise SourceFileError("the address is not https")

    started = _now()
    response = None
    try:
        response = requests.get(
            url,
            stream=True,
            allow_redirects=False,
            timeout=(CONNECT_TIMEOUT_S, READ_TIMEOUT_S),
            # The body as it is, not gzipped: Content-Length then counts the
            # bytes that arrive, and it is the request the city was seen to answer.
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/pdf",
                "Accept-Encoding": "identity",
            },
        )
        status = response.status_code
        if status != 200:
            # A 3xx lands here too, which is how a redirect is not followed.
            raise SourceFileError(f"status {status}", host_down=status >= 500)

        declared = _declared_length(response.headers.get("Content-Length"))
        if declared is not None and declared > MAX_BYTES:
            raise SourceFileError(f"content-length {declared} is over {MAX_BYTES} bytes")

        body = bytearray()
        while True:
            # One read of the socket: what has arrived, not a full chunk.
            piece = response.raw.read1(CHUNK_BYTES)
            if not piece:
                break
            body.extend(piece)
            if len(body) > MAX_BYTES:
                raise SourceFileError(f"the body is over {MAX_BYTES} bytes")
            if _now() - started > DEADLINE_S:
                raise SourceFileError(
                    f"not finished within {DEADLINE_S:g} seconds", host_down=True
                )

        if _PDF_MARK not in bytes(body[:_PDF_MARK_WITHIN]):
            raise SourceFileError("the body is not a PDF")
        return bytes(body)
    except (requests.RequestException, urllib3.exceptions.HTTPError, OSError) as exc:
        # read1 is urllib3's own, so its errors arrive unwrapped by requests.
        raise SourceFileError(f"{type(exc).__name__}: {exc}", host_down=True) from exc
    finally:
        if response is not None:
            response.close()


def _declared_length(value: object) -> int | None:
    """The Content-Length as a size, or None when it is absent or is not one."""
    try:
        length = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return length if length >= 0 else None
