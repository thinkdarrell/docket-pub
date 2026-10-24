import hashlib
import subprocess
from pathlib import Path
import pytest
from transcriber.audio import (
    AudioFetchError, BROWSER_USER_AGENT, download_url_for, fetch_audio,
    probe_duration, sha256_file,
)


def test_download_url():
    assert download_url_for("1950") == (
        "https://bhamal.granicus.com/DownloadFile.php?view_id=2&clip_id=1950"
    )


class _FakeRun:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        rc, err = self.results.pop(0)
        if rc == 0 and "-i" in cmd and cmd[-1].endswith(".wav"):
            Path(cmd[-1]).write_bytes(b"RIFF" + b"\0" * 44)
        return subprocess.CompletedProcess(cmd, rc, stdout="", stderr=err)


def test_fetch_audio_uses_browser_ua_and_pcm_flags(tmp_path):
    run = _FakeRun([(0, "")])
    out = fetch_audio("https://x/video.mp4", tmp_path / "a.wav", runner=run)
    cmd = run.calls[0]
    assert cmd[0] == "ffmpeg"
    assert cmd[cmd.index("-user_agent") + 1] == BROWSER_USER_AGENT
    for flag, val in (("-vn", None), ("-ac", "1"), ("-ar", "16000"), ("-c:a", "pcm_s16le")):
        assert flag in cmd
        if val:
            assert cmd[cmd.index(flag) + 1] == val
    assert out.exists()


def test_fetch_audio_retries_then_raises_with_stderr(tmp_path):
    run = _FakeRun([(1, "HTTP error 403 Forbidden")] * 3)
    with pytest.raises(AudioFetchError, match="403 Forbidden"):
        fetch_audio("https://x/video.mp4", tmp_path / "a.wav", runner=run, delay_s=0)
    assert len(run.calls) == 3


def test_fetch_audio_no_ua_for_local_file(tmp_path):
    run = _FakeRun([(0, "")])
    fetch_audio("/clips/local.mp4", tmp_path / "a.wav", runner=run)
    assert "-user_agent" not in run.calls[0]


def test_probe_duration_parses_ffprobe(tmp_path):
    def run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout="530.600000\n", stderr="")
    assert probe_duration("https://x/video.mp4", runner=run) == pytest.approx(530.6)


def test_sha256_file(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"hello")
    assert sha256_file(p) == hashlib.sha256(b"hello").hexdigest()


# --- source_for: a Granicus clip id or a yt- id (YouTube recordings, plan youtube-council-channel M6) ---

import sys
import types


def _fake_yt_dlp(monkeypatch, *, fail=False, writes="webm"):
    """Install a stand-in yt_dlp module (the repo venv does not carry the real one) that records
    the options it was built with and writes <outtmpl with ext> on download."""
    class DownloadError(Exception):
        pass

    seen = {}

    class YoutubeDL:
        def __init__(self, opts):
            seen["opts"] = dict(opts)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def download(self, urls):
            seen["urls"] = list(urls)
            if fail:
                raise DownloadError("ERROR: [youtube] abc: Sign in to confirm you're not a bot")
            Path(seen["opts"]["outtmpl"].replace("%(ext)s", writes)).write_bytes(b"\0" * 64)
            return 0

    mod = types.ModuleType("yt_dlp")
    mod.YoutubeDL = YoutubeDL
    mod.utils = types.SimpleNamespace(DownloadError=DownloadError)
    monkeypatch.setitem(sys.modules, "yt_dlp", mod)
    return seen


def test_source_for_a_clip_id_is_the_granicus_url(tmp_path):
    from transcriber.audio import source_for
    assert source_for("2024", tmp_path) == download_url_for("2024")
    assert list(tmp_path.iterdir()) == []                 # nothing downloaded for Granicus


def test_source_for_a_yt_id_downloads_the_best_audio(monkeypatch, tmp_path):
    from transcriber.audio import source_for
    monkeypatch.delenv("TRANSCRIBER_YTDLP_COOKIES", raising=False)
    seen = _fake_yt_dlp(monkeypatch)
    got = source_for("yt-abc", tmp_path)
    assert got == str(tmp_path / "yt-abc.webm") and Path(got).exists()
    assert seen["urls"] == ["https://www.youtube.com/watch?v=abc"]
    assert seen["opts"]["format"] == "bestaudio/best"
    assert seen["opts"]["outtmpl"] == str(tmp_path / "yt-abc.%(ext)s")
    assert seen["opts"]["noplaylist"] is True and seen["opts"]["quiet"] is True


def test_source_for_a_yt_id_raises_audio_fetch_error_on_download_error(monkeypatch, tmp_path):
    from transcriber.audio import source_for
    _fake_yt_dlp(monkeypatch, fail=True)
    with pytest.raises(AudioFetchError, match="not a bot"):
        source_for("yt-abc", tmp_path)


def test_source_for_passes_the_cookie_file_only_when_set(monkeypatch, tmp_path):
    from transcriber.audio import source_for
    monkeypatch.delenv("TRANSCRIBER_YTDLP_COOKIES", raising=False)
    seen = _fake_yt_dlp(monkeypatch)
    source_for("yt-abc", tmp_path)
    assert "cookiefile" not in seen["opts"]
    monkeypatch.setenv("TRANSCRIBER_YTDLP_COOKIES", "/secrets/cookies.txt")
    source_for("yt-def", tmp_path)
    assert seen["opts"]["cookiefile"] == "/secrets/cookies.txt"
