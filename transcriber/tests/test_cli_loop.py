from datetime import date
from pathlib import Path
import pytest

from transcriber import cli
from transcriber.contract import TranscriptOutput
from transcriber.db import Claim
from transcriber.engine import DiarTurn, RawSegment


class FakeEngine:
    name = "fake"; asr_model = "tiny"; diarization_model = None
    last_words: list = []
    def transcribe(self, wav, initial_prompt):
        return [RawSegment(0.0, 200.0, "Item 15 passes.", -0.1, 0.0)]
    def diarize(self, wav):
        return [DiarTurn(0.0, 200.0, "SPEAKER_00")], {"SPEAKER_00": [0.1]}


class FakeConn:
    """No-op connection: the loop only calls commit()."""
    def commit(self): pass
    def rollback(self): pass


class FakeDB:
    """Stands in for transcriber.db functions via monkeypatch."""
    def __init__(self, claims):
        self.claims = list(claims); self.status = []; self.uploaded = []; self.beats = []
    def claim_next(self, conn, **kw):
        return self.claims.pop(0) if self.claims else None
    def mark_status(self, conn, tid, status, **kw):
        self.status.append((tid, status, kw.get("error")))
    def heartbeat(self, conn, host, status, mid, ver):
        self.beats.append(status)
    def roster_for_meeting(self, conn, mid):
        return ["Darrell O'Quinn"]
    def upload(self, conn, out: TranscriptOutput):
        self.uploaded.append(out.meeting_id); return len(out.segments)


@pytest.fixture
def cfg(tmp_path):
    return cli.Config(since=date(2025, 10, 28), limit=10, max_hours=None, host="test",
                      work_dir=tmp_path / "work", archive_dir=tmp_path / "archive",
                      dry_run_file=None, version="0.1.0")


def _wire(monkeypatch, fakedb, *, fetch_ok=True):
    for name in ("claim_next", "mark_status", "heartbeat", "roster_for_meeting", "upload"):
        monkeypatch.setattr(cli.tdb, name, getattr(fakedb, name))
    def fake_fetch(source, out_wav, **kw):
        if not fetch_ok:
            from transcriber.audio import AudioFetchError
            raise AudioFetchError("ffmpeg could not read: HTTP 403 Forbidden")
        Path(out_wav).parent.mkdir(parents=True, exist_ok=True)
        Path(out_wav).write_bytes(b"RIFF" + b"\0" * 100); return Path(out_wav)
    monkeypatch.setattr(cli, "fetch_audio", fake_fetch)
    monkeypatch.setattr(cli, "probe_duration", lambda *a, **k: 200.0)
    monkeypatch.setattr(cli, "sha256_file", lambda p: "ab" * 32)


def _claim(i, status="claimed"):
    return Claim(i, 100 + i, str(1950 + i), f"M{i}", date(2026, 2, 17), status)


def test_happy_path_uploads_and_archives_json(monkeypatch, cfg):
    fdb = FakeDB([_claim(1)]); _wire(monkeypatch, fdb)
    counts = cli.run_loop(FakeConn(), FakeEngine(), cfg)
    assert counts == {"uploaded": 1, "failed": 0, "low_speech": 0}
    assert fdb.uploaded == [101]
    assert any(p.suffix == ".json" for p in cfg.archive_dir.rglob("*"))
    assert not list(cfg.work_dir.rglob("*.wav"))          # audio deleted after upload
    assert [s for _, s, _ in fdb.status][:2] == ["audio_fetched", "transcribed"]


def test_fetch_failure_marks_failed_with_stderr_and_continues(monkeypatch, cfg):
    fdb = FakeDB([_claim(1), _claim(2)]); _wire(monkeypatch, fdb, fetch_ok=False)
    counts = cli.run_loop(FakeConn(), FakeEngine(), cfg)
    assert counts["failed"] == 2
    assert all(s == "failed" and "403" in (e or "") for _, s, e in fdb.status)


def test_transcribed_claim_skips_gpu_and_uploads(monkeypatch, cfg, tmp_path):
    out = TranscriptOutput(meeting_id=101, version=1, engine="fake", asr_model="tiny",
                           diarization_model=None, audio_duration_s=200.0, speech_seconds=200.0,
                           audio_sha256="ab" * 32, segments=[], speakers=[])
    path = cfg.archive_dir / "101" / "transcript.json"
    path.parent.mkdir(parents=True); path.write_text(out.to_json())
    fdb = FakeDB([_claim(1, status="transcribed")]); _wire(monkeypatch, fdb)
    class Boom(FakeEngine):
        def transcribe(self, *a, **k): raise AssertionError("GPU must not run")
    counts = cli.run_loop(FakeConn(), Boom(), cfg)
    assert counts["uploaded"] == 1 and fdb.uploaded == [101]


def test_low_speech_is_not_uploaded(monkeypatch, cfg):
    class Quiet(FakeEngine):
        def transcribe(self, wav, p): return [RawSegment(0.0, 30.0, "quorum?", None, None)]
    fdb = FakeDB([_claim(1)]); _wire(monkeypatch, fdb)
    counts = cli.run_loop(FakeConn(), Quiet(), cfg)
    assert counts["low_speech"] == 1 and fdb.uploaded == []
    assert fdb.status[-1][1] == "low_speech"


def test_max_hours_stops_between_meetings(monkeypatch, cfg):
    cfg.max_hours = 1.0
    fdb = FakeDB([_claim(1), _claim(2)]); _wire(monkeypatch, fdb)
    t = iter([0.0, 0.0, 3601.0, 3601.0, 3601.0])
    counts = cli.run_loop(FakeConn(), FakeEngine(), cfg, clock=lambda: next(t))
    assert counts["uploaded"] == 1 and len(fdb.claims) == 1


def test_stops_after_consecutive_failures(monkeypatch, cfg):
    fdb = FakeDB([_claim(i) for i in range(1, 8)]); _wire(monkeypatch, fdb, fetch_ok=False)
    counts = cli.run_loop(FakeConn(), FakeEngine(), cfg)
    assert counts["failed"] == 5 and len(fdb.claims) == 2
    assert fdb.beats[-1] == "exited"


def test_upload_exception_marks_failed_and_continues(monkeypatch, cfg):
    fdb = FakeDB([_claim(1), _claim(2)]); _wire(monkeypatch, fdb)
    calls = []
    def flaky_upload(conn, out):
        calls.append(out.meeting_id)
        if len(calls) == 1:
            raise RuntimeError("boom")
        fdb.uploaded.append(out.meeting_id); return 1
    monkeypatch.setattr(cli.tdb, "upload", flaky_upload)
    counts = cli.run_loop(FakeConn(), FakeEngine(), cfg)
    assert counts["failed"] == 1 and counts["uploaded"] == 1
    failed = [x for x in fdb.status if x[1] == "failed"]
    assert len(failed) == 1 and "boom" in failed[0][2]
    assert fdb.uploaded == [102]


def test_run_loop_passes_retry_failed_to_claim(monkeypatch, cfg):
    seen = {}
    class _Conn:
        def commit(self): pass
    class _NoStop:
        requested = False
    def fake_claim(conn, **kw):
        seen.update(kw); return None
    monkeypatch.setattr(cli.tdb, "claim_next", fake_claim)
    monkeypatch.setattr(cli.tdb, "heartbeat", lambda *a, **k: None)
    cfg.retry_failed = True
    cli.run_loop(_Conn(), None, cfg, stop_flag=_NoStop())
    assert seen["retry_failed"] is True
