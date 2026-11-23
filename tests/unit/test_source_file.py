"""Unit tests for ``docket.adapters.source_file.fetch_pdf``.

One bounded GET of a city's PDF: one attempt, ``https`` only, no redirect
followed, a size cap, a deadline, and a check that the body is a PDF.
``requests.get`` is faked in all but the last tests, which point it at a
socket server on this machine to see what a real slow body does; no test
sends a request off the machine.

The module is imported inside each test (through the ``sf`` fixture) so
that this file collects, and each test fails by itself, before the module
exists.

Plan `minutes-open-at-the-vote-page`, M1.
"""

from __future__ import annotations

import importlib
import socket
import threading
import time

import pytest
import requests
import urllib3

URL = "https://mobileal.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=3854,plainText=false)"
PDF = b"%PDF-1.6\n" + b"x" * 5000


class _Response:
    def __init__(self, status_code=200, headers=None, chunks=(PDF,)):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = list(chunks)
        self.chunk_sizes = []
        self.closed = False

    @property
    def raw(self):
        return self

    def read1(self, amt=None):
        """What urllib3's ``read1`` gives: the next piece that arrived, b"" at the end."""
        self.chunk_sizes.append(amt)
        return self._chunks.pop(0) if self._chunks else b""

    def close(self):
        self.closed = True


class _Get:
    """A stand-in for ``requests.get`` that records how it was called."""

    def __init__(self, response=None, raises=None):
        self.response = response
        self.raises = raises
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.raises is not None:
            raise self.raises
        return self.response


@pytest.fixture
def sf():
    return importlib.import_module("docket.adapters.source_file")


def _fake(sf, monkeypatch, response=None, raises=None):
    get = _Get(response, raises)
    monkeypatch.setattr(sf.requests, "get", get)
    return get


def test_a_pdf_body_is_returned_whole_from_one_bounded_request(sf, monkeypatch):
    response = _Response(chunks=(PDF[:100], PDF[100:]))
    get = _fake(sf, monkeypatch, response)

    assert sf.fetch_pdf(URL) == PDF

    assert len(get.calls) == 1
    url, kwargs = get.calls[0]
    assert url == URL
    assert kwargs["stream"] is True
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == (sf.CONNECT_TIMEOUT_S, sf.READ_TIMEOUT_S)
    assert kwargs["headers"]["User-Agent"] == sf.USER_AGENT
    assert "docket.pub" in sf.USER_AGENT
    assert kwargs["headers"]["Accept"] == "application/pdf"
    # The body as it is: the request Mobile was watched answering asked for
    # no encoding, and Content-Length then counts the bytes that arrive.
    assert kwargs["headers"]["Accept-Encoding"] == "identity"
    # Two pieces and the empty read that ends the body, each asked for at most a chunk.
    assert response.chunk_sizes == [sf.CHUNK_BYTES] * 3
    assert response.closed


def test_the_bounds_are_the_ones_the_plan_states(sf):
    assert (sf.CONNECT_TIMEOUT_S, sf.READ_TIMEOUT_S, sf.DEADLINE_S) == (3.0, 4.0, 8.0)
    assert sf.MAX_BYTES == 25 * 1024 * 1024
    assert sf.CHUNK_BYTES == 16 * 1024


def test_a_pdf_header_after_a_byte_order_mark_is_accepted(sf, monkeypatch):
    body = b"\xef\xbb\xbf\n%PDF-1.7\n" + b"y" * 200
    response = _Response(chunks=(body,))
    _fake(sf, monkeypatch, response)

    assert sf.fetch_pdf(URL) == body
    assert response.closed


def test_an_http_address_is_refused_without_a_request(sf, monkeypatch):
    get = _fake(sf, monkeypatch, _Response())

    with pytest.raises(sf.SourceFileError) as raised:
        sf.fetch_pdf("http://mobileal.api.civicclerk.com/file.pdf")

    assert raised.value.host_down is False
    assert get.calls == []


def test_an_https_address_in_capitals_is_fetched(sf, monkeypatch):
    get = _fake(sf, monkeypatch, _Response())

    assert sf.fetch_pdf("HTTPS://MobileAL.api.civicclerk.com/x") == PDF
    assert len(get.calls) == 1


@pytest.mark.parametrize(
    "status, host_down",
    [(302, False), (404, False), (500, True), (503, True)],
)
def test_any_status_but_200_is_refused(sf, monkeypatch, status, host_down):
    response = _Response(status_code=status, headers={"Location": "https://elsewhere.example/x.pdf"})
    get = _fake(sf, monkeypatch, response)

    with pytest.raises(sf.SourceFileError) as raised:
        sf.fetch_pdf(URL)

    assert raised.value.host_down is host_down
    assert len(get.calls) == 1  # one attempt, and no redirect followed
    assert response.chunk_sizes == []
    assert response.closed


def test_a_content_length_above_the_cap_is_refused_before_the_body_is_read(sf, monkeypatch):
    response = _Response(headers={"Content-Length": str(sf.MAX_BYTES + 1)})
    _fake(sf, monkeypatch, response)

    with pytest.raises(sf.SourceFileError) as raised:
        sf.fetch_pdf(URL)

    assert raised.value.host_down is False
    assert response.chunk_sizes == []
    assert response.closed


def test_a_content_length_at_the_cap_is_not_refused(sf, monkeypatch):
    response = _Response(headers={"Content-Length": str(sf.MAX_BYTES)})
    _fake(sf, monkeypatch, response)

    assert sf.fetch_pdf(URL) == PDF


@pytest.mark.parametrize("value", ["abc", "-5"])
def test_a_content_length_that_is_no_size_is_ignored(sf, monkeypatch, value):
    response = _Response(headers={"Content-Length": value})
    _fake(sf, monkeypatch, response)

    assert sf.fetch_pdf(URL) == PDF
    assert response.closed


def test_a_body_that_passes_the_cap_while_streaming_is_refused(sf, monkeypatch):
    monkeypatch.setattr(sf, "MAX_BYTES", 10)
    response = _Response(chunks=(b"%PDF-1.6\n", b"more than ten bytes in all"))
    _fake(sf, monkeypatch, response)

    with pytest.raises(sf.SourceFileError) as raised:
        sf.fetch_pdf(URL)

    assert raised.value.host_down is False
    assert response.closed


def test_a_body_of_exactly_the_cap_is_returned(sf, monkeypatch):
    body = b"%PDF-1.6\nx"
    monkeypatch.setattr(sf, "MAX_BYTES", len(body))
    _fake(sf, monkeypatch, _Response(chunks=(body,)))

    assert sf.fetch_pdf(URL) == body


def test_a_body_that_is_not_a_pdf_is_refused(sf, monkeypatch):
    response = _Response(chunks=(b"<html><body>Sign in</body></html>",))
    _fake(sf, monkeypatch, response)

    with pytest.raises(sf.SourceFileError) as raised:
        sf.fetch_pdf(URL)

    assert raised.value.host_down is False
    assert response.closed


def test_a_pdf_header_past_the_first_1024_bytes_is_not_a_pdf(sf, monkeypatch):
    response = _Response(chunks=(b" " * 1024 + b"%PDF-1.6\n",))
    _fake(sf, monkeypatch, response)

    with pytest.raises(sf.SourceFileError) as raised:
        sf.fetch_pdf(URL)

    assert raised.value.host_down is False


@pytest.mark.parametrize(
    "error",
    [requests.ConnectionError("refused"), requests.Timeout("timed out")],
)
def test_a_host_that_does_not_answer_is_a_host_down_error(sf, monkeypatch, error):
    get = _fake(sf, monkeypatch, raises=error)

    with pytest.raises(sf.SourceFileError) as raised:
        sf.fetch_pdf(URL)

    assert raised.value.host_down is True
    assert len(get.calls) == 1  # one attempt


def test_an_error_while_the_body_is_read_is_a_host_down_error(sf, monkeypatch):
    class _Breaks(_Response):
        def read1(self, amt=None):
            self.chunk_sizes.append(amt)
            if len(self.chunk_sizes) == 1:
                return PDF[:50]
            raise urllib3.exceptions.ProtocolError("cut off")

    response = _Breaks()
    _fake(sf, monkeypatch, response)

    with pytest.raises(sf.SourceFileError) as raised:
        sf.fetch_pdf(URL)

    assert raised.value.host_down is True
    assert response.closed


def test_the_deadline_passing_between_chunks_is_a_host_down_error(sf, monkeypatch):
    # The clock is read once before the request and once after each chunk.
    times = iter([100.0, 100.0 + sf.DEADLINE_S / 2, 100.0 + sf.DEADLINE_S + 0.5, 200.0, 200.0])
    monkeypatch.setattr(sf, "_now", lambda: next(times))
    response = _Response(chunks=(PDF[:100], PDF[100:200], PDF[200:]))
    _fake(sf, monkeypatch, response)

    with pytest.raises(sf.SourceFileError) as raised:
        sf.fetch_pdf(URL)

    assert raised.value.host_down is True
    assert response.closed


def test_a_fetch_that_ends_inside_the_deadline_is_returned(sf, monkeypatch):
    times = iter([100.0, 100.0 + sf.DEADLINE_S - 0.5, 100.0 + sf.DEADLINE_S - 0.1])
    monkeypatch.setattr(sf, "_now", lambda: next(times))
    _fake(sf, monkeypatch, _Response(chunks=(PDF[:100], PDF[100:])))

    assert sf.fetch_pdf(URL) == PDF


def test_the_error_keeps_its_reason_and_whether_the_host_was_down(sf):
    plain = sf.SourceFileError("status 404")
    down = sf.SourceFileError("timed out", host_down=True)

    assert (str(plain), plain.host_down) == ("status 404", False)
    assert (str(down), down.host_down) == ("timed out", True)


# ── A real slow body, from a socket server on this machine ─────────────────
#
# The tests above hand fetch_pdf the pieces they chose, so they cannot show
# when a real body's pieces are handed over. These run the real requests and
# urllib3 read path against a server that sends a body a little at a time
# (debt row D204: with iter_content, a body of declared length was not looked
# at against the deadline until a whole chunk had arrived or the body ended).


class _TrickleServer:
    """Answers one GET on 127.0.0.1 with ``body``, ``step`` bytes every ``pause`` seconds."""

    def __init__(self, body, *, step, pause, chunked=False, declared=None, send=None):
        self.body, self.step, self.pause, self.chunked = body, step, pause, chunked
        self.declared = len(body) if declared is None else declared
        self.send = len(body) if send is None else send
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        try:
            conn, _ = self.sock.accept()
        except OSError:
            return
        with conn:
            try:
                while b"\r\n\r\n" not in conn.recv(65536):
                    pass
                head = b"HTTP/1.1 200 OK\r\nContent-Type: application/pdf\r\nConnection: close\r\n"
                if self.chunked:
                    head += b"Transfer-Encoding: chunked\r\n\r\n"
                else:
                    head += b"Content-Length: %d\r\n\r\n" % self.declared
                conn.sendall(head)
                for at in range(0, self.send, self.step):
                    piece = self.body[at:at + self.step]
                    if self.chunked:
                        piece = b"%x\r\n%s\r\n" % (len(piece), piece)
                    conn.sendall(piece)
                    time.sleep(self.pause)
                if self.chunked and self.send == len(self.body):
                    conn.sendall(b"0\r\n\r\n")
            except OSError:
                pass  # the client gave up, which is what the test is about

    def close(self):
        self.sock.close()
        self.thread.join(timeout=5)


@pytest.fixture
def served(sf, monkeypatch):
    """Start a trickle server and send fetch_pdf's one request to it."""
    servers = []
    real_get = requests.get

    def start(body, **kwargs):
        server = _TrickleServer(body, **kwargs)
        servers.append(server)
        monkeypatch.setattr(
            sf.requests, "get",
            lambda url, **kw: real_get(f"http://127.0.0.1:{server.port}/file.pdf", **kw),
        )
        return server

    yield start
    for server in servers:
        server.close()


SLOW_BODY = b"%PDF-1.7\n" + b"y" * 5991  # 6,000 bytes: under one chunk of 16,384


@pytest.mark.parametrize("chunked", [False, True], ids=["content-length", "chunked"])
def test_a_body_that_trickles_without_a_silence_is_given_up_at_the_deadline(
    sf, monkeypatch, served, chunked
):
    # 100 bytes every 0.05 s: never a silence of READ_TIMEOUT_S, and 3 seconds
    # to arrive in full. The fetch must end near DEADLINE_S, not when the body does.
    monkeypatch.setattr(sf, "DEADLINE_S", 0.5)
    monkeypatch.setattr(sf, "READ_TIMEOUT_S", 0.3)
    served(SLOW_BODY, step=100, pause=0.05, chunked=chunked)

    began = time.monotonic()
    with pytest.raises(sf.SourceFileError) as raised:
        sf.fetch_pdf(URL)
    took = time.monotonic() - began

    assert raised.value.host_down is True
    assert "not finished within" in raised.value.reason
    # DEADLINE_S plus one read of READ_TIMEOUT_S is 0.8 s; the body needs 3.
    assert took < 1.5


def test_a_real_body_sent_in_pieces_is_returned_whole(sf, served):
    served(SLOW_BODY, step=2000, pause=0.01)

    assert sf.fetch_pdf(URL) == SLOW_BODY


def test_a_real_chunked_body_is_returned_whole(sf, served):
    served(SLOW_BODY, step=2000, pause=0.01, chunked=True)

    assert sf.fetch_pdf(URL) == SLOW_BODY


def test_a_body_cut_off_before_its_declared_length_is_a_host_down_error(sf, served):
    served(SLOW_BODY, step=1000, pause=0.0, send=2000)

    with pytest.raises(sf.SourceFileError) as raised:
        sf.fetch_pdf(URL)

    assert raised.value.host_down is True


def test_a_host_that_falls_silent_mid_body_is_a_host_down_error(sf, monkeypatch, served):
    monkeypatch.setattr(sf, "READ_TIMEOUT_S", 0.3)
    served(SLOW_BODY, step=1000, pause=2.0)

    began = time.monotonic()
    with pytest.raises(sf.SourceFileError) as raised:
        sf.fetch_pdf(URL)

    assert raised.value.host_down is True
    assert time.monotonic() - began < 1.5
