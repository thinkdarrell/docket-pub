"""A page of a meeting's minutes, drawn from the city's own file on request.

``page_view`` is given the minutes address stored on a meeting and a page
number, and returns that page as a picture. The caller (the web route)
has already read the address from the meeting's row and checked it against
the allowlist; this module takes no address from a request, reads no
database and has no SQL.

Nothing is stored: the city's file is fetched when a reader asks
(``docket.adapters.source_file``), kept in this process's memory for at
most ``CACHE_TTL_S``, and drawn one page at a time
(``docket.analysis.pdf_page``). The cache holds at most ``CACHE_FILES``
files and ``CACHE_BYTES`` bytes and drops the least recently used. It is
per process: two web processes each have their own.

What keeps a reader's clicks polite to the city:

- one fetch for callers who ask for the same file at once (the others wait
  for it, at most ``WAIT_S``, and are handed the file it brought);
- at least ``HOST_GAP_S`` between one request to a host ending and the
  next beginning, kept by a lock per host held across that host's wait and
  fetch;
- a failure is remembered for ``FAILURE_TTL_S``: for the one address when
  it is about the file, and for the whole host when the host did not
  answer.

``_state_lock`` guards the four dictionaries below and is held only while
they are read or changed: never across a sleep, a fetch, or a draw. A
caller who waited too long, behind another fetch of the same file or for
the host, gets ``Unavailable`` and no failure is remembered for it.

Every constant, and ``_fetch``, ``_now`` and ``_sleep``, are read when
``page_view`` is called, so a test can change them.

Plan `minutes-open-at-the-vote-page`, M2; M2b made the cache sixteen
files, put the file's page count on ``NoSuchPage``, and hands a caller who
waited the file the fetch it waited for brought.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import NamedTuple
from urllib.parse import urlsplit

from docket.adapters import source_file
from docket.analysis import pdf_page

logger = logging.getLogger(__name__)

MAX_PAGE = 2000
CACHE_FILES = 16
CACHE_BYTES = 40 * 1024 * 1024
CACHE_TTL_S = 3600.0
FAILURE_TTL_S = 60.0
HOST_GAP_S = 1.0
WAIT_S = 13.0
SLOW_FETCH_S = 3.0

_fetch = source_file.fetch_pdf  # replaced in tests
_now = time.monotonic
_sleep = time.sleep


@dataclass(frozen=True)
class PageView:
    page: int
    page_count: int
    image: bytes
    mime: str
    width: int
    height: int


class NoSuchPage(Exception):
    """The page is outside the bound, or past the file's last page.

    ``page_count`` is the file's page count when the file was in hand (the
    page is past its end), and None when the page is outside 1 to
    ``MAX_PAGE`` and nothing was fetched.
    """

    def __init__(self, message: str = "", page_count: int | None = None):
        super().__init__(message)
        self.page_count = page_count


class Unavailable(Exception):
    """The city's file could not be fetched or read just now."""


class _Entry(NamedTuple):
    data: bytes
    page_count: int
    fetched_at: float


class _Flight:
    """A fetch now running: its event, and the entry it stored (None until
    it has stored one, and for ever if it ends any other way)."""

    def __init__(self) -> None:
        self.event = threading.Event()
        self.entry: _Entry | None = None


_state_lock = threading.Lock()
# address -> _Entry, least recently used first
_files: OrderedDict[str, _Entry] = OrderedDict()
# an address, or "host:" + host for a host that did not answer -> when it failed
_failures: dict[str, float] = {}
# address -> the fetch now running for it
_inflight: dict[str, _Flight] = {}
# host -> [its lock, when the last request to it returned or raised (None: never)]
_hosts: dict[str, list] = {}


def clear() -> None:
    """Forget every cached file, failure, in-flight marker, host lock and host time; for tests."""
    with _state_lock:
        _files.clear()
        _failures.clear()
        _inflight.clear()
        _hosts.clear()


def page_view(minutes_url: str, page: int) -> PageView:
    """Page `page` (1-based) of the PDF at `minutes_url`, as a picture.

    NoSuchPage when the page is below 1, above MAX_PAGE (neither sends the
    city anything), or above the file's last page. Unavailable when the
    file cannot be fetched or read, or the wait for it was too long.
    """
    if not 1 <= page <= MAX_PAGE:
        raise NoSuchPage(f"page {page}")

    # Held in a local, so nothing another thread drops can take it away.
    entry = _entry(minutes_url)
    if page > entry.page_count:
        raise NoSuchPage(f"page {page} of {entry.page_count}", page_count=entry.page_count)

    try:
        rendered = pdf_page.render_page(entry.data, page)
    except pdf_page.PageOutOfRange as exc:
        raise NoSuchPage(str(exc), page_count=exc.page_count) from exc
    except pdf_page.UnreadablePdf as exc:
        logger.warning(
            "minutes viewer: page %d could not be drawn url=%s reason=%s", page, minutes_url, exc
        )
        with _state_lock:
            if _files.get(minutes_url) is entry:
                del _files[minutes_url]
            _failures[minutes_url] = _now()
        raise Unavailable(str(exc)) from exc

    return PageView(
        page=page,
        page_count=rendered.page_count,
        image=rendered.image,
        mime=rendered.mime,
        width=rendered.width,
        height=rendered.height,
    )


def _host_of(url: str) -> str:
    """The address's host, lower case and without its port."""
    return (urlsplit(url).hostname or "").lower()


def _failed(url: str, host: str, now: float) -> bool:
    """Whether a failure for the address or its host is remembered. Under the state lock."""
    remembered = False
    for key in (url, "host:" + host):
        at = _failures.get(key)
        if at is None:
            continue
        if now - at < FAILURE_TTL_S:
            remembered = True
        else:
            del _failures[key]
    return remembered


def _cached(url: str, host: str) -> _Entry | None:
    """The address's entry if the cache holds a fresh one, marked as just used.

    Unavailable when a failure is remembered for the address or its host.
    Under the state lock.
    """
    now = _now()
    if _failed(url, host, now):
        raise Unavailable("a failure is remembered")
    entry = _files.get(url)
    if entry is not None and now - entry.fetched_at < CACHE_TTL_S:
        _files.move_to_end(url)
        return entry
    return None


def _entry(url: str) -> _Entry:
    """The file's entry, from the cache or from one fetch shared by everyone asking."""
    host = _host_of(url)

    with _state_lock:
        entry = _cached(url, host)
        if entry is not None:
            return entry
        flight = _inflight.get(url)
        fetcher = flight is None
        if fetcher:
            flight = _inflight[url] = _Flight()

    if fetcher:
        return _fetch_and_store(url, host, flight)

    # A waiter: someone else is fetching this address.
    if not flight.event.wait(WAIT_S):
        logger.warning("minutes viewer: gave up waiting for a fetch in flight url=%s", url)
        raise Unavailable("waited too long")
    # Handed the file that fetch brought: the cache is not read again (the
    # entry may already have been dropped from it), and no fetch of our own.
    entry = flight.entry
    if entry is None:
        raise Unavailable("the fetch waited for left nothing")
    return entry


def _fetch_and_store(url: str, host: str, flight: _Flight) -> _Entry:
    """The fetcher's part: wait for the host, fetch, check, store. Under no lock on entry."""
    try:
        data, fetched_at = _fetch_politely(url, host)

        try:
            count = pdf_page.page_count(data)
        except pdf_page.UnreadablePdf as exc:
            logger.warning(
                "minutes viewer: not a readable PDF url=%s bytes=%d reason=%s",
                url,
                len(data),
                exc,
            )
            with _state_lock:
                _failures[url] = _now()
            raise Unavailable(str(exc)) from exc

        entry = _Entry(data, count, fetched_at)
        with _state_lock:
            _files[url] = entry
            _files.move_to_end(url)  # a stale entry replaced keeps its old place otherwise
            # Least recently used first, and never the one just stored.
            while len(_files) > 1 and (
                len(_files) > CACHE_FILES
                or sum(len(kept.data) for kept in _files.values()) > CACHE_BYTES
            ):
                _files.popitem(last=False)
        # For the callers waiting on this fetch, before the event is set.
        flight.entry = entry
        return entry
    finally:
        # Whatever the outcome, no waiter is left waiting on a fetch that ended.
        with _state_lock:
            _inflight.pop(url, None)
        flight.event.set()


def _fetch_politely(url: str, host: str) -> tuple[bytes, float]:
    """One fetch of the address, the host's gap kept. Returns the bytes and when they arrived."""
    with _state_lock:
        slot = _hosts.get(host)
        if slot is None:
            slot = _hosts[host] = [threading.Lock(), None]
    host_lock = slot[0]

    if not host_lock.acquire(timeout=WAIT_S):
        logger.warning("minutes viewer: gave up waiting for the host url=%s", url)
        raise Unavailable("waited too long for the host")
    try:
        with _state_lock:
            last = slot[1]
            # The request this one waited behind may have found the host down.
            if _failed(url, host, _now()):
                raise Unavailable("a failure is remembered")
        if last is not None:
            remaining = HOST_GAP_S - (_now() - last)
            if remaining > 0:
                _sleep(remaining)

        started = _now()
        try:
            data = _fetch(url)
        except source_file.SourceFileError as exc:
            ended = _now()
            logger.warning(
                "minutes viewer: fetch failed url=%s reason=%s ms=%d",
                url,
                exc.reason,
                round((ended - started) * 1000),
            )
            with _state_lock:
                _failures[url] = ended
                if exc.host_down:
                    _failures["host:" + host] = ended
            raise Unavailable(exc.reason) from exc
        finally:
            ended_at = _now()
            with _state_lock:
                slot[1] = ended_at

        if ended_at - started > SLOW_FETCH_S:
            logger.warning(
                "minutes viewer: slow fetch url=%s bytes=%d ms=%d",
                url,
                len(data),
                round((ended_at - started) * 1000),
            )
        return data, ended_at
    finally:
        host_lock.release()
