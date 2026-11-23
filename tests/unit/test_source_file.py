"""Unit tests for ``docket.adapters.source_file.fetch_pdf``.

One bounded GET of a city's PDF: one attempt, ``https`` only, no redirect
followed, a size cap, a deadline, and a check that the body is a PDF.
``requests.get`` is faked throughout; no test sends a request.

The module is imported inside each test (through the ``sf`` fixture) so
that this file collects, and each test fails by itself, before the module
exists.

Plan `minutes-open-at-the-vote-page`, M1.
"""

from __future__ import annotations

import importlib

import pytest
import requests

URL = "https://mobileal.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=3854,plainText=false)"
PDF = b"%PDF-1.6\n" + b"x" * 5000


class _Response:
    def __init__(self, status_code=200, headers=None, chunks=(PDF,)):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = list(chunks)
        self.chunk_sizes = []
        self.closed = False

    def iter_content(self, chunk_size=None):
        self.chunk_sizes.append(chunk_size)
        yield from self._chunks

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
    assert response.chunk_sizes == [sf.CHUNK_BYTES]
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
        def iter_content(self, chunk_size=None):
            self.chunk_sizes.append(chunk_size)
            yield PDF[:50]
            raise requests.exceptions.ChunkedEncodingError("cut off")

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
