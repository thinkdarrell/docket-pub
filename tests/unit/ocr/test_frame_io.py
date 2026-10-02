"""Unit tests for the ffmpeg/ffprobe wrappers' HTTP behavior.

Granicus serves archive video through CloudFront, which answers 403 to
non-browser user agents (ffprobe/ffmpeg's ``Lavf/...``, ``Python-urllib``).
Every HTTP touchpoint must identify as a browser, and a failed probe must
say why instead of surfacing as ``float('')``.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docket.analysis.ocr import frame_io
from docket.analysis.ocr.frame_io import (
    VideoProbeError,
    download_video_to_tempfile,
    extract_frames_to_dir,
    probe_duration,
)

URL = "https://bhamal.granicus.com/DownloadFile.php?view_id=2&clip_id=2014"


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> MagicMock:
    proc = MagicMock()
    proc.stdout, proc.stderr, proc.returncode = stdout, stderr, returncode
    return proc


def _ua_of(cmd: list[str]) -> str | None:
    return cmd[cmd.index("-user_agent") + 1] if "-user_agent" in cmd else None


class TestProbeDuration:
    def test_sends_browser_user_agent_for_http_url(self):
        with patch.object(frame_io.subprocess, "run", return_value=_completed("3689.15\n")) as run:
            assert probe_duration(URL) == pytest.approx(3689.15)
        cmd = run.call_args.args[0]
        assert "Mozilla/5.0" in (_ua_of(cmd) or "")
        assert cmd.index("-user_agent") < cmd.index(URL)

    def test_no_user_agent_for_local_file(self, tmp_path):
        local = str(tmp_path / "clip.mp4")
        with patch.object(frame_io.subprocess, "run", return_value=_completed("12.5\n")) as run:
            assert probe_duration(local) == pytest.approx(12.5)
        assert _ua_of(run.call_args.args[0]) is None

    def test_failed_probe_reports_ffprobe_error_not_float_conversion(self):
        failure = _completed("", "https://...: Server returned 403 Forbidden (access denied)\n", 1)
        with patch.object(frame_io.subprocess, "run", return_value=failure):
            with pytest.raises(VideoProbeError, match="403 Forbidden"):
                probe_duration(URL)


class TestExtractFrames:
    def test_sends_browser_user_agent_before_input_for_http_url(self, tmp_path):
        with patch.object(frame_io.subprocess, "run", return_value=_completed()) as run:
            extract_frames_to_dir(URL, tmp_path, fps_expression="1/2")
        cmd = run.call_args.args[0]
        assert "Mozilla/5.0" in (_ua_of(cmd) or "")
        assert cmd.index("-user_agent") < cmd.index("-i")

    def test_no_user_agent_for_local_file(self, tmp_path):
        with patch.object(frame_io.subprocess, "run", return_value=_completed()) as run:
            extract_frames_to_dir(str(tmp_path / "clip.mp4"), tmp_path, fps_expression="2")
        assert _ua_of(run.call_args.args[0]) is None


class TestDownloadVideo:
    def test_sends_browser_user_agent(self):
        resp = MagicMock()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        resp.read = MagicMock(side_effect=[b"", b""])
        with patch.object(frame_io.urllib.request, "urlopen", return_value=resp) as urlopen:
            with download_video_to_tempfile(URL) as local:
                assert isinstance(local, Path)
        request = urlopen.call_args.args[0]
        assert "Mozilla/5.0" in request.get_header("User-agent", "")


class TestFailureMessages:
    def test_failed_frame_extraction_reports_ffmpeg_error(self, tmp_path):
        """The recorded error must carry ffmpeg's own message, not just the exit code."""
        failure = _completed("", "https://...: Server returned 403 Forbidden (access denied)\n", 1)
        with patch.object(frame_io.subprocess, "run", return_value=failure):
            with pytest.raises(VideoProbeError, match="403 Forbidden"):
                extract_frames_to_dir(URL, tmp_path, fps_expression="1/2")

    def test_probe_with_no_duration_reports_it(self):
        with patch.object(frame_io.subprocess, "run", return_value=_completed("N/A\n")):
            with pytest.raises(VideoProbeError, match="N/A"):
                probe_duration(URL)
