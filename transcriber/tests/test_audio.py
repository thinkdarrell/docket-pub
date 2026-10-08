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
